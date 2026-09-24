# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The Workers AI adapter, against the documented request and response shapes.

No network. A transport is injected, so what these tests establish is the
parsing and the failure mapping, not the model's behaviour. The fixture below
is the response shape from the Cloudflare Workers AI documentation for
`typesafe/jev`, kept verbatim so a change upstream shows up as a diff here
rather than as a surprise in production.

Three of the assertions matter more than the rest, because each pins a place
where a quieter adapter would lose information a decision depends on:

* a `noul` answer is a probability and stays one, so 0.51 and 0.99 cannot
  collapse into the same record
* a `score` answer keeps the legend that gives its number meaning
* the resolved model version comes from the response, not from the alias the
  request asked for

Scope (declared, not exhaustive): request construction, response parsing,
failure mapping. Nothing here is evidence about the model's answers, its
latency or its availability.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from remora.decision_providers import (
    DecisionProvider,
    DecisionProviderError,
    DecisionQuestion,
    QuestionKind,
)
from remora.decision_providers.cloudflare import JEV_MODEL_ID, CloudflareJevProvider

# Verbatim from the Workers AI documentation for typesafe/jev.
DOCUMENTED_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "is_urgent": {"type": "noul", "noul": 0.95},
        "department": {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.8,
            "probabilities": {"billing": 0.87, "sales": 0, "technical": 0.13},
        },
        "frustration": {
            "type": "score",
            "score": 1.04,
            "confidence": 0.94,
            "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
            "probabilities": {"0": 0, "1": 0.96, "2": 0.04},
        },
    },
    "usage": {"input_tokens": 426, "output_tokens": 73},
}

QUESTIONS = [
    DecisionQuestion(
        id="is_urgent",
        kind=QuestionKind.BOOLEAN,
        instructions="Does this convey urgency?",
        criteria={"true": "Explicitly time-sensitive", "false": "No urgency expressed"},
    ),
    DecisionQuestion(
        id="department",
        kind=QuestionKind.CHOICE,
        instructions="Which team should handle this?",
        options=("billing", "technical", "sales"),
        criteria={
            "billing": "Payments, invoicing, refunds",
            "technical": "Bugs, outages, integrations",
            "sales": "Pricing, upgrades, new accounts",
        },
    ),
    DecisionQuestion(
        id="frustration",
        kind=QuestionKind.SCORE,
        instructions="How frustrated is the customer?",
        legend=("Calm", "Frustrated", "Very angry"),
    ),
]

STATE = {"message": "Help! My payouts have been failing for 3 days."}


class _Recorder:
    """An injected transport that records the call and replays a document."""

    def __init__(self, document=None, raises: Exception | None = None):
        self.document = document if document is not None else DOCUMENTED_RESPONSE
        self.raises = raises
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, payload, headers, timeout_s):
        self.calls.append((url, json.loads(payload), dict(headers)))
        if self.raises is not None:
            raise self.raises
        return self.document


def _provider(transport, **kw) -> CloudflareJevProvider:
    return CloudflareJevProvider(
        question_set_version="support-triage-v1",
        account_id="acct-123",
        api_token="token-abc",
        transport=transport,
        **kw,
    )


# ── request shape ───────────────────────────────────────────────────────────


def test_the_request_matches_the_documented_endpoint_and_body() -> None:
    recorder = _Recorder()
    _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    url, body, headers = recorder.calls[0]

    assert url == "https://api.cloudflare.com/client/v4/accounts/acct-123/ai/run"
    assert headers["Authorization"] == "Bearer token-abc"
    assert body["model"] == JEV_MODEL_ID
    assert body["input"]["state"] == STATE
    assert set(body["input"]["questions"]) == {"is_urgent", "department", "frustration"}


def test_each_question_kind_is_sent_under_its_api_name() -> None:
    recorder = _Recorder()
    _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    sent = recorder.calls[0][1]["input"]["questions"]
    assert sent["is_urgent"]["type"] == "noul"
    assert sent["department"]["type"] == "choice"
    assert sent["frustration"]["type"] == "score"


def test_declared_criteria_are_forwarded_and_a_score_legend_becomes_criteria() -> None:
    recorder = _Recorder()
    _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    sent = recorder.calls[0][1]["input"]["questions"]
    assert sent["is_urgent"]["criteria"]["true"] == "Explicitly time-sensitive"
    assert sent["department"]["criteria"]["billing"] == "Payments, invoicing, refunds"
    assert sent["frustration"]["criteria"] == ["Calm", "Frustrated", "Very angry"]


def test_all_questions_go_in_one_request() -> None:
    """The provider evaluates in parallel against one state; one call, not three."""
    recorder = _Recorder()
    _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert len(recorder.calls) == 1


# ── response parsing, where information is easiest to lose ──────────────────


def test_a_noul_answer_stays_a_probability() -> None:
    evidence = _provider(_Recorder()).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    answer = evidence.answer("is_urgent")
    assert answer.value == pytest.approx(0.95)
    assert answer.probabilities == {"true": pytest.approx(0.95), "false": pytest.approx(0.05)}


def test_thresholding_a_noul_answer_demands_an_explicit_threshold() -> None:
    evidence = _provider(_Recorder()).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    answer = evidence.answer("is_urgent")
    assert answer.as_bool(threshold=0.9) is True
    assert answer.as_bool(threshold=0.99) is False
    with pytest.raises(TypeError):
        answer.as_bool()  # type: ignore[call-arg]  # no default threshold exists
    with pytest.raises(ValueError):
        answer.as_bool(threshold=1.5)


def test_a_score_answer_keeps_the_legend_that_gives_it_meaning() -> None:
    evidence = _provider(_Recorder()).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    answer = evidence.answer("frustration")
    assert answer.value == pytest.approx(1.04)
    assert answer.legend == ("Calm", "Frustrated", "Very angry")
    assert answer.value > 1.0, "1.04 is past the middle label, not a [0, 1] fraction"


def test_a_choice_answer_carries_its_probabilities() -> None:
    evidence = _provider(_Recorder()).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    answer = evidence.answer("department")
    assert answer.value == "billing"
    assert answer.confidence == pytest.approx(0.8)
    assert answer.probabilities["technical"] == pytest.approx(0.13)


def test_the_resolved_version_comes_from_the_response_not_the_alias() -> None:
    """An alias repointed upstream must be visible in the record."""
    evidence = _provider(_Recorder()).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    assert evidence.model_alias == JEV_MODEL_ID
    assert evidence.resolved_model == "jev-1.13.0"
    assert evidence.model_alias != evidence.resolved_model


def test_a_result_wrapped_response_is_accepted() -> None:
    evidence = _provider(_Recorder({"result": DOCUMENTED_RESPONSE})).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    assert evidence.resolved_model == "jev-1.13.0"


def test_the_evidence_is_still_not_authoritative() -> None:
    evidence = _provider(_Recorder()).evaluate(
        state=STATE, questions=QUESTIONS, timeout_s=5.0
    )
    assert evidence.authoritative is False


# ── failure mapping: never a favourable default ─────────────────────────────


@pytest.mark.parametrize(
    "missing", [{"account_id": None}, {"api_token": None}]
)
def test_missing_credentials_refuse_rather_than_answer(monkeypatch, missing) -> None:
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    provider = CloudflareJevProvider(
        question_set_version="v1",
        account_id="acct" if "account_id" not in missing else None,
        api_token="tok" if "api_token" not in missing else None,
        transport=_Recorder(),
    )
    with pytest.raises(DecisionProviderError):
        provider.evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)


def test_an_http_error_becomes_a_provider_error() -> None:
    failure = urllib.error.HTTPError("u", 500, "boom", {}, None)  # type: ignore[arg-type]
    provider = _provider(_Recorder(raises=failure), max_attempts=1)
    with pytest.raises(DecisionProviderError, match="HTTP 500"):
        provider.evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)


def test_a_timeout_becomes_a_provider_error() -> None:
    provider = _provider(_Recorder(raises=TimeoutError("slow")), max_attempts=1)
    with pytest.raises(DecisionProviderError):
        provider.evaluate(state=STATE, questions=QUESTIONS, timeout_s=0.01)


def test_a_missing_answer_is_refused_rather_than_skipped() -> None:
    partial = {"model": "jev-1.13.0", "answers": {"is_urgent": {"type": "noul", "noul": 0.9}}}
    with pytest.raises(DecisionProviderError, match="no answer for question"):
        _provider(_Recorder(partial)).evaluate(
            state=STATE, questions=QUESTIONS, timeout_s=5.0
        )


def test_a_response_without_a_model_version_is_refused() -> None:
    anonymous = {"answers": DOCUMENTED_RESPONSE["answers"]}
    with pytest.raises(DecisionProviderError, match="names no model version"):
        _provider(_Recorder(anonymous)).evaluate(
            state=STATE, questions=QUESTIONS, timeout_s=5.0
        )


def test_an_answer_of_the_wrong_kind_is_refused() -> None:
    swapped = {
        "model": "jev-1.13.0",
        "answers": {
            "is_urgent": {"type": "choice", "choice": "billing"},
            "department": DOCUMENTED_RESPONSE["answers"]["department"],
            "frustration": DOCUMENTED_RESPONSE["answers"]["frustration"],
        },
    }
    with pytest.raises(DecisionProviderError, match="answered"):
        _provider(_Recorder(swapped)).evaluate(
            state=STATE, questions=QUESTIONS, timeout_s=5.0
        )


def test_a_choice_outside_the_declared_options_is_refused() -> None:
    """The provider does not get to invent an option the deployment never declared."""
    invented = {
        "model": "jev-1.13.0",
        "answers": {
            "is_urgent": DOCUMENTED_RESPONSE["answers"]["is_urgent"],
            "department": {"type": "choice", "choice": "legal", "probabilities": {}},
            "frustration": DOCUMENTED_RESPONSE["answers"]["frustration"],
        },
    }
    with pytest.raises(DecisionProviderError, match="not one of the declared options"):
        _provider(_Recorder(invented)).evaluate(
            state=STATE, questions=QUESTIONS, timeout_s=5.0
        )


def test_no_questions_is_an_error_not_an_empty_answer() -> None:
    with pytest.raises(DecisionProviderError):
        _provider(_Recorder()).evaluate(state=STATE, questions=[], timeout_s=5.0)


def test_the_adapter_satisfies_the_protocol() -> None:
    assert isinstance(_provider(_Recorder()), DecisionProvider)
