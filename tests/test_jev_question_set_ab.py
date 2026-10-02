# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The V1/V2 A/B generator, run offline with deterministic providers.

Pins the scenario grid, that both sets see the same content, and the summary
arithmetic, without a call to TypeSafe.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from remora.decision_providers import DeterministicDecisionProvider

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("jev_ab", ROOT / "experiments" / "jev_question_set_ab.py")
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)

V1 = {"intent_match": 0.9, "target_matches_request": 0.9, "possible_injection": 0.6,
      "scope_drift": 0.1, "action_reversibility": 1.0, "semantic_risk": 1.0}
V2 = {"intent_match": 0.9, "target_matches_request": 0.9, "scope_drift": 0.1,
      "injection_instruction": 0.1, "injection_authority_claim": 0.2, "injection_extra_action": 0.3,
      "action_reversibility": 0.2, "semantic_risk": 1.0}


def _providers(name: str):
    version, _ = ab.SETS[name]
    return DeterministicDecisionProvider(V1 if name == "v1" else V2, question_set_version=version)


def test_the_grid_is_four_tasks_by_four_labels_by_two_languages() -> None:
    items = ab.scenarios()
    assert len(items) == 32
    assert len({i["id"] for i in items}) == 32
    assert {i["language"] for i in items} == {"en", "no"}


def test_variants_differ_from_the_legitimate_call_in_one_place() -> None:
    by_id = {i["id"]: i for i in ab.scenarios()}
    legit = by_id["vlan.en.legitimate"]
    assert by_id["vlan.en.wrong_target"]["arguments"]["customer_id"] != legit["arguments"]["customer_id"]
    assert set(by_id["vlan.en.scope_drift"]["arguments"]) > set(legit["arguments"])
    assert by_id["vlan.en.injection"]["arguments"] == legit["arguments"]
    assert by_id["vlan.en.injection"]["untrusted"] != legit["untrusted"]


def test_both_sets_see_the_same_content() -> None:
    item = ab.scenarios()[0]
    v1, v2 = ab.state_for("v1", item), ab.state_for("v2", item)
    assert v1["intent"] == v2["operator_request"]
    assert v1["arguments"] == v2["proposed_call"]["arguments"]
    assert v1["context"]["ticket_text"] == v2["untrusted_content"]["ticket_text"]


def test_the_summary_counts_admissions_per_cell() -> None:
    runs = ab.run_round(_providers, ab.scenarios(), repeats=2)
    summary = ab.summarise(runs)
    assert summary["runs"] == 32 * 2 * 2
    assert summary["accept_reached"] == 0
    v1 = summary["cells"]["v1.en.legitimate"]
    v2 = summary["cells"]["v2.en.legitimate"]
    assert v1["adversarial_raised_rate"] == 1.0  # 0.6 >= 0.5
    assert v2["adversarial_raised_rate"] == 0.0  # max(0.1, 0.2, 0.3) < 0.5
    assert v2["injection"] == 0.3
    assert v2["favourable_admitted_rate"] == 1.0
    assert summary["max_repeat_spread_probability"] == {"v1": 0.0, "v2": 0.0}
