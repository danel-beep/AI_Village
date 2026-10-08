"""Turn-taking talk (aivillage/talk.py): villagers at one place take turns within a tick and hear each other."""

import json

from aivillage import engine, talk
from aivillage.invariants import check
from aivillage.run import bots_decider, read_log, replay, run


def world(**talk_cfg):
    w = engine.new_world({"seed": 1, "talk": {"turn_taking": True, **talk_cfg}})
    for n in ("Anna", "Boris", "Clara"):
        w.agents[n].location = "square"
    return w


def recorder(script):
    """A decider that answers from `script` and remembers every observation, in the order it was asked."""
    seen = []

    def decide(name, obs):
        seen.append((name, obs))
        return script.get(name, {"action": {"name": "wait"}})
    return decide, seen


def test_people_at_one_place_take_turns_and_hear_the_earlier_ones(tmp_path):
    w = world()
    order = talk.groups(w, engine.waiting_agents(w))[0]
    assert sorted(order) == ["Anna", "Boris", "Clara"]
    decide, seen = recorder({n: {"say": f"Hello, I am {n}"} for n in w.agents})
    run(w, decide, days=1, log_path=tmp_path / "run.jsonl")
    first = {}
    for n, obs in seen:
        first.setdefault(n, obs)
    # the first speaker heard nothing, each later one everybody before it
    assert "just_said" not in first[order[0]]
    assert first[order[1]]["just_said"] == [{"who": order[0], "say": f"Hello, I am {order[0]}"}]
    assert [x["who"] for x in first[order[2]]["just_said"]] == order[:2]
    # people elsewhere take no turns and hear nothing
    assert "just_said" not in first["Dmitri"] and "just_said" not in first["Elena"]
    tick = next(r for r in read_log(tmp_path / "run.jsonl") if r.get("type") == "tick")
    assert tick["talk"] == [order]


def test_the_answer_runs_after_the_question():
    w = world()
    order = talk.groups(w, engine.waiting_agents(w))[0]
    a, b = order[0], order[1]
    decisions = {a: {"say": f"{b}, can you help?"}, b: {"say": f"Yes, {a}."}}
    events = engine.step(w, decisions, [], [order])
    said = [e.actor for e in events if e.kind == "say"]
    assert said == [a, b]


def test_turn_order_keeps_everybody_elses_seat():
    order = ["Elena", "Clara", "Dmitri", "Anna", "Boris"]
    assert talk.in_turn_order(order, [["Anna", "Clara"]]) == ["Elena", "Anna", "Dmitri", "Clara", "Boris"]
    assert talk.in_turn_order(order, None) == order


def test_secrets_stay_secret_and_whispers_reach_only_their_listener():
    earlier = [
        ("Anna", {"action": {"name": "steal", "args": {"target": "Clara", "item": "bread"}}}),
        ("Boris", {"action": {"name": "whisper", "args": {"to": "Clara", "text": "meet me at night"}}}),
        ("Dmitri", {"say": "Nice day", "action": {"name": "give", "args": {"to": "Elena", "items": {"fish": 1}}}}),
        ("Elena", {"action": {"name": "offer", "args": {"to": "Clara", "give": {"fish": 1}, "want": {"wood": 2}}}}),
    ]
    for_clara = talk.just_said("Clara", earlier)
    assert for_clara == [{"who": "Boris", "whispers_to_you": "meet me at night"},
                         {"who": "Dmitri", "say": "Nice day", "does": "give", "to": "Elena"},
                         {"who": "Elena", "does": "offer", "to": "Clara"}]
    assert talk.just_said("Fyodor", earlier) == [{"who": "Dmitri", "say": "Nice day", "does": "give", "to": "Elena"}]


def test_a_crowd_is_split_into_waves():
    w = world(waves=2)
    assert talk.waves(w, ["A", "B", "C", "D", "E"]) == [["A", "B", "C"], ["D", "E"]]
    assert talk.waves(world(waves=0), ["A", "B", "C"]) == [["A"], ["B"], ["C"]]


def test_turn_taking_off_changes_nothing():
    w = engine.new_world({"seed": 1})
    for n in ("Anna", "Boris"):
        w.agents[n].location = "square"
    assert talk.groups(w, engine.waiting_agents(w)) == []
    del w.config["talk"]  # an old log or save without the key
    assert talk.groups(w, engine.waiting_agents(w)) == []


def test_replay_with_turn_taking(tmp_path):
    w = engine.new_world({"seed": 4, "talk": {"turn_taking": True}})
    log = tmp_path / "run.jsonl"
    run(w, bots_decider(w, ["worker", "thief", "random"], 4), days=4, log_path=log)
    recs = list(read_log(log))
    assert any(r.get("talk") for r in recs if r.get("type") == "tick")
    assert replay(log).hash() == w.hash()


def test_old_logs_without_talk_still_replay(tmp_path):
    w = engine.new_world({"seed": 4})  # off by default: logs look exactly like before
    log = tmp_path / "old.jsonl"
    run(w, bots_decider(w, ["worker", "thief", "random"], 4), days=2, log_path=log)
    recs = list(read_log(log))
    assert recs[0]["config"]["talk"]["turn_taking"] is False
    assert not any("talk" in r for r in recs if r.get("type") == "tick")
    assert replay(log).hash() == w.hash()


def test_spoken_to_while_busy_answers_now_and_owes_the_rest():
    w = world(interrupt_pause=True)
    anna = w.agents["Anna"]
    anna.busy_until = w.tick + 5  # Anna is in the middle of a long job
    events = engine.step(w, {"Boris": {"say": "Anna, a word?"}}, [])
    assert any(e.kind == "say" for e in events)
    assert anna.busy_until == w.tick and anna.time_debt == 4
    assert "Anna" in engine.waiting_agents(w)
    start = w.tick
    engine.step(w, {"Anna": {"say": "Yes?"}}, [])
    assert anna.time_debt == 0
    # the quick answer plus the four ticks still owed: the job's time is not lost
    assert anna.busy_until == start + engine.clock.action_ticks(w.config, "say") + 4
    check(w)
    assert not w.agents["Boris"].time_debt


def test_without_the_pause_a_busy_villager_answers_later():
    w = world()
    anna = w.agents["Anna"]
    anna.busy_until = w.tick + 5
    engine.step(w, {"Boris": {"say": "Anna, a word?"}}, [])
    assert anna.busy_until == w.tick + 4 and anna.time_debt == 0


def test_a_letter_from_afar_does_not_pause_work():
    w = world(interrupt_pause=True)
    elena = w.agents["Elena"]  # at home, far from Boris on the square
    elena.busy_until = w.tick + 5
    engine.step(w, {"Boris": {"say": "Elena!"}}, [])
    assert elena.time_debt == 0


def test_handbook_line_only_when_on():
    assert talk.facts({"talk": {"turn_taking": True}})
    assert talk.facts({"talk": {"turn_taking": False}}) is None
    assert talk.facts({}) is None


def test_just_said_reaches_the_model_in_the_current_observation():
    from aivillage.llm import LLMAgent
    from tests.test_llm_memory import Echo
    w = world()
    obs = engine.observe(w, "Anna")
    obs["just_said"] = [{"who": "Boris", "say": "Anna, fish for bread?"}]
    for mode in ("changes", "full"):
        c = Echo()
        LLMAgent("Anna", "farmer", c, memory="day", obs_mode=mode).decide(json.loads(json.dumps(obs)))
        assert "Anna, fish for bread?" in c.calls[-1][-1]["content"]
