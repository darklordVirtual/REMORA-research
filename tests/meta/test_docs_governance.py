from remora.audit_gates.api import run_docs_gate, Violation
import yaml

def test_doc_uniqueness_fails(sandbox):
    """Register to filer med samme 'topic' for canonical: feiler."""
    reg_path = sandbox / "docs/assurance/document_register_v1.yaml"
    reg = yaml.safe_load(reg_path.read_text())
    
    # duplicate topic
    reg["documents"].append({
        "path": "docs/02-another.md",
        "status": "canonical",
        "topic": "architecture" # same as first one
    })
    
    reg_path.write_text(yaml.safe_dump(reg))
    
    result = run_docs_gate(sandbox)
    assert not result.passed
    assert result.has(Violation.DOC_DUPLICATE_TOPIC)

def test_historical_reference_fails(sandbox):
    """En markdown fil refererer til whitepaper.md som er historical (referencing_allowed: false)."""
    readme = sandbox / "README.md"
    readme.write_text(readme.read_text() + "\nSee paper/whitepaper.md\n")
    
    result = run_docs_gate(sandbox)
    assert not result.passed
    assert result.has(Violation.DOC_HISTORICAL_REFERENCE)
