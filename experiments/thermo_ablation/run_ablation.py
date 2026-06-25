"""Thermo-control ablation runner (scaffolding).

PRE-REGISTERED, NOT YET RUN. See PREREGISTERED.md. This scaffolding refuses to
fabricate results: without a real action-log input it writes a status:pending
output and exits non-zero. It never invents AURC numbers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
VARIANTS = ["V0", "V1", "V2", "V3", "V4", "V5"]


def write_pending(reason: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "thermo_ablation_results.json"
    out.write_text(json.dumps({
        "status": "pending",
        "reason": reason,
        "split": "held_out",
        "seed": 42,
        "variants": [],
        "claims_allowed": False,
    }, indent=2))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Thermo ablation (pre-registered).")
    p.add_argument("--action-log", type=Path, help="JSONL action log (held-out).")
    p.add_argument("--allow-missing", action="store_true")
    args = p.parse_args(argv)

    if not args.action_log or not args.action_log.exists():
        out = write_pending("no action log provided; ablation not run")
        print(f"PENDING: no input. Wrote status:pending to {out}")
        print("This is scaffolding. No results were fabricated.")
        return 0 if args.allow_missing else 2

    # A real implementation would: load log, lock tau* on train, score each
    # variant's AURC on held-out, bootstrap CIs. Deliberately NOT implemented
    # with synthetic data to avoid producing tunable/inventable numbers.
    out = write_pending("scoring not implemented; refusing to fabricate AURC")
    print(f"PENDING: scoring unimplemented. Wrote {out}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
