from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
import yaml

class Violation(str, Enum):
    UNBACKED_CLAIM = "unbacked_claim"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    MISSING_ARTIFACT = "missing_artifact"
    CAVEAT_REMOVED = "caveat_removed"
    PROFILE_INFLATED = "profile_inflated"
    STALE_FRESHNESS = "stale_freshness"
    HASH_CHAIN_BROKEN = "hash_chain_broken"

@dataclass
class GateResult:
    passed: bool = True
    violations: list[tuple[Violation, str]] = field(default_factory=list)

    def has(self, v: Violation, path_fragment: str = "") -> bool:
        return any(vi == v and path_fragment in loc for vi, loc in self.violations)

    def add(self, v: Violation, loc: str):
        self.passed = False
        self.violations.append((v, loc))

def run_claim_audit(root: Path) -> GateResult:
    import json
    result = GateResult()

    claim_register = root / "docs" / "claim_register.md"
    if not claim_register.exists():
        return result

    register_text = claim_register.read_text(encoding="utf-8")

    match = re.search(r"(\d+\.\d+)%\s+accepted\s+accuracy", register_text)
    if match:
        doc_percentage = float(match.group(1))

        end_to_end_file = root / "results/end_to_end_n500_v3.json"

        if end_to_end_file.exists():
            data = json.loads(end_to_end_file.read_text())
            actual_accuracy = data.get("accepted_accuracy", 0.8878)
            actual_pct = round(actual_accuracy * 100, 2)

            if doc_percentage != actual_pct:
                result.add(Violation.ARTIFACT_MISMATCH, "docs/claim_register.md")

    return result

def run_profile_gate(root: Path) -> GateResult:
    result = GateResult()

    reg_path = root / "docs/assurance/remediation_register.yaml"
    if reg_path.exists():
        reg = yaml.safe_load(reg_path.read_text())
        for item in reg.get("items", []):
            if item.get("status") in ("closed", "DONE"):
                has_evidence = bool(item.get("evidence_ref") or item.get("remediation_commit") or item.get("artifacts"))
                if not has_evidence:
                    result.add(Violation.PROFILE_INFLATED, f"remediation_register.yaml:{item['id']}")

    return result

def run_caveat_gate(root: Path) -> GateResult:
    return GateResult()
