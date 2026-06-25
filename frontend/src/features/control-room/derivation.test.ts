import { describe, it, expect } from "vitest";
import {
  deriveAsset,
  deriveWhyEscalated,
  deriveRiskMatrix,
  deriveEvidence,
  deriveTimeline,
  deriveHistory,
  derivePolicyLearning,
  deriveFollowUpDefaults,
  deriveFieldResponse,
  deriveReviewerContext,
  deriveFollowUpBlock,
  deriveHistoryBlock,
  derivePolicyLearningBlock,
  requestTypeLabel,
} from "./derivation";
import type { EscalationItem } from "./types";
import type { DecisionTrace } from "@/lib/remora-sim";

function makeMockTrace(overrides: Partial<DecisionTrace> = {}): DecisionTrace {
  return {
    request_id: "req-abc-1234-5678-9def",
    ts: new Date().toISOString(),
    query: "test query",
    verdict: "ESCALATE",
    reason: "Oracle disagreement too high",
    intent: {
      domain: "well_engineering",
      risk: "critical",
      sensitivity: "restricted",
    } as DecisionTrace["intent"],
    oracles: [],
    thermo: {
      T: 0.82,
      H: 0.45,
      D: 0.38,
      F: 0.12,
      trust: 0.42,
      phase: "disordered",
    },
    policy: {
      version: "v1",
      triggers: [{ rule: "SAFETY-01", effect: "block_action", reason: "Test" }],
      permitted: ["ESCALATE"],
    },
    evidence: [],
    steps: [],
    total_latency_ms: 180,
    approval_required: true,
    ...overrides,
  };
}

function makeMockItem(overrides: Partial<EscalationItem> = {}): EscalationItem {
  return {
    id: 1,
    title: "Test escalation",
    sector: "Well Engineering",
    icon: "🛢",
    proposed_action: "Test proposed action for well engineering scenario",
    reason: "Test reason",
    risk: "critical",
    trust: 0.42,
    phase: "disordered",
    ts: "14:22",
    trace: makeMockTrace(),
    status: "pending",
    ...overrides,
  };
}

describe("deriveAsset", () => {
  it("generates an asset with expected fields", () => {
    const item = makeMockItem();
    const asset = deriveAsset(item);
    expect(asset.id).toMatch(/^WH-\d{2}$/);
    expect(asset.type).toBe("Wellhead Assembly");
    expect(asset.zone).toBe("Wellbay / Level 2");
    expect(asset.system).toBe("Well Control System (WCS)");
    expect(asset.criticality).toBe("SIL-3 / Class A");
    expect(asset.cmmsRef).toMatch(/^SAP-PM-2024-/);
  });

  it("maps domains to correct asset types", () => {
    const process = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "process_safety",
          risk: "high",
          sensitivity: "internal",
        } as DecisionTrace["intent"],
      }),
    });
    expect(deriveAsset(process).type).toBe("Emergency Shutdown Valve");

    const maint = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "maintenance_planning",
          risk: "medium",
          sensitivity: "public",
        } as DecisionTrace["intent"],
      }),
    });
    expect(deriveAsset(maint).type).toBe("Rotating Equipment");
  });
});

describe("deriveWhyEscalated", () => {
  it("includes risk tier when critical", () => {
    const item = makeMockItem({ risk: "critical" });
    const reasons = deriveWhyEscalated(item.trace, item);
    expect(reasons.some((r) => r.includes("CRITICAL"))).toBe(true);
  });

  it("includes trust score when below 50%", () => {
    const item = makeMockItem({ trust: 0.42 });
    const reasons = deriveWhyEscalated(item.trace, item);
    expect(reasons.some((r) => r.includes("Trust score"))).toBe(true);
  });

  it("limits to max 5 reasons", () => {
    const trace = makeMockTrace({
      thermo: { T: 0.9, H: 0.8, D: 0.7, F: 0.1, trust: 0.3, phase: "disordered" },
      policy: {
        version: "v1",
        triggers: [
          { rule: "R1", effect: "block_action", reason: "" },
          { rule: "R2", effect: "block_action", reason: "" },
        ],
        permitted: ["ESCALATE"],
      },
    });
    const item = makeMockItem({ trace });
    const reasons = deriveWhyEscalated(trace, item);
    expect(reasons.length).toBeLessThanOrEqual(5);
  });
});

describe("deriveRiskMatrix", () => {
  it("raises safety to critical for process_safety", () => {
    const item = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "process_safety",
          risk: "high",
          sensitivity: "restricted",
        } as DecisionTrace["intent"],
      }),
    });
    const matrix = deriveRiskMatrix(item);
    const safety = matrix.find((m) => m.label === "Safety");
    expect(safety?.level).toBe("critical");
  });

  it("uses item risk for operational dimension", () => {
    const item = makeMockItem({ risk: "medium" });
    const matrix = deriveRiskMatrix(item);
    const op = matrix.find((m) => m.label === "Operational");
    expect(op?.level).toBe("medium");
  });
});

describe("deriveEvidence", () => {
  it("returns found + missing evidence items", () => {
    const trace = makeMockTrace({
      evidence: [
        { source: "NORSOK", section: "D-010", snippet: "barrier", score: 0.95, fresh_days: 2 },
      ],
    });
    const ev = deriveEvidence(trace, "well_engineering");
    expect(ev.some((e) => e.found)).toBe(true);
    expect(ev.some((e) => !e.found)).toBe(true);
  });

  it("returns at least 2 items even with empty evidence", () => {
    const trace = makeMockTrace({ evidence: [] });
    const ev = deriveEvidence(trace, "general");
    expect(ev.length).toBeGreaterThanOrEqual(2);
  });
});

describe("deriveTimeline", () => {
  it("produces 5 timeline entries", () => {
    const item = makeMockItem();
    const asset = deriveAsset(item);
    const tl = deriveTimeline(item, asset);
    expect(tl.length).toBe(5);
    expect(tl[tl.length - 1].type).toBe("block");
  });
});

describe("deriveHistory", () => {
  it("returns deterministic case counts", () => {
    const item = makeMockItem();
    const h = deriveHistory(item);
    expect(h.count).toBeGreaterThanOrEqual(5);
    expect(h.count).toBeLessThanOrEqual(10);
    expect(h.approved + h.rejected + h.follow_up).toBe(h.count);
    expect(h.cases.length).toBe(Math.min(h.count, 5));
  });
});

describe("derivePolicyLearning", () => {
  it("marks candidate when rejection+follow-up rate >= 60%", () => {
    const item = makeMockItem();
    const history = deriveHistory(item);
    const pl = derivePolicyLearning(item, history);
    expect(typeof pl.candidate).toBe("boolean");
    expect(pl.confidence).toBeGreaterThanOrEqual(0);
    expect(pl.confidence).toBeLessThanOrEqual(1);
    expect(pl.recommendation.length).toBeGreaterThan(10);
  });
});

describe("deriveFollowUpDefaults", () => {
  it("sets correct evidence list per domain", () => {
    const well = makeMockItem();
    const form = deriveFollowUpDefaults(well);
    expect(form.evidence).toContain("Updated ECD calculation");
    expect(form.priority).toBe("Critical");
    expect(form.assignTo).toBe("Independent Well Engineer");
  });

  it("selects request type based on domain", () => {
    const maint = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "maintenance_planning",
          risk: "medium",
          sensitivity: "public",
        } as DecisionTrace["intent"],
      }),
    });
    const form = deriveFollowUpDefaults(maint);
    expect(form.requestType).toBe("photo_evidence");
  });
});

describe("deriveFieldResponse", () => {
  it("returns technician mapped by domain", () => {
    const well = makeMockItem();
    const resp = deriveFieldResponse(well);
    expect(resp.technician).toContain("Kjetil Andersen");
  });

  it("sets rerunReady for environmental_compliance", () => {
    const env = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "environmental_compliance",
          risk: "low",
          sensitivity: "public",
        } as DecisionTrace["intent"],
      }),
    });
    const resp = deriveFieldResponse(env);
    expect(resp.rerunReady).toBe(true);
    expect(resp.inspectionCompleted).toBe(true);
  });
});

describe("deriveReviewerContext", () => {
  it("generates well_engineering reviewer context with asset and missing data", () => {
    const item = makeMockItem();
    const asset = deriveAsset(item);
    const rc = deriveReviewerContext(item, asset);
    expect(rc.asset.field).toBe("Ivar Aasen");
    expect(rc.asset.asset_id).toMatch(/^WH-\d{2}$/);
    expect(rc.decision_question).toContain("kill mud weight");
    expect(rc.critical_missing_data).toContain("Updated pore pressure window");
    expect(rc.critical_missing_data).toContain("Independent well engineer sign-off");
  });

  it("maps process_safety to correct context", () => {
    const item = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "process_safety",
          risk: "high",
          sensitivity: "restricted",
        } as DecisionTrace["intent"],
      }),
    });
    const rc = deriveReviewerContext(item, deriveAsset(item));
    expect(rc.decision_question).toContain("safety barrier");
    expect(rc.critical_missing_data).toContain("SIL verification report");
  });
});

describe("deriveFollowUpBlock", () => {
  it("returns required=true for ESCALATE verdict", () => {
    const item = makeMockItem();
    const fb = deriveFollowUpBlock(item);
    expect(fb.required).toBe(true);
    expect(fb.type).toBe("independent_well_engineering_review");
    expect(fb.priority).toBe("critical");
    expect(fb.sla_hours).toBe(4);
  });

  it("returns required=false for ACCEPT verdict", () => {
    const item = makeMockItem({
      trace: makeMockTrace({ verdict: "ACCEPT" }),
    });
    const fb = deriveFollowUpBlock(item);
    expect(fb.required).toBe(false);
  });

  it("maps assign_to_role by domain", () => {
    const maint = makeMockItem({
      trace: makeMockTrace({
        intent: {
          domain: "maintenance_planning",
          risk: "medium",
          sensitivity: "internal",
        } as DecisionTrace["intent"],
      }),
    });
    const fb = deriveFollowUpBlock(maint);
    expect(fb.assign_to_role).toBe("site_technician");
    expect(fb.sla_hours).toBe(72);
  });
});

describe("deriveHistoryBlock", () => {
  it("transforms CaseHistory into HistoryBlock format", () => {
    const item = makeMockItem();
    const h = deriveHistory(item);
    const hb = deriveHistoryBlock(h);
    expect(hb.similar_cases_found).toBe(h.count);
    expect(hb.decision_pattern.approved).toBe(h.approved);
    expect(hb.decision_pattern.rejected).toBe(h.rejected);
    expect(hb.similar_cases.length).toBeGreaterThan(0);
  });

  it("includes known_blockers from history", () => {
    const item = makeMockItem();
    const h = deriveHistory(item);
    const hb = deriveHistoryBlock(h);
    expect(hb.known_blockers.length).toBeGreaterThan(0);
    expect(hb.known_blockers[0]).toContain("Missing");
  });
});

describe("derivePolicyLearningBlock", () => {
  it("proposes L2 autonomy for well_engineering with high rejection rate", () => {
    const item = makeMockItem();
    const h = deriveHistory(item);
    const pl = derivePolicyLearning(item, h);
    const plb = derivePolicyLearningBlock(item, h, pl);
    expect(plb.candidate_rule_update).toBe(true);
    expect(plb.proposed_autonomy_level).toBe("L2_REQUEST_EVIDENCE_AUTOMATICALLY");
    expect(plb.autonomy_allowed).toBe(false);
    expect(plb.requires_policy_owner_approval).toBe(true);
  });

  it("links supporting_cases to history cases", () => {
    const item = makeMockItem();
    const h = deriveHistory(item);
    const pl = derivePolicyLearning(item, h);
    const plb = derivePolicyLearningBlock(item, h, pl);
    expect(plb.supporting_cases.length).toBeGreaterThan(0);
    expect(plb.supporting_cases[0]).toMatch(/^case_2026_/);
  });
});

describe("requestTypeLabel", () => {
  it("maps known request types", () => {
    expect(requestTypeLabel("photo_evidence")).toBe("Photo evidence");
    expect(requestTypeLabel("on_site_inspection")).toBe("On-site inspection");
  });

  it("falls back to humanized value for unknown types", () => {
    expect(requestTypeLabel("unknown_type")).toBe("unknown type");
  });
});
