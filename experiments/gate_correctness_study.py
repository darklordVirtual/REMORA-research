#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Gate-correctness study v1 (quality program WS7 item 1).

Pre-registered in experiments/gate_correctness/PREREGISTERED.md before this
file existed. Seven arms over the 540 fleetops episodes of the §33 validator
study; only the validator changes between arms. Ground truth is the episode
family: IDENTITY calls are valid, WRONG_ARG_VALUE calls carry an identifier
that exists in no role.

The question is not how often the agent is wrong, but what REMORA does when
its own gate is wrong: a stale snapshot, a lenient matcher, lookups that fail
open, an incomplete export read as closed-world.

    python experiments/gate_correctness_study.py

Writes results/gate_correctness_study_v1.json. Deterministic: every sampled
fault uses seed 0 or a stable hash of the episode and argument.
"""
from __future__ import annotations

import json
import random
import sys
import zlib
from collections import Counter
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.policy.report import DecisionAction  # noqa: E402
from remora.policy.resolution import validate_and_reenter  # noqa: E402
from remora.toolcall.routing.evaluate import build_full_observation, build_observation  # noqa: E402
from remora.toolcall.routing.mutations import MutationFamily, family_of  # noqa: E402
from remora.toolcall.routing.validator_study import build_study  # noqa: E402

OUT = ROOT / "results" / "gate_correctness_study_v1.json"
WORK_DIR = ROOT / ".cache" / "routing_bench" / "gate_correctness_study"
SEED = 0
STALE_MISSING = 0.15
FAIL_OPEN_RATE = 0.20
EXPORT_FRACTION = 0.70

Lookup = Callable[[str, str], "bool | None"]


def _drop(live: dict[str, frozenset[str]], fraction: float) -> dict[str, frozenset[str]]:
    """A deterministic subset of each role's identifiers without ``fraction`` of them."""
    rng = random.Random(SEED)
    out = {}
    for role in sorted(live):
        values = sorted(live[role])
        keep = len(values) - round(len(values) * fraction)
        out[role] = frozenset(rng.sample(values, keep))
    return out


def fault_lookup(arm: str, live: dict[str, frozenset[str]]) -> Callable[[str, str], "bool | None"]:
    """(argument, value) -> exists / absent / unknown, as the arm's faulty validator answers."""
    if arm == "correct":
        return lambda arg, value: value in live.get(arg, frozenset())
    if arm == "stale_snapshot":
        snap = _drop(live, STALE_MISSING)
        return lambda arg, value: value in snap.get(arg, frozenset())
    if arm == "prefix_matcher":
        return lambda arg, value: any(value.startswith(v) for v in live.get(arg, frozenset()))
    if arm == "fail_open":
        def lookup(arg: str, value: str) -> bool | None:
            unavailable = zlib.crc32(f"{arg}|{value}".encode()) % 100 < FAIL_OPEN_RATE * 100
            return True if unavailable else value in live.get(arg, frozenset())
        return lookup
    if arm in ("partial_closed_world", "partial_unknown"):
        export = _drop(live, 1 - EXPORT_FRACTION)
        closed = arm == "partial_closed_world"

        def partial(arg: str, value: str) -> bool | None:
            if value in export.get(arg, frozenset()):
                return True
            return False if closed else None
        return partial
    raise ValueError(f"unknown arm {arm!r}")


ARMS = ("no_gate", "correct", "stale_snapshot", "prefix_matcher", "fail_open",
        "partial_closed_world", "partial_unknown")


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def run_arm(study, arm: str) -> dict:
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    lookup = None if arm == "no_gate" else fault_lookup(arm, study.live_values)
    finals: list[tuple[object, DecisionAction]] = []
    for episode in study.episodes:
        if lookup is None:
            finals.append((episode, DecisionAction.ACCEPT))
            continue
        obs = build_full_observation(episode, study.registry, study.state, validators=study.validators)

        def validator(source_tool: str, argument: str, _ep=episode) -> bool | None:
            value = _ep.proposed_tool_args.get(argument)
            return lookup(argument, value) if isinstance(value, str) else None

        outcome = validate_and_reenter(obs, engine, validator=validator)
        finals.append((episode, outcome.final_report.action))

    def is_write(ep) -> bool:
        return build_observation(ep, study.registry).action_type == "write"

    identity = [(e, a) for e, a in finals if family_of(e) is MutationFamily.IDENTITY]
    wrong = [(e, a) for e, a in finals if family_of(e) is MutationFamily.WRONG_ARG_VALUE]
    reads = [(e, a) for e, a in identity if not is_write(e)]
    wrong_reads = [(e, a) for e, a in wrong if not is_write(e)]
    writes = [(e, a) for e, a in identity if is_write(e)]
    accept = DecisionAction.ACCEPT
    success = _rate(sum(a is accept for _, a in reads), len(reads))
    return {
        "false_allow": _rate(sum(a is accept for _, a in wrong), len(wrong)),
        "valid_read_success": success,
        "false_block": round(1 - success, 4),
        "valid_read_refused": _rate(sum(a is DecisionAction.ABSTAIN for _, a in reads), len(reads)),
        "write_auto_accept": _rate(sum(a is accept for _, a in writes), len(writes)),
        "review_burden": _rate(sum(a in (DecisionAction.VERIFY, DecisionAction.ESCALATE) for _, a in finals),
                               len(finals)),
        # Post hoc, added after the run and not a pre-registered measure: the
        # pre-registered false_allow counts corrupt writes, which the engine
        # never auto-accepts, in its denominator.
        "post_hoc_false_allow_reads_only": _rate(sum(a is accept for _, a in wrong_reads), len(wrong_reads)),
        "n": {"episodes": len(finals), "wrong_arg_value": len(wrong), "wrong_arg_value_reads": len(wrong_reads),
              "identity_reads": len(reads),
              "identity_writes": len(writes)},
        "final_routes": dict(sorted(Counter(a.value for _, a in finals).items())),
    }


def predictions(arms: dict[str, dict]) -> dict[str, dict]:
    c, s, p, f = arms["correct"], arms["stale_snapshot"], arms["prefix_matcher"], arms["fail_open"]
    pc, pu = arms["partial_closed_world"], arms["partial_unknown"]
    checks = {
        "P1": (c["false_allow"] <= 0.05 and c["valid_read_success"] >= 0.85,
               f"false_allow {c['false_allow']}, valid_read_success {c['valid_read_success']}"),
        "P2": (arms["no_gate"]["false_allow"] == 1.0 and arms["no_gate"]["write_auto_accept"] == 1.0,
               f"false_allow {arms['no_gate']['false_allow']}, write_auto_accept {arms['no_gate']['write_auto_accept']}"),
        "P3": (c["valid_read_success"] - s["valid_read_success"] >= 0.10 and s["false_allow"] <= c["false_allow"],
               f"success drop {round(c['valid_read_success'] - s['valid_read_success'], 4)}, "
               f"false_allow {s['false_allow']}"),
        "P4": (p["false_allow"] >= 0.50, f"false_allow {p['false_allow']}"),
        "P5": (0.10 <= f["false_allow"] <= 0.30, f"false_allow {f['false_allow']}"),
        "P6": (pc["valid_read_refused"] - pu["valid_read_refused"] >= 0.20
               and pu["review_burden"] > pc["review_burden"],
               f"refused {pc['valid_read_refused']} vs {pu['valid_read_refused']}, "
               f"review {pu['review_burden']} vs {pc['review_burden']}"),
        "P7": (all(arms[a]["write_auto_accept"] == 0.0 for a in ARMS if a != "no_gate"),
               ", ".join(f"{a} {arms[a]['write_auto_accept']}" for a in ARMS if a != "no_gate")),
    }
    return {k: {"met": bool(ok), "measured": detail} for k, (ok, detail) in checks.items()}


def run() -> dict:
    study = build_study(WORK_DIR)
    arms = {arm: run_arm(study, arm) for arm in ARMS}
    return {
        "schema": "gate_correctness_study_v1",
        "status": "mechanism_study_not_blind",
        "preregistration": "experiments/gate_correctness/PREREGISTERED.md",
        "faults": {"seed": SEED, "stale_missing_fraction": STALE_MISSING,
                   "fail_open_rate": FAIL_OPEN_RATE, "partial_export_fraction": EXPORT_FRACTION},
        "arms": arms,
        "predictions": predictions(arms),
        "caveat": ("Openly non-blind mechanism study on the synthetic fleetops domain. The retired-"
                   "identifier path of a stale snapshot is not sampled. Numbers bound this material, "
                   "not REMORA in general."),
    }


def main() -> int:
    result = run()
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for arm, m in result["arms"].items():
        print(f"{arm:22} false_allow={m['false_allow']:.3f} success={m['valid_read_success']:.3f} "
              f"refused={m['valid_read_refused']:.3f} review={m['review_burden']:.3f} writes={m['write_auto_accept']:.3f}")
    for pid, v in result["predictions"].items():
        print(f"{pid}: {'met' if v['met'] else 'MISSED'} ({v['measured']})")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
