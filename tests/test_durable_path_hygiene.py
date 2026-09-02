# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""No test may hardcode a /tmp path into a durable-state variable.

An external review (2026-08-30, F2) found four tests failing on a reviewer's
machine and passing in CI. They set ``REMORA_CHAIN_DB=/tmp/remora-chain.db``,
and the production durability guard correctly refuses tmpfs: /tmp is memory on
many Linux installs and disk on the GitHub runners. The guard was right and
the tests were environment-dependent.

CI cannot catch a recurrence, because /tmp is durable where CI runs. That is
the whole reason this file exists rather than a workflow step: the defect is
invisible from the only place the suite normally runs, and
``docs/06-reproducibility.md`` claims the suite reproduces on a foreign
machine.

Only the variables the durability guard actually inspects are covered.
Unrelated /tmp literals -- a payload string, a prior path that is never
probed -- are not this file's business and are left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: The variables servers/api.py resolves to a filesystem path and probes for
#: durability before allowing production to start.
DURABLE_PATH_VARS = ("REMORA_CHAIN_DB", "REMORA_CONTROL_PLANE_DB")

_PATTERN = re.compile(
    r"""["'](?P<var>%s)["']\s*,\s*["']/tmp/""" % "|".join(DURABLE_PATH_VARS)
)


def test_no_test_points_a_durable_state_variable_at_tmp():
    offenders = []
    for path in sorted(TESTS.rglob("test_*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            if _PATTERN.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()[:70]}")
    assert offenders == [], (
        "a durable-state variable is pointed at /tmp, which the production "
        "guard refuses wherever /tmp is tmpfs. Use the tmp_path fixture and "
        "stub servers.api.filesystem_type_for, or use a DSN:\n"
        + "\n".join(offenders)
    )
