#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""AST-based evaluator leakage detector.

Fails CI if runtime/policy packages reference evaluation-only fields.

Implements intern_forbedring.txt §2 requirement:
  'Add an AST-based leakage detector: scripts/check_no_evaluation_leakage.py'

Scans runtime packages (remora/policy/, remora/toolcall/, remora/runtime/)
for references to evaluation-only fields. These fields must ONLY appear in:
  - evaluation scripts (experiments/, tests/)
  - scoring code (remora/toolcall/scoring.py, simulators.py)
  - benchmark loaders (remora/toolcall/benchmark*.py)
  - this script itself
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Fields that are evaluation-only: must not appear in runtime/policy code.
# These fields are in ToolCallTask but should never be read by the gate.
FORBIDDEN_RUNTIME_FIELDS = {
    "is_unsafe_if_executed",
    "ground_truth_action",
    "expected_failure_mode",
    "expected_decision",
    "expected_action",
    "benchmark_label",
    "gold_label",
    "evaluator_truth",
    "harmful",
    "reward",
    "utility_label",
    "hidden_adversarial_category",
}

# Files where these fields ARE allowed (evaluators, scorers, test fixtures).
ALLOWLIST_PATTERNS = [
    "experiments/",
    "tests/",
    "remora/toolcall/scoring.py",
    "remora/toolcall/simulators.py",
    "remora/toolcall/benchmark",
    "remora/toolcall/schema.py",
    "remora/toolcall/schema_v3.py",
    "remora/aromer/evals/",
    "remora/toolcall/live_execution.py",
    "remora/toolcall/evaluation/",   # evaluation sub-package allowed to have labels
    "scripts/check_no_evaluation_leakage.py",
    "results/",
    "artifacts/",
]

# Runtime packages that must NOT reference evaluation fields.
RUNTIME_SCAN_DIRS = [
    REPO_ROOT / "remora" / "policy",
    REPO_ROOT / "remora" / "toolcall",
    REPO_ROOT / "remora" / "governance",
    REPO_ROOT / "remora" / "governance_intelligence",
    REPO_ROOT / "remora" / "shadow",
    REPO_ROOT / "remora" / "selective",
    REPO_ROOT / "remora" / "causal",
]

# Runtime toolcall files to exclude (evaluation-layer, not runtime-gate)
RUNTIME_EXCLUDED_FILES = {
    "benchmark.py", "benchmark_v2.py", "benchmark_v3.py",
    "scoring.py", "scoring_v3.py", "simulators.py", "live_execution.py",
    "baselines.py", "baselines_v3.py", "splits_v2.py",
}

# Import patterns forbidden in runtime packages (architectural boundary REM-016)
FORBIDDEN_EVAL_IMPORT_PATTERNS = {
    "remora.toolcall.evaluation",
    "from remora.toolcall import evaluation",
}

# Directories that constitute the evaluation layer (allowed to have label fields)
EVALUATION_SUBDIRS = {"evaluation"}  # remora/toolcall/evaluation/


class EvalImportVisitor(ast.NodeVisitor):
    """Check for forbidden imports of remora.toolcall.evaluation from runtime."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[tuple[int, str]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if "remora.toolcall.evaluation" in alias.name:
                self.violations.append((node.lineno, f"import {alias.name}"))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if "remora.toolcall.evaluation" in module:
            self.violations.append((node.lineno, f"from {module} import ..."))
        self.generic_visit(node)


class LeakageVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[tuple[int, str, str]] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_RUNTIME_FIELDS:
            self.violations.append((node.lineno, node.attr, "attribute_access"))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        val = getattr(node, "value", getattr(node, "s", None))
        if isinstance(val, str) and val in FORBIDDEN_RUNTIME_FIELDS:
            self.violations.append((node.lineno, val, "string_constant"))
        self.generic_visit(node)


def is_allowlisted(filepath: Path) -> bool:
    rel = str(filepath.relative_to(REPO_ROOT)).replace("\\", "/")
    return any(pattern in rel for pattern in ALLOWLIST_PATTERNS)


def is_evaluation_subdir(filepath: Path) -> bool:
    """True if file lives under remora/toolcall/evaluation/ (allowed to have labels)."""
    parts = filepath.parts
    return "evaluation" in parts and "toolcall" in parts


def scan_file_for_eval_imports(filepath: Path) -> list[tuple[Path, int, str, str]]:
    """Scan for forbidden imports of remora.toolcall.evaluation in runtime files."""
    # evaluation/ itself and allowlisted paths are permitted
    if is_allowlisted(filepath) or is_evaluation_subdir(filepath):
        return []
    if filepath.name in RUNTIME_EXCLUDED_FILES:
        return []
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []
    visitor = EvalImportVisitor(filepath)
    visitor.visit(tree)
    return [(filepath, line, pattern, "forbidden_import") for line, pattern in visitor.violations]


def scan_file(filepath: Path) -> list[tuple[Path, int, str, str]]:
    if is_allowlisted(filepath):
        return []
    if filepath.name in RUNTIME_EXCLUDED_FILES:
        return []

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    visitor = LeakageVisitor(filepath)
    visitor.visit(tree)
    return [(filepath, line, field, kind) for line, field, kind in visitor.violations]


def main() -> int:
    violations: list[tuple[Path, int, str, str]] = []
    scanned = 0

    for scan_dir in RUNTIME_SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for py_file in scan_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            found = scan_file(py_file)
            found += scan_file_for_eval_imports(py_file)
            violations.extend(found)
            scanned += 1

    if violations:
        print(f"\n[LEAKAGE DETECTOR] FAIL — {len(violations)} evaluator field reference(s) in runtime code\n")
        for filepath, line, field, kind in violations:
            rel = str(filepath.relative_to(REPO_ROOT)).replace("\\", "/")
            print(f"  {rel}:{line}: '{field}' ({kind})")
        print(
            "\nRuntime packages must not reference evaluation-only fields."
            "\nSee intern_forbedring.txt §2 and NEGATIVE_RESULTS.md §14 (M1)."
            "\nTo fix: move field access to evaluation/scorer layer only."
            "\nTo allow a specific file: add its path to ALLOWLIST_PATTERNS."
        )
        return 1

    print(f"[LEAKAGE DETECTOR] OK — scanned {scanned} runtime files, 0 evaluation field leaks found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
