"""AssuranceEnvelope — stronger audit wrapper around AssuranceTrace.

Adds config hash, model pool hash, policy hash, and a signature standard.
This is NOT a cryptographic signature — it is a tamper-evident hash envelope.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AssuranceEnvelope:
    root_hash: str              # Merkle root of the consensus log (from AssuranceTrace)
    config_hash: str            # SHA-256 of the serialised Genome config
    model_pool_hash: str        # SHA-256 of sorted list of oracle provider IDs
    policy_hash: str            # SHA-256 of the policy_decision dict (if present)
    leaf_count: int
    signature_standard: str = "REMORA-AssuranceEnvelope-v1-unsigned"
    # "unsigned" is explicit: no private-key signature has been applied


def _sha256_dict(d: dict) -> str:
    """Stable SHA-256 of a dict: sorted keys, compact JSON."""
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256_list(items: list[str]) -> str:
    """Stable SHA-256 of a sorted list of strings."""
    return hashlib.sha256(
        json.dumps(sorted(items), separators=(",", ":")).encode()
    ).hexdigest()


def build_envelope(
    trace_root_hash: str,
    leaf_count: int,
    genome_dict: dict,
    oracle_provider_ids: list[str],
    policy_decision: dict | None = None,
) -> AssuranceEnvelope:
    """Build an AssuranceEnvelope from a trace root and config data.

    genome_dict: serialisable dict of the Genome (use genome.__dict__ or dataclasses.asdict)
    oracle_provider_ids: list of oracle provider ID strings
    policy_decision: the policy_decision dict from report(), or None
    """
    config_hash = _sha256_dict(genome_dict)
    model_pool_hash = _sha256_list(oracle_provider_ids)
    policy_hash = _sha256_dict(policy_decision) if policy_decision is not None else _sha256_dict({})
    return AssuranceEnvelope(
        root_hash=trace_root_hash,
        config_hash=config_hash,
        model_pool_hash=model_pool_hash,
        policy_hash=policy_hash,
        leaf_count=leaf_count,
    )
