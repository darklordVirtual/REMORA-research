# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Dispatch across the authority/execution trust boundary (ADR-A).

The custody split needs the lease to cross a process boundary, because that is
the only way one side can hold a private key the other does not. This module is
that crossing: the authority domain mints a lease and hands it, with the call it
authorises, to the execution domain.

    AUTHORITY                                 EXECUTION
    holds Ed25519 PRIVATE key                 holds PUBLIC key only
    runs the PDP                              holds downstream credentials
    holds NO downstream credential            runs GovernedToolDispatcher
            │                                          ▲
            └── POST (lease, call, context) ───────────┘

Why this direction
------------------
The authority calls the executor, not the reverse. If the executor could ask
the authority to sign something, the split would be cosmetic -- a compromised
executor would simply request the lease it wanted. Here the executor receives a
lease it had no part in requesting, and the authority never receives a request
to sign anything: it decides, then signs what IT decided.

What the executor must still do
-------------------------------
Verify. A lease is not authorisation because it arrived over a trusted
transport; ``GovernedToolDispatcher.dispatch`` re-checks the entire binding
against the concrete call, so an authority-signed lease for a different
argument, tenant or target is refused on the execution side exactly as a
forgery is. The transport is not part of the security argument.

Failure posture
---------------
Every failure to reach the executor, or to understand its answer, is reported
as a REFUSAL with a named reason -- never as an execution that may have
happened. The one case that cannot be reported as a clean refusal is a request
that was sent and whose response was lost: the effect may have occurred and the
nonce is spent. That is reported as unknown state, because it is, and because
the alternative is a caller that retries a side effect it already caused.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

__all__ = [
    "ENDPOINT_ENV",
    "TOKEN_ENV",
    "TIMEOUT_ENV",
    "RemoteDispatchUnavailable",
    "execution_endpoint",
    "remote_dispatch",
]

#: Set on the AUTHORITY domain, pointing at the execution domain. Absent means
#: this deployment has not split custody, and dispatch stays local.
ENDPOINT_ENV = "REMORA_EXECUTION_ENDPOINT"

#: Shared bearer for the internal hop. NOT an authority credential: it
#: authenticates the transport, and holding it lets a caller ask the executor
#: to dispatch a lease -- which the executor will still refuse unless the lease
#: verifies against the public key and matches the call. Compromise of this
#: token does not permit forging authority.
TOKEN_ENV = "REMORA_EXECUTION_TOKEN"

TIMEOUT_ENV = "REMORA_EXECUTION_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT = 120.0


class RemoteDispatchUnavailable(RuntimeError):
    """The execution domain could not be reached, or its answer was unusable.

    Distinct from a refusal by the executor, which arrives as a normal result
    with a refusal_reason. This is "no verdict", and it fails closed.
    """


def execution_endpoint() -> str:
    return os.environ.get(ENDPOINT_ENV, "").strip()


def _timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_TIMEOUT
    except ValueError:
        return _DEFAULT_TIMEOUT
    return value if value > 0 else _DEFAULT_TIMEOUT


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Seam for tests. Replaced wholesale rather than mocked piecemeal."""
    headers = {"Content-Type": "application/json",
               "User-Agent": "remora-authority/1"}
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers,
        method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else {}


def remote_dispatch(
    *,
    lease: Any,
    tenant: str,
    principal: str,
    tool_call: Any,
    now: str,
) -> dict[str, Any]:
    """Hand a minted lease to the execution domain and return its outcome.

    The return value is the executor's ``tool_execution`` dict, unchanged, so
    callers cannot tell a local dispatch from a remote one -- which is the
    point: the audit record says what happened, not which topology produced it.
    """
    url = execution_endpoint()
    if not url:
        raise RemoteDispatchUnavailable(
            f"{ENDPOINT_ENV} is not set; there is no execution domain to "
            "dispatch to")

    payload = {
        "lease": lease.to_dict(),
        "tenant_id": tenant,
        "actor_identity": principal,
        "now": now,
        "tool_call": {
            "tool_name": tool_call.tool_name,
            "arguments": tool_call.arguments,
            "target_environment": tool_call.target_environment,
        },
    }

    try:
        answer = _post(url.rstrip("/") + "/v1/execution/dispatch-leased",
                       payload, _timeout())
    except urllib.error.HTTPError as exc:
        # The executor answered, and refused. A 4xx here is its verdict on the
        # lease or the call, so it is reported as a refusal rather than as an
        # outage -- an operator reading the audit chain needs to know which.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001 - best effort on an error path
            detail = ""
        if 400 <= exc.code < 500:
            return {"executed": False,
                    "refusal_reason": "execution_domain_refused",
                    "error": f"HTTP {exc.code}: {detail}"}
        raise RemoteDispatchUnavailable(
            f"execution domain returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Never reached, or reached and the answer lost. Both are unknown
        # state: the nonce may be spent and the effect may have happened.
        raise RemoteDispatchUnavailable(
            f"execution domain unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RemoteDispatchUnavailable(
            f"execution domain returned an unparseable answer: {exc}") from exc

    execution = answer.get("tool_execution")
    if not isinstance(execution, dict):
        raise RemoteDispatchUnavailable(
            "execution domain answered without a tool_execution object; "
            "refusing to infer whether the effect happened")
    return execution
