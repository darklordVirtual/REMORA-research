import type { OpActivity, AgentProposal, OpKPI } from "./types";
import { simulate } from "@/lib/remora-sim";

export const OPS_DATE = "2026-05-30";

export const CREWS = [
  "Night Shift (OIM: Lars H.)",
  "Day Shift (OIM: Kjetil A.)",
  "Evening Shift (OIM: Ola S.)",
];

export const OP_ACTIVITIES: OpActivity[] = [
  {
    id: "act-prejob",
    title: "Pre-job safety meeting & JSA review",
    category: "Planning",
    status: "completed",
    plannedStart: "06:00",
    plannedEnd: "07:00",
    actualStart: "06:00",
    crew: "Day Shift (OIM: Kjetil A.)",
    procedureRef: "PROC-SAFE-001",
    steps: [
      { id: "s1", label: "Toolbox talk", status: "completed" },
      { id: "s2", label: "JSA sign-off", status: "completed" },
      { id: "s3", label: "Permit to work issued", status: "completed" },
    ],
  },
  {
    id: "act-bop",
    title: "BOP pressure test — 345 bar envelope",
    category: "Well Control",
    status: "delayed",
    plannedStart: "07:00",
    plannedEnd: "09:00",
    actualStart: "07:00",
    crew: "Day Shift (OIM: Kjetil A.)",
    procedureRef: "PROC-WELL-042",
    deviation: "Pressure drop 12 bar/min (spec: <5 bar/min)",
    steps: [
      { id: "s1", label: "Isolate wellhead", status: "completed" },
      {
        id: "s2",
        label: "Pressurize to 345 bar",
        status: "in_progress",
        detail: "Holding at 333 bar, dropping",
      },
      { id: "s3", label: "15-minute hold test", status: "pending" },
      { id: "s4", label: "Depressurize & vent", status: "pending" },
    ],
  },
  {
    id: "act-riser",
    title: "Riser inspection — structural integrity",
    category: "Structural",
    status: "blocked",
    plannedStart: "09:00",
    plannedEnd: "11:00",
    crew: "Day Shift (OIM: Kjetil A.)",
    procedureRef: "PROC-STRUC-017",
    deviation: "DT-physical deviation 11.2% (threshold: 10%)",
    steps: [
      { id: "s1", label: "Visual inspection topside", status: "completed" },
      {
        id: "s2",
        label: "DT model comparison",
        status: "failed",
        detail: "Deviation exceeds NORSOK N-006 §6.3",
      },
      { id: "s3", label: "ROV subsea survey", status: "pending" },
      { id: "s4", label: "Sign-off by structural engineer", status: "pending" },
    ],
  },
  {
    id: "act-scale",
    title: "Scale squeeze — inhibitor injection",
    category: "Chemical",
    status: "in_progress",
    plannedStart: "11:00",
    plannedEnd: "13:30",
    actualStart: "11:15",
    crew: "Day Shift (OIM: Kjetil A.)",
    procedureRef: "PROC-CHEM-008",
    deviation: "Scale inhibitor A stock: 180 L remaining (planned: 420 L)",
    steps: [
      { id: "s1", label: "Isolate production line", status: "completed" },
      { id: "s2", label: "Inject pre-flush", status: "completed" },
      { id: "s3", label: "Main squeeze (inhibitor A)", status: "in_progress" },
      { id: "s4", label: "Over-flush & soak", status: "pending" },
      { id: "s5", label: "Return to production", status: "pending" },
    ],
  },
  {
    id: "act-restart",
    title: "Production restart — post-intervention",
    category: "Production",
    status: "planned",
    plannedStart: "14:00",
    plannedEnd: "15:30",
    crew: "Evening Shift (OIM: Ola S.)",
    procedureRef: "PROC-PROD-031",
    steps: [
      { id: "s1", label: "Barrier integrity verification", status: "pending" },
      { id: "s2", label: "Wellhead pressure build-up", status: "pending" },
      { id: "s3", label: "Choke manifold alignment", status: "pending" },
      { id: "s4", label: "Gas lift activation", status: "pending" },
      { id: "s5", label: "Stabilize at target rate", status: "pending" },
    ],
  },
  {
    id: "act-postjob",
    title: "Post-job verification & handover",
    category: "Planning",
    status: "planned",
    plannedStart: "16:00",
    plannedEnd: "17:00",
    crew: "Evening Shift (OIM: Ola S.)",
    procedureRef: "PROC-SAFE-002",
    steps: [
      { id: "s1", label: "Physical barrier checks", status: "pending" },
      { id: "s2", label: "Digital log completion", status: "pending" },
      { id: "s3", label: "Shift handover note", status: "pending" },
    ],
  },
];

function makeProposal(
  id: string,
  activityId: string,
  title: string,
  trigger: string,
  proposedAction: string,
  consequenceIfBlocked: string,
  query: string,
  simOpts: Parameters<typeof simulate>[1],
): AgentProposal {
  const trace = simulate(query, simOpts);
  return {
    id,
    activityId,
    title,
    trigger,
    proposedAction,
    consequenceIfBlocked,
    trace,
    reviewStatus:
      trace.verdict === "ESCALATE" || trace.verdict === "ABSTAIN"
        ? "pending"
        : trace.verdict === "ACCEPT"
          ? "approved"
          : "ready_for_review",
  };
}

export const AGENT_PROPOSALS: AgentProposal[] = [
  makeProposal(
    "prop-bop-01",
    "act-bop",
    "Reduce BOP test pressure & continue",
    "Pressure drop 12 bar/min exceeds 5 bar/min spec during BOP hold test. Possible minor seal leak or instrument drift.",
    "Autonomously reduce BOP test pressure from 345 bar to 300 bar and continue with 15-minute hold",
    "Test aborted. 2-hour NPT while maintenance crew investigates. Production deferment risk.",
    "BOP pressure test showing 12 bar/min drop. Agent proposes reducing test pressure to 300 bar and continuing. NORSOK D-010 barrier envelope maintained?",
    { scenarioId: "bop-pressure-drop", bias: 0.35, risk: "critical", domain: "well_engineering" },
  ),
  makeProposal(
    "prop-riser-01",
    "act-riser",
    "Auto-recalibrate DT fatigue model",
    "DT-physical deviation on riser SCF 11.2% vs last physical inspection. Threshold per NORSOK N-006 is 10%.",
    "Auto-recalibrate digital twin fatigue accumulation model to match latest sensor telemetry and continue with planned inspection",
    "Inspection postponed pending structural engineer review. DT model remains out of sync with physical asset.",
    "DT model on riser shows 11.2% fatigue deviation vs physical inspection. Auto-recalibrate DT or escalate to structural engineer?",
    { scenarioId: "dt-riser-deviation", bias: 0.33, risk: "high", domain: "digital_twin" },
  ),
  makeProposal(
    "prop-scale-01",
    "act-scale",
    "Substitute scale inhibitor B for A",
    "Scale inhibitor A inventory at 180 L. Planned squeeze requires 420 L. Inhibitor B (similar spec, different vendor) available at 600 L.",
    "Autonomously substitute scale inhibitor A with inhibitor B (same active concentration) and adjust injection rate by +8%",
    "Squeeze operation paused 45 min while chemical supply is confirmed. Potential formation damage if wrong inhibitor used.",
    "Scale inhibitor A low stock. Agent proposes substituting with inhibitor B. Same active concentration. Chemical compatibility verified?",
    {
      scenarioId: "chemical-substitution",
      bias: 0.68,
      risk: "medium",
      domain: "maintenance_planning",
    },
  ),
  makeProposal(
    "prop-restart-01",
    "act-restart",
    "Optimized gas lift allocation",
    "Post-intervention well productivity index updated. Model recommends revised gas lift rate across 3 wells for plateau target.",
    "Apply optimized gas lift allocation: GL-01 → 18.5 MSm3/d, GL-02 → 22.1 MSm3/d, GL-03 → 15.8 MSm3/d. All within PDO envelope.",
    "Default gas lift rates applied. Sub-optimal plateau target. Production engineer must manually adjust later.",
    "Post-intervention restart. Model recommends optimized gas lift allocation across 3 wells. All within PDO envelope. Proceed?",
    {
      scenarioId: "gas-lift-optimization",
      bias: 0.91,
      risk: "low",
      domain: "reservoir_engineering",
    },
  ),
];

export const INITIAL_KPI: OpKPI = {
  totalActivities: OP_ACTIVITIES.length,
  completed: 1,
  delayed: 1,
  blocked: 1,
  proposalsGenerated: AGENT_PROPOSALS.length,
  proposalsAccepted: AGENT_PROPOSALS.filter((p) => p.trace.verdict === "ACCEPT").length,
  proposalsEscalated: AGENT_PROPOSALS.filter((p) => p.trace.verdict === "ESCALATE").length,
  engineerTimeSavedMin: 0,
};
