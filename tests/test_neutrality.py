"""Everything the villager model reads stays neutral (dossier item 8), the handbook is built from the
action registry, and the cooking hint (item 9) states facts only.

If the neutrality scan fails after you changed a text the model reads, rephrase it as a plain fact of the
world (what happens, what it costs), never as advice or a judgement. Widening `ALLOWED` needs the owner's OK.
"""

import json
import re

from aivillage import engine, handbook, llm, modes, runconfig
from aivillage.registry import ACTIONS, NoArgs
from aivillage.run import bots_decider, llm_agents, run

# Advice, judgement and morality words. Facts like "the best weapon you carry is used" stay allowed.
EVALUATIVE = re.compile(
    r"\b(should|shouldn't|ought|better (?:to|off|if)|is better|worth it|worthwhile|wise(?:ly)?|smart|clever|"
    r"foolish|stupid|recommend\w*|advis\w*|suggest\w*|consider|good idea|bad idea|make sure|(?:don't|do not) forget|"
    r"profitable|lucrative|selfish|evil|wicked|virtu\w*|moral\w*|ethic\w*|good deeds?|bad deeds?|the right thing|"
    r"it pays to|best to|best way|you (?:may|might) want|be careful|cooperat\w*|help each other|work together)\b",
    re.I)
ALLOWED: set[str] = set()


def evaluative(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in EVALUATIVE.finditer(text)} - ALLOWED)


def neutral_agents(mode: str, **rc) -> dict:
    w = engine.new_world(runconfig.RunConfig(mode=mode, **rc).world_override())
    return w, llm_agents(w, {n: "stub" for n in w.agents})


def test_villager_prompts_are_neutral_in_every_mode():
    for mode in modes.MODES:
        w, agents = neutral_agents(mode, characters="off")
        a = next(iter(agents.values()))
        system, user = (m["content"] for m in a.messages(engine.observe(w, a.name, consume_inbox=False)))
        reflect = llm.REFLECT.format(name=a.name, profession=a.profession, words=llm.DIARY_WORDS, character="")
        for text in (system, user, reflect):
            assert evaluative(text) == [], (mode, evaluative(text))


def test_event_and_error_texts_are_neutral():
    """Fuzz bots touch every action; every observation they get (news, errors, board) is scanned."""
    for mode in ("standard", "crafts"):
        w = engine.new_world(runconfig.RunConfig(mode=mode, seed=4).world_override())
        bots = bots_decider(w, ["random", "thief", "worker"], 4)
        found: set[str] = set()

        def decide(name, obs, _bots=bots):
            found.update(evaluative(json.dumps(obs)))
            return _bots(name, obs)
        decide.bots = bots.bots
        run(w, decide, days=3)
        assert found == set(), (mode, found)


def test_characters_off_neutralises_everyone():
    rc = dict(agents=[{"name": "Anna", "profession": "farmer", "character": "sly"},
                      {"name": "Boris", "profession": "fisher", "character": "You love fishing jokes."}])
    _, agents = neutral_agents("standard", characters="off", **rc)
    assert all(a.character == "" for a in agents.values())
    _, agents = neutral_agents("standard", **rc)  # "default" keeps own characters (show runs)
    assert agents["Anna"].character == llm.CHARACTERS["sly"]


def test_handbook_lists_every_action_once_by_topic():
    text = handbook.text()
    for name in ACTIONS.specs:
        assert text.count(f"\n{name}(") == 1, name
    assert text.index("[Body and time]") < text.index("[Taking and force]")
    off = handbook.text(frozenset({"steal"}))
    assert "\nsteal(" not in off


def test_new_action_appears_in_handbook_by_itself():
    @ACTIONS.action("_hb_probe", "A probe action registered by a test.", NoArgs)
    def _probe(ctx, a, args):
        pass
    try:
        assert "[Other]\n_hb_probe(): A probe action registered by a test." in handbook.text()
    finally:
        del ACTIONS.specs["_hb_probe"]


def test_craft_hint_lists_what_own_goods_make():
    w = engine.new_world(runconfig.RunConfig(mode="crafts").world_override())
    a = next(x for x in w.agents.values() if x.profession != "smith")
    a.inventory.clear()
    a.inventory.update({"grain": 5, "wood": 4, "ore": 3})
    you = engine.observe(w, a.name, consume_inbox=False)["you"]
    assert you["can_craft_now"]["bread"] == {"times": 2, "where": "your home"}
    assert "tool" not in you["can_craft_now"]  # smith only
    assert "fish_soup" not in you["can_craft_now"]
    assert you["not_edible"]["grain"].startswith("not food")
    assert "ore" not in you["not_edible"]

    w.config["craft_hint"] = False
    you = engine.observe(w, a.name, consume_inbox=False)["you"]
    assert "can_craft_now" not in you and "not_edible" not in you
