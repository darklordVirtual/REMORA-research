# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 review-state extraction (slice 2).

The transaction adapter moved to remora/persistence/execution_state.py with
module globals turned into parameters; servers.execution_api binds its own
ambient state in db_transaction_state(). The transactional semantics
themselves are pinned by tests/test_execution_fault_injection.py — these
tests pin the wiring and the package-conversion compatibility.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_api_re_exports_are_the_extracted_objects() -> None:
    import servers.execution_api as api
    from remora.persistence import execution_state

    assert api.to_dict is execution_state.to_dict
    assert api.from_dict is execution_state.from_dict


def test_persistence_package_keeps_legacy_oracle_cache_surface() -> None:
    # remora/persistence.py became a package; the flat module's public
    # classes must remain importable from the same dotted path.
    from remora.persistence import CachedOracle, Store  # noqa: F401


def test_execution_state_module_has_no_http_knowledge() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "remora" / "persistence" / "execution_state.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("fastapi", "APIRouter", "HTTPException", "Request", "servers."):
        assert forbidden not in src, forbidden


def test_in_process_transaction_rolls_back_mirrors() -> None:
    """Direct exercise of the extracted adapter's in-process branch."""
    import contextvars

    from remora.persistence.execution_state import transaction_state

    class _Q:
        def __init__(self):
            import threading
            self._items = {"a": {"v": 1}}
            self._lock = threading.Lock()

    q = _Q()
    item_tenant = {"a": "t1"}
    var: contextvars.ContextVar = contextvars.ContextVar("tx", default=None)

    try:
        with transaction_state(
            "t1", queue=q, item_tenant=item_tenant,
            active_tx_connection=var, dsn="", db_path="",
        ) as tx_q:
            tx_q._items["a"]["v"] = 2
            item_tenant["b"] = "t1"
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert q._items == {"a": {"v": 1}}, "deep-copied snapshot must restore items"
    assert item_tenant == {"a": "t1"}, "item->tenant mirror must restore"
