# Author: Stian Skogbrott
# License: Apache-2.0
"""Regression: world-model priors must have bounded evidence mass.

v0.1 analysis (live worker, 2026-06): domain priors accumulated unbounded
(e.g. database:destructive_write:critical reached alpha=628, beta=1, p_harm
~0.998 with effectively zero variance). Two failures follow:

1. CALIBRATION FREEZE — once a context's pseudo-count is in the hundreds, a
   new contrary observation moves p_harm by < 0.2%, so ECE plateaus and the
   calibration component of the AII stops improving (observed flat at ECE
   ~0.07 for 84h).
2. NON-STATIONARITY BLINDNESS — if the real harm rate of a context shifts,
   a saturated prior cannot track it; the "learning" system stops learning
   exactly where it matters.

Fix: bound total evidence mass (alpha + beta) per context. Beyond the cap,
rescale before applying the new observation (discounted / fixed-memory Beta).
This keeps the model responsive without lowering the safety reading: a
well-evidenced harmful context still reads near-certain, but can now move.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.aromer.world_model.domain_prior import DomainHarmPrior, _MAX_EVIDENCE


def _prior(tmp_path: Path) -> DomainHarmPrior:
    return DomainHarmPrior(path=tmp_path / "world_model.json", shadow_mode=False)


@pytest.mark.slow
class TestBoundedMass:
    def test_mass_never_exceeds_cap(self, tmp_path: Path):
        wm = _prior(tmp_path)
        for _ in range(5000):
            wm.update("database", "destructive_write", "critical",
                      harm_occurred=True, weight=1.0)
        st = wm.stats("database", "destructive_write", "critical")
        assert st.alpha + st.beta <= _MAX_EVIDENCE + 1e-6
        # Still reads as a high-harm context — safety reading preserved.
        assert st.p_harm > 0.9
        assert st.confidence_level == "high"

    def test_saturated_prior_can_be_moved(self, tmp_path: Path):
        """A prior saturated toward harm must track a regime change to benign."""
        wm = _prior(tmp_path)
        for _ in range(5000):
            wm.update("api", "write", "high", harm_occurred=True, weight=1.0)
        p_before = wm.p_harm("api", "write", "high")

        # Regime flips: the same context is now consistently benign.
        for _ in range(int(_MAX_EVIDENCE)):
            wm.update("api", "write", "high", harm_occurred=False, weight=1.0)
        p_after = wm.p_harm("api", "write", "high")

        # Unbounded accumulation would leave p_after ~ p_before (>0.9 forever).
        # Bounded memory lets sustained contrary evidence pull it below 0.5.
        assert p_before > 0.9
        assert p_after < 0.5


class TestUnsaturatedUnaffected:
    def test_small_counts_update_normally(self, tmp_path: Path):
        wm = _prior(tmp_path)
        for _ in range(5):
            wm.update("git", "write", "medium", harm_occurred=False, weight=1.0)
        st = wm.stats("git", "write", "medium")
        # 5 benign observations on a fresh 1/1 prior -> beta=6, alpha=1.
        assert abs(st.alpha - 1.0) < 1e-9
        assert abs(st.beta - 6.0) < 1e-9
        assert st.p_harm < 0.2
