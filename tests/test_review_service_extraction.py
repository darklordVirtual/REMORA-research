# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 review-service extraction (slice 6)."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.execution.review_service import (
    ReviewConflict,
    ReviewNotFound,
    reject_item,
)


def test_review_service_has_no_http_knowledge() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "remora" / "execution" / "review_service.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "HTTPException", "APIRouter", "servers."):
        assert forbidden not in src, forbidden


class _Queue:
    def __init__(self, items: dict):
        self._items = items

    def item(self, item_id):
        return self._items[item_id]

    def expire_due(self):
        pass

    def reject(self, item_id, *, reviewer, reason):
        if item_id not in self._items:
            raise KeyError(item_id)
        return self._items[item_id]


class _Chain:
    def __init__(self):
        self.entries = []

    def append(self, tenant, payload):
        self.entries.append((tenant, payload))
        return type("E", (), {"sequence_no": len(self.entries), "entry_hash": "h"})()


def _deps(items: dict, item_tenant: dict):
    chain = _Chain()

    @contextmanager
    def transaction(tenant):
        yield _Queue(items)

    return {
        "transaction": transaction,
        "item_tenant": item_tenant,
        "chain": chain,
        "lifecycle_guard": lambda *a: None,
        "note_proposal_id": lambda _p: None,
    }, chain


def test_foreign_tenant_item_is_not_found_never_forbidden() -> None:
    item = type("I", (), {"observation": type("O", (), {"proposal_id": "p1"})()})()
    deps, _ = _deps({"i1": item}, {"i1": "other-tenant"})
    with pytest.raises(ReviewNotFound):
        reject_item(tenant="t1", principal="rev", item_id="i1",
                    reason="no", **deps)


def test_reject_records_authenticated_principal_only() -> None:
    item = type("I", (), {"observation": type("O", (), {"proposal_id": "p1"})()})()
    deps, chain = _deps({"i1": item}, {"i1": "t1"})
    result = reject_item(tenant="t1", principal="reviewer@x", item_id="i1",
                         reason="unsafe", **deps)
    assert result["status"] == "rejected"
    tenant, payload = chain.entries[0]
    assert (tenant, payload["actor"], payload["reason"]) == ("t1", "reviewer@x", "unsafe")


def test_queue_refusal_becomes_conflict() -> None:
    class _RefusingQueue(_Queue):
        def reject(self, item_id, *, reviewer, reason):
            raise ValueError("item is not pending")

    @contextmanager
    def transaction(tenant):
        yield _RefusingQueue({"i1": object()})

    deps, _ = _deps({}, {"i1": "t1"})
    deps["transaction"] = transaction
    with pytest.raises(ReviewConflict, match="not pending"):
        reject_item(tenant="t1", principal="rev", item_id="i1",
                    reason="x", **deps)
