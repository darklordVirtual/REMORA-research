# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Adapter for the `typesafe/jev` model served through Cloudflare Workers AI.

Reaches the model at ``POST /accounts/{account}/ai/run`` with a body of
``{"model": "typesafe/jev", "input": {"state": ..., "questions": {...}}}``.
Routing through the Cloudflare binding means no separate vendor key: the
account's token and unified billing cover it.

Three shape differences between this API and the contract in
:mod:`remora.decision_providers` are handled here rather than pushed onto
callers, and each one is a place where a quieter adapter would lose
information:

``noul`` answers are probabilities
    The API returns ``{"type": "noul", "noul": 0.95}``. It does not return a
    boolean. This adapter carries the probability through as the answer value;
    thresholding is left to policy, because a 0.51 and a 0.99 must not become
    the same record.

``score`` answers index a legend
    The API returns a value such as ``1.04`` together with a legend naming
    each position. The value is meaningless without the legend, so both travel
    together and neither is normalised away.

the resolved model is in the response
    The response names the concrete version, for example ``jev-1.13.0``, while
    the request names ``typesafe/jev``. Recording only the requested name would
    hide an alias being repointed under a deployment whose thresholds were
    calibrated against the previous version.

Scope (declared, not exhaustive): request construction, response parsing and
failure mapping, exercised against the documented response shape through an
injected transport. **This adapter has not been run against the live
service in this repository**, so nothing here is evidence about the model's
answers, latency or availability. It is evidence about the parsing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Sequence

from remora.decision_providers import (
    DecisionAnswer,
    DecisionEvidence,
    DecisionProviderError,
    DecisionQuestion,
    QuestionKind,
    evidence_fingerprint,
)

__all__ = ["CloudflareJevProvider", "JEV_MODEL_ID"]

#: The Workers AI model identifier. Not a version: the response names that.
JEV_MODEL_ID = "typesafe/jev"

_API_KIND = {
    QuestionKind.BOOLEAN: "noul",
    QuestionKind.CHOICE: "choice",
    QuestionKind.SCORE: "score",
}

#: Status codes Workers AI returns under burst load, worth one retry each.
_RETRYABLE = frozenset({429, 500, 502, 503, 504})

Transport = Callable[[str, bytes, Mapping[str, str], float], Mapping[str, Any]]


def _https_transport(
    url: str, payload: bytes, headers: Mapping[str, str], timeout_s: float
) -> Mapping[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
        url, data=payload, headers=dict(headers), method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        return json.loads(response.read())


class CloudflareJevProvider:
    """A :class:`~remora.decision_providers.DecisionProvider` over Workers AI."""

    provider_name = "cloudflare-workers-ai"

    def __init__(
        self,
        *,
        question_set_version: str,
        account_id: str | None = None,
        api_token: str | None = None,
        model: str = JEV_MODEL_ID,
        max_attempts: int = 3,
        transport: Transport | None = None,
    ) -> None:
        self._question_set_version = question_set_version
        self._account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        self._api_token = api_token or os.environ.get("CLOUDFLARE_API_TOKEN")
        self._model = model
        self._max_attempts = max(1, max_attempts)
        self._transport = transport or _https_transport

    # -- request ----------------------------------------------------------

    def _question_payload(self, question: DecisionQuestion) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": _API_KIND[question.kind],
            "instructions": question.instructions,
        }
        if question.criteria is not None:
            payload["criteria"] = dict(question.criteria)
        elif question.kind is QuestionKind.CHOICE:
            payload["criteria"] = {option: option for option in question.options}
        elif question.kind is QuestionKind.SCORE:
            payload["criteria"] = list(question.legend)
        return payload

    def _body(
        self, state: Mapping[str, Any], questions: Sequence[DecisionQuestion]
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "input": {
                "state": dict(state),
                "questions": {q.id: self._question_payload(q) for q in questions},
            },
        }

    # -- response ---------------------------------------------------------

    @staticmethod
    def _answer(question: DecisionQuestion, raw: Mapping[str, Any]) -> DecisionAnswer:
        kind = raw.get("type")
        expected = _API_KIND[question.kind]
        if kind != expected:
            raise DecisionProviderError(
                f"question {question.id!r} asked for {expected!r} and the provider "
                f"answered {kind!r}"
            )
        probabilities = raw.get("probabilities")
        if kind == "noul":
            if "noul" not in raw:
                raise DecisionProviderError(f"noul answer for {question.id!r} has no value")
            probability = float(raw["noul"])
            return DecisionAnswer(
                question_id=question.id,
                value=probability,
                probabilities={"true": probability, "false": 1.0 - probability},
                confidence=raw.get("confidence"),
            )
        if kind == "choice":
            chosen = raw.get("choice")
            if chosen not in question.options:
                raise DecisionProviderError(
                    f"provider chose {chosen!r} for {question.id!r}, which is not one of "
                    f"the declared options {question.options}"
                )
            return DecisionAnswer(
                question_id=question.id,
                value=chosen,
                probabilities=dict(probabilities) if probabilities else None,
                confidence=raw.get("confidence"),
            )
        if "score" not in raw:
            raise DecisionProviderError(f"score answer for {question.id!r} has no value")
        legend = raw.get("legend")
        if isinstance(legend, Mapping):
            labels = tuple(legend[key] for key in sorted(legend, key=int))
        else:
            labels = question.legend
        return DecisionAnswer(
            question_id=question.id,
            value=float(raw["score"]),
            probabilities=dict(probabilities) if probabilities else None,
            confidence=raw.get("confidence"),
            legend=labels or None,
        )

    # -- the contract -----------------------------------------------------

    def evaluate(
        self,
        *,
        state: Mapping[str, Any],
        questions: Sequence[DecisionQuestion],
        timeout_s: float,
    ) -> DecisionEvidence:
        if not questions:
            raise DecisionProviderError("no questions to evaluate")
        if not self._account_id:
            raise DecisionProviderError(
                "CLOUDFLARE_ACCOUNT_ID is not set; refusing to answer rather than "
                "returning a default"
            )
        if not self._api_token:
            raise DecisionProviderError(
                "CLOUDFLARE_API_TOKEN is not set; refusing to answer rather than "
                "returning a default"
            )

        url = f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/run"
        payload = json.dumps(self._body(state, questions)).encode()
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        document = self._fetch(url, payload, headers, timeout_s)
        latency_ms = (time.perf_counter() - started) * 1000.0

        # Workers AI wraps some responses in {"result": ...}; accept either.
        wrapped = document.get("result")
        body: Mapping[str, Any] = wrapped if isinstance(wrapped, Mapping) else document
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
            answers.append(self._answer(question, raw_answers[question.id]))

        return DecisionEvidence(
            provider=self.provider_name,
            model_alias=self._model,
            resolved_model=str(resolved),
            question_set_version=self._question_set_version,
            state_hash=evidence_fingerprint(state),
            response_hash=evidence_fingerprint(dict(raw_answers)),
            answers=tuple(answers),
            latency_ms=latency_ms,
        )

    def _fetch(
        self, url: str, payload: bytes, headers: Mapping[str, str], timeout_s: float
    ) -> Mapping[str, Any]:
        last: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                return self._transport(url, payload, headers, timeout_s)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in _RETRYABLE and attempt < self._max_attempts - 1:
                    time.sleep(2**attempt)
                    continue
                raise DecisionProviderError(
                    f"Workers AI returned HTTP {exc.code}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last = exc
                if attempt < self._max_attempts - 1:
                    time.sleep(2**attempt)
                    continue
                raise DecisionProviderError(f"Workers AI request failed: {exc}") from exc
        raise DecisionProviderError(f"Workers AI request failed: {last}")
