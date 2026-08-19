# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Research attic: retained research modules outside every production path.

Nothing under this package is imported by the safety core
(``remora/policy``, ``remora/enforcement``, ``remora/execution``), the
servers, or any adapter. The modules are kept for reproducibility and audit
history — several are cited from the claim register or from negative
results — but they carry no runtime behaviour and receive no maintenance
beyond keeping their tests green.

Moving a module OUT of the attic requires a production importer and a
capability-register entry; moving one IN requires proof that no production
path imports it (see tests/test_research_attic_isolation.py).
"""
