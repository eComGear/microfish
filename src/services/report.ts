import { http } from "./_http.js";

export async function generateReport(input: {
  simulation_id: string;
  force_regenerate?: boolean;
}): Promise<{ report_id: string; task_id?: string; status: string; already_generated?: boolean }> {
  return call("/api/report/generate", {
    method: "POST",
    body: JSON.stringify(input),
    timeoutMs: 15 * 60_000,
  });
}

export async function getReportStatus(report_id: string): Promise<{
  status: string; progress?: number; message?: string;
}> {
  return call("/api/report/generate/status", {
    method: "POST",
    body: JSON.stringify({ report_id }),
  });
}
