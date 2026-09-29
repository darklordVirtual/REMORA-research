# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""NTA-1 conformance: authority does not travel through composition.

Runs conformance/non-transitivity-of-authority-v1 against REMORA and checks that
every vector matches. A suite that always matches proves nothing, so the same
vectors are also run against a permissive adapter and against REMORA with one
guard weakened at a time; each weakening must surface as a divergence on the
vectors that name it. See docs/security/non-transitivity-of-authority.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parents[1] / "conformance" / "non-transitivity-of-authority-v1"
sys.path.insert(0, str(SUITE))

import adapter_remora  # noqa: E402
import run_conformance  # noqa: E402

VECTORS = json.loads((SUITE / "vectors.json").read_text(encoding="utf-8"))


def _outcomes(adapter) -> dict[str, str]:
    return {v["id"]: run_conformance.run_vector(adapter, v, VECTORS["world"])
            for v in VECTORS["vectors"]}


def _divergent(adapter) -> set[str]:
    observed = _outcomes(adapter)
    return {v["id"] for v in VECTORS["vectors"] if observed[v["id"]] != v["expect"]}


def test_remora_matches_every_vector():
    assert _divergent(adapter_remora.build()) == set()


def test_the_runner_writes_a_record_with_no_divergence(tmp_path):
    out = tmp_path / "record.json"
    subprocess.run([sys.executable, str(SUITE / "run_conformance.py"), "--adapter", "remora",
                    "--out", str(out)], check=True, capture_output=True, text=True)
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["counts"] == {"match": 13, "divergent": 0, "unsupported": 0,
                                "error": 0, "total": 13}


def test_every_vector_names_one_of_the_three_forms_or_the_baseline():
    assert {v["form"] for v in VECTORS["vectors"]} == {
        "reachability", "argument", "delegation", "baseline"}


class _Permissive(adapter_remora.RemoraNtaAdapter):
    """Authority travels: every delegation is granted, every call runs."""

    def delegate(self, handle, **_):
        return "DELEGATED"

    def authorize(self, handle, **_):
        return "AUTHORIZED"

    def dispatch(self, **_):
        return "EXECUTED"


def test_a_system_where_authority_travels_diverges_on_every_refusal_vector():
    refusal_vectors = {v["id"] for v in VECTORS["vectors"]
                       if v["expect"] not in {"EXECUTED", "DELEGATED"}}
    assert _divergent(_Permissive()) == refusal_vectors


def test_an_unbounded_chain_is_caught_by_the_depth_vector(monkeypatch):
    import remora.capabilities.delegation as delegation

    monkeypatch.setattr(delegation, "MAX_DELEGATION_DEPTH", 10)
    assert _divergent(adapter_remora.build()) == {"NTA-10"}


def test_default_transitivity_is_caught(monkeypatch):
    import remora.capabilities.delegation as delegation

    real = delegation.delegate

    def transitive_by_default(parent, **kwargs):
        kwargs["transitive"] = True
        return real(parent, **kwargs)

    monkeypatch.setattr(delegation, "delegate", transitive_by_default)
    monkeypatch.setattr("remora.capabilities.delegate", transitive_by_default)
    # NTA-10 still holds: every link there opts in, so only the depth cap stops it.
    assert _divergent(adapter_remora.build()) == {"NTA-07"}


@pytest.mark.parametrize("skeleton", ["skeleton"])
def test_an_unimplemented_adapter_reports_unsupported_not_failure(skeleton, tmp_path):
    out = tmp_path / "record.json"
    subprocess.run([sys.executable, str(SUITE / "run_conformance.py"), "--adapter", skeleton,
                    "--out", str(out)], check=True, capture_output=True, text=True)
    counts = json.loads(out.read_text(encoding="utf-8"))["counts"]
    assert counts["unsupported"] == 13 and counts["divergent"] == 0


def test_dropping_argument_constraints_is_caught(monkeypatch):
    from remora.capabilities.model import EffectiveCapabilitySet

    monkeypatch.setattr(EffectiveCapabilitySet, "check_arguments",
                        lambda self, *args, **kwargs: None)
    assert _divergent(adapter_remora.build()) == {"NTA-04", "NTA-06"}


def test_revocation_that_ignores_ancestors_is_caught(monkeypatch):
    import remora.capabilities.revocation as revocation
    from remora.capabilities.model import CapabilityRefusal

    def self_only(capability_set, source):
        if source is not None and source.revoked(capability_set.capability_set_id):
            return CapabilityRefusal.REVOKED
        return None

    # The dispatcher imports the function at call time, so patching the module
    # attribute reaches it.
    monkeypatch.setattr(revocation, "revocation_refusal", self_only)
    assert _divergent(adapter_remora.build()) == {"NTA-12"}
