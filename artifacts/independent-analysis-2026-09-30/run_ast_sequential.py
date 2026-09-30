"""Run the committed AST sweep sequentially when Windows blocks process pools."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "scripts/mutation_evidence_sufficiency_ast.py"
spec = importlib.util.spec_from_file_location("independent_ast_sweep", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SequentialPool:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def map(self, fn, jobs, chunksize=1):
        return map(fn, jobs)


module.ProcessPoolExecutor = SequentialPool
raise SystemExit(module.main(["--workers", "1", "--json", str(Path(__file__).resolve().parent / "ast-sweep.json")]))
