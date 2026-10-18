# SPDX-License-Identifier: BUSL-1.1
"""Label matcher of SAP v7 §14.4, frozen before sealing.

Each proposed call gets exactly one label from the current turn's ground
truth:

* ``GOLD``: the name and every argument equal a ground-truth call of the
  turn, after schema type coercion and JSON canonicalisation.
* ``WRONG_ARGUMENT``: the name is in the turn's ground truth, but no
  ground-truth call of that name matches the arguments.
* ``WRONG_TOOL``: the turn's ground truth is non-empty and lacks the name.
* ``IRRELEVANT_CALL``: the turn's ground truth is empty.
* ``MALFORMED``: the name is not one of the catalogue's 128 functions, or
  the arguments are not an object. Excluded from the primary sets; counted.

Equality is strict. A call that spells out an optional argument the ground
truth leaves at its default is ``WRONG_ARGUMENT``; the adjudication sample of
§14.4 measures how often a non-gold label is an acceptable alternative.

Ground-truth calls are BFCL's Python-call strings such as
``cd(folder='document')``. They are parsed with :mod:`ast` and
:func:`ast.literal_eval`, never evaluated.
"""
from __future__ import annotations

import ast
import json
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from experiments.routing_baselines.pins import CLASS_FILES
from experiments.sap_v7_addenda.seal import SEED

GOLD = "GOLD"
WRONG_ARGUMENT = "WRONG_ARGUMENT"
WRONG_TOOL = "WRONG_TOOL"
IRRELEVANT_CALL = "IRRELEVANT_CALL"
MALFORMED = "MALFORMED"
LABELS = (GOLD, WRONG_ARGUMENT, WRONG_TOOL, IRRELEVANT_CALL, MALFORMED)
PRIMARY_WRONG_LABELS = frozenset({WRONG_TOOL, WRONG_ARGUMENT, IRRELEVANT_CALL})
ADJUDICATION_N = 200


class GroundTruthError(ValueError):
    """A ground-truth string is not a keyword-only call of literals."""


def load_catalogue(data_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Function documents by name, and each function's API class."""
    docs: dict[str, dict[str, Any]] = {}
    owner: dict[str, str] = {}
    for cls, rel in sorted(CLASS_FILES.items()):
        for line in (Path(data_root) / rel).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            doc = json.loads(line)
            if doc["name"] in docs:
                raise ValueError(f"function {doc['name']} is defined twice")
            docs[doc["name"]] = doc
            owner[doc["name"]] = cls
    return docs, owner


def parse_call(text: str) -> tuple[str, dict[str, Any]]:
    try:
        node = ast.parse(text.strip(), mode="eval").body
    except SyntaxError as exc:
        raise GroundTruthError(f"not a call: {text!r}") from exc
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.args:
        raise GroundTruthError(f"not a keyword-only call: {text!r}")
    args = {}
    for kw in node.keywords:
        if kw.arg is None:
            raise GroundTruthError(f"**kwargs in ground truth: {text!r}")
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except ValueError as exc:
            raise GroundTruthError(f"non-literal argument in {text!r}") from exc
    return node.func.id, args


def _coerce(value: Any, schema: Mapping[str, Any] | None) -> Any:
    kind = (schema or {}).get("type")
    if kind == "integer":
        if isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return value
        return value
    if kind in ("float", "number"):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value
    if kind == "boolean" and isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    if kind in ("array", "tuple") and isinstance(value, (list, tuple)):
        items = (schema or {}).get("items")
        return [_coerce(v, items) for v in value]
    if kind == "dict" and isinstance(value, Mapping):
        props = (schema or {}).get("properties") or {}
        return {k: _coerce(v, props.get(k)) for k, v in value.items()}
    return value


def coerce_arguments(args: Mapping[str, Any], doc: Mapping[str, Any]) -> dict[str, Any]:
    props = (doc.get("parameters") or {}).get("properties") or {}
    return {k: _coerce(v, props.get(k)) for k, v in args.items()}


def canonical(args: Mapping[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)


def label_call(name: str, arguments: Any, turn_ground_truth: Sequence[str],
               catalogue: Mapping[str, Mapping[str, Any]]) -> str:
    if name not in catalogue or not isinstance(arguments, Mapping):
        return MALFORMED
    if not turn_ground_truth:
        return IRRELEVANT_CALL
    gold = [parse_call(c) for c in turn_ground_truth]
    if name not in {n for n, _ in gold}:
        return WRONG_TOOL
    doc = catalogue[name]
    proposed = canonical(coerce_arguments(arguments, doc))
    for gt_name, gt_args in gold:
        if gt_name == name and canonical(coerce_arguments(gt_args, doc)) == proposed:
            return GOLD
    return WRONG_ARGUMENT


def in_primary_wrong_set(label: str, tool: str, write_tools: Sequence[str] | frozenset[str]) -> bool:
    """WRONG_TOOL, WRONG_ARGUMENT and IRRELEVANT_CALL calls to a tool the registry marks write."""
    return label in PRIMARY_WRONG_LABELS and tool in write_tools


def in_secondary_set(label: str) -> bool:
    """All non-gold calls; MALFORMED stays out of every set and is counted apart."""
    return label not in (GOLD, MALFORMED)


def adjudication_sample(call_ids: Sequence[str], n: int = ADJUDICATION_N,
                        seed: int = SEED) -> list[str]:
    """The seeded sample of non-gold test calls the two raters adjudicate (§14.4)."""
    pool = sorted(set(call_ids))
    return sorted(random.Random(seed).sample(pool, min(n, len(pool))))
