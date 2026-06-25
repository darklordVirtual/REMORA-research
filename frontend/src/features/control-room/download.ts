import type { DecisionTrace } from "@/lib/remora-sim";
import type {
  CRScenario,
  EscalationItem,
  FollowUpForm,
  FieldResponse,
  CaseHistory,
  PolicyLearningSuggestion,
} from "./types";
import {
  deriveAsset,
  deriveReviewerContext,
  deriveFollowUpBlock,
  deriveHistoryBlock,
  derivePolicyLearningBlock,
  deriveHistory,
  derivePolicyLearning,
  deriveWhyEscalated,
} from "./derivation";

export function downloadEnvelope(trace: DecisionTrace, sc: CRScenario, queryOverride?: string) {
  // Build operational envelope blocks
  const mockItem: EscalationItem = {
    id: 0,
    title: sc.title,
    sector: sc.sector ?? "Well Engineering",
    icon: sc.icon ?? "⚡",
    proposed_action: sc.proposed_action,
    without_remora: sc.without_remora,
    with_remora: sc.with_remora,
    reason: trace.reason,
    risk: trace.intent.risk,
    trust: trace.thermo.trust,
    phase: trace.thermo.phase,
    ts: new Date().toISOString().slice(11, 16),
    trace,
    status: "pending",
  };
  const asset = deriveAsset(mockItem);
  const reviewerContext = deriveReviewerContext(mockItem, asset);
  const followUp = deriveFollowUpBlock(mockItem);
  const history = deriveHistory(mockItem);
  const policyLearningRaw = derivePolicyLearning(mockItem, history);
  const historyBlock = deriveHistoryBlock(history);
  const policyLearning = derivePolicyLearningBlock(mockItem, history, policyLearningRaw);

  // Enrich oracle votes with readable labels
  const enrichedOracles = trace.oracles.map((vote) => ({
    oracle: vote.oracle,
    family: vote.family,
    answer: {
      label: vote.answer,
      summary:
        vote.confidence > 0.85
          ? "High confidence agreement with consensus"
          : vote.confidence > 0.6
            ? "Moderate confidence — within acceptable range"
            : "Low confidence — significant uncertainty detected",
    },
    confidence: vote.confidence,
    latency_ms: vote.latency_ms,
    tokens: vote.tokens,
  }));

  // Enrich evidence with relevance classification
  const enrichedEvidence = trace.evidence.map((chunk) => {
    const raw = chunk.score;
    const normalized = Math.min(1.0, raw);
    return {
      source: chunk.source,
      section: chunk.section,
      snippet: chunk.snippet,
      retrieval_score_raw: raw,
      retrieval_score_normalized: parseFloat(normalized.toFixed(3)),
      evidence_relevance: normalized > 0.85 ? "high" : normalized > 0.65 ? "medium" : "low",
      evidence_sufficient_for_autonomous_action: normalized > 0.85 && chunk.fresh_days < 90,
      fresh_days: chunk.fresh_days,
    };
  });

  const envelope = {
    envelope: {
      schema: "remora.operational_envelope.v2",
      request_id: trace.request_id,
      timestamp: new Date().toISOString(),
      scenario_id: sc.id,
      query: queryOverride || sc.query,
      proposed_action: sc.proposed_action,
    },
    analysis: {
      intent: trace.intent,
      approval_required: trace.approval_required,
      oracle_votes: enrichedOracles,
      thermodynamic: trace.thermo,
      evidence: enrichedEvidence,
      policy: trace.policy,
    },
    score_calculation: {
      oracle_count: trace.oracles.length,
      trust_score: trace.thermo.trust,
      dissensus_index: trace.thermo.D,
      entropy: trace.thermo.H,
      thermodynamic_phase: trace.thermo.phase,
      free_energy_F: trace.thermo.F,
      policy_triggers_count: trace.policy.triggers.length,
      formula: "V(t) = H(t) + λ·D(t), λ=0.3",
      gate_outcome: trace.verdict,
    },
    decision: {
      verdict: trace.verdict,
      reason: trace.reason,
      total_latency_ms: trace.total_latency_ms,
      cascade_steps: trace.steps,
      approval_required: trace.approval_required,
      blocked_action: trace.verdict === "ACCEPT" ? null : sc.proposed_action,
      allowed_next_steps:
        trace.verdict === "ACCEPT"
          ? ["execute", "log", "close"]
          : trace.verdict === "ESCALATE"
            ? [
                "request_follow_up",
                "attach_evidence",
                "request_independent_review",
                "rerun_assessment",
              ]
            : trace.verdict === "VERIFY"
              ? ["request_evidence", "attach_documentation", "rerun_assessment"]
              : ["request_follow_up", "attach_evidence", "rerun_assessment"],
    },
    reviewer_context: reviewerContext,
    follow_up: followUp,
    history: historyBlock,
    policy_learning: policyLearning,
    audit: {
      invariant:
        "History may recommend. Policy decides. Human approval is required for rule changes. Audit records every transition.",
    },
  };
  const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `remora-envelope-${trace.request_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadReviewEnvelope(
  item: EscalationItem,
  followUp: FollowUpForm,
  fieldResponse: FieldResponse | null,
  history: CaseHistory,
  policyLearning: PolicyLearningSuggestion,
  reviewerNote: string,
) {
  const selectedReasons = Object.entries(followUp.reasons)
    .filter(([, selected]) => selected)
    .map(([reason]) => reason);

  const asset = deriveAsset(item);
  const reviewerContext = deriveReviewerContext(item, asset);
  const followUpBlock = deriveFollowUpBlock(item);
  const historyBlock = deriveHistoryBlock(history);
  const plBlock = derivePolicyLearningBlock(item, history, policyLearning);
  const whyEscalated = deriveWhyEscalated(item.trace, item);

  const enrichedOracles = item.trace.oracles.map((vote) => ({
    oracle: vote.oracle,
    family: vote.family,
    answer: {
      label: vote.answer,
      summary:
        vote.confidence > 0.85
          ? "High confidence agreement with consensus"
          : vote.confidence > 0.6
            ? "Moderate confidence — within acceptable range"
            : "Low confidence — significant uncertainty detected",
    },
    confidence: vote.confidence,
    latency_ms: vote.latency_ms,
    tokens: vote.tokens,
  }));

  const enrichedEvidence = item.trace.evidence.map((chunk) => {
    const raw = chunk.score;
    const normalized = Math.min(1.0, raw);
    return {
      source: chunk.source,
      section: chunk.section,
      snippet: chunk.snippet,
      retrieval_score_raw: raw,
      retrieval_score_normalized: parseFloat(normalized.toFixed(3)),
      evidence_relevance: normalized > 0.85 ? "high" : normalized > 0.65 ? "medium" : "low",
      evidence_sufficient_for_autonomous_action: normalized > 0.85 && chunk.fresh_days < 90,
      fresh_days: chunk.fresh_days,
    };
  });

  const envelope = {
    envelope: {
      schema: "remora.operational_review_envelope.v2",
      request_id: item.trace.request_id,
      generated_at: new Date().toISOString(),
      case_status: item.status,
      audit_hash: item.trace.request_id.slice(0, 16),
    },
    proposed_action: {
      title: item.title,
      domain: item.trace.intent.domain,
      risk: item.risk,
      action: item.proposed_action,
      remora_verdict: item.trace.verdict,
      reason: item.trace.reason,
      blocked_action: item.trace.verdict === "ACCEPT" ? null : item.proposed_action,
      allowed_next_steps:
        item.trace.verdict === "ACCEPT"
          ? ["execute", "log", "close"]
          : item.trace.verdict === "ESCALATE"
            ? [
                "request_follow_up",
                "attach_evidence",
                "request_independent_review",
                "rerun_assessment",
              ]
            : item.trace.verdict === "VERIFY"
              ? ["request_evidence", "attach_documentation", "rerun_assessment"]
              : ["request_follow_up", "attach_evidence", "rerun_assessment"],
    },
    decision_options: [
      "APPROVED",
      "REJECTED",
      "FOLLOW_UP_REQUIRED",
      "SITE_VERIFICATION_PENDING",
      "EVIDENCE_RECEIVED",
      "READY_FOR_REVIEW",
      "CLOSED",
    ],
    reviewer_context: reviewerContext,
    follow_up: {
      ...followUpBlock,
      status: fieldResponse ? "EVIDENCE_RECEIVED" : "SITE_VERIFICATION_PENDING",
      reasons: selectedReasons,
      request_type: followUp.requestType,
      assign_to: followUp.assignTo,
    },
    field_response: fieldResponse
      ? {
          technician: fieldResponse.technician,
          time: fieldResponse.time,
          location_verified: fieldResponse.locationVerified,
          photos_attached: fieldResponse.photosAttached,
          inspection_completed: fieldResponse.inspectionCompleted,
          recommendation: fieldResponse.recommendation,
          rerun_ready: fieldResponse.rerunReady,
        }
      : null,
    history: historyBlock,
    policy_learning: plBlock,
    analysis: {
      oracle_votes: enrichedOracles,
      thermodynamic: item.trace.thermo,
      evidence: enrichedEvidence,
      policy: item.trace.policy,
      why_escalated: whyEscalated,
    },
    reviewer_note: reviewerNote || null,
    audit: {
      invariant:
        "History may recommend. Policy decides. Human approval is required for rule changes. Audit records every transition.",
    },
  };
  const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `remora-review-envelope-${item.trace.request_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
