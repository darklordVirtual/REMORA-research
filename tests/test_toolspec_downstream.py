# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""ToolSpec v2: the optional downstream-capability ceiling (NTA-2 phase 2).

A signed ToolSpec may declare the most its implementation may reach. The
declaration is part of the signed content, is parsed and validated when the
bundle loads, and is only accepted in a schema-version-2 bundle, so a v1
consumer never meets a field it does not know. Absent, it changes no existing
spec hash.
"""
from __future__ import annotations

import pytest

from remora.capabilities.ceiling import DownstreamCeiling
from remora.toolcall.toolspec import ToolSpecBundle, ToolSpecRefused, _spec_hash, sign_bundle
from tests.test_toolspec_runtime import IDENTITY, KEY, _spec

DECLARATION = [
    {"capability": "database.read", "resources": ["Database://Reporting-EU/*"],
     "purpose": "generate_report"},
]


def _load(specs, schema_version):
    bundle = sign_bundle({"schema_version": schema_version, "tool_specs": specs},
                         key=KEY, signing_identity=IDENTITY,
                         signed_at="2026-09-29T00:00:00+00:00")
    return ToolSpecBundle.load(bundle, key=KEY, trusted_identities=[IDENTITY])


def test_a_v1_spec_without_a_declaration_is_unchanged():
    raw = _spec()
    spec = _load([raw], 1).get("store_artifact")
    assert spec.downstream_capabilities is None
    assert spec.toolspec_hash == _spec_hash(raw)


def test_a_v2_bundle_accepts_specs_without_a_declaration():
    assert _load([_spec()], 2).get("store_artifact").downstream_capabilities is None


def test_a_v2_declaration_is_parsed_canonically_and_hashed():
    raw = _spec(downstream_capabilities=DECLARATION)
    spec = _load([raw], 2).get("store_artifact")
    assert isinstance(spec.downstream_capabilities, DownstreamCeiling)
    assert spec.downstream_capabilities.tool == "store_artifact"
    assert spec.downstream_capabilities.capability("database.read").resources == (
        "database://reporting-eu/*",)
    assert spec.toolspec_hash == _spec_hash(raw) != _spec_hash(_spec())


def test_a_declaration_in_a_v1_bundle_is_refused():
    with pytest.raises(ToolSpecRefused) as exc:
        _load([_spec(downstream_capabilities=DECLARATION)], 1)
    assert exc.value.reason_code == "toolspec_downstream_requires_v2"


@pytest.mark.parametrize("declaration", [
    [{"capability": "database.read", "resources": ["database://../x"], "purpose": "p"}],
    [{"capability": "database.read", "resources": [], "purpose": "p"}],
    "not-a-list",
])
def test_a_malformed_declaration_refuses_the_bundle(declaration):
    with pytest.raises(ToolSpecRefused) as exc:
        _load([_spec(downstream_capabilities=declaration)], 2)
    assert exc.value.reason_code == "toolspec_downstream_declaration_invalid"


@pytest.mark.parametrize("version", [0, 4, "3", None])  # 3 is the CR-005 effect policy
def test_an_unknown_schema_version_is_refused(version):
    with pytest.raises(ToolSpecRefused) as exc:
        _load([_spec()], version)
    assert exc.value.reason_code == "toolspec_schema_version_unsupported"


def test_the_declaration_round_trips():
    spec = _load([_spec(downstream_capabilities=DECLARATION)], 2).get("store_artifact")
    ceiling = spec.downstream_capabilities
    assert DownstreamCeiling.from_dict(ceiling.tool, ceiling.to_list()) == ceiling


def test_the_v2_contract_lists_exactly_the_codes_the_loader_adds():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1] / "schemas"
    v2 = yaml.safe_load((root / "tool_spec_v2.yaml").read_text(encoding="utf-8"))
    v1 = yaml.safe_load((root / "tool_spec_v1.yaml").read_text(encoding="utf-8"))
    assert v2["extends"] == "tool_spec_v1.yaml" and v2["schema_version"] == 2
    assert set(v2["reason_codes_added"]) <= {c["code"] for c in v1["reason_codes"]}
    assert "downstream_capabilities" in v2["optional_fields"]
