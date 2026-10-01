# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CORE modules do not import EXPERIMENTAL ones (quality program Q5.1).

The Module Stability Index in ARCHITECTURE.md rates every module. A CORE
module that imports an EXPERIMENTAL one inherits its instability, and a
"core" install cannot leave the research code out. The imports that existed
when this contract landed are listed in KNOWN with the reason; the list only
shrinks. A new CORE -> EXPERIMENTAL import fails, and so does a KNOWN entry
that no longer occurs.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNSTABLE = {"EXPERIMENTAL", "RESEARCH_ONLY", "HISTORICAL"}

#: CORE module -> unstable module, as of 2026-09-28. Each is layering debt.
KNOWN: dict[str, str] = {
    "remora/cli -> remora/engine": "the CLI exposes the research consensus engine",
    "remora/cli -> remora/integrations": "the CLI wires optional integrations",
    "remora/cli -> remora/oracles": "the CLI builds oracle swarms for research commands",
    "remora/cli -> remora/shadow": "the CLI runs shadow replay",
    "remora/cli -> remora/toolcall": "the CLI runs tool-call benchmarks",
    "remora/governance/envelope -> remora/causal": "lazy import of the optional causal explanation",
    "remora/policy/__init__ -> remora/governance_intelligence": "lazy import of optional enrichment",
    "remora/policy/thermodynamic_braking -> remora/lyapunov": "braking reads the Lyapunov state type",
    "remora/reporting -> remora/assurance": "lazy import of the assurance trace",
    "remora/reporting -> remora/evidence": "the report routes critical items to evidence",
    "remora/reporting -> remora/graph": "lazy import of claim-graph metrics",
    "remora/selective/guardrail -> remora/calibration": "the guardrail applies the trust calibrator",
    "remora/selective/pvd -> remora/semantic_entropy": "PVD scores with semantic entropy",
    "remora/state -> remora/lyapunov": "the engine state carries a Lyapunov controller",
}


def _ratings() -> dict[str, str]:
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    section = text[text.index("## 9. Module Stability Index"):]
    end = section.find("\n## ", 5)
    section = section[:end] if end != -1 else section
    out: dict[str, str] = {}
    for line in section.splitlines():
        if line.startswith("| `"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            for path in re.findall(r"`([^`]+)`", cells[0]):
                out[path.rstrip("/").removesuffix(".py")] = cells[1].strip("* ")
    return out


def _rating_of(module: str, ratings: dict[str, str]) -> tuple[str, str] | None:
    hits = [p for p in ratings if module == p or module.startswith(p + "/")]
    return (max(hits, key=len), ratings[max(hits, key=len)]) if hits else None


def _violations() -> set[str]:
    ratings = _ratings()
    found: set[str] = set()
    for path in (ROOT / "remora").rglob("*.py"):
        mod = path.relative_to(ROOT).with_suffix("").as_posix()
        own = _rating_of(mod, ratings)
        if not own or own[1] != "CORE":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else \
                [a.name for a in node.names] if isinstance(node, ast.Import) else []
            for name in names:
                if name.startswith("remora"):
                    target = _rating_of(name.replace(".", "/"), ratings)
                    if target and target[1] in UNSTABLE:
                        found.add(f"{mod} -> {target[0]}")
    return found


def test_no_new_core_to_experimental_import() -> None:
    new = sorted(_violations() - set(KNOWN))
    assert new == [], f"CORE modules importing unstable ones: {new}"


def test_known_debt_only_shrinks() -> None:
    stale = sorted(set(KNOWN) - _violations())
    assert stale == [], f"remove these KNOWN entries, the import is gone: {stale}"
