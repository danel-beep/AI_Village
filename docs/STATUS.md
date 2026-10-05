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
- Backlog 1 (branch `claude/project-thread-ifc3d6`): first real-model run, report `docs/runs/first-llm-run.md`. Default model `llm.DEFAULT_MODEL = "openai/gpt-6-luna"` (newest ultra-cheap, $0.10/$0.50 per 1M; `--models default`), also the translate default. 5 agents × 5 days: $0.0027 per agent-day, 0% invalid actions (Gemini 2.5 Flash Lite: 10–19%, agents starved). Prompt now has a rules cheat sheet from config (`world_facts`), last 3 own actions, JSON mode, retry on unparseable reply, low reasoning effort; client backs off on HTTP 429 (Luna allows ~4 parallel calls).
- Demo replay published (now the first LLM run): https://claude.ai/artifact/Ftf7M9UrQnRYXxohReXqYy
- Backlog 4 (branch `claude/project-thread-sl1k6b`): economy balance. `satiety_loss_per_hour` 3→2 (about one meal a day), forest wood 80/regen 40, mine stone 60/regen 30, ore 30/regen 10 (before: woodcutter, miner, smith were evicted or hospitalised even solo). New bots `TraderBot` (evening market at the square, sells meals/tools/wood/ore at the NPC mid price) and `LonerBot` (same, NPC only). `tests/test_balance.py`, a full year with winter, 3 seeds: loners never hit hospital or eviction; traders end with about +30% village wealth and no profession below 90% of its solo result. Not covered: food regen is fixed per map, so 20 agents will need bigger field/river numbers.
- One-click launcher (branch `claude/project-thread-m74d7m`): `scripts/install.ps1` (Windows, one PowerShell line) and `scripts/install.sh` (Mac/Linux, one Terminal line) put an "AI Village" icon on the Desktop. Each start (`scripts/start.ps1` / `start.sh`) installs uv (which brings Python 3.12) if missing, re-downloads `main` from GitHub into `~/AIVillage/app`, and opens a Russian menu (`aivillage/launcher.py`): LLM village (5 agents, `AIVILLAGE_MODEL`, default `llm.DEFAULT_MODEL`, key asked once, stored in `~/AIVillage/openrouter_key`), bots village, open a past run (built with `build_demo.py`), change key. Browser opens itself; logs go to `~/AIVillage/runs`. Requires the repo to stay public. Tested on Linux only; Windows/Mac scripts untested on real machines. 24/7 cloud hosting not set up (would need a paid host account, e.g. Railway; nothing registered).
- Demo artifact rebuilt from current main (same link).
- Living map (branch `claude/project-thread-6a8b9l`): finite map objects (`aivillage/tiles.py`). Forest = 8 trees (chopped tree → stump → regrows), field = 8 beds (harvested → bare soil → sprouts → gold), 5 berry bushes, 6 fish shoals, 6 rocks + 6 ore veins. New action `plant` (1 grain in a free bed → 5 grain after 2 nights, anyone can harvest; frozen in winter). Fire: burns 10 hours, +1 bucket every 2 hours (max 8), night = 4 hours; `extinguish` pours all carried water; events `pour_water`, `fire_grows`, `slot_empty`, `plant`, `crop_ripe`. Log `view` has `map` and `fire_info` (schema in ARCHITECTURE.md). Viewer layer `viewer/maplayer.js` draws them (hooks in pixelmap.js only behind `window.MapLayer`). Balance test unchanged and green. Bots don't plant yet (LLM agents see it).

## Blocked

- Nothing. `OPENROUTER_API_KEY` works in the cloud environment ($10 limit on the key).

## Backlog (independent)

1. ~~First LLM run + report~~ — done (see above).
12. **Request queue for 20 agents.** Cap parallel model calls per provider and queue the rest instead of hitting 429.
13. **Model comparison run.** Same seed, one model per agent (gpt-6-luna, deepseek-v4.1-flash, ...); compare survival, trades, deceit.
2. ~~Night reflection / diary~~ — done (see above). Viewer shows diaries on villager click.
5. ~~Metrics script~~ — done (`aivillage/metrics.py`).
6. ~~Live viewer~~ — done (see above).
9. ~~**Run config in YAML.**~~ Done, see above.
7. ~~Pixel-art viewer~~ — done, see above.
8. ~~Translation layer for viewers~~ — done (see above).
10. ~~**Seasons.**~~ Done, see above.
11. ~~**CI.** GitHub Actions running pytest on PRs.~~ Готово: `.github/workflows/tests.yml` гоняет pytest на каждом PR и push в main.
