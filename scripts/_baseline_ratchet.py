# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Compare a committed baseline against the one on ``origin/master``.

A ratchet that reads a baseline out of the working tree is not a ratchet:
the same pull request that raises a count can raise the baseline in the
same commit, and the gate reports success. Three gates in this repository
had that shape (prose style, pip-audit, coverage floors).

The fix is to read the baseline the pull request is measured against from
``origin/master`` rather than from the branch. Locally, where
``origin/master`` may be absent or stale, the comparison is skipped and the
skip is printed, because a silent skip is the same failure in a new place.

CI is identified by ``GITHUB_EVENT_NAME``. That is also what makes the
bootstrap escape hatch refusable on a pull request or a push, where it must
never be reachable.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: Events during which a baseline must come from origin/master, and during
#: which a bootstrap escape hatch is refused.
GATED_EVENTS = {"pull_request", "pull_request_target", "push", "merge_group"}

BASE_REF = "origin/master"


def is_gated_ci() -> bool:
    """True when this run is a CI event that must not trust the branch."""
    return os.environ.get("GITHUB_EVENT_NAME", "") in GATED_EVENTS


def base_blob(rel_path: str, root: Path) -> str | None:
    """``git show origin/master:<rel_path>``, or None if unavailable.

    None means "could not compare", never "nothing to compare against":
    callers print the skip rather than passing quietly.
    """
    blob = _show(rel_path, root, (BASE_REF,))
    if blob is not None:
        return blob
    # A shallow or single-branch checkout has no origin/master yet. One
    # fetch is cheap and turns a skipped comparison into a real one.
    try:
        subprocess.run(
            ["git", "fetch", "--no-tags", "--depth=1", "origin", "master"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _show(rel_path, root, (BASE_REF, "FETCH_HEAD"))


def _show(rel_path: str, root: Path, refs: tuple[str, ...]) -> str | None:
    for ref in refs:
        try:
            proc = subprocess.run(
                ["git", "show", f"{ref}:{rel_path}"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if proc.returncode == 0:
            return proc.stdout
    return None


def skip_note(rel_path: str) -> str:
    return (
        f"[NOTE] {BASE_REF}:{rel_path} is not available, so the baseline was "
        f"read from the working tree and the against-{BASE_REF} comparison "
        "was SKIPPED. In CI this is a failure; locally, fetch origin to "
        "reproduce what CI checks."
    )
