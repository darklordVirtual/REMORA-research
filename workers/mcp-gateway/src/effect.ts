/**
 * Effect verification for graph writes.
 *
 * Dispatching a call and the effect happening are different facts. The
 * dispatcher returning cleanly says the request was accepted, not that the
 * row is there — and treating the first as evidence of the second is the
 * distinction REMORA exists to keep.
 *
 * So after a write executes, the fact is read back from the system of record
 * and compared against the call a person approved. The tool's own result only
 * locates the row (the id it minted); it never supplies the expected values.
 * Comparing the row with what the tool said it wrote checks the tool against
 * itself, and a tool that wrote something else and reported it faithfully
 * came out VERIFIED (RMR-AUD-004, observation_from_the_tool).
 *
 * The result is submitted to REMORA as an attestation by a named verifier,
 * bound to the dispatch it describes. REMORA adjudicates the binding and
 * records it; the gateway reports REMORA's verdict, and says so when the
 * receipt was not recorded rather than presenting its own reading as one.
 *
 * Only the fields the call names are compared. A field the call does not
 * name is out of scope by construction — a concurrent legitimate write
 * elsewhere in the row is not this action's problem, and reporting it would
 * train whoever reads these to dismiss the signal.
 */

/** The five outcomes, kept distinct because collapsing any pair loses
 *  something an operator needs to decide what to do next. */
export type EffectStatus =
  | "EFFECT_VERIFIED"
  | "EFFECT_MISMATCH"
  | "EFFECT_UNOBSERVABLE"
  | "EFFECT_VERIFIER_FAILED"
  | "EFFECT_UNSUPPORTED";

const EFFECT_STATUSES: readonly string[] = [
  "EFFECT_VERIFIED", "EFFECT_MISMATCH", "EFFECT_UNOBSERVABLE",
  "EFFECT_VERIFIER_FAILED", "EFFECT_UNSUPPORTED",
];

export interface Verification {
  status: EffectStatus;
  reason_code: string;
  expected_sha256: string;
  observed_sha256: string;
  detail: string;
}

/**
 * Canonical JSON, matching remora.governance.effect_verification.effect_digest.
 *
 * Sorted keys and no whitespace, so two callers that agree on the value agree
 * on the digest. This is reimplemented rather than shared because the writer
 * and the verifier are in different languages; a test pins it against the
 * Python output so the two cannot drift apart silently.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return "{" + keys.map((k) =>
    JSON.stringify(k) + ":" + canonicalJson(obj[k])).join(",") + "}";
}

export async function effectDigest(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)]
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Fields of an asserted fact that a read-back must reproduce. */
const ASSERT_FIELDS = ["graph", "subject", "predicate", "object", "object_kind",
                       "source", "confidence"] as const;

/** Seconds a row's created_at may trail the gateway's dispatch clock. The
 *  row is stamped by the container's clock, not this one. */
const CLOCK_SKEW_SECONDS = 5;

/** What the approved call asked kg_assert_fact to write, with the tool's own
 *  defaults applied (deploy/gateway/kg_registry.py). */
function expectedAssert(args: Record<string, unknown>): Record<string, unknown> {
  return {
    graph: String(args.graph ?? ""),
    subject: String(args.subject ?? ""),
    predicate: String(args.predicate ?? ""),
    object: args.object ?? null,
    object_kind: String(args.object_kind ?? "literal").toLowerCase(),
    source: String(args.source ?? ""),
    confidence: Number(args.confidence ?? 1),
  };
}

/** The same fields as they landed. object_json is decoded, so the comparison
 *  is between values and not between two JSON writers' spacing. */
function observedAssert(row: Record<string, unknown>): Record<string, unknown> {
  let object: unknown;
  try {
    object = JSON.parse(String(row.object_json));
  } catch {
    object = { unparseable_object_json: String(row.object_json ?? "") };
  }
  return {
    graph: row.graph ?? null,
    subject: row.subject ?? null,
    predicate: row.predicate ?? null,
    object,
    object_kind: row.object_kind ?? null,
    source: row.source ?? null,
    confidence: row.confidence === null || row.confidence === undefined
      ? null : Number(row.confidence),
  };
}

export interface VerifyOptions {
  /** Unix seconds when the gateway asked REMORA to dispatch. A row created
   *  before then was not produced by this call. */
  dispatchedAt?: number;
}

/**
 * Verify one graph write against what actually landed.
 *
 * `approvedArgs` are the arguments a person approved (or the ACCEPT token was
 * bound to). `toolResult` is what the tool returned; it is read only for the
 * id of the row it created. `read` returns the row, or null when the reader
 * could not see it. Null is UNOBSERVABLE, never MISMATCH: not knowing is a
 * different fact from knowing it is wrong, and only one of them justifies
 * compensating.
 */
export async function verifyGraphWrite(
  tool: string,
  approvedArgs: Record<string, unknown>,
  toolResult: Record<string, unknown>,
  read: (id: string) => Promise<Record<string, unknown> | null>,
  opts: VerifyOptions = {},
): Promise<Verification> {
  if (tool === "kg_retract_fact") {
    // The declared effect is absence of the fact the approval named. The id
    // the tool reports is not consulted: it could name a different fact.
    const target = String(approvedArgs.id ?? "");
    if (!target) {
      return { status: "EFFECT_UNSUPPORTED", reason_code: "no_target_in_call",
               expected_sha256: "", observed_sha256: "", detail: "" };
    }
    let row: Record<string, unknown> | null;
    try {
      row = await read(target);
    } catch (e) {
      return { status: "EFFECT_VERIFIER_FAILED", reason_code: "reader_error",
               expected_sha256: "", observed_sha256: "",
               detail: String(e instanceof Error ? e.message : e).slice(0, 200) };
    }
    const expected = await effectDigest({ present: false });
    const observed = await effectDigest({ present: row !== null });
    return row === null
      ? { status: "EFFECT_VERIFIED", reason_code: "fact_absent",
          expected_sha256: expected, observed_sha256: observed, detail: "" }
      : { status: "EFFECT_MISMATCH", reason_code: "fact_still_present",
          expected_sha256: expected, observed_sha256: observed,
          detail: `fact ${target} is still readable` };
  }

  if (tool !== "kg_assert_fact") {
    // Reads change nothing, so there is no postcondition to check. Saying so
    // is better than reporting a vacuous success.
    return { status: "EFFECT_UNSUPPORTED", reason_code: "no_postcondition",
             expected_sha256: "", observed_sha256: "", detail: "" };
  }

  const id = String(toolResult.id ?? "");
  if (!id) {
    return { status: "EFFECT_UNSUPPORTED", reason_code: "no_id_in_result",
             expected_sha256: "", observed_sha256: "", detail: "" };
  }

  let row: Record<string, unknown> | null;
  try {
    row = await read(id);
  } catch (e) {
    return { status: "EFFECT_VERIFIER_FAILED", reason_code: "reader_error",
             expected_sha256: "", observed_sha256: "",
             detail: String(e instanceof Error ? e.message : e).slice(0, 200) };
  }

  const expectedValue = expectedAssert(approvedArgs);
  const expected = await effectDigest(expectedValue);

  if (row === null) {
    return { status: "EFFECT_UNOBSERVABLE", reason_code: "fact_not_readable",
             expected_sha256: expected, observed_sha256: "",
             detail: `fact ${id} could not be read back` };
  }

  const observedValue = observedAssert(row);
  const observed = await effectDigest(observedValue);

  // A matching row that existed before the dispatch shows the state, not
  // that this call produced it. Checked only when both times are known.
  const createdAt = row.created_at;
  if (opts.dispatchedAt !== undefined && typeof createdAt === "number"
      && createdAt < opts.dispatchedAt - CLOCK_SKEW_SECONDS) {
    return { status: "EFFECT_MISMATCH", reason_code: "fact_predates_dispatch",
             expected_sha256: expected, observed_sha256: observed,
             detail: `fact ${id} was created at ${createdAt}, before the ` +
                     `dispatch at ${opts.dispatchedAt}` };
  }

  if (expected === observed) {
    return { status: "EFFECT_VERIFIED", reason_code: "delta_matches",
             expected_sha256: expected, observed_sha256: observed, detail: "" };
  }
  const differing = ASSERT_FIELDS.filter(
    (f) => canonicalJson(expectedValue[f]) !== canonicalJson(observedValue[f]));
  return { status: "EFFECT_MISMATCH", reason_code: "delta_differs",
           expected_sha256: expected, observed_sha256: observed,
           detail: `differing: ${differing.join(", ")}` };
}

// ── the receipt REMORA records ─────────────────────────────────────────────

/** The dispatch a receipt is about, as REMORA reported it at assess and
 *  execute time. Every field is read from REMORA's own responses. */
export interface EffectBinding {
  proposal_id: string;
  tool_call_hash: string;
  grant_jti: string;
  execution_id: string;
  execution_context_hash: string;
}

/** Who looked. The identity must be bound to the verifier credential on the
 *  server (REMORA_EFFECT_VERIFIER_BINDINGS); it is not the agent's. */
export interface VerifierConfig {
  identity: string;
  version: string;
}

/** The body of POST /v1/execution/proposals/{id}/effect
 *  (servers/execution_contracts.py EffectVerificationRequest). */
export interface EffectReceipt {
  execution_id: string;
  execution_context_hash?: string;
  tool_id: string;
  tool_call_hash: string;
  grant_jti: string;
  status: EffectStatus;
  reason_code: string;
  verifier_identity: string;
  verifier_version: string;
  expected_sha256: string;
  observed_sha256: string;
  verified_at: string;
  detail: string;
}

/** What happened to a receipt. `status` is REMORA's adjudicated status,
 *  present only when it recorded the receipt. */
export interface EffectRecord {
  recorded: boolean;
  http_status?: number;
  status?: EffectStatus;
  /** REMORA's account of the record: `computed` (it evaluated the
   *  observation itself), `attested` (a status that cannot raise the state) or
   *  `claimed` (a reported VERIFIED it had no signed postcondition to check;
   *  the proposal shows EFFECT_CLAIMED, never EFFECT_VERIFIED). */
  verdict_source?: string;
  reason?: string;
  detail?: string;
}

export interface EffectReport {
  /** The gateway's own read-back. Not evidence until REMORA records it. */
  observation: Verification;
  record: EffectRecord;
}

export type Poster = (path: string, body: unknown) =>
  Promise<{ status: number; body: unknown }>;

export function buildEffectReceipt(
  tool: string,
  v: Verification,
  binding: EffectBinding,
  verifier: VerifierConfig,
  verifiedAt: string,
): EffectReceipt {
  return {
    execution_id: binding.execution_id,
    ...(binding.execution_context_hash
      ? { execution_context_hash: binding.execution_context_hash }
      : {}),
    tool_id: tool,
    tool_call_hash: binding.tool_call_hash,
    grant_jti: binding.grant_jti,
    status: v.status,
    reason_code: v.reason_code,
    verifier_identity: verifier.identity,
    verifier_version: verifier.version,
    expected_sha256: v.expected_sha256,
    observed_sha256: v.observed_sha256,
    verified_at: verifiedAt,
    detail: v.detail.slice(0, 2000),
  };
}

/** Submit a receipt and report REMORA's answer, refusals included. A receipt
 *  that could not be filed is reported as not recorded; it never undoes the
 *  execution that already happened, and it is never reported as recorded. */
export async function fileEffectReceipt(
  post: Poster,
  proposalId: string,
  receipt: EffectReceipt,
): Promise<EffectRecord> {
  let res: { status: number; body: unknown };
  try {
    res = await post(
      `/v1/execution/proposals/${encodeURIComponent(proposalId)}/effect`,
      receipt);
  } catch (e) {
    return { recorded: false, reason: "transport_error",
             detail: String(e instanceof Error ? e.message : e).slice(0, 200) };
  }
  const body = (res.body ?? {}) as Record<string, unknown>;
  if (res.status === 200) {
    const status = String(body.status ?? "");
    const source = typeof body.verdict_source === "string"
      ? { verdict_source: body.verdict_source } : {};
    return EFFECT_STATUSES.includes(status)
      ? { recorded: true, http_status: 200, status: status as EffectStatus, ...source }
      : { recorded: true, http_status: 200, ...source };
  }
  const detail = body.detail;
  return {
    recorded: false,
    http_status: res.status,
    reason: (typeof detail === "string" ? detail : JSON.stringify(detail ?? body))
      .slice(0, 300),
  };
}

export interface ObserveArgs {
  tool: string;
  approvedArgs: Record<string, unknown>;
  toolResult: Record<string, unknown>;
  binding: EffectBinding;
  dispatchedAt?: number;
  read: (id: string) => Promise<Record<string, unknown> | null>;
  post: Poster;
  /** Null when no verifier credential is configured: the gateway then reads
   *  back and says so, but files nothing under the agent's identity. */
  verifier: VerifierConfig | null;
  now: () => Date;
}

/** Read the effect back, then file it as a bound receipt when that is
 *  possible, and report both. */
export async function observeAndRecord(a: ObserveArgs): Promise<EffectReport> {
  const observation = await verifyGraphWrite(
    a.tool, a.approvedArgs, a.toolResult, a.read,
    { dispatchedAt: a.dispatchedAt });
  // Taken after the read, so it is when the verifier looked.
  const verifiedAt = a.now().toISOString();
  if (observation.status === "EFFECT_UNSUPPORTED") {
    return { observation, record: { recorded: false, reason: "nothing_to_attest" } };
  }
  if (!a.verifier) {
    return { observation,
             record: { recorded: false, reason: "verifier_not_configured" } };
  }
  const b = a.binding;
  if (!b.proposal_id || !b.tool_call_hash || !b.grant_jti || !b.execution_id) {
    return { observation, record: { recorded: false, reason: "binding_incomplete" } };
  }
  const receipt = buildEffectReceipt(a.tool, observation, b, a.verifier, verifiedAt);
  return { observation, record: await fileEffectReceipt(a.post, b.proposal_id, receipt) };
}
