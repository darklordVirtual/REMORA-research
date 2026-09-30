"""Score pre-registered faults against v1.2 and v1.3 without editing frozen trees."""

from __future__ import annotations

import hashlib
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DEFS = OUT / "fault-definitions.json"
PINNED_SHA256 = "241fe7d878df28021b3ee3294ea780a13a1b12c27fcba6c495fd14fe0c6d1733"
if hashlib.sha256(DEFS.read_bytes()).hexdigest() != PINNED_SHA256:
    raise RuntimeError("fault definitions changed after pre-registration")
definitions = json.loads(DEFS.read_text(encoding="utf-8"))
source = (ROOT / "conformance/evidence-sufficiency-v1/checker.py").read_text(encoding="utf-8")


def load_checker(text: str, name: str):
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(text, name, "exec"), module.__dict__)
    return module


def score_cases(mod, base, cases: list[dict], suite: str):
    rows = []
    for case in cases:
        scope = {"kind": "synthetic_fixture", "suite": suite, "bounded": True, "case": case["id"]}
        try:
            actual = mod.assess(case["claim"], case["observations"], scope=scope).as_dict()
        except Exception as exc:
            actual = {"crash": type(exc).__name__, "message": str(exc)}
        try:
            unmutated = base.assess(case["claim"], case["observations"], scope=scope).as_dict()
        except Exception as exc:
            unmutated = {"crash": type(exc).__name__, "message": str(exc)}
        expected = case["expected"]
        row1 = "crash" in actual or (actual.get("status"), actual.get("reason")) != (expected["status"], expected["reason"])
        row2 = "crash" in actual or (actual.get("missing_evidence"), actual.get("decisive_if")) != (unmutated.get("missing_evidence"), unmutated.get("decisive_if"))
        rows.append({"id": case["id"], "expected": expected, "actual": actual, "unmutated": unmutated,
                     "row1_kill": row1, "row2_kill": row2})
    return rows


base = load_checker(source, "independent_base")
all_results = {"fault_definitions_sha256": PINNED_SHA256, "source_commit": definitions["source_commit"],
               "versions": {}}
if True:
    tmp = str(OUT / "sandbox")
    temp_root = Path(tmp) / "conformance"
    temp_root.mkdir(parents=True, exist_ok=True)
    checker_dir = temp_root / "evidence-sufficiency-v1"
    checker_dir.mkdir(exist_ok=True)
    temp_checker = checker_dir / "checker.py"
    for version in ("v1.3", "v1.2"):
        suite = "evidence-sufficiency-" + version
        original_dir = ROOT / "conformance" / suite
        temp_dir = temp_root / suite
        shutil.copytree(original_dir, temp_dir, dirs_exist_ok=True)
        cases = json.loads((original_dir / "cases.json").read_text(encoding="utf-8"))["cases"]
        output = []
        for definition in definitions["faults"]:
            at = definition["offset"]
            old = definition["old"]
            if source[at:at + len(old)] != old:
                raise RuntimeError(f"offset drift: {definition['id']}")
            changed = source[:at] + definition["new"] + source[at + len(old):]
            mod = load_checker(changed, "independent_" + version.replace(".", "_") + "_" + definition["id"])
            case_rows = score_cases(mod, base, cases, suite)
            temp_checker.write_text(changed, encoding="utf-8")
            runner_output = temp_dir / ("mutant-" + definition["id"] + ".json")
            run = subprocess.run([sys.executable, str(temp_dir / "run_evidence_sufficiency.py"), "--out", str(runner_output)],
                                 text=True, capture_output=True, timeout=60)
            if runner_output.exists():
                record = json.loads(runner_output.read_text(encoding="utf-8"))
                row3 = {"exit_code": run.returncode, "failures": record.get("failures", []),
                        "stdout": run.stdout, "stderr": run.stderr,
                        "checker_is_frozen_v1": record.get("checker_is_frozen_v1")}
                runner_output.unlink()
            else:
                row3 = {"exit_code": run.returncode, "crash": True, "stdout": run.stdout, "stderr": run.stderr}
            output.append({"id": definition["id"], "class": definition["class"], "case_rows": case_rows,
                           "row1_kill_cases": [r["id"] for r in case_rows if r["row1_kill"]],
                           "row2_kill_cases": [r["id"] for r in case_rows if r["row2_kill"]],
                           "row3": row3,
                           "row3_kill": bool(row3.get("crash") or row3.get("failures"))})
            print(version, definition["id"], len(output[-1]["row1_kill_cases"]),
                  len(output[-1]["row2_kill_cases"]), int(output[-1]["row3_kill"]), flush=True)
            all_results["versions"][version] = output
            (OUT / "raw-row-outputs.json.gz").write_bytes(
                gzip.compress((json.dumps(all_results, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
            )
    scratch = Path(tmp).resolve()
    if not scratch.is_relative_to(OUT) or scratch.parent != OUT:
        raise RuntimeError(f"unsafe scratch path: {scratch}")
    shutil.rmtree(scratch)
