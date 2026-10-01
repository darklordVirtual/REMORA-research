# Superseded: trust calibration with a 4.0 temperature ceiling

**Status: superseded.** `trust_calibration_report.json` as committed, produced
on 2026-05-31 when the temperature search stopped at 4.0. The fitted value
sat on that ceiling. The calibrator in `remora/calibration/trust_calibrator.py`
now searches up to 8.0, so the committed generator no longer produces this
file.

The current version lives at `results/trust_calibration_report.json`,
regenerated on 2026-09-28 from the same input. Its fitted temperature is 8.0,
again at the ceiling. The claim `trust_calibration_temperature_scaling` in
`docs/thermodynamics/claim_ledger.yaml` stays `not_demonstrated`.

Kept so the first reading stays auditable. Do not cite this as a current result.
