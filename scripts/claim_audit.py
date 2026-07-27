#!/usr/bin/env python3
# Author: Auto-fix
# SPDX-License-Identifier: BUSL-1.1
"""Claim audit script."""
import sys
from pathlib import Path

# Add project root to import path if needed
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.audit_gates.api import run_claim_audit

def main():
    result = run_claim_audit(ROOT)
    if not result.passed:
        print("Claim audit failed!")
        for violation, loc in result.violations:
            print(f" - {violation.value} in {loc}")
        sys.exit(1)
    print("Claim audit passed.")

if __name__ == "__main__":
    main()
