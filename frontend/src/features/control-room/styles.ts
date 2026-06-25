import type { Verdict, Phase } from "@/lib/remora-sim";
import type { ReviewStatus, RK } from "./types";

export const EXPECTED_BADGE: Record<Verdict, string> = {
  ACCEPT: "text-state-accept   border-state-accept/35   bg-state-accept/5",
  VERIFY: "text-state-verify   border-state-verify/35   bg-state-verify/5",
  ABSTAIN: "text-muted-foreground border-border/40",
  ESCALATE: "text-state-escalate border-state-escalate/35 bg-state-escalate/5",
};

export const EXPECTED_STRIPE: Record<Verdict, string> = {
  ACCEPT: "border-l-state-accept/50",
  VERIFY: "border-l-state-verify/50",
  ABSTAIN: "border-l-border/30",
  ESCALATE: "border-l-state-escalate/60",
};

export const RISK_STRIPE: Record<string, string> = {
  low: "bg-state-accept/60",
  medium: "bg-state-verify/70",
  high: "bg-orange-400/80",
  critical: "bg-state-escalate/80",
};

export const RISK_BADGE: Record<string, string> = {
  low: "text-state-accept   border-state-accept/30   bg-state-accept/5",
  medium: "text-state-verify   border-state-verify/30   bg-state-verify/5",
  high: "text-orange-400     border-orange-400/30     bg-orange-400/5",
  critical: "text-state-escalate border-state-escalate/30 bg-state-escalate/5",
};

export const VERDICT_TICKER: Record<Verdict, string> = {
  ACCEPT: "text-state-accept",
  VERIFY: "text-state-verify",
  ABSTAIN: "text-muted-foreground/75",
  ESCALATE: "text-state-escalate",
};

export const FAMILY_DOT: Record<string, string> = {
  groq: "bg-blue-400",
  mistral: "bg-purple-400",
  anthropic: "bg-amber-400",
  openai: "bg-green-400",
  local: "bg-border",
};

export const STATUS_LABEL: Record<ReviewStatus, string> = {
  pending: "PENDING REVIEW",
  approved: "APPROVED",
  rejected: "REJECTED",
  follow_up_required: "FOLLOW-UP REQUIRED",
  site_verification_pending: "SITE VERIFICATION",
  evidence_received: "EVIDENCE RECEIVED",
  ready_for_review: "READY FOR REVIEW",
  closed: "CLOSED",
};

export const RISK_LEVEL_CLS: Record<RK["level"], string> = {
  low: "text-state-accept   bg-state-accept/8   border-state-accept/30",
  medium: "text-state-verify   bg-state-verify/8   border-state-verify/30",
  high: "text-orange-400     bg-orange-400/8     border-orange-400/30",
  critical: "text-state-escalate bg-state-escalate/8 border-state-escalate/30",
};

export function statusPillClass(status: ReviewStatus) {
  if (status === "approved") return "border-state-accept/40 text-state-accept/75 bg-state-accept/5";
  if (status === "rejected" || status === "closed")
    return "border-border/40 text-muted-foreground/68";
  if (status === "site_verification_pending" || status === "follow_up_required") {
    return "border-state-verify/45 text-state-verify/85 bg-state-verify/5";
  }
  if (status === "evidence_received" || status === "ready_for_review") {
    return "border-signal/45 text-signal/85 bg-signal/5";
  }
  return "border-state-escalate/35 text-state-escalate/78 bg-state-escalate/4";
}

export function canOpenEscalation(status: ReviewStatus) {
  return !["approved", "rejected", "closed"].includes(status);
}

export function verdictBorderBg(v: Verdict) {
  return {
    ACCEPT: "border-state-accept/40 bg-state-accept/5",
    VERIFY: "border-state-verify/40 bg-state-verify/5",
    ABSTAIN: "border-border/60 bg-muted/10",
    ESCALATE: "border-state-escalate/50 bg-state-escalate/5",
  }[v];
}

export function verdictText(v: Verdict) {
  return {
    ACCEPT: "text-state-accept",
    VERIFY: "text-state-verify",
    ABSTAIN: "text-muted-foreground",
    ESCALATE: "text-state-escalate",
  }[v];
}

export function phaseText(p: Phase) {
  return {
    ordered: "text-state-accept",
    critical: "text-state-verify",
    disordered: "text-state-escalate",
  }[p];
}
