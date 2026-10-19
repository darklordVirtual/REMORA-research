# SPDX-License-Identifier: BUSL-1.1
"""Shared harness parts for the SAP v7 addenda Q6 and Q7 (§12 and §15).

``seal`` refuses a run unless its locked manifest matches every file,
``budget`` counts tokens from API usage fields and stops before the cap, and
``registry`` holds the two tool labellers of §12.2. Nothing here calls a
model by itself: every model client is injected, so the tests use fakes.

Status: harness code only. No registry, manifest, pilot or test-split run
exists for either study (SAP v7 §15.5).
"""
