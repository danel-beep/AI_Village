# Status

Updated: 2026-10-05. Each backlog item is independent and sized for one thread / one PR. When you take one, move it to "In progress" with your branch name; when merged, move it to "Done".

## Done

- Step 1: deterministic engine, 25 actions, god mode (fire, treasure, rumor, drought, sickness, gift), scripted bots, invariants, replay, 46 tests.
- Step 2 (PR #1): LLM agents via OpenRouter + stub, parallel turns, per-agent token/cost accounting, 2D log viewer, `build_demo.py`.
- Seasons (#10): `aivillage/seasons.py`, config block `seasons` (7-day spring/summer/autumn/winter, regrowth multipliers; winter: field grain withers and does not regrow, berries 0, fish x0.5). Agents see `season`, `season_days_left`, `next_season` in `observe()["time"]`; public `season` event at each change. `seasons.enabled: false` turns it off.
- Backlog 2 (branch `claude/project-thread-iswb8u`): night diary + memory about people. Each LLM agent keeps a day log of its turns; after night `reflect()` writes a ≤150-word diary and updates `people` notes (fed into every next prompt). `run(on_night=...)` logs `{"type": "diary"}` records; replay skips them. Agents with no turns that day make no call.
- Backlog 3 (branch `claude/project-thread-0orll2`): wake-on-event rules. `engine.WAKE_RULES` decides which events stop a busy agent: only events addressed to it (whisper, letter, offer, trade/decline, give, lend, theft, chest taken), `say` only when it names the agent, fire wakes everyone, hunger wakes once when satiety hits 0. Bystanders seeing a give/lend/say are no longer woken. `scripts/wake_stats.py` measures calls: tasks save ~35% vs asking every hour; new rules save 2–4% more than the old ones with chatty bots (more with real chatty LLMs in one place).
- Backlog 7 (branch `claude/project-thread-qzs03i`): pixel-art viewer. Free tilesets were unreachable from the sandbox, so all art is drawn in code in `viewer/pixelmap.js` (no third-party license): tiled map (river+dock, fenced field, market stalls, cobbled square with well, forest, mine, smithy, one coloured house per villager, up to 6 per street row), 12x16 villagers with walk cycles walking along paths, chimney smoke, fire, evening lighting. Click a villager (map or card) to follow them and read their night diaries. Data-source entry point for a live server: `Viewer.start(header)` + `Viewer.push(row)`. `build_demo.py` inlines local scripts.
- Demo replay published: https://claude.ai/artifact/Ftf7M9UrQnRYXxohReXqYy

## Blocked

- First real-model run: needs `OPENROUTER_API_KEY` in the project's cloud environment and network access to `openrouter.ai`.

## Backlog (independent)

1. **First LLM run + report.** 3–5 agents on one cheap model, 5 days; record cost per agent-day, invalid-action rate, interesting episodes; tune the prompt. (Needs the key.)
2. ~~Night reflection / diary~~ — done (see above). Viewer shows diaries on villager click.
4. **Balance pass with bots.** Non-food professions barely survive solo; tune `config.py` so trade is clearly better than solo but solo is possible. Add a balance test.
5. **Metrics script.** From a log: interaction graph, trades, debts repaid/defaulted, thefts seen/unseen, Gini by day, fire responders. Output JSON + markdown.
6. **Live viewer.** FastAPI + WebSocket server streaming ticks while the sim runs; god buttons in the viewer.
7. ~~Pixel-art viewer~~ — done, see above.
8. **Translation layer for viewers.** Agents speak English; viewer shows Russian translations of thoughts/says (batched, cached).
9. **Run config in YAML.** `--config runs/x.yaml`: agents, models, mechanics on/off, god script.
10. ~~**Seasons.**~~ Done, see above.
11. **CI.** GitHub Actions running pytest on PRs.
