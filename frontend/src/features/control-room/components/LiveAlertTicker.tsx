import { cn } from "@/lib/utils";
import type { LiveAlert } from "../types";
import { VERDICT_TICKER } from "../styles";

export function LiveAlertTicker({ alerts }: { alerts: LiveAlert[] }) {
  if (alerts.length === 0) {
    return (
      <div className="shrink-0 border-b border-border bg-muted/5 px-5 py-1.5 flex items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/58">
          Live feed
        </span>
        <span className="font-mono text-[11px] text-muted-foreground/48">
          — awaiting platform telemetry
        </span>
      </div>
    );
  }

  return (
    <div
      className="shrink-0 border-b border-border bg-muted/5 flex items-center overflow-hidden"
      style={{ height: "30px" }}
    >
      <div className="shrink-0 font-mono text-[11px] uppercase tracking-wider text-muted-foreground/62 px-4 border-r border-border/40 h-full flex items-center">
        Live
      </div>
      <div className="flex-1 overflow-hidden relative">
        <div
          className="flex items-center gap-4 px-4 absolute whitespace-nowrap"
          style={{
            animation: alerts.length > 0 ? "ticker-scroll 60s linear infinite" : "none",
          }}
        >
          {[...alerts, ...alerts].map((a, i) => (
            <span
              key={`${a.id}-${i}`}
              className="flex items-center gap-2 font-mono text-[11px] shrink-0"
            >
              <span className="text-muted-foreground/62">{a.ts}</span>
              <span className="text-muted-foreground/75">{a.platform}</span>
              <span className="text-foreground/80">{a.title}</span>
              <span className={cn("uppercase font-medium", VERDICT_TICKER[a.verdict])}>
                {a.verdict}
              </span>
              <span className="text-border/40 mx-1">·</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
