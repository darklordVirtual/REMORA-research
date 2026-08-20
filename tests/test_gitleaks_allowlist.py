# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The secret-scanner allowlist stays narrow and stays justified.

A secret scanner that has been widened until it is quiet is not a control.
These tests pin the shape of `.gitleaks.toml`: the default ruleset stays on,
the allowlist stays small, every entry names a specific literal or path rather
than a broad pattern, and each one carries a comment recording what was
verified. Growing the allowlist requires editing this test, which puts the
justification in front of a reviewer.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".gitleaks.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "supply-chain.yml"

# Raising these caps is a deliberate act, not a drive-by edit.
MAX_ALLOWLISTED_PATHS = 4
MAX_ALLOWLISTED_REGEXES = 8

#: An allowlist entry must be anchored to something specific to this
#: repository. A bare value like "dev-token" reads as narrow but suppresses
#: every future finding anywhere that happens to contain the string, which is
#: how a secret scanner gets quietly disarmed. Flagged by the automated
#: security review on 2026-08-20 after exactly that entry was added.
_REQUIRED_ANCHORS: tuple[str, ...] = (
    "REMORA", "remora", "localhost:8000", "friction_thresholds",
    "test-pdp-signing-key",
)


def _config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_default_ruleset_stays_enabled() -> None:
    assert _config()["extend"]["useDefault"] is True, (
        "the default gitleaks rules must stay on; narrow the allowlist instead"
    )


def test_allowlist_stays_small() -> None:
    allowlist = _config()["allowlist"]
    assert len(allowlist["paths"]) <= MAX_ALLOWLISTED_PATHS
    assert len(allowlist["regexes"]) <= MAX_ALLOWLISTED_REGEXES


def test_no_catch_all_entries() -> None:
    """Nothing may allowlist a whole tree or match everything."""
    allowlist = _config()["allowlist"]
    forbidden = {".*", ".+", "", "^.*$"}
    for entry in [*allowlist["paths"], *allowlist["regexes"]]:
        assert entry not in forbidden, f"catch-all allowlist entry: {entry!r}"
        assert len(entry) >= 8, f"suspiciously broad allowlist entry: {entry!r}"
    # Whole source trees are never allowlisted: a finding in code is a finding.
    for path in allowlist["paths"]:
        assert not path.startswith(("remora", "servers", "workers", "scripts")), (
            f"source tree allowlisted wholesale: {path!r}"
        )


def test_regexes_are_matched_against_the_whole_line() -> None:
    """Anchoring only works if the allowlist sees the context.

    gitleaks matches allowlist regexes against the extracted SECRET by
    default, which forces every entry to be a bare value — and a bare value
    suppresses unrelated future findings. regexTarget = "line" is what makes
    the anchoring in the entries above meaningful rather than decorative.
    """
    assert _config()["allowlist"].get("regexTarget") == "line"


def test_every_regex_is_anchored_to_this_repository() -> None:
    """A bare value would suppress unrelated future findings."""
    for entry in _config()["allowlist"]["regexes"]:
        assert any(anchor in entry for anchor in _REQUIRED_ANCHORS), (
            f"allowlist regex {entry!r} is not anchored to a REMORA-specific "
            f"context; it would suppress any future finding containing that "
            f"string. Anchor it to the assignment or the file it appears in."
        )


def test_every_allowlist_entry_is_documented() -> None:
    """Each entry sits under a comment block explaining what was verified."""
    lines = CONFIG.read_text(encoding="utf-8").splitlines()
    entry_lines = [
        i for i, line in enumerate(lines)
        if line.strip().startswith("'''") and line.strip().endswith("''',")
    ]
    assert entry_lines, "no allowlist entries found — did the format change?"
    for i in entry_lines:
        preceding = [ln.strip() for ln in lines[max(0, i - 6):i]]
        assert any(ln.startswith("#") for ln in preceding), (
            f"undocumented allowlist entry on line {i + 1}: {lines[i].strip()}"
        )


def test_gitleaks_action_is_sha_pinned() -> None:
    """The scanner itself must not move under us (this is what broke master)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "gitleaks/gitleaks-action@v2\n" not in text, (
        "gitleaks-action is pinned to a mutable tag; pin the SHA"
    )
    assert "gitleaks/gitleaks-action@" in text
    for line in text.splitlines():
        if "gitleaks/gitleaks-action@" in line:
            ref = line.split("gitleaks/gitleaks-action@", 1)[1].split()[0]
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), (
                f"expected a 40-char commit SHA, got {ref!r}"
            )


def test_workflow_points_at_this_config() -> None:
    assert "GITLEAKS_CONFIG" in WORKFLOW.read_text(encoding="utf-8"), (
        "the workflow must pass GITLEAKS_CONFIG or the allowlist is ignored"
    )
