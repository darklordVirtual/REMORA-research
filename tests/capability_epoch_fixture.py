# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Revocation epochs for capability sets (REMORA_CAPABILITY_EPOCH_MODULE)."""
from __future__ import annotations

from remora.capabilities import CapabilityEpochs

EPOCHS: dict[str, int] = {"policy": 1, "toolspec": 1, "tenant": 1, "principal": 1}
REVOKED: set[str] = set()
DOWN: dict[str, bool] = {"down": False}


def current(tenant_id: str, principal_id: str) -> CapabilityEpochs:
    if DOWN["down"]:
        raise ConnectionError("epoch store unreachable")
    return CapabilityEpochs(**EPOCHS)


def revoked(capability_set_id: str) -> bool:
    if DOWN["down"]:
        raise ConnectionError("epoch store unreachable")
    return capability_set_id in REVOKED


def reset() -> None:
    EPOCHS.update(policy=1, toolspec=1, tenant=1, principal=1)
    REVOKED.clear()
    DOWN["down"] = False
