#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Verify the replication pack against the committed artifacts.

``artifacts/replication-pack/replication_pack_v1.json`` lists, for each
active headline claim, the artifacts it rests on with their LF SHA-256
(docs/assurance/artifact_manifest_v1.md protocol), the claim's metric values
with the JSON field each one must equal, and the offline commands that
regenerate or structurally validate it. This script checks that list.

``--check`` (default, offline, a few seconds)
    Every listed artifact hash, every integrity pin and every metric value
    against the committed files; the pinned environment (requirements lock
    hash, the digest-pinned base image in deploy/reference/Dockerfile); and
    that the pack has not drifted from the claim register and the results
    manifest: each metric the pack takes from the register carries the
    register's value and binding, each artifact carries its results-manifest
    class, and every active claim is either in the pack or excluded with a
    reason. Exits 1 on any mismatch.

``--regenerate``
    Everything ``--check`` does, then runs each entry's commands in a
    temporary git worktree of HEAD (the committed tree, never the working
    tree) and compares the outputs: ``lf_sha256`` entries must be byte
    identical, ``fields`` entries must match apart from the listed volatile
    fields, and every metric is re-resolved against the regenerated files.
    Entries whose mode is ``none`` (sealed or imported results) are only
    checked, never re-run. Needs git and the package's dependencies.

    python scripts/verify_replication_pack.py
    python scripts/verify_replication_pack.py --regenerate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_claim_metric_bindings import wilson_upper  # noqa: E402
from reproduce_results import compare_entry  # noqa: E402

PACK = Path("artifacts/replication-pack/replication_pack_v1.json")
COMMAND_TIMEOUT_S = 600

_DERIVED = re.compile(r"^wilson_upper\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$")
_FROM_LINE = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)


class PackError(Exception):
    """A pointer or binding in the pack could not be resolved."""


# --------------------------------------------------------------------------
# primitives


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class Resolver:
    """Resolves ``<file>#<dotted.path[i]>`` pointers under one root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, Any] = {}

    def load(self, relative: str) -> Any:
        relative = relative.strip()
        if relative not in self._cache:
            path = self.root / relative
            if not path.is_file():
                raise PackError(f"{relative} does not exist")
            try:
                self._cache[relative] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise PackError(f"{relative} is not valid JSON ({exc})") from exc
        return self._cache[relative]

    def value(self, pointer: str) -> Any:
        if "#" not in pointer:
            raise PackError(f"pointer {pointer!r} has no '#<path>' half")
        relative, path = pointer.split("#", 1)
        node = self.load(relative)
        for part in path.strip().split("."):
            if not part:
                continue
            index = None
            if part.endswith("]") and "[" in part:
                part, raw = part[:-1].split("[", 1)
                index = int(raw)
            if part:
                if not isinstance(node, dict) or part not in node:
                    raise PackError(f"{relative}: no key {part!r} on the way to {path!r}")
                node = node[part]
            if index is not None:
                if not isinstance(node, list) or index >= len(node):
                    raise PackError(f"{relative}: index [{index}] out of range in {path!r}")
                node = node[index]
        return node

    def number(self, pointer: str) -> float:
        node = self.value(pointer)
        if isinstance(node, bool) or not isinstance(node, (int, float)):
            raise PackError(f"{pointer} resolves to {node!r}, not a number")
        return float(node)


def metric_actual(resolver: Resolver, binding: dict) -> Any:
    """The value a binding produces, after scale and before rounding."""
    scale = float(binding.get("scale", 1))
    if "path" in binding:
        raw = resolver.value(str(binding["path"]))
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return raw
        return float(raw) * scale
    if "derived" in binding:
        match = _DERIVED.match(str(binding["derived"]).strip())
        if not match:
            raise PackError(f"derivation {binding['derived']!r} is not wilson_upper(<k>, <n>)")
        k = resolver.number(match.group(1))
        n = resolver.number(match.group(2))
        return wilson_upper(k, n) * scale
    if "ratio" in binding:
        num, den = binding["ratio"]
        d = resolver.number(den)
        if d == 0:
            raise PackError(f"ratio denominator {den} is zero")
        return resolver.number(num) / d * scale
    raise PackError("binding declares none of path, derived or ratio")


def metric_matches(expected: Any, actual: Any, binding: dict, tolerance: float) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        # True == 1.0 in Python; a boolean claim needs a boolean field.
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, str):
        return expected == actual
    if not isinstance(actual, (int, float)):
        return False
    if "rounded_to" in binding:
        return abs(round(actual, int(binding["rounded_to"])) - float(expected)) <= 1e-9
    return abs(actual - float(expected)) <= tolerance


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    text = str(value)
    # Full hashes are in the pack; the table shows enough to tell them apart.
    return text[:16] + "..." if _HEX64.match(text) else text


# --------------------------------------------------------------------------
# report


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, str, str]] = []

    def add(self, claim: str, check: str, subject: str, expected: Any, actual: Any,
            status: str) -> None:
        self.rows.append((claim, check, subject, _fmt(expected), _fmt(actual), status))

    @property
    def failures(self) -> list[tuple[str, ...]]:
        return [r for r in self.rows if r[-1] == "FAIL"]

    def print(self) -> None:
        header = ("claim", "check", "subject", "expected", "actual", "status")
        widths = [len(h) for h in header]
        clipped = []
        for row in self.rows:
            row = tuple(c if len(c) <= 72 else c[:34] + "..." + c[-35:] for c in row)
            clipped.append(row)
            widths = [max(w, len(c)) for w, c in zip(widths, row)]
        line = "  ".join(h.ljust(w) for h, w in zip(header, widths))
        print(line)
        print("  ".join("-" * w for w in widths))
        for row in clipped:
            print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


# --------------------------------------------------------------------------
# --check


def _load_yaml(path: Path) -> Any:
    import yaml  # the gates that read registers all depend on PyYAML

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_environment(pack: dict, root: Path, report: Report) -> None:
    env = pack["environment"]
    lock = env["requirements_lock"]
    lock_path = root / lock["path"]
    actual = sha256_lf(lock_path) if lock_path.is_file() else "<missing>"
    report.add("env", "sha256", lock["path"], lock["sha256_lf"], actual,
               "OK" if actual == lock["sha256_lf"] else "FAIL")

    image = env["reference_image"]
    dockerfile = root / image["dockerfile"]
    pinned = f"{image['base_image']}@{image['base_digest']}"
    froms = _FROM_LINE.findall(dockerfile.read_text(encoding="utf-8")) if dockerfile.is_file() else []
    ok = bool(froms) and all(f == pinned for f in froms)
    report.add("env", "base image", image["dockerfile"], pinned,
               ", ".join(sorted(set(froms))) or "<no FROM line>", "OK" if ok else "FAIL")

    if env.get("image") is None:
        has_reason = bool(str(env.get("image_reason", "")).strip())
        report.add("env", "image", "published image", "null + reason",
                   "null + reason" if has_reason else "null, no reason",
                   "OK" if has_reason else "FAIL")
    else:
        report.add("env", "image", "published image", "a digest the pack can prove",
                   env["image"], "FAIL")


def check_entry(entry: dict, resolver: Resolver, tolerance: float, report: Report) -> None:
    claim = entry["claim_id"]
    root = resolver.root
    for art in entry["artifacts"]:
        path = root / art["path"]
        actual = sha256_lf(path) if path.is_file() else "<missing>"
        report.add(claim, "sha256", art["path"], art["sha256_lf"], actual,
                   "OK" if actual == art["sha256_lf"] else "FAIL")

    for pin in entry.get("integrity", []):
        fail = "WARN" if pin.get("advisory") else "FAIL"
        subject = pin["pointer"].split("#", 1)[-1]
        try:
            if pin["kind"] == "equals":
                expected, actual = pin["expected"], resolver.value(pin["pointer"])
            elif pin["kind"] == "sha256_of":
                expected = resolver.value(pin["pointer"])
                target = root / pin["file"]
                actual = sha256_lf(target) if target.is_file() else "<missing>"
                subject = pin["file"]
            elif pin["kind"] == "same_value":
                expected, actual = resolver.value(pin["other"]), resolver.value(pin["pointer"])
            else:
                raise PackError(f"unknown integrity kind {pin['kind']!r}")
            status = "OK" if expected == actual else fail
        except PackError as exc:
            expected, actual, status = pin.get("expected", "?"), f"<{exc}>", fail
        report.add(claim, "integrity", subject, expected, actual, status)

    for metric in entry["metrics"]:
        binding = metric["binding"]
        try:
            actual = metric_actual(resolver, binding)
            ok = metric_matches(metric["expected"], actual, binding, tolerance)
        except PackError as exc:
            actual, ok = f"<{exc}>", False
        report.add(claim, f"metric ({metric['source']})", metric["name"],
                   metric["expected"], actual, "OK" if ok else "FAIL")


def check_drift(pack: dict, root: Path, report: Report) -> None:
    """The pack must say what the register and the results manifest say."""
    sources = pack["sources"]
    register = _load_yaml(root / sources["claim_register"])
    claims = {c["id"]: c for c in register.get("claims", [])}
    manifest = _load_yaml(root / sources["results_manifest"])
    classes = {e["path"]: e["class"] for e in manifest.get("results", [])}

    active = {cid for cid, c in claims.items() if c.get("status") == "active"}
    in_pack = [e["claim_id"] for e in pack["entries"]]
    excluded = [e["claim_id"] for e in pack.get("excluded", [])]

    def bound(claim: dict) -> bool:
        bindings = claim.get("metric_bindings") or {}
        return any(isinstance(b, dict) and ("path" in b or "derived" in b)
                   for b in bindings.values())

    problems: list[tuple[str, str, str, str]] = []
    for cid in sorted(set(in_pack) | set(excluded)):
        if cid not in claims:
            problems.append((cid, "register", "claim exists", "absent from the register"))
        elif cid not in active:
            problems.append((cid, "register", "status active", str(claims[cid].get("status"))))
    for cid in sorted(active - set(in_pack) - set(excluded)):
        problems.append((cid, "coverage", "in the pack or excluded with a reason", "neither"))
    for cid in sorted(set(in_pack) & set(excluded)):
        problems.append((cid, "coverage", "in the pack or excluded", "both"))
    for cid in sorted({c for c in in_pack if in_pack.count(c) > 1}):
        problems.append((cid, "coverage", "one pack entry", "duplicated"))
    for item in pack.get("excluded", []):
        cid = item["claim_id"]
        if not str(item.get("reason", "")).strip():
            problems.append((cid, "coverage", "an exclusion reason", "empty"))
        if cid in claims and bound(claims[cid]):
            problems.append((cid, "coverage", "machine-bound claims are in the pack",
                             "excluded although it has a path or derived metric binding"))

    for entry in pack["entries"]:
        cid = entry["claim_id"]
        claim = claims.get(cid, {})
        reg_metrics = claim.get("metrics") or {}
        reg_bindings = claim.get("metric_bindings") or {}
        reg_artifacts = set(claim.get("artifact") or [])
        for art in entry["artifacts"]:
            path = art["path"]
            if path.startswith("results/"):
                want = classes.get(path, "<not in results manifest>")
                if art.get("results_manifest_class") != want:
                    problems.append((cid, "class", f"{path}: {want}",
                                     str(art.get("results_manifest_class"))))
        listed = {a["path"] for a in entry["artifacts"]} | {
            n["path"] for n in entry.get("not_hashed", [])}
        for path in sorted(reg_artifacts - listed):
            problems.append((cid, "artifact", f"{path} listed or not_hashed", "missing from pack"))
        packed_names = {m["name"] for m in entry["metrics"]} | {
            m["name"] for m in entry.get("unbound_metrics", [])}
        for name, value in reg_metrics.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and name not in packed_names:
                problems.append((cid, "metric", f"{name} in the pack", "missing"))
        for metric in entry["metrics"]:
            name = metric["name"]
            if metric["source"] == "register":
                if reg_metrics.get(name) != metric["expected"]:
                    problems.append((cid, "metric", f"{name} = register {reg_metrics.get(name)}",
                                     _fmt(metric["expected"])))
                reg = {k: v for k, v in (reg_bindings.get(name) or {}).items()
                       if k in ("path", "derived", "scale", "rounded_to")}
                if reg != metric["binding"]:
                    problems.append((cid, "binding", f"{name} = register binding",
                                     "differs from the register"))
            elif name in reg_metrics and reg_metrics[name] != metric["expected"]:
                problems.append((cid, "metric", f"{name} = register {reg_metrics[name]}",
                                 _fmt(metric["expected"])))

    if not problems:
        report.add("pack", "drift", "register + results manifest", "consistent", "consistent", "OK")
    for cid, check, expected, actual in problems:
        report.add(cid, f"drift ({check})", "", expected, actual, "FAIL")


def run_check(pack: dict, root: Path, report: Report) -> None:
    tolerance = float(pack.get("metric_tolerance", 5e-3))
    check_environment(pack, root, report)
    resolver = Resolver(root)
    for entry in pack["entries"]:
        check_entry(entry, resolver, tolerance, report)
    check_drift(pack, root, report)


# --------------------------------------------------------------------------
# --regenerate


def _run(cmd: str, cwd: Path) -> tuple[int, float, str]:
    argv = shlex.split(cmd)
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    env = dict(os.environ, PYTHONPATH=str(cwd))
    start = time.monotonic()
    proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=COMMAND_TIMEOUT_S)
    tail = " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:])
    return proc.returncode, time.monotonic() - start, tail


def run_regenerate(pack: dict, root: Path, report: Report) -> None:
    tolerance = float(pack.get("metric_tolerance", 5e-3))
    workdir = Path(tempfile.mkdtemp(prefix="remora-replication-"))
    tree = workdir / "tree"
    subprocess.run(["git", "worktree", "add", "--detach", "--quiet", str(tree), "HEAD"],
                   cwd=root, check=True)
    try:
        for entry in pack["entries"]:
            claim = entry["claim_id"]
            regen = entry["regenerate"]
            if regen["mode"] == "none":
                report.add(claim, "regenerate", "-", "not re-run", "not re-run", "SKIP")
                continue
            ok = True
            for command in regen["commands"]:
                code, secs, tail = _run(command["run"], tree)
                ok = ok and code == 0
                report.add(claim, "run", command["run"], "exit 0",
                           f"exit {code} in {secs:.1f}s" + (f": {tail}" if code else ""),
                           "OK" if code == 0 else "FAIL")
            if not ok:
                continue
            for cmp in regen["compare"]:
                path = cmp["path"]
                new_path = tree / path
                if not new_path.is_file():
                    report.add(claim, "compare", path, "file written", "<missing>", "FAIL")
                    continue
                if cmp["match"] == "lf_sha256":
                    want = next((a["sha256_lf"] for a in entry["artifacts"] if a["path"] == path),
                                sha256_lf(root / path))
                    got = sha256_lf(new_path)
                    report.add(claim, "compare lf_sha256", path, want, got,
                               "OK" if got == want else "FAIL")
                else:
                    changed = compare_entry(
                        cmp,
                        json.loads((root / path).read_text(encoding="utf-8")),
                        json.loads(new_path.read_text(encoding="utf-8")))
                    shown = ", ".join(changed[:4]) + (" ..." if len(changed) > 4 else "")
                    report.add(claim, "compare fields", path,
                               f"equal except {', '.join(cmp.get('volatile', [])) or 'nothing'}",
                               shown or "equal", "FAIL" if changed else "OK")
            regenerated = Resolver(tree)
            written = {c["path"] for c in regen["compare"]}
            for metric in entry["metrics"]:
                binding = metric["binding"]
                files = {str(v).split("#", 1)[0].strip() for v in _pointers(binding)}
                if not files <= written:
                    continue
                try:
                    actual = metric_actual(regenerated, binding)
                    good = metric_matches(metric["expected"], actual, binding, tolerance)
                except PackError as exc:
                    actual, good = f"<{exc}>", False
                report.add(claim, "regenerated metric", metric["name"], metric["expected"],
                           actual, "OK" if good else "FAIL")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root,
                       capture_output=True)
        shutil.rmtree(workdir, ignore_errors=True)


def _pointers(binding: dict) -> list[str]:
    if "path" in binding:
        return [binding["path"]]
    if "ratio" in binding:
        return list(binding["ratio"])
    if "derived" in binding:
        match = _DERIVED.match(str(binding["derived"]).strip())
        return [match.group(1), match.group(2)] if match else []
    return []


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="offline hash and metric check (default)")
    mode.add_argument("--regenerate", action="store_true",
                      help="also re-run regenerable entries in a temporary worktree of HEAD")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--pack", type=Path, default=None, help="pack file (default: under --root)")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    pack_path = args.pack or root / PACK
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    if pack.get("schema") != "remora_replication_pack_v1":
        print(f"[FAIL] {pack_path}: unknown schema {pack.get('schema')!r}")
        return 1
    if not pack.get("entries"):
        print(f"[FAIL] {pack_path}: no entries; a pack that checks nothing is not evidence")
        return 1

    report = Report()
    run_check(pack, root, report)
    if args.regenerate:
        run_regenerate(pack, root, report)
    report.print()

    failures = report.failures
    warnings = sum(1 for r in report.rows if r[-1] == "WARN")
    print()
    if failures:
        print(f"[FAIL] replication pack: {len(failures)} of {len(report.rows)} checks failed.")
        return 1
    print(f"[PASS] replication pack: {len(report.rows)} checks over {len(pack['entries'])} "
          f"claims, {len(pack.get('excluded', []))} claims excluded with reasons"
          + (f", {warnings} advisory warning(s)" if warnings else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
