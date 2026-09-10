# Provenance record

This directory is an additive REMORA-research re-expression of the private working artifact `Decision_Evidence_Review_v0.1(1).zip` supplied by Stian Skogbrott on 2026-09-10.

## Source package

- ZIP SHA-256: `a5b422bc4b8b58e4a0e2ec3c35ef26b6591c09c7f919ffd6dec1ff258bfddec4`
- source `checker.py`: `c5b03f10b9d3634bb74d0e482084bbbbf78eb3d7fa5b560e0f3ee8c60df2d9de`
- source `cases.json`: `e44ab2a09a0b96abc53282155cf7d4ad46dd5f078bcc76fdac5d145856338010`
- source `run_review.py`: `9e0f274db97dc31704034893d8aa2adfceff4d654dd0f94047f88a37ce6f332c`
- source `run-report.json`: `39b7ba12304947946d5edc84ee7bf56228178c3838e544509130a672c81b9ab3`

The source package was verified against its own `SHA256SUMS.txt` before adaptation.

## Existing REMORA provenance preserved

The implementation is based on REMORA-research `master` at commit:

`850220687994455fae7f4d76497a3e9885c4b404`

The already-published `conformance/decision-to-effect-v1/vectors.json` blob at that base is:

`0dd98172541c7f93fbb2d2d6e0f13112209504c5`

No file under `conformance/decision-to-effect-v1/` is modified by this work. The new suite is intentionally additive so earlier author-run and external reproduction references remain resolvable to the bytes they actually tested.

## Adaptation boundary

The working review model was strengthened for repository use by:

- introducing a typed `EvidenceVerdict` with explicit `claim`, `status`, `reason`, `scope`, `missing_evidence` and `decisive_if`;
- adding an explicit synthetic-premise guard to prevent accidental production reuse;
- separating case expectation matching from property verdicts in the run record;
- adding deterministic byte-for-byte artifact reproduction;
- adding a polarity-preservation regression for evidence removal from decisive cases;
- keeping the original indistinguishable-world and wrong-shortcut witnesses.

This provenance record does not claim that the private source artifact, this adaptation, REMORA, APS or CoSAI has independently validated the other.
