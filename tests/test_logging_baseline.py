# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #45 gap 7: the logging baseline stops lying.

Two small facts with outsized operational cost: /v1/health reported a
hardcoded ``oracle_count=3`` that was false for every non-default backend,
and the MCP server's process-global ``basicConfig(level=ERROR)`` silenced
every oracle-failure and degradation WARNING the rest of remora emits.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_health_reports_the_observed_swarm_size_not_a_constant(monkeypatch) -> None:
    """None before any engine build, the real count after one.

    Health is a liveness probe: it must answer from observation, never by
    instantiating oracle backends -- and never with a constant.
    """
    from servers import api as api_mod

    monkeypatch.setattr(api_mod, "_LAST_ORACLE_COUNT", None)
    assert api_mod.health().oracle_count is None

    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "mock")
    monkeypatch.setenv("REMORA_ENV", "development")
    engine = api_mod._make_engine()
    assert api_mod.health().oracle_count == len(engine.oracles)


def test_mcp_import_does_not_silence_warnings() -> None:
    """The old basicConfig(ERROR) turned off the operational record for MCP
    deployments. Run in a subprocess because pytest configures logging in
    this process, which would make basicConfig a no-op and the test a lie.
    """
    code = (
        "import logging, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "import servers.mcp_remora\n"
        "level = logging.getLogger().getEffectiveLevel()\n"
        "assert level <= logging.WARNING, f'root at {level}: warnings silenced'\n"
        "print('root level', level)\n"
    ) % ROOT
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "root level 30" in proc.stdout
