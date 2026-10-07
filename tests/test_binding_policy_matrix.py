# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The binding x profile matrix is backed by the code (CR-006).

docs/assurance/binding_policy_matrix_v1.yaml states, per binding, which
states the v2 contract allows, what compares it, what it refuses with and what
startup requires. These tests keep that document from drifting into claims.
"""
from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest
import yaml

from remora.enforcement.binding_policy import BINDINGS, CORE_BINDINGS

ROOT = Path(__file__).resolve().parents[1]
MATRIX = yaml.safe_load((ROOT / "docs/assurance/binding_policy_matrix_v1.yaml").read_text(encoding="utf-8"))
CODE = "\n".join(p.read_text(encoding="utf-8")
                 for folder in ("remora", "servers") for p in (ROOT / folder).rglob("*.py"))
PROFILE = (ROOT / "remora/toolcall/runtime_profile.py").read_text(encoding="utf-8")


def test_every_binding_is_in_the_matrix_and_nothing_else() -> None:
    assert list(MATRIX["bindings"]) == list(BINDINGS)


@pytest.mark.parametrize("binding", BINDINGS)
def test_every_named_refusal_exists_in_the_code(binding) -> None:
    entry = MATRIX["bindings"][binding]
    for key, reason in entry.items():
        if key.startswith("refusal"):
            assert f'"{reason}"' in CODE, (binding, reason)


@pytest.mark.parametrize("binding", BINDINGS)
def test_core_bindings_allow_only_required(binding) -> None:
    states = MATRIX["bindings"][binding]["states_v2"]
    if binding in CORE_BINDINGS and binding != "resolved_effect":
        assert states == ["REQUIRED"], binding
    assert "UNVERIFIABLE" not in states or binding not in CORE_BINDINGS


@pytest.mark.parametrize("binding", ["capability_set", "resolved_effect", "runtime_surface"])
def test_every_startup_requirement_is_enforced_at_startup(binding) -> None:
    for name in (n.strip() for n in MATRIX["bindings"][binding]["startup"].split(",")):
        assert f'"{name}"' in PROFILE, (binding, name)


def test_enforce_is_deprecated_and_has_no_production_caller() -> None:
    callers = []
    for folder in ("remora", "servers"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "enforce" and path.name != "gate.py"):
                    callers.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert callers == [], callers

    from remora.enforcement.gate import EnforcementGate

    from remora.enforcement.token import PolicyDecisionToken

    gate = EnforcementGate(strict=False)
    token = PolicyDecisionToken.issue(action="abstain", observation_hash="h" * 64,
                                      request_id="r", issued_at="2026-10-07T00:00:00+00:00")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            gate.enforce(token, lambda: None)
        except PermissionError:
            pass  # an abstain token is refused; the warning is what is tested
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
