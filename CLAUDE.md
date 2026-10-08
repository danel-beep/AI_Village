# AI Village

Before changing code read `docs/STATUS.md` (in progress, next, decisions; short) and `docs/ARCHITECTURE.md` (boundaries, task → files map, how to add a mechanic). Per-module details: `docs/modules.md`, only the part you need. Old history: `docs/changelog/` (grep, never read whole).

- Tests: `python -m pytest -q` (needs `pydantic`, `pytest`). Keep them green; never weaken invariants or replay.
- One task per branch/PR. In the same PR update `docs/STATUS.md` by its rules (one line, no long write-ups; details go in the PR description).
- The owner (Danel) writes Russian; user-facing docs in Russian, code and comments in English.
- Save tokens: don't re-read large files, pipe long output through `tail`.
