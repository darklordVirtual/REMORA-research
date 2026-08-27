# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Generic HTTP read-back verifier for property G (effect verification).

The verification contract and its five-status vocabulary live in
``remora.governance.effect_verification``. Until now the only concrete
reader was the GitHub issue reader, and every other deployment had to write
its own before the loop against a live system of record could close.

This module is the generic reader: GET the object the postcondition names,
hand what came back to ``verify_declared_delta``, and let the contract
decide. It adds no comparison logic of its own. What it adds is the honest
mapping from transport outcomes to observation outcomes:

* 200 with a JSON object   -> observed, compare against the declared delta
* 404                      -> ``None``: the object is absent, which is
                              EFFECT_UNOBSERVABLE, never a mismatch
* anything else, or a
  network failure          -> ``ReadBackFailed``: the verifier failed, which
                              is a different fact from either of the above

The verifier holds no credential of its own. A deployment that needs one
passes ``headers``; the value is used and not stored.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Mapping

from remora.governance.effect_verification import (
    EffectStatus,
    EffectVerification,
    PostconditionContract,
    verify_declared_delta,
)

__all__ = ["ReadBackFailed", "http_read_back", "verify_http_effect"]

VERIFIER_IDENTITY = "remora.integrations.http_readback"


class ReadBackFailed(RuntimeError):
    """The read-back could not be performed. Not evidence about the world."""


def http_read_back(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any] | None:
    """GET ``url``; a JSON object, ``None`` for 404, ``ReadBackFailed`` otherwise."""
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", **dict(headers or {})}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ReadBackFailed(f"read-back of {url} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReadBackFailed(f"read-back of {url} failed: {exc}") from exc
    try:
        observed = json.loads(body)
    except ValueError as exc:
        raise ReadBackFailed(f"read-back of {url} was not JSON") from exc
    if not isinstance(observed, dict):
        raise ReadBackFailed(f"read-back of {url} was not a JSON object")
    return observed


def verify_http_effect(
    contract: PostconditionContract,
    url: str,
    *,
    proposal_id: str,
    execution_id: str,
    toolspec_hash: str,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    now: datetime | None = None,
) -> EffectVerification:
    """Read the object at ``url`` and verify it against ``contract``.

    A failed read-back is recorded as EFFECT_VERIFIER_FAILED with the reason,
    rather than raised: the caller asked for a verification record, and
    "the verifier could not look" is a record, not an exception.
    """
    deadline = (
        timeout_seconds
        if timeout_seconds is not None
        else float(contract.observation_deadline_seconds)
    )
    try:
        observed = http_read_back(url, headers=headers, timeout_seconds=deadline)
    except ReadBackFailed as exc:
        return EffectVerification.build(
            proposal_id=proposal_id,
            execution_id=execution_id,
            tool_id=contract.tool_id,
            toolspec_hash=toolspec_hash,
            status=EffectStatus.VERIFIER_FAILED,
            reason_code="read_back_failed",
            verifier_identity=VERIFIER_IDENTITY,
            expected=contract.expected_fields,
            observed={},
            detail=str(exc),
            now=now,
        )
    return verify_declared_delta(
        contract,
        observed,
        proposal_id=proposal_id,
        execution_id=execution_id,
        toolspec_hash=toolspec_hash,
        verifier_identity=VERIFIER_IDENTITY,
        now=now,
    )
