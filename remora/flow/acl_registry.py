# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A resource ACL registry read from a file, for flow control on the execution API.

Flow control needs to know who may read a resource twice: when a tool reads
one (the result's label) and when a tool writes to one (the recipients of the
payload). ``REMORA_FLOW_RESOURCE_ACL_MODULE`` names the module the execution
API asks. A deployment can write its own, backed by the system that holds the
resources. This one is the simplest that is safe to run: a JSON file the
deployment owner writes, named in ``REMORA_FLOW_RESOURCE_ACL_FILE``::

    {"schema": "remora-flow-resource-acl/v1",
     "tenants": {
       "acme": [
         {"resource": "res://records/cust-secret", "readers": ["user://acme/alice"]},
         {"resource": "res://records/public/*",    "readers": "PUBLIC"}
       ]}}

Rules:

* ``resource`` is a canonical resource or a subtree (``.../*``). The entry
  that matches most specifically decides: an exact entry before any subtree,
  a longer subtree before a shorter one.
* ``readers`` is the word ``PUBLIC`` or a non-empty list of canonical
  principals. A subtree as a reader is refused: a reader is one principal.
* No restricted entry may lie inside a PUBLIC subtree. "Everything here is
  public, except this record" fails open as soon as the system that holds
  the records knows the record by another name: another case, a child, a
  version suffix. The lookup compares canonical resources and knows none of
  those aliases, so it would answer PUBLIC for them. Such a file is refused
  at load. Public resources get their own subtree or their own exact
  entries, and everything else is restricted or unknown. The reverse, a
  PUBLIC entry inside a restricted subtree, is allowed: an alias of it
  falls back to the restricted answer.
* A resource no entry matches has no answer. The lookup returns an empty
  list, which :func:`remora.flow.check.resource_readers` refuses, so an
  unknown resource is never treated as open or as read by nobody.
* The file is read once per process and its SHA-256 is kept
  (:func:`registry_digest`). A changed file takes effect at restart. A file
  that is missing, unreadable or malformed raises :class:`AclRegistryError`
  whenever the registry is used; the execution API calls :func:`validate`
  when it binds the module and binds nothing on failure. Every flow
  decision then fails with an error until the file is fixed, and none
  turns into a quiet refusal that looks like policy.

What it is not: evidence about the resources. The file is the deployment's
statement, and REMORA does not compare it with the system that holds the
data. An entry that calls a secret record PUBLIC lets it out
(NEGATIVE_RESULTS §87, counterfactual).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from remora.capabilities.resource import (
    ResourceRefused,
    canonical_resource,
    canonical_resource_pattern,
)
from remora.flow.label import PUBLIC

__all__ = ["SCHEMA", "AclRegistryError", "StaticResourceAcl", "registry_digest", "reset",
           "resource_acl", "validate"]

SCHEMA: Final = "remora-flow-resource-acl/v1"
FILE_ENV: Final = "REMORA_FLOW_RESOURCE_ACL_FILE"
_MAX_BYTES: Final = 8 * 1024 * 1024


class AclRegistryError(ValueError):
    """The registry file is missing, unreadable or malformed."""


@dataclass(frozen=True)
class _Entry:
    pattern: str
    readers: Any  # PUBLIC or a tuple of canonical principals

    @property
    def subtree(self) -> bool:
        return self.pattern.endswith("/*")


class StaticResourceAcl:
    """The parsed registry. ``lookup`` answers ``[]`` for anything it does not know."""

    def __init__(self, tenants: Mapping[str, tuple[_Entry, ...]], digest: str) -> None:
        self._count = {tenant: len(entries) for tenant, entries in tenants.items()}
        self._exact = {tenant: {e.pattern: e.readers for e in entries if not e.subtree}
                       for tenant, entries in tenants.items()}
        #: subtree root (without the trailing ``/*``) -> readers
        self._subtree = {tenant: {e.pattern[:-2]: e.readers for e in entries if e.subtree}
                         for tenant, entries in tenants.items()}
        self.digest = digest

    @classmethod
    def from_document(cls, document: Any, digest: str = "") -> StaticResourceAcl:
        if not isinstance(document, dict) or set(document) != {"schema", "tenants"}:
            raise AclRegistryError("the registry is an object with exactly schema and tenants")
        if document["schema"] != SCHEMA:
            raise AclRegistryError(f"schema must be {SCHEMA!r}")
        if not isinstance(document["tenants"], dict):
            raise AclRegistryError("tenants maps a tenant id to a list of entries")
        tenants: dict[str, tuple[_Entry, ...]] = {}
        for tenant, rows in document["tenants"].items():
            if not isinstance(tenant, str) or not tenant or not isinstance(rows, list):
                raise AclRegistryError(f"tenant {tenant!r} needs a non-empty id and a list")
            entries: list[_Entry] = []
            seen: set[str] = set()
            for index, row in enumerate(rows):
                where = f"tenants.{tenant}[{index}]"
                if not isinstance(row, dict) or set(row) != {"resource", "readers"}:
                    raise AclRegistryError(f"{where} has exactly resource and readers")
                try:
                    pattern = canonical_resource_pattern(row["resource"])
                except ResourceRefused as exc:
                    raise AclRegistryError(f"{where}.resource: {exc}") from exc
                if pattern != row["resource"]:
                    raise AclRegistryError(
                        f"{where}.resource is not in canonical form (expected {pattern!r})")
                if pattern in seen:
                    raise AclRegistryError(f"{where}.resource {pattern!r} is listed twice")
                seen.add(pattern)
                entries.append(_Entry(pattern, _readers(row["readers"], where)))
            public_roots = [e.pattern[:-1] for e in entries if e.subtree and e.readers is PUBLIC]
            for entry in entries:
                if entry.readers is PUBLIC:
                    continue
                inside = next((root for root in public_roots
                               if entry.pattern.startswith(root)), None)
                if inside is not None:
                    raise AclRegistryError(
                        f"tenants.{tenant}: restricted entry {entry.pattern!r} lies inside the "
                        f"PUBLIC subtree {inside + '*'!r}; an alias of it would be answered "
                        "PUBLIC. Give public resources their own subtree or exact entries")
            tenants[tenant] = tuple(entries)
        return cls(tenants, digest)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> StaticResourceAcl:
        try:
            with Path(path).open("rb") as handle:
                raw = handle.read(_MAX_BYTES + 1)   # never more, whatever the file is
        except OSError as exc:
            raise AclRegistryError(f"cannot read the registry file: {exc}") from exc
        if len(raw) > _MAX_BYTES:
            raise AclRegistryError("the registry file is larger than 8 MiB")
        try:
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
        except RecursionError as exc:
            raise AclRegistryError(
                "the registry file is not strict JSON: nested too deeply") from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise AclRegistryError(f"the registry file is not strict JSON: {exc}") from exc
        return cls.from_document(document, "sha256:" + hashlib.sha256(raw).hexdigest())

    def lookup(self, tenant: str, resource: str) -> Any:
        """PUBLIC, the readers of the most specific matching entry, or ``[]``."""
        try:
            canonical = canonical_resource(resource)
            exact = self._exact.get(tenant)
        except (ResourceRefused, TypeError):
            return []
        if exact is None:
            return []
        readers = exact.get(canonical)
        if readers is None:
            # The longest subtree that holds it: walk up one segment at a time.
            subtrees = self._subtree[tenant]
            head, _, rest = canonical.partition("://")
            parts = rest.split("/")
            for depth in range(len(parts) - 1, 0, -1):
                readers = subtrees.get(f"{head}://" + "/".join(parts[:depth]))
                if readers is not None:
                    break
        if readers is None:
            return []
        return PUBLIC if readers is PUBLIC else list(readers)

    def entries(self, tenant: str) -> int:
        try:
            return self._count.get(tenant, 0)
        except TypeError:
            return 0


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate member {key!r}")
        out[key] = value
    return out


def _readers(value: Any, where: str) -> Any:
    if value == "PUBLIC":
        return PUBLIC
    if not isinstance(value, list) or not value:
        raise AclRegistryError(f"{where}.readers is \"PUBLIC\" or a non-empty list of principals")
    out = []
    for reader in value:
        try:
            canonical = canonical_resource(reader)
        except ResourceRefused as exc:
            raise AclRegistryError(f"{where}.readers: {reader!r} is not one principal: {exc}") \
                from exc
        if canonical != reader:
            raise AclRegistryError(
                f"{where}.readers: {reader!r} is not in canonical form (expected {canonical!r})")
        out.append(canonical)
    if len(set(out)) != len(out):
        raise AclRegistryError(f"{where}.readers lists a principal twice")
    return tuple(out)


# ── the module interface REMORA_FLOW_RESOURCE_ACL_MODULE expects ─────────

_REGISTRY: StaticResourceAcl | None = None
_LOCK = threading.Lock()


def _registry() -> StaticResourceAcl:
    global _REGISTRY
    if _REGISTRY is None:
        with _LOCK:   # one load, one digest, whoever asks first
            if _REGISTRY is None:
                path = os.environ.get("REMORA_FLOW_RESOURCE_ACL_FILE", "").strip()
                if not path:
                    raise AclRegistryError(f"{FILE_ENV} is not set")
                _REGISTRY = StaticResourceAcl.from_file(path)
    return _REGISTRY


def validate() -> str:
    """Load the registry now and return its digest; raises on a bad file."""
    return _registry().digest


def registry_digest() -> str:
    return _registry().digest


def resource_acl(tenant: str, resource: str) -> Any:
    return _registry().lookup(tenant, resource)


def reset() -> None:
    """Forget the loaded registry (tests, and a process that re-reads its settings)."""
    global _REGISTRY
    with _LOCK:
        _REGISTRY = None
