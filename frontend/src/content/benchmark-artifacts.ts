import benchmarkSnapshotRaw from "./benchmark-snapshot.json?raw";

type NullableNumber = number | null | undefined;

export type ClaimStatus = "holdout" | "simulator_only" | "in_sample" | "calibration" | "live_ci";

export interface MetricTile {
  label: string;
  value: string;
  detail: string;
  status: ClaimStatus;
  source: string;
}

export interface ToolcallStrategyRow {
  id: string;
  name: string;
  accuracy: number;
  unsafeExecutionRate: number;
  meanUtility: number;
  falseAcceptRate: number;
  falseBlockRate: number;
  criticalInterceptRate: number;
}

export interface SourceArtifact {
  label: string;
  path: string;
  scope: string;
  regenerate: string;
  test: string;
}

export interface PolicyActionRow {
  action: "ACCEPT" | "VERIFY" | "ABSTAIN" | "ESCALATE";
  count: number;
  share: number;
  accuracy: number | null;
  risk: number | null;
}

export interface ConformalRow {
  targetRisk: number;
  observedRisk: number;
  coverage: number;
  accepted: number;
  threshold: number;
  upperBoundMet: boolean;
}

export type BenchmarkArtifactMap = Record<string, unknown>;

interface ToolcallBaseline {
  accuracy: number;
  unsafe_execution_rate: number;
  mean_utility: number;
  false_accept_rate: number;
  false_block_rate: number;
  critical_error_intercept_rate: number;
}

interface ToolcallV2Results {
  benchmark: string;
  benchmark_artifact: string;
  n_tasks: number;
  baselines: Record<string, ToolcallBaseline>;
}

interface SelectiveN500HoldoutResults {
  meta: { script: string; data_source: string; random_seed: number };
  full_dataset: { n: number; baseline_accuracy: number };
  split: { n_train: number; n_holdout: number };
  holdout_evaluation: {
    tau_star: number;
    n_holdout: number;
    n_accepted: number;
    correct: number;
    accuracy_holdout: number;
    coverage_holdout: number;
    baseline_accuracy_holdout: number;
    lift_pp_holdout: number;
    wilson_ci_holdout: [number, number];
    p_one_sided_holdout: number;
  };
}

interface N500PolicyResults {
  n_items: number;
  accepted: number;
  verified: number;
  abstained: number;
  escalated: number;
  accuracy_by_action: Record<"accept" | "verify" | "abstain" | "escalate", number | null>;
  risk_by_action: Record<"accept" | "verify" | "abstain" | "escalate", number | null>;
  temperature_threshold: number;
  in_sample_calibration_warning: string;
}

interface ConformalReport {
  threshold: number;
  target_risk: number;
  holdout_risk: number;
  holdout_coverage: number;
  holdout_accepted: number;
  target_risk_met_by_upper_bound: boolean;
}

interface ConformalHoldoutResults {
  n: number;
  cal_fraction: number;
  seed: number;
  reports: Record<string, ConformalReport>;
}

interface BenchmarkSnapshot {
  artifact_paths: string[];
  generated_by: string;
  snapshot_hash: string;
  source_hashes: Record<string, string>;
  artifacts: BenchmarkArtifactMap;
}

export interface BenchmarkDashboard {
  artifactFingerprint: string;
  metricTiles: MetricTile[];
  toolcallRows: ToolcallStrategyRow[];
  policyRows: PolicyActionRow[];
  conformalRows: ConformalRow[];
  sourceArtifacts: SourceArtifact[];
  claimBoundaries: string[];
}

export const ARTIFACT_PATHS = {
  toolcallV2: "results/toolcall_benchmark_v2_results.json",
  n500Holdout: "results/selective_n500_holdout_results.json",
  n500Policy: "results/end_to_end_n500_v3.json",
  conformalHoldout: "results/conformal_guardrail_holdout.json",
} as const;

const snapshot = JSON.parse(benchmarkSnapshotRaw) as BenchmarkSnapshot;

export const BENCHMARK_SNAPSHOT_METADATA = {
  artifactPaths: snapshot.artifact_paths,
  generatedBy: snapshot.generated_by,
  snapshotHash: snapshot.snapshot_hash,
  sourceHashes: snapshot.source_hashes,
};

export const BENCHMARK_SNAPSHOT_ARTIFACTS = snapshot.artifacts;

const baselineOrder = [
  "single_model_heuristic",
  "majority_vote_heuristic",
  "self_consistency_heuristic",
  "verifier_heuristic",
  "remora_temperature_gate_heuristic",
  "remora_full_policy_gate",
] as const;

const baselineNames: Record<(typeof baselineOrder)[number], string> = {
  single_model_heuristic: "Single model heuristic",
  majority_vote_heuristic: "Majority vote heuristic",
  self_consistency_heuristic: "Self-consistency heuristic",
  verifier_heuristic: "Verifier heuristic",
  remora_temperature_gate_heuristic: "REMORA temperature gate",
  remora_full_policy_gate: "REMORA full policy gate",
};

export function formatPercent(value: NullableNumber, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatSignedPoints(value: NullableNumber, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)} pp`;
}

export function formatDecimal(value: NullableNumber, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

function fingerprint(input: string): string {
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function buildToolcallRows(toolcallV2: ToolcallV2Results): ToolcallStrategyRow[] {
  return baselineOrder.map((id) => {
    const row = toolcallV2.baselines[id];
    return {
      id,
      name: baselineNames[id],
      accuracy: row.accuracy,
      unsafeExecutionRate: row.unsafe_execution_rate,
      meanUtility: row.mean_utility,
      falseAcceptRate: row.false_accept_rate,
      falseBlockRate: row.false_block_rate,
      criticalInterceptRate: row.critical_error_intercept_rate,
    };
  });
}

function buildPolicyRows(n500Policy: N500PolicyResults): PolicyActionRow[] {
  const rows = [
    ["ACCEPT", n500Policy.accepted, "accept"],
    ["VERIFY", n500Policy.verified, "verify"],
    ["ABSTAIN", n500Policy.abstained, "abstain"],
    ["ESCALATE", n500Policy.escalated, "escalate"],
  ] as const;

  return rows.map(([action, count, key]) => ({
    action,
    count,
    share: n500Policy.n_items > 0 ? count / n500Policy.n_items : 0,
    accuracy: n500Policy.accuracy_by_action[key],
    risk: n500Policy.risk_by_action[key],
  }));
}

function buildConformalRows(conformalHoldout: ConformalHoldoutResults): ConformalRow[] {
  return ["0.100", "0.150"].map((key) => {
    const report = conformalHoldout.reports[key];
    return {
      targetRisk: report.target_risk,
      observedRisk: report.holdout_risk,
      coverage: report.holdout_coverage,
      accepted: report.holdout_accepted,
      threshold: report.threshold,
      upperBoundMet: report.target_risk_met_by_upper_bound,
    };
  });
}

export function buildBenchmarkDashboard(
  artifacts: BenchmarkArtifactMap = BENCHMARK_SNAPSHOT_ARTIFACTS,
  fingerprintSeed?: string,
): BenchmarkDashboard {
  const toolcallV2 = artifacts[ARTIFACT_PATHS.toolcallV2] as ToolcallV2Results;
  const n500Holdout = artifacts[ARTIFACT_PATHS.n500Holdout] as SelectiveN500HoldoutResults;
  const n500Policy = artifacts[ARTIFACT_PATHS.n500Policy] as N500PolicyResults;
  const conformalHoldout = artifacts[ARTIFACT_PATHS.conformalHoldout] as ConformalHoldoutResults;
  const remoraFull = toolcallV2.baselines.remora_full_policy_gate;
  const majority = toolcallV2.baselines.majority_vote_heuristic;
  const holdout = n500Holdout.holdout_evaluation;
  const acceptAccuracy = n500Policy.accuracy_by_action.accept;

  return {
    artifactFingerprint: fingerprintSeed
      ? fingerprintSeed.slice(0, 12)
      : fingerprint(
          [
            JSON.stringify(toolcallV2),
            JSON.stringify(n500Holdout),
            JSON.stringify(n500Policy),
            JSON.stringify(conformalHoldout),
          ].join("\n"),
        ),
    metricTiles: [
      {
        label: "Tool-call v2 unsafe rate",
        value: formatPercent(remoraFull.unsafe_execution_rate),
        detail: `${toolcallV2.n_tasks} deterministic dry-run tasks; majority baseline ${formatPercent(
          majority.unsafe_execution_rate,
        )}.`,
        status: "simulator_only",
        source: ARTIFACT_PATHS.toolcallV2,
      },
      {
        label: "Tool-call v2 utility",
        value: formatDecimal(remoraFull.mean_utility, 2),
        detail: `Accuracy ${formatPercent(remoraFull.accuracy)}; critical intercept ${formatPercent(
          remoraFull.critical_error_intercept_rate,
        )}.`,
        status: "simulator_only",
        source: ARTIFACT_PATHS.toolcallV2,
      },
      {
        label: "N500 held-out accuracy",
        value: formatPercent(holdout.accuracy_holdout),
        detail: `${holdout.correct}/${holdout.n_accepted} accepted at ${formatPercent(
          holdout.coverage_holdout,
        )} coverage; lift ${formatSignedPoints(holdout.lift_pp_holdout)}.`,
        status: "holdout",
        source: ARTIFACT_PATHS.n500Holdout,
      },
      {
        label: "N500 policy accept slice",
        value: formatPercent(acceptAccuracy),
        detail: `${n500Policy.accepted}/${n500Policy.n_items} accepted; threshold ${formatDecimal(
          n500Policy.temperature_threshold,
          4,
        )}. In-sample calibration warning applies.`,
        status: "in_sample",
        source: ARTIFACT_PATHS.n500Policy,
      },
    ],
    toolcallRows: buildToolcallRows(toolcallV2),
    policyRows: buildPolicyRows(n500Policy),
    conformalRows: buildConformalRows(conformalHoldout),
    sourceArtifacts: [
      {
        label: "Tool-call v2 safety",
        path: ARTIFACT_PATHS.toolcallV2,
        scope: "Deterministic simulator; no live destructive execution.",
        regenerate: "python experiments/evaluate_toolcall_benchmark_v2.py",
        test: "python -m pytest tests/test_toolcall_v2_results.py -q",
      },
      {
        label: "N500 held-out selective trust",
        path: ARTIFACT_PATHS.n500Holdout,
        scope: "Held-out split with tau* locked from training.",
        regenerate: "python scripts/selective_n500_holdout.py",
        test: "python -m pytest tests/test_selective_n500.py -q",
      },
      {
        label: "N500 policy layer",
        path: ARTIFACT_PATHS.n500Policy,
        scope: "In-sample policy artifact; warning must remain visible.",
        regenerate: "python experiments/end_to_end_n500_v3.py",
        test: "python -m pytest tests/test_end_to_end_n500_v3.py -q",
      },
      {
        label: "Conformal guardrail holdout",
        path: ARTIFACT_PATHS.conformalHoldout,
        scope: "N302 split-conformal holdout; exchangeability caveat applies.",
        regenerate: "python experiments/conformal_phase_guardrail.py",
        test: "python -m pytest tests/test_conformal.py -q",
      },
    ],
    claimBoundaries: [
      "Dashboard metrics are derived from a generated frontend snapshot of committed JSON artifacts, not hand-entered README values.",
      "Tool-call safety numbers are simulator-scoped and are not deployment certification.",
      "The live CI panel reports workflow status; it does not create new benchmark measurements.",
      "For Cloudflare deployment, rerun benchmark scripts and rebuild the frontend after artifact changes.",
    ],
  };
}

export const BENCHMARK_DASHBOARD = buildBenchmarkDashboard(
  BENCHMARK_SNAPSHOT_ARTIFACTS,
  BENCHMARK_SNAPSHOT_METADATA.snapshotHash,
);
