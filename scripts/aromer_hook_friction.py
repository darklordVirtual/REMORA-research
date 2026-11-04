#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Descriptive statistics of AROMER's shadow-mode verdicts on recorder-hook traffic.

Reads ``episodes_public.jsonl`` from the AROMER D1 export of 2026-11-03 (kept
outside git; its SHA-256 is pinned in the export's JSON) and writes one JSON
artifact: how AROMER's verdicts fell on the 18,249 Claude Code PreToolUse
episodes, by tool, action type and risk tier.

What this is: a measured friction profile of one shadow-mode scorer on real,
mostly routine agent tool calls, and the tool mix of that traffic.

What this is not: a false-block rate. The hook episodes carry presumed-benign
defaults or TTL expiries, not adjudicated labels, so a VERIFY on them is
review load, not a proven false block. The episodes have no arguments, so they
cannot be replayed through REMORA's own gate.

Usage::

    python scripts/aromer_hook_friction.py episodes_public.jsonl \
        --export artifacts/aromer/d1_export_2026-11-03/aromer_d1_export_2026-11-03.json \
        --out artifacts/aromer/d1_export_2026-11-03/hook_episode_friction_v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HOOK_SOURCE = "claude_code_pretooluse"
VERDICTS = ("ACCEPT", "VERIFY", "ESCALATE", "pending")


def _verdict(row: dict[str, Any]) -> str:
    v = str(row.get("verdict") or "pending")
    return v if v in VERDICTS else "other"


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counts of AROMER verdicts on hook episodes, by tool, action type and tier.

    Pure: the same rows give the same summary. Rates are reported next to
    their counts and denominators; nothing is rounded away.
    """
    hook = [r for r in rows if ((r.get("meta") or {}).get("source") == HOOK_SOURCE)]
    by_verdict: Counter[str] = Counter(_verdict(r) for r in hook)
    truth: Counter[str] = Counter(str(r.get("ground_truth")) for r in hook)

    def table(key: str) -> dict[str, dict[str, int]]:
        out: dict[str, Counter[str]] = defaultdict(Counter)
        for r in hook:
            value = (r.get("meta") or {}).get(key) if key == "tool" else r.get(key)
            out[str(value)][_verdict(r)] += 1
        return {k: dict(sorted(v.items())) for k, v in sorted(out.items(), key=lambda kv: -sum(kv[1].values()))}

    n = len(hook)
    review = by_verdict.get("VERIFY", 0) + by_verdict.get("ESCALATE", 0)
    p_harm = sorted(float((r.get("meta") or {}).get("p_harm")) for r in hook
                    if (r.get("meta") or {}).get("p_harm") is not None)

    def quantile(q: float) -> float | None:
        if not p_harm:
            return None
        i = min(len(p_harm) - 1, max(0, round(q * (len(p_harm) - 1))))
        return p_harm[i]

    return {
        "hook_episodes": n,
        "verdicts": dict(sorted(by_verdict.items())),
        "review_required": {"count": review, "denominator": n,
                            "rate": (review / n) if n else None},
        "ground_truth": dict(sorted(truth.items())),
        "by_tool": table("tool"),
        "by_action_type": table("action_type"),
        "by_risk_tier": table("risk_tier"),
        "by_domain": table("domain"),
        "p_harm": {"n": len(p_harm), "min": p_harm[0] if p_harm else None,
                   "p50": quantile(0.5), "p90": quantile(0.9), "p99": quantile(0.99),
                   "max": p_harm[-1] if p_harm else None},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("episodes", type=Path, help="episodes_public.jsonl from the export")
    parser.add_argument("--export", type=Path, required=True,
                        help="the export JSON whose public_episode_file.sha256 pins the input")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    export = json.loads(args.export.read_text(encoding="utf-8"))
    pinned = export["public_episode_file"]["sha256"]
    data = args.episodes.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != pinned:
        print(f"refusing: input sha256 {actual} is not the pinned {pinned}", file=sys.stderr)
        return 2
    # split on newlines only: str.splitlines() also breaks on U+2028 and other
    # separators that occur inside JSON strings
    rows = [json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip()]
    if len(rows) != export["public_episode_file"]["rows"]:
        print(f"refusing: {len(rows)} rows, export pins {export['public_episode_file']['rows']}",
              file=sys.stderr)
        return 2

    out = {
        "schema": "aromer_hook_episode_friction_v1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input": {"name": args.episodes.name, "sha256": actual, "rows": len(rows),
                  "pinned_in": str(args.export).replace("\\", "/")},
        "scope": ("AROMER shadow-mode verdicts on Claude Code PreToolUse recorder-hook episodes, "
                  "2026-06-04 to 2026-07-02. Descriptive only."),
        "caveats": [
            "Hook labels are presumed-benign defaults or TTL expiries, not adjudications; "
            "VERIFY is review load, not a proven false block.",
            "Episodes carry no tool arguments (sanitized), so they cannot be replayed through "
            "REMORA's gate; this measures AROMER, not REMORA.",
            "One scorer, one deployment, one month of one developer's traffic; not a benchmark.",
        ],
        "summary": summarize(rows),
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    # The result is written with its provenance sidecar (scripts/result_provenance.py),
    # as every result artifact in this repository is; a sidecar is never written later.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from result_provenance import write_sidecar

    write_sidecar(args.out, script="scripts/aromer_hook_friction.py",
                  inputs={"episodes": args.episodes, "export": args.export},
                  command="python scripts/aromer_hook_friction.py <episodes_public.jsonl> "
                          f"--export {args.export.as_posix()} --out {args.out.as_posix()}")
    s = out["summary"]
    print(f"hook episodes {s['hook_episodes']}: {s['verdicts']}; review rate "
          f"{s['review_required']['count']}/{s['review_required']['denominator']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
