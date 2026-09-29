# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A read-only 'was this nonce consumed?' that never consumes (NTA-2 phase 3).

The effect domain asks it before serving a mediated effect: a lease whose
nonce was never consumed was never dispatched, so no execution exists for the
effect to belong to.
"""
from __future__ import annotations

import pytest

from remora.enforcement.nonce_store import DurableNonceStore, InMemoryNonceStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryNonceStore()
    return DurableNonceStore(db_path=str(tmp_path / "nonces.db"))


def test_unconsumed_reads_false_and_stays_consumable(store):
    assert store.consumed("n-1", tenant_id="acme") is False
    assert store.consumed("n-1", tenant_id="acme") is False
    assert store.try_consume("n-1", tenant_id="acme") is True


def test_consumed_reads_true(store):
    assert store.try_consume("n-1", tenant_id="acme") is True
    assert store.consumed("n-1", tenant_id="acme") is True


def test_the_lookup_is_tenant_scoped(store):
    store.try_consume("n-1", tenant_id="acme")
    assert store.consumed("n-1", tenant_id="other") is False
