import React from "react";
import { cn } from "@/lib/utils";
import type { DecisionTrace } from "@/lib/remora-sim";
import type { CRScenario } from "../types";
import { phaseText } from "../styles";
import { downloadEnvelope } from "../download";
import { OracleSwarm } from "./OracleSwarm";
import { ThermoCompact } from "./ThermoBlocks";
import { SectionLabel, RiskBadge } from "./MiniComponents";

function PipelinePanelRaw({
  sc,
  trace,
  queryOverride,
}: {
  sc: CRScenario;
  trace: DecisionTrace;
  queryOverride?: string;
}) {
  const isCustom = queryOverride && queryOverride !== sc.query;
  const displayedAction = isCustom ? queryOverride : sc.proposed_action;
  const isBlocked = trace.verdict === "ESCALATE";
  const isWarning = trace.verdict === "VERIFY";
  const isAbstain = trace.verdict === "ABSTAIN";
  const isClear = trace.verdict === "ACCEPT";

  return (
    <div className="space-y-0">
      {/* Decision event banner */}
      {!isClear && (
        <div
          className={cn(
            "px-7 py-5 border-b-2",
            isBlocked
              ? "border-b-state-escalate bg-state-escalate/5"
              : isWarning
                ? "border-b-state-verify bg-state-verify/4"
                : "border-b-border bg-muted/8",
          )}
        >
          <div className="flex items-start gap-8">
            <div className="min-w-0">
              <div
                className={cn(
                  "font-mono text-[11px] uppercase tracking-[0.14em] mb-1.5",
                  isBlocked
                    ? "text-state-escalate/65"
                    : isWarning
                      ? "text-state-verify/65"
                      : "text-muted-foreground/75",
                )}
              >
                {isBlocked
                  ? "Autonomous action blocked"
                  : isWarning
                    ? "Operator confirmation required"
                    : "Oracle consensus insufficient"}
              </div>
              <div
                className={cn(
                  "font-serif text-4xl tracking-tight leading-none",
                  isBlocked
                    ? "text-state-escalate"
                    : isWarning
                      ? "text-state-verify"
                      : "text-muted-foreground",
                )}
              >
                {trace.verdict}
              </div>
              <p className="mt-3 font-mono text-[11px] text-foreground/80 leading-relaxed max-w-lg">
                {trace.reason}
              </p>
            </div>
            <div className="shrink-0 space-y-2 pt-1">
              <div className="grid grid-cols-2 gap-x-5 gap-y-1.5">
                <span className="font-mono text-[11px] text-muted-foreground/68 uppercase tracking-wider">
                  Trust
                </span>
                <span
                  className={cn(
                    "font-mono text-[11px] tabular-nums text-right font-medium",
                    trace.thermo.trust < 0.5 ? "text-state-escalate/70" : "text-state-verify/70",
                  )}
                >
                  {(trace.thermo.trust * 100).toFixed(0)}%
                </span>
                <span className="font-mono text-[11px] text-muted-foreground/68 uppercase tracking-wider">
                  Phase
                </span>
                <span
                  className={cn(
                    "font-mono text-[11px] text-right font-medium capitalize",
                    phaseText(trace.thermo.phase),
                  )}
                >
                  {trace.thermo.phase}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground/68 uppercase tracking-wider">
                  Policy
                </span>
                <span className="font-mono text-[11px] text-right font-medium text-foreground/82">
                  {trace.policy.triggers.length} triggers
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="p-5 space-y-5">
        {/* Agent task */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <SectionLabel>Agent Task</SectionLabel>
            <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground/75">
              <span className="capitalize">{trace.intent.domain.replace(/_/g, " ")}</span>
              <span className="text-border">·</span>
              <RiskBadge risk={trace.intent.risk} />
              <span className="text-border">·</span>
              <span>{trace.intent.sensitivity}</span>
              {trace.approval_required && (
                <>
                  <span className="text-border">·</span>
                  <span className="text-state-escalate/80 font-medium">approval required</span>
                </>
              )}
            </div>
          </div>
          <p className="border-l-2 border-signal/40 pl-4 font-serif text-sm leading-relaxed text-foreground/80 italic">
            "{displayedAction}"
          </p>
        </section>

        {/* Oracle swarm */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <SectionLabel>Oracle Swarm</SectionLabel>
            <span className="font-mono text-[11px] text-muted-foreground/68">
              {trace.oracles.length} oracles · parallel
            </span>
          </div>
          <OracleSwarm votes={trace.oracles} />
        </section>

        {/* Thermodynamic phase */}
        <section>
          <SectionLabel>Thermodynamic Phase</SectionLabel>
          <div className="mt-2">
            <ThermoCompact thermo={trace.thermo} />
          </div>
        </section>

        {/* Cascade pipeline */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <SectionLabel>Cascade Pipeline</SectionLabel>
            <span className="font-mono text-[11px] text-muted-foreground/58 tabular-nums">
              {trace.total_latency_ms}ms total
            </span>
          </div>
          <div className="border border-border divide-y divide-border/40">
            {trace.steps.map((step) => (
              <div
                key={step.id}
                className={cn(
                  "flex items-center gap-3 px-3 py-1.5",
                  step.status === "warn" && "bg-state-verify/4",
                )}
              >
                <span
                  className={cn("h-1.5 w-1.5 rounded-full shrink-0", {
                    "bg-state-accept": step.status === "ok",
                    "bg-state-verify": step.status === "warn",
                    "bg-state-escalate": step.status === "fail",
                  })}
                />
                <span className="font-mono text-[11px] text-foreground/82 w-36 shrink-0">
                  {step.label}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground/72 flex-1 truncate">
                  {step.detail}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground/58 tabular-nums shrink-0">
                  {step.duration_ms}ms
                </span>
              </div>
            ))}
          </div>
          <div className="mt-1 font-mono text-[10px] text-muted-foreground/52 text-right">
            {trace.request_id}
          </div>
        </section>

        {/* Evidence */}
        {trace.evidence.length > 0 && (
          <section>
            <SectionLabel>Evidence Retrieved</SectionLabel>
            <div className="mt-2 border border-border divide-y divide-border/40">
              {trace.evidence.map((e, i) => (
                <div key={i} className="flex items-baseline gap-3 px-3 py-2">
                  <span className="font-mono text-[11px] text-foreground/80 shrink-0 font-medium">
                    {e.source}
                  </span>
                  <span className="font-mono text-[10px] text-muted-foreground/68 shrink-0">
                    {e.section}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground/82 flex-1 truncate">
                    {e.snippet}
                  </span>
                  <span className="font-mono text-[10px] text-muted-foreground/58 shrink-0 tabular-nums">
                    {e.score} · {e.fresh_days}d
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Download envelope */}
        <section>
          <button
            onClick={() => downloadEnvelope(trace, sc, queryOverride)}
            className="w-full font-mono text-[11px] border border-border/60 px-4 py-2.5 text-muted-foreground/72 hover:text-foreground/85 hover:border-foreground/30 transition-colors flex items-center gap-2"
          >
            <span>↓</span>
            <span>Download decision envelope</span>
            <span className="text-muted-foreground/52">
              JSON · request + oracle scores + policy trace
            </span>
            <span className="ml-auto text-muted-foreground/45 font-mono text-[10px]">
              {trace.request_id}
            </span>
          </button>
        </section>
      </div>
    </div>
  );
}

export const PipelinePanel = React.memo(PipelinePanelRaw);
