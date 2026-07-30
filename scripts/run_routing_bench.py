# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evaluate the REMORA policy engine against the routing benchmark.

Reads the committed episodes in ``data/routing_bench_v1/`` — no network, no
source cache needed — and writes ``results/routing_bench_v1_results.json``.

Runs a metadata ablation rather than a single number. The benchmark supplies
only what an integrator observes before execution (task text, tool name,
arguments). Everything beyond that must be *supplied* by the deployment, so the
ablation measures how much of the routing outcome is determined by the proposed
action versus by the surrounding metadata block.

Arms C and D are counterfactual: they inject uniform trust and phase values
that no real oracle run would produce. They answer "what does the engine do at
fixed high trust", not "what would REMORA score in deployment". They are
labelled ``counterfactual: true`` in the artifact.

Exit code 0 always; a bad result is a finding, not a crash.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.policy.observation import PolicyObservation  # noqa: E402
from remora.toolcall.routing.episode import RoutingEpisode  # noqa: E402
from remora.toolcall.routing.evaluate import (  # noqa: E402
    _ACTION_TO_ROUTE,
    build_observation,
    score_routing,
)

DATA = REPO_ROOT / "data" / "routing_bench_v1"
OUT = REPO_ROOT / "results" / "routing_bench_v1_results.json"

Arm = tuple[str, str, bool, Callable[[PolicyObservation], PolicyObservation]]

ARMS: list[Arm] = [
    (
        "A_observable_only",
        "Task text, tool name and arguments only — what an integrator has "
        "before running any oracle.",
        False,
        lambda o: o,
    ),
    (
        "B_plus_schema_valid",
        "Adds schema_valid=True. Genuinely checkable without an oracle: the "
        "dataset's calls are well-formed.",
        False,
        lambda o: replace(o, schema_valid=True),
    ),
    (
        "C_plus_low_risk_tier",
        "Adds risk_tier=low. Counterfactual: a deployment would classify risk "
        "per call, not declare everything low.",
        True,
        lambda o: replace(o, schema_valid=True, risk_tier="low"),
    ),
    (
        "D_plus_uniform_high_trust",
        "Adds phase=ordered, trust_score=0.9, no contradictions, counterfactual "
        "passed. Counterfactual: simulates an oracle ensemble agreeing uniformly "
        "on every episode.",
        True,
        lambda o: replace(
            o,
            schema_valid=True,
            risk_tier="low",
            phase="ordered",
            trust_score=0.9,
            evidence_contradictions=0,
            counterfactual_passed=True,
        ),
    ),
]


def load_episodes() -> list[RoutingEpisode]:
    episodes: list[RoutingEpisode] = []
    for path in sorted(DATA.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                episodes.append(RoutingEpisode.from_json_dict(json.loads(line)))
    return episodes


def main() -> None:
    if not DATA.exists():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(
                {
                    "schema": "routing_bench_v1_results",
                    "status": "skipped",
                    "reason": f"{DATA} missing; run scripts/build_routing_bench.py",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"status:skipped — {DATA} missing")
        return

    episodes = load_episodes()
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    engine = RemoraDecisionEngine()

    arms: dict[str, Any] = {}
    for name, description, counterfactual, mutate in ARMS:
        results = [
            (ep, _ACTION_TO_ROUTE[engine.decide(mutate(build_observation(ep))).action])
            for ep in episodes
        ]
        scored = score_routing(results)
        scored["description"] = description
        scored["counterfactual"] = counterfactual
        arms[name] = scored

        accept = scored["per_route"]["accept"]
        print(
            f"{name:<28} accuracy={scored['routing_accuracy']:>6.1%}  "
            f"ACCEPT-recall="
            f"{accept.get('recall', float('nan')):>6.1%}  "
            f"wrong-call-accept={scored['safety_axis']['wrong_call_accept_rate']:>6.1%}"
            + ("  [counterfactual]" if counterfactual else "")
        )

    report = {
        "schema": "routing_bench_v1_results",
        "status": "measured",
        "n_episodes": len(episodes),
        "n_clusters": len({e.cluster_id for e in episodes}),
        "route_table_version": manifest["route_table_version"],
        "route_table_content_hash": manifest["route_table_content_hash"],
        "sources": manifest["sources"],
        "label_distribution": {
            r: sum(1 for e in episodes if (e.route.value if e.route else "null") == r)
            for r in ("accept", "verify", "abstain", "escalate", "null")
        },
        "arms": arms,
        "caveats": [
            "Routes with zero labelled episodes are reported as unmeasured, never "
            "as a zero rate. ABSTAIN has no support in this source and ESCALATE "
            "has 2 episodes; neither supports a claim.",
            "Confidence intervals are cluster-adjusted over cluster_id: many "
            "episodes derive from one upstream task and are not independent draws.",
            "Arms C and D are counterfactual metadata injections, not deployment "
            "measurements.",
            "The benchmark scores the routing decision over a single proposed "
            "call. tau2 tasks are multi-turn conversations; no agent is run.",
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
