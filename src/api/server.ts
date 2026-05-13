// Minimal Hono API server. Run with: node dist/api/server.js
// Single endpoint: POST /pipeline/run
//
// Auth: shared bearer token in `Authorization: Bearer <PIPELINE_RUN_TOKEN>`.
// Lovable holds this token as a secret and sends it on every request.

import { Hono } from "hono";
import { serve } from "@hono/node-server";
import { z } from "zod";
import { query } from "../lib/db.js";
import { spawnWorkerMachine } from "../lib/fly-machines.js";
import { patchReport } from "../lib/supabase.js";

const app = new Hono();

const RunSchema = z.object({
  reportId:    z.string().uuid(),
  userId:      z.string().uuid(),
  prompt:      z.string().min(1).max(20_000),
  scenario:    z.string().max(20_000).optional(),
  seedFileUrl: z.string().url().optional(),
});

app.get("/health", (c) => c.json({ ok: true }));

app.post("/pipeline/run", async (c) => {
  const auth = c.req.header("authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  if (!token || token !== process.env.PIPELINE_RUN_TOKEN) {
    return c.json({ error: "unauthorized" }, 401);
  }

  let input: z.infer<typeof RunSchema>;
  try {
    input = RunSchema.parse(await c.req.json());
  } catch (e: any) {
    return c.json({ error: "invalid_payload", detail: e.message }, 400);
  }

  // 1. Insert job row (durable)
  const [job] = await query<{ id: string }>(
    `insert into pipeline_jobs (report_id, user_id, prompt, scenario, seed_file_url, status)
     values ($1,$2,$3,$4,$5,'queued') returning id`,
    [input.reportId, input.userId, input.prompt, input.scenario ?? null, input.seedFileUrl ?? null]
  );

  // 2. Mark report as queued so the UI shows it immediately
  await patchReport(input.reportId, { status: "queued" }).catch(() => {});

  // 3. Spawn fly machine. If this throws, mark job failed but return 202 anyway —
  //    a recovery cron (see pipeline_jobs_stuck view) will retry.
  let machineId: string | null = null;
  try {
    machineId = await spawnWorkerMachine({ jobId: job.id, reportId: input.reportId });
    await query(
      `update pipeline_jobs set status='spawning', machine_id=$2, started_at=now() where id=$1`,
      [job.id, machineId]
    );
  } catch (err: any) {
    await query(
      `update pipeline_jobs set status='failed', error=$2, finished_at=now() where id=$1`,
      [job.id, String(err?.message || err)]
    );
    await patchReport(input.reportId, { status: "failed" }).catch(() => {});
    return c.json({ jobId: job.id, error: "spawn_failed", detail: String(err?.message || err) }, 502);
  }

  return c.json({ jobId: job.id, machineId, reportId: input.reportId }, 202);
});

const port = Number(process.env.PORT || 8080);
serve({ fetch: app.fetch, port });
console.log(`microfish api listening on :${port}`);
