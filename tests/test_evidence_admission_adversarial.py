# SPDX-License-Identifier: BUSL-1.1
"""Adversarial matrix for admit_evidence (task section 6).

Every test here attacks a shortcut the layer exists to refuse: producer
self-claims, coverage scope confusion, declared independence, identifier
equality as binding, post-hoc commitments, and processing/property collapse.
"""
from __future__ import annotations

from remora.evidence.admission import (
    CoverageAttestation,
    CoverageState,
    InvocationBindingProof,
    KnownGap,
    ManifestTrust,
    ObservationVantage,
    PriorCommitment,
    ProducerCapabilityManifest,
    TrustConfig,
    admit_evidence,
)

H64 = "a" * 64
H64B = "b" * 64
NOW = 500
EXEC_STARTED = 400

INVOCATION = {
    "invocation_id": "inv-1",
    "proposal_id": "p-1",
    "execution_id": "e-1",
    "tool_call_hash": H64,
    "dispatch_id": "d-1",
    "toolspec_hash": H64B,
    "tenant": "acme",
    "target": "prod",
    "operation": "write",
    "attempt": "1",
}

FIELDS = ("effect", "delegation")
INTERVAL = (100, 200)


def _manifest(**kw) -> ProducerCapabilityManifest:
    base = dict(
        producer_id="collector-1", manifest_id="m-1", schema_version="v1",
        fields_visible=FIELDS, scope={"tenant": "acme"},
        trust=ManifestTrust.ACCEPTED, valid_from=0, valid_until=1000,
    )
    base.update(kw)
    return ProducerCapabilityManifest(**base)


def _coverage(**kw) -> CoverageAttestation:
    base = dict(
        invocation_id="inv-1", fields=FIELDS, interval_start=100,
        interval_end=200, state=CoverageState.COMPLETE, producer_id="collector-1",
    )
    base.update(kw)
    return CoverageAttestation(**base)


def _vantage(**kw) -> ObservationVantage:
    base = dict(
        observer_id="watcher-1", observed_party="agent-1",
        control_domain="deployer-b", observed_control_domain="deployer-a",
        can_observed_party_forge=False, can_observed_party_suppress=False,
    )
    base.update(kw)
    return ObservationVantage(**base)


def _binding(**kw) -> InvocationBindingProof:
    base = dict(
        evidence_id="ev-1", proposal_id="p-1", execution_id="e-1",
        tool_call_hash=H64, dispatch_id="d-1", toolspec_hash=H64B,
        tenant="acme", target="prod", operation="write", attempt="1",
    )
    base.update(kw)
    return InvocationBindingProof(**base)


def _commitment(**kw) -> PriorCommitment:
    base = dict(
        commitment_id="c-1", proposal_id="p-1", tool_call_hash=H64,
        target="prod", operation="write", expected_digest="c" * 64,
        created_at=100, valid_until=1000, issuer="deployer",
        provenance_ref="deployment-ledger://commitment/c-1",
    )
    base.update(kw)
    return PriorCommitment(**base)


def _trust_for(
    manifest: ProducerCapabilityManifest,
    prior_commitment: PriorCommitment | None = None,
) -> TrustConfig:
    return TrustConfig(
        accepted_producers={manifest.producer_id: manifest.digest},
        accepted_prior_commitments=(
            {prior_commitment.commitment_id: prior_commitment.digest}
            if prior_commitment is not None else {}
        ),
        trusted_vantage_domains=("deployer-b",),
    )


def _full(**overrides):
    """A complete, correctly bound evidence set — the happy path."""
    kwargs = dict(
        manifest=_manifest(),
        coverage=_coverage(),
        vantage=_vantage(),
        binding=_binding(),
        prior_commitment=_commitment(),
        trust=None,  # filled below
        expected_invocation=INVOCATION,
        execution_started_at=EXEC_STARTED,
        evaluated_fields=FIELDS,
        evaluated_interval=INTERVAL,
        now=NOW,
    )
    kwargs.update(overrides)
    if kwargs["trust"] is None:
        kwargs["trust"] = (
            _trust_for(kwargs["manifest"], kwargs["prior_commitment"])
            if kwargs["manifest"] is not None
            else TrustConfig()
        )
    return admit_evidence(**kwargs)


# ── happy path pins the join ────────────────────────────────────────────────

def test_fully_bound_evidence_establishes_every_fact() -> None:
    result = _full()
    assert result.reason_codes == ("effect_observation_not_supplied",)
    for fact in (
        "source_accepted", "scope_accepted", "producer_visibility_established",
        "observation_coverage_complete",
        "same_protected_operation", "vantage_independent",
        "invocation_binding_established", "prior_commitment_established",
    ):
        assert result.is_established(fact), fact
    assert not result.is_established("effect_observation_accepted")


def test_complete_coverage_does_not_claim_an_observed_effect() -> None:
    result = _full(vantage=None, binding=None, prior_commitment=None)

    assert result.is_established("observation_coverage_complete")
    assert not result.is_established("effect_observation_accepted")


def test_typed_evidence_digest_is_deterministic_and_content_bound() -> None:
    complete = _full()
    repeated = _full()
    changed = _full(coverage=_coverage(interval_end=250))

    assert complete.evidence_digest == repeated.evidence_digest
    assert complete.evidence_digest != changed.evidence_digest


def test_missing_evidence_obligations_are_named() -> None:
    result = _full(
        coverage=None,
        vantage=None,
        binding=None,
        prior_commitment=None,
    )

    assert "coverage_incomplete" in result.reason_codes
    assert "observation_vantage_not_established" in result.reason_codes
    assert "invocation_binding_not_established" in result.reason_codes
    assert "prior_commitment_missing" in result.reason_codes
    assert "effect_observation_not_supplied" in result.reason_codes


# ── visibility (task 6, "Visibility") ───────────────────────────────────────

def test_visibility_unknown_means_no_absence_support() -> None:
    m = _manifest(trust=ManifestTrust.NOT_ESTABLISHED)
    result = _full(manifest=m, trust=_trust_for(m))
    assert not result.is_established("producer_visibility_established")
    assert not result.is_established("observation_coverage_complete")
    assert "producer_visibility_not_established" in result.reason_codes


def test_self_declared_capability_is_not_accepted() -> None:
    # Producer says it can see the fields; the deployment map does not carry it.
    m = _manifest()
    result = _full(manifest=m, trust=TrustConfig(accepted_producers={}))
    assert not result.is_established("producer_visibility_established")
    assert "producer_capability_self_declared" in result.reason_codes


def test_manifest_not_covering_a_field_fails_visibility() -> None:
    m = _manifest(fields_visible=("effect",))
    result = _full(manifest=m, trust=_trust_for(m))
    assert not result.is_established("producer_visibility_established")


def test_manifest_for_another_tenant_cannot_establish_visibility_or_coverage() -> None:
    manifest = _manifest(scope={"tenant": "other"})
    result = _full(manifest=manifest, trust=_trust_for(manifest))

    assert result.is_established("source_accepted")
    assert not result.is_established("producer_visibility_established")
    assert not result.is_established("observation_coverage_complete")
    assert "producer_scope_mismatch" in result.reason_codes


# ── coverage (task 6, "Coverage") ───────────────────────────────────────────

def test_coverage_for_another_invocation_is_a_scope_mismatch() -> None:
    result = _full(coverage=_coverage(invocation_id="inv-2"))
    assert not result.is_established("observation_coverage_complete")
    assert "coverage_scope_mismatch" in result.reason_codes


def test_known_gap_means_not_complete() -> None:
    c = _coverage(state=CoverageState.INCOMPLETE,
                  known_gaps=(KnownGap(120, 130, "collector_unavailable"),))
    result = _full(coverage=c)
    assert not result.is_established("observation_coverage_complete")
    assert "coverage_incomplete" in result.reason_codes


def test_unknown_coverage_never_supports_absence() -> None:
    result = _full(coverage=_coverage(state=CoverageState.UNKNOWN))
    assert not result.is_established("observation_coverage_complete")
    assert "coverage_unknown" in result.reason_codes


def test_field_outside_attested_set_is_incomplete() -> None:
    result = _full(coverage=_coverage(fields=("effect",)))
    assert not result.is_established("observation_coverage_complete")


# ── vantage (task 6, "Vantage / independence") ──────────────────────────────

def test_self_observation_is_never_independent() -> None:
    v = _vantage(observer_id="agent-1", observed_party="agent-1",
                 control_domain="deployer-b")
    result = _full(vantage=v)
    assert not result.is_established("vantage_independent")
    assert "self_report_not_independent" in result.reason_codes


def test_declared_independence_without_facts_stays_unestablished() -> None:
    # Same control domain on both sides: nothing derives independence.
    v = _vantage(control_domain="deployer-a", declared_independence=True)
    result = _full(vantage=v)
    assert not result.is_established("vantage_independent")
    assert "observation_vantage_not_established" in result.reason_codes


def test_independent_observer_outside_trusted_domains_is_unestablished() -> None:
    m = _manifest()
    result = _full(
        manifest=m,
        trust=TrustConfig(
            accepted_producers={m.producer_id: m.digest},
            trusted_vantage_domains=("deployer-z",),  # not deployer-b
        ),
    )
    assert not result.is_established("vantage_independent")


def test_unconfigured_domain_list_does_not_accept_vantage() -> None:
    m = _manifest()
    result = _full(
        manifest=m,
        trust=TrustConfig(accepted_producers={m.producer_id: m.digest}),
    )
    assert not result.is_established("vantage_independent")


def test_unaccepted_prior_commitment_is_not_established() -> None:
    manifest = _manifest()
    commitment = _commitment()
    result = _full(
        manifest=manifest,
        prior_commitment=commitment,
        trust=_trust_for(manifest),
    )

    assert not result.is_established("prior_commitment_established")
    assert "prior_commitment_unaccepted" in result.reason_codes


# ── binding (task 6, "Binding") ─────────────────────────────────────────────

def test_matching_ids_but_different_tool_call_hash_rejects() -> None:
    result = _full(binding=_binding(tool_call_hash=H64B))
    assert not result.is_established("invocation_binding_established")
    assert "tool_call_hash_mismatch" in result.reason_codes


def test_ids_copied_into_unrelated_record_do_not_bind() -> None:
    # IDs match, but the proof declares a different tenant than the invocation.
    result = _full(binding=_binding(tenant="globex"))
    assert not result.is_established("invocation_binding_established")
    assert "binding_scope_mismatch" in result.reason_codes


def test_binding_absent_leaves_scope_unestablished() -> None:
    result = _full(binding=None)
    assert not result.is_established("scope_accepted")
    assert not result.is_established("invocation_binding_established")


# ── prior commitment (task 6, "Prior commitment") ───────────────────────────

def test_post_hoc_commitment_is_rejected() -> None:
    result = _full(prior_commitment=_commitment(created_at=450))
    assert not result.is_established("prior_commitment_established")
    assert "prior_commitment_postdates_execution" in result.reason_codes


def test_commitment_for_another_call_does_not_bind() -> None:
    result = _full(prior_commitment=_commitment(tool_call_hash=H64B))
    assert not result.is_established("prior_commitment_established")
    assert "prior_commitment_scope_mismatch" in result.reason_codes


def test_missing_commitment_is_reported_not_assumed() -> None:
    result = _full(prior_commitment=None)
    assert not result.is_established("prior_commitment_established")


# ── derived facts are never caller-asserted ─────────────────────────────────

def test_caller_supplied_fact_names_change_nothing() -> None:
    """expected_invocation carries no premise booleans; adding lookalike keys
    to it must not strengthen anything."""
    poisoned = dict(INVOCATION)
    poisoned["source_accepted"] = True
    poisoned["coverage_complete"] = True
    result = _full(manifest=None, coverage=None, binding=None,
                   vantage=None, prior_commitment=None,
                   expected_invocation=poisoned)
    assert result.is_established("source_accepted") is False
    assert result.is_established("observation_coverage_complete") is False
