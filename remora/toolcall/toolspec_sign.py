# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Offline ToolSpec bundle signing (RMR-CR-001).

Signing a bundle is a release act on the authoring side, not something a
runtime does. A strict runtime refuses to start while it holds ToolSpec
signing material; it verifies with ``REMORA_TOOLSPEC_VERIFY_KEYS`` and
accepts only ``REMORA_TOOLSPEC_PINNED_DIGEST``. This command produces both
values for the runtime from a seed that stays with the signer::

    python -m remora.toolcall.toolspec_sign --seed-file signer.seed \\
        --bundle unsigned.json --out toolspec-bundle.json

Every spec's ``signing_identity`` is set to the key's derived id before
signing, because the id is inside the signed bytes and an Ed25519 signer is
named by its key, never by a label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from remora.crypto import SignatureDomain, SigningKey
from remora.toolcall.toolspec import canonical_signing_bytes, sign_bundle_ed25519

__all__ = ["sign_with_seed", "main"]


def sign_with_seed(
    bundle: Mapping[str, Any], seed: str, *, signed_at: str | None = None
) -> tuple[dict[str, Any], str, str]:
    """(signed bundle, public key hex, pinned digest) for one seed."""
    key = SigningKey.from_text(seed, [SignatureDomain.TOOLSPEC_BUNDLE])
    unsigned = {k: v for k, v in bundle.items() if k != "registry_signature"}
    unsigned["tool_specs"] = [
        {**spec, "signing_identity": key.kid} for spec in bundle.get("tool_specs", [])
    ]
    stamp = signed_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    signed = sign_bundle_ed25519(unsigned, key=key, signed_at=stamp)
    digest = hashlib.sha256(canonical_signing_bytes(signed)).hexdigest()
    return signed, key.verification_key().public_bytes.hex(), digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed-file", type=Path, required=True,
                        help="file holding the 32-byte Ed25519 seed (hex or base64)")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    signed, public, digest = sign_with_seed(
        bundle, args.seed_file.read_text(encoding="utf-8").strip())
    args.out.write_text(json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"REMORA_TOOLSPEC_VERIFY_KEYS={public}")
    print(f"REMORA_TOOLSPEC_PINNED_DIGEST={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
