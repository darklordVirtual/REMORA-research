# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""``federation-port/v0`` transport (SDD sections 9, 10 and 12, Mode A).

federation-port/v0 (aeoess/federation-port) admits or refuses an action by
asking pinned components for claims. REMORA takes part as a portable verifier
component: the adapter in ``integrations/federation-port/remora-adapter``
receives the evidence bytes this module produces, verifies them with a pinned
public key, and returns only the claims the projection map permits. It holds
no secret, reaches no network and does not run REMORA.

What V0 carries is the action as JavaScript values, a caller-supplied tenant
label, an approval id and per-component evidence bytes. So REMORA's
exact-call binding projects to ``remora.port_v0.bound_action`` (NARROWED),
expiry at admission projects to ``remora.authorization_unexpired``, and
principal binding, custody isolation and effect verification are not
exported. An integer V0 would change (beyond 2^53 - 1) is refused here: the
argument values themselves would not survive.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from remora.crypto import SigningKey
from remora.federation.canonical import javascript_losses
from remora.federation.capabilities import TransportCapabilities
from remora.federation.evidence import envelope_evidence, projection_record
from remora.federation.models import NativeFederationAction
from remora.federation.projection import ClaimProjection, ProjectionError, ProjectionMap
from remora.federation.transports.base import TransportAction

__all__ = ["COMPONENT_ID", "TRANSPORT", "FederationPortV0Transport", "artifact_digest"]

TRANSPORT = "federation-port/v0"
#: The component id of REMORA's adapter in a federation-port customer policy.
COMPONENT_ID = "remora-research/authorization-evidence"
#: Native claims this transport projects, in report order.
NATIVE_CLAIMS = ("authorization_integrity", "exact_call_binding", "fresh_authority_at_dispatch",
                 "principal_binding", "authority_executor_custody_isolation",
                 "effect_verification")


def artifact_digest(base: str | Path, files: list[str]) -> str:
    """federation-port/v0 section 3: files sorted by path, framed path, length, bytes."""
    digest = hashlib.sha256()
    for name in sorted(files):
        data = (Path(base) / name).read_bytes()
        digest.update(f"{name}\n{len(data)}\n".encode())
        digest.update(data)
    return "sha256:" + digest.hexdigest()


class FederationPortV0Transport:
    def __init__(self, *, capabilities: TransportCapabilities, projection_map: ProjectionMap,
                 signing_key: SigningKey, adapter_digest: str, remora_revision: str,
                 transport_revision: str) -> None:
        if capabilities.transport != TRANSPORT:
            raise ProjectionError(f"capabilities are for {capabilities.transport}")
        self._caps = capabilities
        self._map = projection_map
        self._key = signing_key
        self._adapter_digest = adapter_digest
        self._remora_revision = remora_revision
        self._transport_revision = transport_revision

    def capabilities(self) -> TransportCapabilities:
        return self._caps

    def project_claim(self, native_claim: str,
                      native: NativeFederationAction | None = None) -> ClaimProjection:
        losses = javascript_losses(native.arguments) if native is not None else {}
        return self._map.project(native_claim, self._caps, losses)

    def _port_projection(self, native: NativeFederationAction) -> dict[str, Any]:
        authority = native.authority
        if not authority.get("authorization_id"):
            raise ProjectionError("federation-port/v0 binds an approval id; the authority has none")
        if not authority.get("valid_until"):
            raise ProjectionError("federation-port/v0 needs valid_until for its admission deadline")
        return {
            "transport": TRANSPORT,
            "component": COMPONENT_ID,
            "workflow": native.workflow_id,
            "operation_id": native.operation_id,
            "tenant": authority.get("tenant"),
            "approval_id": authority["authorization_id"],
            "valid_until": authority["valid_until"],
            # The arguments as V0 will carry them. A JavaScript reader compares
            # them by value, so 1 and 1.0 match there: that is the narrowing
            # the projection record states, not a native exact-call match.
            "action": {"tool": native.tool, "args": json.loads(json.dumps(native.arguments))},
        }

    def project_action(self, native: NativeFederationAction) -> TransportAction:
        """The V0 request and its evidence, or a refusal when V0 cannot carry the action."""
        losses = javascript_losses(native.arguments)
        if "integer_precision" in losses:
            raise ProjectionError(
                "federation-port/v0 would change integers beyond 2^53 - 1 at "
                f"{losses['integer_precision']}; the argument values do not survive the transport")
        port = self._port_projection(native)
        document = {**native.to_dict(), "transport_projection": port}
        evidence = envelope_evidence(document, self._key)
        native_bytes = json.dumps(native.to_dict(), sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")
        records = [
            projection_record(
                projection=self.project_claim(claim, native).to_dict(), transport=TRANSPORT,
                native_evidence=native_bytes, transport_evidence=evidence,
                adapter_digest=self._adapter_digest, projection_map_digest=self._map.digest,
                capabilities_digest=self._caps.digest, remora_revision=self._remora_revision,
                transport_revision=self._transport_revision)
            for claim in NATIVE_CLAIMS
        ]
        request: dict[str, Any] = {
            "workflow": port["workflow"], "operation_id": port["operation_id"],
            "approval_id": port["approval_id"], "action": port["action"],
        }
        if port["tenant"]:
            request["tenant"] = port["tenant"]
        return TransportAction(transport=TRANSPORT, request=request, evidence=evidence,
                               projection_records=records)
