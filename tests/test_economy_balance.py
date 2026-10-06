"""Economy audit balance fixes: one trader purse per trade, project rewards by contribution, a smith keeps the
place while buying ore, a laborer may gather berries and wood (crafts mode)."""

from aivillage import engine, labor, ops, works
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.modes import world_override


def crafts_world(**extra):
    return engine.new_world({**world_override("crafts"), "seed": 1, "crises": {"enabled": False}, **extra})


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def give(w, name, **items):
    for k, v in items.items():
        ops.mint(w, w.agents[name].inventory, k, v)


def test_miner_goods_share_one_purse():
    w = crafts_world()
    a = next(x for x in w.agents.values() if x.profession == "miner")
    a.location = "market"
    give(w, a.name, ore=20, stone=20)
    purse = labor.coins_left(w, "miner")
    assert purse >= 12
    coins = a.coins
    for item in ("ore", "stone"):
        left = engine.observe(w, a.name, consume_inbox=False)["trader_today"]["will_buy"][item]
        if left:
            assert not errors(act(w, a.name, "sell", item=item, qty=left))
    earned = a.coins - coins
    assert 0 < earned <= purse and labor.coins_left(w, "miner") == purse - earned
    assert engine.observe(w, a.name, consume_inbox=False)["trader_today"]["will_buy"]["stone"] == 0
    msg = errors(act(w, a.name, "sell", item="stone", qty=1))[0]
    assert "miner goods (stone, ore, gold)" in msg
    # a fisher's purse was never touched
    assert labor.coins_left(w, "fisher") == purse
    assert "one purse" in world_facts(w.config)


def test_no_purse_outside_the_crafts_mode():
    w = engine.new_world({"seed": 1})
    assert labor.coins_left(w, "miner") is None


def project_world(split):
    return engine.new_world({"seed": 1, "works": {"reward_split": split},
                             "projects": {"bridge": {"name": "Bridge", "needs": {"wood": 3}, "reward_coins_each": 10,
                                                     "structure": "bridge"}}})


def build_bridge(w):
    for n in ("Anna", "Boris"):
        w.agents[n].location = "square"
    give(w, "Anna", wood=2, stone=20)  # the default bridge also needs 30 stone
    give(w, "Boris", wood=1, stone=10)
    before = {n: a.coins for n, a in w.agents.items()}
    act(w, "Anna", "contribute", project_id="bridge", items={"wood": 2, "stone": 20})
    ev = act(w, "Boris", "contribute", project_id="bridge", items={"wood": 1, "stone": 10})
    done = next(e for e in ev if e.kind == "project_done")
    return done, {n: a.coins - before[n] for n, a in w.agents.items()}


def test_project_reward_shared_by_contribution():
    w = project_world("contribution")
    assert engine.observe(w, "Clara")["board"]["projects"][0]["reward_when_done"].startswith("50 coins")
    done, got = build_bridge(w)
    assert got["Anna"] == 33 and got["Boris"] == 17 and all(got[n] == 0 for n in got if n not in ("Anna", "Boris"))
    assert "shared by contribution: Anna 33, Boris 17" in done.text


def test_project_reward_to_everyone_by_default():
    w = project_world("everyone")
    assert "reward_when_done" not in engine.observe(w, "Clara")["board"]["projects"][0]
    done, got = build_bridge(w)
    assert set(got.values()) == {10} and "Every villager receives 10 coins" in done.text


def test_smith_buying_ore_counts_as_work_at_the_trade():
    w = crafts_world()
    smith = next(x for x in w.agents.values() if x.profession == "smith")
    smith.location, smith.trade_day = "market", 0
    ops.mint_coins(w, smith, 50)
    act(w, smith.name, "buy", item="ore", qty=1)
    assert smith.trade_day == w.day
    other = next(x for x in w.agents.values() if x.profession == "fisher")
    other.location, other.trade_day = "market", 0
    ops.mint_coins(w, other, 50)
    act(w, other.name, "buy", item="ore", qty=1)
    assert other.trade_day == 0  # ore is no input of a fisher's recipes


def test_laborer_gathers_berries_and_wood_in_crafts():
    w = crafts_world()
    a = next(x for x in w.agents.values() if x.profession == "fisher")
    a.profession = "laborer"
    assert labor.may_gather(w.config, a, "berries") is None and labor.may_gather(w.config, a, "wood") is None
    assert labor.may_gather(w.config, a, "fish") and labor.may_gather(w.config, a, "ore")
    assert "berries, wood and village work" in world_facts(w.config)
