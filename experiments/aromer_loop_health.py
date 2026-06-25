# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER learning-loop health report.

Pulls the live ``/intelligence`` history, applies the tested reference
smoothing (remora.aromer.intelligence.score), and runs deterministic defect
checks on the measurement pipeline itself:

1. **transfer_provenance** — is the AII transfer component a real measurement
   (``python_replay_arena``) or the static seed expectation?
2. **aii_volatility** — std-dev of raw AII across the window vs the smoothed
   series; high raw volatility on a static episode set is measurement noise.
3. **episode_growth** — is the labelled-episode window actually moving, or has
   the loop stopped ingesting new experience?
4. **stability_liveness** — is the T5 stability component flat at the old
   structural floor (~0.10) or responding to the v2 formula?
5. **safety** — false_accept_rate must be 0 across the window.

Writes ``artifacts/aromer/loop_health.json``. Exits non-zero when the worker
is unreachable or a safety check fails, so this can run as a CI/cron guard.
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from remora.aromer.intelligence.score import EMA_ALPHA, ema_smooth  # noqa: E402

DEFAULT_WORKER_URL = "https://aromer.razorsharp.workers.dev"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "aromer"


def fetch_intelligence(worker_url: str, history: int = 48) -> dict:
    url = f"{worker_url.rstrip('/')}/intelligence?history={history}"
    # The zone WAF blocks the default Python-urllib agent.
    req = urllib.request.Request(
        url, headers={"User-Agent": "remora-loop-health/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def analyse(data: dict) -> dict:
    history = data.get("history") or []
    # newest-first from the API; analysis runs oldest-first
    rows = list(reversed(history))
    raw_aii = [float(r["aii"]) for r in rows]
    smoothed = ema_smooth(raw_aii)

    checks: dict[str, dict] = {}

    meta = data.get("meta") or {}
    transfer_source = meta.get("transfer_source", "unknown")
    checks["transfer_provenance"] = {
        "status": "PASS" if transfer_source == "python_replay_arena" else "WARN",
        "transfer_source": transfer_source,
        "detail": (
            "transfer component is a real measured replay result"
            if transfer_source == "python_replay_arena"
            else "transfer component is a static seed expectation — run "
                 "scripts/aromer_publish_replay.py --publish"
        ),
    }

    if len(raw_aii) >= 4:
        raw_std = statistics.pstdev(raw_aii)
        smoothed_std = statistics.pstdev(smoothed)
        # 0.06 chosen below the observed live noise floor (std ≈ 0.077 on a
        # static episode set, 2026-06-05..09) so that regime is flagged.
        volatile = raw_std >= 0.06
        checks["aii_volatility"] = {
            "status": "WARN" if volatile else "PASS",
            "raw_std": round(raw_std, 4),
            "smoothed_std": round(smoothed_std, 4),
            "detail": (
                "raw AII volatile — read aii_smoothed / trend, not single cycles"
                if volatile
                else "raw AII volatility within expected measurement band"
            ),
        }

    n_eps = [int(r.get("n_episodes", 0)) for r in rows]
    if n_eps:
        static_window = len(set(n_eps)) == 1
        checks["episode_growth"] = {
            "status": "WARN" if static_window else "PASS",
            "n_episodes_values": sorted(set(n_eps)),
            "detail": (
                "labelled-episode window size unchanged across the whole "
                "history — verify new episodes are being ingested (the window "
                "caps at ADAPTATION_CYCLE_WINDOW, so a full window is also "
                "consistent with healthy ingestion)"
                if static_window
                else "labelled-episode window is moving"
            ),
        }

    stability = [float(r.get("stability_score", 0.0)) for r in rows]
    if stability:
        flat_floor = max(stability) < 0.15
        checks["stability_liveness"] = {
            "status": "WARN" if flat_floor else "PASS",
            "max_stability": round(max(stability), 4),
            "detail": (
                "stability pinned at the old structural floor — expected to "
                "recover after the v2 formula has 2+ post-deploy cycles"
                if flat_floor
                else "stability component is live"
            ),
        }

    fa = [float(r.get("false_accept_rate", 0.0)) for r in rows]
    checks["safety"] = {
        "status": "PASS" if all(v == 0.0 for v in fa) else "FAIL",
        "max_false_accept_rate": max(fa) if fa else 0.0,
        "detail": "no false accepts in window" if all(v == 0.0 for v in fa)
        else "false accepts present — investigate before tuning anything",
    }

    overall = (
        "FAIL" if any(c["status"] == "FAIL" for c in checks.values())
        else "WARN" if any(c["status"] == "WARN" for c in checks.values())
        else "PASS"
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "aii_raw_latest": raw_aii[-1] if raw_aii else None,
        "aii_smoothed_latest": round(smoothed[-1], 4) if smoothed else None,
        "aii_smoothed_api": data.get("aii_smoothed"),
        "trend": data.get("trend"),
        "interpretation": data.get("interpretation"),
        "ema_alpha": EMA_ALPHA,
        "n_history": len(rows),
        "checks": checks,
    }


def main() -> int:
    worker_url = DEFAULT_WORKER_URL
    if len(sys.argv) > 1:
        worker_url = sys.argv[1]
    try:
        data = fetch_intelligence(worker_url)
    except OSError as exc:
        print(f"FAIL: AROMER worker unreachable: {exc}", file=sys.stderr)
        return 1

    report = analyse(data)

    print("\nAROMER Loop Health")
    print("=" * 50)
    print(f"  overall:        {report['overall']}")
    print(f"  AII raw:        {report['aii_raw_latest']}")
    print(f"  AII smoothed:   {report['aii_smoothed_latest']} "
          f"(api: {report['aii_smoothed_api']})")
    print(f"  trend:          {report['trend']}  [{report['interpretation']}]")
    for name, check in report["checks"].items():
        print(f"  [{check['status']:4}] {name}: {check['detail']}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACT_DIR / "loop_health.json"
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nartifact: {artifact}")

    return 1 if report["overall"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
