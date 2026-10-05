from aivillage import engine
from aivillage.llm import LLMAgent, compact_obs, parse_decision
from aivillage.run import llm_agents, replay, run


def test_parse_plain_and_wrapped_json():
    assert parse_decision('{"action": {"name": "wait"}}')["action"]["name"] == "wait"
    d = parse_decision('Sure!\n```json\n{"thought": "a {b} \\"c\\"", "action": {"name": "eat", "args": {"item": "bread"}}}\n``` bye}')
    assert d["action"]["args"] == {"item": "bread"}
    d = parse_decision('I think {"x": 1} then {"action": {"name": "sleep"}}')
    assert d["action"]["name"] == "sleep"


def test_parse_garbage_becomes_wait():
    for text in ["", "no json here", "{broken", '{"no_action": 1}']:
        assert parse_decision(text)["action"]["name"] == "wait"


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
    assert "Boris owes me" in agent.messages(engine.observe(w, "Anna"))[1]["content"]
