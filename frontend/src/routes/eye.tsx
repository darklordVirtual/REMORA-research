import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/eye")({
  head: () => ({
    meta: [{ title: "REMORA — Governance Eye" }],
  }),
  component: EyePage,
});

// ── Types ─────────────────────────────────────────────────────────────────

type Decision = "ACCEPT" | "VERIFY" | "ABSTAIN" | "ESCALATE";
type ThermPhase = "ordered" | "critical" | "disordered";
type ActionStage = "QUEUED" | "PROCESSING" | "DECIDED" | "SEALED";

interface AgentAction {
  id: number;
  action: string;
  domain: string;
  decision: Decision;
  hash: string;
  phase: ThermPhase;
  trust: number;
  entropy: number;
  risk: "low" | "medium" | "high" | "critical";
  envelopeId: string;
}

interface LiveAction extends AgentAction {
  stage: ActionStage;
  processingPhaseIdx: number; // which layer is being evaluated (0–5)
  phaseStartedAt: number; // performance.now() when phase began
  decidedAt?: number;
}

interface AuditEntry extends AgentAction {
  ts: string;
  outcome: string; // "allowed" | "blocked" | "human review"
}

// ── Constants ─────────────────────────────────────────────────────────────

const PROCESSING_PHASES = [
  "Analysing",
  "Evidence Routing",
  "Oracle Consensus",
  "Shadow Replay",
  "Fail-Closed Controls",
  "Policy Gate",
  "Final Verdict",
];

const PHASE_DURATION_MS = [900, 1000, 1100, 900, 900, 1100, 700]; // ms per phase — slow enough to read

// Governance layer order: outermost → innermost (matches PROCESSING_PHASES index 1–5)
const LAYERS = [
  { label: "Fail-Closed Controls", color: "oklch(0.56 0.17 25)" },
  { label: "Tenant Audit", color: "oklch(0.52 0.14 50)" },
  { label: "Shadow Replay", color: "oklch(0.50 0.12 200)" },
  { label: "Evidence Routing", color: "oklch(0.50 0.13 260)" },
  { label: "Oracle Consensus", color: "oklch(0.50 0.11 300)" },
  { label: "Policy Gate", color: "oklch(0.44 0.14 155)" },
];

const RING_RADII = [122, 107, 93, 81, 70, 60];

const STATE: Record<
  Decision,
  { fg: string; bg: string; border: string; glow: string; label: string; outcome: string }
> = {
  ACCEPT: {
    fg: "oklch(0.40 0.14 155)",
    bg: "oklch(0.95 0.05 155)",
    border: "oklch(0.68 0.12 155)",
    glow: "oklch(0.68 0.12 155 / 0.30)",
    label: "ACCEPT",
    outcome: "allowed",
  },
  VERIFY: {
    fg: "oklch(0.44 0.15 75)",
    bg: "oklch(0.95 0.05 75)",
    border: "oklch(0.70 0.12 75)",
    glow: "oklch(0.70 0.12 75 / 0.30)",
    label: "VERIFY",
    outcome: "human review",
  },
  ABSTAIN: {
    fg: "oklch(0.38 0.028 260)",
    bg: "oklch(0.94 0.014 260)",
    border: "oklch(0.68 0.020 260)",
    glow: "oklch(0.68 0.020 260 / 0.25)",
    label: "ABSTAIN",
    outcome: "deferred",
  },
  ESCALATE: {
    fg: "oklch(0.46 0.22 25)",
    bg: "oklch(0.96 0.06 25)",
    border: "oklch(0.68 0.16 25)",
    glow: "oklch(0.68 0.16 25 / 0.40)",
    label: "ESCALATE",
    outcome: "blocked",
  },
};

const THERM: Record<ThermPhase, { ringColor: string; speed: number; label: string }> = {
  ordered: { ringColor: "oklch(0.44 0.14 155)", speed: 0.18, label: "ORDERED" },
  critical: { ringColor: "oklch(0.52 0.14 75)", speed: 0.38, label: "CRITICAL" },
  disordered: { ringColor: "oklch(0.50 0.20 25)", speed: 0.7, label: "DISORDERED" },
};

const SAMPLES: Omit<AgentAction, "id">[] = [
  {
    action: "sql.execute  DROP TABLE customers",
    domain: "database",
    decision: "ESCALATE",
    hash: "e4be3a8d",
    phase: "disordered",
    trust: 0.002,
    entropy: 0.94,
    risk: "critical",
    envelopeId: "env_e4be3a8d",
  },
  {
    action: "file.read    finance/Q2_revenue.csv",
    domain: "finance",
    decision: "ACCEPT",
    hash: "4528ea7f",
    phase: "ordered",
    trust: 0.946,
    entropy: 0.08,
    risk: "low",
    envelopeId: "env_4528ea7f",
  },
  {
    action: "router.set_config  bgp_peer  zone=core",
    domain: "network",
    decision: "VERIFY",
    hash: "4f550c88",
    phase: "critical",
    trust: 0.471,
    entropy: 0.51,
    risk: "medium",
    envelopeId: "env_4f550c88",
  },
  {
    action: "data.export  users/*  →  s3://partner/",
    domain: "data",
    decision: "ABSTAIN",
    hash: "eb33fa75",
    phase: "disordered",
    trust: 0.009,
    entropy: 0.88,
    risk: "high",
    envelopeId: "env_eb33fa75",
  },
  {
    action: "deploy.run   service=payments  env=prod",
    domain: "infra",
    decision: "VERIFY",
    hash: "9c1d2a44",
    phase: "critical",
    trust: 0.512,
    entropy: 0.47,
    risk: "medium",
    envelopeId: "env_9c1d2a44",
  },
  {
    action: "iam.revoke   token  user=admin",
    domain: "auth",
    decision: "ESCALATE",
    hash: "2b7f8e01",
    phase: "disordered",
    trust: 0.008,
    entropy: 0.91,
    risk: "critical",
    envelopeId: "env_2b7f8e01",
  },
  {
    action: "git.push     origin/main  --force",
    domain: "devops",
    decision: "VERIFY",
    hash: "5e3c9f12",
    phase: "critical",
    trust: 0.411,
    entropy: 0.53,
    risk: "medium",
    envelopeId: "env_5e3c9f12",
  },
  {
    action: "query.run    SELECT id FROM users",
    domain: "database",
    decision: "ACCEPT",
    hash: "7a4d1c33",
    phase: "ordered",
    trust: 0.921,
    entropy: 0.11,
    risk: "low",
    envelopeId: "env_7a4d1c33",
  },
  {
    action: "k8s.scale    replicas=0  svc=payments",
    domain: "infra",
    decision: "VERIFY",
    hash: "3f8b2e55",
    phase: "critical",
    trust: 0.388,
    entropy: 0.57,
    risk: "medium",
    envelopeId: "env_3f8b2e55",
  },
  {
    action: "email.send   bulk_unsubscribe=all",
    domain: "comms",
    decision: "ESCALATE",
    hash: "d0b3e921",
    phase: "disordered",
    trust: 0.031,
    entropy: 0.86,
    risk: "critical",
    envelopeId: "env_d0b3e921",
  },
  {
    action: "cache.flush  scope=global",
    domain: "infra",
    decision: "ABSTAIN",
    hash: "c9a5d770",
    phase: "disordered",
    trust: 0.044,
    entropy: 0.79,
    risk: "high",
    envelopeId: "env_c9a5d770",
  },
  {
    action: "file.read    logs/nginx/access.log",
    domain: "ops",
    decision: "ACCEPT",
    hash: "1e6f4a88",
    phase: "ordered",
    trust: 0.887,
    entropy: 0.09,
    risk: "low",
    envelopeId: "env_1e6f4a88",
  },
];

function ts() {
  return new Date().toISOString().slice(11, 19);
}
function shortAction(a: string) {
  return a.split(/\s+/).slice(0, 2).join(" ");
}

// ── Governance Eye SVG ─────────────────────────────────────────────────────

function GovernanceEye({
  live,
  tick,
  pulse,
}: {
  live: LiveAction | null;
  tick: number;
  pulse: number;
}) {
  const now = tick * 0.016; // approximate seconds
  const CX = 145,
    CY = 145;
  const blobR = 46;
  const blobPts = 80;

  const therm = live ? THERM[live.phase] : THERM.ordered;
  const decision = live?.stage === "DECIDED" ? live.decision : null;
  const activeLayerIdx =
    live?.stage === "PROCESSING"
      ? Math.max(0, live.processingPhaseIdx - 1) // phase 1–5 map to layers 0–4
      : null;

  // Elastic blob
  const blobPath =
    Array.from({ length: blobPts }, (_, i) => {
      const angle = (i / blobPts) * Math.PI * 2;
      const w =
        pulse *
        (Math.sin(angle * 3 + now * therm.speed * 1.4) * 4.5 +
          Math.sin(angle * 5 - now * therm.speed * 1.0) * 2.5 +
          Math.sin(angle * 7 + now * therm.speed * 0.7) * 1.0);
      const r = blobR + w;
      return `${i === 0 ? "M" : "L"} ${CX + Math.cos(angle) * r} ${CY + Math.sin(angle) * r}`;
    }).join(" ") + " Z";

  const blobFill = decision ? STATE[decision].bg : "oklch(0.987 0.005 90)";
  const blobBorder = decision ? STATE[decision].border : "oklch(0.83 0.008 260)";

  return (
    <svg viewBox="0 0 290 290" width={290} height={290} style={{ overflow: "visible" }}>
      <defs>
        <radialGradient id="halo-g" cx="50%" cy="50%" r="50%">
          <stop offset="60%" stopColor="transparent" />
          <stop
            offset="100%"
            stopColor={decision ? STATE[decision].glow : "oklch(0.88 0.006 260 / 0.12)"}
          />
        </radialGradient>
      </defs>

      {/* Halo */}
      {live && <circle cx={CX} cy={CY} r={RING_RADII[0] + 14} fill="url(#halo-g)" opacity={0.7} />}

      {/* Governance rings */}
      {RING_RADII.map((r, i) => {
        const isActive = activeLayerIdx !== null && RING_RADII.length - 1 - i === activeLayerIdx;
        const layerColor = LAYERS[RING_RADII.length - 1 - i].color;
        const rotSpeed = (i % 2 === 0 ? 1 : -1) * therm.speed * (0.5 + i * 0.09);
        const rotDeg = (now * rotSpeed * 14) % 360;
        const baseOpacity = 0.13 + (RING_RADII.length - i) * 0.04;
        const activeOpacity = isActive ? 0.85 : baseOpacity;
        const strokeW = isActive ? 2.2 : 1.0;
        const dashLen = isActive ? 10 : 6 + i * 1.5;
        const gapLen = isActive ? 4 : 8 + i * 2;

        return (
          <g key={i} transform={`rotate(${rotDeg}, ${CX}, ${CY})`}>
            <circle
              cx={CX}
              cy={CY}
              r={r}
              fill="none"
              stroke={isActive ? layerColor : layerColor}
              strokeWidth={strokeW}
              strokeDasharray={`${dashLen} ${gapLen}`}
              opacity={activeOpacity}
              style={{ transition: "opacity 0.25s, stroke-width 0.25s" }}
            />
            {/* Bright arc when active */}
            {isActive && (
              <circle
                cx={CX}
                cy={CY}
                r={r}
                fill="none"
                stroke={layerColor}
                strokeWidth={3}
                strokeDasharray={`${r * 0.55} ${r * Math.PI * 2}`}
                opacity={0.5 + Math.sin(now * 4) * 0.3}
              />
            )}
          </g>
        );
      })}

      {/* Cross-hairs */}
      <line
        x1={CX - 20}
        y1={CY}
        x2={CX + 20}
        y2={CY}
        stroke="oklch(0.72 0.008 260)"
        strokeWidth={0.5}
        opacity={0.22}
      />
      <line
        x1={CX}
        y1={CY - 20}
        x2={CX}
        y2={CY + 20}
        stroke="oklch(0.72 0.008 260)"
        strokeWidth={0.5}
        opacity={0.22}
      />

      {/* Blob */}
      <path
        d={blobPath}
        fill={blobFill}
        stroke={blobBorder}
        strokeWidth={1.8}
        style={{ transition: "fill 0.5s, stroke 0.5s" }}
      />

      {/* Inner dot */}
      <circle
        cx={CX}
        cy={CY}
        r={5}
        fill={decision ? STATE[decision].fg : "oklch(0.68 0.014 260)"}
        opacity={0.55}
        style={{ transition: "fill 0.5s" }}
      />
    </svg>
  );
}

// ── Queue card ────────────────────────────────────────────────────────────

function QueueCard({
  action,
  position,
  isNext,
}: {
  action: AgentAction;
  position: number;
  isNext: boolean;
}) {
  return (
    <div
      className={cn(
        "px-3 py-2.5 rounded border font-mono text-[10px] transition-all duration-300",
        isNext
          ? "border-foreground/25 bg-background shadow-sm"
          : "border-border/50 bg-background/60",
      )}
      style={{ opacity: isNext ? 1 : Math.max(0.35, 0.85 - position * 0.18) }}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-muted-foreground/40 tabular-nums w-4 text-[10px]">
          {position + 1}
        </span>
        <span className="text-foreground/70 truncate text-[11px] font-medium">
          {shortAction(action.action)}
        </span>
      </div>
      <div className="flex gap-2 text-muted-foreground/50 text-[10px]">
        <span className="uppercase tracking-wide text-[9px]">{action.domain}</span>
        <span>·</span>
        <span>{action.envelopeId}</span>
      </div>
    </div>
  );
}

// ── Processing beam (right side of queue card → eye) ──────────────────────

function ProcessingBeam({ active }: { active: boolean }) {
  return (
    <div
      className="absolute left-0 right-0 top-1/2 -translate-y-1/2 pointer-events-none"
      style={{ height: 2, overflow: "hidden" }}
    >
      {active && (
        <div
          className="h-full w-16 absolute"
          style={{
            background:
              "linear-gradient(90deg, transparent, oklch(0.60 0.12 260 / 0.55), transparent)",
            animation: "beam 1.2s ease-in-out infinite",
          }}
        />
      )}
    </div>
  );
}

// ── Execution gate ────────────────────────────────────────────────────────

function ExecutionGate({ live, stats }: { live: LiveAction | null; stats: Stats }) {
  const decided = live?.stage === "DECIDED";
  const d = decided && live ? live.decision : null;
  const s = d ? STATE[d] : null;

  return (
    <div className="flex flex-col items-center gap-3">
      <span className="font-mono text-[9px] uppercase tracking-[0.20em] text-muted-foreground/40">
        Execution Gate
      </span>

      {/* Gate visual */}
      <div
        className="w-14 h-20 rounded border-2 flex items-center justify-center relative"
        style={{
          borderColor: s ? s.border : "oklch(0.85 0.008 260)",
          background: s ? s.bg : "oklch(0.985 0.004 90)",
          transition: "border-color 0.4s, background 0.4s",
          boxShadow: s ? `0 0 16px ${s.glow}` : "none",
        }}
      >
        {/* Gate bars */}
        {(!d || d === "ESCALATE" || d === "ABSTAIN") && (
          <>
            <div
              className="absolute inset-x-2 top-2 h-1 rounded-sm"
              style={{ background: s ? s.border : "oklch(0.82 0.01 260)", opacity: 0.7 }}
            />
            <div
              className="absolute inset-x-2 bottom-2 h-1 rounded-sm"
              style={{ background: s ? s.border : "oklch(0.82 0.01 260)", opacity: 0.7 }}
            />
          </>
        )}
        <span
          className="font-mono text-[9px] font-semibold text-center px-1 leading-tight"
          style={{ color: s?.fg ?? "oklch(0.60 0.012 260)" }}
        >
          {d === "ACCEPT" && "✓\nALLOW"}
          {d === "VERIFY" && "?\nREVIEW"}
          {d === "ABSTAIN" && "–\nDEFER"}
          {d === "ESCALATE" && "✕\nBLOCK"}
          {!d && "—"}
        </span>
      </div>

      {/* Outcome label */}
      <div className="text-center">
        <div
          className="font-mono text-[9px] uppercase tracking-widest"
          style={{ color: s?.fg ?? "oklch(0.72 0.012 260)", minHeight: "1em" }}
        >
          {s?.outcome ?? "awaiting"}
        </div>
      </div>

      {/* Counts */}
      <div className="flex flex-col gap-1 mt-1 w-full">
        {[
          { label: "Executed", val: stats.ACCEPT, color: STATE.ACCEPT.fg },
          { label: "Review", val: stats.VERIFY, color: STATE.VERIFY.fg },
          { label: "Deferred", val: stats.ABSTAIN, color: STATE.ABSTAIN.fg },
          { label: "Blocked", val: stats.ESCALATE, color: STATE.ESCALATE.fg },
        ].map((row) => (
          <div key={row.label} className="flex items-center justify-between font-mono text-[9px]">
            <span className="text-muted-foreground/40">{row.label}</span>
            <span className="tabular-nums font-medium" style={{ color: row.color }}>
              {String(row.val).padStart(2, "0")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Stats ─────────────────────────────────────────────────────────────────

type Stats = { total: number; ACCEPT: number; VERIFY: number; ABSTAIN: number; ESCALATE: number };

// ── Main page ─────────────────────────────────────────────────────────────

export default function EyePage() {
  const nextIdRef = useRef(0);
  const sampleIdxRef = useRef(0);
  const rafRef = useRef<number>(0);
  const pulseRef = useRef(0);
  const lastSpawnRef = useRef(0);
  const pausedRef = useRef(false);

  // Queue: waiting to enter
  const [queue, setQueue] = useState<AgentAction[]>([]);
  // The one currently being processed
  const [live, setLive] = useState<LiveAction | null>(null);
  const liveRef = useRef<LiveAction | null>(null);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [stats, setStats] = useState<Stats>({
    total: 0,
    ACCEPT: 0,
    VERIFY: 0,
    ABSTAIN: 0,
    ESCALATE: 0,
  });
  const [paused, setPaused] = useState(false);
  const [tick, setTick] = useState(0);

  const enqueue = useCallback(() => {
    const idx = sampleIdxRef.current++ % SAMPLES.length;
    const sample = SAMPLES[idx];
    setQueue((q) => [...q, { ...sample, id: nextIdRef.current++ }]);
  }, []);

  // Pull next from queue into the eye
  const pullNext = useCallback(() => {
    setQueue((q) => {
      if (q.length === 0) return q;
      const [next, ...rest] = q;
      const newLive: LiveAction = {
        ...next,
        stage: "PROCESSING",
        processingPhaseIdx: 0,
        phaseStartedAt: performance.now(),
      };
      liveRef.current = newLive;
      setLive(newLive);
      pulseRef.current = 0.5;
      return rest;
    });
  }, []);

  useEffect(() => {
    let lastTime = performance.now();

    function frame(now: number) {
      rafRef.current = requestAnimationFrame(frame);
      const dt = Math.min(now - lastTime, 80);
      lastTime = now;
      if (pausedRef.current) return;

      // Spawn into queue
      if (now - lastSpawnRef.current > 5500) {
        lastSpawnRef.current = now;
        enqueue();
      }

      // Decay pulse
      pulseRef.current = Math.max(0, pulseRef.current - 0.012);

      // Advance live action phases
      const cur = liveRef.current;
      if (cur && cur.stage === "PROCESSING") {
        const elapsed = now - cur.phaseStartedAt;
        const phaseDuration = PHASE_DURATION_MS[cur.processingPhaseIdx] ?? 500;

        if (elapsed >= phaseDuration) {
          const nextPhaseIdx = cur.processingPhaseIdx + 1;
          if (nextPhaseIdx >= PROCESSING_PHASES.length) {
            // Done — move to DECIDED
            const decided: LiveAction = { ...cur, stage: "DECIDED", decidedAt: now };
            liveRef.current = decided;
            setLive(decided);
            pulseRef.current = 1.0;
          } else {
            // Next phase
            const updated: LiveAction = {
              ...cur,
              processingPhaseIdx: nextPhaseIdx,
              phaseStartedAt: now,
            };
            liveRef.current = updated;
            setLive(updated);
            pulseRef.current = Math.min(1, pulseRef.current + 0.25);
          }
        }
      } else if (cur && cur.stage === "DECIDED") {
        // Hold for 1.2s then seal to audit log
        if (cur.decidedAt && now - cur.decidedAt > 2200) {
          setAuditLog((prev) =>
            [
              {
                ...cur,
                ts: ts(),
                outcome: STATE[cur.decision].outcome,
              },
              ...prev,
            ].slice(0, 60),
          );
          setStats((prev) => ({
            total: prev.total + 1,
            ACCEPT: prev.ACCEPT + (cur.decision === "ACCEPT" ? 1 : 0),
            VERIFY: prev.VERIFY + (cur.decision === "VERIFY" ? 1 : 0),
            ABSTAIN: prev.ABSTAIN + (cur.decision === "ABSTAIN" ? 1 : 0),
            ESCALATE: prev.ESCALATE + (cur.decision === "ESCALATE" ? 1 : 0),
          }));
          liveRef.current = null;
          setLive(null);
        }
      } else if (!cur) {
        // Pull next from queue if available (check via a ref-safe approach)
        setQueue((q) => {
          if (q.length === 0) return q;
          const [next, ...rest] = q;
          const newLive: LiveAction = {
            ...next,
            stage: "PROCESSING",
            processingPhaseIdx: 0,
            phaseStartedAt: performance.now(),
          };
          liveRef.current = newLive;
          setLive(newLive);
          pulseRef.current = 0.6;
          return rest;
        });
      }

      setTick((n) => n + 1);
    }

    rafRef.current = requestAnimationFrame(frame);
    // Seed initial queue
    setTimeout(() => {
      enqueue();
      enqueue();
      enqueue();
    }, 100);
    return () => cancelAnimationFrame(rafRef.current);
  }, [enqueue]);

  const currentPhaseLabel =
    live?.stage === "PROCESSING"
      ? PROCESSING_PHASES[live.processingPhaseIdx]
      : live?.stage === "DECIDED"
        ? "Final Verdict"
        : null;

  const therm = live ? THERM[live.phase] : null;
  const decidedState = live?.stage === "DECIDED" ? STATE[live.decision] : null;

  return (
    <div className="h-dvh flex flex-col bg-background overflow-hidden">
      {/* ── Header ── */}
      <header className="shrink-0 flex items-center justify-between px-6 py-3 border-b border-border bg-background/98 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <Link to="/" className="font-serif text-xl tracking-tight">
            REMORA
          </Link>
          <span className="font-mono text-[11px] uppercase tracking-[0.12em] border border-border px-2 py-0.5 text-muted-foreground">
            Governance Eye
          </span>
          <span className="hidden lg:block font-mono text-[11px] text-muted-foreground/50">
            Agent actions evaluated before execution
          </span>
        </div>
        <div className="flex items-center gap-5">
          {/* Pipeline status */}
          <div className="hidden lg:flex items-center gap-2 font-mono text-[10px] text-muted-foreground/50">
            <span className={cn(queue.length > 0 ? "text-foreground/60" : "")}>
              QUEUE {String(queue.length).padStart(2, "0")}
            </span>
            <span className="opacity-30">·</span>
            <span className={cn(live?.stage === "PROCESSING" ? "text-foreground/70" : "")}>
              IN EYE {live?.stage === "PROCESSING" ? "01" : "00"}
            </span>
            <span className="opacity-30">·</span>
            <span className={cn(live?.stage === "DECIDED" ? "text-foreground/70" : "")}>
              DECIDED {live?.stage === "DECIDED" ? "01" : "00"}
            </span>
            <span className="opacity-30">·</span>
            <span>SEALED {String(stats.total).padStart(2, "0")}</span>
          </div>
          <button
            onClick={() => {
              pausedRef.current = !pausedRef.current;
              setPaused((p) => !p);
            }}
            className="font-mono text-[11px] uppercase tracking-widest px-3 py-1.5 border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors rounded-sm"
          >
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex flex-1 min-h-0">
        {/* ── Left: Queue ── */}
        <div className="w-52 shrink-0 border-r border-border flex flex-col">
          <div className="px-4 py-3 border-b border-border/60 flex items-center justify-between">
            <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/40">
              Agent Actions
            </span>
            <span className="font-mono text-[9px] text-muted-foreground/40">
              QUEUE {String(queue.length).padStart(2, "0")}
            </span>
          </div>

          <div className="flex-1 flex flex-col justify-start px-3 py-3 gap-2 overflow-hidden">
            {queue.length === 0 && !live && (
              <p className="font-mono text-[9px] text-muted-foreground/25 text-center mt-4">
                Awaiting actions…
              </p>
            )}
            {queue.slice(0, 5).map((a, i) => (
              <QueueCard key={a.id} action={a} position={i} isNext={i === 0} />
            ))}
          </div>

          <div className="px-4 py-3 border-t border-border/50 text-center">
            <span className="font-mono text-[9px] text-muted-foreground/30 uppercase tracking-widest">
              ↓ into REMORA Eye
            </span>
          </div>
        </div>

        {/* ── Center: Governance Eye ── */}
        <div className="flex-1 relative flex items-center justify-center overflow-hidden">
          {/* Stage label top */}
          <div className="absolute top-5 left-1/2 -translate-x-1/2 text-center select-none">
            <p className="font-mono text-[9px] uppercase tracking-[0.20em] text-muted-foreground/30">
              REMORA Eye Processing Queue
            </p>
          </div>

          {/* Processing beam (left guide → eye) */}
          <div
            className="absolute left-0 right-1/2 pointer-events-none"
            style={{ top: "50%", height: 1 }}
          >
            <div
              className="absolute inset-0"
              style={{ background: "oklch(0.85 0.006 260 / 0.30)" }}
            />
            {live?.stage === "PROCESSING" && (
              <div
                className="absolute inset-y-0"
                style={{
                  width: 60,
                  background: `linear-gradient(90deg, transparent, ${therm?.ringColor ?? "oklch(0.60 0.12 260)"}, transparent)`,
                  opacity: 0.7,
                  animation: "beam 2.2s ease-in-out infinite",
                }}
              />
            )}
          </div>

          {/* Right guide (eye → gate) */}
          <div
            className="absolute left-1/2 right-0 pointer-events-none"
            style={{ top: "50%", height: 1, background: "oklch(0.85 0.006 260 / 0.30)" }}
          >
            {live?.stage === "DECIDED" && (
              <div
                className="absolute inset-y-0 right-0"
                style={{
                  width: 60,
                  background: `linear-gradient(90deg, transparent, ${decidedState?.border ?? "oklch(0.68 0.12 155)"}, transparent)`,
                  opacity: 0.7,
                  animation: "beam 1.1s ease-in-out infinite reverse",
                }}
              />
            )}
          </div>

          {/* The eye */}
          <div className="relative z-10 select-none">
            <GovernanceEye live={live} tick={tick} pulse={pulseRef.current} />

            {/* Center overlay */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              {!live && (
                <>
                  <span className="font-serif text-base tracking-tight text-foreground/25">
                    REMORA
                  </span>
                  <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/25 mt-1">
                    Governance Engine
                  </span>
                </>
              )}
              {live?.stage === "PROCESSING" && (
                <>
                  <span className="font-mono text-[12px] uppercase tracking-[0.10em] text-foreground/70">
                    {currentPhaseLabel}
                  </span>
                  <span
                    className="font-mono text-[10px] mt-1.5 uppercase tracking-[0.14em] font-medium"
                    style={{ color: therm?.ringColor }}
                  >
                    {therm?.label}
                  </span>
                </>
              )}
              {live?.stage === "DECIDED" && (
                <>
                  <span
                    className="font-mono text-[15px] font-bold uppercase tracking-[0.08em]"
                    style={{ color: decidedState?.fg }}
                  >
                    {live.decision}
                  </span>
                  <span
                    className="font-mono text-[10px] mt-1 uppercase tracking-widest"
                    style={{ color: decidedState?.fg, opacity: 0.6 }}
                  >
                    {decidedState?.outcome}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Decision flash ring */}
          {live?.stage === "DECIDED" && (
            <div
              key={`ring-${live.id}-${live.decision}`}
              className="absolute rounded-full pointer-events-none"
              style={{
                width: 340,
                height: 340,
                border: `1.5px solid ${decidedState?.border}`,
                animation: "ping-once 1s ease-out forwards",
              }}
            />
          )}

          {/* Metrics halo around eye */}
          {live && (
            <>
              {/* Top: current action */}
              <div
                className="absolute font-mono text-[11px] text-center select-none"
                style={{ top: "calc(50% - 184px)" }}
              >
                <span className="text-foreground/55 uppercase tracking-widest text-[9px]">
                  {live.domain}
                </span>
                <span className="mx-2 opacity-30">·</span>
                <span className="text-foreground/70 font-medium">{shortAction(live.action)}</span>
              </div>

              {/* Left: trust / entropy */}
              <div className="absolute right-[calc(50%+162px)] text-right font-mono text-[11px] leading-6 select-none">
                <div>
                  <span className="text-muted-foreground/50">trust </span>
                  <span className="text-foreground/75 font-medium tabular-nums">
                    {live.trust.toFixed(3)}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground/50">entropy </span>
                  <span className="text-foreground/75 font-medium tabular-nums">
                    {live.entropy.toFixed(2)}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground/50">risk </span>
                  <span
                    className="font-semibold"
                    style={{
                      color:
                        live.risk === "critical"
                          ? STATE.ESCALATE.fg
                          : live.risk === "high"
                            ? STATE.VERIFY.fg
                            : STATE.ACCEPT.fg,
                    }}
                  >
                    {live.risk}
                  </span>
                </div>
              </div>

              {/* Right: phase / envelope */}
              <div className="absolute left-[calc(50%+162px)] font-mono text-[11px] leading-6 select-none">
                <div>
                  <span className="text-muted-foreground/50">phase </span>
                  <span className="font-semibold" style={{ color: therm?.ringColor }}>
                    {live.phase}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground/50">policy </span>
                  <span className="text-foreground/65">fail-closed</span>
                </div>
                <div>
                  <span className="text-muted-foreground/50">id </span>
                  <span className="text-foreground/55">{live.envelopeId}</span>
                </div>
              </div>

              {/* Bottom: processing phase progress */}
              <div
                className="absolute font-mono text-[9px] text-center select-none"
                style={{ bottom: "calc(50% - 178px)" }}
              >
                <div className="flex items-center gap-1.5 justify-center">
                  {PROCESSING_PHASES.slice(0, -1).map((ph, i) => {
                    const done = live.stage === "DECIDED" || i < live.processingPhaseIdx;
                    const active = live.stage === "PROCESSING" && i === live.processingPhaseIdx;
                    const layerColor = LAYERS[i]?.color ?? "oklch(0.70 0.01 260)";
                    return (
                      <div
                        key={ph}
                        className="w-1.5 h-1.5 rounded-full transition-all duration-200"
                        style={{
                          background: done
                            ? layerColor
                            : active
                              ? layerColor
                              : "oklch(0.88 0.006 260)",
                          opacity: done ? 0.8 : active ? 1 : 0.25,
                          boxShadow: active ? `0 0 6px ${layerColor}` : "none",
                        }}
                      />
                    );
                  })}
                </div>
                <div className="mt-1.5 text-muted-foreground/55 tracking-[0.14em] uppercase text-[9px] font-medium">
                  {live.stage === "PROCESSING" ? currentPhaseLabel : "Verdict sealed"}
                </div>
              </div>
            </>
          )}

          {/* Bottom label */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 select-none">
            <p className="font-mono text-[9px] text-muted-foreground/22 tracking-widest uppercase text-center">
              ACCEPT · VERIFY · ABSTAIN · ESCALATE
            </p>
          </div>
        </div>

        {/* ── Right: Execution gate + audit log ── */}
        <div className="w-64 shrink-0 border-l border-border flex flex-col">
          {/* Gate */}
          <div className="px-5 py-5 border-b border-border/60 flex flex-col items-center gap-0">
            <ExecutionGate live={live} stats={stats} />
          </div>

          {/* Audit log */}
          <div className="flex-1 min-h-0 flex flex-col">
            <div className="px-4 py-2.5 border-b border-border/50 flex items-center justify-between">
              <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/40">
                Audit Log
              </span>
              <div className="flex items-center gap-1.5">
                <div
                  className="w-1.5 h-1.5 rounded-full animate-pulse"
                  style={{ background: STATE.ACCEPT.fg }}
                />
                <span className="font-mono text-[9px] text-muted-foreground/35">sealed</span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto py-1" style={{ scrollbarWidth: "none" }}>
              {auditLog.length === 0 && (
                <p className="font-mono text-[9px] text-muted-foreground/28 text-center mt-6 px-4">
                  Awaiting sealed decisions…
                </p>
              )}
              {auditLog.map((e, i) => {
                const s = STATE[e.decision];
                return (
                  <div
                    key={e.id}
                    className={cn(
                      "px-3 py-2 border-b border-border/35",
                      i === 0 && "animate-fade-in",
                    )}
                    style={{
                      borderLeft: `2.5px solid ${s.border}`,
                      opacity: Math.max(0.18, 1 - i * 0.03),
                    }}
                  >
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="font-mono text-[11px] font-bold" style={{ color: s.fg }}>
                        {e.decision}
                      </span>
                      {/* Lock icon = tamper-evident */}
                      <svg width="9" height="10" viewBox="0 0 9 10" fill="none" opacity={0.5}>
                        <rect
                          x="1"
                          y="4.5"
                          width="7"
                          height="5"
                          rx="0.8"
                          stroke={s.fg}
                          strokeWidth="1"
                        />
                        <path d="M2.5 4.5V3a2 2 0 014 0v1.5" stroke={s.fg} strokeWidth="1" />
                      </svg>
                      <span className="font-mono text-[9px] text-muted-foreground/45 ml-auto tabular-nums">
                        {e.ts}
                      </span>
                    </div>
                    <div className="font-mono text-[10px] text-foreground/65 truncate">
                      {e.action}
                    </div>
                    <div className="font-mono text-[9px] mt-0.5 flex gap-1.5 items-center">
                      <span className="font-medium" style={{ color: s.fg, opacity: 0.7 }}>
                        {e.outcome}
                      </span>
                      <span className="text-muted-foreground/30">·</span>
                      <span className="text-muted-foreground/50">#{e.hash}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* ── Layer legend strip at bottom ── */}
      <div className="shrink-0 border-t border-border/50 px-6 py-2 flex items-center gap-6 bg-background/90">
        <span className="font-mono text-[8px] uppercase tracking-[0.18em] text-muted-foreground/30 shrink-0">
          Layers
        </span>
        {LAYERS.map((l, i) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <div
              className="w-2 h-2 rounded-full shrink-0"
              style={{ background: l.color, opacity: 0.7, boxShadow: `0 0 4px ${l.color}` }}
            />
            <span className="font-mono text-[8px] text-muted-foreground/45 whitespace-nowrap">
              {l.label}
            </span>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes ping-once {
          0%   { transform: scale(0.65); opacity: 0.55; }
          100% { transform: scale(1.5);  opacity: 0; }
        }
        @keyframes beam {
          0%   { left: -60px; }
          100% { left: 100%; }
        }
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(-3px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .animate-fade-in { animation: fade-in 0.2s ease-out; }
      `}</style>
    </div>
  );
}
