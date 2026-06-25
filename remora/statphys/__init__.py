# Author: Stian Skogbrott
# License: Apache-2.0
"""Statistical-physics foundations for multi-oracle consensus.

This package provides a principled mapping between multi-oracle AI
consensus states and statistical-physics concepts.  The modules here
are explicitly **research-track** — they are a modelling layer, not
proven laws.  Every function is documented with the assumptions it makes
and the gap between the model and the real system.

Modules
-------
energy      Consensus energy H(σ) for a multi-oracle state.
gibbs       Gibbs/Boltzmann distributions over consensus states.
potts       Potts-model approximation for multi-verdict systems.

Design principles
-----------------
* Stdlib-only — no numpy, scipy, or torch.
* Every public function has explicit gap documentation.
* Numerical safety: no division by zero, no silent overflow.
"""

from remora.stability import RESEARCH_ONLY
__stability__ = RESEARCH_ONLY

from remora.statphys.energy import consensus_energy, state_entropy
from remora.statphys.gibbs import gibbs_probability, partition_function_approx
from remora.statphys.potts import potts_energy, potts_order_parameter

__all__ = [
    "consensus_energy",
    "state_entropy",
    "gibbs_probability",
    "partition_function_approx",
    "potts_energy",
    "potts_order_parameter",
]
