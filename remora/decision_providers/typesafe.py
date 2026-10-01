# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Adapter for Jev called directly on TypeSafe's own API.

Reaches the model at ``POST https://api.typesafe.ai/v1/systemone`` with a body
of ``{"model": "jev-latest", "state": ..., "questions": {...}}`` and a bearer
key from the TypeSafe console. This is the route to use when the key is a
TypeSafe key rather than a Cloudflare token: no AI Gateway, no credits on the
Cloudflare account, and none of the 402/403 prerequisites recorded in
:mod:`remora.decision_providers.cloudflare`.

The key is read from ``JEV_API_KEY``, the name the repository's GitHub Agents
secret uses, and falls back to ``TYPESAFE_API_KEY``, the name TypeSafe's own
documentation uses.

The question and answer shapes are the same as on Workers AI, so both adapters
share :func:`~remora.decision_providers.cloudflare.question_payload` and
:func:`~remora.decision_providers.cloudflare.parse_answer`. A ``noul`` answer
stays a probability, a ``score`` keeps its legend, and the resolved model
version comes from the response rather than from the alias in the request.

Scope (declared, not exhaustive): request construction, response parsing and
failure mapping, exercised against the documented shapes through an injected
transport. Nothing here is evidence about the model's answers, latency or
availability.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
from typing import Any, Mapping, Sequence

from remora.decision_providers import (
    DecisionEvidence,
    DecisionProviderError,
    DecisionQuestion,
    evidence_fingerprint,
)
from remora.decision_providers.cloudflare import (
    Transport,
    _https_transport,
    _input_tokens,
    parse_answer,
    question_payload,
)

__all__ = ["TYPESAFE_BASE_URL", "TYPESAFE_MODEL_ALIAS", "TypeSafeJevProvider"]

TYPESAFE_BASE_URL = "https://api.typesafe.ai"

#: The alias TypeSafe documents. Not a version: the response names that.
TYPESAFE_MODEL_ALIAS = "jev-latest"

#: 429 is rate limiting and 529 is TypeSafe's "overloaded"; both are worth a
#: retry, as are the usual gateway errors.
_RETRYABLE = frozenset({429, 500, 502, 503, 504, 529})

#: Upper bound on an honoured ``retry-after``, so a hostile or confused header
#: cannot park a decision for minutes.
_MAX_RETRY_AFTER_S = 10.0


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """TypeSafe's own error text and request id, which is what support asks for."""
    request_id = exc.headers.get("x-typesafe-request-id") if exc.headers else None
    try:
        body = json.loads(exc.read())
    except (ValueError, OSError):
        body = None
    message = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("type")
        elif isinstance(error, str):
            message = error
        message = message or body.get("message") or body.get("detail")
    if not isinstance(message, str):
        message = json.dumps(message) if message is not None else None
    detail = message or (exc.reason if isinstance(exc.reason, str) else "no detail")
    return f"{detail} (request id {request_id})" if request_id else detail


def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
    header = exc.headers.get("retry-after") if exc.headers else None
    try:
        return min(max(float(header), 0.0), _MAX_RETRY_AFTER_S)
    except (TypeError, ValueError):
        return float(2**attempt)


class TypeSafeJevProvider:
    """A :class:`~remora.decision_providers.DecisionProvider` over TypeSafe's API."""

    provider_name = "typesafe"

    def __init__(
        self,
        *,
        question_set_version: str,
        api_key: str | None = None,
        model: str = TYPESAFE_MODEL_ALIAS,
        base_url: str = TYPESAFE_BASE_URL,
        max_attempts: int = 3,
        transport: Transport | None = None,
    ) -> None:
        self._question_set_version = question_set_version
        self._api_key = (
            api_key or os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
        )
        self._model = model
        self._url = base_url.rstrip("/") + "/v1/systemone"
        self._max_attempts = max(1, max_attempts)
        self._transport = transport or _https_transport

    def _body(
        self, state: Mapping[str, Any], questions: Sequence[DecisionQuestion]
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "state": dict(state),
            "questions": {q.id: question_payload(q) for q in questions},
        }

    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Sequence[DecisionQuestion],
        timeout_s: float,
    ) -> DecisionEvidence:
        if not questions:
            raise DecisionProviderError("no questions to evaluate")
        if not self._api_key:
            raise DecisionProviderError(
                "neither JEV_API_KEY nor TYPESAFE_API_KEY is set; refusing to answer "
                "rather than returning a default"
            )

        payload = json.dumps(self._body(state, questions)).encode()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        body = self._fetch(payload, headers, timeout_s)
        latency_ms = (time.perf_counter() - started) * 1000.0

        resolved = body.get("model")
        if not resolved:
            raise DecisionProviderError(
                "the response names no model version, so the answers cannot be bound to "
                "the model that produced them"
            )
        raw_answers = body.get("answers")
        if not isinstance(raw_answers, Mapping):
            raise DecisionProviderError("the response carries no answers object")

        answers = []
        for question in questions:
            if question.id not in raw_answers:
                raise DecisionProviderError(f"no answer for question {question.id!r}")
            answers.append(parse_answer(question, raw_answers[question.id]))

        return DecisionEvidence(
            provider=self.provider_name,
            model_alias=self._model,
            resolved_model=str(resolved),
            question_set_version=self._question_set_version,
            state_hash=evidence_fingerprint(state),
            response_hash=evidence_fingerprint(dict(raw_answers)),
            answers=tuple(answers),
            latency_ms=latency_ms,
            input_tokens=_input_tokens(body),
        )

    def _fetch(
        self, payload: bytes, headers: Mapping[str, str], timeout_s: float
    ) -> Mapping[str, Any]:
        last: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                document = self._transport(self._url, payload, headers, timeout_s)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in _RETRYABLE and attempt < self._max_attempts - 1:
                    time.sleep(_retry_after(exc, attempt))
                    continue
                raise DecisionProviderError(
                    f"TypeSafe returned HTTP {exc.code}: {_error_detail(exc)}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last = exc
                if attempt < self._max_attempts - 1:
                    time.sleep(2**attempt)
                    continue
                raise DecisionProviderError(f"TypeSafe request failed: {exc}") from exc
            if not isinstance(document, Mapping):
                raise DecisionProviderError("the response is not a JSON object")
            return document
        raise DecisionProviderError(f"TypeSafe request failed: {last}")
