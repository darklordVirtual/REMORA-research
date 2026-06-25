import { DecisionChip } from "@/components/primitives";
import type { DecisionTrace } from "@/lib/remora-sim";

export function DecisionCard({ trace }: { trace: DecisionTrace }) {
  return (
    <div className="border border-foreground p-5">
      <div className="flex items-center justify-between">
        <DecisionChip state={trace.verdict} />
        <div className="font-mono text-[10px] text-muted-foreground">
          {trace.request_id} · {trace.total_latency_ms} ms
        </div>
      </div>
      <p className="mt-4 font-serif text-2xl leading-tight tracking-tight">{trace.reason}.</p>
      <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-[11px]">
        <div className="text-muted-foreground">domain</div>
        <div className="text-right">{trace.intent.domain}</div>
        <div className="text-muted-foreground">risk</div>
        <div className="text-right uppercase">{trace.intent.risk}</div>
        <div className="text-muted-foreground">phase</div>
        <div className="text-right uppercase">{trace.thermo.phase}</div>
        <div className="text-muted-foreground">trust</div>
        <div className="text-right tabular-nums">{(trace.thermo.trust * 100).toFixed(0)}/100</div>
        <div className="text-muted-foreground">approval</div>
        <div className="text-right">{trace.approval_required ? "required" : "not required"}</div>
        <div className="text-muted-foreground">policy</div>
        <div className="text-right">{trace.policy.version}</div>
      </dl>
    </div>
  );
}
