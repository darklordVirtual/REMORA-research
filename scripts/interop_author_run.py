#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Write or check REMORA's author run records for its interop contracts.

For every contract in ``artifacts/interop/index.json`` that has fixtures, two
L0_SELF_TEST evaluations are run per claim: REMORA's own evaluator
(``remora.interop.boundary_fixtures`` or the ``remora.interop.agentavow``
adapter) and the package's reference verifier. Each becomes one
``interop-result-v1`` record under ``artifacts/interop/runs/``.

    --write    run everything and (re)write the author records
    --check    run everything and refuse if a committed record's cases,
               status or digests differ from what the package yields now

An author record is evidence that the committed fixtures describe REMORA. It
is the producer evaluating itself, advances no contract lifecycle, and the
record says so in its independence level. The two evaluators are kept as two
records so a reader can see that they agree rather than being told.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INDEX = ROOT / "artifacts" / "interop" / "index.json"
RUNS = ROOT / "artifacts" / "interop" / "runs"
REPOSITORY = "darklordVirtual/REMORA-research"
LEVEL = "L0_SELF_TEST"
#: The evaluators mint leases and tokens; a process with no signing key would
#: report every case as unverifiable, which is a configuration fact and not a
#: result. Keys are fixed, never real, and set only for this process.
_ENV = {"REMORA_LEASE_SIGNING_KEY": "author-run-lease-key", "REMORA_ENV": "development"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_cases(contract: dict[str, Any], fixtures: dict[str, Any]) -> list[dict[str, Any]]:
    if contract["id"].startswith("agentavow-"):
        from remora.interop.agentavow import evaluate_fixture_case

        records = []
        for case in fixtures["cases"]:
            observed = evaluate_fixture_case(case, fixtures["trusted_signers"])
            expected = {k: case["expected"][k] for k in ("verdict", "reason")}
            records.append({"case_id": case["id"], "claim_id": case["claim_id"], "expected": expected,
                            "observed": observed, "result": case["expected"]["claim_result"] if observed == expected else "CONTRADICTED"})
        return records
    from remora.interop.boundary_fixtures import evaluate_package

    return evaluate_package(fixtures)


def _reference_cases(contract: dict[str, Any], fixtures: dict[str, Any]) -> list[dict[str, Any]]:
    out = subprocess.run([sys.executable, str(ROOT / contract["reference_verifier"])], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    if out.returncode not in (0, 1) or not out.stdout:
        raise RuntimeError(f"{contract['id']}: reference verifier did not produce a result: {out.stderr}")
    payload = json.loads(out.stdout)
    by_id = {case["id"]: case for case in fixtures["cases"]}
    records = []
    for item in payload["results"]:
        case = by_id[item["id"]]
        records.append({"case_id": item["id"], "claim_id": case["claim_id"],
                        "expected": {"value": item["expected"]}, "observed": {"value": item["actual"]},
                        "result": case["expected"]["claim_result"] if item["ok"] else "CONTRADICTED"})
    return records


def _status(cases: list[dict[str, Any]]) -> str:
    if any(c["result"] == "CONTRADICTED" for c in cases):
        return "CONTRADICTED"
    if any(c["result"] == "ESTABLISHED" for c in cases):
        return "ESTABLISHED"
    return "NOT_ESTABLISHED"


def _record(contract: dict[str, Any], packet: dict[str, Any], claim: dict[str, Any], kind: str,
            cases: list[dict[str, Any]], started: str, completed: str) -> dict[str, Any]:
    fixture_path = contract["fixtures"]
    claim_cases = [c for c in cases if c["claim_id"] == claim["claim_id"]]
    status = _status(claim_cases)
    if kind == "PRODUCER_RUNTIME":
        evaluator_path = ("remora/interop/agentavow/adapter.py" if contract["id"].startswith("agentavow-")
                          else "remora/interop/boundary_fixtures.py")
        command = f"python scripts/interop_author_run.py --write  # {evaluator_path}"
        imports_runtime = True
    else:
        evaluator_path = contract["reference_verifier"]
        command = f"python {evaluator_path}"
        imports_runtime = False
    name = f"{contract['id']}-{claim['claim_id']}-author-{'runtime' if kind == 'PRODUCER_RUNTIME' else 'reference'}-L0.json"
    return {
        "schema_version": "remora-interop-result-v1",
        "contract_id": contract["id"],
        "edge": contract["edge"],
        "claim": claim["claim_id"],
        "subject": f"{packet['subject']['class']}:{packet['subject']['id']}",
        "status": status,
        "producer": {"project": "REMORA", "repository": REPOSITORY, "revision": contract["source_revision"]},
        "consumer": {"project": "REMORA", "repository": REPOSITORY, "revision": contract["source_revision"]},
        "fixture": {"path": fixture_path, "digest": "sha256:" + _sha(ROOT / fixture_path), "package_digest": contract["package_digest"]},
        "evaluator": {"project": "REMORA", "repository": REPOSITORY, "revision": contract["source_revision"], "kind": kind,
                      "maintained_by": "PRODUCER", "imports_producer_runtime": imports_runtime,
                      "imports_reference_evaluator": kind == "REFERENCE", "command": command},
        "operator": "PRODUCER",
        "host": "PRODUCER_CONTROLLED",
        "independence_level": LEVEL,
        "runner": {"path": "scripts/interop_author_run.py", "revision": contract["source_revision"]},
        "environment": f"Python {platform.python_version()}, {platform.system()} {platform.machine()}",
        "started_at": started,
        "completed_at": completed,
        "cases": claim_cases,
        "establishes": [f"{claim['claim_id']}: {claim['claim_ceiling']}"] if status == "ESTABLISHED" else [],
        "does_not_establish": list(packet["explicit_non_claims"]),
        "ceiling": {"implies_endorsement": False, "implies_production_safety": False,
                    "implies_broader_validity": False, "confers_authority": False},
        "run_ref": f"artifacts/interop/runs/{name}",
        "published_at": None,
    }


def produce() -> dict[str, dict[str, Any]]:
    os.environ.update({k: v for k, v in _ENV.items() if k not in os.environ})
    index = _load(INDEX)
    records: dict[str, dict[str, Any]] = {}
    for contract in index["contracts"]:
        if "fixtures" not in contract or "reference_verifier" not in contract:
            continue
        fixtures = _load(ROOT / contract["fixtures"])
        packet = _load(ROOT / contract["claim_packet"])
        if "claims" not in fixtures:
            continue  # the E7 package predates the author-run contract and keeps its own CI step
        for kind, run in (("PRODUCER_RUNTIME", _runtime_cases), ("REFERENCE", _reference_cases)):
            started = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            cases = run(contract, fixtures)
            completed = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            for claim in packet["claims"]:
                record = _record(contract, packet, claim, kind, cases, started, completed)
                records[Path(record["run_ref"]).name] = record
    return records


_VOLATILE = ("started_at", "completed_at", "environment")


def _stable(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _VOLATILE}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    records = produce()
    RUNS.mkdir(parents=True, exist_ok=True)
    if args.write:
        for name, record in records.items():
            (RUNS / name).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"[WRITE] {name}: {record['status']} ({len(record['cases'])} cases)")
        return 0
    problems = []
    for name, record in records.items():
        path = RUNS / name
        if not path.is_file():
            problems.append(f"missing author record {name}; run --write")
            continue
        committed = _load(path)
        if _stable(committed) != _stable(record):
            problems.append(f"{name} no longer matches what the package yields; run --write and review the diff")
        else:
            print(f"[PASS] {name}: {record['status']}")
    for problem in problems:
        print(f"[FAIL] {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
