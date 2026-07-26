from remora.audit_gates.api import run_claim_audit, Violation

def test_number_drift_between_doc_and_artifact(sandbox):
    """Endre ETT siffer i et dokumentert tall; artefaktet er uendret."""
    doc = sandbox / "docs/claim_register.md"
    text = doc.read_text()
    # Find a number to replace. E.g. 88.78% -> 89.78%
    doc.write_text(text.replace("88.78%", "89.78%", 1))

    result = run_claim_audit(sandbox)
    assert result.has(Violation.ARTIFACT_MISMATCH), (
        "Gate sammenligner ikke dokumenterte tall mot artefaktinnhold — "
        "den sjekker bare at lenken eksisterer."
    )
