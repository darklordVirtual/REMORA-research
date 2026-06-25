import { cn } from "@/lib/utils";
import type { CRScenario } from "../types";
import { EXPECTED_BADGE, EXPECTED_STRIPE, RISK_STRIPE } from "../styles";

const RISK_LABEL: Record<string, string> = {
  low: "●",
  medium: "●",
  high: "●",
  critical: "●",
};

export function ScenarioCard({
  sc,
  isActive,
  spinnerOn,
  onClick,
}: {
  sc: CRScenario;
  isActive: boolean;
  spinnerOn: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-4 py-3.5 transition-all duration-200 border-l-2 group relative",
        isActive
          ? cn(
              "bg-foreground/[0.04] shadow-[inset_0_0_20px_rgba(255,255,255,0.02)]",
              EXPECTED_STRIPE[sc.expected],
            )
          : cn("border-l-transparent hover:bg-muted/[0.08] hover:border-l-border/40"),
      )}
    >
      {/* Subtle top gradient line for active */}
      {isActive && (
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-foreground/10 to-transparent" />
      )}

      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base shrink-0 opacity-70 group-hover:opacity-100 transition-opacity">
            {sc.icon}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/65 truncate">
            {sc.sector}
          </span>
          {sc.risk && (
            <span
              className={cn(
                "text-[8px] leading-none",
                RISK_STRIPE[sc.risk]?.replace("bg-", "text-"),
              )}
              title={`Risk: ${sc.risk}`}
            >
              {RISK_LABEL[sc.risk]}
            </span>
          )}
        </div>
        <span
          className={cn(
            "font-mono text-[10px] border px-1.5 py-px uppercase tracking-wider shrink-0 transition-all",
            EXPECTED_BADGE[sc.expected],
            isActive && "shadow-sm",
          )}
        >
          {spinnerOn ? (
            <span className="inline-flex items-center gap-1">
              <span className="h-1 w-1 rounded-full bg-current animate-pulse" />
              RUN
            </span>
          ) : (
            sc.expected
          )}
        </span>
      </div>

      <div className="font-mono text-[11px] text-foreground/90 leading-snug font-medium group-hover:text-foreground transition-colors">
        {sc.title}
      </div>

      <div className="mt-1.5 font-mono text-[10px] text-muted-foreground/60 leading-relaxed line-clamp-2">
        {sc.blurb}
      </div>

      {/* Bias indicator */}
      {sc.bias !== undefined && (
        <div className="mt-2 flex items-center gap-1.5">
          <div className="flex-1 h-[2px] bg-border/30 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                sc.bias > 0.7
                  ? "bg-state-accept/60"
                  : sc.bias > 0.4
                    ? "bg-state-verify/60"
                    : "bg-state-escalate/60",
              )}
              style={{ width: `${sc.bias * 100}%` }}
            />
          </div>
          <span className="font-mono text-[9px] text-muted-foreground/45 tabular-nums">
            {(sc.bias * 100).toFixed(0)}%
          </span>
        </div>
      )}
    </button>
  );
}
