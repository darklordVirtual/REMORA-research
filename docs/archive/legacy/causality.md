# Causal Stress Testing & Counterfactual Validation (Do-Calculus)

REMORA introduces a fundamentally new paradigm in LLM assurance: **Causal Stress Testing**.

Instead of purely relying on multiple models confirming each other's outputs (which remains vulnerable to shared training-data biases and massive-scale pattern matching errors), REMORA implements Pearl's Do-Calculus (causal inference) to physically attack the logical consistency of an LLM ensemble.

## The Core Problem: Pattern Matching Hallucinations

When an LLM ensemble encounters a heavily learned correlation—for instance, "Landlord notice periods are 3 months"—they will confidently answer "Yes" to almost any question related to landlord notices. This happens even if the text explicitly contains a counter-condition (e.g., "The lease explicitly states 1-month notice"). 

Standard cross-examination fails here because all LLMs share the same heavy bias toward the training data norm. They collectively hallucinate the same wrong answer.

## REMORA's Solution: The Causal Intervention Gate

When REMORA's initial `router_gate` detects overwhelming early consensus (e.g., 80%+ agreement directly out the gate), the system grows suspicious. Instead of blindly accepting the answer, it triggers a **Causal Intervention**.

### How It Works

1. **Red-Team Intervention ($P(Y|do(\neg X))$):**
   A fast, specialized Red-Team Oracle reads the original question and forcibly *inverts* a core assumption or premise.
   * *Original:* "According to the Norwegian husleieloven, is the standard notice period for landlords 3 months?"
   * *Intervention:* "If the lease explicitly states a 1-month notice period, is the standard notice period for landlords 3 months?"

2. **Counterfactual Evaluation:**
   The entire LLM ensemble is asked the exact same question, but with the inverted counterfactual premise.

3. **Validation & Escalation:**
   REMORA parses the counterfactual responses. 
   - If the ensemble changes its polarity (or explicitly denies the premise), it proves they are employing **logical deduction**. REMORA passes the gate and accepts the consensus.
   - If the ensemble answers with the **exact same truth value** despite the premise being logically inverted, they are caught in a blind pattern-matching execution. REMORA immediately fails the stress test, registers the consensus as invalid, and escalates the engine to full Deep Counter-Examination (forcing the Lyapunov state to mandate external RAG lookups and deeper iterations).

## Code Structure

- **`remora/causality.py`**: The home of the Red-Team counterfactual generator and the `evaluate_causal_response` evaluator.
- **`remora/engine.py`**: The `_router_gate` intercepts highly correlated immediate consensus and executes the causal stress test safely before permitting short-circuit acceptance.
- **`remora/genome.py`**: Controlled via `enable_causal_stress_test` and `causal_stress_threshold`.

By simulating alternative logical realities on the fly, REMORA doesn't just ensure LLMs agree; it ensures they *understand why* they agree.
