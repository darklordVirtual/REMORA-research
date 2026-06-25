import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader, SectionLabel } from "@/components/primitives";
import { buildTelemetry } from "@/lib/remora-sim";

export const Route = createFileRoute("/telemetry")({
  head: () => ({
    meta: [
      { title: "REMORA · Telemetry — golden signals, safety & utility" },
      {
        name: "description",
        content:
          "30-day rolling view of REMORA traffic, decision distribution, latency percentiles and safety metrics — modelled on the observability spec.",
      },
    ],
  }),
  component: TelemetryPage,
});

const VERDICT_COLORS = {
  ACCEPT: "var(--state-accept)",
  VERIFY: "var(--state-verify)",
  ABSTAIN: "var(--state-abstain)",
  ESCALATE: "var(--state-escalate)",
} as const;

interface SessionKPI {
  runs: number;
  accept: number;
  verify: number;
  abstain: number;
  escalate: number;
  unsafe_prevented: number;
  audit_entries: number;
  total_ms: number;
}

function readSessionKpi(): SessionKPI | null {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(localStorage.getItem("remora_session_kpi") ?? "null");
  } catch {
    return null;
  }
}

function TelemetryPage() {
  const data = useMemo(() => buildTelemetry(30), []);
  const session = useMemo(readSessionKpi, []);

  const totals = data.reduce(
    (a, d) => ({
      ACCEPT: a.ACCEPT + d.ACCEPT,
      VERIFY: a.VERIFY + d.VERIFY,
      ABSTAIN: a.ABSTAIN + d.ABSTAIN,
      ESCALATE: a.ESCALATE + d.ESCALATE,
      total: a.total + d.total,
      injection: a.injection + d.injection_blocked,
    }),
    { ACCEPT: 0, VERIFY: 0, ABSTAIN: 0, ESCALATE: 0, total: 0, injection: 0 },
  );

  const pie = (["ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"] as const).map((k) => ({
    name: k,
    value: totals[k],
    fill: VERDICT_COLORS[k],
  }));

  const slos = [
    { label: "Audit completeness", value: "100.0%", target: "≥ 99.9%", ok: true },
    { label: "Critical autonomous actions", value: "0", target: "0", ok: true },
    { label: "Tool allowlist violations", value: "0", target: "0", ok: true },
    { label: "P95 low-risk latency", value: "1.92 s", target: "< 5 s", ok: true },
    { label: "Unsafe execution rate", value: "0.00%", target: "0", ok: true },
    { label: "Injection intercept rate", value: "100%", target: "100%", ok: true },
  ];

  const sessionTimeSavedMin = session
    ? session.accept * 12 + session.verify * 6 + session.abstain * 3
    : 0;
  const sessionTimeSaved =
    sessionTimeSavedMin >= 60
      ? `${(sessionTimeSavedMin / 60).toFixed(1)} hrs`
      : `${sessionTimeSavedMin} min`;
  const sessionAutoRate =
    session && session.runs > 0
      ? (((session.accept + session.verify + session.abstain) / session.runs) * 100).toFixed(0)
      : null;
  const sessionAvgMs =
    session && session.runs > 0 ? Math.round(session.total_ms / session.runs) : null;

  return (
    <div className="mx-auto max-w-6xl px-6 pt-16 pb-24">
      <PageHeader
        eyebrow="REMORA · golden signals"
        title="Telemetry."
        lede="Operational view of the control plane: throughput, decision mix, latency percentiles, safety metrics, SLO posture. A safe-but-useless system escalates everything; a useful-but-unsafe one executes too much."
      />

      {session && session.runs > 0 && (
        <section className="mt-12">
          <SectionLabel number="00">Live session</SectionLabel>
          <div className="mt-4 font-mono text-[10px] text-muted-foreground/72 mb-3">
            Data from the active Control Room session — updates each time you return here.
          </div>
          <div className="grid gap-px bg-border grid-cols-3 md:grid-cols-6">
            <Stat label="Decisions" value={session.runs.toLocaleString()} />
            <Stat
              label="Accept"
              value={session.accept.toString()}
              sub="auto-approved"
              accent="accept"
            />
            <Stat
              label="Verify"
              value={session.verify.toString()}
              sub="human confirmed"
              accent="verify"
            />
            <Stat
              label="Escalate"
              value={session.escalate.toString()}
              sub="human required"
              accent="escalate"
            />
            <Stat label="Autonomous rate" value={`${sessionAutoRate}%`} />
            <Stat label="Time saved" value={sessionTimeSaved} accent="accept" />
          </div>
          {sessionAvgMs && (
            <div className="mt-3 font-mono text-[10px] text-muted-foreground/68">
              Avg decision latency this session: {sessionAvgMs}ms · {session.audit_entries} audit
              entries written
            </div>
          )}
        </section>
      )}

      <section className="mt-12">
        <SectionLabel number="01">30-day simulation</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-4">
          <Stat label="Total decisions" value={totals.total.toLocaleString()} />
          <Stat
            label="Acceptance rate"
            value={`${((totals.ACCEPT / totals.total) * 100).toFixed(1)}%`}
          />
          <Stat
            label="Escalation rate"
            value={`${((totals.ESCALATE / totals.total) * 100).toFixed(1)}%`}
          />
          <Stat label="Injections blocked" value={totals.injection.toString()} />
        </div>
      </section>

      <section className="mt-12">
        <SectionLabel number="02">Decisions over time — 30-day simulation</SectionLabel>
        <div className="mt-6 border border-border p-4 h-72">
          <ResponsiveContainer>
            <AreaChart data={data} margin={{ top: 10, right: 12, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
              <XAxis
                dataKey="day"
                stroke="var(--muted-foreground)"
                fontSize={10}
                tickLine={false}
              />
              <YAxis stroke="var(--muted-foreground)" fontSize={10} tickLine={false} />
              <Tooltip
                contentStyle={{
                  background: "var(--background)",
                  border: "1px solid var(--border)",
                  fontSize: 11,
                  fontFamily: "var(--font-mono)",
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)" }} />
              <Area
                type="monotone"
                dataKey="ACCEPT"
                stackId="1"
                stroke={VERDICT_COLORS.ACCEPT}
                fill={VERDICT_COLORS.ACCEPT}
                fillOpacity={0.5}
              />
              <Area
                type="monotone"
                dataKey="VERIFY"
                stackId="1"
                stroke={VERDICT_COLORS.VERIFY}
                fill={VERDICT_COLORS.VERIFY}
                fillOpacity={0.5}
              />
              <Area
                type="monotone"
                dataKey="ABSTAIN"
                stackId="1"
                stroke={VERDICT_COLORS.ABSTAIN}
                fill={VERDICT_COLORS.ABSTAIN}
                fillOpacity={0.4}
              />
              <Area
                type="monotone"
                dataKey="ESCALATE"
                stackId="1"
                stroke={VERDICT_COLORS.ESCALATE}
                fill={VERDICT_COLORS.ESCALATE}
                fillOpacity={0.6}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="mt-12 grid gap-10 lg:grid-cols-2">
        <div>
          <SectionLabel number="03">Verdict distribution</SectionLabel>
          <div className="mt-6 border border-border p-4 h-72">
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={pie}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={55}
                  outerRadius={95}
                  strokeWidth={1}
                  stroke="var(--background)"
                >
                  {pie.map((p) => (
                    <Cell key={p.name} fill={p.fill} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "var(--background)",
                    border: "1px solid var(--border)",
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)" }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div>
          <SectionLabel number="04">Latency (P50 / P95)</SectionLabel>
          <div className="mt-6 border border-border p-4 h-72">
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 10, right: 12, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
                <XAxis
                  dataKey="day"
                  stroke="var(--muted-foreground)"
                  fontSize={10}
                  tickLine={false}
                />
                <YAxis stroke="var(--muted-foreground)" fontSize={10} tickLine={false} unit="ms" />
                <Tooltip
                  contentStyle={{
                    background: "var(--background)",
                    border: "1px solid var(--border)",
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)" }} />
                <Line
                  type="monotone"
                  dataKey="p50"
                  stroke="var(--signal)"
                  strokeWidth={1.5}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="p95"
                  stroke="var(--state-verify)"
                  strokeWidth={1.5}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      <section className="mt-12">
        <SectionLabel number="05">Adversarial intercepts (daily)</SectionLabel>
        <div className="mt-6 border border-border p-4 h-56">
          <ResponsiveContainer>
            <BarChart data={data} margin={{ top: 10, right: 12, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="var(--border)" />
              <XAxis
                dataKey="day"
                stroke="var(--muted-foreground)"
                fontSize={10}
                tickLine={false}
              />
              <YAxis stroke="var(--muted-foreground)" fontSize={10} tickLine={false} />
              <Tooltip
                contentStyle={{
                  background: "var(--background)",
                  border: "1px solid var(--border)",
                  fontSize: 11,
                  fontFamily: "var(--font-mono)",
                }}
              />
              <Bar dataKey="injection_blocked" fill="var(--state-escalate)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="mt-12">
        <SectionLabel number="06">Pilot SLOs</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-3">
          {slos.map((s) => (
            <div key={s.label} className="bg-background p-5">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                {s.label}
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-serif text-2xl tracking-tight">{s.value}</span>
                <span
                  className={`font-mono text-[10px] uppercase tracking-widest ${s.ok ? "text-state-accept" : "text-state-escalate"}`}
                >
                  {s.ok ? "ok" : "breach"}
                </span>
              </div>
              <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                target {s.target}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "accept" | "verify" | "escalate";
}) {
  const vc =
    accent === "accept"
      ? "text-state-accept"
      : accent === "verify"
        ? "text-state-verify"
        : accent === "escalate"
          ? "text-state-escalate"
          : "";
  return (
    <div className="bg-background p-5">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
        {label}
      </div>
      <div className={`mt-2 font-serif text-3xl tracking-tight tabular-nums ${vc}`}>{value}</div>
      {sub && <div className="mt-1 font-mono text-[11px] text-muted-foreground/68">{sub}</div>}
    </div>
  );
}
