# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""ADR migration step 3: agent-control's canonical-execution adapter.

Executes the REAL TypeScript adapter (esbuild+node) against a fake canonical
service. Pins: accept -> execute-accepted under the returned token;
verify/escalate -> canonical review item surfaced, nothing executes locally;
every failure shape refuses (no fallback to in-worker execution); a
transport failure AFTER the token was sent reports state-unknown and never
retries.
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

_DRIVER = """
import { canonicalExecutionConfigured, executeViaCanonicalService } from BUNDLE;


const results = {};
const CALL = ["store_artifact", {key: "a.md", content: "x"}, "cloudflare_worker"];

function service(handler) {
  return {
    EXECUTION_API_TOKEN: "tok",
    EXECUTION_SERVICE: { fetch: async (url, init) => handler(url, init) },
  };
}
function jsonResp(status, body) {
  return new Response(JSON.stringify(body), {status});
}

results.unconfigured = canonicalExecutionConfigured({});
results.configured = canonicalExecutionConfigured(service(() => jsonResp(200, {})));

// accept path: assess -> execute-accepted with the SAME token; real dispatch
{
  const calls = [];
  const env = service(async (url, init) => {
    calls.push({url, body: JSON.parse(init.body), auth: init.headers.Authorization});
    if (url.endsWith("/assess")) {
      return jsonResp(200, {decision: "accept", proposal_id: "p1",
                            execution_token: {jti: "j1", action: "accept"}});
    }
    return jsonResp(200, {tool_execution: {executed: true, result: {ok: 1}}});
  });
  results.accept = await executeViaCanonicalService(env, ...CALL);
  results.accept_calls = calls;
}

// verify path: review item surfaced, nothing executed
{
  const env = service(async (url) => url.endsWith("/assess")
    ? jsonResp(200, {decision: "verify", proposal_id: "p2", review_item_id: "ri-9"})
    : jsonResp(500, {}));
  results.verify = await executeViaCanonicalService(env, ...CALL);
}

// abstain refuses
{
  const env = service(async () => jsonResp(200, {decision: "abstain", proposal_id: "p3"}));
  results.abstain = await executeViaCanonicalService(env, ...CALL);
}

// accept without token refuses (never executes on faith)
{
  const env = service(async () => jsonResp(200, {decision: "accept", proposal_id: "p4"}));
  results.accept_no_token = await executeViaCanonicalService(env, ...CALL);
}

// canonical execute refusal propagates the named reason
{
  const env = service(async (url) => url.endsWith("/assess")
    ? jsonResp(200, {decision: "accept", proposal_id: "p5",
                     execution_token: {jti: "j5"}})
    : jsonResp(200, {tool_execution: {executed: false,
                     refusal_reason: "token_already_consumed"}}));
  results.execute_refused = await executeViaCanonicalService(env, ...CALL);
}

// transport failure AFTER token sent: state unknown, no retry
{
  let attempts = 0;
  const env = service(async (url) => {
    if (url.endsWith("/assess")) {
      return jsonResp(200, {decision: "accept", proposal_id: "p6",
                            execution_token: {jti: "j6"}});
    }
    attempts += 1;
    throw new Error("connection reset");
  });
  results.transport_unknown = await executeViaCanonicalService(env, ...CALL);
  results.transport_attempts = attempts;
}

// assess unreachable refuses
{
  const env = service(async () => { throw new Error("down"); });
  results.assess_unreachable = await executeViaCanonicalService(env, ...CALL);
}

console.log(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def outcome(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_WORKER_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")
    tmp = tmp_path_factory.mktemp("canonical_adapter")
    bundle = tmp / "adapter.mjs"
    subprocess.run(
        ["npx", "esbuild", str(_WORKER_DIR / "src" / "execution_adapter.ts"),
         "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}"],
        cwd=_WORKER_DIR, check=True, capture_output=True, shell=os.name == "nt",
    )
    driver = tmp / "driver.mjs"
    driver.write_text(
        _DRIVER.replace("BUNDLE", json.dumps(bundle.as_uri())), encoding="utf-8"
    )
    result = subprocess.run(["node", str(driver)], cwd=_WORKER_DIR, check=True,
                            capture_output=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_adapter_inactive_without_binding(outcome: dict) -> None:
    assert outcome["unconfigured"] is False
    assert outcome["configured"] is True


def test_accept_dispatches_via_canonical_path(outcome: dict) -> None:
    assert outcome["accept"]["executed"] is True
    assert outcome["accept"]["proposal_id"] == "p1"
    calls = outcome["accept_calls"]
    assert calls[0]["url"].endswith("/v1/execution/assess")
    assert calls[1]["url"].endswith("/v1/execution/execute-accepted")
    assert calls[1]["body"]["execution_token"]["jti"] == "j1"
    assert all(c["auth"] == "Bearer tok" for c in calls)


def test_verify_surfaces_canonical_review_and_never_executes(outcome: dict) -> None:
    v = outcome["verify"]
    assert v["executed"] is False
    assert v["review_item_id"] == "ri-9"
    assert v["refusal_reason"] == "canonical_review_required"


def test_abstain_and_tokenless_accept_refuse(outcome: dict) -> None:
    assert outcome["abstain"]["executed"] is False
    assert outcome["accept_no_token"]["refusal_reason"] == "canonical_accept_without_token"


def test_canonical_refusal_reason_propagates(outcome: dict) -> None:
    assert outcome["execute_refused"]["executed"] is False
    assert outcome["execute_refused"]["refusal_reason"] == "token_already_consumed"


def test_transport_failure_after_token_is_unknown_and_never_retried(outcome: dict) -> None:
    t = outcome["transport_unknown"]
    assert t["executed"] is False
    assert t["refusal_reason"] == "canonical_execute_unreachable_state_unknown"
    assert outcome["transport_attempts"] == 1


def test_assess_unreachable_refuses(outcome: dict) -> None:
    assert outcome["assess_unreachable"]["refusal_reason"] == "canonical_service_unreachable"
