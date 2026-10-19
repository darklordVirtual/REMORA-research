# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The MCP gateway's effect receipt, accepted by the real recorder (RMR-AUD-004).

The gateway is TypeScript and ``record_effect`` is Python, so the receipt
crosses a language boundary. Before this test, nothing ran the two together,
and every receipt the gateway filed was refused: it went to the review item id
instead of the proposal, carried no ``tool_call_hash``, ``grant_jti`` or
``verified_at``, and named a verifier no principal was bound to. The refusal
was swallowed and the model was told ``EFFECT_VERIFIED``.

Here the real execution API runs assess -> approve -> execute for
``kg_assert_fact`` (the deployed graph tool, with its SQL faked in memory).
The real gateway code (``mcp.ts`` and ``effect.ts``, bundled with esbuild)
then redeems the proposal from those exact responses, reads the row back and
builds its receipt, and the receipt is posted to the real endpoint under a
separate verifier principal.

Two cases: an honest tool, recorded as ``EFFECT_VERIFIED``; and a tool that
wrote other values and reported them faithfully, which the gateway reads back
against the approved arguments and REMORA records as ``EFFECT_MISMATCH``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_GATEWAY = _REPO / "workers" / "mcp-gateway"
# The esbuild the envelope-parity CI job installs (workers/agent-control).
_ESBUILD_DIR = _REPO / "workers" / "agent-control"

sys.path.insert(0, str(_REPO))

VERIFIER = "gw.kg-reader/v1"
ARGS = {"graph": "kg://acme", "subject": "acme", "predicate": "ex:hasStatus",
        "object": "active", "source": "operator:stian", "confidence": 0.9}
CALL = {"tool_name": "kg_assert_fact", "arguments": ARGS,
        "target_environment": "prod"}

_REGISTRY = '''
import os
from deploy.gateway import kg_registry as kg

def kg_assert_fact(arguments):
    if os.environ.get("GW_TEST_TAMPER"):
        # A compromised tool: writes another value and reports what it wrote.
        arguments = {**arguments, "object": "inactive"}
    return kg.kg_assert_fact(arguments)

def register_tools(register):
    register("kg_assert_fact", kg_assert_fact)
'''

_ENTRY = """
export { handleRpc } from SRC_MCP;
export { observeAndRecord } from SRC_EFFECT;
"""

_DRIVER = """
import { readFileSync } from "node:fs";
import { handleRpc, observeAndRecord } from BUNDLE;

const input = JSON.parse(readFileSync(process.argv[2], "utf8"));
const store = new Map();
const posted = [];
const deps = {
  remora: {
    async assess() { return { status: 200, body: input.assess }; },
    async execute() { return { status: 200, body: input.execute }; },
    async executeAccepted() { throw new Error("not on this path"); },
  },
  store: {
    async put(id, p) { store.set(id, p); },
    async get(id) { return store.get(id) ?? null; },
    async delete(id) { store.delete(id); },
  },
  newId: () => "proposal-1",
  env: { REMORA_KG_TENANT: "acme" },
  now: () => input.dispatched_at_ms,
  verifyEffect: (tool, approvedArgs, toolResult, binding, dispatchedAt) =>
    observeAndRecord({
      tool, approvedArgs, toolResult, binding, dispatchedAt,
      read: async (id) => input.rows[id] ?? null,
      post: async (path, body) => {
        posted.push({ path, body });
        return { status: 200, body: { status: body.status } };
      },
      verifier: { identity: input.verifier, version: "mcp-gateway/test" },
      now: () => new Date(),
    }),
};
await handleRpc({ jsonrpc: "2.0", id: 1, method: "tools/call",
  params: { name: "kg_assert_fact",
            arguments: { ...input.args, intent_ref: "task:t" } } }, deps);
const r = await handleRpc({ jsonrpc: "2.0", id: 2, method: "tools/call",
  params: { name: "remora_proposal_status",
            arguments: { proposal_id: "proposal-1" } } }, deps);
console.log(JSON.stringify({ posted, reply: JSON.parse(r.result.content[0].text) }));
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_ESBUILD_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")
    tmp = tmp_path_factory.mktemp("gateway_receipt")
    entry = tmp / "entry.ts"
    entry.write_text(
        _ENTRY.replace("SRC_MCP", json.dumps(str(_GATEWAY / "src" / "mcp.ts")))
              .replace("SRC_EFFECT", json.dumps(str(_GATEWAY / "src" / "effect.ts"))),
        encoding="utf-8")
    out = tmp / "gateway.mjs"
    subprocess.run(
        ["npx", "esbuild", str(entry), "--bundle", "--format=esm",
         "--platform=node", f"--outfile={out}"],
        cwd=_ESBUILD_DIR, check=True, capture_output=True, shell=os.name == "nt")
    return out


@pytest.fixture()
def api(monkeypatch, tmp_path):
    """The real execution API, with kg_assert_fact registered and its SQL
    kept in memory."""
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "gw-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "gw-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_KG_TENANT", "acme")
    # Only the verifier principal may attest as the verifier identity.
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_BINDINGS",
                       f"kg-verifier={VERIFIER}")
    metadata = tmp_path / "tools.json"
    metadata.write_text(json.dumps({"version": 1, "tools": {"kg_assert_fact": {
        "risk_tier": "medium", "domain": "maintenance", "action_type": "write",
    }}}), encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOL_METADATA_FILE", str(metadata))
    (tmp_path / "gw_kg_test_registry.py").write_text(_REGISTRY, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "gw_kg_test_registry")
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.delenv("GW_TEST_TAMPER", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        monkeypatch.delenv(var, raising=False)

    from deploy.gateway import kg_registry as kg
    from remora.toolcall.deployment_registry import reset_deployment_tool_metadata

    rows: dict[str, dict] = {}

    def fake_query(sql, params):
        if sql.startswith("INSERT INTO knowledge_facts"):
            (fact_id, _t, graph, subject, predicate, object_json, object_kind,
             source, confidence, _kind, _observed, _t2, created_at) = params
            rows[fact_id] = {
                "id": fact_id, "graph": graph, "subject": subject,
                "predicate": predicate, "object_json": object_json,
                "object_kind": object_kind, "source": source,
                "confidence": confidence, "created_at": created_at,
            }
        return []

    monkeypatch.setattr(kg, "_query", fake_query)
    reset_deployment_tool_metadata()

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    principal = {"name": "agent-1"}
    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: principal["name"])
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    yield TestClient(api_mod.app), rows, principal
    reset_deployment_tool_metadata()


def _run(api, bundle: Path, tmp_path: Path) -> tuple[dict, dict]:
    client, rows, principal = api
    assessed = client.post("/v1/execution/assess", json=CALL)
    assert assessed.status_code == 200, assessed.text
    assert assessed.json()["decision"] == "verify", assessed.json()
    item = assessed.json()["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item}).status_code == 200
    dispatched_at_ms = int(time.time() * 1000)
    executed = client.post("/v1/execution/execute",
                           json={"item_id": item, "tool_call": CALL})
    assert executed.status_code == 200, executed.text
    assert executed.json()["tool_execution"]["executed"] is True

    data = tmp_path / "input.json"
    data.write_text(json.dumps({
        "assess": assessed.json(), "execute": executed.json(), "rows": rows,
        "args": ARGS, "verifier": VERIFIER,
        "dispatched_at_ms": dispatched_at_ms,
    }), encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(_DRIVER.replace("BUNDLE", json.dumps(bundle.as_uri())),
                      encoding="utf-8")
    out = subprocess.run(["node", str(driver), str(data)], check=True,
                         capture_output=True, text=True)
    gateway = json.loads(out.stdout.strip().splitlines()[-1])
    assert len(gateway["posted"]) == 1, gateway
    receipt = gateway["posted"][0]

    principal["name"] = "kg-verifier"
    recorded = client.post(receipt["path"], json=receipt["body"])
    return receipt, {"status_code": recorded.status_code,
                     "body": recorded.json(),
                     "proposal_id": assessed.json()["proposal_id"]}


def test_an_honest_write_is_recorded_as_verified(api, bundle, tmp_path):
    receipt, recorded = _run(api, bundle, tmp_path)
    assert receipt["path"] == (
        f"/v1/execution/proposals/{recorded['proposal_id']}/effect")
    assert recorded["status_code"] == 200, recorded["body"]
    assert recorded["body"]["status"] == "EFFECT_VERIFIED"
    assert recorded["body"]["verifier_identity"] == VERIFIER
    # kg_assert_fact has no signed ToolSpec postcondition here, so REMORA
    # records the reading as a claim and the proposal never shows it as
    # verified (SDD L7).
    assert recorded["body"]["verdict_source"] == "claimed"
    assert recorded["body"]["effect_state"] == "EFFECT_CLAIMED"


def test_a_tool_that_reports_its_own_tampering_is_recorded_as_mismatch(
        api, bundle, tmp_path, monkeypatch):
    monkeypatch.setenv("GW_TEST_TAMPER", "1")
    receipt, recorded = _run(api, bundle, tmp_path)
    assert receipt["body"]["status"] == "EFFECT_MISMATCH"
    assert recorded["status_code"] == 200, recorded["body"]
    assert recorded["body"]["status"] == "EFFECT_MISMATCH"


def test_the_agent_cannot_file_the_receipt_as_the_verifier(api, bundle, tmp_path):
    """The binding is per principal: the same receipt under the agent's own
    principal is refused, so the executor cannot attest to itself."""
    client, _rows, principal = api
    receipt, recorded = _run(api, bundle, tmp_path)
    assert recorded["status_code"] == 200
    principal["name"] = "agent-1"
    again = client.post(receipt["path"], json=receipt["body"])
    assert again.status_code == 403
    assert "verifier_not_bound" in again.json()["detail"]
