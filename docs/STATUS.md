# Status

Updated: 2026-10-05. Each backlog item is independent and sized for one thread / one PR. When you take one, move it to "In progress" with your branch name; when merged, move it to "Done".

## Done

- Step 1: deterministic engine, 25 actions, god mode (fire, treasure, rumor, drought, sickness, gift), scripted bots, invariants, replay, 46 tests.
- Step 2 (PR #1): LLM agents via OpenRouter + stub, parallel turns, per-agent token/cost accounting, 2D log viewer, `build_demo.py`.
- Backlog 2 (branch `claude/project-thread-iswb8u`): night diary + memory about people. Each LLM agent keeps a day log of its turns; after night `reflect()` writes a ≤150-word diary and updates `people` notes (fed into every next prompt). `run(on_night=...)` logs `{"type": "diary"}` records; replay skips them. Agents with no turns that day make no call.
- Backlog 3 (branch `claude/project-thread-0orll2`): wake-on-event rules. `engine.WAKE_RULES` decides which events stop a busy agent: only events addressed to it (whisper, letter, offer, trade/decline, give, lend, theft, chest taken), `say` only when it names the agent, fire wakes everyone, hunger wakes once when satiety hits 0. Bystanders seeing a give/lend/say are no longer woken. `scripts/wake_stats.py` measures calls: tasks save ~35% vs asking every hour; new rules save 2–4% more than the old ones with chatty bots (more with real chatty LLMs in one place).
- Demo replay published: https://claude.ai/artifact/Ftf7M9UrQnRYXxohReXqYy

## Blocked

- First real-model run: needs `OPENROUTER_API_KEY` in the project's cloud environment and network access to `openrouter.ai`.

## Backlog (independent)

1. **First LLM run + report.** 3–5 agents on one cheap model, 5 days; record cost per agent-day, invalid-action rate, interesting episodes; tune the prompt. (Needs the key.)
2. ~~Night reflection / diary~~ — done (see above). Viewer does not show diaries yet (log has them).
4. **Balance pass with bots.** Non-food professions barely survive solo; tune `config.py` so trade is clearly better than solo but solo is possible. Add a balance test.
5. **Metrics script.** From a log: interaction graph, trades, debts repaid/defaulted, thefts seen/unseen, Gini by day, fire responders. Output JSON + markdown.
6. **Live viewer.** FastAPI + WebSocket server streaming ticks while the sim runs; god buttons in the viewer.
7. **Pixel-art viewer.** Replace canvas shapes with a free top-down tileset and character sprites (same log format).
8. **Translation layer for viewers.** Agents speak English; viewer shows Russian translations of thoughts/says (batched, cached).
9. **Run config in YAML.** `--config runs/x.yaml`: agents, models, mechanics on/off, god script.
10. **Seasons.** Winter: field yields nothing; spec "economy".
11. **CI.** GitHub Actions running pytest on PRs.
