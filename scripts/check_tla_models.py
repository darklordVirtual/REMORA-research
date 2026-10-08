#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Run the TLA+ models under formal/tla with TLC and compare with expected.json.

Each configuration is expected either to hold (no invariant violated in the
whole finite state space) or to be violated with a named invariant and an
exact counterexample action sequence. A changed verdict or trace fails.

TLC needs Java 11+. The pinned tla2tools.jar is downloaded once into
``.cache/tla/`` and checked against its SHA-256. Without Java, or without the
jar and network, the script prints BLOCKED and exits 2: a model that was not
checked is never reported as passing (formal SDD FM-AC11).

    python scripts/check_tla_models.py [--jar PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TLA = ROOT / "formal" / "tla"
EXPECTED = TLA / "expected.json"
CACHE = ROOT / ".cache" / "tla"

_VIOLATED = re.compile(r"Invariant (\w+) is violated")
_STATE = re.compile(r"^State \d+: <(.+?) line \d+", re.M)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jar(spec: dict, given: str | None) -> Path | None:
    if given:
        path = Path(given)
    else:
        path = CACHE / f"tla2tools-{spec['version']}.jar"
        if not path.exists():
            try:
                CACHE.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(spec["url"], timeout=60) as resp:  # noqa: S310 - pinned https URL
                    path.write_bytes(resp.read())
            except OSError as exc:
                print(f"BLOCKED: cannot fetch TLC ({exc})")
                return None
    if not path.exists() or _sha(path) != spec["sha256"]:
        print(f"BLOCKED: {path} is missing or does not match the pinned SHA-256")
        return None
    return path


def check_one(java: str, jar: Path, name: str) -> dict:
    with tempfile.TemporaryDirectory() as meta:
        proc = subprocess.run(  # noqa: S603 - fixed argument list
            [java, "-XX:+UseParallelGC", "-cp", str(jar), "tlc2.TLC", "-config", f"{name}.cfg",
             "-workers", "1", "-deadlock", "-noGenerateSpecTE", "-metadir", meta, "LeaseRetry.tla"],
            cwd=TLA, capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    if "No error has been found" in out:
        return {"result": "holds"}
    m = _VIOLATED.search(out)
    if m:
        trace = [s.strip() for s in _STATE.findall(out) if s.strip() != "Initial predicate>"]
        trace = [t for t in trace if not t.startswith("Initial predicate")]
        return {"result": "violated", "invariant": m.group(1), "trace": trace}
    return {"result": "error", "output_tail": out[-800:]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jar")
    args = ap.parse_args()
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    java = shutil.which("java")
    if java is None:
        print("BLOCKED: java not found; the TLA+ models were not checked")
        return 2
    jar = _jar(expected["tlc"], args.jar)
    if jar is None:
        return 2
    failures = []
    for name, want in expected["configs"].items():
        got = check_one(java, jar, name)
        keys = ("result", "invariant", "trace") if want["result"] == "violated" else ("result",)
        ok = all(got.get(k) == want.get(k) for k in keys)
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {got['result']}"
              + (f" {got.get('invariant')} via {' -> '.join(got.get('trace', []))}" if got["result"] == "violated" else ""))
        if not ok:
            failures.append((name, want, got))
    if failures:
        for name, want, got in failures:
            print(f"  {name}: expected {want}, got {got}")
        return 1
    print(f"[PASS] {len(expected['configs'])} TLA+ configurations match formal/tla/expected.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
