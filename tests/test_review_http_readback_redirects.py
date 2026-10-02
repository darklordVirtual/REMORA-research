# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings: read-back must be http(s) only and never follow redirects with credentials."""
from __future__ import annotations

import http.server
import threading

import pytest

from remora.integrations.http_readback import ReadBackFailed, http_read_back


def test_non_http_scheme_is_refused(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}")
    with pytest.raises(ReadBackFailed):
        http_read_back(f.as_uri())


def test_redirect_is_not_followed_and_auth_not_forwarded():
    seen = {"target_hits": 0, "target_auth": None}

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["target_hits"] += 1
            seen["target_auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    target = http.server.HTTPServer(("127.0.0.1", 0), Target)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{target.server_port}/x")
            self.end_headers()

        def log_message(self, *a):
            pass

    origin = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    for s in (target, origin):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with pytest.raises(ReadBackFailed):
            http_read_back(
                f"http://127.0.0.1:{origin.server_port}/o",
                headers={"Authorization": "Bearer secret-token"},
                timeout_seconds=5,
            )
    finally:
        for s in (target, origin):
            s.shutdown()
            s.server_close()
    assert seen["target_hits"] == 0
    assert seen["target_auth"] is None
