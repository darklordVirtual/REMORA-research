# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A deployment's resource ACL registry, for tests: REMORA_FLOW_RESOURCE_ACL_MODULE names it."""
from __future__ import annotations

from typing import Any

from remora.flow.label import PUBLIC

CALLS: list[tuple[str, str]] = []


def resource_acl(tenant: str, resource: str) -> Any:
    CALLS.append((tenant, resource))
    if tenant != "acme":
        return []
    if resource == "res://records/secret":
        return ["user://acme/alice"]
    return PUBLIC
