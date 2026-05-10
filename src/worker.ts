import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  MIROFISH_CONTAINER: DurableObjectNamespace<MirofishContainer>;
}

export class MirofishContainer extends Container<Env> {
  // MUST match the port your app inside the Docker image listens on
  defaultPort = 8080;
  sleepAfter = "10m";
  // Give the container time to cold-start (model loading, etc.)
  startupTimeout = "120s";

  override onStart() {
    console.log("MirofishContainer started");
  }
  override onStop() {
    console.log("MirofishContainer stopped");
  }
  override onError(error: unknown) {
    console.error("MirofishContainer error:", error);
  }
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
      // Route everything to a single shared container instance.
      // For per-user isolation, swap "singleton" for a user/session id.
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
        {
          status: 500,
          headers: { "content-type": "application/json", ...CORS },
        }
      );
    }
  },
};
