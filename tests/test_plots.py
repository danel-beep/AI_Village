"""Private plots: building, animals and feed, garden beds, land and house purchases, yard theft."""

from aivillage import engine, plots
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run


def world(**over):
    agents = over.pop("agents", [{"name": "Anna", "profession": "farmer"},
                                 {"name": "Boris", "profession": "fisher"}])
    return engine.new_world({"agents": agents, **over})


def act(w, name, action, args=None):
    w.agents[name].last_error = None
    events = engine.step(w, {name: {"thought": "", "action": {"name": action, "args": args or {}}}})
    check(w)
    return w.agents[name].last_error, events


def night(w):
    engine.step(w, {})
    while w.hour != w.config["day_start_hour"]:
        engine.step(w, {})
    check(w)


def test_start_plot_from_spec():
    w = world(agents=[{"name": "Anna", "profession": "farmer", "plot_cells": 12, "house_level": 2,
                       "buildings": ["chicken_coop"]},
                      {"name": "Boris", "profession": "fisher"}])
    a, b = w.plots["home_Anna"], w.plots["home_Boris"]
    assert (a.cells, a.house, [x["kind"] for x in a.buildings]) == (12, 2, ["chicken_coop"])
    assert (b.cells, b.house, b.buildings) == (6, 1, [])
    obs = engine.observe(w, "Boris")
    assert obs["plot"]["free_cells"] == 6
    assert obs["village_plots"]["Anna"] == {"cells": 12, "house": 2, "buildings": 1}


def test_build_costs_and_cells():
    w = world()
    a = w.agents["Anna"]
    err, _ = act(w, "Anna", "build", {"kind": "chicken_coop"})
    assert "missing" in err
    a.inventory["wood"] = 20
    w.ledger["wood"] = 20
    treasury = w.governance.coins
    err, _ = act(w, "Anna", "build", {"kind": "chicken_coop"})
    assert err is None
    assert a.coins == 5 and a.inventory["wood"] == 16 and w.governance.coins == treasury + 15
    err, _ = act(w, "Anna", "build", {"kind": "cow_pen"})
    assert "35 more coins, 2 stone" in err
    a.coins += 100
    w.ledger["coins"] += 100
    assert act(w, "Anna", "build", {"kind": "chicken_coop"})[0] is None
    assert act(w, "Anna", "build", {"kind": "chicken_coop"})[0] is None  # 6 of 6 cells used
    assert "free cells" in act(w, "Anna", "build", {"kind": "garden_bed"})[0]
    assert act(w, "Anna", "build", {"kind": "fence"})[0] is None  # a fence takes no cells
    assert "max 1" in act(w, "Anna", "build", {"kind": "fence"})[0]
    err, _ = act(w, "Anna", "build", {"kind": "castle"})
    assert "unknown building" in err
    act(w, "Anna", "move", {"to": "square"})
    err, _ = act(w, "Anna", "build", {"kind": "garden_bed"})
    assert "own home" in err


def test_animals_eat_from_chest_and_produce():
    w = world(agents=[{"name": "Anna", "profession": "farmer", "buildings": ["chicken_coop"]}])
    night(w)
    assert plots.stock(w.plots["home_Anna"]) == {}  # no grain in the chest: hungry
    w.chests["chest_Anna"].items["grain"] = 2
    w.ledger["grain"] = w.ledger.get("grain", 0) + 2
    night(w)
    assert plots.stock(w.plots["home_Anna"]) == {"egg": 3}
    assert w.chests["chest_Anna"].items == {"grain": 1}
    err, _ = act(w, "Anna", "collect")
    assert err is None and w.agents["Anna"].inventory["egg"] == 3
    err, _ = act(w, "Anna", "collect")
    assert "nothing" in err


def test_garden_bed_is_private():
    w = world(agents=[{"name": "Anna", "profession": "farmer", "buildings": ["garden_bed"]}])
    a = w.agents["Anna"]
    a.inventory["grain"] = 1
    w.ledger["grain"] = 1
    err, _ = act(w, "Anna", "plant")
    assert err is None and "grain" not in a.inventory
    err, _ = act(w, "Anna", "plant")
    assert "sown or ripe" in err
    night(w)
    night(w)
    assert plots.stock(w.plots["home_Anna"]) == {"grain": 6}
    obs = engine.observe(w, "Anna")
    assert "collect" in obs["available_actions"]


def test_expand_and_upgrade():
    w = world()
    a = w.agents["Anna"]
    a.coins += 300
    w.ledger["coins"] += 300
    a.inventory.update({"wood": 8, "stone": 6})
    w.ledger.update({"wood": 8, "stone": 6})
    assert act(w, "Anna", "expand_plot")[0] is None
    assert act(w, "Anna", "expand_plot")[0] is None
    p = w.plots["home_Anna"]
    assert p.cells == 10 and a.coins == 320 - 25 - 40
    assert act(w, "Anna", "upgrade_house")[0] is None
    assert p.house == 2 and p.cells == 12 and a.inventory == {}
    assert "missing" in act(w, "Anna", "upgrade_house")[0]
    assert plots.health_bonus(w, a) == 5


def test_steal_from_plot_with_family_away():
    w = world(agents=[{"name": "Anna", "profession": "farmer", "buildings": ["beehive"]},
                      {"name": "Boris", "profession": "fisher"}])
    p = w.plots["home_Anna"]
    p.buildings[0]["items"]["honey"] = 3
    w.ledger["honey"] = 3
    act(w, "Anna", "move", {"to": "square"})
    w.agents["Boris"].location = "home_Anna"
    obs = engine.observe(w, "Boris")
    assert obs["here_plot"]["ready"] == {"honey": 3} and "steal_from_plot" in obs["available_actions"]
    err, events = act(w, "Boris", "steal_from_plot", {"item": "honey", "qty": 5})
    assert err is None
    assert w.agents["Boris"].inventory["honey"] == 3 and plots.stock(p) == {}
    assert any(e.kind == "robbed" and e.to == ["Anna"] for e in events)


def test_family_at_home_notices_thief():
    w = world(agents=[{"name": "Anna", "profession": "farmer", "buildings": ["beehive", "fence"]},
                      {"name": "Boris", "profession": "fisher"}])
    w.plots["home_Anna"].buildings[0]["items"]["honey"] = 4
    w.ledger["honey"] = 4
    w.agents["Boris"].location = "home_Anna"
    err, events = act(w, "Boris", "steal_from_plot", {"item": "honey"})
    assert err is None
    assert any(e.kind == "steal_attempt" and e.to == ["Anna"] for e in events)
    assert w.governance.crimes and w.governance.crimes[0]["thief"] == "Boris"
    assert "Anna" in w.governance.crimes[0]["known_by"]
    assert "steal_from_plot" not in engine.observe(w, "Anna")["available_actions"]  # own yard


def test_fire_burns_the_yard_stock():
    w = world(agents=[{"name": "Anna", "profession": "farmer", "house_level": 2, "buildings": ["beehive"]}])
    w.plots["home_Anna"].buildings[0]["items"]["honey"] = 2
    w.ledger["honey"] = 2
    ctx = engine.Ctx(w, engine.rng_for(w))
    engine.burn_house(ctx, "home_Anna")
    check(w)
    assert plots.stock(w.plots["home_Anna"]) == {} and w.plots["home_Anna"].house == 1


def test_disabled_plots():
    w = world(plots={"enabled": False})
    assert w.plots == {}
    assert "plot" not in engine.observe(w, "Anna")
    assert act(w, "Anna", "build", {"kind": "garden_bed"})[0]


def test_homestead_bots_replay(tmp_path):
    log = tmp_path / "h.jsonl"
    w = engine.new_world({"seed": 3})
    run(w, bots_decider(w, ["homestead", "homestead", "thief", "homestead", "homestead"], 3), days=8, log_path=log)
    assert any(p.buildings for p in w.plots.values())
    replay(log)


def test_run_config_sets_unequal_start():
    from aivillage.runconfig import RunConfig
    rc = RunConfig.model_validate({"agents": [
        {"name": "Anna", "profession": "farmer", "plot_cells": 16, "house_level": 3, "buildings": ["cow_pen"]},
        {"name": "Boris", "profession": "fisher", "plot_cells": 2}]})
    w = engine.new_world(rc.world_override())
    assert (w.plots["home_Anna"].cells, w.plots["home_Anna"].house) == (16, 3)
    assert w.plots["home_Boris"].cells == 2 and w.plots["home_Boris"].buildings == []
