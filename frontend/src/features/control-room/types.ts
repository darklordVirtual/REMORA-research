import type { DecisionTrace, Domain, Phase, ThermoSnapshot, Verdict } from "@/lib/remora-sim";

export interface CRScenario {
  id: string;
  title: string;
  sector: string;
  icon: string;
  query: string;
  blurb: string;
  expected: Verdict;
  proposed_action: string;
  without_remora: string;
  with_remora: string;
  bias?: number;
  risk?: "low" | "medium" | "high" | "critical";
  domain?: Domain;
}

export interface LiveAlert {
  id: number;
  platform: string;
  title: string;
  verdict: Verdict;
  risk: string;
  ts: string;
}

export interface ActivityBucket {
  label: string;
  auto: number;
  escalated: number;
}

export interface SessionKPI {
  runs: number;
  accept: number;
  verify: number;
  abstain: number;
  escalate: number;
  unsafe_prevented: number;
  audit_entries: number;
  total_ms: number;
}

export type ReviewStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "follow_up_required"
  | "site_verification_pending"
  | "evidence_received"
  | "ready_for_review"
  | "closed";

export interface EscalationItem {
  id: number;
  title: string;
  sector: string;
  icon: string;
  proposed_action: string;
  without_remora?: string;
  with_remora?: string;
  reason: string;
  risk: string;
  trust: number;
  phase: Phase;
  ts: string;
  trace: DecisionTrace;
  status: ReviewStatus;
}

export interface AutoHandled {
  id: number;
  platform: string;
  title: string;
  verdict: "ACCEPT" | "VERIFY";
  trust: number;
  latency_ms: number;
  ts: string;
}

export interface SimilarCase {
  id: string;
  similarity: number;
  action: string;
  verdict: string;
  human_decision: string;
  outcome: string;
  reason: string;
}

export interface CaseHistory {
  count: number;
  approved: number;
  rejected: number;
  follow_up: number;
  autonomous: number;
  blockers: string[];
  cases: SimilarCase[];
}

export interface FollowUpForm {
  reasons: Record<string, boolean>;
  requestType: string;
  priority: string;
  assignTo: string;
  sla: string;
  evidence: string[];
}

export interface FieldResponse {
  technician: string;
  time: string;
  locationVerified: boolean;
  photosAttached: number;
  inspectionCompleted: boolean;
  recommendation: string;
  rerunReady: boolean;
}

export interface PolicyLearningSuggestion {
  candidate: boolean;
  confidence: number;
  recommendation: string;
}

// ── New operational envelope blocks ──────────────────────────────────

export interface ReviewerContext {
  asset: {
    field: string;
    asset_id: string;
    section: string;
    operation: string;
  };
  decision_question: string;
  critical_missing_data: string[];
}

export interface FollowUpBlock {
  required: boolean;
  type: string;
  priority: string;
  reason: string;
  assign_to_role: string;
  requested_evidence: string[];
  sla_hours: number;
  rerun_condition: string;
}

export interface DecisionPattern {
  approved: number;
  rejected: number;
  follow_up_required: number;
  autonomous_handled: number;
}

export interface HistoryBlock {
  similar_cases_found: number;
  similarity_basis: string[];
  decision_pattern: DecisionPattern;
  known_blockers: string[];
  similar_cases: SimilarCase[];
}

export interface PolicyLearningBlock {
  candidate_rule_update: boolean;
  recommendation: string;
  confidence: number;
  supporting_cases: string[];
  proposed_autonomy_level: string;
  autonomy_allowed: boolean;
  requires_policy_owner_approval: boolean;
}

export interface AssetInfo {
  id: string;
  type: string;
  zone: string;
  system: string;
  criticality: string;
  lastInspection: string;
  nextDue: string;
  overdueBy: string;
  cmmsRef: string;
}

export interface EvSrc {
  label: string;
  found: boolean;
}

export interface TL {
  date: string;
  event: string;
  type: "info" | "warn" | "block";
}

export interface RK {
  label: string;
  level: "low" | "medium" | "high" | "critical";
}
