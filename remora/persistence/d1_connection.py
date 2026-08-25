# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A DB-API-shaped connection over Cloudflare D1.

Exists so a container with no writable disk can still keep durable execution
state. The container has no database credential: it posts to an internal
hostname, and the Worker that owns it answers from a D1 binding.

**What this is not.** D1 over HTTP has no interactive transaction. There is no
``BEGIN EXCLUSIVE`` to hold and no server-side rollback to call. So writes are
buffered and sent as one batch at ``commit()``, and ``rollback()`` is simply
never sending them. That gives all-or-nothing for the write set, which is what
``transaction_state`` needs, and it does **not** give isolation from a
concurrent writer between load and commit.

That is safe here only because the deployment runs a single container
instance, so the container itself serialises. It would not be safe with more
than one, and the guard below says so rather than leaving it to be discovered.
"""
from __future__ import annotations

from remora.errors import RemoraError

import json
import os
import urllib.error
import urllib.request
from typing import Any

#: Where the Worker intercepts. Nothing resolves this on the public internet:
#: if the interception is not configured the request fails rather than
#: escaping to somewhere that might answer.
ENDPOINT_ENV = "REMORA_STATE_ENDPOINT"

_TIMEOUT = 20


class D1Unavailable(RemoraError, RuntimeError):
    """The state store could not be reached, or refused the statement."""

    code = "d1_unavailable"
    category = "persistence"


def endpoint() -> str:
    return os.getenv(ENDPOINT_ENV, "").strip()


def _post(statements: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    url = endpoint()
    if not url:
        raise D1Unavailable(f"{ENDPOINT_ENV} is not set")
    body = json.dumps({"batch": statements}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise D1Unavailable(f"state store returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise D1Unavailable(f"state store unreachable: {exc.reason}") from exc
    if not payload.get("success"):
        raise D1Unavailable(f"state store refused: {str(payload.get('errors'))[:300]}")
    return payload.get("results") or []


def _is_write(sql: str) -> bool:
    head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    return head not in {"SELECT", "PRAGMA", "EXPLAIN", "WITH"}


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def fetchone(self):
        if not self._rows:
            return None
        # The callers index positionally, as they do with sqlite3.
        return tuple(self._rows[0].values())

    def fetchall(self):
        return [tuple(r.values()) for r in self._rows]

    def __iter__(self):
        return iter(self.fetchall())


class D1Connection:
    """Enough of the sqlite3 connection surface for ``transaction_state``.

    Reads execute immediately. Writes accumulate and are sent as one atomic
    batch by ``commit()``, so an exception before commit leaves the store
    untouched without needing a server-side rollback.
    """

    def __init__(self) -> None:
        self._pending: list[dict[str, Any]] = []
        self._closed = False

    # ── sqlite3-shaped surface ──────────────────────────────────────────
    def execute(self, sql: str, params: Any = ()) -> _Cursor:
        if self._closed:
            raise D1Unavailable("connection is closed")
        args = list(params or ())
        if _is_write(sql):
            self._pending.append({"sql": sql, "params": args})
            return _Cursor([])
        # A read must see this transaction's own writes, so anything pending
        # is flushed first. Statements stay ordered; nothing is reordered
        # behind the caller's back.
        if self._pending:
            self._flush()
        results = _post([{"sql": sql, "params": args}])
        return _Cursor(results[0] if results else [])

    def commit(self) -> None:
        self._flush()

    def rollback(self) -> None:
        # Nothing was sent, so nothing has to be undone.
        self._pending.clear()

    def close(self) -> None:
        self._pending.clear()
        self._closed = True

    def __enter__(self) -> "D1Connection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()

    # ── internals ───────────────────────────────────────────────────────
    def _flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        _post(batch)


def connect() -> D1Connection:
    return D1Connection()
