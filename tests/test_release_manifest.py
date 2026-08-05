# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What the product repository pins, and what it would miss if we forgot.

The consuming product must never install from ``master`` or copy internal
modules; it pins a hash-identified artifact set instead. That pin is only
worth as much as its coverage: a manifest listing the wheel but not the
frozen contracts lets a product pin the code and still disagree with
REMORA about what a ToolSpec is or what an effect status means — which is
exactly the drift the pin exists to prevent.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_release_manifest", ROOT / "scripts" / "build_release_manifest.py"
)
assert _spec and _spec.loader
build_release_manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_release_manifest)


@pytest.fixture()
def manifest(tmp_path):
    wheel = tmp_path / "remora-0.10.0-py3-none-any.whl"
    wheel.write_bytes(b"not a real wheel, only its identity is under test")
    return build_release_manifest.build_manifest(wheel)


REQUIRED_ARTIFACTS = {
    "wheel",
    "openapi",
    "sdk_public_api",
    "execution_lifecycle_schema",
    "tool_spec_schema",
    "postcondition_contract_schema",
}


def test_every_contract_a_consumer_verifies_against_is_pinned(manifest) -> None:
    assert set(manifest["artifacts"]) == REQUIRED_ARTIFACTS, {
        "missing": REQUIRED_ARTIFACTS - set(manifest["artifacts"]),
        "unexpected": set(manifest["artifacts"]) - REQUIRED_ARTIFACTS,
    }


def test_each_artifact_carries_a_real_digest(manifest) -> None:
    for name, entry in manifest["artifacts"].items():
        assert len(entry["sha256"]) == 64, f"{name}: not a sha256"
        assert entry["filename"], f"{name}: unnamed"


def test_the_stable_namespace_and_the_internal_ones_are_both_stated(
    manifest,
) -> None:
    """A consumer needs to know what it may rely on AND what it may not.
    Stating only the first leaves the second to be discovered by breakage."""
    contract = manifest["consumer_contract"]
    assert contract["stable_namespace"] == "remora.sdk"
    for internal in ("remora.policy", "remora.enforcement",
                     "remora.governance", "servers"):
        assert internal in contract["internal_namespaces"]


def test_the_effect_surface_is_present_in_the_pinned_sdk(manifest) -> None:
    """PR 5's surface must actually reach the product, not just master."""
    symbols = manifest["sdk"]["symbols"]
    for name in ("EffectStatus", "EffectVerificationView", "PostconditionSpec",
                 "ToolSpecIdentity", "build_postcondition", "verify_effect"):
        assert name in symbols, f"{name} missing from the pinned SDK surface"


def test_a_missing_wheel_fails_loudly(tmp_path) -> None:
    with pytest.raises(SystemExit):
        build_release_manifest.build_manifest(tmp_path / "absent.whl")
