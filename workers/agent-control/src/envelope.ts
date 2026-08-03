/**
 * DecisionEnvelope v2 persistence for the agent-control Worker.
 *
 * Why this exists
 * ───────────────
 * The Worker used to record only `audit_log` rows: tool name, input/output
 * hash, verdict. That is a call log, not a governance record — it carries no
 * decision contract, no predecessor linkage, and nothing a reviewer can
 * recompute. A deleted row left no trace.
 *
 * This module writes the canonical `DecisionEnvelope` (schema_version "2",
 * the same contract as `remora/governance/envelope.py`) into a hash-chained
 * D1 table, so the live path produces a trail that can be re-verified after
 * the fact, by someone who was not present when it ran.
 *
 * Hash contract
 * ─────────────
 * Identical to `remora.governance.tenant_chain.compute_entry_hash` (REM-034):
 *
 *   entry_hash = SHA256( previous_hash ␟ canonical(payload) ␟ tenant_id
 *                        ␟ sequence_no ␟ timestamp )
 *
 * where ␟ is ASCII unit separator (0x1f) and `canonical` is JSON with sorted
 * keys, no whitespace, and non-ASCII escaped — matching Python's
 * `json.dumps(sort_keys=True, separators=(",", ":"))`.
 *
 * The exact canonical string that was hashed is stored verbatim in
 * `envelope_canonical`. Verifiers hash the stored bytes rather than
 * re-serialising the parsed object, so no cross-language serialisation
 * difference (notably JS collapsing `1.0` to `1`) can ever turn an intact
 * chain into a reported break.
 *
 * Scope — do not overclaim
 * ────────────────────────
 * `gate.outcome` here records what THIS control plane did: whether it
 * required human approval and whether the call executed. It is NOT a REMORA
 * policy-engine verdict; `audit.policy_version` says so explicitly. Wiring
 * the full decision engine in front of tool dispatch is REM-024/REM-030.
 */

const GENESIS = "0".repeat(64);
const US = "\u001f"; // ASCII unit separator: injective field delimiter

// ── Canonical JSON ─────────────────────────────────────────────────────────────

/**
 * Escape non-ASCII so the output matches Python's default `ensure_ascii=True`.
 * JS emits raw UTF-8 for e.g. "æ"; Python emits "æ". Norwegian text is
 * routine here, so this is not a corner case.
 */
function escapeNonAscii(s: string): string {
  let out = "";
  for (const unit of s) {
    const code = unit.codePointAt(0)!;
    if (code > 0x7f) {
      // Iterate UTF-16 code units so surrogate pairs emit two escapes,
      // exactly as Python does.
      for (let i = 0; i < unit.length; i++) {
        out += "\\u" + unit.charCodeAt(i).toString(16).padStart(4, "0");
      }
    } else {
      out += unit;
    }
  }
  return out;
}

/**
 * Deterministic JSON with recursively sorted keys and no whitespace.
 *
 * Known limitation: JavaScript cannot distinguish the float 1.0 from the
 * integer 1, so a payload containing an integral float serialises as `1`
 * here and `1.0` in Python. That affects only cross-language recomputation
 * of `tool_args_hash` from re-parsed input, and it fails closed (a mismatch
 * refuses the call). Chain verification is unaffected because verifiers hash
 * the stored canonical string, not a re-serialisation.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number") {
    return Number.isFinite(value) ? JSON.stringify(value) : "null";
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return escapeNonAscii(JSON.stringify(value));
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return (
      "{" +
      entries
        .map(([k, v]) => escapeNonAscii(JSON.stringify(k)) + ":" + canonicalJson(v))
        .join(",") +
      "}"
    );
  }
  return escapeNonAscii(JSON.stringify(String(value)));
}

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacSha256Hex(key: string, message: string): Promise<string> {
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** SHA-256 binding a tool call to its exact, full arguments (REM-034 / CLAIM 6). */
export async function canonicalToolCallHash(
  name: string,
  args: unknown,
  tenant: string,
  target: string,
): Promise<string> {
  return sha256Hex(
    canonicalJson({ name, arguments: args, tenant: tenant || "", target: target || "" }),
  );
}

export async function computeEntryHash(
  previousHash: string,
  canonicalPayload: string,
  tenantId: string,
  sequenceNo: number,
  timestamp: string,
): Promise<string> {
  return sha256Hex(
    [previousHash, canonicalPayload, tenantId, String(sequenceNo), timestamp].join(US),
  );
}

// ── Envelope construction ──────────────────────────────────────────────────────

export interface EnvelopeInput {
  requestId: string;
  tenantId: string;
  sessionId: string;
  actorIdentity: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  toolArgsHash: string;
  riskTier: string;
  domain: string;
  targetEnvironment: string;
  outcome: "accept" | "escalate" | "abstain";
  policyTriggers: string[];
  approvalRequired: boolean;
  executed: boolean;
  effectOutcome: string;
  verdict?: string;
  confidence?: number;
  auditId?: number | null;
  timestampUtc: string;
}

/** Build a DecisionEnvelope v2 payload — same block layout as the Python contract. */
export function buildEnvelope(input: EnvelopeInput): Record<string, unknown> {
  return {
    request: {
      request_id: input.requestId,
      domain: input.domain,
      risk_tier: input.riskTier,
      proposed_action: `${input.toolName}(${Object.keys(input.toolArgs).sort().join(",")})`,
      action_type: input.toolName,
      target_environment: input.targetEnvironment,
    },
    assessment: {
      // The control plane runs no oracle consensus of its own; upstream
      // verdicts arrive as a single reported vote, and the empty
      // thermodynamic block says plainly that no phase state was measured.
      oracle_votes:
        input.verdict === undefined
          ? []
          : [{ source: "upstream", verdict: input.verdict, confidence: input.confidence ?? null }],
      thermodynamic: {},
      evidence_quality: {
        verdict: input.verdict ?? null,
        confidence: input.confidence ?? null,
        signal_source: "upstream_worker",
      },
      policy_triggers: [...input.policyTriggers].sort(),
    },
    gate: {
      outcome: input.outcome,
      blocked_action: input.outcome === "accept" ? null : input.toolName,
      allowed_next_steps: input.approvalRequired ? ["human_review"] : [],
    },
    reviewer_context: {
      asset: {
        session_id: input.sessionId,
        risk_tier: input.riskTier,
        target_environment: input.targetEnvironment,
      },
      missing_critical_data: [],
    },
    follow_up: {
      required: input.approvalRequired && !input.executed,
      type: input.approvalRequired && !input.executed ? "human_review" : null,
      requested_evidence: [],
      sla_hours: null,
    },
    history: {
      similar_cases_found: 0,
      decision_pattern: {},
      known_blockers: [],
      synthetic: false,
    },
    policy_learning: {
      candidate_rule_update: false,
      requires_policy_owner_approval: true,
    },
    audit: {
      // Names the gate that actually produced this outcome. This is the
      // control plane's approval gate, NOT the REMORA policy engine.
      policy_version: "agent-control-gate/v1",
      hash: null,
      previous_hash: null,
      signature: null,
      schema_version: "2",
      timestamp_utc: input.timestampUtc,
      tenant_id: input.tenantId,
      actor_identity: input.actorIdentity,
      policy_bundle_hash: null,
      tool_args_hash: input.toolArgsHash,
      data_classification: null,
      retention_policy: null,
    },
    effect: {
      executed: input.executed,
      tool_call_hash: input.toolArgsHash,
      effect_outcome: input.effectOutcome,
      ledger_entry: input.auditId ? { audit_log_id: input.auditId } : {},
    },
  };
}

// ── Chained append ─────────────────────────────────────────────────────────────

export interface AppendResult {
  requestId: string;
  sequenceNo: number;
  previousHash: string;
  entryHash: string;
  signature: string;
  timestamp: string;
}

/**
 * Append an envelope to the tenant's chain, atomically.
 *
 * D1 has no `SELECT ... FOR UPDATE`, so fork-freedom comes from two
 * cooperating mechanisms:
 *
 *   1. `UNIQUE (tenant_id, sequence_no)` on `decision_envelopes` — the real
 *      guard. Two writers that read the same head compute the same sequence
 *      number; the second INSERT violates the constraint and its whole batch
 *      rolls back. A fork cannot be committed.
 *   2. A compare-and-set on `envelope_chain_head`, batched with the INSERT so
 *      both apply or neither does, keeping the head cursor consistent.
 *
 * The loser retries against the new head. On exhausting retries this throws:
 * the caller must treat a failed envelope write as a failed governance
 * record, never as a silent success.
 */
export async function appendEnvelope(
  db: D1Database,
  opts: {
    tenantId: string;
    sessionId: string;
    requestId: string;
    envelope: Record<string, unknown>;
    auditId: number | null;
    signingKey?: string;
    maxRetries?: number;
  },
): Promise<AppendResult> {
  const maxRetries = opts.maxRetries ?? 5;
  let lastError: unknown = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const head = await db
      .prepare("SELECT head_hash, head_sequence FROM envelope_chain_head WHERE tenant_id = ?")
      .bind(opts.tenantId)
      .first<{ head_hash: string; head_sequence: number }>();

    const previousHash = head?.head_hash ?? GENESIS;
    const sequenceNo = head ? head.head_sequence + 1 : 0;
    const timestamp = new Date().toISOString();

    // Stamp the chain fields into the envelope BEFORE canonicalising, so the
    // hash covers the linkage it claims. `hash` stays null in the preimage —
    // a value cannot commit to itself.
    const audit = { ...(opts.envelope.audit as Record<string, unknown>) };
    audit.previous_hash = previousHash;
    audit.hash = null;
    const payload = { ...opts.envelope, audit };
    const canonicalPayload = canonicalJson(payload);

    const entryHash = await computeEntryHash(
      previousHash,
      canonicalPayload,
      opts.tenantId,
      sequenceNo,
      timestamp,
    );
    const signature = opts.signingKey ? await hmacSha256Hex(opts.signingKey, entryHash) : "";

    const statements = head
      ? [
          db
            .prepare(
              "UPDATE envelope_chain_head SET head_hash = ?, head_sequence = ? " +
                "WHERE tenant_id = ? AND head_sequence = ?",
            )
            .bind(entryHash, sequenceNo, opts.tenantId, head.head_sequence),
        ]
      : [
          db
            .prepare("INSERT INTO envelope_chain_head (tenant_id, head_hash, head_sequence) VALUES (?,?,?)")
            .bind(opts.tenantId, entryHash, sequenceNo),
        ];

    statements.push(
      db
        .prepare(
          `INSERT INTO decision_envelopes
             (request_id, tenant_id, session_id, sequence_no, created_at,
              envelope_canonical, previous_hash, entry_hash, signature, audit_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)`,
        )
        .bind(
          opts.requestId,
          opts.tenantId,
          opts.sessionId,
          sequenceNo,
          timestamp,
          canonicalPayload,
          previousHash,
          entryHash,
          signature,
          opts.auditId,
        ),
    );

    try {
      await db.batch(statements);
      return { requestId: opts.requestId, sequenceNo, previousHash, entryHash, signature, timestamp };
    } catch (e) {
      // Lost the race (UNIQUE violation or stale CAS): re-read and retry.
      lastError = e;
    }
  }

  throw new Error(
    `envelope chain append failed after ${maxRetries} attempts: ` +
      (lastError instanceof Error ? lastError.message : String(lastError)),
  );
}

// ── Verification ───────────────────────────────────────────────────────────────

export interface ChainRow {
  sequence_no: number;
  created_at: string;
  envelope_canonical: string;
  previous_hash: string;
  entry_hash: string;
  signature: string;
}

export interface VerifyResult {
  chain_valid: boolean;
  records_checked: number;
  breaks: string[];
  signatures_checked: boolean;
}

/**
 * Recompute a tenant's chain from stored rows.
 *
 * Reports every break rather than stopping at the first, so an operator sees
 * the full extent of the damage. Rows must be supplied in ascending
 * sequence order.
 */
export async function verifyChain(
  rows: ChainRow[],
  signingKey?: string,
): Promise<VerifyResult> {
  const breaks: string[] = [];
  let expectedPrevious = GENESIS;
  let expectedSequence = 0;

  for (const row of rows) {
    const label = `seq ${row.sequence_no}`;

    if (row.sequence_no !== expectedSequence) {
      breaks.push(`${label}: expected sequence ${expectedSequence} — an entry is missing or reordered`);
    }
    if (row.previous_hash !== expectedPrevious) {
      breaks.push(`${label}: previous_hash ${row.previous_hash} does not link to ${expectedPrevious}`);
    }

    const recomputed = await computeEntryHash(
      row.previous_hash,
      row.envelope_canonical,
      // tenant_id is inside the canonical payload's audit block; the chain
      // hash also binds it separately, recovered here from that payload.
      (JSON.parse(row.envelope_canonical)?.audit?.tenant_id as string) ?? "",
      row.sequence_no,
      row.created_at,
    );
    if (recomputed !== row.entry_hash) {
      breaks.push(`${label}: entry_hash does not match the stored payload — the record was modified`);
    }

    if (signingKey) {
      const expectedSig = await hmacSha256Hex(signingKey, row.entry_hash);
      if (row.signature !== expectedSig) {
        breaks.push(
          `${label}: signature invalid or stripped` +
            (row.signature ? "" : " (empty — written before signing was enabled, or removed)"),
        );
      }
    }

    expectedPrevious = row.entry_hash;
    expectedSequence = row.sequence_no + 1;
  }

  return {
    chain_valid: breaks.length === 0,
    records_checked: rows.length,
    breaks,
    signatures_checked: Boolean(signingKey),
  };
}
