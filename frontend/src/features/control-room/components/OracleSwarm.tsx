import { cn } from "@/lib/utils";
import type { OracleVote } from "@/lib/remora-sim";
import { FAMILY_DOT } from "../styles";

export function OracleSwarm({ votes }: { votes: OracleVote[] }) {
  const counts = new Map<string, number>();
  for (const v of votes) counts.set(v.answer, (counts.get(v.answer) ?? 0) + 1);
  const dominant = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const agreement = (counts.get(dominant ?? "") ?? 0) / votes.length;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 font-mono text-[11px]">
        <span className="text-muted-foreground/75 shrink-0">Agreement</span>
        <div className="flex-1 h-1.5 bg-border/30 rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              agreement >= 0.75
                ? "bg-state-accept"
                : agreement >= 0.5
                  ? "bg-state-verify"
                  : "bg-state-escalate/60",
            )}
            style={{ width: `${agreement * 100}%` }}
          />
        </div>
        <span
          className={cn(
            "tabular-nums font-medium shrink-0",
            agreement >= 0.75
              ? "text-state-accept"
              : agreement >= 0.5
                ? "text-state-verify"
                : "text-state-escalate/80",
          )}
        >
          {Math.round(agreement * 100)}%
        </span>
        <span className="text-muted-foreground/58 shrink-0">{counts.size} distinct answers</span>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        {votes.map((v) => {
          const wins = v.answer === dominant;
          const lowConf = v.confidence < 0.5;
          const roleLabel = wins ? "MAJORITY" : lowConf ? "LOW CONF" : "DISSENTER";
          const roleCls = wins
            ? "border-state-accept/35 text-state-accept/75 bg-state-accept/8"
            : lowConf
              ? "border-border/30 text-muted-foreground/68"
              : "border-state-escalate/30 text-state-escalate/65";
          return (
            <div
              key={v.oracle}
              className={cn(
                "border p-3 space-y-2",
                wins ? "border-state-accept/30 bg-state-accept/5" : "border-border/50",
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full shrink-0",
                    FAMILY_DOT[v.family] ?? "bg-border",
                  )}
                />
                <span className="font-mono text-[11px] truncate text-muted-foreground/80 flex-1">
                  {v.oracle}
                </span>
                <span
                  className={cn(
                    "font-mono text-[8px] uppercase tracking-wider border px-1.5 py-px shrink-0",
                    roleCls,
                  )}
                >
                  {roleLabel}
                </span>
              </div>
              <div className="font-mono text-[11px] leading-snug line-clamp-2 text-foreground/85">
                {v.answer}
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between font-mono text-[11px]">
                  <span className="text-muted-foreground/68">Confidence</span>
                  <span
                    className={cn(
                      "tabular-nums font-medium",
                      lowConf ? "text-state-escalate/60" : "",
                    )}
                  >
                    {(v.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="h-1 bg-border/25 overflow-hidden">
                  <div
                    className={cn(
                      "h-full transition-all",
                      wins
                        ? "bg-state-accept/60"
                        : lowConf
                          ? "bg-state-escalate/35"
                          : "bg-state-verify/50",
                    )}
                    style={{ width: `${v.confidence * 100}%` }}
                  />
                </div>
              </div>
              <div className="font-mono text-[11px] text-muted-foreground/58 tabular-nums">
                {v.latency_ms}ms · {v.tokens} tokens
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
