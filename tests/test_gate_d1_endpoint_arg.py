# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""EnforcementGate(state_endpoint=...) must talk to THAT endpoint.

External review 2026-08-26 (F1): the constructor accepted ``state_endpoint``
but ``d1_connection.connect()`` read only REMORA_STATE_ENDPOINT, so a caller
that passed the argument without also exporting the variable got
D1Unavailable at construction and the parameter was a bare backend switch.
The explicit argument now wins over the environment.
"""
from __future__ import annotations

import pytest

from remora.persistence import d1_connection as d1

ENDPOINT = "http://state.internal/query"


class _Fake:
    def __init__(self) -> None:
        self.urls: list[str | None] = []

    def post(self, statements, url=None):  # noqa: ANN001
        self.urls.append(url)
        return [[] for _ in statements]


def test_explicit_endpoint_is_used_without_the_env_var(monkeypatch) -> None:
    monkeypatch.delenv(d1.ENDPOINT_ENV, raising=False)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "endpoint-arg-test-key")
    fake = _Fake()
    monkeypatch.setattr(d1, "_post", fake.post)

    from remora.enforcement.gate import EnforcementGate

    EnforcementGate(state_endpoint=ENDPOINT)  # _ensure_table goes through connect()

    assert fake.urls, "the gate never reached the state store"
    assert set(fake.urls) == {ENDPOINT}


def test_explicit_endpoint_wins_over_the_env_var(monkeypatch) -> None:
    monkeypatch.setenv(d1.ENDPOINT_ENV, "http://other.internal/query")
    fake = _Fake()
    monkeypatch.setattr(d1, "_post", fake.post)

    with d1.connect(ENDPOINT) as conn:
        conn.execute("SELECT 1")

    assert fake.urls == [ENDPOINT]


def test_no_endpoint_anywhere_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv(d1.ENDPOINT_ENV, raising=False)
    with pytest.raises(d1.D1Unavailable):
        with d1.connect() as conn:
            conn.execute("SELECT 1")
