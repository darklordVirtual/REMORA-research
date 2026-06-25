import type { Domain, DecisionTrace } from "@/lib/remora-sim";
import type {
  EscalationItem,
  CaseHistory,
  SimilarCase,
  FollowUpForm,
  FieldResponse,
  PolicyLearningSuggestion,
  AssetInfo,
  EvSrc,
  TL,
  RK,
} from "./types";

export function deriveReviewerContext(
  item: EscalationItem,
  asset: AssetInfo,
): import("./types").ReviewerContext {
  const d = item.trace.intent.domain;
  const fields: Partial<Record<Domain, string>> = {
    well_engineering: "Ivar Aasen",
    process_safety: "Johan Sverdrup",
    maintenance_planning: "Valhall",
    digital_twin: "Johan Sverdrup",
    environmental_compliance: "Valhall",
    reservoir_engineering: "Ivar Aasen",
    general: "Ivar Aasen",
  };
  const sections: Partial<Record<Domain, string>> = {
    well_engineering: "8.5 inch",
    process_safety: "Module A ESDV",
    maintenance_planning: "Compressor Train C",
    digital_twin: "Riser Section B",
    environmental_compliance: "Water Treatment",
    reservoir_engineering: "Well Pad 3",
    general: "Process Deck",
  };
  const ops: Partial<Record<Domain, string>> = {
    well_engineering: "drilling",
    process_safety: "barrier verification",
    maintenance_planning: "inspection",
    digital_twin: "model recalibration",
    environmental_compliance: "discharge monitoring",
    reservoir_engineering: "production optimisation",
    general: "autonomous action",
  };
  const questions: Partial<Record<Domain, string>> = {
    well_engineering:
      "Can the kill mud weight be reduced while maintaining NORSOK D-010 barrier envelope?",
    process_safety: "Can the safety barrier be bypassed during the unplanned maintenance window?",
    maintenance_planning:
      "Can this maintenance task be deferred based on the current inspection data?",
    digital_twin:
      "Can the digital twin model be auto-recalibrated when physical deviation exceeds 10%?",
    environmental_compliance: "Can overboard discharge proceed without updated lab analysis?",
    reservoir_engineering: "Can gas lift allocation be autonomously optimised across all wells?",
    general:
      "Can this autonomous action proceed with the available evidence and current trust score?",
  };
  const missingData: Partial<Record<Domain, string[]>> = {
    well_engineering: [
      "Updated pore pressure window",
      "Fracture gradient",
      "ECD calculation",
      "Kick tolerance calculation",
      "Barrier envelope confirmation",
      "Independent well engineer sign-off",
    ],
    process_safety: [
      "SIL verification report",
      "Root cause investigation",
      "OIM sign-off",
      "MOC documentation",
      "Barrier integrity confirmation",
    ],
    maintenance_planning: [
      "Latest inspection photo",
      "Criticality class confirmation",
      "Inspector sign-off",
      "CMMS work order",
    ],
    digital_twin: [
      "Physical inspection report",
      "Structural engineer sign-off",
      "DT-physical deviation reconciliation",
    ],
    environmental_compliance: [
      "Lab analysis certificate",
      "Updated OiW measurement",
      "Regulator notification receipt",
    ],
    general: ["Independent physical verification", "SME sign-off", "Policy trigger clearance"],
  };
  return {
    asset: {
      field: fields[d] ?? "Ivar Aasen",
      asset_id: asset.id,
      section: sections[d] ?? "Process Deck",
      operation: ops[d] ?? "autonomous action",
    },
    decision_question: questions[d] ?? "Is this autonomous action safe to execute?",
    critical_missing_data: missingData[d] ?? ["Independent verification", "SME sign-off"],
  };
}

export function deriveFollowUpBlock(item: EscalationItem): import("./types").FollowUpBlock {
  const d = item.trace.intent.domain;
  const types: Partial<Record<Domain, string>> = {
    well_engineering: "independent_well_engineering_review",
    process_safety: "independent_safety_review",
    maintenance_planning: "on_site_inspection",
    digital_twin: "physical_inspection_and_dt_reconciliation",
    environmental_compliance: "lab_analysis_and_regulator_notification",
    general: "independent_verification",
  };
  const reasons: Partial<Record<Domain, string>> = {
    well_engineering:
      "Autonomous mud weight change is blocked until barrier envelope is independently verified.",
    process_safety:
      "Barrier bypass requires independent SIL verification and OIM approval before proceeding.",
    maintenance_planning:
      "Maintenance deferral requires updated inspection evidence and inspector sign-off.",
    digital_twin: "DT model update requires physical inspection confirmation before recalibration.",
    environmental_compliance:
      "Discharge approval requires updated lab analysis and regulator notification.",
    general: "Autonomous action blocked pending independent verification.",
  };
  const roles: Partial<Record<Domain, string>> = {
    well_engineering: "independent_well_engineer",
    process_safety: "independent_safety_engineer",
    maintenance_planning: "site_technician",
    digital_twin: "structural_integrity_engineer",
    environmental_compliance: "environmental_officer",
    general: "operations_lead",
  };
  const evidenceMap: Partial<Record<Domain, string[]>> = {
    well_engineering: [
      "Updated ECD model",
      "Kick tolerance calculation",
      "Pore pressure and fracture gradient window",
      "NORSOK D-010 barrier envelope confirmation",
      "Well programme change justification",
      "Two-person approval",
    ],
    process_safety: [
      "SIL verification report",
      "Root cause investigation",
      "OIM sign-off",
      "MOC documentation",
      "Barrier integrity test results",
    ],
    maintenance_planning: [
      "Field inspection photo",
      "Updated CMMS work order",
      "Inspector sign-off form",
      "Criticality class confirmation",
    ],
    digital_twin: [
      "Physical inspection report",
      "Structural engineer sign-off",
      "DT-physical deviation reconciliation note",
    ],
    environmental_compliance: [
      "Lab analysis certificate",
      "Updated OiW measurement",
      "Regulator notification receipt",
    ],
    general: ["Independent physical verification", "SME sign-off", "Supporting evidence package"],
  };
  const slaMap: Partial<Record<Domain, number>> = {
    well_engineering: 4,
    process_safety: 2,
    maintenance_planning: 72,
    digital_twin: 24,
    environmental_compliance: 48,
    general: 24,
  };
  return {
    required: item.trace.verdict === "ESCALATE" || item.trace.verdict === "ABSTAIN",
    type: types[d] ?? "independent_verification",
    priority: item.risk === "critical" ? "critical" : item.risk === "high" ? "high" : "medium",
    reason: reasons[d] ?? "Autonomous action blocked pending verification.",
    assign_to_role: roles[d] ?? "operations_lead",
    requested_evidence: evidenceMap[d] ?? ["Independent verification", "Expert sign-off"],
    sla_hours: slaMap[d] ?? 24,
    rerun_condition: "All requested evidence attached and independent verification completed",
  };
}

export function deriveHistoryBlock(h: CaseHistory): import("./types").HistoryBlock {
  return {
    similar_cases_found: h.count,
    similarity_basis: [
      `same domain: ${h.cases[0]?.action.split(" ")[0] ?? "well_engineering"}`,
      "same action type",
      "same risk tier",
      "same policy triggers",
    ],
    decision_pattern: {
      approved: h.approved,
      rejected: h.rejected,
      follow_up_required: h.follow_up,
      autonomous_handled: h.autonomous,
    },
    known_blockers: h.blockers,
    similar_cases: h.cases,
  };
}

export function derivePolicyLearningBlock(
  item: EscalationItem,
  h: CaseHistory,
  pl: PolicyLearningSuggestion,
): import("./types").PolicyLearningBlock {
  const autonomyMap: Partial<Record<Domain, string>> = {
    well_engineering: "L2_REQUEST_EVIDENCE_AUTOMATICALLY",
    process_safety: "L2_REQUEST_EVIDENCE_AUTOMATICALLY",
    maintenance_planning: "L3_CONDITIONAL_AUTO_APPROVE",
    digital_twin: "L2_REQUEST_EVIDENCE_AUTOMATICALLY",
    environmental_compliance: "L2_REQUEST_EVIDENCE_AUTOMATICALLY",
    general: "L1_HUMAN_REQUIRED",
  };
  return {
    candidate_rule_update: pl.candidate,
    recommendation: pl.recommendation,
    confidence: pl.confidence,
    supporting_cases: h.cases.map((c) => c.id),
    proposed_autonomy_level: autonomyMap[item.trace.intent.domain] ?? "L1_HUMAN_REQUIRED",
    autonomy_allowed: false,
    requires_policy_owner_approval: true,
  };
}

export function deriveHistory(item: EscalationItem): CaseHistory {
  const d = item.trace.intent.domain;
  const n = (parseInt(item.trace.request_id.replace(/-/g, "").slice(-3), 16) % 5) + 5;
  const rejected = Math.round(n * 0.55);
  const follow_up = Math.round(n * 0.27);
  const approved = n - rejected - follow_up;
  const blockersMap: Partial<Record<Domain, string[]>> = {
    well_engineering: [
      "Missing updated ECD calculation",
      "Kick tolerance not verified",
      "Barrier envelope not independently confirmed",
      "OIM written sign-off absent",
    ],
    process_safety: [
      "SIL verification report missing",
      "Root cause not identified",
      "PSA §17 barrier deferral requires OIM approval",
      "MOC documentation incomplete",
    ],
    maintenance_planning: [
      "Latest inspection photo not attached",
      "Criticality class unconfirmed",
      "Inspector sign-off missing",
      "CMMS work order not raised",
    ],
    digital_twin: [
      "Physical inspection report absent",
      "Structural engineer sign-off missing",
      ">10% DT-physical deviation threshold exceeded",
    ],
    environmental_compliance: [
      "Lab analysis certificate missing",
      "OSPAR threshold not independently calculated",
      "Regulator acknowledgment not received",
    ],
    general: [
      "Independent physical verification missing",
      "SME sign-off not obtained",
      "Policy trigger not cleared",
    ],
  };
  const blockers = blockersMap[d] ?? [
    "Independent verification missing",
    "Expert sign-off not obtained",
  ];
  const humanDecisions = [
    "REJECTED",
    "FOLLOW_UP",
    "REJECTED",
    "REJECTED",
    "APPROVED",
    "FOLLOW_UP",
    "REJECTED",
    "APPROVED",
  ];
  const outcomes = [
    "No autonomous action taken — field verification required",
    "Follow-up inspection completed, action rejected",
    "Rejected after OIM review — policy trigger not cleared",
    "Independent engineer confirmed: do not proceed",
    "Approved after full evidence package submitted",
    "Follow-up resolved in 6h, then approved with conditions",
    "Rejected — regulatory sign-off not obtainable in SLA window",
    "Approved with independent verifier sign-off",
  ];
  const cases: SimilarCase[] = Array.from({ length: Math.min(n, 5) }, (_, i) => ({
    id: `case_2026_${String(10142 + i * 17 + (parseInt(item.trace.request_id.slice(-2), 16) % 40)).padStart(5, "0")}`,
    similarity: parseFloat((0.91 - i * 0.05).toFixed(2)),
    action: item.proposed_action.slice(0, 52) + "…",
    verdict: "ESCALATE",
    human_decision: humanDecisions[i % humanDecisions.length],
    outcome: outcomes[i % outcomes.length],
    reason: blockers[i % blockers.length],
  }));
  return {
    count: n,
    approved,
    rejected,
    follow_up,
    autonomous: 0,
    blockers: blockers.slice(0, 3),
    cases,
  };
}

export function derivePolicyLearning(
  item: EscalationItem,
  h: CaseHistory,
): PolicyLearningSuggestion {
  const d = item.trace.intent.domain;
  const pct = (h.follow_up + h.rejected) / h.count;
  const recs: Partial<Record<Domain, string>> = {
    well_engineering:
      "Require ECD calculation, kick tolerance, and independent verifier sign-off before any mud weight modification.",
    process_safety:
      "Require SIL verification and OIM approval before any barrier bypass or restart after unknown-cause trip.",
    maintenance_planning:
      "Require photo evidence and inspector sign-off before deferring criticality-class-B or higher maintenance.",
    digital_twin:
      "Flag all DT-physical deviations >10% for structural engineer review before any model update.",
    environmental_compliance:
      "Require lab analysis certificate before approving overboard discharge.",
    general: "Require independent physical verification before autonomous production writes.",
  };
  return {
    candidate: pct >= 0.6,
    confidence: Math.min(0.95, pct * 0.9 + 0.12),
    recommendation:
      recs[d] ?? "Require independent verification for all critical-risk autonomous actions.",
  };
}

export function deriveFollowUpDefaults(item: EscalationItem): FollowUpForm {
  const d = item.trace.intent.domain;
  const evidenceMap: Partial<Record<Domain, string[]>> = {
    well_engineering: [
      "Updated ECD calculation",
      "Kick tolerance calculation",
      "Barrier envelope confirmation vs NORSOK D-010",
      "Responsible drilling engineer sign-off",
    ],
    process_safety: [
      "SIL verification report",
      "Root cause investigation note",
      "OIM sign-off",
      "MOC documentation",
    ],
    maintenance_planning: [
      "Field inspection photo",
      "Updated CMMS work order",
      "Inspector sign-off form",
    ],
    digital_twin: [
      "Physical inspection report",
      "Structural engineer sign-off",
      "DT-physical deviation reconciliation note",
    ],
    environmental_compliance: [
      "Lab analysis certificate",
      "Updated OiW measurement",
      "Regulator notification receipt",
    ],
    general: ["Independent physical verification", "SME sign-off", "Supporting evidence package"],
  };
  const assignMap: Partial<Record<Domain, string>> = {
    well_engineering: "Independent Well Engineer",
    process_safety: "OIM + Maintenance Supervisor",
    maintenance_planning: "Site Technician",
    digital_twin: "Structural Integrity Engineer",
    environmental_compliance: "Environmental Officer",
    general: "Operations Lead",
  };
  const slaMap: Partial<Record<Domain, string>> = {
    well_engineering: "4 hours",
    process_safety: "2 hours",
    maintenance_planning: "72 hours",
    digital_twin: "24 hours",
    environmental_compliance: "48 hours",
    general: "24 hours",
  };
  return {
    reasons: {
      "Missing field confirmation": true,
      "Safety barrier not independently verified":
        d === "well_engineering" || d === "process_safety",
      "Low REMORA trust score": item.trace.thermo.trust < 0.5,
      "Regulatory approval required": item.risk === "critical" || item.risk === "high",
    },
    requestType:
      d === "maintenance_planning"
        ? "photo_evidence"
        : d === "environmental_compliance"
          ? "sensor_reading"
          : "on_site_inspection",
    priority: item.risk === "critical" ? "Critical" : item.risk === "high" ? "High" : "Medium",
    assignTo: assignMap[d] ?? "Operations Lead",
    sla: slaMap[d] ?? "24 hours",
    evidence: evidenceMap[d] ?? ["Independent verification", "Expert sign-off"],
  };
}

export function deriveFieldResponse(item: EscalationItem): FieldResponse {
  const d = item.trace.intent.domain;
  const techMap: Partial<Record<Domain, string>> = {
    well_engineering: "Kjetil Andersen (Drilling Engineer)",
    process_safety: "Lars Haugen (OIM Deputy)",
    maintenance_planning: "Ola Hansen (Site Technician)",
    digital_twin: "Siri Bakken (Structural Engineer)",
    environmental_compliance: "Marte Olsen (Environmental Officer)",
    general: "Tor Nilsen (Operations Lead)",
  };
  const recMap: Partial<Record<Domain, string>> = {
    well_engineering:
      "Do not reduce mud weight — barrier envelope insufficient per current ECD model",
    process_safety: "Hold — SIL report pending, root cause unresolved, OIM not available",
    maintenance_planning: "Inspection rescheduled within 24h — do not defer further",
    digital_twin: "Physical inspection required before DT model update",
    environmental_compliance: "Lab analysis confirms compliance — approved for discharge",
    general: "Independent verification in progress — hold autonomous action",
  };
  return {
    technician: techMap[d] ?? "Operations Lead",
    time: "14:22",
    locationVerified: true,
    photosAttached: d === "maintenance_planning" || d === "digital_twin" ? 3 : 0,
    inspectionCompleted: d === "environmental_compliance",
    recommendation: recMap[d] ?? "Hold — further verification required",
    rerunReady: d === "environmental_compliance",
  };
}

export function deriveAsset(item: EscalationItem): AssetInfo {
  const d = item.trace.intent.domain;
  const n = (parseInt(item.trace.request_id.replace(/-/g, "").slice(-4), 16) % 20) + 1;
  const pad = (x: number) => (x < 10 ? "0" + x : "" + x);
  const prefix =
    d === "well_engineering"
      ? "WH"
      : d === "digital_twin"
        ? "RS"
        : d === "process_safety"
          ? "ESD"
          : "A";
  const zones: Partial<Record<Domain, string>> = {
    well_engineering: "Wellbay / Level 2",
    process_safety: "Module A / Hazardous Area",
    maintenance_planning: "Utility Module / Level 3",
    digital_twin: "Subsea / Riser Section B",
    environmental_compliance: "Water Treatment / Level 1",
    reservoir_engineering: "Control Room / ICSS",
    general: "Process Deck / Level 2",
  };
  const types: Partial<Record<Domain, string>> = {
    well_engineering: "Wellhead Assembly",
    process_safety: "Emergency Shutdown Valve",
    maintenance_planning: "Rotating Equipment",
    digital_twin: "Production Riser",
    environmental_compliance: "Water Treatment Unit",
    reservoir_engineering: "Integrated Asset Model",
    general: "Safety-Critical Asset",
  };
  const systems: Partial<Record<Domain, string>> = {
    well_engineering: "Well Control System (WCS)",
    process_safety: "Safety Instrumented System (SIS)",
    maintenance_planning: "CMMS / SAP PM",
    digital_twin: "Structural Integrity DT",
    environmental_compliance: "Environmental Monitoring",
    general: "Safety Instrumented System",
  };
  const base = new Date("2026-01-29");
  const fmt = (dt: Date) => dt.toISOString().slice(0, 10);
  const overduedays = 9 + (n % 11);
  return {
    id: `${prefix}-${pad(n)}`,
    type: types[d] ?? "Safety-Critical Asset",
    zone: zones[d] ?? "Process Deck / Level 2",
    system: systems[d] ?? "Safety Instrumented System",
    criticality:
      item.risk === "critical"
        ? "SIL-3 / Class A"
        : item.risk === "high"
          ? "SIL-2 / Class B"
          : "SIL-1 / Class C",
    lastInspection: fmt(new Date(base.getTime() - (70 + n * 2) * 86400000)),
    nextDue: fmt(new Date(base.getTime() - overduedays * 86400000)),
    overdueBy: `${overduedays} days`,
    cmmsRef: `SAP-PM-2024-${7700 + n}`,
  };
}

export function deriveWhyEscalated(t: DecisionTrace, item: EscalationItem): string[] {
  const out: string[] = [];
  if (item.risk === "critical" || item.risk === "high")
    out.push(`Risk tier is ${item.risk.toUpperCase()} — mandatory human review threshold`);
  if (t.thermo.trust < 0.5)
    out.push(
      `Trust score ${(t.thermo.trust * 100).toFixed(0)}% — below autonomous-action threshold (50%)`,
    );
  const c = new Map<string, number>();
  for (const v of t.oracles) c.set(v.answer, (c.get(v.answer) ?? 0) + 1);
  const dom = [...c.entries()].sort((a, b) => b[1] - a[1])[0];
  const agr = dom ? (dom[1] / t.oracles.length) * 100 : 0;
  if (agr < 70)
    out.push(
      `Oracle agreement ${agr.toFixed(0)}% — no stable majority (dissensus D=${t.thermo.D.toFixed(2)})`,
    );
  if (t.policy.triggers.length > 0) out.push(`Policy gate fired: ${t.policy.triggers[0].rule}`);
  if (t.thermo.phase === "disordered")
    out.push("Thermodynamic phase DISORDERED — entropy too high for autonomous action");
  if (t.approval_required)
    out.push("Proposed action requires explicit human approval under OPA/Rego policy");
  return out.slice(0, 5);
}

export function deriveRiskMatrix(item: EscalationItem): RK[] {
  const d = item.trace.intent.domain;
  const isSafety = d === "process_safety" || d === "well_engineering";
  const isEnv = d === "environmental_compliance";
  const isMaint = d === "maintenance_planning" || d === "digital_twin";
  const r = item.risk as RK["level"];
  return [
    { label: "Operational", level: r },
    {
      label: "Compliance",
      level: isSafety || isEnv ? "high" : r === "critical" ? "high" : "medium",
    },
    { label: "Safety", level: isSafety ? "critical" : isMaint ? "high" : r },
    { label: "Audit / Ptil", level: item.trace.policy.triggers.length > 0 ? "critical" : "medium" },
  ];
}

export function deriveEvidence(t: DecisionTrace, d: Domain): EvSrc[] {
  const found: EvSrc[] = t.evidence
    .slice(0, 4)
    .map((e) => ({ label: `${e.source} ${e.section}`, found: true }));
  const missingMap: Partial<Record<Domain, string[]>> = {
    maintenance_planning: ["Latest field inspection photo", "Inspector sign-off document"],
    process_safety: ["SIL verification report", "MOC sign-off"],
    well_engineering: ["Well barrier schematic (current)", "OIM written sign-off"],
    digital_twin: ["Physical inspection report", "Structural engineer sign-off"],
    environmental_compliance: ["Lab analysis certificate", "Regulator acknowledgment"],
    general: ["Physical verification", "Independent SME sign-off"],
  };
  const missing: EvSrc[] = (missingMap[d] ?? ["Independent verification", "Expert sign-off"]).map(
    (l) => ({ label: l, found: false }),
  );
  return [...found, ...missing];
}

export function deriveTimeline(item: EscalationItem, asset: AssetInfo): TL[] {
  return [
    { date: asset.lastInspection, event: "Last inspection completed — cleared", type: "info" },
    { date: asset.nextDue, event: "Inspection window passed — not yet rescheduled", type: "warn" },
    { date: "2026-01-20", event: "CMMS follow-up task created (status: open)", type: "info" },
    {
      date: "2026-01-29",
      event: `Agent requested: ${item.proposed_action.slice(0, 55)}…`,
      type: "warn",
    },
    { date: "2026-01-29", event: "REMORA blocked — escalated to reviewer queue", type: "block" },
  ];
}

export function requestTypeLabel(value: string) {
  const types: Record<string, string> = {
    photo_evidence: "Photo evidence",
    on_site_inspection: "On-site inspection",
    sensor_reading: "Sensor reading",
    manual_measurement: "Manual measurement",
    supervisor_signoff: "Supervisor sign-off",
    service_work_order: "Service work order",
  };
  return types[value] ?? value.replace(/_/g, " ");
}
