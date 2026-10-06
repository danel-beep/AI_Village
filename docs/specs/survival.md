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
  `feature:elections`, `feature:taxes`, `feature:raids`, `feature:council_orders` (taxes.py) and
  `feature:council_projects` (works.py), both with a town_hall. True when progress is off or the key has no rule.
  For a rules line, `governance.opens_note(cfg, key)` gives " (once a town_hall stands in the village)" (or "").
- Register a mechanic's rule by adding to `progress.DEFAULT_UNLOCKS` in that module
  (`DEFAULT_UNLOCKS["action:hunt"] = {"stage": "hamlet"}`), rule = `{"stage": id}` and/or `{"building": kind}`.
- Locked actions are refused by a registry guard and hidden from `available_actions` and the handbook.
- `progress.built(world) -> Counter`: what stands. Counted from plots (`house` by `plot.house`, yard
  buildings by `kind`, with `level` if the building dict has one) and `world.works.levels`. Leveled kinds
  count as `kind`, `kind@2`, `kind@3`. A module with its own buildings appends `fn(world) -> Counter`
  to `progress.BUILT_SOURCES`.
- Unlocks are sticky; the stage never drops. Starting at a later stage, the buildings that stage and the
  earlier ones require count as standing (`world.progress.prebuilt`).
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

## Construction (`aivillage/construction.py`, done)

Config `construction`: `enabled`, `team_window_minutes`, `team_bonus`, `team_max`, `max_open_sites`, `catalog`
(kind -> `name`, `place` "home" | "village", `at` (allowed places for village kinds), `levels`: rows of
`items`, `hours`, `min_workers` and effects `roof`, `food_keeps_x` (+ `food_items`), `sell_bonus`, `defense`,
`workshop`, `extra_per_batch` (a workshop adds that many to every batch made there), `makes` + `feed` + `cap`
(yard production fed from the owner's chest at night, collected like a coop); a row is what that level gives,
not added up). `raw_instead` maps crafted materials to raw ones when crafting is off. Catalog: `shelter`,
`house` 1–3, `campfire` 1–2, `workbench` 1–2, `granary` 1–2, `smokehouse` 1–2, `market_square` 1–2, `smithy` 1–2,
`town_hall`, `tavern`, `palisade` 1–2, `kiln` 1–2, `mill` 1–2, `tannery` 1–2, `weaving_shed`, `pen` 1–2,
`wall` 1–2 (needs `palisade@2`). Events: `workshop_bonus` {recipe, amount, building, level}.

- Actions: `start_building(kind)` (here: own yard for "home" kinds, a common place for "village" ones),
  `bring_materials(site_id, items)`, `construct(site_id)` (one hour). With `min_workers` > 1 an hour counts only
  while that many different villagers worked on the site within the window (same day); lone hours older than the
  window are lost (`site_work_lost`). `upgrade_house` is refused while construction is on.
- Unlock keys: `building:<kind>` and `building:<kind>@<level>` (registered in `progress.DEFAULT_UNLOCKS`).
- Finished "home" buildings are plot building dicts with `level` (`house` sets `plot.house`); "village" ones are
  `world.construction["buildings"]` (`{id, kind, level, location, owner: None, built_day, builders}`), counted
  through `progress.BUILT_SOURCES`.
- API: `has_building(world, kind, name=None, location=None) -> level`, `has_roof(world, name)`,
  `place(world, kind, location, level=1)` (start stages), `food_keeps_x` (via `spoilage.STORAGE_SOURCES`),
  `defense` / `sell_bonus` (via `works.DEFENSE_SOURCES` / `works.SELL_BONUS_SOURCES`).
- Events: `site_started` (public), `site_supplied`, `construct` (location), `site_work_lost` (private),
  `building_done` (public: who worked how many hours, who brought how much; for village buildings who did not take part).

## Roof and fire (tasks 3 and 11)

A villager has a roof when their plot has `house >= 1` or a `shelter` yard building
(`construction.has_roof(world, name)`). `plot.house = 0` means no house yet.

## Item ids

Today: `grain fish berries wood stone ore water bread fish_soup tool lock egg milk honey gold club spear stew
pancakes honey_cake ring`. Added by the plan: raw `clay meat hide hay`; materials `plank brick iron leather
flour`; tools `stone_axe stone_pick iron_axe iron_pick hoe fishing_rod` (`tool` stays as the generic iron
tool of today's modes); weapons `bow sword`; armor `leather_armor iron_armor`; food `smoked_meat`.

## Crafting (`aivillage/crafting.py`, task 7)

Config `crafting` (off = recipes and the generic `tool` as before). Workshop kinds and the trade their owner
takes: `workbench` carpenter, `smithy` smith, `kiln` potter, `mill` miller, `tannery` tanner, `smokehouse`,
`campfire` (no trade; "at home" recipes can also be made by a campfire). A recipe's `building` needs that
workshop where the crafter stands; `more_at` makes more there. Workshops are found by
`crafting.workshops_at(world, location) -> [{"kind", "owner", "level", "users"}]`: private yard buildings
(`Plot.buildings`, used by the owner's household), map locations whose id is a workshop kind (owner None,
everyone), finished buildings in `world.construction["buildings"]` (`{kind, level, location, owner}`, owner None =
everyone, else the owner's household), and `crafting.WORKSHOP_SOURCES` (`fn(world, location) -> list`) for buildings kept elsewhere.
`crafting.makes(cfg, kind)` lists what a workshop kind makes. Workshop recipes register
`recipe:<id>: {"building": kind}` in `progress.DEFAULT_UNLOCKS`. Log: `craft` events carry `recipe` and
`amount`; `tool_broke` carries `tool`; `trade_changed` with `profession` and `workshop` when an owner takes a trade.

## Log fields for the viewer (task 13b)

- `village_stage` events (above).
- Construction sites (task 3 defines them, fields fixed here): tick `view.sites` =
  `[{"id", "kind", "level", "location", "done": 0..1, "workers": [names]}]`; `workers` = who worked on it within
  the last `team_window_minutes`. Common buildings: tick `view.buildings` = `[{"id", "kind", "level", "location"}]`.
- Buildings with levels: plot building dicts carry `level` (default 1); works keep `works.levels`.
- Unexplored places (task 6): tick `view.known` = location ids someone has seen.
