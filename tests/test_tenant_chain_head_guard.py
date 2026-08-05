# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A missing chain head must fail loudly, not as an opaque TypeError.

``PostgresTenantChain.append`` upserts the per-tenant head row and then
selects it back ``FOR UPDATE``. In practice the row is always there, which
is why indexing the result unguarded went unnoticed — mypy flagged it as
"tuple[Any, ...] | None is not indexable" and it stayed flagged.

The failure it hides is worth naming: if the head row is ever absent (a
truncated table, a migration that dropped it, a tenant scoped away by a
policy the code does not know about), the append crashes with
``'NoneType' object is not subscriptable`` — an error that says nothing
about audit chains and sends the reader to the wrong place. An explicit
refusal names the tenant and the table.
"""
from __future__ import annotations

import pytest

from remora.governance.tenant_chain import PostgresTenantChain


class _NoHeadCursor:
    """A connection whose head SELECT finds nothing."""

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _NoHeadConnection(_NoHeadCursor):
    def transaction(self):
        return _FakeTransaction()


class _FakePsycopg:
    def connect(self, dsn):  # noqa: ARG002 - signature parity only
        return _NoHeadConnection()


def test_missing_head_row_raises_a_named_error(monkeypatch) -> None:
    chain = PostgresTenantChain.__new__(PostgresTenantChain)
    chain._psycopg = _FakePsycopg()
    chain._dsn = "postgresql://unused"
    chain._now_fn = lambda: __import__("datetime").datetime.now(
        __import__("datetime").UTC
    )

    with pytest.raises(RuntimeError) as exc:
        chain.append("acme", {"event": "test"})

    message = str(exc.value)
    assert "acme" in message, "the error must name the tenant"
    assert "tenant_chain_head" in message, "and the table that is missing it"
    assert "NoneType" not in message, (
        "an opaque TypeError is exactly what this guard replaces"
    )
