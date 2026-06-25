import { cn } from "@/lib/utils";
import type { OpActivity } from "../types";

const STEP_DOT: Record<OpStep["status"], string> = {
  pending: "bg-border",
  in_progress: "bg-signal animate-pulse",
  completed: "bg-state-accept",
  failed: "bg-state-escalate",
};

interface OpStep {
  id: string;
  label: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  detail?: string;
}

export function ProcedurePanel({ activity }: { activity: OpActivity }) {
  const done = activity.steps.filter((s) => s.status === "completed").length;
  const total = activity.steps.length;
  const pct = Math.round((done / total) * 100);

  return (
    <div className="border border-border/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground/62">
          Procedure {activity.procedureRef}
        </div>
        <span className="font-mono text-[10px] text-muted-foreground/55 tabular-nums">
          {done}/{total} steps · {pct}%
        </span>
      </div>

      <div className="relative pl-4 space-y-3">
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border/40" />
        {activity.steps.map((step, i) => (
          <div key={step.id} className="relative flex gap-3">
            <div
              className={cn(
                "absolute left-[-11px] top-1 h-2.5 w-2.5 rounded-full border border-background z-10",
                STEP_DOT[step.status],
              )}
            />
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[11px] text-foreground/82">{step.label}</div>
              {step.detail && (
                <div className="font-mono text-[10px] text-muted-foreground/65 mt-0.5">
                  {step.detail}
                </div>
              )}
            </div>
            <span
              className={cn(
                "font-mono text-[9px] uppercase tracking-wider px-1.5 py-px border shrink-0 h-fit",
                step.status === "completed"
                  ? "border-state-accept/30 text-state-accept/70 bg-state-accept/5"
                  : step.status === "in_progress"
                    ? "border-signal/40 text-signal/70 bg-signal/5"
                    : step.status === "failed"
                      ? "border-state-escalate/30 text-state-escalate/70 bg-state-escalate/5"
                      : "border-border/30 text-muted-foreground/50",
              )}
            >
              {step.status.replace("_", " ")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
