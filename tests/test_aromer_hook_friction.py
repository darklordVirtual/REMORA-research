# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The hook-friction summary counts what the rows say and refuses the wrong file."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.aromer_hook_friction import main, summarize  # noqa: E402


def _row(verdict, tool="Read", action="read", tier="low", truth="benign", p_harm=0.05, source="claude_code_pretooluse"):
    return {"verdict": verdict, "action_type": action, "risk_tier": tier, "domain": "system",
            "ground_truth": truth, "meta": {"source": source, "tool": tool, "p_harm": p_harm}}


ROWS = [
    _row("ACCEPT"), _row("ACCEPT", tool="Bash", action="execution"),
    _row("VERIFY", tool="Bash", action="execution", tier="medium", p_harm=0.4),
    _row("ESCALATE", tool="Write", action="write", tier="high", truth="unknown", p_harm=0.9),
    _row("ACCEPT", source="decide_endpoint"),  # not a hook episode: excluded
    {"verdict": "ACCEPT", "meta": None, "ground_truth": "harmful"},  # no meta: excluded
]


def test_summary_counts_only_hook_episodes_and_keeps_denominators():
    s = summarize(ROWS)
    assert s["hook_episodes"] == 4
    assert s["verdicts"] == {"ACCEPT": 2, "ESCALATE": 1, "VERIFY": 1}
    assert s["review_required"] == {"count": 2, "denominator": 4, "rate": 0.5}
    assert s["ground_truth"] == {"benign": 3, "unknown": 1}
    assert s["by_tool"]["Bash"] == {"ACCEPT": 1, "VERIFY": 1}
    assert s["by_action_type"]["write"] == {"ESCALATE": 1}
    assert s["by_risk_tier"]["low"] == {"ACCEPT": 2}
    assert s["p_harm"]["n"] == 4 and s["p_harm"]["max"] == 0.9 and s["p_harm"]["min"] == 0.05


def test_summary_is_deterministic_and_handles_no_rows():
    assert summarize(ROWS) == summarize(list(ROWS))
    empty = summarize([])
    assert empty["hook_episodes"] == 0 and empty["review_required"]["rate"] is None


def test_main_refuses_an_input_whose_hash_is_not_pinned(tmp_path):
    episodes = tmp_path / "episodes_public.jsonl"
    episodes.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n")
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"public_episode_file": {"sha256": "0" * 64, "rows": len(ROWS)}}))
    out = tmp_path / "out.json"
    assert main([str(episodes), "--export", str(export), "--out", str(out)]) == 2
    assert not out.exists()


def test_main_writes_the_artifact_for_the_pinned_input(tmp_path):
    episodes = tmp_path / "episodes_public.jsonl"
    episodes.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n")
    digest = hashlib.sha256(episodes.read_bytes()).hexdigest()
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"public_episode_file": {"sha256": digest, "rows": len(ROWS)}}))
    out = tmp_path / "out.json"
    assert main([str(episodes), "--export", str(export), "--out", str(out)]) == 0
    written = json.loads(out.read_text())
    assert written["schema"] == "aromer_hook_episode_friction_v1"
    assert written["input"]["sha256"] == digest
    assert written["summary"]["hook_episodes"] == 4
    assert len(written["caveats"]) == 3
