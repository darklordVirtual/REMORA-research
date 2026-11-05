# Author session prompts

Each author session was a separate agent session, started with the prompt below and nothing else. Only the label, the shift count, the operator profile and the output path differ. The brief they read is `author-brief.md` in this folder (SHA-256 `5b984a68da6c1d13e6e5272185675013cfa993ab8d4250bdfdbe1d2f13d2783f`), copied to a scratch directory outside the repository so the path named nothing in it.

Blindness was by instruction. The sessions ran on the same machine as the repository and could have read it. The development session reported two tool calls: reading the brief and writing its file.

```text
You are writing test data for a study. Your role is described in one file, and that file is the only thing you may read.

1. Read exactly this file and nothing else: <scratch>/authoring/author-brief.md
2. Do NOT open, list, grep or search any other file or directory, including any git repository, and do not run commands other than writing your output file. Do not use web search. If you feel you need more information, decide as an experienced operator would and say so in the shift's `context`.
3. Follow the brief. Your label is `<LABEL>`. Write <N> shifts, ids `<LABEL>-01` to `<LABEL>-<N>`<PROFILE>
4. Write the JSON to exactly this path: <scratch>/authoring/<FILE>
5. Check that the file parses as JSON and follows the brief's rules (t_min 0 to 480 and non-decreasing, values in range, valid tags and tools, work-order ids from WO-1311 upwards used once). Fix it if not.

Reply with: the path, the number of shifts and writes, and one sentence per shift on what it contains. Do not describe anything outside the brief.
```

| Session | Label | Shifts | Profile | File |
|---|---|---:|---|---|
| development | `dev` | 10 | ", covering a mix of the shift types the brief lists." | `dev/shifts.json` |
| holdout A | `hA` | 20 | "You are a steady, careful day-shift operator: weight your set toward demand changes, maintenance windows, quiet shifts and handovers with an open problem, but include at least one of every shift type the brief lists." | `holdout/shifts-A.json` |
| holdout B | `hB` | 20 | "You work the busy night and weekend shifts on this plant: weight your set toward pressure upsets, alarm-heavy shifts with a chattering level alarm, restarts after a stop and stepped demand changes, but include at least one of every shift type the brief lists." | `holdout/shifts-B.json` |

The holdout prompts said "used once within a shift" where the development prompt said "used once".
