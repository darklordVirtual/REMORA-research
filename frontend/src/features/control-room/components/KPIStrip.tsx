import React, { useEffect, useRef, useState } from "react";
import type { SessionKPI } from "../types";
import { cn } from "@/lib/utils";

function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const [display, setDisplay] = useState(0);
  const prevRef = useRef(value);

  useEffect(() => {
    const from = prevRef.current;
    const to = value;
    const duration = 400;
    const start = performance.now();
    let raf: number;

    const tick = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(from + (to - from) * eased));
      if (progress < 1) raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    prevRef.current = value;
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <span className={className}>{display}</span>;
}

export function KPIStrip({ kpi }: { kpi: SessionKPI }) {
  const avg = kpi.runs > 0 ? Math.round(kpi.total_ms / kpi.runs) : 0;
  const autoRate = kpi.runs > 0 ? ((kpi.accept + kpi.verify) / kpi.runs) * 100 : 0;
  const blockRate = kpi.runs > 0 ? ((kpi.escalate + kpi.abstain) / kpi.runs) * 100 : 0;

  const verdicts = [
    { label: "Accept", value: kpi.accept, color: "bg-state-accept", text: "text-state-accept" },
    { label: "Verify", value: kpi.verify, color: "bg-state-verify", text: "text-state-verify" },
    {
      label: "Abstain",
      value: kpi.abstain,
      color: "bg-state-abstain",
      text: "text-muted-foreground/60",
    },
    {
      label: "Escalate",
      value: kpi.escalate,
      color: "bg-state-escalate",
      text: "text-state-escalate",
    },
  ];

  const meta = [
    {
      label: "Blocked autonomous",
      value: kpi.unsafe_prevented,
      cls: "text-state-escalate font-medium",
    },
    { label: "Ptil audit entries", value: kpi.audit_entries, cls: "text-muted-foreground/82" },
    {
      label: "Avg ms",
      value: avg > 0 ? `${avg}` : "—",
      cls: "text-muted-foreground/82",
      suffix: "ms",
    },
  ];

  return (
    <div className="shrink-0 border-b border-border/60 bg-background">
      {/* Top row: verdicts with progress */}
      <div className="flex items-stretch gap-px bg-border/30 overflow-x-auto">
        {verdicts.map(({ label, value, color, text }) => (
          <div
            key={label}
            className="flex flex-col items-center justify-center bg-background px-5 py-2.5 min-w-[90px] shrink-0 relative"
          >
            <div
              className={cn(
                "font-serif text-2xl tracking-tight tabular-nums leading-none animate-count-up",
                text,
              )}
            >
              <AnimatedNumber value={value} />
            </div>
            <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60 mt-1.5 text-center leading-tight">
              {label}
            </div>
            {/* Mini progress dot */}
            {kpi.runs > 0 && (
              <div className="absolute top-1.5 right-1.5">
                <span className={cn("h-1.5 w-1.5 rounded-full block", color)} />
              </div>
            )}
          </div>
        ))}

        {/* Autonomy rate */}
        <div className="flex flex-col items-center justify-center bg-background px-5 py-2.5 min-w-[100px] shrink-0">
          <div className="font-serif text-2xl tracking-tight tabular-nums leading-none text-state-accept">
            {kpi.runs > 0 ? <AnimatedNumber value={Math.round(autoRate)} /> : "—"}
            <span className="text-sm text-muted-foreground/40">%</span>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60 mt-1.5 text-center leading-tight">
            Autonomy
          </div>
          {kpi.runs > 0 && (
            <div className="w-12 h-0.5 bg-border/40 mt-1.5 rounded-full overflow-hidden">
              <div
                className="h-full bg-state-accept transition-all duration-500 ease-out"
                style={{ width: `${autoRate}%` }}
              />
            </div>
          )}
        </div>

        {/* Block rate */}
        <div className="flex flex-col items-center justify-center bg-background px-5 py-2.5 min-w-[100px] shrink-0">
          <div className="font-serif text-2xl tracking-tight tabular-nums leading-none text-state-escalate">
            {kpi.runs > 0 ? <AnimatedNumber value={Math.round(blockRate)} /> : "—"}
            <span className="text-sm text-muted-foreground/40">%</span>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60 mt-1.5 text-center leading-tight">
            Human gate
          </div>
          {kpi.runs > 0 && (
            <div className="w-12 h-0.5 bg-border/40 mt-1.5 rounded-full overflow-hidden">
              <div
                className="h-full bg-state-escalate transition-all duration-500 ease-out"
                style={{ width: `${blockRate}%` }}
              />
            </div>
          )}
        </div>

        {/* Meta items */}
        {meta.map(({ label, value, cls, suffix }) => (
          <div
            key={label}
            className="flex flex-col items-center justify-center bg-background px-5 py-2.5 min-w-[100px] shrink-0 border-l border-border/20"
          >
            <div className={cn("font-serif text-xl tracking-tight tabular-nums leading-none", cls)}>
              <AnimatedNumber value={typeof value === "number" ? value : 0} />
              {suffix && <span className="text-xs text-muted-foreground/40 ml-0.5">{suffix}</span>}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/55 mt-1.5 text-center leading-tight">
              {label}
            </div>
          </div>
        ))}
      </div>

      {/* Bottom mini progress bar: verdict distribution */}
      {kpi.runs > 0 && (
        <div className="flex h-[3px] bg-border/20">
          {verdicts.map(({ value, color }) => (
            <div
              key={color}
              className={cn("transition-all duration-700 ease-out", color)}
              style={{ width: `${kpi.runs > 0 ? (value / kpi.runs) * 100 : 0}%` }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
