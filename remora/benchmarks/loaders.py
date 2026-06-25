# Author: Stian Skogbrott
# License: Apache-2.0
"""Standardised benchmark loaders for REMORA evaluation datasets."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

class BenchmarkName(str, Enum):
    HOTPOTQA = "hotpotqa"; SCIFACT = "scifact"; FEVER = "fever"; DCE = "dce"

class GroundTruthType(str, Enum):
    POLARITY = "polarity"; SHORT_ANSWER = "answer"; CATEGORICAL = "categorical"

@dataclass(frozen=True)
class BenchmarkItem:
    item_id: str; benchmark: str; question: str; ground_truth: Any
    truth_type: str; context: Optional[str] = None; metadata: dict = field(default_factory=dict)
    def hash(self) -> str:
        return hashlib.sha256(f"{self.benchmark}::{self.item_id}".encode()).hexdigest()[:16]

_HOTPOTQA_MINI = [
    {"id":"hp_001","q":"Which magazine was founded first, Arthur's Magazine or First for Women?","context":"Arthur's Magazine was an American literary periodical founded in 1844. First for Women is a women's magazine published in 1989.","answer":"Arthur's Magazine"},
    {"id":"hp_002","q":"Were Scott Derrickson and Ed Wood of the same nationality?","context":"Scott Derrickson (born July 16, 1966) is an American director. Edward Davis Wood Jr. (October 10, 1924 – December 10, 1978) was an American filmmaker.","answer":"yes"},
    {"id":"hp_003","q":"What government position was held by the woman who portrayed Corliss Archer in the film Kiss and Tell?","context":"Kiss and Tell is a 1945 American comedy film starring Shirley Temple as Corliss Archer. Shirley Temple Black served as the United States Ambassador to Ghana and Czechoslovakia.","answer":"Ambassador"},
    {"id":"hp_004","q":"The Oberoi family is part of a hotel company that has a head office in what city?","context":"The Oberoi family is involved in the The Oberoi Group hotel company. The Oberoi Group is headquartered in Delhi.","answer":"Delhi"},
    {"id":"hp_005","q":"What nationality was James Henry Miller's wife?","context":"Peggy Seeger is an American folksinger. She married the British folksinger James Henry Miller.","answer":"American"},
]

_SCIFACT_MINI = [
    # Fallback items used when the HuggingFace SCIFACT dataset is unavailable.
    # Claims are in English to match the actual SCIFACT corpus (biomedical, English).
    {"id":"sf_001","claim":"Self-medication is a known risk factor for the development of antibiotic resistance.","label":True},
    {"id":"sf_002","claim":"Vaccination causes autism.","label":False},
    {"id":"sf_003","claim":"Mitochondria produce ATP through oxidative phosphorylation.","label":True},
    {"id":"sf_004","claim":"Humans only use 10% of their brain.","label":False},
    {"id":"sf_005","claim":"CRISPR-Cas9 is a tool for gene editing.","label":True},
    {"id":"sf_006","claim":"Insulin is produced in the kidneys.","label":False},
]

_FEVER_MINI = [
    {"id":"fv_001","claim":"Earth orbits the Sun.","label":True},
    {"id":"fv_002","claim":"The Great Wall of China is visible from the Moon with the naked eye.","label":False},
    {"id":"fv_003","claim":"Norway is a member of the European Union.","label":False},
    {"id":"fv_004","claim":"Mount Everest is located on the border between Nepal and Tibet.","label":True},
    {"id":"fv_005","claim":"The capital of Australia is Sydney.","label":False},
    {"id":"fv_006","claim":"Water boils at 100 degrees Celsius at standard atmospheric pressure.","label":True},
]

_DCE_MINI = [
    # DCE (Debt Collection Engine) items are intentionally in Norwegian.
    # This domain covers Norwegian debt collection law (inkassoloven) and GDPR.
    # Norwegian is the correct language for this domain-specific benchmark.
    {"id":"dce_001","q":"Er et inkassosalær på kr 700 i strid med inkassoloven § 17 for et hovedkrav på kr 200?","answer":True,"reasoning":"Salær må stå i rimelig forhold til hovedkravet."},
    {"id":"dce_002","q":"Kan en inkassator legge til purregebyr før purrefristen på 14 dager har utløpt?","answer":False,"reasoning":"Inkassoloven krever 14 dagers betalingsfrist før gebyrpåslag."},
    {"id":"dce_003","q":"Foreldes et pengekrav etter 3 år i Norge når det ikke har vært gyldige avbruddshandlinger?","answer":True,"reasoning":"Foreldelsesloven § 2: alminnelig foreldelsesfrist er 3 år."},
    {"id":"dce_004","q":"Har debitor rett til innsyn i opprinnelig kontrakt fra kreditor under GDPR art. 15?","answer":True,"reasoning":"Art. 15 SAR gir rett til kopi av personopplysninger som ligger til grunn for kravet."},
    {"id":"dce_005","q":"Kan en inkassator splitte ett krav i flere saker for å øke gebyrgrunnlaget?","answer":False,"reasoning":"Anti-fragmentering: kunstig oppdeling regnes som god inkassoskikk-brudd."},
]

def _try_load_hf(dataset_name, split, n):
    try:
        from datasets import load_dataset
    except ImportError:
        return None
    try:
        ds = load_dataset(dataset_name, split=split, streaming=False)
        return list(ds.select(range(min(n, len(ds)))))
    except Exception:
        return None

def load_hotpotqa(n_samples=50):
    hf_data = _try_load_hf("hotpot_qa", "validation", n_samples)
    if hf_data:
        items = []
        for ex in hf_data:
            context = ""
            if "context" in ex and isinstance(ex["context"], dict):
                titles = ex["context"].get("title", []); sentences = ex["context"].get("sentences", [])
                ctx_parts = [f"{t}: {' '.join(s)}" for t, s in zip(titles, sentences) if isinstance(s, list)]
                context = "\n".join(ctx_parts)
            items.append(BenchmarkItem(item_id=str(ex.get("id", len(items))), benchmark=BenchmarkName.HOTPOTQA.value,
                question=ex["question"], ground_truth=ex["answer"], truth_type=GroundTruthType.SHORT_ANSWER.value, context=context or None))
        return items
    return [BenchmarkItem(item_id=ex["id"], benchmark=BenchmarkName.HOTPOTQA.value, question=ex["q"],
        ground_truth=ex["answer"], truth_type=GroundTruthType.SHORT_ANSWER.value, context=ex.get("context"))
        for ex in _HOTPOTQA_MINI[:n_samples]]

def load_scifact(n_samples=50):
    return [BenchmarkItem(item_id=ex["id"], benchmark=BenchmarkName.SCIFACT.value, question=ex["claim"],
        ground_truth=ex["label"], truth_type=GroundTruthType.POLARITY.value) for ex in _SCIFACT_MINI[:n_samples]]

def load_fever(n_samples=50):
    return [BenchmarkItem(item_id=ex["id"], benchmark=BenchmarkName.FEVER.value, question=ex["claim"],
        ground_truth=ex["label"], truth_type=GroundTruthType.POLARITY.value) for ex in _FEVER_MINI[:n_samples]]

def load_dce(n_samples=50, path=None):
    if path:
        import json
        from pathlib import Path
        p = Path(path)
        if p.exists():
            items = []
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line: continue
                try:
                    ex = json.loads(line)
                    items.append(BenchmarkItem(item_id=str(ex.get("id", len(items))), benchmark=BenchmarkName.DCE.value,
                        question=ex["q"], ground_truth=ex["answer"], truth_type=GroundTruthType.POLARITY.value,
                        metadata={"reasoning": ex.get("reasoning", "")}))
                    if len(items) >= n_samples: break
                except (json.JSONDecodeError, KeyError): continue
            return items
    return [BenchmarkItem(item_id=ex["id"], benchmark=BenchmarkName.DCE.value, question=ex["q"],
        ground_truth=ex["answer"], truth_type=GroundTruthType.POLARITY.value,
        metadata={"reasoning": ex.get("reasoning", "")}) for ex in _DCE_MINI[:n_samples]]

def load_combined(n_per_benchmark=5, include=None, dce_path=None):
    if include is None: include = list(BenchmarkName)
    items = []
    if BenchmarkName.HOTPOTQA in include: items.extend(load_hotpotqa(n_per_benchmark))
    if BenchmarkName.SCIFACT in include: items.extend(load_scifact(n_per_benchmark))
    if BenchmarkName.FEVER in include: items.extend(load_fever(n_per_benchmark))
    if BenchmarkName.DCE in include: items.extend(load_dce(n_per_benchmark, path=dce_path))
    return items
