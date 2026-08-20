# SPDX-License-Identifier: BUSL-1.1
"""The research shelf, and proof that its gate can actually fail.

A validator that passes everything is indistinguishable from no validator. The
mutation tests below each break one property the shelf promises and require the
checker to notice — the same discipline `tests/meta/` applies to the claim
gates.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from scripts.check_research_shelf import SHELF, _violations  # noqa: E402

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def shelf() -> dict:
    return yaml.safe_load(SHELF.read_text(encoding="utf-8"))


def _mutate(shelf: dict, component_id: str, **changes) -> dict:
    out = copy.deepcopy(shelf)
    for component in out["components"]:
        if component["id"] == component_id:
            component.update(changes)
    return out


# ── The shipped shelf must be sound ──────────────────────────────────────────


def test_shipped_shelf_has_no_violations(shelf: dict) -> None:
    assert _violations(shelf) == []


def test_every_adopted_entry_names_code_and_a_test_that_exist(shelf: dict) -> None:
    """The property that makes a pick trustworthy: the code is really there."""
    adopted = [
        c for c in shelf["components"] if c["adoption"] in {"ADOPTED", "PARTIAL"}
    ]
    assert adopted, "a shelf with nothing adopted is not exercising this rule"
    for component in adopted:
        evidence = component["remora_evidence"]
        for path in evidence:
            assert (ROOT / path).exists(), f"{component['id']}: missing {path}"
        assert any("test" in p for p in evidence), component["id"]


def test_no_entry_records_a_remora_measurement(shelf: dict) -> None:
    """Someone else's number must never be able to read as REMORA's."""
    for component in shelf["components"]:
        keys = set(component["source"])
        assert "remora_results" not in keys
        assert "our_results" not in keys
        # Every entry states whose numbers these are.
        assert component["source"]["reported_results"].strip()


def test_unverified_sources_are_never_adopted(shelf: dict) -> None:
    for component in shelf["components"]:
        if component["source"]["verification"] == "UNVERIFIED":
            assert component["adoption"] in {"UNEVALUATED", "DECLINED"}, (
                f"{component['id']} is adopted on an unretrieved source"
            )


# ── The gate must reject each failure mode ───────────────────────────────────


def test_gate_rejects_adopting_an_unverified_source(shelf: dict) -> None:
    broken = copy.deepcopy(shelf)
    for component in broken["components"]:
        if component["id"] == "SHELF-004":
            component["adoption"] = "ADOPTED"
            component["remora_evidence"] = ["remora/policy/decision_engine.py"]
    problems = _violations(broken)
    assert any("must stay UNEVALUATED" in p for p in problems)


def test_gate_rejects_evidence_that_does_not_exist(shelf: dict) -> None:
    broken = _mutate(
        shelf,
        "SHELF-002",
        remora_evidence=["remora/toolcall/routing/does_not_exist.py", "tests/x.py"],
    )
    problems = _violations(broken)
    assert any("does not exist" in p for p in problems)


def test_gate_rejects_adopted_without_a_test(shelf: dict) -> None:
    broken = _mutate(
        shelf, "SHELF-002", remora_evidence=["remora/toolcall/routing/effect_prediction.py"]
    )
    problems = _violations(broken)
    assert any("names no test" in p for p in problems)


def test_gate_rejects_a_remora_result_smuggled_into_a_source(shelf: dict) -> None:
    broken = copy.deepcopy(shelf)
    broken["components"][0]["source"]["remora_results"] = "97% accuracy"
    problems = _violations(broken)
    assert any("belong in the claim register" in p for p in problems)


def test_gate_rejects_an_internal_entry_citing_an_external_url(shelf: dict) -> None:
    """An internal finding must not borrow an external work's authority."""
    broken = copy.deepcopy(shelf)
    for component in broken["components"]:
        if component["source"]["verification"] == "INTERNAL":
            component["source"]["url"] = "https://arxiv.org/abs/2607.21835"
    problems = _violations(broken)
    assert any("must not cite a url" in p for p in problems)


def test_gate_rejects_verified_without_a_date(shelf: dict) -> None:
    broken = copy.deepcopy(shelf)
    for component in broken["components"]:
        if component["source"]["verification"] == "VERIFIED_RETRIEVED":
            component["source"].pop("verified", None)
            break
    problems = _violations(broken)
    assert any("requires a 'verified' date" in p for p in problems)


def test_gate_rejects_a_declined_entry_with_no_reason(shelf: dict) -> None:
    broken = _mutate(shelf, "SHELF-014", adoption="DECLINED")
    problems = _violations(broken)
    assert any("requires a decline_reason" in p for p in problems)


def test_gate_rejects_a_dangling_blocked_by(shelf: dict) -> None:
    broken = _mutate(shelf, "SHELF-003", blocked_by="SHELF-999")
    problems = _violations(broken)
    assert any("is not a shelf id" in p for p in problems)


def test_gate_rejects_a_duplicate_id(shelf: dict) -> None:
    broken = copy.deepcopy(shelf)
    broken["components"].append(copy.deepcopy(broken["components"][0]))
    problems = _violations(broken)
    assert any("duplicate id" in p for p in problems)


# ── Cross-reference integrity with the narrative roadmap ─────────────────────


def test_roadmap_refs_point_at_real_work_packages(shelf: dict) -> None:
    roadmap = (ROOT / "docs" / "13-research-frontier-roadmap.md").read_text(
        encoding="utf-8"
    )
    for component in shelf["components"]:
        ref = component.get("roadmap_ref")
        if ref:
            assert f"## {ref} " in roadmap, f"{component['id']}: unknown {ref}"
