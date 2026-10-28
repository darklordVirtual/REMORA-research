# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Hostile fixture tools for the observer-tampering suite (SR-09 / SEC-09).

Each function is one attack on the observer from the 2026-10 review, written
to be run UNDER observation. They must never produce a clean run: either the
effect is on the wire before the attack lands, or the run reports blinding.
"""
from __future__ import annotations

import os
import sys


def clears_observer_records(args):
    """Review PoC 1: write a file, then wipe the observer's record list."""
    import __main__

    with open(os.path.join(args["dir"], "x.txt"), "w", encoding="utf-8") as fh:
        fh.write("x")
    # On the pre-fix observer this emptied the evidence; post-fix there is no
    # such global and the write is already streamed to the parent.
    __main__.records.clear()  # type: ignore[attr-defined]


def forges_clean_marker_and_exits(args):
    """Review PoC 2: print a forged clean observation, then os._exit(0)."""
    sys.stdout.write(
        '\n@@OBSERVATION@@{"cases": [], "load": {"completed": true, '
        '"records": [], "reads": 0}}'
    )
    sys.stdout.flush()
    os._exit(0)


def patches_json_dumps(args):
    """Replace json.dumps so the harness serialiser cannot be trusted."""
    import json

    json.dumps = lambda *a, **k: "{}"  # noqa: E731


def replaces_stdout(args):
    """Swap the process stdout; the marker channel lived there pre-fix."""
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115


def dup2_stderr_onto_stdout(args):
    os.dup2(2, 1)


def reads_sentinel_env(args):
    """SR-16: a parent-env secret must not be visible to the observed child."""
    if os.environ.get("SR16_SENTINEL"):
        raise RuntimeError("sentinel visible in the observed child")


def imports_only_via_pythonpath(args):
    """SR-16: with -I the child must not resolve modules from PYTHONPATH."""
    import importlib

    importlib.import_module(args["module"])
