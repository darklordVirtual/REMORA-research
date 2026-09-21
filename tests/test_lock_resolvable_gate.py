"""Unit tests for the lock-resolvability gate's offline parts.

The gate itself (``scripts/check_lock_resolvable.py``) needs network access and
a real resolver, so it runs in CI rather than in this suite. What is tested
here is everything around that call: the constraints filter must drop exactly
the lines pip rejects, the declared extra sets must stay in step with the
workflows that install them, and pip's conflict explanation must survive into
the failure message -- a gate that reports "resolution failed" without naming
the two pins that collided costs a debugging round each time it fires.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.check_lock_resolvable import (
    _conflict_reason,
    _constraint_lines,
    declared_extra_sets,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# The exact pip output that reddened the NLI parity run on 2026-09-21.
PIP_CONFLICT_OUTPUT = """\
INFO: pip is looking at multiple versions of huggingface-hub.
ERROR: Cannot install sentence-transformers because these package versions have conflicting dependencies.

The conflict is caused by:
    huggingface-hub 1.28.0 depends on click<9.0.0 and >=8.4.2
    The user requested (constraint) click==8.1.8

To fix this you could try to:
1. loosen the range of package versions you've specified
"""


def test_constraint_filter_drops_what_pip_rejects() -> None:
    lock = "\n".join(
        [
            "# a comment",
            "click==8.4.2",
            "-e .",
            "",
            "torch @ file:///wheels/torch.whl",
            "   numpy==2.4.6   ",
        ]
    )
    assert _constraint_lines(lock) == ["click==8.4.2", "numpy==2.4.6"]


def test_conflict_reason_names_both_sides_of_the_collision() -> None:
    reason = _conflict_reason(PIP_CONFLICT_OUTPUT)
    assert "huggingface-hub 1.28.0 depends on click<9.0.0 and >=8.4.2" in reason
    assert "click==8.1.8" in reason
    assert "To fix this" not in reason


def test_conflict_reason_falls_back_to_the_error_line() -> None:
    assert _conflict_reason("ERROR: No matching distribution found for torch==2.13.0").startswith(
        "ERROR:"
    )


def test_conflict_reason_never_returns_empty() -> None:
    assert _conflict_reason("some unstructured pip noise")


@pytest.mark.parametrize(
    "extras",
    sorted(
        {
            match.group(1)
            for path in WORKFLOWS_DIR.glob("*.yml")
            for match in re.finditer(
                r'pip install[^\n]*-e "\.\[([^]]+)\]"[^\n]*-c ',
                path.read_text(encoding="utf-8"),
            )
        }
    ),
)
def test_every_constrained_workflow_install_set_is_declared(extras: str) -> None:
    """A set CI installs under the lock but the gate never resolves is an untested pin set."""
    assert frozenset(extras.split(",")) in declared_extra_sets(), (
        f'a workflow installs ".[{extras}]" with requirements-lock.txt as constraints, but '
        "EXTRA_SETS in scripts/check_lock_resolvable.py declares no set with those extras, "
        "so the gate would never resolve that combination."
    )
