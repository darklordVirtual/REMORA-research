# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Transport capability declarations (SDD section 8).

Every transport states what it can actually carry, as data. The projection
engine derives the strongest permissible exported claim from these
capabilities; an adapter cannot raise it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from remora.policy.observation import _canonical_json

__all__ = ["CAPABILITIES_SCHEMA", "TransportCapabilities", "load_capabilities"]

CAPABILITIES_SCHEMA = "remora-federation-transport-capabilities-v1"
#: A capability is true, false, or "partial", which counts as not supplied.
_VALUES = (True, False, "partial")


@dataclass(frozen=True)
class TransportCapabilities:
    transport: str
    revision: str
    capabilities: dict[str, Any]
    digest: str

    def supplies(self, capability: str) -> bool:
        """True only for an explicit ``true``. Absent, false and partial do not supply."""
        return self.capabilities.get(capability) is True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransportCapabilities":
        if data.get("schema_version") != CAPABILITIES_SCHEMA:
            raise ValueError(f"capabilities schema must be {CAPABILITIES_SCHEMA}")
        caps = data.get("capabilities")
        if not isinstance(caps, dict) or not caps:
            raise ValueError("capabilities must be a non-empty mapping")
        bad = {k: v for k, v in caps.items() if v not in _VALUES or isinstance(v, int) and
               not isinstance(v, bool)}
        if bad:
            raise ValueError(f"capability values must be true, false or partial: {bad}")
        return cls(transport=str(data["transport"]), revision=str(data.get("revision", "")),
                   capabilities=dict(caps),
                   digest="sha256:" + hashlib.sha256(
                       _canonical_json(data).encode("utf-8")).hexdigest())


def load_capabilities(path: str | Path) -> TransportCapabilities:
    with open(path, encoding="utf-8") as fh:
        return TransportCapabilities.from_dict(yaml.safe_load(fh))
