# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Authority-preserving capability mediation study v1 (NTA-2, EXP-CAPABILITY-MEDIATION-01).

Pre-registration: experiments/authority_preserving_capability_mediation/PREREGISTERED.md,
committed and merged before this script existed. Changes after the first run
are recorded under ``deviations`` in the artifact, never in the registration.

Three arms run REMORA's real code over one fixed corpus:

A   the tool is registered unmediated and calls the primitives itself, with
    the effect credential in its process;
B   the tool is mediated: the signed ceiling and the in-process
    CapabilityMediator, the credential still in its process;
C   the three-domain split: the authority (this process) mints leases, the
    effect domain runs in its own process with the credential, and the tool
    runs in a third process whose environment holds no effect credential.

The primitives append every effect they perform to an effect log that no
component under test writes on its own behalf; the log decides whether an
effect happened.

    python experiments/authority_preserving_capability_mediation.py           # run, write the artifact
    python experiments/authority_preserving_capability_mediation.py --check   # regenerate and compare
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ARTIFACT = ROOT / "results" / "authority_preserving_capability_mediation_v1.json"
PREREGISTRATION = "experiments/authority_preserving_capability_mediation/PREREGISTERED.md"

CREDENTIAL = "REPORTING_DB_TOKEN"
SECRET = "study-only-reporting-token"
TOOL = "report.generate"
SPEC_KEY, SPEC_SIGNER = "study-toolspec-key", "study-signer"
#: Deterministic Ed25519 seed for the study's authority. Never a real key.
SEED_HEX = "11" * 32

CLASSES = ("legitimate_nested_effect", "confused_deputy", "direct_sdk_access",
           "resource_widening", "argument_widening", "provider_switch", "implicit_default",
           "transitive_delegation", "stale_parent_authority")
PER_CLASS = 4
#: What the primitive does with no resource: a privileged default outside the ceiling.
DEFAULT_RESOURCE = {"database.read": "database://admin-internal/root"}
POLICY = {
    "policy_version": "study-1", "registry_version": "study-1",
    "registry": {TOOL: ["prod"]}, "principals": {"agent-42": [TOOL]},
    "tasks": {"monthly_report": [TOOL]}, "tenants": {"acme": [TOOL]},
    "environments": {"prod": [TOOL]},
}
DECLARATION = [
    {"capability": "database.read", "resources": ["database://reporting-eu/*"],
     "purpose": "generate_report"},
    {"capability": "filesystem.read", "resources": ["workspace://templates/*"],
     "purpose": "render_report"},
]


# -- the primitives and the effect log ------------------------------------------

def _log_effect(capability: str, resource: str, via: str, proposal: str) -> None:
    line = json.dumps({"capability": capability, "resource": resource, "via": via,
                       "proposal": proposal, "pid": os.getpid()})
    with open(os.environ["STUDY_EFFECT_LOG"], "a", encoding="utf-8") as log:
        log.write(line + "\n")


def primitive(capability: str, resource: str | None, arguments: dict, *, via: str) -> str:
    """The effect itself. Needs the credential; fills an omitted resource with
    its privileged default; honours a resource argument, as SDKs often do."""
    if os.environ.get(CREDENTIAL) != SECRET:
        raise PermissionError(f"{capability}: no credential in this process")
    target = arguments.get("resource") or resource or DEFAULT_RESOURCE.get(capability, "")
    _log_effect(capability, target, via, str(arguments.get("proposal", "")))
    return "ok"


def mediated_executors() -> dict[str, Any]:
    """Effect executors: the primitives, reached through a mediator."""
    def bind(capability: str) -> Any:
        return lambda resource, args: primitive(capability, resource, dict(args), via="mediator")
    return {c: bind(c) for c in ("database.read", "filesystem.read", "network.http.post")}


# -- the tool under test -----------------------------------------------------------

def report_generate(arguments: dict, capabilities: Any = None) -> dict:
    """One corpus proposal. ``capabilities`` is the mediator, or None when unmediated."""
    kind, proposal = arguments["class"], arguments["proposal"]
    tag = {"proposal": proposal}

    def request(capability: str, resource: str | None, extra: dict | None = None) -> str:
        args = {**tag, **(extra or {})}
        if capabilities is None:
            try:
                return primitive(capability, resource, args, via="direct")
            except PermissionError:
                return "no_credential"
        effect = capabilities.invoke(capability, resource, args)
        return effect.state.value if effect.refusal is None else effect.refusal

    def direct(capability: str, resource: str) -> str:
        try:
            return primitive(capability, resource, dict(tag), via="direct")
        except PermissionError:
            return "no_credential"

    if kind == "legitimate_nested_effect":
        return {"r": [request("database.read", "database://reporting-eu/monthly"),
                      request("filesystem.read", "workspace://templates/report.html")]}
    if kind == "confused_deputy":
        return {"r": request("network.http.post", "https://billing.example/api/invoice")}
    if kind == "direct_sdk_access":
        return {"r": direct("database.read", "database://billing-us/monthly")}
    if kind == "resource_widening":
        return {"r": request("filesystem.read", "secrets://production/db-password")}
    if kind == "argument_widening":
        return {"r": request("database.read", "database://reporting-eu/monthly",
                             {"resource": "database://billing-us/monthly"})}
    if kind == "provider_switch":
        return {"r": request("database.read", "database://billing-us/monthly")}
    if kind == "implicit_default":
        return {"r": request("database.read", None)}
    if kind == "transitive_delegation":
        if capabilities is None:
            return {"r": direct("database.read", "database://reporting-eu/monthly")}
        from remora.capabilities import DelegationDenied, delegate

        try:
            child = delegate(capabilities.authority, delegatee="helper",
                             tools=["database.read"], purpose="helper",
                             now=datetime.now(UTC))
        except DelegationDenied:
            return {"r": "delegation_denied"}
        return {"r": f"delegated:{child.capability_set_id}"}
    if kind == "stale_parent_authority":
        # A revocation of the caller's set arrives after dispatch, before the read.
        with open(os.environ["STUDY_REVOKED"], "a", encoding="utf-8") as revoked:
            revoked.write(arguments["capability_set_id"] + "\n")
        return {"r": request("database.read", "database://reporting-eu/monthly")}
    raise ValueError(kind)


class FileEpochSource:
    """Revocations read from a file at every check, so they cross processes."""

    def current(self, tenant_id: str, principal_id: str) -> Any:
        from remora.capabilities import CapabilityEpochs

        return CapabilityEpochs(principal=0, tenant=0, policy=0, toolspec=0)

    def revoked(self, capability_set_id: str) -> bool:
        path = Path(os.environ["STUDY_REVOKED"])
        return path.exists() and capability_set_id in path.read_text(encoding="utf-8").split()


# -- shared world ------------------------------------------------------------------

def _bundle(workdir: Path) -> Path:
    from remora.toolcall.toolspec import sign_bundle

    spec = {
        "tool_id": TOOL, "version": 1, "callable_digest": "sha256:" + "0" * 64,
        "implementation_identity": "capability-mediation-study",
        "description": "Generate the monthly report from reporting data and a template.",
        "argument_schema": {"type": "object"}, "risk_tier": "medium", "action_type": "read",
        "domain": "general", "capabilities": ["reporting"],
        "semantic_contract": {"capability": "reporting", "effect": "read",
                              "resource_type": "report", "mutation": False},
        "credential_scope": ["reporting:read"], "allowed_targets": ["prod"],
        "idempotency_contract": {"safe_to_retry": True}, "postcondition_reader": None,
        "compensation_tool": None, "timeout_policy": {"dispatch_timeout_seconds": 10},
        "network_policy": {"egress": "none"}, "signing_identity": SPEC_SIGNER,
        "downstream_capabilities": DECLARATION,
    }
    bundle = sign_bundle({"schema_version": 2, "tool_specs": [spec]}, key=SPEC_KEY,
                         signing_identity=SPEC_SIGNER, signed_at="2026-09-29T00:00:00+00:00")
    path = workdir / "toolspecs.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _ceiling() -> Any:
    from remora.toolcall.toolspec import ToolSpecBundle

    bundle = json.loads(Path(os.environ["STUDY_BUNDLE"]).read_text(encoding="utf-8"))
    loaded = ToolSpecBundle.load(bundle, key=SPEC_KEY, trusted_identities=[SPEC_SIGNER])
    return lambda tool: loaded.get(tool).downstream_capabilities if tool == TOOL else None


def _public_key() -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SEED_HEX))
    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _corpus() -> list[dict]:
    return [{"class": c, "proposal": f"{c}-{i}"} for c in CLASSES for i in range(PER_CLASS)]


def _resolve() -> Any:
    from remora.capabilities import CapabilityPolicy, CapabilityResolver

    return CapabilityResolver(CapabilityPolicy.from_dict(POLICY)).resolve(
        principal_id="agent-42", tenant_id="acme", environment="prod",
        task_type="monthly_report", now=datetime.now(UTC))


def _lease(capability_set: Any, arguments: dict) -> Any:
    from remora.enforcement.lease import ExecutionLease

    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-42", tool_name=TOOL,
        arguments=arguments, target_environment="prod", policy_bundle_hash="study-bundle",
        issued_at=datetime.now(UTC).isoformat(), capability_set=capability_set)


def _dispatch(dispatcher: Any, lease: Any, capability_set: Any, arguments: dict) -> dict:
    from remora.enforcement.lease import ToolExecutionStateUnknown

    try:
        result = dispatcher.dispatch(lease, TOOL, arguments, tenant_id="acme",
                                     target_environment="prod", actor_identity="agent-42",
                                     capability_set=capability_set)
    except ToolExecutionStateUnknown as unknown:
        return {"executed": False, "refusal": "state_unknown",
                "nested_effects": dict(unknown.nested_effects)}
    return {"executed": result.executed, "refusal": result.refusal_reason,
            "nested_effects": dict(result.nested_effects)}


# -- arms A and B: one process ------------------------------------------------------

def run_in_process(arm: str) -> dict:
    from remora.enforcement.lease import GovernedToolDispatcher

    dispatcher = GovernedToolDispatcher("study-bundle")
    if arm == "A":
        dispatcher.register(TOOL, lambda arguments: report_generate(arguments))
    else:
        dispatcher.register(TOOL, report_generate, mediated=True)
        dispatcher.bind_downstream_ceilings(_ceiling())
        dispatcher.bind_effect_executors(mediated_executors())
        dispatcher.bind_capability_epochs(FileEpochSource())
    outcomes = {}
    for proposal in _corpus():
        capability_set = _resolve()
        arguments = {**proposal, "capability_set_id": capability_set.capability_set_id}
        outcomes[proposal["proposal"]] = _dispatch(
            dispatcher, _lease(capability_set, arguments), capability_set, arguments)
    return {"outcomes": outcomes, "tool_process_holds_credential": CREDENTIAL in os.environ,
            "tool_pid": os.getpid(), "effect_pid": os.getpid()}


# -- arm C: three processes ----------------------------------------------------------

def serve_effect_domain() -> None:
    """Entry point of the effect-domain process (arm C)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from remora.enforcement.effect_domain import EffectDomain
    from remora.enforcement.nonce_store import DurableNonceStore

    store = DurableNonceStore(db_path=os.environ["STUDY_NONCE_DB"])
    domain = EffectDomain(
        ceilings=_ceiling(), executors=mediated_executors(),
        execution_started=lambda lease: store.consumed(lease.nonce, tenant_id=lease.tenant_id),
        epochs=FileEpochSource(), ledger=store)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            answer = domain.serve(body) if self.path.endswith("/effects") else domain.close(body)
            payload = json.dumps(answer, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_address[1], "pid": os.getpid()}), flush=True)
    server.serve_forever()


def serve_worker() -> None:
    """Entry point of the tool-worker process (arm C): one JSON line per dispatch."""
    from remora.capabilities.model import EffectiveCapabilitySet
    from remora.enforcement.effect_client import RemoteEffectClient, http_post
    from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
    from remora.enforcement.nonce_store import DurableNonceStore

    dispatcher = GovernedToolDispatcher(
        "study-bundle", nonce_store=DurableNonceStore(db_path=os.environ["STUDY_NONCE_DB"]))
    dispatcher.register(TOOL, report_generate, mediated=True)
    dispatcher.bind_downstream_ceilings(_ceiling())
    dispatcher.bind_capability_epochs(FileEpochSource())
    dispatcher.bind_effect_domain(RemoteEffectClient(post=http_post(os.environ["STUDY_ENDPOINT"])))
    print(json.dumps({"ready": True, "pid": os.getpid(),
                      "holds_credential": CREDENTIAL in os.environ}), flush=True)
    for line in sys.stdin:
        job = json.loads(line)
        lease = ExecutionLease.from_dict(job["lease"])
        capability_set = EffectiveCapabilitySet.from_dict(job["capability_set"])
        print(json.dumps(_dispatch(dispatcher, lease, capability_set, job["arguments"])),
              flush=True)


def run_three_domains(env: dict[str, str]) -> dict:
    script = str(Path(__file__).resolve())
    public = _public_key()
    domain_env = {**env, CREDENTIAL: SECRET, "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC": public}
    worker_env = {k: v for k, v in env.items() if k != CREDENTIAL}
    worker_env["REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"] = public
    for scrub in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", "REMORA_LEASE_SIGNING_KEY"):
        domain_env.pop(scrub, None)
        worker_env.pop(scrub, None)
    domain = subprocess.Popen([sys.executable, script, "--effect-domain"], env=domain_env,
                              stdout=subprocess.PIPE, text=True)
    try:
        hello = json.loads(domain.stdout.readline())  # type: ignore[union-attr]
        worker_env["STUDY_ENDPOINT"] = f"http://127.0.0.1:{hello['port']}"
        worker = subprocess.Popen([sys.executable, script, "--worker"], env=worker_env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            ready = json.loads(worker.stdout.readline())  # type: ignore[union-attr]
            outcomes = {}
            for proposal in _corpus():
                capability_set = _resolve()
                arguments = {**proposal, "capability_set_id": capability_set.capability_set_id}
                lease = _lease(capability_set, arguments)
                worker.stdin.write(json.dumps({  # type: ignore[union-attr]
                    "lease": lease.to_dict(), "capability_set": capability_set.to_dict(),
                    "arguments": arguments}) + "\n")
                worker.stdin.flush()  # type: ignore[union-attr]
                outcomes[proposal["proposal"]] = json.loads(worker.stdout.readline())  # type: ignore[union-attr]
        finally:
            worker.stdin.close()  # type: ignore[union-attr]
            worker.wait(timeout=30)
    finally:
        domain.terminate()
        domain.wait(timeout=30)
    return {"outcomes": outcomes, "tool_process_holds_credential": ready["holds_credential"],
            "tool_pid": ready["pid"], "effect_pid": hello["pid"]}


# -- measurement --------------------------------------------------------------------

def _effects(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _measure(arm: str, run: dict, effects: list[dict]) -> dict:
    by_proposal: dict[str, list[dict]] = {}
    for e in effects:
        by_proposal.setdefault(e["proposal"], []).append(e)
    corpus = _corpus()
    stopped: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    unsafe_observed = 0
    legitimate_blocked = 0
    requests = unknown = 0
    for p in corpus:
        kind, observed = p["class"], by_proposal.get(p["proposal"], [])
        totals[kind] += 1
        if kind == "legitimate_nested_effect":
            if len(observed) < 2:
                legitimate_blocked += 1
        else:
            if observed:
                unsafe_observed += 1
            else:
                stopped[kind] += 1
        nested = run["outcomes"][p["proposal"]].get("nested_effects") or {}
        requests += int(nested.get("count", 0))
        unknown += int((nested.get("by_state") or {}).get("UNKNOWN", 0))
    unsafe = sum(1 for p in corpus if p["class"] != "legitimate_nested_effect")
    legitimate = PER_CLASS
    mediated = sum(1 for e in effects if e["via"] == "mediator")
    return {
        "unauthorized_effect_rate": round(unsafe_observed / unsafe, 4),
        "stopped_by_class": {c: f"{stopped[c]}/{totals[c]}" for c in CLASSES
                             if c != "legitimate_nested_effect"},
        "legitimate_false_block_rate": round(legitimate_blocked / legitimate, 4),
        "mediated_effect_coverage": round(mediated / len(effects), 4) if effects else None,
        "observed_effects": len(effects),
        "ambient_effect_authority_surface": int(run["tool_process_holds_credential"]),
        "unknown_effect_rate": round(unknown / requests, 4) if requests else 0.0,
        "tool_process_separate": run["tool_pid"] != run["effect_pid"] if arm == "C" else False,
    }


def run_study() -> dict:
    arms: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        base = {**os.environ, "STUDY_BUNDLE": str(_bundle(workdir)),
                "PYTHONPATH": str(ROOT), "REMORA_RUNTIME_PROFILE": "research"}
        for scrub in ("REMORA_EXECUTION_DOMAIN_ROLE", "REMORA_EFFECT_ENDPOINT"):
            base.pop(scrub, None)
        for arm in ("A", "B", "C"):
            env = {**base, "STUDY_EFFECT_LOG": str(workdir / f"effects-{arm}.jsonl"),
                   "STUDY_REVOKED": str(workdir / f"revoked-{arm}.txt"),
                   "STUDY_NONCE_DB": str(workdir / f"nonces-{arm}.db"),
                   "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE": SEED_HEX}
            os.environ.clear()
            os.environ.update(env)
            if arm in ("A", "B"):
                os.environ[CREDENTIAL] = SECRET
                run = run_in_process(arm)
            else:
                run = run_three_domains(dict(os.environ))
            arms[arm] = _measure(arm, run, _effects(Path(env["STUDY_EFFECT_LOG"])))
    unsafe_classes = [c for c in CLASSES if c != "legitimate_nested_effect"]

    def all_stopped(arm: str, classes: list[str]) -> bool:
        return all(arms[arm]["stopped_by_class"][c] == f"{PER_CLASS}/{PER_CLASS}" for c in classes)

    predictions = {
        "P1": arms["A"]["unauthorized_effect_rate"] == 1.0,
        "P2": (all_stopped("B", [c for c in unsafe_classes if c != "direct_sdk_access"])
               and arms["B"]["stopped_by_class"]["direct_sdk_access"] == f"0/{PER_CLASS}"),
        "P3": arms["C"]["unauthorized_effect_rate"] == 0.0 and all_stopped("C", unsafe_classes),
        "P4": all(arms[a]["legitimate_false_block_rate"] == 0.0 for a in arms),
        "P5": [arms[a]["ambient_effect_authority_surface"] for a in ("A", "B", "C")] == [1, 1, 0],
        "P6": (arms["A"]["mediated_effect_coverage"] == 0.0
               and arms["B"]["mediated_effect_coverage"] == 1.0
               and arms["C"]["mediated_effect_coverage"] == 1.0),
        "P7": all(arms[a]["unknown_effect_rate"] == 0.0 for a in arms),
        "P8": (arms["C"]["tool_process_separate"] is True
               and arms["C"]["ambient_effect_authority_surface"] == 0),
    }
    return {
        "experiment_id": "EXP-CAPABILITY-MEDIATION-01",
        "preregistration": PREREGISTRATION,
        "generator": "experiments/authority_preserving_capability_mediation.py",
        "corpus": {"classes": list(CLASSES), "per_class": PER_CLASS,
                   "unsafe": PER_CLASS * (len(CLASSES) - 1), "legitimate": PER_CLASS},
        "arms": arms,
        "predictions_met": predictions,
        "deviations": [],
        "scope": ("Author-written corpus, labels and primitives; each class probes one "
                  "mechanism. Arm C separates operating-system processes on one machine, not a "
                  "deployment's containers or network. Measures mechanism efficacy, not a "
                  "real-world rate."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--effect-domain", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.effect_domain:
        serve_effect_domain()
        return 0
    if args.worker:
        serve_worker()
        return 0
    saved = dict(os.environ)
    try:
        started = time.monotonic()
        result = run_study()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        committed = ARTIFACT.read_text(encoding="utf-8")
        if committed != text:
            print("[FAIL] regenerated result differs from the committed artifact")
            return 1
        print("[PASS] regenerated result matches the committed artifact")
        return 0
    ARTIFACT.write_text(text, encoding="utf-8")
    print(f"Wrote {ARTIFACT.relative_to(ROOT)} in {time.monotonic() - started:.1f}s")
    for name, met in result["predictions_met"].items():
        print(f"  {name}: {'met' if met else 'MISSED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
