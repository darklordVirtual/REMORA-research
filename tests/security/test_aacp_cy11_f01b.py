# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AACP-CY-11 and AACP-F-01 (ACCEPT path), found by AACP binding remora-428b823.

CY-11: a signed ToolSpec pins a callable digest measured from source text,
while the code that runs is a code object compiled earlier. Loading other
bytes and putting the pinned bytes back on disk passed registration, and the
substituted code dispatched. Measurement now requires the measured text to
compile to the code that runs (``toolspec_callable_source_mismatch``).

F-01b: an ACCEPT token bound the call but not the plan premises it was
decided on, so after the state moved a caller could present a plan that reads
the new revision and execute. The token now binds ``plan_hash``.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import secrets
import shutil
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from remora.toolcall.callable_digest import (
    CallableSourceMismatch,
    closure_digest,
    source_digest,
)
from remora.toolcall.toolspec import ToolSpecRefused

GOOD = "def tool(arguments):\n    return 'good'\n"
EVIL = "def tool(arguments):\n    marker = 'substituted'\n    return 'evil'\n"


# ---------------------------------------------------------------- CY-11

@pytest.fixture()
def artifact(tmp_path, monkeypatch):
    pkg = f"cy11_{secrets.token_hex(4)}"
    d = tmp_path / pkg
    d.mkdir()
    (d / "__init__.py").write_text("")
    path = d / "tool.py"
    path.write_text(GOOD)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield pkg, path
    for k in [k for k in sys.modules if k.startswith(pkg)]:
        del sys.modules[k]


def _load(pkg):
    sys.modules.pop(f"{pkg}.tool", None)
    importlib.invalidate_caches()
    return importlib.import_module(f"{pkg}.tool")


def _swap(pkg, path):
    """Other bytes into memory, the pinned bytes back on disk."""
    path.write_text(EVIL)
    shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)
    evil = _load(pkg)
    assert evil.tool({}) == "evil"
    path.write_text(GOOD)
    return evil


def _signed_runtime(digest):
    from remora.enforcement.lease import GovernedToolDispatcher
    from remora.toolcall.runtime_surface import RuntimeTool, canonical_json
    from remora.toolcall.signed_surface_runtime import SignedSurfaceRuntime
    from remora.toolcall.toolspec import sign_bundle

    raw = dict(tool_id="write", version=1, callable_digest=digest,
               implementation_identity="cy11-v1", description="Write.",
               argument_schema={"type": "object", "properties": {"value": {"type": "integer"}},
                                "required": ["value"], "additionalProperties": False},
               risk_tier="medium", action_type="write", domain="general", capabilities=["record"],
               semantic_contract={"effect": "update"}, credential_scope=["local-record:write"],
               allowed_targets=["local-record"], idempotency_contract={"safe_to_retry": False},
               postcondition_reader="local-reader", compensation_tool=None,
               timeout_policy={"dispatch_timeout_seconds": 10}, network_policy={"egress": "none"},
               signing_identity="cy11-signer")
    key = secrets.token_hex(32)
    bundle = sign_bundle({"schema_version": 1, "tool_specs": [raw]}, key=key,
                         signing_identity="cy11-signer", signed_at=datetime.now(UTC).isoformat())
    runtime = SignedSurfaceRuntime(GovernedToolDispatcher("reference-policy"), bundle, key=key,
                                   trusted_identities=["cy11-signer"], mode="shadow")
    spec = runtime._bundle.get("write")
    observed = RuntimeTool("write", "native", True, True, spec.toolspec_hash,
                           implementation_identity="cy11-v1",
                           argument_schema_json=canonical_json(raw["argument_schema"]))
    return runtime, observed


@pytest.mark.parametrize("measure", [source_digest, closure_digest], ids=["source", "closure"])
def test_swapped_bytes_are_refused_at_registration(artifact, measure):
    pkg, path = artifact
    good = _load(pkg)
    pinned = measure(good.tool)
    runtime, observed = _signed_runtime(pinned)
    runtime.register(observed, good.tool)  # the unchanged artifact still registers
    evil = _swap(pkg, path)
    with pytest.raises(ToolSpecRefused) as refusal:
        _signed_runtime(pinned)[0].register(observed, evil.tool)
    assert refusal.value.reason_code == "toolspec_callable_source_mismatch"


@pytest.mark.parametrize("measure", [source_digest, closure_digest], ids=["source", "closure"])
def test_measuring_swapped_code_raises(artifact, measure):
    pkg, path = artifact
    evil = _swap(pkg, path)
    with pytest.raises(CallableSourceMismatch):
        measure(evil.tool)


def test_source_digest_value_is_unchanged_for_unchanged_code(artifact):
    """Bundles already signed keep verifying: the digest is of the same text."""
    pkg, _ = artifact
    good = _load(pkg)
    expected = "sha256:" + hashlib.sha256(inspect.getsource(good.tool).encode()).hexdigest()
    assert source_digest(good.tool) == expected


def test_the_research_registry_tools_still_measure():
    import servers.tool_registry_research as registry
    for fn in (registry.store_artifact, registry.read_telemetry):
        assert source_digest(fn).startswith("sha256:")
        assert closure_digest(fn).startswith("closure-sha256:")


def test_a_wrapped_callable_is_measured_through_its_wrapper(artifact):
    import functools
    pkg, _ = artifact
    good = _load(pkg)

    @functools.wraps(good.tool)
    def wrapper(arguments):
        return good.tool(arguments)

    # The wrapper's own code lives in this test file and matches it; the
    # unwrapped tool matches its own file. Neither is a false mismatch.
    source_digest(wrapper)
    closure_digest(good.tool)


def test_a_helper_swapped_in_memory_is_refused_by_the_closure_digest(tmp_path, monkeypatch):
    pkg = f"cy11h_{secrets.token_hex(4)}"
    root = tmp_path / pkg
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "helper.py").write_text("def scale(x):\n    return x * 2\n")
    (root / "tool.py").write_text(f"from {pkg}.helper import scale\n\ndef run(a):\n    return scale(a)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    tool = importlib.import_module(f"{pkg}.tool")
    pinned = closure_digest(tool.run)
    helper = sys.modules[f"{pkg}.helper"]
    helper.scale = types.FunctionType(
        compile("def scale(x):\n    return x * 1000\n", helper.__file__, "exec").co_consts[0],
        vars(helper), "scale")
    with pytest.raises(CallableSourceMismatch):
        closure_digest(tool.run)
    del helper.scale
    import importlib as _il
    _il.reload(helper)
    assert closure_digest(tool.run) == pinned


# ---------------------------------------------------------------- F-01b

@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "f01b-key-" + "0" * 32)
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    from fastapi.testclient import TestClient

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    revisions = {"workorder/WO-1": "7"}
    state = types.ModuleType("f01b_state")
    state.read_revision = lambda resource: revisions[resource]
    monkeypatch.setitem(sys.modules, "f01b_state", state)
    monkeypatch.setenv("REMORA_STATE_REVISION_MODULE", "f01b_state")
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    yield TestClient(api_mod.app, raise_server_exceptions=False), revisions, tmp_path / "art"
    exec_mod._reset_tool_dispatcher()


def _call(artifact_id, revision=None):
    call = {"tool_name": "store_artifact",
            "arguments": {"artifact_id": artifact_id, "content": {"x": 1}},
            "target_environment": "staging"}
    if revision is not None:
        call["plan"] = {"plan_id": f"plan-{artifact_id}", "reads": {"workorder/WO-1": revision},
                        "depends_on": ["workorder/WO-1"]}
    return call


def _mint(call):
    """As assess_proposal's ACCEPT branch mints it, plan binding included."""
    import servers.execution_api as exec_mod
    from remora.enforcement.token import PolicyDecisionToken
    from remora.execution.service import authorization_context, observation_binding, plan_hash_of

    tool_call = exec_mod.ToolCallRequest(**call)
    obs, semantic = exec_mod._observation_with_context(tool_call, "acme")
    now = datetime.now(UTC)
    return PolicyDecisionToken.issue(
        action="accept", observation_hash=observation_binding(obs), request_id="f01b",
        issued_at=now.isoformat(), expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
        context=authorization_context(
            tenant="acme", principal="agent-1", semantic=semantic,
            target_environment=call.get("target_environment", ""),
            policy_bundle_hash=exec_mod._current_policy_bundle_hash(),
            toolspec_hash=str(exec_mod._resolve_toolspec(
                call["tool_name"], call["arguments"], call["target_environment"])["hash"]),
            plan_hash=plan_hash_of(tool_call))).to_dict()


def _redeem(client, token, call):
    return client.post("/v1/execution/execute-accepted",
                       json={"execution_token": token, "tool_call": call})


def _written(art, artifact_id):
    return (art / f"{artifact_id}.json").exists()


def test_a_token_for_the_current_plan_executes(api):
    client, _, art = api
    call = _call("f01b-ok", "7")
    r = _redeem(client, _mint(call), call)
    assert r.status_code == 200 and _written(art, "f01b-ok"), r.text


def test_a_plan_rewritten_after_the_state_moved_is_refused_unspent(api):
    client, revisions, art = api
    token = _mint(_call("f01b", "7"))
    revisions["workorder/WO-1"] = "8"
    r = _redeem(client, token, _call("f01b", "8"))
    assert r.status_code == 409 and "context_mismatch" in r.text, r.text
    assert not _written(art, "f01b")
    # The grant was not spent by the refusal: presented as decided, it is
    # refused for the stale premise, not as a replay.
    stale = _redeem(client, token, _call("f01b", "7"))
    assert "stale_plan" in stale.text and not _written(art, "f01b"), stale.text


def test_adding_or_dropping_a_plan_after_the_decision_is_refused(api):
    client, _, art = api
    with_plan = _mint(_call("f01b-add", "7"))
    assert _redeem(client, with_plan, _call("f01b-add")).status_code == 409
    without = _mint(_call("f01b-drop"))
    assert _redeem(client, without, _call("f01b-drop", "7")).status_code == 409
    assert not _written(art, "f01b-add") and not _written(art, "f01b-drop")


def test_a_call_without_a_plan_hashes_as_before():
    from remora.enforcement.token import AuthorizationContext
    from remora.execution.service import authorization_context

    kwargs = dict(tenant="acme", principal="p", semantic={}, target_environment="staging",
                  policy_bundle_hash="b", toolspec_hash="t")
    legacy = AuthorizationContext(tenant="acme", principal="p", target_environment="staging",
                                  policy_bundle_hash="b", toolspec_hash="t")
    assert authorization_context(**kwargs).hash() == legacy.hash()
    assert authorization_context(**kwargs, plan_hash="a" * 64).hash() != legacy.hash()
    assert "plan_hash" not in authorization_context(**kwargs).to_dict()


def test_the_token_assess_mints_binds_the_plan(api, monkeypatch):
    """The ACCEPT branch of /assess itself binds the plan, not only a test mint."""
    import servers.execution_api as exec_mod
    from remora.enforcement.token import PolicyDecisionToken
    from remora.policy.decision_engine import RemoraDecisionEngine

    client, revisions, _ = api
    monkeypatch.setattr(exec_mod, "_ENGINE", RemoraDecisionEngine(
        execution_profile=True, low_consequence_accept=True))
    plan = {"plan_id": "plan-read", "reads": {"workorder/WO-1": "7"}, "depends_on": ["workorder/WO-1"]}
    call = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
            "target_environment": "staging", "plan": plan}
    def assess():
        assessed = client.post("/v1/execution/assess", json=call).json()
        if assessed.get("decision") != "accept" or not assessed.get("execution_token"):
            pytest.fail(f"precondition: /assess did not mint an ACCEPT token: {assessed}")
        return assessed["execution_token"]

    # Honest: the token /assess minted redeems with the plan it was decided on.
    honest = _redeem(client, assess(), call)
    assert honest.status_code == 200 and honest.json()["tool_execution"]["executed"], honest.text
    token = assess()
    from remora.execution.service import plan_hash_of
    expected = PolicyDecisionToken.from_dict(token).context_hash
    assert expected  # the context, plan included, is signed into the grant
    revisions["workorder/WO-1"] = "8"
    refreshed = dict(call, plan=dict(plan, reads={"workorder/WO-1": "8"}))
    r = _redeem(client, token, refreshed)
    assert r.status_code == 409 and "context_mismatch" in r.text, r.text
    assert plan_hash_of(exec_mod.ToolCallRequest(**call))
