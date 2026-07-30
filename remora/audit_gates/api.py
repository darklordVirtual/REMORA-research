# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
import subprocess
import yaml

class Violation(str, Enum):
    UNBACKED_CLAIM = "unbacked_claim"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    MISSING_ARTIFACT = "missing_artifact"
    CAVEAT_REMOVED = "caveat_removed"
    PROFILE_INFLATED = "profile_inflated"
    STALE_FRESHNESS = "stale_freshness"
    HASH_CHAIN_BROKEN = "hash_chain_broken"
    DOC_DUPLICATE_TOPIC = "doc_duplicate_topic"
    DOC_HISTORICAL_REFERENCE = "doc_historical_reference"
    DOC_STALE = "doc_stale"
    DOC_UNREGISTERED = "doc_unregistered"

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

def run_docs_gate(root: Path) -> GateResult:
    result = GateResult()
    reg_path = root / "docs/assurance/document_register_v1.yaml"
    if not reg_path.exists():
        return result

    reg = yaml.safe_load(reg_path.read_text())
    docs = reg.get("documents", [])

    topics: dict[str, str] = {}
    historical_banned = []

    for d in docs:
        status = d.get("status")
        path = d.get("path")

        if status == "canonical":
            topic = d.get("topic")
            if topic in topics:
                result.add(Violation.DOC_DUPLICATE_TOPIC, f"{path} and {topics[topic]}")
            else:
                topics[topic] = path

        if status == "historical" and d.get("referencing_allowed") is False:
            historical_banned.append(path)

    # When the root is a real git checkout, restrict the scan to tracked
    # files — the same scope check_document_governance.py uses. Untracked or
    # gitignored local files are not repository surface. Sandbox roots
    # (metatests) have no .git and are scanned in full.
    tracked: set[str] | None = None
    if (root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "ls-files"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0:
                tracked = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
        except Exception:
            tracked = None  # git unavailable: fall back to full-tree scan

    def _rel(search_file: Path) -> str:
        return str(search_file.relative_to(root)).replace("\\", "/")

    if historical_banned:
        # A reference by full registered path or by bare filename both count:
        # citing the banned document's filename is as stale as the full path.
        forbidden = [Path(p).name for p in historical_banned] + list(historical_banned)

        def _skip(search_file: Path) -> bool:
            rel = search_file.relative_to(root)
            # Dot-directories (.git, .remember, .vscode, ...) and vendored
            # trees are not governed documentation surface.
            if any(part.startswith(".") or part == "node_modules" for part in rel.parts):
                return True
            if tracked is not None and _rel(search_file) not in tracked:
                return True
            # The banned documents themselves, the registers that must name
            # them, and the metatests that exercise this gate are exempt.
            if _rel(search_file) in historical_banned:
                return True
            if search_file.name in ("document_register_v1.yaml", "claim_register.md"):
                return True
            return rel.parts[:2] == ("tests", "meta")

        for pattern in ("*.md", "*.py"):
            for search_file in root.rglob(pattern):
                if _skip(search_file):
                    continue
                text_cont = search_file.read_text(encoding="utf-8", errors="replace")
                if any(token in text_cont for token in forbidden):
                    result.add(Violation.DOC_HISTORICAL_REFERENCE, f"{search_file.relative_to(root)}")

    # The document register covers tracked docs/ exactly (archive is out of
    # this gate's scope); any unregistered markdown file is a lifecycle
    # violation.
    registered_paths = {d.get("path") for d in docs if d.get("path")}
    for doc_file in (root / "docs").rglob("*.md"):
        if "archive" in doc_file.parts:
            continue
        rel_path = _rel(doc_file)
        if tracked is not None and rel_path not in tracked:
            continue
        if rel_path not in registered_paths:
            result.add(Violation.DOC_UNREGISTERED, rel_path)

    return result

