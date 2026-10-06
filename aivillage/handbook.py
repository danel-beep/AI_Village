"""The villager's handbook: a neutral guide to everything a person can do in this world.

Built from the action registry every time, so an action another module registers shows up here by itself:
under its topic in `ACTION_TOPIC`, else its module's topic in `MODULE_TOPIC`, else under "Other".
Topic titles and the intro only name what exists; they never rank, recommend or judge an action
(tests/test_neutrality.py checks every text the model reads).

Also the cooking hint (config `craft_hint`, dossier item 9): `you.can_craft_now` (recipes the villager's own
inventory covers, how many times, where) and `you.not_edible` (raw goods held that only go into a recipe).
Both are computed facts from rules the model already has; switching the hint off is logged with the config.
"""

from __future__ import annotations

from . import crafting, progress
from .registry import ACTIONS

INTRO = ("Handbook of this world: everything a villager can do. Every villager has the same list, and so do you; "
         "nobody has a script, a goal or a side set for them. Some actions need a place, an item, a role or a moment: "
         "\"available_actions\" in each observation lists the ones possible right now.")

# Topic order is the order in the prompt. Titles are plain nouns, no judgement.
TOPICS = ["Body and time", "Gathering and making", "Trade and money", "Talk and news", "Home, chests and land",
          "People and family", "Village affairs", "Taking and force", "Outsiders and dangers", "Other"]

ACTION_TOPIC = {
    "move": "Body and time", "eat": "Body and time", "sleep": "Body and time", "wait": "Body and time",
    "work": "Gathering and making", "craft": "Gathering and making", "plant": "Gathering and making",
    "pick_up": "Gathering and making", "build": "Home, chests and land", "collect": "Gathering and making",
    "buy": "Trade and money", "sell": "Trade and money", "offer": "Trade and money", "accept": "Trade and money",
    "decline": "Trade and money", "give": "Trade and money", "lend": "Trade and money", "repay": "Trade and money",
    "post_order": "Trade and money", "fulfill_order": "Trade and money", "dice": "Trade and money",
    "say": "Talk and news", "whisper": "Talk and news", "letter": "Talk and news", "gossip": "Talk and news",
    "announce": "Talk and news",
    "store": "Home, chests and land", "take": "Home, chests and land", "share_chest": "Home, chests and land",
    "unshare_chest": "Home, chests and land", "install_lock": "Home, chests and land",
    "steal": "Taking and force", "steal_from_plot": "Taking and force", "attack": "Taking and force",
    "set_fire": "Taking and force",
    "contribute": "Village affairs", "extinguish": "Village affairs",
    "care": "People and family", "pay_respects": "People and family",
    "defend": "Outsiders and dangers", "help_stranger": "Outsiders and dangers",
    "chase_stranger": "Outsiders and dangers",
}

MODULE_TOPIC = {
    "plots": "Home, chests and land", "land": "Home, chests and land", "family": "People and family",
    "graves": "People and family", "luxury": "People and family", "governance": "Village affairs", "polity": "Village affairs", "works": "Village affairs",
    "reputation": "Talk and news", "conflict": "Taking and force", "threats": "Outsiders and dangers", "animals": "Gathering and making",
    "transport": "Body and time",
    "illness": "People and family", "dice": "Trade and money",
    "debts": "Trade and money", "market": "Trade and money", "taxes": "Village affairs", "places": "Gathering and making", "chronicle": "Talk and news", "honors": "Talk and news",
    "construction": "Home, chests and land", "settle": "Home, chests and land", "crafting": "Gathering and making", "hire": "Trade and money",
}


def topic(name: str) -> str:
    if name in ACTION_TOPIC:
        return ACTION_TOPIC[name]
    module = ACTIONS.specs[name].apply.__module__.rsplit(".", 1)[-1]
    return MODULE_TOPIC.get(module, "Other")


def text(disabled: frozenset[str] | set[str] = frozenset()) -> str:
    """The handbook for the system prompt: intro, then every enabled action under its topic."""
    groups: dict[str, list[str]] = {t: [] for t in TOPICS}
    for name, spec in ACTIONS.specs.items():
        if name not in disabled:
            groups.setdefault(topic(name), []).append(spec.prompt_line())
    parts = [INTRO]
    for t, lines in groups.items():
        if lines:
            parts.append(f"[{t}]\n" + "\n".join(lines))
    return "\n".join(parts)


def observe(world, name: str) -> dict:
    """`can_craft_now` / `not_edible` for the villager's `you` block; {} when the hint is off."""
    cfg = world.config
    if not cfg.get("craft_hint", True):
        return {}
    a = world.agents[name]
    inv = a.inventory
    can = {}
    for rid, r in cfg["recipes"].items():
        if r.get("profession") and r["profession"] != a.profession:
            continue
        if not progress.unlocked(world, f"recipe:{rid}"):
            continue
        if not crafting.may_make(world, a, rid):  # secret recipes: someone else knows it
            continue
        times = min((inv.get(k, 0) // n for k, n in r["inputs"].items() if n > 0), default=0)
        if times > 0:
            can[rid] = {"times": times, "where": "your home" if r["where"] == "home" else r["where"]}
    items = cfg["items"]
    raw = {}
    for item, qty in inv.items():
        if qty <= 0 or items.get(item, {}).get("food"):
            continue
        into = [rid for rid, r in cfg["recipes"].items() if item in r["inputs"] and items.get(rid, {}).get("food")]
        if into:
            raw[item] = "not food; an ingredient of " + ", ".join(into)
    out = {}
    if can:
        out["can_craft_now"] = can
    if raw:
        out["not_edible"] = raw
    return out
