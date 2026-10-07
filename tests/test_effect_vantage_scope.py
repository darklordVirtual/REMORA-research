# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-008: an effect verdict carries its vantage and its scope.

``EFFECT_VERIFIED`` is an attestation, by a verifier the deployment
allowlists, that the DECLARED delta is present. It is not independent
confirmation, and it says nothing about fields the postcondition did not
declare. The record states both: ``vantage`` (``same_deployment`` unless
independence is derived) and ``scope`` (``declared_delta_only``).

``independent`` is never taken from the verifier's own word. It is set only
from an :class:`ObservationVantage` whose independence is derived as
INDEPENDENT; anything else stays ``same_deployment``.
"""
from __future__ import annotations

import pytest

from remora.evidence.admission import ObservationVantage
from remora.governance.effect_verification import (
    SCOPE_DECLARED_DELTA_ONLY,
    VANTAGE_INDEPENDENT,
    VANTAGE_SAME_DEPLOYMENT,
    EffectStatus,
    EffectVerification,
    PostconditionContract,
    verify_declared_delta,
)


def _verified() -> EffectVerification:
    contract = PostconditionContract(tool_id="t", reader="r", target_selector={},
                                     expected_fields={"status": "closed"})
    return verify_declared_delta(contract, {"status": "closed", "other": 1},
                                 proposal_id="p", execution_id="e", toolspec_hash="h",
                                 verifier_identity="reader/v1")


def test_every_record_names_its_vantage_and_scope() -> None:
    record = _verified()
    assert record.status is EffectStatus.VERIFIED
    out = record.to_dict()
    assert out["vantage"] == VANTAGE_SAME_DEPLOYMENT
    assert out["scope"] == SCOPE_DECLARED_DELTA_ONLY


def test_an_undeclared_field_is_outside_the_stated_scope() -> None:
    """'other' changed and the verdict is VERIFIED: the scope says why."""
    assert _verified().to_dict()["scope"] == "declared_delta_only"


@pytest.mark.parametrize("field, value", [("vantage", "independent-ish"),
                                          ("vantage", VANTAGE_INDEPENDENT),
                                          ("scope", "everything")])
def test_a_vantage_or_scope_cannot_be_asserted(field, value) -> None:
    import dataclasses

    with pytest.raises(ValueError):
        dataclasses.replace(_verified(), **{field: value})


def _vantage(**over) -> ObservationVantage:
    base = dict(observer_id="auditor", observed_party="deployment-a",
                control_domain="audit-org", observed_control_domain="ops-org",
                can_observed_party_forge=False, can_observed_party_suppress=False)
    base.update(over)
    return ObservationVantage(**base)


def test_independence_is_derived_never_declared() -> None:
    assert _verified().observed_from(_vantage()).vantage == VANTAGE_INDEPENDENT
    same_domain = _vantage(control_domain="ops-org")
    assert _verified().observed_from(same_domain).vantage == VANTAGE_SAME_DEPLOYMENT
    forgeable = _vantage(can_observed_party_forge=True, declared_independence=True)
    assert _verified().observed_from(forgeable).vantage == VANTAGE_SAME_DEPLOYMENT
