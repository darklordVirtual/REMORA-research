/**
 * Typed read-model client for the REAL /v1 governance API (Phase 12).
 *
 * Every consumer receives an explicit DataSourceState alongside its data —
 * LIVE, DEMO, OFFLINE, DEGRADED or ERROR — and this module NEVER substitutes
 * simulated data: with no API configured the state is DEMO and `data` is
 * null; a failed call is OFFLINE/ERROR with `data` null. Rendering something
 * synthetic in those states is a UI decision that must go through the
 * sim modules and carry the DemoBanner — it can never happen silently here
 * (guarded by test: this module imports nothing from remora-sim).
 *
 * Types mirror servers/execution_contracts.py by hand until OpenAPI type
 * generation lands; field names are the wire names.
 */

export type DataSourceState = "LIVE" | "DEMO" | "OFFLINE" | "DEGRADED" | "ERROR";

export interface SourcedResult<T> {
  state: DataSourceState;
  data: T | null;
  /** Machine-readable detail for OFFLINE/ERROR/DEGRADED. */
  detail?: string;
}

export interface ApiConfig {
  baseUrl: string;
  token: string;
}

/** Explicit runtime config: unset means DEMO, never a silent default host. */
export function apiConfig(
  env: Record<string, string | undefined> = (
    import.meta as unknown as { env: Record<string, string | undefined> }
  ).env,
): ApiConfig | null {
  const baseUrl = (env.VITE_REMORA_API_URL ?? "").trim().replace(/\/$/, "");
  const token = (env.VITE_REMORA_API_TOKEN ?? "").trim();
  if (!baseUrl || !token) return null;
  return { baseUrl, token };
}

// ── Wire types (mirroring servers/execution_contracts.py) ─────────────────────

export interface AuditRef {
  sequence_no: number;
  entry_hash: string;
}

export interface ProposalLifecycle {
  proposal_id: string;
  current_state: string;
  events: Array<{
    sequence_no: number;
    entry_hash: string;
    event: string;
    actor: string | null;
    payload: Record<string, unknown>;
  }>;
  dispatch: Record<string, unknown> | null;
  effect: Record<string, unknown>;
}

export interface GovernanceMetrics {
  execution_assess_total?: number;
  execution_decision_counts?: Record<string, number>;
  execution_executes_total?: number;
  execution_tool_calls_executed?: number;
  execution_refusals?: Record<string, number>;
  execution_state_durable?: boolean;
  [key: string]: unknown;
}

export interface PolicyVersion {
  policy_version: string;
  policy_hash: string;
  runtime_mode: string;
  execution_state_durable: boolean;
  [key: string]: unknown;
}

// ── Fetch with explicit state derivation ──────────────────────────────────────

async function sourcedGet<T>(
  config: ApiConfig | null,
  path: string,
  degradedWhen?: (data: T) => string | null,
): Promise<SourcedResult<T>> {
  if (!config) {
    return { state: "DEMO", data: null, detail: "no API configured" };
  }
  let resp: Response;
  try {
    resp = await fetch(`${config.baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${config.token}` },
    });
  } catch (e) {
    return {
      state: "OFFLINE",
      data: null,
      detail: e instanceof Error ? e.message : String(e),
    };
  }
  if (!resp.ok) {
    return { state: "ERROR", data: null, detail: `HTTP ${resp.status}` };
  }
  let data: T;
  try {
    data = (await resp.json()) as T;
  } catch {
    return { state: "ERROR", data: null, detail: "unparseable response" };
  }
  const degraded = degradedWhen?.(data);
  if (degraded) {
    return { state: "DEGRADED", data, detail: degraded };
  }
  return { state: "LIVE", data };
}

export function getGovernanceMetrics(
  config: ApiConfig | null,
): Promise<SourcedResult<GovernanceMetrics>> {
  return sourcedGet<GovernanceMetrics>(config, "/v1/metrics", (m) =>
    m.execution_state_durable === false ? "execution state is in-process (not durable)" : null,
  );
}

export function getPolicyVersion(config: ApiConfig | null): Promise<SourcedResult<PolicyVersion>> {
  return sourcedGet<PolicyVersion>(config, "/v1/policy/version", (p) =>
    p.execution_state_durable === false ? "execution state is in-process (not durable)" : null,
  );
}

export function getProposalLifecycle(
  config: ApiConfig | null,
  proposalId: string,
): Promise<SourcedResult<ProposalLifecycle>> {
  return sourcedGet<ProposalLifecycle>(
    config,
    `/v1/execution/proposals/${encodeURIComponent(proposalId)}/lifecycle`,
  );
}
