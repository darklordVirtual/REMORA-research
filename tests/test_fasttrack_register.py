"""Machine enforcement of the fasttrack register's delivery contract.

The register (docs/assurance/fasttrack_register_v1.yaml) is the source of
truth for what the fasttrack program has delivered. Until 2026-08-05 it was
prose-checked only; the maintainer's review that day required the
definition-of-done to be "håndhevet maskinelt i fasttrack-registeret og
PR-manifestet". These tests are that enforcement:

- the register must declare both contract layers (the research-side
  ``delivery_contract`` and the reusability-side ``definition_of_done``),
- every item must use a declared status value,
- any item flipped to DONE on or after ``dod_enforced_from`` must carry a
  ``dod:`` mapping with an evidence string for every definition-of-done
  criterion — a bare status flip can no longer mark a slice delivered.

Gate0 items completed before enforcement are grandfathered via their
``evidence`` date; they still require evidence, just not the per-criterion
breakdown that did not exist when they were closed.
"""

from __future__ import annotations

import pytest

from pathlib import Path

import yaml

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

REGISTER = Path(__file__).resolve().parents[1] / "docs" / "assurance" / "fasttrack_register_v1.yaml"

VALID_STATUSES = {
    "NOT_STARTED",
    "DESIGN_IN_REVIEW",
    "IN_PROGRESS",
    "BLOCKED_ON_MAINTAINER",
    "DONE",
}

# The reusability-side definition of done (maintainer review 2026-08-05).
# Order and keys are the contract; the register must declare exactly these.
DOD_CRITERIA = [
    "single_module_single_responsibility",
    "no_duplicate_abstraction_or_vocabulary",
    "documented_public_api",
    "unit_and_integration_tests",
    "negative_and_failure_paths",
    "architecture_or_adr_on_contract_change",
    "openapi_schema_updates_when_relevant",
    "runnable_external_example",
    "stability_classification",
    "clean_install_wheel_test",
]


def _load():
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8"))


def test_register_parses_and_has_items():
    data = _load()
    assert data["version"] == 1
    assert isinstance(data["items"], list) and data["items"]


def test_register_declares_both_contract_layers():
    data = _load()
    # Research-side layers (artifacts, literature, negative results, review).
    assert isinstance(data["delivery_contract"], list) and data["delivery_contract"]
    # Reusability-side definition of done — must match the agreed criteria
    # exactly so a slice cannot satisfy a quietly weakened contract.
    assert data["definition_of_done"] == DOD_CRITERIA


def test_enforcement_date_is_declared():
    data = _load()
    assert data["dod_enforced_from"] == "2026-08-05"


def test_every_item_has_id_title_priority_and_valid_status():
    for item in _load()["items"]:
        assert item.get("id"), f"item without id: {item}"
        assert item.get("title"), f"{item['id']}: missing title"
        assert item.get("priority"), f"{item['id']}: missing priority"
        assert item.get("status") in VALID_STATUSES, (
            f"{item['id']}: status {item.get('status')!r} not in {sorted(VALID_STATUSES)}"
        )


def test_item_ids_are_unique():
    ids = [item["id"] for item in _load()["items"]]
    assert len(ids) == len(set(ids)), f"duplicate ids: {sorted(set(i for i in ids if ids.count(i) > 1))}"


def test_done_items_carry_evidence():
    for item in _load()["items"]:
        if item["status"] == "DONE":
            assert item.get("evidence"), f"{item['id']}: DONE without evidence"


def test_done_after_enforcement_requires_full_dod_breakdown():
    """A slice closed on/after the enforcement date must show its work.

    ``dod`` must be a mapping covering every criterion with a non-empty
    evidence string. Grandfathered items declare ``dod_grandfathered: true``
    together with a pre-enforcement completion date in ``evidence``.
    """
    data = _load()
    for item in data["items"]:
        if item["status"] != "DONE":
            continue
        if item.get("dod_grandfathered"):
            continue
        dod = item.get("dod")
        assert isinstance(dod, dict), (
            f"{item['id']}: DONE after {data['dod_enforced_from']} requires a dod mapping "
            "(or dod_grandfathered: true for pre-enforcement closures)"
        )
        missing = [c for c in DOD_CRITERIA if not (isinstance(dod.get(c), str) and dod[c].strip())]
        assert not missing, f"{item['id']}: dod missing evidence for {missing}"


def test_sdk_surface_separation_is_on_the_roadmap():
    """The 2026-08-05 review's structural goal — a stable, small public SDK
    surface separated from experimental/research namespaces — must exist as
    a tracked item, not only as prose in a review."""
    items = {item["id"]: item for item in _load()["items"]}
    assert "FT-13" in items, "FT-13 (stable SDK surface separation) missing from register"
    ft13 = items["FT-13"]
    for ns in ("core_api", "adapters", "experimental"):
        assert ns in yaml.dump(ft13), f"FT-13 does not mention namespace {ns!r}"
