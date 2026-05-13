// Thin wrapper around the fly.io Machines REST API.
// Docs: https://fly.io/docs/machines/api/

const FLY_API = "https://api.machines.dev/v1";

const FLY_TOKEN     = process.env.FLY_API_TOKEN!;
const WORKER_APP    = process.env.FLY_WORKER_APP!;     // e.g. "microfish-worker"
const WORKER_IMAGE  = process.env.FLY_WORKER_IMAGE!;   // e.g. "registry.fly.io/microfish-worker:latest"
const WORKER_REGION = process.env.FLY_WORKER_REGION || "iad";
const WORKER_CPU    = Number(process.env.FLY_WORKER_CPUS || 1);
const WORKER_MEM_MB = Number(process.env.FLY_WORKER_MEMORY_MB || 512);

export interface SpawnInput {
  jobId: string;
  reportId: string;
}

export async function spawnWorkerMachine(input: SpawnInput): Promise<string> {
  if (!FLY_TOKEN || !WORKER_APP || !WORKER_IMAGE) {
    throw new Error("Missing FLY_API_TOKEN / FLY_WORKER_APP / FLY_WORKER_IMAGE");
  }

  const body = {
    region: WORKER_REGION,
    config: {
      auto_destroy: true,                       // self-clean on exit
      restart: { policy: "no" },
      guest: {
        cpu_kind: "shared",
        cpus: WORKER_CPU,
        memory_mb: WORKER_MEM_MB,
      },
      image: WORKER_IMAGE,
      env: {
        JOB_ID: input.jobId,
        REPORT_ID: input.reportId,
        DATABASE_URL: process.env.DATABASE_URL!,
        SUPABASE_URL: process.env.SUPABASE_URL!,
        SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY!,
        DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY!,
        // forward any other secrets your pipeline needs here
      },
      processes: [
        {
          name: "worker",
          entrypoint: ["node"],
          cmd: ["dist/worker/run-pipeline.js"],
        },
      ],
    },
  };

  const res = await fetch(`${FLY_API}/apps/${WORKER_APP}/machines`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${FLY_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`fly spawn failed: ${res.status} ${text}`);
  }

  const json = (await res.json()) as { id: string };
  return json.id;
}

export async function destroyMachine(machineId: string) {
  await fetch(`${FLY_API}/apps/${WORKER_APP}/machines/${machineId}?force=true`, {
    method: "DELETE",
    headers: { "Authorization": `Bearer ${FLY_TOKEN}` },
  }).catch(() => {});
}
