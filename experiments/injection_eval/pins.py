# SPDX-License-Identifier: BUSL-1.1
"""InjecAgent pin of SAP v7 §13.2. The builder refuses a checkout that differs."""
from __future__ import annotations

from pathlib import Path

from experiments.sap_v7_addenda.seal import RunRefused

REPOSITORY = "uiuc-kang-lab/InjecAgent"
COMMIT = "f19c9f2c79a41046eb13c03c51a24c567a8ffa07"

#: Raw SHA-256 of the files the builder reads, at the pinned commit.
FILES: dict[str, str] = {
    "data/test_cases_dh_base.json": "0a8186468d21389af432e8c7b399ae42264d1b93a07b65c7a489468508604305",
    "data/test_cases_ds_base.json": "4daab35c62a3845e8b9400f4dca58b9c9f37e57cd33b2337552557fbb26282e9",
    "data/test_cases_dh_enhanced.json": "885602716b72c18af80695ce6c2e1f242fa03163bc90b0788b0c5e4ab6216d50",
    "data/test_cases_ds_enhanced.json": "7bc510868df032511053fc40e8470e68a041fb7148d055112093594bf73ab0ce",
    "data/attacker_cases_dh.jsonl": "999d52e15af3c80a3303a09430af0f3878d1f91e4c573ca7b477a91cdfa6b991",
    "data/attacker_cases_ds.jsonl": "87952398c989d8ca841724e38ecdbb789676d3841e19dfc44aac7b710df9cb1f",
    "data/user_cases.jsonl": "c840e2b00fdce68e7142d0970220522303d67b2530d6fb36ef1112448cdd8977",
    "data/tools.json": "e21a8f70b1d5de4677d6d52642936a322655d79b17a72c84f600550384083a1e",
    "data/attacker_simulated_responses.json": "b1da2e1fb75f266c069b832fef6738c295f01d8962fae15bdac9ff6625e5594e",
}


def mismatches(root: Path, files: dict[str, str] | None = None) -> list[str]:
    """Pinned files under *root* that are missing or whose SHA-256 differs."""
    import hashlib

    bad = []
    for rel, expected in sorted((files if files is not None else FILES).items()):
        path = Path(root) / rel
        if not path.is_file():
            bad.append(f"{rel} (missing)")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            bad.append(rel)
    return bad


def verify_checkout(root: Path, files: dict[str, str] | None = None) -> None:
    bad = mismatches(root, files)
    if bad:
        raise RunRefused(f"InjecAgent checkout differs from the pin {COMMIT[:8]}: {bad}")
