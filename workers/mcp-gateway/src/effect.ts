/**
 * Effect verification for graph writes.
 *
 * Dispatching a call and the effect happening are different facts. The
 * dispatcher returning cleanly says the request was accepted, not that the
 * row is there — and treating the first as evidence of the second is the
 * distinction REMORA exists to keep.
 *
 * So after a write executes, the fact is read back from the system of record
 * and compared against the delta the tool declared. The result is submitted
 * as an attestation by a named verifier; REMORA records it exactly as
 * reported, mismatches included.
 *
 * Only the declared fields are compared. A field the delta does not name is
 * out of scope by construction — a concurrent legitimate write elsewhere in
 * the row is not this action's problem, and reporting it would train whoever
 * reads these to dismiss the signal.
 */

/** The five outcomes, kept distinct because collapsing any pair loses
 *  something an operator needs to decide what to do next. */
export type EffectStatus =
  | "EFFECT_VERIFIED"
  | "EFFECT_MISMATCH"
  | "EFFECT_UNOBSERVABLE"
  | "EFFECT_VERIFIER_FAILED"
  | "EFFECT_UNSUPPORTED";

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

/** Fields of the declared delta that a read-back must reproduce. */
const ASSERT_FIELDS = ["subject", "predicate", "object_json", "object_kind",
                       "source", "confidence"] as const;

function project(row: Record<string, unknown>,
                 fields: readonly string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) out[f] = row[f] ?? null;
  return out;
}

/**
 * Verify one graph write against what actually landed.
 *
 * `read` returns the row, or null when the reader could not see it. Null is
 * UNOBSERVABLE, never MISMATCH: not knowing is a different fact from knowing
 * it is wrong, and only one of them justifies compensating.
 */
export async function verifyGraphWrite(
  tool: string,
  declared: Record<string, unknown>,
  read: (id: string) => Promise<Record<string, unknown> | null>,
): Promise<Verification> {
  const id = String(declared.id ?? "");

  if (tool === "kg_retract_fact") {
    // The declared effect is absence. Present is the mismatch here.
    const retracted = (declared.retracted ?? {}) as Record<string, unknown>;
    const target = String(retracted.id ?? "");
    if (!target) {
      return { status: "EFFECT_UNSUPPORTED", reason_code: "no_target_in_delta",
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

  if (!id) {
    return { status: "EFFECT_UNSUPPORTED", reason_code: "no_id_in_delta",
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

  const expectedValue = project(declared, ASSERT_FIELDS);
  const expected = await effectDigest(expectedValue);

  if (row === null) {
    return { status: "EFFECT_UNOBSERVABLE", reason_code: "fact_not_readable",
             expected_sha256: expected, observed_sha256: "",
             detail: `fact ${id} could not be read back` };
  }

  const observedValue = project(row, ASSERT_FIELDS);
  const observed = await effectDigest(observedValue);

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
