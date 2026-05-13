// src/worker/run-pipeline.ts
//
// One process = one simulation. Spawned by the API as a fly machine with:
//   JOB_ID=<uuid>  fly machines run ... node dist/worker/run-pipeline.js
//
// Reads the job row, runs the full pipeline, heartbeats every stage into
// BOTH `pipeline_jobs` (ops) and `reports` (what the Lovable UI polls).
// On any throw: marks job failed, marks report failed, exits 1 (no restart).

import { pool } from "../lib/db";
import { supabaseAdmin } from "../lib/supabase";

// --- existing MicroFish pipeline modules (already in this repo) -------------
import { generateOntologyFromFiles } from "../services/ontology";
import { buildGraphAndWait }         from "../services/graph";
import { prepareAndWait, startSimulation, getSimulationStatus } from "../services/simulation";
import { generateReport, getReportStatus } from "../services/report";
// ----------------------------------------------------------------------------

const JOB_ID = process.env.JOB_ID;
if (!JOB_ID) { console.error("JOB_ID env required"); process.exit(2); }

type Stage =
  | "ontology" | "graph" | "prepare" | "simulate" | "report" | "done";

type JobRow = {
  id: string;
  user_id: string;
  report_id: string;
  simulation_id: string | null;
  payload: {
    files: Array<{ name: string; bucket: string; path: string }>; // Supabase Storage refs
    simulation_requirement: string;
    project_name?: string;
    additional_context?: string;
    num_agents: number;
    num_rounds: number;
    enable_twitter?: boolean;
    enable_reddit?: boolean;
    seed_experts?: Array<{ id: string; display_name: string; persona: string; fee_per_simulation?: number }>;
  };
};

async function loadJob(): Promise<JobRow> {
  const { rows } = await pool.query(
    `update pipeline_jobs
        set status = 'running', stage = 'ontology', heartbeat_at = now(),
            updated_at = now()
      where id = $1
      returning id, user_id, report_id, simulation_id, payload`,
    [JOB_ID],
  );
  if (!rows[0]) throw new Error(`job ${JOB_ID} not found`);
  return rows[0] as JobRow;
}

/** Heartbeat + progress to BOTH tables. UI polls `reports`; ops watches `pipeline_jobs`. */
async function mark(job: JobRow, patch: {
  stage?: Stage;
  progress?: number;
  message?: string;
  status?: "running" | "completed" | "failed";
  simulation_id?: string;
  report_id_external?: string; // microfish report id
  graph_id?: string;
  error?: string;
}) {
  await pool.query(
    `update pipeline_jobs set
        stage           = coalesce($2, stage),
        progress_percent= coalesce($3, progress_percent),
        message         = coalesce($4, message),
        status          = coalesce($5, status),
        simulation_id   = coalesce($6, simulation_id),
        error           = coalesce($7, error),
        heartbeat_at    = now(),
        updated_at      = now()
      where id = $1`,
    [job.id, patch.stage, patch.progress, patch.message, patch.status,
     patch.simulation_id, patch.error],
  );

  const reportPatch: Record<string, unknown> = {};
  if (patch.status === "completed") reportPatch.status = "completed";
  else if (patch.status === "failed") reportPatch.status = "failed";
  else reportPatch.status = "running";
  if (patch.simulation_id)      reportPatch.simulation_id = patch.simulation_id;
  if (patch.graph_id)           reportPatch.graph_id = patch.graph_id;
  if (patch.report_id_external) reportPatch.report_id = patch.report_id_external;

  await supabaseAdmin
    .from("reports")
    .update(reportPatch)
    .eq("id", job.report_id);
}

async function fetchSeedFiles(job: JobRow): Promise<File[]> {
  const out: File[] = [];
  for (const ref of job.payload.files) {
    const { data, error } = await supabaseAdmin.storage.from(ref.bucket).download(ref.path);
    if (error || !data) throw new Error(`download ${ref.path}: ${error?.message}`);
    out.push(new File([await data.arrayBuffer()], ref.name));
  }
  return out;
}

async function runPipeline() {
  const job = await loadJob();
  console.log(`[job ${job.id}] starting`);

  // 1. Ontology / project
  await mark(job, { stage: "ontology", progress: 5, message: "上傳種子檔並生成本體" });
  const files = await fetchSeedFiles(job);
  const ontology = await generateOntologyFromFiles({
    files,
    simulation_requirement: job.payload.simulation_requirement,
    project_name:           job.payload.project_name,
    additional_context:     job.payload.additional_context,
  });
  const project_id = ontology.project_id;

  // 2. Graph
  await mark(job, { stage: "graph", progress: 20, message: "建構知識圖譜" });
  const { graph_id } = await buildGraphAndWait({ project_id });
  await mark(job, { graph_id, progress: 35 });

  // 3. Prepare simulation (creates sim + agent profiles)
  await mark(job, { stage: "prepare", progress: 40, message: "建立模擬與 agent profiles" });
  const { simulation_id } = await prepareAndWait({
    project_id,
    graph_id,
    enable_twitter:        job.payload.enable_twitter,
    enable_reddit:         job.payload.enable_reddit,
    max_agents:            job.payload.num_agents,
    seed_experts:          job.payload.seed_experts,
  });
  await mark(job, { simulation_id, progress: 55 });

  // 4. Run rounds
  await mark(job, { stage: "simulate", progress: 60, message: "執行模擬中" });
  await startSimulation({
    simulation_id,
    num_agents: job.payload.num_agents,
    num_rounds: job.payload.num_rounds,
  });
  // poll
  for (;;) {
    const st = await getSimulationStatus(simulation_id);
    const pct = 60 + Math.min(25, Math.round(((st.progress_percent ?? 0) / 100) * 25));
    await mark(job, {
      progress: pct,
      message: `Round ${st.current_round ?? 0}/${st.total_rounds ?? job.payload.num_rounds}`,
    });
    if (st.status === "completed") break;
    if (st.status === "failed") throw new Error(`simulation failed: ${(st as any).error ?? ""}`);
    await new Promise(r => setTimeout(r, 5000));
  }

  // 5. Report (DeepSeek)
  await mark(job, { stage: "report", progress: 88, message: "生成報告 (DeepSeek)" });
  const rep = await generateReport({ simulation_id });
  for (;;) {
    const st = await getReportStatus(rep.report_id);
    if (st.status === "completed") break;
    if (st.status === "failed") throw new Error(`report failed: ${st.message ?? ""}`);
    await mark(job, {
      progress: 88 + Math.min(10, Math.round(((st.progress ?? 0) / 100) * 10)),
      message: st.message ?? "報告生成中",
    });
    await new Promise(r => setTimeout(r, 4000));
  }

  await mark(job, {
    stage: "done", progress: 100, status: "completed",
    message: "完成", report_id_external: rep.report_id,
  });
  console.log(`[job ${job.id}] completed`);
}

runPipeline()
  .then(() => process.exit(0))
  .catch(async (err) => {
    console.error("pipeline failed", err);
    try {
      const { rows } = await pool.query(
        `select id, user_id, report_id, simulation_id, payload from pipeline_jobs where id=$1`,
        [JOB_ID],
      );
      if (rows[0]) {
        await mark(rows[0] as JobRow, {
          status: "failed",
          error: err?.message ?? String(err),
          message: "失敗",
        });
      }
    } catch (e) { console.error("failure-mark also failed", e); }
    process.exit(1);
  });

