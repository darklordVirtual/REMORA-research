# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Seal C-ext3 — BFCL v4 semantic-authority confirmation (SAP v5).

Samples 500 fresh positive clusters and 300 fresh irrelevance cases from the
pinned BFCL v4 populations, excluding the spent IDs of BOTH the v3 track and
C-ext2. The frozen semantic bundle's file hash is recorded in the manifest at
seal time; editing the bundle after sealing invalidates the track.
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
OUT_DIR = REPO_ROOT / "data" / "routing_bench_bfcl_v4_cext3"
SPENT_V3 = REPO_ROOT / "data" / "routing_bench_bfcl" / "bfcl_holdout.jsonl"
SPENT_CEXT2 = REPO_ROOT / "data" / "routing_bench_bfcl_v4" / "bfcl_holdout.jsonl"
BUNDLE_FILE = REPO_ROOT / "remora" / "toolcall" / "routing" / "bfcl_semantic_bundle.py"
GOAL_MATCH_FILE = REPO_ROOT / "remora" / "toolcall" / "routing" / "goal_match.py"

UPSTREAM_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
UPSTREAM_REPO = "https://github.com/ShishirPatil/gorilla"
SEED = 20260820
N_POSITIVE = 500
N_IRRELEVANCE = 300

# SAP v5 §2 — pre-registered before the sample was drawn.
TARGETS: dict[str, tuple[str, float]] = {
    "required_unknown_auto_accept": ("<=", 0.0),
    "known_wrong_call_accept": ("<=", 0.01),
    "constructed_wrong_tool_accept": ("<=", 0.01),
    "irrelevance_abstain_recall": (">=", 0.95),
    "obtainable_verify_recall": (">=", 0.95),
    "unobtainable_abstain_recall": (">=", 0.95),
    "legitimate_read_autonomy": (">=", 0.75),
}

FILES = {
    "positive": "BFCL_v4_live_multiple.json",
    "answers": "BFCL_v4_live_multiple_answers.json",
    "irrelevance": "BFCL_v4_live_irrelevance.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_bytes(
        ("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n").encode()
    )


def _spent_ids() -> set[str]:
    ids: set[str] = set()
    for spent_file in (SPENT_V3, SPENT_CEXT2):
        for row in _rows(spent_file):
            cluster = str(row["cluster_id"])
            ids.add(cluster.split(":", 1)[1])
    return ids


def main() -> int:
    for name in FILES.values():
        if not (CACHE / name).exists():
            print(f"missing {CACHE / name}", file=sys.stderr)
            return 2

    positive = _rows(CACHE / FILES["positive"])
    answers = _rows(CACHE / FILES["answers"])
    irrelevance = _rows(CACHE / FILES["irrelevance"])
    spent = _spent_ids()

    positive = [r for r in positive if r["id"] not in spent]
    irrelevance = [r for r in irrelevance if r["id"] not in spent]
    if len(positive) < N_POSITIVE or len(irrelevance) < N_IRRELEVANCE:
        print(f"insufficient population: {len(positive)}/{len(irrelevance)}",
              file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    sel_pos = rng.sample(positive, N_POSITIVE)
    sel_ids = {r["id"] for r in sel_pos}
    sel_ans = [r for r in answers if r["id"] in sel_ids]
    sel_irr = rng.sample(irrelevance, N_IRRELEVANCE)
    if len(sel_ans) != N_POSITIVE:
        print("positive/answer ID mismatch", file=sys.stderr)
        return 2
    if sel_ids & spent or {r["id"] for r in sel_irr} & spent:
        print("REFUSING: overlap with spent v3/C-ext2 populations",
              file=sys.stderr)
        return 2

    pos_path = CACHE / "BFCL_v4_live_multiple_cext3_sampled.json"
    ans_path = CACHE / "BFCL_v4_live_multiple_answers_cext3_sampled.json"
    irr_path = CACHE / "BFCL_v4_live_irrelevance_cext3_sampled.json"
    _write_jsonl(pos_path, sel_pos)
    _write_jsonl(ans_path, sel_ans)
    _write_jsonl(irr_path, sel_irr)

    adapter = BfclAdapter(
        simple_path=pos_path, answers_path=ans_path, irrelevance_path=irr_path,
        commit=UPSTREAM_COMMIT[:12],
    )
    registry = bfcl_registry([pos_path, irr_path])
    native = adapter.build_episodes()
    gold = [e for e in native if e.id.endswith(":gold")]
    keep_native = [e for e in native if not e.id.endswith(":gold")]
    mutants = [
        m for m in mutate_episodes(gold, registry)
        if family_of(m) is not MutationFamily.WRONG_ARG_VALUE
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
        "schema": "routing_bench_bfcl_v4_cext3_v1",
        "track": "C-ext3 — BFCL v4 semantic-authority confirmation (SAP v5)",
        "status": "sealed_never_run",
        "sap": "docs/assurance/statistical_analysis_plan_v5_bfcl_semantic.md",
        "frozen_semantic_bundle_sha256": _sha(BUNDLE_FILE),
        "frozen_goal_match_sha256": _sha(GOAL_MATCH_FILE),
        "upstream": {
            "repo": UPSTREAM_REPO,
            "commit": UPSTREAM_COMMIT,
            "license": "Apache-2.0",
            "files": {k: _sha(CACHE / v) for k, v in FILES.items()},
            "samples": {
                "seed": SEED,
                "positive": {"n": N_POSITIVE, "population": len(positive),
                             "sha256": _sha(pos_path)},
                "irrelevance": {"n": N_IRRELEVANCE, "population": len(irrelevance),
                                "sha256": _sha(irr_path)},
            },
            "disjoint_from": "spent v3 AND spent C-ext2 populations",
            "overlap_count": 0,
        },
        "sha256": _sha(episodes_path),
        "registry_sha256": _sha(registry_path),
        "route_table_version_hash": table_content_hash(),
        "n_episodes": len(episodes),
        "n_clusters": len({e.cluster_id for e in episodes}),
        "targets": {k: [op, v] for k, (op, v) in TARGETS.items()},
        "admission": admission,
        "excluded_axes": {
            "wrong_argument_value": "No vouchable external state table; labels "
                                    "may not be used as authority."
        },
        "caveat": (
            "Evaluated once, sealed. Configuration: frozen deterministic "
            "semantic bundle (contracts from tool names only; intent from task "
            "text only), semantic_authority_floor on, low_consequence_accept "
            "on, EMPTY state index (BFCL provides no system of record and none "
            "is invented) — the accept property is SEMANTICALLY AUTHORIZED "
            "READ, explicitly weaker than SAP v4 grounded read. No retuning "
            "against this set is permitted; misses are published as measured."
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
    print(f"remaining reserve: positive {len(positive) - N_POSITIVE}, "
          f"irrelevance {len(irrelevance) - N_IRRELEVANCE}")
    print(f"bundle sha: {manifest['frozen_semantic_bundle_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
