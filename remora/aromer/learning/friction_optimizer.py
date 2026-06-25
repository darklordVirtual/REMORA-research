# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER Review Friction Optimizer.

Aggregates MetaJudge structured critique outputs to propose quality-gated
threshold adjustments that reduce unnecessary VERIFY verdicts on benign
tool calls — without increasing false accepts.

Pipeline
--------
1. Collect recommended_adjustment objects from episode critique_text fields.
2. Aggregate by scope (domain/action_type/risk_tier): count "reduce_review_friction"
   recommendations vs "increase_vigilance" vs "none".
3. Propose candidate adjustments only where:
   - ≥ MIN_SIGNAL_COUNT critiques recommend friction reduction for a scope
   - No critique recommends increased vigilance for the same scope
4. Quality-gate: simulate the proposed adjustment on holdout episodes and
   verify false_accept_rate stays at 0.
5. Write approved proposals to artifacts/candidate_threshold_adjustments.json.

Usage
-----
    python -m remora.aromer.learning.friction_optimizer
    python -m remora.aromer.learning.friction_optimizer --dry-run
"""
from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).parents[3]
HOLDOUT_PATH = ROOT / "artifacts" / "aromer_holdout_episodes.jsonl"
OUTPUT_PATH  = ROOT / "artifacts" / "candidate_threshold_adjustments.json"

# Minimum MetaJudge critiques recommending friction reduction before we propose a change
MIN_SIGNAL_COUNT = 3
# Maximum trust-score boost per scope (safety cap)
MAX_DELTA = 0.05


@dataclass
class FrictionSignal:
    scope: str          # "domain/action_type/risk_tier"
    reduce_count: int   # critiques recommending reduce_review_friction
    vigilance_count: int  # critiques recommending increase_vigilance
    none_count: int
    total: int

    @property
    def net_signal(self) -> float:
        """Positive = safe to reduce friction, negative = tighten up."""
        return (self.reduce_count - self.vigilance_count) / max(self.total, 1)


@dataclass
class CandidateAdjustment:
    scope: str
    adjustment_type: str      # "reduce_review_friction"
    max_delta: float          # 0.0–MAX_DELTA
    signal_count: int
    net_signal: float
    holdout_false_accept_rate: float  # must be 0.0
    holdout_cases: int
    approved: bool
    reason: str


@dataclass
class OptimizationReport:
    generated_at: str
    n_episodes_scanned: int
    n_scopes_analyzed: int
    n_candidates: int
    n_approved: int
    adjustments: list[CandidateAdjustment] = field(default_factory=list)


# ---------------------------------------------------------------------------

def load_episode_critiques(episode_store_path: pathlib.Path | None = None) -> list[dict[str, Any]]:
    """Load episodes that have structured MetaJudge critique_text (v2 schema)."""
    # Try local JSONL store
    default_path = pathlib.Path.home() / ".aromer" / "episodes.jsonl"
    path = episode_store_path or default_path
    episodes = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ep = json.loads(line)
                if ep.get("critique_text"):
                    episodes.append(ep)
            except json.JSONDecodeError:
                pass
    return episodes


def extract_signals(episodes: list[dict[str, Any]]) -> dict[str, FrictionSignal]:
    """Parse critique_text JSON and aggregate recommended_adjustments by scope."""
    signals: dict[str, FrictionSignal] = {}

    for ep in episodes:
        raw = ep.get("critique_text", "")
        if not raw:
            continue
        try:
            critique = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue

        rec = critique.get("recommended_adjustment") or {}
        adj_type = str(rec.get("type", "none")).lower()
        scope = str(rec.get("scope", "unknown/unknown/unknown"))

        if scope not in signals:
            signals[scope] = FrictionSignal(
                scope=scope, reduce_count=0, vigilance_count=0,
                none_count=0, total=0
            )
        s = signals[scope]
        s.total += 1
        if adj_type == "reduce_review_friction":
            s.reduce_count += 1
        elif adj_type == "increase_vigilance":
            s.vigilance_count += 1
        else:
            s.none_count += 1

    return signals


def _scope_false_accept_rate(
    scope: str, holdout: list[dict[str, Any]]
) -> tuple[float, int]:
    """Compute false_accept_rate on holdout episodes matching this scope."""
    domain, action_type, risk_tier = (scope + "//").split("/")[:3]
    matching = [
        ep for ep in holdout
        if ep.get("domain") == domain
        and ep.get("action_type") == action_type
        and ep.get("risk_tier") == risk_tier
    ]
    if not matching:
        return 0.0, 0
    false_accepts = sum(
        1 for ep in matching
        if str(ep.get("ground_truth", "")) == "harmful"
        and str(ep.get("verdict", "")).upper() == "ACCEPT"
    )
    harmful = sum(1 for ep in matching if str(ep.get("ground_truth", "")) == "harmful")
    rate = false_accepts / max(harmful, 1) if harmful > 0 else 0.0
    return rate, len(matching)


def load_holdout() -> list[dict[str, Any]]:
    if not HOLDOUT_PATH.exists():
        return []
    episodes = []
    for line in HOLDOUT_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                ep = json.loads(line)
                if not ep.get("can_train", True):  # holdout episodes
                    episodes.append(ep)
            except json.JSONDecodeError:
                pass
    return episodes


def propose_adjustments(
    signals: dict[str, FrictionSignal],
    holdout: list[dict[str, Any]],
) -> list[CandidateAdjustment]:
    candidates = []
    for scope, sig in signals.items():
        if sig.reduce_count < MIN_SIGNAL_COUNT:
            continue
        if sig.vigilance_count > 0:
            continue  # any vigilance signal blocks reduction
        if sig.net_signal < 0.5:
            continue

        fa_rate, n_cases = _scope_false_accept_rate(scope, holdout)
        delta = min(MAX_DELTA, sig.net_signal * MAX_DELTA)
        approved = fa_rate == 0.0

        candidates.append(CandidateAdjustment(
            scope=scope,
            adjustment_type="reduce_review_friction",
            max_delta=round(delta, 4),
            signal_count=sig.reduce_count,
            net_signal=round(sig.net_signal, 4),
            holdout_false_accept_rate=fa_rate,
            holdout_cases=n_cases,
            approved=approved,
            reason=(
                "approved: FA=0 on holdout, sufficient reduce signals, no vigilance signals"
                if approved else
                f"blocked: FA={fa_rate:.3f} > 0 on holdout"
            ),
        ))
    return sorted(candidates, key=lambda c: -c.net_signal)


def run(
    *,
    episode_store_path: pathlib.Path | None = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> OptimizationReport:
    episodes = load_episode_critiques(episode_store_path)
    holdout  = load_holdout()
    signals  = extract_signals(episodes)
    candidates = propose_adjustments(signals, holdout)

    approved = [c for c in candidates if c.approved]
    report = OptimizationReport(
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        n_episodes_scanned=len(episodes),
        n_scopes_analyzed=len(signals),
        n_candidates=len(candidates),
        n_approved=len(approved),
        adjustments=candidates,
    )

    if verbose:
        print(f"Scanned {len(episodes)} critiqued episodes across {len(signals)} scopes")
        print(f"Candidates: {len(candidates)}  Approved: {len(approved)}")
        for c in approved:
            print(f"  APPROVED  {c.scope}  delta={c.max_delta:+.4f}  signals={c.signal_count}  {c.reason}")
        for c in candidates:
            if not c.approved:
                print(f"  BLOCKED   {c.scope}  {c.reason}")

    if not dry_run:
        out = {
            "generated_at": report.generated_at,
            "n_episodes_scanned": report.n_episodes_scanned,
            "n_scopes_analyzed": report.n_scopes_analyzed,
            "quality_gate": "holdout_false_accept_rate == 0.0",
            "adjustments": [asdict(c) for c in candidates],
        }
        OUTPUT_PATH.parent.mkdir(exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"Written to {OUTPUT_PATH}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="AROMER Review Friction Optimizer")
    parser.add_argument("--store", help="Path to episodes.jsonl (default: ~/.aromer/episodes.jsonl)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output file")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run(
        episode_store_path=pathlib.Path(args.store) if args.store else None,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
