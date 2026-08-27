# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The execution domain, in its own process, holding the effect credential.

This is the half of ADR-A that the single-process bypass suite cannot
demonstrate. This process holds two things the agent process does not: the
credential that reaches the protected effect, and the tool callable that
closes over it. It holds one thing less: the Ed25519 private seed. It can
verify a lease and it cannot mint one, which is what makes the custody split
more than a naming convention.

The dispatch endpoint takes a serialised lease and re-verifies the whole
binding against the concrete call before the callable is reached. A lease
that arrived over a trusted channel is not authorisation.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.enforcement.nonce_store import DurableNonceStore

EFFECT_URL_ENV = "CONFORMANCE_EFFECT_URL"
EFFECT_TOKEN_ENV = "CONFORMANCE_EFFECT_TOKEN"
BUNDLE_ENV = "CONFORMANCE_POLICY_BUNDLE_HASH"

_DISPATCHER: GovernedToolDispatcher | None = None


def _send_mail(arguments: object) -> dict:
    """The governed tool. The credential lives here and nowhere else."""
    args = arguments if isinstance(arguments, dict) else {}
    token = os.environ[EFFECT_TOKEN_ENV]
    body = json.dumps({"to": args.get("to", "")}).encode("utf-8")
    request = urllib.request.Request(
        os.environ[EFFECT_URL_ENV] + "/send",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/whoami":
            # Lets the test assert what this process can and cannot do,
            # rather than assuming it from how it was started.
            self._json(
                200,
                {
                    "holds_effect_credential": bool(
                        os.environ.get(EFFECT_TOKEN_ENV, "").strip()
                    ),
                    "holds_lease_private_key": bool(
                        os.environ.get(
                            "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", ""
                        ).strip()
                    ),
                    "holds_lease_public_key": bool(
                        os.environ.get(
                            "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", ""
                        ).strip()
                    ),
                    # Asserted by the test rather than assumed from how the
                    # process was started: the distributed single-use claim
                    # is only as good as the store actually in use.
                    "nonce_store": (
                        "durable"
                        if (os.environ.get("REMORA_PG_DSN", "").strip()
                            or os.environ.get("REMORA_CHAIN_DB", "").strip())
                        else "in_process"
                    ),
                },
            )
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/dispatch":
            self._json(404, {"error": "not_found"})
            return
        assert _DISPATCHER is not None
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            lease = ExecutionLease.from_dict(payload["lease"])
        except Exception as exc:
            self._json(400, {"executed": False, "refusal_reason": f"bad_lease: {exc}"})
            return
        result = _DISPATCHER.dispatch(
            lease,
            payload["tool_name"],
            payload["arguments"],
            tenant_id=payload.get("tenant_id", ""),
            target_environment=payload.get("target_environment"),
            actor_identity=payload.get("actor_identity"),
        )
        self._json(
            200,
            {
                "executed": bool(result.executed),
                "refusal_reason": result.refusal_reason or "",
            },
        )


def main() -> int:
    global _DISPATCHER
    if os.environ.get("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", "").strip():
        # Refusing here is the point: an execution domain that can sign has
        # not split custody, it has renamed it.
        print("executor refuses to hold the lease signing key", file=sys.stderr)
        return 2
    if not os.environ.get(EFFECT_TOKEN_ENV, "").strip():
        print("executor requires the effect credential", file=sys.stderr)
        return 2
    # Same variable the real server reads (servers/execution_api.py,
    # _lease_nonce_store), so this fixture cannot claim a durability the
    # deployment path does not have.
    dsn = os.environ.get("REMORA_PG_DSN", "").strip()
    db_path = os.environ.get("REMORA_CHAIN_DB", "").strip()
    _DISPATCHER = GovernedToolDispatcher(
        expected_policy_bundle_hash=os.environ[BUNDLE_ENV],
        nonce_store=(
            DurableNonceStore(dsn=dsn, db_path=db_path) if (dsn or db_path) else None
        ),
    )
    _DISPATCHER.register("send_mail", _send_mail)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
