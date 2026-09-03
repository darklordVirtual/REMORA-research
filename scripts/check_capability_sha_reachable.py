#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every capability must be bound to a commit a fresh clone can resolve.

`check_capability_freshness.py` asks whether the cited sources changed since
`verified_at_sha`. It cannot ask whether that commit still exists anywhere but
the machine running it. A local clone keeps the objects of a branch that was
rebased or squash-merged, so a binding to a commit that left the repository
passes locally and fails in CI with "is not in this repository".

This gate closes that gap: it fails when a `verified_at_sha` is not an ancestor
of the branch under test. Run it after a rebase and after a squash merge, and
pass `--rebind <sha>` to move the unreachable bindings onto the commit that
replaced them.

It needs full history for the same reason `check_capability_freshness --strict`
does: in a shallow clone every commit below the fetched depth is equally
unreachable, so the gate would refuse correct bindings. It declines to render a
verdict there rather than render a false one, which is why it runs in the
documentation-governance job, the one checked out with `fetch-depth: 0`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REGISTER = Path(__file__).resolve().parents[1] / "docs/assurance/capability_register_v1.yaml"
SHA_PATTERN = re.compile(r"verified_at_sha: ([0-9a-f]{7,40})")


def _is_shallow(root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


def _is_ancestor(sha: str, ref: str, root: Path) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, ref],
            cwd=root,
            capture_output=True,
        ).returncode
        == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--ref",
        default="HEAD",
        help="the commit every binding must be reachable from (default: HEAD)",
    )
    parser.add_argument(
        "--rebind",
        metavar="SHA",
        help="rewrite every unreachable binding onto this commit instead of failing",
    )
    args = parser.parse_args()

    if _is_shallow(args.root):
        print(
            "[SKIP] shallow clone: every commit below the fetched depth is "
            "unreachable here, so this gate cannot tell a stale binding from an "
            "old one. Run it on a checkout with fetch-depth: 0."
        )
        return 0

    register = args.root / "docs/assurance/capability_register_v1.yaml"
    text = register.read_text(encoding="utf-8")
    unreachable = sorted(
        {sha for sha in SHA_PATTERN.findall(text) if not _is_ancestor(sha, args.ref, args.root)}
    )

    if not unreachable:
        print(f"[PASS] every capability binding is reachable from {args.ref}.")
        return 0

    if args.rebind:
        target = subprocess.run(
            ["git", "rev-parse", args.rebind],
            cwd=args.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for sha in unreachable:
            text = text.replace(sha, target)
            text = text.replace(
                f"branch commit {sha[:8]}",
                f"branch commit {sha[:8]} (left the repository; rebound to {target[:7]})",
            )
        register.write_text(text, encoding="utf-8", newline="\n")
        print(f"[OK] rebound {len(unreachable)} binding(s) onto {target[:12]}.")
        return 0

    print(f"[FAIL] {len(unreachable)} capability binding(s) are not reachable from {args.ref}:")
    for sha in unreachable:
        print(f"  - {sha[:12]}")
    print(
        "\nA rebase or a squash merge left these commits behind. Rebind them with:\n"
        f"  python scripts/check_capability_sha_reachable.py --rebind {args.ref}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
