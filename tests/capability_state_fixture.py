# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Trusted state for capability constraints (REMORA_CAPABILITY_STATE_MODULE)."""
from __future__ import annotations

from typing import Any

INVOICES: dict[str, dict[str, Any]] = {
    "4711": {"status": "APPROVED", "authorized_recipient": "supplier-381"},
    "4712": {"status": "PENDING", "authorized_recipient": "supplier-9"},
}


def read(source: str, arguments: Any) -> Any:
    record = INVOICES[str(arguments["invoice"])]
    return {"invoice.status": record["status"],
            "invoice.authorized_recipient": record["authorized_recipient"]}[source]
