import React from "react";
import { cn } from "@/lib/utils";
import type { EscalationItem, AutoHandled, ReviewStatus } from "../types";
import { RISK_BADGE, statusPillClass, STATUS_LABEL, canOpenEscalation } from "../styles";

function EscalationInboxRaw({
  items,
  autoHandled,
  activeTab,
  onTabChange,
  onOpen,
  onDecide,
  onDismiss,
  onDismissAll,
  height,
}: {
  items: EscalationItem[];
  autoHandled: AutoHandled[];
  activeTab: "escalations" | "auto";
  onTabChange: (tab: "escalations" | "auto") => void;
  onOpen: (item: EscalationItem) => void;
  onDecide: (id: number, decision: ReviewStatus) => void;
  onDismiss: (id: number) => void;
  onDismissAll: () => void;
  height: number;
}) {
  const pending = items.filter((i) => canOpenEscalation(i.status));
  const resolved = items.filter((i) => !canOpenEscalation(i.status));
  const HEADER_H = 36;

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Tab bar */}
      <div
        className="shrink-0 flex items-stretch border-b border-border bg-background/98"
        style={{ height: HEADER_H }}
      >
        <button
          onClick={() => onTabChange("escalations")}
          className={cn(
            "flex items-center gap-2 px-5 font-mono text-[11px] uppercase tracking-[0.10em] border-r border-border transition-colors",
            activeTab === "escalations"
              ? "text-state-escalate/80 bg-state-escalate/4"
              : "text-muted-foreground/68 hover:text-muted-foreground/82",
          )}
        >
          Escalations
          {pending.length > 0 && (
            <span className="font-mono text-[11px] bg-state-escalate/15 text-state-escalate border border-state-escalate/30 px-1.5 py-px tabular-nums">
              {pending.length}
            </span>
          )}
        </button>
        <button
          onClick={() => onTabChange("auto")}
          className={cn(
            "flex items-center gap-2 px-5 font-mono text-[11px] uppercase tracking-[0.10em] border-r border-border transition-colors",
            activeTab === "auto"
              ? "text-state-accept/80 bg-state-accept/4"
              : "text-muted-foreground/68 hover:text-muted-foreground/82",
          )}
        >
          Auto-handled
          {autoHandled.length > 0 && (
            <span className="font-mono text-[11px] bg-state-accept/10 text-state-accept/70 border border-state-accept/25 px-1.5 py-px tabular-nums">
              {autoHandled.length}
            </span>
          )}
        </button>
        <div className="flex-1" />
        {activeTab === "escalations" && items.length > 0 && (
          <button
            onClick={onDismissAll}
            className="px-4 font-mono text-[11px] uppercase tracking-wider text-muted-foreground/58 hover:text-muted-foreground/78 transition-colors"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Content */}
      <div
        className="flex-1 overflow-y-auto divide-y divide-border/30"
        style={{ height: height - HEADER_H }}
      >
        {activeTab === "escalations" ? (
          items.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <span className="font-mono text-[11px] text-muted-foreground/48 uppercase tracking-[0.12em]">
                No pending escalations
              </span>
            </div>
          ) : (
            <>
              {pending.map((item) => (
                <EscalationRow
                  key={item.id}
                  item={item}
                  onOpen={onOpen}
                  onDecide={onDecide}
                  onDismiss={onDismiss}
                />
              ))}
              {resolved.length > 0 && pending.length > 0 && (
                <div className="px-5 py-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground/52 bg-muted/5 border-y border-border/20">
                  Resolved
                </div>
              )}
              {resolved.map((item) => (
                <EscalationRow
                  key={item.id}
                  item={item}
                  onOpen={onOpen}
                  onDecide={onDecide}
                  onDismiss={onDismiss}
                />
              ))}
            </>
          )
        ) : autoHandled.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <span className="font-mono text-[11px] text-muted-foreground/48 uppercase tracking-[0.12em]">
              Awaiting autonomous decisions
            </span>
          </div>
        ) : (
          autoHandled.map((item) => <AutoHandledRow key={item.id} item={item} />)
        )}
      </div>
    </div>
  );
}

function EscalationRow({
  item,
  onOpen,
  onDecide,
  onDismiss,
}: {
  item: EscalationItem;
  onOpen: (item: EscalationItem) => void;
  onDecide: (id: number, decision: ReviewStatus) => void;
  onDismiss: (id: number) => void;
}) {
  const isOpenable = canOpenEscalation(item.status);
  const isActionable =
    item.status === "pending" ||
    item.status === "evidence_received" ||
    item.status === "ready_for_review";
  return (
    <div
      onClick={() => isOpenable && onOpen(item)}
      className={cn(
        "flex items-center gap-3 px-5 py-2.5 transition-colors",
        isOpenable
          ? "hover:bg-muted/8 cursor-pointer border-l-2 border-l-state-escalate/50"
          : "opacity-45 cursor-default border-l-2 border-l-transparent",
      )}
    >
      <span className="text-sm shrink-0">{item.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-foreground/85 truncate">{item.title}</span>
          <span className="font-mono text-[11px] text-muted-foreground/68 shrink-0">
            {item.sector}
          </span>
          <span className="font-mono text-[11px] text-muted-foreground/52 shrink-0">{item.ts}</span>
        </div>
        <div className="font-mono text-[11px] text-muted-foreground/75 truncate mt-0.5">
          {isOpenable ? item.proposed_action.slice(0, 90) : item.reason.slice(0, 90)}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span
          className={cn(
            "font-mono text-[11px] border px-1.5 py-px uppercase tracking-wider",
            RISK_BADGE[item.risk] ?? RISK_BADGE.high,
          )}
        >
          {item.risk}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground/68 tabular-nums w-7 text-right">
          {(item.trust * 100).toFixed(0)}%
        </span>
        {isActionable ? (
          <>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onOpen(item);
              }}
              className="font-mono text-[11px] px-2.5 py-1 border border-state-verify/40 text-state-verify/80 hover:bg-state-verify/10 transition-colors uppercase tracking-wider"
            >
              Review
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDecide(item.id, "rejected");
              }}
              className="font-mono text-[11px] px-2.5 py-1 border border-border/40 text-muted-foreground/75 hover:border-state-escalate/40 hover:text-state-escalate/70 transition-colors uppercase tracking-wider"
            >
              Reject
            </button>
            <span className="font-mono text-[11px] text-muted-foreground/48 pl-1">detail →</span>
          </>
        ) : (
          <span
            className={cn(
              "font-mono text-[11px] uppercase tracking-wider border px-1.5 py-px",
              statusPillClass(item.status),
            )}
          >
            {STATUS_LABEL[item.status]}
          </span>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDismiss(item.id);
          }}
          className="font-mono text-base leading-none text-muted-foreground/48 hover:text-muted-foreground/78 transition-colors ml-1"
          aria-label="Dismiss"
        >
          ×
        </button>
      </div>
    </div>
  );
}

function AutoHandledRow({ item }: { item: AutoHandled }) {
  return (
    <div className="flex items-center gap-3 px-5 py-2.5 border-l-2 border-l-state-accept/20 hover:bg-muted/5 transition-colors">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-foreground/82 truncate">{item.title}</span>
          <span className="font-mono text-[11px] text-muted-foreground/68 shrink-0">
            {item.platform}
          </span>
          <span className="font-mono text-[11px] text-muted-foreground/52 shrink-0">{item.ts}</span>
        </div>
        <div className="font-mono text-[11px] text-muted-foreground/62 mt-0.5">
          Agent acted autonomously · human time reserved for decisions that matter
        </div>
      </div>
      <div className="flex items-center gap-2.5 shrink-0">
        <span
          className={cn(
            "font-mono text-[11px] border px-1.5 py-px uppercase tracking-wider",
            item.verdict === "ACCEPT"
              ? "border-state-accept/30 text-state-accept/70 bg-state-accept/5"
              : "border-state-verify/30 text-state-verify/70 bg-state-verify/5",
          )}
        >
          {item.verdict}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground/62 tabular-nums">
          {(item.trust * 100).toFixed(0)}% trust
        </span>
        <span className="font-mono text-[11px] text-muted-foreground/52 tabular-nums">
          {item.latency_ms}ms
        </span>
      </div>
    </div>
  );
}

export const EscalationInbox = React.memo(EscalationInboxRaw);
