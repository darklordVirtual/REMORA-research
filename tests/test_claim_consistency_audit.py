from __future__ import annotations

from experiments.claim_consistency_audit import run_audit


def test_claim_consistency_audit_passes() -> None:
    audit = run_audit()
    assert audit["all_passed"], audit
    assert audit["checks"], "expected at least one consistency check"
