"""The reachability gate must fail on a binding that left the repository.

The freshness gate cannot see this class of defect: a local clone still holds
the objects of a rebased or squash-merged branch, so a stale binding passes on
the machine that made it and fails only in CI's fresh clone.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_capability_sha_reachable.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def _is_shallow() -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=REPO,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "true"
    )


def test_the_committed_register_is_reachable_from_head() -> None:
    """On full history this is a real assertion; on a shallow clone it is not.

    Most CI jobs check out shallow, where every commit below the fetched depth
    is unreachable and the gate declines to answer. The gate says so, and this
    asserts it exits cleanly either way rather than reporting a false stale
    binding.
    """

    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    expected = "[SKIP]" if _is_shallow() else "[PASS]"
    assert expected in result.stdout, result.stdout


def test_an_unreachable_binding_fails(tmp_path: Path) -> None:
    """A binding to a commit that is not an ancestor of the ref is refused."""

    root = tmp_path / "repo"
    (root / "docs" / "assurance").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    register = root / "docs" / "assurance" / "capability_register_v1.yaml"
    register.write_text("capabilities: []\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)

    # A commit that is real but on a branch the ref cannot reach.
    subprocess.run(["git", "checkout", "-qb", "side"], cwd=root, check=True)
    (root / "other.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "side"], cwd=root, check=True)
    orphan = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "-"], cwd=root, check=True)

    register.write_text(f"    verified_at_sha: {orphan}\n", encoding="utf-8")
    result = _run("--root", str(root))
    assert result.returncode == 1, result.stdout
    assert orphan[:12] in result.stdout

    rebound = _run("--root", str(root), "--rebind", "HEAD")
    assert rebound.returncode == 0, rebound.stdout
    assert orphan not in register.read_text(encoding="utf-8")
