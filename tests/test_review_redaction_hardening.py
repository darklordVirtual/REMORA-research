# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings: value redaction must catch quoted, vendor-prefixed and nested secrets."""
from __future__ import annotations

import pytest

from remora.observability.redaction import MARKER, redact_field, redact_text

# Assembled at import so no credential-shaped literal is committed.
SK = "sk-" + "abcdef123456789"
ANT = "sk-ant-" + "api03-AbCdEfGhIjKlMnOpQrStUv"
AKIA = "AKIA" + "IOSFODNN7EXAMPLE"
GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
XOX = "xoxb-" + "123456789012-abcdefghijkl"


@pytest.mark.parametrize(
    "text, secret",
    [
        ('{"password": "hunter2secret"}', "hunter2secret"),
        ('{"api_key":"' + SK + '"}', SK),
        ("api_key " + SK, SK),
        ("failed with " + ANT, ANT),
        ("key " + AKIA + " rejected", AKIA),
        ("token leaked " + GHP, GHP),
        ("slack " + XOX, XOX),
        ("password='hun ter2'", "ter2"),
        ('password="hun ter2" next', "ter2"),
    ],
)
def test_secret_shapes_are_redacted(text, secret):
    out = redact_text(text)
    assert secret not in out
    assert MARKER in out


def test_quoted_value_with_space_leaves_no_residue():
    assert "'" not in redact_text("password='hun ter2'").replace(MARKER, "")


def test_structured_values_are_redacted_recursively():
    out = redact_field("payload", {"headers": {"a": "Bearer abcdefgh12345678"}, "l": [SK]})
    assert "abcdefgh12345678" not in repr(out)
    assert SK not in repr(out)


def test_exception_values_are_redacted():
    out = redact_field("error", RuntimeError("Bearer abcdefgh12345678"))
    assert "abcdefgh12345678" not in str(out)


def test_id_and_hash_fields_still_pass_digests_but_not_credentials():
    digest = "a" * 64
    assert redact_field("tool_call_hash", digest) == digest
    assert redact_field("proposal_id", "prop-123") == "prop-123"
    assert SK not in str(redact_field("request_id", "x " + SK))
    assert "abcdefgh12345678" not in str(
        redact_field("call_hash", "Authorization: Bearer abcdefgh12345678 " + SK)
    )
