# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Execution-kernel use-case modules (issue #241 extraction).

No HTTP knowledge lives here: modules receive chain/queue/config explicitly
from the API layer and raise domain errors (never HTTPException).
"""
