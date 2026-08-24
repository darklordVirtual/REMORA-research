# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Whether the optional 'security' extra must be present, or may be skipped.

A plain module rather than a conftest helper: conftest is resolved by pytest
per directory, and `tests/meta/conftest.py` shadows the bare name `conftest`
during a full-suite run, so importing the helper from there worked in a single
file and broke on collection of the whole suite.
"""
import importlib
import os

import pytest

__all__ = ["require_security_extra"]


def require_security_extra() -> None:
    """Skip, or fail hard, when the optional 'security' extra is absent.

    Ed25519 lease signing lives behind ``pip install remora[security]``. The
    tests that attack the PDP->PEP custody boundary need it, and how a missing
    dependency should behave differs by context:

    - Local checkout without the extra: skipping is correct. The tests are not
      applicable to that install.
    - CI: skipping is NOT correct. CI once installed ``.[dev,causal,api]`` and
      not ``[security]``, so every Ed25519 test skipped and the adversarial
      evidence for the authority boundary was silently absent from the
      pipeline. The only symptom was a coverage floor -- a missing-evidence
      failure wearing a coverage-failure costume.

    CI therefore sets ``REMORA_REQUIRE_SECURITY_EXTRA=1``, under which a
    missing ``cryptography`` is an ImportError rather than a skip.

    ``importlib.import_module`` rather than a bare ``import cryptography``:
    the import exists only for its failure, so binding a name nobody reads is
    what CodeQL correctly flagged as an unused import (py/unused-import). This
    form has the same effect and no unused binding.
    """
    if os.environ.get("REMORA_REQUIRE_SECURITY_EXTRA", "").strip() in {
        "1", "true",
    }:
        importlib.import_module("cryptography")
    else:
        pytest.importorskip(
            "cryptography",
            reason="Ed25519 lease signing needs the optional 'security' extra",
        )
