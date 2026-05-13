import { createClient } from "@supabase/supabase-js";

// Service role: workers/API write to `reports` directly.
export const supabaseAdmin = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!,
  { auth: { persistSession: false } }
);

export async function patchReport(
  reportId: string,
  patch: Record<string, unknown>
) {
  const { error } = await supabaseAdmin
    .from("reports")
    .update(patch)
    .eq("id", reportId);
  if (error) throw new Error(`reports patch failed: ${error.message}`);
}
