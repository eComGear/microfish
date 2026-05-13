import { call } from "./_http";

export type OntologyResult = {
  project_id: string;
  project_name: string;
  ontology: unknown;
  analysis_summary: string;
  files: Array<{ filename: string; size: number }>;
  total_text_length: number;
};

export async function generateOntologyFromFiles(input: {
  files: File[];
  simulation_requirement: string;
  project_name?: string;
  additional_context?: string;
}): Promise<OntologyResult> {
  const fd = new FormData();
  for (const f of input.files) fd.append("files", f, f.name);
  fd.append("simulation_requirement", input.simulation_requirement);
  if (input.project_name) fd.append("project_name", input.project_name);
  if (input.additional_context) fd.append("additional_context", input.additional_context);
  return call<OntologyResult>("/api/graph/ontology/generate", {
    method: "POST",
    body: fd,
    timeoutMs: 15 * 60_000,
  });
}
