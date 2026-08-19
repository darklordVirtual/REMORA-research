/**
 * Persistent synthetic-data indicator (remediation Phase 11).
 *
 * Every page backed by the remora-sim engine renders this banner so a
 * simulated screen can never be mistaken for live operations. It is sticky,
 * visually loud, and deliberately not dismissible: an approvals screen full
 * of synthetic proposals must announce itself on every scroll position.
 */
export function DemoBanner() {
  return (
    <div
      role="status"
      aria-label="Demo data – synthetic, no live actions"
      className="sticky top-0 z-50 w-full border-y border-amber-500/60 bg-amber-500/15 px-4 py-1.5 text-center"
    >
      <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-500">
        Demo data · Synthetic — no live actions
      </span>
    </div>
  );
}
