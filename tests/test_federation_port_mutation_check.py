# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The mutation check for the federation-port components: fault generation, stable ids and
the equivalents lists. Running the faults needs a federation-port checkout and Node, which
reproduce.sh does; these tests cover what can be checked from the repository alone."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FP = ROOT / "integrations" / "federation-port"
spec = importlib.util.spec_from_file_location("federation_port_mutation_check", FP / "mutation_check.py")
mc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mc  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(mc)  # type: ignore[union-attr]

SNIPPET = """\
// comment with === and || that must not be mutated
import { x } from 'y'
const DOMAIN = 'A/v1'
export const CLAIM = 'remora.claim'
function f(a, b) {
  if (a === null || typeof a !== 'object') return JSON.stringify(a)
  if (b.length !== 64 || !ok(b)) integrity = 'signature_invalid'
  const chosen = items[0]
  return now <= deadline ? { status: 'established' } : { status: 'not_established', reason: 'expired' }
}
"""


def test_generation_skips_comments_imports_and_constants() -> None:
    mutants = mc.generate(SNIPPET)
    lines = {m.line for m in mutants}
    assert 1 not in lines and 2 not in lines and 3 not in lines and 4 not in lines
    assert lines <= {6, 7, 8, 9}


def test_every_mutant_is_a_single_line_edit_with_a_stable_id() -> None:
    mutants = mc.generate(SNIPPET)
    base = SNIPPET.split("\n")
    assert len({m.id for m in mutants}) == len(mutants)
    assert len({m.source for m in mutants}) == len(mutants)
    for m in mutants:
        changed = [i for i, (a, b) in enumerate(zip(base, m.source.split("\n"))) if a != b]
        assert changed == [m.line - 1], m.id
        op, line, n, digest = m.id.split(":")
        assert op == m.operator and line == f"L{m.line}"
        assert digest == hashlib.sha256(base[m.line - 1].encode()).hexdigest()[:8]
    # the same source gives the same ids; a changed line changes its ids only
    assert [m.id for m in mc.generate(SNIPPET)] == [m.id for m in mutants]
    edited = SNIPPET.replace("items[0]", "items[0] /* x */")
    before = {m.id for m in mutants if m.line != 8}
    after = {m.id for m in mc.generate(edited) if m.line != 8}
    assert before == after
    assert {m.id for m in mc.generate(edited) if m.line == 8}.isdisjoint({m.id for m in mutants if m.line == 8})


def test_the_operators_reach_the_shapes_the_adapters_use() -> None:
    ops = {m.operator for m in mc.generate(SNIPPET)}
    for expected in ("eq_to_neq", "neq_to_eq", "or_to_and", "drop_not", "guard_false", "guard_true",
                     "index_last", "int_shift", "le_to_lt", "established_to_not", "not_to_established"):
        assert expected in ops, expected
    sources = [m.source for m in mc.generate(SNIPPET)]
    assert any("items[items.length - 1]" in s for s in sources)
    assert any("if (false) return JSON.stringify(a)" in s for s in sources)


def test_string_literals_are_left_alone_except_status_words() -> None:
    line = "const x = 'a === b' || y !== z"
    mutants = mc.generate(line)
    for m in mutants:
        assert "'a === b'" in m.source, m.id  # the literal is untouched
    assert any("||" not in m.source for m in mutants)  # the operator outside the literal is


@pytest.mark.parametrize("component", sorted(mc.COMPONENTS))
def test_listed_equivalents_name_faults_that_exist_today(component: str) -> None:
    spec = mc.COMPONENTS[component]
    src = (spec["source"] / "adapter.ts").read_text(encoding="utf-8")
    ids = {m.id for m in mc.generate(src)}
    path = spec["source"] / "mutation-equivalents.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["component"] == component
    for entry in doc["equivalent"]:
        assert entry["id"] in ids, f"{entry['id']} no longer exists: its line changed, review the justification"
        assert len(entry["justification"]) > 40, entry["id"]
    assert len({e["id"] for e in doc["equivalent"]}) == len(doc["equivalent"])


@pytest.mark.parametrize("component", sorted(mc.COMPONENTS))
def test_positive_control_anchor_exists(component: str) -> None:
    spec = mc.COMPONENTS[component]
    src = (spec["source"] / "adapter.ts").read_text(encoding="utf-8")
    anchor, replacement = spec["positive_control"]
    assert src.count(anchor) == 1
    assert replacement != anchor


def test_artifact_digest_matches_the_transport_implementation(tmp_path: Path) -> None:
    from remora.federation.transports.federation_port_v0 import artifact_digest

    (tmp_path / "b.txt").write_bytes(b"bb")
    (tmp_path / "a.txt").write_bytes(b"a\n")
    files = ["b.txt", "a.txt"]
    assert mc.artifact_digest(tmp_path, files) == artifact_digest(tmp_path, files)
