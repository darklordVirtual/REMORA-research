#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A second operator set over the evidence-sufficiency checker, scored in process by the v1.3 runner.

mutmut's operators are one sample of the fault space, and the v1.3 corpus was
finished with mutmut's survivor list in view. This script applies operators
mutmut does not have, so that the corpus is measured against faults it was not
tuned to (DeMillo, Lipton and Sayward, 1978; Jia and Harman, 2011):

- ``delete_statement``: a guard, a return or an assignment removed;
- ``swap_adjacent_guards``: two neighbouring guards exchanged (precedence);
- ``comparison_variant``: ``is True`` and its kin flipped, negated, made
  truthiness (``bool(x)``, ``not x``) or made equality (``== True``);
- ``reason_confusion``: a reason literal replaced by every other reason of the
  same assessor;
- ``status_polarity``: a terminal status replaced by each other status;
- ``field_confusion``: a premise name replaced by every other premise the same
  assessor reads;
- ``state_comparison``: the postcondition comparison replaced by raw equality,
  ``str``, ``repr``, unsorted ``json.dumps``, case-folded, stripped, anagram or
  constant comparisons;
- ``negate_condition``: an ``if`` test negated;
- ``type_vocabulary``: a type removed from or added to the accepted scalar types,
  and exact type checks relaxed to ``isinstance``.

Second-order mutants (Jia and Harman, 2009) are sampled from pairs of
non-overlapping first-order edits with a fixed seed, so a pair whose faults
mask each other is measured too. Every mutant is a text edit on the checker's
source, applied in memory and scored by ``build_record`` of the v1.3 runner.
The kill signature of a mutant is the set of check labels that failed, which
gives a redundancy reading per mutant: a mutant killed by one label only is
fragile, and that label is load-bearing.

The survivors are ratcheted against
``docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt`` exactly
as the mutmut sweep is. A survivor absent from the baseline fails the gate.

Usage::

    python scripts/mutation_evidence_sufficiency_ast.py                 # sweep, compare, exit 1 on new survivors
    python scripts/mutation_evidence_sufficiency_ast.py --update        # rewrite the baseline
    python scripts/mutation_evidence_sufficiency_ast.py --json out.json # full report
    python scripts/mutation_evidence_sufficiency_ast.py --list          # print the mutant catalogue only
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "conformance" / "evidence-sufficiency-v1" / "checker.py"
RUNNER = ROOT / "conformance" / "evidence-sufficiency-v1.3" / "run_evidence_sufficiency.py"
BASELINE = ROOT / "docs" / "assurance" / "mutation_baseline_evidence_sufficiency_ast_v1.txt"

ASSESSORS = ("admission_accounting", "tested_route_enforcement", "postcondition_observed")
TARGET_FUNCTIONS = ASSESSORS + ("validate_json", "canonical", "assess", "_result", "_unknown", "_scope")
STATUSES = ("ESTABLISHED", "VIOLATED", "NOT_ESTABLISHED")
SECOND_ORDER_SAMPLE = 200
SEED = 20260930


# ── Source spans ──────────────────────────────────────────────────────────────


class Source:
    """The checker's source with byte offsets for AST nodes."""

    def __init__(self, text: str):
        self.text = text
        self.data = text.encode("utf-8")
        self.line_starts = [0]
        for line in self.data.splitlines(keepends=True):
            self.line_starts.append(self.line_starts[-1] + len(line))
        self.tree = ast.parse(text)

    def span(self, node: ast.AST) -> tuple[int, int]:
        start = self.line_starts[node.lineno - 1] + node.col_offset
        end = self.line_starts[node.end_lineno - 1] + node.end_col_offset
        return start, end

    def segment(self, node: ast.AST) -> str:
        start, end = self.span(node)
        return self.data[start:end].decode("utf-8")

    def apply(self, edits: list[tuple[int, int, str]]) -> str:
        """Non-overlapping (start, end, replacement) edits, applied from the end."""
        data = self.data
        for start, end, replacement in sorted(edits, reverse=True):
            data = data[:start] + replacement.encode("utf-8") + data[end:]
        return data.decode("utf-8")


def functions(source: Source) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in source.tree.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    }


def statements(body: list[ast.stmt]):
    """Every statement in a body, recursively through if/else, with its containing body."""
    for index, stmt in enumerate(body):
        yield body, index, stmt
        if isinstance(stmt, ast.If):
            yield from statements(stmt.body)
            yield from statements(stmt.orelse)
        elif isinstance(stmt, ast.For):
            yield from statements(stmt.body)


# ── Operators: each yields (site, description, replacement) over a function ────


def op_delete_statement(source: Source, fn: ast.FunctionDef):
    for body, index, stmt in statements(fn.body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue  # a docstring
        start, end = source.span(stmt)
        yield (start, end), f"delete `{source.segment(stmt).splitlines()[0][:60]}`", "pass"


def op_swap_adjacent_guards(source: Source, fn: ast.FunctionDef):
    seen = set()
    for body, index, stmt in statements(fn.body):
        if index + 1 >= len(body):
            continue
        first, second = body[index], body[index + 1]
        if not (isinstance(first, ast.If) and isinstance(second, ast.If)):
            continue
        key = (id(body), index)
        if key in seen:
            continue
        seen.add(key)
        start, _ = source.span(first)
        _, end = source.span(second)
        indent = " " * first.col_offset
        swapped = source.segment(second) + "\n" + indent + source.segment(first)
        yield (start, end), f"swap `{source.segment(first).splitlines()[0][:40]}` with the next guard", swapped


def _bool_compare(node: ast.AST):
    return (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.Is, ast.IsNot))
        and isinstance(node.comparators[0], ast.Constant)
        and isinstance(node.comparators[0].value, bool)
    )


def op_comparison_variant(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if not _bool_compare(node):
            continue
        left = source.segment(node.left)
        is_not = isinstance(node.ops[0], ast.IsNot)
        const = node.comparators[0].value
        span = source.span(node)
        yield span, f"flip operator in `{source.segment(node)}`", f"{left} {'is' if is_not else 'is not'} {const}"
        yield span, f"flip constant in `{source.segment(node)}`", f"{left} {'is not' if is_not else 'is'} {not const}"
        truthy_wanted = (not is_not and const) or (is_not and not const)
        yield span, f"truthiness for `{source.segment(node)}`", f"bool({left})" if truthy_wanted else f"not {left}"
        yield span, f"equality for `{source.segment(node)}`", f"{left} {'!=' if is_not else '=='} {const}"


def _reason_sites(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "_unknown" and len(node.args) >= 2:
            arg = node.args[1]
        elif node.func.id == "_result" and len(node.args) >= 3:
            arg = node.args[2]
        else:
            continue
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield node, arg


def op_reason_confusion(source: Source, fn: ast.FunctionDef):
    sites = list(_reason_sites(source, fn))
    reasons = sorted({arg.value for _, arg in sites})
    for _, arg in sites:
        for other in reasons:
            if other != arg.value:
                yield source.span(arg), f"reason `{arg.value}` becomes `{other}`", json.dumps(other)


def op_status_polarity(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "EvidenceStatus":
            if node.attr in STATUSES:
                for other in STATUSES:
                    if other != node.attr:
                        yield source.span(node), f"status `{node.attr}` becomes `{other}`", f"EvidenceStatus.{other}"


def _field_sites(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                yield node.args[0]
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                yield node.left
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            yield node.slice


def op_field_confusion(source: Source, fn: ast.FunctionDef):
    sites = list(_field_sites(source, fn))
    fields = sorted({site.value for site in sites})
    for site in sites:
        for other in fields:
            if other != site.value:
                yield source.span(site), f"field `{site.value}` becomes `{other}`", json.dumps(other)


def op_state_comparison(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)):
            continue
        left, right = node.left, node.comparators[0]
        if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "canonical"):
            continue
        a, b = source.segment(left.args[0]), source.segment(right.args[0])
        span = source.span(node)
        variants = {
            "raw equality": f"{a} == {b}",
            "str equality": f"str({a}) == str({b})",
            "repr equality": f"repr({a}) == repr({b})",
            "unsorted json equality": f"json.dumps({a}) == json.dumps({b})",
            "case-folded": f"canonical({a}).casefold() == canonical({b}).casefold()",
            "stripped": f"canonical({a}).strip() == canonical({b}).strip()",
            "anagram": f"sorted(canonical({a})) == sorted(canonical({b}))",
            "inverted": f"canonical({a}) != canonical({b})",
            "always equal": f"canonical({a}) == canonical({a})",
            "length only": f"len(canonical({a})) == len(canonical({b}))",
        }
        for name, replacement in variants.items():
            yield span, f"state comparison: {name}", replacement


def op_negate_condition(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            yield source.span(node.test), f"negate `{source.segment(node.test)[:50]}`", f"not ({source.segment(node.test)})"


def op_type_vocabulary(source: Source, fn: ast.FunctionDef):
    for node in ast.walk(fn):
        if isinstance(node, ast.Tuple) and all(isinstance(e, ast.Name) for e in node.elts) and len(node.elts) >= 2:
            names = [e.id for e in node.elts]
            if set(names) <= {"str", "bool", "int", "float", "list", "dict"}:
                for dropped in names:
                    remaining = [n for n in names if n != dropped]
                    yield source.span(node), f"drop `{dropped}` from the scalar types", "(" + ", ".join(remaining) + ",)"
                yield source.span(node), "add `float` to the scalar types", "(" + ", ".join(names + ["float"]) + ")"
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Is)
            and isinstance(node.left, ast.Call)
            and isinstance(node.left.func, ast.Name)
            and node.left.func.id == "type"
            and isinstance(node.comparators[0], ast.Name)
        ):
            value = source.segment(node.left.args[0])
            yield source.span(node), f"isinstance for `{source.segment(node)}`", f"isinstance({value}, {node.comparators[0].id})"


OPERATORS = {
    "delete_statement": op_delete_statement,
    "swap_adjacent_guards": op_swap_adjacent_guards,
    "comparison_variant": op_comparison_variant,
    "reason_confusion": op_reason_confusion,
    "status_polarity": op_status_polarity,
    "field_confusion": op_field_confusion,
    "state_comparison": op_state_comparison,
    "negate_condition": op_negate_condition,
    "type_vocabulary": op_type_vocabulary,
}


def catalogue(source: Source) -> list[dict]:
    """Every first-order mutant, with a stable id."""
    mutants = []
    fns = functions(source)
    for name, fn in fns.items():
        for op_name, op in OPERATORS.items():
            for index, (span, description, replacement) in enumerate(op(source, fn)):
                original = source.data[span[0]:span[1]].decode("utf-8")
                if original.strip() == replacement.strip():
                    continue
                mutants.append({
                    "id": f"{op_name}:{name}:{index}",
                    "operator": op_name,
                    "function": name,
                    "span": list(span),
                    "description": description,
                    "replacement": replacement,
                    "order": 1,
                })
    return mutants


def second_order(mutants: list[dict], sample: int, seed: int) -> list[dict]:
    """A fixed-seed sample of non-overlapping pairs of first-order mutants."""
    rng = random.Random(seed)
    pairs = []
    attempts = 0
    while len(pairs) < sample and attempts < sample * 50:
        attempts += 1
        a, b = rng.sample(mutants, 2)
        (a0, a1), (b0, b1) = a["span"], b["span"]
        if a1 <= b0 or b1 <= a0:
            key = tuple(sorted((a["id"], b["id"])))
            if key not in {p["parts"] for p in pairs}:
                pairs.append({"parts": key})
    return [
        {
            "id": f"second:{p['parts'][0]}+{p['parts'][1]}",
            "operator": "second_order",
            "function": "+".join(sorted({m["function"] for m in mutants if m["id"] in p["parts"]})),
            "edits": [m for m in mutants if m["id"] in p["parts"]],
            "description": " and ".join(m["description"] for m in mutants if m["id"] in p["parts"]),
            "order": 2,
        }
        for p in pairs
    ]


def mutated_source(source: Source, mutant: dict) -> str:
    edits = mutant.get("edits") or [mutant]
    return source.apply([(e["span"][0], e["span"][1], e["replacement"]) for e in edits])


# ── Scoring ───────────────────────────────────────────────────────────────────

_RUNNER = None


def _runner():
    global _RUNNER
    if _RUNNER is None:
        spec = importlib.util.spec_from_file_location("evidence_sufficiency_v1_3_runner_for_ast", RUNNER)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _RUNNER = module
    return _RUNNER


def load_mutant(mutant_id: str, text: str):
    """The mutated checker as a module; the caller removes it from sys.modules."""
    name = "es_mutant_" + hashlib.sha256(mutant_id.encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(CHECKER)
    sys.modules[name] = module
    try:
        exec(compile(text, str(CHECKER), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return name, module


def score(job: tuple[str, str]) -> tuple[str, list[str], list[str]]:
    """(mutant id, failure labels, reference-model disagreements) for one mutated source."""
    mutant_id, text = job
    try:
        name, module = load_mutant(mutant_id, text)
        try:
            record = _runner().build_record(module)
        finally:
            sys.modules.pop(name, None)
        return mutant_id, list(record["failures"]), list(record["reference_model"]["disagreements"])
    except Exception as exc:  # noqa: BLE001 - an import-time crash is a kill with its own label
        return mutant_id, [f"crash:import:{type(exc).__name__}"], []


def label_of(failure: str) -> str:
    """Collapse a failure string to the check that produced it."""
    head = failure.split(":", 1)[0]
    if head in ("MR-1", "MR-2", "MR-3", "MR-4", "MR-5", "MR-6", "MR-7", "MR-8", "MR-9", "MR-10", "MR-11"):
        return head
    if head in ("rejection", "reference_model", "crash", "precedence", "isolation", "unreached_reason",
                "undeclared_guidance", "orphan_guidance", "unwitnessed_precedence", "unisolated_reason",
                "model_ladder_mismatch", "model_reason_mismatch", "unimplemented_relation", "undeclared_relation"):
        return head
    if "-" in head and head.split("-")[0][:1] in "ABEW" and head.split("-")[0][1:].isdigit():
        return "guidance:" + head.split("-")[0]  # e.g. A01-field:problem from the erasure loop
    return head  # a case id, a witness id, a wrong-shortcut name or a guidance label


def sweep(workers: int, sample: int, seed: int, only: str | None = None) -> dict:
    source = Source(CHECKER.read_text(encoding="utf-8"))
    first = catalogue(source)
    second = second_order(first, sample, seed)
    mutants = [m for m in first + second if not only or m["id"].startswith(only)]
    jobs = [(m["id"], mutated_source(source, m)) for m in mutants]
    # The unmutated checker must pass, or every kill below is meaningless.
    _, baseline_failures, _ = score(("original", source.text))
    if baseline_failures:
        raise SystemExit(f"the unmutated checker fails the runner: {baseline_failures[:5]}")
    results: dict[str, tuple[list[str], list[str]]] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for mutant_id, failures, points in pool.map(score, jobs, chunksize=4):
            results[mutant_id] = (failures, points)
    rows = []
    for m in mutants:
        failures, points = results[m["id"]]
        labels = sorted({label_of(f) for f in failures})
        rows.append({
            "id": m["id"], "operator": m["operator"], "function": m["function"], "order": m["order"],
            "description": m["description"], "status": "killed" if failures else "survived",
            "labels": labels, "label_count": len(labels), "failure_count": len(failures),
            "model_only": labels == ["reference_model"],
            "disagreements": points if labels == ["reference_model"] else [],
        })
    killed = [r for r in rows if r["status"] == "killed"]
    fragile = [r for r in killed if r["label_count"] == 1]
    load_bearing = Counter(r["labels"][0] for r in fragile)
    by_operator = {}
    for r in rows:
        entry = by_operator.setdefault(r["operator"], {"mutants": 0, "killed": 0})
        entry["mutants"] += 1
        entry["killed"] += r["status"] == "killed"
    return {
        "checker_sha256": hashlib.sha256(source.data.replace(b"\r\n", b"\n")).hexdigest(),
        "seed": seed,
        "mutants": len(rows),
        "first_order": sum(1 for m in mutants if m["order"] == 1),
        "second_order": sum(1 for m in mutants if m["order"] == 2),
        "killed": len(killed),
        "survived": sorted(r["id"] for r in rows if r["status"] == "survived"),
        "by_operator": by_operator,
        "redundancy": {
            "labels_per_killed_mutant": dict(sorted(Counter(r["label_count"] for r in killed).items())),
            "fragile": [r["id"] for r in fragile],
            "load_bearing_labels": dict(load_bearing.most_common()),
        },
        "rows": rows,
    }


def _parse_point(disagreement: str) -> tuple[str, dict]:
    """(claim, observations) from a reference-model disagreement string."""
    claim, rest = disagreement.split(":", 1)
    body = rest[: rest.rindex(":model=")]
    return claim, json.loads(body)


def derive_cases(report: dict, source: Source) -> list[dict]:
    """A greedy cover of the mutants only the reference model kills, as authored cases.

    Every candidate point is a lattice point where some model-only mutant and the
    model disagreed. Coverage is computed exactly by running each such mutant on
    each candidate, then the smallest greedy set of points that kills them all is
    returned, with the model's verdict as the expected result and the mutants the
    point separates as the rationale.
    """
    runner = _runner()
    model = runner.load_json(runner.HERE / "model.json")
    targets = [r for r in report["rows"] if r["model_only"]]
    if not targets:
        return []
    by_id = {m["id"]: m for m in catalogue(source)}
    by_id.update({m["id"]: m for m in second_order(catalogue(source), report["second_order"], report["seed"])})
    candidates: dict[str, tuple[str, dict]] = {}
    for row in targets:
        for point in row["disagreements"]:
            claim, obs = _parse_point(point)
            candidates.setdefault(f"{claim}:{json.dumps(obs, sort_keys=True)}", (claim, obs))
    coverage: dict[str, set[str]] = {key: set() for key in candidates}
    for row in targets:
        name, module = load_mutant(row["id"], mutated_source(source, by_id[row["id"]]))
        try:
            for key, (claim, obs) in candidates.items():
                expected = runner.interpret_model(model, claim, obs)
                try:
                    verdict = module.assess(claim, json.loads(json.dumps(obs)))
                    actual = (verdict.status.value, verdict.reason)
                except Exception as exc:  # noqa: BLE001
                    actual = ("raised", type(exc).__name__)
                if actual != expected:
                    coverage[key].add(row["id"])
        finally:
            sys.modules.pop(name, None)
    uncovered = {row["id"] for row in targets}
    chosen: list[dict] = []
    while uncovered:
        key = max(sorted(candidates), key=lambda k: len(coverage[k] & uncovered))
        gained = coverage[key] & uncovered
        if not gained:
            break
        claim, obs = candidates[key]
        status, reason = runner.interpret_model(model, claim, obs)
        chosen.append({
            "claim": claim, "observations": obs, "expected": {"status": status, "reason": reason},
            "separates": sorted(gained),
            "descriptions": sorted(by_id[m]["description"] for m in gained),
        })
        uncovered -= gained
    return chosen


def read_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--list", action="store_true", help="print the first-order catalogue and exit")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sample", type=int, default=SECOND_ORDER_SAMPLE, help="second-order pairs")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--only", help="score only mutants whose id starts with this prefix (no gate)")
    parser.add_argument("--derive-cases", type=Path, help="write a greedy cover of the model-only kills as candidate cases")
    args = parser.parse_args(argv)
    if args.list:
        source = Source(CHECKER.read_text(encoding="utf-8"))
        for m in catalogue(source):
            print(f"{m['id']}\t{m['description']}")
        return 0
    report = sweep(args.workers, args.sample, args.seed, args.only)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.derive_cases:
        cases = derive_cases(report, Source(CHECKER.read_text(encoding="utf-8")))
        args.derive_cases.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
        print(f"derived {len(cases)} candidate case(s) covering {sum(1 for r in report['rows'] if r['model_only'])} model-only kills")
    if args.only:
        for row in report["rows"]:
            print(f"{row['status']:8} {row['id']}  {row['labels'][:6]}")
        return 0
    ops = ", ".join(f"{k} {v['killed']}/{v['mutants']}" for k, v in report["by_operator"].items())
    print(f"mutants {report['mutants']} ({report['first_order']} first-order, {report['second_order']} second-order): "
          f"{report['killed']} killed, {len(report['survived'])} survived; {ops}")
    red = report["redundancy"]
    print(f"labels per killed mutant: {red['labels_per_killed_mutant']}; fragile (one label): {len(red['fragile'])}; "
          f"load-bearing labels: {red['load_bearing_labels']}")
    if args.update:
        header = [
            "# Surviving mutants of conformance/evidence-sufficiency-v1/checker.py under the second",
            "# operator set (scripts/mutation_evidence_sufficiency_ast.py), scored by the v1.3 runner.",
            f"# checker sha256 {report['checker_sha256']}; second-order seed {report['seed']}.",
            "# Every id below is classified in docs/assurance/mutation_testing_v1.md.",
        ]
        BASELINE.write_text("\n".join(header + report["survived"]) + "\n", encoding="utf-8", newline="\n")
        print(f"[OK] baseline updated: {len(report['survived'])} survivor(s) recorded")
        return 0
    baseline = read_baseline(BASELINE)
    new = sorted(set(report["survived"]) - baseline)
    dead = sorted(baseline - set(report["survived"]))
    for mid in dead:
        print(f"[HINT] baseline survivor now killed (remove it from the baseline): {mid}")
    if new:
        print(f"[FAIL] {len(new)} surviving mutant(s) absent from the baseline:", file=sys.stderr)
        for mid in new:
            print(f"  {mid}", file=sys.stderr)
        return 1
    print(f"[OK] no new survivors ({len(baseline)} in the baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
