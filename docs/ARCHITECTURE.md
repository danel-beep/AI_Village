# Architecture

Spec: https://claude.ai/code/artifact/df507acc-4173-430d-9dfe-760898a4e089

```
god events ─┐
            ▼
  engine.step(world, decisions, god) ──► events ──► run.py JSONL log ──► viewer / analytics
       ▲                 │
       │ decisions       │ observe(world, name)
       │                 ▼
  bots.py / llm.py (LLMAgent → Client: OpenRouter | Stub)
```

## Boundaries (keep them)

- **Engine is pure and deterministic.** `engine.py`, `actions.py`, `god.py`, `ops.py`, `state.py` never import LLM code, never read the clock or global randomness. Randomness = `rng_for(world)` seeded by `(seed, tick)`. This is what makes replay work; `tests/test_sim.py` breaks if you violate it.
- **Agents only see `observe()` and only act through decisions** `{"thought", "action": {"name", "args"}, "say", "notes"?}`. Bots and LLMs use the same interface.
- **All item/coin changes go through `ops.mint/burn/move_*`.** `invariants.check` compares holdings with `world.ledger` after every tick.
- **Numbers live in `config.py`.** No magic constants in actions.
- **Viewer reads only the log** (`view` snapshot per tick + events + decisions). It never talks to the engine.

## Modules

| File | Role |
| --- | --- |
| `aivillage/config.py` | all tunables, map, items, recipes, professions, agents |
| `aivillage/state.py` | dataclasses, `to_dict/from_dict`, `hash()` |
| `aivillage/ops.py` | `Ctx` (world + rng + `emit`), event delivery to inboxes, ledger-safe item/coin ops |
| `aivillage/registry.py` | `ACTIONS` / `GOD` registries: args model → prompt line, JSON schema, validation |
| `aivillage/actions.py` | agent actions |
| `aivillage/god.py` | experimenter interventions |
| `aivillage/engine.py` | `new_world`, `observe`, `step`, tasks, end of hour, night (tax, debts, orders, regrowth) |
| `aivillage/reputation.py` | reputation (each agent's own tally of deeds it saw: thefts, defaults, repaid debts, fire help, trades, gifts) and rumors (`gossip` action; stored with the teller, never scored). Hooks in via `ops.EVENT_HOOKS`; adds `reputation` / `rumors` to `observe()`; config block `reputation` |
| `aivillage/tiles.py` | finite map objects: a resource with `slots` is split into trees / beds / bushes / shoals / rocks; take, regrow, sow, ripen |
| `aivillage/family.py` | feelings (directed scores moved by events via `family.on_event`), hang_out/propose/answer_proposal/divorce, marriage (shared house + chests), inheritance; feelings via `ops.EVENT_HOOKS`; engine calls `after_hour` (estates) / `after_night`; `observe()["relations"]`. Unlike reputation (what I saw), feelings are the relationship that drives marriage and inheritance |
| `aivillage/invariants.py` | per-tick checks |
| `aivillage/bots.py` | RandomBot (fuzzer), WorkerBot, ThiefBot |
| `aivillage/llm.py` | prompt, `parse_decision`, `LLMAgent`, `OpenRouterClient`, `StubClient` |
| `aivillage/run.py` | run loop (parallel decisions), JSONL log, `replay`, CLI |
| `aivillage/runconfig.py` | YAML run config (`--config`): validated up front, resolves to a world override, per-agent brains, god script; `mechanics.disabled` → world `disabled_actions`, enforced in `registry` |
| `aivillage/translate.py` | post-processes a finished log into a `<log>.ru.json` sidecar for spectators (never touches the log) |
| `aivillage/summary.py` | LLM recaps of log stretches for spectators (digest of thoughts/actions/says/events → 3-6 Russian sentences); sidecar `<log>.summary.json` |
| `aivillage/reports.py` | problem reports: note + log + recaps zipped for the project chat; `show` prints the moment around the reported tick |
| `aivillage/metrics.py` | behaviour metrics from a log only (JSON + Russian markdown) |
| `aivillage/server.py` | live mode: FastAPI app runs `run.run()` in a thread, streams log records over `/ws`, god events via `POST /api/god` (queued into `god_script`, so they are logged and replay exactly), pause/pace via `POST /api/control` |
| `viewer/report.js` | injected by the server: recap panel (`/api/summary`) and problem report form (`/api/report`) |
| `viewer/live.js`, `viewer/god.js` | injected by the server into `index.html`: live feed (uses only `load()` / `ticks` / optional `window.viewerAppend`) and the god panel built from GOD schemas |
| `viewer/index.html` | Replay UI (controls, villager cards, diary, events). Feed it via `Viewer.start(header)` / `Viewer.push(row)`; `scripts/build_demo.py` bundles a log + scripts into one page |
| `viewer/pixelmap.js` | Pixel-art map renderer: map layout (viewer-only coordinates), art drawn in code, walking, lighting |
| `viewer/actors.js` | Villagers: activity per tick from their own events (`work` resource/slots, `plant`, `pour_water`, `craft`, `eat`, `say`...), poses with tools and particles (axe, pick, hoe, rod, bucket, hammer), idle strolls, smoothing of every position jump, speech/thought/whisper bubbles. Wall-clock loops keep villagers busy between ticks. To animate a new event kind add it to `KIND` (+ a pose in `POSES`) |
| `viewer/camera.js` | Zoom (wheel, +/- buttons, keys `+ - 0`), drag to pan, follows the selected villager. `PixelMap.pick(x, y)` takes canvas pixels and converts through the camera |
| `viewer/maplayer.js` | Map objects layer, drawn from `view.map` / `view.fire_info` / events: trees and stumps, beds by growth stage, bushes, fish, rocks, fire size, water splashes. Hooked into pixelmap via `MapLayer.init/claimTrees/draw/drawTop` |

## Map objects and fire in the log

A location resource with `"slots": n` in `config.py` is n objects of `max // n` units (`tiles.py`). `loc.resources[r]`
(what agents see) always equals `sum(loc.slots[r])`; invariants check it. Gathering empties the least-full object
first (a tree is chopped down before the next one is started); night regrowth adds one unit at a time to the emptiest
object, so beds grow through visible stages. `"plant": {"seed", "days"}` makes a resource sowable: `plant` takes a free
(empty, unsown) bed, it is skipped by regrowth and becomes full on `ripe_day`. Winter frost and god drought go through
`tiles.clear` / `tiles.scale`.

Every tick's `view` carries:

- `map`: `{loc: {"slots": {resource: [units per object]}, "cap": {resource: units when full}, "planted": {slot: {"resource", "by", "ripe_day"}}}}`.
  Object i keeps its index forever, so the viewer can give it a fixed place. 0 units = stump / bare soil / empty bush.
- `fire_info`: `{house: {"water_needed", "hours_left", "hours"}}` (`fires` stays a plain list of houses).

Events for animation (all have `actor`, `location` and `data`):

| kind | data | visibility |
| --- | --- | --- |
| `work` | `resource`, `amount`, `slots` (objects touched) | actor only |
| `slot_empty` | `resource`, `slot` (a tree fell, a bed was harvested) | log only |
| `plant` | `resource`, `slot`, `ripe_day` | location |
| `crop_ripe` | `resource`, `slot`, `by` | the planter |
| `fire` | `victim`, `house` | public |
| `fire_grows` | `house`, `water_needed`, `hours_left` | location |
| `pour_water` / `fire_out` | `helper`, `house`, `buckets`, `water_needed` | location / public |
| `house_burned` | `home` | public |

Fire: lasts `fire_ticks` hours, needs one more bucket every `fire_grow_hours` (up to `fire_water_max`), a night counts
as `fire_night_hours`. `extinguish` pours all the water the agent carries (up to what the fire needs).

## How to add a mechanic

1. Numbers → `config.py`.
2. State, if needed → a field in `state.py` (and `from_dict`).
3. Action → `@ACTIONS.action("name", "one-line description for the model", ArgsModel, available=...)` in `actions.py`. Validate everything first, raise `ActionError` with a message the agent can act on, then mutate. Use `ops` for items/coins and `ctx.emit` for what others see (`visibility`: public / location / private).
4. Reacting to events (social modules) → append `hook(ctx, event, recipients)` to `ops.EVENT_HOOKS`; it runs after every `emit`, recipients are who actually saw it. Extra observation fields → `obs.update(module.observe(world, name))` in `engine.observe`. Per-agent state → a defaulted field on `Agent` (old logs still load).
5. Periodic effects → `end_of_hour` or `night` in `engine.py`. If a new event should stop a busy agent, add its kind to `engine.WAKE_RULES` (each wake costs a model call).
6. Tests → one in `tests/test_mechanics.py`; the fuzzer in `tests/test_sim.py` starts calling the action automatically. Teach `RandomBot` its args if they are non-trivial.
7. `python -m pytest -q` must stay green.

A god event is the same, with `@GOD.action` in `god.py`.
