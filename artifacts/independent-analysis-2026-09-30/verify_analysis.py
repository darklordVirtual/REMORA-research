"""Verify the report's core measurements against the attached raw artifacts."""

import gzip
import hashlib
import json
from pathlib import Path

out = Path(__file__).resolve().parent
definitions = out / "fault-definitions.json"
assert hashlib.sha256(definitions.read_bytes()).hexdigest() == "241fe7d878df28021b3ee3294ea780a13a1b12c27fcba6c495fd14fe0c6d1733"
faults = json.loads(definitions.read_text(encoding="utf-8"))["faults"]
assert len(faults) == 43
assert sum(f["class"] == "hand_picked" for f in faults) == 24
assert sum(f["class"] == "systematic" for f in faults) == 19
raw = json.loads(gzip.decompress((out / "raw-row-outputs.json.gz").read_bytes()))
assert raw["fault_definitions_sha256"] == hashlib.sha256(definitions.read_bytes()).hexdigest()
expected = {"v1.2": {"hand_picked": (23, 22, 23), "systematic": (19, 19, 19)},
            "v1.3": {"hand_picked": (24, 23, 24), "systematic": (19, 19, 19)}}
for version, groups in expected.items():
    rows = raw["versions"][version]
    assert len(rows) == 43
    for group, totals in groups.items():
        selected = [r for r in rows if r["class"] == group]
        measured = (sum(bool(r["row1_kill_cases"]) for r in selected),
                    sum(bool(r["row2_kill_cases"]) for r in selected),
                    sum(r["row3_kill"] for r in selected))
        assert measured == totals, (version, group, measured)
ast = json.loads((out / "ast-sweep.json").read_text(encoding="utf-8"))
assert (ast["mutants"], ast["first_order"], ast["second_order"], ast["killed"], len(ast["survived"])) == (905, 705, 200, 901, 4)
assert len(ast["redundancy"]["fragile"]) == 18
report = (out / "report.md").read_text(encoding="utf-8")
assert "Pending" not in report and "241fe7d878df28021b3ee3294ea780a13a1b12c27fcba6c495fd14fe0c6d1733" in report
print("verified: hash, 43 faults, six rows per fault, AST sweep counts, report completeness")
