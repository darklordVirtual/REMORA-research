# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Cryptographic primitives shared across REMORA's signed artifacts.

A leaf package: it imports nothing from the rest of ``remora`` except the
error base, so ``toolcall`` (which must not import ``enforcement``) and
``enforcement`` can both depend on it without changing the import direction.
"""
from remora.crypto.domain_signing import (
    ALGORITHM,
    Signature,
    SignatureDomain,
    SigningKey,
    SigningUnavailable,
    VerificationKey,
    VerificationResult,
    derive_kid,
    preimage,
    sign,
    verify,
)

__all__ = [
    "ALGORITHM",
    "Signature",
    "SignatureDomain",
    "SigningKey",
    "SigningUnavailable",
    "VerificationKey",
    "VerificationResult",
    "derive_kid",
    "preimage",
    "sign",
    "verify",
]
