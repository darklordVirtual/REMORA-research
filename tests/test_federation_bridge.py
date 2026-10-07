# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA Federation Bridge: loss-aware projection onto federation-port/v0.

The adapter side runs in an unmodified federation-port runtime
(``integrations/federation-port/remora-adapter/tests``). This suite covers
the REMORA side: native canonical preservation, the capability declaration,
the projection engine's monotonicity, the transport's refusals, the
projection records and the lifecycle separation (SDD acceptance criteria
AC-04 to AC-12).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey  # noqa: E402
from remora.federation import (  # noqa: E402
    NativeFederationAction,
    ProjectionError,
    ProjectionMap,
    TransportCapabilities,
    canonical_arguments,
    javascript_losses,
    load_capabilities,
    load_projection_map,
    transport_outcome,
)
from remora.federation.evidence import verify_evidence  # noqa: E402
from remora.federation.projection import weaker_or_equal  # noqa: E402
from remora.federation.transports.federation_port_v0 import (  # noqa: E402
    FederationPortV0Transport,
    artifact_digest,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts" / "interop" / "federation-port-v0"
ADAPTER = ROOT / "integrations" / "federation-port" / "remora-adapter"
KEY = SigningKey.from_text("c3" * 32, [SignatureDomain.FEDERATION_ACTION])
REFUND = {"payment_id": "pay_A", "amount_minor": 4000, "currency": "EUR"}


@pytest.fixture(scope="module")
def caps() -> TransportCapabilities:
    return load_capabilities(BASE / "capabilities.yaml")


@pytest.fixture(scope="module")
def pmap() -> ProjectionMap:
    return load_projection_map(BASE / "projection-map.yaml")


def _native(arguments=None, **authority) -> NativeFederationAction:
    auth = {"authorization_id": "apr-1", "principal": "agent-A", "tenant": "tenant-a",
            "valid_until": "2026-10-07T12:05:00.000Z", **authority}
    return NativeFederationAction(operation_id="op-1", workflow_id="refund", tool="refund",
                                  arguments=dict(REFUND) if arguments is None else arguments,
                                  authority={k: v for k, v in auth.items() if v is not None})


def _transport(caps, pmap) -> FederationPortV0Transport:
    return FederationPortV0Transport(capabilities=caps, projection_map=pmap, signing_key=KEY,
                                     adapter_digest="sha256:" + "0" * 64,
                                     remora_revision="test", transport_revision="test")


# -- native canonical preservation (SDD 6) ------------------------------------------

def test_one_and_one_point_zero_stay_distinct_natively() -> None:
    a, b = canonical_arguments({"n": 1}), canonical_arguments({"n": 1.0})
    assert a.digest != b.digest
    assert a.typed_scalars == (("/n", "integer"),) and b.typed_scalars == (("/n", "float"),)
    assert a.canonicalization == b.canonicalization == "remora-canonical-json-v1"


def test_javascript_losses_are_named_by_pointer() -> None:
    assert javascript_losses({"a": 1, "b": 1.5, "c": True}) == {}
    assert javascript_losses({"a": [1.0, -0.0]}) == {"lexical_numeric_type": ["/a/0", "/a/1"]}
    assert javascript_losses({"id": 2 ** 53}) == {"integer_precision": ["/id"]}


def test_unavailable_fields_are_listed_never_invented() -> None:
    envelope = _native().to_dict()
    assert envelope["authority"]["target"] is None
    assert "authority.target" in envelope["unavailable"]
    assert "execution_context.policy_digest" in envelope["unavailable"]


def test_valid_until_must_be_exact_utc_milliseconds() -> None:
    with pytest.raises(ValueError):
        _native(valid_until="2026-10-07T12:05:00Z")


# -- capability declaration (SDD 8) ----------------------------------------------------

def test_partial_and_absent_capabilities_supply_nothing(caps) -> None:
    assert caps.supplies("frozen_action")
    assert not caps.supplies("tool_definition_binding")  # partial
    assert not caps.supplies("no_such_capability")


def test_a_capability_value_outside_true_false_partial_is_refused() -> None:
    with pytest.raises(ValueError):
        TransportCapabilities.from_dict({"schema_version": "remora-federation-transport-capabilities-v1",
                                         "transport": "t", "capabilities": {"x": "yes"}})


# -- projection (SDD 3, 4, 7, 9, 10) ---------------------------------------------------

@pytest.mark.parametrize("claim, result, exported", [
    ("authorization_integrity", "PRESERVED", "remora.authorization_integrity"),
    ("exact_call_binding", "NARROWED", "remora.port_v0.bound_action"),
    ("fresh_authority_at_dispatch", "NARROWED", "remora.authorization_unexpired"),
    ("principal_binding", "NOT_ESTABLISHED", None),
    ("authority_executor_custody_isolation", "NOT_ESTABLISHED", None),
    ("effect_verification", "UNSUPPORTED", None),
])
def test_v0_projections(caps, pmap, claim, result, exported) -> None:
    projection = pmap.project(claim, caps)
    assert (projection.result, projection.exported_claim) == (result, exported)


def test_exact_call_over_v0_names_what_did_not_survive(caps, pmap) -> None:
    projection = pmap.project("exact_call_binding", caps)
    assert {"authenticated_principal", "authenticated_tenant", "lexical_numeric_type",
            "independent_target"} <= set(projection.not_established)
    assert "does not establish full REMORA exact_call_binding-v1.1" in projection.limits


def test_revocation_is_not_established_through_expiry(caps, pmap) -> None:
    """Revoked before dispatch but unexpired: V0 can say only 'unexpired'."""
    projection = pmap.project("fresh_authority_at_dispatch", caps)
    assert projection.exported_claim == "remora.authorization_unexpired"
    assert "revocation_state" in projection.not_established


def test_an_integer_v0_would_change_takes_the_bound_action_with_it(caps, pmap) -> None:
    projection = pmap.project("exact_call_binding", caps, javascript_losses({"id": 2 ** 53}))
    assert projection.result == "NOT_ESTABLISHED" and projection.exported_claim is None


def test_an_adapter_cannot_export_a_stronger_claim(caps, pmap) -> None:
    exact = pmap.project("exact_call_binding", caps)
    pmap.assert_export("remora.port_v0.bound_action", exact)
    with pytest.raises(ProjectionError):
        pmap.assert_export("remora.exact_call_binding", exact)
    with pytest.raises(ProjectionError):
        pmap.assert_export("remora.principal_binding", pmap.project("principal_binding", caps))


def test_the_adapter_manifest_claims_are_exported_by_the_map(pmap) -> None:
    manifest = json.loads((ADAPTER / "manifest.json").read_text(encoding="utf-8"))
    assert {c["id"] for c in manifest["claims"]} <= pmap.exported_claims()


def test_a_stronger_transport_preserves_without_changing_the_native_claim(caps, pmap) -> None:
    """AC-11: only the capability declaration changes."""
    stronger = TransportCapabilities.from_dict({
        "schema_version": "remora-federation-transport-capabilities-v1",
        "transport": "federation-port/v0",
        "capabilities": {**caps.capabilities, "typed_scalar_preservation": True,
                         "authenticated_tenant": True, "authenticated_principal": True,
                         "independent_target": True}})
    assert pmap.project("exact_call_binding", stronger).result == "PRESERVED"
    assert weaker_or_equal(pmap.project("exact_call_binding", caps).result, "PRESERVED")


def test_unknown_map_versions_and_misdeclared_maps_are_refused() -> None:
    with pytest.raises(ProjectionError):
        ProjectionMap.from_dict({"schema_version": "remora-federation-projection-map-v9"})
    with pytest.raises(ProjectionError):
        ProjectionMap.from_dict({
            "schema_version": "remora-federation-projection-map-v1", "projection_map_id": "x",
            "transport": "t", "native_claims": {"c": {"dimensions": {"a": ["x"]},
                                                      "narrowed": {"exported_claim": "remora.c",
                                                                   "requires": ["b"]}}}})


def test_a_map_for_another_transport_is_refused(caps, pmap) -> None:
    other = TransportCapabilities.from_dict({
        "schema_version": "remora-federation-transport-capabilities-v1",
        "transport": "other/v1", "capabilities": {"frozen_action": True}})
    with pytest.raises(ProjectionError):
        pmap.project("exact_call_binding", other)


# -- transport (SDD 9, 12, 14, 18) -------------------------------------------------------

def test_the_v0_request_and_signed_evidence(caps, pmap) -> None:
    projected = _transport(caps, pmap).project_action(_native())
    assert projected.request == {"workflow": "refund", "operation_id": "op-1",
                                 "approval_id": "apr-1", "tenant": "tenant-a",
                                 "action": {"tool": "refund", "args": REFUND}}
    ok, reason, envelope = verify_evidence(projected.evidence, [KEY.verification_key()])
    assert ok, reason
    assert envelope["transport_projection"]["valid_until"] == "2026-10-07T12:05:00.000Z"
    import base64

    outer = json.loads(projected.evidence)
    payload = base64.b64decode(outer["envelope_b64"]).replace(b"apr-1", b"apr-2")
    outer["envelope_b64"] = base64.b64encode(payload).decode()
    tampered = json.dumps(outer).encode()
    assert verify_evidence(tampered, [KEY.verification_key()]) == (False, "signature_invalid", None)


def test_v0_refuses_an_action_whose_integers_it_would_change(caps, pmap) -> None:
    with pytest.raises(ProjectionError, match="2\\^53"):
        _transport(caps, pmap).project_action(_native({"id": 2 ** 53 + 1}))


@pytest.mark.parametrize("missing", ["authorization_id", "valid_until"])
def test_v0_refuses_an_authority_missing_what_it_binds(caps, pmap, missing) -> None:
    with pytest.raises(ProjectionError):
        _transport(caps, pmap).project_action(_native(**{missing: None}))


def test_every_result_carries_its_projection_records(caps, pmap) -> None:
    projected = _transport(caps, pmap).project_action(_native(principal="agent-B"))
    by_claim = {r["native_claim"]: r for r in projected.projection_records}
    assert by_claim["principal_binding-v1"]["projection"] == "NOT_ESTABLISHED"
    assert by_claim["exact_call_binding-v1.1"]["projection"] == "NARROWED"
    for record in projected.projection_records:
        assert record["schema_version"] == "remora-federation-projection-v1"
        assert record["projection_map_digest"] == pmap.digest
        assert record["capabilities_digest"] == caps.digest


# -- lifecycle (SDD 15, 16) -----------------------------------------------------------------

def test_provider_confirmed_is_never_effect_verified() -> None:
    reading = transport_outcome("provider_confirmed")
    assert reading == {"transport_outcome": "provider_confirmed",
                       "execution": "EXECUTION_REPORTED_SUCCESS", "effect": "NOT_ESTABLISHED"}


def test_only_remora_effect_evidence_establishes_the_effect() -> None:
    from remora.governance.effect_verification import (
        PostconditionContract,
        verify_declared_delta,
    )

    contract = PostconditionContract(tool_id="refund", reader="r", target_selector={},
                                     expected_fields={"status": "refunded"})
    verified = verify_declared_delta(contract, {"status": "refunded"}, proposal_id="p",
                                     execution_id="e", toolspec_hash="h", verifier_identity="v")
    assert transport_outcome("provider_confirmed", verified)["effect"] == "EFFECT_VERIFIED"
    assert transport_outcome("unknown")["effect"] == "NOT_ESTABLISHED"
    with pytest.raises(ValueError):
        transport_outcome("settled")


# -- artifacts ----------------------------------------------------------------------------------

def test_fixtures_and_adapter_seal_match_the_code() -> None:
    result = subprocess.run([sys.executable, "scripts/build_federation_port_v0_fixtures.py",
                             "--check"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_adapter_digest_is_federation_port_s() -> None:
    manifest = json.loads((ADAPTER / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact"]["digest"] == artifact_digest(ADAPTER, manifest["artifact"]["files"])


def test_the_artifacts_validate_against_their_published_schemas(caps, pmap) -> None:
    import base64

    import jsonschema
    import yaml

    def schema(name: str) -> dict:
        return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))

    projected = _transport(caps, pmap).project_action(_native())
    envelope = json.loads(base64.b64decode(json.loads(projected.evidence)["envelope_b64"]))
    jsonschema.validate(envelope, schema("remora-federation-action-v1.json"))
    jsonschema.validate(yaml.safe_load((BASE / "capabilities.yaml").read_text(encoding="utf-8")),
                        schema("remora-federation-transport-capabilities-v1.json"))
    for record in projected.projection_records:
        jsonschema.validate(record, schema("remora-federation-projection-v1.json"))


def test_no_native_execution_primitive_imports_the_bridge() -> None:
    """AC-10: transports are replaceable because nothing native depends on them."""
    import ast

    offenders = []
    for package in ("remora/enforcement", "remora/execution", "remora/policy",
                    "remora/governance", "remora/crypto", "servers"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                         else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                if any(n.startswith("remora.federation") for n in names):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []
