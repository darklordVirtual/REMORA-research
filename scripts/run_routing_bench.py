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

#: (name, description, counterfactual, observation mutator, engine factory)
Arm = tuple[
    str, str, bool,
    Callable[[PolicyObservation], PolicyObservation],
    Callable[[], RemoraDecisionEngine],
]

_DEFAULT_ENGINE: Callable[[], RemoraDecisionEngine] = RemoraDecisionEngine

ARMS: list[Arm] = [
    (
        "A_observable_only",
        "Task text, tool name and arguments only — what an integrator has "
        "before running any oracle.",
        False,
        lambda o: o,
        _DEFAULT_ENGINE,
    ),
    (
        "B_plus_schema_valid",
        "Adds schema_valid=True. Genuinely checkable without an oracle: the "
        "dataset's calls are well-formed.",
        False,
        lambda o: replace(o, schema_valid=True),
        _DEFAULT_ENGINE,
    ),
    (
        "C_plus_low_risk_tier",
        "Adds risk_tier=low. Counterfactual: a deployment would classify risk "
        "per call, not declare everything low.",
        True,
        lambda o: replace(o, schema_valid=True, risk_tier="low"),
        _DEFAULT_ENGINE,
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
        _DEFAULT_ENGINE,
    ),
    (
        "E_high_trust_critical_risk",
        "As D but risk_tier=critical. Isolates a confound in D: the "
        "tainted-argument escalation path is tier-dependent (v4, issue #40) and "
        "declaring everything low-risk suppresses it. Counterfactual in the "
        "same way as D.",
        True,
        lambda o: replace(
            o,
            schema_valid=True,
            risk_tier="critical",
            phase="ordered",
            trust_score=0.9,
            evidence_contradictions=0,
            counterfactual_passed=True,
        ),
        _DEFAULT_ENGINE,
    ),
    (
        "F_low_consequence_accept",
        "Arm A plus the opt-in low-consequence ACCEPT path "
        "(RemoraDecisionEngine(low_consequence_accept=True)). Not "
        "counterfactual: it injects no metadata, only enables a policy option a "
        "deployment can actually set.",
        False,
        lambda o: o,
        lambda: RemoraDecisionEngine(low_consequence_accept=True),
    ),
]


#: Non-redistributable episodes (ToolSandbox) live only here. Included when
#: present so a local run covers the ABSTAIN axis; absent in CI, where the
#: artifact records the reduced coverage rather than hiding it.
LOCAL = REPO_ROOT / ".cache" / "routing_bench" / "local"


def _read_jsonl(path: Path) -> list[RoutingEpisode]:
    return [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_episodes() -> tuple[list[RoutingEpisode], list[str]]:
    """Return all available episodes and the names of any local-only sources."""
    episodes: list[RoutingEpisode] = []
    for path in sorted(DATA.glob("*.jsonl")):
        episodes.extend(_read_jsonl(path))

    local_sources: list[str] = []
    if LOCAL.exists():
        for path in sorted(LOCAL.glob("*.jsonl")):
            local = _read_jsonl(path)
            if local:
                episodes.extend(local)
                local_sources.append(local[0].source_dataset)
    return episodes, local_sources


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

    episodes, local_sources = load_episodes()
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    arms: dict[str, Any] = {}
    for name, description, counterfactual, mutate, make_engine in ARMS:
        engine = make_engine()
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
        "local_only_sources_included": local_sources,
        "per_source_episode_counts": {
            name: sum(1 for e in episodes if e.source_dataset == name)
            for name in sorted({e.source_dataset for e in episodes})
        },
        "label_distribution": {
            r: sum(1 for e in episodes if (e.route.value if e.route else "null") == r)
            for r in ("accept", "verify", "abstain", "escalate", "null")
        },
        "arms": arms,
        "caveats": [
            "Routes with zero labelled episodes are reported as unmeasured, "
            "never as a zero rate.",
            "ToolSandbox is not redistributable (Apple's own license, not OSI). "
            "Its episodes are built locally and never committed, so a CI run "
            "has no ABSTAIN support while a local run does. The "
            "local_only_sources_included field records which applied.",
            "Confidence intervals are cluster-adjusted over cluster_id: many "
            "episodes derive from one upstream task and are not independent draws.",
            "Arms C and D are counterfactual metadata injections, not deployment "
            "measurements.",
            "The benchmark scores the routing decision over a single proposed "
            "call. tau2 tasks are multi-turn conversations; no agent is run.",
            "Arm F buys ACCEPT recall with two measured costs, both real: it "
            "accepts 101 of 227 known-wrong calls (all read-only), and it takes "
            "ABSTAIN recall from 62.5% to 0% because ToolSandbox's unanswerable "
            "tasks propose reads that its minefields mark as disclosing. The "
            "path asserts bounded consequence, and those 10 cases are where "
            "that assertion is false. Distinguishing them needs a disclosure or "
            "blast-radius signal the observation does not carry.",
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
