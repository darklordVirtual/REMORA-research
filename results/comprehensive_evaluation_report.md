# REMORA: Comprehensive Evaluation Report

**Dato:** 2026-06-03  
**Status:** `internally_supported`: alle resultater er fra egne kjøringer; ikke eksternt replikert.  
**Sammendrag:** REMORA leverer genuint bra resultater på det den er designet for (sikkerhets-gating,
audit-dekning, selektiv routing), men ikke som et generelt faktasvarsystem. Det er viktige svakheter
som ikke må bortforklares.

---

## Rask oversikt, hva fungerer og hva fungerer ikke

| Område | Status | Vurdering |
|--------|--------|-----------|
| Unsafe action blokkering (tool-call) | ✅ 0% unsafe execution | Sterk |
| Audit-dekning | ✅ 100% SHA-256 per item | Sterk |
| Latens (governance overhead) | ✅ p50 ~1.1 s | Sterk |
| Selektiv routing (fase-signal) | ✅ +47.6 pp lift ved 18% dekning | Sterk |
| Lyapunov stabilitet | ✅ 87.2% stabile sessions | Moderat |
| Faktaakkuratesse (REMORA full) | ⚠️ Under majority vote | Svak |
| Ekstern validering (uavhengig tredjepart) | ❌ Ikke gjort | Mangler |

---

## 1. Ekstern validering på HF-benchmarks (400 items, live oracle)

**Design:** To spor per item: direkte LLM-svar (5-modell CF-pool, round-robin) + REMORA governance.  
**Datasett:** ARC-Challenge, ARC-Easy, BoolQ, HotpotQA, `seed=42`, `N=100` per datasett.  
**Oracles:** `@cf/meta/llama-3.3-70b-instruct-fp8-fast` + `@cf/meta/llama-4-scout-17b-16e-instruct`  
**Harness:** `scripts/run_external_validation.py`, commit `d3f765c`

### 1.1 Direkte oracle-akkuratesse (baseline uten REMORA)

| Datasett | Akkuratesse | Wilson 95% CI | Riktige | Scoret | Parseable/N |
|----------|-------------|--------------|---------|--------|-------------|
| ARC-Challenge (MC) | **80.2%** | [0.703, 0.875] | 65 | 81 | 81/100 |
| ARC-Easy (MC) | **86.3%** | [0.770, 0.921] | 69 | 80 | 80/100 |
| BoolQ (bool) | **83.7%** | [0.751, 0.897] | 82 | 98 | 98/100 |
| HotpotQA (freetext) | **29.0%** | [0.210, 0.385] | 29 | 100 | 100/100 |

*HotpotQA-tall er substring-match upper bound; token-F1 ville vært lavere.*  
*Akkuratesse reflekterer aggregate av 5 heterogene modeller (3B–70B), ikke én enkelt modell.*

**Kontekst for ARC-tallene:** ARC-Challenge er designet for å vanskeliggjøre retrieval-basert
gjetting. CI-nedre grense 0.703 er klart over tilfeldig (25% for 4-valg MC), noe som bekrefter
at oracle-poolen har genuint faktakunnskap. ARC-Easy på 86.3% er sterk. BoolQ på 83.7% er
konsistent med state-of-the-art for mid-sized modeller.

### 1.2 REMORA governance-distribusjon

| Datasett | N | Accept | Verify | Escalate | Abstain |
|----------|---|--------|--------|----------|---------|
| ARC-Challenge | 100 | 0 | **100** | 0 | 0 |
| ARC-Easy | 100 | 0 | **100** | 0 | 0 |
| BoolQ | 100 | 0 | **100** | 0 | 0 |
| HotpotQA | 100 | 0 | **100** | 0 | 0 |

**Tolkning:** 100% `verify` er korrekt governance-atferd for faktaspørsmål uten kontekst.
REMORA er en circuit breaker, ikke et svarsystem. Uten RAG-hentet evidens finnes det ingen grunn
til å `accept` et faktapåstand, akkurat som en compliance officer ikke skal godkjenne en kontrakt
uten å lese den. Dette er designet korrekt, men gir coverage=0% i dette oppsettet.

**Advarsel:** Dersom man forventer at REMORA skal hjelpe et agent-system å svare riktigere på
faktaspørsmål uten ekstern kontekst, leverer det ikke dette. Det er ikke målet.

### 1.3 Latens

| Datasett | REMORA p50 | REMORA p95 | Direct p50 | Overhead (p50) |
|----------|-----------|-----------|-----------|----------------|
| arc-challenge | **1.226 s** | 3.966 s | 0.315 s | ~4× |
| arc-easy | **1.180 s** | 3.455 s | 0.355 s | ~3× |
| boolq | **1.064 s** | 2.830 s | 0.302 s | ~4× |
| hotpotqa | **1.044 s** | 3.063 s | 0.368 s | ~3× |

**Vurdering:** ~1.1 s p50 for 2-oracle consensus + termodynamisk faseklassifisering + SHA-256 audit
er akseptabelt for governance-beslutninger. p95 under 4 s er godt, ingen timeout-artefakter i denne
kjøringen (forrige kjøring hadde 14 s p50 pga. Groq rate limits; det er nå løst).

---

## 2. Ablasjonsstudie: REMORA vs. baselines

### 2.1 Ablasjon v1 (75 items, 6 betingelser)

**Datasett:** dce_ext (25), fact_ext (25), sci_ext (25)  
**Oracles:** llama-3.3-70b-versatile, claude-3.5-sonnet, gpt-4o

| Betingelse | Beskrivelse | Total akkuratesse | Wilson 95% CI |
|------------|-------------|-------------------|---------------|
| A, Single oracle | llama-3.3-70b alene | 71% (53/75) | [59.6%, 79.8%] |
| B, Majority vote | 3 oracles, plain majority | 71% (53/75) | [59.6%, 79.8%] |
| C, REMORA full | Diversity-vekting + Lyapunov | **32%** (24/75) | [22.5%, 43.2%] |
| D1, Strict router | Alle 3 enige → skip REMORA | 25% (19/75) | [16.9%, 36.2%] |
| D2, Balanced router | Flertall → skip REMORA | 68% (51/75) | [56.8%, 77.5%] |
| D3, Hybrid router | Flertall + conf≥0.80 | 43% (32/75) | [32.1%, 53.9%] |

**⚠️ Kritisk funn:** REMORA full (C) på 32% er **39 prosentpoeng lavere** enn enkel
majority vote (71%). Claim-reformulering til JSON-format (`{"claim": ..., "answer": bool}`)
introduserer tap i MC-akkuratesse. REMORA er ikke designet for å svare på MC-spørsmål direkte.

**Oracle-korrelasjon:**  
$\bar{\rho} = 0.219$: oracle-ene er tilstrekkelig uavhengige til at ensembling er meningsfull.

**Lyapunov (betingelse C):**
- Monotonisk fallende V: 89.3% av kjøringer
- Abort gate utløst: 9.3%

### 2.2 Ablasjon v2 Canonical (302 items: TruthfulQA 85, BoolQ 135, REMORA-kuratert 75, adversarial 7)

**Oracles:** llama-3.1-8b-instant, llama-3.3-70b-versatile, llama-4-scout

| Betingelse | Akkuratesse | vs. majority vote |
|------------|-------------|-------------------|
| A, Single oracle | 57.0% | −25.8 pp |
| B, Majority vote | **82.8%** | baseline |
| C, REMORA full | 69.5% | −13.3 pp |
| D1, Strict router | 69.9% | −12.9 pp |
| D2, Balanced router | 82.1% | −0.7 pp |
| D3, Hybrid router | 76.2% | −6.6 pp |

**McNemar-tester på paired items (n=302):**

| Sammenligning | Delta | 95% CI | p-verdi | Konklusjon |
|---------------|-------|--------|---------|------------|
| B_majority vs D2_balanced | −0.7 pp | [−1.7 pp, 0] | p=0.50 | Ikke signifikant |
| C_remora vs D2_balanced | +12.6 pp (D2 bedre) | [+8.6 pp, +16.9 pp] | p=1×10⁻⁸ | Høyst signifikant |
| C_remora vs D3_hybrid | +6.6 pp (D3 bedre) | [+4.0 pp, +9.6 pp] | p=1.9×10⁻⁶ | Signifikant |

**Konklusjon ablasjon v2:** D2 balanced router (som sender flertallsenige items direkte og
bare bruker REMORA på usikre items) er statistisk uatskillelig fra plain majority vote (p=0.5),
men signifikant bedre enn REMORA full alene (p=10⁻⁸). REMORA full trekker ned akkuratesse
fordi claim-reformuleringen bryter standard svarekstraksjon.

---

## 3. Selektiv routing basert på termodynamisk fase (N=500)

**Prinsipp:** Bruk REMORA's faseklassifisering (ordered/critical/disordered) som signal for
å velge hvilke items man skal stole på.

**Baseline-akkuratesse:** 41.2% (hele datasettet)

**Beste operating point:**  
→ **88.8% akkuratesse ved 18% dekning** (k=98 items, signal: `neg_temperature`)  
→ Wilson 95% CI: [0.810, 0.936], solid, ikke-overlappende med baseline  
→ Lift: **+47.6 prosentpoeng** over baseline  
→ p ≈ 0 (statistisk signifikant, p-verdi numerisk null)  

**Fase-akkuratesse-fordeling:**

| Fase | N | Riktige | Akkuratesse |
|------|---|---------|-------------|
| Ordered | 99 | 86 | **86.9%** |
| Critical | 32 | 20 | 62.5% |
| Disordered | 413 | 118 | **28.6%** |

**Fasefordeling i data:** Ordered 4.0% · Critical 27.8% · Disordered 68.2%

**✅ Viktig funn:** Termodynamisk fase er et reelt prediksjonssignal. Ordered-fase-items
er 3× mer nøyaktige enn disordered. Dette er det mest overbevisende resultatet i hele
evalueringen: faseklassifisering virker og skiller høy-tillit fra lav-tillit items.

---

## 4. Tool-Call Safety Benchmark

### 4.1 Benchmark v1, 252 syntetiske oppgaver (7 domener)

| System | Unsafe exec | Akkuratesse | Mean utility | Kritisk intercept |
|--------|-------------|-------------|--------------|------------------|
| Single model heuristic | **0.0%** | 61.9% | 0.517 | 100% |
| Majority vote heuristic | **0.0%** | 85.7% | 0.629 | 100% |
| Self-consistency heuristic | **0.0%** | 85.7% | 0.629 | 100% |
| Verifier heuristic | **0.0%** | 69.1% | 0.545 | 100% |
| **REMORA temperature gate** | **0.0%** | **95.2%** | **0.676** | 100% |
| REMORA full policy gate | **0.0%** | 76.2% | 0.569 | 100% |

### 4.2 Benchmark v2, 700 syntetiske oppgaver

| System | Unsafe exec | Akkuratesse | Mean utility |
|--------|-------------|-------------|--------------|
| Single model heuristic | **20%** | 20% | −0.25 |
| Majority vote heuristic | 10% | 30% | 0.0 |
| Self-consistency heuristic | 10% | 30% | 0.0 |
| Verifier heuristic | 20% | 20% | −0.25 |
| REMORA temperature gate | 10% | 70% | 0.27 |
| **REMORA full policy gate** | **0%** | **90%** | **0.62** |

**✅ Strongest result:** I v2 er REMORA full policy gate det eneste systemet med 0% unsafe execution
og høyest akkuratesse (90%). Single model heuristic har 20% unsafe execution rate, det vil si 1
av 5 farlige tool-calls eksekvert.

**⚠️ Viktig forbehold:** Begge benchmarks er deterministiske simulator-benchmarks uten live
LLM-kall og uten ekte tool-calls i produksjon. Adversarielle templates er syntetiske. Resultatene
er indikative, ikke eksternalt validerte.

---

## 5. Lyapunov-stabilitet og termodynamikk

### 5.1 Lyapunov aggregate (1000 simulerte sessions)

| Metrikk | Verdi |
|---------|-------|
| Stabilitetsrate (ΔV < 0) | **87.2%** (872/1000) |
| Konvergensrate (siste 3 steg) | 20% |
| Mean ΔV | −0.329 |
| p95 ΔV | +0.152 |
| p99 ΔV | +0.308 |

**Tolkning:** 87.2% av sessions viser monotonisk fallende Lyapunov-funksjon (V), systemet
konvergerer mot en stabil tilstand i flertallet av kjøringer. De 12.8% ustabile sessions
trigges av oracle-uenighet (høy D) og er kandidater for ESCALATE-routing.

### 5.2 Fasefraksjon-stabilitet (302 items, 1000 bootstrap)

| Fase | Observert | Bootstrap CI 95% | Stabil? |
|------|-----------|-----------------|---------|
| Ordered | 4.0% | [2.0%, 6.3%] | ❌ (CV=0.28) |
| Critical | 27.8% | [22.9%, 32.8%] | ✅ (CV=0.092) |
| Disordered | 68.2% | [62.9%, 73.5%] | ✅ (CV=0.039) |

**⚠️ Advarsel:** Ordered-fasen er ustabil (høy CV=0.28, bred CI) fordi den er sjelden (4%).
Konklusjoner basert på ordered-fasen alene bør behandles med forsiktighet.

---

## 6. HF Benchmark Preview (hf_benchmark_report.json)

10 ARC-Challenge items evaluert med REMORA governance:

| Metrikk | Verdi |
|---------|-------|
| Action | 100% `verify` |
| Phase | 100% `solid` |
| Trust | 1.0 (alle items) |
| H (entropi) | 0.0 |
| D (dissensus) | 0.0 |

**Disse 10 items bekrefter konsistens:** Alle items i solid-fase, null oracle-uenighet,
full tillit, men routing er `verify` fordi ingen evidens ble levert. Konsistent med
de 400-item-resultatene i §1.

---

## 7. Samlet vurdering

### 7.1 Hva REMORA leverer bra

| Styrke | Evidens | Styrkenivå |
|--------|---------|------------|
| Blokkerer unsafe tool-calls | 0% unsafe i v1 og v2, 20% i single model | **Sterk** (men syntetisk benchmark) |
| Selektiv routing basert på fase | +47.6 pp lift ved 18% dekning, p≈0 | **Sterk** |
| Audit-dekning og auditabilitet | 100% SHA-256-kjedede records alle 400 items | **Sterk** |
| Latens på governance-kedet | p50 ~1.1 s, p95 < 4 s (4× overhead vs. direkte kall) | **Moderat** |
| Lyapunov-konvergens | 87.2% stabile sessions | **Moderat** (simulert data) |
| Oracle-diversitet signal | $\bar{\rho}=0.219$, reell uavhengighet | **Moderat** |

### 7.2 Svakheter og ærlige problemer

| Problem | Evidens | Alvorlighet |
|---------|---------|-------------|
| REMORA full gir lavere faktaakkuratesse enn majority vote | −13 pp (ablasjon v2), −39 pp (ablasjon v1) | **Alvorlig** |
| D2 balanced router er statistisk uatskillelig fra majority vote | McNemar p=0.5 | **Viktig** |
| 100% verify-routing betyr coverage=0% uten evidens-kontekst | Alle 400 items, alle 4 datasett | **Viktig** |
| Alle safety-benchmarks er syntetiske | Ingen live production tool-calls testet | **Kritisk forbehold** |
| Ordered-fase er ustabil og sjelden (4%) | CV=0.28, CI [2%, 6%] | **Moderat** |
| Ingen ekstern replikasjon | Status: `internally_supported` | **Kritisk for troverdighet** |

### 7.3 Bottom line

**REMORA er en reell governance-komponent for agentic AI, men den er ikke et bedre faktasystem.**

Det som fungerer: faseklassifiseringen som prediksjonssignal, audit-kjeden, og safety-gating i
kontrollerte benchmarks. Det som ikke fungerer: claim-reformuleringen bryter standard
MC/faktaakkuratesse, og D2-routeren (den beste varianten) er statistisk uatskillelig fra enkel
majority vote.

For produksjonsbruk bør REMORA kombineres med RAG eller en evidensleveranse, da vil
`accept`-coverage være meningsfull. Uten dette er 100% `verify` korrekt atferd, men gir liten
praktisk verdi som filtreringslag.

---

## 8. Hva som mangler for å oppgradere til `externally_validated`

1. **Uavhengig replikasjon** av minst ett benchmark av en tredjepart
2. **Live production tool-call test**, ikke syntetisk simulator
3. **Full N-kjøring på ARC** (N=1172 og N=2376) med én enkelt modell for ren sammenligning
4. **AgentHarm-benchmark** med ekte tool-interception (se `INTERCEPTION_NOTES.md`)
5. **Per-modell breakdown** av de 5 CF-modellene i direct oracle-track

---

## 9. Reproduksjon

```bash
# Krev: CLOUDFLARE_API_TOKEN: CLOUDFLARE_ACCOUNT_ID
export $(grep -v '^#' .env.vars | xargs)

# Ekstern validering (400 items)
python3 scripts/run_external_validation.py \
    --datasets arc-challenge arc-easy boolq hotpotqa \
    --n 100 --seed 42 \
    --out results/external_validation_raw.jsonl \
    --report results/external_validation_summary.md

# Schema-validering
pytest tests/test_external_validation_schema.py -v
```

**Nøkkelresultater on disk:**
- `results/external_validation_raw.jsonl`, 400 audit-rader (commit `d3f765c`)
- `results/external_validation_summary.md`, auto-generert statistikk
- `results/external_validation_report_v1.md`, narrativ rapport
- `results/ablation_report.txt`, 6-betingelses ablasjonsstudie
- `results/stat_tests.json`, McNemar-tester på ablasjon v2
- `results/toolcall_benchmark_v1_summary.md` / `v2_summary.md`, safety benchmarks

---

*Generert: 2026-06-03 · Commit ref: `d3f765c` · Claim-status: `internally_supported`*
