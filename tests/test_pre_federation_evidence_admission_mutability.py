# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation probes for evidence-admission scope immutability."""
from __future__ import annotations

from remora.evidence.admission.admission import TrustConfig, admit_evidence
from remora.evidence.admission.models import (
    ManifestTrust,
    ProducerCapabilityManifest,
)


def test_accepted_manifest_digest_cannot_be_reused_after_nested_scope_mutation():
    """An accepted content digest must bind the exact scope later admitted."""
    source_scope = {"resource": {"tenant": "acme"}}
    manifest = ProducerCapabilityManifest(
        producer_id="collector-1",
        manifest_id="m-1",
        schema_version="v1",
        fields_visible=("status",),
        scope=source_scope,
        trust=ManifestTrust.ACCEPTED,
        valid_from=0,
        valid_until=1000,
    )
    accepted_digest = manifest.digest
    trust = TrustConfig(
        accepted_producers={"collector-1": accepted_digest},
    )

    # Mutate through the caller-owned nested alias after the deployment has
    # accepted the original digest.
    source_scope["resource"]["tenant"] = "globex"

    result = admit_evidence(
        manifest=manifest,
        coverage=None,
        vantage=None,
        binding=None,
        prior_commitment=None,
        trust=trust,
        expected_invocation={"resource": {"tenant": "globex"}},
        execution_started_at=100,
        evaluated_fields=("status",),
        evaluated_interval=(100, 101),
        now=200,
    )
    assert not result.is_established("producer_visibility_established"), (
        "manifest content changed after its accepted digest was computed, "
        "but the old digest still authorized visibility in the new scope"
    )


def test_manifest_scope_still_hashes_to_the_digest_trust_accepted():
    source_scope = {"resource": {"tenant": "acme"}}
    manifest = ProducerCapabilityManifest(
        producer_id="collector-1",
        manifest_id="m-1",
        schema_version="v1",
        fields_visible=("status",),
        scope=source_scope,
        trust=ManifestTrust.ACCEPTED,
        valid_from=0,
        valid_until=1000,
    )
    source_scope["resource"]["tenant"] = "globex"

    rebuilt = ProducerCapabilityManifest(
        producer_id=manifest.producer_id,
        manifest_id=manifest.manifest_id,
        schema_version=manifest.schema_version,
        fields_visible=manifest.fields_visible,
        scope=dict(manifest.scope),
        trust=manifest.trust,
        valid_from=manifest.valid_from,
        valid_until=manifest.valid_until,
        provenance_ref=manifest.provenance_ref,
    )
    assert rebuilt.digest == manifest.digest, (
        "the live manifest scope no longer corresponds to the digest carried "
        "by the supposedly immutable record"
    )


def test_admission_report_scope_cannot_drift_through_expected_invocation_alias():
    invocation = {"resource": {"tenant": "acme"}}
    result = admit_evidence(
        manifest=None,
        coverage=None,
        vantage=None,
        binding=None,
        prior_commitment=None,
        trust=TrustConfig(),
        expected_invocation=invocation,
        execution_started_at=100,
        evaluated_fields=(),
        evaluated_interval=(100, 101),
        now=200,
    )
    invocation["resource"]["tenant"] = "globex"
    assert result.scope["resource"]["tenant"] == "acme", (
        "an already-produced admission report changed scope after evaluation"
    )
