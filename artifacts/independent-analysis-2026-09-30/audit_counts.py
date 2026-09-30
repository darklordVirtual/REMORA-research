"""Extract directly reproducible evidence-sufficiency quantities."""

from collections import Counter
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
for version in ("v1", "v1.1", "v1.2", "v1.3"):
    folder = root / "conformance" / ("evidence-sufficiency-" + version)
    corpus = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    record = json.loads((folder / "run-record.json").read_text(encoding="utf-8"))
    gaps = Counter(case.get("gap", "inherited") for case in corpus["cases"])
    print(version, "authored_cases", len(corpus["cases"]), "gaps", dict(gaps),
          "json_rejections", len(corpus.get("rejections", [])), "failures", len(record["failures"]),
          "model", record.get("reference_model", {}).get("documents"),
          "relations", len(record.get("metamorphic_relations", [])))
for name in ("mutation_baseline_evidence_sufficiency_v1.txt",
             "mutation_baseline_evidence_sufficiency_ast_v1.txt"):
    p = root / "docs/assurance" / name
    print(name, "named_survivors", sum(bool(line.strip()) and not line.startswith("#")
                                       for line in p.read_text(encoding="utf-8").splitlines()))
