# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for future_concept/ module guard rails.

Verifies:
1. Module is clearly marked EXPERIMENTAL in its docstring.
2. weight_grafting.py does not fail on import when numpy is absent
   (numpy is optional; the module must use try/except guard).
3. The EXPERIMENTAL module does not re-export anything into remora's
   top-level namespace.
"""
from __future__ import annotations

import sys


class TestFutureConceptExperimentalMarking:

    def test_init_docstring_contains_experimental(self):
        import remora.future_concept as fc
        doc = fc.__doc__ or ""
        assert "EXPERIMENTAL" in doc.upper(), (
            "remora/future_concept/__init__.py docstring must contain EXPERIMENTAL"
        )

    def test_init_docstring_contains_not_functional(self):
        import remora.future_concept as fc
        doc = fc.__doc__ or ""
        keywords = ("not functional", "not production", "conceptual sketch",
                    "stub", "placeholder")
        assert any(kw in doc.lower() for kw in keywords), (
            f"future_concept docstring must warn that implementations are stubs. Got: {doc!r}"
        )

    def test_future_concept_not_in_remora_top_level(self):
        """future_concept symbols must not pollute remora's top-level namespace."""
        import remora
        public = [name for name in dir(remora) if not name.startswith("_")]
        fc_symbols = {"NeuralSplicer", "GraftedModel", "Lean4Compiler",
                      "FormalProof", "SubTokenInterceptor", "InterceptResult"}
        leaked = fc_symbols & set(public)
        assert not leaked, (
            f"future_concept symbols leaked into remora namespace: {leaked}"
        )


class TestNumpyGuardInWeightGrafting:

    def test_weight_grafting_importable_without_numpy(self):
        """weight_grafting must import cleanly even if numpy is not installed.

        Strategy: temporarily shadow numpy in sys.modules so the import
        behaves as if numpy is absent, then verify the module loads without
        ImportError.
        """
        # Save original numpy if present
        original_numpy = sys.modules.get("numpy")
        original_module = sys.modules.pop("remora.future_concept.weight_grafting", None)
        try:
            # Remove numpy from sys.modules to simulate absent package
            sys.modules["numpy"] = None  # type: ignore[assignment]
            # Force fresh import
            if "remora.future_concept.weight_grafting" in sys.modules:
                del sys.modules["remora.future_concept.weight_grafting"]
            # Should not raise ImportError
            import remora.future_concept.weight_grafting  # noqa: F401
        except ImportError as exc:
            raise AssertionError(
                f"weight_grafting must not raise ImportError when numpy is absent: {exc}"
            ) from exc
        finally:
            # Restore original state
            if original_numpy is not None:
                sys.modules["numpy"] = original_numpy
            elif "numpy" in sys.modules:
                del sys.modules["numpy"]
            # Restore original module state
            if original_module is not None:
                sys.modules["remora.future_concept.weight_grafting"] = original_module
            elif "remora.future_concept.weight_grafting" in sys.modules:
                del sys.modules["remora.future_concept.weight_grafting"]

    def test_weight_grafting_gracefully_degrades_without_numpy(self):
        """NeuralSplicer must still be importable; methods may raise ImportError."""
        # This test verifies the class is accessible even without numpy
        original_numpy = sys.modules.get("numpy")
        original_module = sys.modules.pop("remora.future_concept.weight_grafting", None)
        try:
            sys.modules["numpy"] = None  # type: ignore[assignment]
            if "remora.future_concept.weight_grafting" in sys.modules:
                del sys.modules["remora.future_concept.weight_grafting"]
            import remora.future_concept.weight_grafting as wg
            # Class must be accessible
            assert hasattr(wg, "NeuralSplicer"), "NeuralSplicer must exist after no-numpy import"
        finally:
            if original_numpy is not None:
                sys.modules["numpy"] = original_numpy
            elif "numpy" in sys.modules:
                del sys.modules["numpy"]
            if original_module is not None:
                sys.modules["remora.future_concept.weight_grafting"] = original_module
            elif "remora.future_concept.weight_grafting" in sys.modules:
                del sys.modules["remora.future_concept.weight_grafting"]
