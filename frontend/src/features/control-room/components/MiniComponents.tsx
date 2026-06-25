import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[11px] uppercase tracking-[0.13em] text-muted-foreground">
      {children}
    </div>
  );
}

export function MetaRow({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="font-mono text-[11px]">
      <span className="text-muted-foreground/72">{k} </span>
      <span className="text-foreground/80">{v}</span>
    </div>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const cls: Record<string, string> = {
    low: "text-state-accept",
    medium: "text-state-verify",
    high: "text-orange-400",
    critical: "text-state-escalate font-medium",
  };
  return <span className={cn("uppercase tracking-wider", cls[risk] ?? "")}>{risk}</span>;
}

export function SectorChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "font-mono text-[11px] uppercase tracking-wider px-2 py-0.5 border transition-colors",
        active
          ? "border-foreground/50 text-foreground bg-foreground/5"
          : "border-border/40 text-muted-foreground/75 hover:border-foreground/25 hover:text-muted-foreground",
      )}
    >
      {label}
    </button>
  );
}

import type { CRScenario } from "../types";
import { STAGE_LABELS } from "../data";

export function RunningPanel({ sc, queryOverride }: { sc: CRScenario; queryOverride?: string }) {
  const isCustom = queryOverride && queryOverride !== sc.query;
  const subtitle = isCustom
    ? queryOverride.slice(0, 90) + (queryOverride.length > 90 ? "…" : "")
    : sc.proposed_action;
  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 p-10">
      <div className="text-center space-y-2 max-w-sm">
        <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/68">
          REMORA evaluating
        </div>
        <div className="font-serif text-2xl tracking-tight">
          {isCustom ? "Custom query" : sc.title}
        </div>
        <div className="font-mono text-xs text-muted-foreground/75 leading-relaxed">{subtitle}</div>
      </div>
      <div className="w-full max-w-xs space-y-3">
        {STAGE_LABELS.map((s, i) => (
          <div key={s.key} className="flex items-center gap-3">
            <span
              className="h-2 w-2 rounded-full bg-signal animate-pulse shrink-0"
              style={{ animationDelay: `${i * 130}ms` }}
            />
            <div>
              <div className="font-mono text-[11px] text-foreground/82">{s.key}</div>
              <div className="font-mono text-[11px] text-muted-foreground/62">{s.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function EmptyPanel() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 px-8 text-center">
      <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/48">
        Select a scenario to route a decision
      </div>
      <div className="font-mono text-[11px] text-muted-foreground/38 max-w-xs leading-relaxed">
        AI agents handle volume autonomously · human authority engaged at every safety threshold
      </div>
    </div>
  );
}
