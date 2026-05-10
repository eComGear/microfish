import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  MIROFISH_CONTAINER: DurableObjectNamespace<MirofishContainer>;
  LLM_API_KEY?: string;
  LLM_BASE_URL?: string;
  LLM_MODEL_NAME?: string;
  ZEP_API_KEY?: string;
  SECRET_KEY?: string;
}

export class MirofishContainer extends Container<Env> {
  defaultPort = 5001;
  sleepAfter = "10m";
  startupTimeout = "120s";

  // Forward Worker secrets as env vars inside the container.
  // The Container base reads `envVars` and passes them to the process.
  envVars = {
    LLM_API_KEY: this.env?.LLM_API_KEY ?? "",
    LLM_BASE_URL: this.env?.LLM_BASE_URL ?? "https://api.openai.com/v1",
    LLM_MODEL_NAME: this.env?.LLM_MODEL_NAME ?? "gpt-4o-mini",
    ZEP_API_KEY: this.env?.ZEP_API_KEY ?? "",
    SECRET_KEY: this.env?.SECRET_KEY ?? "mirofish-secret",
    FLASK_DEBUG: "false",
  };

  override onStart() { console.log("MirofishContainer started"); }
  override onStop() { console.log("MirofishContainer stopped"); }
  override onError(error: unknown) { console.error("MirofishContainer error:", error); }
}

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "Content-Type, Authorization, Accept-Language",
  "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
  "access-control-max-age": "86400",
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }
    try {
      const container = getContainer(env.MIROFISH_CONTAINER, "singleton");
      const upstream = await container.fetch(request);
      const headers = new Headers(upstream.headers);
      for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers,
      });
    } catch (err) {
      console.error("Worker fetch error:", err);
      return new Response(
        JSON.stringify({
          error: "WORKER_ERROR",
          message: err instanceof Error ? err.message : String(err),
        }),
        { status: 500, headers: { "content-type": "application/json", ...CORS } }
      );
    }
  },
};
