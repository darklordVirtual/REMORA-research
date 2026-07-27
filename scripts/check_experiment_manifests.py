# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Experiment-manifest gate.

Validates ``experiments/*/experiment_manifest.yaml`` files: lightweight,
per-experiment metadata (hypothesis, lifecycle status, seeds, artifacts)
that makes exploratory work traceable WITHOUT production-grade ceremony.
Spec: docs/assurance/experiment_manifest_spec_v1.md.

Two tiers, mirroring check_document_governance.py:

  HARD (fail CI) — machine-readability of what exists:
    * A manifest that is unparseable YAML, misses a required key, uses an
      unknown lifecycle status, or reuses another manifest's experiment_id.

  ADVISORY (warn only) — coverage backlog, never a build breaker:
    * Experiment directories without a manifest.
    * Declared result_artifacts that do not exist (yet).
    * results/*.json files lacking a .provenance.json sidecar
      (see docs/assurance/artifact_provenance_spec_v1.md).

Exit codes: 0 = no HARD violations, 1 = HARD violations on stderr.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_KEYS = ("experiment_id", "title", "status", "hypothesis", "result_artifacts")
# Lifecycle statuses — deliberately orthogonal to the claim-evidence ladder in
# docs/assurance/evidence_levels.md: a manifest tracks where an EXPERIMENT is
# in its life, the claim register tracks how strong its RESULTS are.
ALLOWED_STATUSES = {
    "exploratory",      # hypothesis being formed; results are candidates only
    "preregistered",    # decision rule frozen before test data is seen
    "in_progress",      # runs underway
    "completed",        # runs done; artifacts final (positive OR negative)
    "superseded",       # replaced by a newer experiment (name it in notes)
    "abandoned",        # stopped; keep the manifest, results stay candidates
}


def _manifest_paths() -> list[Path]:
    exp_root = ROOT / "experiments"
    if not exp_root.is_dir():
        return []
    return sorted(exp_root.glob("*/experiment_manifest.yaml"))


def check_manifests(errors: list[str], warnings: list[str]) -> None:
    seen_ids: dict[str, str] = {}
    exp_root = ROOT / "experiments"

    if exp_root.is_dir():
        for d in sorted(p for p in exp_root.iterdir() if p.is_dir()):
            if d.name.startswith(("_", ".")):
                continue
            if not (d / "experiment_manifest.yaml").is_file():
                warnings.append(
                    f"experiment-manifest: experiments/{d.name}/ has no "
                    f"experiment_manifest.yaml (advisory backlog)"
                )

    for path in _manifest_paths():
        rel = path.relative_to(ROOT).as_posix()
        try:
            with open(path, encoding="utf-8") as f:
                m = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            errors.append(f"experiment-manifest: {rel}: unparseable YAML ({exc})")
            continue
        if not isinstance(m, dict):
            errors.append(f"experiment-manifest: {rel}: not a mapping")
            continue

        for key in REQUIRED_KEYS:
            if key not in m:
                errors.append(f"experiment-manifest: {rel}: missing required key {key!r}")

        status = m.get("status")
        if "status" in m and status not in ALLOWED_STATUSES:
            errors.append(
                f"experiment-manifest: {rel}: invalid status {status!r} "
                f"(allowed: {sorted(ALLOWED_STATUSES)})"
            )

        eid = m.get("experiment_id")
        if isinstance(eid, str) and eid:
            if eid in seen_ids:
                errors.append(
                    f"experiment-manifest: duplicate experiment_id {eid} in "
                    f"{seen_ids[eid]} and {rel}"
                )
            else:
                seen_ids[eid] = rel

        artifacts = m.get("result_artifacts")
        if isinstance(artifacts, list):
            for a in artifacts:
                if isinstance(a, str) and a and not (ROOT / a).exists():
                    warnings.append(
                        f"experiment-manifest: {rel}: declared artifact does "
                        f"not exist (yet): {a}"
                    )


def check_provenance_coverage(warnings: list[str]) -> None:
    """Advisory: results/*.json files without a .provenance.json sidecar."""
    results = ROOT / "results"
    if not results.is_dir():
        return
    missing = 0
    total = 0
    for p in sorted(results.rglob("*.json")):
        if p.name.endswith(".provenance.json"):
            continue
        total += 1
        if not p.with_name(p.name[: -len(".json")] + ".provenance.json").is_file():
            missing += 1
    if missing:
        warnings.append(
            f"experiment-manifest: {missing}/{total} results/*.json lack a "
            f".provenance.json sidecar (advisory backlog; spec: "
            f"docs/assurance/artifact_provenance_spec_v1.md)"
        )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    check_manifests(errors, warnings)
    check_provenance_coverage(warnings)

    for w in warnings:
        print(f"WARN: {w}")
    if warnings:
        print(f"experiment manifests: {len(warnings)} advisory warning(s)")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"experiment manifests: {len(errors)} hard violation(s)", file=sys.stderr)
        return 1
    print("experiment manifests: all hard checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
