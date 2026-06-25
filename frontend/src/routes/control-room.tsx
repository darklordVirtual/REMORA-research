import { createFileRoute, Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { Suspense, lazy } from "react";

import { useControlRoom } from "@/features/control-room/hooks/useControlRoom";
import { CR_SCENARIOS, SECTORS } from "@/features/control-room/data";
import type { EscalationItem, ReviewStatus } from "@/features/control-room/types";

import { KPIStrip } from "@/features/control-room/components/KPIStrip";
import { LiveAlertTicker } from "@/features/control-room/components/LiveAlertTicker";
import { SectorChip } from "@/features/control-room/components/MiniComponents";
import { ScenarioCard } from "@/features/control-room/components/ScenarioCard";
import { RunningPanel, EmptyPanel } from "@/features/control-room/components/MiniComponents";
import { ActivityGraph } from "@/features/control-room/components/ActivityGraph";
import { PipelinePanel } from "@/features/control-room/components/PipelinePanel";
import { DecisionPanel } from "@/features/control-room/components/DecisionPanel";
import { EscalationInbox } from "@/features/control-room/components/EscalationInbox";
const ApprovalModal = lazy(() =>
  import("@/features/control-room/components/ApprovalModal").then((m) => ({
    default: m.ApprovalModal,
  })),
);

export const Route = createFileRoute("/control-room")({
  head: () => ({
    meta: [
      { title: "REMORA Control Room — Agentic Governance for E&P Operations" },
      {
        name: "description",
        content:
          "REMORA governance layer for AI agents in exploration & production: multi-oracle consensus, OPA/Rego policy gates, PSA/Ptil audit trail, and human escalation for safety-critical decisions.",
      },
    ],
  }),
  component: ControlRoomPage,
});

function ControlRoomPage() {
  const { state, dispatch, runScenario, submitCustom, onDragStart } = useControlRoom();

  const filtered = state.sector
    ? CR_SCENARIOS.filter((s) => s.sector === state.sector)
    : CR_SCENARIOS;

  return (
    <div className="h-dvh flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <header className="shrink-0 flex items-center justify-between px-6 py-3 border-b border-border bg-background/98 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <span className="font-serif text-xl tracking-tight">REMORA</span>
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] border border-border px-2 py-0.5 text-muted-foreground">
            Control Room
          </span>
          <span className="hidden lg:block font-mono text-[11px] text-muted-foreground/68">
            OPA/Rego policy engine · multi-oracle consensus · PSA/Ptil audit trail
          </span>
        </div>
        <nav className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
          <Link to="/telemetry" className="px-3 py-1.5 hover:text-foreground transition-colors">
            Telemetry
          </Link>
        </nav>
      </header>

      {/* KPI strip */}
      <KPIStrip kpi={state.kpi} />

      {/* Live alert ticker */}
      <LiveAlertTicker alerts={state.liveAlerts} />

      {/* Three-column body */}
      <div className="flex-1 flex min-h-0 divide-x divide-border overflow-hidden">
        {/* Left: Scenario selector */}
        <aside className="w-64 shrink-0 flex flex-col overflow-hidden">
          <div className="shrink-0 px-4 pt-4 pb-3 border-b border-border space-y-3">
            <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/75">
              Agent scenarios
            </div>
            <div className="flex flex-wrap gap-1.5">
              <SectorChip
                label="All"
                active={!state.sector}
                onClick={() => dispatch({ type: "SET_SECTOR", sector: null })}
              />
              {SECTORS.map((s) => (
                <SectorChip
                  key={s}
                  label={s}
                  active={state.sector === s}
                  onClick={() =>
                    dispatch({ type: "SET_SECTOR", sector: s === state.sector ? null : s })
                  }
                />
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto divide-y divide-border/40">
            {filtered.map((sc) => (
              <ScenarioCard
                key={sc.id}
                sc={sc}
                isActive={state.active.id === sc.id}
                spinnerOn={state.running && state.active.id === sc.id}
                onClick={() => runScenario(sc)}
              />
            ))}
          </div>
          {/* Custom query input */}
          <div className="shrink-0 border-t border-border p-3 space-y-2">
            <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/68">
              Custom query
            </div>
            <textarea
              value={state.customQuery}
              onChange={(e) => dispatch({ type: "SET_CUSTOM_QUERY", value: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submitCustom();
                }
              }}
              disabled={state.running}
              placeholder="Paste any agent task or tool call…"
              rows={2}
              className="w-full resize-none bg-muted/10 border border-border/50 rounded-none px-3 py-2 font-mono text-[11px] text-foreground/80 placeholder:text-muted-foreground/58 focus:outline-none focus:border-foreground/25 disabled:opacity-40 leading-relaxed"
            />
            <button
              onClick={submitCustom}
              disabled={!state.customQuery.trim() || state.running}
              className="w-full font-mono text-[11px] uppercase tracking-[0.10em] border border-border/50 px-3 py-1.5 text-muted-foreground/60 hover:text-foreground/80 hover:border-foreground/25 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {state.running ? "Evaluating…" : "Run → REMORA"}
            </button>
          </div>
        </aside>

        {/* Center: Activity graph + Pipeline */}
        <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <ActivityGraph data={state.activityBuckets} kpi={state.kpi} />
          <div className="flex-1 overflow-y-auto">
            {state.running ? (
              <RunningPanel sc={state.active} queryOverride={state.activeQueryText} />
            ) : state.trace ? (
              <PipelinePanel
                sc={state.active}
                trace={state.trace}
                queryOverride={state.activeQueryText}
              />
            ) : (
              <EmptyPanel />
            )}
          </div>
        </main>

        {/* Right: Decision */}
        <aside className="w-80 shrink-0 overflow-y-auto flex flex-col">
          <DecisionPanel
            sc={state.active}
            trace={state.trace}
            running={state.running}
            compareOpen={state.compareOpen}
            onToggleCompare={() => dispatch({ type: "TOGGLE_COMPARE" })}
          />
        </aside>
      </div>

      {/* Drag handle */}
      <div
        className="shrink-0 h-[6px] cursor-ns-resize bg-border/20 hover:bg-signal/25 transition-colors group flex items-center justify-center select-none"
        onMouseDown={onDragStart}
      >
        <div className="w-10 h-[2px] rounded-full bg-border/50 group-hover:bg-signal/60 transition-colors" />
      </div>

      {/* Work queue — resizable */}
      <div
        style={{ height: state.inboxHeight }}
        className="shrink-0 border-t border-border overflow-hidden flex flex-col"
      >
        <EscalationInbox
          items={state.escalations}
          autoHandled={state.autoHandled}
          activeTab={state.inboxTab}
          onTabChange={(tab) => dispatch({ type: "SET_INBOX_TAB", tab })}
          onOpen={(item: EscalationItem) => dispatch({ type: "SET_APPROVAL_TARGET", item })}
          onDecide={(id: number, decision: ReviewStatus) =>
            dispatch({ type: "DECIDE_ESCALATION", id, decision })
          }
          onDismiss={(id: number) => dispatch({ type: "DISMISS_ESCALATION", id })}
          onDismissAll={() => dispatch({ type: "DISMISS_ALL_ESCALATIONS" })}
          height={state.inboxHeight}
        />
      </div>

      {/* Approval modal */}
      {state.approvalTarget && (
        <Suspense fallback={null}>
          <ApprovalModal
            item={state.approvalTarget}
            onDecide={(id: number, decision: ReviewStatus) =>
              dispatch({ type: "DECIDE_ESCALATION", id, decision })
            }
            onClose={() => dispatch({ type: "SET_APPROVAL_TARGET", item: null })}
          />
        </Suspense>
      )}
    </div>
  );
}
