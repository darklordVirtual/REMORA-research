import { cn } from "@/lib/utils";
import type { OracleVote } from "@/lib/remora-sim";

export function OracleBoard({ votes }: { votes: OracleVote[] }) {
  const counts = new Map<string, number>();
  for (const v of votes) counts.set(v.answer, (counts.get(v.answer) ?? 0) + 1);
  const winning = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];

  return (
    <div className="border border-border">
      <div className="flex items-center justify-between border-b border-border p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Oracle votes
        </div>
        <div className="font-mono text-[11px] text-muted-foreground">
          {votes.length} oracles · {counts.size} distinct answer{counts.size === 1 ? "" : "s"}
        </div>
      </div>
      <ul className="divide-y divide-border">
        {votes.map((v) => {
          const agrees = v.answer === winning;
          return (
            <li key={v.oracle} className="grid grid-cols-[1fr_auto] gap-4 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      agrees ? "bg-state-accept" : "bg-state-verify",
                    )}
                  />
                  <span className="font-mono text-xs">{v.oracle}</span>
                </div>
                <div className="mt-1 text-sm truncate">{v.answer}</div>
              </div>
              <div className="text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                <div>{(v.confidence * 100).toFixed(0)}% conf</div>
                <div>
                  {v.latency_ms}ms · {v.tokens}t
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
