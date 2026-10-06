"""World configuration: everything tunable lives here, nothing is hardcoded in the engine.

A run is fully defined by (config, seed, decisions), which is what makes replay possible.
Override any key by passing a partial dict to `make_config`.
"""

from __future__ import annotations

import copy
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "seed": 1,
    # Time: one tick = tick_minutes game minutes (clock.py). Agents act from day_start to day_end, then
    # night runs. 60 is the old hourly mode the engine tests use; the CLI, live server and launcher run 15.
    "day_start_hour": 6,
    "day_end_hour": 22,
    "tick_minutes": 60,
    # How long an action keeps a villager busy (game minutes, rounded up to whole ticks; not listed = 60).
    # Talking, trading, eating and other quick deeds take a quarter hour; work, craft, a walk between two
    # places, planting, building, hanging out and stealing (thieves keep the old hourly pace) take an hour.
    # Busy villagers are not asked (no model call).
    "action_minutes": {
        **{a: 15 for a in (
            "say", "whisper", "letter", "give", "lend", "repay", "offer", "accept", "decline", "eat",
            "store", "take", "share_chest", "unshare_chest", "install_lock", "pick_up",
            "contribute", "fulfill_order", "buy", "sell", "extinguish", "collect",
            "expand_plot", "propose", "answer_proposal", "divorce", "run_for_mayor", "vote",
            "propose_law", "vote_law", "report_theft", "gossip", "buy_land", "sell_land", "attack", "set_fire")},
        "error": 15,  # a failed action only costs a quarter hour
    },
    # Survival
    "satiety_max": 100,
    "satiety_start": 80,
    "satiety_loss_per_hour": 2,  # ~1 meal a day: fewer eat turns, more time for people
    "satiety_loss_asleep_per_hour": 2,
    "satiety_loss_night": 10,
    "starving_health_loss_per_hour": 5,
    "starving_health_loss_night": 20,
    "health_max": 100,
    "health_regen_night_at_home": 15,
    "health_regen_min_satiety": 30,
    # What happens at health 0: "hospital" (lose half the inventory, back in N days) or "death".
    "death_mode": "hospital",
    "hospital_days": 2,
    # Economy
    "start_coins": 20,
    "tax_every_days": 7,
    "tax_amount": 20,
    "eviction_days": 2,
    "work_base_yield": 1,
    "work_profession_multiplier": 3,
    "work_tool_multiplier": 2,
    "tool_durability_hours": 40,
    "max_work_hours": 4,
    "offer_ttl_ticks": 3,
    "steal_notice_chance": 0.5,
    "steal_awake_target_success": 0.5,
    "max_steal_qty": 3,
    "max_text_len": 200,
    "inbox_size": 30,
    "order_every_days": 3,
    "order_ttl_days": 3,
    "orders_per_post": 1,  # orders posted at once; scaled with the population (coins for tax)
    # Fire: burns fire_ticks hours, then the house and chest are lost. Every fire_grow_hours it needs
    # one more bucket (up to fire_water_max). Night counts as fire_night_hours of burning.
    "fire_ticks": 10,
    "fire_water_needed": 3,
    "fire_grow_hours": 2,
    "fire_water_max": 8,
    "fire_night_hours": 4,
    # Items. value = base price; NPC buys at value*npc_buy_ratio, sells at value*npc_sell_ratio.
    "npc_buy_ratio": 0.5,
    "npc_sell_ratio": 1.5,
    "items": {
        "grain": {"value": 2},
        "fish": {"value": 3, "food": 15},
        "berries": {"value": 1, "food": 10},
        "wood": {"value": 2},
        "stone": {"value": 2},
        "ore": {"value": 5},
        "water": {"value": 0, "tradable": False},
        "bread": {"value": 6, "food": 40},
        "fish_soup": {"value": 7, "food": 45},
        "tool": {"value": 20},
        "lock": {"value": 15},
        # made on private plots (aivillage/plots.py)
        "egg": {"value": 2, "food": 10},
        "milk": {"value": 4, "food": 20},
        "honey": {"value": 6, "food": 25},
        # the shared mine's prize (aivillage/land.py, config locations.mine): finite, only sold for coins
        "gold": {"value": 20},
        # weapons for fights (aivillage/conflict.py, config combat.weapons); a tool works as a shovel/pick
        "club": {"value": 4},
        "spear": {"value": 15},
    },
    # Recipes: where they can be made and by whom (None = anyone).
    "recipes": {
        "bread": {"inputs": {"grain": 2}, "output": 1, "where": "home", "profession": None},
        "fish_soup": {"inputs": {"fish": 2}, "output": 1, "where": "home", "profession": None},
        "tool": {"inputs": {"wood": 2, "ore": 1}, "output": 1, "where": "smithy", "profession": "smith"},
        "lock": {"inputs": {"ore": 1, "stone": 1}, "output": 1, "where": "smithy", "profession": "smith"},
        "club": {"inputs": {"wood": 3}, "output": 1, "where": "home", "profession": None},
        "spear": {"inputs": {"wood": 2, "ore": 1}, "output": 1, "where": "smithy", "profession": "smith"},
    },
    "professions": {
        "farmer": ["grain"],
        "fisher": ["fish"],
        "woodcutter": ["wood"],
        "miner": ["stone", "ore", "gold"],
        "smith": [],
    },
    # Procedural map (mapgen.py): with procedural on, every seed lays out its own village from the
    # locations below (positions, roads, waypoints, homes with plots, resource amounts, start money);
    # `unfairness` 0..1 goes from as equal as possible to random and unfair (see mapgen.MAP_DEFAULTS).
    # Off here (the engine and its tests use the hand-made map below); the CLI and the live server
    # turn it on unless --fixed-map.
    "map": {"procedural": False, "unfairness": 0.3},
    # Map: a graph of locations. Homes are added per agent and connected to the square.
    # "slots" splits a resource into finite map objects (trees, beds, bushes, shoals, rocks; see tiles.py).
    # "plant": the resource can be sown in an empty bed (costs `seed` of it, ripe after `days` nights).
    # "per_hour": at most this many units per work hour, whatever the multipliers (gold).
    # "patch": False keeps a resource out of mapgen's copies (the old quarry has no gold).
    # "lot": an empty piece of land for sale (aivillage/land.py): cells to build on and its price.
    # There is no common field: grain grows only in garden beds on private plots (plots.py).
    "locations": {
        "square": {"name": "Village square", "neighbors": ["market", "forest", "river", "smithy", "lot_1"]},
        "market": {"name": "Market", "neighbors": ["square"]},
        "river": {"name": "River", "neighbors": ["square", "lot_2"],
                  "resources": {"fish": {"start": 30, "max": 30, "regen": 8, "slots": 6},
                                "water": {"start": 999, "max": 999, "regen": 999}}},
        "forest": {"name": "Forest", "neighbors": ["square", "mine", "lot_3"],
                   "resources": {"wood": {"start": 80, "max": 80, "regen": 40, "slots": 8},
                                 "berries": {"start": 15, "max": 15, "regen": 5, "slots": 5}}},
        # The one shared mine: stone, ore, and a finite stock of gold that never comes back once dug out.
        "mine": {"name": "Mine", "neighbors": ["forest"],
                 "resources": {"stone": {"start": 60, "max": 60, "regen": 30, "slots": 6},
                               "ore": {"start": 30, "max": 30, "regen": 10, "slots": 6},
                               "gold": {"start": 24, "max": 24, "regen": 0, "slots": 4, "per_hour": 2,
                                        "patch": False}}},
        "smithy": {"name": "Smithy", "neighbors": ["square"]},
        "lot_1": {"name": "Lot by the square", "neighbors": ["square"], "lot": {"cells": 6, "price": 54}},
        "lot_2": {"name": "Lot by the river", "neighbors": ["river"], "lot": {"cells": 8, "price": 56}},
        "lot_3": {"name": "Lot at the forest edge", "neighbors": ["forest"], "lot": {"cells": 10, "price": 60}},
    },
    "projects": {
        "bridge": {"name": "Bridge over the river", "needs": {"wood": 40, "stone": 30},
                   "reward_coins_each": 20},
    },
    # Order templates the NPC council posts on the board; one is picked at random.
    "order_templates": [
        {"needs": {"bread": 3, "fish_soup": 2}, "reward": 80},
        {"needs": {"tool": 2, "wood": 5}, "reward": 90},
        {"needs": {"lock": 1, "stone": 10, "fish": 5}, "reward": 85},
    ],
    # Seasons (backlog #10): a season scales nightly resource regrowth. Day 1 is the first day of
    # order[0]. "wither" empties resources at the first dawn of a season (field crops die in winter).
    "seasons": {
        "enabled": True,
        "length_days": 7,
        "order": ["spring", "summer", "autumn", "winter"],
        "regen_multiplier": {
            "summer": {"berries": 1.5},
            "autumn": {"grain": 1.5},
            "winter": {"grain": 0, "berries": 0, "fish": 0.5},
        },
        "wither": {},  # {season: {location: [resources]}} emptied at the season's first dawn
        "announce": {
            "spring": "Gardens can be sown again.",
            "winter": "The ground is frozen: garden beds cannot be sown until spring, berries are gone, "
                      "fish are scarce.",
        },
    },
    # Soft world crises (aivillage/crises.py): at dawn, from `first_day`, with `chance_per_day`, a crisis of a
    # kind picked by `weight` starts and lasts `days` [min, max]; at most `max_active` at once, `gap_days` quiet
    # days after one ends, never more than `max_quiet_days` calm days in a row. They hit villagers unevenly
    # (some yards, some chests), so the lucky have food to trade and the unlucky have reasons to ask, borrow
    # or steal. Economy modes tune these numbers.
    "crises": {
        "enabled": True,
        "first_day": 2,
        "chance_per_day": 0.5,
        "max_active": 1,
        "gap_days": 1,
        "max_quiet_days": 4,
        "kinds": {
            # Common crops fail: `resources` keep `keep` of what is left and do not regrow; sown beds on
            # common land die, and so do sown garden beds in `garden_share` of the yards.
            "crop_failure": {"weight": 3, "days": [2, 3], "resources": ["grain"], "keep": 0.3,
                             "garden_share": 0.5},
            # Drought: river and bushes dry up (same rules as crop_failure, no gardens).
            "drought": {"weight": 2, "days": [2, 3], "resources": ["fish", "berries"], "keep": 0.4},
            # Rats get into `share` of the houses at once and eat `eat` of the food in each chest.
            "rats": {"weight": 2, "days": [1, 1], "share": 0.5, "eat": 0.6,
                     "items": ["grain", "fish", "berries", "bread", "fish_soup", "egg", "milk", "honey"]},
            # The trader runs short of one food: buying it from him costs `buy` times more.
            "shortage": {"weight": 2, "days": [2, 3], "items": ["grain", "fish", "bread", "fish_soup"],
                         "buy": 3.0},
            # A caravan merchant at the market pays `sell` times more for one good while he stays.
            "caravan": {"weight": 2, "days": [2, 2], "items": ["wood", "stone", "ore", "tool", "fish"],
                        "sell": 2.5},
        },
    },
    # Population (aivillage/population.py): size N > len(agents) adds generated villagers (seeded names,
    # professions by weight); resources and project needs scale by max(1, N / base_size). None = just `agents`.
    "population": {
        "size": None,
        "base_size": 5,  # the map numbers above are tuned for this many villagers
        "scale_resources": True,
        "scale_projects": True,
        "scale_orders": True,  # more council orders at once: they are the main coin source besides the trader
        "profession_weights": {"farmer": 1.2, "fisher": 1.2, "woodcutter": 1, "miner": 1, "smith": 0.6},
    },
    # Mayor, treasury and laws (aivillage/governance.py). When enabled, the weekly tax goes to the
    # village treasury instead of vanishing; the mayor proposes laws and villagers vote on them.
    "governance": {
        "enabled": True,
        "first_election_day": 2,
        "election_every_days": 5,
        "law_vote_hours": 12,  # a proposal stays open this many waking hours
        "max_open_proposals": 2,
        "exile_days": 3,
        # Actions an exiled villager may not use.
        "exile_bans": ["buy", "sell", "fulfill_order", "vote", "run_for_mayor", "vote_law"],
        # Allowed values for laws that set a number; laws start at "start" (tax: tax_amount).
        "limits": {"tax": [0, 60], "theft_fine": [0, 50], "mayor_salary": [0, 20], "grant": [1, 200]},
        "start": {"theft_fine": 0, "mayor_salary": 0},
        "crime_memory_days": 7,  # a witnessed theft can be reported for this many days
    },
    # Friendship, marriage and inheritance (aivillage/family.py). Feelings are directed scores
    # (what A feels about B), clamped to [-max, max]; events listed in "on_event" move them.
    "family": {
        "feeling_max": 100,
        "friend_at": 30,      # label "friend" at or above, "enemy" at or below -friend_at
        "decay_per_night": 1,  # every feeling drifts 1 point toward 0 each night
        "hang_out_gain": 4,    # both sides, once per pair per day
        "propose_min": 25,     # proposer's and accepter's own feeling needed
        "proposal_ttl_days": 2,
        "wedding_cost": 0,     # coins the proposer pays (burned) when the proposal is accepted
        "wedding_boost": 20,   # both feelings raised to at least propose_min + this
        "spouse_night_gain": 1,
        "divorce_hurt": 40,    # the left spouse's feeling drops by this
        "estate_statuses": ["dead", "exiled", "banished"],  # property passes on in these states
        # event kind -> [who, delta]: "to" = addressees about the actor, "both" = both ways,
        # "lender" = the debt's lender, "owner" = who lives in the house where it happened
        "on_event": {
            "give": ["to", 5], "lend": ["to", 4], "repay": ["lender", 4], "trade": ["both", 2],
            "whisper": ["both", 1], "letter": ["to", 1], "decline": ["to", -1],
            "steal_attempt": ["to", -20], "witness": ["to", -10], "default": ["lender", -15],
            "fire_out": ["owner", 10], "extinguish": ["owner", 4],
        },
    },
    # Reputation and rumors (aivillage/reputation.py). Each agent keeps its own tally of deeds it saw or
    # lived through; "deltas" maps event kinds to score changes. Rumors (gossip) never change scores.
    "reputation": {
        "enabled": True,
        "score_cap": 10,
        "notes_per_person": 3,
        "rumors_kept": 6,
        "deltas": {
            "witness": -3,        # saw someone steal
            "steal_attempt": -4,  # caught someone stealing from you
            "default": -3,        # debt not repaid on time (public)
            "repay": 2,           # debt fully repaid on time (public)
            "fire_out": 3,        # put out a fire (public)
            "extinguish": 1,      # helped with a fire (seen there)
            "give": 1,
            "lend": 1,
            "trade": 1,           # completed a trade with you
            "contribute": 1,      # gave to a village project (public)
        },
    },
    # Private plots (aivillage/plots.py): each house has a yard of `cells` where its family builds.
    # An agent spec may set its own start: "plot_cells", "house_level", "buildings" (a list of kinds, free);
    # mapgen.py (generated map) fills them from the fenced yard and the unfairness knob unless set.
    # Building costs: "coins" (to the treasury) + "items" (from the inventory). Animals eat "feed" of
    # "feed_item" from the owner's chest each night, else make nothing; stock stops at "cap".
    "plots": {
        "enabled": True,
        "start_cells": 6,
        # Free buildings at start when the agent spec has no "buildings" (as many as fit the yard);
        # garden beds start sown and are ripe on day 2. Others build their own beds (1 wood each).
        "start_buildings": {"farmer": ["garden_bed", "garden_bed", "garden_bed"], "default": []},
        "max_cells": 24,          # expand_plot stops here (house upgrades still add cells)
        "expand_cells": 2,
        "expand_price": 25,       # first purchase; each next one costs expand_price_step more
        "expand_price_step": 15,
        "house_max": 3,
        "house_upgrade": {"2": {"coins": 60, "items": {"wood": 8, "stone": 6}},
                          "3": {"coins": 150, "items": {"wood": 12, "stone": 12}}},
        "house_bonus_cells": 2,   # per upgrade
        "house_bonus_health": 5,  # extra night health at home per level above 1
        "steal_max": 4,           # units per steal_from_plot
        "fence_success": 0.5,     # a fence multiplies a thief's chance by this
        "buildings": {
            "garden_bed": {"cells": 1, "coins": 0, "items": {"wood": 1},
                           "crop": "grain", "seed": 1, "yield": 6, "days": 2,
                           "profession_bonus": 3,  # extra yield when sown by a farmer (professions: grain)
                           "tool_bonus": 2},  # and when the sower carries a tool (a hoe)
            "chicken_coop": {"cells": 2, "coins": 15, "items": {"wood": 4},
                             "makes": "egg", "per_day": 3, "cap": 9, "feed": 1, "feed_item": "grain"},
            "cow_pen": {"cells": 4, "coins": 40, "items": {"wood": 6, "stone": 2},
                        "makes": "milk", "per_day": 3, "cap": 9, "feed": 2, "feed_item": "grain"},
            "beehive": {"cells": 1, "coins": 10, "items": {"wood": 2},
                        "makes": "honey", "per_day": 1, "every_days": 2, "cap": 4, "idle_seasons": ["winter"]},
            "fence": {"cells": 0, "coins": 0, "items": {"wood": 6}, "max": 1},
        },
    },
    # Land for sale (aivillage/land.py): locations with a "lot" spec are empty plots anyone can buy
    # (coins to the treasury) and then build on like a yard; owners can sell them on to each other.
    # On a generated map mapgen.py lays out `lots` of them (None = about one per two villagers),
    # `price_per_cell` coins per cell, nearer the square a bit dearer.
    "land": {
        "enabled": True,
        "lots": None,
        "cells": [6, 8, 10],
        "price_per_cell": 7,
        "sale_ttl_hours": 6,  # how long a sell_land offer stays open
    },
    # Fights and arson (aivillage/conflict.py). attack: a few D&D-like rounds of automatic dice rolls:
    # each round the attacker, then the defender swings: d`die` + weapon attack >= `hit_at` hits for
    # d`damage_die` + weapon damage. Whoever dealt more damage wins (a tie: the defender holds); a winning
    # attacker takes up to `loot_max` of what they asked for from the loser. A fighter at or below
    # `give_up_health` stops. The best weapon carried is used automatically.
    "combat": {
        "enabled": True,
        "rounds": 3,
        "die": 20,
        "hit_at": 10,
        "damage_die": 8,
        "give_up_health": 15,
        "min_health": 20,         # too weak to start a fight below this
        "loot_max": 3,
        "loot_coins_max": 10,
        "weapons": {"tool": {"attack": 1, "damage": 2}, "club": {"attack": 0, "damage": 3},
                    "spear": {"attack": 2, "damage": 5}},
        # feelings (family.py) and reputation (reputation.py) toward the attacker / arsonist
        "feelings": {"victim": -30, "witness": -10},
        "reputation": {"victim": -5, "witness": -3},
        # set_fire: costs `arson_wood` wood; the family at home awake always sees who did it,
        # bystanders with steal_notice_chance.
        "arson_wood": 1,
    },
    # Random fires (engine night): each dawn a random house catches fire with this chance
    # (0 = only the god or an arsonist starts fires). Shown as a setting in the app.
    "random_fires": {"per_day": 0.0},
    "agents": [
        {"name": "Anna", "profession": "farmer"},
        {"name": "Boris", "profession": "fisher"},
        {"name": "Clara", "profession": "woodcutter"},
        {"name": "Dmitri", "profession": "miner"},
        {"name": "Elena", "profession": "smith"},
    ],
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def make_config(override: dict | None = None) -> dict:
    from .population import resolve
    return resolve(_merge(DEFAULT_CONFIG, override or {}))
