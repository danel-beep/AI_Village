"""Trader bots in the crafts mode («Обычный»): only the trade gathers its goods, so the bots feed each other
through the market board (food, firewood, ore for the smith, tools). Without it the bot village starved and
bot checks of this mode's economy said nothing (docs/runs/economy-audit.md)."""

from collections import Counter

from aivillage import engine, modes
from aivillage.run import bots_decider, replay, run


def test_crafts_bots_trade_food_and_stay_fed(tmp_path):
    w = engine.new_world(modes.world_override("crafts", {"seed": 1, "population": {"size": 10},
                                                         "map": {"procedural": True}, "tick_minutes": 15}))
    seen = Counter()
    log = tmp_path / "c.jsonl"
    stats = run(w, bots_decider(w, ["trader"], 1), 5, None, log,
                on_tick=lambda world, events: seen.update(e.kind for e in events))
    assert seen["sale"] >= 20 and seen["trade"] >= 20  # listings on the board and deals between villagers
    assert not stats.get("hospital") and all(a.status == "active" for a in w.agents.values())
    assert all(a.satiety > 0 for a in w.agents.values())
    assert replay(log).hash() == w.hash()
