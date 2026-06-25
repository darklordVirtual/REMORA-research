import { createFileRoute } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { PageHeader, SectionLabel } from "@/components/primitives";
import {
  BENCHMARK_DASHBOARD,
  ARTIFACT_PATHS,
  buildBenchmarkDashboard,
  formatDecimal,
  formatPercent,
  type BenchmarkArtifactMap,
  type BenchmarkDashboard,
  type ClaimStatus,
  type ToolcallStrategyRow,
} from "@/content/benchmark-artifacts";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/benchmarks")({
  head: () => ({
    meta: [
      { title: "REMORA Benchmarks" },
      {
        name: "description",
        content: "Artifact-backed benchmark dashboard for REMORA with live GitHub Actions status.",
      },
      { property: "og:title", content: "REMORA Benchmarks" },
      {
        property: "og:description",
        content:
          "Frontend benchmark metrics derived from committed result artifacts, with CI status polling.",
      },
    ],
  }),
  component: BenchmarksPage,
});

type GithubRun = {
  id: number;
  name: string;
  status: "queued" | "in_progress" | "completed";
  conclusion: "success" | "failure" | "cancelled" | "skipped" | null;
  html_url: string;
  created_at: string;
  updated_at: string;
  head_sha: string;
};

type RunState =
  | { state: "loading"; runs: GithubRun[]; updatedAt: null }
  | { state: "ready"; runs: GithubRun[]; updatedAt: Date }
  | { state: "error"; runs: GithubRun[]; updatedAt: Date | null };

type ArtifactState =
  | { state: "snapshot"; dashboard: BenchmarkDashboard; updatedAt: null }
  | { state: "loading"; dashboard: BenchmarkDashboard; updatedAt: null }
  | { state: "live"; dashboard: BenchmarkDashboard; updatedAt: Date }
  | { state: "error"; dashboard: BenchmarkDashboard; updatedAt: Date | null };

const RAW_ARTIFACT_BASE = "https://raw.githubusercontent.com/darklordVirtual/REMORA/main/";

const statusLabels: Record<ClaimStatus, string> = {
  holdout: "HOLDOUT",
  simulator_only: "SIMULATOR",
  in_sample: "IN-SAMPLE",
  calibration: "CALIBRATION",
  live_ci: "LIVE CI",
};

const statusClasses: Record<ClaimStatus, string> = {
  holdout: "border-state-accept text-state-accept",
  simulator_only: "border-state-verify text-state-verify",
  in_sample: "border-state-escalate text-state-escalate",
  calibration: "border-signal text-signal",
  live_ci: "border-foreground text-foreground",
};

function BenchmarksPage() {
  const { runState, refresh } = useGithubRuns();
  const { artifactState, dashboard, refreshArtifacts } = useBenchmarkArtifacts();
  const latestQuality = useMemo(
    () => runState.runs.find((run) => run.name === "Quality Gates"),
    [runState.runs],
  );
  const artifactSource =
    artifactState.state === "live"
      ? "GitHub main artifacts"
      : artifactState.state === "error"
        ? "snapshot fallback"
        : "loading GitHub artifacts";

  return (
    <div className="mx-auto max-w-7xl px-6 pt-16 pb-24">
      <PageHeader
        eyebrow="REMORA benchmarks"
        title="Artifact-backed benchmark control."
        lede="A dedicated benchmark page should be boring in the best way: every number is derived from committed result artifacts, every source is named, and CI status is separated from measured benchmark claims."
      />

      <section className="mt-10 border-y border-border py-4">
        <div className="grid gap-4 md:grid-cols-[1.5fr_1fr_auto] md:items-center">
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              Artifact source
            </div>
            <div className="mt-1 font-mono text-sm text-foreground">
              {artifactSource} / {dashboard.artifactFingerprint}
            </div>
          </div>
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              Latest quality gate
            </div>
            <div className="mt-1 text-sm">
              {latestQuality ? (
                <a
                  href={latestQuality.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(
                    "font-mono hover:underline",
                    latestQuality.conclusion === "success"
                      ? "text-state-accept"
                      : latestQuality.status === "completed"
                        ? "text-state-escalate"
                        : "text-state-verify",
                  )}
                >
                  {latestQuality.status}
                  {latestQuality.conclusion ? ` / ${latestQuality.conclusion}` : ""}
                </a>
              ) : (
                <span className="font-mono text-muted-foreground">waiting</span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              void refresh();
              void refreshArtifacts();
            }}
            className="inline-flex h-10 items-center justify-center gap-2 border border-border px-3 text-sm hover:border-foreground transition-colors"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Refresh data
          </button>
        </div>
        <p className="mt-3 max-w-3xl text-xs leading-relaxed text-muted-foreground">
          Metrics below are refreshed from the public `main` branch `results/*.json` artifacts when
          reachable. The generated frontend snapshot is the tested fallback. The CI strip polls
          public GitHub Actions status every 60 seconds, so readers can distinguish benchmark
          evidence from the latest test run state.
        </p>
      </section>

      <section className="mt-12">
        <SectionLabel number="01">Headline metrics</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-2 xl:grid-cols-4">
          {dashboard.metricTiles.map((tile) => (
            <MetricTile key={tile.label} tile={tile} />
          ))}
        </div>
      </section>

      <section className="mt-14">
        <SectionLabel number="02">Tool-call v2 safety and utility</SectionLabel>
        <p className="mt-4 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          This table is simulator-scoped. It is useful because it checks whether REMORA's policy
          gate can reduce unsafe dry-run execution while preserving task utility, but it is not a
          live production result.
        </p>
        <ToolcallComparison rows={dashboard.toolcallRows} />
      </section>

      <section className="mt-14 grid gap-12 lg:grid-cols-[1fr_1fr]">
        <div>
          <SectionLabel number="03">N500 policy distribution</SectionLabel>
          <div className="mt-6 border-y border-border">
            {dashboard.policyRows.map((row) => (
              <div
                key={row.action}
                className="grid grid-cols-[100px_1fr_90px] gap-4 border-b border-border/60 py-4 last:border-0"
              >
                <div className="font-mono text-[11px] text-muted-foreground">{row.action}</div>
                <div>
                  <div className="h-2 bg-muted">
                    <div
                      className={cn(
                        "h-2",
                        row.action === "ACCEPT" && "bg-state-accept",
                        row.action === "VERIFY" && "bg-state-verify",
                        row.action === "ABSTAIN" && "bg-state-abstain",
                        row.action === "ESCALATE" && "bg-state-escalate",
                      )}
                      style={{ width: formatPercent(row.share, 2) }}
                    />
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    accuracy {formatPercent(row.accuracy)} / risk {formatPercent(row.risk)}
                  </div>
                </div>
                <div className="text-right font-mono text-sm tabular-nums">
                  {row.count}{" "}
                  <span className="text-muted-foreground">{formatPercent(row.share)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <SectionLabel number="04">Conformal holdout</SectionLabel>
          <div className="mt-6 border-y border-border">
            {dashboard.conformalRows.map((row) => (
              <div
                key={row.targetRisk}
                className="grid grid-cols-[90px_1fr] gap-4 border-b border-border/60 py-4 last:border-0"
              >
                <div className="font-mono text-[11px] text-muted-foreground">
                  {formatPercent(row.targetRisk, 0)} target
                </div>
                <div>
                  <div className="grid gap-2 text-sm sm:grid-cols-4">
                    <Scalar label="risk" value={formatPercent(row.observedRisk)} />
                    <Scalar label="coverage" value={formatPercent(row.coverage)} />
                    <Scalar label="accepted" value={row.accepted.toString()} />
                    <Scalar label="upper bound" value={row.upperBoundMet ? "met" : "missed"} />
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    threshold {formatDecimal(row.threshold, 4)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mt-14">
        <SectionLabel number="05">Evidence sources and commands</SectionLabel>
        <div className="mt-6 overflow-x-auto border-y border-border">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border">
                <HeadCell align="left">Artifact</HeadCell>
                <HeadCell align="left">Scope</HeadCell>
                <HeadCell align="left">Regenerate</HeadCell>
                <HeadCell align="left">Test</HeadCell>
              </tr>
            </thead>
            <tbody>
              {dashboard.sourceArtifacts.map((source) => (
                <tr key={source.path} className="border-b border-border/60 last:border-0">
                  <td className="px-4 py-4 font-medium">{source.label}</td>
                  <td className="px-4 py-4 text-muted-foreground">{source.scope}</td>
                  <td className="px-4 py-4 font-mono text-xs">{source.regenerate}</td>
                  <td className="px-4 py-4 font-mono text-xs">{source.test}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-14">
        <SectionLabel number="06">Claim boundaries</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-2">
          {dashboard.claimBoundaries.map((boundary) => (
            <div key={boundary} className="bg-background p-5 text-sm leading-relaxed">
              {boundary}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function MetricTile({ tile }: { tile: BenchmarkDashboard["metricTiles"][number] }) {
  return (
    <article className="bg-background p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
          {tile.label}
        </div>
        <span
          className={cn(
            "border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]",
            statusClasses[tile.status],
          )}
        >
          {statusLabels[tile.status]}
        </span>
      </div>
      <div className="mt-6 font-serif text-5xl tracking-tight">{tile.value}</div>
      <p className="mt-4 text-sm leading-relaxed text-muted-foreground">{tile.detail}</p>
      <div className="mt-4 font-mono text-[10px] text-muted-foreground/80">{tile.source}</div>
    </article>
  );
}

function ToolcallComparison({ rows }: { rows: ToolcallStrategyRow[] }) {
  const maxUnsafe = Math.max(...rows.map((row) => row.unsafeExecutionRate), 0.001);
  const maxUtility = Math.max(...rows.map((row) => Math.max(row.meanUtility, 0)), 0.001);

  return (
    <div className="mt-6 overflow-x-auto border-y border-border">
      <table className="w-full min-w-[920px] text-sm">
        <thead>
          <tr className="border-b border-border">
            <HeadCell align="left">Strategy</HeadCell>
            <HeadCell>Unsafe rate</HeadCell>
            <HeadCell>Utility</HeadCell>
            <HeadCell>Accuracy</HeadCell>
            <HeadCell>False accept</HeadCell>
            <HeadCell>Critical intercept</HeadCell>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={cn(
                "border-b border-border/60 last:border-0",
                row.id === "remora_full_policy_gate" && "bg-muted/40",
              )}
            >
              <td className="px-4 py-4 font-medium">{row.name}</td>
              <td className="px-4 py-4">
                <BarMetric
                  value={formatPercent(row.unsafeExecutionRate)}
                  width={`${(row.unsafeExecutionRate / maxUnsafe) * 100}%`}
                  tone={row.unsafeExecutionRate === 0 ? "accept" : "escalate"}
                />
              </td>
              <td className="px-4 py-4">
                <BarMetric
                  value={formatDecimal(row.meanUtility, 2)}
                  width={`${(Math.max(row.meanUtility, 0) / maxUtility) * 100}%`}
                  tone="verify"
                />
              </td>
              <td className="px-4 py-4 text-right font-mono tabular-nums">
                {formatPercent(row.accuracy)}
              </td>
              <td className="px-4 py-4 text-right font-mono tabular-nums">
                {formatPercent(row.falseAcceptRate)}
              </td>
              <td className="px-4 py-4 text-right font-mono tabular-nums">
                {formatPercent(row.criticalInterceptRate)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BarMetric({
  value,
  width,
  tone,
}: {
  value: string;
  width: string;
  tone: "accept" | "verify" | "escalate";
}) {
  return (
    <div className="grid grid-cols-[80px_1fr] items-center gap-3">
      <span className="text-right font-mono tabular-nums">{value}</span>
      <span className="block h-2 bg-muted">
        <span
          className={cn(
            "block h-2 min-w-[2px]",
            tone === "accept" && "bg-state-accept",
            tone === "verify" && "bg-state-verify",
            tone === "escalate" && "bg-state-escalate",
          )}
          style={{ width }}
        />
      </span>
    </div>
  );
}

function Scalar({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm tabular-nums">{value}</div>
    </div>
  );
}

function HeadCell({
  children,
  align = "right",
}: {
  children: ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={cn(
        "px-4 py-3 font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground font-normal",
        align === "left" ? "text-left" : "text-right",
      )}
    >
      {children}
    </th>
  );
}

function useGithubRuns() {
  const [runState, setRunState] = useState<RunState>({
    state: "loading",
    runs: [],
    updatedAt: null,
  });

  const load = useCallback(async () => {
    try {
      const response = await fetch(
        "https://api.github.com/repos/darklordVirtual/REMORA/actions/runs?branch=main&per_page=12",
      );
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
      const payload = (await response.json()) as { workflow_runs?: GithubRun[] };
      setRunState({
        state: "ready",
        runs: payload.workflow_runs ?? [],
        updatedAt: new Date(),
      });
    } catch {
      setRunState((prev) => ({
        state: "error",
        runs: prev.runs,
        updatedAt: prev.updatedAt,
      }));
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  return { runState, refresh: load };
}

function useBenchmarkArtifacts() {
  const [artifactState, setArtifactState] = useState<ArtifactState>({
    state: "snapshot",
    dashboard: BENCHMARK_DASHBOARD,
    updatedAt: null,
  });

  const load = useCallback(async () => {
    setArtifactState((prev) => ({
      state: prev.state === "live" ? "live" : "loading",
      dashboard: prev.dashboard,
      updatedAt: prev.updatedAt,
    }));

    try {
      const entries = await Promise.all(
        Object.values(ARTIFACT_PATHS).map(async (path) => {
          const response = await fetch(`${RAW_ARTIFACT_BASE}${path}?t=${Date.now()}`);
          if (!response.ok) throw new Error(`GitHub raw returned ${response.status}`);
          return [path, await response.json()] as const;
        }),
      );
      const artifacts = Object.fromEntries(entries) as BenchmarkArtifactMap;
      setArtifactState({
        state: "live",
        dashboard: buildBenchmarkDashboard(artifacts),
        updatedAt: new Date(),
      });
    } catch {
      setArtifactState((prev) => ({
        state: "error",
        dashboard: prev.dashboard,
        updatedAt: prev.updatedAt,
      }));
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  return { artifactState, dashboard: artifactState.dashboard, refreshArtifacts: load };
}
