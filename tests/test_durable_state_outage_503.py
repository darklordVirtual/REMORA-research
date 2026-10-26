# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A durable store that does not answer is a 503, not an internal error.

The OT pilot's fault-injection run on 2026-10-26 stopped its Postgres
service. ``/v1/execution/assess`` and ``/v1/execution/execute`` refused, and
nothing executed, but both answered 500 "An internal error occurred". A
client cannot tell that from a defect, so it cannot know that a retry once
the store is back is the right move. A driver ``OperationalError`` (psycopg
v3 or psycopg2: the connection failed or was lost) now answers 503
``durable_state_unavailable`` with the same correlation id. Every other
unhandled exception is still a 500, and neither body carries the message.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _driver_error(module: str, name: str = "OperationalError") -> type[Exception]:
    """A class shaped like the driver's, so the test needs no driver installed."""
    base = type(name, (Exception,), {})
    base.__module__ = module
    return type("ConnectionTimeout", (base,), {"__module__": f"{module}.errors"})


@pytest.fixture()
def client(monkeypatch):
    import servers.api as api_mod

    def route_raising(exc_type: type[Exception], message: str):
        path = f"/__test/raise/{id(exc_type):x}"

        def boom() -> None:
            raise exc_type(message)

        api_mod.app.add_api_route(path, boom, methods=["GET"])
        return path

    yield TestClient(api_mod.app, raise_server_exceptions=False), route_raising


@pytest.mark.parametrize("module", ["psycopg", "psycopg2"])
def test_a_driver_operational_error_is_503_durable_state_unavailable(client, module):
    http, route_raising = client
    secret = "failed to resolve host 'postgres' password=hunter2"
    r = http.get(route_raising(_driver_error(module), secret))
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["detail"] == "durable_state_unavailable"
    assert len(body["correlation_id"]) == 8
    assert "hunter2" not in r.text and "postgres" not in r.text


def test_another_driver_error_stays_500(client):
    http, route_raising = client
    r = http.get(route_raising(_driver_error("psycopg", "ProgrammingError"), "syntax"))
    assert r.status_code == 500
    assert r.json()["detail"].startswith("An internal error occurred")


def test_an_operational_error_from_elsewhere_stays_500(client):
    http, route_raising = client
    r = http.get(route_raising(_driver_error("sqlite3"), "database is locked"))
    assert r.status_code == 500


def test_the_real_driver_class_is_recognised_when_installed():
    psycopg = pytest.importorskip("psycopg")
    import servers.api as api_mod

    assert api_mod._is_durable_state_outage(psycopg.OperationalError("down"))
    assert not api_mod._is_durable_state_outage(psycopg.ProgrammingError("syntax"))
