---
name: remora-deslop
description: Use when writing or rewriting any reader-facing Markdown in REMORA-research (README, docs/, ARCHITECTURE, paper .md), when the prose-style ratchet (scripts/check_prose_style.py) fails, or when asked to "deslop", "fjern AI-slop", "rydd prosa", "skriv om dokumentasjon". Removes structural AI-writing tells without touching claims, numbers, anchors or preserved history.
---

# remora-deslop

Adapted from stephenturner/skill-deslop and poteto/noodle unslop. The
vocabulary catalogs in those skills were measured at zero in this repo
(2026-08-26). What this repo has is structural: em dashes at about five per
thousand words, arrows inside sentences, bold-first bullet lists. This skill
targets those, and adds the constraints an assurance repository needs that
neither source has.

## Hard constraints (never violated by a prose pass)

1. Numbers, percentages, counts, dates, commit SHAs, issue numbers, CLAIM-/
   CAP-/REM-/RF-/DOC- identifiers and claim anchors are copied verbatim.
   A prose pass changes wording only. If a number looks wrong, stop and
   report it; do not fix it in passing.
2. Generated documents are rewritten in their generator, never in the
   output. Register status `generated` and `generated_by` name the script.
3. NEGATIVE_RESULTS.md section markers (open/accepted/superseded) and any
   text labelled superseded, historical or withdrawn are preserved word for
   word. `docs/archive/`, `attic/` and `docs/researchpapers/` are out of
   scope entirely.
4. Pre-registered and frozen documents are never reworded after the fact:
   `docs/assurance/statistical_analysis_plan_v*.md`, `superseded_claims.md`,
   `experiments/*/PREREGISTERED.md`. Their counts simply stay in the baseline.
5. The paper is edited in `paper/remora_paper.md` and `paper/remora_paper.tex`
   together; the PDF is master-owned. `scripts/check_paper_sync.py` must pass.
6. README.md stays within its line budget (`check_document_governance.py`).
7. Every gate that touches text must pass before the PR: document
   governance, links, readme-claims, paper-sync, claim-provenance, and
   `scripts/check_prose_style.py` (counts may only fall; then run
   `--update-baseline` and commit the baseline in the same PR).

## What to remove

- Em dash in prose. Rewrite the sentence: split it, use a comma, a colon
  before a list, or parentheses. Do not search-and-replace the character.
- Arrow (→, ⇒) inside a sentence. Write the relation in words. Keep arrows
  in pipeline notation lines (`A → B → C`), tables, code and diagrams.
- Bold-first bullets (`- **Label:** text`). Turn the list into prose, or a
  table if the items really are label/value pairs, or plain bullets whose
  first words carry the meaning without bold.
- "Not X, but Y" / "not just X, it's Y". State Y.
- Filler openers and transitions: "it is worth noting", "it should be
  noted", "importantly,", "notably,", "in order to".
- Superficial participle tails: ", ensuring safety", ", highlighting the
  need for". Either say concretely what is ensured, or delete.
- Copula dodges: "serves as", "stands as". Use "is".
- Tool or assistant residue in reader-facing text: "ChatGPT analysis",
  "as the assistant noted", "let me know", "hope this helps". Attribution of
  AI assistance belongs in docs/AI_USE.md only.
- Triple stacks of short fragments for emphasis; self-posed questions
  answered in the next sentence; "In conclusion"; "Despite these challenges".

## What to keep (rejected from the source skills)

- Passive voice and impersonal register where the subject is the system or
  the evidence. "The grant is consumed atomically" is correct technical prose.
- Lists of three when there are three things. No tricolon ban.
- Precise domain terms (fail-closed, nonce, envelope hash, PEP, PDP).
- Caveats and hedges that carry information ("not claimed as production
  evidence"). Remove only hedges that stack without adding a condition.
- No "soul", opinions, first person or deliberate mess. Assurance documents
  are read by reviewers looking for claims; voice is not the goal.

## Process for a systematic pass

1. `python scripts/check_prose_style.py --report` to pick the next file by
   count. Work one layer per PR: reader-facing entry docs first (README,
   ARCHITECTURE, DEVELOPER_OVERVIEW, CONTRIBUTING, docs/00-13), then
   docs/assurance, then docs/design and roadmap, then generators, then paper.
2. Read the whole file before editing. Rewrite sentence by sentence; keep
   each paragraph's claims and their order.
3. Run the gates in constraint 7. Diff the file and re-read the diff for
   any changed number or identifier.
4. `python scripts/check_prose_style.py --update-baseline`, commit the
   baseline with the text.
5. One PR per layer, titled `docs(prose): <layer>`; the PR body lists the
   before/after counts from the scanner.
