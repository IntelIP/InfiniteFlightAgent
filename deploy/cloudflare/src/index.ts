// Edge Worker: verifies the Cloudflare Access JWT, then forwards /mcp and
// /health to one Cloudflare Container running the Python MCP server.
import { DurableObject } from "cloudflare:workers";
import { checkAccess } from "./auth.ts";

const CONTAINER_NAME = "dispatcher";
const CONTAINER_PORT = 8080;
const CONTAINER_INSTANCE = "standard-1";
const INACTIVITY_TIMEOUT_MS = 15 * 60 * 1000;
const INTERNAL_TOKEN_HEADER = "x-ifd-internal-token";
const FORWARDED_PATHS = new Set(["/mcp", "/mcp/", "/health"]);

// Passed from Worker secrets into the container environment at start.
const CONTAINER_ENV_KEYS = [
  "DATABASE_URL",
  "IFD_CREDENTIAL_KEY",
  "IFD_INTERNAL_TOKEN",
  "AEROAPI_KEY",
  "BROWSERBASE_API_KEY",
  "BROWSERBASE_SIMBRIEF_CONTEXT_ID",
  "SIMBRIEF_USERID",
  "LANGSMITH_API_KEY",
  "LANGSMITH_PROJECT",
  "LANGSMITH_TRACING",
  "R2_ACCOUNT_ID",
  "R2_ACCESS_KEY_ID",
  "R2_SECRET_ACCESS_KEY",
  "R2_BUCKET",
] as const;

export function containerEnv(env: Env): Record<string, string> {
  const source = env as unknown as Record<string, unknown>;
  const result: Record<string, string> = {};
  for (const key of CONTAINER_ENV_KEYS) {
    const value = source[key];
    if (typeof value === "string" && value !== "") result[key] = value;
  }
  // Paid operations stay off unless explicitly enabled.
  result.IFD_PAID_OPERATIONS_ENABLED = source.IFD_PAID_OPERATIONS_ENABLED === "true" ? "true" : "false";
  return result;
}

async function fingerprint(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export class DispatcherContainer extends DurableObject<Env> {
  private starting: Promise<void> | undefined;
  private readyFor: string | undefined;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    const container = ctx.container;
    if (container?.running) {
      void ctx.blockConcurrencyWhile(() => container.setInactivityTimeout(INACTIVITY_TIMEOUT_MS));
    }
  }

  async fetch(request: Request): Promise<Response> {
    this.starting ??= this.ensureReady().finally(() => {
      this.starting = undefined;
    });
    await this.starting;

    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");
    return this.ctx.container!.getTcpPort(CONTAINER_PORT).fetch(forwarded);
  }

  // Starts the container, or restarts it when its startup configuration
  // (secrets, paid-operations flag, image) no longer matches the deployed
  // Worker. A running process keeps the environment it started with, so this
  // is what makes secret changes and the emergency stop take effect.
  private async ensureReady(): Promise<void> {
    const container = this.ctx.container;
    if (!container) throw new Error("No container is configured for this Durable Object");

    const env = containerEnv(this.env);
    const image = container.images.base;
    const wanted = await fingerprint({ env, image, instance: CONTAINER_INSTANCE });
    if (container.running && this.readyFor === wanted) return;

    if (container.running && (await this.ctx.storage.get<string>("fingerprint")) !== wanted) {
      await container.destroy("Startup configuration changed");
    }
    if (!container.running) {
      container.start({ image, instance: CONTAINER_INSTANCE, enableInternet: true, env });
      await this.ctx.storage.put("fingerprint", wanted);
    }
    await container.setInactivityTimeout(INACTIVITY_TIMEOUT_MS);
    await this.waitForHealth();
    this.readyFor = wanted;
  }

  private async waitForHealth(): Promise<void> {
    const port = this.ctx.container!.getTcpPort(CONTAINER_PORT);
    let lastError: unknown;
    for (let attempt = 0; attempt < 300; attempt++) {
      try {
        const response = await port.fetch("http://container/health", {
          signal: AbortSignal.timeout(2000),
        });
        await response.body?.cancel();
        if (response.ok) return;
        lastError = new Error(`Health check returned ${response.status}`);
      } catch (error) {
        lastError = error;
      }
      await scheduler.wait(200);
    }
    throw new Error(`Container did not become healthy on port ${CONTAINER_PORT}`, { cause: lastError });
  }
}

function errorResponse(status: number, message: string): Response {
  return Response.json({ error: message }, { status, headers: { "cache-control": "no-store" } });
}

export default {
  async fetch(request, env): Promise<Response> {
    const access = await checkAccess(request, {
      teamDomain: env.ACCESS_TEAM_DOMAIN,
      audience: env.ACCESS_AUD,
      allowedEmail: env.ACCESS_ALLOWED_EMAIL,
    });
    if (!access.ok) return access.response;

    if (!FORWARDED_PATHS.has(new URL(request.url).pathname)) return errorResponse(404, "Not found");
    if (!env.IFD_INTERNAL_TOKEN) return errorResponse(503, "Internal token is not configured");

    const headers = new Headers(request.headers);
    headers.delete("cf-access-jwt-assertion");
    headers.delete("cookie");
    headers.set(INTERNAL_TOKEN_HEADER, env.IFD_INTERNAL_TOKEN);
    headers.set("x-ifd-access-identity", access.identity);

    try {
      return await env.DISPATCHER.getByName(CONTAINER_NAME).fetch(new Request(request, { headers }));
    } catch (error) {
      console.error("Container request failed", error);
      return errorResponse(503, "Dispatcher container is unavailable");
    }
  },
} satisfies ExportedHandler<Env>;
