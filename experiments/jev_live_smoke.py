#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Live smoke round: the demo's scenarios put to Jev on TypeSafe's API.

Runs each scenario of ``examples/jev_decision_provider_demo.py`` against the
live model ``repeats`` times and records, per run, the resolved model, every
answer with its probabilities and legend, the admission notes, and the
engine's decision with and without the provider. Repeats exist to show
whether the same state gets the same answers; they are not a sample size.

    set -a; . ./.env; set +a          # JEV_API_KEY
    python experiments/jev_live_smoke.py --repeats 3

Writes ``results/jev_live_smoke_v1.json`` and its provenance sidecar.

Scope (declared, not exhaustive): three hand-written English scenarios under
the demo's illustrative thresholds. This is evidence that the integration
works end to end against the live service and of what the model answered on
these three states. It is not a calibration study, it says nothing about
accuracy on any corpus, and the thresholds in it are not recommendations.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "jev_decision_provider_demo.py"
RESULT = REPO_ROOT / "results" / "jev_live_smoke_v1.json"

sys.path.insert(0, str(REPO_ROOT))

from remora.decision_providers.enrich import enrich, semantic_state  # noqa: E402
from remora.decision_providers.questions import (  # noqa: E402
    QUESTION_SET_VERSION,
    REMORA_QUESTIONS_V1,
)
from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine  # noqa: E402
from remora.policy.observation import PolicyObservation  # noqa: E402


def _load_example():
    spec = importlib.util.spec_from_file_location("jev_demo", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _thresholds_record(thresholds) -> dict[str, float]:
    return {
        name: getattr(thresholds, name)
        for name in ("intent_match", "target_matches_request", "possible_injection", "scope_drift")
    }


def run_round(provider_for, scenarios: dict, thresholds, repeats: int) -> dict[str, Any]:
    """Run every scenario ``repeats`` times; ``provider_for(scenario)`` builds the provider."""
    engine = RemoraDecisionEngine(execution_profile=True)
    runs: list[dict[str, Any]] = []
    for name in sorted(scenarios):
        scenario = scenarios[name]
        state = semantic_state(
            intent=scenario["intent"],
            tool_name="access.change_customer_vlan",
            arguments=scenario["arguments"],
        )
        observation = PolicyObservation(
            question=scenario["intent"],
            risk_tier="high",
            action_type="configuration_change",
            target_environment="prod",
        )
        baseline = engine.decide(observation)
        for repeat in range(repeats):
            result = enrich(
                observation,
                provider_for(scenario),
                state=state,
                thresholds=thresholds,
                questions=REMORA_QUESTIONS_V1,
            )
            decision = engine.decide(result.observation)
            evidence = result.evidence
            runs.append(
                {
                    "scenario": name,
                    "repeat": repeat,
                    "outcome": result.outcome,
                    "notes": list(result.notes),
                    "resolved_model": evidence.resolved_model if evidence else None,
                    "state_hash": evidence.state_hash if evidence else None,
                    "response_hash": evidence.response_hash if evidence else None,
                    "latency_ms": round(evidence.latency_ms, 1) if evidence else None,
                    "answers": {
                        a.question_id: {
                            "value": a.value,
                            "probabilities": a.probabilities,
                            "confidence": a.confidence,
                            "legend": list(a.legend) if a.legend else None,
                        }
                        for a in (evidence.answers if evidence else ())
                    },
                    "decision_without_provider": baseline.action.name,
                    "decision_with_provider": decision.action.name,
                    "reasons": [r.name for r in decision.reasons],
                    "accept_reached": decision.action is DecisionAction.ACCEPT,
                }
            )

    by_scenario: dict[str, dict[str, Any]] = {}
    for name in sorted(scenarios):
        mine = [r for r in runs if r["scenario"] == name]
        by_scenario[name] = {
            "runs": len(mine),
            "distinct_response_hashes": len({r["response_hash"] for r in mine}),
            "decisions_with_provider": sorted({r["decision_with_provider"] for r in mine}),
            "outcomes": sorted({r["outcome"] for r in mine}),
        }
    return {
        "question_set_version": QUESTION_SET_VERSION,
        "thresholds": _thresholds_record(thresholds),
        "thresholds_status": "illustrative, from the demo; not calibrated",
        "repeats": repeats,
        "summary": {
            "runs": len(runs),
            "accept_reached": sum(r["accept_reached"] for r in runs),
            "provider_unavailable": sum(r["outcome"] == "provider_unavailable" for r in runs),
            "resolved_models": sorted({r["resolved_model"] for r in runs if r["resolved_model"]}),
            "by_scenario": by_scenario,
        },
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=RESULT)
    args = parser.parse_args(argv)

    if not (os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")):
        sys.exit("needs JEV_API_KEY (or TYPESAFE_API_KEY); this round is live by definition")

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from result_provenance import capture_pre_run_state, write_sidecar

    from remora.decision_providers.typesafe import TypeSafeJevProvider

    pre = capture_pre_run_state()
    demo = _load_example()
    provider = TypeSafeJevProvider(question_set_version=QUESTION_SET_VERSION)
    result = {
        "schema": "jev_live_smoke_v1",
        "provider": provider.provider_name,
        "model_alias": "jev-latest",
        "endpoint": "https://api.typesafe.ai/v1/systemone",
        "scope": (
            "three hand-written English scenarios from examples/jev_decision_provider_demo.py "
            "under illustrative thresholds; integration evidence, not a calibration study"
        ),
        **run_round(lambda _s: provider, demo.SCENARIOS, demo.THRESHOLDS, args.repeats),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    out_rel = args.out.resolve().relative_to(REPO_ROOT).as_posix()
    sidecar_rel = out_rel.rsplit(".", 1)[0] + ".provenance.json"
    write_sidecar(
        args.out,
        script="experiments/jev_live_smoke.py",
        inputs={"scenarios": EXAMPLE},
        command=f"python experiments/jev_live_smoke.py --repeats {args.repeats}",
        extra={"n_samples": result["summary"]["runs"]},
        pre_run_worktree_clean=pre["pre_run_worktree_clean"],
        allowed_generated_outputs=[out_rel, sidecar_rel],
    )

    summary = result["summary"]
    print(f"runs={summary['runs']} models={summary['resolved_models']} "
          f"unavailable={summary['provider_unavailable']} accept_reached={summary['accept_reached']}")
    for name, row in summary["by_scenario"].items():
        print(f"  {name:14s} decisions={row['decisions_with_provider']} "
              f"distinct_responses={row['distinct_response_hashes']}/{row['runs']}")
    print(f"artifact: {out_rel}")
    return 1 if summary["accept_reached"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
