#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Build the requests a second approver is asked about, without saying who asks.

    python scripts/build_limits_approval_packets.py --policy P --trusted-key K \
        --shifts S.json [...] --episodes E.json [...] --seed TEXT \
        --packets PACKETS.json --key KEY.json

Plan v6 (docs/assurance/ot_limits_holdout_plan_v6.md) puts every write that
would pass a second tier to an approver who does not know whether the
request comes from a legitimate shift or from a misuse episode. This script
makes that approver's input.

Each sequence, shift or episode alike, is replayed under the policy with a
second approver who approves everything, so that every write that could need
one is found. For each such write a packet holds the writes proposed before
it in the sequence, with their reasons, the request itself, and the bounds it
would pass. A packet has an opaque case id and nothing that names its file,
its sequence id, its position or its population: a shift's ``context`` and an
episode's ``harm`` and ``approach`` are left out. Packets are sorted by case
id, which is a digest, so the two populations are mixed.

The key file maps each case back to its sequence and index. The approver
never sees it. ``merge`` turns the approver's answer and the key into the
approvals file the replays read.

What an approver cannot be asked about is a write that needs a second
approver only because an earlier one was refused. The replays treat such a
write as not approved and count it.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_limits_holdout as holdout  # noqa: E402
import run_limits_protection as protection  # noqa: E402

SCHEMA = "remora-limits-approval-packets/v1"
#: What a write shows the approver. Nothing else of a write is copied.
SHOWN = ("t_min", "tool", "args", "why")


def case_id(seed: str, sequence_id: str, index: int) -> str:
    return "case-" + hashlib.sha256(f"{seed}\x00{sequence_id}\x00{index}".encode()).hexdigest()[:12]


def _shown(write: dict[str, Any]) -> dict[str, Any]:
    return {k: write[k] for k in SHOWN if k in write}


def packets_for(sequence_id: str, writes: list[dict[str, Any]], policy: Any, registry: Any,
                pristine: dict[str, Any], seed: str) -> list[tuple[dict[str, Any], int]]:
    """``(packet, index)`` for every write of one sequence that could need a second approver."""
    shift = {"shift_id": sequence_id, "writes": writes}
    with tempfile.TemporaryDirectory() as tmp:
        rows = holdout.replay_shift(shift, policy, registry, pristine, Path(tmp), approvers=2)
    out = []
    for row in rows:
        if not row.get("dual_control"):
            continue
        index = row["index"]
        out.append(({"case": case_id(seed, sequence_id, index),
                     "log_so_far": [_shown(w) for w in writes[:index]],
                     "request": _shown(writes[index]),
                     "would_pass": sorted(row["dual_control"])}, index))
    return out


def build(policy_path: Path, key_file: Path, shifts: list[Path], episodes: list[Path],
          seed: str) -> tuple[dict[str, Any], dict[str, Any]]:
    policy, digest, _ = holdout.load_policy(policy_path,
                                            key_file.read_text(encoding="utf-8").split())
    registry = holdout._registry()
    pristine = copy.deepcopy(registry.PLANT)
    packets: list[dict[str, Any]] = []
    key: dict[str, dict[str, Any]] = {}
    sources = [("shift", p, holdout.validate, "shift_id") for p in shifts]
    sources += [("episode", p, protection.validate, "episode_id") for p in episodes]
    for population, path, validate, id_field in sources:
        for sequence in validate(json.loads(path.read_bytes())):
            sid = sequence[id_field]
            for packet, index in packets_for(sid, sequence["writes"], policy, registry,
                                             pristine, seed):
                if packet["case"] in key:
                    raise SystemExit(f"case id collision on {sid}:{index}; change --seed")
                packets.append(packet)
                key[packet["case"]] = {"population": population, "file": path.name,
                                       "sequence": sid, "index": index}
    packets.sort(key=lambda p: p["case"])
    return ({"schema": SCHEMA, "policy_sha256": digest, "packets": packets},
            {"schema": SCHEMA + "/key", "policy_sha256": digest,
             "cases": dict(sorted(key.items()))})


def merge(answer: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    """The approvals file: one decision per case the approver answered and the key holds."""
    cases = key["cases"]
    rows = answer.get("decisions")
    if not isinstance(rows, list):
        raise SystemExit("the approver's answer is {\"decisions\": [{\"case\", \"approve\", \"why\"}]}")
    decisions: dict[str, bool] = {}
    seen: set[str] = set()
    for row in rows:
        case = row.get("case")
        if case not in cases or case in seen or not isinstance(row.get("approve"), bool):
            raise SystemExit(f"decision for {case!r} is unknown, repeated or not a boolean")
        seen.add(case)
        decisions[f"{cases[case]['sequence']}:{cases[case]['index']}"] = row["approve"]
    return {"schema": "remora-limits-approvals/v1",
            "approver_session": answer.get("approver_session"),
            "cases_asked": len(cases), "cases_answered": len(seen),
            "unanswered_and_so_not_approved": sorted(
                f"{cases[c]['sequence']}:{cases[c]['index']}" for c in cases if c not in seen),
            "decisions": dict(sorted(decisions.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--policy", type=Path, required=True)
    b.add_argument("--trusted-key", type=Path, required=True)
    b.add_argument("--shifts", type=Path, nargs="*", default=[])
    b.add_argument("--episodes", type=Path, nargs="*", default=[])
    b.add_argument("--seed", required=True)
    b.add_argument("--packets", type=Path, required=True)
    b.add_argument("--key", type=Path, required=True)
    m = sub.add_parser("merge")
    m.add_argument("--answer", type=Path, required=True)
    m.add_argument("--key", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        packets, key = build(args.policy, args.trusted_key, args.shifts, args.episodes, args.seed)
        args.packets.write_text(json.dumps(packets, indent=1, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        args.key.write_text(json.dumps(key, indent=1) + "\n", encoding="utf-8")
        by = {}
        for entry in key["cases"].values():
            by[entry["population"]] = by.get(entry["population"], 0) + 1
        print(f"{len(packets['packets'])} packets: {by}")
        return 0
    out = merge(json.loads(args.answer.read_text(encoding="utf-8")),
                json.loads(args.key.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{out['cases_answered']} of {out['cases_asked']} cases answered, "
          f"{sum(out['decisions'].values())} approved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
