# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One process serves two products; a deployment may serve only one.

The execution surface is policy-only — no model, no egress. The assess surface
is oracle-backed. Production mode used to demand the assess surface's
prerequisites from every deployment, so an execution-only product had to name
an oracle backend it would never call and ship a retrieval evidence pack it
would never read. ``deploy/ot-pilot/docker-compose.yml`` does exactly that.

The property that makes this a scoping change rather than a weakening: a
disabled surface is **unmounted**. Dropping the prerequisites while leaving
``/v1/assess`` reachable would put a mock-oracle assess endpoint into
production, which is the opposite of the intent.
"""
from __future__ import annotations

import importlib
import sys

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _served_paths(app) -> set[str]:
    """Every path this app answers, including routers included as one object.

    This FastAPI version does not flatten ``include_router`` into the parent's
    route list: the execution router appears as a single ``_IncludedRouter``
    holding the original router. Enumerating only the top level would report
    the execution surface as absent and quietly turn every assertion about it
    into a tautology.
    """
    paths: set[str] = set()
    for route in app.router.routes:
        if (path := getattr(route, "path", None)) is not None:
            paths.add(path)
            continue
        inner = getattr(route, "original_router", None)
        for nested in getattr(inner, "routes", ()):
            if (nested_path := getattr(nested, "path", None)) is not None:
                paths.add(nested_path)
    return paths


@pytest.fixture(autouse=True)
def _restore_api_modules():
    """Put the session's real servers.api / servers.execution_api back.

    _reload_api pops both from sys.modules and re-imports them under this
    test's environment. Without this, the module built for an execution-only
    production deployment with a scratch chain DB is the one every subsequent
    test in the session gets from `import servers.api`. That is how a gate
    pointed at a throwaway database outlived this file and failed unrelated
    tests with `no such table: pep_consumed` (issue #379).
    """
    names = ("servers.api", "servers.execution_api")
    saved = {name: sys.modules.get(name) for name in names}
    yield
    package = sys.modules.get("servers")
    for name, module in saved.items():
        if module is not None:
            sys.modules[name] = module
        else:
            sys.modules.pop(name, None)
        # BOTH bindings, not just sys.modules. `_reload_api`'s fresh import
        # also rebinds the submodule as an attribute of the `servers` package,
        # and `from servers.execution_api import X` resolves through THAT
        # attribute. Restoring only sys.modules leaves the two lookup paths
        # pointing at different module objects: a test then patches the module
        # it imported while runtime code reads the other one, and the patch
        # silently does not apply -- which is how a policy tightening became
        # invisible to the execute path three files later.
        if package is not None:
            attr = name.rsplit(".", 1)[1]
            if module is not None:
                setattr(package, attr, module)
            elif hasattr(package, attr):
                delattr(package, attr)
    # Restoring the original object is not enough: it carries whatever cached
    # state earlier tests left on it (a signed toolspec bundle, a dispatcher,
    # an outbox). The reload this fixture undoes used to hand later tests a
    # FRESH module, so restore that property too -- reset the caches under
    # the session's real environment, which monkeypatch has already put back
    # by the time this teardown runs.
    exec_mod = sys.modules.get("servers.execution_api")
    if exec_mod is not None:
        exec_mod._reset_semantic_bundle()
        exec_mod._reset_tool_dispatcher()
        exec_mod._reset_outbox()
        exec_mod._reset_toolspec_bundle()
        exec_mod._reset_idempotency_store()
        exec_mod._QUEUES.clear()
        exec_mod._ITEM_TENANT.clear()


@pytest.fixture
def durable_paths(tmp_path, monkeypatch):
    """Real files for the durable stores, never ``:memory:``.

    An in-memory SQLite database is empty on every per-operation connect, so
    it is not durable and the guard now refuses it. These tests are about
    surface selection, not storage, so they get files that behave.
    """
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DB", str(tmp_path / "control.db"))


def _reload_api(monkeypatch, **env):
    """Import servers.api fresh under a given environment.

    Surface selection happens at import, because unmounting a route after the
    app is serving would be a different and much weaker guarantee.
    """
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for module in ("servers.api", "servers.execution_api"):
        sys.modules.pop(module, None)
    return importlib.import_module("servers.api")


_PROD_EXECUTION_ENV = {
    "REMORA_ENV": "production",
    "REMORA_API_BEARER_TOKEN": "t",
    "REMORA_API_TOKENS": '{"t":{"tenant":"acme","role":"operator"}}',
    "REMORA_PDP_SIGNING_KEY": "k",
    "REMORA_LEASE_SIGNING_KEY": "k",
    "REMORA_ENVELOPE_SIGNING_KEY": "k",
}


# ── Default: nothing changes for an existing deployment ────────────────────

def test_both_surfaces_are_served_by_default(monkeypatch) -> None:
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES=None)
    assert api.enabled_surfaces() == frozenset({"execution", "assess"})
    paths = _served_paths(api.app)
    assert "/v1/assess" in paths
    assert "/v1/execution/assess" in paths


def test_an_unknown_surface_name_refuses_startup(monkeypatch) -> None:
    """A misspelled ``execution`` must not yield a server with no surfaces."""
    with pytest.raises(RuntimeError, match="unknown surface"):
        _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="executon")


def test_an_empty_selection_refuses_startup(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="names no surface"):
        _reload_api(monkeypatch, REMORA_ENABLED_SURFACES=" , ")


# ── The scoping itself ─────────────────────────────────────────────────────

def test_an_execution_only_deployment_unmounts_the_assess_routes(
    monkeypatch,
) -> None:
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution")
    paths = _served_paths(api.app)
    assert "/v1/assess" not in paths
    assert "/v1/rerun" not in paths
    # Everything the product actually uses stays.
    assert "/v1/execution/assess" in paths
    assert "/v1/health" in paths
    assert "/v1/audit/chain/verify" in paths
    assert "/v1/policy/version" in paths


def test_a_disabled_route_is_absent_not_merely_forbidden(monkeypatch) -> None:
    """404, because the route does not exist — not 403 from a live handler.

    A guard inside the handler would leave a mock-oracle assess endpoint
    answering in production. Absence is the property.
    """
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution",
                      REMORA_ENV="development", REMORA_PDP_SIGNING_KEY="k")
    response = TestClient(api.app).post("/v1/assess", json={"question": "x"})
    assert response.status_code == 404


def test_the_openapi_document_stops_advertising_the_disabled_surface(
    monkeypatch,
) -> None:
    """A consumer generating a client must not build calls that cannot answer."""
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution",
                      REMORA_ENV="development", REMORA_PDP_SIGNING_KEY="k")
    document = TestClient(api.app).get("/openapi.json").json()
    assert "/v1/assess" not in document["paths"]
    assert "/v1/execution/assess" in document["paths"]


def test_the_root_endpoint_reports_which_surfaces_are_served(
    monkeypatch,
) -> None:
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution",
                      REMORA_ENV="development", REMORA_PDP_SIGNING_KEY="k")
    body = TestClient(api.app).get("/").json()
    assert body["surfaces"] == ["execution"]


# ── Prerequisites follow the surface ───────────────────────────────────────

def test_execution_only_production_starts_without_an_oracle_backend(durable_paths,
    monkeypatch,
) -> None:
    """The gap this closes.

    Before, this raised "missing required env vars: REMORA_ORACLE_BACKEND"
    and the only way past it was to name a backend the deployment would
    never call.
    """
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution",
                      REMORA_ORACLE_BACKEND=None, **_PROD_EXECUTION_ENV)
    assert api.enabled_surfaces() == frozenset({"execution"})


def test_execution_only_production_starts_without_an_evidence_store(durable_paths,
    monkeypatch, tmp_path,
) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    api = _reload_api(
        monkeypatch, REMORA_ENABLED_SURFACES="execution",
        REMORA_ORACLE_BACKEND=None,
        REMORA_RUNTIME_EVIDENCE_JSONL=str(empty),
        REMORA_BASE_EVIDENCE_JSONL=str(empty),
        **_PROD_EXECUTION_ENV,
    )
    assert api._RETRIEVAL_EVIDENCE_PROVIDER is None


def test_serving_assess_in_production_still_requires_an_oracle_backend(durable_paths,
    monkeypatch,
) -> None:
    """The check is scoped, not removed. This is the regression that would
    matter most: a deployment that DOES serve assess must still fail closed."""
    with pytest.raises(RuntimeError, match="REMORA_ORACLE_BACKEND"):
        _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution,assess",
                    REMORA_ORACLE_BACKEND=None, **_PROD_EXECUTION_ENV)


def test_serving_assess_in_production_still_requires_an_evidence_store(durable_paths,
    monkeypatch, tmp_path,
) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="retrieval evidence store is empty"):
        _reload_api(
            monkeypatch, REMORA_ENABLED_SURFACES="assess,execution",
            REMORA_ORACLE_BACKEND="groq",
            REMORA_RUNTIME_EVIDENCE_JSONL=str(empty),
            REMORA_BASE_EVIDENCE_JSONL=str(empty),
            **_PROD_EXECUTION_ENV,
        )


def test_the_durable_state_prerequisites_are_never_scoped_away(durable_paths,
    monkeypatch,
) -> None:
    """Execution-only does not mean fewer guarantees about execution.

    Durable execution state and a durable envelope store belong to the
    surface that IS enabled, so dropping either must still refuse.
    """
    env = dict(_PROD_EXECUTION_ENV)
    env["REMORA_CHAIN_DB"] = None
    with pytest.raises(RuntimeError, match="durable execution state"):
        _reload_api(monkeypatch, REMORA_ENABLED_SURFACES="execution",
                    REMORA_ORACLE_BACKEND=None, **env)


# ── The classification cannot decay ────────────────────────────────────────

def test_every_route_is_classified_into_a_surface(monkeypatch) -> None:
    """A new route must be a deliberate choice, not a default.

    ``_ASSESS_SURFACE_PATHS`` is an allowlist of what disappears. Everything
    else stays mounted on an execution-only deployment, so a future
    oracle-backed route added without updating this set would be reachable —
    with no backend — on a deployment that never asked for it. This test does
    not know which surface is right for a new route; it forces someone to
    say.
    """
    api = _reload_api(monkeypatch, REMORA_ENABLED_SURFACES=None)
    served = _served_paths(api.app)

    # Every path the assess surface claims must actually exist, or the
    # unmount silently covers nothing.
    assert api._ASSESS_SURFACE_PATHS <= served, (
        f"assess surface names paths that are not served: "
        f"{sorted(api._ASSESS_SURFACE_PATHS - served)}"
    )

    known_execution_and_infra = {
        "/", "/v1/health", "/metrics", "/v1/metrics", "/openapi.json",
        "/docs", "/docs/oauth2-redirect", "/redoc",
        "/v1/envelope/{request_id}", "/v1/audit/{request_id}",
        "/v1/audit/chain/verify", "/v1/review", "/v1/follow-up",
        "/v1/policy/version", "/v1/evidence",
    }
    unclassified = (
        served - api._ASSESS_SURFACE_PATHS - known_execution_and_infra
        - {p for p in served if p.startswith("/v1/execution")}
    )
    assert not unclassified, (
        f"new route(s) {sorted(unclassified)} are not classified into a "
        f"surface. Decide: add to _ASSESS_SURFACE_PATHS if the route needs an "
        f"oracle or a retrieval store, otherwise add it to this test's "
        f"execution/infrastructure set."
    )
