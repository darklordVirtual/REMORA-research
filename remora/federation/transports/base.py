# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The transport plugin interface (SDD section 11).

A transport turns a native action into what it can carry, projects native
claims through its capability declaration, and states its evidence. Adding a
transport adds an implementation of this protocol; it changes no native
REMORA primitive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from remora.federation.capabilities import TransportCapabilities
from remora.federation.models import NativeFederationAction
from remora.federation.projection import ClaimProjection

__all__ = ["FederationTransport", "TransportAction"]


@dataclass(frozen=True)
class TransportAction:
    """What one transport carries for one native action, and the evidence for it."""

    transport: str
    request: dict[str, Any]
    evidence: bytes
    projection_records: list[dict[str, Any]] = field(default_factory=list)


class FederationTransport(Protocol):
    def capabilities(self) -> TransportCapabilities: ...

    def project_action(self, native: NativeFederationAction) -> TransportAction: ...

    def project_claim(self, native_claim: str,
                      native: NativeFederationAction | None = None) -> ClaimProjection: ...
