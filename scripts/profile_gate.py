#!/usr/bin/env python3
# Author: Auto-fix
# SPDX-License-Identifier: BUSL-1.1
"""Profile gate script."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.audit_gates.api import run_profile_gate

def main():
    result = run_profile_gate(ROOT)
    if not result.passed:
        print("Profile gate failed!")
        for violation, loc in result.violations:
            print(f" - {violation.value} in {loc}")
        sys.exit(1)
    print("Profile gate passed.")

if __name__ == "__main__":
    main()
