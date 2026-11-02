"""Guard dev/master CI parity, promotion source and no dev production writes."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

FULL_CHECKS = (
    "ci.yml",
    "quality-gates.yml",
    "codeql.yml",
    "supply-chain.yml",
    "shadow-replay-smoke.yml",
    "docs-site.yml",
)
PATH_SCOPED_CHECKS = (
    "aps-interop.yml",
    "federation-interop.yml",
    "probity-boundary-reproduction.yml",
    "probity-e7-reproduction.yml",
    "probity-invocation-axes-reproduction.yml",
    "pre-federation-redteam.yml",
)
WRITE_WORKFLOWS = (
    "deploy-aromer-worker.yml",
    "deploy-frontend.yml",
    "codegraph-index.yml",
    "compile-paper.yml",
    "osf-sync.yml",
    "sync-papers-to-r2.yml",
)

def _workflow(filename: str) -> dict:
    # BaseLoader preserves the GitHub Actions 'on' mapping as a string.
    data = yaml.load((WORKFLOWS / filename).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(data, dict), filename
    return data


@pytest.mark.parametrize("filename", FULL_CHECKS + PATH_SCOPED_CHECKS)
def test_dev_and_master_push_run_identical_validation(filename: str) -> None:
    config = _workflow(filename)
    branches = config["on"]["push"]["branches"]
    assert "dev" in branches and "master" in branches, filename


def test_dev_push_runs_full_python_matrix_and_promotion_pr_is_full() -> None:
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "github.event_name == 'pull_request' && github.base_ref != 'master'" in workflow
    assert "['3.11', '3.12', '3.13', '3.14']" not in workflow  # JSON expression uses double quotes.
    assert '"3.11", "3.12", "3.13", "3.14"' in workflow
    assert 'SOURCE_BRANCH: ${{ github.event.pull_request.head.ref }}' in workflow
    assert 'SOURCE_REPO: ${{ github.event.pull_request.head.repo.full_name }}' in workflow
    assert 'SOURCE_REPO" != "$TARGET_REPO' in workflow


def test_dev_branch_is_never_pruned_by_branch_hygiene() -> None:
    workflow = (WORKFLOWS / "branch-hygiene.yml").read_text(encoding="utf-8")
    assert '"$branch" == "dev"' in workflow


@pytest.mark.parametrize("filename", WRITE_WORKFLOWS)
def test_production_side_effect_workflows_not_triggered_by_dev(filename: str) -> None:
    config = _workflow(filename)
    branches = config.get("on", {}).get("push", {}).get("branches", [])
    assert "dev" not in branches, filename


def test_docs_publish_still_master_only() -> None:
    workflow = (WORKFLOWS / "docs-site.yml").read_text(encoding="utf-8")
    assert "github.ref == 'refs/heads/master' && vars.PUBLISH_DOCS == 'true'" in workflow
    assert 'if: github.ref == \'refs/heads/master\'' in workflow
