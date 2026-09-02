# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Identifiers frozen by REMORA APS Interop Profile v0.1."""

PROFILE_ID = "remora-aps-profile-v0.1"
RUN_MODE = "B"
FAMILIES = (
    "actionref-canonical",
    "accountability-record",
    "receipt-decision-relation",
    "instruction-provenance",
)

__all__ = ["FAMILIES", "PROFILE_ID", "RUN_MODE"]
