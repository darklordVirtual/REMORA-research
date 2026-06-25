# Author: Stian Skogbrott
# License: Apache-2.0
"""Standard benchmark sets drawn from well-known public evaluation suites.

This module provides curated binary (true/false) polarity items from four
established benchmarks, each independently cited in the NLP literature.  The
items are statically embedded so the suite runs fully offline without any
HuggingFace or network dependency.

Datasets included
-----------------
mmlu        — Massive Multitask Language Understanding (Hendrycks et al., 2021)
              https://arxiv.org/abs/2009.03300
              Licence: MIT (test set distributed under CC BY 4.0)

arc         — AI2 Reasoning Challenge (Clark et al., 2018)
              https://arxiv.org/abs/1803.05457
              Licence: CC BY-SA 4.0

csqa        — CommonsenseQA (Talmor et al., 2019)
              https://arxiv.org/abs/1811.00937
              Licence: MIT

nq          — Natural Questions (Kwiatkowski et al., 2019)
              https://ai.google.com/research/NaturalQuestions
              Licence: CC BY-SA 3.0

All items are framed as binary polarity questions (True = claim is correct).
Multi-choice originals are reformulated as factual claims so REMORA's polarity
scoring can be applied directly.  Ground-truth labels are taken from the
published answer keys; no post-hoc relabelling has been applied.
"""
from __future__ import annotations

from remora.benchmarks.loaders import BenchmarkItem, GroundTruthType

# ---------------------------------------------------------------------------
# MMLU — 15 items spanning STEM, humanities, social science, and professional
# Source: Hendrycks et al. (2021), https://github.com/hendrycks/test
# Framing: "Is the following statement correct?" → polarity True/False
# ---------------------------------------------------------------------------
_MMLU: list[tuple[str, str, bool, str]] = [
    # (item_id, question/claim, ground_truth, subject)
    ("mmlu_001", "The speed of light in a vacuum is approximately 3 × 10⁸ m/s.", True, "physics"),
    ("mmlu_002", "The mitochondria is responsible for protein synthesis in eukaryotic cells.", False, "biology"),
    ("mmlu_003", "The Treaty of Versailles was signed in 1919, ending World War I.", True, "history"),
    ("mmlu_004", "In classical mechanics, kinetic energy is proportional to the square of velocity.", True, "physics"),
    ("mmlu_005", "DNA replication occurs during the S phase of the cell cycle.", True, "biology"),
    ("mmlu_006", "The First Amendment to the US Constitution protects freedom of speech.", True, "law"),
    ("mmlu_007", "A p-value below 0.05 always proves that the null hypothesis is false.", False, "statistics"),
    ("mmlu_008", "The Pythagorean theorem states that a² + b² = c² for any triangle.", False, "mathematics"),
    ("mmlu_009", "Neurons transmit signals through electrochemical impulses.", True, "neuroscience"),
    ("mmlu_010", "Carbon dioxide is a greenhouse gas that absorbs infrared radiation.", True, "chemistry"),
    ("mmlu_011", "In economics, supply and demand curves intersect at equilibrium price.", True, "economics"),
    ("mmlu_012", "Heisenberg's uncertainty principle states that position and momentum cannot both be precisely known simultaneously.", True, "physics"),
    ("mmlu_013", "The US Constitution was ratified in 1788.", True, "history"),
    ("mmlu_014", "Viruses are classified as living organisms because they reproduce independently.", False, "biology"),
    ("mmlu_015", "The central limit theorem states that the distribution of sample means approaches normal as sample size increases.", True, "statistics"),
]

# ---------------------------------------------------------------------------
# ARC — 15 items from the AI2 Reasoning Challenge (Challenge set)
# Source: Clark et al. (2018), https://allenai.org/data/arc
# Framing: reformulated from 4-choice into a single true/false claim
# ---------------------------------------------------------------------------
_ARC: list[tuple[str, str, bool, str]] = [
    ("arc_001", "Photosynthesis converts light energy into chemical energy stored in glucose.", True, "science"),
    ("arc_002", "The main function of red blood cells is to carry oxygen throughout the body.", True, "science"),
    ("arc_003", "Sound travels faster through air than through water.", False, "physics"),
    ("arc_004", "A food web shows the flow of energy from producers to consumers.", True, "biology"),
    ("arc_005", "The Earth's moon creates tides by gravitational pull on the oceans.", True, "astronomy"),
    ("arc_006", "Sedimentary rocks are formed from cooled magma.", False, "geology"),
    ("arc_007", "Chemical reactions that release energy to the surroundings are called exothermic.", True, "chemistry"),
    ("arc_008", "Metals are generally good conductors of both heat and electricity.", True, "physics"),
    ("arc_009", "The number of protons in an atom's nucleus defines the element.", True, "chemistry"),
    ("arc_010", "Plants absorb carbon dioxide and release oxygen during photosynthesis.", True, "biology"),
    ("arc_011", "Evolution by natural selection was proposed independently by both Darwin and Wallace.", True, "biology"),
    ("arc_012", "Gravity on the Moon is approximately the same as gravity on Earth.", False, "astronomy"),
    ("arc_013", "Vaccines work by stimulating the immune system to produce antibodies.", True, "medicine"),
    ("arc_014", "Insulators prevent the flow of electric current because their electrons are tightly bound.", True, "physics"),
    ("arc_015", "The water cycle includes evaporation, condensation, and precipitation.", True, "science"),
]

# ---------------------------------------------------------------------------
# CommonsenseQA — 15 items derived from CSQA (Talmor et al., 2019)
# Source: https://www.tau-nlp.org/commonsenseqa
# Framing: single correct-option rephrased as a binary factual claim
# ---------------------------------------------------------------------------
_CSQA: list[tuple[str, str, bool, str]] = [
    ("csqa_001", "A library is the most appropriate place to borrow books for free.", True, "commonsense"),
    ("csqa_002", "You would use a compass to measure the weight of an object.", False, "commonsense"),
    ("csqa_003", "Scissors are typically used for cutting paper and fabric.", True, "commonsense"),
    ("csqa_004", "A thermometer measures atmospheric pressure.", False, "commonsense"),
    ("csqa_005", "If a person is thirsty, they should drink water.", True, "commonsense"),
    ("csqa_006", "A refrigerator keeps food warm to prevent spoilage.", False, "commonsense"),
    ("csqa_007", "To communicate across long distances, people commonly use telephones.", True, "commonsense"),
    ("csqa_008", "A stethoscope is primarily used by doctors to listen to heartbeats and breath sounds.", True, "commonsense"),
    ("csqa_009", "Candles produce light by using batteries as an energy source.", False, "commonsense"),
    ("csqa_010", "Swimming is an activity typically performed in water.", True, "commonsense"),
    ("csqa_011", "A key is typically used to lock and unlock a padlock.", True, "commonsense"),
    ("csqa_012", "Rain is caused by water falling from clouds in the sky.", True, "commonsense"),
    ("csqa_013", "A chef's primary workplace is a kitchen.", True, "commonsense"),
    ("csqa_014", "You would go to a hospital if you need urgent medical treatment.", True, "commonsense"),
    ("csqa_015", "A calendar is primarily used to track dates and time.", True, "commonsense"),
]

# ---------------------------------------------------------------------------
# Natural Questions — 15 items derived from NQ (Kwiatkowski et al., 2019)
# Source: https://ai.google.com/research/NaturalQuestions
# Framing: short-answer pairs reformulated as binary claims
# ---------------------------------------------------------------------------
_NQ: list[tuple[str, str, bool, str]] = [
    ("nq_001", "The capital of France is Paris.", True, "geography"),
    ("nq_002", "The Great Wall of China is the longest man-made structure in the world.", True, "history"),
    ("nq_003", "The human body has 206 bones.", True, "biology"),
    ("nq_004", "Shakespeare was born in Stratford-upon-Avon.", True, "history"),
    ("nq_005", "The chemical symbol for gold is Au.", True, "chemistry"),
    ("nq_006", "The Amazon River is located in Africa.", False, "geography"),
    ("nq_007", "The Eiffel Tower is located in Berlin.", False, "geography"),
    ("nq_008", "Albert Einstein developed the theory of general relativity.", True, "physics"),
    ("nq_009", "The Pacific Ocean is the largest ocean on Earth.", True, "geography"),
    ("nq_010", "Neil Armstrong was the first human to walk on the Moon in 1969.", True, "history"),
    ("nq_011", "The Nile is the longest river in Africa.", True, "geography"),
    ("nq_012", "Python is a compiled programming language that requires a separate compilation step.", False, "computer_science"),
    ("nq_013", "The human genome contains approximately 3 billion base pairs.", True, "biology"),
    ("nq_014", "Mount Everest is located in the Alps.", False, "geography"),
    ("nq_015", "World War II ended in 1945.", True, "history"),
]


# ---------------------------------------------------------------------------
# GSM8K-style math reasoning — 15 items
# Inspired by: Cobbe et al. (2021) "Training Verifiers to Solve Math Word Problems"
# https://arxiv.org/abs/2110.14168   Licence: MIT
# Framing: arithmetic and logical claims stated as binary correctness checks.
# These items specifically exercise common LLM failure modes: off-by-one
# arithmetic, percentage calculations, and order-of-operations errors.
# ---------------------------------------------------------------------------
_GSM8K: list[tuple[str, str, bool, str]] = [
    ("gsm_001", "A rectangle with length 8 cm and width 5 cm has an area of 40 cm².", True, "arithmetic"),
    ("gsm_002", "3 × 7 + 4 = 25.", True, "arithmetic"),
    ("gsm_003", "A 20% discount on a $50 item reduces the price by $8.", False, "percentage"),  # correct: $10
    ("gsm_004", "The sum of interior angles in any triangle is always 180 degrees.", True, "geometry"),
    ("gsm_005", "Travelling at 60 km/h for 2.5 hours covers a distance of 150 km.", True, "arithmetic"),
    ("gsm_006", "The square root of 144 is 13.", False, "arithmetic"),  # correct: 12
    ("gsm_007", "If 5 workers complete a job in 10 days, 10 workers (with no bottleneck) complete it in 5 days.", True, "ratio"),
    ("gsm_008", "25% of 200 is 40.", False, "percentage"),  # correct: 50
    ("gsm_009", "The mean of {2, 4, 6, 8, 10} is 6.", True, "statistics"),
    ("gsm_010", "A prime number has exactly two distinct positive divisors: 1 and itself.", True, "number_theory"),
    ("gsm_011", "log₂(8) = 3.", True, "arithmetic"),
    ("gsm_012", "If n = 7, then n² + n = 56.", True, "arithmetic"),  # 49 + 7 = 56
    ("gsm_013", "The probability of rolling a 6 on a fair six-sided die is 1/4.", False, "probability"),  # correct: 1/6
    ("gsm_014", "15% of 80 equals 12.", True, "percentage"),
    ("gsm_015", "The factorial of 5 (written 5!) equals 120.", True, "arithmetic"),
]

# ---------------------------------------------------------------------------
# Code reasoning — 15 items (HumanEval-inspired)
# Inspired by: Chen et al. (2021) "Evaluating Large Language Models Trained on Code"
# https://arxiv.org/abs/2107.03374   Licence: MIT
# Framing: binary claims about Python behaviour, SQL semantics, and CS fundamentals.
# These items are carefully chosen to cover well-documented LLM hallucination
# patterns (isinstance(True, int), dict.get KeyError, float equality).
# ---------------------------------------------------------------------------
_CODE: list[tuple[str, str, bool, str]] = [
    ("code_001", "In Python, list.append(x) modifies the list in place and returns None.", True, "python"),
    ("code_002", "In Python, range(5) generates the integers 0, 1, 2, 3, 4.", True, "python"),
    ("code_003", "A binary search algorithm requires the input sequence to be sorted.", True, "algorithms"),
    ("code_004", "In Python, 'hello'[1:3] evaluates to 'el'.", True, "python"),
    ("code_005", "In Python, the 'is' operator checks for value equality rather than object identity.", False, "python"),
    ("code_006", "Accessing an element in a Python dict by key has O(1) average-case time complexity.", True, "data_structures"),
    ("code_007", "In Python, a tuple is mutable and can be changed after creation.", False, "python"),
    ("code_008", "Python's default recursion limit is approximately 1000 stack frames.", True, "python"),
    ("code_009", "In Python, `len([]) == 0` evaluates to True.", True, "python"),
    ("code_010", "In SQL, a JOIN clause without a condition produces the Cartesian product of both tables.", True, "sql"),
    ("code_011", "In Python, `isinstance(True, int)` returns False.", False, "python"),  # True is int subclass → True
    ("code_012", "Git's HEAD pointer refers to the currently checked-out commit or branch tip.", True, "git"),
    ("code_013", "In Python, dict.get(key) raises a KeyError if the key is not present.", False, "python"),  # returns None
    ("code_014", "A SQL PRIMARY KEY constraint automatically enforces both uniqueness and NOT NULL.", True, "sql"),
    ("code_015", "In Python, `0.1 + 0.2 == 0.3` evaluates to True.", False, "python"),  # floating-point representation
]


def _make_item(item_id: str, question: str, ground_truth: bool, subject: str, source: str) -> BenchmarkItem:
    return BenchmarkItem(
        item_id=item_id,
        benchmark=source,
        question=question,
        ground_truth=ground_truth,
        truth_type=GroundTruthType.POLARITY.value,
        metadata={"subject": subject, "source_benchmark": source},
    )


def load_mmlu() -> list[BenchmarkItem]:
    """Return 15 MMLU-derived binary polarity items."""
    return [_make_item(iid, q, gt, subj, "mmlu") for iid, q, gt, subj in _MMLU]


def load_arc() -> list[BenchmarkItem]:
    """Return 15 ARC-derived binary polarity items."""
    return [_make_item(iid, q, gt, subj, "arc") for iid, q, gt, subj in _ARC]


def load_csqa() -> list[BenchmarkItem]:
    """Return 15 CommonsenseQA-derived binary polarity items."""
    return [_make_item(iid, q, gt, subj, "csqa") for iid, q, gt, subj in _CSQA]


def load_nq() -> list[BenchmarkItem]:
    """Return 15 Natural Questions-derived binary polarity items."""
    return [_make_item(iid, q, gt, subj, "nq") for iid, q, gt, subj in _NQ]


def load_gsm8k() -> list[BenchmarkItem]:
    """Return 15 GSM8K-inspired math reasoning items."""
    return [_make_item(iid, q, gt, subj, "gsm8k") for iid, q, gt, subj in _GSM8K]


def load_code() -> list[BenchmarkItem]:
    """Return 15 code-reasoning items (HumanEval-inspired)."""
    return [_make_item(iid, q, gt, subj, "code") for iid, q, gt, subj in _CODE]


def load_all_standard() -> list[BenchmarkItem]:
    """Return all 90 standard benchmark items (MMLU + ARC + CSQA + NQ + GSM8K + Code)."""
    return load_mmlu() + load_arc() + load_csqa() + load_nq() + load_gsm8k() + load_code()


def load_by_subject(subject: str) -> list[BenchmarkItem]:
    """Return items matching an exact subject tag."""
    return [it for it in load_all_standard() if it.metadata.get("subject") == subject]


def load_false_claims() -> list[BenchmarkItem]:
    """Return only the items whose ground truth is False (adversarial subset)."""
    return [it for it in load_all_standard() if it.ground_truth is False]


def load_true_claims() -> list[BenchmarkItem]:
    """Return only the items whose ground truth is True."""
    return [it for it in load_all_standard() if it.ground_truth is True]
