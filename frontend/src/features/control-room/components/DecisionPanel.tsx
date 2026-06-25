import React from "react";
import { cn } from "@/lib/utils";
import type { DecisionTrace, Verdict } from "@/lib/remora-sim";
import type { CRScenario } from "../types";
import { verdictBorderBg, verdictText, phaseText } from "../styles";

function DecisionPanelRaw({
  sc,
  trace,
  running,
  compareOpen,
  onToggleCompare,
}: {
  sc: CRScenario;
  trace: DecisionTrace | null;
  running: boolean;
  compareOpen: boolean;
  onToggleCompare: () => void;
}) {
  if (!trace && !running) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="font-mono text-[11px] text-muted-foreground/52 uppercase tracking-[0.12em]">
          No verdict yet
        </div>
      </div>
    );
  }

  if (running) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 gap-4 p-8">
        <div className="h-2.5 w-2.5 rounded-full bg-signal animate-pulse" />
        <div className="font-mono text-[11px] text-muted-foreground/68 uppercase tracking-[0.12em]">
          Evaluating…
        </div>
      </div>
    );
  }

  const t = trace!;

  const verdictSubtitle: Record<Verdict, string> = {
    ACCEPT: "Agent proceeds · no human time required",
    VERIFY: "Operator confirmation before execution",
    ABSTAIN: "Oracle disagreement — agent withholds",
    ESCALATE: "Human authority required · agent paused",
  };

  const verdictGuidance: Record<Verdict, string[]> = {
    ACCEPT: [
      "Agent acts autonomously — zero engineer time required",
      "Decision and evidence chain written to audit ledger",
      "Ptil-compliant record created automatically",
    ],
    VERIFY: [
      "Agent recommendation surfaced for operator confirmation",
      "Human judgment applied before execution",
      "Audit entry written with operator sign-off",
    ],
    ABSTAIN: [
      "Agent withholds — oracle disagreement too high to act",
      "Uncertainty surfaced transparently to requester",
      "No action taken; human expertise required",
    ],
    ESCALATE: [
      "Agent paused — human authority required at this threshold",
      "Work order or notification drafted for responsible engineer",
      "Immutable audit entry written with blocking reason",
      "No autonomous action taken under any circumstances",
    ],
  };

  return (
    <div className="flex flex-col divide-y divide-border/50 min-h-full">
      {/* Verdict block */}
      <div className="p-5 space-y-4">
        <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/72">
          Decision Gate
        </div>
        <div className={cn("border-2 px-5 py-6 text-center space-y-2", verdictBorderBg(t.verdict))}>
          <div
            className={cn(
              "font-serif text-5xl tracking-tight leading-none",
              verdictText(t.verdict),
            )}
          >
            {t.verdict}
          </div>
          <div className="font-mono text-xs text-muted-foreground/60 mt-2">
            {verdictSubtitle[t.verdict]}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="border border-border/40 p-3 text-center">
            <div className="font-serif text-xl text-foreground/85 tabular-nums">
              {(t.thermo.trust * 100).toFixed(0)}%
            </div>
            <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/68 mt-1">
              Trust
            </div>
          </div>
          <div className="border border-border/40 p-3 text-center">
            <div
              className={cn(
                "font-mono text-xs uppercase tracking-wide font-medium",
                phaseText(t.thermo.phase),
              )}
            >
              {t.thermo.phase}
            </div>
            <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/68 mt-1">
              Phase
            </div>
          </div>
        </div>
        <p className="font-mono text-[11px] text-muted-foreground/80 leading-relaxed">{t.reason}</p>

        {/* Policy-override callout */}
        {t.thermo.trust >= 0.52 && (t.verdict === "ESCALATE" || t.verdict === "ABSTAIN") && (
          <div className="border border-state-escalate/20 bg-state-escalate/4 px-4 py-3 mt-1">
            <div className="font-mono text-[11px] uppercase tracking-wider text-state-escalate/55 mb-1.5">
              Policy gate overrode oracle consensus
            </div>
            <div className="font-mono text-[11px] text-foreground/80 leading-relaxed">
              Oracle swarm: {(t.thermo.trust * 100).toFixed(0)}% agreement &nbsp;·&nbsp;{t.verdict}:
              risk tier + policy trigger enforced
            </div>
          </div>
        )}
      </div>

      {/* Policy triggers */}
      {t.policy.triggers.length > 0 && (
        <div className="p-5 space-y-3">
          <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/72">
            Policy triggers
          </div>
          <div className="space-y-2">
            {t.policy.triggers.map((tr) => (
              <div key={tr.rule} className="border border-border/35 px-3 py-2.5">
                <div className="flex items-center justify-between font-mono text-[11px] mb-1">
                  <span className="text-foreground/75">{tr.rule}</span>
                  <span className="text-state-verify/80 text-[11px] uppercase tracking-wider shrink-0 ml-2">
                    {tr.effect.replace(/_/g, " ")}
                  </span>
                </div>
                <div className="font-mono text-[11px] text-muted-foreground/75">{tr.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Next steps */}
      <div className="p-5 space-y-3">
        <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/72">
          Allowed next steps
        </div>
        <ul className="space-y-1.5">
          {verdictGuidance[t.verdict].map((step) => (
            <li
              key={step}
              className="font-mono text-[11px] text-muted-foreground/80 leading-relaxed flex gap-2"
            >
              <span className="text-muted-foreground/58 shrink-0">·</span>
              {step}
            </li>
          ))}
        </ul>
      </div>

      {/* Approval badge */}
      {t.approval_required && (
        <div className="px-5 py-4">
          <div className="border border-state-escalate/30 bg-state-escalate/5 px-4 py-3">
            <div className="font-mono text-[11px] uppercase tracking-[0.10em] text-state-escalate/80">
              Human approval required
            </div>
            <div className="font-mono text-[11px] text-state-escalate/40 mt-1">
              Immutable audit hash attached
            </div>
          </div>
        </div>
      )}

      {/* Before / After comparison */}
      <div className="p-5 mt-auto">
        <button
          onClick={onToggleCompare}
          className="w-full font-mono text-[11px] uppercase tracking-[0.10em] text-muted-foreground/68 hover:text-muted-foreground/82 transition-colors border border-border/30 px-3 py-2"
        >
          {compareOpen ? "▾ Hide comparison" : "▸ Without vs with REMORA"}
        </button>
        {compareOpen && (
          <div className="mt-3 space-y-2.5">
            <div className="border border-state-escalate/25 p-4">
              <div className="font-mono text-[11px] uppercase tracking-wider text-state-escalate/55 mb-2">
                Without REMORA
              </div>
              <div className="font-mono text-[11px] text-muted-foreground/80 leading-relaxed">
                {sc.without_remora}
              </div>
            </div>
            <div className="border border-state-accept/25 p-4">
              <div className="font-mono text-[11px] uppercase tracking-wider text-state-accept/55 mb-2">
                With REMORA
              </div>
              <div className="font-mono text-[11px] text-muted-foreground/80 leading-relaxed">
                {sc.with_remora}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export const DecisionPanel = React.memo(DecisionPanelRaw);
