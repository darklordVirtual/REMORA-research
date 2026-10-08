#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Mutation check of REMORA's federation-port/v0 components.

For each component (authorization evidence and report result) this script
applies small single-edit faults to the installed ``adapter.ts``, reseals the
manifest the way federation-port does, runs the component's own test file in
a federation-port checkout, and reports which faults survived.

A survivor is a test-corpus gap, not an adapter defect. The gate fails when a
survivor is not listed in the component's ``mutation-equivalents.json`` with
a justification, and also when a listed fault is killed, so the list cannot
go stale. The fault ids carry a hash of the original line, so an edit to that
line invalidates its entry and forces a fresh look.

The check runs after the components are installed into federation-port's
tree, as ``remora-adapter/reproduce.sh`` does::

    FEDERATION_PORT_DIR=<checkout> \\
    REMORA_ADAPTER_DIR=<checkout>/adapters/remora-research-authorization \\
    REMORA_REPORT_COMPONENT_DIR=<checkout>/adapters/remora-research-report-result \\
    REMORA_INTEROP_DIR=<checkout>/test/fixtures/remora \\
    python3 integrations/federation-port/mutation_check.py --out report.json

It restores the original adapter and manifest bytes before it exits. Only
the standard library is used; the artifact digest is federation-port/v0
section 3 (files sorted by path, framed path, length, bytes), the same
function REMORA's transport uses. This is the producer's own check and it
tests the corpus, not the adapter's correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

COMPONENTS = {
    "remora-research/authorization-evidence": {
        "source": HERE / "remora-adapter",
        "installed_env": "REMORA_ADAPTER_DIR",
        "test": "test/remora-adapter.test.ts",
        # positive control: a terminal established claim turned into a refusal
        "positive_control": ("{ claim: BOUND, status: 'established' }",
                             "{ claim: BOUND, status: 'not_established', reason: 'control' }"),
    },
    "remora-research/report-result": {
        "source": HERE / "remora-report-result",
        "installed_env": "REMORA_REPORT_COMPONENT_DIR",
        "test": "test/remora-report-result.test.ts",
        "positive_control": ("if (native.status === 'ESTABLISHED') return respond('established', undefined, record)",
                             "if (native.status === 'ESTABLISHED') return respond('not_established', 'control', record)"),
    },
}


def artifact_digest(base: Path, files: list[str]) -> str:
    """federation-port/v0 section 3: files sorted by path, framed path, length, bytes."""
    digest = hashlib.sha256()
    for name in sorted(files):
        data = (base / name).read_bytes()
        digest.update(f"{name}\n{len(data)}\n".encode())
        digest.update(data)
    return "sha256:" + digest.hexdigest()


# --------------------------------------------------------------------------- mutants

@dataclass
class Mutant:
    id: str
    operator: str
    line: int
    description: str
    source: str


def _line_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def _in_string(line: str, pos: int) -> bool:
    """True when ``pos`` sits inside a single- or double-quoted literal on this line."""
    quote = None
    for i, ch in enumerate(line[:pos]):
        if ch == "\\":
            continue
        if quote is None and ch in "'\"`":
            quote = ch
        elif ch == quote:
            quote = None
    return quote is not None


_SKIP = re.compile(r"^\s*(//|/\*|\*|import |export const [A-Z_]+ = '[^']*'\s*$|const [A-Z_]+ = '[^']*'\s*$|\s*$)")

_OPERATORS: list[tuple[str, re.Pattern[str], str | None, str]] = [
    # name, pattern, replacement (None means handled by a function), description
    ("eq_to_neq", re.compile(r"==="), "!==", "=== to !=="),
    ("neq_to_eq", re.compile(r"!=="), "===", "!== to ==="),
    ("and_to_or", re.compile(r" && "), " || ", "&& to ||"),
    ("or_to_and", re.compile(r" \|\| "), " && ", "|| to &&"),
    ("le_to_lt", re.compile(r" <= "), " < ", "<= to <"),
    ("lt_to_le", re.compile(r"(?<![<=>!]) < (?!=)"), " <= ", "< to <="),
    ("ge_to_gt", re.compile(r" >= "), " > ", ">= to >"),
    ("gt_to_ge", re.compile(r"(?<![<=>!-]) > (?!=)"), " >= ", "> to >="),
    ("drop_not", re.compile(r"(?<![=!])!(?=[A-Za-z(])"), "", "negation removed"),
    ("index_last", re.compile(r"\b(\w+)\[0\]"), None, "[0] to [length - 1]"),
    ("drop_sort", re.compile(r"\.sort\(\)"), "", ".sort() removed"),
    ("drop_filter_undef", re.compile(r"\.filter\(k => obj\[k\] !== undefined\)"), "", "undefined filter removed"),
    ("nullish_to_or", re.compile(r" \?\? "), " || ", "?? to ||"),
    ("established_to_not", re.compile(r"'established'"), "'not_established'", "established to not_established"),
    ("not_to_established", re.compile(r"'not_established'"), "'established'", "not_established to established"),
    ("failed_to_not", re.compile(r"'failed'"), "'not_established'", "failed to not_established"),
    ("unsupported_to_not", re.compile(r"'unsupported'"), "'not_established'", "unsupported to not_established"),
    ("optional_chain_drop", re.compile(r"\?\."), ".", "?. to ."),
]

_GUARD = re.compile(r"^(\s*(?:\}\s*)?(?:else )?if \()(.+?)(\)\s*(?:\{|return|integrity|[a-z_]+ =).*)$")
_INT = re.compile(r"(?<![\w.'\"])(\d+)(?![\w.'\"])")


def generate(src: str) -> list[Mutant]:
    lines = src.split("\n")
    out: list[Mutant] = []
    seen: set[str] = set()

    def add(op: str, idx: int, new_line: str, desc: str) -> None:
        if new_line == lines[idx]:
            return
        mutated = lines[:idx] + [new_line] + lines[idx + 1:]
        text = "\n".join(mutated)
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in seen:
            return
        seen.add(key)
        n = sum(1 for m in out if m.line == idx + 1 and m.operator == op)
        out.append(Mutant(f"{op}:L{idx + 1}:{n}:{_line_hash(lines[idx])}", op, idx + 1, desc, text))

    for idx, line in enumerate(lines):
        if _SKIP.match(line):
            continue
        for op, rx, repl, desc in _OPERATORS:
            for m in rx.finditer(line):
                if _in_string(line, m.start()) and not op.endswith(("_to_not", "_to_established")):
                    continue
                if repl is None and op == "index_last":
                    name = m.group(1)
                    new = line[:m.start()] + f"{name}[{name}.length - 1]" + line[m.end():]
                else:
                    new = line[:m.start()] + (repl or "") + line[m.end():]
                add(op, idx, new, f"{desc} at col {m.start() + 1}")
        g = _GUARD.match(line)
        if g:
            add("guard_false", idx, f"{g.group(1)}false{g.group(3)}", "condition replaced by false")
            add("guard_true", idx, f"{g.group(1)}true{g.group(3)}", "condition replaced by true")
        for m in _INT.finditer(line):
            if _in_string(line, m.start()):
                continue
            n = int(m.group(1))
            for delta in (1, -1):
                if n + delta < 0:
                    continue
                new = line[:m.start()] + str(n + delta) + line[m.end():]
                add("int_shift", idx, new, f"{n} to {n + delta}")
    return out


# --------------------------------------------------------------------------- running

@dataclass
class Result:
    id: str
    operator: str
    line: int
    description: str
    outcome: str  # killed | survived | crashed
    passed: int = 0
    failed: int = 0
    failing_tests: list[str] = field(default_factory=list)


def run_tests(fp: Path, test: str, env: dict[str, str]) -> tuple[str, int, int, list[str]]:
    cmd = ["node", "--disable-warning=ExperimentalWarning", "--test", "--test-concurrency=1",
           "--test-reporter=tap", test]
    proc = subprocess.run(cmd, cwd=fp, env=env, capture_output=True, text=True)
    tap = proc.stdout + proc.stderr
    passed = int(m.group(1)) if (m := re.search(r"^# pass (\d+)$", tap, re.M)) else -1
    failed = int(m.group(1)) if (m := re.search(r"^# fail (\d+)$", tap, re.M)) else -1
    failing = re.findall(r"^not ok \d+ - (.*)$", tap, re.M)
    if passed < 0:
        return "crashed", 0, 0, failing
    return ("killed" if failed > 0 else "survived"), passed, failed, failing


ROOT = HERE.parents[1]
FIXTURE_BUILDER = ROOT / "scripts" / "build_federation_port_v0_fixtures.py"
FIXTURES_DIR = ROOT / "artifacts" / "interop" / "federation-port-v0"
FIXTURE_FILES = ("fixtures.json", "report-results.json", "projection-map.yaml")


def check_component(cid: str, spec: dict, fp: Path, env: dict[str, str], only: str | None) -> dict:
    """Mutate the component in REMORA's own tree, rebuild the signed fixtures that carry its
    digest, install both into the federation-port checkout and run the component's tests."""
    installed = Path(env[spec["installed_env"]])
    interop = Path(env["REMORA_INTEROP_DIR"])
    source_adapter = spec["source"] / "adapter.ts"
    original = source_adapter.read_text(encoding="utf-8")
    if installed.resolve() != spec["source"].resolve() and (installed / "adapter.ts").read_text(encoding="utf-8") != original:
        raise SystemExit(f"{cid}: installed adapter differs from {spec['source']}")

    # Everything the fixture builder rewrites, saved for restoration.
    touched: list[Path] = [c["source"] / "adapter.ts" for c in COMPONENTS.values()]
    touched += [c["source"] / "manifest.json" for c in COMPONENTS.values()]
    touched += [FIXTURES_DIR / f for f in FIXTURE_FILES]
    touched += [installed / "adapter.ts", installed / "manifest.json"]
    touched += [interop / f for f in FIXTURE_FILES]
    saved = {p: p.read_bytes() for p in dict.fromkeys(touched) if p.exists()}

    equivalents_path = spec["source"] / "mutation-equivalents.json"
    equivalents: dict[str, str] = {}
    if equivalents_path.exists():
        equivalents = {e["id"]: e["justification"] for e in json.loads(equivalents_path.read_text())["equivalent"]}

    def install(text: str) -> None:
        source_adapter.write_text(text, encoding="utf-8", newline="\n")
        # Reseal both manifests and re-sign the fixtures, exactly as the committed ones are made.
        proc = subprocess.run([sys.executable, str(FIXTURE_BUILDER), "--seal", "--write"],
                              cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"{cid}: fixture builder failed on a mutant\n{proc.stdout}{proc.stderr}")
        for name in ("adapter.ts", "manifest.json"):
            (installed / name).write_bytes((spec["source"] / name).read_bytes())
        for name in FIXTURE_FILES:
            (interop / name).write_bytes((FIXTURES_DIR / name).read_bytes())

    results: list[Result] = []
    controls: dict[str, str] = {}
    try:
        # Baseline: the unmutated component passes.
        outcome, passed, failed, failing = run_tests(fp, spec["test"], env)
        if outcome != "survived":
            raise SystemExit(f"{cid}: baseline does not pass ({outcome}: {failing[:3]})")
        baseline = passed
        # Controls.
        install(original + "\n// inert control\n")
        controls["inert"] = run_tests(fp, spec["test"], env)[0]
        a, b = spec["positive_control"]
        if a not in original:
            raise SystemExit(f"{cid}: positive control anchor not found")
        install(original.replace(a, b, 1))
        controls["positive"] = run_tests(fp, spec["test"], env)[0]

        mutants = generate(original)
        if only:
            mutants = [m for m in mutants if only in m.id]
        for mut in mutants:
            install(mut.source)
            outcome, passed, failed, failing = run_tests(fp, spec["test"], env)
            results.append(Result(mut.id, mut.operator, mut.line, mut.description, outcome, passed, failed, failing[:5]))
    finally:
        for path, data in saved.items():
            path.write_bytes(data)

    survivors = [r for r in results if r.outcome == "survived"]
    unexplained = [r for r in survivors if r.id not in equivalents]
    stale = [i for i in equivalents if i not in {r.id for r in survivors}]
    return {
        "component": cid,
        "test": spec["test"],
        "baseline_tests": baseline,
        "controls": controls,
        "mutants": len(results),
        "killed": sum(1 for r in results if r.outcome == "killed"),
        "crashed": sum(1 for r in results if r.outcome == "crashed"),
        "survived": len(survivors),
        "equivalent_listed": len(equivalents),
        "unexplained_survivors": [r.__dict__ for r in unexplained],
        "stale_equivalents": stale,
        "results": [r.__dict__ for r in results],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="write the JSON report here")
    parser.add_argument("--component", action="append", choices=sorted(COMPONENTS), help="limit to one component")
    parser.add_argument("--only", help="run only mutant ids containing this text")
    parser.add_argument("--list", action="store_true", help="list mutants and exit")
    args = parser.parse_args(argv)

    fp = Path(os.environ.get("FEDERATION_PORT_DIR", "")).resolve()
    if not fp.is_dir():
        print("set FEDERATION_PORT_DIR to a federation-port checkout with the components installed", file=sys.stderr)
        return 2
    env = dict(os.environ)
    env["FEDERATION_PORT_DIR"] = str(fp)
    for cid, spec in COMPONENTS.items():
        if spec["installed_env"] not in env:
            print(f"set {spec['installed_env']} (installed {cid})", file=sys.stderr)
            return 2
    if "REMORA_INTEROP_DIR" not in env:
        print("set REMORA_INTEROP_DIR (installed fixtures)", file=sys.stderr)
        return 2

    report: dict = {"schema_version": "remora-federation-port-mutation-check-v1",
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "components": []}
    status = 0
    for cid, spec in COMPONENTS.items():
        if args.component and cid not in args.component:
            continue
        if args.list:
            for m in generate((spec["source"] / "adapter.ts").read_text(encoding="utf-8")):
                print(f"{cid}\t{m.id}\t{m.description}")
            continue
        c = check_component(cid, spec, fp, env, args.only)
        report["components"].append(c)
        ok = (c["controls"].get("inert") == "survived" and c["controls"].get("positive") == "killed"
              and not c["unexplained_survivors"] and not c["stale_equivalents"])
        print(f"== {cid}: {c['mutants']} mutants, {c['killed']} killed, {c['crashed']} crashed, "
              f"{c['survived']} survived ({c['equivalent_listed']} listed equivalent); "
              f"controls inert={c['controls'].get('inert')} positive={c['controls'].get('positive')}")
        for r in c["unexplained_survivors"]:
            print(f"   SURVIVED {r['id']}: {r['description']}")
        for i in c["stale_equivalents"]:
            print(f"   STALE equivalent entry no longer survives (or line changed): {i}")
        if not ok:
            status = 1
    if args.list:
        return 0
    check = subprocess.run([sys.executable, str(FIXTURE_BUILDER), "--check"], cwd=ROOT, capture_output=True, text=True)
    report["restored"] = check.returncode == 0
    if check.returncode != 0:
        print("[FAIL] the tree was not restored: " + check.stdout.strip())
        status = 1
    report["status"] = "pass" if status == 0 else "fail"
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("[PASS] every non-equivalent fault is killed" if status == 0 else "[FAIL] unexplained survivors or stale equivalents")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
