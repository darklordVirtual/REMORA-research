import { cn } from "@/lib/utils";
import type { ThermoSnapshot } from "@/lib/remora-sim";
import { phaseText } from "../styles";

export function PhaseSpectrum({ thermo }: { thermo: ThermoSnapshot }) {
  const pos = Math.min(thermo.D, 1);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between font-mono text-[11px]">
        <span className="text-state-accept/70">ORDERED</span>
        <span className={cn("uppercase tracking-widest font-semibold", phaseText(thermo.phase))}>
          {thermo.phase}
        </span>
        <span className="text-state-escalate/70">DISORDERED</span>
      </div>
      <div className="relative h-3 rounded-sm overflow-hidden bg-gradient-to-r from-state-accept/20 via-state-verify/15 to-state-escalate/20 border border-border/30">
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-foreground/80"
          style={{ left: `${pos * 100}%`, transition: "left 0.6s ease" }}
        />
      </div>
      <div className="font-mono text-[11px] text-muted-foreground/68">
        D = {thermo.D.toFixed(3)} · oracle dissensus index
      </div>
    </div>
  );
}

export function ThermoGrid({ thermo }: { thermo: ThermoSnapshot }) {
  const items = [
    { k: "T", v: thermo.T.toFixed(3), hint: "Temperature" },
    { k: "H", v: thermo.H.toFixed(3), hint: "Entropy" },
    { k: "D", v: thermo.D.toFixed(3), hint: "Dissensus" },
    { k: "F", v: thermo.F.toFixed(4), hint: "Free energy" },
    { k: "Trust", v: (thermo.trust * 100).toFixed(0) + "%", hint: "Trust score" },
  ];
  return (
    <div className="border border-border/50 p-3.5">
      <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/62 mb-3">
        F = λD − TH · λ = 0.3
      </div>
      <div className="grid grid-cols-5 gap-2">
        {items.map(({ k, v }) => (
          <div key={k} className="text-center">
            <div className="font-mono text-xs text-foreground/85 tabular-nums">{v}</div>
            <div className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground/68 mt-1 leading-none">
              {k}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ThermoCompact({ thermo }: { thermo: ThermoSnapshot }) {
  const pos = Math.min(thermo.D, 1);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] text-state-accept/70 shrink-0">ordered</span>
        <div className="relative flex-1 h-2 overflow-hidden bg-gradient-to-r from-state-accept/20 via-state-verify/15 to-state-escalate/20 border border-border/30">
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-foreground/80"
            style={{ left: `${pos * 100}%`, transition: "left 0.6s ease" }}
          />
        </div>
        <span className="font-mono text-[10px] text-state-escalate/70 shrink-0">disordered</span>
        <span
          className={cn(
            "font-mono text-[11px] uppercase font-semibold shrink-0 w-20 text-right",
            phaseText(thermo.phase),
          )}
        >
          {thermo.phase}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted-foreground/68">
        <span>T={thermo.T.toFixed(3)}</span>
        <span>H={thermo.H.toFixed(3)}</span>
        <span>D={thermo.D.toFixed(3)}</span>
        <span>F={thermo.F.toFixed(4)}</span>
        <span className="text-muted-foreground/45">·</span>
        <span className="text-muted-foreground/52 text-[10px]">V(t)=H+λD, λ=0.3</span>
        <span className="ml-auto font-medium text-foreground/75">
          Trust {(thermo.trust * 100).toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
