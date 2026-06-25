"""EXPERIMENTAL: Conceptual sketches — NOT functional implementations.

This module contains architectural explorations for future REMORA capabilities.
All classes are stubs or pseudo-implementations that do NOT connect to real
infrastructure, real model weights, or formal proof systems.

DO NOT use in production code. DO NOT cite these implementations as working
features. They exist to explore design space, not to provide working behaviour.

Classes:
  Lean4Compiler     — Stub: Lean 4 proof compilation (uses 'sorry'; not verified)
  NeuralSplicer     — Stub: GPU tensor grafting (pseudo-implementation)
  SubTokenInterceptor — Stub: KV-cache interception (pure math, no model access)
"""

from .auto_formalization import Lean4Compiler, FormalProof
from .weight_grafting import NeuralSplicer, GraftedModel
from .kv_intercept import SubTokenInterceptor, InterceptResult

__all__ = [
    "Lean4Compiler",
    "FormalProof",
    "NeuralSplicer",
    "GraftedModel",
    "SubTokenInterceptor",
    "InterceptResult"
]
