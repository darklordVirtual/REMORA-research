"""AgentHarm preflight: dependency, HF, Cloudflare REST, and model-naming sanity.

Runs all gating checks before any AgentHarm pilot. Exits non-zero if any
required check fails. No secret values are printed.

    python experiments/agentharm/preflight.py
"""
from __future__ import annotations
# Allow direct invocation as a script (python experiments/agentharm/<file>.py)
import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import importlib.util
import sys

from experiments.agentharm.cf_compat import (
    resolve_api_key,
    resolve_base_url,
    resolve_model,
    to_inspect_model,
)


def _check_deps() -> list[str]:
    missing = []
    for mod in ("inspect_ai", "inspect_evals", "openai", "yaml", "datasets",
                "huggingface_hub"):
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing


def check_dependency_sanity() -> bool:
    missing = _check_deps()
    if missing:
        print(f"[deps]      FAIL: missing modules: {', '.join(missing)}")
        return False
    print("[deps]      OK")
    return True


def check_model_naming() -> bool:
    """Inspect model-naming sanity: cf model -> inspect --model string."""
    cf_model = resolve_model()
    inspect_model = to_inspect_model(cf_model)
    if not inspect_model.startswith("openai/openai/") and cf_model.startswith("openai/"):
        print(f"[model]     FAIL: {cf_model} -> {inspect_model} (expected double openai/)")
        return False
    print(f"[model]     OK: cf={cf_model} inspect={inspect_model}")
    return True


def check_base_url() -> bool:
    try:
        base_url = resolve_base_url()
    except ValueError as e:
        print(f"[base_url]  FAIL: {e}")
        return False
    has_key = bool(resolve_api_key())
    print(f"[base_url]  OK: {base_url} (token present: {has_key})")
    return True


def main() -> int:
    print("=== AgentHarm preflight ===")
    ok = True
    ok &= check_dependency_sanity()
    ok &= check_base_url()
    ok &= check_model_naming()
    # HF + live Cloudflare chat checks are delegated to their dedicated scripts,
    # which require network and are run separately by run_pilot.sh.
    print("--- run check_hf_access.py and check_cloudflare_openai_compat.py for live checks ---")
    if not ok:
        print("PREFLIGHT FAILED", file=sys.stderr)
        return 1
    print("PREFLIGHT OK (static checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
