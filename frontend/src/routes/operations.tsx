import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, Suspense, lazy } from "react";
import { cn } from "@/lib/utils";

import { OP_ACTIVITIES, AGENT_PROPOSALS, OPS_DATE, INITIAL_KPI } from "@/features/operations/data";
import type { AgentProposal, OpActivity } from "@/features/operations/types";
import type { ReviewStatus } from "@/features/control-room/types";

import { OpTimeline } from "@/features/operations/components/OpTimeline";
import { ProcedurePanel } from "@/features/operations/components/ProcedurePanel";
import { AgentProposalCard } from "@/features/operations/components/AgentProposalCard";

import { DecisionPanel } from "@/features/control-room/components/DecisionPanel";
import { PipelinePanel } from "@/features/control-room/components/PipelinePanel";
import { EscalationInbox } from "@/features/control-room/components/EscalationInbox";
const ApprovalModal = lazy(() =>
  import("@/features/control-room/components/ApprovalModal").then((m) => ({
    default: m.ApprovalModal,
  })),
);
import { EscalationItem } from "@/features/control-room/types";
import { verdictBorderBg, verdictText } from "@/features/control-room/styles";

export const Route = createFileRoute("/operations")({
  head: () => ({
    meta: [
      { title: "REMORA Live Operations — AI Assurance for Operational Execution" },
      {
        name: "description",
        content:
          "REMORA governs AI agents interacting with live operational plans: autonomous proposals, policy gates, multi-oracle consensus, and human-on-the-loop approval for safety-critical decisions.",
      },
    ],
  }),
  component: OperationsPage,
});

function OperationsPage() {
  const [selectedActivityId, setSelectedActivityId] = useState<string | null>(null);
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<AgentProposal[]>(AGENT_PROPOSALS);
  const [escalations, setEscalations] = useState<EscalationItem[]>(() =>
    AGENT_PROPOSALS.filter(
      (p) => p.trace.verdict === "ESCALATE" || p.trace.verdict === "ABSTAIN",
    ).map((p, i) => makeEscalationItem(p, i)),
  );
  const [approvalTarget, setApprovalTarget] = useState<EscalationItem | null>(null);
  const [inboxTab, setInboxTab] = useState<"escalations" | "auto">("escalations");

  const selectedActivity = useMemo(
    () => OP_ACTIVITIES.find((a) => a.id === selectedActivityId) ?? null,
    [selectedActivityId],
  );

  const selectedProposal = useMemo(
    () => proposals.find((p) => p.id === selectedProposalId) ?? null,
    [proposals, selectedProposalId],
  );

  const proposalsForActivity = useMemo(
    () =>
      selectedActivityId ? proposals.filter((p) => p.activityId === selectedActivityId) : proposals,
    [proposals, selectedActivityId],
  );

  const autoHandled = useMemo(
    () =>
      proposals
        .filter((p) => p.trace.verdict === "ACCEPT" || p.trace.verdict === "VERIFY")
        .map((p) => ({
          id: parseInt(p.id.replace(/\D/g, ""), 10) || 0,
          platform: p.activityId,
          title: p.title,
          verdict: p.trace.verdict as "ACCEPT" | "VERIFY",
          trust: p.trace.thermo.trust,
          latency_ms: p.trace.total_latency_ms,
          ts: "14:22",
        })),
    [proposals],
  );

  const kpi = useMemo(() => {
    const accepted = proposals.filter((p) => p.reviewStatus === "approved").length;
    const escalated = proposals.filter((p) => p.reviewStatus === "pending").length;
    const completed = OP_ACTIVITIES.filter((a) => a.status === "completed").length;
    const delayed = OP_ACTIVITIES.filter((a) => a.status === "delayed").length;
    const blocked = OP_ACTIVITIES.filter((a) => a.status === "blocked").length;
    return {
      ...INITIAL_KPI,
      completed,
      delayed,
      blocked,
      proposalsAccepted: accepted,
      proposalsEscalated: escalated,
      engineerTimeSavedMin: accepted * 12,
    };
  }, [proposals]);

  function handleDecide(id: number, decision: ReviewStatus) {
    setEscalations((prev) => prev.map((e) => (e.id === id ? { ...e, status: decision } : e)));
    setProposals((prev) =>
      prev.map((p) =>
        (parseInt(p.id.replace(/\D/g, ""), 10) || 0) === id ? { ...p, reviewStatus: decision } : p,
      ),
    );
    if (decision === "approved" || decision === "rejected" || decision === "closed") {
      setApprovalTarget(null);
    }
  }

  return (
    <div className="h-dvh flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <header className="shrink-0 flex items-center justify-between px-6 py-3 border-b border-border bg-background/98 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <span className="font-serif text-xl tracking-tight">REMORA</span>
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] border border-border px-2 py-0.5 text-muted-foreground">
            Live Operations
          </span>
          <span className="hidden lg:block font-mono text-[11px] text-muted-foreground/68">
            AI assurance layer · procedure-linked decisions · human-on-the-loop · audit trail
          </span>
        </div>
        <div className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
          <span className="px-2 py-1">{OPS_DATE}</span>
          <span className="text-border">·</span>
          <span className="px-2 py-1 text-signal">Day Shift</span>
        </div>
      </header>

      {/* KPI strip */}
      <div className="shrink-0 flex items-stretch gap-px bg-border/40 overflow-x-auto border-b border-border">
        {[
          {
            label: "Activities",
            value: `${kpi.completed}/${kpi.totalActivities}`,
            cls: "text-foreground/85",
          },
          { label: "Delayed", value: kpi.delayed, cls: "text-state-verify" },
          { label: "Blocked", value: kpi.blocked, cls: "text-state-escalate" },
          { label: "Agent proposals", value: kpi.proposalsGenerated, cls: "text-foreground/85" },
          { label: "Auto-accepted", value: kpi.proposalsAccepted, cls: "text-state-accept" },
          { label: "Escalated", value: kpi.proposalsEscalated, cls: "text-state-escalate" },
          {
            label: "Engineer time freed",
            value: `${kpi.engineerTimeSavedMin} min`,
            cls: "text-state-accept",
          },
        ].map(({ label, value, cls }) => (
          <div
            key={label}
            className="flex flex-col items-center justify-center bg-background px-5 py-2 min-w-[88px] shrink-0"
          >
            <div className={`font-serif text-2xl tracking-tight tabular-nums leading-none ${cls}`}>
              {value}
            </div>
            <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/68 mt-1 text-center leading-tight">
              {label}
            </div>
          </div>
        ))}
      </div>

      {/* Three-column body */}
      <div className="flex-1 flex min-h-0 divide-x divide-border overflow-hidden">
        {/* Left: Timeline + Procedure */}
        <aside className="w-80 shrink-0 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <OpTimeline
              activities={OP_ACTIVITIES}
              selectedId={selectedActivityId}
              onSelect={setSelectedActivityId}
            />
            {selectedActivity && <ProcedurePanel activity={selectedActivity} />}
          </div>
        </aside>

        {/* Center: Agent proposals */}
        <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <div className="shrink-0 px-5 py-3 border-b border-border">
            <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/75">
              Agent Proposals — {selectedActivity ? selectedActivity.title : "All activities"}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {proposalsForActivity.length === 0 ? (
              <div className="flex items-center justify-center h-full font-mono text-[11px] text-muted-foreground/48 uppercase tracking-[0.12em]">
                No agent proposals for this activity
              </div>
            ) : (
              proposalsForActivity.map((p) => (
                <AgentProposalCard
                  key={p.id}
                  proposal={p}
                  isSelected={selectedProposalId === p.id}
                  onClick={() => setSelectedProposalId(p.id)}
                />
              ))
            )}
          </div>
        </main>

        {/* Right: REMORA decision gate */}
        <aside className="w-[26rem] shrink-0 overflow-y-auto flex flex-col">
          {selectedProposal ? (
            <div className="flex flex-col divide-y divide-border/50 min-h-full">
              <div className="p-5 space-y-4">
                <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                  Agent Proposal
                </div>
                <div className="border-l-2 border-signal/40 pl-3 font-mono text-[11px] text-foreground/80 leading-relaxed italic">
                  “{selectedProposal.proposedAction}”
                </div>
                <div className="font-mono text-[10px] text-muted-foreground/60 leading-relaxed">
                  {selectedProposal.consequenceIfBlocked}
                </div>
              </div>

              <div className="p-5 space-y-4">
                <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                  REMORA Decision Gate
                </div>
                <OpDecisionMini trace={selectedProposal.trace} />
              </div>

              <div className="flex-1 p-5 overflow-y-auto">
                <PipelinePanel
                  sc={adaptToScenario(selectedProposal)}
                  trace={selectedProposal.trace}
                />
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="font-mono text-[11px] text-muted-foreground/52 uppercase tracking-[0.12em] text-center max-w-xs leading-relaxed">
                Select an agent proposal to view REMORA evaluation, oracle consensus, and policy
                analysis
              </div>
            </div>
          )}
        </aside>
      </div>

      {/* Bottom: Work queue / audit */}
      <div
        className="shrink-0 border-t border-border overflow-hidden flex flex-col"
        style={{ height: 200 }}
      >
        <EscalationInbox
          items={escalations}
          autoHandled={autoHandled}
          activeTab={inboxTab}
          onTabChange={setInboxTab}
          onOpen={(item) => setApprovalTarget(item)}
          onDecide={(id, decision) => handleDecide(id, decision)}
          onDismiss={(id) => setEscalations((prev) => prev.filter((e) => e.id !== id))}
          onDismissAll={() => setEscalations([])}
          height={200}
        />
      </div>

      {/* Approval modal */}
      {approvalTarget && (
        <Suspense fallback={null}>
          <ApprovalModal
            item={approvalTarget}
            onDecide={(id, decision) => handleDecide(id, decision)}
            onClose={() => setApprovalTarget(null)}
          />
        </Suspense>
      )}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeEscalationItem(p: AgentProposal, idx: number): EscalationItem {
  const activity = OP_ACTIVITIES.find((a) => a.id === p.activityId);
  return {
    id: (parseInt(p.id.replace(/\D/g, ""), 10) || 0) + idx * 100,
    title: p.title,
    sector: activity?.category ?? "Operations",
    icon: activity?.status === "blocked" ? "🚫" : "⚡",
    proposed_action: p.proposedAction,
    reason: p.trace.reason,
    risk: p.trace.intent.risk,
    trust: p.trace.thermo.trust,
    phase: p.trace.thermo.phase,
    ts: "14:22",
    trace: p.trace,
    status: "pending",
  };
}

function adaptToScenario(p: AgentProposal) {
  const activity = OP_ACTIVITIES.find((a) => a.id === p.activityId);
  return {
    id: p.activityId,
    title: p.title,
    sector: activity?.category ?? "Operations",
    icon: "🤖",
    query: p.proposedAction,
    blurb: p.trigger,
    expected: p.trace.verdict,
    proposed_action: p.proposedAction,
    without_remora: p.consequenceIfBlocked,
    with_remora: p.trace.reason,
    bias: p.trace.thermo.trust,
    risk: p.trace.intent.risk as "low" | "medium" | "high" | "critical",
    domain: p.trace.intent.domain,
  };
}

function OpDecisionMini({ trace }: { trace: AgentProposal["trace"] }) {
  const v = trace.verdict;
  return (
    <div className={cn("border-2 px-5 py-5 text-center space-y-2", verdictBorderBg(v))}>
      <div className={cn("font-serif text-4xl tracking-tight leading-none", verdictText(v))}>
        {v}
      </div>
      <div className="font-mono text-xs text-muted-foreground/60">
        {v === "ACCEPT"
          ? "Agent proceeds autonomously — zero engineer time required"
          : v === "VERIFY"
            ? "Operator confirmation required before execution"
            : v === "ABSTAIN"
              ? "Oracle disagreement — agent withholds action"
              : "Human authority required — agent paused"}
      </div>
      <div className="grid grid-cols-2 gap-3 pt-2">
        <div className="border border-border/40 p-2 text-center">
          <div className="font-serif text-xl text-foreground/85 tabular-nums">
            {(trace.thermo.trust * 100).toFixed(0)}%
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/68 mt-1">
            Trust
          </div>
        </div>
        <div className="border border-border/40 p-2 text-center">
          <div className="font-mono text-xs uppercase tracking-wide font-medium text-foreground/82">
            {trace.thermo.phase}
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/68 mt-1">
            Phase
          </div>
        </div>
      </div>
      <p className="font-mono text-[11px] text-muted-foreground/80 leading-relaxed pt-1">
        {trace.reason}
      </p>
    </div>
  );
}
