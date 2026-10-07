# SPDX-License-Identifier: BUSL-1.1
"""Deployment wiring for execution context capture and freshness checks."""
from __future__ import annotations

import importlib
import os
from functools import lru_cache

from remora.governance.execution_identity import (
    ExecutionContextProvider, ExecutionContextRefused,
)


def context_required() -> bool:
    value = os.environ.get("REMORA_REQUIRE_EXECUTION_CONTEXT", "").strip().lower()
    if value not in {"", "0", "false", "no", "off", "1", "true", "yes", "on"}:
        raise ExecutionContextRefused("execution_context_requirement_invalid")
    return value in {"1", "true", "yes", "on"}


@lru_cache(maxsize=8)
def _provider(module: str) -> ExecutionContextProvider:
    try:
        provider: ExecutionContextProvider = importlib.import_module(module).execution_context_provider
    except (ImportError, AttributeError) as exc:
        raise ExecutionContextRefused("execution_context_provider_unavailable") from exc
    for name in ("capture", "data_scope_valid", "current_build_provenance_digest"):
        if not callable(getattr(provider, name, None)):
            raise ExecutionContextRefused("execution_context_provider_invalid")
    return provider


def context_provider() -> ExecutionContextProvider | None:
    module = os.environ.get("REMORA_EXECUTION_CONTEXT_MODULE", "").strip()
    if module:
        return _provider(module)
    if context_required():
        raise ExecutionContextRefused("execution_context_provider_missing")
    return None
