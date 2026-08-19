# Claude Code repository note

This file contains no independent project policy. Follow, in order:

1. `CONTRIBUTING.md`
2. `DEVELOPER_OVERVIEW.md`
3. `ARCHITECTURE.md`
4. `docs/10-contributing.md`
5. the machine-readable registers under `docs/assurance/`

Repository invariants:

- Claims must resolve to committed evidence; do not invent or upgrade results.
- Preserve negative results, caveats and superseded findings.
- Behavioral changes require tests.
- Do not bypass strict runtime-profile prerequisites or weaken deterministic hard guards.
- Do not commit secrets, local agent state, generated planning files or scratch output.
- Prefer editing the canonical document for a topic over creating another explanation.

AI-assisted development is disclosed in `docs/AI_USE.md`; tool-generated output is not evidence by itself.
