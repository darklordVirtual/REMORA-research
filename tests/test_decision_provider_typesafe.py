# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The direct TypeSafe adapter, against the documented request and response shapes.

No network. A transport is injected, so what these tests establish is the
request construction, the parsing and the failure mapping, not the model's
behaviour. The answer parsing is shared with the Workers AI adapter and is
covered in depth in ``tests/test_decision_provider_cloudflare.py``; here it is
checked only far enough to show the shared parser is the one in use.

Scope (declared, not exhaustive): nothing here is evidence about the model's
answers, its latency or its availability.
"""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message

import pytest

from remora.decision_providers import DecisionProvider, DecisionProviderError
from remora.decision_providers.typesafe import TYPESAFE_MODEL_ALIAS, TypeSafeJevProvider
from tests.test_decision_provider_cloudflare import DOCUMENTED_RESPONSE, QUESTIONS, STATE


class _Recorder:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [DOCUMENTED_RESPONSE]
        self.calls: list[tuple[str, dict, dict, float]] = []

    def __call__(self, url, payload, headers, timeout_s):
        self.calls.append((url, json.loads(payload), dict(headers), timeout_s))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _http_error(code: int, body: dict | None = None, **headers: str) -> urllib.error.HTTPError:
    message = Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    raw = json.dumps(body).encode() if body is not None else b""
    return urllib.error.HTTPError("https://api.typesafe.ai", code, "err", message, io.BytesIO(raw))


def _provider(transport, **kw) -> TypeSafeJevProvider:
    kw.setdefault("api_key", "ts-key")
    return TypeSafeJevProvider(question_set_version="support-triage-v1", transport=transport, **kw)


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("remora.decision_providers.typesafe.time.sleep", lambda _s: None)


def test_it_satisfies_the_provider_protocol() -> None:
    assert isinstance(_provider(_Recorder()), DecisionProvider)


def test_the_request_matches_the_documented_endpoint_and_body() -> None:
    recorder = _Recorder()
    _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    url, body, headers, timeout_s = recorder.calls[0]

    assert url == "https://api.typesafe.ai/v1/systemone"
    assert headers["Authorization"] == "Bearer ts-key"
    assert body["model"] == TYPESAFE_MODEL_ALIAS == "jev-latest"
    assert body["state"] == STATE
    assert "input" not in body, "the Workers AI wrapper does not belong on this API"
    assert body["questions"]["is_urgent"]["type"] == "noul"
    assert body["questions"]["frustration"]["criteria"] == ["Calm", "Frustrated", "Very angry"]
    assert timeout_s == 5.0
    assert len(recorder.calls) == 1


def test_the_key_comes_from_jev_api_key_first(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "fallback")
    monkeypatch.setenv("JEV_API_KEY", "from-agents-secret")
    recorder = _Recorder()
    _provider(recorder, api_key=None).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert recorder.calls[0][2]["Authorization"] == "Bearer from-agents-secret"


def test_typesafe_api_key_is_the_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "fallback")
    recorder = _Recorder()
    _provider(recorder, api_key=None).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert recorder.calls[0][2]["Authorization"] == "Bearer fallback"


def test_no_key_is_a_refusal_not_a_default() -> None:
    recorder = _Recorder()
    with pytest.raises(DecisionProviderError, match="JEV_API_KEY"):
        _provider(recorder, api_key=None).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert recorder.calls == []


def test_the_shared_parser_keeps_probability_legend_and_resolved_model() -> None:
    evidence = _provider(_Recorder()).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert evidence.provider == "typesafe"
    assert evidence.model_alias == "jev-latest"
    assert evidence.resolved_model == "jev-1.13.0"
    assert evidence.answer("is_urgent").value == pytest.approx(0.95)
    assert evidence.answer("frustration").legend == ("Calm", "Frustrated", "Very angry")
    assert evidence.answer("department").value == "billing"
    assert evidence.input_tokens == 426


def test_a_response_without_a_model_version_is_refused() -> None:
    document = {k: v for k, v in DOCUMENTED_RESPONSE.items() if k != "model"}
    with pytest.raises(DecisionProviderError, match="no model version"):
        _provider(_Recorder(document)).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)


def test_a_missing_answer_is_refused() -> None:
    answers = {k: v for k, v in DOCUMENTED_RESPONSE["answers"].items() if k != "department"}
    document = {**DOCUMENTED_RESPONSE, "answers": answers}
    with pytest.raises(DecisionProviderError, match="department"):
        _provider(_Recorder(document)).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)


def test_401_is_refused_at_once_with_typesafe_detail_and_request_id() -> None:
    recorder = _Recorder(
        _http_error(401, {"error": {"message": "invalid api key"}}, x_typesafe_request_id="req-9")
    )
    with pytest.raises(DecisionProviderError) as caught:
        _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert "HTTP 401" in str(caught.value)
    assert "invalid api key" in str(caught.value)
    assert "req-9" in str(caught.value)
    assert len(recorder.calls) == 1


@pytest.mark.parametrize("code", [429, 529, 503])
def test_rate_limit_and_overload_are_retried_then_succeed(code: int) -> None:
    recorder = _Recorder(_http_error(code, retry_after="1"), DOCUMENTED_RESPONSE)
    evidence = _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert evidence.resolved_model == "jev-1.13.0"
    assert len(recorder.calls) == 2


def test_persistent_overload_becomes_a_refusal() -> None:
    recorder = _Recorder(_http_error(529))
    with pytest.raises(DecisionProviderError, match="HTTP 529"):
        _provider(recorder, max_attempts=3).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert len(recorder.calls) == 3


def test_retry_after_is_bounded(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("remora.decision_providers.typesafe.time.sleep", slept.append)
    recorder = _Recorder(_http_error(429, retry_after="3600"), DOCUMENTED_RESPONSE)
    _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
    assert slept == [10.0]


def test_a_network_failure_becomes_a_refusal() -> None:
    recorder = _Recorder(urllib.error.URLError("dns"))
    with pytest.raises(DecisionProviderError, match="TypeSafe request failed"):
        _provider(recorder).evaluate(state=STATE, questions=QUESTIONS, timeout_s=5.0)
