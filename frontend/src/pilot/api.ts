// Typed client for the pilot console API (deploy/ot-pilot/console/app.py).
//
// These types describe what the *console* returns. The governed API's own
// OpenAPI contract is still largely untyped (`response_model=dict`); when that
// contract is typed, this file should be replaced by a generated client.

export type PilotRole = "operator" | "approver" | "viewer";

export type PilotHealth = { status?: string; version?: string; error?: string };

export type PilotPolicy = {
  runtime_mode?: string;
  policy_hash?: string;
  execution_state_durable?: boolean;
  execution_state_backend?: string;
  error?: string;
};

export type PilotMetrics = {
  execution_assess_total?: number;
  execution_approvals_total?: number;
  execution_tool_calls_executed?: number;
  execution_decision_counts?: Record<string, number>;
  execution_refusals?: Record<string, number>;
  control_plane_backend?: string;
  error?: string;
};

export type PilotChain = { chain_valid?: boolean; records_checked?: number; error?: string };

export type PilotState = {
  api: string;
  health?: PilotHealth;
  policy?: PilotPolicy;
  metrics?: PilotMetrics;
  chain?: PilotChain;
};

export type Scenario = {
  label: string;
  expect: string;
  payload: Record<string, unknown>;
};

export type GovernedCallResult = {
  status: number;
  role: string;
  path: string;
  body: { decision?: string } & Record<string, unknown>;
};

export type EvidenceRunSummary = {
  cases_total?: number;
  cases_passed?: number;
  cases_failed?: number;
  confirmed_side_effects?: number;
};

export type EvidenceRunAudit = {
  tenant_chain_valid?: boolean;
  tenant_chain_records_checked?: number;
  execution_chain_valid?: boolean;
  execution_chain_records_checked?: number;
};

export type EvidenceRunRow = {
  run_id: string;
  started_at?: string;
  finished_at?: string;
  exit_code?: number;
  suite_id?: string;
  summary?: EvidenceRunSummary;
  audit?: EvidenceRunAudit;
  error?: string;
};

export type EvidenceRuns = { evidence_root: string; runs: EvidenceRunRow[] };

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const pilotApi = {
  state: () => getJson<PilotState>("/api/state"),
  scenarios: () => getJson<Scenario[]>("/api/scenarios"),

  async governedCall(
    role: PilotRole,
    payload: Record<string, unknown>,
  ): Promise<GovernedCallResult> {
    const res = await fetch("/api/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, path: "/v1/execution/assess", payload }),
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return (await res.json()) as GovernedCallResult;
  },

  // Verbatim on purpose: a console that summarised the battery output could
  // hide a failing case. The text is shown exactly as the runner printed it.
  async runBattery(): Promise<string> {
    const res = await fetch("/api/battery", { method: "POST" });
    return await res.text();
  },

  envelope: (requestId: string) =>
    getJson<Record<string, unknown>>(`/api/envelope/${encodeURIComponent(requestId)}`),

  evidenceRuns: () => getJson<EvidenceRuns>("/api/evidence/runs"),
  evidenceManifest: (runId: string) =>
    getJson<Record<string, unknown>>(`/api/evidence/runs/${encodeURIComponent(runId)}`),
  evidenceArchiveUrl: (runId: string) => `/api/evidence/runs/${encodeURIComponent(runId)}/archive`,
};
