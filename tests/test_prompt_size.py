"""The villager's system prompt stays short (audit 2026-10-08, C-2 and D-2): World facts follow what the village
has opened, one build verb instead of three, and the rules are stated as facts, not advice."""

import re

from test_construction import act, errors, give, site_of, world

from aivillage import construction, engine, llm, progress, runconfig
from aivillage.run import llm_agents, with_tick_minutes

# «С нуля» at the first hour was 37.5k characters before the cut; raise this only with a reason in the PR.
START_PROMPT_MAX = 24_500


def survival(start=None):
    ov = runconfig.RunConfig(mode="survival", seed=3).world_override()
    with_tick_minutes(ov, None)
    if start:
        ov.setdefault("progress", {})["start_stage"] = start
    w = engine.new_world(ov)
    agents = llm_agents(w, ["stub"])
    name = sorted(agents)[0]
    return w, agents[name], engine.observe(w, name, consume_inbox=False)


def test_start_prompt_is_short():
    _, ag, obs = survival()
    assert len(ag.system_prompt(obs)) <= START_PROMPT_MAX


def test_facts_follow_the_village_stage():
    _, camp, obs = survival()
    early = camp.facts_now(obs)
    _, town, obs_town = survival("town")
    late = town.facts_now(obs_town)
    for rule in ("Polities", "Market board", "merchant from afar", "Transport", "Outsiders", "Council orders",
                 "town_hall ("):
        assert rule not in early, rule
        assert rule in late, rule
    assert "More buildings and levels open at later village stages." in early
    # the full sheet (progress off, tests, tools) still has every rule
    full = llm.world_facts(camp.facts_cfg)
    assert "Polities" in full and "town_hall (" in full and "from stage" in full


def test_rules_are_facts_not_advice():
    rules = llm.SYSTEM[llm.SYSTEM.index("How things work:"):]
    for line in rules.splitlines():
        assert not re.match(r"- (Keep|Check|Read|Make|Eat|Try|Avoid|Do|Don't|Remember)\b", line), line
    assert "do something different" not in llm.SYSTEM


def test_build_opens_supplies_and_works_a_site():
    w = world()
    give(w, "Anna", wood=6, stone=2)
    assert "build" in engine.observe(w, "Anna", consume_inbox=False)["available_actions"]
    assert not errors(act(w, "Anna", "build", kind="workbench"))
    s = site_of(w, "workbench")
    assert construction.remaining(s) == {} and s["work"] == 1 and s["owner"] == "Anna"
    for _ in range(int(s["hours"]) - 1):
        assert not errors(act(w, "Anna", "build", kind="workbench"))
    assert s["id"] not in construction.sites(w) and progress.built(w)["workbench"] == 1


def test_build_errors_say_what_to_do():
    w = world()
    assert "buildings:" in errors(act(w, "Anna", "build", kind="castle"))[0]
    w.agents["Anna"].location = "square"
    assert "go to home_Anna first" in errors(act(w, "Anna", "build", kind="workbench"))[0]


def test_models_see_one_build_verb():
    w = world()
    agents = llm_agents(w, ["stub"])
    ag = agents["Anna"]
    act(w, "Anna", "start_building", kind="workbench")  # bots and old logs still use the three steps
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "construct" in obs["available_actions"]
    sent = []
    complete = ag.client.complete
    ag.client.complete = lambda messages: (sent.extend(messages), complete(messages))[1]
    ag.decide(obs)
    text = "\n".join(m["content"] for m in sent)
    assert "\nbuild(kind)" in text
    for n in ("start_building", "bring_materials", "construct"):
        assert f"\n{n}(" not in text and f'"{n}"' not in text, n
