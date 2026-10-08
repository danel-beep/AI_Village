import json

from aivillage import engine
from aivillage.llm import DIARY_WORDS, LLMAgent, compact_obs, parse_decision
from aivillage.run import llm_agents, night_reflection, read_log, replay, run


def test_parse_plain_and_wrapped_json():
    assert parse_decision('{"action": {"name": "wait"}}')["action"]["name"] == "wait"
    d = parse_decision('Sure!\n```json\n{"thought": "a {b} \\"c\\"", "action": {"name": "eat", "args": {"item": "bread"}}}\n``` bye}')
    assert d["action"]["args"] == {"item": "bread"}
    d = parse_decision('I think {"x": 1} then {"action": {"name": "sleep"}}')
    assert d["action"]["name"] == "sleep"


def test_parse_garbage_becomes_wait():
    for text in ["", "no json here", "{broken", '{"no_action": 1}']:
        assert parse_decision(text)["action"]["name"] == "wait"


def test_parse_action_given_as_a_bare_name():
    assert parse_decision('{"thought": "t", "action": "eat"}')["action"] == {"name": "eat"}
    assert parse_decision('{"action": null}')["action"] == {"name": "wait"}


class Boom:
    model = "boom"

    def complete(self, messages):
        raise RuntimeError("provider down")


def test_dead_provider_means_wait_not_crash():
    w = engine.new_world()
    agent = LLMAgent("Anna", "farmer", Boom())
    assert agent.decide(engine.observe(w, "Anna"))["action"]["name"] == "wait"
    assert agent.usage.failures == 1


def test_compact_obs_is_smaller():
    w = engine.new_world()
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert len(str(compact_obs(obs))) < len(str(obs))


def test_stub_llm_village_runs_and_replays(tmp_path):
    w = engine.new_world({"seed": 2})
    agents = llm_agents(w, ["stub"])
    log = tmp_path / "llm.jsonl"
    run(w, lambda n, o: agents[n].decide(o), days=3, log_path=log)
    assert all(a.usage.calls > 0 and a.usage.failures == 0 for a in agents.values())
    assert replay(log).hash() == w.hash()


def test_notes_persist_between_turns():
    class Noter:
        model = "noter"

        def complete(self, messages):
            return '{"action": {"name": "wait"}, "notes": "Boris owes me"}', {}

    w = engine.new_world()
    agent = LLMAgent("Anna", "farmer", Noter())
    agent.decide(engine.observe(w, "Anna"))
    assert agent.notes == "Boris owes me"
    assert "Boris owes me" in agent.messages(engine.observe(w, "Anna"))[-1]["content"]


class Diarist:
    """Answers turns with `wait` and nights with a fixed diary."""
    model = "diarist"

    def __init__(self, diary="I trust nobody. " * 100, people=None):
        self.diary, self.people, self.calls = diary, people or {}, []

    def complete(self, messages):
        self.calls.append(messages)
        if messages[-1]["content"].startswith("End of day"):
            return json.dumps({"diary": self.diary, "people": self.people}), {}
        return '{"action": {"name": "wait"}, "say": "hello Boris"}', {}


def test_reflect_writes_short_diary_and_people_memory():
    w = engine.new_world()
    c = Diarist(people={"Boris": "Owes me 3 coins.", "Nobody": "made up", "Anna": "me"})
    agent = LLMAgent("Anna", "farmer", c)
    assert agent.reflect(1) is None  # nothing happened yet: no call
    agent.decide(engine.observe(w, "Anna"))
    assert any("hello Boris" in line for line in agent.day_log)
    entry = agent.reflect(1)
    assert entry["day"] == 1 and len(entry["text"].split()) <= DIARY_WORDS
    assert agent.people == {"Boris": "Owes me 3 coins."}  # unknown names and self are dropped
    assert agent.day_log == []
    prompt = "".join(m["content"] for m in agent.messages(engine.observe(w, "Anna")))
    assert "Owes me 3 coins." in prompt and "I trust nobody." in prompt


def test_reflect_failure_keeps_memory():
    w = engine.new_world()
    agent = LLMAgent("Anna", "farmer", Diarist(), people={"Boris": "friend"})
    agent.decide(engine.observe(w, "Anna"))
    agent.client = Boom()
    assert agent.reflect(1) is None and agent.people == {"Boris": "friend"} and agent.usage.failures == 2  # retried once


def test_night_diary_logged_and_replay_ignores_it(tmp_path):
    w = engine.new_world({"seed": 3})
    agents = llm_agents(w, ["stub"])
    log = tmp_path / "llm.jsonl"
    run(w, lambda n, o: agents[n].decide(o), days=2, log_path=log,
        on_night=lambda world, day: night_reflection(world, agents, day))
    diaries = [r for r in read_log(log) if r["type"] == "diary"]
    assert [r["day"] for r in diaries] == [1, 2]
    assert set(diaries[0]["entries"]) == set(agents)
    assert all(a.diary for a in agents.values())
    assert replay(log).hash() == w.hash()


def test_cost_cap_stops_the_run_early_and_log_still_replays(tmp_path):
    w = engine.new_world({"seed": 2})
    agents = llm_agents(w, ["stub"])
    for ag in agents.values():  # the stub is free: pretend each turn costs a cent
        ag.client.complete = (lambda f: lambda m: (lambda r: (r[0], {**r[1], "cost": 0.01}))(f(m)))(ag.client.complete)

    def decide(n, o):
        return agents[n].decide(o)
    decide.agents = agents
    log = tmp_path / "cap.jsonl"
    stats = run(w, decide, days=3, log_path=log, max_cost=0.2)
    spent = sum(a.usage.cost_usd for a in agents.values())
    assert stats["stopped_at_cost_cap"] == 1 and 0.2 <= spent < 0.3 and w.day == 1
    recs = list(read_log(log))
    assert any(r["type"] == "stop" for r in recs) and recs[-1]["type"] == "usage"
    assert replay(log).hash() == w.hash()


class Hung:
    """Answers only when released: a provider that hangs."""
    model = "hung"

    def __init__(self):
        import threading
        self.release, self.calls = threading.Event(), 0

    def complete(self, messages):
        self.calls += 1
        self.release.wait(10)
        return json.dumps({"thought": "late", "action": {"name": "sleep"}}), {"cost": 0.25, "prompt_tokens": 10}


def test_hung_model_waits_this_turn_and_late_answer_is_dropped():
    # Audit task 7: one hung call must not hold the whole tick; the answer that comes later is not acted on,
    # but what it cost is still counted.
    import time
    w = engine.new_world()
    c = Hung()
    agent = LLMAgent("Anna", "farmer", c, decision_timeout_s=0.2)
    t0 = time.monotonic()
    dec = agent.decide(engine.observe(w, "Anna"))
    assert time.monotonic() - t0 < 2
    assert dec["action"] == {"name": "wait"} and "no answer in 0.2 s" in dec["thought"]
    assert agent.usage.failures == 1 and agent.usage.cost_usd == 0 and agent.recent == []
    c.release.set()
    end = time.monotonic() + 5
    while agent.usage.cost_usd == 0 and time.monotonic() < end:
        time.sleep(0.01)
    assert agent.usage.cost_usd == 0.25 and agent.usage.calls == 1 and agent.recent == []
    # Without a deadline (a player's own AI, the stub) the answer is waited for.
    agent2 = LLMAgent("Anna", "farmer", c)
    assert agent2.decide(engine.observe(w, "Anna"))["action"]["name"] == "sleep"


def test_live_villagers_get_the_deadline_stub_does_not(monkeypatch):
    import aivillage.llm as llm_mod
    w = engine.new_world()
    assert all(a.decision_timeout_s is None for a in llm_agents(w, ["stub"]).values())
    monkeypatch.setattr(llm_mod, "make_client", lambda m, fallbacks=None: llm_mod.StubClient("x"))
    agents = llm_agents(w, ["some/model"])
    assert all(a.decision_timeout_s == llm_mod.DECISION_TIMEOUT_S == 60 for a in agents.values())


def test_in_flight_counts_requests_on_their_way():
    from aivillage import llm
    before = llm.in_flight()
    with llm._sending():
        with llm._sending():
            assert llm.in_flight() == before + 2
    assert llm.in_flight() == before
