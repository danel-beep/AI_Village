"""Exploration: villagers know only the places they have been to (aivillage/explore.py)."""

import random

import pytest

from aivillage import engine, explore
from aivillage.llm import world_facts
from aivillage.ops import Ctx
from aivillage.registry import ACTIONS, ActionError
from aivillage.run import bots_decider, replay, run

CFG = {"seed": 1, "crises": {"enabled": False}, "explore": {"enabled": True}}


def move(w, name, to):
    ACTIONS.run(Ctx(w, random.Random(0)), w.agents[name], "move", {"to": to})


def walk(w, name, to):
    """Move and keep walking until there, then be observed (as the run loop does)."""
    move(w, name, to)
    a = w.agents[name]
    while a.task:
        engine.continue_task(Ctx(w, random.Random(0)), a)
    return engine.observe(w, name)


def test_off_changes_nothing():
    w = engine.new_world({"seed": 1})
    obs = engine.observe(w, "Anna")
    assert "explored" not in obs and w.explore == {} and explore.view(w) is None
    move(w, "Anna", "mine")  # the whole map is open
    assert "Map:" in world_facts(w.config) and "Gather with work at" in world_facts(w.config)


def test_start_knows_home_square_and_its_neighbours():
    w = engine.new_world(CFG)
    ex = engine.observe(w, "Anna")["explored"]
    assert set(ex["places"]) == {"home_Anna", *w.locations["square"].neighbors, "square"}
    assert "mine" not in ex["places"] and "wood" in ex["places"]["forest"]
    assert ex["roads_to_unexplored"]["forest"] == ["mine", "lot_3"]
    assert explore.view(w) == sorted(ex["places"])


def test_move_one_road_past_known_then_known_after_arriving():
    w = engine.new_world({**CFG, "explore": {"enabled": True, "start_radius": 0}})
    assert set(engine.observe(w, "Anna")["explored"]["places"]) == {"home_Anna", "square"}
    with pytest.raises(ActionError, match="do not know the way"):
        move(w, "Anna", "mine")  # two roads past what Anna knows
    ex = walk(w, "Anna", "forest")["explored"]
    assert "forest" in ex["places"] and "mine" in ex["roads_to_unexplored"]["forest"]
    assert "forest" not in engine.observe(w, "Boris")["explored"]["places"]  # knowledge is personal
    walk(w, "Anna", "mine")
    assert w.agents["Anna"].location == "mine"
    assert {"forest", "mine"} <= set(explore.view(w))


def test_walks_only_through_known_places():
    w = engine.new_world({**CFG, "explore": {"enabled": True, "start_radius": 0}})
    w.explore["Anna"] = ["home_Anna", "square", "mine"]  # heard of the mine only by walking it long ago
    with pytest.raises(ActionError, match="through places you know"):
        move(w, "Anna", "mine")  # the only road goes through the forest, unknown to her


def test_prompt_map_is_hidden():
    facts = world_facts(engine.new_world(CFG).config)
    assert "explored.places" in facts and "Gather with work at" not in facts and "mine ->" not in facts


def test_bots_run_and_replay(tmp_path):
    w = engine.new_world({**CFG, "map": {"procedural": True, "size": "normal"}})
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["random", "worker", "thief"], 3), days=2, log_path=log)
    assert replay(log).hash() == w.hash()
    import json
    ticks = [json.loads(line) for line in log.read_text().splitlines() if '"type": "tick"' in line]
    assert all("known" in t["view"] for t in ticks)
    assert len(ticks[-1]["view"]["known"]) >= len(ticks[0]["view"]["known"])


def test_texts_are_neutral():
    from tests.test_neutrality import evaluative
    w = engine.new_world({**CFG, "explore": {"enabled": True, "start_radius": 0}})
    texts = [explore.facts(w.config)]
    for to in ("mine",):
        try:
            move(w, "Anna", to)
        except ActionError as e:
            texts.append(str(e))
    assert len(texts) == 2 and evaluative(" ".join(texts)) == []


def test_view_by_is_written_only_when_someone_learns_a_place():
    w = engine.new_world(CFG)
    assert explore.view_by(engine.new_world({"seed": 1})) == {}  # exploration off
    engine.observe(w, "Anna")
    first = explore.view_by(w)["known_by"]
    assert first["Anna"] == sorted(explore.known(w, "Anna"))
    assert explore.view_by(w) == {}  # nothing new
    walk(w, "Anna", "mine")
    assert "mine" in explore.view_by(w)["known_by"]["Anna"]
