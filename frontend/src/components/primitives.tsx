import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SectionLabel({ number, children }: { number?: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
      {number && <span className="text-foreground">{number}</span>}
      <span className="h-px w-8 bg-border" />
      <span>{children}</span>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  lede,
}: {
  eyebrow: string;
  title: string;
  lede?: string;
}) {
  return (
    <div className="max-w-3xl">
      <SectionLabel>{eyebrow}</SectionLabel>
      <h1 className="mt-6 font-serif text-5xl md:text-6xl leading-[1.05] tracking-tight">
        {title}
      </h1>
      {lede && (
        <p className="mt-6 text-lg text-muted-foreground leading-relaxed max-w-2xl">{lede}</p>
      )}
    </div>
  );
}

export function Callout({
  title,
  children,
  tone = "muted",
}: {
  title: string;
  children: ReactNode;
  tone?: "muted" | "warn";
}) {
  return (
    <aside
      className={cn(
        "border-l-2 pl-5 py-4 my-8",
        tone === "warn" ? "border-state-escalate" : "border-signal",
      )}
    >
      <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </div>
      <div className="mt-2 text-sm leading-relaxed">{children}</div>
    </aside>
  );
}

const stateClasses: Record<string, string> = {
  ACCEPT: "text-state-accept border-state-accept",
  VERIFY: "text-state-verify border-state-verify",
  ABSTAIN: "text-state-abstain border-state-abstain",
  ESCALATE: "text-state-escalate border-state-escalate",
};

export function DecisionChip({ state }: { state: keyof typeof stateClasses }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border px-2 py-0.5 font-mono text-[11px] tracking-widest",
        stateClasses[state],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {state}
    </span>
  );
}

export function EvidenceTable({
  cols,
  rows,
  caption,
}: {
  cols: string[];
  rows: string[][];
  caption?: string;
}) {
  return (
    <figure className="my-8">
      <div className="overflow-x-auto border-y border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              {cols.map((c, i) => (
                <th
                  key={c}
                  className={cn(
                    "px-4 py-3 font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground font-normal",
                    i === 0 ? "text-left" : "text-right",
                  )}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border/60 last:border-0">
                {row.map((cell, j) => (
                  <td
                    key={j}
                    className={cn(
                      "px-4 py-3",
                      j === 0 ? "text-left font-medium" : "text-right font-mono tabular-nums",
                    )}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {caption && (
        <figcaption className="mt-3 text-xs text-muted-foreground italic">{caption}</figcaption>
      )}
    </figure>
  );
}

export function Cite({ id }: { id: string }) {
  return (
    <a
      href={`/whitepaper#cite-${id}`}
      className="font-mono text-[10px] align-super text-signal hover:underline"
    >
      [{id}]
    </a>
  );
}
