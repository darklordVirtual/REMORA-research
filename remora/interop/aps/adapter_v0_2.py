# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Additive runner for REMORA APS Interop Profile v0.2.

The v0.1 mapping and evidence remain frozen. v0.2 adds two observations:

1. APS accountability-record schema-layer parity. This is explicitly adapter
   evidence, not a REMORA runtime claim. The runner reads the current APS
   manifest, verifies the pinned Draft 2020-12 schema bytes, and applies the
   same decisive/non-decisive rule as APS' Python parity implementation.
2. token-exchange-attenuation-v0 P1 only. Scope monotonicity is projected onto
   REMORA's existing delegation-chain verifier. P2 and P3 are NOT_RUN because
   REMORA has no RFC 8693 upstream-claim/actor attribute evaluator and the
   adapter must not manufacture a passing implementation of an external rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from remora.governance.a2a_envelope import (
    PROTOCOL_VERSION,
    A2AGovernanceEnvelope,
    AgentIdentity,
    DelegationLink,
)

from .adapter import run_profile as run_profile_v0_1
from .profile_v0_2 import NOT_RUN_PROPERTIES, PROFILE_ID, RUN_MODE

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_SCOPE_INVALID_REASON = "t2_scope_not_subset_of_t1"
_FIXED_TIME = "2026-09-09T00:00:00+00:00"


def _json_pointer(path: Iterable[object]) -> str:
    return "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1")
        for part in path
    )


def _blocked_schema(reason: str) -> dict[str, Any]:
    return {
        "family": "accountability-record",
        "layer": "schema",
        "evidence_scope": "adapter-evidence",
        "status": "BLOCKED",
        "reason": reason,
        "summary": {
            "decisive_checks": 0,
            "passed": 0,
            "divergences": 1,
            "non_decisive": 0,
        },
        "results": [],
    }


def run_accountability_schema_layer(suite: Path) -> dict[str, Any]:
    """Recompute APS' declared accountability schema layer in Python.

    A crypto/digest negative is reported but is not decisive for this layer.
    Positives must be schema-valid. A negative whose rejection_kind is owned by
    the schema layer must be rejected with the exact path/keyword binding the
    APS manifest declares for its expected_error_code.
    """

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return _blocked_schema("jsonschema is not installed")

    manifest_path = suite / "fixtures/manifest.json"
    fixture_path = (
        suite
        / "fixtures/accountability-record/accountability-record-fixture-v1.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _blocked_schema(f"cannot read APS accountability inputs: {exc}")

    entry = next(
        (
            item
            for item in manifest.get("fixtures", [])
            if item.get("category") == "accountability-record"
        ),
        None,
    )
    if entry is None:
        return _blocked_schema("APS manifest has no accountability-record entry")

    required_layers = entry.get("required_layers") or []
    layers = entry.get("layers") or {}
    declaration = layers.get("schema")
    if "schema" not in required_layers or not isinstance(declaration, dict):
        return _blocked_schema("APS manifest does not require a schema layer")
    if declaration.get("dialect") != DRAFT_2020_12:
        return _blocked_schema(
            f"unexpected schema dialect: {declaration.get('dialect')!r}"
        )

    relative_schema = declaration.get("schema_path")
    pinned_digest = declaration.get("schema_sha256")
    if not isinstance(relative_schema, str) or not isinstance(pinned_digest, str):
        return _blocked_schema("schema path or digest pin is missing")

    schema_path = suite / "fixtures" / relative_schema
    try:
        schema_bytes = schema_path.read_bytes()
        schema = json.loads(schema_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _blocked_schema(f"cannot read pinned schema: {exc}")

    observed_digest = hashlib.sha256(schema_bytes).hexdigest()
    if observed_digest != pinned_digest:
        return _blocked_schema(
            "schema digest mismatch: "
            f"manifest={pinned_digest} observed={observed_digest}"
        )
    if schema.get("$schema") != DRAFT_2020_12:
        return _blocked_schema("schema does not declare Draft 2020-12")

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # jsonschema raises a family of schema exceptions
        return _blocked_schema(f"schema meta-validation failed: {exc}")

    validator = Draft202012Validator(schema)
    owned = set(declaration.get("owns_rejection_kinds") or [])
    bindings = declaration.get("error_bindings") or {}
    results: list[dict[str, Any]] = []

    for vector in fixture.get("vectors", []):
        errors = sorted(
            validator.iter_errors(vector["record"]),
            key=lambda error: list(error.absolute_path),
        )
        observed_errors = [
            {
                "instance_path": _json_pointer(error.absolute_path),
                "keyword": str(error.validator),
            }
            for error in errors
        ]
        observed_pairs = {
            (item["instance_path"], item["keyword"])
            for item in observed_errors
        }
        rejection_kind = vector.get("rejection_kind")
        error_code = vector.get("expected_error_code")

        if rejection_kind in owned:
            expected_binding = bindings.get(error_code) if error_code else None
            if not errors:
                passed = False
                reason = "expected schema rejection was not observed"
            elif error_code is None:
                passed = True
                reason = "schema rejection observed"
            elif not isinstance(expected_binding, dict):
                passed = False
                reason = f"no manifest binding for {error_code}"
            else:
                expected_pair = (
                    expected_binding.get("instance_path"),
                    expected_binding.get("keyword"),
                )
                passed = expected_pair in observed_pairs
                reason = (
                    "expected error binding observed"
                    if passed
                    else f"expected error binding not observed: {expected_pair}"
                )
            outcome = "PASS" if passed else "DIVERGENCE"
            decisive = True
        elif vector.get("expected_verification") is False:
            outcome = "NON_DECISIVE"
            decisive = False
            reason = (
                f"{rejection_kind} negative; schema result is reported but "
                "does not decide this vector"
            )
        else:
            passed = not errors
            outcome = "PASS" if passed else "DIVERGENCE"
            decisive = True
            reason = (
                "positive is schema-valid"
                if passed
                else "positive is schema-invalid"
            )

        results.append(
            {
                "name": vector["name"],
                "outcome": outcome,
                "decisive": decisive,
                "rejection_kind": rejection_kind,
                "expected_error_code": error_code,
                "observed_errors": observed_errors,
                "reason": reason,
            }
        )

    decisive_results = [item for item in results if item["decisive"]]
    return {
        "family": "accountability-record",
        "layer": "schema",
        "evidence_scope": "adapter-evidence",
        "status": "RUN",
        "schema_sha256": observed_digest,
        "validator": "python-jsonschema Draft202012Validator",
        "claim_boundary": (
            "This reproduces the APS schema-layer decision rule. It is adapter "
            "evidence and is not a REMORA runtime schema-validation claim."
        ),
        "summary": {
            "decisive_checks": len(decisive_results),
            "passed": sum(item["outcome"] == "PASS" for item in decisive_results),
            "divergences": sum(
                item["outcome"] == "DIVERGENCE" for item in decisive_results
            ),
            "non_decisive": sum(
                item["outcome"] == "NON_DECISIVE" for item in results
            ),
        },
        "results": results,
    }


def _scope_tokens(claims: dict[str, Any]) -> tuple[str, ...]:
    raw = claims.get("scope", "")
    if raw is None:
        return ()
    if not isinstance(raw, str):
        raise ValueError("scope must be a space-separated string")
    return tuple(raw.split())


def _remora_p1_observation(
    t1_scope: tuple[str, ...], t2_scope: tuple[str, ...]
) -> dict[str, Any]:
    """Project one T1->T2 scope relation into REMORA's existing chain verifier."""

    identity = AgentIdentity(
        agent_id="aps://token-exchange/t2",
        agent_version="v0",
        issuer_org="aps-interop",
        responsible_org="aps-interop",
    )
    chain = (
        DelegationLink(
            delegator="aps://token-exchange/t1",
            delegatee="aps://token-exchange/exchange",
            scope=t1_scope,
            issued_at=_FIXED_TIME,
        ),
        DelegationLink(
            delegator="aps://token-exchange/exchange",
            delegatee=identity.agent_id,
            scope=t2_scope,
            issued_at=_FIXED_TIME,
        ),
    )
    envelope = A2AGovernanceEnvelope(
        envelope_id="aps-token-exchange-p1",
        protocol=PROTOCOL_VERSION,
        identity=identity,
        delegation_chain=chain,
        requested_scope=t2_scope,
        policy_version="aps-token-exchange-p1",
        decision_ref=None,
        evidence_refs=(),
        issued_at=_FIXED_TIME,
        expires_at=None,
        audience="aps://token-exchange/p1",
        nonce="aps-token-exchange-p1",
    )

    # This adapter deliberately calls the existing REMORA verifier primitive.
    # It does not duplicate subset logic in the APS package. P1 is authority
    # shape evidence, so link signatures, clocks and replay are outside scope.
    failures = envelope._verify_delegation_chain()  # noqa: SLF001
    widened = any(item.startswith("scope_widened_at_link:1") for item in failures)
    return {
        "scope_widened": widened,
        "failures": failures,
        "effective_scope": sorted(envelope.effective_scope()),
    }


def run_token_exchange_attenuation_p1(path: Path) -> dict[str, Any]:
    """Run only P1 from token-exchange-attenuation-v0 through REMORA."""

    fixture = json.loads(path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []

    for case in fixture.get("cases", []):
        if "P1" not in case.get("properties", []):
            continue
        t1_scope = _scope_tokens(case["subject_token_claims"])
        t2_scope = _scope_tokens(case["exchanged_token_claims"])
        observation = _remora_p1_observation(t1_scope, t2_scope)
        expected_effective = sorted(set(t1_scope) & set(t2_scope))
        vector_valid = bool(case.get("vector_valid"))
        invalid_reason = case.get("invalid_reason")

        if vector_valid:
            passed = (
                not observation["scope_widened"]
                and observation["effective_scope"] == expected_effective
            )
            reason = "T2 does not widen T1"
        elif invalid_reason == _SCOPE_INVALID_REASON:
            passed = observation["scope_widened"]
            reason = "REMORA rejected T2 scope widening"
        else:
            passed = False
            reason = f"unsupported P1 invalid reason: {invalid_reason!r}"

        results.append(
            {
                "id": case["id"],
                "outcome": "PASS" if passed else "DIVERGENCE",
                "vector_valid": vector_valid,
                "invalid_reason": invalid_reason,
                "t1_scope": list(t1_scope),
                "t2_scope": list(t2_scope),
                "observed_scope_widening": observation["scope_widened"],
                "effective_scope": observation["effective_scope"],
                "remora_failures": observation["failures"],
                "reason": reason,
            }
        )

    return {
        "family": "token-exchange-attenuation-v0",
        "property": "P1",
        "mode": RUN_MODE,
        "evidence_scope": "remora-delegation-evidence",
        "claim_boundary": (
            "P1 only: T2 scope must not widen T1. The adapter maps the two "
            "opaque scope sets into consecutive REMORA DelegationLink objects "
            "and invokes REMORA's existing chain verifier."
        ),
        "not_run": {
            "properties": list(NOT_RUN_PROPERTIES["token-exchange-attenuation-v0"]),
            "reason": (
                "REMORA has no RFC 8693 upstream_claims/act attribute-policy "
                "evaluator. Implementing P2/P3 in this adapter would be adapter "
                "evidence rather than a REMORA property."
            ),
        },
        "summary": {
            "cases": len(results),
            "passed": sum(item["outcome"] == "PASS" for item in results),
            "divergences": sum(
                item["outcome"] == "DIVERGENCE" for item in results
            ),
        },
        "results": results,
    }


def run_profile(suite: Path) -> dict[str, Any]:
    inherited = run_profile_v0_1(suite)
    schema_layer = run_accountability_schema_layer(suite)
    token_p1 = run_token_exchange_attenuation_p1(
        suite / "fixtures/cross-stack/token-exchange-attenuation-v0/vectors.json"
    )
    return {
        "profile": PROFILE_ID,
        "mode": RUN_MODE,
        "inherits": inherited,
        "additional_evidence": [schema_layer, token_p1],
        "summary": {
            "v0_1_vectors_run": inherited["summary"]["vectors_run"],
            "v0_1_passed": inherited["summary"]["passed"],
            "v0_1_divergences": inherited["summary"]["divergences"],
            "v0_1_mapping_divergences": inherited["summary"][
                "mapping_divergences"
            ],
            "schema_status": schema_layer["status"],
            "schema_decisive_checks": schema_layer["summary"]["decisive_checks"],
            "schema_passed": schema_layer["summary"]["passed"],
            "schema_divergences": schema_layer["summary"]["divergences"],
            "token_exchange_p1_cases": token_p1["summary"]["cases"],
            "token_exchange_p1_passed": token_p1["summary"]["passed"],
            "token_exchange_p1_divergences": token_p1["summary"]["divergences"],
            "token_exchange_not_run": token_p1["not_run"]["properties"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aps-suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = run_profile(args.aps_suite)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    summary = report["summary"]
    print(json.dumps(summary, separators=(",", ":")))

    schema_ran = summary["schema_status"] == "RUN"
    token_p1_ran = summary["token_exchange_p1_cases"] > 0
    clean = (
        summary["v0_1_divergences"] == 0
        and summary["v0_1_mapping_divergences"] == 0
        and summary["schema_divergences"] == 0
        and summary["token_exchange_p1_divergences"] == 0
    )
    return 0 if schema_ran and token_p1_ran and clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
