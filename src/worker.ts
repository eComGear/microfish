// Cloudflare Worker that proxies HTTPS traffic to the MiroFish Flask container.
// Adds permissive CORS so the Lovable frontend can call it from any origin.
import { Container, getContainer } from "@cloudflare/containers";

export class MirofishContainer extends Container {
  defaultPort = 8080;          // must match EXPOSE / app bind port
  sleepAfter = "10m";
  startupTimeout = "120s";     // give the image time to boot
 envVars = {
    // Secrets you set with `wrangler secret put` are auto-injected;
    // list any plain env passthroughs here if needed.
  };
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept-Language",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request: Request, env: { MIROFISH: DurableObjectNamespace<MirofishContainer> }) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const container = getContainer(env.MIROFISH, "singleton");
    const res = await container.fetch(request);
    const headers = new Headers(res.headers);
    for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  },
};
