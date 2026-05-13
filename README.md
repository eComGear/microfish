# MicroFish — Option 3 (fly.io machine-per-simulation)

Drop these files into the MicroFish repo. They give you:

1. `migrations/001_pipeline_jobs.sql` — durable job table
2. `src/api/server.ts` — `POST /pipeline/run` endpoint Lovable calls
3. `src/worker/run-pipeline.ts` — one process per simulation
4. `Dockerfile` + `fly.api.toml` + `fly.worker.toml` — fly deploy config

## One-time setup

```bash
# 1. Migrate Postgres
psql "$DATABASE_URL" -f migrations/001_pipeline_jobs.sql

# 2. Create both fly apps
flyctl apps create microfish-api
flyctl apps create microfish-worker

# 3. Set secrets on BOTH apps
for app in microfish-api microfish-worker; do
  flyctl secrets set -a $app \
    DATABASE_URL="postgres://..." \
    SUPABASE_URL="https://xxx.supabase.co" \
    SUPABASE_SERVICE_ROLE_KEY="..." \
    DEEPSEEK_API_KEY="..." \
    PIPELINE_RUN_TOKEN="$(openssl rand -hex 32)" \
    FLY_API_TOKEN="$(flyctl auth token)" \
    FLY_WORKER_APP="microfish-worker" \
    FLY_WORKER_IMAGE="registry.fly.io/microfish-worker:latest" \
    FLY_WORKER_REGION="iad" \
    FLY_WORKER_CPUS="1" \
    FLY_WORKER_MEMORY_MB="512"
done

# 4. Build and push the worker image first (so the API can spawn it)
flyctl deploy -c fly.worker.toml --build-only --push --image-label latest

# 5. Deploy the API
flyctl deploy -c fly.api.toml
```

## How it works

```
Lovable → POST https://microfish-api.fly.dev/pipeline/run
          Authorization: Bearer $PIPELINE_RUN_TOKEN
          { reportId, userId, prompt, scenario, seedFileUrl }
   ↓
API inserts pipeline_jobs row, calls fly Machines API to spawn worker, returns 202
   ↓
Worker machine boots → reads JOB_ID env → runs pipeline → updates Supabase reports
   ↓
Worker exits → fly auto-destroys the machine ($0 idle cost)
```

## Wire the real pipeline

Open `src/worker/run-pipeline.ts` and replace the commented stubs
(`uploadSeed`, `buildGraph`, `prepare`, `startSimulation`, `runRounds`) with
imports from your existing MicroFish modules.

## Stuck-job recovery (optional, recommended)

`pipeline_jobs_stuck` view lists jobs whose worker died without writing a
final status. Run a small cron (every 60s) that selects from this view and
either re-spawns a worker or marks them failed after `max_attempts`.
