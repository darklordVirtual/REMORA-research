#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Product Truth Contract gate.

Validates docs/product/product_truth_contract.yaml and enforces that public
documentation and frontend landing copy do not present a non-core capability
(optional / experimental / legacy / demo) as a mandatory component of the
canonical product execution path.

Checks (all HARD):
  1. Contract integrity — schema_version, product_definition, every capability
     carries exactly one declared class from the `classes` registry, and every
     required capability name is classified.
  2. Evidence existence — every capability's `module` path resolves on disk.
  3. Mandatory-path scan — in each `scan_files` entry, a line that mentions a
     non-core capability alias AND asserts mandatory-path placement (a multi-arrow
     flow line, or mandatory-language markers) without a scoping qualifier
     ("optional", "experimental", "research", "not ", ...) is a violation.
     Lines matching an `exemptions` entry are skipped.

Stdlib + PyYAML only, mirroring check_document_governance.py conventions.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "product" / "product_truth_contract.yaml"

REQUIRED_CAPABILITIES = {
    "RemoraDecisionEngine",
    "PolicyObservation",
    "hard guards",
    "review queue",
    "PolicyDecisionToken",
    "EnforcementGate",
    "ExecutionLease",
    "GovernedToolDispatcher",
    "ExecutionOutbox",
    "effect verification",
    "tenant audit chain",
    "ToolSpec",
    "OPA",
    "semantic bundle",
    "MCP",
    "multi-oracle consensus",
    "thermodynamics",
    "AROMER",
    "RAG oracle",
    "law search",
    "frontend simulator",
    "Cloudflare agent-control",
}

# A line asserts mandatory-path placement when it is a flow line (two or more
# arrows) or carries explicit mandatory language.
ARROW_RE = re.compile(r"(→|->).*(→|->)")
MANDATORY_MARKERS = (
    "required for",
    "mandatory",
    "prerequisite",
    "primary execution path",
    "canonical execution path",
    "before any action runs",
    "every action passes",
)
# Qualifiers that scope a mention as non-mandatory / negated.
QUALIFIERS = (
    "optional",
    "experimental",
    "research",
    "advisory",
    "not ",
    "never",
    "cannot",
    "legacy",
    "demo",
    "without",
)


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))


def contract_errors(contract: dict) -> list[str]:
    errors: list[str] = []
    if str(contract.get("schema_version")) != "1":
        errors.append("contract: schema_version must be '1'")
    if not str(contract.get("product_definition", "")).strip():
        errors.append("contract: product_definition missing")
    classes = set(contract.get("classes", {}))
    if not {"core", "optional", "experimental", "legacy", "demo"} <= classes:
        errors.append("contract: classes registry must declare all five classes")
    caps = contract.get("capabilities", [])
    names = set()
    for cap in caps:
        name = cap.get("name", "<unnamed>")
        if name in names:
            errors.append(f"contract: duplicate capability {name!r}")
        names.add(name)
        if cap.get("class") not in classes:
            errors.append(f"contract: {name!r} has invalid class {cap.get('class')!r}")
        module = cap.get("module")
        if not module:
            errors.append(f"contract: {name!r} missing module evidence path")
        elif not (ROOT / module).exists():
            errors.append(f"contract: {name!r} module {module!r} does not exist")
    missing = REQUIRED_CAPABILITIES - names
    if missing:
        errors.append(f"contract: unclassified required capabilities: {sorted(missing)}")
    return errors


def line_violates(line: str, aliases: list[str]) -> bool:
    """A single documentation line places a non-core capability on the mandatory path."""
    lowered = line.lower()
    if not any(a.lower() in lowered for a in aliases):
        return False
    if any(q in lowered for q in QUALIFIERS):
        return False
    if ARROW_RE.search(line):
        return True
    return any(m in lowered for m in MANDATORY_MARKERS)


def scan_errors(contract: dict) -> list[str]:
    errors: list[str] = []
    non_core = [
        c for c in contract.get("capabilities", []) if c.get("class") != "core"
    ]
    exemptions = contract.get("exemptions", []) or []
    for rel in contract.get("scan_files", []):
        path = ROOT / rel
        if not path.exists():
            errors.append(f"scan: file {rel!r} listed in scan_files does not exist")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(
                e.get("file") == rel and e.get("contains", "") in line
                for e in exemptions
            ):
                continue
            for cap in non_core:
                aliases = cap.get("aliases") or [cap["name"]]
                if line_violates(line, aliases):
                    errors.append(
                        f"scan: {rel}:{lineno}: {cap['class']} capability "
                        f"{cap['name']!r} presented as mandatory-path: {line.strip()[:120]}"
                    )
    return errors


def main() -> int:
    if not CONTRACT_PATH.exists():
        print(f"[FAIL] missing {CONTRACT_PATH.relative_to(ROOT)}")
        return 1
    contract = load_contract()
    errors = contract_errors(contract) + scan_errors(contract)
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        print(f"product-truth gate: {len(errors)} error(s)")
        return 1
    n = len(contract.get("capabilities", []))
    print(f"[OK]   product-truth contract: {n} capabilities classified, scan clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
