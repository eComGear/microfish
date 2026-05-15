-- =========================================================
-- MicroFish schema (external Supabase, run once)
-- =========================================================

create table if not exists public.engine_projects (
  project_id  text primary key,
  name        text,
  status      text not null default 'created',
  data        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.engine_extracted_texts (
  id          bigserial primary key,
  project_id  text not null,
  source_id   text not null default 'default',
  content     text not null default '',
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  unique (project_id, source_id)
);
create index if not exists engine_extracted_texts_project_idx
  on public.engine_extracted_texts (project_id);

create table if not exists public.engine_graphs (
  graph_id    text primary key,
  project_id  text not null,
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now()
);
create index if not exists engine_graphs_project_idx
  on public.engine_graphs (project_id);

create table if not exists public.engine_tasks (
  task_id     text primary key,
  state       jsonb not null,
  updated_at  timestamptz not null default now()
);

-- Cache: dedupe identical simulation runs by (project_id, input_hash)
create table if not exists public.simulations (
  id             uuid primary key default gen_random_uuid(),
  project_id     text not null,
  input_hash     text not null,
  simulation_id  text,
  task_id        text,
  config         jsonb not null default '{}'::jsonb,
  result         jsonb,
  status         text not null default 'pending',
  error          text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (project_id, input_hash)
);
create index if not exists simulations_project_created_idx
  on public.simulations (project_id, created_at desc);
create index if not exists simulations_simid_idx
  on public.simulations (simulation_id);

-- Optional metadata sidecar (kept for forward-compat with existing code paths)
create table if not exists public.simulations_meta (
  simulation_id  text primary key,
  project_id     text,
  meta           jsonb not null default '{}'::jsonb,
  updated_at     timestamptz not null default now()
);

-- Reports: full markdown + structured payload, retrievable by report_id or simulation_id
create table if not exists public.engine_reports (
  report_id         text primary key,
  simulation_id     text,
  project_id        text,
  status            text not null default 'pending',
  title             text,
  markdown_content  text,
  data              jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists engine_reports_sim_idx
  on public.engine_reports (simulation_id, updated_at desc);
create index if not exists engine_reports_project_idx
  on public.engine_reports (project_id, updated_at desc);

-- RLS on (service-role key bypasses; no policies needed for backend)
alter table public.engine_projects        enable row level security;
alter table public.engine_extracted_texts enable row level security;
alter table public.engine_graphs          enable row level security;
alter table public.engine_tasks           enable row level security;
alter table public.simulations            enable row level security;
alter table public.simulations_meta       enable row level security;
alter table public.engine_reports         enable row level security;
