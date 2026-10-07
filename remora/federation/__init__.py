# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA Federation Bridge: loss-aware projection of native assurance.

REMORA's native claims are stronger than some federation transports can
carry. The bridge never weakens a native claim to fit a transport, and never
reports a transport-level result as the native one. It projects:

    native claim -> PRESERVED | NARROWED | NOT_ESTABLISHED | UNSUPPORTED

and a projection can only weaken. The mapping is data
(``artifacts/interop/<transport>/projection-map.yaml``), the transport's
capabilities are data (``capabilities.yaml``), and every result carries a
projection record naming what survived and what did not.

The bridge consumes REMORA's native mechanisms; it replaces none of them.
Design: ``docs/interop/FEDERATION_BRIDGE.md``.
"""
from remora.federation.canonical import (
    CANONICALIZATION,
    CanonicalArguments,
    canonical_arguments,
    javascript_losses,
)
from remora.federation.capabilities import TransportCapabilities, load_capabilities
from remora.federation.lifecycle import transport_outcome
from remora.federation.models import NativeFederationAction
from remora.federation.projection import (
    PROJECTION_RESULTS,
    ClaimProjection,
    ProjectionError,
    ProjectionMap,
    load_projection_map,
)

__all__ = [
    "CANONICALIZATION",
    "PROJECTION_RESULTS",
    "CanonicalArguments",
    "ClaimProjection",
    "NativeFederationAction",
    "ProjectionError",
    "ProjectionMap",
    "TransportCapabilities",
    "canonical_arguments",
    "javascript_losses",
    "load_capabilities",
    "load_projection_map",
    "transport_outcome",
]
