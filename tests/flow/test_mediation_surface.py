# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Mediation completeness of the execution API (IFC-11, execution API slice).

Premise A1 of the flow SDD: a tool runs, and a tool result returns, only
through the governed dispatcher under the flow check. Here that is held as a
property of the routes: every route of the execution API is classified
(``MEDIATION_TOOL_DISPATCH`` or ``MEDIATION_NO_TOOL_RESULT``), the dispatching
ones hand the call to ``_dispatch_under_lease`` and nothing else reaches the
dispatcher, and a route added to neither set fails here. The bypass probes
present forged, foreign and replayed contexts to the dispatching routes with
flow control on; each is refused before a tool runs and before a nonce or a
grant is spent. What this slice does not inventory is listed by the checker.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

import scripts.check_flow_mediation_surface as surface  # noqa: E402
from tests.flow.test_flow_dispatch_leased import (  # noqa: E402,F401
    MODEL,
    USER,
    _call,
    _context,
    _lease,
    executor,
)
from tests.test_dispatch_leased_endpoint import CALL, _post  # noqa: E402
from tests.test_dispatch_leased_endpoint import executor as _executor  # noqa: E402,F401


def _ex():
    import servers.execution_api as ex

    return ex


# ── the inventory and the static funnel ────────────────────────────────────


def test_every_execution_route_is_classified_and_funnels_through_the_governed_path(capsys):
    assert surface.main([]) == 0
    assert "[PASS]" in capsys.readouterr().out


def test_the_three_dispatching_routes_and_the_worker_are_the_whole_dispatch_surface():
    ex = _ex()
    found = surface.routes(ex)
    assert {k for k in found if k in ex.MEDIATION_TOOL_DISPATCH} == {
        ("POST", "/v1/execution/execute"), ("POST", "/v1/execution/execute-accepted"),
        ("POST", "/v1/execution/dispatch-leased")}
    assert ex.MEDIATION_WORKER_ENTRIES == {"dispatch_pending_intents"}
    assert len(found) == len(ex.MEDIATION_TOOL_DISPATCH) + len(ex.MEDIATION_NO_TOOL_RESULT)


def test_a_route_added_to_neither_set_is_reported():
    ex = _ex()

    def probe() -> dict:  # pragma: no cover - never called
        return {}

    ex.router.add_api_route("/probe", probe, methods=["POST"])  # the router adds its prefix
    try:
        problems = surface.classification_problems(
            surface.routes(ex), ex.MEDIATION_TOOL_DISPATCH, ex.MEDIATION_NO_TOOL_RESULT)
    finally:
        ex.router.routes[:] = [r for r in ex.router.routes
                               if getattr(r, "path", "") != "/v1/execution/probe"]
    assert problems == ["POST /v1/execution/probe: served and classified in neither set (handler probe)"]
    assert surface.classification_problems(
        surface.routes(ex), ex.MEDIATION_TOOL_DISPATCH, ex.MEDIATION_NO_TOOL_RESULT) == []


def test_a_classified_route_that_is_no_longer_served_is_reported():
    ex = _ex()
    gone = frozenset({("DELETE", "/v1/execution/gone")})
    problems = surface.classification_problems(
        surface.routes(ex), ex.MEDIATION_TOOL_DISPATCH, ex.MEDIATION_NO_TOOL_RESULT | gone)
    assert problems == ["DELETE /v1/execution/gone: classified but not served"]


SERVICE_OK = "def execute_approved_item():\n    dispatch_under_lease()\n"
DISPATCH_OK = "def dispatch_under_lease(dispatcher):\n    dispatcher.dispatch()\n"
API_OK = (
    "def _dispatch_under_lease():\n    _flow_at_dispatch()\n    _dispatch_under_lease_impl()\n"
    "def execute():\n    service(dispatch_under_lease=_dispatch_under_lease)\n"
    "def dispatch_leased():\n    x = 'flow_lease_unbound'\n    _dispatch_under_lease()\n"
    "def dispatch_pending_intents():\n    _dispatch_under_lease\n"
    "def assess():\n    return {}\n"
)
FOUND = {("POST", "/v1/execution/execute"): "execute",
         ("POST", "/v1/execution/dispatch-leased"): "dispatch_leased",
         ("POST", "/v1/execution/assess"): "assess"}
TD = frozenset({("POST", "/v1/execution/execute"), ("POST", "/v1/execution/dispatch-leased")})
NTR = frozenset({("POST", "/v1/execution/assess")})
WORKERS = frozenset({"dispatch_pending_intents"})


def _static(api=API_OK, service=SERVICE_OK, dispatch=DISPATCH_OK):
    return surface.static_problems(api, service, dispatch, FOUND, TD, NTR, WORKERS)


def test_the_synthetic_well_formed_api_passes_the_static_check():
    assert _static() == []


@pytest.mark.parametrize("api, fragment", [
    (API_OK.replace("def execute():\n    service(dispatch_under_lease=_dispatch_under_lease)\n",
                    "def execute():\n    return run_tool()\n"),
     "does not hand the call to _dispatch_under_lease"),
    (API_OK.replace("def assess():\n    return {}\n",
                    "def assess():\n    return _dispatch_under_lease()\n"),
     "reaches _dispatch_under_lease but returns no tool result"),
    (API_OK.replace("def assess():\n    return {}\n",
                    "def assess():\n    return _tool_dispatcher().dispatch(None)\n"),
     "calls .dispatch()"),
    (API_OK.replace("def assess():\n    return {}\n",
                    "def assess():\n    return _dispatch_under_lease_impl()\n"),
     "reaches _dispatch_under_lease_impl"),
    (API_OK.replace("    _flow_at_dispatch()\n", ""), "does not run _flow_at_dispatch"),
    (API_OK.replace("    x = 'flow_lease_unbound'\n", ""), "flow_lease_unbound"),
    (API_OK.replace("def dispatch_pending_intents():\n    _dispatch_under_lease\n",
                    "def dispatch_pending_intents():\n    pass\n"),
     "worker entry dispatch_pending_intents does not hand the call"),
])
def test_a_handler_that_leaves_the_governed_path_is_reported(api, fragment):
    problems = _static(api=api)
    assert problems and any(fragment in p for p in problems), problems


def test_a_service_or_dispatch_call_site_outside_the_allowlist_is_reported():
    assert any("dispatch_under_lease called from sneak" in p for p in _static(
        service=SERVICE_OK + "def sneak():\n    dispatch_under_lease()\n"))
    assert any("dispatcher.dispatch called from sneak" in p for p in _static(
        dispatch=DISPATCH_OK + "def sneak(dispatcher):\n    dispatcher.dispatch()\n"))


def test_the_inventory_covers_every_surface_the_sdd_names_and_says_what_it_cannot_hold():
    """IFC-11 §4: the inventory names the execution API, the assess API, the
    MCP server, the gateway (with the agent-control worker) and the SDK. What
    the property does not cover is stated, not left out."""
    inv = surface.inventory()
    assert inv["problems"] == []
    assert {r["class"] for r in inv["routes"]} == {"TOOL_DISPATCH", "NO_TOOL_RESULT"}
    surfaces = inv["surfaces"]
    assert set(surfaces) == {"servers/api.py", "servers/mcp_remora.py", "remora/sdk", "workers"}
    mcp = surfaces["servers/mcp_remora.py"]
    assert mcp["runs_tools_locally"] is False
    assert mcp["forwards_to_execution"] == ["agent_execute_tool"]
    assert "agent_execute_tool" in mcp["handlers"] and len(mcp["handlers"]) >= 14
    assert "/v1/execution/execute-accepted" in surfaces["remora/sdk"]["paths"]
    assert any(p.startswith("workers/mcp-gateway/") for p in surfaces["workers"])
    assert any(p.startswith("workers/agent-control/") for p in surfaces["workers"])
    assert any("runTool" in s for s in inv["out_of_property"])
    assert any("remora/sdk" in s and "flow_context_unknown" in s for s in inv["out_of_property"])
    assert any("outside REMORA" in s for s in inv["out_of_property"])


# ── the other surfaces, on synthetic sources ───────────────────────────────


def test_the_assess_api_may_mount_the_routers_but_not_reach_the_dispatcher():
    ok = ("from servers.execution_api import router\n"
          "from remora.enforcement.token import verify\n"
          "def assess():\n    return decide()\n")
    assert surface.assess_api_problems(ok) == []
    bad = ok + "def rerun():\n    return _tool_dispatcher().dispatch(None)\n"
    assert any("rerun calls .dispatch()" in p for p in surface.assess_api_problems(bad))
    bad = ok + "def rerun():\n    return _dispatch_under_lease()\n"
    assert any("rerun reaches _dispatch_under_lease" in p for p in surface.assess_api_problems(bad))
    bad = "from remora.execution.service import execute_approved_item\n" + ok
    assert any("imports remora.execution.service" in p for p in surface.assess_api_problems(bad))


MCP_OK = (
    "import json\n"
    "TOOLS = [{'name': 'remora_status'}, {'name': 'agent_execute_tool'}]\n"
    "def _agent_post(path, payload):\n    return {}\n"
    "def handle_remora_status(args):\n    return 'ok'\n"
    "def handle_agent_execute_tool(args):\n    return str(_agent_post('/execute', args))\n"
    "HANDLERS = {'remora_status': handle_remora_status,\n"
    "            'agent_execute_tool': handle_agent_execute_tool}\n"
    "def handle_request(request):\n    return HANDLERS.get(request['params']['name'])\n"
)


@pytest.mark.parametrize("source, fragment", [
    (MCP_OK.replace("def handle_remora_status(args):\n    return 'ok'\n",
                    "def handle_remora_status(args):\n    return _helper(args)\n"
                    "def _helper(args):\n    return GovernedToolDispatcher().dispatch(args)\n"),
     "remora_status (handle_remora_status) reaches GovernedToolDispatcher"),
    (MCP_OK.replace("TOOLS = [{'name': 'remora_status'}, {'name': 'agent_execute_tool'}]\n",
                    "TOOLS = [{'name': 'remora_status'}]\n"),
     "agent_execute_tool is in TOOLS or HANDLERS but not both"),
    (MCP_OK.replace("            'agent_execute_tool': handle_agent_execute_tool}\n",
                    "            'agent_execute_tool': handle_missing}\n"),
     "names handle_missing, which is not defined"),
    (MCP_OK.replace("    return str(_agent_post('/execute', args))\n", "    return 'ran it here'\n"),
     "classified as forwarding but never posts"),
    ("from servers.execution_api import _dispatch_under_lease\n" + MCP_OK,
     "imports servers.execution_api"),
    (MCP_OK.replace("    return HANDLERS.get(request['params']['name'])\n", "    return None\n"),
     "handle_request does not look tools/call up in HANDLERS"),
])
def test_an_mcp_server_that_runs_or_reaches_a_tool_itself_is_reported(source, fragment):
    assert surface.mcp_problems(MCP_OK) == []
    problems = surface.mcp_problems(source)
    assert problems and any(fragment in p for p in problems), problems


def test_an_sdk_path_the_execution_api_does_not_serve_is_reported():
    found = {("POST", "/v1/execution/execute"): "execute",
             ("GET", "/v1/execution/proposals/{proposal_id}"): "proposal"}
    td = frozenset({("POST", "/v1/execution/execute")})
    ok = ('def run(self, pid):\n    self._request("POST", "/v1/execution/execute")\n'
          '    self._request("GET", f"/v1/execution/proposals/{pid}")\n'
          '_EXECUTION_PATHS = frozenset({"/v1/execution/execute"})\n')
    assert surface.sdk_problems({"client.py": ok}, found, td) == []
    bad = ok.replace('"/v1/execution/execute")\n    self', '"/v1/execution/run")\n    self')
    assert any("calls /v1/execution/run, which the execution API does not serve" in p
               for p in surface.sdk_problems({"client.py": bad}, found, td))
    bad = ok.replace('_EXECUTION_PATHS = frozenset({"/v1/execution/execute"})',
                     '_EXECUTION_PATHS = frozenset({"/v1/execution/proposals/{proposal_id}"})')
    assert any("_EXECUTION_PATHS names" in p for p in surface.sdk_problems({"client.py": bad}, found, td))
    bad = "from remora.enforcement.lease import GovernedToolDispatcher\n" + ok
    assert any("imports remora.enforcement.lease" in p
               for p in surface.sdk_problems({"client.py": bad}, found, td))


def test_a_worker_path_the_execution_api_does_not_serve_is_reported():
    found = {("POST", "/v1/execution/assess"): "assess",
             ("POST", "/v1/execution/proposals/{proposal_id}/effect"): "effect"}
    ok = {"w/a.ts": 'post(env, "/v1/execution/assess", call);\n'
                    '`/v1/execution/proposals/${encodeURIComponent(id)}/effect`\n'
                    '/** POST /v1/execution/proposals/{id}/effect */\n'}
    assert surface.worker_paths(ok) == {"w/a.ts": ["/v1/execution/assess",
                                                   "/v1/execution/proposals/{param}/effect"]}
    assert surface.worker_problems(ok, found) == []
    bad = {"w/a.ts": 'post(env, "/v1/execution/run-anything", call);\n'}
    assert surface.worker_problems(bad, found) == [
        "w/a.ts: names /v1/execution/run-anything, which the execution API does not serve"]


# ── bypass probes on the execution domain, flow control on ─────────────────


def test_a_forged_context_is_refused_before_the_tool_and_spends_no_nonce(executor):  # noqa: F811
    """The lease was judged in context A; the call names a context nobody
    minted. The executor's own context lookup refuses, the tool does not run,
    and the same lease still runs for the call it was granted for."""
    context_id = _context(executor)
    call = _call(context_id)
    lease = _lease(executor, call)
    forged = dict(call, context_id="ctx_" + "f" * 26)
    body = _post(executor, lease, call=forged).json()
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] in ("flow_context_unknown", "task_mismatch")
    assert executor.registry.CALLS == []
    assert _post(executor, lease, call=call).json()["tool_execution"]["executed"] is True


def test_another_principals_context_is_unknown_to_the_lease_actor(executor):  # noqa: F811
    """A context minted by another principal is not readable by the lease's
    actor; the executor sees an unknown context and refuses."""
    import servers.execution_api as ex

    foreign = ex._flow_contexts().mint("acme", "employee-2", user_principal=USER,
                                       model_principal=MODEL).context_id
    call = _call(foreign)
    body = _post(executor, _lease(executor, call, bound=False), call=call).json()
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] in ("flow_context_unknown", "flow_lease_unbound")
    assert executor.registry.CALLS == []


def test_a_lease_from_one_context_does_not_run_in_another(executor):  # noqa: F811
    """Both contexts exist and the arguments are equal; the lease binds the
    task and the flow decision of the first, so the second is refused."""
    first, second = _context(executor), _context(executor)
    lease = _lease(executor, _call(first))
    body = _post(executor, lease, call=_call(second)).json()
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] in (
        "task_mismatch", "flow_epoch_changed", "flow_digest_changed", "flow_context_unknown")
    assert executor.registry.CALLS == []


# ── bypass probes on the other surfaces ────────────────────────────────────


def test_the_sdk_cannot_address_a_flow_context_so_nothing_runs_under_flow_control(executor):  # noqa: F811
    """The SDK's ToolCall has no context field. With flow control on, its
    assess is judged in no context and refuses (flow_context_unknown); no
    execution token is minted and the registry sees no call. The SDK is a
    client of the classified routes, not a way around them."""
    from remora.sdk import DecisionAction, RemoraClient, ToolCall

    # /assess is an authority route; the shared rig is the executor (RMR-SEC-0001).
    executor.monkeypatch.delenv("REMORA_EXECUTION_DOMAIN_ROLE", raising=False)
    client = RemoraClient(base_url="http://testserver", token="t", http_client=executor.client)
    result = client.assess(ToolCall(tool_name="update_work_order",
                                    arguments={"work_order_id": "WO-1", "status": "closed"},
                                    target_environment="staging", schema_valid=True))
    assert result.action is not DecisionAction.ACCEPT
    assert result.execution_token is None
    assert executor.registry.CALLS == []


def test_the_mcp_server_runs_no_governed_tool_and_forwards_only_to_the_agent_control_worker(
        monkeypatch, _executor):  # noqa: F811
    """A tools/call naming a governed tool is unknown to the MCP server; the
    one handler that reaches an execution surface refuses without a network
    when no worker is configured. Nothing reaches the test registry."""
    import importlib
    import socket
    import sys
    import urllib.request

    for var in ("REMORA_MCP_PROFILE", "REMORA_PROFILE", "REMORA_WORKER_URL", "RAG_WORKER_URL",
                "LAW_SEARCH_WORKER_URL", "AGENT_CONTROL_URL", "AGENT_CONTROL_SECRET",
                "CODEGRAPH_URL", "REPO_SEARCH_URL"):
        monkeypatch.delenv(var, raising=False)

    def _no_network(*_a, **_k):  # pragma: no cover - must never run
        raise AssertionError("the MCP server touched the network")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    sys.modules.pop("servers.mcp_remora", None)
    mcp = importlib.import_module("servers.mcp_remora")
    try:
        assert set(mcp.HANDLERS) == {t["name"] for t in mcp.TOOLS}
        assert "update_work_order" not in mcp.HANDLERS
        unknown = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "update_work_order",
                                                 "arguments": {"work_order_id": "WO-1"}}})
        assert unknown["error"]["code"] == -32602 and "Unknown tool" in unknown["error"]["message"]
        forwarded = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": "agent_execute_tool",
                                                   "arguments": {"tool": "store_artifact",
                                                                 "arguments": {}}}})
        assert "AGENT_CONTROL_URL" in forwarded["result"]["content"][0]["text"]
    finally:
        sys.modules.pop("servers.mcp_remora", None)
    assert _executor.registry.CALLS == []


def test_a_tool_served_by_an_mcp_server_outside_remora_is_unknown_to_the_execution_api(_executor):  # noqa: F811
    """The in-repository analogue of the SDD's last probe: a lease for a tool
    no registry in this process serves is refused as unknown_tool before
    anything runs. A tool reachable only through a foreign MCP server has no
    callable here, so the execution API cannot be made to run it."""
    from tests.test_dispatch_leased_endpoint import _lease as _plain_lease

    call = dict(CALL, tool_name="ext_mcp.search", arguments={"q": "anything"})
    body = _post(_executor, _plain_lease(_executor, call=call), call=call).json()
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] == "unknown_tool", body
    assert _executor.registry.CALLS == []
