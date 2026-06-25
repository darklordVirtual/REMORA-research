#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] Generate canonical results snapshot"
python scripts/generate_results_snapshot.py

echo "[2/4] Run statistical tests"
python scripts/statistical_tests.py

echo "[3/4] Verify claim consistency"
python scripts/check_claim_consistency.py

echo "[4/4] Run test suite"
pytest -q

echo "Done. Artifacts updated in artifacts/ and docs/."
