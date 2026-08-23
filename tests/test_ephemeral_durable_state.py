# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The durability guard must reject storage that does not survive a restart.

Found by deploying to Cloudflare Containers on 2026-08-23. The production
check required ``REMORA_PG_DSN`` or ``REMORA_CHAIN_DB`` and refused to start
without one — but it accepted a ``REMORA_CHAIN_DB`` path on the container's
own writable layer, which is discarded when the instance restarts.

The consequence is not a lost audit trail. The one-time-grant ledger is the
thing that refuses a replayed grant; when it disappears, a grant already
consumed is accepted again. The check passed while providing none of the
guarantee it exists to provide.

The guard was testing whether a path had been *configured*, not whether the
storage behind it *persists*. These tests pin the difference.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from servers import api as api_module  # noqa: E402


@pytest.fixture()
def api(monkeypatch):
    """The api module with production prerequisites satisfied except storage."""
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_ENABLED_SURFACES", "execution")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "t")
    monkeypatch.setenv("REMORA_API_TOKENS", '{"t":{"tenant":"a","role":"operator"}}')
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://x/y")
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", "k")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "k")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "k")
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "k")
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    return api_module


# ── the filesystem probe ────────────────────────────────────────────────────

@pytest.mark.parametrize("fstype", ["overlay", "overlayfs", "tmpfs", "ramfs", "aufs"])
def test_container_writable_layers_are_ephemeral(fstype):
    assert api_module.is_ephemeral_filesystem_type(fstype) is True


@pytest.mark.parametrize("fstype", ["ext4", "xfs", "btrfs", "zfs", "nfs4", "ext3"])
def test_real_filesystems_are_not_ephemeral(fstype):
    assert api_module.is_ephemeral_filesystem_type(fstype) is False


def test_unknown_filesystem_type_is_not_called_ephemeral():
    """A guard that guesses is worse than one that says it does not know.

    Refusing an unrecognised filesystem would break every deployment on
    storage this list has not heard of. The uncertainty is reported, not
    resolved by assumption.
    """
    assert api_module.is_ephemeral_filesystem_type("some-future-fs") is False
    assert api_module.is_ephemeral_filesystem_type(None) is False


def test_filesystem_type_resolves_the_nearest_existing_ancestor(tmp_path, monkeypatch):
    """The database file does not exist yet on a first start.

    The check must look at the directory it would be created in rather than
    give up because the file is absent.
    """
    seen: list[str] = []

    def fake_lookup(path):
        seen.append(str(path))
        return "ext4"

    monkeypatch.setattr(api_module, "_mount_filesystem_type", fake_lookup)
    target = tmp_path / "does" / "not" / "exist" / "state.db"
    api_module.filesystem_type_for(target)
    assert seen, "the probe never looked anything up"
    assert str(tmp_path) in seen[0], (
        "the probe must walk up to an existing ancestor, not query a "
        f"non-existent path: {seen[0]}"
    )


# ── the production guard ────────────────────────────────────────────────────

def test_sqlite_on_an_ephemeral_filesystem_is_refused(api, tmp_path, monkeypatch):
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "overlay")
    with pytest.raises(RuntimeError) as exc:
        api._validate_production_prerequisites()
    message = str(exc.value)
    assert "overlay" in message, "the refusal must name the filesystem it found"
    assert "replay" in message.lower(), (
        "the refusal must say what actually goes wrong, not merely that a "
        "rule was violated"
    )


def test_sqlite_on_a_durable_filesystem_is_accepted(api, tmp_path, monkeypatch):
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "ext4")
    api._validate_production_prerequisites()


def test_undeterminable_filesystem_is_allowed(api, tmp_path, monkeypatch):
    """No /proc/mounts is not evidence of ephemerality.

    The probe reads Linux mount tables. A platform without them cannot be
    refused on that basis alone, or the guard would reject deployments it
    knows nothing bad about.
    """
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: None)
    api._validate_production_prerequisites()


def test_postgres_is_not_subjected_to_the_filesystem_probe(api, monkeypatch):
    """A network service is durable relative to the process that connects.

    Probing the local filesystem for a Postgres DSN would be meaningless, and
    an ephemeral container disk must not disqualify a remote database.
    """
    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://user@db.example:5432/remora")

    def explode(path):  # pragma: no cover - fails the test if reached
        raise AssertionError("the filesystem was probed for a Postgres DSN")

    monkeypatch.setattr(api, "filesystem_type_for", explode)
    api._validate_production_prerequisites()


def test_postgres_wins_when_both_are_set(api, tmp_path, monkeypatch):
    """REMORA_PG_DSN takes precedence, so an ephemeral chain path is moot."""
    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://user@db.example:5432/remora")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "overlay")
    api._validate_production_prerequisites()


def test_no_durable_store_still_refuses(api):
    """The original guarantee is unchanged by the new one."""
    with pytest.raises(RuntimeError) as exc:
        api._validate_production_prerequisites()
    assert "REMORA_PG_DSN" in str(exc.value)


def test_the_refusal_names_the_path_the_operator_configured(api, tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setenv("REMORA_CHAIN_DB", str(db))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "tmpfs")
    with pytest.raises(RuntimeError) as exc:
        api._validate_production_prerequisites()
    assert str(db) in str(exc.value)


def test_development_mode_is_unaffected(monkeypatch, tmp_path):
    """The guard is a production check; local work on tmpfs stays possible."""
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api_module, "filesystem_type_for", lambda p: "overlay")
    api_module._validate_production_prerequisites()


# ── the acknowledged-ephemeral escape hatch ─────────────────────────────────

def test_ephemeral_is_allowed_only_with_the_exact_acknowledgement(
    api, tmp_path, monkeypatch
):
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "overlay")
    monkeypatch.setenv(api.EPHEMERAL_ACK_ENV, api.EPHEMERAL_ACK_VALUE)
    api._validate_production_prerequisites()


@pytest.mark.parametrize("value", ["1", "true", "yes", "YES", "", "accepted"])
def test_a_truthy_flag_is_not_an_acknowledgement(api, tmp_path, monkeypatch, value):
    """The point is that it cannot be set without reading what it says."""
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "overlay")
    monkeypatch.setenv(api.EPHEMERAL_ACK_ENV, value)
    with pytest.raises(RuntimeError):
        api._validate_production_prerequisites()


def test_the_acknowledgement_value_names_the_consequence(api):
    assert "replay" in api.EPHEMERAL_ACK_VALUE, (
        "a bare truthy value would be set without reading it; the value has "
        "to say what accepting it means"
    )


def test_the_refusal_points_at_the_escape_hatch(api, tmp_path, monkeypatch):
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(api, "filesystem_type_for", lambda p: "overlay")
    with pytest.raises(RuntimeError) as exc:
        api._validate_production_prerequisites()
    assert api.EPHEMERAL_ACK_ENV in str(exc.value)
