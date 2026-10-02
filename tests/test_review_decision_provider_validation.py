# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings: malformed or out-of-range provider answers fail as DecisionProviderError."""
from __future__ import annotations

import math

import pytest

from remora.decision_providers import (
    DecisionProviderError,
    DecisionQuestion,
    QuestionKind,
)
from remora.decision_providers.cloudflare import CloudflareJevProvider
from remora.decision_providers.enrich import SemanticThresholds, enrich
from remora.policy.observation import PolicyObservation

Q = [
    DecisionQuestion(
        id="q", kind=QuestionKind.BOOLEAN, instructions="?",
        criteria={"true": "y", "false": "n"},
    )
]
TH = SemanticThresholds(
    intent_match=0.5, target_matches_request=0.5, possible_injection=0.5, scope_drift=0.5
)


def _provider(noul):
    def transport(url, payload, headers, timeout_s):
        return {"model": "m", "answers": {"q": {"type": "noul", "noul": noul}}}

    return CloudflareJevProvider(
        question_set_version="v", account_id="a", api_token="t", transport=transport
    )


def _observation():
    return PolicyObservation(
        question="refund the duplicate charge",
        risk_tier="medium",
        action_type="financial_transaction",
        target_environment="prod",
    )


@pytest.mark.parametrize("bad", ["high", None, 7.5, -0.1, math.nan, math.inf, True])
def test_bad_noul_is_a_provider_error(bad):
    with pytest.raises(DecisionProviderError):
        _provider(bad).evaluate(state={}, questions=Q, timeout_s=1.0)


def test_valid_noul_still_works():
    ev = _provider(0.25).evaluate(state={}, questions=Q, timeout_s=1.0)
    assert ev.answer("q").value == 0.25


def test_enrich_leaves_observation_unchanged_on_malformed_answer():
    obs = _observation()
    out = enrich(obs, _provider("high"), state={}, thresholds=TH, questions=Q)
    assert out.observation is obs
    assert out.outcome == "provider_unavailable"


def test_enrich_survives_a_provider_raising_arbitrary_errors():
    class Boom:
        def evaluate(self, **kw):
            raise TypeError("boom")

    obs = _observation()
    out = enrich(obs, Boom(), state={}, thresholds=TH, questions=Q)
    assert out.observation is obs
    assert out.outcome == "provider_unavailable"
