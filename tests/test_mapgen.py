"""Procedural map: deterministic per seed, different between seeds, honest minimum, unfairness knob."""

import pytest

from aivillage import engine, mapgen
from aivillage.config import make_config
from aivillage.run import bots_decider, replay, run

PROFS = ["farmer", "fisher", "woodcutter", "miner", "smith"]


def agents(n: int) -> list[dict]:
    return [{"name": f"V{i}", "profession": PROFS[i % len(PROFS)]} for i in range(n)]


def gen(seed: int, n: int = 5, **m) -> dict:
    return mapgen.generate(make_config({"seed": seed, "agents": agents(n), "map": {"procedural": True, **m}}))


def test_same_seed_same_village_other_seed_other_village():
    a, b, c = gen(1), gen(1), gen(2)
    assert a == b
    assert a["map"]["layout"] != c["map"]["layout"]


@pytest.mark.parametrize("n", [2, 5, 12, 20])
def test_honest_minimum_for_every_seed(n):
    for seed in range(1, 6):
        cfg = gen(seed, n)
        mapgen.check(cfg, make_config()["locations"], {**mapgen.params(cfg), **{
            k: mapgen.params(cfg)[k] + cfg["map"]["relaxed"] for k in mapgen.RELAXABLE}})
        fair = cfg["map"]["fairness"]
        assert len(fair) == n
        for f in fair.values():
            assert f["square"] <= 3 and f["market"] <= 4 and f["work"] <= 4, f


def test_layout_has_no_overlaps_and_plots_are_private():
    cfg = gen(3, 12)
    lay = cfg["map"]["layout"]
    owned = {}
    for pid, pl in lay["places"].items():
        area = pl.get("plot") or pl.get("box")
        if not area:
            continue
        x, y, w, h = area
        assert 0 <= x and 0 <= y and x + w <= lay["cols"] and y + h <= lay["rows"], pid
        for t in mapgen.rect(x, y, w, h):
            assert t not in owned, (pid, owned.get(t))
            owned[t] = pid
    homes = [pl for pl in lay["places"].values() if pl["kind"] == "home"]
    assert sorted(h["owner"] for h in homes) == sorted(a["name"] for a in cfg["agents"])
    for h in homes:
        px, py, pw, ph = h["plot"]
        bx, by, bw, bh = h["box"]
        assert px <= bx and py <= by and bx + bw <= px + pw and by + bh <= py + ph  # house inside its plot


def test_engine_uses_generated_graph_and_replays(tmp_path):
    cfg = {"seed": 4, "map": {"procedural": True}}
    w = engine.new_world(cfg)
    links = w.config["map"]["homes"]
    for name, to in links.items():
        assert w.locations[f"home_{name}"].neighbors == to
        assert all(f"home_{name}" in w.locations[t].neighbors for t in to)
    for lid, loc in w.locations.items():  # roads go both ways
        assert all(lid in w.locations[n].neighbors for n in loc.neighbors), lid
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["worker", "thief", "random"], 4), days=2, log_path=log)
    assert replay(log).hash() == w.hash()


def test_extra_patches_and_waypoints_are_real_locations():
    seen = set()
    for seed in range(1, 8):
        w = engine.new_world({"seed": seed, "map": {"procedural": True}})
        seen |= {pl["kind"] for pl in w.config["map"]["layout"]["places"].values()}
        for lid, loc in w.locations.items():
            assert loc.neighbors, lid
    assert {"grove", "pond", "quarry"} & seen and "home" in seen


def test_unfairness_zero_is_equal_one_is_not():
    fair = gen(5, 8, unfairness=0)["map"]
    assert len({s["coins"] for s in fair["start"].values()}) == 1
    assert len({(s["plot"][2], s["plot"][3]) for s in fair["start"].values()}) == 1
    assert not any(s["items"] for s in fair["start"].values())
    rich = [gen(seed, 8, unfairness=1)["map"]["start"] for seed in range(1, 4)]
    assert any(len({s["coins"] for s in st.values()}) > 3 for st in rich)
    assert any(len({s["plot"][2] * s["plot"][3] for s in st.values()}) > 2 for st in rich)
    assert any(s["items"] for st in rich for s in st.values())


def test_unfair_start_goes_through_the_ledger():
    w = engine.new_world({"seed": 2, "agents": agents(8), "map": {"procedural": True, "unfairness": 1}})
    start = w.config["map"]["start"]
    for name, a in w.agents.items():
        assert a.coins == start[name]["coins"]
        for item, n in start[name]["items"].items():
            assert a.inventory[item] == n
    from aivillage import invariants
    invariants.check(w)


def test_fixed_map_flag_and_for_run():
    assert mapgen.for_run({})["map"]["procedural"] is True
    assert mapgen.for_run({}, fixed_map=True)["map"]["procedural"] is False
    assert mapgen.for_run({"map": {"procedural": False}})["map"]["procedural"] is False
    assert mapgen.for_run({}, unfairness=0.8)["map"]["unfairness"] == 0.8
    w = engine.new_world()
    assert "layout" not in w.config["map"]  # the engine default stays the hand-made map
