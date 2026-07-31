# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Closed-world coverage declarations (§30 follow-up).

§30 established that completeness must be declared rather than inferred. This
module makes the declaration a *versioned evidence object* rather than a
configuration flag, because the ways a completeness claim goes wrong are all
scope errors that a bare flag cannot express:

* complete for one tenant, applied to another
* complete at one instant, consulted later
* complete for active records, silent about archived or deleted ones
* ``user_id`` conflated with a recipient id or an owner id
* aliases and normalised forms treated as absent

Each of those would produce exactly the failure §26 and §29 measured — a
confident negative about a value that is in fact valid — so each is bound
explicitly and checked.

Two rules the runtime cannot bend:

1. **Runtime never upgrades open-world to closed-world.** Only a declaration
   admits a scope, and a declaration is authored, not computed.
2. **A stale or mismatched declaration degrades to UNKNOWN**, never to
   UNSUPPORTED. Losing the ability to make a negative claim is the safe
   direction; keeping it on stale evidence is how a valid identifier gets
   rejected.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

#: How a declared value space is compared. Only exact string comparison is
#: implemented; declaring anything else is refused rather than silently
#: approximated, because a mismatch between declared and actual
#: canonicalisation is one of the failure modes this object exists to prevent.
_SUPPORTED_CANONICALIZATION = frozenset({"string_exact"})


class DeclarationInvalid(ValueError):
    """A declaration cannot be honoured as written."""


@dataclass(frozen=True)
class CoverageDeclaration:
    """A curator's claim that an index is complete for one argument role."""

    domain: str
    tenant: str
    entity_type: str
    argument_role: str
    #: SHA-256 of the state snapshot this claim was made against. A declaration
    #: is only valid for the exact bytes it was written for.
    source_snapshot_sha256: str
    as_of: date
    completeness_basis: str
    curator: str
    canonicalization: str = "string_exact"
    aliases_supported: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "domain", "tenant", "entity_type", "argument_role",
            "source_snapshot_sha256", "completeness_basis", "curator",
        ):
            if not str(getattr(self, field_name)).strip():
                raise DeclarationInvalid(f"{field_name} must not be empty")
        if len(self.source_snapshot_sha256) != 64:
            raise DeclarationInvalid(
                "source_snapshot_sha256 must be a full SHA-256 digest"
            )
        if self.canonicalization not in _SUPPORTED_CANONICALIZATION:
            raise DeclarationInvalid(
                f"canonicalization {self.canonicalization!r} is not implemented; "
                "declaring it would claim a comparison the code does not perform"
            )
        if self.aliases_supported:
            raise DeclarationInvalid(
                "alias resolution is not implemented; a declaration claiming it "
                "would mark normalised forms of valid values as unsupported"
            )

    def matches_snapshot(self, path: Path) -> bool:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return digest == self.source_snapshot_sha256

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "tenant": self.tenant,
            "entity_type": self.entity_type,
            "argument_role": self.argument_role,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "as_of": self.as_of.isoformat(),
            "completeness_basis": self.completeness_basis,
            "curator": self.curator,
            "canonicalization": self.canonicalization,
            "aliases_supported": self.aliases_supported,
        }

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> CoverageDeclaration:
        return cls(
            domain=d["domain"],
            tenant=d["tenant"],
            entity_type=d["entity_type"],
            argument_role=d["argument_role"],
            source_snapshot_sha256=d["source_snapshot_sha256"],
            as_of=date.fromisoformat(d["as_of"]),
            completeness_basis=d["completeness_basis"],
            curator=d["curator"],
            canonicalization=d.get("canonicalization", "string_exact"),
            aliases_supported=bool(d.get("aliases_supported", False)),
        )


def load_declarations(path: Path) -> tuple[CoverageDeclaration, ...]:
    """Load declarations from a JSON document."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(CoverageDeclaration.from_json_dict(d) for d in payload["declarations"])


def admitted_scopes(
    declarations: tuple[CoverageDeclaration, ...],
    snapshots: dict[str, Path],
    *,
    tenant: str,
) -> dict[str, set[str]]:
    """Return ``{domain: {argument_role}}`` for declarations that hold right now.

    A declaration is dropped — degrading that scope to open-world, hence to
    UNKNOWN — when its tenant does not match, when no snapshot is available for
    its domain, or when the snapshot bytes differ from those it was written
    against. Dropping is always the safe direction: it removes the ability to
    make a negative claim, it never adds one.
    """
    admitted: dict[str, set[str]] = {}
    for declaration in declarations:
        if declaration.tenant != tenant:
            continue
        snapshot = snapshots.get(declaration.domain)
        if snapshot is None or not declaration.matches_snapshot(snapshot):
            continue
        admitted.setdefault(declaration.domain, set()).add(declaration.argument_role)
    return admitted
