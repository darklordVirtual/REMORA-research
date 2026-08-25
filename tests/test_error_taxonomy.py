# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One root, machine-readable identity, and no un-caught builtins (issue #45 gap 4).

The audit found three custom exceptions with three unrelated bases and 230
builtin raises: routing severity required string-matching messages. These
tests pin the taxonomy from the three directions that matter: every
governance exception descends from RemoraError and carries a stable code;
the codes are unique (they are an alerting dimension, not documentation);
and every builtin base that callers catch today is preserved, because a
taxonomy change that silently un-catches a guarded failure is a safety
regression dressed as a cleanup.
"""
from __future__ import annotations

import pytest

from remora.errors import RemoraError

# (class path, expected code, expected category, preserved builtin base)
TAXONOMY = [
    ("remora.enforcement.lease", "ToolExecutionStateUnknown",
     "tool_execution_state_unknown", "enforcement", RuntimeError),
    ("remora.enforcement.lease", "LeaseRefused",
     "lease_refused", "enforcement", None),
    ("remora.enforcement.lease_signing", "SigningUnavailable",
     "signing_unavailable", "enforcement", RuntimeError),
    ("remora.enforcement.nonce_store", "NonceStoreUnavailable",
     "nonce_store_unavailable", "enforcement", RuntimeError),
    ("remora.execution.projections", "EffectVerificationReplay",
     "effect_verification_replay", "execution", RuntimeError),
    ("remora.execution.remote_dispatch", "RemoteDispatchUnavailable",
     "remote_dispatch_unavailable", "execution", RuntimeError),
    ("remora.execution.review_service", "ReviewNotFound",
     "review_not_found", "execution", None),
    ("remora.execution.review_service", "ReviewConflict",
     "review_conflict", "execution", None),
    ("remora.execution.service", "ToolSpecChanged",
     "toolspec_changed", "execution", None),
    ("remora.execution.service", "TokenRefused",
     "token_refused", "execution", None),
    ("remora.governance.effect_receipt", "ReceiptRefused",
     "receipt_refused", "governance", None),
    ("remora.governance.lifecycle", "IllegalTransition",
     "illegal_lifecycle_transition", "governance", None),
    ("remora.governance.spec_intake", "SpecIntakeRefused",
     "spec_intake_refused", "governance", ValueError),
    ("remora.knowledge_domains.multitenant", "CrossTenantError",
     "cross_tenant_access", "tenancy", KeyError),
    ("remora.persistence.d1_connection", "D1Unavailable",
     "d1_unavailable", "persistence", RuntimeError),
    ("remora.policy.invariants", "InvariantViolationError",
     "invariant_violation", "governance", RuntimeError),
]


def _load(module: str, name: str) -> type:
    import importlib
    return getattr(importlib.import_module(module), name)


@pytest.mark.parametrize("module,name,code,category,builtin",
                         TAXONOMY, ids=[t[1] for t in TAXONOMY])
def test_descends_from_the_root_with_a_stable_identity(
    module, name, code, category, builtin
) -> None:
    cls = _load(module, name)
    assert issubclass(cls, RemoraError)
    assert cls.code == code
    assert cls.category == category


@pytest.mark.parametrize("module,name,code,category,builtin",
                         [t for t in TAXONOMY if t[4] is not None],
                         ids=[t[1] for t in TAXONOMY if t[4] is not None])
def test_the_builtin_base_callers_catch_today_is_preserved(
    module, name, code, category, builtin
) -> None:
    """dispatch.py catches RuntimeError, spec_intake's caller ValueError,
    multitenant's KeyError: rebasing must not un-catch any of them."""
    assert issubclass(_load(module, name), builtin)


def test_codes_are_unique_across_the_taxonomy() -> None:
    codes = [t[2] for t in TAXONOMY]
    assert len(set(codes)) == len(codes)


def test_machine_readable_carries_the_routable_identity() -> None:
    from remora.enforcement.lease import LeaseRefused
    err = LeaseRefused("decision was not accept")
    assert err.machine_readable() == {
        "code": "lease_refused",
        "category": "enforcement",
        "error": "LeaseRefused",
    }


def test_the_sdk_hierarchy_stays_a_separate_contract() -> None:
    """remora.sdk.errors.RemoraError is the CLIENT-side view of HTTP
    responses and is stable by policy (FT-13). The two hierarchies meet at
    the wire, not in Python — sharing a root would leak server churn into
    the SDK contract."""
    from remora.sdk.errors import RemoraError as SdkRemoraError
    assert SdkRemoraError is not RemoraError
    assert not issubclass(SdkRemoraError, RemoraError)
    assert not issubclass(RemoraError, SdkRemoraError)


def test_dispatchs_runtime_error_handler_still_catches_state_unknown() -> None:
    """The one catch the audit called most alert-worthy: 'tool failed, nonce
    burned, state unknown' is handled via `except RuntimeError` in
    dispatch.py. The rebase must leave that path reachable."""
    from remora.enforcement.lease import ToolExecutionStateUnknown
    caught = False
    try:
        raise ToolExecutionStateUnknown("boom", proposal_id="p", tenant_id="t")
    except RuntimeError as exc:
        caught = True
        assert exc.machine_readable()["code"] == "tool_execution_state_unknown"
    assert caught
