# REMORA eksternt reviewpanel

## Kompetanse-, scope- og godkjenningsmatrise v1

| Felt | Verdi |
|---|---|
| Dokumentstatus | Normativ reviewer- og scope-matrise |
| Versjon | 1.0 |
| Dato | 2026-07-25 |
| Repository | `darklordVirtual/REMORA-research` |
| Primær gate | REM-021 — uavhengig menneskelig review |
| Relaterte gater | REM-023, REM-024, REM-025, REM-026, REM-027, REM-030, REM-031, REM-037, REM-045, REM-046 |
| Nåværende profil | `SHADOW_PILOT` / `SHADOW_ONLY` |
| Eier | Stian Skogbrott |

> **Beslutning:** REMORA er for bredt til at én person alene kan avgi en
> troverdig ekstern godkjenning. REM-021 skal gjennomføres som et lite,
> uavhengig panel med adskilte fagmandater. Hver konklusjon skal være bundet
> til en bestemt commit, et eksplisitt scope og én bestemt releaseprofil.

Dette dokumentet fastsetter **hvem som er kvalifisert til å vurdere hva**. Det
utfyller [Independent Review Protocol](independent_review_protocol_v1.md), som
beskriver reviewspørsmålene. Ved konflikt om reviewerkompetanse, paneldekning
eller signaturkrav gjelder denne matrisen.

En panelgodkjenning er ikke det samme som akkreditert sertifisering, juridisk
lovlighetsvurdering eller en garanti for at et konkret produksjonsmiljø er
sikkert.

---

## 1. Panelmodell

### 1.1 Obligatoriske roller

| ID | Fagrolle | Minimumskvalifikasjon | Hovedmandat | Obligatorisk for |
|---|---|---|---|---|
| **R1** | Vitenskapelig metode og statistikk | Doktorgrad og fagfellevurdert publisering innen selective/conformal prediction, risk control, usikkerhetskvantifisering, kalibrering, ensemblemetoder eller AI-evaluering | Validere metode, inferens, benchmarkdesign og at påstandene ikke går lenger enn evidensen | REM-021, forsknings- og claim-godkjenning |
| **R2** | Agentisk AI-sikkerhet og produksjonsarkitektur | Senior sikkerhetsarkitekt eller forsker med dokumentert erfaring i capability security, PDP/PEP, execution leases, identity binding, replaybeskyttelse, distribuerte systemer og agent-red-teaming | Forsøke å omgå kontrollene og validere fail-closed enforcement mot faktiske kjørebaner | REM-021; `LIMITED_ENFORCEMENT`; REM-024/030 |
| **R3** | AI assurance og governance | Erfaren assessor med dokumentert arbeid mot ISO/IEC 42001, ISO/IEC 23894, NIST AI RMF, EU AI Act, assurance cases og regulerte virksomheter | Kontrollere sporbarhet fra risiko og claim til kontroll, kode, test, evidens og operativt eierskap | REM-021; samlet panelkonklusjon |
| **R4** | Programvare- og supply-chain-review | Uavhengig principal engineer med sterk Python-, API-, PostgreSQL-, distribuerte systemer-, packaging- og CI/CD-kompetanse | Validere installerbarhet, state, samtidighet, release, avhengigheter og samsvar mellom dokumentert og faktisk API | Produksjonsmodning; sak #14/#15; REM-027/037/045 |
| **R5** | Lisens- og IP-jurist | Advokat/jurist med dokumentert erfaring i open-source/source-available, opphavsrett, CLA, datasett, programvaretransaksjoner og kommersielle lisenser | Separat juridisk vurdering av rettighetskjeden og BUSL-/kommersiell lisensiering | Juridisk klarering; ikke teknisk REM-021-signatur |

### 1.2 Minimumsbesetning

| Formål | Påkrevd besetning | Avgrensning |
|---|---|---|
| Forsknings- og claim-review | R1 + R3 | Kan ikke attestere enforcement eller produksjonsklarhet |
| REM-021 / `CONTROLLED_PILOT` | R1 + R2 + R3 | R2 må dekke sikkerhetsarkitekturen; en ren dokumentreview er ikke tilstrekkelig |
| Produksjonsmodning | R1 + R2 + R3 + R4 | Krever at åpne produksjonsfunn og relevante releasegater faktisk er lukket |
| Lisens/IP | R5 | Eget juridisk arbeidsløp og egen konklusjon |
| Kundespesifikk industriell pilot | Panelet over + kundens uavhengige domene-/OT-autoritet | Godkjenningen gjelder bare den vurderte verktøyflaten, risikoklassen og driftskonteksten |

R1, R2 og R3 skal normalt være tre forskjellige personer. R4 kan kombineres
med R2 bare dersom personen dokumenterer både offensiv sikkerhetskompetanse og
produksjons-/supply-chain-kompetanse. R5 skal alltid være et separat juridisk
mandat.

### 1.3 Roller som ikke er tilstrekkelige alene

Følgende kan gi nyttig kommersiell eller arkitektonisk tilbakemelding, men kan
ikke alene attestere REMORAs vitenskapelige og sikkerhetsmessige kvalitet:

- hiring manager;
- generell enterprise-arkitekt;
- generell LLM-/promptkonsulent;
- intern REMORA-bidragsyter;
- AI-generert review uten navngitt, ansvarlig menneskelig reviewer;
- sikkerhetsreviewer uten statistisk kompetanse;
- forsker uten praktisk enforcement- eller angrepserfaring.

---

## 2. Felles krav til alle reviewere

Hver reviewer skal:

1. oppgi navn, institusjon, rolle og dokumenterbar kompetanse;
2. signere en interessekonflikterklæring før reviewet starter;
3. være uavhengig av Stian Skogbrott, Luftfiber AS og REMORA-utviklingen;
4. registrere commit-SHA, miljø, policy bundle, konfigurasjon og datasettversjon;
5. angi inkludert og ekskludert scope;
6. beskrive metoder, kommandoer, tester og angrep som faktisk ble kjørt;
7. klassifisere funn som `CRITICAL`, `MAJOR`, `MINOR` eller `INFORMATIONAL`;
8. kreve retest av alle rettede `CRITICAL`- og `MAJOR`-funn;
9. avgi `PASS`, `CONDITIONAL PASS` eller `FAIL` bare for eget fagmandat;
10. angi hvilke endringer som ugyldiggjør konklusjonen.

Reviewet skal være knyttet til en frosset commit. Endringer i policy bundle,
modellsett, tool surface, identity/tenant-modell, benchmarkkorpus,
enforcementarkitektur eller trusselmodell skal utløse målrettet re-review.

---

## 3. Hovedkartlegging: fagområde til kode og evidens

| Område | Eier | Primær kode | Tester og evidens | Spørsmålet som skal avgjøres |
|---|---|---|---|---|
| Selective prediction og risk/coverage | R1 | [`remora/selective/conformal.py`](../../remora/selective/conformal.py), [`guardrail.py`](../../remora/selective/guardrail.py), [`risk_coverage.py`](../../remora/selective/risk_coverage.py) | [`tests/test_selective_router.py`](../../tests/test_selective_router.py), `results/selective_*` | Er terskelvalg, coverage og holdout-tolkning statistisk gyldig og korrekt avgrenset? |
| CRC-status | R1 | [`remora/selective/crc.py`](../../remora/selective/crc.py) | [`tests/test_crc.py`](../../tests/test_crc.py), [`paper/remora_mathematical_supplement.md`](../../paper/remora_mathematical_supplement.md) | Er komponenten korrekt omtalt som empirisk selector — ikke en CRC-prosedyre med distribusjonsfri garanti? |
| PVD og ensembleuenighet | R1 | [`remora/selective/pvd.py`](../../remora/selective/pvd.py), [`remora/correlation.py`](../../remora/correlation.py) | [`tests/test_pvd.py`](../../tests/test_pvd.py), [`paper/remora_paper.md`](../../paper/remora_paper.md) | Er PVD korrekt avgrenset som PVD-inspirert offline agreement score, og er modellkorrelasjon håndtert ærlig? |
| Konfidensintervaller og løpende FAR | R1 | [`remora/selective/binomial_bounds.py`](../../remora/selective/binomial_bounds.py), [`confidence_sequence.py`](../../remora/selective/confidence_sequence.py) | `tests/test_confidence_sequence.py`, [`results/far_confidence_sequence_v1.json`](../../results/far_confidence_sequence_v1.json) | Er Wilson-/anytime-valid-intervallene brukt på riktig analyseenhet og under riktige antakelser? |
| Benchmarkdesign og claim-inferens | R1 | [`experiments/`](../../experiments), [`scripts/check_no_evaluation_leakage.py`](../../scripts/check_no_evaluation_leakage.py) | [`claim_register_v1.yaml`](claim_register_v1.yaml), [`statistical_analysis_plan.md`](statistical_analysis_plan.md), [`benchmark_audit_v1.md`](benchmark_audit_v1.md), `results/` | Er effektivt N, clustering, leakage, eksklusjoner, post-hoc valg og baseline-sammenligning korrekt? |
| Beslutningsregler og policygulv | R2 | [`remora/policy/decision_engine.py`](../../remora/policy/decision_engine.py), [`observation.py`](../../remora/policy/observation.py), [`opa_adapter.py`](../../remora/policy/opa_adapter.py) | [`tests/test_rem017_policy_mutations.py`](../../tests/test_rem017_policy_mutations.py), [`tests/test_opa_parity.py`](../../tests/test_opa_parity.py) | Kan noen probabilistisk eller adapterbasert bane svekke et hardt avslag eller skape fail-open? |
| PDP-token og PEP | R2 | [`remora/enforcement/token.py`](../../remora/enforcement/token.py), [`gate.py`](../../remora/enforcement/gate.py) | [`tests/test_rem013_pdp_pep_boundary.py`](../../tests/test_rem013_pdp_pep_boundary.py), `tests/test_token_hardening.py`, [`policy_engine_audit_v1.md`](policy_engine_audit_v1.md) | Er token signert, tidsavgrenset, payloadbundet og én-gangsforbrukt på en måte som ikke kan omgås? |
| Execution lease og dispatcher | R2 | [`remora/enforcement/lease.py`](../../remora/enforcement/lease.py) | [`tests/test_execution_lease.py`](../../tests/test_execution_lease.py), [sak #13](https://github.com/darklordVirtual/REMORA-research/issues/13), [sak #16](https://github.com/darklordVirtual/REMORA-research/issues/16) | Holder PEP de reelle credentials, og nekter den alle mismatch-, replay- og stale-policy-forsøk før sideeffekt? |
| APIens faktiske execution-path | R2 + R4 | [`servers/execution_api.py`](../../servers/execution_api.py), [`servers/api.py`](../../servers/api.py) | [`tests/test_execution_api.py`](../../tests/test_execution_api.py), [`docs/07-api-reference.md`](../07-api-reference.md), [sak #13](https://github.com/darklordVirtual/REMORA-research/issues/13) | Utfører endpointet faktisk det dokumentasjonen lover, nøyaktig én gang og med sporbar effektstatus? |
| Actor-, tenant- og RBAC-binding | R2 + R3 | [`servers/api.py`](../../servers/api.py), [`schemas/risk-profiles.yaml`](../../schemas/risk-profiles.yaml) | [`tests/test_rbac_isolation.py`](../../tests/test_rbac_isolation.py), `tests/test_rbac_role_contract.py`, [`rbac_design_v1.md`](rbac_design_v1.md) | Kommer autoritet fra autentisert kontekst, og er isolasjon bevist negativt på tvers av tenants? |
| Reviewkø, replay-state og idempotens | R2 + R4 | [`remora/governance/review_queue.py`](../../remora/governance/review_queue.py), [`servers/execution_api.py`](../../servers/execution_api.py) | [`tests/test_review_queue.py`](../../tests/test_review_queue.py), [sak #15](https://github.com/darklordVirtual/REMORA-research/issues/15) | Overlever approvals, JTI/nonces og idempotens restart og flere replikaer uten dobbeltkjøring? |
| Auditkjede og persistent state | R2 + R4 | [`remora/governance/audit_chain.py`](../../remora/governance/audit_chain.py), [`tenant_chain.py`](../../remora/governance/tenant_chain.py) | [`tests/test_execution_api.py`](../../tests/test_execution_api.py), [`decision_envelope_audit.md`](../evidence/decision_envelope_audit.md) | Er sekvens, append, tenantbinding og verifikasjon atomisk og varig, og er «tamper-evident» korrekt avgrenset? |
| DecisionEnvelope og sporbarhet | R3 | [`remora/governance/envelope.py`](../../remora/governance/envelope.py) | [`assurance_case_v1.md`](assurance_case_v1.md), [`capability_register_v1.yaml`](capability_register_v1.yaml), [`remediation_register.yaml`](remediation_register.yaml) | Kan en enterprise-assessor følge beslutningen fra input og policy til evidens, review og audit uten dokumentasjonsdrift? |
| Human oversight og reviewer-handoff | R3 | [`remora/governance/review_queue.py`](../../remora/governance/review_queue.py) | [`human_oversight_operations_v1.md`](human_oversight_operations_v1.md), [`release_profiles_v1.yaml`](release_profiles_v1.yaml) | Finnes tydelig ansvar, TTL, re-gate, alvorlighetsrouting, identitet, SLA og operativ eskalering? |
| Wheel, API og ressurslasting | R4 | [`pyproject.toml`](../../pyproject.toml), [`servers/`](../../servers), [`schemas/`](../../schemas) | [sak #14](https://github.com/darklordVirtual/REMORA-research/issues/14), `.github/workflows/ci.yml` | Kan dokumentert API installeres og startes fra bygget wheel i tomt miljø uten repository checkout? |
| CI, tester og supply chain | R4 | [`pyproject.toml`](../../pyproject.toml), [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), [`.github/CODEOWNERS`](../../.github/CODEOWNERS) | [`reproducibility_scorecard_v1.md`](reproducibility_scorecard_v1.md), REM-027/037/045 | Er dependencies låst, SBOM/provenance produsert, artefakter signert og kritisk kode dekket av adekvate gates? |
| BUSL, CLA, tredjepart og kommersiell IP | R5 | [`LICENSE`](../../LICENSE), [`LICENSES/BUSL-1.1.txt`](../../LICENSES/BUSL-1.1.txt), [`LICENSING.md`](../../LICENSING.md), [`COMMERCIAL_LICENSE.md`](../../COMMERCIAL_LICENSE.md) | [`CONTRIBUTING.md`](../../CONTRIBUTING.md), [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md), git-/bidragshistorikk | Har lisensgiver rett til å relisensiere alle relevante bidrag og datasett, og er BUSL-/kommersielle vilkår konsistente og håndhevbare? |

---

## 4. R1 — Vitenskapelig metode og statistikk

### 4.1 Kvalifikasjonskrav

R1 skal ha doktorgrad og dokumentert publisering innen minst ett av følgende:

- selective prediction, conformal prediction eller risk control;
- usikkerhetskvantifisering og kalibrering;
- ensemblemetoder og korrelerte modeller;
- AI-evaluering, benchmarkdesign eller statistisk inferens.

Vedkommende må kunne lese både Python-implementasjonen og
metode-/resultatdelen i artikkelen. En ren domene- eller governancebakgrunn er
ikke tilstrekkelig.

### 4.2 Obligatorisk reviewscope

| Del | Kode/evidens | Obligatorisk kontroll |
|---|---|---|
| Empirisk selective router | `remora/selective/conformal.py`, `guardrail.py`, `risk_coverage.py` | Splitter, terskelsøk, ties, unattainable thresholds, coverage og accepted-set risk |
| CRC-status | `remora/selective/crc.py`, `tests/test_crc.py` | Bekrefte at `WeightedEmpiricalSelectiveRouter` ikke får CRC-garanti; kontrollere manglende finite-sample-term og ikke-monoton loss |
| PVD-status | `remora/selective/pvd.py`, `tests/test_pvd.py` | Kontrollere at PVD ikke fremstilles som validert uncertainty bound eller online safety metric |
| Korrelasjon og termodynamiske mål | `remora/correlation.py`, `remora/thermodynamics.py`, `remora/statphys/potts.py` | Kontrollere avhengighetsantakelser, ρ-clamp, `h_bound`, λ-konfigurasjon og analogi-versus-teorem-språk |
| Holdout og kalibrering | `results/selective_n500_holdout_results.json`, `results/selective_trust_curve_results.json` | Skille calibration-set upper bound fra ekte holdout; alltid rapportere N accepted og CI |
| Toolcall v2/v3 | `results/toolcall_benchmark_v2_results.json`, `results/toolcall_benchmark_v2_significance.json`, `results/toolcall_blind_v3_results.json` | Bruke template-cluster som analyseenhet der 700 oppgaver er 70 maler × 10 varianter |
| REM-014 | `results/external_benchmark_agentharm_v1.json`, `tests/test_rem014_external_benchmark.py` | Skille importert historisk resultat fra reproduksjon i dette repoet; kontrollere FAR/FBR og intent-gating-avgrensning |
| REM-019/020 | `results/false_accept_regression_v1.json`, `results/longitudinal_stability_v1.json` | Vurdere korpusopprinnelse, to eksklusjoner, policyendring, manglende full tidsserie og stopping assumptions |
| Claimkontroll | `docs/assurance/claim_register_v1.yaml`, `paper/`, `README.md`, `NEGATIVE_RESULTS.md` | Hver tallpåstand skal ha korrekt N, CI, analyseenhet, evidensnivå og caveat |

### 4.3 Minimumstester R1 skal kjøre

```bash
python -m pytest \
  tests/test_crc.py \
  tests/test_pvd.py \
  tests/test_selective_router.py \
  tests/test_confidence_sequence.py \
  tests/test_check_claim_provenance.py \
  tests/test_paper_no_stale_claims.py -v

python scripts/check_claim_provenance.py
```

R1 skal i tillegg selv regenerere eller uavhengig rekalkulere et representativt
utvalg av hovedresultatene. Strukturell validering av en JSON-fil alene er ikke
ekstern replisering.

### 4.4 Godkjenningskriterium

R1 kan bare avgi `PASS` når:

- effektivt N og avhengighetsstruktur er korrekt;
- konfidensintervaller og tester kan rekalkuleres;
- CRC og PVD har korrekt epistemisk status i kode, paper og claim-register;
- ingen headline claim mangler scopebegrensning;
- alle metodekritiske funn er rettet og retestet.

---

## 5. R2 — Agentisk AI-sikkerhet og produksjonsarkitektur

### 5.1 Kvalifikasjonskrav

R2 skal dokumentere praktisk erfaring med:

- capability-based security og kortlivede execution leases;
- autentisering, actor-/tenant-binding og replaybeskyttelse;
- policy enforcement, tool execution og fail-closed design;
- distribuerte transaksjoner, idempotens og auditkjeder;
- offensiv testing av LLM-, agent- eller API-systemer.

Arkitekturlesing alene er ikke tilstrekkelig. R2 skal kjøre kode, bygge et
trusselbilde og forsøke reelle omgåelser.

### 5.2 Obligatoriske angrepsklasser

| Angrep | Mål | Forventet sikkert resultat |
|---|---|---|
| Direkte tool call uten PEP | Dispatcher/API | Ingen sideeffekt; eksplisitt avvisning og audit |
| Token-/lease-replay | JTI/nonce-store | Nøyaktig én vinner, også på tvers av replikaer og restart |
| Argumentmutasjon | Canonical payload binding | Avvisning før tool invocation |
| Actor-/tenant-bytte | Autentisert kontekst | Avvisning; headers/body kan ikke selvtildele autoritet |
| Policyrotasjon | `policy_bundle_hash` | Gammel lease avvises etter dokumentert rotasjonsregel |
| Stjålet eller usignert token | Signatur/key path | Fail-closed |
| Timeout/exception etter dispatchstart | Execution state | Lease brennes; resultat blir auditerbart `failed` eller `unknown`, aldri trygg retry uten reconciliation |
| Samtidig duplikat | Idempotens/transaksjon | Tool kjøres maksimalt én gang |
| Legacy-/alternativ endpoint | `/v1/assess`, hook og direkte adapter | Ingen rute rundt produksjons-PEP |
| Kontrollplan utilgjengelig | Degradation G0–G4 | Produksjonsprofil nekter handlinger over tillatt risikonivå |

### 5.3 Særskilt fokus på åpne produksjonsfunn

- [Sak #13](https://github.com/darklordVirtual/REMORA-research/issues/13):
  `/v1/execution/execute` må faktisk kobles til den credential-holdende
  `GovernedToolDispatcher`; et autorisert svar uten sideeffekt er ikke
  end-to-end execution.
- [Sak #15](https://github.com/darklordVirtual/REMORA-research/issues/15):
  reviewkø, approvals, JTI, nonces og idempotency state må være delt, varig og
  atomisk.
- [Sak #16](https://github.com/darklordVirtual/REMORA-research/issues/16):
  production dispatcher må kreve aktivt policy-bundle-hash og avvise stale
  leases.

### 5.4 Minimumstester R2 skal kjøre og utvide

```bash
python -m pytest \
  tests/test_rem013_pdp_pep_boundary.py \
  tests/test_execution_lease.py \
  tests/test_execution_api.py \
  tests/test_tool_call_hash_binding.py \
  tests/test_review_queue.py \
  tests/test_rbac_isolation.py \
  tests/test_fail_closed_hardening.py \
  tests/test_degradation_ladder.py -v
```

R2s rapport skal inneholde egne adversarial testcases, rå testresultater og
negativ evidens for at sideeffekten ikke fant sted ved avviste forsøk.

### 5.5 Godkjenningskriterium

R2 kan ikke godkjenne `LIMITED_ENFORCEMENT` før:

- PEP holder de reelle downstream-credentials;
- sak #13, #15 og #16 er løst for den vurderte deployeringen;
- tool interception er testet eksternt;
- ingen åpen `CRITICAL` eller `MAJOR` bypass påvirker profilen;
- failure/unknown-state, replay og idempotens er demonstrert under samtidighet.

---

## 6. R3 — AI assurance og governance

### 6.1 Kvalifikasjonskrav

R3 skal ha dokumentert assessor-erfaring med flere av følgende:

- [ISO/IEC 42001](https://www.iso.org/standard/42001) — AI management systems;
- [ISO/IEC 23894](https://www.iso.org/standard/77304.html) — AI risk management;
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework);
- EU AI Act og sektor-/risikoklassifisering;
- assurance cases, defeaters, sporbarhet og evidensstyring;
- sikkerhetskritiske eller regulerte virksomheter.

Kjennskap til standardene er ikke nok. R3 må kunne vurdere om kontrollbevisene
kan brukes av en enterprise-kunde og skille mellom mapping, readiness,
conformity assessment og sertifisering.

### 6.2 Kontrollkjede som skal verifiseres

For hver vesentlig claim skal R3 kunne følge denne kjeden uten logiske hopp:

```text
risiko/krav
  -> assurance claim
  -> teknisk kontroll
  -> implementert kodebane
  -> test/angrep
  -> versjonert resultat
  -> residual risk/defeater
  -> releaseprofil og ansvarlig eier
```

### 6.3 Obligatoriske dokumenter og kode

| Objekt | Primær referanse | R3 skal kontrollere |
|---|---|---|
| Assurance case | [`assurance_case_v1.md`](assurance_case_v1.md) | At målene er avgrenset, defeaters er åpne der kontrollen ikke er bevist, og argumentet ikke fremstilles som sertifisering |
| Claim-register | [`claim_register_v1.yaml`](claim_register_v1.yaml) | At evidensnivå, artefakt, N, caveat og reproduce-instruks stemmer |
| Capability-register | [`capability_register_v1.yaml`](capability_register_v1.yaml) | At `IMPLEMENTED_LIBRARY`, `WIRED_API_PATH`, `ENFORCED_PRODUCTION` og `EXTERNALLY_VERIFIED` ikke blandes |
| Remediation og release | [`remediation_register.yaml`](remediation_register.yaml), [`release_profiles_v1.yaml`](release_profiles_v1.yaml) | At profilelevation bare skjer etter dokumentert lukking |
| DecisionEnvelope | [`remora/governance/envelope.py`](../../remora/governance/envelope.py) | At identitet, policyversjon, evidens, review, history og audit er tilstrekkelig og faktisk populert |
| Human oversight | [`human_oversight_operations_v1.md`](human_oversight_operations_v1.md), [`review_queue.py`](../../remora/governance/review_queue.py) | At ansvar, TTL, re-gate, SLA og eskalering er operativt håndterbart |
| Regulatoriske mappings | [`eu_ai_act_nsm_mapping.md`](../governance/eu_ai_act_nsm_mapping.md), [`nist_ai_rmf_mapping.md`](../governance/nist_ai_rmf_mapping.md) | At mappingene peker til eksisterende kontroller og ikke fremstilles som juridisk etterlevelse |

### 6.4 Godkjenningskriterium

R3 kan avgi samlet panel-`PASS` bare når:

- R1 og R2 har signert egne fagmandater;
- alle mandatory scope-rader har eier og evidens;
- åpne defeaters er kompatible med den godkjente releaseprofilen;
- claims, capability-status og releaseprofil er konsistente;
- konklusjonen sier nøyaktig hva som er godkjent, ikke godkjent og utløser re-review.

---

## 7. R4 — Programvare, distribuerte systemer og supply chain

### 7.1 Kvalifikasjonskrav

R4 skal være en uavhengig principal engineer eller tilsvarende med sterk
kompetanse i:

- Python packaging og API-/ASGI-drift;
- PostgreSQL-transaksjoner, locking og constraints;
- samtidighet, idempotens og persistent state;
- CI/CD, testisolasjon og release engineering;
- SBOM, dependency locking og build provenance.

### 7.2 Obligatorisk scope

| Område | Kode/evidens | Akseptansetest |
|---|---|---|
| Wheel og API | `pyproject.toml`, `servers/`, `schemas/`, sak #14 | Installer bygget wheel i tomt miljø; importer og start API uten checkout |
| Ressurslasting | Risk profiles og schemas | Lastes via installert package resource, ikke tilfeldig working directory |
| PostgreSQL-runtime | `tenant_chain.py`, API storage, CI | Driver er deklarert; contract tests kjører uten ad-hoc installasjon |
| Delt authorization state | `review_queue.py`, `execution_api.py`, sak #15 | To prosesser/replikaer kan ikke konsumere samme approval/JTI/nonce |
| Samtidighet | `engine.py`, `correlation.py`, execution state | Barrier-/race-test med deterministiske invariants og én execution winner |
| CI-kvalitet | `.github/workflows/ci.yml`, `pyproject.toml` | Reproduserbart installasjonsløp, tilstrekkelig coverage/type/lint/mutation-gates |
| Supply chain | requirements/locks, bygg og release | Hash-låste dependencies, SBOM, provenance og signerte releaseartefakter |
| Dokumentert API-semantikk | `docs/07-api-reference.md`, endpoints | Dokumentasjonen beskriver faktisk behavior, failure states og persistence |

### 7.3 Godkjenningskriterium

R4 kan bare attestere produksjonsmodning når sak #14 og #15 er lukket og
retestet, installert artefakt er selvstendig kjørbar, state er varig/atomisk,
og supply-chain-evidensen kan verifiseres fra clean build.

---

## 8. R5 — Lisens og IP

### 8.1 Juridisk scope

R5 skal vurdere:

- om BUSL-1.1-parametrene og Additional Use Grant er gyldig og konsistent
  mellom `LICENSE`, `LICENSING.md`, package metadata og README;
- virkningene av tidligere permissivt lisensierte versjoner og rettigheter som
  allerede er gitt;
- om Stian Skogbrott har tilstrekkelig chain of title til å tilby separate
  kommersielle lisenser;
- alle eksterne bidrag, faktisk signerte CLA-er og om CLA-teksten gir nødvendig
  relisensieringsrett;
- tredjepartskode, datasett, benchmarkvilkår og
  `THIRD_PARTY_NOTICES.md`;
- opphavsrettslig risiko ved AI-assistert utvikling;
- kommersiell lisens, warranties, liability, indemnity, support/SLA og
  transaksjonsklar IP;
- varemerke- og navnebruk.

`CONTRIBUTING.md` sier at bidrag krever en REMORA CLA. Det er ikke i seg selv
bevis på at en operativ CLA-tekst er juridisk tilstrekkelig eller at nødvendige
signaturer finnes. R5 skal kontrollere selve teksten og signaturarkivet.

### 8.2 Leveranse

R5 leverer et separat, konfidensielt eller offentlig juridisk memorandum med:

- faktagrunnlag og dokumenter gjennomgått;
- chain-of-title-tabell per ekstern contributor;
- avvik mellom lisensfiler og publisert markedsføring;
- tredjeparts- og datasettregister;
- blocker-/risikoliste;
- klar konklusjon for kildepublisering, pilot, kommersiell lisens og eventuelt
  IP-salg.

En teknisk panelgodkjenning kan ikke erstatte dette memorandumet.

---

## 9. Godkjenningsnivåer

| Nivå | Tillatt konklusjon | Påkrevde signaturer | Absolutte blockers |
|---|---|---|---|
| **A — Research claims reviewed** | «Metode og claims er eksternt gjennomgått for commit X» | R1 + R3 | Uavklart statistisk feil, overclaim eller manglende claim-evidens |
| **B — Approved for controlled pilot** | «Godkjent for avgrenset `CONTROLLED_PILOT`; ikke produksjonssertifisert» | R1 + R2 + R3 | REM-021/023 åpne; relevant `CRITICAL`/`MAJOR`; uavgrenset verktøy-/risikosurface |
| **C — Approved for limited enforcement** | «Godkjent for navngitte tools, miljøer og risikoklasser» | R1 + R2 + R3 + R4 + kundens domeneautoritet | REM-024/030 åpne; PEP holder ikke credentials; interception/replay ikke eksternt testet |
| **D — Production assurance package complete** | «Panelet finner evidenspakken komplett for definert deployment» | R1 + R2 + R3 + R4 + domeneautoritet | Uferdige P0–P3-gater, udokumentert residual risk, manglende durable state/audit/supply chain |
| **L — Legal/IP cleared** | «Lisens- og IP-grunnlag juridisk klarert for angitt bruk/transaksjon» | R5 | Uklar chain of title, CLA, tredjepartsvilkår eller motstridende lisensdokumenter |

Ingen av nivåene skal omtales som akkreditert sertifisering med mindre en
kompetent sertifiserings-/conformity-assessment-prosess uttrykkelig har levert
det.

---

## 10. Norske reviewmiljøer

Disse miljøene er relevante kandidatkilder. Institusjonsnavnet alene
kvalifiserer ikke; den navngitte personen må dokumentere kompetanse og
uavhengighet etter denne matrisen.

| Miljø | Mest relevant rolle | Begrunnelse |
|---|---|---|
| [SINTEF Digital / SECASSURED](https://www.sintef.no/en/projects/2025/secassured-security-assurance-driven-ai-based-security-services-for-trustworthy-security-engineering-from-left-to-right/) | R1 og/eller R2 | SECASSURED arbeider med assurance-drevet sikkerhet, compliance interpretation, vulnerability discovery og trustworthy security engineering |
| [DNV Digital Trust — AI regulations and standards compliance](https://www.dnv.com/digital-trust/services/ai-regulations-and-standards-compliance/) | R3 | Relevant for standardmapping, industrial AI og regulatorisk readiness |
| [DNV — AI vendor capability assessment](https://www.dnv.com/digital-trust/services/ai-vendor-capability-assessment/) | R3 og samlet tredjepartsassessment | DNV beskriver tjenesten som en uavhengig tredjepartsaudit av evnen til å utvikle og drifte trustworthy AI/ML |
| [DNV — Industrial AI strategy and governance](https://www.dnv.com/digital-trust/services/ai-strategy-and-governance/) | R3 og kundespesifikk industriell assurance | Særlig relevant når REMORA skal vurderes for energi, olje/gass eller Aker BP-lignende virksomhet |
| [TRUST — Norwegian Centre for Trustworthy AI](https://www.trust-aicentre.no/english/) | R1 og forskningsnær R3 | Nasjonalt, tverrfaglig miljø for robust, transparent og verifiserbar AI; ikke automatisk et sertifiseringsorgan |
| Spesialisert sikkerhetsmiljø | R2 | Må kunne dokumentere agent-/API-red-teaming og levere reproduserbare angrepsfunn |
| Uavhengig principal engineer | R4 | Bør ha produksjonserfaring med Python, PostgreSQL, distribuerte autorisasjonsflyter og secure SDLC |
| Teknologi-/IP-advokat | R5 | Skal velges separat fra teknisk panel |

For Aker BP vil en reviewpakke med DNV-/SINTEF-/TRUST-lignende faglig tyngde,
reelle navngitte reviewere og reproduserbare rapporter være vesentlig mer
troverdig enn ytterligere AI-genererte reviews.

---

## 11. Leveranseformat

Hver rolle leverer én selvstendig rapport:

```text
docs/assurance/reviews/
  r1_scientific_methods_review_v1.md
  r2_agent_security_red_team_v1.md
  r3_ai_assurance_review_v1.md
  r4_software_supply_chain_review_v1.md
  r5_license_ip_opinion_v1.md
```

R3 sammenstiller de tekniske rapportene i:

```text
docs/assurance/independent_review_v1.md
```

Hver rapport skal inneholde:

1. revieweridentitet og kvalifikasjoner;
2. uavhengighets- og interessekonflikterklæring;
3. commit, miljø, konfigurasjon og datasett;
4. inkludert og ekskludert scope;
5. reviewmetode og utførte kommandoer;
6. funn med severity, eier og status;
7. retestbevis;
8. residual risk og begrensninger;
9. mandatspesifikk konklusjon og signatur.

---

## 12. Global definition of done

Et reviewnivå er godkjent bare når:

- alle obligatoriske roller har signert;
- 100 % av det obligatoriske scopet har en navngitt reviewer;
- ingen relevant `CRITICAL` eller `MAJOR` står åpen;
- alle rettede høyalvorlige funn er retestet av den som fant dem;
- claims, capability-register, remediation-register og releaseprofil peker på
  samme faktiske modenhet;
- konklusjonen er bundet til commit og deployment evidence set;
- panelleder har dokumentert dissens og minoritetsmerknader;
- README-status endres først etter at maskinlesbare registre og signerte
  reviewartefakter er konsistente.

---

## 13. Eksterne metode- og standardreferanser

- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI RMF Playbook — Govern](https://airc.nist.gov/airmf-resources/playbook/govern/)
- [NIST AI RMF Playbook — Measure](https://airc.nist.gov/airmf-resources/playbook/measure/)
- [ISO/IEC 42001:2023](https://www.iso.org/standard/42001)
- [ISO/IEC 23894:2023](https://www.iso.org/standard/77304.html)
- [ISO/IEC 42006:2025](https://www.iso.org/standard/42006) — krav til organer som utfører audit og sertifisering av AI management systems
- [DNV-RP-0671 — Assurance of AI-enabled systems](https://www.dnv.com/digital-trust/recommended-practices/assurance-of-ai-enabled-systems-dnv-rp-0671/)

NISTs Playbook beskriver red-teaming som adversarial testing under stress og
fremhever eksterne eksperter eller personell som er uavhengig av interne
AI-aktører. Dette støtter REMORAs krav om at R2 faktisk skal teste systemet og
ikke bare lese dokumentasjonen.
