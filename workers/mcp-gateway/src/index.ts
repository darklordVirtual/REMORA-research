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
import { Container, ContainerProxy, getContainer } from "@cloudflare/containers";
import { DurableObject } from "cloudflare:workers";

// Required by outbound interception: the runtime routes the container's
// intercepted requests through this, so it has to be exported from the
// entrypoint even though nothing here calls it directly.
export { ContainerProxy };
import { handleRpc, type JsonRpcRequest, type PendingProposal, type ProposalStore } from "./mcp";
import { RemoraClient } from "./remora";
import { verifyGraphWrite } from "./effect";

export interface Env {
  /** Absent in the development config, which uses REMORA_API_URL instead. */
  REMORA?: DurableObjectNamespace<RemoraContainer>;
  PROPOSALS: DurableObjectNamespace<ProposalDO>;
  REMORA_AGENT_TOKEN: string;
  /** The execution domain's container binding. Absent = unsplit deployment. */
  EXECUTION?: DurableObjectNamespace<RemoraExecutionContainer>;
  /**
   * Compliance boundary for the proposal store, e.g. "eu". Set in
   * wrangler.toml alongside the container's own jurisdiction constraint so
   * the two cannot drift apart. Unset means Cloudflare places the object
   * without a constraint, which is only right for local development.
   */
  PROPOSAL_JURISDICTION?: string;

  // ── Container configuration, all supplied as Worker secrets ──────────────
  // Named individually rather than passed as one blob so a missing one is a
  // deploy-time type error instead of a container that starts and then fails
  // its fail-closed check in production.
  /**
   * Durable execution state. Exactly one of these is set.
   *
   * REMORA_PG_DSN is the real posture: Postgres over TLS, surviving restarts
   * and replacements. REMORA_CHAIN_DB is a path on the container's own disk,
   * which on Cloudflare is ephemeral — the file is gone the next time the
   * instance starts. It exists so the deployment path can be exercised before
   * a database is provisioned, and the gateway refuses to describe itself as
   * anything else while it is in use.
   */
  REMORA_PG_DSN?: string;
  REMORA_CHAIN_DB?: string;
  REMORA_API_TOKENS: string;
  /** The credential for the governed tools. It lives in the container and
   *  nowhere else — the agent never holds it, which is what makes a refusal
   *  final rather than advisory. */
  REMORA_GITHUB_TOKEN?: string;
  /** Repositories this deployment may touch, comma separated. A closed list
   *  rather than an open credential scope: the token may have wider access,
   *  and the deployment narrows it. */
  REMORA_GITHUB_REPOS?: string;
  /** exeQta knowledge graph. The tenant is configuration, never an argument:
   *  a tool that accepted a tenant id would make cross-tenant access a matter
   *  of what the agent proposed. */
  REMORA_KG_TENANT?: string;
  /** The environment a call targets. Describes this deployment, not the data.
   *  Set to prod on a production deployment and the ACCEPT paths exclude it
   *  again, deliberately. */
  REMORA_TARGET_ENVIRONMENT?: string;
  /** The graph database. A binding, not a token: it cannot be read out of the
   *  container, because it is never in the container. */
  GRAPH_DB?: D1Database;
  /** Durable execution state. A binding, so the container keeps durable state
   *  without a credential and without a writable disk. */
  STATE_DB?: D1Database;
  REMORA_PDP_SIGNING_KEY: string;
  /**
   * Symmetric lease key. Goes to the AUTHORITY container only, and only for
   * the migration window: while it exists, whoever holds it can mint. It is
   * deliberately absent from the execution container's envVars below.
   */
  REMORA_LEASE_SIGNING_KEY: string;
  /**
   * Ed25519 seed, 32 bytes hex. The authority domain's private key and the
   * whole point of the split: the container that executes never receives it,
   * so a compromise there cannot author authority. Never log this.
   */
  REMORA_LEASE_ED25519_PRIVATE?: string;
  /**
   * Ed25519 public key, 32 bytes hex. Safe in the execution container, which
   * is exactly why the split works.
   */
  REMORA_LEASE_ED25519_PUBLIC?: string;
  // No dedicated hop secret. The executor authenticates every caller against
  // its REMORA_API_TOKENS table, so a bearer that table does not know is a
  // 401 -- which is how the first deployment of this split failed. The hop
  // reuses REMORA_AGENT_TOKEN, granting nothing new: the Worker already calls
  // the container with it. A dedicated secret would need its own entry in that
  // table, and would still not be an authority credential.
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
   * The graph, reached without a credential in the container.
   *
   * The container makes a plain HTTP request to graph.internal; this handler
   * runs in the Workers runtime, outside the container, and answers it from
   * the D1 binding. No database token is ever inside the container, so there
   * is nothing there to read out and reuse elsewhere — which is the
   * difference between a binding and a secret.
   *
   * Only parameterised statements are accepted, and the tenant clause is the
   * caller's to supply. That is not this layer's job to enforce: the registry
   * module binds it into every statement, and a test pins that it does.
   */
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
      ...(env.REMORA_PG_DSN
        ? {
            REMORA_PG_DSN: env.REMORA_PG_DSN,
            REMORA_CONTROL_PLANE_DSN: env.REMORA_PG_DSN,
          }
        : {
            // Durable state over the STATE_DB binding. Not the container's
            // disk: that is discarded at every restart, and the ledger that
            // refuses a replayed grant would go with it.
            REMORA_STATE_ENDPOINT: "http://state.internal/query",
            REMORA_CONTROL_PLANE_DB: env.REMORA_CHAIN_DB ?? "",
          }),
      REMORA_API_TOKENS: env.REMORA_API_TOKENS,
      REMORA_API_BEARER_TOKEN: env.REMORA_AGENT_TOKEN,
      REMORA_PDP_SIGNING_KEY: env.REMORA_PDP_SIGNING_KEY,
      // ── ADR-A: this container is the AUTHORITY domain ──────────────────
      // It decides and it signs what it decided. When an Ed25519 private key
      // is configured, leases are minted under it and the executor -- which
      // holds only the public half -- cannot produce one.
      //
      // The symmetric key is still passed while it is configured, because a
      // deployment mid-migration legitimately has only that. Once the keypair
      // is in service, removing REMORA_LEASE_SIGNING_KEY from the secret store
      // is what closes the window; the code refuses HMAC on its own the moment
      // asymmetric material appears (lease_signing.hmac_accepted).
      REMORA_LEASE_SIGNING_KEY: env.REMORA_LEASE_SIGNING_KEY ?? "",
      ...(env.REMORA_LEASE_ED25519_PRIVATE
        ? {
            REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE:
              env.REMORA_LEASE_ED25519_PRIVATE,
          }
        : {}),
      ...(env.REMORA_LEASE_ED25519_PUBLIC
        ? {
            REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC:
              env.REMORA_LEASE_ED25519_PUBLIC,
          }
        : {}),
      // Where the effect actually happens. Set only when the execution
      // container exists; absent, this container dispatches locally exactly as
      // it did before the split, which is the compatibility path.
      ...(env.REMORA_LEASE_ED25519_PRIVATE
        ? {
            REMORA_EXECUTION_ENDPOINT: "http://execution.internal",
            // The hop authenticates against the executor's REMORA_API_TOKENS
            // table, which is the same authenticator every other caller goes
            // through. A dedicated hop secret would need its own entry in that
            // table; until it has one, a token the table does not know is
            // simply a 401, which is how the first deployment of this split
            // failed. Reusing the operator token grants nothing new -- the
            // Worker already calls the container with it.
            REMORA_EXECUTION_TOKEN: env.REMORA_AGENT_TOKEN,
          }
        : {}),
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
      // The governed GitHub tool set. Authority comes from a GitHub issue
      // rather than a work-order file, so there is no intent source to point
      // at: the bundle reads the issue named by intent_ref and digests its
      // text, which means an issue edited after approval stops matching.
      // Risk metadata for the tools this deployment names. Without it every
      // one of them falls to the fail-closed critical/unknown default, which
      // is the right default and a useless classification — a predicate list
      // and a write into a shared graph become the same thing, ACCEPT is
      // structurally unreachable, and every call waits for a person.
      //
      // The file is hashed into the policy bundle: editing it moves the hash
      // and invalidates every outstanding lease, so a tool cannot be
      // relabelled and then executed under an older authorization.
      // The deterministic ACCEPT for a read whose every grounding signal is
      // confirmed under a server-resolved authority. Off by default because
      // it is meaningless without declared tool contracts, a state index and
      // an intent source; this deployment now has all three.
      //
      // It does not make production reads autonomous: _is_grounded_read
      // requires a non-production target, because no read-only guarantee
      // covers the disclosure blast radius of production data. That refusal
      // is the active decision here, not a missing piece.
      REMORA_GROUNDED_READ_ACCEPT: "1",
      REMORA_TOOL_METADATA_FILE: "/app/deploy/gateway/tool_metadata.json",
      REMORA_TOOL_REGISTRY_MODULE: "deploy.gateway.registry",
      REMORA_SEMANTIC_BUNDLE_MODULE: "deploy.gateway.bundle",
      // Which tool sets are live is decided from whether their configuration
      // is complete, so an absent credential means the set is not offered
      // rather than offered and broken.
      REMORA_GITHUB_TOKEN: env.REMORA_GITHUB_TOKEN ?? "",
      REMORA_GITHUB_REPOS: env.REMORA_GITHUB_REPOS ?? "",
      REMORA_KG_TENANT: env.REMORA_KG_TENANT ?? "",
      REMORA_EXECUTION_ARTIFACT_DIR: "/var/lib/remora/artifacts",
      PYTHONPATH: "/app",
    };
  }
}

/**
 * The EXECUTION domain (ADR-A).
 *
 * Same image, different custody. This container holds the Ed25519 PUBLIC key
 * and the downstream tool credentials; it never receives the private lease
 * key, so `ExecutionLease.issue` refuses here and there is no material with
 * which to author authority. It serves exactly one execution surface,
 * /v1/execution/dispatch-leased, and either dispatches what a presented lease
 * binds or refuses.
 *
 * What this does and does not buy, stated plainly because the distinction is
 * easy to overclaim:
 *
 *   it CANNOT mint new ExecutionLease authority  -- no private key exists here
 *   it CAN still reach the downstream system     -- it holds those credentials
 *
 * The second line is the ambient-bypass property (E2) and is NOT addressed by
 * splitting keys. A compromised executor cannot forge authority; it can still
 * call GitHub with the token it legitimately holds. Closing that needs the
 * credential to move behind a binding, which is separate work.
 */
export class RemoraExecutionContainer extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "30m";
  enableInternet = true;
  envVars: Record<string, string>;

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      REMORA_ENV: "production",
      REMORA_ENABLED_SURFACES: "execution",
      ...(env.REMORA_RUNTIME_PROFILE
        ? { REMORA_RUNTIME_PROFILE: env.REMORA_RUNTIME_PROFILE }
        : {}),
      // Durable state: the nonce ledger this container consumes into must
      // survive its own replacement, or the one-time property has the
      // lifetime of a container.
      ...(env.REMORA_PG_DSN
        ? {
            REMORA_PG_DSN: env.REMORA_PG_DSN,
            REMORA_CONTROL_PLANE_DSN: env.REMORA_PG_DSN,
          }
        : {
            REMORA_STATE_ENDPOINT: "http://state.internal/query",
            REMORA_CONTROL_PLANE_DB: env.REMORA_CHAIN_DB ?? "",
          }),
      REMORA_API_TOKENS: env.REMORA_API_TOKENS,
      REMORA_API_BEARER_TOKEN: env.REMORA_AGENT_TOKEN,

      // ── the custody split, as configuration ──────────────────────────────
      // PUBLIC key only. REMORA_LEASE_SIGNING_KEY and the Ed25519 private key
      // are deliberately NOT listed. Their absence is the security property,
      // so it is asserted by a test rather than left to review to notice.
      REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC:
        env.REMORA_LEASE_ED25519_PUBLIC ?? "",
      // Production fail-closed requires a PDP token key; this container
      // verifies tokens, and the token scheme is still symmetric (ADR-A
      // converts the lease only). Recorded as a known remaining exposure in
      // docs/deployment/authority-key-topology.md rather than hidden here.
      REMORA_PDP_SIGNING_KEY: env.REMORA_PDP_SIGNING_KEY,
      REMORA_AUDIT_SIGNING_KEY: env.REMORA_AUDIT_SIGNING_KEY,
      REMORA_ENVELOPE_SIGNING_KEY: env.REMORA_ENVELOPE_SIGNING_KEY,

      // Downstream credentials live HERE and nowhere else. The authority
      // container cannot cause an effect even if it wanted to.
      REMORA_GITHUB_TOKEN: env.REMORA_GITHUB_TOKEN ?? "",
      REMORA_GITHUB_REPOS: env.REMORA_GITHUB_REPOS ?? "",
      REMORA_KG_TENANT: env.REMORA_KG_TENANT ?? "",
      REMORA_TARGET_ENVIRONMENT: env.REMORA_TARGET_ENVIRONMENT ?? "staging",

      REMORA_GROUNDED_READ_ACCEPT: "1",
      REMORA_TOOL_METADATA_FILE: "/app/deploy/gateway/tool_metadata.json",
      REMORA_TOOL_REGISTRY_MODULE: "deploy.gateway.registry",
      REMORA_SEMANTIC_BUNDLE_MODULE: "deploy.gateway.bundle",
      REMORA_EXECUTION_ARTIFACT_DIR: "/var/lib/remora/artifacts",
      PYTHONPATH: "/app",
    };
  }
}

/**
 * Give the container the graph without giving it a credential.
 *
 * Assigned after the class rather than declared as `static outboundByHost`
 * inside it: the base class exposes this as a static accessor, and a static
 * class field compiles to defineProperty, which shadows the setter instead of
 * calling it. The handler then never registers and the container's request
 * escapes to the public internet, where `graph.internal` fails DNS. That is
 * how this was found.
 */
/** One D1 request from the container, answered from a binding. */
async function d1Request(db: D1Database | undefined, request: Request,
                         what: string): Promise<Response> {
  if (request.method !== "POST") {
    return Response.json(
      { success: false, errors: [{ message: "POST only" }] }, { status: 405 });
  }
  if (!db) {
    return Response.json(
      { success: false, errors: [{ message: `no ${what} binding here` }] },
      { status: 503 });
  }
  let body: { sql?: string; params?: unknown[]; batch?: { sql: string; params?: unknown[] }[] };
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { success: false, errors: [{ message: "malformed request" }] },
      { status: 400 });
  }

  // A batch is the container's transaction: D1 applies it atomically, which
  // is what stands in for a rollback the container cannot ask for.
  const statements = body.batch
    ?? (typeof body.sql === "string" ? [{ sql: body.sql, params: body.params }] : null);
  if (!statements || statements.length === 0) {
    return Response.json(
      { success: false, errors: [{ message: "sql or batch is required" }] },
      { status: 400 });
  }

  try {
    const prepared = statements.map((s) => {
      const stmt = db.prepare(s.sql);
      return Array.isArray(s.params) && s.params.length
        ? stmt.bind(...s.params) : stmt;
    });
    const out = await db.batch(prepared);
    return Response.json({
      success: true,
      errors: [],
      // Two shapes, because the two callers want different things: the graph
      // tools read `result`, the state adapter reads `results`.
      result: out.map((r) => ({ results: r.results ?? [] })),
      results: out.map((r) => r.results ?? []),
    });
  } catch (e) {
    return Response.json(
      { success: false,
        errors: [{ message: String(e instanceof Error ? e.message : e) }] },
      { status: 500 });
  }
}

/**
 * Give the container its stores without giving it a credential.
 *
 * Assigned after the class rather than declared as `static outboundByHost`
 * inside it: the base class exposes this as a static accessor, and a static
 * class field compiles to defineProperty, which shadows the setter instead of
 * calling it. The handler then never registers and the container's request
 * escapes to the public internet, where the internal name fails DNS. That is
 * how this was found.
 */
RemoraContainer.outboundByHost = {
  "graph.internal": (request: Request, env: Env) =>
    d1Request(env.GRAPH_DB, request, "GRAPH_DB"),
  // Durable execution state: the tenant audit chain, the review queue and the
  // one-time-grant ledger. On container disk these would be discarded at
  // every restart and a consumed grant would become replayable.
  "state.internal": (request: Request, env: Env) =>
    d1Request(env.STATE_DB, request, "STATE_DB"),
  // The execution domain. Routed through the Worker rather than given as a
  // URL the container could redirect: the authority asks for
  // execution.internal and the Workers runtime decides what that means.
  "execution.internal": (request: Request, env: Env) => {
    if (!env.EXECUTION) {
      return Promise.resolve(Response.json(
        { error: "no execution container bound on this deployment" },
        { status: 503 }));
    }
    return getContainer(env.EXECUTION).fetch(request);
  },
};

// Same static-accessor caveat as above: assigned after the class, never as a
// static field. The execution container reaches durable state and nothing else.
RemoraExecutionContainer.outboundByHost = {
  "state.internal": (request: Request, env: Env) =>
    d1Request(env.STATE_DB, request, "STATE_DB"),
  "graph.internal": (request: Request, env: Env) =>
    d1Request(env.GRAPH_DB, request, "GRAPH_DB"),
};

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
  // A pending proposal holds the exact arguments of a call awaiting human
  // approval — what someone asked to change, and on which system. That is the
  // same class of record as the audit chain, so it is pinned to the same
  // jurisdiction as the container rather than placed wherever is nearest.
  //
  // The jurisdiction is fixed at creation and cannot be changed afterwards,
  // which is the property that makes it worth anything.
  const ns = env.PROPOSAL_JURISDICTION
    ? env.PROPOSALS.jurisdiction(env.PROPOSAL_JURISDICTION as DurableObjectJurisdiction)
    : env.PROPOSALS;
  const stub = ns.get(ns.idFromName(session));
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

/** Submit one verification to the proposal's audit trail. */
async function recordEffect(
  env: Env,
  declared: Record<string, unknown>,
  v: { status: string; reason_code: string; expected_sha256: string;
       observed_sha256: string; detail: string },
  executionId: string,
  tool: string,
): Promise<void> {
  if (v.status === "EFFECT_UNSUPPORTED") return;  // nothing to attest to
  const proposalId = String(declared.proposal_id ?? executionId);
  const body = JSON.stringify({
    execution_id: executionId,
    tool_id: tool,
    status: v.status,
    reason_code: v.reason_code,
    // Mandatory: an attestation nobody signed is not evidence, because a
    // reader cannot tell who claimed to have looked.
    verifier_identity: "remora-mcp-gateway/worker",
    expected_sha256: v.expected_sha256,
    observed_sha256: v.observed_sha256,
  });
  const request = new Request(
    `http://remora/v1/execution/proposals/${encodeURIComponent(proposalId)}/effect`,
    { method: "POST", body,
      headers: { "Content-Type": "application/json",
                 Authorization: `Bearer ${env.REMORA_AGENT_TOKEN}` } });
  try {
    if (env.REMORA_API_URL) {
      await fetch(new Request(
        `${env.REMORA_API_URL}/v1/execution/proposals/` +
        `${encodeURIComponent(proposalId)}/effect`, request));
    } else if (env.REMORA) {
      await getContainer(env.REMORA).fetch(request);
    }
  } catch {
    // A verification that could not be filed must not undo the execution
    // that already happened. It is lost from the trail, which is worse than
    // recording it and better than pretending the call failed.
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      const durable = Boolean(env.REMORA_PG_DSN) || Boolean(env.STATE_DB);
      return Response.json({
        status: "ok",
        service: "remora-mcp-gateway",
        transport: env.REMORA_API_URL ? "direct (development)" : "container",
        jurisdiction: env.PROPOSAL_JURISDICTION ?? "unconstrained",
        execution_state: env.REMORA_PG_DSN
          ? "durable (postgres)"
          : env.STATE_DB
            ? "durable (D1 binding)"
            : "EPHEMERAL (container disk)",
        ...(durable
          ? {}
          : {
              warning:
                "Execution state is on the container's own disk, which is " +
                "ephemeral. The tenant audit chain and the one-time-grant " +
                "ledger do not survive an instance restart, so a consumed " +
                "grant becomes replayable. This deployment exercises the " +
                "path; it is not a pilot. Set REMORA_PG_DSN to fix it.",
            }),
      });
    }

    // ── Human approval ────────────────────────────────────────────────────
    // The container is reachable only through this Worker, so without this
    // route nothing awaiting approval could ever be approved and every
    // mutating call would wait forever. That is fail-closed, but it is not
    // usable.
    //
    // The caller's own Authorization header is forwarded untouched and the
    // Worker's operator token is deliberately not used here. REMORA decides
    // whether the presented identity holds the approver role, exactly as it
    // does for a direct caller — so this route relays authority, it does not
    // confer any. A request arriving with the gateway's own operator token
    // gets the same 403 it would get anywhere else.
    if (url.pathname === "/approve" && request.method === "POST") {
      const auth = request.headers.get("Authorization");
      if (!auth) {
        return Response.json(
          {
            error: "missing Authorization",
            explanation:
              "Approving requires a bearer token holding the approver role. " +
              "The gateway cannot supply one; that is the point.",
          },
          { status: 401 },
        );
      }
      if (env.REMORA_API_URL) {
        return fetch(
          new Request(`${env.REMORA_API_URL}/v1/execution/approve`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: auth,
            },
            body: await request.text(),
          }),
        );
      }
      return getContainer(env.REMORA!).fetch(
        new Request("http://remora/v1/execution/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: auth },
          body: await request.text(),
        }),
      );
    }

    if (url.pathname !== "/mcp") {
      return new Response(
        "Not found. The MCP endpoint is /mcp; approvals go to /approve.",
        { status: 404 },
      );
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
      env: env as unknown as Record<string, unknown>,
      // The verifier reads the system of record through the Worker's own
      // binding — the same store the write landed in, reached without the
      // container's involvement. It answers "did it happen", not "was the
      // request accepted".
      verifyEffect: env.STATE_DB || env.GRAPH_DB
        ? async (tool: string, declared: Record<string, unknown>,
                 executionId: string) => {
            const verification = await verifyGraphWrite(
              tool, declared,
              async (id: string) => {
                if (!env.GRAPH_DB) return null;
                const row = await env.GRAPH_DB
                  .prepare(
                    "SELECT id, subject, predicate, object_json, object_kind, " +
                    "source, confidence FROM knowledge_facts " +
                    "WHERE tenant_id = ? AND id = ?")
                  .bind(env.REMORA_KG_TENANT ?? "", id)
                  .first();
                return (row as Record<string, unknown> | null) ?? null;
              });
            // Recorded on the proposal's own trail, as an attestation by a
            // named verifier. REMORA stores it as reported; it does not
            // independently re-check, and the record says so.
            await recordEffect(env, declared, verification, executionId, tool);
            return verification;
          }
        : undefined,
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
