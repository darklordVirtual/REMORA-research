# AI-Assisted Development Disclosure

REMORA was built by a human author with the assistance of generative AI
development tools. This document records how those tools were used, what
they were not used for, and how the research integrity of the project is
maintained.

---

## Tools Used

| Field | Detail |
|---|---|
| **Tools** | Claude (Anthropic), primary development assistant throughout |
| **Usage** | Code drafting, refactoring, test scaffolding, documentation editing, language revision, brainstorming, architecture discussion, literature search support |
| **Not used for** | Inventing results, fabricating citations, generating unverified benchmark numbers, producing fake experiments |
| **Human control** | Every commit reviewed and approved by the author; all tests verified to pass on committed code; all cited sources checked against originals; all numerical claims tied to committed artifacts and automated tests |
| **Reproducibility** | All scripts committed to git; all result artifacts locked under `artifacts/`; all claims linked to artifact paths and test IDs in `docs/claim_register.md` |
| **Limitation** | AI-generated output was treated as an unverified draft. No AI response was accepted as evidence unless independently confirmed by a committed artifact, a passing test, or a verified external source |

---

## What the Author Did

The human author was responsible for:

- **Defining the research question.** What problem does REMORA address? What
  constitutes a governance outcome? When should an agent action be blocked,
  verified, abstained, or escalated?

- **Designing the architecture.** The five-stage cascade, the thermodynamic
  phase model, the AROMER learning loop, the AII formula, the DecisionEnvelope
  contract, the shadow-mode replay mechanism, and the claim-hygiene system were
  designed by the author. AI tools were used to explore alternatives and draft
  implementations, not to originate the design.

- **Establishing the claim-hygiene protocol.** The rule that no number may
  appear in a paper, README, or badge without a committed artifact was the
  author's design decision. This constraint was enforced iteratively throughout
  the project, including removing overclaiming statements identified during
  review.

- **Keeping the negative results.** Every regression, every gap (Gap 2: FA=22.2%
  on aradhye holdout; Gap 4: NLI/SE DLL block), every documented failure
  (§9–§13 in NEGATIVE_RESULTS.md) was preserved by the author's decision, in
  some cases against AI suggestions to frame results more optimistically. The
  claim register marks `not_supported` and `failed` claims as first-class
  entries.

- **Running and verifying experiments.** All benchmark runs, all artifact
  generation scripts, and all regression tests were executed by the author. The
  AROMER live deployment (aromer.razorsharp.workers.dev) was configured,
  monitored, and controlled by the author across 13+ autonomous adaptation
  cycles.

- **Selecting and verifying sources.** All citations were opened, verified for
  author/title/venue/DOI correctness, and confirmed to support the specific
  claim they were cited for. No AI-generated reference was accepted without this
  check.

- **Resolving ambiguity.** Methodological choices, the proxy trust formula, the
  structural gate flags, the five-condition ablation design, the brr EMA window
  size, the production gate list, required the author to make judgement calls
  that AI tools could propose but not decide.

- **Standing behind all claims.** The author is the sole responsible party for
  every assertion in this research prototype. No AI tool is listed as an author
  and no AI tool can be held accountable for errors. That accountability rests
  entirely with the human author.

---

## What AI Tools Did

Generative AI tools acted as a development assistant, comparable to an IDE
with advanced autocomplete, an interactive documentation tool, or a code
reviewer that can draft alternatives:

- Generated initial implementations of described interfaces (e.g., structural
  gate functions, proxy trust scoring, the five-condition ablation scaffold),
  which were subsequently reviewed line by line, corrected, and tested.
- Drafted prose for documentation sections, which were edited for technical
  accuracy before inclusion.
- Proposed alternative architectures and explained trade-offs, which the author
  evaluated and chose from.
- Helped locate relevant literature, which the author then read and verified.
- Suggested test cases, which the author extended and adapted.
- Translated intent into code skeletons, none of which were accepted without
  review and test coverage.

In no case was AI-generated output treated as a research result. The
distinction enforced throughout this project:

```
AI-generated suggestion  ≠  verified method
AI-generated prose       ≠  scientific evidence
AI-generated code        ≠  tested, reproducible implementation
```

---

## How This Fits the Claim-Hygiene System

REMORA's own `docs/claim_register.md` and `docs/thermodynamics/claim_ledger.yaml`
enforce the same epistemic standard that governs this disclosure:

- Every claim requires a committed artifact and an automated test.
- Uncertain or disproven claims are recorded as `candidate` or `not_supported`,
  not silently removed.
- External replication is listed as a distinct evidence level, explicitly
  required before any `externally_validated` label.

AI-generated text was subject to exactly the same standard. No AI output was
promoted from draft to claim without artifact evidence.

---

## For Reviewers

If you are reviewing this project and want to assess the human authorship:

1. **Git history** records the iterative decisions: design regressions,
   architectural pivots, negative results kept, overclaiming statements removed.
   `git log --all --oneline` shows the full trajectory.

2. **NEGATIVE_RESULTS.md** documents every failure the author chose to
   preserve, including cases where AI suggestions pointed toward more optimistic
   framing.

3. **The claim register** (`docs/claim_register.md`) shows the author's
   distinction between what is supported, what is theoretical, and what requires
   external replication: a distinction that AI tools cannot make autonomously.

4. **Artifacts and tests** (`artifacts/`, `tests/`) are the primary evidence
   base. They are independent of any AI text generation and are deterministically
   reproducible.

5. **The production gates** (longitudinal stability audit, closed
   2026-07-17; RBAC audit, closed with recorded deviation; independent
   human review, still open) represent the author's own assessment of what
   remains before the system can claim deployment readiness, a conservative
   judgement kept despite the system's strong internal results.

---

## arXiv Compliance

Generative AI language tools are not listed as authors in this work, in
accordance with arXiv policy ([arXiv help, metadata fields][1]). AI tools
were used as described above, as assistive development tools, not as
autonomous researchers, co-authors, or independent sources of experimental
evidence.

[1]: https://info.arxiv.org/help/prep.html "Metadata for Required and Optional Fields, arXiv info"
