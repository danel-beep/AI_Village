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
- **Agents only see `observe()` and only act through decisions** `{"thought", "action": {"name", "args"}, "say", "notes"?}`. Bots and LLMs use the same interface.
- **All item/coin changes go through `ops.mint/burn/move_*`.** `invariants.check` compares holdings with `world.ledger` after every tick.
- **Numbers live in `config.py`.** No magic constants in actions.
- **Viewer reads only the log** (`view` snapshot per tick + events + decisions). It never talks to the engine.

## Modules

| File | Role |
| --- | --- |
| `aivillage/config.py` | all tunables, map, items, recipes, professions, agents |
| `aivillage/population.py` | `population.size` → N villagers (configured ones first, then seeded names, professions by weight); scales resources, project needs, council orders by max(1, N/base_size). Runs at the end of `make_config`, idempotent (`resolved`) so replay does not grow twice |
| `aivillage/clock.py` | game time: `tick_minutes` (15 in runs, 60 = hourly), tick <-> (day, hour, minute), `action_ticks` from `action_minutes` |
| `aivillage/state.py` | dataclasses, `to_dict/from_dict`, `hash()` |
| `aivillage/ops.py` | `Ctx` (world + rng + `emit`), event delivery to inboxes, ledger-safe item/coin ops |
| `aivillage/registry.py` | `ACTIONS` / `GOD` registries: args model → prompt line, JSON schema, validation |
| `aivillage/actions.py` | agent actions |
| `aivillage/god.py` | experimenter interventions |
| `aivillage/governance.py` | mayor elections, law proposals and votes, treasury, exile (via `ACTIONS.guards`), theft reports; engine hooks `end_of_hour` / `new_day` |
| `aivillage/engine.py` | `new_world`, `observe`, `step` (one tick; agents busy until `busy_until`, staggered wake-up), tasks, end of hour (last tick of the hour), night (tax, debts, orders, regrowth) |
| `aivillage/reputation.py` | reputation (each agent's own tally of deeds it saw: thefts, defaults, repaid debts, fire help, trades, gifts) and rumors (`gossip` action; stored with the teller, never scored). Hooks in via `ops.EVENT_HOOKS`; adds `reputation` / `rumors` to `observe()`; config block `reputation` |
| `aivillage/mapgen.py` | procedural village for a seed (`map.procedural`): river, landmarks, patches, hamlets, homes with plots, A* roads cut into one-hour hops by waypoints; honest-minimum `check`; `map.unfairness` 0..1 for plots, start coins/goods, resource richness. Run from `engine.new_world` when the config has no `map.layout` yet (replay never re-rolls) |
| `aivillage/tiles.py` | finite map objects: a resource with `slots` is split into trees / beds / bushes / shoals / rocks; take, regrow, sow, ripen |
| `aivillage/family.py` | feelings (directed scores moved by events via `family.on_event`), hang_out/propose/answer_proposal/divorce, marriage (shared house + chests), inheritance; feelings via `ops.EVENT_HOOKS`; engine calls `after_hour` (estates) / `after_night`; `observe()["relations"]`. Unlike reputation (what I saw), feelings are the relationship that drives marriage and inheritance |
| `aivillage/plots.py` | private yards (`world.plots[home]`): build / collect / expand_plot / upgrade_house / steal_from_plot, garden beds via `plant` at home, animals fed from the owner's chest in `after_night`, fire hook, `observe` (`plot`, `here_plot`, `village_plots`), prompt `facts`, log `view`; config block `plots`, start from `config.agents[i]` (`plot_cells`, `house_level`, `buildings`) |
| `aivillage/land.py` | land for sale: locations with a `lot` spec become unowned plots (`kind: "lot"`); `buy_land` (on the spot, to the treasury; or an owner's `sell_land` offer from anywhere), observation `your_lots` / `land_for_sale` / `land_owners` / `land_offers`, prompt `facts`. Building, collecting and yard theft on a lot are plots.py's |
| `aivillage/conflict.py` | `attack` (seeded D&D-like dice rounds, weapons from `combat.weapons`, loot), `set_fire` (arson with witnesses), `random_fire` (engine night, `random_fires.per_day`); an `ops.EVENT_HOOKS` hook lowers feelings and reputation toward the culprit; governance records `fight` / `arson_seen` as crimes |
| `aivillage/works.py` | village structures (well, bridge, watchtower, wall; levels from config `works.catalog`): `propose_build` (mayor, anyone without one; council after idle days), `build_work`, `fund_project`, `contribute` goes through `works.contribute`/`maybe_finish`; effect helpers `defense`, `sell_factor`, `notice_bonus`, `fire_grow_bonus` (imports no game module but ops/registry/population/state, so anyone can call them); `after_night`, `observe` (`village_structures`), `board`, `view`. Treasury embezzlement and audits live in `governance.py` (`embezzle`, `audit_treasury`, `handover`) |
| `aivillage/crises.py` | soft world crises (crop failure, drought, rats, trader shortage, caravan) started at dawn by `new_day` from config block `crises` (modes tune it); state in `world.crises`; engine hooks `blocks_regrowth` (regrowth loop) and `price_factor` (trader prices in `_price` and `observe`); `observe()["crises"]`, god event `crisis` |
| `aivillage/labor.py` | division of labour (config block `labor`, on in the `crafts` mode): only the profession gathers/sows its goods (berries, water free), `work_hours_per_day`, skill levels from hours at one's own trade (`Agent.skill_hours`, +`skill_bonus` per hour), the trader's daily buy/sell limits per item (`World.trader_day`, reset at dawn, checked in `buy`/`sell`); observation `work_today` / `trader_today`, prompt `facts`, log `view.labor` |
| `aivillage/graves.py` | a death (`death_mode: "death"`) buries the villager by their house: `World.graves`, public `death` event that wakes everyone, `graves` / `graves_here` in every observation, `pay_respects` at the grave, `view.graves` (drawn by `viewer/plotlayer.js`); cause = `Agent.harm` (god `lightning`) else hunger / wounds |
| `aivillage/invariants.py` | per-tick checks |
| `aivillage/bots.py` | RandomBot (fuzzer), WorkerBot, ThiefBot |
| `aivillage/llm.py` | prompt, `parse_decision`, `LLMAgent`, `OpenRouterClient`, `StubClient`; `RateGate` per model (max parallel calls, shared cooldown after 429, env `AIVILLAGE_MAX_PARALLEL`), fallback models (`AIVILLAGE_FALLBACK_MODELS`, `--fallback`, YAML `fallback_models`); `OpenAIClient` + `FallbackClient`; build clients only with `make_client(model)` (provider from keys.py) |
| `aivillage/keys.py` | keys, provider, model, parallel limit in `<home>/settings.json` on the player's computer (file wins over env); `public()` = masked view for the viewer |
| `aivillage/run.py` | run loop (parallel decisions), JSONL log (header `brains` = who plays whom, `usage` records = tokens and cost per LLM villager), `replay`, CLI |
| `aivillage/saves.py` | save / continue a village: `<log>.save.json` = world dict (hash-checked), villagers' brains (LLM memory + usage, bot fields + RNG state), pending god events, run options, log length. Taken only at run()'s `checkpoint` (between ticks); loading cuts the log back to that length and `run(resume_header=...)` appends to the same log, so replay of the whole log still holds. Live: `LiveSim.save()`, autosave every game hour / on stop / at the end, `Host.load()`, `/api/saves`, `/api/save`, `/api/load`; UI `viewer/saves.js` |
| `aivillage/scorecard.py` | end-of-run scorecard from a log: per villager (survival, wealth, thefts, gifts, trades, loans, defaults, fire help, gossip, invalid actions, top actions, cost; optional lie judge), also added up per brain; `run.main` writes `<log>.scorecard.md/.json` |
| `aivillage/runconfig.py` | YAML run config (`--config`): validated up front, resolves to a world override, per-agent brains, god script; `mechanics.disabled` → world `disabled_actions`, enforced in `registry` |
| `aivillage/modes.py` | economy modes: named world-rule presets (`mode:` in YAML, `--mode`, start screen). Partial world config + disabled actions, applied under the run config's `world:`; recorded as `config.economy_mode`. The prompt is the same in every mode, only `world_facts` numbers differ. `scripts/compare_modes.py` runs all modes and compares behaviour |
| `aivillage/translate.py` | post-processes a finished log into a `<log>.ru.json` sidecar for spectators (never touches the log) |
| `aivillage/summary.py` | LLM recaps of log stretches for spectators (digest of thoughts/actions/says/events → 3-6 Russian sentences); sidecar `<log>.summary.json` |
| `aivillage/reports.py` | problem reports: note + log + recaps zipped for the project chat; `show` prints the moment around the reported tick |
| `aivillage/metrics.py` | behaviour metrics from a log only (JSON + Russian markdown) |
| `aivillage/server.py` | live mode: FastAPI app runs `run.run()` in a thread, streams log records over `/ws`, god events via `POST /api/god` (scheduled for a tick just after the one on screen via `GodQueue`, announced as `god_pending`, then logged in `god`, so replay stays exact), pause/pace via `POST /api/control` |
| `aivillage/knobs.py` | start-screen settings: `KNOBS`, one dict per slider/choice/toggle. `path` = dotted world-config key (default from the chosen economy mode, hidden until the key exists in `DEFAULT_CONFIG`), no path = run option (villagers, days, pace, seed, bots). `to_run(answers)` -> world override + run options. **A new config knob for the app = one line here**, no JS. |
| `viewer/setup.js` + `server.py --setup` | the app opens on the start screen (no village yet); `GET /api/setup` (schema + per-mode defaults), `POST /api/start` builds a `LiveSim` via `Host`, page reloads into live mode; `POST /api/stop` ("🔄 Новая деревня") goes back. Also `/api/runs`, `/replay/<name>` (build_demo on demand), `/api/report-last`. Launcher = `server --setup`, no terminal questions. |
| `viewer/report.js` | injected by the server: recap panel (`/api/summary`) and problem report form (`/api/report`) |
| `viewer/live.js`, `viewer/god.js` | injected by the server into `index.html`: live feed (uses only `load()` / `ticks` / optional `window.viewerAppend`) and the god panel built from GOD schemas |
| `viewer/index.html` | Replay UI (controls, villager cards, diary, events). Feed it via `Viewer.start(header)` / `Viewer.push(row)`; `scripts/build_demo.py` bundles a log + scripts into one page |
| `viewer/pixelmap.js` | Pixel-art map renderer: map layout (viewer-only coordinates), art drawn in code, walking, lighting |
| `viewer/sprites.js`, `viewer/sprites_data.js` | `Sprites`: SpriteCook art atlas (built by `scripts/build_sprites.py` from the sheets in `viewer/art/`; every name is listed in `viewer/art/CATALOG.md`). Hooks call `Sprites.draw(g, name, x, y)` (bottom-centre) and fall back to the code art when it returns false; `?sprites=0` forces the code art. Ground textures `tex_*` (48 px, seamless): `Sprites.pattern(g, name)` for fills, `Sprites.pixels(name)` for pixel work (pixelmap's `terrain()`); `Sprites.brawl(g, x, y, sec, {dice})` draws a fight cloud for whoever shows fights |
| `viewer/actors.js` | Villagers: activity per tick from their own events (`work` resource/slots, `plant`, `pour_water`, `craft`, `eat`, `say`...), poses with tools and particles (axe, pick, hoe, rod, bucket, hammer), idle strolls, smoothing of every position jump, speech/thought/whisper bubbles. Wall-clock loops keep villagers busy between ticks. To animate a new event kind add it to `KIND` (+ a pose in `POSES`) |
| `viewer/sound.js` | `Sound`: music, ambience and event cues synthesized with WebAudio from the shown tick (`Sound.update(header, ticks, i, playing)` in `render()`). New event sound: add a row to `CUES` (regex on kind) and a function to `SFX`. Adds 🔊/volume/🎵 to `#bar` |
| `viewer/camera.js` | Zoom (wheel, +/- buttons, keys `+ - 0`), drag to pan, follows the selected villager. `PixelMap.pick(x, y)` takes canvas pixels and converts through the camera |
| `viewer/mapgen.js` | `GenMap`: turns `config.map.layout` into pixelmap's layout (landmark art shifted by `off`), paints river/plots/patches/hamlets/signposts, gives maplayer the resource spots of patches and the river |
| `viewer/plotlayer.js` | Yards from `view.plots`: buildings packed into cells in build order (beds, coop with hens, cow pen, hives with bees), what is ready, bought land, house level on the roof. Yard = `layout.plots[home]` / the house's generated `plot`, else 3x3 tiles behind the house. Hooked via `PlotLayer.init/draw` |
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
| `fire` | `victim`, `house` (+ `arsonist` or `cause: "accident"`) | public |
| `fight` | `attacker`, `defender`, `winner`, `rounds`, `damage`, `loot`, `weapons`, `witnesses` | location + defender |
| `set_fire` / `arson_seen` | `victim`, `house` (+ `arsonist`) | arsonist / each witness |
| `land_bought` / `land_sold` / `land_offer` | `lot`, `price` | public / public / buyer |
| `fire_grows` | `house`, `water_needed`, `hours_left` | location |
| `pour_water` / `fire_out` | `helper`, `house`, `buckets`, `water_needed` | location / public |
| `house_burned` | `home` | public |

Fire: lasts `fire_ticks` hours, needs one more bucket every `fire_grow_hours` (up to `fire_water_max`), a night counts
as `fire_night_hours`. `extinguish` pours all the water the agent carries (up to what the fire needs).

## How to add a mechanic

1. Numbers → `config.py`.
2. State, if needed → a field in `state.py` (and `from_dict`).
3. Action → `@ACTIONS.action("name", "one-line description for the model", ArgsModel, available=...)` in `actions.py`. Validate everything first, raise `ActionError` with a message the agent can act on, then mutate. Use `ops` for items/coins and `ctx.emit` for what others see (`visibility`: public / location / private).
   To forbid an action under some rule without editing it, append a guard to `ACTIONS.guards` (see `governance._exile_guard`).
4. Reacting to events (social modules) → append `hook(ctx, event, recipients)` to `ops.EVENT_HOOKS`; it runs after every `emit`, recipients are who actually saw it. Extra observation fields → `obs.update(module.observe(world, name))` in `engine.observe`. Per-agent state → a defaulted field on `Agent` (old logs still load).
   How long it keeps the agent busy: `config.action_minutes[name]` (not listed = 60 min). Anything measured in hours
   or ticks goes through `clock.hours(cfg, n)` / `clock.tick_of`, never `tick + n`.
5. Periodic effects → `end_of_hour` or `night` in `engine.py`. If a new event should stop a busy agent, add its kind to `engine.WAKE_RULES` (each wake costs a model call).
6. Tests → one in `tests/test_mechanics.py`; the fuzzer in `tests/test_sim.py` starts calling the action automatically. Teach `RandomBot` its args if they are non-trivial.
7. `python -m pytest -q` must stay green.

A god event is the same, with `@GOD.action` in `god.py`.
