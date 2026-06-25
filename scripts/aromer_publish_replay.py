# Author: Stian Skogbrott
# License: Apache-2.0
"""Run the REAL Python replay arena and publish the result to the AROMER worker.

Closes the transfer-score provenance gap: the AROMER worker's AII transfer
component (weight 0.15) previously came from a hardcoded static seed
expectation. This script runs the actual replay arena
(remora.aromer.evals.replay_runner) against the live RemoraDecisionEngine,
writes the result as a local artifact, and — with ``--publish`` — POSTs it to
the worker's ``/replay-report`` endpoint so the next adaptation cycle uses a
*measured* transfer score (source: ``python_replay_arena``).

Usage
-----
    python scripts/aromer_publish_replay.py            # run + artifact only
    python scripts/aromer_publish_replay.py --publish  # also POST to worker

No API keys required; ``--publish`` needs network access to the worker.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from remora.aromer.evals.replay_runner import run_arena  # noqa: E402
from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402

DEFAULT_WORKER_URL = "https://aromer.razorsharp.workers.dev"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "aromer"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true",
                        help="POST the measured report to the AROMER worker")
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL)
    args = parser.parse_args()

    report = run_arena(engine=RemoraDecisionEngine())
    print("\n".join(report.summary_lines()))

    payload = {
        "replay_score": round(report.sis.sis, 4),
        "replay_accuracy": round(report.overall_accuracy, 4),
        "replay_transfer_score": round(report.sis.transfer_success, 4),
        "replay_cases": report.total_episodes,
        "categories": [
            {"category": cm.category, "n": cm.n,
             "expectedAccuracy": round(cm.accuracy, 4)}
            for cm in report.category_metrics
        ],
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACT_DIR / "replay_arena_report.json"
    artifact.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": report.run_id,
        "false_accept_rate": report.false_accept_rate,
        "false_block_rate": report.false_block_rate,
        "review_friction": report.review_friction,
        "worker_payload": payload,
    }, indent=2), encoding="utf-8")
    print(f"\nartifact: {artifact}")

    if report.false_accept_rate > 0:
        print("FAIL: replay arena detected false accepts — not publishing",
              file=sys.stderr)
        return 1

    if args.publish:
        req = urllib.request.Request(
            f"{args.worker_url.rstrip('/')}/replay-report",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # The zone WAF blocks the default Python-urllib agent.
                "User-Agent": "remora-replay-publisher/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except OSError as exc:
            print(f"FAIL: could not publish to worker: {exc}", file=sys.stderr)
            return 1
        print(f"published: {body}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
