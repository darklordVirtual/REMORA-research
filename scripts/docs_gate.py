#!/usr/bin/env python3
# Author: Auto-fix
# SPDX-License-Identifier: BUSL-1.1
"""Docs gate script."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.audit_gates.api import run_docs_gate

def main():
    result = run_docs_gate(ROOT)
    if not result.passed:
        print("Docs gate failed!")
        for violation, loc in result.violations:
            print(f" - {violation.value} in {loc}")
        sys.exit(1)
    print("Docs gate passed.")

if __name__ == "__main__":
    main()
