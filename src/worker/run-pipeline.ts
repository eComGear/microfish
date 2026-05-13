// Worker entrypoint. One process = one simulation. Exits when done; fly auto-destroys
// the machine because config.auto_destroy=true.
//
// Env vars (injected by spawnWorkerMachine):
//   JOB_ID, REPORT_ID, DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
//   DEEPSEEK_API_KEY, plus anything else your existing pipeline needs.

import { query, pool } from "../lib/db.js";
import { patchReport, supabaseAdmin } from "../lib/supabase.js";

// === Replace these with the real MicroFish pipeline functions ===
// import { uploadSeed, buildGraph, prepare, startSimulation, runRounds }
//   from "@microfish/pipeline";
// ================================================================

const JOB_ID    = process.env.JOB_ID!;
const REPORT_ID = process.env.REPORT_ID!;

if (!JOB_ID || !REPORT_ID) {
  console.error("Missing JOB_ID or REPORT_ID");
  process.exit(2);
}

let heartbeat: NodeJS.Timeout | null = null;

async function setStage(stage: string, progress: number) {
  await query(
    `update pipeline_jobs set status='running', stage=$2, progress=$3, heartbeat_at=now() where id=$1`,
    [JOB_ID, stage, progress]
  );
  await patchReport(REPORT_ID, { status: "running", stage, progress }).catch(() => {});
}

async function fail(err: unknown) {
  const msg = err instanceof Error ? err.message : String(err);
  console.error("pipeline failed:", msg);
  await query(
    `update pipeline_jobs
       set status='failed', error=$2, finished_at=now(), attempt = attempt + 1
     where id=$1`,
    [JOB_ID, msg]
  );
  await patchReport(REPORT_ID, { status: "failed", error: msg }).catch(() => {});
}

async function complete(result: unknown) {
  await query(
    `update pipeline_jobs
       set status='completed', progress=100, finished_at=now(), result=$2
     where id=$1`,
    [JOB_ID, JSON.stringify(result)]
  );
  await patchReport(REPORT_ID, {
    status: "completed",
    progress: 100,
    result,
  }).catch(() => {});
}

async function main() {
  // Load job
  const [job] = await query<{
    id: string; prompt: string; scenario: string | null; seed_file_url: string | null;
  }>(`select id, prompt, scenario, seed_file_url from pipeline_jobs where id=$1`, [JOB_ID]);

  if (!job) throw new Error(`job ${JOB_ID} not found`);

  // Heartbeat every 20s so the stuck-job watchdog leaves us alone
  heartbeat = setInterval(() => {
    query(`update pipeline_jobs set heartbeat_at=now() where id=$1`, [JOB_ID]).catch(() => {});
  }, 20_000);

  // === Run the actual pipeline. Wire these to real MicroFish functions. ===
  await setStage("upload", 10);
  // const graphInput = await uploadSeed(job.seed_file_url);

  await setStage("build_graph", 25);
  // const graph = await buildGraph(graphInput, job.prompt);

  await setStage("prepare", 45);
  // const sim = await prepare(graph, { scenario: job.scenario });

  await setStage("start", 60);
  // const simulationId = await startSimulation(sim);
  // await patchReport(REPORT_ID, { simulation_id: simulationId });

  await setStage("rounds", 75);
  // const rounds = await runRounds(simulationId, { onRound: async (n, total) => {
  //   await setStage("rounds", 75 + Math.floor((n / total) * 24));
  // }});

  // Replace with your real result shape.
  const result = { ok: true, finishedAt: new Date().toISOString() };

  await complete(result);
}

main()
  .catch(fail)
  .finally(async () => {
    if (heartbeat) clearInterval(heartbeat);
    await pool.end().catch(() => {});
    process.exit(0);
  });
