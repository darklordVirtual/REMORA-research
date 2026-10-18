# SPDX-License-Identifier: BUSL-1.1
"""Development/test split of SAP v7 §14.3 and the gated entry loader.

The 200 base indices are ordered by ``sha256("20261018:<index>")`` and the
first 25 % form the development side. All four categories of one index go
to the same side. This holds only if entry ``i`` of each category shares
``involved_classes`` and ``initial_config`` with base entry ``i``; when any
does not, the split is drawn per entry id over all 800 entries instead, and
the task cluster becomes the entry.

:func:`structural_fields` is the one reader that touches every entry. It
keeps the id, ``involved_classes`` and ``initial_config`` that the check
needs and drops the rest of each line as it is parsed. :func:`load_entries`
returns question turns and ground truth for the development side freely and
for the test side only against a :class:`~experiments.sap_v7_addenda.seal.
LockedManifest`, which only the run gate issues.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from experiments.routing_baselines.pins import CATEGORIES, verify_data
from experiments.sap_v7_addenda.seal import SEED, LockedManifest, require_lock

DEV_SHARE = 0.25
N_BASE = 200


def entry_index(entry_id: str) -> int:
    return int(entry_id.rsplit("_", 1)[1])


def category_of(entry_id: str) -> str:
    return entry_id.rsplit("_", 1)[0]


def _order(keys: Iterable[str], seed: int) -> list[str]:
    return sorted(keys, key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest())


def seeded_dev(keys: Iterable[str], seed: int = SEED, dev_share: float = DEV_SHARE) -> set[str]:
    ordered = _order(set(keys), seed)
    return set(ordered[:round(dev_share * len(ordered))])


def _lines(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def structural_fields(data_root: Path) -> dict[str, tuple[tuple[str, ...], str]]:
    """Entry id to (involved classes, canonical initial config), for every entry."""
    out = {}
    for category in CATEGORIES:
        for row in _lines(Path(data_root) / f"BFCL_v4_{category}.json"):
            out[row["id"]] = (tuple(sorted(row["involved_classes"])),
                              json.dumps(row["initial_config"], sort_keys=True))
    return out


def aligned(structure: Mapping[str, tuple[tuple[str, ...], str]]) -> bool:
    base = {entry_index(i): v for i, v in structure.items() if category_of(i) == CATEGORIES[0]}
    for entry_id, value in structure.items():
        if base.get(entry_index(entry_id)) != value:
            return False
    return True


@dataclass(frozen=True)
class Split:
    unit: str  # "index" or "entry"
    dev: frozenset[str]
    test: frozenset[str]

    def cluster(self, entry_id: str) -> str:
        """Task cluster: the base index, or the entry when the split fell back."""
        return f"index:{entry_index(entry_id)}" if self.unit == "index" else entry_id


def draw_split(structure: Mapping[str, tuple[tuple[str, ...], str]], seed: int = SEED) -> Split:
    ids = set(structure)
    if aligned(structure):
        dev_idx = seeded_dev((str(i) for i in range(N_BASE)), seed)
        dev = {i for i in ids if str(entry_index(i)) in dev_idx}
        return Split("index", frozenset(dev), frozenset(ids - dev))
    dev = seeded_dev(ids, seed)
    return Split("entry", frozenset(dev), frozenset(ids - dev))


@dataclass(frozen=True)
class Entry:
    entry_id: str
    turns: Sequence[Sequence[Mapping[str, str]]]
    ground_truth: Sequence[Sequence[str]]
    involved_classes: tuple[str, ...]
    initial_config: Mapping[str, Any]
    excluded_functions: tuple[str, ...] = ()
    #: turn index to function names withheld until that turn (miss_func).
    missed_functions: Mapping[int, tuple[str, ...]] = field(default_factory=dict)


def load_entries(data_root: Path, split: Split, side: str,
                 lock: LockedManifest | None = None,
                 files: dict[str, str] | None = None) -> list[Entry]:
    """Entries of one side. The test side needs the run gate's lock."""
    if side == "test":
        require_lock(lock, "reading the Q7 test split")
        wanted = split.test
    elif side == "dev":
        wanted = split.dev
    else:
        raise ValueError(f"unknown side {side!r}")
    verify_data(data_root, files)
    out = []
    for category in CATEGORIES:
        answers = {}
        for row in _lines(Path(data_root) / "possible_answer" / f"BFCL_v4_{category}.json"):
            if row["id"] in wanted:
                answers[row["id"]] = row["ground_truth"]
        for row in _lines(Path(data_root) / f"BFCL_v4_{category}.json"):
            if row["id"] not in wanted:
                continue
            missed = {int(k): tuple(v) for k, v in (row.get("missed_function") or {}).items()}
            out.append(Entry(row["id"], row["question"], answers[row["id"]],
                             tuple(row["involved_classes"]), row["initial_config"],
                             tuple(row.get("excluded_function") or ()), missed))
    return sorted(out, key=lambda e: e.entry_id)
