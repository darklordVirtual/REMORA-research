# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-003: a governance log line must not carry a credential or a location.

The module's first design constraint is "never log a secret". It screened field
NAMES, which is a rule a reviewer can check by reading a call site, and it is
the right rule for structured fields. It is the wrong rule for
``detail=str(exc)``: the field name is innocent and the value is whatever a
downstream library chose to put in an exception message.

These tests drive the emitter with exception text of the shape that actually
occurs — bearer tokens, JWTs, connection strings, absolute paths, internal
hostnames — and assert that none of it reaches any handler.
"""
from __future__ import annotations

import logging

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.observability.events import governance_event
from remora.observability.redaction import MARKER, redact_field, redact_text

#: A probe value, not a credential. The name matters: a constant called PROBE
#: flowing into a logging call is a true clear-text-logging dataflow as far as
#: static analysis is concerned, and the analysis is right about the flow and
#: wrong about the thing. This value exists to prove it gets redacted.
PROBE = "PROBE-NOT-A-REAL-CREDENTIAL-a1b2c3d4e5f6"

#: Assembled at import rather than written out, so no JWT-shaped literal is
#: committed. A secret scanner that has been taught to ignore one is a scanner
#: with a hole in it, and the hole outlives the test.
JWT_SHAPED = ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NSJ9", PROBE])


@pytest.fixture
def captured(caplog):
    caplog.set_level(logging.DEBUG, logger="remora.governance")
    return caplog


def emitted_text(captured) -> str:
    """Everything a handler could see: the rendered line and the structured extra."""

    parts = []
    for record in captured.records:
        parts.append(record.getMessage())
        parts.append(repr(getattr(record, "remora", {})))
    return "\n".join(parts)


@pytest.mark.parametrize(
    "leak",
    [
        f"Authorization: Bearer {PROBE}",
        f"token {PROBE}",
        JWT_SHAPED,
        f"api_key={PROBE}",
        f"password: {PROBE}",
        f"signing_key = {PROBE}",
        f"postgresql://remora:{PROBE}@db.internal:5432/chain",
        "/srv/private/config/authority.key",
        r"C:\Secrets\authority.key",
        "https://vault.internal/v1/secret/data/remora",
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "connect failed to broker.corp",
    ],
)
def test_no_leak_shape_survives_the_emitter(captured, leak):
    governance_event("dispatch.tool_raised", detail=f"RuntimeError: {leak}")
    text = emitted_text(captured)
    assert PROBE not in text
    assert MARKER in text


def test_the_exact_probe_from_the_review_is_redacted(captured):
    governance_event(
        "dispatch.tool_raised",
        tenant_id="t1",
        detail=(
            f"RuntimeError: Bearer {PROBE} "
            "host=internal.local path=/srv/private/config"
        ),
    )
    text = emitted_text(captured)
    assert PROBE not in text
    assert "/srv/private/config" not in text
    assert "internal.local" not in text
    assert "t1" in text, "redaction must not eat ordinary identifiers"


def test_identifiers_and_digests_are_not_redacted(captured):
    digest = "a" * 64
    governance_event(
        "grant.checked",
        tool_call_hash=digest,
        proposal_id="prop-123",
        jti="9f8e7d6c5b4a39281706",
        policy_bundle_hash="b" * 40,
    )
    text = emitted_text(captured)
    assert digest in text
    assert "prop-123" in text
    assert "9f8e7d6c5b4a39281706" in text


def test_non_string_values_pass_through_untouched():
    assert redact_field("count", 7) == 7
    assert redact_field("allowed", True) is True
    assert redact_field("ratio", 0.5) == 0.5


@settings(max_examples=200, deadline=None)
@given(
    prefix=st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Zs")), max_size=30),
    secret=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=12,
        max_size=48,
    ),
    suffix=st.text(alphabet=st.characters(whitelist_categories=("Ll", "Zs")), max_size=30),
)
def test_a_bearer_token_never_survives_wherever_it_sits(prefix, secret, suffix):
    """The credential is generated, so the test cannot be passing on a fixture.

    The property is that the credential does not survive as a credential. A
    generated prefix may coincidentally equal the secret text, and that
    coincidence is not a leak, so the assertion is on the bearer run itself.
    """

    text = f"{prefix} Bearer {secret} {suffix}"
    assert f"Bearer {secret}" not in redact_text(text)


@settings(max_examples=200, deadline=None)
@given(
    key=st.sampled_from(["api_key", "password", "secret", "token", "private_key", "auth"]),
    sep=st.sampled_from(["=", ": ", " = ", ":"]),
    value=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=8, max_size=40
    ),
)
def test_an_assigned_credential_never_survives(key, sep, value):
    assert value not in redact_text(f"failed: {key}{sep}{value} while connecting")


def test_ordinary_prose_is_left_alone():
    """Redaction that eats the message defeats the point of logging it."""

    prose = "tool raised: connection reset by peer after 3 attempts"
    assert redact_text(prose) == prose
