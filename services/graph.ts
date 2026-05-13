import { call, waitForGraphTask } from "./_http";

export async function buildGraphAndWait(input: {
  project_id: string;
  graph_name?: string;
  force?: boolean;
}): Promise<{ graph_id: string; node_count: number; edge_count: number }> {
  const { task_id } = await call<{ project_id: string; task_id: string; message: string }>(
    "/api/graph/build",
    { method: "POST", body: JSON.stringify(input) },
  );
  const t = await waitForGraphTask(task_id);
  if (!t.result) throw new Error("graph task completed without result");
  return {
    graph_id: t.result.graph_id,
    node_count: t.result.node_count,
    edge_count: t.result.edge_count,
  };
}
