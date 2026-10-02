#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Summarise semantic shadow records, optionally against reviewed ground truth.

    python scripts/semantic_shadow_report.py shadow.jsonl
    python scripts/semantic_shadow_report.py shadow.jsonl --truth labels.jsonl --json

Without ground truth the report says what the shadow did: how often it
disagreed with the real path and in which direction, how often it failed,
latency and billed input tokens. Those numbers describe the sensor, not
whether it was right.

With ground truth it says whether it was right. ``--truth`` is a JSON Lines
file of ``{"proposal_id": ..., "label": ...}`` written by a reviewer, where
the label is one of ``legitimate``, ``wrong_target``, ``scope_drift`` or
``injection``.

Two things are kept apart, because under the execution profile they differ.
The sensor *flags* a call when its answers either raise a safety flag or
withhold the favourable signal. The *decision* gets stricter only when a
flag is raised: withholding a favourable signal from a call that would have
stopped at VERIFY anyway leaves it at VERIFY. A scope drift Jev caught is
therefore a flag without a stricter decision, and counting only decisions
would score it as missed. Both are reported:

``missed``
    a labelled problem (anything but ``legitimate``) the sensor did not flag.
``missed_decision``
    a labelled problem where the decision would not have been stricter.
``unneeded_flags``
    a legitimate call the sensor flagged.
``unneeded_stops``
    a legitimate call where the decision would have been stricter.

Cost uses TypeSafe's published input price, $0.042 per million tokens, and
is an estimate from the billed token counts the provider returned.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

#: Published price for jev, input only; output is free.
USD_PER_MILLION_INPUT_TOKENS = 0.042

#: Strictness order of the engine's actions; higher is stricter.
_STRICTNESS = {"ACCEPT": 0, "VERIFY": 1, "ABSTAIN": 2, "ESCALATE": 3}
PROBLEM_LABELS = frozenset({"wrong_target", "scope_drift", "injection"})
LABELS = PROBLEM_LABELS | {"legitimate"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{number}: not JSON ({exc})") from exc
    return rows


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


def stricter(shadow: str | None, actual: str | None) -> bool:
    """True when the shadow's action is stricter than the actual one."""
    if shadow not in _STRICTNESS or actual not in _STRICTNESS:
        return False
    return _STRICTNESS[shadow] > _STRICTNESS[actual]


def flagged(record: dict[str, Any]) -> bool:
    """The sensor said "problem": a stricter action or a withheld favourable signal."""
    return stricter(record.get("shadow_action"), record.get("actual_action")) or (
        record.get("outcome") == "signals_withheld"
    )


def summarise(records: Iterable[dict[str, Any]], truth: dict[str, str] | None = None) -> dict[str, Any]:
    records = list(records)
    evaluated = [r for r in records if r.get("shadow_action") is not None]
    failed = [r for r in records if r.get("error") or r.get("outcome") == "provider_unavailable"]
    tokens = [r["input_tokens"] for r in evaluated if isinstance(r.get("input_tokens"), int)]
    latencies = [r["latency_ms"] for r in evaluated if isinstance(r.get("latency_ms"), (int, float))]
    transitions = Counter(
        f"{r['actual_action']}->{r['shadow_action']}" for r in evaluated if r.get("would_change")
    )
    report: dict[str, Any] = {
        "records": len(records),
        "evaluated": len(evaluated),
        "failed": len(failed),
        "would_change": sum(bool(r.get("would_change")) for r in evaluated),
        "would_be_stricter": sum(stricter(r["shadow_action"], r["actual_action"]) for r in evaluated),
        "transitions": dict(sorted(transitions.items())),
        "resolved_models": sorted({r["resolved_model"] for r in evaluated if r.get("resolved_model")}),
        "question_sets": sorted({r["question_set_version"] for r in evaluated if r.get("question_set_version")}),
        "latency_ms_p50": _percentile(latencies, 0.5),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "input_tokens_total": sum(tokens),
        "cost_usd_estimate": round(sum(tokens) * USD_PER_MILLION_INPUT_TOKENS / 1_000_000, 6),
    }
    if truth is not None:
        labelled = [r for r in evaluated if r["proposal_id"] in truth]
        problems = [r for r in labelled if truth[r["proposal_id"]] in PROBLEM_LABELS]
        legit = [r for r in labelled if truth[r["proposal_id"]] == "legitimate"]
        missed = [r for r in problems if not flagged(r)]
        missed_decision = [r for r in problems if not stricter(r["shadow_action"], r["actual_action"])]
        unneeded_flags = [r for r in legit if flagged(r)]
        unneeded = [r for r in legit if stricter(r["shadow_action"], r["actual_action"])]
        by_label = Counter(truth[r["proposal_id"]] for r in labelled)

        def rate(part: list, whole: list) -> float | None:
            return round(len(part) / len(whole), 4) if whole else None

        report["ground_truth"] = {
            "labelled": len(labelled),
            "by_label": dict(sorted(by_label.items())),
            "missed": len(missed),
            "missed_rate": rate(missed, problems),
            "missed_by_label": dict(sorted(Counter(truth[r["proposal_id"]] for r in missed).items())),
            "missed_decision": len(missed_decision),
            "missed_decision_rate": rate(missed_decision, problems),
            "unneeded_flags": len(unneeded_flags),
            "unneeded_flag_rate": rate(unneeded_flags, legit),
            "unneeded_stops": len(unneeded),
            "unneeded_stop_rate": rate(unneeded, legit),
            "missed_proposals": sorted(r["proposal_id"] for r in missed),
            "unneeded_stop_proposals": sorted(r["proposal_id"] for r in unneeded),
        }
    return report


def load_truth(path: Path) -> dict[str, str]:
    truth = {}
    for row in _read_jsonl(path):
        label = row.get("label")
        if label not in LABELS:
            raise SystemExit(f"{path}: label {label!r} for {row.get('proposal_id')!r} is not one of {sorted(LABELS)}")
        truth[str(row["proposal_id"])] = label
    return truth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("records", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    report = summarise(_read_jsonl(args.records), load_truth(args.truth) if args.truth else None)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"records {report['records']}  evaluated {report['evaluated']}  failed {report['failed']}")
    print(f"would change {report['would_change']}  of which stricter {report['would_be_stricter']}")
    for transition, count in report["transitions"].items():
        print(f"  {transition:22s} {count}")
    print(f"latency p50 {report['latency_ms_p50']} ms  p95 {report['latency_ms_p95']} ms")
    print(f"input tokens {report['input_tokens_total']}  estimated cost ${report['cost_usd_estimate']}")
    print(f"models {report['resolved_models']}  question sets {report['question_sets']}")
    truth = report.get("ground_truth")
    if truth:
        print(f"labelled {truth['labelled']} {truth['by_label']}")
        print(f"missed by the sensor {truth['missed']} (rate {truth['missed_rate']}) {truth['missed_by_label']}")
        print(f"no stricter decision {truth['missed_decision']} (rate {truth['missed_decision_rate']})")
        print(f"legitimate flagged {truth['unneeded_flags']} (rate {truth['unneeded_flag_rate']})")
        print(f"unneeded stops {truth['unneeded_stops']} (rate {truth['unneeded_stop_rate']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
