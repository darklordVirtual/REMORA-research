#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reproduce declared custody guards in separate, same-user local processes.

Synthetic credentials and temporary local effects only. Process separation
does not establish OS isolation or discover undeclared external credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEMANTIC = {"tool_contract_bundle_hash": "reference-contract", "intent_authority_hash": "reference-intent"}


def _call(value: int = 1) -> SimpleNamespace:
    return SimpleNamespace(tool_name="write", arguments={"value": value}, target_environment="local-record")


def _worker(request: dict) -> dict:
    from remora.enforcement.custody import CustodyViolation, assert_custody_split
    from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
    from remora.enforcement.nonce_store import DurableNonceStore
    from remora.enforcement.runtime_identity import RuntimeTrustBaseIdentity
    from remora.execution.dispatch import dispatch_under_lease

    role = request["role"]
    os.environ["REMORA_RUNTIME_PROFILE"] = "review"
    os.environ["REMORA_EXECUTION_DOMAIN_ROLE"] = role
    os.environ["REMORA_EFFECT_CREDENTIAL_ENV_NAMES"] = "REPRO_EFFECT_CREDENTIAL"
    os.environ["REMORA_RUNTIME_KIND"] = request.get("runtime_kind", "custody-reproduction")
    now = datetime.now(UTC)
    if role == "authority":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.generate()
        os.environ["REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE"] = key.private_bytes_raw().hex()
        public = key.public_key().public_bytes_raw().hex()
        os.environ["REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"] = public
        if request.get("control") == "authority_holds_credential":
            os.environ["REPRO_EFFECT_CREDENTIAL"] = "synthetic-custody-credential"
    else:
        public = request["public_key"]
        os.environ["REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"] = public
        os.environ["REPRO_EFFECT_CREDENTIAL"] = "synthetic-custody-credential"
        if request.get("control") == "executor_holds_signing_key":
            os.environ["REMORA_LEASE_SIGNING_KEY"] = "synthetic-invalid-signing-material"
    if request.get("control") == "undeclared_inventory":
        os.environ["REMORA_EFFECT_CREDENTIAL_ENV_NAMES"] = ""
    try:
        assert_custody_split()
    except CustodyViolation:
        return {"pid": os.getpid(), "custody_refused": True}
    if role == "authority":
        leases = {}
        for name, issued in (("fresh", now), ("expired", now - timedelta(hours=1))):
            leases[name] = ExecutionLease.issue(
                decision="accept", tenant_id="reference", actor_identity="reference-agent",
                tool_name="write", arguments={"value": 1}, target_environment="local-record",
                issued_at=issued.isoformat(), policy_bundle_hash="reference-policy", **SEMANTIC,
                runtime_identity_hash=RuntimeTrustBaseIdentity(runtime_kind="custody-reproduction").identity_hash(),
                proposal_id="reference-proposal", grant_jti="reference-grant",
            ).to_dict()
        return {"pid": os.getpid(), "public_key": public, "leases": leases}

    root = Path(request["state"])
    effect = root / "effects.jsonl"
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash="reference-policy",
        nonce_store=DurableNonceStore(db_path=str(root / "nonces.sqlite")),
    )

    def write(arguments: dict) -> str:
        with effect.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(arguments, sort_keys=True) + "\n")
        if request.get("lose_response"):
            raise TimeoutError("synthetic response loss after local effect")
        return "written"

    dispatcher.register("write", write)
    lease = ExecutionLease.from_dict(request["lease"]) if request.get("lease") else None
    try:
        result = dispatch_under_lease(
            tenant=request.get("tenant", "reference"),
            principal=request.get("principal", "reference-agent"),
            tool_call=_call(request.get("value", 1)), semantic=SEMANTIC,
            now=now, dispatcher=dispatcher, policy_bundle_hash="reference-policy",
            proposal_id="reference-proposal", grant_jti="reference-grant", presented_lease=lease,
        )
    except CustodyViolation:
        if lease is not None:
            raise
        result = {"executed": False, "refusal_reason": "custody_violation"}
    return {"pid": os.getpid(), "executed": result["executed"],
            "refusal_reason": result.get("refusal_reason"),
            "state_unknown": result.get("state_unknown", False),
            "effect_count": len(effect.read_text(encoding="utf-8").splitlines()) if effect.exists() else 0}


def _spawn(request: dict) -> dict:
    # Allowlist OS bootstrap variables; never inherit caller credentials,
    # PYTHONPATH, REMORA configuration, or unrelated provider settings.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    env = {name: value for name, value in os.environ.items() if name.upper() in allowed}
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        input=json.dumps(request), capture_output=True, text=True,
        cwd=ROOT, env=env, timeout=60, check=True,
    )
    return json.loads(result.stdout)


def evaluate(root: Path) -> dict:
    authority = _spawn({"role": "authority"})
    cases = {}
    for name, changes in (
        ("valid", {}), ("restart_replay", {}), ("wrong_call", {"value": 2}),
        ("wrong_tenant", {"tenant": "other"}), ("wrong_principal", {"principal": "other"}),
        ("wrong_runtime", {"runtime_kind": "other"}),
        ("expired", {}), ("tampered", {}), ("self_mint", {}),
        ("lost_response", {"lose_response": True}), ("lost_response_restart", {}),
    ):
        state_name = {"restart_replay": "valid", "lost_response_restart": "lost_response"}.get(name, name)
        state = root / state_name
        state.mkdir(exist_ok=True)
        lease = dict(authority["leases"]["expired" if name == "expired" else "fresh"])
        if name == "tampered":
            lease["signature"] = "00" * 64
        request = {"role": "executor", "state": str(state),
                   "public_key": authority["public_key"],
                   "lease": None if name == "self_mint" else lease, **changes}
        cases[name] = _spawn(request)
        expected = name == "valid"
        count = 1 if name in ("valid", "restart_replay", "lost_response", "lost_response_restart") else 0
        if cases[name]["executed"] is not expected or cases[name]["effect_count"] != count:
            raise ValueError(f"custody control failed: {name}: {cases[name]}")
    if cases["restart_replay"]["refusal_reason"] != "nonce_already_consumed":
        raise ValueError("replay was not refused by the durable nonce ledger")
    if not cases["lost_response"]["state_unknown"]:
        raise ValueError("response loss must preserve unknown outcome")
    if cases["lost_response_restart"]["refusal_reason"] != "nonce_already_consumed":
        raise ValueError("response loss must not authorize retry after restart")
    concurrent = root / "concurrent"
    concurrent.mkdir()
    request = {"role": "executor", "state": str(concurrent),
               "public_key": authority["public_key"], "lease": authority["leases"]["fresh"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(_spawn, [request, request]))
    effect_count = len((concurrent / "effects.jsonl").read_text(encoding="utf-8").splitlines())
    if sum(row["executed"] for row in attempts) != 1 or effect_count != 1:
        raise ValueError("concurrent dispatch must produce exactly one local effect")
    if sorted(row["refusal_reason"] or "executed" for row in attempts) != ["executed", "nonce_already_consumed"]:
        raise ValueError("concurrent refusal must be attributable to nonce consumption")
    cases["concurrent"] = {"attempts": attempts, "effect_count": effect_count}
    for name, role in (("authority_holds_credential", "authority"),
                       ("executor_holds_signing_key", "executor"),
                       ("undeclared_inventory", "executor")):
        cases[name] = _spawn({"role": role, "control": name, "public_key": authority["public_key"]})
        if not cases[name].get("custody_refused"):
            raise ValueError(f"custody control failed: {name}")
    return {"schema_version": 1, "authority_pid": authority["pid"], "cases": cases,
            "claim_boundary": {"scope": "separate local processes, same OS user, synthetic credential",
                               "host_isolation": "NOT_ESTABLISHED",
                               "undeclared_credentials": "NOT_ESTABLISHED",
                               "external_reproduction": False}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(json.load(sys.stdin))))
        return 0
    if args.output is None:
        parser.error("--output is required")
    with tempfile.TemporaryDirectory(prefix="remora-custody-") as temporary:
        result = evaluate(Path(temporary))
    # Exclusive create prevents overwriting an earlier evidence record.
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
