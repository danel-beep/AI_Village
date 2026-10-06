"""The honor board (aivillage/honors.py): villagers praise each other in public notes, laws of the village or of
a polity give titles. The world sets no criteria and attaches nothing to a note or a title."""

from aivillage import chronicle, engine, honors, modes
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, replay, run

from test_neutrality import evaluative

CFG = {"seed": 1, "honors": {"enabled": True}}


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def act(w, name, action, **args):
    for _ in range(200):
        if engine.needs_decision(w, name):
            return step(w, {name: (action, args)})
        step(w)
    raise AssertionError(f"{name} never got a turn")


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def test_praise_pins_a_public_note_once_a_day():
    w = engine.new_world(CFG)
    coins = {n: a.coins for n, a in w.agents.items()}
    events = act(w, "Anna", "praise", person="Boris", text="  fixed   my roof ")
    ev = next(e for e in events if e.kind == "praise")
    assert ev.visibility == "public" and ev.data["person"] == "Boris" and ev.data["note"] == "fixed my roof"
    board = engine.observe(w, "Clara")["honor_board"]
    assert board["notes"] == [{"day": 1, "by": "Anna", "about": "Boris", "text": "fixed my roof"}]
    assert engine.observe(w, "Anna")["honor_board"]["your_notes_left_today"] == 0
    assert errors(act(w, "Anna", "praise", person="Clara", text="kind"))  # one a day
    assert errors(act(w, "Clara", "praise", person="Clara", text="me"))  # not about oneself
    assert errors(act(w, "Clara", "praise", person="Boris", text="   "))
    assert {n: a.coins for n, a in w.agents.items()} == coins  # nothing else comes with a note
    while w.day < 2:
        step(w)
    assert not errors(act(w, "Anna", "praise", person="Clara", text="kind"))


def test_board_keeps_the_last_notes():
    w = engine.new_world({**CFG, "honors": {"enabled": True, "per_day": 5, "keep": 3, "show": 2}})
    for i in range(5):
        act(w, "Anna", "praise", person="Boris", text=f"note {i}")
    assert [n["text"] for n in w.honors["notes"]] == ["note 2", "note 3", "note 4"]
    assert [n["text"] for n in engine.observe(w, "Boris")["honor_board"]["notes"]] == ["note 3", "note 4"]


def test_off_by_default_and_hash_unchanged():
    w = engine.new_world({"seed": 1})
    assert "honor_board" not in engine.observe(w, "Anna")
    assert errors(act(w, "Anna", "praise", person="Boris", text="x"))
    assert "honors" not in w.to_dict()
    assert all("text" not in p for p in w.to_dict()["governance"]["proposals"].values())


def test_village_law_gives_a_title():
    w = engine.new_world(CFG)
    act(w, "Anna", "run_for_mayor", pitch="order")
    while w.day < 2:
        step(w)
    step(w, {n: ("vote", {"candidate": "Anna"}) for n in w.agents})
    while w.day < 3:
        step(w)
    assert w.governance.mayor == "Anna"
    assert errors(act(w, "Anna", "propose_law", law="title", person="Boris"))  # no words
    events = act(w, "Anna", "propose_law", law="title", person="Boris", text="Keeper of the Well")
    pid = next(e.data["law"] for e in events if e.kind == "law_proposed")
    act(w, "Boris", "vote_law", proposal_id=pid, vote="yes")
    events = act(w, "Clara", "vote_law", proposal_id=pid, vote="yes")
    assert "law_passed" in [e.kind for e in events]
    given = next(e for e in events if e.kind == "title_given")
    assert given.data == {"person": "Boris", "honor": "Keeper of the Well", "by": "the village"}
    assert engine.observe(w, "Elena")["honor_board"]["titles"] == {"Boris": ["Keeper of the Well (from the village, day 3)"]}


def test_polity_law_gives_a_title_to_a_member():
    from test_polity import act as pact, errors as perrors, found, names, world
    w = world()
    a, b, c, d, *_ = names(w)
    p = found(w, [a, b, c], name="North", coin="mark", form="ruler", leader=lambda n: a)
    assert perrors(pact(w, a, "polity_propose", law="title", person=d, text="Friend"), a)  # not a member
    events = pact(w, a, "polity_propose", law="title", person=b, text="First Builder")
    assert any(e.kind == "polity_law_passed" for e in events)
    assert w.honors["titles"][b][0]["title"] == "First Builder" and w.honors["titles"][b][0]["by"] == p["name"]


def test_chronicle_names_who_was_praised():
    w = engine.new_world({**CFG, "chronicle": {"enabled": True}})
    act(w, "Anna", "praise", person="Boris", text="thanks")
    act(w, "Clara", "praise", person="Boris", text="thanks too")
    assert "Praised on the honor board: Boris x2." in chronicle.report(w)


def test_on_in_crafts_and_survival_facts_are_neutral():
    for mode in ("crafts", "survival"):
        cfg = engine.new_world(modes.world_override(mode, {"seed": 1})).config
        assert honors.enabled(cfg)
        assert "honor board" in world_facts(cfg) and not evaluative(honors.facts(cfg))
    assert not honors.enabled(engine.new_world(modes.world_override("standard", {"seed": 1})).config)


def test_view_and_replay(tmp_path):
    log = tmp_path / "h.jsonl"
    w = engine.new_world({**CFG, "honors": {"enabled": True, "per_day": 3}})
    run(w, bots_decider(w, ["random"], 3), days=2, log_path=log)
    assert w.honors["notes"]  # the fuzzer praises too
    assert replay(log).hash() == w.hash()
    from aivillage.run import view
    assert view(w)["honors"]["notes"] == w.honors["notes"]
