# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The TLA+ models under formal/tla match their expected verdicts and traces.

Runs scripts/check_tla_models.py when Java is available. Without Java the
check is skipped with that reason: a model that was not checked is not
passing. The structural tests below run everywhere.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TLA = ROOT / "formal" / "tla"
EXPECTED = json.loads((TLA / "expected.json").read_text(encoding="utf-8"))


def test_every_expected_configuration_has_a_cfg_and_every_cfg_is_expected() -> None:
    cfgs = {p.stem for p in TLA.glob("*.cfg")}
    assert cfgs == set(EXPECTED["configs"])
    for name, want in EXPECTED["configs"].items():
        assert want["result"] in ("holds", "violated"), name
        if want["result"] == "violated":
            assert want["invariant"] and want["trace"], name
        assert want["why"].strip(), name


def test_the_model_has_a_control_that_holds_and_a_fix_that_holds() -> None:
    """A model violated everywhere would prove nothing about the fix."""
    results = {n: c["result"] for n, c in EXPECTED["configs"].items()}
    assert results["pinned_reachable"] == "holds"
    assert results["pinned_outage"] == "violated"
    assert results["sticky_all"] == "holds"


def test_the_cp_f4_trace_is_the_one_the_contract_probe_replays() -> None:
    probe = (ROOT / "integrations/federation-port/contract-probes/contract-probes.test.ts").read_text(encoding="utf-8")
    assert "test('CP-F4 " in probe
    probe = probe[probe.index("test('CP-F4 "):]
    probe = probe[:probe.index("\ntest(", 10)]
    assert EXPECTED["configs"]["pinned_outage"]["trace"] == [
        "Send(1)", 'Finish(1,"unknown")', "Claim", 'Finish(2,"failed_retriable")', "Tick", "Claim"]
    # The probe replays the trace's steps in order (lost response, outage, retry, deadline,
    # claim). Since the upstream fix the claim past the deadline ends in reconciliation, not closure.
    order = [probe.index(s) for s in ("drop_after_commit", "provider.close()", "const retry",
                                       "valid_until", "reconciliation_required")]
    assert order == sorted(order)


def test_the_tlc_jar_is_pinned() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", EXPECTED["tlc"]["sha256"])
    assert EXPECTED["tlc"]["url"].startswith("https://github.com/tlaplus/tlaplus/releases/download/")


@pytest.mark.skipif(shutil.which("java") is None, reason="java not found: TLA+ models NOT checked")
def test_tlc_reproduces_every_expected_verdict_and_trace() -> None:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/check_tla_models.py")],
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode == 2:
        pytest.skip("BLOCKED: " + proc.stdout.strip()[-300:])
    assert proc.returncode == 0, proc.stdout + proc.stderr
