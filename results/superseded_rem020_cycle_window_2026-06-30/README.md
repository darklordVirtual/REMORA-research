# Superseded: the REM-020 cycle-level monitoring window

**Status: superseded as the live REM-020 record; still the input of CLAIM-011.**
`longitudinal_stability_v1.json` as committed on 2026-06-30 (`c10a8ea`). It
counts 168 analysed adapt cycles with no false accept. On 2026-07-17 the live
record at `results/longitudinal_stability_v1.json` was rewritten to the 7-day
closure criterion under which REM-020 was closed, and that version no longer
carries cycle counts.

CLAIM-011's anytime-valid bound (`results/far_confidence_sequence_v1.json`,
4.72 %) was computed from this window, and
`scripts/compute_far_confidence_sequence.py` reads it from here. The bound
reproduces from this file unchanged.

Kept so the bound stays reproducible and its input auditable. Do not cite this
as the current REM-020 status; that is the live record.
