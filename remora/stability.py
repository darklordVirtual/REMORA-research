# Author: Stian Skogbrott
# License: Apache-2.0
"""Module stability classification for REMORA.

Usage (module-level marker)::

    from remora.stability import EXPERIMENTAL
    __stability__ = EXPERIMENTAL

Usage (function decorator)::

    from remora.stability import experimental, research_only

    @experimental("topology analysis", since="0.6.0")
    def topological_persistence(data): ...

    @research_only("zero-knowledge proofs")
    def zkp_assurance_proof(claim): ...

Stability levels
----------------
CORE          Production-stable. Covered by backwards-compatibility policy.
EXPERIMENTAL  Under active development. API may change between minor versions.
RESEARCH_ONLY Not production-ready. Simulator/lab results only. No BC guarantee.
"""
from __future__ import annotations

import functools
import warnings
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

CORE = "core"
EXPERIMENTAL = "experimental"
RESEARCH_ONLY = "research_only"


def experimental(feature_name: str, since: str = "unknown") -> Callable[[F], F]:
    """Mark a function or class as experimental; emits UserWarning on call."""
    def decorator(fn: F) -> F:
        msg = (
            f"{fn.__qualname__} is part of the experimental '{feature_name}' feature "
            f"(since {since}). API may change in minor versions."
        )
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(msg, UserWarning, stacklevel=2)
            return fn(*args, **kwargs)
        wrapper.__stability__ = EXPERIMENTAL  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]
    return decorator


def research_only(feature_name: str) -> Callable[[F], F]:
    """Mark a function as research-only; emits UserWarning on call."""
    def decorator(fn: F) -> F:
        msg = (
            f"{fn.__qualname__} is part of '{feature_name}' which is research-only. "
            "Results come from simulators, not production deployments. Not production-certified."
        )
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(msg, UserWarning, stacklevel=2)
            return fn(*args, **kwargs)
        wrapper.__stability__ = RESEARCH_ONLY  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]
    return decorator
