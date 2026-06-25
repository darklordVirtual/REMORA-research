from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from remora.agent_hook import IntentAnchor, LyapunovTracker, RiskLevel, assess_tool_call
from scripts.remora_hook import build_claim


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "scripts" / "remora_hook.py"


def _run_hook(payload: dict, session_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("AGENT_CONTROL_SECRET", None)
    env["REMORA_SESSION_DIR"] = str(session_dir)
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=20,
        check=False,
    )


def test_risk_classifier_marks_read_only_as_low() -> None:
    assessment = assess_tool_call("Read", {"file_path": "README.md"})
    assert assessment.risk == RiskLevel.LOW
    assert assessment.local_block is False


def test_risk_classifier_local_blocks_destructive_shell() -> None:
    assessment = assess_tool_call("Bash", {"command": "rm -rf /tmp/remora-danger"})
    assert assessment.risk == RiskLevel.HIGH
    assert assessment.local_block is True
    assert assessment.category == "shell_destructive"


@pytest.mark.parametrize(
    "command",
    [
        "printf 'cm0gLXJmIC8=' | base64 -d | bash",
        "bash -c \"r''m -r''f /tmp/remora-danger\"",
        "sh -c 'r\\m -r\\f /tmp/remora-danger'",
    ],
)
def test_risk_classifier_local_blocks_obfuscated_destructive_shell(command: str) -> None:
    assessment = assess_tool_call("Bash", {"command": command})
    assert assessment.risk == RiskLevel.HIGH
    assert assessment.local_block is True
    assert assessment.category in {"shell_destructive", "shell_obfuscated"}


def test_intent_anchor_persists_and_scores_drift(tmp_path: Path) -> None:
    anchor = IntentAnchor(session_dir=tmp_path)
    anchor.anchor("Update documentation and keep benchmark claims factual")

    same_goal = anchor.drift_score("Edit docs README benchmark claims")
    different_goal = anchor.drift_score("Deploy production worker and rotate secrets")

    assert IntentAnchor(session_dir=tmp_path).intent == anchor.intent
    assert same_goal < different_goal
    assert 0.0 <= same_goal <= 1.0
    assert 0.0 <= different_goal <= 1.0


def test_lyapunov_tracker_records_local_state(tmp_path: Path) -> None:
    tracker = LyapunovTracker(session_dir=tmp_path)
    abort, reason = tracker.record("Read", "VERIFIED", 0.95, drift_score=0.0)

    assert abort is False
    assert reason == "warming_up"
    assert (tmp_path / "lyapunov.json").exists()
    assert tracker.summary()["tool_calls"] == 1


def test_build_claim_for_file_write_is_reviewable() -> None:
    claim, context = build_claim("Write", {"file_path": "docs/example.md", "content": "hello"})
    assert "docs/example.md" in claim
    assert "hello" in context


def test_hook_allows_low_risk_read_and_records_state(tmp_path: Path) -> None:
    result = _run_hook(
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        session_dir=tmp_path,
    )

    assert result.returncode == 0
    assert (tmp_path / "lyapunov.json").exists()


def test_hook_blocks_locally_destructive_shell_without_remote(tmp_path: Path) -> None:
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/remora-danger"}},
        session_dir=tmp_path,
    )

    assert result.returncode == 2
    assert "local deterministic safety rule" in result.stderr


def test_hook_blocks_large_intent_drift(tmp_path: Path) -> None:
    IntentAnchor(session_dir=tmp_path).anchor("Edit documentation for README clarity")
    env = os.environ.copy()
    env.pop("AGENT_CONTROL_SECRET", None)
    env["REMORA_SESSION_DIR"] = str(tmp_path)
    env["REMORA_HOOK_DRIFT_BLOCK_THRESHOLD"] = "0.50"

    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(
            {
                "tool_name": "WebSearch",
                "tool_input": {"query": "rotate production credentials and deploy worker"},
            }
        ),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "semantic drift" in result.stderr


def test_risk_classifier_gh_cli_is_medium_not_blocked() -> None:
    """Safe gh subcommands must be classified MEDIUM without triggering the
    obfuscation detector, even when the body contains heredocs or structured text."""
    cases = [
        "gh pr create --title 'fix: something' --body-file body.md",
        'gh pr create --title "fix" --body "$(cat <<\'EOF\'\n## Summary\nBash hook fix\nEOF\n)"',
        "gh pr list --state open",
        "gh pr merge 42 --squash",
        "gh issue create --title 'Bug' --body 'Steps to reproduce'",
        "gh release create v1.0.0 --notes 'Initial release'",
    ]
    for cmd in cases:
        assessment = assess_tool_call("Bash", {"command": cmd})
        assert assessment.risk == RiskLevel.MEDIUM, (
            f"Expected MEDIUM for gh command, got {assessment.risk}: {cmd!r}"
        )
        assert assessment.local_block is False, f"gh command must not be locally blocked: {cmd!r}"


def test_risk_classifier_gh_cli_chaining_is_blocked() -> None:
    """gh commands that chain additional shell commands via ;, &&, or || must NOT
    be trusted — they could inject a payload after the trusted gh prefix."""
    attack_cases = [
        "gh pr create --title x; rm -rf /important",    # semicolon chaining
        "gh pr create --title x && cat /etc/passwd",    # and-and chaining
        "gh issue create --body text || curl evil.com", # or-or chaining
        "gh pr create --body content | bash",           # pipe at shell level
        "gh pr create --body `malicious_cmd`",          # backtick subshell
    ]
    for cmd in attack_cases:
        assessment = assess_tool_call("Bash", {"command": cmd})
        # Must be HIGH risk or locally blocked — never MEDIUM or LOW
        assert assessment.risk in {RiskLevel.HIGH} or assessment.local_block, (
            f"Attack vector must not be MEDIUM/LOW: {cmd!r} → {assessment.risk}"
        )


def test_risk_classifier_trusted_remora_domains_are_low_risk() -> None:
    """Calls to REMORA's own Cloudflare workers must fast-path as LOW — no oracle needed."""
    for url in [
        "https://go-star-remora.razorsharp.workers.dev/status",
        "https://remora-rag-oracle.razorsharp.workers.dev/status",
        "https://remora-law-search.razorsharp.workers.dev/status",
        "https://remora-agent-control.razorsharp.workers.dev/status",
        "https://aromer.razorsharp.workers.dev/intelligence",
        "https://razorsharp.workers.dev/",
        "http://razorsharp.workers.dev/status",
    ]:
        assessment = assess_tool_call("WebFetch", {"url": url})
        assert assessment.risk == RiskLevel.LOW, f"Expected LOW for {url}, got {assessment.risk}"
        assert assessment.local_block is False
        assert assessment.category == "network_trusted"


def test_risk_classifier_external_webfetch_remains_medium() -> None:
    """Non-REMORA URLs must stay MEDIUM so the oracle still validates them."""
    for url in [
        "https://example.com/api",
        "https://github.com/some/repo",
        "https://api.openai.com/v1/models",
        # Bypass attempts — must NOT be LOW risk
        "https://evil.com/?x=razorsharp.workers.dev",
        "https://evil.com/path/razorsharp.workers.dev",
        "https://razorsharp.workers.dev.evil.com/",
        "https://notrazorsharp.workers.dev/",
        "https://evil.com#razorsharp.workers.dev",
        "https://user:razorsharp.workers.dev@evil.com/",
    ]:
        assessment = assess_tool_call("WebFetch", {"url": url})
        assert assessment.risk == RiskLevel.MEDIUM, (
            f"Expected MEDIUM for bypass URL {url!r}, got {assessment.risk} — allowlist bypass!"
        )


def test_hook_allows_remora_worker_webfetch_without_oracle(tmp_path: Path) -> None:
    """Hook must exit 0 (allow) for WebFetch to REMORA workers without calling the oracle."""
    result = _run_hook(
        {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://go-star-remora.razorsharp.workers.dev/status"},
        },
        session_dir=tmp_path,
    )
    assert result.returncode == 0, f"Hook blocked a trusted REMORA URL: {result.stderr}"
