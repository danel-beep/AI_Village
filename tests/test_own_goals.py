"""Own goals (config `own_goals`): the villager is asked what it wants, never told, and sees its own words."""

import json

from aivillage import engine, llm, runconfig, saves, scorecard
from aivillage.run import llm_agents, night_reflection, run


def stub_village(tmp_path, **rc):
    w = engine.new_world(runconfig.RunConfig(mode="standard", **rc).world_override())
    agents = llm_agents(w, {n: "stub" for n in w.agents})

    def decide(name, obs):
        return agents[name].decide(obs)
    decide.agents, decide.bots = agents, {}
    log = tmp_path / "run.jsonl"
    run(w, decide, days=2, log_path=log, on_night=lambda world, day: night_reflection(world, agents, day))
    return w, agents, [json.loads(l) for l in log.read_text().splitlines()]


def test_intro_before_first_turn_and_wants_every_night(tmp_path):
    w, agents, recs = stub_village(tmp_path)
    a = next(iter(agents.values()))
    assert a.own_goals and a.introduced and a.about_me and a.wants == "A quiet life." and a.plan == "Work and eat."
    intros = {n: d["intro"] for r in recs if r["type"] == "tick" for n, d in r["decisions"].items() if "intro" in d}
    assert set(intros) == set(agents)  # once each, on the first decision
    diaries = [r for r in recs if r["type"] == "diary"]
    assert diaries and all({"wants", "plan"} <= set(e) for r in diaries for e in r["entries"].values())
    g = scorecard.goals(recs)
    assert g[a.name][0] == (0, "A quiet life.") and len(g[a.name]) == 1  # unchanged wants are listed once
    assert "## Чего хотят жители" in scorecard.to_markdown(scorecard.compute([tmp_path / "run.jsonl"]))


def test_own_words_come_first_in_memory_and_night_prompt_asks(tmp_path):
    w = engine.new_world(runconfig.RunConfig(mode="standard").world_override())
    a = next(iter(llm_agents(w, {n: "stub" for n in w.agents}).values()))
    a.wants, a.plan = "Build a bigger house.", "Cut wood."
    system, user = (m["content"] for m in a.messages(engine.observe(w, a.name, consume_inbox=False)))
    assert llm.GOALS.strip() in system
    memory = json.loads(user.split("(your memory: ", 1)[1].split("):\n", 1)[0])
    assert list(memory)[:3] == ["about_me", "what_you_want", "your_plan_for_today"]
    assert memory["what_you_want"] == "Build a bigger house."
    sent = []
    a.client.complete = lambda msgs: (sent.append(msgs), ('{"diary": "x", "wants": "", "tomorrow": "Rest."}', {}))[1]
    a.day_log = ["8:00 at home: I did wait"]
    entry = a.reflect(1)
    assert llm.REFLECT_GOALS in sent[0][0]["content"] and "Build a bigger house." in sent[0][1]["content"]
    assert entry["wants"] == "" and a.wants == "" and a.plan == "Rest."  # dropping a want is allowed


def test_off_means_the_old_prompt(tmp_path):
    w, agents, recs = stub_village(tmp_path, world={"own_goals": False})
    a = next(iter(agents.values()))
    assert not a.introduced and not a.wants
    system, user = (m["content"] for m in a.messages(engine.observe(w, a.name, consume_inbox=False)))
    assert llm.GOALS.strip() not in system and "what_you_want" not in user
    assert not any("intro" in d for r in recs if r["type"] == "tick" for d in r["decisions"].values())
    assert all("wants" not in e for r in recs if r["type"] == "diary" for e in r["entries"].values())


def test_prompt_names_no_goal():
    """The opening of the prompt no longer singles out food, tax and coins as the stakes of life."""
    head = llm.SYSTEM.split("Whenever you are free to act")[0].lower()
    assert not any(w in head for w in ("food", "tax", "coin", "trader"))


def test_goals_survive_a_save(tmp_path):
    _, agents, _ = stub_village(tmp_path)
    state = saves._agent_state(next(iter(agents.values())))
    assert state["goals"] == {"about_me": state["goals"]["about_me"], "wants": "A quiet life.",
                              "plan": "Work and eat.", "introduced": True}
