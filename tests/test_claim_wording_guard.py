
import pytest

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate
FORBIDDEN = [
    'guarantees safety',
    'mathematically unassailable',
    'externally validated',
    'production safe',
    'mathematical uangripelig',
]


def _scan_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            txt = f.read().lower()
            return txt
    except FileNotFoundError:
        return ''


def test_readme_and_claim_register_no_forbidden_phrases():
    files = ['README.md', 'docs/claim_register.md']
    txt = '\n'.join(_scan_file(p) for p in files)
    for phrase in FORBIDDEN:
        assert phrase not in txt, f'Forbidden claim phrase found: {phrase}'
