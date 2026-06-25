"""Verify Hugging Face access to the AgentHarm dataset.

Prints OK on success, fails non-zero on auth / access errors. No token printed.

    python experiments/agentharm/check_hf_access.py
"""
from __future__ import annotations
# Allow direct invocation as a script (python experiments/agentharm/<file>.py)
import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import os
import sys

DATASET_ID = "ai-safety-institute/AgentHarm"


def main() -> int:
    token = os.getenv("HF_TOKEN")
    print(f"HF_TOKEN present: {bool(token)}")
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("FAIL: huggingface_hub not installed (pip install huggingface_hub)",
              file=sys.stderr)
        return 1
    try:
        api = HfApi(token=token)
        info = api.dataset_info(DATASET_ID)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: cannot access {DATASET_ID}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1
    print("OK")
    print(f"dataset accessible: {info.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
