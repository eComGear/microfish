import { http } from "./_http.js";

export type SimStatus = {
  status: string;
  current_round?: number;
  total_rounds?: number;
  progress_percent?: number;
  error?: string;
};

export async function prepareAndWait(input: {
  project_id: string;
  graph_id?: string;
  enable_twitter?: boolean;
  enable_reddit?: boolean;
  max_agents?: number;
  use_llm_for_profiles?: boolean;
  parallel_profile_count?: number;
  seed_experts?: Array<{
    id: string; display_name: string; persona: string; fee_per_simulation?: number;
  }>;
}): Promise<{ simulation_id: string }> {
  const created = await call<{ simulation_id: string; project_id: string; graph_id?: string }>(
    "/api/simulation/create",
    {
      method: "POST",
      body: JSON.stringify({
        project_id: input.project_id,
        graph_id: input.graph_id,
        enable_twitter: input.enable_twitter,
        enable_reddit: input.enable_reddit,
      }),
    },
  );
  const simulation_id = created.simulation_id;

  const prep = await call<{ simulation_id: string; task_id?: string; status: string; already_prepared?: boolean }>(
    "/api/simulation/prepare",
    {
      method: "POST",
      body: JSON.stringify({
        simulation_id,
        max_agents: input.max_agents,
        use_llm_for_profiles: input.use_llm_for_profiles ?? true,
        parallel_profile_count: input.parallel_profile_count,
        seed_experts: input.seed_experts,
      }),
      timeoutMs: 15 * 60_000,
    },
  );
  if (prep.already_prepared || prep.status === "completed") return { simulation_id };

  const start = Date.now();
  for (;;) {
    const st = await call<{ status: string; progress?: number; message?: string; error?: string }>(
      "/api/simulation/prepare/status",
      { method: "POST", body: JSON.stringify({ simulation_id }) },
    );
    if (st.status === "completed") return { simulation_id };
    if (st.status === "failed") throw new Error(`prepare failed: ${st.error ?? st.message ?? ""}`);
    if (Date.now() - start > 30 * 60_000) throw new Error("prepare timeout");
    await new Promise(r => setTimeout(r, 4000));
  }
}

export async function startSimulation(input: {
  simulation_id: string;
  num_agents: number;
  num_rounds: number;
}): Promise<{ task_id: string }> {
  return call<{ task_id: string }>("/api/simulation/start", {
    method: "POST",
    body: JSON.stringify({
      simulation_id: input.simulation_id,
      num_agents: input.num_agents,
      max_agents: input.num_agents,
      num_rounds: input.num_rounds,
      max_rounds: input.num_rounds,
    }),
  });
}

export async function getSimulationStatus(simulation_id: string): Promise<SimStatus> {
  return call<SimStatus>(`/api/simulation/${encodeURIComponent(simulation_id)}`);
}
