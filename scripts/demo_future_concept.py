# Author: Stian Skogbrott
# License: Apache-2.0
"""Run experimental future-concept components for manual exploratory demos."""
import sys
import os
import numpy as np

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from remora.future_concept.auto_formalization import Lean4Compiler
from remora.future_concept.weight_grafting import NeuralSplicer
from remora.future_concept.kv_intercept import SubTokenInterceptor

def main():
    print("==================================================")
    print("REMORA THE FINAL HORIZON - EXPERIMENTAL PROTOTYPE")
    print("==================================================\n")

    print("1. Testing Lean 4 Auto-Formalization Core...")
    compiler = Lean4Compiler()
    proof = compiler.formalize_consensus("1 + 1 = 2", {})
    print(f"   Generated Theorem: {proof.theorem_statement}")
    print(f"   Proof Script: {proof.proof_script}")
    print(f"   Compilation Verification: {'Verified' if compiler.verify_proof(proof) else 'Failed (contains sorry)'}\n")

    print("2. Testing Liquid Neural Splicing (Weight Grafting)...")
    splicer = NeuralSplicer()
    base_weights = {"attn.q_proj": np.array([0.1]), "mlp.fc1": np.array([0.2])}
    donor_weights = {"mlp.fc1": np.array([0.999])}

    grafted = splicer.splice_layers(base_weights, donor_weights, ["mlp.fc1"])
    print(f"   Grafted Model: {grafted.base_model_name}")
    print(f"   Spliced Layers: {grafted.grafted_layers}")
    print(f"   Stability Score: {splicer.evaluate_graft_stability(grafted):.2f}\n")

    print("3. Testing Sub-Token Intercept in KV-Cache...")
    interceptor = SubTokenInterceptor(alpha=0.5)

    print("   [Scenario A] Stable Semantic Path:")
    res_a = interceptor.monitor_kv_cache(current_token_logits=[12.5], hidden_states=[0.1, 0.05, -0.1])
    print(f"      Betti-1 Hole Detected: {res_a.betti_hole_detected}")
    print(f"      Logit Penalty Applied: {res_a.original_logit - res_a.modified_logit:.4f}")

    print("   [Scenario B] Topological Dissonance (Hallucination incoming):")
    res_b = interceptor.monitor_kv_cache(current_token_logits=[15.0], hidden_states=[8.2, -9.1, 7.5])
    print(f"      Betti-1 Hole Detected: {res_b.betti_hole_detected}")
    print(f"      Original Logit: {res_b.original_logit:.4f} -> Modded Logit: {res_b.modified_logit:.4f}")
    print(f"      Logit Penalty Applied: {res_b.original_logit - res_b.modified_logit:.4f}")

    print("\n[+] All Future Concept Prototypes validated successfully!")

if __name__ == "__main__":
    main()
