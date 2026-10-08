"""Choosing where to live in a camp start (aivillage/settle.py) and the empty valley of mapgen."""

from aivillage import construction, engine, modes, run, settle
from aivillage.invariants import check


def world(stage="camp", procedural=True, **extra):
    return engine.new_world(modes.world_override("normal", {
        "seed": 5, "progress": {"start_stage": stage}, "map": {"procedural": procedural}, **extra}))


def step(w, decisions):
    for n in decisions:
        a = w.agents[n]
        a.busy_until, a.task, a.asleep = w.tick, None, False
    engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in decisions.items()})
    check(w)


def test_camp_map_has_house_sites_not_houses():
    w = world()
    m = w.config["map"]
    places = m["layout"]["places"]
    assert m["camp"] and not any(p["kind"] in ("home", "hamlet") for p in places.values())
    assert len(m["sites"]) >= len(w.agents)
    assert all(places[sid]["kind"] == "homesite" and places[sid]["near"] == s["near"] for sid, s in m["sites"].items())
    assert {s["near"] for s in m["sites"].values()} - {"square"}  # sites by the forest, river, mine...
    for a in w.agents.values():  # everyone sleeps at the camp
        assert w.locations[a.home].neighbors == ["square"] and a.location == a.home
    assert w.locations["square"].name == "Camp"


def test_resource_places_lie_apart():
    w = world()
    places, gap = w.config["map"]["layout"]["places"], w.config["settle"]["zone_gap"]
    zones = [p["anchor"] for p in places.values() if p["kind"] in ("forest", "mine", "grove", "pond", "quarry")]
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) >= gap


def test_settle_moves_the_home_first_come_once():
    w = world()
    near = w.config["map"]["sites"]
    place = next(s["near"] for s in near.values() if s["near"] != "square")
    free = len(settle.free_sites(w, place))
    a, b = w.agents["Anna"], w.agents["Boris"]
    a.location = a.home
    step(w, {"Anna": ("start_building", {"kind": "shelter"})})
    assert not construction.sites(w)  # no yard at the camp
    a.location = b.location = place
    step(w, {"Anna": ("settle", {})})
    assert w.locations[a.home].neighbors == [place] and a.home in w.locations[place].neighbors
    assert a.home not in w.locations["square"].neighbors
    assert w.settle["homes"]["Anna"] in near and "Anna" not in w.settle["camp"]
    assert len(settle.free_sites(w, place)) == free - 1
    assert w.locations[a.home].name == "Anna's house"
    step(w, {"Anna": ("settle", {})})
    assert w.locations[a.home].neighbors == [place] and a.last_error  # already here
    a.location = "square"  # an empty yard may still move: the old site is free again
    step(w, {"Anna": ("settle", {})})
    assert w.locations[a.home].neighbors == ["square"] and len(settle.free_sites(w, place)) == free
    a.location = place
    step(w, {"Anna": ("settle", {})})
    a.location = a.home
    step(w, {"Anna": ("start_building", {"kind": "shelter"})})
    assert construction.sites(w)  # now there is a yard
    a.location = "square"
    step(w, {"Anna": ("settle", {})})
    assert w.locations[a.home].neighbors == [place] and "stays" in a.last_error  # a site in the yard: it stays
    obs = engine.observe(w, "Boris")
    assert obs["house_sites"]["yours"] is None and obs["house_sites"]["free_here"] == free - 1
    assert "settle" in obs["available_actions"]


def test_settle_at_the_camp_itself():
    """The camp spot hangs off the camp but is no house site: a free site at the camp can still be taken
    (live run 2026-10-07: Elena was told "already one road from here" and had no yard for 4 days)."""
    w = world()
    a = w.agents["Elena"]
    a.location = "square"
    assert settle.free_sites(w, "square") and "settle" in engine.observe(w, "Elena")["available_actions"]
    step(w, {"Elena": ("settle", {})})
    assert not a.last_error and "Elena" not in w.settle["camp"] and w.settle["homes"]["Elena"]
    a.location = a.home
    step(w, {"Elena": ("start_building", {"kind": "shelter"})})
    assert construction.sites(w)  # a yard now
    a.location = "square"
    step(w, {"Elena": ("settle", {})})
    assert a.last_error  # settled: no second site at the same place


def test_walks_leave_trails():
    w = world()
    a = w.agents["Anna"]
    step(w, {"Anna": ("move", {"to": "square"})})
    assert w.settle["trails"] == {"home_Anna|square": 1}
    view = run.view(w)
    assert view["settle"]["trails"] == {"home_Anna|square": 1} and a.location == "square"


def test_hand_made_map_gets_plain_sites():
    w = world(procedural=False)
    sites = settle.sites(w.config)
    assert sites and {"square", "forest", "river", "mine"} <= {s["near"] for s in sites.values()}
    assert settle.active(w.config)


def test_ready_village_and_trades_world_untouched():
    for w in (world("hamlet"), engine.new_world(modes.trades_override({"seed": 5, "map": {"procedural": True}}))):
        assert not settle.active(w.config) and not w.settle
        assert not w.config["map"].get("camp") and any(p["kind"] == "home" for p in w.config["map"]["layout"]["places"].values())


def test_normal_maps_unchanged_by_the_settle_block():
    cfg = modes.trades_override({"seed": 9, "map": {"procedural": True}})
    a = engine.new_world(cfg).config["map"]["layout"]
    b = engine.new_world({**cfg, "settle": {"enabled": True}}).config["map"]["layout"]
    assert a == b  # settling needs a camp start


def test_knob_spread_widens_the_valley():
    small = world(settle={"spread_bonus": 0}).config["map"]["layout"]
    assert world().config["map"]["layout"]["cols"] > small["cols"]
