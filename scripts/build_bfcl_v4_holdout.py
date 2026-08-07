# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Seal the second external BFCL routing track without exposing its contents.

The first BFCL v3 population is spent.  This track uses two disjoint BFCL v4
populations: ``live_multiple`` for positive/gold calls and only previously
unused rows from ``live_irrelevance`` for native refusals.  It deliberately
retains the original five targets so this is a confirmation, not a new test
whose bar was chosen after looking at results.

Expected cache files (copied verbatim from the pinned upstream commit):

* ``BFCL_v4_live_multiple.json``
* ``BFCL_v4_live_multiple_answers.json``
* ``BFCL_v4_live_irrelevance.json``
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.toolcall.routing.admission import assess_admission  # noqa: E402
from remora.toolcall.routing.compatibility import StateIndex  # noqa: E402
from remora.toolcall.routing.mutations import (  # noqa: E402
    MutationFamily,
    family_of,
    mutate_episodes,
)
from remora.toolcall.routing.route_table import table_content_hash  # noqa: E402
from remora.toolcall.routing.sources.bfcl import BfclAdapter, bfcl_registry  # noqa: E402

CACHE = REPO_ROOT / ".cache" / "routing_bench" / "bfcl_v4"
OUT_DIR = REPO_ROOT / "data" / "routing_bench_bfcl_v4"
SPENT = REPO_ROOT / "data" / "routing_bench_bfcl" / "bfcl_holdout.jsonl"

UPSTREAM_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
UPSTREAM_REPO = "https://github.com/ShishirPatil/gorilla"
SEED = 20260807
N_POSITIVE = 258
N_IRRELEVANCE = 258

TARGETS: dict[str, tuple[str, float]] = {
    "required_unknown_auto_accept": ("<=", 0.0),
    "known_wrong_call_accept": ("<=", 0.20),
    "irrelevance_abstain_recall": (">=", 0.70),
    "obtainable_verify_recall": (">=", 0.70),
    "unobtainable_abstain_recall": (">=", 0.70),
}

FILES = {
    "positive": "BFCL_v4_live_multiple.json",
    "answers": "BFCL_v4_live_multiple_answers.json",
    "irrelevance": "BFCL_v4_live_irrelevance.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_bytes(
        ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()
    )


def _spent_ids() -> set[str]:
    ids: set[str] = set()
    for row in _rows(SPENT):
        cluster = str(row["cluster_id"])
        ids.add(cluster.split(":", 1)[1])
    return ids


def main() -> int:
    for name in FILES.values():
        if not (CACHE / name).exists():
            print(f"missing {CACHE / name}; fetch pinned upstream first", file=sys.stderr)
            return 2

    positive = _rows(CACHE / FILES["positive"])
    answers = _rows(CACHE / FILES["answers"])
    irrelevance = _rows(CACHE / FILES["irrelevance"])
    spent = _spent_ids()

    positive = [row for row in positive if row["id"] not in spent]
    irrelevance = [row for row in irrelevance if row["id"] not in spent]
    if len(positive) < N_POSITIVE or len(irrelevance) < N_IRRELEVANCE:
        print("insufficient disjoint BFCL v4 population", file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    selected_positive = rng.sample(positive, N_POSITIVE)
    selected_ids = {row["id"] for row in selected_positive}
    selected_answers = [row for row in answers if row["id"] in selected_ids]
    selected_irrelevance = rng.sample(irrelevance, N_IRRELEVANCE)
    if len(selected_answers) != N_POSITIVE:
        print("positive/answer ID mismatch", file=sys.stderr)
        return 2
    if selected_ids & spent or {r["id"] for r in selected_irrelevance} & spent:
        print("REFUSING: selected population overlaps spent BFCL v3", file=sys.stderr)
        return 2

    CACHE.mkdir(parents=True, exist_ok=True)
    positive_path = CACHE / "BFCL_v4_live_multiple_sampled.json"
    answers_path = CACHE / "BFCL_v4_live_multiple_answers_sampled.json"
    irrelevance_path = CACHE / "BFCL_v4_live_irrelevance_unspent_sampled.json"
    _write_jsonl(positive_path, selected_positive)
    _write_jsonl(answers_path, selected_answers)
    _write_jsonl(irrelevance_path, selected_irrelevance)

    adapter = BfclAdapter(
        simple_path=positive_path,
        answers_path=answers_path,
        irrelevance_path=irrelevance_path,
        commit=UPSTREAM_COMMIT[:12],
    )
    registry = bfcl_registry([positive_path, irrelevance_path])
    native = adapter.build_episodes()
    gold = [e for e in native if e.id.endswith(":gold")]
    keep_native = [e for e in native if not e.id.endswith(":gold")]
    mutants = [
        mutant
        for mutant in mutate_episodes(gold, registry)
        if family_of(mutant) is not MutationFamily.WRONG_ARG_VALUE
    ]
    episodes = sorted(keep_native + mutants, key=lambda e: e.id)
    admission = assess_admission(
        list(episodes), StateIndex.from_values(set(), scopes=())
    ).to_json_dict()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes_path = OUT_DIR / "bfcl_holdout.jsonl"
    episodes_path.write_bytes(
        ("\n".join(e.to_jsonl() for e in episodes) + "\n").encode("utf-8")
    )
    registry_path = OUT_DIR / "registry.json"
    registry_path.write_bytes(
        (json.dumps(registry.to_json_dict(), indent=1, sort_keys=True) + "\n").encode()
    )

    manifest = {
        "schema": "routing_bench_bfcl_v4_v1",
        "track": "C-ext2 — disjoint external blind routing on BFCL v4 live",
        "status": "sealed_never_run",
        "upstream": {
            "repo": UPSTREAM_REPO,
            "commit": UPSTREAM_COMMIT,
            "license": "Apache-2.0",
            "files": {key: _sha(CACHE / value) for key, value in FILES.items()},
            "samples": {
                "seed": SEED,
                "positive": {"n": N_POSITIVE, "population": len(positive), "sha256": _sha(positive_path)},
                "irrelevance": {"n": N_IRRELEVANCE, "population": len(irrelevance), "sha256": _sha(irrelevance_path)},
            },
            "disjoint_from": "routing_bench_bfcl v3 spent population",
            "overlap_count": 0,
        },
        "sha256": _sha(episodes_path),
        "registry_sha256": _sha(registry_path),
        "route_table_version_hash": table_content_hash(),
        "n_episodes": len(episodes),
        "n_clusters": len({e.cluster_id for e in episodes}),
        "targets": {key: [op, value] for key, (op, value) in TARGETS.items()},
        "admission": admission,
        "excluded_axes": {
            "wrong_argument_value": "No vouchable external state table; labels may not be used as authority."
        },
        "caveat": (
            "Evaluated once on a disjoint sealed sample from BFCL v4 live_multiple "
            "and previously unused live_irrelevance rows, Apache-2.0, with an empty "
            "state index and no validator bindings. No retuning is permitted."
        ),
    }
    (OUT_DIR / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    (OUT_DIR / "ATTRIBUTION.md").write_text(
        "# Attribution\n\nDerived from Berkeley Function Calling Leaderboard v4 "
        f"(`live_multiple`, `live_irrelevance`), {UPSTREAM_REPO} @ "
        f"`{UPSTREAM_COMMIT}`, Apache-2.0.\n",
        encoding="utf-8",
    )
    print(f"sealed {len(episodes)} episodes over {manifest['n_clusters']} clusters")
    print("overlap with spent BFCL v3: 0")
    print(f"episodes sha256: {manifest['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
