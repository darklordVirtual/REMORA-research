"""Summarize the independently recorded row outputs and committed records."""

import gzip
import json
from collections import Counter
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[1]
raw = json.loads(gzip.decompress((out / "raw-row-outputs.json.gz").read_bytes()))
for version, rows in raw["versions"].items():
    print(version, "faults", len(rows))
    for group in ("hand_picked", "systematic"):
        selected = [r for r in rows if r["class"] == group]
        print(group, len(selected),
              "row1", sum(bool(r["row1_kill_cases"]) for r in selected),
              "row2", sum(bool(r["row2_kill_cases"]) for r in selected),
              "row3", sum(r["row3_kill"] for r in selected))
    for r in rows:
        if r["id"] == "H15":
            print("H15 detail", "row1", r["row1_kill_cases"], "row2", r["row2_kill_cases"],
                  "row3", r["row3"].get("failures", [])[:8])
        if not r["row1_kill_cases"] or not r["row2_kill_cases"] or not r["row3_kill"]:
            print("exception", r["id"], "row1", r["row1_kill_cases"],
                  "row2", r["row2_kill_cases"], "row3", r["row3_kill"],
                  "runner_failures", r["row3"].get("failures", [])[:5])
    record = json.loads((root / "conformance" / ("evidence-sufficiency-" + version) / "run-record.json").read_text(encoding="utf-8"))
    corpus = json.loads((root / "conformance" / ("evidence-sufficiency-" + version) / "cases.json").read_text(encoding="utf-8"))
    print("committed", "cases", len(corpus["cases"]), "rejections", len(corpus.get("rejections", [])),
          "failures", len(record["failures"]), "model", record.get("reference_model", {}))
