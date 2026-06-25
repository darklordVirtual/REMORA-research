import { cn } from "@/lib/utils";
import type { ThermoSnapshot } from "@/lib/remora-sim";

const phaseColor: Record<ThermoSnapshot["phase"], string> = {
  ordered: "bg-state-accept",
  critical: "bg-state-verify",
  disordered: "bg-state-escalate",
};

export function PhaseMeter({ thermo }: { thermo: ThermoSnapshot }) {
  const metrics = [
    {
      k: "T",
      label: "Temperature",
      v: thermo.T,
      max: 1.6,
      hint: "stochastic spread across oracles",
    },
    { k: "H", label: "Entropy", v: thermo.H, max: 1.6, hint: "answer distribution entropy (nats)" },
    { k: "D", label: "Dissensus", v: thermo.D, max: 1, hint: "1 − max(p)" },
    { k: "F", label: "Trust gap", v: thermo.F, max: 1, hint: "free-energy proxy" },
  ];

  return (
    <div className="border border-border p-5">
      <div className="flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Phase analysis
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", phaseColor[thermo.phase])} />
          <span className="font-mono text-xs uppercase tracking-widest">{thermo.phase}</span>
        </div>
      </div>
      <div className="mt-2 font-serif text-3xl tracking-tight">
        trust {(thermo.trust * 100).toFixed(0)}
        <span className="text-muted-foreground text-base">/100</span>
      </div>
      <div className="mt-6 space-y-4">
        {metrics.map((m) => (
          <div key={m.k}>
            <div className="flex items-baseline justify-between">
              <div className="font-mono text-[11px]">
                <span className="text-foreground">{m.k}</span>
                <span className="text-muted-foreground ml-2">{m.label}</span>
              </div>
              <div className="font-mono text-xs tabular-nums">{m.v.toFixed(3)}</div>
            </div>
            <div className="mt-1.5 h-1 bg-muted">
              <div
                className={cn("h-full", phaseColor[thermo.phase])}
                style={{ width: `${Math.min(100, (m.v / m.max) * 100)}%` }}
              />
            </div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">{m.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
