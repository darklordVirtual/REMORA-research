# Author: Stian Skogbrott
# License: Apache-2.0
"""Platform-agnostic adapters for REMORA.

REMORA is designed to be deployable on any infrastructure. These adapters
provide a consistent interface for LLM access, storage, identity, and
audit across cloud providers and on-premises environments.

Adapter categories:
    llm/       — Model API adapters (OpenAI, Azure OpenAI, Anthropic, local)
    storage/   — Artifact and evidence storage (filesystem, S3, Azure Blob, R2)
    identity/  — Authentication and authorisation (JWT, Entra ID, Keycloak)
    audit/     — Audit trail backends (PostgreSQL, JSONL)
"""

from remora.adapters.action_gate import (
    ActionGateResult,
    LangGraphActionAdapter,
    OpenAIToolCallingAdapter,
    RemoraActionGate,
)

__all__ = [
    "RemoraActionGate",
    "ActionGateResult",
    "LangGraphActionAdapter",
    "OpenAIToolCallingAdapter",
]
