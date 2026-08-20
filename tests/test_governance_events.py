# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The safety core emits operational events, and never a credential.

The audit chain answers "what was authorised, under which policy, by whom".
These events answer "what did the process do, when" — the question you need
answered to run a pilot. Before 2026-08-20 the core answered neither:
remora/policy, remora/enforcement and remora/execution held zero loggers.
"""
from __future__ import annotations

import logging

import pytest

from remora.observability.events import SecretFieldError, governance_event
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation


def test_a_decision_emits_one_event(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="remora.governance"):
        RemoraDecisionEngine().decide(
            PolicyObservation(question="read the status page")
        )
    events = [r for r in caplog.records if r.getMessage().startswith("decision.made")]
    assert len(events) == 1
    payload = events[0].remora  # type: ignore[attr-defined]
    assert payload["action"] in {"accept", "verify", "abstain", "escalate"}
    assert isinstance(payload["reasons"], list)


def test_the_escalation_replacement_does_not_double_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One decision, one decision.made line — the rebuild must stay silent."""
    with caplog.at_level(logging.INFO, logger="remora.governance"):
        RemoraDecisionEngine().decide(
            PolicyObservation(
                question="delete prod", risk_tier="critical", action_type="delete"
            )
        )
    made = [r for r in caplog.records if r.getMessage().startswith("decision.made")]
    assert len(made) == 1


@pytest.mark.parametrize(
    "field",
    ["api_key", "signing_key", "bearer_token", "password", "client_secret",
     "authorization", "private_key", "credential"],
)
def test_secret_shaped_field_names_are_refused(field: str) -> None:
    """A logging call must never become the reason a key leaks."""
    with pytest.raises(SecretFieldError):
        governance_event("probe", **{field: "value"})


def test_token_identifiers_are_allowed() -> None:
    """jti identifies a grant; it is not the grant."""
    governance_event("probe", token_jti="abc", grant_jti="def")


def test_emission_never_raises_on_an_unrenderable_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An observability defect must not become a governance defect."""

    class _Explodes:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="remora.governance"):
        governance_event("probe", value=_Explodes())


def test_events_are_off_when_the_logger_is(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("remora.governance")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        with caplog.at_level(logging.CRITICAL, logger="remora.governance"):
            governance_event("probe", ordinary_field=1)
        assert not [r for r in caplog.records if r.getMessage().startswith("probe")]
    finally:
        logger.setLevel(previous)
