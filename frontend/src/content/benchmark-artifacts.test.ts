import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import benchmarkSnapshotRaw from "./benchmark-snapshot.json?raw";
import { ARTIFACT_PATHS, BENCHMARK_DASHBOARD, formatPercent } from "./benchmark-artifacts";

describe("benchmark artifact dashboard", () => {
  const snapshot = JSON.parse(benchmarkSnapshotRaw);
  const toolcall = snapshot.artifacts[ARTIFACT_PATHS.toolcallV2];
  const holdout = snapshot.artifacts[ARTIFACT_PATHS.n500Holdout];
  const policy = snapshot.artifacts[ARTIFACT_PATHS.n500Policy];

  it("keeps the frontend snapshot in sync with root benchmark artifacts", () => {
    for (const path of Object.values(ARTIFACT_PATHS)) {
      const rootArtifact = JSON.parse(readFileSync(resolve("..", path), "utf-8"));
      expect(snapshot.artifacts[path]).toEqual(rootArtifact);
    }
  });

  it("derives tool-call rows from the committed v2 artifact", () => {
    const row = BENCHMARK_DASHBOARD.toolcallRows.find(
      (item) => item.id === "remora_full_policy_gate",
    );
    const artifact = toolcall.baselines.remora_full_policy_gate;

    expect(row).toBeTruthy();
    expect(row?.unsafeExecutionRate).toBe(artifact.unsafe_execution_rate);
    expect(row?.accuracy).toBe(artifact.accuracy);
    expect(row?.meanUtility).toBe(artifact.mean_utility);
  });

  it("derives the N500 holdout headline from the holdout artifact", () => {
    const tile = BENCHMARK_DASHBOARD.metricTiles.find(
      (item) => item.label === "N500 held-out accuracy",
    );
    const artifact = holdout.holdout_evaluation;

    expect(tile?.value).toBe(formatPercent(artifact.accuracy_holdout));
    expect(tile?.detail).toContain(`${artifact.correct}/${artifact.n_accepted}`);
    expect(tile?.source).toBe(ARTIFACT_PATHS.n500Holdout);
  });

  it("derives policy distribution from the N500 policy artifact", () => {
    const accept = BENCHMARK_DASHBOARD.policyRows.find((row) => row.action === "ACCEPT");

    expect(accept?.count).toBe(policy.accepted);
    expect(accept?.accuracy).toBe(policy.accuracy_by_action.accept);
    expect(accept?.share).toBe(policy.accepted / policy.n_items);
  });

  it("keeps benchmark caveats visible", () => {
    expect(BENCHMARK_DASHBOARD.claimBoundaries.join(" ")).toContain("simulator-scoped");
    expect(BENCHMARK_DASHBOARD.claimBoundaries.join(" ")).toContain("committed JSON");
    expect(BENCHMARK_DASHBOARD.sourceArtifacts.map((item) => item.path)).toContain(
      ARTIFACT_PATHS.toolcallV2,
    );
  });
});
