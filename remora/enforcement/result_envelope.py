# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bounded, verifiable tool results.

A governed dispatch used to inline the whole tool result into the HTTP
response and the audit record. Three problems followed from that:

* an unbounded audit record — one verbose tool inflates the tenant chain
  permanently, and the chain is the artifact an auditor has to read;
* an unbounded context surface — whatever consumes the envelope next
  (an agent, a reviewer UI) receives attacker-influenced bytes in full,
  so a prompt-injection payload rides along at no cost;
* non-determinism in replay when a result is large enough to be handled
  differently by different consumers.

The envelope here bounds what is *retained* without bounding what is
*verified*: the SHA-256 always covers the full canonical result, so a
replay can prove it observed the same output even when only a preview was
kept. Truncation is recorded explicitly — a shortened preview must never
be mistakable for the whole result.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

#: Retained-bytes budget when the deployment declares none. 64 KiB is far
#: above any structured governance result and far below the size at which an
#: audit chain becomes unreadable.
DEFAULT_MAX_RESULT_BYTES = 64 * 1024

#: Deployment override.
ENV_MAX_RESULT_BYTES = "REMORA_MAX_TOOL_RESULT_BYTES"

#: Marker written into a truncated preview. Present so a consumer cannot read
#: a preview as if it were the complete result.
TRUNCATION_KEY = "_remora_truncated"


def _canonical_bytes(value: Any) -> tuple[bytes, str]:
    """Canonical JSON of *value*, or a text projection when it will not encode.

    Returns ``(bytes, media_type)``. Never raises: a tool that returns an
    unserialisable object must still produce an auditable record, and failing
    the dispatch after the side effect already happened would be worse than
    recording a degraded projection.
    """
    # Broad except on purpose: `default=str` invokes the value's own __str__ /
    # __repr__, which is third-party code and may raise anything at all. The
    # side effect has already happened by the time we get here, so refusing to
    # produce a record would lose the audit entry for a call that really ran.
    try:
        return (
            json.dumps(value, sort_keys=True, separators=(",", ":"),
                       default=str).encode("utf-8"),
            "application/json",
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        return repr(value).encode("utf-8", errors="replace"), "text/plain"
    except Exception:  # noqa: BLE001
        return b"<unrepresentable tool result>", "text/plain"


def configured_max_bytes() -> int:
    """Retained-bytes budget from the environment, or the default.

    A non-numeric or non-positive value falls back to the default rather than
    disabling the bound: an unbounded audit record is the failure this module
    exists to prevent, so a typo must not silently re-enable it.
    """
    raw = os.environ.get(ENV_MAX_RESULT_BYTES, "").strip()
    if not raw:
        return DEFAULT_MAX_RESULT_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_RESULT_BYTES
    return value if value > 0 else DEFAULT_MAX_RESULT_BYTES


@dataclass(frozen=True)
class ToolResultEnvelope:
    """What a governed dispatch retains about a tool's output.

    ``sha256`` covers the FULL canonical result; ``preview`` may be a bounded
    projection of it. ``truncated`` says which of the two the preview is.
    """

    sha256: str
    size_bytes: int
    truncated: bool
    preview: Any
    media_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def capture_tool_result(
    result: Any, *, max_bytes: int | None = None
) -> ToolResultEnvelope:
    """Hash *result* in full and retain at most *max_bytes* of it.

    ``max_bytes`` defaults to :func:`configured_max_bytes`.
    """
    budget = configured_max_bytes() if max_bytes is None else max_bytes
    raw, media_type = _canonical_bytes(result)
    digest = hashlib.sha256(raw).hexdigest()

    if len(raw) <= budget:
        # Within budget: retain the value itself, not a re-parsed projection,
        # so a consumer sees exactly what the tool returned.
        preview: Any = result if media_type == "application/json" else raw.decode(
            "utf-8", errors="replace"
        )
        return ToolResultEnvelope(
            sha256=digest, size_bytes=len(raw), truncated=False,
            preview=preview, media_type=media_type,
        )

    head = raw[:budget].decode("utf-8", errors="replace")
    return ToolResultEnvelope(
        sha256=digest,
        size_bytes=len(raw),
        truncated=True,
        preview={
            TRUNCATION_KEY: True,
            "retained_bytes": budget,
            "total_bytes": len(raw),
            "head": head,
        },
        media_type=media_type,
    )
