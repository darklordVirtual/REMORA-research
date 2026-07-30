#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Deterministic Merkle checkpoint generator for the demo shadow-replay chain.

Replays ``artifacts/demo/shadow_mode_sample_agent_action_log.jsonl`` through
the shadow replay engine (the same path as ``remora.shadow.replay``), verifies
the DecisionEnvelope hash chain, and emits one Merkle checkpoint per span of
N=8 envelope hashes (the final span may be shorter) to
``artifacts/audit_anchoring/sample_checkpoints.jsonl``.

The output is byte-identical on re-run: no timestamps, no randomness, sorted
JSON keys, LF line endings.

Exit codes: 0 = success, 1 = input log missing, 2 = invalid --interval,
envelope hash chain or checkpoint self-verification failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the repo root is on the path so that `remora` is importable when this
# script is invoked directly (e.g. `python scripts/generate_audit_checkpoints.py`)
# without the package being installed in the active Python environment.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from remora.audit.checkpoint import (
    Checkpoint,
    envelope_chain_leaves,
    make_checkpoint,
    verify_checkpoint_chain,
    verify_span,
)
from remora.shadow.replay import replay_action_log, verify_envelope_hash_chain

_DEFAULT_INPUT = _REPO_ROOT / "artifacts" / "demo" / "shadow_mode_sample_agent_action_log.jsonl"
_DEFAULT_OUTPUT = _REPO_ROOT / "artifacts" / "audit_anchoring" / "sample_checkpoints.jsonl"


def build_checkpoints(leaves: list[str], interval: int) -> list[Checkpoint]:
    """Chunk *leaves* into contiguous spans of *interval* and checkpoint each."""
    checkpoints: list[Checkpoint] = []
    prev: Checkpoint | None = None
    for start in range(0, len(leaves), interval):
        checkpoint = make_checkpoint(leaves[start : start + interval], start, prev)
        checkpoints.append(checkpoint)
        prev = checkpoint
    return checkpoints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic Merkle checkpoints over the demo shadow-replay chain"
    )
    parser.add_argument(
        "--input",
        default=str(_DEFAULT_INPUT),
        help="Agent action log JSONL to replay (default: demo shadow log)",
    )
    parser.add_argument(
        "--output",
        default=str(_DEFAULT_OUTPUT),
        help="Checkpoint JSONL output path",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=8,
        help="Number of envelope hashes per checkpoint span (default: 8)",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[FAIL] input log not found: {input_path}", file=sys.stderr)
        return 1
    if args.interval < 1:
        print(f"[FAIL] --interval must be >= 1, got {args.interval}", file=sys.stderr)
        return 2

    result = replay_action_log(str(input_path))
    if not verify_envelope_hash_chain(result.envelopes):
        print("[FAIL] envelope hash chain did not verify — refusing to checkpoint", file=sys.stderr)
        return 2

    leaves = envelope_chain_leaves(result.envelopes)
    checkpoints = build_checkpoints(leaves, args.interval)

    # Self-verify before writing: every span must recompute to its root and
    # the checkpoint chain must be internally consistent.
    for checkpoint in checkpoints:
        span = leaves[checkpoint.seq_start : checkpoint.seq_end + 1]
        if not verify_span(span, checkpoint):
            print(
                f"[FAIL] checkpoint span [{checkpoint.seq_start}, {checkpoint.seq_end}] "
                "did not verify against its own root",
                file=sys.stderr,
            )
            return 2
    ok, problems = verify_checkpoint_chain(checkpoints)
    if not ok:
        print(f"[FAIL] checkpoint chain inconsistent: {problems}", file=sys.stderr)
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" pins LF endings on every platform so the artifact is
    # byte-identical on re-run (determinism gate for this generator).
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        for checkpoint in checkpoints:
            f.write(json.dumps(checkpoint.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")

    print(f"[OK] replayed {len(result.envelopes)} envelopes from {input_path}")
    print(f"[OK] wrote {len(checkpoints)} checkpoint(s) (interval={args.interval}) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
