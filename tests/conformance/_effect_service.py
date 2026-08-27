# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A protected external effect, in its own process, behind a real credential.

Stands in for the SMTP relay or vendor API that a governed tool actually
reaches. Two properties matter for the conformance fixture:

* ``POST /send`` requires the bearer token. Without it the effect does not
  happen, so "the agent has no credential" becomes a testable statement
  rather than an architectural intention.
* ``GET /mailbox`` is unauthenticated and authoritative. It is the read-back
  path for property G: what the world says happened, as opposed to what the
  dispatch call returned.

Prints its port on stdout so the parent can bind to an ephemeral port
instead of racing for a fixed one.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_ENV = "CONFORMANCE_EFFECT_TOKEN"

_MAILBOX: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # keep pytest output clean
        return

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/mailbox":
            self._json(200, {"delivered": _MAILBOX})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/send":
            self._json(404, {"error": "not_found"})
            return
        # Drain the body before deciding. An unread request body makes the
        # peer see a connection reset instead of the 401, which would hide
        # the refusal this fixture exists to observe.
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""

        expected = os.environ.get(TOKEN_ENV, "")
        presented = self.headers.get("Authorization", "")
        if not expected or presented != f"Bearer {expected}":
            # The whole fixture rests on this branch being real.
            self._json(401, {"error": "unauthorized"})
            return
        payload = json.loads(raw or b"{}")
        _MAILBOX.append({"to": payload.get("to", "")})
        self._json(200, {"status": "delivered", "count": len(_MAILBOX)})


def main() -> int:
    if not os.environ.get(TOKEN_ENV, "").strip():
        print("effect service refuses to start without a token", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
