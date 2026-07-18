# Author: Stian Skogbrott
# License: Apache-2.0
"""Review findings: one authoritative RBAC role vocabulary, and audit
identity bound to the authenticated credential — never client-declared."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")  # servers.api needs the 'api' extra
from servers import api as api_mod  # noqa: E402


def _table(role: str, actor: str | None = None) -> str:
    entry: dict = {"tenant": "acme", "role": role}
    if actor is not None:
        entry["actor_id"] = actor
    return json.dumps({"tok_x": entry})


@pytest.mark.parametrize("role", sorted(api_mod._BUILTIN_ROLE_PERMISSIONS))
def test_every_documented_role_is_provisionable(monkeypatch, role) -> None:
    """The capability matrix IS the vocabulary: all eight roles provision."""
    monkeypatch.setenv("REMORA_API_TOKENS", _table(role))
    table = api_mod._load_token_table()
    assert table["tok_x"] == ("acme", role)
    # ...and each provisioned role has a defined capability set.
    assert api_mod._BUILTIN_ROLE_PERMISSIONS[role] is not None


@pytest.mark.parametrize("bad_role", ["auditor", "root", "superuser", ""])
def test_undocumented_roles_are_rejected(monkeypatch, bad_role) -> None:
    """No role outside the capability matrix authenticates — including the
    former 'auditor', which parsed but carried zero permissions."""
    monkeypatch.setenv("REMORA_API_TOKENS", _table(bad_role))
    with pytest.raises(Exception):
        api_mod._load_token_table()


class _StubRequest:
    def __init__(self, bearer: str | None) -> None:
        self.headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}


def test_principal_comes_from_credential_not_body(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_API_TOKENS", _table("reviewer", actor="employee-123"))
    api_mod._TOKEN_ACTOR_IDS.clear()
    api_mod._load_token_table()
    assert api_mod._authenticated_principal(_StubRequest("tok_x")) == "employee-123"


def test_principal_falls_back_to_credential_fingerprint(monkeypatch) -> None:
    api_mod._TOKEN_ACTOR_IDS.clear()
    principal = api_mod._authenticated_principal(_StubRequest("some-opaque-token"))
    assert principal.startswith("cred-") and len(principal) == 17
    # Deterministic per credential; different credential -> different identity.
    assert principal == api_mod._authenticated_principal(_StubRequest("some-opaque-token"))
    assert principal != api_mod._authenticated_principal(_StubRequest("other-token"))


def test_startup_with_actor_id_in_first_import(tmp_path) -> None:
    """Review-7 P1: REMORA_API_TOKENS with actor_id set BEFORE first import
    must not abort module init (the actor map must exist before the loader
    runs). Subprocess = genuinely fresh import."""
    import json as _json
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = dict(os.environ)
    env["REMORA_API_TOKENS"] = _json.dumps(
        {"tok_1": {"tenant": "acme", "role": "reviewer", "actor_id": "employee-123"}}
    )
    env["REMORA_ENV"] = "development"
    proc = subprocess.run(
        [sys.executable, "-c",
         "import servers.api as a; assert a._TOKEN_ACTOR_IDS['tok_1'] == 'employee-123'; print('ok')"],
        capture_output=True, text=True, env=env, timeout=120,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "ok" in proc.stdout


def test_execution_endpoints_enforce_capabilities(monkeypatch) -> None:
    """Review-7 P1: a viewer must not reach assess/execute; audit needs read."""
    import pytest as _pytest

    _pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("REMORA_ENV", "development")
    import servers.api as api_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "viewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "v-1")
    client = TestClient(api_mod.app)
    r = client.post("/v1/execution/assess", json={"tool_name": "read_x"})
    assert r.status_code == 403
    r = client.post("/v1/execution/execute",
                    json={"item_id": "x", "tool_call": {"tool_name": "t"}})
    assert r.status_code == 403
    # viewer HAS read -> audit verify is allowed
    assert client.get("/v1/execution/audit/verify").status_code == 200
    # reviewer lacks assess/execute as well
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    assert client.post("/v1/execution/assess", json={"tool_name": "read_x"}).status_code == 403
