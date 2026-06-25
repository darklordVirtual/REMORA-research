import { describe, it, expect } from "vitest";
import { CR_SCENARIOS } from "../data";
import type { DecisionTrace } from "@/lib/remora-sim";
import type { CRScenario, EscalationItem, ActivityBucket } from "../types";

// ── Re-create pure helpers from useControlRoom for direct testing ──

function updateKpi(
  kpi: {
    runs: number;
    accept: number;
    verify: number;
    abstain: number;
    escalate: number;
    unsafe_prevented: number;
    audit_entries: number;
    total_ms: number;
  },
  verdict: "ACCEPT" | "VERIFY" | "ABSTAIN" | "ESCALATE",
  steps: number,
  latency: number,
) {
  return {
    runs: kpi.runs + 1,
    accept: kpi.accept + (verdict === "ACCEPT" ? 1 : 0),
    verify: kpi.verify + (verdict === "VERIFY" ? 1 : 0),
    abstain: kpi.abstain + (verdict === "ABSTAIN" ? 1 : 0),
    escalate: kpi.escalate + (verdict === "ESCALATE" ? 1 : 0),
    unsafe_prevented: kpi.unsafe_prevented + (verdict !== "ACCEPT" ? 1 : 0),
    audit_entries: kpi.audit_entries + steps,
    total_ms: kpi.total_ms + latency,
  };
}

function pushActivity(
  buckets: ActivityBucket[],
  verdict: "ACCEPT" | "VERIFY" | "ABSTAIN" | "ESCALATE",
): ActivityBucket[] {
  const bucketKey = Math.floor(Date.now() / 15000);
  const d = new Date(bucketKey * 15000);
  const label = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const isEsc = verdict === "ESCALATE";
  const last = buckets[buckets.length - 1];
  if (last && last.label === label) {
    return [
      ...buckets.slice(0, -1),
      { label, auto: last.auto + (isEsc ? 0 : 1), escalated: last.escalated + (isEsc ? 1 : 0) },
    ];
  }
  return [...buckets, { label, auto: isEsc ? 0 : 1, escalated: isEsc ? 1 : 0 }].slice(-22);
}

function makeEscalation(
  trace: DecisionTrace,
  sc: CRScenario | undefined,
  query: string,
  ts: string,
  id: number,
): EscalationItem {
  return {
    id,
    title: sc?.title ?? query.slice(0, 40) + (query.length > 40 ? "…" : ""),
    sector: sc?.sector ?? "Custom",
    icon: sc?.icon ?? "⚡",
    proposed_action: sc?.proposed_action ?? query.slice(0, 80),
    without_remora: sc?.without_remora,
    with_remora: sc?.with_remora,
    reason: trace.reason,
    risk: trace.intent.risk,
    trust: trace.thermo.trust,
    phase: trace.thermo.phase,
    ts,
    trace,
    status: "pending",
  };
}

const baseKpi = {
  runs: 0,
  accept: 0,
  verify: 0,
  abstain: 0,
  escalate: 0,
  unsafe_prevented: 0,
  audit_entries: 0,
  total_ms: 0,
};

const mockTrace = (verdict: "ACCEPT" | "VERIFY" | "ABSTAIN" | "ESCALATE"): DecisionTrace => ({
  request_id: "req-test",
  ts: new Date().toISOString(),
  query: "test",
  verdict,
  reason: "test",
  intent: { domain: "general", sensitivity: "internal", risk: "medium" },
  policy: { version: "v1", triggers: [], permitted: [verdict] },
  oracles: [],
  evidence: [],
  thermo: { T: 0.5, H: 0.3, D: 0.2, F: 0.1, trust: 0.65, phase: "ordered" },
  approval_required: verdict === "ESCALATE",
  steps: [{ id: "s1", label: "FastGate", detail: "", duration_ms: 100, status: "ok" }],
  total_latency_ms: 180,
});

// ── Tests ──

describe("updateKpi", () => {
  it("increments runs for any verdict", () => {
    const k = updateKpi(baseKpi, "ACCEPT", 1, 180);
    expect(k.runs).toBe(1);
  });

  it("increments accept only for ACCEPT", () => {
    const k = updateKpi(baseKpi, "ACCEPT", 1, 180);
    expect(k.accept).toBe(1);
    expect(k.verify).toBe(0);
    expect(k.escalate).toBe(0);
  });

  it("increments verify only for VERIFY", () => {
    const k = updateKpi(baseKpi, "VERIFY", 1, 180);
    expect(k.verify).toBe(1);
    expect(k.accept).toBe(0);
  });

  it("increments escalate only for ESCALATE", () => {
    const k = updateKpi(baseKpi, "ESCALATE", 1, 180);
    expect(k.escalate).toBe(1);
    expect(k.accept).toBe(0);
  });

  it("increments abstain only for ABSTAIN", () => {
    const k = updateKpi(baseKpi, "ABSTAIN", 1, 180);
    expect(k.abstain).toBe(1);
    expect(k.accept).toBe(0);
  });

  it("counts unsafe_prevented for non-ACCEPT verdicts", () => {
    const accept = updateKpi(baseKpi, "ACCEPT", 1, 180);
    expect(accept.unsafe_prevented).toBe(0);

    const verify = updateKpi(baseKpi, "VERIFY", 1, 180);
    expect(verify.unsafe_prevented).toBe(1);

    const escalate = updateKpi(baseKpi, "ESCALATE", 1, 180);
    expect(escalate.unsafe_prevented).toBe(1);

    const abstain = updateKpi(baseKpi, "ABSTAIN", 1, 180);
    expect(abstain.unsafe_prevented).toBe(1);
  });

  it("accumulates audit_entries and total_ms", () => {
    const k1 = updateKpi(baseKpi, "ACCEPT", 3, 200);
    expect(k1.audit_entries).toBe(3);
    expect(k1.total_ms).toBe(200);

    const k2 = updateKpi(k1, "VERIFY", 2, 150);
    expect(k2.audit_entries).toBe(5);
    expect(k2.total_ms).toBe(350);
  });
});

describe("pushActivity", () => {
  it("creates new bucket when empty", () => {
    const buckets = pushActivity([], "ACCEPT");
    expect(buckets.length).toBe(1);
    expect(buckets[0].auto).toBe(1);
    expect(buckets[0].escalated).toBe(0);
  });

  it("increments auto for ACCEPT", () => {
    const b1 = pushActivity([], "ACCEPT");
    const b2 = pushActivity(b1, "VERIFY");
    expect(b2[0].auto).toBe(2);
    expect(b2[0].escalated).toBe(0);
  });

  it("increments escalated for ESCALATE", () => {
    const b1 = pushActivity([], "ACCEPT");
    const b2 = pushActivity(b1, "ESCALATE");
    expect(b2[0].auto).toBe(1);
    expect(b2[0].escalated).toBe(1);
  });

  it("limits to 22 buckets", () => {
    let buckets: ActivityBucket[] = [];
    for (let i = 0; i < 25; i++) {
      buckets = pushActivity(buckets, "ACCEPT");
    }
    expect(buckets.length).toBeLessThanOrEqual(22);
  });
});

describe("makeEscalation", () => {
  it("uses scenario title when available", () => {
    const sc = CR_SCENARIOS[0];
    const esc = makeEscalation(mockTrace("ESCALATE"), sc, sc.query, "14:22", 1);
    expect(esc.title).toBe(sc.title);
    expect(esc.sector).toBe(sc.sector);
    expect(esc.status).toBe("pending");
  });

  it("falls back to query slice when no scenario", () => {
    const trace = mockTrace("ESCALATE");
    const esc = makeEscalation(
      trace,
      undefined,
      "This is a very long query that exceeds forty characters",
      "14:22",
      1,
    );
    expect(esc.title).toBe("This is a very long query that exceeds f…");
    expect(esc.sector).toBe("Custom");
    expect(esc.icon).toBe("⚡");
  });

  it("copies trace risk and trust", () => {
    const trace = mockTrace("ESCALATE");
    trace.intent.risk = "critical";
    trace.thermo.trust = 0.3;
    const esc = makeEscalation(trace, CR_SCENARIOS[0], "q", "14:22", 1);
    expect(esc.risk).toBe("critical");
    expect(esc.trust).toBe(0.3);
  });
});

describe("integration: verdict → kpi + activity + escalation", () => {
  it("ACCEPT produces no escalation and auto count", () => {
    const trace = mockTrace("ACCEPT");
    const kpi = updateKpi(baseKpi, trace.verdict, trace.steps.length, trace.total_latency_ms);
    const buckets = pushActivity([], trace.verdict);

    expect(kpi.accept).toBe(1);
    expect(kpi.escalate).toBe(0);
    expect(buckets[0].auto).toBe(1);
    expect(buckets[0].escalated).toBe(0);
  });

  it("ESCALATE produces escalation count and blocked", () => {
    const trace = mockTrace("ESCALATE");
    const kpi = updateKpi(baseKpi, trace.verdict, trace.steps.length, trace.total_latency_ms);
    const buckets = pushActivity([], trace.verdict);

    expect(kpi.escalate).toBe(1);
    expect(kpi.unsafe_prevented).toBe(1);
    expect(buckets[0].auto).toBe(0);
    expect(buckets[0].escalated).toBe(1);
  });
});
