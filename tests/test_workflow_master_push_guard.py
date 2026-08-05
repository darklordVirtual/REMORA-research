"""Static guard: no GitHub workflow may push commits directly to master.

Master is a protected branch (PRs only, required checks). A workflow step
that pushes to ``refs/heads/master`` is rejected with GH006 at runtime and
reds the job — ``compile-paper.yml`` did exactly that on 2026-08-05 when its
``git-auto-commit-action`` step tried to commit the compiled PDF to master.

Scope (declared, not exhaustive): this is a static scan over two known
push mechanisms in workflow YAML — ``stefanzweifel/git-auto-commit-action``
steps that can run on master without redirecting to another branch, and
``run:`` scripts containing an explicit ``git push`` to master. A novel push
mechanism outside these patterns is not detected here; branch protection
remains the runtime backstop.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

AUTO_COMMIT_ACTION = "stefanzweifel/git-auto-commit-action"

# git push variants that target master explicitly.
PUSH_TO_MASTER = re.compile(r"git\s+push\b[^\n]*\b(origin\s+master|HEAD:master)\b")


def _iter_steps(workflow: dict):
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            yield job_name, step


def _runs_on_master_push(workflow: dict) -> bool:
    # PyYAML parses the bare key `on:` as boolean True.
    triggers = workflow.get("on") or workflow.get(True) or {}
    if not isinstance(triggers, dict):
        return False
    push = triggers.get("push")
    if push is None:
        return False
    branches = (push or {}).get("branches")
    return branches is None or "master" in branches


def test_no_workflow_pushes_directly_to_master() -> None:
    offenders: list[str] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        master_push_workflow = _runs_on_master_push(workflow)
        for job_name, step in _iter_steps(workflow):
            uses = step.get("uses", "")
            if uses.startswith(AUTO_COMMIT_ACTION):
                branch = (step.get("with") or {}).get("branch", "")
                condition = str(step.get("if", ""))
                targets_master = branch in ("", "master") and (
                    "refs/heads/master" in condition
                    or (master_push_workflow and not condition)
                )
                if targets_master:
                    offenders.append(
                        f"{path.name}:{job_name}: {AUTO_COMMIT_ACTION} commits to master"
                    )
            script = step.get("run") or ""
            if PUSH_TO_MASTER.search(script):
                offenders.append(
                    f"{path.name}:{job_name}: run-step pushes to master explicitly"
                )
    assert not offenders, (
        "Workflows must ship changes to master via a pull request, never a "
        "direct push (branch protection rejects it with GH006): "
        + "; ".join(offenders)
    )
