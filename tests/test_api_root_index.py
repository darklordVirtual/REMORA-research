# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The root path must point somewhere, not look like a dead server.

`/` had no route, so the first address anyone types returned
``{"detail":"Not Found"}`` — indistinguishable from "nothing is running" for
an operator opening the pilot in a browser for the first time. The index is
navigation only: it exposes no decision data and requires no token, so it
cannot leak anything a port scan would not already reveal.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import servers.api as api_mod  # noqa: E402

client = TestClient(api_mod.app)


def test_root_returns_an_index_not_a_404() -> None:
    resp = client.get("/")
    assert resp.status_code == 200, resp.text


def test_index_names_the_service_and_version() -> None:
    body = client.get("/").json()
    assert body["service"] == "REMORA API"
    assert body["version"] == api_mod._PACKAGE_VERSION


def test_index_points_at_the_paths_that_exist() -> None:
    """Every link the index advertises must actually resolve — an index that
    sends a first-time reader to a 404 is worse than no index."""
    links = client.get("/").json()["links"]
    for name, path in links.items():
        assert client.get(path).status_code != 404, f"{name} -> {path} is a 404"


def test_index_advertises_docs_health_and_metrics() -> None:
    links = client.get("/").json()["links"]
    assert links["docs"] == "/docs"
    assert links["health"] == "/v1/health"
    assert "metrics" in links


def test_index_states_the_runtime_mode() -> None:
    """An operator must be able to tell a production deployment from a
    development one without a token."""
    body = client.get("/").json()
    assert body["runtime_mode"] in ("production", "development")


def test_index_states_which_surfaces_are_served() -> None:
    """A caller that gets 404 from /v1/assess must be able to tell "this
    deployment does not serve that surface" from "this server is broken"."""
    surfaces = client.get("/").json()["surfaces"]
    assert surfaces == sorted(surfaces)
    assert set(surfaces) <= {"execution", "assess"}


def test_index_carries_no_decision_data() -> None:
    """Navigation only: no counters, no tenant, no policy internals.

    ``surfaces`` is on the allowlist deliberately: the identical fact is
    already derivable from ``/openapi.json``, which is served without a token
    too, so listing it here discloses nothing a caller could not read one
    request later. Anything NOT on this list needs the same argument made
    before it is added.
    """
    body = client.get("/").json()
    assert set(body) <= {"service", "version", "runtime_mode", "status",
                         "links", "surfaces"}
