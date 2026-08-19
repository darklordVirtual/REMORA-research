# SPDX-License-Identifier: BUSL-1.1
"""No-self-approval regression suite for the agent-control Worker (Phase 1).

Executes the REAL TypeScript approval/auth modules (bundled with the esbuild
vendored in the worker directory) rather than a Python reimplementation, so
these tests pin the deployed guard behavior, not a copy of it. Skips without
node/esbuild; CI's worker-envelope-parity job pattern guarantees a JS runtime
where it matters.

Covers the mandatory regression matrix:
  - same bearer/principal cannot self-approve
  - workload credential cannot act as reviewer (approved_by/user_id have no
    identity path at all — identity is credential-derived only)
  - cross-tenant approval is rejected
  - approval for modified arguments is rejected
  - expired approval is rejected
  - approval under stale ToolSpec is rejected
  - approval under stale policy bundle is rejected
  - valid independent reviewer approval succeeds
  - approval is single-use (replay refused)
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
_APPROVAL_TS = _WORKER_DIR / "src" / "approval.ts"

_DRIVER = r"""
import {
  grantApproval, consumeApproval, MemoryApprovalStore,
} from BUNDLE_APPROVAL;
import { authenticate } from BUNDLE_AUTH;

const results = {};

function store(withProposal = true) {
  const s = new MemoryApprovalStore();
  if (withProposal) {
    s.proposals.set(1, {
      proposalId: 1, tenantId: "t1",
      requesterPrincipal: "control_secret_bearer",
      toolName: "store_artifact", toolCallHash: "hash-A",
    });
  }
  return s;
}

const reviewer = {
  tenantId: "t1", principalId: "reviewer@example.com",
  principalType: "human", roles: ["reviewer"], authMethod: "test",
};
const workload = {
  tenantId: "t1", principalId: "control_secret_bearer",
  principalType: "workload", roles: ["workload"], authMethod: "shared_bearer",
};
const grantArgs = {
  proposalId: 1, decision: "approved", reasonCode: "ok",
  toolspecHash: "ts-1", toolspecVersion: "v1", policyBundleHash: "pb-1",
};
const consumeArgs = {
  proposalId: 1, tenantId: "t1", toolCallHash: "hash-A",
  toolspecHash: "ts-1", policyBundleHash: "pb-1",
};

// 1. Workload principal (the proposing bearer) cannot approve at all.
results.workload_cannot_approve = await grantApproval(store(), workload, grantArgs);

// 2. Human whose identity equals the requester cannot self-approve.
const selfReviewer = { ...reviewer, principalId: "control_secret_bearer" };
results.same_principal_cannot_self_approve =
  await grantApproval(store(), selfReviewer, grantArgs);

// 3. Human without the reviewer role cannot approve.
results.missing_role_rejected =
  await grantApproval(store(), { ...reviewer, roles: [] }, grantArgs);

// 4. Reviewer from another tenant cannot approve.
results.cross_tenant_grant_rejected =
  await grantApproval(store(), { ...reviewer, tenantId: "t2" }, grantArgs);

// 5. Valid independent reviewer approval succeeds, then consumes exactly once.
{
  const s = store();
  results.valid_grant = await grantApproval(s, reviewer, grantArgs);
  results.valid_consume = await consumeApproval(s, consumeArgs);
  results.replay_consume = await consumeApproval(s, consumeArgs);
}

// 6. Consumption with modified arguments (different tool-call hash) refused.
{
  const s = store();
  await grantApproval(s, reviewer, grantArgs);
  results.modified_args_rejected =
    await consumeApproval(s, { ...consumeArgs, toolCallHash: "hash-B" });
}

// 7. Stale ToolSpec at consumption refused.
{
  const s = store();
  await grantApproval(s, reviewer, grantArgs);
  results.stale_toolspec_rejected =
    await consumeApproval(s, { ...consumeArgs, toolspecHash: "ts-2" });
}

// 8. Stale policy bundle at consumption refused.
{
  const s = store();
  await grantApproval(s, reviewer, grantArgs);
  results.stale_policy_rejected =
    await consumeApproval(s, { ...consumeArgs, policyBundleHash: "pb-2" });
}

// 9. Expired approval refused.
{
  const s = store();
  await grantApproval(s, reviewer, { ...grantArgs, ttlSeconds: 60, now: new Date("2026-08-19T10:00:00Z") });
  results.expired_rejected =
    await consumeApproval(s, { ...consumeArgs, now: new Date("2026-08-19T10:02:00Z") });
}

// 10. Cross-tenant consumption refused even for a valid approval.
{
  const s = store();
  await grantApproval(s, reviewer, grantArgs);
  results.cross_tenant_consume_rejected =
    await consumeApproval(s, { ...consumeArgs, tenantId: "t2" });
}

// 11. A rejection decision never authorizes execution.
{
  const s = store();
  await grantApproval(s, reviewer, { ...grantArgs, decision: "rejected" });
  results.rejected_decision_never_executes = await consumeApproval(s, consumeArgs);
}

// ── authenticate(): identity is credential-derived only ──────────────────────
const env = { CONTROL_SECRET: "sekrit", TENANT_ID: "t1" };
const nullVerifier = { verify: async () => null };
const fakeHumanVerifier = {
  verify: async (req) =>
    req.headers.get("X-Test-Human") === "yes"
      ? { principalId: "reviewer@example.com", roles: ["reviewer"], authMethod: "test" }
      : null,
};

// 12. The workload bearer stays a workload even when it spoofs human headers
//     (body.approved_by / Cf-Access header without a verifiable JWT).
results.bearer_with_spoofed_headers = await authenticate(
  new Request("https://x/approvals", {
    method: "POST",
    headers: {
      Authorization: "Bearer sekrit",
      "Cf-Access-Authenticated-User-Email": "fake-reviewer@example.com",
      "X-Test-Human": "yes",
    },
  }),
  env, fakeHumanVerifier,
);

// 13. Wrong bearer is rejected outright (not downgraded to human path).
results.wrong_bearer = await authenticate(
  new Request("https://x/approvals", {
    method: "POST",
    headers: { Authorization: "Bearer wrong", "X-Test-Human": "yes" },
  }),
  env, fakeHumanVerifier,
);

// 14. Unverifiable human claim yields no identity at all.
results.unverified_human = await authenticate(
  new Request("https://x/approvals", {
    method: "POST",
    headers: { "Cf-Access-Authenticated-User-Email": "fake@example.com" },
  }),
  env, nullVerifier,
);

// 15. Verified human identity resolves with roles from the verifier only.
results.verified_human = await authenticate(
  new Request("https://x/approvals", { method: "POST", headers: { "X-Test-Human": "yes" } }),
  env, fakeHumanVerifier,
);

console.log(JSON.stringify(results));
"""


def _skip_unless_js_toolchain() -> None:
    if not _APPROVAL_TS.exists():
        pytest.skip("worker approval module not present")
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_WORKER_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")


def _bundle(src: Path, out: Path) -> None:
    subprocess.run(
        [
            "npx", "esbuild", str(src),
            "--bundle", "--format=esm", "--platform=node",
            f"--outfile={out}",
        ],
        cwd=_WORKER_DIR,
        check=True,
        capture_output=True,
        shell=os.name == "nt",
    )


@pytest.fixture(scope="module")
def scenario_results(tmp_path_factory: pytest.TempPathFactory) -> dict:
    _skip_unless_js_toolchain()
    tmp_path = tmp_path_factory.mktemp("agent_control_approvals")
    approval_bundle = tmp_path / "approval.mjs"
    auth_bundle = tmp_path / "auth.mjs"
    _bundle(_APPROVAL_TS, approval_bundle)
    _bundle(_WORKER_DIR / "src" / "auth.ts", auth_bundle)

    driver = tmp_path / "driver.mjs"
    driver.write_text(
        _DRIVER.replace("BUNDLE_APPROVAL", json.dumps(approval_bundle.as_uri()))
        .replace("BUNDLE_AUTH", json.dumps(auth_bundle.as_uri())),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(driver)],
        cwd=_WORKER_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _refused(res: dict, reason: str) -> bool:
    return res.get("ok") is False and res.get("reason") == reason


def test_workload_credential_cannot_approve(scenario_results: dict) -> None:
    assert _refused(scenario_results["workload_cannot_approve"], "REVIEWER_IDENTITY_REQUIRED")


def test_same_principal_cannot_self_approve(scenario_results: dict) -> None:
    assert _refused(
        scenario_results["same_principal_cannot_self_approve"], "SELF_APPROVAL_FORBIDDEN"
    )


def test_missing_reviewer_role_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["missing_role_rejected"], "REVIEWER_IDENTITY_REQUIRED")


def test_cross_tenant_grant_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["cross_tenant_grant_rejected"], "TENANT_MISMATCH")


def test_valid_independent_reviewer_approval_succeeds(scenario_results: dict) -> None:
    grant = scenario_results["valid_grant"]
    assert grant["ok"] is True
    assert grant["approval"]["reviewerPrincipal"] == "reviewer@example.com"
    assert grant["approval"]["requesterPrincipal"] == "control_secret_bearer"
    assert scenario_results["valid_consume"]["ok"] is True


def test_approval_is_single_use(scenario_results: dict) -> None:
    assert _refused(scenario_results["replay_consume"], "APPROVAL_ALREADY_CONSUMED")


def test_modified_arguments_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["modified_args_rejected"], "PAYLOAD_CHANGED_AFTER_APPROVAL")


def test_stale_toolspec_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["stale_toolspec_rejected"], "TOOLSPEC_CHANGED_AFTER_APPROVAL")


def test_stale_policy_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["stale_policy_rejected"], "POLICY_CHANGED_AFTER_APPROVAL")


def test_expired_approval_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["expired_rejected"], "APPROVAL_EXPIRED")


def test_cross_tenant_consumption_rejected(scenario_results: dict) -> None:
    assert _refused(scenario_results["cross_tenant_consume_rejected"], "TENANT_MISMATCH")


def test_rejected_decision_never_executes(scenario_results: dict) -> None:
    assert _refused(scenario_results["rejected_decision_never_executes"], "APPROVAL_REJECTED")


def test_bearer_with_spoofed_human_headers_stays_workload(scenario_results: dict) -> None:
    ctx = scenario_results["bearer_with_spoofed_headers"]
    assert ctx is not None
    assert ctx["principalType"] == "workload"
    assert ctx["principalId"] == "control_secret_bearer"


def test_wrong_bearer_is_rejected_not_downgraded(scenario_results: dict) -> None:
    assert scenario_results["wrong_bearer"] is None


def test_unverified_human_claim_yields_no_identity(scenario_results: dict) -> None:
    assert scenario_results["unverified_human"] is None


def test_verified_human_identity_resolves(scenario_results: dict) -> None:
    ctx = scenario_results["verified_human"]
    assert ctx is not None
    assert ctx["principalType"] == "human"
    assert ctx["principalId"] == "reviewer@example.com"
    assert "reviewer" in ctx["roles"]
