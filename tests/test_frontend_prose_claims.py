"""Bind frontend prose surfaces to the claim register's quoting rules.

tests/test_frontend_benchmark_snapshot.py binds benchmark-snapshot.json to
result artifacts, but the hostile review (P1-12) found violations in the
surfaces it does NOT cover: hardcoded strings in routes/ and content/.
These tests pin those surfaces to the register's rules:

- CLAIM-004: "do not cite 88.0% without the CI" — the Wilson CI must
  accompany the held-out accuracy wherever it is quoted.
- CLAIM-008: 94.7% is at 25% *coverage* (a calibration-set upper bound),
  not "25% abstain"; 82.8% is the majority-vote *baseline*, not a REMORA
  result.
- The audit layer is a SHA-256 hash chain; no RDF graph or OpenTelemetry
  integration exists in remora/ and the frontend must not claim one.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def _read(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


def test_heldout_accuracy_carries_wilson_ci() -> None:
    src = _read("routes/index.tsx")
    block = src.split('stat: "88%"', 1)[1].split("},", 1)[0]
    assert "70.0%" in block and "95.8%" in block, (
        "CLAIM-004 quoting rule: 88% must not appear without its Wilson CI"
    )


def test_trust_curve_operating_point_not_inverted() -> None:
    src = _read("routes/cascade.tsx")
    assert "25% abstain" not in src, (
        "CLAIM-008 is 94.7% at 25% COVERAGE (~75% abstained); '25% abstain' inverts it"
    )
    line = next(ln for ln in src.splitlines() if "94.7%" in ln)
    assert "coverage" in line
    assert "calibration-set" in line, "register caveat: calibration-set upper bound"


def test_baseline_not_presented_as_remora_result() -> None:
    src = _read("routes/cascade.tsx")
    for line in src.splitlines():
        if "82.8%" in line:
            assert "baseline" in line, (
                "82.78% is the majority-vote baseline (CLAIM-008 caveat); "
                "it must be labeled as such"
            )


def test_no_fictional_audit_stack() -> None:
    for rel in ("content/whitepaper.ts", "routes/index.tsx", "routes/cascade.tsx"):
        src = _read(rel)
        assert "RDF" not in src, f"{rel}: audit layer is a SHA-256 hash chain, not RDF"
        assert "OTel" not in src and "OpenTelemetry" not in src, (
            f"{rel}: no OpenTelemetry integration exists in remora/"
        )


def test_no_stale_pdf_as_number_source() -> None:
    """Download links to the hosted PDF are fine; citing the PDF as the
    provenance of displayed numbers is not (it is a stale snapshot —
    docs/02-evidence-and-claims.md)."""
    src = _read("routes/index.tsx")
    comment_lines = [ln for ln in src.splitlines() if ln.lstrip().startswith("//")]
    for line in comment_lines:
        assert "remora_paper.pdf" not in line, (
            "number-provenance comments must cite remora_paper.md, not the stale PDF"
        )


def test_capabilities_list_names_exist_in_repo() -> None:
    """Every capability named 'Integrated' must correspond to something real."""
    src = _read("content/whitepaper.ts")
    integrated = re.findall(r'\{ name: "([^"]+)",[^}]*status: "Integrated" \}', src)
    known = {
        "FastGate": "remora/cascade",
        "OracleDiversityTracker": "remora/oracles/diversity.py",
        "PolicyGate": "remora/policy/opa_adapter.py",
        "PreToolUse Hook": "remora/agent_hook",
        "Audit chain": "remora/audit/hash_chain.py",
    }
    for name in integrated:
        assert name in known, f"unknown 'Integrated' capability in frontend: {name}"
        assert (ROOT / known[name]).exists(), (
            f"'{name}' marked Integrated but {known[name]} does not exist"
        )
