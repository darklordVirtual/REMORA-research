/**
 * REMORA governed MCP gateway.
 *
 * An MCP client (Claude Code, Claude Desktop, ChatGPT) sees ordinary tools.
 * Every call is routed through REMORA's execution path before any side effect
 * occurs. The MCP handler holds no credential to the downstream system; only
 * the GovernedToolDispatcher inside the container does. That is what makes
 * this an execution boundary rather than a filter — an agent that dislikes a
 * refusal has no second route to the same effect.
 *
 * See docs/design/cloudflare-mcp-gateway-v1.md (DOC-319).
 */
import { Container, getContainer } from "@cloudflare/containers";
import { DurableObject } from "cloudflare:workers";
import { handleRpc, type JsonRpcRequest, type PendingProposal, type ProposalStore } from "./mcp";
import { RemoraClient } from "./remora";

export interface Env {
  /** Absent in the development config, which uses REMORA_API_URL instead. */
  REMORA?: DurableObjectNamespace<RemoraContainer>;
  PROPOSALS: DurableObjectNamespace<ProposalDO>;
  REMORA_AGENT_TOKEN: string;

  // ── Container configuration, all supplied as Worker secrets ──────────────
  // Named individually rather than passed as one blob so a missing one is a
  // deploy-time type error instead of a container that starts and then fails
  // its fail-closed check in production.
  REMORA_PG_DSN: string;
  REMORA_API_TOKENS: string;
  REMORA_PDP_SIGNING_KEY: string;
  REMORA_LEASE_SIGNING_KEY: string;
  REMORA_AUDIT_SIGNING_KEY: string;
  REMORA_ENVELOPE_SIGNING_KEY: string;
  /** Set these together, once a signed ToolSpec bundle exists for the
   *  registry. Until then the deployment runs the default research profile
   *  with production prerequisites, and says so. */
  REMORA_RUNTIME_PROFILE?: string;
  REMORA_TOOLSPEC_BUNDLE?: string;
  REMORA_TOOLSPEC_SIGNING_KEY?: string;
  REMORA_TOOLSPEC_TRUSTED_IDENTITIES?: string;
  /**
   * Development only: send execution calls to a REMORA API reachable over the
   * network instead of to the bound container, so the gateway can be run
   * against `deploy/ot-pilot/docker-compose.yml` without building a container
   * image on every edit.
   *
   * This changes the transport, not the authority. Whatever it points at is
   * still a REMORA execution API making every decision; there is no code path
   * here that reaches a tool without one.
   */
  REMORA_API_URL?: string;
}

/**
 * The REMORA container.
 *
 * Always on: measured cold start is 4.1-4.4 s on this instance type, and a
 * wake-on-demand configuration would pay that on every cold MCP call to save
 * roughly $7 a month. DOC-319 records the measurement and the reasoning.
 */
export class RemoraContainer extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "4h";
  // The container reaches its Postgres over TLS. Measured 2026-08-23: raw TCP
  // egress works and psycopg completes a full wire-protocol session, so no
  // HTTP-shaped persistence backend is needed.
  enableInternet = true;

  /**
   * Configuration for the REMORA process.
   *
   * REMORA_ENV=production makes the fail-closed prerequisites binding rather
   * than advisory: without durable execution state and the signing keys the
   * process refuses to start. That refusal is the point — a gateway that came
   * up without a durable one-time-grant ledger would accept a replayed grant
   * after any restart.
   *
   * REMORA_RUNTIME_PROFILE is deliberately NOT pinned to controlled_pilot
   * here. That profile additionally requires a signed ToolSpec bundle, a
   * signing key and a trusted-identity allowlist, and slice 1 has no signed
   * bundle for the OT registry. Naming the stronger profile without the
   * bundle would either refuse to start or, worse, describe a deployment as
   * something it is not. Set REMORA_RUNTIME_PROFILE once the bundle exists;
   * the fail-closed check in remora/toolcall/runtime_profile.py will confirm
   * it rather than take the claim on trust.
   */
  envVars: Record<string, string>;

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      REMORA_ENV: "production",
      REMORA_ENABLED_SURFACES: "execution",
      ...(env.REMORA_RUNTIME_PROFILE
        ? { REMORA_RUNTIME_PROFILE: env.REMORA_RUNTIME_PROFILE }
        : {}),
      REMORA_PG_DSN: env.REMORA_PG_DSN,
      REMORA_CONTROL_PLANE_DSN: env.REMORA_PG_DSN,
      REMORA_API_TOKENS: env.REMORA_API_TOKENS,
      REMORA_API_BEARER_TOKEN: env.REMORA_AGENT_TOKEN,
      REMORA_PDP_SIGNING_KEY: env.REMORA_PDP_SIGNING_KEY,
      REMORA_LEASE_SIGNING_KEY: env.REMORA_LEASE_SIGNING_KEY,
      REMORA_AUDIT_SIGNING_KEY: env.REMORA_AUDIT_SIGNING_KEY,
      REMORA_ENVELOPE_SIGNING_KEY: env.REMORA_ENVELOPE_SIGNING_KEY,
      ...(env.REMORA_TOOLSPEC_BUNDLE
        ? {
            REMORA_TOOLSPEC_BUNDLE: env.REMORA_TOOLSPEC_BUNDLE,
            REMORA_TOOLSPEC_SIGNING_KEY: env.REMORA_TOOLSPEC_SIGNING_KEY ?? "",
            REMORA_TOOLSPEC_TRUSTED_IDENTITIES:
              env.REMORA_TOOLSPEC_TRUSTED_IDENTITIES ?? "",
          }
        : {}),
      REMORA_TOOL_REGISTRY_MODULE: "ot_registry",
      REMORA_SEMANTIC_BUNDLE_MODULE: "ot_bundle",
      REMORA_INTENT_SOURCE_FILE: "/app/work_orders.json",
      REMORA_EXECUTION_ARTIFACT_DIR: "/var/lib/remora/artifacts",
      PYTHONPATH: "/app",
    };
  }
}

/** Durable storage for proposals waiting on a human. */
export class ProposalDO extends DurableObject {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const id = url.pathname.slice(1);
    if (request.method === "PUT") {
      await this.ctx.storage.put(id, await request.json());
      return new Response(null, { status: 204 });
    }
    if (request.method === "DELETE") {
      await this.ctx.storage.delete(id);
      return new Response(null, { status: 204 });
    }
    const found = await this.ctx.storage.get<PendingProposal>(id);
    return found
      ? Response.json(found)
      : new Response(null, { status: 404 });
  }
}

function storeFor(env: Env, session: string): ProposalStore {
  const stub = env.PROPOSALS.get(env.PROPOSALS.idFromName(session));
  const at = (id: string) => `http://proposals/${encodeURIComponent(id)}`;
  return {
    async put(id, p) {
      await stub.fetch(new Request(at(id), { method: "PUT", body: JSON.stringify(p) }));
    },
    async get(id) {
      const res = await stub.fetch(new Request(at(id)));
      return res.status === 200 ? await res.json<PendingProposal>() : null;
    },
    async delete(id) {
      await stub.fetch(new Request(at(id), { method: "DELETE" }));
    },
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({
        status: "ok",
        service: "remora-mcp-gateway",
        transport: env.REMORA_API_URL ? "direct (development)" : "container",
      });
    }

    if (url.pathname !== "/mcp") {
      return new Response("Not found. The MCP endpoint is /mcp.", { status: 404 });
    }
    if (request.method !== "POST") {
      // Streamable HTTP allows a GET listening stream; this server is
      // request/response only and says so rather than hanging the client.
      return new Response("Method not allowed. This server is POST-only.", {
        status: 405,
        headers: { Allow: "POST" },
      });
    }

    let body: JsonRpcRequest | JsonRpcRequest[];
    try {
      body = await request.json();
    } catch {
      return Response.json(
        { jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } },
        { status: 400 },
      );
    }

    // One MCP session gets one proposal store, so a proposal cannot be
    // redeemed from a different session than the one that created it.
    const session =
      request.headers.get("Mcp-Session-Id") ?? "default";

    const direct = env.REMORA_API_URL;
    const deps = {
      remora: direct
        ? new RemoraClient((req) => fetch(req), env.REMORA_AGENT_TOKEN, direct)
        : new RemoraClient(
            (req) => getContainer(env.REMORA!).fetch(req),
            env.REMORA_AGENT_TOKEN,
          ),
      store: storeFor(env, session),
      newId: () => crypto.randomUUID(),
    };

    const messages = Array.isArray(body) ? body : [body];
    const replies = [];
    for (const m of messages) {
      const r = await handleRpc(m, deps);
      if (r !== null) replies.push(r);
    }

    if (replies.length === 0) return new Response(null, { status: 202 });
    return Response.json(Array.isArray(body) ? replies : replies[0]);
  },
};
