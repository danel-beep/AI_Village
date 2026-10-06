"""Game animals and hunting (animals.py): small game alone, big game in a party, killing blow takes all,
herds flee hunted places and breed from what is left; off by default."""

import json

from aivillage import animals, engine, llm, run
from aivillage.invariants import check
from aivillage.run import bots_decider, replay
from test_neutrality import evaluative

QUIET = {"crises": {"enabled": False}, "illness": {"spread_chance": 0.0}}


def world(animal_cfg=None, **over):
    return engine.new_world({"seed": 1, **QUIET, "animals": {"enabled": True, **(animal_cfg or {})}, **over})


def species(**over):
    return {"species": {k: dict(v) for k, v in over.items()}}


def step(w, decisions=None):
    events = engine.step(w, decisions or {})
    check(w)
    return events


def hunt(w, *names, animal):
    return step(w, {n: {"action": {"name": "hunt", "args": {"animal": animal}}} for n in names})


def at_forest(w, *names):
    for n in names:
        w.agents[n].location = "forest"


def kinds(events):
    return [e.kind for e in events]


def test_off_by_default_changes_nothing():
    w = engine.new_world({"seed": 1})
    assert w.animals == {} and "animals" not in w.to_dict()
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "animals_here" not in obs and "hunt" not in obs["available_actions"]
    assert "hunt" in run.llm_agents(w, {"Anna": "stub"})["Anna"].disabled_actions
    assert "animals" not in run.view(w) and "animals" not in llm.world_facts(w.config).lower()
    assert "meat" not in w.config["items"]


def test_habitats_come_from_the_map_and_scale_with_village():
    w = world()
    assert set(w.animals["herds"]["forest"]) == {"hare", "deer", "boar", "elk"}
    assert set(w.animals["herds"]["river"]) == {"duck"}
    assert w.config["items"]["meat"]["food"] > 0 and "hide" in w.config["items"]
    big = world(population={"size": 10})
    assert big.animals["herds"]["forest"]["hare"] == 2 * w.animals["herds"]["forest"]["hare"]
    fixed = world({"habitats": {"river": {"deer": 2}, "nowhere": {"hare": 3}}})
    assert fixed.animals["herds"] == {"river": {"deer": 2}}


def test_procedural_map_puts_big_game_far_away():
    w = world(map={"procedural": True}, seed=5, population={"size": 10})
    herds = w.animals["herds"]
    assert any("elk" in h for h in herds.values())
    elk = [loc for loc, h in herds.items() if "elk" in h]
    assert len(elk) == 1 and "deer" not in herds.get("forest", {})


def test_small_game_alone_catch_is_the_hunters():
    w = world(species(hare={**engine.make_config()["animals"]["species"]["hare"], "hit_at": -50}))
    at_forest(w, "Anna", "Boris")
    before = w.animals["herds"]["forest"]["hare"]
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert obs["animals_here"]["hare"] == {"count": before, "hunters_needed": 1} and "hunt" in obs["available_actions"]
    for _ in range(6):
        ev = hunt(w, "Anna", animal="hare")
        if "hunt_catch" in kinds(ev):
            break
    catch = next(e for e in ev if e.kind == "hunt_catch")
    assert catch.visibility == "location" and catch.data["killer"] == "Anna"
    assert w.agents["Anna"].inventory["meat"] == 1 and w.agents["Anna"].inventory["hide"] == 1
    assert w.animals["herds"]["forest"]["hare"] < before
    assert "meat" not in w.agents["Boris"].inventory


def test_big_game_alone_gets_away():
    w = world()
    at_forest(w, "Anna")
    ev = hunt(w, "Anna", animal="deer")
    assert "hunt_party" in kinds(ev) and "hunt_failed" in kinds(ev)
    assert w.animals["herds"]["forest"]["deer"] == 3 and w.animals["parties"] == []
    assert "meat" not in w.agents["Anna"].inventory


def test_killing_blow_takes_all_the_meat():
    deer = {**engine.make_config()["animals"]["species"]["deer"], "hp": 1, "hit_at": -50}
    w = world(species(deer=deer))
    at_forest(w, "Anna", "Boris")
    ev = hunt(w, "Anna", "Boris", animal="deer")
    kill = next(e for e in ev if e.kind == "hunt_kill")
    killer = kill.data["killer"]
    other = ({"Anna", "Boris"} - {killer}).pop()
    assert sorted(kill.data["hunters"]) == ["Anna", "Boris"] and kill.visibility == "location"
    assert w.agents[killer].inventory["meat"] == 6 and w.agents[killer].inventory["hide"] == 2
    assert "meat" not in w.agents[other].inventory
    assert w.animals["herds"]["forest"]["deer"] == 2


def test_party_waits_for_the_hour_and_needs_hunters_present():
    deer = {**engine.make_config()["animals"]["species"]["deer"], "hp": 1, "hit_at": -50}
    w = world(species(deer=deer), tick_minutes=15)
    at_forest(w, "Anna", "Boris")
    ev = hunt(w, "Anna", animal="deer")
    assert kinds(ev).count("hunt_party") == 1 and "hunt_failed" not in kinds(ev)
    obs = engine.observe(w, "Boris", consume_inbox=False)
    assert obs["hunt_parties_here"] == [{"animal": "deer", "hunters": ["Anna"], "hunters_needed": 2}]
    w.agents["Boris"].busy_until = 0
    ev = hunt(w, "Boris", animal="deer")
    w.agents["Boris"].location = "square"  # left before the hunt ran
    ev += step(w) + step(w)
    assert "hunt_failed" in kinds(ev) and "hunt_kill" not in kinds(ev)


def test_boar_strikes_back():
    boar = {**engine.make_config()["animals"]["species"]["boar"], "hp": 1000, "attack": 100, "damage_die": 5}
    w = world(species(boar=boar))
    at_forest(w, "Anna", "Boris")
    ev = hunt(w, "Anna", "Boris", animal="boar")
    failed = next(e for e in ev if e.kind == "hunt_failed")
    assert sum(failed.data["hurt"].values()) > 0
    assert w.agents["Anna"].health + w.agents["Boris"].health < 200


def test_hunted_herd_flees_and_herds_breed_from_what_is_left():
    sp = engine.make_config()["animals"]["species"]
    w = world({"habitats": {"forest": {"deer": 4}, "river": {"deer": 1}, "mine": {"hare": 0}},
               "stray_chance": 0.0, **species(deer={**sp["deer"], "breed": 0.0}, hare={**sp["hare"], "cap": 10})})
    w.animals["today"] = {"forest": 3}
    animals._night(engine.Ctx(w, engine.rng_for(w)), engine.rng_for(w, "x"))
    assert w.animals["herds"]["forest"]["deer"] == 2 and w.animals["herds"]["river"]["deer"] == 3
    ev = engine.Ctx(w, engine.rng_for(w))
    w.animals["herds"]["mine"] = {"hare": 4}
    w.animals["cap"]["mine"] = {"hare": 10}
    animals._night(ev, engine.rng_for(w, "y"))
    assert w.animals["herds"]["mine"]["hare"] > 4  # breeds toward its cap
    w.animals["herds"]["mine"] = {"hare": 1}
    animals._night(ev, engine.rng_for(w, "z"))
    assert w.animals["herds"]["mine"]["hare"] == 1  # one alone does not breed


def test_hunted_out_place_gets_strays_only_by_chance():
    w = world({"stray_chance": 0.0})
    del w.animals["herds"]["river"]
    animals._night(engine.Ctx(w, engine.rng_for(w)), engine.rng_for(w, "x"))
    assert "river" not in w.animals["herds"]
    w.config["animals"]["stray_chance"] = 1.0
    animals._night(engine.Ctx(w, engine.rng_for(w)), engine.rng_for(w, "x"))
    assert w.animals["herds"]["river"]["duck"] == 2


def test_errors_and_facts_are_plain():
    w = world()
    ev = hunt(w, "Anna", animal="deer")  # at home: no animals
    assert w.agents["Anna"].last_error and "no deer here" in w.agents["Anna"].last_error
    at_forest(w, "Anna")
    w.agents["Anna"].busy_until = 0
    hunt(w, "Anna", animal="dragon")
    assert "unknown animal" in w.agents["Anna"].last_error
    facts = animals.facts(w.config)
    assert "killing blow" in facts and evaluative(facts) == [] and evaluative(llm.world_facts(w.config)) == []
    assert ev is not None


def test_hunters_and_fuzz_bots_keep_invariants_and_replay(tmp_path):
    for mode_cfg in ({}, {"map": {"procedural": True}}):
        w = world(**mode_cfg, seed=3, tick_minutes=15)
        found: set[str] = set()
        bots = bots_decider(w, ["hunter", "random", "hunter", "worker"], 3)

        def decide(name, obs, _bots=bots):
            found.update(evaluative(json.dumps(obs)))
            return _bots(name, obs)
        decide.bots = bots.bots
        log = tmp_path / f"hunt{len(mode_cfg)}.jsonl"
        run.run(w, decide, days=3, log_path=log)
        assert found == set()
        assert replay(log).hash() == w.hash()
        recs = [json.loads(x) for x in log.read_text().splitlines()]
        evs = [e["kind"] for r in recs if r.get("type") == "tick" for e in r["events"]]
        assert "hunt_kill" in evs or "hunt_catch" in evs
        assert any("animals" in r.get("view", {}) for r in recs if r.get("type") == "tick")
