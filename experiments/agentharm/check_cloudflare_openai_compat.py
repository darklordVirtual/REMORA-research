"""Cloudflare Unified Billing OpenAI-compatible sanity check.

Verifies that the configured Cloudflare REST base URL, API token, and model name
produce a chat completion. Prints "OK" and returned text on success; fails
clearly on auth, endpoint, model, or billing errors.

No secret values are printed. Run:

    python experiments/agentharm/check_cloudflare_openai_compat.py
"""
from __future__ import annotations
# Allow direct invocation as a script (python experiments/agentharm/<file>.py)
import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import sys

from experiments.agentharm.cf_compat import (
    build_openai_client,
    mask_secret,
    resolve_api_key,
    resolve_base_url,
    resolve_model,
)


def check_env() -> tuple[str, str, str]:
    """Resolve api_key, base_url, model from env. Raises on misconfig."""
    api_key = resolve_api_key()
    if not api_key:
        raise SystemExit(
            "FAIL: no API token. Set CF_AIG_TOKEN, CF_AI_GATEWAY_KEY, "
            "CLOUDFLARE_API_TOKEN, or OPENAI_API_KEY."
        )
    base_url = resolve_base_url()  # raises ValueError on /chat/completions suffix
    model = resolve_model()
    print(f"api_key:  {mask_secret(api_key)}")
    print(f"base_url: {base_url}")
    print(f"model:    {model}")
    return api_key, base_url, model


def run_chat_sanity(api_key: str, base_url: str, model: str) -> str:
    """Make one minimal chat completion. Returns the text content."""
    import os
    client = build_openai_client(api_key=api_key, base_url=base_url)

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "temperature": 0.0,
        "max_tokens": 16,
    }

    lora_id = os.environ.get("CF_AIG_LORA")
    if lora_id:
        print(f"lora:     {lora_id}")
        kwargs["extra_body"] = {"lora": lora_id}

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def main() -> int:
    try:
        api_key, base_url, model = check_env()
    except (SystemExit, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2

    try:
        text = run_chat_sanity(api_key, base_url, model)
    except Exception as e:  # noqa: BLE001 - surface the real error, do not hide it
        print(f"FAIL: chat completion error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print("OK")
    print(f"returned: {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
