# Status

Updated: 2026-10-05. Each backlog item is independent and sized for one thread / one PR. When you take one, move it to "In progress" with your branch name; when merged, move it to "Done".

## Done

- Step 1: deterministic engine, 25 actions, god mode (fire, treasure, rumor, drought, sickness, gift), scripted bots, invariants, replay, 46 tests.
- Step 2 (PR #1): LLM agents via OpenRouter + stub, parallel turns, per-agent token/cost accounting, 2D log viewer, `build_demo.py`.
- Seasons (#10): `aivillage/seasons.py`, config block `seasons` (7-day spring/summer/autumn/winter, regrowth multipliers; winter: field grain withers and does not regrow, berries 0, fish x0.5). Agents see `season`, `season_days_left`, `next_season` in `observe()["time"]`; public `season` event at each change. `seasons.enabled: false` turns it off.
- Backlog 2 (branch `claude/project-thread-iswb8u`): night diary + memory about people. Each LLM agent keeps a day log of its turns; after night `reflect()` writes a ≤150-word diary and updates `people` notes (fed into every next prompt). `run(on_night=...)` logs `{"type": "diary"}` records; replay skips them. Agents with no turns that day make no call.
- Run config in YAML (#9, branch `claude/project-thread-o3gt1m`): `--config configs/example.yaml` (`aivillage/runconfig.py`). Agents with a per-agent `model` or `bot` (mixed runs work), `mechanics.disabled` (actions hidden from prompt/observation and rejected by the engine via world `disabled_actions`), `world` overrides of `config.py`, god script by day+hour. Validated before any model call; CLI flags override the file; resolved world config is in the log header.
- Demo replay published: https://claude.ai/artifact/Ftf7M9UrQnRYXxohReXqYy

## Blocked

- First real-model run: needs `OPENROUTER_API_KEY` in the project's cloud environment and network access to `openrouter.ai`.

## Backlog (independent)

1. **First LLM run + report.** 3–5 agents on one cheap model, 5 days; record cost per agent-day, invalid-action rate, interesting episodes; tune the prompt. (Needs the key.)
2. ~~Night reflection / diary~~ — done (see above). Viewer does not show diaries yet (log has them).
3. **Wake-on-event tuning.** Decide which events interrupt a busy agent (`engine.end_of_hour`), measure calls saved.
4. **Balance pass with bots.** Non-food professions barely survive solo; tune `config.py` so trade is clearly better than solo but solo is possible. Add a balance test.
5. **Metrics script.** From a log: interaction graph, trades, debts repaid/defaulted, thefts seen/unseen, Gini by day, fire responders. Output JSON + markdown.
6. **Live viewer.** FastAPI + WebSocket server streaming ticks while the sim runs; god buttons in the viewer.
7. **Pixel-art viewer.** Replace canvas shapes with a free top-down tileset and character sprites (same log format).
8. **Translation layer for viewers.** Agents speak English; viewer shows Russian translations of thoughts/says (batched, cached).
9. ~~**Run config in YAML.**~~ Done, see above.
10. ~~**Seasons.**~~ Done, see above.
11. **CI.** GitHub Actions running pytest on PRs.
