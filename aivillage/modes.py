"""The world of «С нуля» and the presets on top of it.

«С нуля» is the one way the game is played (Danel 2026-10-08): the villagers build the village themselves, it climbs
stages (camp, hamlet, village, town; progress.py), nobody has a profession. The old economy modes (the ready
«Обычный» village, «Мирный», «Дефицит», «Долговая яма», «Золотая лихорадка», «Беззаконие») are gone.

A preset (`presets/<name>.yaml`) is «С нуля» plus start-screen knob values (`knobs:`, keys and values as in
aivillage/knobs.py, e.g. the start stage or «Еды в мире»), optional config the screen does not show (`world:`) and
actions switched off (`disabled:`). Pick one with `preset:` in a run config, `--preset` on the command line or the
«Пресет» list on the app's start screen. The villagers' prompt is the same under every preset; only the numbers and
rules of the world change. The log header carries the preset name as `config.preset` (and, from the start screen,
every knob's final value as `start_knobs`), so runs can be compared.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import _merge

# The ready-village economy «С нуля» is built on: professions and trade places, taxes, the trader's stock prices,
# council orders, the chronicle and the honor board. No longer a choice of its own; tests of those mechanics
# start from it, and «С нуля» switches professions off at every start stage (labor.mastery).
TRADES: dict[str, Any] = {
        # the trader sells at most one tool a day (per 5 villagers): tools come from the smith
        # one purse per trade at the trader: the miner's stone, ore and gold share 12 coins a day per 5
        # villagers (economy audit: three item limits made miners 4.5x richer); a laborer who lost a place
        # gathers berries and wood instead of starving
        "labor": {"enabled": True, "trader_sells_per_day": {"tool": 1}, "trader_coins_per_trade": 12,
                  "laborer_goods": ["berries", "wood"]},
        # a finished project's coins go to those who built it, by contribution (not 20 to everyone)
        "works": {"reward_split": "contribution"},
        # wild berries belong to the farmer's trade too: everyone else eats what neighbours grow and catch
        "professions": {"farmer": ["grain", "berries"]},
        # cooking needs firewood: grain is not edible raw, so bread needs a woodcutter too
        "recipes": {"bread": {"inputs": {"grain": 2, "wood": 1}}, "fish_soup": {"inputs": {"fish": 2, "wood": 1}}},
        # gold pays at most ~2x other work: cheaper, and the trader pays less the more he holds;
        # it has uses (a ring at the smithy, a level-3 house)
        "items": {"gold": {"value": 12}},
        "trader_pricing": {"stock_prices": True, "nearest": True},
        # food partly scarce (Danel, 2026-10-06: «частично дефицитная, как в жизни»): the economy audit found
        # 2.2-3.5x the food needed; a garden bed gives 4 grain (+2 for a farmer) instead of 6 (+3)
        "plots": {"house_upgrade": {"3": {"items": {"gold": 2}}},
                  "buildings": {"garden_bed": {"yield": 4, "profession_bonus": 2}}},
        # tools wear out in two to three days of work; everyone starts with one, then buys from the smith
        "start_items": {"tool": 1},
        "tool_durability_hours": 14,
        # tax by income and wealth instead of a flat 20 (taxes.py); council orders pay the goods
        # and take part deliveries
        "tax_amount": 10,
        "taxes": {"enabled": True},
        # council orders pay the goods' value (1.0x, was 1.6x: one order was worth 10-20 days of a fisher's sales)
        "council_orders": {"enabled": True, "reward_mult": 1.0},

        # limited places per trade: no work at your trade for 3 days frees your place (places.py)
        "places": {"enabled": True},
        # everyone's rough wealth is visible; a public chronicle every 7 days (chronicle.py)
        "chronicle": {"enabled": True},
        # a public honor board: notes of praise by villagers, titles by law (honors.py)
        "honors": {"enabled": True},
        # feasts and goods on view: things worth having beyond food (luxury.py, wants research idea 3)
        "luxury": {"enabled": True},
    }

# «С нуля»: the village is built by its villagers and climbs stages (progress.py). A start at hamlet or later
# is the ready village; a camp start empties it (bare_start below).
WORLD: dict[str, Any] = _merge(TRADES, {
    # bandits find the village from the hamlet stage, not only the town (villain run: 0 raids in 50 days)
    "progress": {"enabled": True, "unlocks": {"feature:raids": {"stage": "hamlet"}}},
    "bare_start": {"enabled": True},
    # danger at a random moment: 4 to 10 calm days between, never more in a row (Danel 2026-10-08), mostly
    # announced ahead; bandits also take what lies ready in the yard
    "threats": {"first_day": 4, "warn_chance": 0.8,
                "hostile": {"max_gap_days": 10, "min_gap_days": 4},
                # raids and beasts beaten only together (Danel 2026-10-08): on 6 villagers one defender never
                # wins, 3 with spear and leather ~85%, 3 bare-handed ~10%; stronger as the village arms itself
                "arms": {"enabled": True},
                "kinds": {"raid": {"yard_share": 0.5, "hall_share": 0.4, "hp": 200, "attack": 5, "damage_die": 10},
                          "beast": {"hp": 170, "attack": 5, "damage_die": 10}}},
    # the hospital is no free meal; others see who is wounded
    "hospital_discharge": {"satiety": 30},
    "wounded_seen_below": 40,
    # no professions at any start stage (Danel 2026-10-08): mastery per kind of work, a bigger house a better
    # household (labor.py)
    "labor": {"mastery": {"enabled": True}},
    "settle": {"enabled": True},
    # face-to-face talk: one after another at a place, an answer within the same quarter-hour, and being spoken to
    # pauses the job (talk.py; live A/B Luna+Haiku 3/3 2026-10-08: replies within a tick 6-17% -> 44%,
    # talks of 3+ lines 2-4% -> 14%)
    "talk": {"turn_taking": True, "interrupt_pause": True},
    # pace (progression audit R3, Danel 2026-10-06 «подгоняй настройки»): 2 units an hour by hand instead of 1;
    # builder bots reach the town on d10-12 instead of d14-18
    "work_base_yield": 2,
    # the camp lives off beds before any trade: they keep the old yield, so the pace of the climb stays where it
    # was tuned
    "plots": {"buildings": {"garden_bed": {"yield": 6, "profession_bonus": 3}}},
    "animals": {"enabled": True},
    # each town hall founds a polity (polity.py), so a second one may stand at any common place; treasury: a small
    # minted seed each dawn, and things to spend coins on (Danel 2026-10-08): wages, fund_project, the merchant
    "polity": {"enabled": True, "income_per_member_per_day": 1},
    "merchant": {"enabled": True},
    "illness": {"cure_items": ["honey", "milk", "fish_soup", "medicine"]},
    "construction": {"enabled": True, "catalog": {"town_hall": {"at": []}}},
    "transport": {"enabled": True},
    # something to steal and a chance not to be seen (theft.py), land goes to whoever comes first, no court
    # (land.py), winter nights cost more food (seasons.py)
    "theft": {"enabled": True},
    # "I owe you later" in kind: the hungry can borrow food against a promise (debts.py, plan item 5)
    "debts": {"in_kind": True},
    # a book of deeds instead of a reputation score: good deeds never erase bad ones; each night the villager
    # picks what to keep for long (reputation.py, llm.py; Danel 2026-10-08)
    "reputation": {"record": True},
    "land": {"claim": "first"},
    "seasons": {"night_hunger": {"winter": 10}},
    "hire": {"enabled": True},
    "explore": {"enabled": True},
    "crafting": {"enabled": True, "secrets": {"enabled": True}},
    # clay for bricks a short walk away on every map (the clay hills of a large map are far): a clay bank at the
    # mine; and wild grain in the forest: there is no field and no trader before the market square, so garden
    # beds need seed from somewhere
    "locations": {"mine": {"resources": {"clay": {"start": 20, "max": 20, "regen": 8, "slots": 3}}},
                  "forest": {"resources": {"grain": {"start": 12, "max": 12, "regen": 4, "slots": 3}}}},
})

DIR = Path(__file__).resolve().parent.parent / "presets"
DEFAULT_PRESET = "normal"


def _load() -> dict[str, dict[str, Any]]:
    """presets/*.yaml by name, in their `order`."""
    out = {}
    for p in DIR.glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        unknown = set(d) - {"title", "about", "order", "knobs", "world", "disabled"}
        if unknown or not d.get("title"):
            raise ValueError(f"presets/{p.name}: needs a title; unknown keys {sorted(unknown)}")
        out[p.stem] = {"title": d["title"], "about": d.get("about", ""), "order": d.get("order", 99),
                       "knobs": d.get("knobs") or {}, "world": d.get("world") or {}, "disabled": d.get("disabled") or []}
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["order"], kv[0])))


PRESETS: dict[str, dict[str, Any]] = _load()

# Rules every run starts with (under «С нуля» and the preset), while the bare engine default stays off so
# engine tests can leave villagers idle for days: one hospital stay, the second collapse is death.
RUN_DEFAULTS: dict[str, Any] = {"lives": 2}


def camp_start(cfg: dict) -> bool:
    """True when the run starts as an empty camp: bare_start on, progress on, start stage before `until_stage`."""
    from . import progress
    b = cfg.get("bare_start") or {}
    if not b.get("enabled") or not progress.enabled(cfg):
        return False
    ids = progress.stage_ids(cfg)
    start = cfg["progress"].get("start_stage", 0)
    idx = ids.index(start) if isinstance(start, str) else int(start)
    until = b.get("until_stage")
    return not (until in ids and idx >= ids.index(until))


def bare_start(cfg: dict) -> None:
    """Empty a full world config (in place) for a camp start: called by engine.new_world. Idempotent.

    Does nothing unless `bare_start.enabled`, progress is on and the start stage is before
    `bare_start.until_stage`. Then: houses at level 0, no coins, empty pockets and yards, everyone a
    laborer who may gather anything by hand (trade places open with the market square), no ready workshop at
    the map's Smithy. A start before `coins_from_stage` (the stage whose buildings bring the trader) has no
    coins either, even when it is the ready village."""
    from . import progress
    b = cfg.get("bare_start") or {}
    if not b.get("enabled") or b.get("applied") or not progress.enabled(cfg):
        return
    ids = progress.stage_ids(cfg)
    start = cfg["progress"].get("start_stage", 0)
    idx = ids.index(start) if isinstance(start, str) else int(start)
    coins_from = b.get("coins_from_stage")
    if coins_from in ids and idx < ids.index(coins_from):  # no market yet: nobody has coins
        cfg["start_coins"] = 0
        for st in cfg["map"].get("start", {}).values():
            st["coins"] = 0
    until = b.get("until_stage")
    if until in ids and idx >= ids.index(until):
        b["applied"] = True
        return
    cfg["start_coins"] = 0
    cfg["start_items"] = {k: 0 for k in cfg.get("start_items", {})}
    for st in cfg["map"].get("start", {}).values():  # mapgen's unfair start: yards stay, coins and stashes go
        st["coins"], st["items"] = 0, {}
    for a in cfg["agents"]:
        a.update(profession="laborer", house_level=0, buildings=[])
    cfg["labor"]["own_trade_only"] = False  # trade places stay: they open with the market square (places.py)
    # the map's Smithy is only a place name here: a forge is a smithy someone builds (else, once the first smithy
    # opens the smith's recipes, that place would serve everyone for free)
    cfg.setdefault("crafting", {})["map_workshops"] = False
    b["applied"] = True


# Food the world gives (start screen «Еды в мире», the «Суровый» preset): as tuned, or scarce.
FOOD_SUPPLY = ("normal", "scarce")
WILD_FOOD = ("fish", "berries", "grain")  # wild food at map places (grain: the forest's wild grain in «С нуля»)


def scarce_food(cfg: dict) -> dict:
    """World overrides that make the food of a full config `cfg` scarce: a garden bed gives half its grain, wild fish, berries and grain stand at half and regrow at 40%,
    the trader's food costs at least 2.5x what he pays, everyone starts at most half fed."""
    bed = cfg["plots"]["buildings"]["garden_bed"]
    locs: dict = {}
    for loc_id, loc in cfg["locations"].items():
        for res, r in (loc.get("resources") or {}).items():
            if res in WILD_FOOD:
                mx = max(1, r["max"] // 2)
                locs.setdefault(loc_id, {"resources": {}})["resources"][res] = {
                    "start": min(r.get("start", mx), mx), "max": mx, "regen": max(1, round(r["regen"] * 0.4))}
    return {"plots": {"buildings": {"garden_bed": {"yield": max(1, bed["yield"] // 2)}}},
            "locations": locs,
            "npc_sell_ratio": max(cfg["npc_sell_ratio"], 2.5),
            "satiety_start": min(cfg["satiety_start"], 50),
            "food_supply": "scarce"}


# Titles of the removed economy modes, so the past-villages list can still name an old log's rules.
OLD_MODES = {"survival": "С нуля", "crafts": "Обычный (старый)", "standard": "Свободный", "peaceful": "Мирный",
             "scarcity": "Дефицит", "debt": "Долговая яма", "gold_rush": "Золотая лихорадка", "lawless": "Беззаконие"}


def title(cfg: dict) -> str:
    """What a log's config was played under: the preset's title, or an old log's economy mode."""
    if cfg.get("preset") in PRESETS:
        return PRESETS[cfg["preset"]]["title"]
    mode = cfg.get("economy_mode") or "crafts"  # logs from before the survival default
    return OLD_MODES.get(mode, mode)


def check(preset: str) -> None:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}' (have: {', '.join(PRESETS)})")


def base_override(world: dict | None = None) -> dict:
    """«С нуля» with no preset, `world` (the run config's own overrides) on top."""
    return _merge(_merge(RUN_DEFAULTS, WORLD), world or {})


def trades_override(world: dict | None = None) -> dict:
    """The ready village of TRADES with no stages, professions on (tests of professions, trade places, taxes and
    the trader's stock prices), `world` on top. Not a way to play."""
    return _merge(_merge(RUN_DEFAULTS, TRADES), world or {})


def world_override(preset: str = DEFAULT_PRESET, world: dict | None = None) -> dict:
    """«С нуля» with the preset's settings (its knob values turned into config, its actions off as
    `disabled_actions`) and `world` (the run config's own overrides) on top."""
    from . import knobs
    check(preset)
    out = _merge(knobs.preset_override(preset), world or {})
    out["preset"] = preset
    return out


def disabled(preset: str) -> list[str]:
    """Actions the preset switches off (its `disabled:` and its action knobs set off)."""
    from . import knobs
    check(preset)
    return list(knobs.preset_override(preset).get("disabled_actions", []))
