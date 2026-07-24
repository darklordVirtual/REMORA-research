# Test attestation for this pack

The authoritative, commit-bound test attestation (`test-attestation.json` +
`test-report.txt`) is NOT committed to the repository: a committed copy is
stale by construction and previously carried a `git_dirty_worktree: true`
PASS record.

Obtain it from one of:

1. **CI (authoritative):** the `Review Attestation` workflow
   (`.github/workflows/attestation.yml`) runs on every `review-*` / `v*` tag,
   regenerates both files on a clean checkout of that exact commit, and
   uploads them in the handoff artifact. Its `gate` field is `PASS` only when
   the full deterministic suite is green on that SHA.
2. **Locally:** `python scripts/generate_test_attestation.py` (add
   `--require-clean` to refuse attesting a dirty worktree). The generated
   files land in this directory and are gitignored.
