# Author: Stian Skogbrott
# License: Apache-2.0
"""Central resolution of AROMER on-disk state paths (F-10 completion).

Every default is resolved at CALL time, never at module import, and every
component honours ``REMORA_AROMER_HOME`` so a locked-down or read-only home
directory can redirect all AROMER state (episodic store, world model, bridge
state, promotion ledger, friction optimizer) with one variable.

External review 2026-07-25: the first F-10 fix covered only the episodic
store and adapter bridge; DomainHarmPrior, the seed loader, the promotion
ledger, and the friction optimizer still hard-coded ``Path.home()/.aromer``,
which broke the quickstart in read-only-home runtimes.
"""
from __future__ import annotations

import os
from pathlib import Path


def aromer_home() -> Path:
    """The AROMER state directory: ``$REMORA_AROMER_HOME`` or ``~/.aromer``."""
    override = os.environ.get("REMORA_AROMER_HOME", "").strip()
    return Path(override) if override else Path.home() / ".aromer"


def default_state_path(filename: str) -> Path:
    """Default path for one AROMER state file, resolved at call time."""
    return aromer_home() / filename
