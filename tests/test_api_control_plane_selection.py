# SPDX-License-Identifier: BUSL-1.1
"""Control-plane store selection and durability reporting in the REST gateway.

A deployment that silently falls back to an in-memory store still answers
every request successfully while retaining nothing. These tests pin the two
defences against that: production refuses to start without durable storage,
and a non-durable dev run reports itself as non-durable.
"""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]  # noqa: E402

from servers import api  # noqa: E402


def _load_api(monkeypatch: pytest.MonkeyPatch, **env: str):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DB", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import servers.api as module

    return importlib.reload(module)


def test_sqlite_dsn_forms_are_recognised() -> None:
    assert api._sqlite_path_from_dsn("sqlite:///var/remora/cp.db") == "var/remora/cp.db"
    assert api._sqlite_path_from_dsn("sqlite://cp.db") == "cp.db"
    assert api._sqlite_path_from_dsn("sqlite:cp.db") == "cp.db"
    # Postgres DSNs must not be mistaken for SQLite paths.
    assert api._sqlite_path_from_dsn("postgresql://user@host/db") is None
    assert api._sqlite_path_from_dsn("postgres://user@host/db") is None


def test_sqlite_dsn_selects_a_durable_store(tmp_path, monkeypatch) -> None:
    db = tmp_path / "cp.db"
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", f"sqlite:///{db.as_posix()}")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DB", raising=False)

    store, backend = api._make_control_plane_store()
    assert backend == "sqlite"
    assert store.durable is True


def test_control_plane_db_env_selects_a_durable_store(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DB", str(tmp_path / "cp.db"))

    store, backend = api._make_control_plane_store()
    assert backend == "sqlite"
    assert store.durable is True


def test_dev_without_storage_falls_back_and_admits_it(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DB", raising=False)
    monkeypatch.setenv("REMORA_ENV", "development")

    store, backend = api._make_control_plane_store()
    assert backend == "in_memory"
    # The fallback is allowed in dev, but it must never claim durability.
    assert store.durable is False


def test_production_refuses_to_start_without_durable_storage(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DB", raising=False)
    monkeypatch.setenv("REMORA_ENV", "production")

    with pytest.raises(RuntimeError, match="REMORA_CONTROL_PLANE_DSN"):
        api._make_control_plane_store()


def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "t")
    monkeypatch.setenv("REMORA_API_TOKENS", "t:tenant:operator")
    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    for var in (
        "REMORA_CONTROL_PLANE_DSN",
        "REMORA_CONTROL_PLANE_DB",
        "REMORA_PG_DSN",
        "REMORA_CHAIN_DB",
    ):
        monkeypatch.delenv(var, raising=False)


def test_production_prerequisites_accept_sqlite_storage(monkeypatch) -> None:
    """A single-node SQLite trail is durable, so it satisfies the gate."""
    _production_env(monkeypatch)

    with pytest.raises(RuntimeError, match="REMORA_CONTROL_PLANE_DSN"):
        api._validate_production_prerequisites()

    monkeypatch.setenv("REMORA_CONTROL_PLANE_DB", "/tmp/remora-cp.db")
    monkeypatch.setenv("REMORA_CHAIN_DB", "/tmp/remora-chain.db")
    api._validate_production_prerequisites()  # must not raise


def test_production_refuses_volatile_execution_state(monkeypatch) -> None:
    """A one-time execution grant must not survive a restart as reusable.

    With no durable execution store the PEP's consumed-jti ledger is a
    process-local set, so a second worker accepts a grant the first already
    consumed. Production must refuse to start rather than leave that replay
    window open.
    """
    _production_env(monkeypatch)
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DB", "/tmp/remora-cp.db")

    with pytest.raises(RuntimeError, match="REMORA_PG_DSN or REMORA_CHAIN_DB"):
        api._validate_production_prerequisites()

    monkeypatch.setenv("REMORA_CHAIN_DB", "/tmp/remora-chain.db")
    api._validate_production_prerequisites()  # must not raise


def test_execution_state_backend_is_reported(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    assert api._execution_state_backend() == "in_process"

    monkeypatch.setenv("REMORA_CHAIN_DB", "/tmp/chain.db")
    assert api._execution_state_backend() == "sqlite"

    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://localhost/db")
    assert api._execution_state_backend() == "postgres"


def test_endpoints_report_a_non_durable_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator can see that the trail is volatile without reading the logs."""
    module = _load_api(monkeypatch)
    client = TestClient(module.app)

    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)

    metrics = client.get("/v1/metrics").json()
    assert metrics["control_plane_backend"] == "in_memory"
    assert metrics["control_plane_durable"] is False
    # The execution layer's volatility is reported on the same surface, so an
    # operator sees both halves of the durability story in one call.
    assert metrics["execution_state_backend"] == "in_process"
    assert metrics["execution_state_durable"] is False

    version = client.get("/v1/policy/version").json()
    assert version["control_plane_durable"] is False
    assert version["execution_state_durable"] is False


def test_endpoints_report_a_durable_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    module = _load_api(monkeypatch, REMORA_CONTROL_PLANE_DB=str(tmp_path / "cp.db"))
    client = TestClient(module.app)

    metrics = client.get("/v1/metrics").json()
    assert metrics["control_plane_backend"] == "sqlite"
    assert metrics["control_plane_durable"] is True


def test_assessed_decisions_persist_and_the_chain_verifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """End to end: assess, then fetch the envelope back and prove the chain."""
    db = tmp_path / "cp.db"
    module = _load_api(monkeypatch, REMORA_CONTROL_PLANE_DB=str(db))
    client = TestClient(module.app)

    request_ids = []
    for question in ("Delete the staging bucket?", "Read the changelog?"):
        response = client.post("/v1/assess", json={"question": question, "risk_tier": "high"})
        assert response.status_code == 200, response.text
        request_ids.append(response.json()["request_id"])

    for request_id in request_ids:
        stored = client.get(f"/v1/envelope/{request_id}")
        assert stored.status_code == 200
        assert stored.json()["envelope"]["request"]["request_id"] == request_id

    verify = client.get("/v1/audit/chain/verify").json()
    assert verify["records_checked"] == 2
    assert verify["chain_valid"] is True
    assert verify["durable"] is True

    # The decisions outlive this API instance: a fresh store over the same
    # file still has them. That is the property the whole change exists for.
    from remora.adapters.storage import SQLiteControlPlaneStore

    reopened = SQLiteControlPlaneStore(db_path=str(db))
    assert len(reopened.list_audit_records_for_tenant(tenant_id="default")) == 2
