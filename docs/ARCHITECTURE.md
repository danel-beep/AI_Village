# Architecture

Spec: https://claude.ai/code/artifact/df507acc-4173-430d-9dfe-760898a4e089

```
god events ─┐
            ▼
  engine.step(world, decisions, god) ──► events ──► run.py JSONL log ──► viewer / analytics
       ▲                 │
       │ decisions       │ observe(world, name)
       │                 ▼
  bots.py / llm.py (LLMAgent → Client: OpenAI direct → OpenRouter fallback | OpenRouter | Stub)
```

## Boundaries (keep them)

- **Engine is pure and deterministic.** `engine.py`, `actions.py`, `god.py`, `ops.py`, `state.py` never import LLM code, never read the clock or global randomness. Randomness = `rng_for(world)` seeded by `(seed, tick)`. This is what makes replay work; `tests/test_sim.py` breaks if you violate it.
- **Agents only see `observe()` and only act through decisions** `{"thought", "action": {"name", "args"}, "say", "notes"?}`. Bots and LLMs use the same interface. One exception, outside the engine: with `talk.turn_taking` run.py adds `just_said` (talk.py) to the observation of a villager who takes its turn after others at the same place; it is built from this tick's decisions and is not world state. The turn order is logged per tick (`talk`) and `engine.step(..., talk_order)` executes in it.
- **All item/coin changes go through `ops.mint/burn/move_*`.** `invariants.check` compares holdings with `world.ledger` after every tick.
- **Numbers live in `config.py`.** No magic constants in actions.
- **Viewer reads only the log** (`view` snapshot per tick + events + decisions). It never talks to the engine.

## Task → files

Start from this map; per-module details are in `docs/modules.md` (read only the part you need).

| Task | Files |
|---|---|
| Core rules, actions | `engine.py` (`step`, `observe`, `end_of_hour`, `night`, `WAKE_RULES`), `actions.py`, `ops.py`, `state.py`, `invariants.py`, `registry.py` |
| Numbers, presets | `config.py`, `modes.py` + `presets/*.yaml` (the one «С нуля» world, presets on top), `knobs.py` (settings shown in the app), `runconfig.py` |
| Villager prompt and model calls | `llm.py` (`SYSTEM`, `world_facts`, JSON parsing, memory, cache), `handbook.py`, `talk.py`, `addressed.py`, `budget.py`, `keys.py` |
| Bots | `bots.py` |
| Run loop, log, snapshot | `run.py` (`view`, `llm_agents`, log header), `logio.py` (view deltas; read logs only through `read_log`), `saves.py`, `session.py`, `population.py`, `scenario.py` + `scenarios/*.yaml` |
| Economy | `market.py`, `pricing.py`, `merchant.py`, `crafting.py`, `labor.py`, `hire.py`, `spoilage.py`, `transport.py`, `dice.py`, `luxury.py` |
| Land, building, map | `land.py`, `plots.py`, `settle.py`, `construction.py`, `works.py`, `tiles.py`, `mapgen.py`, `explore.py`, `places.py`, `progress.py` |
| Power and money | `governance.py`, `polity.py`, `taxes.py`, `debts.py`, `theft.py` |
| Social | `reputation.py`, `family.py`, `chronicle.py`, `honors.py`, `graves.py`, `dilemmas.py` |
| Danger, world events | `threats.py`, `animals.py`, `conflict.py`, `crises.py`, `illness.py`, `seasons.py`, `god.py` |
| Measuring, experiments | `metrics.py`, `social_metrics.py`, `scorecard.py`, `lab.py`, `reports.py`, `summary.py`, `highlights.py` |
| App, server, launcher | `server.py`, `launcher.py`, `remote.py`, `tunnel.py`, `mcpserver.py` (own AI, `docs/own-ai.md`; tournament lobby `viewer/join.html`, `docs/tournament.md`), `scripts/install.*`, `scripts/start.*` |
| Viewer (browser) | `viewer/index.html`, `live.js`, `replay.js`, `setup.js`/`settings.js` (start screen), `maplayer.js`/`pixelmap.js`/`sprites*.js` (map art), `actors.js`/`camera.js`/`combat.js` (motion), `dossier.js`/`hero.js`/`inspect.js` (panels), `efir.js`/`fate.js`/`foresight.js` (broadcast) |
| Log format, map objects | `docs/modules.md` («Map objects and fire in the log») |
| Specs and run reports | `docs/specs/`, `docs/runs/` |

A mechanic module is wired by hand in several places (a registry may replace this later):
`engine` world setup calls its `setup`; `engine.observe` / `end_of_hour` / `night` call the module's `observe` / `end_of_hour` / `night`;
`llm.world_facts` adds its rules text (`facts(cfg)`), behind `shown(<unlock key>)` when village stages keep the
mechanic closed at first (the prompt only describes what is open; `tests/test_prompt_size.py` caps its size); `run.view` adds its `view()` for the viewer;
`run.llm_agents` hides its actions when it is off (`hidden_actions`). `grep` an existing module
(e.g. `transport`) in those files to copy the pattern.

## How to add a mechanic

1. Numbers → `config.py`.
2. State, if needed → a field in `state.py` (and `from_dict`).
3. Action → `@ACTIONS.action("name", "one-line description for the model", ArgsModel, available=...)` in `actions.py`. Validate everything first, raise `ActionError` with a message the agent can act on, then mutate. Use `ops` for items/coins and `ctx.emit` for what others see (`visibility`: public / location / private).
   The action shows up in the villager's handbook by itself (`handbook.py`, topic "Other" unless its module or name
   is in `MODULE_TOPIC` / `ACTION_TOPIC`). Describe it as a plain fact, no advice or judgement:
   `tests/test_neutrality.py` scans every prompt, observation, event and error text the model reads.
   To forbid an action under some rule without editing it, append a guard to `ACTIONS.guards` (see `governance._exile_guard`).
   To step in before an action runs (and maybe stop it), append to `ACTIONS.interceptors` `fn(ctx, actor, name, args) -> bool`
   (True = handled, the action does not run; see `hire._intercept`: a guard fights the thief first).
4. Reacting to events (social modules) → append `hook(ctx, event, recipients)` to `ops.EVENT_HOOKS`; it runs after every `emit`, recipients are who actually saw it. Extra observation fields → `obs.update(module.observe(world, name))` in `engine.observe`. Per-agent state → a defaulted field on `Agent` (old logs still load).
   How long it keeps the agent busy: `config.action_minutes[name]` (not listed = 60 min). Anything measured in hours
   or ticks goes through `clock.hours(cfg, n)` / `clock.tick_of`, never `tick + n`.
5. Periodic effects → `end_of_hour` or `night` in `engine.py`. If a new event should stop a busy agent, add its kind to `engine.WAKE_RULES` (each wake costs a model call).
6. Tests → one in `tests/test_mechanics.py`; the fuzzer in `tests/test_sim.py` starts calling the action automatically. Teach `RandomBot` its args if they are non-trivial.
7. `python -m pytest -q` must stay green.

A god event is the same, with `@GOD.action` in `god.py`.
