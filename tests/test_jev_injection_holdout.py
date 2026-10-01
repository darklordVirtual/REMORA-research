# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The held-out runner, offline: seal check, corpus loading and scoring.

Uses a temporary corpus, never the sealed one, and deterministic providers.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from remora.decision_providers import DeterministicDecisionProvider

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("jev_holdout", ROOT / "experiments" / "jev_injection_holdout.py")
holdout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(holdout)


def _row(label: str, language: str = "en", pair: str = "P1", **kw) -> dict:
    row = {
        "pair_id": pair, "language": language, "label": label,
        "operator_request": "Disable port sw-1/0/3 per incident I-1.",
        "tool": "network.shutdown_port", "tool_description": "Disables one port.",
        "arguments": {"port": "sw-1/0/3"}, "untrusted_text": "Storm on sw-1/0/3.",
    }
    row.update(kw)
    return row


def _corpus(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "scenarios_t.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "SHA256SUMS").write_text(f"{digest}  scenarios_t.json\n", encoding="utf-8")
    return tmp_path


def test_a_changed_corpus_file_is_refused(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, [_row("legitimate")])
    (corpus / "scenarios_t.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match"):
        holdout.verify_seal(corpus)


def test_an_unsealed_corpus_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not sealed"):
        holdout.verify_seal(tmp_path)


def test_malformed_rows_are_excluded_and_listed(tmp_path: Path) -> None:
    rows = [_row("legitimate"), _row("bogus"), {"pair_id": "P2"}, _row("injection", language="de")]
    items, excluded = holdout.load_corpus(holdout.verify_seal(_corpus(tmp_path, rows)))
    assert [i["label"] for i in items] == ["legitimate"]
    assert len(excluded) == 3


def test_auroc() -> None:
    assert holdout.auroc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert holdout.auroc([0.1], [0.9]) == 0.0
    assert holdout.auroc([0.5], [0.5]) == 0.5
    assert holdout.auroc([], [0.1]) is None


def test_scoring_applies_the_preregistered_rules(tmp_path: Path) -> None:
    rows = [_row(label, language=lang) for label in holdout.LABELS for lang in ("en", "no")]
    items, _ = holdout.load_corpus(holdout.verify_seal(_corpus(tmp_path, rows)))
    base = {"intent_match": 0.95, "target_matches_request": 0.95, "scope_drift": 0.05,
            "action_reversibility": 0.2, "semantic_risk": 1.0}
    answers = {
        "v1": {**base, "possible_injection": 0.6},
        "v2": {**base, "injection_instruction": 0.7, "injection_authority_claim": 0.1,
               "injection_extra_action": 0.1},
        "v2.1": {**base, "injection_instruction": 0.1, "injection_authority_claim": 0.1,
                 "injection_override": 0.1, "injection_extra_action": 0.1},
    }

    def provider_for(name: str):
        return DeterministicDecisionProvider(answers[name], question_set_version=holdout.SETS[name][0])

    runs = holdout.ab.run_round(provider_for, items, 1, sets=holdout.SETS, injection_ids=holdout.INJECTION_IDS)
    scored = holdout.score(runs)
    assert scored["per_set"]["v2"]["all"]["benign_flag_rate"] == 1.0
    assert scored["per_set"]["v2.1"]["all"]["benign_flag_rate"] == 0.0
    assert scored["per_set"]["v2.1"]["all"]["injection_recall"] == 0.0
    assert scored["H1_v2_1_flags_fewer_benign_than_v2"] is True
    assert scored["G1_v2_1_recall_within_tolerance_of_v2"] is False
    assert scored["v2_1_passes"] is False
    assert scored["accept_reached"] == 0
