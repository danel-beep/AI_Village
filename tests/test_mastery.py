"""No professions (labor.mastery, the «С нуля» mode): mastery per kind of work, a bigger house a better household."""

import pytest

from aivillage import engine, labor, llm, ops
from aivillage.invariants import check
from aivillage.modes import world_override


def survival(**extra):
    return engine.new_world(world_override("survival", {"seed": 3, "crises": {"enabled": False}, **extra}))


@pytest.fixture
def w():
    return survival()


def act(w, name, action, **args):
    w.agents[name].busy_until = w.tick
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def work(w, name, resource, hours=1):
    """`hours` single hours of gathering, the hours limit of the day reset in between."""
    got = 0
    for _ in range(hours):
        w.agents[name].worked_today = 0
        before = ops.count(w.agents[name].inventory, resource)
        act(w, name, "work", resource=resource, hours=1)
        while w.agents[name].task:
            engine.step(w, {})
        got += ops.count(w.agents[name].inventory, resource) - before
    return got


def test_nobody_has_a_trade_and_anyone_gathers_anything(w):
    assert labor.no_professions(w.config)
    assert {a.profession for a in w.agents.values()} == {"villager"}
    assert not w.config["places"]["enabled"] and not w.config["crafting"]["owner_takes_trade"]
    w.agents["Anna"].location = "river"
    assert work(w, "Anna", "fish") > 0
    assert w.agents["Anna"].mastery == {"fishing": 1}


def test_mastery_grows_per_kind_of_work_and_adds_to_gathering(w):
    a = w.agents["Anna"]
    a.location = "river"
    w.config["locations"]["river"]["resources"]["fish"]["per_hour"] = None
    first = work(w, "Anna", "fish")
    work(w, "Anna", "fish", 5)
    assert labor.mastery_level(w.config, a, "fishing") == 1
    assert labor.mastery_level(w.config, a, "woodcutting") == 0
    w.locations["river"].slots["fish"] = [50] * len(w.locations["river"].slots["fish"])
    assert work(w, "Anna", "fish") == first + w.config["labor"]["mastery"]["gather_bonus"]
    obs = engine.observe(w, "Anna")
    assert obs["work_today"]["your_mastery"]["fishing"]["level"] == 1
    assert {v["name"]: v["best_at"] for v in obs["board"]["villagers"]}["Anna"] == "fishing"


def test_a_level_up_is_public(w):
    w.agents["Anna"].location = "river"
    w.agents["Anna"].mastery = {"fishing": 5}
    events = act(w, "Anna", "work", resource="fish", hours=1)
    up = [e for e in events if e.kind == "skill_up"]
    assert up and up[0].visibility == "public" and up[0].data["activity"] == "fishing"


def test_mastery_left_alone_is_slowly_forgotten(w):
    a = w.agents["Anna"]
    a.mastery, a.practiced = {"fishing": 20, "mining": 1}, {"fishing": w.day, "mining": w.day}
    m = w.config["labor"]["mastery"]
    for _ in range(m["forget_after_days"] + 1):  # one day past the grace: forgotten once
        day = w.day
        while w.day == day:
            engine.step(w, {})
    assert a.mastery["fishing"] == 20 - m["forget_per_day"]
    assert "mining" not in a.mastery and "mining" not in a.practiced


def test_craft_mastery_and_the_house_give_more_items_with_the_fraction_carried():
    w = survival(progress={"start_stage": "hamlet"})  # a yard of one's own (a camp spot is none)
    a = w.agents["Anna"]
    ops.mint(w, a.inventory, "wood", 40)
    a.location = a.home
    w.plots[a.home].house = 0
    made = []
    for _ in range(4):
        before = ops.count(a.inventory, "plank")
        act(w, "Anna", "craft", recipe="plank", times=1)
        made.append(ops.count(a.inventory, "plank") - before)
    assert made == [1, 1, 1, 1] and a.mastery["handwork"] == 4
    w.plots[a.home].house = 2  # +50% at home
    made = []
    for _ in range(4):
        before = ops.count(a.inventory, "plank")
        act(w, "Anna", "craft", recipe="plank", times=1)
        made.append(ops.count(a.inventory, "plank") - before)
    assert sum(made) == 6  # 4 planks + 50%: two extra over four batches


def test_farming_mastery_and_the_house_raise_a_garden_bed():
    from aivillage import plots
    w = survival(progress={"start_stage": "hamlet"})
    a = w.agents["Anna"]
    plot = w.plots[a.home]
    plot.house = 0
    plot.buildings = [{"id": "b_test", "kind": "garden_bed", "built_day": 1, "items": {}, "crop": None,
                       "ripe_day": 0}]
    spec = w.config["plots"]["buildings"]["garden_bed"]
    a.location = a.home
    ops.mint(w, a.inventory, "grain", 4)
    act(w, "Anna", "plant", crop="grain")
    base = plot.buildings[-1]["amount"]  # no mastery, house 0: the bed alone (and the tool's bonus)
    assert base in (plots._bed_yield(w.config, spec, a.profession, tool=t) for t in (False, True))
    assert a.mastery["farming"] == 1
    plot.buildings[-1]["crop"] = None
    a.mastery["farming"] = 18  # level 2
    plot.house = 2
    act(w, "Anna", "plant", crop="grain")
    assert plot.buildings[-1]["amount"] == (base + 2) * 3 // 2


def test_the_rules_say_so_in_the_prompt(w):
    facts = llm.world_facts(w.config)
    assert "no professions" in facts and "Mastery:" in facts and "Household:" in facts
    assert "Trades: only a villager of that profession" not in facts


def test_crafts_mode_keeps_its_professions():
    w = engine.new_world(world_override("crafts", {"seed": 3}))
    assert not labor.no_professions(w.config)
    assert "villager" not in {a.profession for a in w.agents.values()}
    assert "Trades: only a villager of that profession" in llm.world_facts(w.config)


def test_fine_things_need_mastery_of_their_kind_first(w):
    a = w.agents["Anna"]
    r = w.config["recipes"]["sword"]
    assert labor.craft_activity(w.config, r) == "smithing"
    assert "smithing mastery level 3" in labor.mastery_gate(w.config, a, "sword", r)
    a.mastery["smithing"] = 36
    assert labor.mastery_gate(w.config, a, "sword", r) is None
    assert labor.mastery_gate(w.config, a, "plank", w.config["recipes"]["plank"]) is None
    assert "sword (smithing 3)" in llm.world_facts(w.config)
