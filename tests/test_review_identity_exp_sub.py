# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings: identity adapters must require exp and sub and reuse one JWKS client."""
from __future__ import annotations

import time

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from remora.adapters.identity.jwt import JWTAdapter  # noqa: E402

KEY = "k" * 32


def test_jwt_without_exp_is_rejected():
    tok = jwt.encode({"sub": "u", "roles": ["admin"]}, KEY, algorithm="HS256")
    assert JWTAdapter(KEY).validate(tok) is None


def test_jwt_without_sub_is_rejected():
    tok = jwt.encode({"exp": int(time.time()) + 60, "roles": ["admin"]}, KEY, algorithm="HS256")
    assert JWTAdapter(KEY).validate(tok) is None


def test_jwt_with_exp_and_sub_is_accepted():
    tok = jwt.encode(
        {"sub": "u", "exp": int(time.time()) + 60, "roles": ["a"]}, KEY, algorithm="HS256"
    )
    ident = JWTAdapter(KEY).validate(tok)
    assert ident is not None and ident.subject == "u"


@pytest.mark.parametrize("which", ["keycloak", "entra"])
def test_idp_adapters_require_exp_sub_and_cache_jwks_client(monkeypatch, which):
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    built: list[str] = []

    class FakeClient:
        def __init__(self, url, *a, **k):
            built.append(url)

        def get_signing_key_from_jwt(self, token):
            class K:
                key = private.public_key()

            return K()

    monkeypatch.setattr("jwt.PyJWKClient", FakeClient)
    if which == "keycloak":
        from remora.adapters.identity.keycloak import KeycloakAdapter

        a = KeycloakAdapter("https://kc.invalid", "r", "cid")
    else:
        from remora.adapters.identity.entra import EntraIDAdapter

        a = EntraIDAdapter("tid", "cid")
    base = {"aud": "cid", "iss": a._issuer}

    def enc(extra):
        return jwt.encode({**base, **extra}, private, algorithm="RS256")

    exp = int(time.time()) + 60
    assert a.validate(enc({"sub": "u"})) is None  # no exp
    assert a.validate(enc({"exp": exp})) is None  # no sub
    ok = a.validate(enc({"sub": "u", "exp": exp}))
    assert ok is not None and ok.subject == "u"
    assert len(built) == 1, built
