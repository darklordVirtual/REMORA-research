# SPDX-License-Identifier: BUSL-1.1
"""Falsification tests for the credential-topology gate (property E, static half).

The gate passes on the committed register, which on its own says nothing:
a check that cannot fail is not evidence. Every test below removes one
property from the register and asserts the gate notices. The zone-breach
case is the important one, because it uses REAL repository data rather than
a fixture: widening the agent zone to include remora/toolcall must surface
the credentials that widening actually exposes.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "docs" / "assurance" / "credential_topology.yaml"


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "check_credential_topology", ROOT / "scripts" / "check_credential_topology.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


@pytest.fixture
def register() -> dict:
    return yaml.safe_load(REGISTER_PATH.read_text(encoding="utf-8"))


def _entry(register: dict, name: str) -> dict:
    for cred in register["credentials"]:
        if cred["name"] == name:
            return cred
    raise AssertionError(f"{name} missing from the committed register")


def test_committed_register_passes(register: dict) -> None:
    assert gate.check(register) == []


def test_undeclared_secret_is_reported(register: dict) -> None:
    """Dropping a real credential must be caught, not tolerated."""
    mutated = copy.deepcopy(register)
    mutated["credentials"] = [
        c for c in mutated["credentials"] if c["name"] != "REMORA_PDP_SIGNING_KEY"
    ]
    failures = gate.check(mutated)
    assert any("REMORA_PDP_SIGNING_KEY" in f and "absent from the register" in f
               for f in failures), failures


def test_stale_declaration_is_reported(register: dict) -> None:
    """A credential nothing reads any more must not linger as decoration."""
    mutated = copy.deepcopy(register)
    mutated["credentials"].append(
        {
            "name": "REMORA_RETIRED_SIGNING_KEY",
            "class": "authority_key",
            "holder": "authority domain",
            "authorized_path": "nowhere",
            "read_by": ["remora/enforcement/token.py"],
            "agent_reachable": False,
            "note": "invented for this test",
        }
    )
    failures = gate.check(mutated)
    assert any("REMORA_RETIRED_SIGNING_KEY" in f and "no longer read" in f
               for f in failures), failures


def test_read_by_drift_is_reported(register: dict) -> None:
    """The register must track who reads a credential, not merely that it exists."""
    mutated = copy.deepcopy(register)
    _entry(mutated, "REMORA_PDP_SIGNING_KEY")["read_by"] = ["servers/api.py"]
    failures = gate.check(mutated)
    assert any("REMORA_PDP_SIGNING_KEY" in f and "read_by drift" in f
               for f in failures), failures


def test_agent_zone_breach_is_reported(register: dict) -> None:
    """The reachability check bites against real code, not only fixtures.

    remora/toolcall is dispatcher-side and benchmark-side, and the register
    says so explicitly. If it were treated as agent-controlled, authority
    keys would be reachable from the agent zone. Asserting that here is what
    turns the register's zone choice from an assumption into a stated,
    testable consequence.
    """
    mutated = copy.deepcopy(register)
    mutated["agent_zone_roots"] = [*mutated["agent_zone_roots"], "remora/toolcall"]
    failures = gate.check(mutated)
    breaches = [f for f in failures if "declared unreachable from the agent zone" in f]
    assert breaches, failures
    joined = " ".join(breaches)
    assert "REMORA_PDP_SIGNING_KEY" in joined
    assert "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE" in joined


def test_committed_zone_is_actually_narrower_than_the_breach_case(
    register: dict,
) -> None:
    """Guards against the zone silently growing to include the dispatcher."""
    reads, _dynamic, files = gate.collect(register)
    zone = gate.import_closure(register["agent_zone_roots"], files)
    assert "remora/enforcement/token.py" not in zone
    assert "remora/enforcement/lease_signing.py" not in zone
    assert any(m.startswith("remora/sdk/") for m in zone)


def test_protected_class_requires_explicit_unreachability(register: dict) -> None:
    mutated = copy.deepcopy(register)
    _entry(mutated, "REMORA_AUDIT_SIGNING_KEY")["agent_reachable"] = True
    failures = gate.check(mutated)
    assert any("REMORA_AUDIT_SIGNING_KEY" in f and "agent_reachable" in f
               for f in failures), failures


def test_protected_class_requires_holder_and_path(register: dict) -> None:
    mutated = copy.deepcopy(register)
    _entry(mutated, "REMORA_PG_DSN")["holder"] = ""
    failures = gate.check(mutated)
    assert any("REMORA_PG_DSN" in f and "holder" in f for f in failures), failures


def test_unknown_class_is_reported(register: dict) -> None:
    mutated = copy.deepcopy(register)
    _entry(mutated, "REMORA_API_TOKENS")["class"] = "probably_fine"
    failures = gate.check(mutated)
    assert any("REMORA_API_TOKENS" in f and "unknown class" in f
               for f in failures), failures


def test_undeclared_dynamic_read_site_is_reported(register: dict) -> None:
    """An opaque environment read must not be able to hide a credential."""
    mutated = copy.deepcopy(register)
    mutated["dynamic_read_sites"] = [
        d for d in mutated["dynamic_read_sites"]
        if not d["site"].startswith("remora/audit/anchor.py")
    ]
    failures = gate.check(mutated)
    assert any("remora/audit/anchor.py" in f and "cannot resolve" in f
               for f in failures), failures


def test_vanished_dynamic_site_is_reported(register: dict) -> None:
    mutated = copy.deepcopy(register)
    mutated["dynamic_read_sites"] = [
        *mutated["dynamic_read_sites"],
        {"site": "remora/nowhere.py:1", "reason": "invented for this test"},
    ]
    failures = gate.check(mutated)
    assert any("remora/nowhere.py:1" in f and "no longer exists" in f
               for f in failures), failures


@pytest.mark.parametrize(
    "name",
    [
        "REMORA_PDP_SIGNING_KEY",
        "GROQ_API_KEY",
        "REMORA_PG_DSN",
        "REMORA_API_BEARER_TOKEN",
        "REMORA_LEASE_ACCEPT_HMAC",
        "CLOUDFLARE_ORACLE_SECRET",
    ],
)
def test_secret_pattern_matches_credential_shaped_names(name: str) -> None:
    assert gate.SECRET.search(name)


@pytest.mark.parametrize(
    "name",
    [
        "REMORA_ENV",
        "REMORA_PDP_SIGNING_KID",
        "REMORA_PDP_REVOKED_KIDS",
        "REMORA_RUNTIME_PROFILE",
        "NO_COLOR",
    ],
)
def test_secret_pattern_does_not_match_configuration(name: str) -> None:
    """A pattern that matched everything would make the register meaningless."""
    assert not gate.SECRET.search(name)


def test_every_limit_has_an_identifier_and_text(register: dict) -> None:
    """The limits block is quoted into the conformance assessment verbatim."""
    limits = register["limits"]
    assert len(limits) >= 5
    for item in limits:
        assert item["id"].startswith("L")
        assert len(item["limit"].strip()) > 40
        # Every limit must say what the strict profiles do about it. A limit
        # with no disposition is one nobody decided on.
        assert len(item["strict_profile"].strip()) > 40, item["id"]


def test_deployment_supplied_credential_gap_is_declared(register: dict) -> None:
    """L5 is the honest core of E and must not quietly disappear."""
    text = " ".join(item["limit"] for item in register["limits"])
    assert "GovernedToolDispatcher" in text


def test_the_gate_never_reads_an_environment_value() -> None:
    """Why the clear-text-logging alert on this script is a false positive.

    CodeQL flags the diagnostic output because the data flowing into it is
    named like secrets. The data IS names: this gate resolves credentials by
    parsing source with ``ast`` and never inspects the running environment,
    so no credential value exists in the process to leak.

    Asserted rather than argued, because a future edit could quietly make the
    argument false. If someone adds an environment read here, this test fails
    and the alert stops being a false positive.
    """
    import ast

    source = (ROOT / "scripts" / "check_credential_topology.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    imported_os = any(
        (isinstance(n, ast.Import) and any(a.name == "os" for a in n.names))
        or (isinstance(n, ast.ImportFrom) and n.module == "os")
        for n in ast.walk(tree)
    )
    assert not imported_os, "the topology gate must not import os"

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"environ", "getenv"}, (
                f"environment access at line {node.lineno}: the gate reads "
                "credential NAMES from source, never values"
            )
