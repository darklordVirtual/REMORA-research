# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property-based invariant testing for the enforcement core.

Example-based tests pin hand-picked cases; these properties search a
DECLARED generated domain for counterexamples to the architecture's claims:
chain verification across generated append sequences with single-entry
tampers, lease refusal of the searched argument mutations, token expiry.
Scope stated honestly: flat dicts of str/int/bool values (max five keys)
and an additive top-level mutation — nested structures, deletions,
value edits, floats, None and unicode-normalization equivalences are NOT
covered. No counterexample found in the stated example counts; this is
searched validation, not formal proof.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.enforcement.lease import ExecutionLease
from remora.enforcement.token import PolicyDecisionToken
from remora.governance.tenant_chain import TenantAuditChain

TENANT = "acme"
ISSUED_AT = "2026-01-01T00:00:00+00:00"
BUNDLE = "sha256:policybundle01"


@pytest.fixture(autouse=True)
def _signing_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "prop-test-lease-key")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "prop-test-pdp-key")


_json_values = st.one_of(
    st.text(max_size=20),
    st.integers(min_value=-10**6, max_value=10**6),
    st.booleans(),
)
_payloads = st.dictionaries(
    keys=st.text(min_size=1, max_size=12), values=_json_values,
    min_size=1, max_size=5,
)


@settings(max_examples=50, deadline=None)
@given(st.lists(_payloads, min_size=1, max_size=8))
def test_chain_verifies_after_any_append_sequence(payloads) -> None:
    chain = TenantAuditChain()
    for payload in payloads:
        chain.append(TENANT, payload)
    ok, problems = chain.verify(TENANT)
    assert ok, problems
    assert len(chain.entries(TENANT)) == len(payloads)


@settings(max_examples=50, deadline=None)
@given(st.lists(_payloads, min_size=1, max_size=6), st.data())
def test_chain_detects_any_single_entry_tamper(payloads, data) -> None:
    chain = TenantAuditChain()
    for payload in payloads:
        chain.append(TENANT, payload)
    entries = chain.entries(TENANT)
    victim = entries[data.draw(st.integers(0, len(entries) - 1), label="victim")]
    # Key is longer than the strategy's max key size (12), so it is
    # guaranteed absent — the mutation can never be a no-op.
    victim.payload["___tamper_marker___"] = data.draw(_json_values, label="tamper")
    ok, problems = chain.verify(TENANT)
    assert not ok
    assert any("hash_mismatch" in p for p in problems)


@settings(max_examples=50, deadline=None)
@given(_payloads, st.data())
def test_lease_refuses_any_argument_mutation(arguments, data) -> None:
    lease = ExecutionLease.issue(
        decision="accept", tenant_id=TENANT, actor_identity="agent-7",
        tool_name="adjust_setpoint", arguments=arguments,
        target_environment="prod", policy_bundle_hash=BUNDLE,
        issued_at=ISSUED_AT,
    )
    same = lease.verify(
        tool_name="adjust_setpoint", arguments=dict(arguments),
        tenant_id=TENANT, target_environment="prod", now=ISSUED_AT,
        expected_policy_bundle_hash=BUNDLE, actor_identity="agent-7",
    )
    assert same.verified, same.reason

    mutated = dict(arguments)
    # Guaranteed-absent key (longer than the strategy's max key size), so
    # the mutation always changes the argument set.
    mutated["___extra_argument___"] = data.draw(_json_values, label="extra")
    diff = lease.verify(
        tool_name="adjust_setpoint", arguments=mutated,
        tenant_id=TENANT, target_environment="prod", now=ISSUED_AT,
        expected_policy_bundle_hash=BUNDLE, actor_identity="agent-7",
    )
    assert not diff.verified
    assert diff.reason == "tool_args_hash_mismatch"


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=10**6))
def test_expired_token_never_verifies(age_seconds) -> None:
    token = PolicyDecisionToken.issue(
        action="accept", observation_hash="a" * 64, request_id="r-1",
        issued_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-01T00:05:00+00:00",
        audience="pep",
    )
    late = f"2026-01-01T00:05:{min(59, age_seconds % 60):02d}+00:00" \
        if age_seconds < 60 else "2026-01-02T00:00:00+00:00"
    result = token.verify(observation_hash="a" * 64, now=late)
    assert not result.verified
    assert result.reason == "token_expired"
