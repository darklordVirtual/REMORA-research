# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fixture adapter for REMORA APS Interop Profile v0.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from remora.enforcement.lease_signing import ALG_ED25519, ENV_ED25519_PUBLIC, verify_payload
from remora.interop.jcs import canonicalise

from .mappings import (
    MappingRefused,
    accountability_decision,
    actionref_canonical,
    classify_receipt_decision_relation,
)
from .profile_v0_1 import PROFILE_ID, RUN_MODE


def run_actionref_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for vector in fixture["vectors"]:
        source = vector["input"]
        try:
            order, observed = actionref_canonical(
                actor_identity=source["agentId"],
                action_type=source["actionType"],
                credential_scope=source["scopeRequired"],
                issued_at=source["timestamp"],
            )
            expected_valid = vector.get("expected_verification", True)
            passed = expected_valid and observed == vector["action_ref"]
            result = {
                "name": vector["name"],
                "outcome": "PASS" if passed else "DIVERGENCE",
                "canonical_scope_order": order,
                "observed_action_ref": observed,
            }
        except MappingRefused as exc:
            expected_refusal = vector.get("expected_verification") is False
            result = {
                "name": vector["name"],
                "outcome": "PASS" if expected_refusal else "REFUSED",
                "reason": str(exc),
            }
        results.append(result)
    return {
        "profile": PROFILE_ID,
        "mode": RUN_MODE,
        "family": "actionref-canonical",
        "mapping": "adapter-constructed ActionRef from deployment-owned REMORA fields",
        "claim_boundary": "does not create or validate a REMORA exact-call identity",
        "summary": {
            "vectors": len(results),
            "passed": sum(item["outcome"] == "PASS" for item in results),
            "divergences": sum(item["outcome"] == "DIVERGENCE" for item in results),
            "refused": sum(item["outcome"] == "REFUSED" for item in results),
        },
        "results": results,
    }


def run_accountability_fixture(path: Path) -> dict[str, Any]:
    """Verify crypto/digest properties; keep APS-only schema evidence separate."""

    fixture = json.loads(path.read_text(encoding="utf-8"))
    public_key = fixture["keypair"]["publicKeyHex"]
    prior = os.environ.get(ENV_ED25519_PUBLIC)
    os.environ[ENV_ED25519_PUBLIC] = public_key
    results: list[dict[str, Any]] = []
    try:
        for vector in fixture["vectors"]:
            record = vector["record"]
            unsigned = {key: value for key, value in record.items() if key != "sig"}
            signature_valid = verify_payload(
                canonicalise(unsigned), record["sig"], alg=ALG_ED25519
            )
            digest_valid = True
            if "action" in record:
                digest_valid = (
                    hashlib.sha256(canonicalise(record["action"])).hexdigest()
                    == record["action_digest"]["sha256"]
                )
            shape_valid = (
                record.get("record_type") == "accountability_record"
                and record.get("decision") in {"allow", "deny", "halt"}
                and record.get("sig_alg") == "Ed25519"
            )
            observed_valid = signature_valid and digest_valid and shape_valid
            expected_valid = vector["expected_verification"]
            scope = (
                "adapter-evidence"
                if vector.get("rejection_kind") == "schema"
                else "remora-crypto-evidence"
            )
            results.append({
                "name": vector["name"],
                "outcome": "PASS" if observed_valid == expected_valid else "DIVERGENCE",
                "expected_verification": expected_valid,
                "observed_verification": observed_valid,
                "signature_valid": signature_valid,
                "action_digest_valid": digest_valid,
                "shape_valid": shape_valid,
                "evidence_scope": scope,
            })
    finally:
        if prior is None:
            os.environ.pop(ENV_ED25519_PUBLIC, None)
        else:
            os.environ[ENV_ED25519_PUBLIC] = prior
    report = _family_report("accountability-record", results)
    mapping_cases = [
        ("ACCEPT-executed", "ACCEPT", True, False, ("allow", True)),
        ("ACCEPT-not-consumed", "ACCEPT", False, False, ("allow", False)),
        ("VERIFY-unresolved", "VERIFY", False, False, ("halt", False)),
        ("ESCALATE-refused", "ESCALATE", False, True, ("deny", False)),
        ("ABSTAIN", "ABSTAIN", False, False, ("deny", False)),
    ]
    report["mapping_checks"] = [
        {
            "name": name,
            "outcome": "PASS" if accountability_decision(
                remora_verdict=verdict,
                executed=executed,
                review_resolved_as_refused=resolved,
            ) == expected else "DIVERGENCE",
            "expected": list(expected),
        }
        for name, verdict, executed, resolved, expected in mapping_cases
    ]
    report["summary"]["mapping_checks"] = len(report["mapping_checks"])
    report["summary"]["mapping_divergences"] = sum(
        item["outcome"] == "DIVERGENCE" for item in report["mapping_checks"]
    )
    report["claim_boundary"] = (
        "schema-only negatives are adapter evidence; cryptographic and digest "
        "checks use REMORA implementations"
    )
    return report


def run_receipt_relation_fixture(directory: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        vector = json.loads(path.read_text(encoding="utf-8"))
        observed = classify_receipt_decision_relation(
            receipt=vector["receipt"], evidence=vector["provided_decision_evidence"]
        )
        expected = vector["expected"]["failure"]
        results.append({
            "name": vector["name"],
            "outcome": "PASS" if observed == expected else "DIVERGENCE",
            "expected_classification": expected,
            "observed_classification": observed,
            "evidence_scope": "profile-projection-evidence",
        })
    return _family_report("receipt-decision-relation", results)


def _family_report(family: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "family": family,
        "summary": {
            "vectors": len(results),
            "passed": sum(item["outcome"] == "PASS" for item in results),
            "divergences": sum(item["outcome"] == "DIVERGENCE" for item in results),
        },
        "results": results,
    }


def run_profile(suite: Path) -> dict[str, Any]:
    actionref = run_actionref_fixture(
        suite / "fixtures/actionref-canonical/actionref-canonical-fixture-v1.json"
    )
    accountability = run_accountability_fixture(
        suite / "fixtures/accountability-record/accountability-record-fixture-v1.json"
    )
    relation = run_receipt_relation_fixture(
        suite / "fixtures/receipt-decision-relation/receipt-decision-relation-v1"
    )
    instruction = {
        "family": "instruction-provenance",
        "summary": {"vectors": 0, "passed": 0, "divergences": 0},
        "status": "NOT_RUN",
        "reason": (
            "The mapped envelope subset is not separable from the fixture's "
            "filesystem path rules. Profile v0.1 requires NOT_RUN rather than "
            "adapter-owned path handling."
        ),
        "declined_surface": "nine filesystem path-canonicalisation rules",
    }
    families = [actionref, accountability, relation, instruction]
    return {
        "profile": PROFILE_ID,
        "mode": RUN_MODE,
        "families": families,
        "summary": {
            "families_declared": 4,
            "families_run": 3,
            "families_not_run": 1,
            "vectors_run": sum(f["summary"]["vectors"] for f in families),
            "passed": sum(f["summary"]["passed"] for f in families),
            "divergences": sum(f["summary"]["divergences"] for f in families),
            "mapping_checks": sum(
                f["summary"].get("mapping_checks", 0) for f in families
            ),
            "mapping_divergences": sum(
                f["summary"].get("mapping_divergences", 0) for f in families
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aps-suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_profile(args.aps_suite)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(json.dumps(report["summary"], separators=(",", ":")))
    return 0 if (
        report["summary"]["divergences"] == 0
        and report["summary"]["mapping_divergences"] == 0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
