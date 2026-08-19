# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Phase 4: traffic-independent outbox reconciliation.

The in-request sweep only runs when a tenant sends traffic; these tests pin
the standalone path: tenant enumeration on every adapter, a wall-clock sweep
over a durable store settling stale rows to UNKNOWN / unclaimed rows to
FAILED with audit records, and the in-process refusal (a separate process
cannot see the API's memory, so sweeping it would report false health).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement.outbox import (
    ExecutionOutbox,
    OutboxState,
    SQLiteExecutionOutbox,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "run_outbox_reconciler.py"


def test_in_process_outbox_enumerates_tenants() -> None:
    box = ExecutionOutbox()
    box.record_intent(proposal_id="p1", tenant_id="t1", item_id="i1",
                      tool_name="x", tool_call_hash="h", grant_jti="j1")
    box.record_intent(proposal_id="p2", tenant_id="t2", item_id="i2",
                      tool_name="x", tool_call_hash="h", grant_jti="j2")
    assert box.tenants() == ["t1", "t2"]


def test_sqlite_outbox_enumerates_tenants(tmp_path: Path) -> None:
    box = SQLiteExecutionOutbox(str(tmp_path / "outbox.db"))
    box.record_intent(proposal_id="p1", tenant_id="t-b", item_id="i1",
                      tool_name="x", tool_call_hash="h", grant_jti="j1")
    box.record_intent(proposal_id="p2", tenant_id="t-a", item_id="i2",
                      tool_name="x", tool_call_hash="h", grant_jti="j2")
    assert box.tenants() == ["t-a", "t-b"]


def test_wall_clock_sweep_settles_idle_tenant(tmp_path: Path,
                                              monkeypatch) -> None:
    """A stale claimed row for a tenant that sends NO traffic settles as
    UNKNOWN via the standalone sweep."""
    db = tmp_path / "chain.db"
    monkeypatch.setenv("REMORA_CHAIN_DB", str(db))
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)

    import importlib
    import servers.execution_api as exec_mod
    importlib.reload(exec_mod)
    try:
        outbox = exec_mod._outbox()
        intent = outbox.record_intent(
            proposal_id="p-idle", tenant_id="idle-tenant", item_id="i1",
            tool_name="x", tool_call_hash="h", grant_jti="j1",
        )
        outbox.claim(intent.outbox_id, worker_id="worker-that-died")

        future = datetime.now(UTC) + timedelta(seconds=3600)
        settled = exec_mod.reconcile_stale_dispatches("idle-tenant", now=future)
        assert len(settled) == 1
        assert settled[0].state is OutboxState.UNKNOWN
        # UNKNOWN is terminal and never auto-retried: a second sweep is a no-op.
        assert exec_mod.reconcile_stale_dispatches("idle-tenant", now=future) == []
    finally:
        monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
        importlib.reload(exec_mod)


def test_cli_refuses_in_process_outbox() -> None:
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("REMORA_PG_DSN", "REMORA_CHAIN_DB")}
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--once"],
        capture_output=True, text=True, cwd=_REPO_ROOT, env=env,
    )
    assert proc.returncode == 2
    assert "in-process outbox" in proc.stdout


def test_cli_sweeps_durable_store(tmp_path: Path) -> None:
    import os
    db = tmp_path / "chain.db"
    box = SQLiteExecutionOutbox(str(db))
    intent = box.record_intent(
        proposal_id="p-cli", tenant_id="t-cli", item_id="i1",
        tool_name="x", tool_call_hash="h", grant_jti="j1",
    )
    box.claim(intent.outbox_id, worker_id="w-dead")

    env = dict(os.environ)
    env.pop("REMORA_PG_DSN", None)
    env["REMORA_CHAIN_DB"] = str(db)
    env["REMORA_OUTBOX_STALE_SECONDS"] = "0"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--once"],
        capture_output=True, text=True, cwd=_REPO_ROOT, env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "state=UNKNOWN" in proc.stdout
    assert "sweep complete: 1 row(s)" in proc.stdout
