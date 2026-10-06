"""Economy modes: named presets of world rules that push villagers toward peace or toward conflict.

The villagers' prompt is the same in every mode; only the numbers and rules of the world change
(and the rules cheat sheet in the prompt shows those numbers as facts). Pick one with `mode:` in a
run config, `--mode` on the command line, or the app's start screen.

A mode is a partial world config (merged over `config.DEFAULT_CONFIG`, under the run config's own
`world:` overrides) plus actions it switches off. The chosen mode is recorded in the log header as
`config.economy_mode`, so metrics can tell runs apart.
"""

from __future__ import annotations

from typing import Any

from .config import _merge


def _food(garden: int, fish: tuple[int, int], berries: tuple[int, int]) -> dict:
    """Grain per garden bed harvest (there is no common field) and (max, nightly regen) of the wild food;
    the stock starts full. Returns world overrides for "plots" and "locations"."""
    def r(mx: int, regen: int) -> dict:
        return {"start": mx, "max": mx, "regen": regen}
    return {
        "plots": {"buildings": {"garden_bed": {"yield": garden}}},
        "locations": {"river": {"resources": {"fish": r(*fish)}},
                      "forest": {"resources": {"berries": r(*berries)}}},
    }


MODES: dict[str, dict[str, Any]] = {
    "standard": {
        "title": "Обычный",
        "about": "Текущие правила без изменений, точка отсчёта для сравнения.",
        "world": {},
    },
    "peaceful": {
        "title": "Мирный",
        "about": "Грядки и природа дают больше еды, налог вдвое ниже, больше денег на старте; "
                 "кражу почти всегда замечают и она редко удаётся, драк и поджогов нет.",
        "world": {
            "map": {"unfairness": 0.1},  # start fairness of the generated village (mapgen.py)
            "start_coins": 40,
            "tax_amount": 10,
            **_food(garden=9, fish=(60, 16), berries=(30, 10)),
            "steal_notice_chance": 0.9,
            "steal_awake_target_success": 0.2,
            "max_steal_qty": 1,
            # rare, mild crises
            "crises": {"chance_per_day": 0.2, "gap_days": 3, "max_quiet_days": 8,
                       "kinds": {"rats": {"eat": 0.3}, "crop_failure": {"keep": 0.6, "garden_share": 0.25}}},
        },
        "disabled": ["attack", "set_fire"],
    },
    "scarcity": {
        "title": "Дефицит",
        "about": "Грядка даёт вдвое меньше зерна, рыбы и ягод мало, у торговца еда очень дорогая, "
                 "все начинают полуголодными.",
        "world": {
            "map": {"unfairness": 0.6},  # start fairness of the generated village (mapgen.py)
            "start_coins": 15,
            "satiety_start": 50,
            "npc_sell_ratio": 2.5,
            **_food(garden=3, fish=(15, 3), berries=(6, 2)),
            # food is already short: crises come often and hit food first
            "crises": {"chance_per_day": 0.6, "gap_days": 0, "max_quiet_days": 2,
                       "kinds": {"caravan": {"weight": 1}, "rats": {"weight": 3}}},
        },
    },
    "debt": {
        "title": "Долговая яма",
        "about": "Налог 12 монет каждые 2 дня (вдвое тяжелее обычного), мало денег на старте, за неуплату выгоняют "
                 "из дома на 3 дня. Без займов не выжить, а возврат никто не обеспечивает.",
        "world": {
            "map": {"unfairness": 0.6},  # start fairness of the generated village (mapgen.py)
            "start_coins": 10,
            "tax_every_days": 2,
            "tax_amount": 12,
            "eviction_days": 3,
            # money is the problem: price spikes and caravans matter more than lost food
            "crises": {"kinds": {"shortage": {"weight": 3}, "caravan": {"weight": 3}}},
        },
    },
    "gold_rush": {
        "title": "Золотая лихорадка",
        "about": "Каждый день на доске один огромный заказ на 150 монет, получает только первый. "
                 "Руда редкая и дорогая, в шахте вдвое больше золота, инструменты и замки делает только кузнец.",
        "world": {
            "map": {"unfairness": 0.7},  # start fairness of the generated village (mapgen.py)
            "start_coins": 10,
            "order_every_days": 1,
            "order_ttl_days": 2,
            "order_templates": [
                {"needs": {"tool": 1, "ore": 3}, "reward": 150},
                {"needs": {"lock": 1, "ore": 3}, "reward": 150},
            ],
            "items": {"ore": {"value": 10}},
            "locations": {"mine": {"resources": {"ore": {"start": 8, "max": 8, "regen": 3},
                                                 "gold": {"start": 48, "max": 48}}}},
            # caravans buy ore and tools dear
            "crises": {"kinds": {"caravan": {"weight": 4, "items": ["ore", "tool", "lock"]}}},
        },
    },
    "lawless": {
        "title": "Беззаконие",
        "about": "Кража удаётся почти всегда, свидетели замечают её редко, за раз можно унести "
                 "10 вещей, замков нет, жаловаться на воров некому.",
        "world": {
            "map": {"unfairness": 0.5},  # start fairness of the generated village (mapgen.py)
            "steal_notice_chance": 0.05,
            "steal_awake_target_success": 0.9,
            "max_steal_qty": 10,
            # want gives thieves a motive: frequent crises, rats hit most houses
            "crises": {"chance_per_day": 0.6, "gap_days": 0, "max_quiet_days": 2,
                       "kinds": {"rats": {"weight": 3, "share": 0.6}}},
        },
        "disabled": ["install_lock", "report_theft"],
    },
}

DEFAULT_MODE = "standard"


def check(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown economy mode '{mode}' (have: {', '.join(MODES)})")


def world_override(mode: str, world: dict | None = None) -> dict:
    """The mode's world settings with `world` (the run config's own overrides) on top."""
    check(mode)
    out = _merge(MODES[mode]["world"], world or {})
    out["economy_mode"] = mode
    return out


def unfairness(mode: str) -> float:
    """Start unfairness of the generated village in this mode (config default when the mode sets none)."""
    from .config import DEFAULT_CONFIG
    check(mode)
    return MODES[mode]["world"].get("map", {}).get("unfairness", DEFAULT_CONFIG["map"]["unfairness"])


def disabled(mode: str) -> list[str]:
    check(mode)
    return list(MODES[mode].get("disabled", []))
