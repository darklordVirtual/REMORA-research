/**
 * Effect verification for graph writes.
 *
 * The distinction under test is the one the whole mechanism exists for:
 * "the dispatcher returned" and "the effect happened" are different facts.
 * Not knowing is a third fact again, and it must not be reported as a
 * mismatch — only one of the two justifies compensating.
 */
import { describe, expect, it } from "vitest";
import { canonicalJson, effectDigest, verifyGraphWrite } from "../src/effect";

const DELTA = {
  id: "fact-1",
  subject: "acme",
  predicate: "ex:hasStatus",
  object_json: '"active"',
  object_kind: "literal",
  source: "operator:stian",
  confidence: 0.9,
};

const ROW = { ...DELTA, tenant_id: "luftfiber", kg_seq: 7 };

const reads = (row: Record<string, unknown> | null) =>
  async () => row;

describe("canonical form", () => {
  it("sorts keys, matching the Python digest input", () => {
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
  });

  it("has no whitespace", () => {
    expect(canonicalJson({ a: [1, 2], b: { c: 3 } }))
      .toBe('{"a":[1,2],"b":{"c":3}}');
  });

  it("sorts nested keys too", () => {
    expect(canonicalJson({ z: { y: 1, x: 2 } })).toBe('{"z":{"x":2,"y":1}}');
  });

  it("agrees with the Python implementation, digest for digest", async () => {
    // Hardcoded from remora.governance.effect_verification.effect_digest.
    // The writer and the verifier are in different languages, so these are
    // reimplementations of each other; without a pinned value they could
    // drift apart and every verification would silently become a mismatch.
    expect(await effectDigest({ a: 1, b: "x" })).toBe(
      "ecf9e98ec0641e23113ff3ce8bdc78d0ddd249886517fd4a7f68cc83d4e65667");

    expect(await effectDigest({
      subject: "acme", predicate: "ex:hasStatus", object_json: '"active"',
      object_kind: "literal", source: "operator:stian", confidence: 0.9,
    })).toBe(
      "03d9bf9e72d12ea2bdc2a2376c448b442de0fdd31328d59506aa30068dd762ee");
  });
});

describe("an assert that landed", () => {
  it("is VERIFIED when the read-back reproduces the delta", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", DELTA, reads(ROW));
    expect(v.status).toBe("EFFECT_VERIFIED");
    expect(v.expected_sha256).toBe(v.observed_sha256);
  });

  it("ignores fields the delta does not name", async () => {
    // A concurrent legitimate write elsewhere in the row is not this
    // action's problem, and reporting it would train people to dismiss this.
    const v = await verifyGraphWrite("kg_assert_fact", DELTA,
      reads({ ...ROW, kg_seq: 999, observed_at: 123456 }));
    expect(v.status).toBe("EFFECT_VERIFIED");
  });
});

describe("an assert that did not land as declared", () => {
  it("is MISMATCH when a declared field differs", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", DELTA,
      reads({ ...ROW, object_json: '"inactive"' }));
    expect(v.status).toBe("EFFECT_MISMATCH");
    expect(v.detail).toContain("object_json");
    expect(v.expected_sha256).not.toBe(v.observed_sha256);
  });

  it("names every differing field, not just the first", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", DELTA,
      reads({ ...ROW, object_json: '"x"', source: "someone-else" }));
    expect(v.detail).toContain("object_json");
    expect(v.detail).toContain("source");
  });

  it("is MISMATCH when the source was rewritten", async () => {
    // Provenance is the point of the graph carrying a source at all.
    const v = await verifyGraphWrite("kg_assert_fact", DELTA,
      reads({ ...ROW, source: "agent" }));
    expect(v.status).toBe("EFFECT_MISMATCH");
  });
});

describe("not knowing is its own answer", () => {
  it("is UNOBSERVABLE when the fact cannot be read back", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", DELTA, reads(null));
    expect(v.status).toBe("EFFECT_UNOBSERVABLE");
    expect(v.status).not.toBe("EFFECT_MISMATCH");
  });

  it("is VERIFIER_FAILED when the reader itself broke", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", DELTA, async () => {
      throw new Error("D1 unreachable");
    });
    expect(v.status).toBe("EFFECT_VERIFIER_FAILED");
    expect(v.detail).toContain("D1 unreachable");
  });

  it("does not report a failed reader as a mismatch", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", DELTA, async () => {
      throw new Error("timeout");
    });
    expect(v.status).not.toBe("EFFECT_MISMATCH");
  });
});

describe("retraction, where the declared effect is absence", () => {
  const RETRACT = { retracted: { id: "fact-9", graph: "g" } };

  it("is VERIFIED when the fact is gone", async () => {
    const v = await verifyGraphWrite("kg_retract_fact", RETRACT, reads(null));
    expect(v.status).toBe("EFFECT_VERIFIED");
    expect(v.reason_code).toBe("fact_absent");
  });

  it("is MISMATCH when the fact is still there", async () => {
    const v = await verifyGraphWrite("kg_retract_fact", RETRACT, reads(ROW));
    expect(v.status).toBe("EFFECT_MISMATCH");
    expect(v.reason_code).toBe("fact_still_present");
  });
});

describe("what has no postcondition", () => {
  it("reports UNSUPPORTED for a read rather than a vacuous success", async () => {
    const v = await verifyGraphWrite("kg_query_facts", {}, reads(ROW));
    expect(v.status).toBe("EFFECT_UNSUPPORTED");
  });

  it("reports UNSUPPORTED when the delta carries no id", async () => {
    const v = await verifyGraphWrite("kg_assert_fact", { subject: "x" },
                                     reads(ROW));
    expect(v.status).toBe("EFFECT_UNSUPPORTED");
  });
});
