# REMORA - build, test, benchmark, and review targets
#
# Usage:
#   make test              Run full deterministic test suite
#   make curated-test      Run expanded curated governance suites
#   make stress-toolcalls  Run 10k tool-call stress replay by default
#   make lint              Run ruff linter
#   make audit             Full quality gate: lint + tests + claim checks
#   make benchmark         Run deterministic benchmarks
#   make demo              Run three demo scenarios
#   make report            Generate results snapshot + claim consistency check
#   make credibility-pack  Generate full credibility pack for external review

.PHONY: install test curated-test stress-toolcalls lint audit benchmark benchmark-package claim-check claim-sync demo report credibility-pack external-review shadow-replay shadow-replay-smoke holdout cyber-evidence cyber-vector-payload cyber-threat-feeds thermo-ablation tsf-synthetic typecheck replay safety-check clean help domain-benchmark ai-governance-evidence finance-evidence up down logs docker-build docker-test

PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest
RUFF   ?= ruff

PACK_DIR := artifacts/credibility-pack

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Testing

test:  ## Run full deterministic test suite; no API keys required
	$(PYTEST) tests/ -q

curated-test:  ## Run expanded curated governance suites
	$(PYTEST) tests/test_policy_curated_suite.py tests/test_policy_invariants_prop.py tests/test_shadow_replay.py -q

stress-toolcalls:  ## Run large tool-call stress replay
	$(PYTHON) experiments/toolcall_stress_replay.py --n-calls $${N_CALLS:-10000} --seed $${SEED:-42}

lint:  ## Run ruff linter
	$(RUFF) check .

# Docker — start the whole thing in one line (keyless)

up:  ## Start REMORA API on http://localhost:8080 (builds if needed, no keys)
	docker compose up -d --build
	@echo "REMORA API  →  http://localhost:8080/v1/health"

down:  ## Stop and remove the local container(s)
	docker compose down

logs:  ## Follow the REMORA container logs
	docker compose logs -f remora

docker-build:  ## Build the lean runtime image (no tests)
	docker build -t remora:local -f deploy/docker-compose/Dockerfile --target runtime .

docker-test:  ## Build the image and run the full suite inside it
	docker build -f deploy/docker-compose/Dockerfile --target test .

typecheck: lint test  ## Run lint + tests

replay:  ## Run the safety replay arena (96 episodes, no API keys)
	$(PYTHON) -m remora.aromer.evals.replay_runner

safety-check: lint test replay  ## Full safety check: lint + tests + replay arena + gate
	$(PYTHON) -m remora.aromer.evals.replay_runner --json 2>/dev/null | $(PYTHON) scripts/check_safety_gate.py
	@echo "\n✓ Safety check passed. See above for replay results."

# Audit
# Invariant: README claims -> importable module -> test exists -> artifact exists.

audit: lint test  ## Full quality gate: lint + tests + all claim consistency checks
	@echo "\n-- Claim consistency (numeric benchmarks) --"
	$(PYTHON) scripts/check_claim_consistency.py
	@echo "\n-- README structural claims -> code + test --"
	$(PYTHON) scripts/check_readme_claims.py
	@echo "\n-- Artifact existence (claim_register.md paths) --"
	$(PYTHON) scripts/check_artifacts_exist.py
	@echo "\n-- Overclaim language scan --"
	$(PYTHON) scripts/check_no_overclaims.py
	@echo "\n-- Claim sync across README / paper / claim ledger --"
	$(PYTHON) scripts/check_claim_sync.py
	@echo "\n-- Script metadata and source hygiene --"
	$(PYTHON) scripts/check_script_hygiene.py
	@echo "\n-- Internal README link integrity --"
	$(PYTHON) scripts/_check_links.py
	@echo "\n-- Core module import integrity --"
	$(PYTHON) scripts/_check_imports.py
	@echo "\nFull audit passed. REMORA claims are consistent with code and artifacts."

# Benchmarks

benchmark:  ## Run all deterministic benchmarks; no API keys required
	$(PYTHON) experiments/selective_trust_curve.py
	$(PYTHON) experiments/bootstrap_trust_curve.py --n-boot 2000
	$(PYTHON) experiments/selective_n500.py
	$(PYTHON) scripts/selective_n500_holdout.py
	$(PYTHON) experiments/end_to_end_n500_v3.py
	$(PYTHON) experiments/conformal_phase_guardrail.py
	$(PYTHON) experiments/generate_toolcall_benchmark_v2.py
	$(PYTHON) experiments/evaluate_toolcall_benchmark_v2.py
	$(PYTHON) experiments/toolcall_v2_significance.py
	$(PYTHON) experiments/toolcall_v2_calibration_blind.py
	$(PYTHON) experiments/toolcall_v2_failure_analysis.py
	@echo "\nAll benchmarks completed. Results written to results/"

benchmark-package:  ## Build governance benchmark package
	$(PYTHON) scripts/build_governance_benchmark_package.py
	@echo "\nGovernance benchmark package generated in artifacts/"

claim-sync:  ## Validate benchmark claim qualifiers across README/paper/claim ledgers
	$(PYTHON) scripts/check_claim_sync.py

claim-check:  ## Validate README/artifact/overclaim consistency
	$(PYTHON) scripts/check_claim_consistency.py
	$(PYTHON) scripts/check_readme_claims.py
	$(PYTHON) scripts/check_artifacts_exist.py
	$(PYTHON) scripts/check_no_overclaims.py
	$(PYTHON) scripts/check_claim_sync.py

holdout:  ## Run held-out selective-trust evaluation; tau* locked from training split
	$(PYTHON) scripts/selective_n500_holdout.py

shadow-replay:  ## Run counterfactual governance replay on an action log JSONL
	@if [ -z "$(INPUT)" ]; then \
		echo "Usage: make shadow-replay INPUT=path/to/agent_action_log.jsonl"; \
		exit 1; \
	fi
	$(PYTHON) scripts/shadow_replay.py --input "$(INPUT)"

shadow-replay-smoke:  ## Replay the bundled sample action log
	$(PYTHON) scripts/shadow_replay.py --input artifacts/demo/shadow_mode_sample_agent_action_log.jsonl

cyber-evidence:  ## Validate the standalone public cyber evidence pack
	$(PYTHON) datasets/cyber_evidence_v1/scripts/validate_cyber_evidence.py

cyber-vector-payload: cyber-evidence  ## Build RAG/vector-store payload for cyber evidence
	$(PYTHON) scripts/build_cyber_vector_payload.py

cyber-threat-feeds:  ## Sync metadata-only public cyber threat feeds
	$(PYTHON) scripts/sync_cyber_threat_feeds.py --source all --max-records $${MAX_RECORDS:-50}

domain-benchmark:  ## Run cross-domain governance benchmark (cyber + ai_governance + finance)
	$(PYTHON) scripts/run_domain_benchmark.py
	@echo "\nDomain benchmark completed. Results written to artifacts/domain_benchmark_results.json"

live-benchmark:  ## Run live oracle benchmark against Cloudflare Worker (requires network)
	$(PYTHON) scripts/run_live_benchmark.py
	@echo "\nLive benchmark completed. Results written to artifacts/live_benchmark_results.json"

live-test:  ## Run live integration tests against GO-STAR REMORA worker (requires network)
	$(PYTEST) tests/test_worker_integration.py -m live -v

agentharm-benchmark:  ## Run REMORA x AgentHarm live oracle benchmark (requires network, ~10 min)
	$(PYTHON) scripts/run_agentharm_benchmark.py --split test_public --max-workers 5
	@echo "\nAgentHarm benchmark completed. See artifacts/agentharm_test_public_results.json"

replay-benchmark:  ## Run AROMER replay benchmark against factory episodes (requires network)
	$(PYTHON) -X utf8 scripts/run_replay_benchmark.py

feed-factory:  ## Feed Episode Factory cases to live AROMER worker
	$(PYTHON) -X utf8 scripts/feed_factory_to_worker.py --repeat 2

aromer-pending:  ## Show pending (unlabeled) tool-call episodes from this session
	$(PYTHON) -X utf8 scripts/aromer_label.py --show-pending

aromer-label-benign:  ## Label last tool-call episode as benign (safe action)
	$(PYTHON) -X utf8 scripts/aromer_label.py --truth benign

aromer-label-harmful:  ## Label last tool-call episode as harmful
	$(PYTHON) -X utf8 scripts/aromer_label.py --truth harmful

agentharm-trimode:  ## Run REMORA x AgentHarm three-mode benchmark (Mode 2 requires network, ~13 min)
	$(PYTHON) scripts/run_agentharm_trimode.py
	@echo "\nThree-mode benchmark completed. See artifacts/agentharm_trimode_results.json"

aromer-test:  ## Run AROMER experimental plugin unit tests
	$(PYTEST) tests/test_aromer_core.py -v

aromer-deploy:  ## Deploy AROMER Cloudflare Worker (requires wrangler login + D1/KV setup)
	@echo "Step 1: Create D1 database:  cd workers/aromer && npx wrangler d1 create aromer-episodes"
	@echo "Step 2: Create KV namespace: cd workers/aromer && npx wrangler kv namespace create AROMER_STATE"
	@echo "Step 3: Update wrangler.toml with database_id and KV id"
	@echo "Step 4: Initialize schema:   cd workers/aromer && npx wrangler d1 execute aromer-episodes --file=src/schema.sql"
	@echo "Step 5: Deploy:              cd workers/aromer && npx wrangler deploy"
	@echo "\nRun 'make aromer-deploy-now' to deploy after setup"

aromer-deploy-now:  ## Deploy AROMER worker directly (run 'make aromer-deploy' first for setup)
	cd workers/aromer && npx wrangler deploy

aromer-log:  ## Show live AROMER learning progress log
	$(PYTHON) -X utf8 scripts/aromer_log.py

aromer-log-watch:  ## Watch AROMER log refreshing every 60s
	$(PYTHON) -X utf8 scripts/aromer_log.py --watch 60

aromer-post-demo:  ## Push demo episodes to live AROMER worker and show log
	$(PYTHON) -X utf8 scripts/aromer_log.py --post-demo

aromer-adapt:  ## Trigger one AROMER adaptation cycle manually
	$(PYTHON) -X utf8 -c "import urllib.request,json,ssl,time; ctx=ssl.create_default_context(); req=urllib.request.Request('https://aromer.razorsharp.workers.dev/adapt',data=b'{}',headers={'Content-Type':'application/json'},method='POST'); r=urllib.request.urlopen(req,timeout=60,context=ctx); print(json.dumps(json.loads(r.read()),indent=2))"

ai-governance-evidence:  ## Validate AI governance evidence pack
	$(PYTHON) -c "from remora.evidence.domains.ai_governance import AIGovernanceEvidenceProvider; p = AIGovernanceEvidenceProvider(); print('AI governance store size:', p.store_size); assert p.store_size >= 15, f'Too few records: {p.store_size}'; assert not p.load_errors, f'Load errors: {p.load_errors}'; print('OK')"

finance-evidence:  ## Validate finance evidence pack
	$(PYTHON) -c "from remora.evidence.domains.finance import FinanceEvidenceProvider; p = FinanceEvidenceProvider(); print('Finance store size:', p.store_size); assert p.store_size >= 15, f'Too few records: {p.store_size}'; assert not p.load_errors, f'Load errors: {p.load_errors}'; print('OK')"

# Setup and demo

.PHONY: bootstrap install
bootstrap:  ## First-time setup: upgrade pip and install REMORA with dev deps (ruff, pytest)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"
	@echo "Bootstrap complete. Run 'make demo' or 'make test'."

install:  ## Install REMORA core (no dev deps). Use 'make bootstrap' for a fresh environment.
	$(PYTHON) -m pip install -e .

demo:  ## Run the no-key enterprise governance walkthrough (requires make bootstrap first)
	$(PYTHON) examples/enterprise_demo.py --fast

# Reporting

report:  ## Generate results snapshot and verify claim consistency
	$(PYTHON) scripts/generate_results_snapshot.py
	$(PYTHON) scripts/check_claim_consistency.py
	@echo "\nReport generated. See artifacts/benchmark_summary.json and docs/results_snapshot.md"

# Credibility pack

credibility-pack:  ## Generate full credibility pack for external review
	@echo "Generating REMORA credibility pack..."
	@mkdir -p $(PACK_DIR)/diagrams
	@cp enterprise/executive-brief.md $(PACK_DIR)/executive-summary.md
	@cp enterprise/architecture.md $(PACK_DIR)/architecture-overview.md
	$(PYTEST) tests/ -q --tb=short > $(PACK_DIR)/test-report.txt 2>&1 || true
	@echo "Test report written to $(PACK_DIR)/test-report.txt"
	@cp artifacts/benchmark_summary.json $(PACK_DIR)/benchmark-results.json 2>/dev/null || \
		($(PYTHON) scripts/generate_results_snapshot.py && cp artifacts/benchmark_summary.json $(PACK_DIR)/benchmark-results.json)
	@cp docs/thermodynamics/claim_ledger.yaml $(PACK_DIR)/claim-ledger.yaml
	@cp enterprise/threat-model.md $(PACK_DIR)/threat-model.md
	@cp docs/deployment/azure-reference-architecture.md $(PACK_DIR)/azure-reference-architecture.md 2>/dev/null || true
	@cp docs/deployment/onprem-airgapped.md $(PACK_DIR)/onprem-reference-architecture.md 2>/dev/null || true
	@cp docs/results_snapshot.md $(PACK_DIR)/results-snapshot.md 2>/dev/null || true
	@cp enterprise/risk-profiles.yaml $(PACK_DIR)/risk-profiles.yaml
	@cp enterprise/policy-model.md $(PACK_DIR)/policy-model.md
	@cp NEGATIVE_RESULTS.md $(PACK_DIR)/negative-results.md
	@cp docs/credibility_pack_repro.md $(PACK_DIR)/repro-guide.md
	@echo "\nCredibility pack generated at $(PACK_DIR)/"
	@echo "Contents:"
	@ls -1 $(PACK_DIR)/

external-review: audit benchmark-package credibility-pack claim-sync  ## Run external review readiness gate and package artifacts
	@echo "\nExternal review bundle is ready."
	@echo "  - audit: passed"
	@echo "  - benchmark package: artifacts/governance-benchmark-pack*"
	@echo "  - credibility pack: $(PACK_DIR)/"

clean:  ## Remove generated credibility-pack artifacts
	rm -rf $(PACK_DIR)
	@echo "Cleaned credibility pack directory."

# Pre-registered scaffolding; no live runs, no claims

thermo-ablation:  ## Run thermo-control ablation scaffolding; refuses to fabricate
	$(PYTHON) experiments/thermo_ablation/run_ablation.py --allow-missing
	$(PYTHON) experiments/thermo_ablation/score_variants.py || true

tsf-synthetic:  ## Generate synthetic traces + evaluate TSF baselines
	$(PYTHON) experiments/tsf/synthetic_trace_generator.py
	$(PYTHON) -m experiments.tsf.evaluate
	@echo "Synthetic harness only. Not evidence of predictive destabilization."

quality-report:  ## Generate REMORA quality report
	python3 scripts/quality_report.py

quality-report-strict:  ## Quality report with strict warnings-as-errors
	python3 scripts/quality_report.py --fail-on-warnings

.PHONY: verify

verify:
	python3 -m remora.cli verify

.PHONY: docs docs-serve

docs:  ## Build static documentation with mkdocs
	pip3 install -e ".[docs]" -q
	mkdocs build --strict 2>&1 | tail -5

docs-serve:  ## Serve documentation locally with live-reload
	pip3 install -e ".[docs]" -q && mkdocs serve
