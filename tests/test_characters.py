"""Villager characters: neutral default prompt, presets, custom text, seeded random."""

from aivillage import engine, llm, runconfig
from aivillage.run import llm_agents


def agents_for(rc: runconfig.RunConfig) -> dict:
    w = engine.new_world(rc.world_override())
    return llm_agents(w, {n: "stub" for n in w.agents})


def system(agent) -> str:
    return agent.messages({"board": {"recipes": {}, "trader_prices": {}}, "fires": [], "offers_to_you": [],
                           "your_offers": []})[0]["content"]


def test_default_prompt_is_neutral():
    a = agents_for(runconfig.RunConfig())["Anna"]
    text = system(a).lower()
    assert a.character == ""
    for nudge in ("lie, steal", "betray", "usually better", "nobody tells you what is right", "ask a neighbour"):
        assert nudge not in text


def test_preset_custom_and_default_per_agent():
    rc = runconfig.RunConfig(agents=[{"name": "Anna", "profession": "farmer", "character": "aggressive"},
                                     {"name": "Boris", "profession": "fisher", "character": "You love fishing jokes."},
                                     {"name": "Clara", "profession": "woodcutter", "character": "default"}],
                             characters="random")
    ag = agents_for(rc)
    assert llm.CHARACTERS["aggressive"] in system(ag["Anna"])
    assert "You love fishing jokes." in system(ag["Boris"])
    assert ag["Clara"].character == ""


def test_random_is_seeded():
    a = {n: x.character for n, x in agents_for(runconfig.RunConfig(characters="random")).items()}
    b = {n: x.character for n, x in agents_for(runconfig.RunConfig(characters="random")).items()}
    assert a == b and all(c in llm.CHARACTERS.values() for c in a.values())


def test_reflect_prompt_carries_character():
    ag = agents_for(runconfig.RunConfig(agents=[{"name": "Anna", "profession": "farmer", "character": "honest"}]))
    a = ag["Anna"]
    a.day_log = ["6:00 at home: I did wait"]
    seen = []
    a.client.complete = lambda msgs: (seen.append(msgs[0]["content"]) or ('{"diary": "ok", "people": {}}', {}))
    a.reflect(1)
    assert llm.CHARACTERS["honest"] in seen[0]
