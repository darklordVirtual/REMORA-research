#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Verify that structural claims in README.md are backed by real code and tests.

This checker is deliberately narrower than check_claim_consistency.py (which
validates numeric percentages against benchmark artifacts).  Its job is to
confirm that every architectural feature mentioned in the README as "implemented"
has a corresponding importable module and at least one test file that references
it by name.

The invariant: README architectural claims → importable module → test exists.
If README says "six-stage cascade", the checker verifies CascadeStage has 6
members.  If README says "PlattScaler", it verifies the import resolves.  Etc.

Run as part of `make audit` (CI-safe - exits 0 on success, 1 on failure).
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
TESTS_DIR = ROOT / "tests"


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require_import(module: str, attr: str | None = None) -> None:
    """Assert that `module` (and optionally `module.attr`) is importable."""
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        fail(f"Cannot import '{module}': {exc}")
        return
    if attr is not None and not hasattr(mod, attr):
        fail(f"'{module}' is importable but has no attribute '{attr}'")
    label = f"{module}.{attr}" if attr else module
    ok(f"Module importable: {label}")


def require_test_references(symbol: str, test_glob: str = "test_*.py") -> None:
    """Assert that at least one test file under tests/ references `symbol`."""
    hits = [
        f for f in TESTS_DIR.glob(test_glob)
        if symbol in read(f)
    ]
    if not hits:
        fail(f"No test file references '{symbol}' - README claims it but tests don't cover it")
    ok(f"Test coverage found for '{symbol}': {hits[0].name}")


def main() -> None:
    readme = read(README)

    # -- 1. Six-stage cascade --------------------------------------------------
    if "six-stage" in readme.lower() or "6" in readme:
        from remora.cascade.result import CascadeStage
        n_stages = len(list(CascadeStage))
        if n_stages < 6:
            fail(
                f"README claims six-stage cascade but CascadeStage only defines "
                f"{n_stages} stages: {[s.name for s in CascadeStage]}"
            )
        ok(f"CascadeStage has {n_stages} stages - six-stage claim is backed")

    # -- 2. PlattScaler --------------------------------------------------------
    if "plattscaler" in readme.lower() or "platt" in readme.lower():
        require_import("remora.calibration.platt_scaler", "PlattScaler")
        require_test_references("PlattScaler")

    # -- 3. OracleDiversityTracker ---------------------------------------------
    if "diversitytracker" in readme.lower() or "oracle diversity" in readme.lower():
        require_import("remora.oracles.diversity", "OracleDiversityTracker")
        require_test_references("OracleDiversityTracker")

    # -- 4. DomainCoverageOptimizer --------------------------------------------
    if "domaincoverageoptimizer" in readme.lower() or "domain coverage" in readme.lower():
        require_import("remora.calibration.domain_optimizer", "DomainCoverageOptimizer")
        require_test_references("DomainCoverageOptimizer")

    # -- 5. Uncertainty decomposition ------------------------------------------
    if "uncertainty decomp" in readme.lower() or "epistemic" in readme.lower():
        require_import("remora.uncertainty.decompose", "decompose")
        require_test_references("decompose")

    # -- 6. MixtureOfAgentsSynth -----------------------------------------------
    if "mixture" in readme.lower() or "moa" in readme.lower():
        require_import("remora.cascade.stages", "MixtureOfAgentsSynth")
        require_test_references("MixtureOfAgentsSynth")

    # -- 7. Thermodynamic trust ------------------------------------------------
    if "thermodynamic" in readme.lower():
        require_import("remora.thermodynamics")
        require_import("remora.statphys")

    # -- 8. Agent hook / tool-call safety -------------------------------------
    if "agent" in readme.lower() and ("hook" in readme.lower() or "tool" in readme.lower()):
        require_import("remora.agent_hook")
        require_test_references("agent_hook")

    # -- 9. No unqualified "production safe" claims ----------------------------
    forbidden = [
        (r"\bproduction[- ]safe\b", "production-safe"),
        (r"\bguarantees safety\b", "guarantees safety"),
        (r"\bexternally validated\b", "externally validated"),
        (r"\bpeer[- ]reviewed theorem\b", "peer-reviewed theorem"),
    ]
    for pattern, label in forbidden:
        if re.search(pattern, readme, flags=re.IGNORECASE):
            fail(f"README contains forbidden overclaim: '{label}'")
    ok("No forbidden overclaim patterns in README")

    print("\n[PASS] All README structural claims are backed by code and tests.")


if __name__ == "__main__":
    main()
