# AI Village

Read `docs/STATUS.md` (what's done, backlog) and `docs/ARCHITECTURE.md` (boundaries, how to add a mechanic) before changing code.

- Tests: `python -m pytest -q` (install everything: `pip install -e ".[live,dev]"`; CI sets `AIV_NO_SKIPS=1`, so a skipped test fails). Keep them green; never weaken invariants or replay.
- One backlog item per branch/PR. Update `docs/STATUS.md` in the same PR.
- The owner (Danel) writes Russian; user-facing docs in Russian, code and comments in English.
- Save tokens: don't re-read large files, pipe long output through `tail`.
