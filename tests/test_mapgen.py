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


def test_plot_start_for_the_plots_engine():
    fair = gen(6, 6, unfairness=0)
    assert {a["plot_cells"] for a in fair["agents"]} == {mapgen.PLOT_CELLS}
    assert {a["house_level"] for a in fair["agents"]} == {1}
    unfair = [gen(seed, 10, unfairness=1) for seed in range(1, 4)]
    assert any(len({a["plot_cells"] for a in c["agents"]}) > 2 for c in unfair)
    assert all(1 <= a["house_level"] <= 3 for c in unfair for a in c["agents"])
    kept = mapgen.generate(make_config({"seed": 1, "map": {"procedural": True}, "agents": [
        {"name": "A", "profession": "farmer", "plot_cells": 40}, {"name": "B", "profession": "smith"}]}))
    assert kept["agents"][0]["plot_cells"] == 40  # an explicit start wins


def test_economy_modes_set_start_unfairness():
    from aivillage import modes
    assert modes.unfairness("peaceful") < modes.unfairness("standard") < modes.unfairness("gold_rush")
    w = engine.new_world(mapgen.for_run(modes.world_override("scarcity")))
    assert w.config["map"]["unfairness"] == 0.6 and "layout" in w.config["map"]


# ---------- large map (map.size) and regrowth from the remainder ----------

def test_normal_size_is_the_old_map():
    a, b = gen(5, 5), gen(5, 5, size="normal")
    assert a["map"]["layout"] == b["map"]["layout"] and a["locations"] == b["locations"]
    assert not any(s.get("biome") for s in a["locations"].values())
    assert "clay" not in a["items"]
    with pytest.raises(ValueError):
        gen(5, 5, size="giant")


@pytest.mark.parametrize("size,n", [("large", 5), ("large", 12), ("huge", 5), ("huge", 20)])
def test_large_map_has_far_wild_zones(size, n):
    for seed in (1, 2):
        cfg = gen(seed, n, size=size)
        assert cfg == gen(seed, n, size=size)  # by seed
        small = gen(seed, n)
        lay = cfg["map"]["layout"]
        assert lay["cols"] > small["map"]["layout"]["cols"] and lay["rows"] > small["map"]["layout"]["rows"]
        p = mapgen.params(cfg)
        mapgen.check(cfg, make_config()["locations"], {**p, **{k: p[k] + cfg["map"]["relaxed"] for k in mapgen.RELAXABLE}})
        d = mapgen.distances(mapgen.graph(cfg), "square")
        wild = {k: s for k, s in cfg["locations"].items() if s.get("biome")}
        kinds = {}
        for lid in wild:
            kinds[lay["places"][lid]["kind"]] = kinds.get(lay["places"][lid]["kind"], 0) + 1
        assert kinds == mapgen.MAP_SIZES[size]["wilds"]
        for lid in wild:
            assert d[lid] >= 2, (lid, d[lid])  # far: the village core stays compact
        res = lambda kind: {r for lid, s in wild.items() if lay["places"][lid]["kind"] == kind for r in s["resources"]}
        assert res("deepwood") == {"wood", "berries"} and res("cave") == {"stone", "ore"}
        assert res("lake") == {"fish", "water"} and res("clayhill") == {"clay"}
        assert cfg["items"]["clay"]["value"] > 0
        # the core is as close as on the normal map's honest minimum
        assert max(f["square"] for f in cfg["map"]["fairness"].values()) <= p["max_home_hops"] + cfg["map"]["relaxed"]


def test_large_map_lake_is_water_roads_go_round():
    cfg = gen(3, 8, size="large")
    lay = cfg["map"]["layout"]
    lake = lay["places"]["lake"]
    water = set(mapgen.lake_tiles(*lake["box"]))
    assert len(water) > lake["box"][2] * lake["box"][3] // 2
    road = set()
    for r in lay["routes"]:
        pts = r["path"]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            road |= {(x, y) for x in range(min(x0, x1), max(x0, x1) + 1) for y in range(min(y0, y1), max(y0, y1) + 1)}
    assert not road & water
    owned = {}
    for pid, pl in lay["places"].items():
        area = pl.get("plot") or pl.get("box")
        if area:
            for t in mapgen.rect(*area):
                assert t not in owned, (pid, owned.get(t))
                owned[t] = pid


def test_large_map_runs_and_replays(tmp_path):
    w = engine.new_world(mapgen.for_run({"seed": 6, "regrowth": {"from_remainder": True}}, size="large"))
    assert w.config["map"]["size"] == "large" and "clay" in w.locations["clayhill"].resources
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["worker", "trader", "random"], 6), days=2, log_path=log)
    assert replay(log).hash() == w.hash()


def test_regrowth_from_remainder():
    from aivillage import tiles
    from aivillage.state import Location
    spec = {"start": 80, "max": 80, "regen": 40, "slots": 8}
    cfg = make_config()
    loc = Location("f", "F", [], {"wood": 40})
    assert tiles.regen(cfg, loc, "wood", spec) == 40  # off by default: the flat rate
    on = make_config({"regrowth": {"from_remainder": True, "floor": 0.1}})
    assert tiles.regen(on, loc, "wood", spec) == 20  # half left: half the rate
    loc.resources["wood"] = 80
    assert tiles.regen(on, loc, "wood", spec) == 40
    loc.resources["wood"] = 0
    assert tiles.regen(on, loc, "wood", spec) == 4  # cleared: only the floor
    assert tiles.regen(on, loc, "wood", {**spec, "regen": 2}) == 1  # never stuck at zero
    assert tiles.regen(on, loc, "gold", {"start": 9, "max": 9, "regen": 0}) == 0
    assert tiles.regen(on, loc, "water", {"start": 999, "max": 999, "regen": 999}) == 999


def test_cleared_forest_comes_back_slower():
    def night_after_clearing(flag: bool) -> int:
        w = engine.new_world({"seed": 2, "regrowth": {"from_remainder": flag}, "seasons": {"enabled": False}})
        f = w.locations["forest"]
        from aivillage import tiles
        tiles.take(f, "wood", f.resources["wood"])
        engine.night(engine.Ctx(w, engine.rng_for(w, "test")))
        return f.resources["wood"]
    assert night_after_clearing(True) < night_after_clearing(False)


def test_size_and_regrowth_on_the_start_screen():
    from aivillage import knobs
    keys = {k["key"]: k for k in knobs.active()}
    assert keys["map_size"]["path"] == "map.size" and keys["regrowth"]["path"] == "regrowth.from_remainder"
    run_ = knobs.to_run({"map_size": "huge", "regrowth": True, "brains": "bots"})
    assert run_["override"]["map"]["size"] == "huge" and run_["override"]["regrowth"]["from_remainder"] is True
    assert knobs.to_run({"brains": "bots"})["override"]["map"]["size"] == "normal"


def test_viewer_lake_matches_python():
    import json
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("node not installed")
    js = (Path(__file__).parent.parent / "viewer" / "mapgen.js").read_text(encoding="utf-8")
    boxes = [[3, 4, 9, 6], [10, 2, 7, 5], [0, 0, 4, 3]]
    probe = "const window = {};\n" + js + f"\nconsole.log(JSON.stringify({json.dumps(boxes)}.map(b => window.GenMap.lakeTiles(b))));"
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    for b, tiles_js in zip(boxes, out):
        assert sorted(map(tuple, tiles_js)) == sorted(mapgen.lake_tiles(*b))
