-- Run once on your Postgres (Supabase or fly Postgres).
-- This table is the durable source of truth for in-flight simulations.

create type pipeline_job_status as enum (
  'queued',
  'spawning',
  'running',
  'completed',
  'failed',
  'cancelled'
);

create table if not exists pipeline_jobs (
  id              uuid primary key default gen_random_uuid(),
  report_id       uuid not null,                 -- Supabase reports.id
  user_id         uuid not null,
  prompt          text not null,
  scenario        text,
  seed_file_url   text,
  status          pipeline_job_status not null default 'queued',
  stage           text,                          -- "upload" | "build_graph" | "prepare" | "start" | "rounds"
  progress        int  not null default 0,       -- 0..100
  machine_id      text,                          -- fly machine id once spawned
  attempt         int  not null default 0,
  max_attempts    int  not null default 3,
  error           text,
  result          jsonb,
  created_at      timestamptz not null default now(),
  started_at      timestamptz,
  finished_at     timestamptz,
  heartbeat_at    timestamptz
);

create index if not exists pipeline_jobs_status_idx
  on pipeline_jobs (status, created_at);

create index if not exists pipeline_jobs_report_idx
  on pipeline_jobs (report_id);

-- Resume helper: jobs that look stuck (no heartbeat for 2 min while running)
create or replace view pipeline_jobs_stuck as
select * from pipeline_jobs
where status in ('spawning','running')
  and (heartbeat_at is null or heartbeat_at < now() - interval '2 minutes');
