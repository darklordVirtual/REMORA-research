import type { DecisionTrace, Verdict } from "@/lib/remora-sim";
import type { ReviewStatus } from "@/features/control-room/types";

export interface OpStep {
  id: string;
  label: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  detail?: string;
}

export interface OpActivity {
  id: string;
  title: string;
  category: string;
  status: "planned" | "in_progress" | "delayed" | "completed" | "blocked";
  plannedStart: string; // "07:00"
  plannedEnd: string;
  actualStart?: string;
  crew: string;
  procedureRef: string;
  steps: OpStep[];
  deviation?: string;
}

export interface AgentProposal {
  id: string;
  activityId: string;
  title: string;
  trigger: string;
  proposedAction: string;
  consequenceIfBlocked: string;
  trace: DecisionTrace;
  reviewStatus: ReviewStatus;
  reviewedAt?: string;
  reviewerNote?: string;
}

export interface OpKPI {
  totalActivities: number;
  completed: number;
  delayed: number;
  blocked: number;
  proposalsGenerated: number;
  proposalsAccepted: number;
  proposalsEscalated: number;
  engineerTimeSavedMin: number;
}
