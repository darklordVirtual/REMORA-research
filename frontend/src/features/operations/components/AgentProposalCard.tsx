import { cn } from "@/lib/utils";
import type { AgentProposal } from "../types";
import { verdictText, verdictBorderBg } from "@/features/control-room/styles";

export function AgentProposalCard({
  proposal,
  isSelected,
  onClick,
}: {
  proposal: AgentProposal;
  isSelected: boolean;
  onClick: () => void;
}) {
  const v = proposal.trace.verdict;
  const auto = v === "ACCEPT";
  const blocked = v === "ESCALATE" || v === "ABSTAIN";

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left border p-3.5 transition-colors space-y-2",
        isSelected
          ? cn(
              "bg-foreground/4",
              blocked
                ? "border-state-escalate/50"
                : auto
                  ? "border-state-accept/50"
                  : "border-state-verify/50",
            )
          : "border-border/40 hover:border-border/70 hover:bg-muted/5",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-foreground/85 truncate">{proposal.title}</span>
        <span
          className={cn(
            "font-mono text-[10px] border px-1.5 py-px uppercase tracking-wider shrink-0",
            verdictBorderBg(v),
            verdictText(v),
          )}
        >
          {v}
        </span>
      </div>

      <div className="font-mono text-[10px] text-muted-foreground/68 leading-relaxed">
        {proposal.trigger}
      </div>

      <div className="border-l-2 border-signal/30 pl-3 font-mono text-[11px] text-foreground/80 leading-relaxed italic">
        “{proposal.proposedAction}”
      </div>

      <div className="flex items-center gap-3 font-mono text-[10px] text-muted-foreground/55">
        <span className="tabular-nums">
          Trust {(proposal.trace.thermo.trust * 100).toFixed(0)}%
        </span>
        <span>·</span>
        <span className="tabular-nums">{proposal.trace.total_latency_ms}ms</span>
        <span>·</span>
        <span>{proposal.trace.policy.triggers.length} policy hits</span>
      </div>
    </button>
  );
}
