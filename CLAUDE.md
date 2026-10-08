# AI Village

Before changing code read `docs/STATUS.md` (next, decisions; short; work in progress = open PRs) and `docs/ARCHITECTURE.md` (boundaries, task → files map, how to add a mechanic). Per-module details: `docs/modules.md`, only the part you need. Old history: `docs/changelog/` (grep, never read whole).

- Tests: `python -m pytest -q` (install everything: `pip install -e ".[live,dev]"`; CI sets `AIV_NO_SKIPS=1`, so a skipped test fails). Keep them green; never weaken invariants or replay.
- One task per branch/PR; the PR description names its file zone and the details. Do not add "done" lines to `docs/STATUS.md` (git log and open PRs are the record); edit it only when the plan, a decision of Danel or a blocker changes.
- After opening a PR enable auto-merge (squash): it merges itself once the `tests-ok` check is green. On a conflict merge main in and push.
- The owner (Danel) writes Russian; user-facing docs in Russian, code and comments in English.
- Save tokens: don't re-read large files, pipe long output through `tail`.
