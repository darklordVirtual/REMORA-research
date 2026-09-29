# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The tool worker's side of the effect domain (NTA-2 phase 3).

In a three-domain deployment the executor holds no effect credential, so its
mediator's executors are these: each forwards the request, with the lease and
the lease-bound capability set, to the effect domain and returns what it
answered. The effect domain decides; the worker's own mediator is a first
check that saves a round trip, never the only one.

A refusal from the domain becomes ``EffectRefused``, which the mediator records
as REFUSED. A transport failure raises, and the mediator records UNKNOWN: the
request may have reached the domain and run.
"""
from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from remora.capabilities.model import EffectiveCapabilitySet
from remora.enforcement.capability_mediator import EffectRefused
from remora.enforcement.lease import ExecutionLease

__all__ = ["EFFECTS_CLOSE_PATH", "EFFECTS_PATH", "EffectDomainUnavailable",
           "RemoteEffectClient", "http_post"]

EFFECTS_PATH = "/v1/execution/effects"
EFFECTS_CLOSE_PATH = "/v1/execution/effects/close"

Post = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class EffectDomainUnavailable(RuntimeError):
    """The effect domain did not answer; the effect's state is unknown."""


def http_post(endpoint: str, *, token: str = "", timeout: float = 30.0) -> Post:
    """A ``Post`` over HTTP(S) to the effect domain at ``endpoint``."""
    if not endpoint.startswith(("http://", "https://")):
        raise ValueError("the effect endpoint must be http(s)")

    def post(path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        # http(s) only: the scheme was checked above, so S310's file: concern
        # cannot arise.
        request = urllib.request.Request(  # noqa: S310
            endpoint.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "remora-executor/1",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return dict(json.loads(response.read().decode()))
        except Exception as exc:  # noqa: BLE001 - unknown state, not a refusal
            raise EffectDomainUnavailable(str(exc)) from exc

    return post


def http_post_from_env() -> Post:
    """The configured effect domain: ``REMORA_EFFECT_ENDPOINT`` and its
    transport bearer ``REMORA_EFFECT_TOKEN`` (not an authority credential)."""
    return http_post(os.environ.get("REMORA_EFFECT_ENDPOINT", "").strip(),
                     token=os.environ.get("REMORA_EFFECT_TOKEN", "").strip())


class RemoteEffectClient:
    def __init__(self, *, post: Post) -> None:
        self._post = post

    def executors_for(self, lease: ExecutionLease, capability_set: EffectiveCapabilitySet,
                      capabilities: Iterable[str]) -> dict[str, Callable[..., Any]]:
        """One forwarding executor per capability the worker's mediator may try."""
        wire_lease, wire_set = lease.to_dict(), capability_set.to_dict()

        def forward(capability: str) -> Callable[[str, Mapping[str, Any]], Any]:
            def run(resource: str, arguments: Mapping[str, Any]) -> Any:
                answer = self._post(EFFECTS_PATH, {
                    "lease": wire_lease, "capability_set": wire_set,
                    "capability": capability, "resource": resource,
                    "arguments": dict(arguments)})
                state = answer.get("state")
                if state == "EXECUTED":
                    return answer.get("result")
                if state == "REFUSED":
                    raise EffectRefused(str(answer.get("refusal") or "effect_domain_refused"))
                raise EffectDomainUnavailable(f"effect domain answered state {state!r}")
            return run

        return {c: forward(c) for c in capabilities}

    def close(self, lease: ExecutionLease) -> None:
        """End the execution in the effect domain. Best effort: a close that
        does not arrive leaves the execution to expire with its authority."""
        self._post(EFFECTS_CLOSE_PATH, {"lease": lease.to_dict()})
