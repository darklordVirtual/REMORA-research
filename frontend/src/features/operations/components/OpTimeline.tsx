import { cn } from "@/lib/utils";
import type { OpActivity } from "../types";

const STATUS_DOT: Record<OpActivity["status"], string> = {
  planned: "bg-muted-foreground/30",
  in_progress: "bg-signal animate-pulse",
  delayed: "bg-state-verify",
  completed: "bg-state-accept",
  blocked: "bg-state-escalate",
};

const STATUS_GLOW: Record<OpActivity["status"], string> = {
  planned: "",
  in_progress: "shadow-[0_0_8px_rgba(0,0,0,0.06)]",
  delayed: "",
  completed: "",
  blocked: "",
};

export function OpTimeline({
  activities,
  selectedId,
  onSelect,
}: {
  activities: OpActivity[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const nowIndex = activities.findIndex((a) =>
    ["in_progress", "delayed", "blocked"].includes(a.status),
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground/60 px-2 mb-1">
        Live Operational Plan
      </div>
      {activities.map((act, idx) => {
        const isCurrent = idx === nowIndex;
        const done = act.steps.filter((s) => s.status === "completed").length;
        const total = act.steps.length;
        const pct = Math.round((done / total) * 100);

        return (
          <button
            key={act.id}
            onClick={() => onSelect(act.id)}
            className={cn(
              "w-full text-left border p-3.5 transition-all duration-200 group relative",
              act.status === "blocked"
                ? "border-state-escalate/40 bg-state-escalate/[0.02]"
                : act.status === "delayed"
                  ? "border-state-verify/40 bg-state-verify/[0.02]"
                  : act.status === "in_progress"
                    ? "border-signal/40 bg-signal/[0.015]"
                    : act.status === "completed"
                      ? "border-state-accept/30 bg-state-accept/[0.01]"
                      : "border-border/30",
              selectedId === act.id
                ? "bg-foreground/[0.03] shadow-sm"
                : "hover:bg-muted/[0.04] hover:border-foreground/20",
              STATUS_GLOW[act.status],
            )}
          >
            {/* Current indicator */}
            {isCurrent && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-8 bg-signal/60 rounded-r-full" />
            )}

            <div className="flex items-center gap-2 mb-2">
              <span className={cn("h-2 w-2 rounded-full shrink-0", STATUS_DOT[act.status])} />
              <span className="font-mono text-[10px] text-muted-foreground/55 uppercase tracking-wider">
                {act.plannedStart}–{act.plannedEnd}
              </span>
              {isCurrent && (
                <span className="ml-auto font-mono text-[9px] text-signal/70 uppercase tracking-wider border border-signal/20 px-1">
                  NOW
                </span>
              )}
              {act.deviation && (
                <span className="ml-auto font-mono text-[9px] text-state-escalate/75 uppercase tracking-wider">
                  ⚠ DEVIATION
                </span>
              )}
            </div>

            <div className="font-mono text-[11px] text-foreground/90 leading-snug font-medium group-hover:text-foreground transition-colors">
              {act.title}
            </div>

            <div className="flex items-center gap-2 mt-1.5">
              <span className="font-mono text-[9px] text-muted-foreground/50 uppercase tracking-wider">
                {act.category}
              </span>
              <span className="text-border/60">·</span>
              <span className="font-mono text-[9px] text-muted-foreground/45 truncate">
                {act.crew.split("(")[0].trim()}
              </span>
              <span className="text-border/60">·</span>
              <span className="font-mono text-[9px] text-muted-foreground/45 tabular-nums">
                {done}/{total}
              </span>
            </div>

            {/* Progress bar */}
            <div className="mt-2 w-full h-[2px] bg-border/20 rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  act.status === "completed"
                    ? "bg-state-accept/50"
                    : act.status === "blocked"
                      ? "bg-state-escalate/50"
                      : act.status === "delayed"
                        ? "bg-state-verify/50"
                        : "bg-signal/40",
                )}
                style={{ width: `${pct}%` }}
              />
            </div>

            {act.deviation && (
              <div className="mt-1.5 font-mono text-[10px] text-state-escalate/65 leading-relaxed">
                {act.deviation}
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}
