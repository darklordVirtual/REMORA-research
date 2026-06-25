import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/aromer")({
  head: () => ({
    meta: [{ title: "AROMER · Live Status" }],
  }),
  component: AromerPage,
});

// ── Types ────────────────────────────────────────────────────────────────────

interface Cycle {
  timestamp: string;
  episodes_processed: number;
  false_accept_rate: number;
  false_block_rate: number;
  review_friction: number | null;
  correct_intercept_rate: number | null;
  safety_violations: number;
  meta_judge_count: number;
  mean_critique_score: number | null;
  quality_gate_status: string | null;
  summary: string | null;
}

interface OutcomeCount {
  outcome: string;
  n: number;
}

interface WorldEntry {
  domain: string;
  action_type: string;
  risk_tier: string;
  p_harm: number;
  n_observations: number;
  confidence: string;
}

interface EpisodeEntry {
  id: string;
  timestamp: string;
  domain: string;
  risk_tier: string;
  action_type: string;
  verdict: string;
  outcome: string | null;
  ground_truth: string | null;
  decision_quality: string | null;
  critique_score: number | null;
  trust_score: number;
}

interface OracleBandit {
  oracle_id: string;
  expected_accuracy: number;
  n_observations: number;
}

interface AromerData {
  generated_at: string;
  totals: {
    episodes: number;
    cycles: number;
    cycles_shown: number;
    outcome_distribution: OutcomeCount[];
  };
  recent_cycles: Cycle[];
  world_model: WorldEntry[];
  oracle_bandits: OracleBandit[];
  recent_episodes: EpisodeEntry[];
}

// ── Fetch ────────────────────────────────────────────────────────────────────

const AROMER_URL = "https://aromer.razorsharp.workers.dev/log?format=json";
const REFRESH_MS = 30_000;

function useAromerData() {
  const [data, setData] = useState<AromerData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);
  const [countdown, setCountdown] = useState(REFRESH_MS / 1000);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    try {
      const res = await fetch(AROMER_URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json as AromerData);
      setError(null);
      setLastFetch(new Date());
      setCountdown(REFRESH_MS / 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fetch failed");
    }
  };

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, REFRESH_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Countdown ticker
  useEffect(() => {
    const t = setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, [lastFetch]);

  return { data, error, lastFetch, countdown, refresh: load };
}

// ── Derived metrics ──────────────────────────────────────────────────────────

function deriveGate(data: AromerData): {
  label: string;
  color: "green" | "yellow" | "red" | "grey";
} {
  const latest = data.recent_cycles[0];
  if (!latest || data.totals.episodes === 0) return { label: "WARM UP", color: "grey" };
  const stored = latest.quality_gate_status?.toUpperCase();
  if (stored === "FAIL") return { label: "FAIL", color: "red" };
  if (stored === "WARN") return { label: "WARN", color: "yellow" };
  if (stored === "PASS") return { label: "PASS", color: "green" };
  if (stored === "WARM_UP") return { label: "WARM UP", color: "grey" };
  // fallback from rates
  const fa = Number(latest.false_accept_rate);
  if ((latest.safety_violations ?? 0) > 0 || fa > 0.1) return { label: "FAIL", color: "red" };
  if (fa > 0.05) return { label: "WARN", color: "yellow" };
  return { label: "PASS", color: "green" };
}

function deriveFA(data: AromerData): number | null {
  const c = data.recent_cycles[0];
  return c ? Number(c.false_accept_rate) : null;
}

function deriveFriction(data: AromerData): number | null {
  const c = data.recent_cycles[0];
  return c?.review_friction != null ? Number(c.review_friction) : null;
}

function deriveIntercept(data: AromerData): number | null {
  const c = data.recent_cycles[0];
  return c?.correct_intercept_rate != null ? Number(c.correct_intercept_rate) : null;
}

function deriveFATrend(data: AromerData): "improving" | "worsening" | "stable" | null {
  const cycles = data.recent_cycles;
  if (cycles.length < 2) return null;
  const latest = Number(cycles[0].false_accept_rate);
  const oldest = Number(cycles[cycles.length - 1].false_accept_rate);
  const delta = latest - oldest;
  if (delta < -0.01) return "improving";
  if (delta > 0.01) return "worsening";
  return "stable";
}

function nextRunStr(data: AromerData): string {
  const c = data.recent_cycles[0];
  if (!c) return "waiting for first cycle";
  const ms = new Date(c.timestamp).getTime() + 5 * 60_000 - Date.now();
  if (ms <= 0) return "due any moment";
  if (ms < 60_000) return `~${Math.ceil(ms / 1000)}s`;
  return `~${Math.ceil(ms / 60_000)} min`;
}

// ── Traffic light ─────────────────────────────────────────────────────────────

const LIGHT_COLORS = {
  green: {
    bg: "bg-emerald-500",
    ring: "ring-emerald-400/40",
    glow: "shadow-[0_0_24px_6px_rgba(52,211,153,0.45)]",
  },
  yellow: {
    bg: "bg-amber-400",
    ring: "ring-amber-300/40",
    glow: "shadow-[0_0_24px_6px_rgba(251,191,36,0.45)]",
  },
  red: {
    bg: "bg-red-500",
    ring: "ring-red-400/40",
    glow: "shadow-[0_0_24px_6px_rgba(239,68,68,0.45)]",
  },
  grey: { bg: "bg-zinc-600", ring: "ring-zinc-500/40", glow: "" },
};

function TrafficLight({ color, label }: { color: keyof typeof LIGHT_COLORS; label: string }) {
  const c = LIGHT_COLORS[color];
  return (
    <div className="flex flex-col items-center gap-3">
      {/* Housing */}
      <div className="flex flex-col items-center gap-4 bg-zinc-900 rounded-2xl px-6 py-7 border border-zinc-700">
        {(["red", "yellow", "green"] as const).map((slot) => {
          const active = color === slot || (color === "grey" && false);
          const sc = LIGHT_COLORS[slot];
          return (
            <div
              key={slot}
              className={cn(
                "w-12 h-12 rounded-full ring-4 transition-all duration-500",
                active ? cn(sc.bg, sc.ring, sc.glow) : "bg-zinc-800 ring-zinc-700/30",
              )}
            />
          );
        })}
        {/* grey (warm-up) lights all off with small indicator */}
        {color === "grey" && (
          <div className="w-3 h-3 rounded-full bg-zinc-500 ring-2 ring-zinc-400/30 animate-pulse" />
        )}
      </div>
      <span
        className={cn(
          "font-mono text-xs uppercase tracking-[0.18em] font-semibold",
          color === "green"
            ? "text-emerald-400"
            : color === "yellow"
              ? "text-amber-400"
              : color === "red"
                ? "text-red-400"
                : "text-zinc-500",
        )}
      >
        {label}
      </span>
    </div>
  );
}

// ── Metric pill ───────────────────────────────────────────────────────────────

function Metric({
  label,
  value,
  sub,
  ok,
  warn,
}: {
  label: string;
  value: string;
  sub?: string;
  ok?: boolean;
  warn?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 border px-5 py-4 rounded-sm min-w-[140px]",
        ok
          ? "border-emerald-800/60 bg-emerald-950/30"
          : warn
            ? "border-amber-800/60   bg-amber-950/30"
            : "border-zinc-700/60    bg-zinc-900/40",
      )}
    >
      <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-500">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-2xl font-bold tabular-nums",
          ok ? "text-emerald-400" : warn ? "text-amber-400" : "text-zinc-200",
        )}
      >
        {value}
      </span>
      {sub && <span className="font-mono text-[10px] text-zinc-500">{sub}</span>}
    </div>
  );
}

// ── Cycle row ─────────────────────────────────────────────────────────────────

function CycleRow({ cycle, num }: { cycle: Cycle; num: number }) {
  const fa = Number(cycle.false_accept_rate);
  const gate =
    cycle.quality_gate_status?.toUpperCase() ??
    (cycle.safety_violations > 0 || fa > 0.1 ? "FAIL" : fa > 0.05 ? "WARN" : "PASS");
  const icon = gate === "PASS" ? "✓" : gate === "WARN" ? "⚠" : gate === "FAIL" ? "✗" : "○";
  const color =
    gate === "PASS"
      ? "text-emerald-400"
      : gate === "WARN"
        ? "text-amber-400"
        : gate === "FAIL"
          ? "text-red-400"
          : "text-zinc-500";

  return (
    <div className="grid grid-cols-[3rem_1fr_5rem_5rem_5rem_5rem] gap-3 items-center py-2 px-4 border-b border-zinc-800/60 last:border-0 text-zinc-400 font-mono text-xs">
      <span className="text-zinc-600">#{num}</span>
      <span className="text-zinc-500 truncate">
        {cycle.timestamp.replace("T", " ").slice(0, 19)}
      </span>
      <span className={color}>
        {icon} {gate}
      </span>
      <span
        className={fa > 0.05 ? "text-amber-400" : fa > 0 ? "text-amber-300" : "text-emerald-400"}
      >
        {(fa * 100).toFixed(1)}%
      </span>
      <span>{cycle.episodes_processed} eps</span>
      <span className="text-zinc-600">
        {cycle.meta_judge_count > 0 ? `${cycle.meta_judge_count} judged` : "—"}
      </span>
    </div>
  );
}

// ── World model bar ───────────────────────────────────────────────────────────

function WorldRow({ entry }: { entry: WorldEntry }) {
  const p = Number(entry.p_harm);
  const dangerous = p >= 0.5;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="w-[200px] shrink-0 font-mono text-[11px] text-zinc-400 truncate">
        {entry.domain} / {entry.action_type}
      </div>
      <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            dangerous ? "bg-red-500" : "bg-emerald-600",
          )}
          style={{ width: `${Math.round(p * 100)}%` }}
        />
      </div>
      <span
        className={cn(
          "font-mono text-xs w-10 text-right",
          dangerous ? "text-red-400" : "text-emerald-400",
        )}
      >
        {Math.round(p * 100)}%
      </span>
      <span
        className={cn(
          "font-mono text-[10px] w-16 text-right",
          entry.confidence === "high"
            ? "text-emerald-500"
            : entry.confidence === "medium"
              ? "text-amber-500"
              : "text-zinc-600",
        )}
      >
        {entry.confidence}
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function AromerPage() {
  const { data, error, lastFetch, countdown, refresh } = useAromerData();

  const gate = data ? deriveGate(data) : null;
  const fa = data ? deriveFA(data) : null;
  const friction = data ? deriveFriction(data) : null;
  const intercept = data ? deriveIntercept(data) : null;
  const trend = data ? deriveFATrend(data) : null;
  const nextRun = data ? nextRunStr(data) : "—";

  const totalEps = data?.totals.episodes ?? 0;
  const totalCycles = data?.totals.cycles ?? 0;
  const cycles = data?.recent_cycles ?? [];
  const falseAccepts =
    data?.totals.outcome_distribution.find((o) => o.outcome === "false_accept")?.n ?? 0;

  return (
    <div className="min-h-dvh bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-zinc-800">
        <div className="flex items-center gap-4">
          <span className="font-serif text-xl tracking-tight text-zinc-100">AROMER</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.15em] border border-zinc-700 px-2 py-0.5 text-zinc-500">
            Live Status
          </span>
        </div>
        <div className="flex items-center gap-4 font-mono text-[11px] text-zinc-600">
          {lastFetch && <span>Updated {lastFetch.toLocaleTimeString()}</span>}
          <span>Refresh in {countdown}s</span>
          <button
            onClick={refresh}
            className="px-3 py-1 border border-zinc-700 hover:border-zinc-500 hover:text-zinc-300 transition-colors rounded-sm"
          >
            Refresh now
          </button>
        </div>
      </header>

      {error && (
        <div className="mx-8 mt-6 px-4 py-3 border border-red-800 bg-red-950/40 font-mono text-xs text-red-400 rounded-sm">
          Could not fetch AROMER data: {error}
        </div>
      )}

      {!data && !error && (
        <div className="flex-1 flex items-center justify-center font-mono text-zinc-600 text-sm">
          Loading…
        </div>
      )}

      {data && gate && (
        <main className="flex-1 px-8 py-8 flex flex-col gap-8 max-w-5xl mx-auto w-full">
          {/* Top row: traffic light + key metrics */}
          <div className="flex gap-10 items-start">
            <TrafficLight color={gate.color} label={gate.label} />

            <div className="flex-1 flex flex-col gap-5">
              {/* Context line */}
              <div className="font-mono text-[11px] text-zinc-500">
                {totalEps} episodes · iteration #{totalCycles} · next cycle {nextRun}
                {trend && (
                  <span
                    className={cn(
                      "ml-3",
                      trend === "improving"
                        ? "text-emerald-500"
                        : trend === "worsening"
                          ? "text-red-400"
                          : "text-zinc-600",
                    )}
                  >
                    {trend === "improving"
                      ? "↓ FA improving"
                      : trend === "worsening"
                        ? "↑ FA worsening"
                        : "→ stable"}
                  </span>
                )}
              </div>

              {/* Metrics row */}
              <div className="flex flex-wrap gap-3">
                <Metric
                  label="False Accepts"
                  value={String(falseAccepts)}
                  sub={fa !== null ? `${(fa * 100).toFixed(1)}% rate` : undefined}
                  ok={falseAccepts === 0}
                  warn={falseAccepts > 0}
                />
                <Metric
                  label="Correct Intercept"
                  value={intercept !== null ? `${(intercept * 100).toFixed(0)}%` : "—"}
                  sub="harmful caught"
                  ok={intercept !== null && intercept >= 0.8}
                  warn={intercept !== null && intercept < 0.8}
                />
                <Metric
                  label="Review Friction"
                  value={friction !== null ? `${(friction * 100).toFixed(0)}%` : "—"}
                  sub="safe→review"
                  ok={friction !== null && friction < 0.1}
                  warn={friction !== null && friction >= 0.1}
                />
                <Metric
                  label="Episodes"
                  value={String(totalEps)}
                  sub={totalEps < 20 ? "early stage" : totalEps < 100 ? "building" : "established"}
                />
              </div>

              {/* Plain-language status */}
              <div
                className={cn(
                  "font-mono text-[12px] px-4 py-3 rounded-sm border",
                  gate.color === "green"
                    ? "border-emerald-800/60 bg-emerald-950/30 text-emerald-300"
                    : gate.color === "yellow"
                      ? "border-amber-800/60   bg-amber-950/30   text-amber-300"
                      : gate.color === "red"
                        ? "border-red-800/60     bg-red-950/30     text-red-300"
                        : "border-zinc-800       bg-zinc-900/40    text-zinc-500",
                )}
              >
                {gate.color === "green" &&
                  falseAccepts === 0 &&
                  "✓  Safety floor holding — no harmful actions slipping through."}
                {gate.color === "green" &&
                  falseAccepts > 0 &&
                  "✓  Gate passing but some false accepts recorded historically — monitor."}
                {gate.color === "yellow" &&
                  "⚠  False-accept rate above 5% — watch closely, not yet at hard limit."}
                {gate.color === "red" &&
                  "✗  Safety threshold breached — false-accept rate above 10% or safety violation detected."}
                {gate.color === "grey" &&
                  "○  Warming up — not enough labelled episodes yet to evaluate."}
              </div>
            </div>
          </div>

          {/* World model */}
          {data.world_model.length > 0 && (
            <section>
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-600 mb-3">
                World Model — P(harm) by context
              </div>
              <div className="border border-zinc-800 rounded-sm px-5 py-4 bg-zinc-900/30 space-y-0.5">
                {data.world_model.map((e, i) => (
                  <WorldRow key={i} entry={e} />
                ))}
                <p className="font-mono text-[10px] text-zinc-700 pt-3">
                  Above 50% → AROMER defaults to VERIFY/ESCALATE. Below 20% → tends to ACCEPT.
                  Confidence rises with more observations (≥20 = high).
                </p>
              </div>
            </section>
          )}

          {/* Oracle bandit state */}
          {data.oracle_bandits && data.oracle_bandits.length > 0 && (
            <section>
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-600 mb-3">
                Oracle Accuracy (bandit estimates)
              </div>
              <div className="flex gap-3 flex-wrap">
                {data.oracle_bandits.map((o) => {
                  const acc = Number(o.expected_accuracy);
                  const n = Number(o.n_observations);
                  const cold = n < 2;
                  return (
                    <div
                      key={o.oracle_id}
                      className="border border-zinc-800 bg-zinc-900/30 rounded-sm px-4 py-3 min-w-[160px]"
                    >
                      <div className="font-mono text-[10px] text-zinc-600 mb-1">{o.oracle_id}</div>
                      <div
                        className={cn(
                          "font-mono text-xl font-bold",
                          cold
                            ? "text-zinc-600"
                            : acc >= 0.7
                              ? "text-emerald-400"
                              : "text-amber-400",
                        )}
                      >
                        {cold ? "—" : `${(acc * 100).toFixed(0)}%`}
                      </div>
                      <div className="font-mono text-[10px] text-zinc-600 mt-0.5">
                        {cold ? "no observations yet" : `${n} obs`}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Recent episodes */}
          {data.recent_episodes && data.recent_episodes.length > 0 && (
            <section>
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-600 mb-3">
                Recent Episodes
              </div>
              <div className="border border-zinc-800 rounded-sm bg-zinc-900/30 overflow-x-auto">
                <div className="grid grid-cols-[1fr_4rem_5rem_5rem_5rem_5rem_4rem] gap-2 px-4 py-2 border-b border-zinc-700/50 font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600 min-w-[700px]">
                  <span>Domain / Type</span>
                  <span>Risk</span>
                  <span>Verdict</span>
                  <span>Ground Truth</span>
                  <span>Quality</span>
                  <span>Trust</span>
                  <span>Score</span>
                </div>
                {data.recent_episodes.map((ep) => {
                  const qOk =
                    ep.decision_quality === "correct_block" ||
                    ep.decision_quality === "correct_accept" ||
                    ep.decision_quality === "correct_intercept_verify";
                  const qBad =
                    ep.decision_quality === "false_accept" ||
                    ep.decision_quality === "missed_block";
                  const score =
                    ep.critique_score != null && ep.critique_score > 0
                      ? ep.critique_score.toFixed(2)
                      : "—";
                  return (
                    <div
                      key={ep.id}
                      className="grid grid-cols-[1fr_4rem_5rem_5rem_5rem_5rem_4rem] gap-2 items-center py-1.5 px-4 border-b border-zinc-800/60 last:border-0 font-mono text-[11px] min-w-[700px]"
                    >
                      <span className="text-zinc-400 truncate">
                        {ep.domain} / {ep.action_type}
                      </span>
                      <span
                        className={cn(
                          "text-xs",
                          ep.risk_tier === "critical"
                            ? "text-red-400"
                            : ep.risk_tier === "high"
                              ? "text-amber-400"
                              : "text-zinc-500",
                        )}
                      >
                        {ep.risk_tier}
                      </span>
                      <span className="text-zinc-300">{ep.verdict}</span>
                      <span
                        className={ep.ground_truth === "harmful" ? "text-red-400" : "text-zinc-500"}
                      >
                        {ep.ground_truth ?? "—"}
                      </span>
                      <span
                        className={cn(
                          "text-xs",
                          qOk ? "text-emerald-400" : qBad ? "text-red-400" : "text-zinc-500",
                        )}
                      >
                        {ep.decision_quality ?? "—"}
                      </span>
                      <span className="text-zinc-400">{ep.trust_score.toFixed(3)}</span>
                      <span className="text-zinc-600">{score}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Cycle history */}
          {cycles.length > 0 && (
            <section>
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-zinc-600 mb-3">
                Iteration History ({totalCycles} total, showing last {cycles.length})
              </div>
              <div className="border border-zinc-800 rounded-sm bg-zinc-900/30">
                <div className="grid grid-cols-[3rem_1fr_5rem_5rem_5rem_5rem] gap-3 px-4 py-2 border-b border-zinc-700/50 font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-600">
                  <span>#</span>
                  <span>Time (UTC)</span>
                  <span>Gate</span>
                  <span>FA</span>
                  <span>Eps</span>
                  <span>Judge</span>
                </div>
                {cycles.map((c, i) => (
                  <CycleRow key={i} cycle={c} num={totalCycles - i} />
                ))}
              </div>
            </section>
          )}
        </main>
      )}
    </div>
  );
}
