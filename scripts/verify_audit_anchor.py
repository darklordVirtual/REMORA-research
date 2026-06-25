#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""External verifier for REMORA audit anchor records."""
from __future__ import annotations

import argparse
import json
import os

from remora.audit.anchor import AnchorRecord, AuditAnchor, verify_anchor_signature


def _load_anchor_record(path: str) -> AnchorRecord:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return AnchorRecord(**payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify REMORA audit anchor record")
    parser.add_argument("--audit-jsonl", required=True, help="Path to hash-linked audit JSONL")
    parser.add_argument("--anchor-record", required=True, help="Path to exported anchor record JSON")
    parser.add_argument(
        "--key-env",
        default="REMORA_AUDIT_ANCHOR_KEY",
        help="Environment variable containing HMAC signing key",
    )
    args = parser.parse_args()

    expected = _load_anchor_record(args.anchor_record)
    observed = AuditAnchor(args.audit_jsonl).anchor()

    mismatches: list[str] = []
    for key in ("root_hash", "entry_count", "chain_valid", "broken_at_index", "error_message"):
        if getattr(expected, key) != getattr(observed, key):
            mismatches.append(
                f"{key}: expected={getattr(expected, key)!r} observed={getattr(observed, key)!r}"
            )

    if mismatches:
        print("anchor verification failed: chain mismatch")
        for mismatch in mismatches:
            print(f" - {mismatch}")
        return 1

    if expected.signature:
        signing_key = os.getenv(args.key_env)
        if not signing_key:
            print(f"anchor verification failed: env var {args.key_env} is missing")
            return 2
        if not verify_anchor_signature(expected, signing_key=signing_key):
            print("anchor verification failed: signature mismatch")
            return 1

    print("anchor verification succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
