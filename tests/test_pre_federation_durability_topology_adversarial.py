# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation probes for authority-state durability topology.

A backend admitted by the production durability guard must not silently leave a
reauthorizing store on a process-local implementation.  D1/state-endpoint is
the discriminating deployment because some authority stores support it and the
dispatch outbox currently does not.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_every_reauthorizing_runtime_store_has_a_wiring_assertion():
    """Declaring a durable adapter is insufficient; selection must be gated.

    The historical defects documented by this repository were all
    "adapter exists but this deployment switch was not wired" failures.
    """
    register = yaml.safe_load(
        (ROOT / "docs/assurance/authority_state_topology.yaml").read_text(
            encoding="utf-8"))
    reauth = {
        entry["id"] for entry in register["state"]
        if entry.get("on_loss") == "reauthorizes"
        and not entry.get("reference_implementation")
    }
    wired = {entry["for"] for entry in register.get("wiring", [])}
    missing = reauth - wired
    assert not missing, (
        "reauthorizing stores have durable adapters but no machine-checked "
        f"selection wiring: {sorted(missing)}"
    )


def test_state_endpoint_does_not_silently_leave_dispatch_outbox_in_process(
        monkeypatch):
    """REMORA_STATE_ENDPOINT is admitted by the production durability guard.

    If no D1 outbox exists, the safe outcome is an explicit unsupported/
    non-durable classification or production refusal -- never a process-local
    ExecutionOutbox under a configuration labelled durable execution state.
    """
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    monkeypatch.setenv("REMORA_STATE_ENDPOINT", "http://state.internal/query")

    import servers.execution_api as execution_api
    from remora.enforcement.outbox import ExecutionOutbox

    outbox = execution_api._build_outbox()
    assert type(outbox) is not ExecutionOutbox, (
        "D1-only deployment selected the process-local dispatch outbox"
    )


def test_state_endpoint_is_not_reported_as_in_process_execution_state(
        monkeypatch):
    """Operator telemetry must describe the backend startup admitted."""
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    monkeypatch.setenv("REMORA_STATE_ENDPOINT", "http://state.internal/query")

    import servers.api as api

    assert api._execution_state_backend() != "in_process", (
        "production may admit REMORA_STATE_ENDPOINT while metrics tell the "
        "operator execution state is in-process"
    )


def test_production_prerequisite_text_does_not_claim_d1_tenant_chain_durability():
    """Static claim-integrity probe.

    The tenant audit chain has SQLite/Postgres adapters and no D1 adapter.
    Production prerequisite guidance must not say the state endpoint supplies
    that property.
    """
    source = (ROOT / "servers/api.py").read_text(encoding="utf-8")
    needle = (
        "REMORA_PG_DSN, REMORA_STATE_ENDPOINT or REMORA_CHAIN_DB "
        "(durable execution state: tenant audit chain, review queue, and "
        "one-time-grant ledger)"
    )
    assert needle not in source
