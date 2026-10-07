# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-001: the ToolSpec trust root is asymmetric under strict profiles.

Before: bundles were HMAC-signed with REMORA_TOOLSPEC_SIGNING_KEY, which the
authority runtime had to hold, so a process that could verify a bundle could
also author one, and signing identities were labels over one shared key.

After: under a strict profile the runtime holds Ed25519 public keys only,
every signer is named by its derived key id, HMAC bundles are refused and the
bundle must match a pinned digest. Outside strict profiles the frozen v1 HMAC
model still works exactly as documented.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey  # noqa: E402
from remora.execution import authorization  # noqa: E402
from remora.scaffold import _demo_spec  # noqa: E402
from remora.toolcall.toolspec import (  # noqa: E402
    ToolSpecBundle,
    ToolSpecRefused,
    canonical_signing_bytes,
    sign_bundle,
)
from remora.toolcall.toolspec_sign import sign_with_seed  # noqa: E402

TOOLSPEC = [SignatureDomain.TOOLSPEC_BUNDLE]
STAMP = "2026-10-07T00:00:00+00:00"


def _unsigned() -> dict:
    return {"schema_version": 1, "tool_specs": [_demo_spec("sha256:" + "0" * 64)]}


def _signed(seed: str | None = None) -> tuple[dict, str, str, SigningKey]:
    key = SigningKey.from_text(seed or SigningKey.generate(TOOLSPEC).seed.hex(), TOOLSPEC)
    bundle, public, digest = sign_with_seed(_unsigned(), key.seed.hex(), signed_at=STAMP)
    return bundle, public, digest, key


def _load(bundle, keys, **kw):
    return ToolSpecBundle.load(bundle, verification_keys=keys, accept_hmac=False, **kw)


# 2 ---------------------------------------------------------------------------
def test_a_valid_ed25519_bundle_loads_and_names_its_signer() -> None:
    bundle, _, digest, key = _signed()
    loaded = _load(bundle, [key.verification_key()], pinned_bundle_digest=digest,
                   require_pinned_digest=True)
    assert loaded.bundle_digest == digest
    assert (loaded.signing_algorithm, loaded.signing_identity) == ("Ed25519", key.kid)
    assert loaded.get("send_notification").signing_identity == key.kid


# 1 ---------------------------------------------------------------------------
def test_a_process_holding_only_the_public_key_cannot_author_an_accepted_bundle() -> None:
    bundle, _, _, key = _signed()
    trusted = [key.verification_key()]
    hostile = copy.deepcopy(bundle)
    hostile["tool_specs"][0]["risk_tier"] = "low"

    # (a) Re-sign under the v1 HMAC model with any key the process could have.
    hmac_forgery = sign_bundle(hostile, key="anything", signing_identity=key.kid,
                               signed_at=STAMP)
    with pytest.raises(ToolSpecRefused) as exc:
        _load(hmac_forgery, trusted)
    assert exc.value.reason_code == "toolspec_signature_algorithm_refused"

    # (b) Sign with a key of its own, but claim the trusted signer's identity.
    own = SigningKey.generate(TOOLSPEC)
    forged = sign_with_seed(hostile, own.seed.hex(), signed_at=STAMP)[0]
    for field in ("signing_identity", "kid"):
        forged["registry_signature"][field] = key.kid
    for spec in forged["tool_specs"]:
        spec["signing_identity"] = key.kid
    with pytest.raises(ToolSpecRefused) as exc:
        _load(forged, trusted)
    assert exc.value.reason_code == "toolspec_signature_invalid"

    # (c) Keep the trusted signature and change the content.
    tampered = copy.deepcopy(bundle)
    tampered["tool_specs"][0]["risk_tier"] = "low"
    with pytest.raises(ToolSpecRefused) as exc:
        _load(tampered, trusted)
    assert exc.value.reason_code == "toolspec_signature_invalid"


# 3 ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    ("tool_specs", 0, "description"),
    ("tool_specs", 0, "allowed_targets"),
    ("schema_version",),
])
def test_any_changed_signed_byte_invalidates_the_signature(path) -> None:
    bundle, _, _, key = _signed()
    target = bundle
    for part in path[:-1]:
        target = target[part]
    value = target[path[-1]]
    target[path[-1]] = (2 if value == 1 else value + ["x"] if isinstance(value, list)
                        else str(value) + " ")
    with pytest.raises(ToolSpecRefused) as exc:
        _load(bundle, [key.verification_key()])
    assert exc.value.reason_code == "toolspec_signature_invalid"


# 4 ---------------------------------------------------------------------------
def test_a_revoked_key_is_refused() -> None:
    bundle, _, _, key = _signed()
    with pytest.raises(ToolSpecRefused) as exc:
        _load(bundle, [key.verification_key()], revoked_identities=[key.kid])
    assert exc.value.reason_code == "toolspec_signing_identity_revoked"


# 5 ---------------------------------------------------------------------------
def test_changing_the_signer_label_cannot_impersonate_a_trusted_key() -> None:
    """The revoked signer relabels its bundle as the still-trusted signer."""
    trusted_bundle, _, _, trusted = _signed()
    revoked_bundle, _, _, revoked = _signed()
    keys = [trusted.verification_key(), revoked.verification_key()]

    relabelled = copy.deepcopy(revoked_bundle)
    relabelled["registry_signature"]["signing_identity"] = trusted.kid
    with pytest.raises(ToolSpecRefused) as exc:
        _load(relabelled, keys, revoked_identities=[revoked.kid])
    assert exc.value.reason_code == "toolspec_signing_identity_mismatch"

    # Relabelling the key id too only makes the trusted key check the
    # signature, and the revoked key's signature does not verify under it.
    relabelled["registry_signature"]["kid"] = trusted.kid
    with pytest.raises(ToolSpecRefused) as exc:
        _load(relabelled, keys, revoked_identities=[revoked.kid])
    assert exc.value.reason_code == "toolspec_signature_invalid"

    assert _load(trusted_bundle, keys, revoked_identities=[revoked.kid])


# 6, 7, 8: through the real environment loader under a strict profile -------
@pytest.fixture
def strict_env(tmp_path, monkeypatch):
    def configure(bundle: dict, *, public: str = "", pin: str | None = "",
                  profile: str = "review", **extra: str) -> None:
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        for name in ("REMORA_TOOLSPEC_SIGNING_KEY", "REMORA_TOOLSPEC_TRUSTED_IDENTITIES",
                     "REMORA_TOOLSPEC_REVOKED_IDENTITIES", "REMORA_TOOLSPEC_PINNED_DIGEST",
                     "REMORA_TOOLSPEC_VERIFY_KEYS", "REMORA_TOOLSPEC_ACCEPT_HMAC"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("REMORA_RUNTIME_PROFILE", profile)
        monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(path))
        if public:
            monkeypatch.setenv("REMORA_TOOLSPEC_VERIFY_KEYS", public)
        if pin:
            monkeypatch.setenv("REMORA_TOOLSPEC_PINNED_DIGEST", pin)
        for name, value in extra.items():
            monkeypatch.setenv(name, value)
        authorization.reset_toolspec_bundle_cache()

    yield configure
    authorization.reset_toolspec_bundle_cache()


def _env_load():
    import os

    return authorization.load_toolspec_bundle(os.environ)


@pytest.mark.parametrize("profile", ["review", "controlled_pilot"])
def test_strict_profile_without_a_pinned_digest_is_refused(strict_env, profile) -> None:
    bundle, public, _, _ = _signed()
    strict_env(bundle, public=public, pin=None, profile=profile)
    with pytest.raises(ToolSpecRefused) as exc:
        _env_load()
    assert exc.value.reason_code == "toolspec_pinned_digest_required"


def test_strict_profile_with_a_wrong_digest_is_refused(strict_env) -> None:
    bundle, public, digest, _ = _signed()
    strict_env(bundle, public=public, pin="0" * 64)
    with pytest.raises(ToolSpecRefused) as exc:
        _env_load()
    assert exc.value.reason_code == "toolspec_bundle_stale"


@pytest.mark.parametrize("compat", ["", "1"])
def test_strict_profile_refuses_a_legacy_hmac_bundle(strict_env, compat) -> None:
    legacy = sign_bundle(_unsigned(), key="k", signing_identity="local-review-signer/v1",
                         signed_at=STAMP)
    digest = hashlib.sha256(canonical_signing_bytes(legacy)).hexdigest()
    _, public, _, _ = _signed()
    extra = {"REMORA_TOOLSPEC_ACCEPT_HMAC": compat} if compat else {}
    strict_env(legacy, public=public, pin=digest,
               REMORA_TOOLSPEC_SIGNING_KEY="k",
               REMORA_TOOLSPEC_TRUSTED_IDENTITIES="local-review-signer/v1", **extra)
    with pytest.raises(ToolSpecRefused) as exc:
        _env_load()
    assert exc.value.reason_code == "toolspec_signature_algorithm_refused"


def test_strict_profile_accepts_the_pinned_ed25519_bundle_and_records_it(
    strict_env, caplog
) -> None:
    bundle, public, digest, key = _signed()
    strict_env(bundle, public=public, pin=digest)
    with caplog.at_level(logging.INFO):
        loaded = _env_load()
    assert loaded is not None and loaded.signing_identity == key.kid
    events = [r for r in caplog.records if "toolspec.bundle_accepted" in r.getMessage()]
    assert events, "the accepted bundle must be recorded as startup evidence"
    text = events[-1].getMessage()
    assert digest in text and key.kid in text


# 9: the documented compatibility mode outside strict profiles ---------------
def test_development_keeps_the_v1_hmac_model_when_no_ed25519_key_is_configured(
    strict_env,
) -> None:
    legacy = sign_bundle(_unsigned(), key="k", signing_identity="local-review-signer/v1",
                         signed_at=STAMP)
    strict_env(legacy, profile="development", REMORA_TOOLSPEC_SIGNING_KEY="k",
               REMORA_TOOLSPEC_TRUSTED_IDENTITIES="local-review-signer/v1")
    loaded = _env_load()
    assert loaded is not None and loaded.signing_algorithm == "HMAC-SHA256"


def test_development_refuses_hmac_once_ed25519_keys_exist_unless_explicitly_allowed(
    strict_env,
) -> None:
    legacy = sign_bundle(_unsigned(), key="k", signing_identity="local-review-signer/v1",
                         signed_at=STAMP)
    _, public, _, _ = _signed()
    common = {"REMORA_TOOLSPEC_SIGNING_KEY": "k",
              "REMORA_TOOLSPEC_TRUSTED_IDENTITIES": "local-review-signer/v1"}
    strict_env(legacy, public=public, profile="development", **common)
    with pytest.raises(ToolSpecRefused) as exc:
        _env_load()
    assert exc.value.reason_code == "toolspec_signature_algorithm_refused"

    strict_env(legacy, public=public, profile="development",
               REMORA_TOOLSPEC_ACCEPT_HMAC="1", **common)
    assert _env_load().signing_algorithm == "HMAC-SHA256"


def test_an_hmac_bundle_never_verifies_without_a_configured_key() -> None:
    """An empty key is a key anyone has."""
    forged = sign_bundle(_unsigned(), key="", signing_identity="local-review-signer/v1",
                         signed_at=STAMP)
    with pytest.raises(ToolSpecRefused) as exc:
        ToolSpecBundle.load(forged, key="", trusted_identities=["local-review-signer/v1"])
    assert exc.value.reason_code == "toolspec_signature_algorithm_refused"
