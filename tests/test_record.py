"""Book of deeds (reputation.record): harms and help kept apart, no score, debts private, and the villager's
own night choice of what to remember for long."""

import json

import pytest

from aivillage import engine, family, llm, modes, ops
from aivillage.invariants import check
from aivillage.llm import LLMAgent


@pytest.fixture
def w():
    w = engine.new_world({"seed": 1})
    w.config["reputation"].update(record=True, mishear_number=0, mishear_name=0, overhear=0)
    return w


def put(w, loc, *names):
    for n in names:
        w.agents[n].location = loc


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def steal(w, thief, victim, witness):
    w.config["steal_notice_chance"] = 1.0
    w.config["steal_awake_target_success"] = 1.0
    put(w, "square", thief, victim, witness)
    ops.mint(w, w.agents[victim].inventory, "fish", 3)
    act(w, thief, "steal", target=victim, item="fish", qty=1)


def test_harm_survives_any_number_of_good_deeds_and_there_is_no_score(w):
    steal(w, "Anna", "Boris", "Clara")
    rec = w.agents["Clara"].reputation["Anna"]
    assert len(rec["harms"]) == 1 and "score" not in rec
    for _ in range(50):
        ops.mint(w, w.agents["Anna"].inventory, "fish", 1)
        act(w, "Anna", "give", to="Clara", items={"fish": 1})
    rec = w.agents["Clara"].reputation["Anna"]
    assert len(rec["harms"]) == 1 and "steal" in rec["harms"][0]
    assert len(rec["help"]) == w.config["reputation"]["record_keep"]
    gifts = rec["counts"]["give"]  # some fall at night, when Anna sleeps
    assert gifts > 2 * w.config["reputation"]["record_keep"] and rec["counts"]["witness"] == 1
    obs = engine.observe(w, "Clara")
    assert "reputation" not in obs
    shown = obs["record"]["Anna"]
    assert shown["harms"] == rec["harms"] and shown["counts"]["gifts seen"] == gifts
    assert "score" not in json.dumps(obs["record"])


def test_trades_and_village_work_are_only_counted(w):
    put(w, "square", "Anna", "Boris")
    ops.mint(w, w.agents["Anna"].inventory, "fish", 1)
    act(w, "Anna", "offer", to="Boris", give={"fish": 1}, want={"coins": 1})
    act(w, "Boris", "accept", offer_id=next(iter(w.offers)))
    rec = w.agents["Boris"].reputation["Anna"]
    assert rec["counts"] == {"trade": 1} and not rec["help"] and not rec["harms"]


def test_a_loan_stays_between_the_two_sides(w):
    put(w, "square", "Anna", "Boris", "Clara")
    act(w, "Anna", "lend", to="Boris", coins=5, repay_coins=5, due_day=2)
    assert "Anna" in w.agents["Boris"].reputation
    assert "Anna" not in w.agents["Clara"].reputation  # she stood there, but the book keeps no one else's debts


def test_people_long_unseen_drop_out_of_the_view_unless_they_did_harm(w):
    steal(w, "Anna", "Boris", "Clara")
    ops.mint(w, w.agents["Dmitri"].inventory, "fish", 1)
    put(w, "square", "Dmitri")
    act(w, "Dmitri", "give", to="Clara", items={"fish": 1})
    assert {"Anna", "Dmitri"} <= set(engine.observe(w, "Clara")["record"])
    w.day += w.config["reputation"]["record_days"] + 1
    shown = engine.observe(w, "Clara")["record"]
    assert "Anna" in shown and "Dmitri" not in shown


def test_feelings_carry_no_friend_or_enemy_label(w):
    family.change(w, "Anna", "Boris", 50)
    assert engine.observe(w, "Anna")["relations"]["feelings"]["Boris"] == {"score": 50}


def test_record_is_on_in_survival_only_and_off_by_default():
    assert modes.MODES["survival"]["world"]["reputation"]["record"] is True
    assert engine.new_world({"seed": 1}).config["reputation"]["record"] is False
    assert "record" not in engine.observe(engine.new_world({"seed": 1}), "Anna")


# ---- the villager's side (llm.py) ----

class Fake(llm.Client):
    model = "fake"

    def __init__(self, night=None):
        self.night, self.seen = night or {}, []

    def complete(self, messages):
        self.seen.append(messages)
        if messages[-1]["content"].startswith("End of day"):
            return json.dumps({"diary": "A day.", **self.night}), {}
        return json.dumps({"action": {"name": "wait"}}), {}


def test_book_sits_in_the_cached_part_and_stays_the_same_all_day(w):
    steal(w, "Anna", "Boris", "Clara")
    ag = LLMAgent("Clara", "farmer", Fake())
    ag.decide(engine.observe(w, "Clara"))
    sys1, user1 = ag.client.seen[-1][0]["content"], ag.client.seen[-1][-1]["content"]
    assert "what_you_saw_people_do" in sys1 and "steal" in sys1
    assert '"record"' not in user1 and "what_you_saw_people_do" not in user1
    ops.mint(w, w.agents["Anna"].inventory, "fish", 1)
    put(w, "square", "Anna", "Clara")
    act(w, "Anna", "give", to="Clara", items={"fish": 1})
    ag.decide(engine.observe(w, "Clara"))
    assert ag.client.seen[-1][0]["content"] == sys1  # the gift shows up in the book tomorrow, not mid-day
    w.day += 1
    ag.decide(engine.observe(w, "Clara"))
    assert ag.client.seen[-1][0]["content"] != sys1 and "gave" in ag.client.seen[-1][0]["content"]


def test_night_choice_of_what_to_remember(w):
    ag = LLMAgent("Clara", "farmer", Fake({"remember": ["Anna stole fish.", "Boris was kind.", "third"]}))
    ag.decide(engine.observe(w, "Clara"))
    entry = ag.reflect(1)
    assert entry["remember"] == ["Anna stole fish.", "Boris was kind."]
    assert [k["text"] for k in ag.kept] == ["Anna stole fish.", "Boris was kind."]
    system = ag.client.seen[-1][0]["content"]
    assert '"remember"' in system and '"forget"' in system
    ag.client.night = {"remember": [], "forget": [2, 9, True]}
    ag.decide(engine.observe(w, "Clara"))
    entry = ag.reflect(2)
    assert entry["forgot"] == ["Boris was kind."] and [k["text"] for k in ag.kept] == ["Anna stole fish."]
    assert "1. day 1: Anna stole fish." in ag.client.seen[-1][-1]["content"]  # shown to the night's choice
    assert ag.long_memory()["you_chose_to_remember"] == ["1. day 1: Anna stole fish."]
    ag.kept = [{"day": 1, "text": str(i)} for i in range(llm.KEEP_MAX)]
    ag.keep(3, ["new"], None)
    assert len(ag.kept) == llm.KEEP_MAX and ag.kept[-1]["text"] == "new" and ag.kept[0]["text"] == "1"


def test_no_book_no_question():
    w = engine.new_world({"seed": 1})
    ag = LLMAgent("Clara", "farmer", Fake({"remember": ["x"]}))
    ag.decide(engine.observe(w, "Clara"))
    entry = ag.reflect(1)
    assert "remember" not in entry and not ag.kept and '"remember"' not in ag.client.seen[-1][0]["content"]


class Flaky(Fake):
    def __init__(self):
        super().__init__()
        self.fails = 1

    def complete(self, messages):
        if messages[-1]["content"].startswith("End of day") and self.fails:
            self.fails -= 1
            return "sorry, no json", {}
        return super().complete(messages)


def test_a_failed_night_is_retried(w):
    ag = LLMAgent("Clara", "farmer", Flaky())
    ag.decide(engine.observe(w, "Clara"))
    assert ag.reflect(1)["text"] == "A day." and ag.diary
