# REMORA: Enterprise Frontend Plan

A minimalist, professional marketing/research site for the REMORA governed agentic AI reference architecture, targeting enterprise & governance audiences (CISO, AI risk, infra leads).

## Design direction

- **Tone:** restrained, technical, evidence-first. Closer to Stripe / Linear / Anthropic research pages than a SaaS landing.
- **Palette:** near-white background (#FAFAF7), deep ink foreground (#0B0E14), single cool accent (deep indigo / signal blue) used sparingly for state and links. Generous negative space.
- **Typography:** serif display for headings (Instrument Serif or similar) paired with a precise grotesque for body (Inter Tight / Söhne-like). Monospace (JetBrains Mono) for decision states, equations, and code.
- **Composition:** single column, wide measure, hairline 1px dividers, small caps section labels, footnote-style citations `[S1]`, numbered sections matching the whitepaper.
- **No:** gradients, glassmorphism, decorative icons, generic "trusted by" logos, dual hero CTAs.

## Information architecture (routes)

```
/                Home — thesis, decision states, CTA to whitepaper
/architecture    Control plane diagram, runtime components, capability inventory
/evidence        Benchmarks, tool-call safety table, calibration, negative results
/governance      Threat model, policy gates, NIST AI RMF alignment
/whitepaper      Full whitepaper reader (sectioned, with citations)
```

Each route gets its own `head()` with unique title/description/og tags.

## Page-level content

**Home (`/`)**

- Eyebrow: "REMORA · v0.6.0 · Reference architecture"
- H1 (serif): "A governance control plane for agentic AI."
- Sub: one-sentence thesis from the whitepaper.
- Decision-state row: ACCEPT / VERIFY / ABSTAIN / ESCALATE as mono chips with one-line definitions.
- Architecture diagram (SVG, hand-built, Input → Oracle pool → Canonicalize → Consensus → Uncertainty → Policy gate → Decision, with Evidence + Audit branches).
- Three pillars: Selective reliability · Safe tool execution · Auditable decisions.
- Evidence-scope disclosure block (boxed, muted) reproducing the audit warning.
- Footer with citations link, repo head `5e051b9`, prepared-for line.

**Architecture (`/architecture`)**

- Decision function `D = g(C, U, P, E, R)` rendered in mono.
- Lyapunov-style monitor `V(t) = H(t) + λD(t)`.
- Runtime capability inventory table (FastGate, OracleDiversityTracker, PlattScaler, DomainCoverageOptimizer, etc.).

**Evidence (`/evidence`)**

- Benchmark tables (full-coverage QA N=302 / N=544, tool-call safety v2).
- Calibration & negative-results section: explicit about what REMORA is _not_.

**Governance (`/governance`)**

- Threat model table (false consensus, prompt injection, etc., with REMORA control + residual risk).
- World-class roadmap as a 6-step numbered list.

**Whitepaper (`/whitepaper`)**

- Long-form reader rendering the parsed whitepaper sections with sticky TOC on desktop, citation tooltips for `[S1]`–`[S13]`, and `[E1]`+ external references.

## Component inventory

- `SiteHeader`: wordmark "REMORA", thin nav, version pill.
- `SiteFooter`: citations, repo head, prepared-for, evidence-scope note.
- `SectionLabel`, small-caps numbered label.
- `DecisionChip`: mono chip for ACCEPT/VERIFY/ABSTAIN/ESCALATE with semantic color tokens.
- `ArchitectureDiagram`, inline SVG, responsive.
- `EvidenceTable`: minimal hairline table with column alignment for numerics.
- `Callout`: boxed muted block for warnings / audit notes.
- `Citation`: inline `[Sx]` with hover tooltip.

## Technical details

- TanStack Start routes under `src/routes/` (flat dot convention). One route file per page; each sets unique `head()` meta including og:title / og:description.
- Design tokens defined in `src/styles.css` only: semantic vars (`--background`, `--foreground`, `--accent`, `--muted`, `--border`, decision-state colors). All component styling via Tailwind utilities bound to tokens; no hardcoded hex in components.
- Fonts loaded via Google Fonts `<link>` in `__root.tsx` head (or self-hosted later).
- SVG diagrams authored by hand (no chart library needed).
- Whitepaper content stored as typed TS data modules in `src/content/whitepaper.ts` (sections, tables, citations) so routes can reuse it.
- No backend / Lovable Cloud needed for v1, pure presentation.
- Replace placeholder `src/routes/index.tsx` content.

## Out of scope (v1)

- Auth, user accounts, contact forms.
- Live demos / interactive policy playground.
- PDF download wiring (placeholder link only until asset provided).
- CMS / blog.

Approve to build.
