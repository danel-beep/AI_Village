# «С нуля» (start from zero): shared spec

The plan (Russian, for Danel): `/mnt/project-files/reports/survival-plan/plan.md`. This file pins the
interfaces the threads of that plan share, so they can work in parallel. Change it only in the thread that
owns `progress.py` (or agree first through the coordinator).

## Rules for every thread of this plan

- Everything new is behind a config flag. The «Обычный» mode behaves as before unless a bot run and a
  1–2 day AI run show nothing broke; then turning it on there is a separate, stated decision.
- Neutral texts only (`tests/test_neutrality.py`): facts, no advice. Dilemmas come from rules, never from words.
- Exact replay, invariants and tests green. One line in `engine.py` per module (`night` / `end_of_hour` /
  `observe`), no other edits there.
- Item, building and stage ids below are canonical: the engine, the art library (viewer) and the
  handbook use the same names. A thread that needs a new id adds it here in its PR.

## Stages and unlocks (`aivillage/progress.py`, done)

Config `progress`: `enabled` (off = everything open), `start_stage` (id or index), `stages`
(`[{"id", "requires": {"buildings": {kind: n}}}]`), `unlocks` (overrides `progress.DEFAULT_UNLOCKS`).

| stage | stands in the village |
|---|---|
| `camp` | (start) |
| `hamlet` | 3 × `house`, 1 × `workbench` |
| `village` | 1 × `market_square`, 1 × `smithy` |
| `town` | 1 × `town_hall`, 3 × `house@2` |

API for other modules:

- `progress.unlocked(world, key) -> bool`. Keys: `action:<name>`, `recipe:<name>`, `building:<kind>`,
  `law:<name>`, `feature:<name>`. Ask it before anything automatic: `feature:trader` (the trader comes),
  `feature:elections`, `feature:taxes`, `feature:raids`. True when progress is off or the key has no rule.
- Register a mechanic's rule by adding to `progress.DEFAULT_UNLOCKS` in that module
  (`DEFAULT_UNLOCKS["action:hunt"] = {"stage": "hamlet"}`), rule = `{"stage": id}` and/or `{"building": kind}`.
- Locked actions are refused by a registry guard and hidden from `available_actions` and the handbook.
- `progress.built(world) -> Counter`: what stands. Counted from plots (`house` by `plot.house`, yard
  buildings by `kind`, with `level` if the building dict has one) and `world.works.levels`. Leveled kinds
  count as `kind`, `kind@2`, `kind@3`. A module with its own buildings appends `fn(world) -> Counter`
  to `progress.BUILT_SOURCES`.
- Unlocks are sticky; the stage never drops.
- Observation (progress on): `village_stage: {stage, next_stage, next_stage_needs_standing: {kind: "have/need"}}`.
- Log: public event `village_stage` with `stage` (id) and `index`. State `world.progress`
  (`stage`, `reached: {id: day}`, `unlocked: [keys]`).

## Empty start (task 2, `modes.py`)

Mode id `survival` («С нуля»). Config `bare_start` (`enabled`, `until_stage`, default `hamlet`): a start before
that stage has every villager at profession `laborer`, house level 0, no coins, items or yard buildings,
gathering anything by hand. From `until_stage` on, the start is the ready village of the crafts mode.

## Building ids

Stage-critical (the stage table uses them): `house` (levels 1–3; `shelter` is the level-0 hut before it),
`workbench`, `market_square`, `smithy`, `town_hall`, `tavern`.
Others from the plan: `campfire`, `granary`, `smokehouse`, `pen`, `kiln`, `mill`, `weaving_shed`,
`tannery`, `stable`, `palisade` (→ `wall`), plus today's yard buildings (`garden_bed`, `chicken_coop`,
`cow_pen`, `beehive`, `fence`) and works (`well`, `bridge`, `watchtower`, `wall`).

## Item ids

Today: `grain fish berries wood stone ore water bread fish_soup tool lock egg milk honey gold club spear stew
pancakes honey_cake ring`. Added by the plan: raw `clay meat hide hay`; materials `plank brick iron leather
flour`; tools `stone_axe stone_pick iron_axe iron_pick hoe fishing_rod` (`tool` stays as the generic iron
tool of today's modes); weapons `bow sword`; armor `leather_armor iron_armor`; food `smoked_meat`.

## Log fields for the viewer (task 13b)

- `village_stage` events (above).
- Construction sites (task 3 defines them, fields fixed here): tick `view.sites` =
  `[{"id", "kind", "level", "location", "done": 0..1, "workers": [names]}]`.
- Buildings with levels: plot building dicts carry `level` (default 1); works keep `works.levels`.
- Unexplored places (task 6): tick `view.known` = location ids someone has seen.
