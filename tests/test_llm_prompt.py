from aivillage import engine
from aivillage.llm import LLMAgent, StubClient, world_facts
from aivillage.run import llm_agents


def test_world_facts_cover_config():
    cfg = engine.new_world({}).config
    facts = world_facts(cfg)
    for item, spec in cfg["items"].items():
        if spec.get("food"):
            assert f"{item} +{spec['food']}" in facts
    for rid in cfg["recipes"]:
        assert f"Craft {rid}:" in facts
    assert "market" in facts


def test_prompt_has_facts_and_recent_actions():
    w = engine.new_world({"seed": 3})
    agents = llm_agents(w, ["stub"])
    name = sorted(agents)[0]
    ag = agents[name]
    assert ag.facts and ag.facts in ag.messages(engine.observe(w, name))[0]["content"]
    for _ in range(4):
        ag.decide(engine.observe(w, name))
    assert 1 <= len(ag.recent) <= 3
    ag.memory = "fresh"
    assert "your_last_actions" in ag.messages(engine.observe(w, name))[1]["content"]
