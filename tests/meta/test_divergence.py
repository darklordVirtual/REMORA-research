from remora.audit_gates.api import run_claim_audit, Violation

def test_number_drift_between_doc_and_artifact(sandbox):
    """Endre ETT siffer i et dokumentert tall; artefaktet er uendret."""
    doc = sandbox / "docs/claim_register.md"
    text = doc.read_text(encoding="utf-8")
    # Find a number to replace. E.g. 88.78% -> 89.78%
    doc.write_text(text.replace("88.78%", "89.78%", 1), encoding="utf-8")

    result = run_claim_audit(sandbox)
    assert result.has(Violation.ARTIFACT_MISMATCH), (
        "Gate sammenligner ikke dokumenterte tall mot artefaktinnhold — "
        "den sjekker bare at lenken eksisterer."
    )


def test_policy_layer_number_drift_is_caught(sandbox):
    """The current-policy number is bound to its own artifact, not a constant."""
    doc = sandbox / "docs/claim_register.md"
    text = doc.read_text(encoding="utf-8")
    assert "31 of 544 accepted at 93.55%" in text
    doc.write_text(text.replace("31 of 544 accepted at 93.55%", "31 of 544 accepted at 96.55%", 1),
                   encoding="utf-8")
    assert run_claim_audit(sandbox).has(Violation.ARTIFACT_MISMATCH)


def test_frozen_round_number_drift_is_caught(sandbox):
    doc = sandbox / "docs/claim_register.md"
    text = doc.read_text(encoding="utf-8")
    doc.write_text(text.replace("has 101 at 96.04%", "has 98 at 96.04%", 1), encoding="utf-8")
    assert run_claim_audit(sandbox).has(Violation.ARTIFACT_MISMATCH)


def test_removed_sentence_is_not_a_silent_pass(sandbox):
    """A binding whose sentence disappeared must fail, not check nothing."""
    doc = sandbox / "docs/claim_register.md"
    text = doc.read_text(encoding="utf-8")
    doc.write_text(text.replace("are 88.78% correct", "are very often correct", 1), encoding="utf-8")
    assert run_claim_audit(sandbox).has(Violation.UNBACKED_CLAIM)
