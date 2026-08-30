# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The identity of the runtime that executes an action (ADR-D).

``ExecutionLease`` binds sixteen fields — tenant, actor, tool, the canonical
argument hash, target environment, policy bundle hash, ToolSpec hash and
version, intent authority, tool contract bundle, proposal id, grant jti, nonce,
issue and expiry, signature algorithm and key id. None of them names the
runtime that performs the action.

``docs/research/adjacent-systems-crosswalk-v2.md`` §3 walks the discriminating
case against HEAD: authorize under ToolSpec T1, policy P1, runtime R1, with no
drift before authorization; execute with arguments unchanged, target unchanged,
policy still P1, ToolSpec *declaration* still T1 — but the runtime
implementation is R2. Exact-call integrity passes, because the call is the
authorized call. Authorization-state drift passes, because the declaration did
not change. Boundary traversal passes, because no alternate path was used.
Every property reports success while the action ran against an implementation
nobody authorized. That gap is what this module closes.

**The trust model, stated precisely, because it is narrower than it looks.**
The executing process reads its own identity from the environment once, at
first use, and caches it behind a lock. Dispatch compares the lease's binding
against that cached value. The identity is never a dispatch parameter, so a
caller in the invocation path cannot present a different one — which is the
whole reason it is read here rather than passed in.

What this closes is *executed by the wrong runtime*: a stale worker generation,
a container image that was rolled back, an MCP runtime that is not the one the
approval was granted under. What it does not close is *executed by a
compromised runtime that lies about itself*. A process that controls its own
environment controls its own declaration, and no amount of hashing changes
that. Closing that case requires an external attestor (TPM, Sigstore, SPIFFE)
signing the identity, which is a separate trust anchor and a separate delivery.
This module is not evidence for it and must not be cited as such.

**Canonicalisation.** ``identity_hash`` uses ``_canonical_json`` from
``remora.policy.observation`` — the same function behind
``canonical_tool_call_hash``, and therefore behind every lease, token, receipt
and audit-chain entry this repository has written. RFC 8785 canonicalisation
(``remora.interop.jcs``) is deliberately NOT used here: that module's own
docstring scopes it to wire interoperability and forbids it replacing the
internal canonicalisation, because the historical record has to stay verifiable
against the code that verifies it.

**Nothing is inferred.** An unset field stays empty, and a wholly undeclared
runtime hashes to the empty string rather than to a hash over six empty
strings. The distinction matters: the empty hash is what dispatch tests for, and a runtime
that declared nothing must be distinguishable from one that declared six
blanks. Declaring *some* fields
is a declaration and hashes normally.
"""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, replace

from remora.policy.observation import _canonical_json

__all__ = [
    "ENV_DEPLOYMENT_GENERATION",
    "ENV_DEPLOYMENT_ID",
    "ENV_EXECUTOR_INSTANCE_CLASS",
    "ENV_IMAGE_DIGEST",
    "ENV_RUNTIME_KIND",
    "ENV_TOOL_RUNTIME_IDENTITY",
    "RuntimeTrustBaseIdentity",
    "current_runtime_identity",
    "current_runtime_identity_hash",
    "reset_runtime_identity",
]

ENV_RUNTIME_KIND = "REMORA_RUNTIME_KIND"
ENV_DEPLOYMENT_ID = "REMORA_DEPLOYMENT_ID"
ENV_IMAGE_DIGEST = "REMORA_IMAGE_DIGEST"
ENV_EXECUTOR_INSTANCE_CLASS = "REMORA_EXECUTOR_INSTANCE_CLASS"
ENV_TOOL_RUNTIME_IDENTITY = "REMORA_TOOL_RUNTIME_IDENTITY"
ENV_DEPLOYMENT_GENERATION = "REMORA_DEPLOYMENT_GENERATION"


@dataclass(frozen=True)
class RuntimeTrustBaseIdentity:
    """What the executing runtime says it is.

    ``generation`` is a string rather than an integer because deployment
    generations are not reliably numeric across orchestrators, and a value that
    is only ever compared for equality needs no numeric semantics.
    """

    runtime_kind: str = ""
    deployment_id: str = ""
    image_digest: str = ""
    executor_instance_class: str = ""
    tool_runtime_identity: str = ""
    generation: str = ""

    @classmethod
    def from_environment(cls, env: "dict[str, str] | None" = None) -> RuntimeTrustBaseIdentity:
        """Read this process's own declaration. Unset fields stay empty."""
        source = os.environ if env is None else env
        return cls(
            runtime_kind=source.get(ENV_RUNTIME_KIND, "").strip(),
            deployment_id=source.get(ENV_DEPLOYMENT_ID, "").strip(),
            image_digest=source.get(ENV_IMAGE_DIGEST, "").strip(),
            executor_instance_class=source.get(ENV_EXECUTOR_INSTANCE_CLASS, "").strip(),
            tool_runtime_identity=source.get(ENV_TOOL_RUNTIME_IDENTITY, "").strip(),
            generation=source.get(ENV_DEPLOYMENT_GENERATION, "").strip(),
        )

    @property
    def declared(self) -> bool:
        """True when at least one field carries a value."""
        return any(
            (
                self.runtime_kind,
                self.deployment_id,
                self.image_digest,
                self.executor_instance_class,
                self.tool_runtime_identity,
                self.generation,
            )
        )

    def identity_hash(self) -> str:
        """SHA-256 over the canonical form; empty string when undeclared."""
        if not self.declared:
            return ""
        preimage = _canonical_json(
            {
                "runtime_kind": self.runtime_kind,
                "deployment_id": self.deployment_id,
                "image_digest": self.image_digest,
                "executor_instance_class": self.executor_instance_class,
                "tool_runtime_identity": self.tool_runtime_identity,
                "generation": self.generation,
            }
        )
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    def with_generation(self, generation: str) -> RuntimeTrustBaseIdentity:
        """A copy at a different generation. Convenience for tests and rollout."""
        return replace(self, generation=generation)


_LOCK = threading.Lock()
_CACHED: RuntimeTrustBaseIdentity | None = None


def current_runtime_identity() -> RuntimeTrustBaseIdentity:
    """This process's own identity, read once and cached.

    Caching is the security property, not an optimisation: the value dispatch
    compares against must not be changeable by anything that happens after
    startup. Tests reset it through :func:`reset_runtime_identity`.
    """
    global _CACHED
    if _CACHED is None:
        with _LOCK:
            if _CACHED is None:
                _CACHED = RuntimeTrustBaseIdentity.from_environment()
    return _CACHED


def current_runtime_identity_hash() -> str:
    """The identity hash of this process; empty string when undeclared."""
    return current_runtime_identity().identity_hash()


def reset_runtime_identity() -> None:
    """Drop the cached identity so the next read re-reads the environment.

    For tests and for a deliberate re-read at process start. Follows the
    reload-restore pattern the suite already uses for module-level state.
    """
    global _CACHED
    with _LOCK:
        _CACHED = None
