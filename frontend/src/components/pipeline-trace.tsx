import { cn } from "@/lib/utils";
import type { DecisionTrace, PipelineStep } from "@/lib/remora-sim";

function statusDot(s: PipelineStep["status"]) {
  return s === "fail" ? "bg-state-escalate" : s === "warn" ? "bg-state-verify" : "bg-state-accept";
}

export function PipelineTrace({ trace }: { trace: DecisionTrace }) {
  const max = Math.max(...trace.steps.map((s) => s.duration_ms));
  return (
    <ol className="border border-border">
      {trace.steps.map((s, i) => (
        <li
          key={s.id}
          className={cn(
            "grid grid-cols-[28px_140px_1fr_80px] items-center gap-4 p-4",
            i > 0 && "border-t border-border",
          )}
        >
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full", statusDot(s.status))} />
            <span className="font-mono text-[10px] text-muted-foreground">
              {String(i + 1).padStart(2, "0")}
            </span>
          </div>
          <div className="font-mono text-xs uppercase tracking-wider">{s.label}</div>
          <div className="text-sm text-muted-foreground truncate">{s.detail}</div>
          <div className="relative h-1.5 bg-muted">
            <div
              className={cn("absolute inset-y-0 left-0", statusDot(s.status))}
              style={{ width: `${Math.max(6, (s.duration_ms / max) * 100)}%` }}
            />
            <div className="absolute -top-4 right-0 font-mono text-[10px] tabular-nums text-muted-foreground">
              {s.duration_ms}ms
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
