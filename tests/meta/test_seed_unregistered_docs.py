from remora.audit_gates.api import run_docs_gate, Violation

def test_unregistered_documents_fail(sandbox):
    """En uregistrert .md fil i docs/ bryter doc pipeline."""
    new_doc = sandbox / "docs" / "unknown_doc.md"
    new_doc.write_text("# Unknown")

    result = run_docs_gate(sandbox)
    assert not result.passed
    assert result.has(Violation.DOC_UNREGISTERED)
