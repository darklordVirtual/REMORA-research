import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DecisionChip, SectionLabel } from "@/components/primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  pilotApi,
  type EvidenceRunRow,
  type PilotRole,
  type PilotState,
  type Scenario,
} from "./api";

const DECISIONS = ["accept", "verify", "abstain", "escalate"] as const;

const DECISION_BAR: Record<(typeof DECISIONS)[number], string> = {
  accept: "bg-state-accept",
  verify: "bg-state-verify",
  abstain: "bg-state-abstain",
  escalate: "bg-state-escalate",
};

type ChipState = "ACCEPT" | "VERIFY" | "ABSTAIN" | "ESCALATE";

function chipState(decision: string | undefined): ChipState | null {
  const upper = (decision ?? "").toUpperCase();
  return (["ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"] as const).find((s) => s === upper) ?? null;
}

function StatusPill({ live, children }: { live: boolean; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "border px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.1em]",
        live
          ? "border-state-accept text-state-accept"
          : "border-state-escalate text-state-escalate",
      )}
    >
      {children}
    </span>
  );
}

function Panel({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <section className={cn("border border-border bg-card p-6", className)}>{children}</section>
  );
}

function Kpi({ label, value, sub }: { label: string; value: React.ReactNode; sub: string }) {
  return (
    <div className="border-l border-border first:border-l-0 px-5 py-4">
      <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 font-mono text-3xl tabular-nums tracking-tight">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) {
    return (
      <div className="flex h-[120px] items-center text-xs text-muted-foreground">collecting…</div>
    );
  }
  const w = 600;
  const h = 120;
  const pad = 6;
  const max = Math.max(1, ...points);
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (points.length - 1);
  const y = (v: number) => h - pad - (v / max) * (h - 2 * pad);
  const line = points.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const area = `${pad},${h - pad} ${line} ${x(points.length - 1)},${h - pad}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-[120px] w-full" preserveAspectRatio="none">
      <polygon points={area} className="fill-signal/15" />
      <polyline points={line} className="fill-none stroke-signal" strokeWidth={1.5} />
    </svg>
  );
}

function DecisionMix({ counts }: { counts: Record<string, number> }) {
  const max = Math.max(1, ...DECISIONS.map((d) => counts[d] ?? 0));
  return (
    <div className="space-y-2.5">
      {DECISIONS.map((d) => {
        const v = counts[d] ?? 0;
        return (
          <div key={d} className="grid grid-cols-[90px_1fr_44px] items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground">{d}</span>
            <div className="h-2 overflow-hidden bg-muted">
              <div
                className={cn("h-full transition-all", DECISION_BAR[d])}
                style={{ width: `${(v / max) * 100}%` }}
              />
            </div>
            <span className="text-right font-mono text-sm tabular-nums">{v}</span>
          </div>
        );
      })}
    </div>
  );
}

function PostureRow({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="m-0 truncate font-mono text-xs">{v}</dd>
    </>
  );
}

function ScenarioButtons({
  scenarios,
  disabled,
  onRun,
}: {
  scenarios: Scenario[];
  disabled: boolean;
  onRun: (s: Scenario) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      {scenarios.map((s) => (
        <Button
          key={s.label}
          variant="outline"
          disabled={disabled}
          onClick={() => onRun(s)}
          className="h-auto flex-col items-start gap-1 whitespace-normal rounded-none px-4 py-3 text-left"
        >
          <span className="text-sm font-medium leading-snug">{s.label}</span>
          <span className="text-xs font-normal text-muted-foreground">{s.expect}</span>
        </Button>
      ))}
    </div>
  );
}

function EvidenceRow({
  run,
  onManifest,
}: {
  run: EvidenceRunRow;
  onManifest: (runId: string) => void;
}) {
  if (run.error) {
    return (
      <TableRow>
        <TableCell className="font-mono text-xs">{run.run_id.slice(0, 8)}</TableCell>
        <TableCell colSpan={5} className="text-xs text-muted-foreground">
          {run.error}
        </TableCell>
      </TableRow>
    );
  }
  const s = run.summary ?? {};
  const a = run.audit ?? {};
  const chainsOk = Boolean(a.tenant_chain_valid && a.execution_chain_valid);
  return (
    <TableRow>
      <TableCell title={run.run_id} className="font-mono text-xs">
        {run.run_id.slice(0, 8)}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">{run.finished_at ?? "?"}</TableCell>
      <TableCell className="text-right font-mono text-sm tabular-nums">
        {s.cases_passed ?? "?"} / {s.cases_total ?? "?"}
        {(s.cases_failed ?? 0) > 0 && (
          <span className="ml-1 text-state-escalate">({s.cases_failed} failed)</span>
        )}
      </TableCell>
      <TableCell
        className={cn("font-mono text-xs", chainsOk ? "text-state-accept" : "text-state-escalate")}
      >
        {chainsOk ? "valid" : "check"}
      </TableCell>
      <TableCell className="text-right font-mono text-sm tabular-nums">
        {run.exit_code ?? "?"}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            className="rounded-none"
            onClick={() => onManifest(run.run_id)}
          >
            Manifest
          </Button>
          <Button variant="outline" size="sm" className="rounded-none" asChild>
            <a href={pilotApi.evidenceArchiveUrl(run.run_id)} download>
              Download
            </a>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

export function PilotApp() {
  const queryClient = useQueryClient();
  const [role, setRole] = useState<PilotRole>("operator");
  const [output, setOutput] = useState(
    "Select a scenario or run the full battery to inspect the live result payload.",
  );
  const [verdict, setVerdict] = useState<ChipState | null>(null);
  const [requestId, setRequestId] = useState("");
  const [envelopeOut, setEnvelopeOut] = useState(
    "Enter a request_id to inspect the stored DecisionEnvelope and related metadata.",
  );
  const [manifestOut, setManifestOut] = useState(
    "Pick a run and open its manifest, or download the zip bundle for offline audit review.",
  );
  const historyRef = useRef<number[]>([]);
  const [history, setHistory] = useState<number[]>([]);

  const state = useQuery<PilotState>({
    queryKey: ["pilot-state"],
    queryFn: pilotApi.state,
    refetchInterval: 3000,
  });
  const scenarios = useQuery<Scenario[]>({ queryKey: ["scenarios"], queryFn: pilotApi.scenarios });
  const evidence = useQuery({ queryKey: ["evidence-runs"], queryFn: pilotApi.evidenceRuns });

  const m = state.data?.metrics ?? {};
  const policy = state.data?.policy ?? {};
  const healthy = state.data?.health?.status === "ok";
  const durable = Boolean(policy.execution_state_durable);
  const refusals = Object.entries(m.execution_refusals ?? {}).filter(([, v]) => v > 0);
  const refusalTotal = refusals.reduce((acc, [, v]) => acc + v, 0);
  const chainValid = Boolean(state.data?.chain?.chain_valid);

  useEffect(() => {
    if (state.data === undefined) return;
    const next = [...historyRef.current, m.execution_tool_calls_executed ?? 0].slice(-120);
    historyRef.current = next;
    setHistory(next);
  }, [state.data, m.execution_tool_calls_executed]);

  const callMutation = useMutation({
    mutationFn: ({ scenario }: { scenario: Scenario }) =>
      pilotApi.governedCall(role, scenario.payload),
    onMutate: () => {
      setVerdict(null);
      setOutput("calling…");
    },
    onSuccess: (r) => {
      setVerdict(chipState(r.body.decision));
      setOutput(`HTTP ${r.status} · as ${r.role}\n\n${JSON.stringify(r.body, null, 2)}`);
      void state.refetch();
    },
    onError: (err) => setOutput(`console error: ${String(err)}`),
  });

  const batteryMutation = useMutation({
    mutationFn: pilotApi.runBattery,
    onMutate: () => {
      setVerdict(null);
      setOutput("running the OT battery — this drives real approvals and side effects…");
    },
    onSuccess: (text) => {
      setOutput(text);
      void state.refetch();
      void queryClient.invalidateQueries({ queryKey: ["evidence-runs"] });
    },
    onError: (err) => setOutput(`console error: ${String(err)}`),
  });

  const loadEnvelope = async () => {
    const id = requestId.trim();
    if (!id) {
      setEnvelopeOut("Enter a request_id first.");
      return;
    }
    try {
      setEnvelopeOut(JSON.stringify(await pilotApi.envelope(id), null, 2));
    } catch (err) {
      setEnvelopeOut(`console error: ${String(err)}`);
    }
  };

  const loadManifest = async (runId: string) => {
    setManifestOut("loading manifest…");
    try {
      setManifestOut(JSON.stringify(await pilotApi.evidenceManifest(runId), null, 2));
    } catch (err) {
      setManifestOut(`console error: ${String(err)}`);
    }
  };

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border px-8 py-4">
        <div className="flex flex-wrap items-center gap-4">
          <span className="font-serif text-xl tracking-tight">REMORA</span>
          <span className="border border-border px-2 py-0.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
            OT Pilot Console
          </span>
          <span className="hidden font-mono text-[11px] text-muted-foreground/70 lg:block">
            production-mode enforcement · durable audit chains · human approval
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <StatusPill live={healthy}>
            {state.isError
              ? "console offline"
              : healthy
                ? (policy.runtime_mode ?? "up")
                : "api unreachable"}
          </StatusPill>
          <StatusPill live={durable}>
            {durable ? `durable · ${policy.execution_state_backend}` : "state NOT durable"}
          </StatusPill>
          <span className="text-xs text-muted-foreground">
            Docs ·{" "}
            <a
              className="text-signal hover:underline"
              href="http://localhost:8080/docs"
              target="_blank"
              rel="noopener noreferrer"
            >
              Swagger
            </a>{" "}
            ·{" "}
            <a
              className="text-signal hover:underline"
              href="http://localhost:8080/metrics"
              target="_blank"
              rel="noopener noreferrer"
            >
              Prometheus
            </a>
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1440px] px-8 pb-20 pt-8">
        <div className="grid grid-cols-2 border-y border-border lg:grid-cols-5">
          <Kpi
            label="Governed decisions"
            value={m.execution_assess_total ?? "–"}
            sub="through the live governance API"
          />
          <Kpi
            label="Human approvals"
            value={m.execution_approvals_total ?? "–"}
            sub="review and approval workflow"
          />
          <Kpi
            label="Confirmed side effects"
            value={m.execution_tool_calls_executed ?? "–"}
            sub="dispatcher-visible execution"
          />
          <Kpi
            label="Refusals at enforcement"
            value={refusalTotal}
            sub="policy, replay, and lease checks"
          />
          <Kpi
            label="Audit chain"
            value={
              <span className={chainValid ? "text-state-accept" : "text-state-escalate"}>
                {chainValid ? "valid" : "check"}
              </span>
            }
            sub="hash-chain verification status"
          />
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <Panel>
            <SectionLabel>Decision mix</SectionLabel>
            <div className="mt-4">
              <DecisionMix counts={m.execution_decision_counts ?? {}} />
            </div>
            <div className="mt-6">
              <SectionLabel>Execution visibility</SectionLabel>
            </div>
            <div className="mt-3">
              <Sparkline points={history} />
            </div>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              This view stays close to the real control plane: metrics, decision counts, and audit
              verification are all fed from the same API endpoints used in enterprise deployments.
            </p>
          </Panel>
          <Panel>
            <SectionLabel>Refusals by reason</SectionLabel>
            <Table className="mt-3">
              <TableHeader>
                <TableRow>
                  <TableHead>Reason</TableHead>
                  <TableHead className="text-right">Count</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {refusals.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={2} className="text-xs text-muted-foreground">
                      none yet
                    </TableCell>
                  </TableRow>
                ) : (
                  refusals.map(([reason, count]) => (
                    <TableRow key={reason}>
                      <TableCell className="font-mono text-xs">{reason}</TableCell>
                      <TableCell className="text-right font-mono text-sm tabular-nums">
                        {count}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
            <div className="mt-6">
              <SectionLabel>Deployment posture</SectionLabel>
            </div>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-5 gap-y-1.5 text-sm">
              <PostureRow k="runtime" v={policy.runtime_mode ?? "?"} />
              <PostureRow k="policy" v={`${(policy.policy_hash ?? "?").slice(0, 24)}…`} />
              <PostureRow k="exec state" v={policy.execution_state_backend ?? "?"} />
              <PostureRow k="envelopes" v={m.control_plane_backend ?? "?"} />
            </dl>
          </Panel>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
          <Panel>
            <SectionLabel>Run a governed call</SectionLabel>
            <div className="mt-4 flex items-center gap-3">
              <span className="text-xs text-muted-foreground">Act as</span>
              <Select value={role} onValueChange={(v) => setRole(v as PilotRole)}>
                <SelectTrigger className="w-56 rounded-none">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="operator">operator (ot-agent)</SelectItem>
                  <SelectItem value="approver">approver (ot-approver)</SelectItem>
                  <SelectItem value="viewer">viewer (ot-viewer)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="mt-4">
              <ScenarioButtons
                scenarios={scenarios.data ?? []}
                disabled={callMutation.isPending}
                onRun={(scenario) => callMutation.mutate({ scenario })}
              />
            </div>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Each action uses the real API path and demonstrates how role-based access and policy
              enforcement change the outcome.
            </p>
          </Panel>
          <Panel>
            <SectionLabel>Live result</SectionLabel>
            <div className="mt-4 flex items-center gap-3">
              <Button
                className="rounded-none"
                disabled={batteryMutation.isPending}
                onClick={() => batteryMutation.mutate()}
              >
                Run the 15-case OT battery
              </Button>
              {batteryMutation.isPending && (
                <span className="text-xs text-muted-foreground">running 15 cases…</span>
              )}
            </div>
            {verdict && (
              <div className="mt-4">
                <DecisionChip state={verdict} />
              </div>
            )}
            <pre className="mt-4 max-h-[460px] overflow-auto whitespace-pre-wrap break-words border border-border bg-muted p-4 font-mono text-xs leading-relaxed">
              {output}
            </pre>
          </Panel>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Panel>
            <SectionLabel>Envelope inspection</SectionLabel>
            <div className="mt-4 flex gap-2">
              <Input
                value={requestId}
                onChange={(e) => setRequestId(e.target.value)}
                placeholder="request_id"
                className="rounded-none font-mono text-xs"
              />
              <Button
                variant="outline"
                className="rounded-none"
                onClick={() => void loadEnvelope()}
              >
                Load envelope
              </Button>
            </div>
            <pre className="mt-4 max-h-[300px] overflow-auto whitespace-pre-wrap break-words border border-border bg-muted p-4 font-mono text-xs leading-relaxed">
              {envelopeOut}
            </pre>
          </Panel>
          <Panel>
            <SectionLabel>Operational trace</SectionLabel>
            <div className="mt-4 space-y-1.5 text-xs text-muted-foreground">
              <div>Trace path: health → policy → metrics → chain</div>
              <div>Observability stack: FastAPI + REMORA metrics + audit verification</div>
              <div>
                Console API base: <span className="font-mono">{state.data?.api ?? "?"}</span>
              </div>
            </div>
          </Panel>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
          <Panel>
            <SectionLabel>Evidence archive</SectionLabel>
            <div className="mt-4 flex items-center gap-3">
              <Button
                variant="outline"
                className="rounded-none"
                onClick={() => void evidence.refetch()}
              >
                Refresh run history
              </Button>
              <span className="truncate font-mono text-[11px] text-muted-foreground">
                {evidence.data?.evidence_root ?? ""}
              </span>
            </div>
            <Table className="mt-3">
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Finished</TableHead>
                  <TableHead className="text-right">Cases</TableHead>
                  <TableHead>Chains</TableHead>
                  <TableHead className="text-right">Exit</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(evidence.data?.runs ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-xs text-muted-foreground">
                      no archived runs yet — run the battery once
                    </TableCell>
                  </TableRow>
                ) : (
                  (evidence.data?.runs ?? []).map((run) => (
                    <EvidenceRow
                      key={run.run_id}
                      run={run}
                      onManifest={(id) => void loadManifest(id)}
                    />
                  ))
                )}
              </TableBody>
            </Table>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Every battery run writes an immutable directory (manifest, results, metrics, chain
              verification, report) to the evidence volume. Retention keeps the newest runs and
              names every directory it prunes.
            </p>
          </Panel>
          <Panel>
            <SectionLabel>Run manifest</SectionLabel>
            <pre className="mt-4 max-h-[460px] overflow-auto whitespace-pre-wrap break-words border border-border bg-muted p-4 font-mono text-xs leading-relaxed">
              {manifestOut}
            </pre>
          </Panel>
        </div>
      </main>
    </div>
  );
}
