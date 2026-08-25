# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One rule for every SQLite-backed durable adapter: no in-memory databases.

Every durable adapter in this package opens ``sqlite3.connect(db_path)`` per
operation. That is the right shape for a file -- no long-lived connection to
leak across workers -- and the wrong shape for ``:memory:``, where each connect
is a fresh, empty database. The DDL runs on one connection at construction,
the next operation opens another, and the table is not there.

The failure is worse than a crash. A ledger whose job is to refuse a replayed
grant, sitting on a store that is empty every time it is read, is a replay
window carrying a durable label. The production guard exists to refuse exactly
that class of configuration, and it accepted ``:memory:`` because it only
checked that a path had been set.

Surfaced by tests/test_enabled_surfaces.py reloading the API under
``REMORA_CHAIN_DB=":memory:"``, which left every later test in the run with a
gate that raised ``no such table: pep_consumed`` (issue #379).
"""
from __future__ import annotations

_MEMORY_MARKERS = (":memory:", "mode=memory")


def is_memory_db(db_path: str) -> bool:
    """True for the forms SQLite treats as an in-memory database."""
    p = db_path.strip().lower()
    return any(marker in p for marker in _MEMORY_MARKERS)


def refuse_memory_db(db_path: str, *, what: str) -> None:
    """Raise if ``db_path`` names an in-memory SQLite database.

    ``what`` names the ledger or chain being configured, so the message says
    which guarantee the setting would have silently removed.
    """
    if db_path and is_memory_db(db_path):
        raise ValueError(
            f"{what}: {db_path!r} is an in-memory SQLite database. Durable "
            f"adapters open a connection per operation, so an in-memory "
            f"database is empty on every read -- the ledger that refuses a "
            f"replayed grant would refuse nothing. Use a file path, "
            f"REMORA_PG_DSN or REMORA_STATE_ENDPOINT."
        )
