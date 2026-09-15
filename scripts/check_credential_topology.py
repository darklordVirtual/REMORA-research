#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Credential-topology gate: the static half of Agent Authority property E.

Property E (execution-boundary integrity) asks whether a protected side
effect can be reached ONLY through the controlled path. Until now that
question reduced, in this repository and in the conformance model itself,
to an argument about credential topology, which the model's own section 8
records as the one property with no measurement procedure.

This gate turns the argument into a check. It refuses to let the topology
drift silently:

* **Declaration.** Every secret-bearing environment variable read anywhere
  under the scanned roots must appear in the register. A credential the
  register does not know about cannot have been reasoned about.
* **Drift.** The register's ``read_by`` set must equal the set of modules
  the AST scan actually finds. A stale entry (credential removed) and an
  undeclared new reader both fail, so the register cannot rot into prose.
* **Reachability.** A credential declared ``agent_reachable: false`` must
  not be read by any module inside the agent zone, the transitive import
  closure of the declared agent-facing roots. This is the falsifiable core:
  it is a statement about the import graph, not about intent.
* **Dynamic reads.** An ``os.environ`` read whose key this scanner cannot
  resolve statically is an opaque hole in the topology, so each one must be
  declared with a reason. Undeclared opacity fails.

What it does NOT establish, and what the bypass suite
(``tests/conformance/test_execution_boundary.py``) exists to cover:
process co-residency (a credential in the same process is readable whether
or not any module imports it), delegated reachability through an already
authenticated client or subprocess, and any credential supplied by
deployment configuration rather than the environment. Those limits are
declared in the register's ``limits`` block and are reproduced in the
conformance assessment; a PASS here is scoped to in-repository environment
credential topology and claims nothing wider.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "credential_topology.yaml"

#: Relative location of the register under whichever root is scanned.
REGISTER_REL = Path("docs") / "assurance" / "credential_topology.yaml"


def set_root(root: Path) -> None:
    """Point the gate at another tree (``--root``, and the meta-tests)."""
    global ROOT, REGISTER
    ROOT = root.resolve()
    REGISTER = ROOT / REGISTER_REL

#: A name matching this is treated as secret-bearing and MUST be declared.
#: Widening it is safe (more declarations); narrowing it is a weakening of
#: the gate and needs the same scrutiny as removing a test.
SECRET = re.compile(
    r"(^|_)(KEY|KEYS|TOKEN|TOKENS|SECRET|PASSWORD|PASSWD|DSN"
    r"|CREDENTIAL|CREDENTIALS|APIKEY|HMAC|BEARER)($|_)"
)

#: Classes whose credentials reach something worth protecting. Each carries
#: the full obligation set (holder, authorized_path, agent_reachable false).
PROTECTED_CLASSES = {"effect_credential", "authority_key", "state_backend"}
#: Declared, deliberately weaker classes. They still must be declared and
#: still must not drift, but they carry no non-reachability obligation.
OPEN_CLASSES = {"oracle_credential", "transport_credential", "non_effect"}
ALL_CLASSES = PROTECTED_CLASSES | OPEN_CLASSES


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _module_consts(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, for indirect env reads."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    out[target.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                out[node.target.id] = node.value.value
    return out


def _environ_bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Names bound to ``os.environ`` and to ``os.getenv`` in this module.

    Before 2026-09 the scanner recognised only the attribute spellings
    (``os.getenv(...)``, ``<x>.environ.get(...)``), so ``from os import
    environ`` followed by ``environ.get("REMORA_SIGNING_KEY")`` was an
    invisible read of a secret. Resolving the import aliases closes that
    hole; it can only widen what the gate sees.
    """
    environ_names: set[str] = {"environ"}
    getenv_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "environ":
                    environ_names.add(alias.asname or alias.name)
                elif alias.name == "getenv":
                    getenv_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            value = node.value
            is_environ = (
                isinstance(value, ast.Attribute) and value.attr == "environ"
            ) or (isinstance(value, ast.Name) and value.id in environ_names)
            if is_environ:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        environ_names.add(target.id)
    return environ_names, getenv_names


def _injected_environ_args(tree: ast.Module) -> dict[str, set[str]]:
    """Function parameters named ``environ``: the mapping is caller-supplied.

    A dependency-injected mapping is opaque to a static scan by
    construction: this scanner cannot know whether the caller passes
    ``os.environ`` or a fixture. Reads through such a parameter are
    therefore reported as dynamic read sites, which must be declared with a
    reason, rather than being silently resolved or silently missed.
    """
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            names = {
                a.arg
                for a in (
                    *args.posonlyargs,
                    *args.args,
                    *args.kwonlyargs,
                    *([args.vararg] if args.vararg else []),
                    *([args.kwarg] if args.kwarg else []),
                )
                if a.arg == "environ"
            }
            if names:
                out.setdefault(node.name, set()).update(names)
    return out


def _is_environ_call(
    node: ast.Call,
    environ_names: frozenset[str] = frozenset({"environ"}),
    getenv_names: frozenset[str] = frozenset(),
) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in getenv_names
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "getenv":
        return True
    if func.attr == "get":
        if isinstance(func.value, ast.Attribute):
            return func.value.attr == "environ"
        if isinstance(func.value, ast.Name):
            return func.value.id in environ_names
    return False


def _is_environ_target(node: ast.expr, environ_names: set[str]) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    if isinstance(node, ast.Name):
        return node.id in environ_names
    return False


def scan_env_reads(path: Path) -> tuple[dict[str, set[str]], list[str]]:
    """Return ({env name: {module}}, [unresolved read site]) for one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return {}, []
    consts = _module_consts(tree)
    rel = _rel(path)
    found: dict[str, set[str]] = {}
    dynamic: list[str] = []

    environ_names, getenv_names = _environ_bindings(tree)
    injected = _injected_environ_args(tree)
    # A parameter named ``environ`` shadows any module-level binding inside
    # its function, and the mapping it carries is unknown to this scan.
    injected_names = {n for names in injected.values() for n in names}

    def record(name: str) -> None:
        found.setdefault(name, set()).add(rel)

    def read(node: ast.AST, key: ast.expr | None, opaque: bool) -> None:
        if opaque:
            # The key is statically visible, so the credential is still
            # declarable and still subject to the drift check; what is
            # opaque is WHICH mapping the caller passed in. Both facts are
            # recorded: the reader, and the opacity of the site.
            dynamic.append(f"{rel}:{node.lineno}")  # type: ignore[attr-defined]
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            record(key.value)
        elif isinstance(key, ast.Name) and key.id in consts:
            record(consts[key.id])
        elif not opaque:
            dynamic.append(f"{rel}:{node.lineno}")  # type: ignore[attr-defined]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_environ_call(
            node, frozenset(environ_names), frozenset(getenv_names)
        ):
            if not node.args:
                continue
            opaque = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in injected_names
            )
            read(node, node.args[0], opaque)
        elif isinstance(node, ast.Subscript) and _is_environ_target(
            node.value, environ_names | injected_names
        ):
            opaque = (
                isinstance(node.value, ast.Name)
                and node.value.id in injected_names
            )
            read(node, node.slice, opaque)
    return found, sorted(set(dynamic))


_IMPORT_MODULE = re.compile(
    r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.M
)


def _module_name(path: Path) -> str:
    name = _rel(path).removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def import_closure(roots: list[str], files: list[Path]) -> set[str]:
    """Transitive import closure of ``roots`` over the scanned files.

    Conservative in the safe direction: an edge the regex misses shrinks the
    zone, so a missed edge can only turn a real finding into a miss, never a
    false accusation. That asymmetry is why a PASS here is stated as "no
    demonstrable reachability" rather than "unreachable".
    """
    by_name = {_module_name(p): p for p in files}
    edges: dict[str, set[str]] = {}
    for name, path in by_name.items():
        text = path.read_text(encoding="utf-8", errors="ignore")
        targets: set[str] = set()
        for frm, imp in _IMPORT_MODULE.findall(text):
            mod = frm or imp
            # Attribute the edge to any declared module the import prefixes.
            for candidate in by_name:
                if mod == candidate or mod.startswith(candidate + "."):
                    targets.add(candidate)
        edges[name] = targets

    root_names = {r.replace("/", ".").removesuffix(".py") for r in roots}
    seen: set[str] = set()
    stack = [
        n
        for n in by_name
        if any(n == r or n.startswith(r + ".") for r in root_names)
    ]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(edges.get(cur, set()) - seen)
    return {_rel(by_name[n]) for n in seen}


def collect(register: dict) -> tuple[dict[str, set[str]], list[str], list[Path]]:
    scope = register["scope"]
    excluded = tuple(e["path"] for e in scope.get("excluded", []))
    files: list[Path] = []
    for root in scope["scanned_roots"]:
        for path in sorted((ROOT / root).rglob("*.py")):
            rel = _rel(path)
            if excluded and rel.startswith(excluded):
                continue
            files.append(path)
    reads: dict[str, set[str]] = {}
    dynamic: list[str] = []
    for path in files:
        found, dyn = scan_env_reads(path)
        for name, mods in found.items():
            reads.setdefault(name, set()).update(mods)
        dynamic.extend(dyn)
    return reads, sorted(set(dynamic)), files


def check(register: dict) -> list[str]:
    failures: list[str] = []
    reads, dynamic, files = collect(register)
    declared = {c["name"]: c for c in register["credentials"]}
    secrets = {n: m for n, m in reads.items() if SECRET.search(n)}

    for name in sorted(secrets):
        if name not in declared:
            where = ", ".join(sorted(secrets[name]))
            failures.append(
                f"{name}: read at {where} but absent from the register. "
                "Declare it with a class and a holder."
            )

    for name, entry in sorted(declared.items()):
        cls = entry.get("class")
        if cls not in ALL_CLASSES:
            failures.append(f"{name}: unknown class {cls!r}")
            continue
        actual = secrets.get(name, set())
        stated = set(entry.get("read_by", ()))
        if not actual:
            failures.append(
                f"{name}: declared but no longer read under the scanned roots. "
                "Remove the entry, because a register that keeps dead "
                "credentials stops describing the system."
            )
            continue
        if stated != actual:
            missing = ", ".join(sorted(actual - stated)) or "-"
            extra = ", ".join(sorted(stated - actual)) or "-"
            failures.append(
                f"{name}: read_by drift. Undeclared readers: {missing}. "
                f"Declared but not reading: {extra}."
            )
        if cls in PROTECTED_CLASSES:
            for field in ("holder", "authorized_path", "note"):
                if not entry.get(field):
                    failures.append(
                        f"{name}: class {cls} requires a non-empty {field}"
                    )
            if entry.get("agent_reachable") is not False:
                failures.append(
                    f"{name}: class {cls} requires an explicit "
                    "'agent_reachable: false' claim for this gate to test"
                )
        elif "agent_reachable" not in entry or not entry.get("note"):
            failures.append(
                f"{name}: every entry needs 'agent_reachable' and a 'note'"
            )

    zone = import_closure(register["agent_zone_roots"], files)
    for name, entry in sorted(declared.items()):
        if entry.get("agent_reachable") is not False:
            continue
        breached = sorted(secrets.get(name, set()) & zone)
        if breached:
            failures.append(
                f"{name}: declared unreachable from the agent zone, but read by "
                f"{', '.join(breached)}, which the agent zone transitively "
                "imports. Either the claim is false or the module belongs "
                "outside the zone."
            )

    allowed_dynamic = {d["site"] for d in register.get("dynamic_read_sites", [])}
    for site in dynamic:
        if site not in allowed_dynamic:
            failures.append(
                f"{site}: environment read with a key this scanner cannot "
                "resolve. Declare it in dynamic_read_sites with a reason, or "
                "read a module-level constant so the topology stays visible."
            )
    for site in sorted(allowed_dynamic - set(dynamic)):
        failures.append(f"{site}: declared dynamic read site no longer exists")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="scan this tree instead of the repository root",
    )
    args = parser.parse_args(argv)
    if args.root is not None:
        set_root(args.root)

    if not REGISTER.exists():
        print(f"[FAIL] credential topology: missing {_rel(REGISTER)}", file=sys.stderr)
        return 1
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    failures = check(register)
    if failures:
        print(
            f"[FAIL] credential topology: {len(failures)} finding(s):",
            file=sys.stderr,
        )
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        print(
            "Fix the topology or the declaration. Widening a class to silence "
            "a reachability finding is a weakening: record the finding "
            "instead.",
            file=sys.stderr,
        )
        return 1
    n = len(register["credentials"])
    print(
        f"[PASS] credential topology: {n} declared credential(s); no declared "
        "unreachable credential is read from the agent zone; no undeclared "
        "secret or opaque environment read. Scope: in-repository environment "
        "credentials only. Process co-residency, delegated clients and "
        "deployment-supplied credentials are the bypass suite's subject."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
