"""Cloudflare Unified Billing / OpenAI-compatible helpers for AgentHarm.

Small, individually testable functions used by the sanity-check and preflight
scripts. No secret values are ever printed or returned in plaintext form.

Cloudflare Unified Billing exposes an OpenAI-compatible REST endpoint:
``https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1``.
The OpenAI SDK, and Inspect through the SDK, appends ``/chat/completions``.
The configured base URL must therefore end at ``/ai/v1`` rather than the
final ``/ai/v1/chat/completions`` endpoint.
"""
from __future__ import annotations

import os
from typing import Optional

SECRET_ENV_VARS = (
    "CF_AIG_TOKEN",
    "OPENAI_API_KEY",
    "HF_TOKEN",
    "GROQ_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "CF_AI_GATEWAY_KEY",
)


def mask_secret(value: Optional[str]) -> str:
    """Return a masked representation of a secret. Never reveals the value.

    >>> mask_secret("sk-abcdefgh1234")
    'sk-a…1234 (len=14)'
    >>> mask_secret(None)
    '<unset>'
    """
    if not value:
        return "<unset>"
    if len(value) <= 8:
        return f"set (len={len(value)})"
    return f"{value[:4]}…{value[-4:]} (len={len(value)})"


def validate_base_url(base_url: Optional[str]) -> str:
    """Validate and normalize an OpenAI-compatible base URL.

    Raises ValueError if the URL ends with ``/chat/completions`` (the classic
    Cloudflare double-suffix bug). Trailing slashes are stripped.
    """
    if not base_url:
        raise ValueError(
            "OPENAI_BASE_URL is empty; expected Cloudflare REST .../ai/v1 "
            "or provider-specific .../{provider} base URL"
        )
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        raise ValueError(
            "OPENAI_BASE_URL must NOT end with '/chat/completions'. "
            "The OpenAI SDK appends it automatically. "
            "Use the Cloudflare REST '.../ai/v1' base URL instead."
        )
    return normalized


def resolve_base_url(env: Optional[dict] = None) -> str:
    """Resolve the base URL from env, validated.

    Honors OPENAI_BASE_URL when set. Otherwise builds the Cloudflare Unified
    Billing REST base URL from CLOUDFLARE_ACCOUNT_ID or CF_ACCOUNT_ID.
    """
    env = os.environ if env is None else env
    base_url = env.get("OPENAI_BASE_URL")
    if not base_url:
        account = env.get("CLOUDFLARE_ACCOUNT_ID") or env.get("CF_ACCOUNT_ID")
        if account:
            base_url = (
                f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"
            )
    return validate_base_url(base_url)


def resolve_model(env: Optional[dict] = None) -> str:
    """Resolve the Cloudflare model name (e.g. 'openai/gpt-5')."""
    env = os.environ if env is None else env
    return env.get("CF_AIG_MODEL", "openai/gpt-5")


def to_inspect_model(cf_model: str) -> str:
    """Map a Cloudflare model name to an Inspect ``--model`` string.

    Inspect parses ``provider/model``; the first segment selects the Inspect
    provider (openai) and the remainder is sent verbatim to Cloudflare. So a
    Cloudflare model ``openai/gpt-5`` must be passed to Inspect as
    ``openai/openai/gpt-5``.

    >>> to_inspect_model("openai/gpt-5")
    'openai/openai/gpt-5'
    >>> to_inspect_model("openai/openai/gpt-5")
    'openai/openai/gpt-5'
    >>> to_inspect_model("gpt-4o-mini")
    'openai/gpt-4o-mini'
    """
    cf_model = cf_model.strip()
    if cf_model.startswith("openai/openai/"):
        return cf_model
    if cf_model.startswith("openai/"):
        return f"openai/{cf_model}"
    return f"openai/{cf_model}"


def resolve_api_key(env: Optional[dict] = None) -> Optional[str]:
    """Resolve Cloudflare/OpenAI-compatible token. Never logged."""
    env = os.environ if env is None else env
    return (
        env.get("CF_AIG_TOKEN")
        or env.get("CF_AI_GATEWAY_KEY")
        or env.get("CLOUDFLARE_API_TOKEN")
        or env.get("OPENAI_API_KEY")
    )


def build_openai_client(api_key: str, base_url: str):
    """Construct an OpenAI SDK client. Imported lazily so tests don't need the SDK."""
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url=base_url)
