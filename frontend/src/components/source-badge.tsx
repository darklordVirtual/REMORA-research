/**
 * Explicit data-source indicator (Phase 12).
 *
 * Every surface backed by the typed read-model client renders the state it
 * actually has — LIVE, DEMO, OFFLINE, DEGRADED or ERROR — so a failed API
 * call can never quietly look like live data.
 */
import type { DataSourceState } from "@/lib/api/execution";

const STYLES: Record<DataSourceState, string> = {
  LIVE: "border-emerald-500/60 bg-emerald-500/10 text-emerald-500",
  DEMO: "border-amber-500/60 bg-amber-500/10 text-amber-500",
  OFFLINE: "border-red-500/60 bg-red-500/10 text-red-500",
  DEGRADED: "border-orange-500/60 bg-orange-500/10 text-orange-500",
  ERROR: "border-red-500/60 bg-red-500/10 text-red-500",
};

export function SourceBadge({ state, detail }: { state: DataSourceState; detail?: string }) {
  return (
    <span
      role="status"
      title={detail}
      className={`inline-flex items-center gap-1 border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] ${STYLES[state]}`}
    >
      {state}
      {detail ? <span className="font-normal normal-case opacity-70">· {detail}</span> : null}
    </span>
  );
}
