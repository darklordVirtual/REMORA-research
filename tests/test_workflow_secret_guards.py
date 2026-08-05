"""Static guard: Cloudflare-dependent workflow steps must guard on secret presence.

This repository has no repo-level Actions secrets configured (verified
2026-08-05: ``gh secret list`` is empty). A workflow step that runs
wrangler/deploy tooling unconditionally therefore fails hard on every
trigger — ``sync-papers-to-r2.yml`` did exactly that on its first-ever
run (2026-08-05) once the paper-PDF commit stopped carrying ``[skip ci]``.
The repo's accepted convention (``codegraph-index.yml``,
``deploy-frontend.yml``) is an explicit, loud presence check that skips
the dependent steps with a visible message instead of failing red or
skipping silently.

Scope (declared, not exhaustive): a static scan asserting that every
workflow file with an UNATTENDED trigger (push/schedule) referencing
``secrets.CLOUDFLARE_API_TOKEN`` also contains a recognizable
presence-guard pattern. ``workflow_dispatch``-only workflows are exempt:
there an operator explicitly requested a run that needs the secret, and
a hard failure IS the loud surface. The scan does not prove the guard is
wired to every dependent step; review owns that.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

SECRET_REF = "secrets.CLOUDFLARE_API_TOKEN"

# Recognized guard idioms:
#  - a check step exporting configured=true/false (codegraph-index.yml)
#  - an expression comparing the secret against '' (deploy-frontend.yml)
GUARD_RE = re.compile(r"configured=(true|false)|CLOUDFLARE_API_TOKEN\s*!=\s*''")


def _has_unattended_trigger(path: Path) -> bool:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML parses the bare key `on:` as boolean True.
    triggers = workflow.get("on") or workflow.get(True) or {}
    if not isinstance(triggers, dict):
        return False
    return "push" in triggers or "schedule" in triggers


def test_cloudflare_workflows_guard_on_secret_presence() -> None:
    unguarded: list[str] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if SECRET_REF not in text:
            continue
        if not _has_unattended_trigger(path):
            continue
        if not GUARD_RE.search(text):
            unguarded.append(path.name)
    assert not unguarded, (
        "Workflows using Cloudflare secrets must check presence explicitly "
        "(loud skip, repo convention) instead of failing hard when the "
        f"secret is absent: {unguarded}"
    )
