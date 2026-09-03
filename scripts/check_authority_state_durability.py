#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every in-process authority store must say what losing it does.

One defect class has recurred four times here: the consumed-jti ledger
(#350), the lease nonce ledger, principal revocation (#502), and the
revocation store's wiring on the D1 backend. Each time a durable backend the
deployment already ran was used by one component and not by another. Each
time it was found by a reviewer or an audit, never by a gate. The second
occurrence's own docstring names the pattern, and the rest happened anyway.

This is the gate. It checks two populations.

The STORES are discovered by AST rather than trusted to a hand-maintained
list, so a new store cannot be added without answering the same question the
previous occurrences failed to answer:

    when this state is lost, does something become executable that was
    refused before?

If yes (``on_loss: reauthorizes``) a durable adapter is required. If no
(``on_loss: loses_evidence``) a tracking item is required, so the gap is a
stated decision rather than an omission.

The WIRING points are declared, and each must read every switch the
durability guard in servers/api.py admits. That is the check the fourth
occurrence needed: its adapter was declared and worked, and the selection
code simply never looked at REMORA_STATE_ENDPOINT.

    python scripts/check_authority_state_durability.py

Exit 0 when every discovered store is declared and every declaration holds.
"""
from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "authority_state_topology.yaml"
PACKAGE = ROOT / "remora"

#: Discovery heuristic: a class whose ``__init__`` creates both a lock and a
#: mutable container is holding shared state that survives a call and does
#: not survive a process. That is the shape of all three past occurrences.
_LOCKS = {"Lock", "RLock"}
_CONTAINERS = {"set", "dict", "list", "OrderedDict", "defaultdict"}

_ON_LOSS = {"reauthorizes", "loses_evidence"}


def _display(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    ``relative_to`` raises for a path outside the repository, and this is
    called while BUILDING an error message. A crash there would replace the
    finding with a traceback, which is strictly worse than the finding.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def discover() -> set[str]:
    """Every ``path::ClassName`` holding lock-guarded mutable state."""
    found: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            init = next(
                (n for n in node.body
                 if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                None,
            )
            if init is None:
                continue
            has_lock = has_container = False
            for sub in ast.walk(init):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else getattr(func, "id", ""))
                    if name in _LOCKS:
                        has_lock = True
                    if name in _CONTAINERS:
                        has_container = True
                if isinstance(sub, (ast.Set, ast.Dict, ast.List)):
                    has_container = True
            if has_lock and has_container:
                rel = path.relative_to(ROOT).as_posix()
                found.add(f"{rel}::{node.name}")
    return found


def _symbol_source(module: Path, name: str) -> str | None:
    """The source of the top-level function or assignment called ``name``.

    A durable store is selected either by a factory function
    (``_revocation_store``) or by a module-level construction (``_GATE``), so
    both shapes have to be readable. Returns None when the name is absent,
    which the caller reports as a stale declaration rather than a pass.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return ast.unparse(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                return ast.unparse(node)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name:
                return ast.unparse(node)
    return None


def _check_wiring(entries: list[dict], declared: dict[str, dict]) -> list[str]:
    """Every wiring point must reach every backend the guard admits.

    The register's first version checked only that a durable adapter was
    DECLARED. The fourth occurrence of the defect class had a declared
    adapter and a working one; what was missing was a switch in the
    selection code, one level below anything the register looked at.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        wid = entry.get("id", "?")
        symbol = entry.get("symbol")
        if not symbol or "::" not in symbol:
            errors.append(f"{wid}: wiring needs a 'file.py::name' symbol")
            continue
        if symbol in seen:
            errors.append(f"{wid}: duplicate wiring symbol {symbol}")
        seen.add(symbol)

        for_id = entry.get("for")
        known = {e.get("id") for e in declared.values()}
        if for_id not in known:
            errors.append(
                f"{wid}: 'for' names {for_id!r}, which is not a declared "
                f"authority-state id"
            )

        module_name, _, name = symbol.partition("::")
        module = ROOT / module_name
        if not module.exists():
            errors.append(f"{wid}: {module_name} does not exist")
            continue

        source = _symbol_source(module, name)
        if source is None:
            errors.append(
                f"{wid}: {symbol} was not found. Correct the symbol if the "
                f"wiring moved; do not delete the entry while the store it "
                f"selects still exists."
            )
            continue

        switches = entry.get("switches") or []
        if not switches:
            errors.append(f"{wid}: no switches declared for {symbol}")
        for switch in switches:
            if switch not in source:
                errors.append(
                    f"{wid} ({symbol}): does not read {switch}, which the "
                    f"durability guard in servers/api.py admits. A "
                    f"deployment configured on {switch} alone passes the "
                    f"guard and then gets the in-process store, which is "
                    f"the defect this register exists to stop."
                )
    return errors


def check() -> list[str]:
    errors: list[str] = []
    data = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    entries = data.get("state") or []

    declared: dict[str, dict] = {}
    for entry in entries:
        eid = entry.get("id", "?")
        symbol = entry.get("symbol")
        if not symbol:
            errors.append(f"{eid}: missing symbol")
            continue
        if symbol in declared:
            errors.append(f"{eid}: duplicate symbol {symbol}")
        declared[symbol] = entry

        module = symbol.split("::")[0]
        if not (ROOT / module).exists():
            errors.append(f"{eid}: {module} does not exist")

        on_loss = entry.get("on_loss")
        if on_loss not in _ON_LOSS:
            errors.append(
                f"{eid}: on_loss must be one of {sorted(_ON_LOSS)}, got {on_loss!r}"
            )
            continue

        adapter = entry.get("durable_adapter")
        if on_loss == "reauthorizes":
            # The rule that would have caught all three occurrences.
            if not adapter or adapter == "none":
                errors.append(
                    f"{eid} ({symbol}): on_loss is 'reauthorizes' but no "
                    f"durable adapter is declared. Losing this state lets "
                    f"something execute that was refused before, which is "
                    f"fail-open. Declare the adapter, or change on_loss if "
                    f"the classification is wrong."
                )
        elif not adapter or adapter == "none":
            # Only an OPEN gap needs a tracking item. A loses_evidence store
            # that already has a durable adapter has nothing left to track,
            # and demanding an item for it would train the reader to treat
            # tracking ids as decoration.
            if not entry.get("tracking"):
                errors.append(
                    f"{eid} ({symbol}): on_loss is 'loses_evidence' with no "
                    f"durable adapter and no tracking item. An accepted gap "
                    f"must name the item that tracks it, so it is a stated "
                    f"decision and not an omission."
                )

        # A declared adapter must name a module that exists, so the register
        # cannot point at something that was moved or removed.
        if adapter and adapter != "none":
            for token in str(adapter).replace(";", " ").split():
                cand = token.split("::")[0].strip(",")
                if cand.endswith(".py") and not (ROOT / cand).exists():
                    errors.append(f"{eid}: declared adapter path {cand} does not exist")

        wired = entry.get("wired_at")
        if wired:
            cand = wired.split("::")[0]
            if not (ROOT / cand).exists():
                errors.append(f"{eid}: wired_at path {cand} does not exist")

    errors.extend(_check_wiring(data.get("wiring") or [], declared))

    discovered = discover()
    for symbol in sorted(discovered - set(declared)):
        errors.append(
            f"UNDECLARED: {symbol} holds lock-guarded mutable state and is not "
            f"in {_display(REGISTER)}. Add it and state "
            f"what losing it does. This is the check that the consumed-jti "
            f"ledger, the lease nonce ledger and principal revocation each "
            f"needed and did not have."
        )
    for symbol in sorted(set(declared) - discovered):
        errors.append(
            f"STALE: {symbol} is declared but no longer holds lock-guarded "
            f"mutable state. Remove it, or correct the symbol if it moved."
        )
    return errors


def main() -> int:
    errors = check()
    data = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    entries = data.get("state") or []
    if errors:
        print("[FAIL] authority-state durability:")
        for e in errors:
            print(f"  - {e}")
        return 1
    wiring = data.get("wiring") or []
    reauth = sum(1 for e in entries if e.get("on_loss") == "reauthorizes")
    evidence = len(entries) - reauth
    open_gaps = [
        e for e in entries
        if e.get("on_loss") == "loses_evidence"
        and (not e.get("durable_adapter") or e.get("durable_adapter") == "none")
    ]
    print(
        f"[PASS] {len(entries)} authority-state stores declared: "
        f"{reauth} fail open on loss and every one has a durable adapter; "
        f"{evidence} lose evidence only."
    )
    print(
        f"       {len(wiring)} wiring points reach every backend the "
        f"durability guard admits."
    )
    if open_gaps:
        # Named, not counted. A gap that only appears as a number in a PASS
        # line is a gap nobody reads.
        print(
            "       open durability gaps, each with a tracking item: "
            + ", ".join(f"{e['id']} ({e['tracking']})" for e in open_gaps)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
