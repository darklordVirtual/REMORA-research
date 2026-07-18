# Author: Stian Skogbrott
# License: Apache-2.0
"""Review findings: one authoritative RBAC role vocabulary, and audit
identity bound to the authenticated credential — never client-declared."""
from __future__ import annotations

import json

import pytest

from servers import api as api_mod


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
