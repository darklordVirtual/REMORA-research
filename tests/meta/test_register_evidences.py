from remora.audit_gates.api import run_profile_gate, Violation
import yaml

def test_register_edit_without_evidence_fails(sandbox):
    """Sett REM-021 til 'closed' uten remediation-referanse."""
    reg_path = sandbox / "docs/assurance/remediation_register.yaml"
    reg = yaml.safe_load(reg_path.read_text())

    found = False
    for item in reg["items"]:
        if item["id"] == "REM-021":
            item["status"] = "closed"
            found = True

            # Remove any evidence if present
            item.pop("evidence_ref", None)
            item.pop("remediation_commit", None)

    assert found, "REM-021 must exist in the register for this test"
    reg_path.write_text(yaml.safe_dump(reg))

    result = run_profile_gate(sandbox)
    assert not result.passed, (
        "Registeret kan settes til 'closed' uten evidensfelt — "
        "profilen kan dermed heves ved å redigere YAML i stedet for prosa. "
        "Samme svindel, ett hakk dypere."
    )
    assert result.has(Violation.PROFILE_INFLATED)
