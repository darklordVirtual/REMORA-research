import shutil
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

AUDIT_SURFACE = [
    "README.md",
    "docs/claim_register.md",
    "docs/assurance/",
    "results/",
    "paper/remora_paper.md",
]

@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """Disponibel kopi av audit-flaten. Metatester muterer KUN denne."""
    for rel in AUDIT_SURFACE:
        src = REPO_ROOT / rel
        if not src.exists():
            continue
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return tmp_path
