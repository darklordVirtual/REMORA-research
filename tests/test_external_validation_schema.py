import json
import os
import pytest


def test_raw_jsonl_schema_exists():
    path = os.path.join('results', 'external_validation_raw.jsonl')
    if not os.path.exists(path):
        pytest.skip('external_validation_raw.jsonl not present; run scripts/run_external_validation.py first')

    with open(path) as f:
        line = f.readline()
        assert line, 'file is empty'
        row = json.loads(line)
        required = [
            'dataset', 'item_id', 'question', 'decision_hash', 'action', 'phase', 'trust'
        ]
        for k in required:
            assert k in row, f'missing required key: {k}'
