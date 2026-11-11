# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Assemble the packet a human approver reads, then record their decision.

REMORA stops a write that passes a cumulative limit's second tier and holds a
review item for a person. Its review-packet endpoint
(``GET /v1/execution/proposals/{id}/review-packet``) returns the basis REMORA
computed: the tool, the decision and its reasons, how the intent resolved, and
the ``dual_control`` block naming the limits and the number of approvers.
REMORA governs by labels and hashes and does not retain the raw arguments, so
it cannot show the operator the request body.

This console joins the two sides. The deployment holds the proposed call (the
exact arguments the agent sent) and the work order's prior accepted writes;
REMORA holds why the call stopped and which bound it crossed. Before it shows
the operator anything, :func:`assemble_packet` recomputes the call's hash and
refuses to assemble when it does not bind to the hash REMORA recorded, so an
operator can never approve a basis built over a different call than the one
REMORA stopped. The operator, or a scripted policy in a demonstration, then
approves or declines, and the console calls ``/approve`` or ``/reject`` with
the operator's own credential (never a role from a body: SR-06).

As a library it takes ``get``/``post`` callables, so a test can drive it with
an in-process client and a deployment can drive it over HTTP. The ``main`` CLI
wires the HTTP client and is for a human operator at the pilot.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from typing import Any

# Package-relative when imported as deploy.ot-pilot is not importable (the dash
# in the path); the pilot runs these scripts with the directory on sys.path, so
# a flat import works, and the repository import works under pytest.
try:
    from remora.policy.observation import canonical_tool_call_hash
except ModuleNotFoundError:  # pragma: no cover - only when run outside the repo
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    from remora.policy.observation import canonical_tool_call_hash

#: Decisions the packet can carry back. APPROVE routes to ``/approve`` (twice
#: when the tier needs two distinct approvers); DECLINE routes to ``/reject``.
APPROVE = "approve"
DECLINE = "decline"


class BindingMismatch(Exception):
    """The call shown to the operator does not bind to the one REMORA stopped.

    Raised before any decision is possible, so a swapped-argument call can
    never reach an approve or a reject under a basis REMORA assembled for a
    different call.
    """


def recompute_tool_call_hash(tenant: str, proposed_call: dict[str, Any]) -> str:
    """The hash REMORA would have bound this call to, recomputed independently.

    Covers the same tuple REMORA covers: name, full arguments, tenant and the
    target environment the call declared. A deployment that pins a riskier
    target server-side would move the hash; the console compares what it can
    see and reports a mismatch rather than hiding it.
    """
    return canonical_tool_call_hash(
        name=proposed_call["tool_name"],
        arguments=proposed_call.get("arguments", {}),
        tenant=tenant,
        target=proposed_call.get("target_environment") or "",
    )


def assemble_packet(
    *,
    tenant: str,
    basis: dict[str, Any],
    proposed_call: dict[str, Any],
    log_so_far: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Join REMORA's decision basis with the deployment's request body.

    ``basis`` is the review-packet JSON. ``proposed_call`` is the exact call
    the operator is asked to approve (``tool_name``, ``arguments``,
    ``target_environment`` and ``intent_ref``). ``log_so_far`` is the work
    order's prior accepted writes the deployment holds, oldest first.

    Raises :class:`BindingMismatch` when the call does not bind to the hash
    REMORA recorded.
    """
    remora_hash = str(basis.get("tool_call_hash") or "")
    recomputed = recompute_tool_call_hash(tenant, proposed_call)
    if not remora_hash or remora_hash != recomputed:
        raise BindingMismatch(
            "the call shown to the approver does not bind to the one REMORA "
            f"stopped: REMORA {remora_hash[:16] or '(none)'}, "
            f"recomputed {recomputed[:16]}"
        )
    return {
        "proposal_id": basis.get("proposal_id"),
        "review_item_id": basis.get("review_item_id"),
        "tool_call_hash": remora_hash,
        "binds": True,
        # What the agent proposes: the human-readable request the deployment
        # holds and REMORA does not.
        "request": {
            "tool_name": proposed_call["tool_name"],
            "arguments": proposed_call.get("arguments", {}),
            "target_environment": proposed_call.get("target_environment"),
            "intent_ref": proposed_call.get("intent_ref"),
        },
        # Why REMORA stopped it, from REMORA.
        "why_stopped": {
            "decision": basis.get("decision"),
            "reasons": basis.get("reasons", []),
            "intent": basis.get("intent", {}),
        },
        # The second tier(s) the write passed and how many approvers it needs.
        "would_pass": basis.get("dual_control"),
        # The work order's own trajectory so far, so the operator sees where
        # this call would take it, not just the call alone.
        "log_so_far": list(log_so_far),
    }


def render_text(packet: dict[str, Any]) -> str:
    """A plain-text rendering of the packet for a human operator."""
    req = packet["request"]
    dc = packet.get("would_pass") or {}
    lines = [
        f"proposal   {packet['proposal_id']}",
        f"review id  {packet['review_item_id']}",
        f"request    {req['tool_name']}  {json.dumps(req['arguments'], sort_keys=True)}",
        f"intent     {req.get('intent_ref')}",
        f"stopped    {packet['why_stopped']['decision']}: "
        f"{', '.join(packet['why_stopped']['reasons'])}",
    ]
    if dc:
        lines.append(
            f"tier       limits {', '.join(dc.get('limits', []))}; "
            f"{dc.get('approvals_required', 1)} approver(s) required"
        )
    if packet["log_so_far"]:
        lines.append("log so far:")
        for prior in packet["log_so_far"]:
            lines.append(
                f"  - {prior.get('tool_name')}  "
                f"{json.dumps(prior.get('arguments', {}), sort_keys=True)}"
            )
    lines.append(f"binds      {packet['binds']}")
    return "\n".join(lines)


def decide(packet: dict[str, Any], policy: Callable[[dict[str, Any]], bool]) -> str:
    """APPROVE or DECLINE for *packet*, from a policy the operator supplies.

    The policy reads the assembled packet and returns True to approve. For a
    human operator the CLI prompts instead; for a demonstration a scripted
    policy stands in for the human's judgment.
    """
    return APPROVE if policy(packet) else DECLINE


class ApproverConsole:
    """Drives the governed surface for one approver, over injectable transport.

    ``get(path, token)`` and ``post(path, token, body)`` return
    ``(status, json)``. The console holds no token of its own: the operator's
    credential is passed per call, so a console process cannot approve on its
    own authority.
    """

    def __init__(
        self,
        get: Callable[[str, str], tuple[int, dict[str, Any]]],
        post: Callable[[str, str, dict[str, Any]], tuple[int, dict[str, Any]]],
        *,
        tenant: str,
    ) -> None:
        self._get = get
        self._post = post
        self._tenant = tenant

    def review_packet(self, proposal_id: str, token: str) -> dict[str, Any]:
        status, body = self._get(
            f"/v1/execution/proposals/{proposal_id}/review-packet", token
        )
        if status != 200:
            raise RuntimeError(f"review-packet {proposal_id}: HTTP {status} {body}")
        return body

    def present(
        self,
        proposal_id: str,
        proposed_call: dict[str, Any],
        token: str,
        *,
        log_so_far: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """Fetch the basis and assemble the operator-facing packet."""
        basis = self.review_packet(proposal_id, token)
        return assemble_packet(
            tenant=self._tenant, basis=basis,
            proposed_call=proposed_call, log_so_far=log_so_far,
        )

    def approve(
        self, item_id: str, approvers: Sequence[str], *, ttl_seconds: int = 600
    ) -> list[tuple[int, dict[str, Any]]]:
        """Record approval under each approver's own credential, in turn.

        ``approvers`` is one token per distinct approver. A second tier needs
        two; the queue refuses a second approval from the same principal, so
        the operator supplies two real credentials, not one used twice.
        """
        results = []
        for token in approvers:
            results.append(self._post(
                "/v1/execution/approve", token,
                {"item_id": item_id, "approval_ttl_seconds": ttl_seconds},
            ))
        return results

    def reject(self, item_id: str, token: str, reason: str) -> tuple[int, dict[str, Any]]:
        return self._post(
            "/v1/execution/reject", token, {"item_id": item_id, "reason": reason}
        )


def _http_transport(base: str):
    """urllib get/post returning ``(status, json)``, for the CLI."""
    def _request(method: str, path: str, token: str, body: dict | None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed base
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def get(path: str, token: str):
        return _request("GET", path, token, None)

    def post(path: str, token: str, body: dict):
        return _request("POST", path, token, body)

    return get, post


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("proposal_id")
    parser.add_argument("--base", default=os.environ.get("OT_PILOT_BASE", "http://127.0.0.1:8080"))
    parser.add_argument("--tenant", default=os.environ.get("OT_TENANT", "ot-pilot"))
    parser.add_argument("--call", required=True,
                        help="JSON of the proposed tool call the operator is approving")
    parser.add_argument("--item-id", help="review item id (for --approve/--reject)")
    parser.add_argument("--approver-token", action="append", default=[],
                        help="an approver credential; repeat for a second approver")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--reject", metavar="REASON")
    args = parser.parse_args(argv)

    get, post = _http_transport(args.base)
    console = ApproverConsole(get, post, tenant=args.tenant)
    proposed_call = json.loads(args.call)
    token = args.approver_token[0] if args.approver_token else os.environ.get("OT_TOKEN_APPROVER", "")

    packet = console.present(args.proposal_id, proposed_call, token)
    print(render_text(packet))

    item_id = args.item_id or packet["review_item_id"]
    if args.approve:
        if not item_id:
            print("no review item id to approve", file=sys.stderr)
            return 2
        for status, body in console.approve(item_id, args.approver_token or [token]):
            print(f"approve: HTTP {status} {json.dumps(body)}")
    elif args.reject is not None:
        status, body = console.reject(item_id, token, args.reject)
        print(f"reject: HTTP {status} {json.dumps(body)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
