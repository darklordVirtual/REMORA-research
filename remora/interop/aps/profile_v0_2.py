# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Identifiers frozen by REMORA APS Interop Profile v0.2.

v0.2 is additive. It inherits the v0.1 mappings unchanged, adds an explicit
APS accountability schema-layer parity observation, and maps only P1 (scope
monotonicity) from token-exchange-attenuation-v0 to a genuine REMORA property.
P2 and P3 remain NOT_RUN because REMORA has no upstream-claim policy evaluator
for the external token-exchange family and the adapter must not invent one.
"""

PROFILE_ID = "remora-aps-profile-v0.2"
RUN_MODE = "B"
INHERITS_PROFILE = "remora-aps-profile-v0.1"

INHERITED_FAMILIES = (
    "actionref-canonical",
    "accountability-record",
    "receipt-decision-relation",
    "instruction-provenance",
)

ADDITIONAL_EVIDENCE = (
    "accountability-record:schema-layer-parity",
    "token-exchange-attenuation-v0:P1",
)

NOT_RUN_PROPERTIES = {
    "token-exchange-attenuation-v0": ("P2", "P3"),
}

__all__ = [
    "ADDITIONAL_EVIDENCE",
    "INHERITED_FAMILIES",
    "INHERITS_PROFILE",
    "NOT_RUN_PROPERTIES",
    "PROFILE_ID",
    "RUN_MODE",
]
