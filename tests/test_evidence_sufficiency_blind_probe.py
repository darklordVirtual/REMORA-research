# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The pre-registered blind probe of evidence-sufficiency v1.4 (NEGATIVE_RESULTS.md §70).

Pins the probe inputs to their pre-registered digests and the published counts
to the committed raw results, and checks the implementation scorer on the
correct controls.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "artifacts" / "evidence-sufficiency-blind-probe-2026-09-30"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result(name: str) -> dict:
    return json.loads(gzip.decompress((PROBE / "results" / name).read_bytes()))


@pytest.mark.docgate
def test_probe_inputs_match_their_pre_registered_digests() -> None:
    for line in (PROBE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name == "./SHA256SUMS":
            continue  # written while the file was being created; it cannot pin itself
        assert hashlib.sha256((PROBE / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.docgate
def test_published_counts_match_the_raw_results() -> None:
    tallies = _result("blind-tallies.json.gz")["tallies"]
    v14 = tallies["evidence-sufficiency-v1.4"]
    assert v14["code_decision"] + v14["impl"] == 83
    assert v14["code_decision_row1"] + v14["impl_row1"] == 76
    assert v14["code_decision_row3"] + v14["impl_row3"] == 80
    assert tallies["evidence-sufficiency-v1.3"] == v14, "v1.4 added no kill on blind faults (§70)"
    assert all(t["controls_clean"] for t in tallies.values())
    faults = _result("blind-faults-result.json.gz")
    assert faults["criterion"]["open_gaps"] == ["FW3-09", "FW3-17", "FW3-19", "FW3-20"]
    impl = _result("blind-impl-result.json.gz")["modules"]
    survivors = sorted(m["module"] for m in impl if m["fault"] and not m["rows"]["evidence-sufficiency-v1.4"]["row3_kill"])
    assert survivors == ["mr2/variant_11.py", "mr3/variant_10.py"]


def test_correct_controls_agree_with_the_model_and_pass_the_runner() -> None:
    probe = _load("probe_for_tests", ROOT / "scripts" / "probe_reimplementations_evidence_sufficiency.py")
    result = probe.score_module(str(PROBE / "mr1" / "correct.py"))
    assert not result["fault"]
    for rows in result["rows"].values():
        assert not (rows["row1_kill"] or rows["row2_kill"] or rows["row3_kill"])


PROBE2 = ROOT / "artifacts" / "evidence-sufficiency-blind-probe-2-2026-09-30"


@pytest.mark.docgate
def test_probe_2_inputs_match_their_digests_and_the_published_counts() -> None:
    for line in (PROBE2 / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((PROBE2 / name).read_bytes()).hexdigest() == digest, name
    tallies = json.loads(gzip.decompress((PROBE2 / "results" / "p2-tallies.json.gz").read_bytes()))["tallies"]
    v14, v15 = tallies["evidence-sufficiency-v1.4"], tallies["evidence-sufficiency-v1.5"]
    decision = v15["code_decision"] + v15["impl"]
    assert decision == 77
    assert (v14["code_decision_row3"] + v14["impl_row3"], v15["code_decision_row3"] + v15["impl_row3"]) == (74, 77)
    assert (v14["code_decision_row1"] + v14["impl_row1"], v15["code_decision_row1"] + v15["impl_row1"]) == (73, 76)
    faults = json.loads(gzip.decompress((PROBE2 / "results" / "p2-faults.json.gz").read_bytes()))
    assert faults["criterion"]["open_gaps"] == ["P2C-20"]
