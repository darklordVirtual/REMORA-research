# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The execution surface a lease is granted under, on the API path (CR-006).

The dispatcher has long been able to compare the tool surface a lease was
granted under with the surface observed at dispatch (Q3.2), but on the API
path nothing supplied either side: no lease carried a surface digest and no
observer was bound, so the binding was inert. This module defines the
surface for that path.

Under a strict custody split the authority that issues a lease holds no tool
callables, only the pinned, signed ToolSpec bundle. So the surface is defined
from what both sides can see:

- **Signed surface** (authority, at lease issuance): the bundle digest and,
  for every spec in the bundle, its tool id and spec hash.
- **Observed surface** (executor, at dispatch): the same bundle digest and,
  for every tool the executor has actually registered, its tool id and the
  spec hash the bundle gives it. A registered tool the bundle does not
  describe appears with the hash ``"unsigned"``.

The two digests are equal only when the executor runs exactly the signed
surface: no tool missing, none extra, none under another spec. A tool
registered on the executor that the signed contract does not describe is an
alternative execution path, and an enforced surface binding refuses every
dispatch until it is removed or signed.

What this does not establish: what each tool's implementation does (that is
the ToolSpec and the callable digest), or tools reachable outside the
governed dispatcher (``runtime_capability_surface_completeness`` stays
NOT_ESTABLISHED).
"""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from remora.toolcall.toolspec import ToolSpecBundle

__all__ = ["SURFACE_SCHEMA", "UNSIGNED", "observed_surface_digest", "signed_surface_digest"]

SURFACE_SCHEMA = "remora-execution-surface/v1"
#: Spec hash recorded for a registered tool the signed bundle does not describe.
UNSIGNED = "unsigned"


def _digest(bundle_digest: str, tools: Iterable[tuple[str, str]]) -> str:
    payload = {
        "schema": SURFACE_SCHEMA,
        "bundle_digest": bundle_digest,
        "tools": sorted([name, spec_hash] for name, spec_hash in tools),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def signed_surface_digest(bundle: "ToolSpecBundle") -> str:
    """The surface the signed bundle declares: every spec, by id and hash."""
    return _digest(bundle.bundle_digest,
                   ((s.tool_id, s.toolspec_hash) for s in bundle.tool_specs()))


def observed_surface_digest(bundle: "ToolSpecBundle", registered: Iterable[str]) -> str:
    """The surface an executor actually offers: its registered tools, each
    with the spec hash the bundle gives it, or ``unsigned``."""
    specs = {s.tool_id: s.toolspec_hash for s in bundle.tool_specs()}
    return _digest(bundle.bundle_digest,
                   ((name, specs.get(name, UNSIGNED)) for name in set(registered)))
