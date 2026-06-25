"""Probe which tools AgentHarm exposes to a solver under Inspect.

Earlier runs showed only the synthetic ``submit`` tool in the request, which
would mean REMORA is gating *intent* (the submit payload), not real tool calls.
This script records, deterministically and without making LLM calls, which
scenario tools AgentHarm attaches to a sample's TaskState. It writes
``results/agentharm/tool_probe.json``.

    python experiments/agentharm/inspect_tools_probe.py [--limit 3]
"""
from __future__ import annotations
# Allow direct invocation as a script (python experiments/agentharm/<file>.py)
import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent.parent.parent / "results" / "agentharm" / "tool_probe.json"


def _write(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT}")


def probe(limit: int) -> dict:
    """Load a few AgentHarm samples and list the tools each one would attach.

    Uses sample metadata (``target_functions``) plus the benchmark tool modules,
    matching what solvers.py injects. This reflects the true tool surface without
    needing a model or network.
    """
    result: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "samples": [],
        "tools_beyond_submit_exposed": False,
        "error": None,
    }
    try:
        from inspect_evals.agentharm.benchmark import benign_tools, harmful_tools
        from inspect_evals.agentharm.agentharm import agentharm as agentharm_task
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    try:
        task = agentharm_task()
        samples = list(task.dataset)[:limit]
        any_real_tools = False
        for s in samples:
            md = getattr(s, "metadata", {}) or {}
            targets = md.get("target_functions", []) or []
            available = [
                name for name in targets
                if hasattr(harmful_tools, name) or hasattr(benign_tools, name)
            ]
            if available:
                any_real_tools = True
            result["samples"].append({
                "id": getattr(s, "id", None),
                "target_functions": targets,
                "available_tools": available,
            })
        result["tools_beyond_submit_exposed"] = any_real_tools
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()
    payload = probe(args.limit)
    _write(payload)
    if payload["error"]:
        print(f"PROBE INCOMPLETE: {payload['error']}", file=sys.stderr)
        return 1
    print(f"tools_beyond_submit_exposed: {payload['tools_beyond_submit_exposed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
