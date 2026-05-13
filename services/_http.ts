// Shared HTTP helper that mirrors backend's { success, data, error } envelope.
export const BACKEND_URL =
  process.env.BACKEND_URL ?? "http://localhost:5001";

export class BackendError extends Error {
  constructor(message: string, public status?: number) { super(message); }
}

type Envelope<T> = { success: boolean; data: T; error?: string };

export async function call<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), init.timeoutMs ?? 600_000);
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        Accept: "application/json",
        ...(init.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(init.headers ?? {}),
      },
    });
  } finally { clearTimeout(t); }

  const text = await res.text();
  let body: unknown;
  try { body = text ? JSON.parse(text) : undefined; } catch { body = text; }
  if (!res.ok) {
    const msg =
      (typeof body === "object" && body
        ? (body as { error?: string; message?: string }).error
          ?? (body as { error?: string; message?: string }).message
        : undefined) ?? `HTTP ${res.status}`;
    throw new BackendError(msg, res.status);
  }
  const env = body as Envelope<T>;
  if (env && typeof env === "object" && "success" in env) {
    if (!env.success) throw new BackendError(env.error ?? "backend failed");
    return env.data;
  }
  return body as T;
}

export async function waitForGraphTask(taskId: string, intervalMs = 3000, timeoutMs = 30 * 60_000) {
  const start = Date.now();
  for (;;) {
    const t = await call<{
      task_id: string; status: string; progress?: number; message?: string;
      result?: { project_id: string; graph_id: string; node_count: number; edge_count: number };
      error?: string;
    }>(`/api/graph/task/${encodeURIComponent(taskId)}`);
    if (t.status === "completed") return t;
    if (t.status === "failed") throw new BackendError(t.error || t.message || "graph task failed");
    if (Date.now() - start > timeoutMs) throw new BackendError("graph task timeout", 408);
    await new Promise(r => setTimeout(r, intervalMs));
  }
}
