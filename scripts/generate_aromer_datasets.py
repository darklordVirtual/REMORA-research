#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Generate AROMER train/holdout episode datasets.

Outputs:
  artifacts/aromer_train_episodes.jsonl    — 18 seed episodes (can_train=True)
  artifacts/aromer_holdout_episodes.jsonl  — 65 arena cases as episodes (can_train=False)

Distribution of holdout: 61.5% benign, 38.5% harmful (matches arena composition).
"""
import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_seeds() -> list[dict]:
    seeds_dir = ROOT / "remora/aromer/seeds"
    episodes = []
    for f in sorted(seeds_dir.glob("*.seed.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    ep = json.loads(line)
                    ep["source"] = "seed"
                    ep["label_source"] = "synthetic"
                    ep["label_confidence"] = 0.90
                    ep["synthetic"] = True
                    ep["can_train"] = True
                    ep["can_publish_metric"] = True
                    episodes.append(ep)
                except json.JSONDecodeError:
                    pass
    return episodes


def load_arena_as_episodes() -> list[dict]:
    arena_dir = ROOT / "remora/aromer/evals/replay_arena"
    episodes = []
    for f in sorted(arena_dir.glob("*.jsonl")):
        if f.name == "index.json":
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    case = json.loads(line)
                    ep = {
                        "id": case["id"],
                        "domain": case.get("domain", "unknown"),
                        "risk_tier": case.get("risk_tier", "medium"),
                        "action_type": case.get("action_type", "execution"),
                        "phase": case.get("phase", "critical"),
                        "trust_score": case.get("trust_score", 0.5),
                        "entropy_H": case.get("final_H", 0.5),
                        "dissensus_D": case.get("final_D", 0.5),
                        "verdict": case.get("expected_verdict", "VERIFY"),
                        "ground_truth": case.get("expected_truth", "unknown"),
                        "category": case.get("category", "unknown"),
                        "question": case.get("question", ""),
                        "source": "replay",
                        "label_source": "replay_truth",
                        "label_confidence": 1.0,
                        "synthetic": True,
                        "can_train": False,   # HOLDOUT — AROMER must not adapt from these
                        "can_publish_metric": True,
                        "tags": case.get("tags", []),
                    }
                    episodes.append(ep)
                except (json.JSONDecodeError, KeyError):
                    pass
    return episodes


def main():
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    train = load_seeds()
    holdout = load_arena_as_episodes()

    train_path = artifacts / "aromer_train_episodes.jsonl"
    holdout_path = artifacts / "aromer_holdout_episodes.jsonl"

    train_path.write_text(
        "\n".join(json.dumps(ep, ensure_ascii=False) for ep in train),
        encoding="utf-8"
    )
    holdout_path.write_text(
        "\n".join(json.dumps(ep, ensure_ascii=False) for ep in holdout),
        encoding="utf-8"
    )

    # Print summary
    harmful_holdout = sum(1 for ep in holdout if ep["ground_truth"] == "harmful")
    benign_holdout = sum(1 for ep in holdout if ep["ground_truth"] == "benign")
    print(f"Train: {len(train)} episodes (source=seed)")
    print(f"Holdout: {len(holdout)} episodes (can_train=False)")
    print(f"  harmful: {harmful_holdout}, benign: {benign_holdout}")


if __name__ == "__main__":
    main()
