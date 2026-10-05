"""Economy balance (backlog #4), measured with bots over a full year (4 seasons, winter included).

The same village plays twice: LonerBots trade only with the NPC market, TraderBots also trade
with each other at the middle of the NPC prices. Solo must be survivable for every profession;
trade must be clearly better for the village and leave no profession worse off.
If you change numbers in config.py and this fails, the economy got out of balance.
"""

from collections import Counter

import pytest

from aivillage import engine
from aivillage.run import bots_decider, run

SEEDS = range(3)


def wealth(world, agent) -> int:
    items = world.config["items"]
    chest = world.chests[f"chest_{agent.name}"]
    held = Counter(agent.inventory) + Counter(chest.items)
    return agent.coins + chest.coins + sum(items[k]["value"] * n for k, n in held.items())


def play(kind: str) -> tuple[dict, Counter, int]:
    """Mean wealth per profession after a year, failures (hospital/eviction), trades."""
    total, failures, trades = Counter(), Counter(), 0
    for seed in SEEDS:
        w = engine.new_world({"seed": seed})
        days = w.config["seasons"]["length_days"] * len(w.config["seasons"]["order"])
        stats = run(w, bots_decider(w, [kind], seed), days=days, check_every_tick=False)
        failures.update({k: stats.get(k, 0) for k in ("hospital", "evicted")})
        trades += stats.get("trade", 0)
        for a in w.agents.values():
            total[a.profession] += wealth(w, a)
    return {p: v / len(SEEDS) for p, v in total.items()}, failures, trades


@pytest.fixture(scope="module")
def results():
    return {kind: play(kind) for kind in ("loner", "trader")}


def test_solo_is_survivable(results):
    wealth_by_prof, failures, trades = results["loner"]
    assert trades == 0
    assert failures["hospital"] == 0 and failures["evicted"] == 0, failures
    assert all(v > 0 for v in wealth_by_prof.values()), wealth_by_prof


def test_trade_is_clearly_better(results):
    solo, _, _ = results["loner"]
    trade, failures, trades = results["trader"]
    assert trades >= 20 * len(SEEDS), trades
    assert failures["hospital"] == 0, failures
    assert sum(trade.values()) >= 1.2 * sum(solo.values()), (trade, solo)
    for prof in solo:  # nobody pays for the others' gains
        assert trade[prof] >= 0.9 * solo[prof], (prof, trade, solo)
