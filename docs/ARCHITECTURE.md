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
| `aivillage/population.py` | `population.size` → N villagers (configured ones first, then seeded names, professions by weight); scales resources, project needs, council orders by max(1, N/base_size). Runs at the end of `make_config`, idempotent (`resolved`) so replay does not grow twice |
| `aivillage/state.py` | dataclasses, `to_dict/from_dict`, `hash()` |
| `aivillage/ops.py` | `Ctx` (world + rng + `emit`), event delivery to inboxes, ledger-safe item/coin ops |
| `aivillage/registry.py` | `ACTIONS` / `GOD` registries: args model → prompt line, JSON schema, validation |
| `aivillage/actions.py` | agent actions |
| `aivillage/god.py` | experimenter interventions |
| `aivillage/engine.py` | `new_world`, `observe`, `step`, tasks, end of hour, night (tax, debts, orders, regrowth) |
| `aivillage/invariants.py` | per-tick checks |
| `aivillage/bots.py` | RandomBot (fuzzer), WorkerBot, ThiefBot |
| `aivillage/llm.py` | prompt, `parse_decision`, `LLMAgent`, `OpenRouterClient`, `StubClient`; `RateGate` per model (max parallel calls, shared cooldown after 429, env `AIVILLAGE_MAX_PARALLEL`), fallback models (`AIVILLAGE_FALLBACK_MODELS`, `--fallback`, YAML `fallback_models`) |
| `aivillage/run.py` | run loop (parallel decisions), JSONL log, `replay`, CLI |
| `aivillage/runconfig.py` | YAML run config (`--config`): validated up front, resolves to a world override, per-agent brains, god script; `mechanics.disabled` → world `disabled_actions`, enforced in `registry` |
| `aivillage/translate.py` | post-processes a finished log into a `<log>.ru.json` sidecar for spectators (never touches the log) |
| `aivillage/metrics.py` | behaviour metrics from a log only (JSON + Russian markdown) |
| `aivillage/server.py` | live mode: FastAPI app runs `run.run()` in a thread, streams log records over `/ws`, god events via `POST /api/god` (queued into `god_script`, so they are logged and replay exactly), pause/pace via `POST /api/control` |
| `viewer/live.js`, `viewer/god.js` | injected by the server into `index.html`: live feed (uses only `load()` / `ticks` / optional `window.viewerAppend`) and the god panel built from GOD schemas |
| `viewer/index.html` | Replay UI (controls, villager cards, diary, events). Feed it via `Viewer.start(header)` / `Viewer.push(row)`; `scripts/build_demo.py` bundles a log + scripts into one page |
| `viewer/pixelmap.js` | Pixel-art map renderer: map layout (viewer-only coordinates), art drawn in code, walking, fire, lighting |

## How to add a mechanic

1. Numbers → `config.py`.
2. State, if needed → a field in `state.py` (and `from_dict`).
3. Action → `@ACTIONS.action("name", "one-line description for the model", ArgsModel, available=...)` in `actions.py`. Validate everything first, raise `ActionError` with a message the agent can act on, then mutate. Use `ops` for items/coins and `ctx.emit` for what others see (`visibility`: public / location / private).
4. Periodic effects → `end_of_hour` or `night` in `engine.py`. If a new event should stop a busy agent, add its kind to `engine.WAKE_RULES` (each wake costs a model call).
5. Tests → one in `tests/test_mechanics.py`; the fuzzer in `tests/test_sim.py` starts calling the action automatically. Teach `RandomBot` its args if they are non-trivial.
6. `python -m pytest -q` must stay green.

A god event is the same, with `@GOD.action` in `god.py`.
