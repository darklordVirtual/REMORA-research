from remora.audit_gates.api import run_docs_gate, Violation
import yaml

def test_doc_uniqueness_fails(sandbox):
    """Register to filer med samme 'topic' for canonical: feiler."""
    reg_path = sandbox / "docs/assurance/document_register_v1.yaml"
    reg = yaml.safe_load(reg_path.read_text())

    existing_topic = None
    for item in reg.get("documents", []):
        topic = item.get("topic")
        if topic:
            existing_topic = topic
            break

    assert existing_topic is not None, "document register must contain at least one topic"

    # Duplicate an existing topic to force the gate to fail deterministically.
    reg["documents"].append({
        "path": "docs/02-another.md",
        "status": "canonical",
        "topic": existing_topic,
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

def test_unregistered_documents_fail(sandbox):
    """Any unregistered .md file under docs/ breaks the gate — every document
    must enter the lifecycle through the register, regardless of its name."""
    probe = sandbox / "docs" / "governance_probe_not_in_register.md"
    probe.write_text("# Probe\nThis file is deliberately not in the register.\n")

    result = run_docs_gate(sandbox)
    assert not result.passed
    assert result.has(Violation.DOC_UNREGISTERED)


def test_registered_documents_pass(sandbox):
    """The unmodified sandbox audit surface passes the docs gate — the real
    register covers the real files exactly."""
    result = run_docs_gate(sandbox)
    assert result.passed, [f"{v.value}: {loc}" for v, loc in result.violations]
