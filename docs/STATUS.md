# Status

Updated: 2026-10-05. Each backlog item is independent and sized for one thread / one PR. When you take one, move it to "In progress" with your branch name; when merged, move it to "Done".

## Done

- Step 1: deterministic engine, 25 actions, god mode (fire, treasure, rumor, drought, sickness, gift), scripted bots, invariants, replay, 46 tests.
- Step 2 (PR #1): LLM agents via OpenRouter + stub, parallel turns, per-agent token/cost accounting, 2D log viewer, `build_demo.py`.
- Translation for viewers (backlog 8): `python -m aivillage.translate runs/x.jsonl` writes sidecar `runs/x.ru.json` (thoughts, says, event texts, diaries; batched, cached in `runs/.cache/`, model `google/gemini-2.5-flash-lite`, ~$0.0002 per 3-agent day). Viewer has an RU/EN button; `build_demo.py` embeds the sidecar. The model transliterates names (Boris → Борис) despite the prompt.
- Backlog 5: metrics script `python -m aivillage.metrics run.jsonl --json m.json --md m.md` (interaction graph, trades, debts repaid/late/defaulted/open, thefts seen/unseen, coin Gini by day, fire responders).
- Seasons (#10): `aivillage/seasons.py`, config block `seasons` (7-day spring/summer/autumn/winter, regrowth multipliers; winter: field grain withers and does not regrow, berries 0, fish x0.5). Agents see `season`, `season_days_left`, `next_season` in `observe()["time"]`; public `season` event at each change. `seasons.enabled: false` turns it off.
- Backlog 2 (branch `claude/project-thread-iswb8u`): night diary + memory about people. Each LLM agent keeps a day log of its turns; after night `reflect()` writes a ≤150-word diary and updates `people` notes (fed into every next prompt). `run(on_night=...)` logs `{"type": "diary"}` records; replay skips them. Agents with no turns that day make no call.
- Run config in YAML (#9, branch `claude/project-thread-o3gt1m`): `--config configs/example.yaml` (`aivillage/runconfig.py`). Agents with a per-agent `model` or `bot` (mixed runs work), `mechanics.disabled` (actions hidden from prompt/observation and rejected by the engine via world `disabled_actions`), `world` overrides of `config.py`, god script by day+hour. Validated before any model call; CLI flags override the file; resolved world config is in the log header.
- Backlog 3 (branch `claude/project-thread-0orll2`): wake-on-event rules. `engine.WAKE_RULES` decides which events stop a busy agent: only events addressed to it (whisper, letter, offer, trade/decline, give, lend, theft, chest taken), `say` only when it names the agent, fire wakes everyone, hunger wakes once when satiety hits 0. Bystanders seeing a give/lend/say are no longer woken. `scripts/wake_stats.py` measures calls: tasks save ~35% vs asking every hour; new rules save 2–4% more than the old ones with chatty bots (more with real chatty LLMs in one place).
- Live viewer (#6): `pip install -e .[live]`, `python -m aivillage.server`, open http://localhost:8000. Ticks stream over WebSocket; god panel (fire, treasure, rumor, drought, sickness, gift) + pause/speed; god events are logged, replay stays exact. `viewer/live.js` + `viewer/god.js` are injected by the server.
- Backlog 7 (branch `claude/project-thread-qzs03i`): pixel-art viewer. Free tilesets were unreachable from the sandbox, so all art is drawn in code in `viewer/pixelmap.js` (no third-party license): tiled map (river+dock, fenced field, market stalls, cobbled square with well, forest, mine, smithy, one coloured house per villager, up to 6 per street row), 12x16 villagers with walk cycles walking along paths, chimney smoke, fire, evening lighting. Click a villager (map or card) to follow them and read their night diaries. Data-source entry point for a live server: `Viewer.start(header)` + `Viewer.push(row)`. `build_demo.py` inlines local scripts.
- Demo replay published: https://claude.ai/artifact/Ftf7M9UrQnRYXxohReXqYy

## Blocked

- First real-model run: needs `OPENROUTER_API_KEY` in the project's cloud environment and network access to `openrouter.ai`.

## Backlog (independent)

1. **First LLM run + report.** 3–5 agents on one cheap model, 5 days; record cost per agent-day, invalid-action rate, interesting episodes; tune the prompt. (Needs the key.)
2. ~~Night reflection / diary~~ — done (see above). Viewer shows diaries on villager click.
4. **Balance pass with bots.** Non-food professions barely survive solo; tune `config.py` so trade is clearly better than solo but solo is possible. Add a balance test.
5. ~~Metrics script~~ — done (`aivillage/metrics.py`).
6. ~~Live viewer~~ — done (see above).
9. ~~**Run config in YAML.**~~ Done, see above.
7. ~~Pixel-art viewer~~ — done, see above.
8. ~~Translation layer for viewers~~ — done (see above).
10. ~~**Seasons.**~~ Done, see above.
11. **CI.** GitHub Actions running pytest on PRs.
