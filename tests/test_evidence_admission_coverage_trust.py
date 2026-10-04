# SPDX-License-Identifier: BUSL-1.1
"""Coverage attestations must be accepted by deployment-owned trust.

Before this slice, ``observation_coverage_complete`` could be ESTABLISHED by
any ``CoverageAttestation`` that named an accepted producer, the right
invocation, ``COMPLETE`` and a matching field set and interval. The
attestation's own digest was never compared with anything the deployment
holds, so a fabricated or mutated statement from (or in the name of) an
accepted producer passed on content alone. The repair: the deployment's
``TrustConfig.accepted_coverage`` maps a producer to the attestation digests
it has accepted, and an attestation whose digest is not in that set for its
producer is ``coverage_attestation_unaccepted``, whatever its content says.

Every test here pins the fail-closed direction; none of them can make the
layer establish more than before.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.evidence.admission import (
    CoverageAttestation,
    CoverageState,
    EvidenceAdmission,
    TrustConfig,
    admit_evidence,
)
from remora.evidence.admission.admission import FACT_NAMES
from remora.evidence.admission.reasons import REASON_CODES
from tests.test_evidence_admission_adversarial import (
    EXEC_STARTED,
    FIELDS,
    INTERVAL,
    INVOCATION,
    NOW,
    _binding,
    _commitment,
    _coverage,
    _manifest,
    _vantage,
)

UNACCEPTED = "coverage_attestation_unaccepted"


def _trust(
    manifest,
    accepted: tuple[CoverageAttestation, ...] = (),
    *,
    commitment=None,
    coverage_producer: str | None = None,
) -> TrustConfig:
    """Deployment trust that accepts ``manifest`` and exactly ``accepted``."""
    producer = coverage_producer or manifest.producer_id
    return TrustConfig(
        accepted_producers={manifest.producer_id: manifest.digest},
        accepted_prior_commitments=(
            {commitment.commitment_id: commitment.digest} if commitment else {}
        ),
        trusted_vantage_domains=("deployer-b",),
        accepted_coverage={producer: tuple(c.digest for c in accepted)},
    )


def _admit(*, manifest=None, coverage, trust, **overrides) -> EvidenceAdmission:
    manifest = manifest or _manifest()
    kwargs = dict(
        manifest=manifest,
        coverage=coverage,
        vantage=None,
        binding=None,
        prior_commitment=None,
        trust=trust,
        expected_invocation=INVOCATION,
        execution_started_at=EXEC_STARTED,
        evaluated_fields=FIELDS,
        evaluated_interval=INTERVAL,
        now=NOW,
    )
    kwargs.update(overrides)
    return admit_evidence(**kwargs)


# ── 1. the accepted exact statement still establishes coverage ─────────────

def test_accepted_exact_coverage_establishes_coverage_when_premises_hold() -> None:
    manifest, coverage = _manifest(), _coverage()
    result = _admit(manifest=manifest, coverage=coverage,
                    trust=_trust(manifest, (coverage,)))

    assert result.is_established("observation_coverage_complete")
    assert UNACCEPTED not in result.reason_codes


# ── 2-6. the same producer, the statement changed after trust was recorded ─

@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(dict(state=CoverageState.INCOMPLETE), id="complete-to-incomplete"),
        pytest.param(dict(fields=("effect",)), id="field-removed"),
        pytest.param(dict(interval_end=150), id="interval-shortened"),
        pytest.param(dict(invocation_id="inv-2"), id="invocation-changed"),
        # These three still satisfy every content check; only the digest
        # tells them apart from the accepted statement.
        pytest.param(dict(interval_start=90, interval_end=210), id="interval-widened"),
        pytest.param(dict(fields=FIELDS + ("extra",)), id="field-added"),
        pytest.param(dict(provenance_ref="collector://other"), id="provenance-changed"),
    ],
)
def test_mutated_attestation_loses_acceptance(mutation) -> None:
    manifest, accepted = _manifest(), _coverage()
    mutated = _coverage(**mutation)
    assert mutated.digest != accepted.digest

    result = _admit(manifest=manifest, coverage=mutated,
                    trust=_trust(manifest, (accepted,)))

    assert not result.is_established("observation_coverage_complete")
    assert result.is_established("source_accepted")


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(dict(interval_start=90, interval_end=210), id="interval-widened"),
        pytest.param(dict(fields=FIELDS + ("extra",)), id="field-added"),
        pytest.param(dict(provenance_ref="collector://other"), id="provenance-changed"),
    ],
)
def test_content_valid_but_unaccepted_statement_names_the_reason(mutation) -> None:
    manifest, accepted = _manifest(), _coverage()
    result = _admit(manifest=manifest, coverage=_coverage(**mutation),
                    trust=_trust(manifest, (accepted,)))

    assert UNACCEPTED in result.reason_codes
    assert "coverage_incomplete" not in result.reason_codes
    assert "coverage_scope_mismatch" not in result.reason_codes


# ── 7. fabricated COMPLETE statement in an accepted producer's name ────────

def test_fabricated_complete_attestation_from_accepted_producer_is_unaccepted() -> None:
    manifest = _manifest()
    genuine = _coverage(provenance_ref="collector://run/1")
    fabricated = _coverage()  # same producer, same invocation, COMPLETE
    assert fabricated.digest != genuine.digest

    result = _admit(manifest=manifest, coverage=fabricated,
                    trust=_trust(manifest, (genuine,)))

    assert not result.is_established("observation_coverage_complete")
    assert UNACCEPTED in result.reason_codes
    # The producer itself is still accepted; only the statement is not.
    assert result.is_established("source_accepted")
    assert result.is_established("producer_visibility_established")


# ── 8. missing trust material fails closed ─────────────────────────────────

def test_no_accepted_coverage_material_fails_closed() -> None:
    manifest, coverage = _manifest(), _coverage()
    trust_without_coverage = TrustConfig(
        accepted_producers={manifest.producer_id: manifest.digest},
        trusted_vantage_domains=("deployer-b",),
    )
    result = _admit(manifest=manifest, coverage=coverage, trust=trust_without_coverage)

    assert not result.is_established("observation_coverage_complete")
    assert UNACCEPTED in result.reason_codes


def test_digest_accepted_for_another_producer_does_not_transfer() -> None:
    manifest, coverage = _manifest(), _coverage()
    result = _admit(manifest=manifest, coverage=coverage,
                    trust=_trust(manifest, (coverage,), coverage_producer="collector-9"))

    assert not result.is_established("observation_coverage_complete")
    assert UNACCEPTED in result.reason_codes


def test_accepted_coverage_is_frozen_and_never_read_from_evidence() -> None:
    manifest, coverage = _manifest(), _coverage()
    trust = _trust(manifest, (coverage,))
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        trust.accepted_coverage[manifest.producer_id] = ()  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        trust.accepted_coverage = {}  # type: ignore[misc]
    # The attestation carries no field that could stand in for acceptance.
    assert not any(
        name in {"accepted", "trusted", "trust", "accepted_by"}
        for name in (f.name for f in dataclasses.fields(coverage))
    )


# ── C4 as documented: the producer must be able to see what it attests ────

def test_coverage_beyond_producer_visibility_is_not_complete() -> None:
    manifest = _manifest(fields_visible=("effect",))
    coverage = _coverage()  # attests both fields; the producer can see one
    result = _admit(manifest=manifest, coverage=coverage,
                    trust=_trust(manifest, (coverage,)))

    assert result.is_established("source_accepted")
    assert not result.is_established("producer_visibility_established")
    assert not result.is_established("observation_coverage_complete")


# ── 9. coverage acceptance alone never establishes an observed effect ──────

def test_accepted_coverage_alone_never_establishes_an_observed_effect() -> None:
    manifest, coverage = _manifest(), _coverage()
    result = _admit(manifest=manifest, coverage=coverage,
                    trust=_trust(manifest, (coverage,)))

    assert result.is_established("observation_coverage_complete")
    assert not result.is_established("effect_observation_accepted")
    assert "effect_observation_not_supplied" in result.reason_codes


# ── 10. no result creates execution authority; the vocabulary only grew ───

def test_acceptance_adds_a_reason_code_and_no_fact_and_no_authority_field() -> None:
    assert UNACCEPTED in REASON_CODES
    assert set(FACT_NAMES) == {
        "source_accepted", "scope_accepted", "producer_visibility_established",
        "observation_coverage_complete", "effect_observation_accepted",
        "same_protected_operation", "vantage_independent",
        "invocation_binding_established", "prior_commitment_established",
    }
    manifest, coverage, commitment = _manifest(), _coverage(), _commitment()
    full = _admit(
        manifest=manifest, coverage=coverage, vantage=_vantage(), binding=_binding(),
        prior_commitment=commitment,
        trust=_trust(manifest, (coverage,), commitment=commitment),
    )
    field_names = {f.name for f in dataclasses.fields(full)}
    assert field_names == {
        "processing", "reason_codes", "established_facts", "evidence_digest", "scope",
    }
    assert not any(
        token in name
        for name in field_names
        for token in ("authority", "lease", "token", "decision", "verdict", "allow")
    )


# ── erasure monotonicity holds across the new trust input ─────────────────

def test_removing_accepted_coverage_never_strengthens_any_fact() -> None:
    manifest, coverage, commitment = _manifest(), _coverage(), _commitment()
    common = dict(manifest=manifest, coverage=coverage, vantage=_vantage(),
                  binding=_binding(), prior_commitment=commitment)
    with_trust = _admit(trust=_trust(manifest, (coverage,), commitment=commitment), **common)
    without = _admit(trust=_trust(manifest, (), commitment=commitment), **common)

    for name, status in without.established_facts.items():
        if status.name == "ESTABLISHED":
            assert with_trust.established_facts[name].name == "ESTABLISHED", name
    assert with_trust.is_established("observation_coverage_complete")
    assert not without.is_established("observation_coverage_complete")
