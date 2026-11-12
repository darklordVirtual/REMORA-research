# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signed, append-only chain-head anchors kept outside the chain store.

A head stored next to the entries (``tenant_chain_head``) detects deleted
entries, but not an attacker who rewrites entries and head together
(SDD-RMR-AACP-X R1). An anchor removes that gap only if it lives where the
store's writer cannot rewrite it. This module writes one HMAC-signed line per
committed head to a file at ``REMORA_AUDIT_ANCHOR_PATH``, which the deployment
must place on append-only storage (WORM bucket, ``chattr +a``, a separate
host). The code cannot enforce that placement; it reports which anchor it
checked against.

Each line binds ``(chain_id, tenant_id, sequence_no, entry_hash)`` under
``REMORA_AUDIT_ANCHOR_KEY``. Reading verifies every line and that each
``(chain_id, tenant_id)`` only moves forward, so a rolled-back or edited
anchor file is refused, not trusted.

Checking a chain against its anchor (:func:`anchor_problems`):

- the anchored entry must be present with the anchored hash. A chain cut
  below the anchor, or rewritten at or before it, fails;
- the chain may be longer than the anchor. The anchor is written after the
  entry commits, so a crash leaves it one step behind. Entries past the
  anchor are reported as ``anchor_lag`` and are protected only locally;
- a non-empty chain with no anchor at all fails (``anchor_absent``) once
  anchoring is configured. An operator records a first anchor with
  ``record`` when enabling it on an existing chain; that anchor covers the
  history as found and verifies nothing before it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from remora.timebase import utc_now

ENV_PATH = "REMORA_AUDIT_ANCHOR_PATH"
ENV_KEY = "REMORA_AUDIT_ANCHOR_KEY"
ANCHOR_FORMAT = "remora-chain-anchor-v1"
_DOMAIN = b"REMORA-CHAIN-ANCHOR-v1\x1f"
_MIN_KEY_BYTES = 32
_HEX = frozenset("0123456789abcdef")


class ChainAnchorInvalid(RuntimeError):
    """The anchor file cannot be trusted: a line is malformed, unsigned,
    signed with another key, or moves a chain's head backwards."""


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _preimage(record: dict[str, Any]) -> bytes:
    body = {k: record[k] for k in ("format", "chain_id", "tenant_id", "sequence_no",
                                   "entry_hash", "recorded_at")}
    return _DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


class ChainAnchor:
    """Append-only file of signed heads, for any number of chains and tenants."""

    def __init__(self, path: str, key: str | bytes) -> None:
        raw = key.encode() if isinstance(key, str) else bytes(key)
        if len(raw.strip()) < _MIN_KEY_BYTES:
            raise ValueError(f"{ENV_KEY} must be at least {_MIN_KEY_BYTES} bytes")
        self._path = Path(path)
        self._key = raw.strip()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _sign(self, record: dict[str, Any]) -> str:
        return hmac.new(self._key, _preimage(record), hashlib.sha256).hexdigest()

    def record(self, chain_id: str, tenant_id: str, sequence_no: int, entry_hash: str) -> None:
        """Append a signed anchor for ``(chain_id, tenant_id)`` at this head.

        Refuses a head that would move the anchor backwards, so a caller can
        never record a rollback either.
        """
        if type(sequence_no) is not int or sequence_no < 0 or not _is_hex64(entry_hash):
            raise ValueError("anchor needs a non-negative sequence_no and a hex entry_hash")
        with self._lock:
            current = self.latest(chain_id, tenant_id)
            if current is not None and sequence_no < current[0]:
                raise ChainAnchorInvalid(
                    f"anchor for {chain_id}/{tenant_id} is at {current[0]}; "
                    f"refusing to record {sequence_no}")
            if current == (sequence_no, entry_hash):
                return
            record: dict[str, Any] = {
                "format": ANCHOR_FORMAT,
                "chain_id": chain_id,
                "tenant_id": tenant_id,
                "sequence_no": sequence_no,
                "entry_hash": entry_hash,
                "recorded_at": utc_now().isoformat(),
            }
            record["signature"] = self._sign(record)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line.encode())
                os.fsync(fd)
            finally:
                os.close(fd)

    def _records(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        heads: dict[tuple[str, str], tuple[int, str]] = {}
        with open(self._path, encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    ok = (
                        isinstance(rec, dict)
                        and rec.get("format") == ANCHOR_FORMAT
                        and isinstance(rec.get("chain_id"), str)
                        and isinstance(rec.get("tenant_id"), str)
                        and type(rec.get("sequence_no")) is int and rec["sequence_no"] >= 0
                        and _is_hex64(rec.get("entry_hash"))
                        and isinstance(rec.get("recorded_at"), str)
                        and isinstance(rec.get("signature"), str)
                        and hmac.compare_digest(self._sign(rec), rec["signature"])
                    )
                except (json.JSONDecodeError, KeyError, TypeError):
                    ok = False
                if not ok:
                    raise ChainAnchorInvalid(f"{self._path}: line {n} is malformed or not "
                                             "signed with this deployment's anchor key")
                key = (rec["chain_id"], rec["tenant_id"])
                prev = heads.get(key)
                if prev is not None and rec["sequence_no"] < prev[0]:
                    raise ChainAnchorInvalid(f"{self._path}: line {n} moves {key} back from "
                                             f"{prev[0]} to {rec['sequence_no']}")
                if prev is not None and rec["sequence_no"] == prev[0] and \
                        rec["entry_hash"] != prev[1]:
                    raise ChainAnchorInvalid(f"{self._path}: line {n} gives {key} a second "
                                             f"hash at {prev[0]}")
                heads[key] = (rec["sequence_no"], rec["entry_hash"])
                out.append(rec)
        return out

    def latest(self, chain_id: str, tenant_id: str) -> tuple[int, str] | None:
        """The newest verified anchor for this chain and tenant, or None."""
        found = None
        for rec in self._records():
            if rec["chain_id"] == chain_id and rec["tenant_id"] == tenant_id:
                found = (rec["sequence_no"], rec["entry_hash"])
        return found


def anchor_from_env(environ: dict[str, str] | None = None) -> ChainAnchor | None:
    """``ChainAnchor`` from ``REMORA_AUDIT_ANCHOR_PATH``/``_KEY``, or None.

    A path without a key is a configuration error, not "unanchored": an
    unsigned anchor would be as rewritable as the store it protects.
    """
    env = os.environ if environ is None else environ
    path = env.get(ENV_PATH, "").strip()
    if not path:
        return None
    key = env.get(ENV_KEY, "").strip()
    if not key:
        raise ValueError(f"{ENV_PATH} is set but {ENV_KEY} is not")
    return ChainAnchor(path, key)


def anchor_problems(entries: Sequence[Any], anchor: tuple[int, str] | None) -> list[str]:
    """Problems with ``entries`` (each has ``entry_hash``) against an anchor.

    ``entries[i]`` is the entry at position ``i``. ``anchor_lag`` is not a
    problem: it is reported by :func:`anchor_status`.
    """
    if anchor is None:
        return ["anchor_absent"] if entries else []
    seq, entry_hash = anchor
    if seq >= len(entries):
        return [f"anchor_truncated:anchored_seq={seq}:actual_seq={len(entries) - 1}"]
    if entries[seq].entry_hash != entry_hash:
        return [f"anchor_mismatch_at:{seq}"]
    return []


def anchor_status(entries: Sequence[Any], anchor: tuple[int, str] | None) -> dict[str, Any]:
    """``anchored_sequence`` and ``anchor_lag`` (entries protected only locally)."""
    last = len(entries) - 1
    return {
        "anchored_sequence": None if anchor is None else anchor[0],
        "anchor_lag": (last + 1) if anchor is None else max(0, last - anchor[0]),
    }
