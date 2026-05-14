import { createClient } from "@supabase/supabase-js";
import ws from "ws";

// Service role client: workers/API write to `reports` directly.
// Node 20 has no native WebSocket, so we explicitly provide the `ws`
// package as the realtime transport. Without this, @supabase/realtime-js
// throws "Node.js 20 detected without native WebSocket support" on import
// and the Fly.io machine crashes in a restart loop.
export const supabaseAdmin = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!,
  {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
    realtime: {
      transport: ws as unknown as typeof WebSocket,
    },
  }
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
