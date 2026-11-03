# SPDX-License-Identifier: BUSL-1.1
"""W-01 / F-02: write-effect tools never execute inside the agent-control Worker.

Without a bound canonical execution service (EXECUTION_SERVICE plus
EXECUTION_API_TOKEN) the Worker used to run store_artifact locally after a
human approval, writing to R2 outside the canonical assess -> grant -> PEP ->
lease path. That is a second write path, which the single-authoritative-
execution-path ADR rules out.

Drives the REAL Worker fetch handler (esbuild bundle, node) with an in-memory
D1 and an R2 bucket that records every put. Pins:

- an unbound write-effect call is refused with a governance record and no
  R2 put, with or without an approval reference;
- a read-only tool that deployment config added to the approval list keeps
  the local approval flow (it has no write effect);
- with the canonical service bound, the write goes to that service and the
  Worker's own R2 binding is still never touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKER_DIR = _REPO_ROOT / "workers" / "agent-control"

_DRIVER = r"""
import worker from BUNDLE;

function fakeD1() {
  const rows = { envelopes: [] };
  let nextId = 1;
  const stmt = (sql) => {
    let args = [];
    const s = {
      bind: (...a) => { args = a; return s; },
      first: async () => {
        if (/RETURNING id/i.test(sql)) return { id: nextId++ };
        return null;
      },
      run: async () => {
        if (/INSERT INTO decision_envelopes/i.test(sql)) rows.envelopes.push(args);
        return { success: true, meta: { changes: 1, last_row_id: nextId } };
      },
      all: async () => ({ results: [] }),
    };
    return s;
  };
  return {
    rows,
    prepare: stmt,
    batch: async (stmts) => Promise.all(stmts.map((s) => s.run())),
  };
}

function fakeR2() {
  const puts = [];
  return { puts, put: async (key, value) => { puts.push(key); return {}; } };
}

const SECRET = "test-control-secret";

async function execute(env, body) {
  const res = await worker.fetch(
    new Request("https://agent-control.test/execute", {
      method: "POST",
      headers: { Authorization: `Bearer ${SECRET}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    env,
  );
  let payload = null;
  try { payload = await res.json(); } catch {}
  return { status: res.status, payload };
}

function baseEnv(extra = {}) {
  return {
    CONTROL_SECRET: SECRET,
    AUDIT_DB: fakeD1(),
    ARTIFACTS: fakeR2(),
    SESSIONS: { get: async () => null, put: async () => {} },
    APPROVAL_REQUIRED_TOOLS: "",
    TENANT_ID: "default",
    TARGET_ENVIRONMENT: "cloudflare_worker",
    LAW_SERVICE: { fetch: async () => new Response(JSON.stringify({ hits: [] }), { status: 200 }) },
    ...extra,
  };
}

const write = { tool: "store_artifact", session_id: "s1",
                input: { key: "a.md", content: "hello" } };
const results = {};

{
  const env = baseEnv();
  results.unbound = await execute(env, write);
  results.unbound_puts = env.ARTIFACTS.puts.length;
  results.unbound_envelopes = env.AUDIT_DB.rows.envelopes.length;
}

{
  // Presenting an approval reference must not reopen the local path.
  const env = baseEnv();
  results.unbound_with_approval = await execute(env, {
    ...write, input: { ...write.input, audit_id: 1 },
  });
  results.unbound_with_approval_puts = env.ARTIFACTS.puts.length;
}

{
  // Token without service, and service without token, are both "unbound".
  const halfA = baseEnv({ EXECUTION_API_TOKEN: "tok" });
  const halfB = baseEnv({ EXECUTION_SERVICE: { fetch: async () => { throw new Error("unused"); } } });
  results.half_token = (await execute(halfA, write)).status;
  results.half_service = (await execute(halfB, write)).status;
  results.half_puts = halfA.ARTIFACTS.puts.length + halfB.ARTIFACTS.puts.length;
}

{
  // A read-only tool added to the approval list keeps the local approval gate.
  const env = baseEnv({ APPROVAL_REQUIRED_TOOLS: "dce_search_law" });
  results.config_gated_read = await execute(env, {
    tool: "dce_search_law", session_id: "s2", input: { query: "personvern" },
  });
}

{
  // Bound: the canonical service executes; the Worker's R2 stays untouched.
  const calls = [];
  const env = baseEnv({
    EXECUTION_API_TOKEN: "tok",
    EXECUTION_SERVICE: {
      fetch: async (url, init) => {
        calls.push(String(url));
        if (String(url).endsWith("/assess")) {
          return new Response(JSON.stringify({
            decision: "accept", proposal_id: "p1",
            execution_token: { jti: "j1", action: "accept" },
          }), { status: 200 });
        }
        return new Response(JSON.stringify({
          tool_execution: { executed: true, result: { ok: 1 } },
        }), { status: 200 });
      },
    },
  });
  results.bound = await execute(env, write);
  results.bound_puts = env.ARTIFACTS.puts.length;
  results.bound_calls = calls.length;
}

console.log(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def outcome(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_WORKER_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")
    tmp = tmp_path_factory.mktemp("agent_control_no_local_write")
    bundle = tmp / "index.mjs"
    subprocess.run(
        ["npx", "esbuild", str(_WORKER_DIR / "src" / "index.ts"),
         "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}"],
        cwd=_WORKER_DIR, check=True, capture_output=True, shell=os.name == "nt",
    )
    driver = tmp / "driver.mjs"
    driver.write_text(_DRIVER.replace("BUNDLE", json.dumps(bundle.as_uri())), encoding="utf-8")
    result = subprocess.run(["node", str(driver)], cwd=_WORKER_DIR, check=True,
                            capture_output=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_unbound_write_is_refused_without_touching_r2(outcome: dict) -> None:
    assert outcome["unbound"]["status"] == 503
    assert outcome["unbound"]["payload"]["output"]["status"] == "CANONICAL_EXECUTION_UNBOUND"
    assert outcome["unbound_puts"] == 0


def test_unbound_refusal_is_recorded_as_a_governance_envelope(outcome: dict) -> None:
    assert outcome["unbound_envelopes"] == 1


def test_an_approval_reference_does_not_reopen_the_local_write_path(outcome: dict) -> None:
    assert outcome["unbound_with_approval"]["status"] == 503
    assert outcome["unbound_with_approval_puts"] == 0


def test_half_configured_canonical_binding_counts_as_unbound(outcome: dict) -> None:
    assert outcome["half_token"] == 503
    assert outcome["half_service"] == 503
    assert outcome["half_puts"] == 0


def test_config_gated_read_tool_keeps_local_approval_flow(outcome: dict) -> None:
    assert outcome["config_gated_read"]["status"] == 402
    assert outcome["config_gated_read"]["payload"]["output"]["status"] == "APPROVAL_REQUIRED"


def test_bound_write_runs_through_canonical_service_only(outcome: dict) -> None:
    assert outcome["bound"]["status"] == 200
    assert outcome["bound"]["payload"]["canonical"] is True
    assert outcome["bound_calls"] == 2
    assert outcome["bound_puts"] == 0
