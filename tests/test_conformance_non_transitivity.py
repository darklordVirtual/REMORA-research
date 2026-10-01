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
    n = len(VECTORS["vectors"])
    assert record["counts"] == {"match": n, "divergent": 0, "unsupported": 0,
                                "error": 0, "total": n}


def test_every_vector_names_one_of_the_three_forms_or_the_baseline():
    assert {v["form"] for v in VECTORS["vectors"]} == {
        "reachability", "argument", "delegation", "implementation", "baseline"}


class _Permissive(adapter_remora.RemoraNtaAdapter):
    """Authority travels: every delegation is granted, every call runs."""

    def delegate(self, handle, **_):
        return "DELEGATED"

    def authorize(self, handle, **_):
        return "AUTHORIZED"

    def dispatch(self, **_):
        return "EXECUTED"

    def open_execution(self, handle, **_):
        return "OPENED"

    def mediate(self, **_):
        return "EXECUTED"

    def close_execution(self, execution):
        return "CLOSED"


def test_a_system_where_authority_travels_diverges_on_every_refusal_vector():
    refusal_vectors = {v["id"] for v in VECTORS["vectors"]
                       if v["expect"] not in {"EXECUTED", "DELEGATED", "OPENED"}}
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
    assert counts["unsupported"] == len(VECTORS["vectors"]) and counts["divergent"] == 0


def test_dropping_argument_constraints_is_caught(monkeypatch):
    from remora.capabilities.model import EffectiveCapabilitySet

    monkeypatch.setattr(EffectiveCapabilitySet, "check_arguments",
                        lambda self, *args, **kwargs: None)
    # The resource patterns of NTA-2 are argument constraints too, so the
    # provider-switch and resource-widening vectors fall with them.
    assert _divergent(adapter_remora.build()) == {"NTA-04", "NTA-06", "NTA2-02", "NTA2-04"}


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
    # The tool's effect authority has the caller's set as an ancestor.
    assert _divergent(adapter_remora.build()) == {"NTA-12", "NTA2-09"}


# NTA-2: each guard of the mediator, weakened on its own.

def test_ignoring_resource_patterns_is_caught(monkeypatch):
    import remora.capabilities.resource as resource

    monkeypatch.setattr(resource, "resource_within", lambda value, patterns: True)
    assert _divergent(adapter_remora.build()) == {"NTA2-02", "NTA2-04"}


def test_normalising_traversal_instead_of_refusing_it_is_caught(monkeypatch):
    import posixpath

    import remora.capabilities.resource as resource

    real = resource.canonical_resource

    def normalising(raw):
        scheme, _, rest = str(raw).partition("://")
        authority, _, path = rest.partition("/")
        return real(f"{scheme}://{authority}" + posixpath.normpath("/" + path).rstrip("/"))

    monkeypatch.setattr(resource, "canonical_resource", normalising)
    import remora.enforcement.capability_mediator as mediator

    monkeypatch.setattr(mediator, "canonical_resource", normalising)
    # normpath clamps ".." at the root of the path, so
    # workspace://reports/../secrets/key becomes workspace://reports/secrets/key
    # and lands inside workspace://reports/*. Refusing ambiguous forms, rather
    # than normalising them, is what keeps the traversal vector refused.
    assert _divergent(adapter_remora.build()) == {"NTA2-03"}


def test_accepting_an_unresolved_resource_is_caught(monkeypatch):
    import remora.enforcement.capability_mediator as mediator

    real = mediator.CapabilityMediator.invoke

    def defaulting(self, capability, resource, arguments=None):
        return real(self, capability, resource or "database://reporting-eu/default", arguments)

    monkeypatch.setattr(mediator.CapabilityMediator, "invoke", defaulting)
    assert _divergent(adapter_remora.build()) == {"NTA2-05"}


def test_ignoring_close_is_caught(monkeypatch):
    import remora.enforcement.capability_mediator as mediator

    monkeypatch.setattr(mediator.CapabilityMediator, "close", lambda self: None)
    assert _divergent(adapter_remora.build()) == {"NTA2-08"}


def test_letting_policy_widen_the_ceiling_is_caught(monkeypatch):
    import remora.enforcement.effect_capability as effect

    real = effect.derive_effect_authority

    def widening(parent, **kwargs):
        kwargs.pop("policy_allows", None)
        return real(parent, **kwargs)

    monkeypatch.setattr(effect, "derive_effect_authority", widening)
    assert _divergent(adapter_remora.build()) == {"NTA2-10"}
