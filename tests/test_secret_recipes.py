"""Secret recipes (crafting.secrets, «С нуля» plan task 19): know-how is owned, taught or sold."""

import json

import pytest

from aivillage import crafting, engine, handbook, ops
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.ops import Ctx
from aivillage.registry import ACTIONS, ActionError
from aivillage.run import bots_decider, replay, run

from test_neutrality import evaluative

CFG = {"seed": 1, "crises": {"enabled": False},
       "crafting": {"enabled": True, "secrets": {"enabled": True, "common": ["bread"]}}}


@pytest.fixture
def w():
    w = engine.new_world(CFG)
    names = sorted(w.agents)
    for n in names[1:]:  # everyone stands with the first villager
        w.agents[n].location = w.agents[names[0]].location
    return w


def names(w):
    return sorted(w.agents)


def act(w, name, action, **args):
    ACTIONS.run(Ctx(w, engine.rng_for(w)), w.agents[name], action, args)
    check(w)


def give(w, name, **items):
    for k, n in items.items():
        ops.mint(w, w.agents[name].inventory, k, n)


def test_off_everyone_knows_everything():
    w = engine.new_world({**CFG, "crafting": {"enabled": True}})
    a = names(w)[0]
    give(w, a, wood=2)
    act(w, a, "craft", recipe="plank", times=1)
    assert w.agents[a].known_recipes == [] and w.agents[a].inventory.get("plank") == 1
    assert "teach" not in ACTIONS.available(Ctx(w, engine.rng_for(w)), w.agents[a])


def test_common_recipes_need_no_knowledge(w):
    a = names(w)[0]
    give(w, a, flour=1, wood=1)
    w.agents[a].location = w.agents[a].home
    act(w, a, "craft", recipe="bread", times=1)
    assert w.agents[a].inventory.get("bread") == 1 and w.agents[a].known_recipes == []


def test_first_maker_works_it_out_and_others_cannot(w):
    a, b = names(w)[:2]
    give(w, a, wood=4)
    give(w, b, wood=2)
    act(w, a, "craft", recipe="plank", times=1)
    assert w.agents[a].known_recipes == ["plank"]
    assert w.agents[a].task and w.agents[a].task["hours_left"] >= 3  # working it out took longer
    assert crafting.knowers(w, "plank") == [a]
    with pytest.raises(ActionError, match="known to"):
        act(w, b, "craft", recipe="plank", times=1)
    assert w.agents[b].inventory.get("wood") == 2  # nothing spent on a refused craft
    w.agents[a].task = None
    act(w, a, "craft", recipe="plank", times=1)  # known now: an ordinary craft
    assert w.agents[a].task is None


def test_free_teaching_and_teaching_on(w):
    a, b, c = names(w)[:3]
    w.agents[a].known_recipes = ["leather"]
    act(w, a, "teach", person=b, recipe="leather")
    assert w.agents[b].known_recipes == ["leather"]
    act(w, b, "teach", person=c, recipe="leather")  # the learner may pass it on
    assert crafting.knowers(w, "leather") == sorted([a, b, c])
    with pytest.raises(ActionError, match="already knows"):
        act(w, a, "teach", person=c, recipe="leather")
    with pytest.raises(ActionError, match="not a recipe known only to some"):
        act(w, a, "teach", person=c, recipe="bread")


def test_paid_lesson(w):
    a, b = names(w)[:2]
    w.agents[a].known_recipes = ["leather"]
    coins_a, coins_b = w.agents[a].coins, w.agents[b].coins
    assert coins_b >= 4
    give(w, b, wood=2)
    act(w, a, "teach", person=b, recipe="leather", price={"coins": 4, "wood": 2})
    assert w.agents[b].known_recipes == []
    obs = engine.observe(w, b)
    assert [(o["teacher"], o["recipe"]) for o in obs["lessons_offered"]] == [(a, "leather")]
    act(w, b, "learn", teacher=a, recipe="leather")
    assert w.agents[b].known_recipes == ["leather"] and w.agents[b].coins == coins_b - 4
    assert w.agents[a].coins == coins_a + 4 and w.agents[a].inventory.get("wood", 0) >= 2
    with pytest.raises(ActionError, match="no open lesson"):
        act(w, b, "learn", teacher=a, recipe="leather")


def test_lesson_needs_payment_and_presence(w):
    a, b = names(w)[:2]
    w.agents[a].known_recipes = ["leather"]
    act(w, a, "teach", person=b, recipe="leather", price={"coins": 999})
    with pytest.raises(ActionError, match="you do not have it"):
        act(w, b, "learn", teacher=a, recipe="leather")
    w.agents[a].location = "nowhere-else"
    with pytest.raises(ActionError, match="must be here"):
        act(w, b, "learn", teacher=a, recipe="leather")


def test_dead_knowers_free_the_recipe(w):
    a, b = names(w)[:2]
    w.agents[a].known_recipes = ["leather"]
    assert not crafting.may_make(w, w.agents[b], "leather")
    w.agents[a].status = "dead"
    assert crafting.may_make(w, w.agents[b], "leather")


def test_hint_and_facts_follow_knowledge(w):
    a, b = names(w)[:2]
    w.agents[a].known_recipes = ["leather"]
    w.agents[a].known_recipes = ["plank"]
    give(w, b, wood=2)
    assert "plank" not in handbook.observe(w, b).get("can_craft_now", {})
    facts = world_facts(w.config)
    assert "Recipes known to everyone" in facts and "teach" in facts
    assert not evaluative(facts)
    assert engine.observe(w, a)["recipes_you_know"] == ["plank"]


def test_bots_run_with_secrets_is_exact_and_neutral(tmp_path):
    w = engine.new_world({**CFG, "seed": 3})
    bots = bots_decider(w, ["random", "worker"], 3)
    found = set()

    def decide(name, obs, _bots=bots):
        found.update(evaluative(json.dumps(obs)))
        return _bots(name, obs)
    decide.bots = bots.bots
    log = tmp_path / "run.jsonl"
    run(w, decide, days=3, log_path=log)
    assert found == set()
    assert replay(log).hash() == w.hash()
