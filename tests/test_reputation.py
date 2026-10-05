"""Reputation and rumors: subjective tallies from seen deeds, rumors stored but never scored."""

import pytest

from aivillage import engine, ops
from aivillage.invariants import check
from aivillage.state import World


@pytest.fixture
def w():
    return engine.new_world({"seed": 1})


def put(w, loc, *names):
    for n in names:
        w.agents[n].location = loc


def act(w, name, action, **args):
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def test_witnessed_theft_lowers_thief_for_witness_and_victim(w):
    w.config["steal_notice_chance"] = 1.0
    w.config["steal_awake_target_success"] = 1.0
    put(w, "square", "Anna", "Boris", "Clara")
    ops.mint(w, w.agents["Boris"].inventory, "fish", 3)
    act(w, "Anna", "steal", target="Boris", item="fish", qty=1)
    for who in ("Boris", "Clara"):
        rec = w.agents[who].reputation["Anna"]
        assert rec["score"] < 0 and "Anna" in rec["seen"][-1]
    assert "Anna" not in w.agents["Anna"].reputation
    obs = engine.observe(w, "Clara")
    assert obs["reputation"]["Anna"]["score"] == w.config["reputation"]["deltas"]["witness"]


def test_trade_and_repay_raise_score_default_lowers_for_everyone(w):
    put(w, "square", "Anna", "Boris")
    ops.mint(w, w.agents["Anna"].inventory, "fish", 1)
    act(w, "Anna", "offer", to="Boris", give={"fish": 1}, want={"coins": 1})
    act(w, "Boris", "accept", offer_id=next(iter(w.offers)))
    assert w.agents["Anna"].reputation["Boris"]["score"] == 1
    assert w.agents["Boris"].reputation["Anna"]["score"] == 1
    act(w, "Anna", "lend", to="Boris", coins=5, repay_coins=5, due_day=2)
    debt = next(iter(w.debts))
    act(w, "Boris", "repay", debt_id=debt, coins=5)
    assert w.agents["Clara"].reputation["Boris"]["score"] == 2  # public, on time
    act(w, "Boris", "lend", to="Anna", coins=3, repay_coins=4, due_day=w.day + 1)
    for _ in range(60):
        if any(d.status == "defaulted" for d in w.debts.values()):
            break
        engine.step(w, {})
    assert w.agents["Clara"].reputation["Anna"]["score"] == w.config["reputation"]["deltas"]["default"]


def test_fire_helper_gains_public_reputation(w):
    engine.step(w, {}, [{"name": "fire", "args": {"person": "Boris"}}])
    home = w.agents["Boris"].home
    put(w, home, "Anna")
    ops.mint(w, w.agents["Anna"].inventory, "water", 10)
    for _ in range(w.fires[home].water_needed):
        act(w, "Anna", "extinguish")
    assert home not in w.fires
    assert w.agents["Dmitri"].reputation["Anna"]["score"] >= w.config["reputation"]["deltas"]["fire_out"]


def test_gossip_is_stored_with_source_and_never_scored(w):
    put(w, "square", "Anna", "Boris", "Clara")
    ev = act(w, "Anna", "gossip", about="Dmitri", text="Dmitri steals from chests")
    assert not [e for e in ev if e.kind == "error"]
    for who in ("Boris", "Clara"):
        r = w.agents[who].rumors[-1]
        assert r == {"day": 1, "from": "Anna", "about": "Dmitri", "text": "Dmitri steals from chests"}
        assert "Dmitri" not in w.agents[who].reputation
    assert engine.observe(w, "Boris")["rumors"][-1]["from"] == "Anna"
    assert not w.agents["Anna"].rumors and not w.agents["Dmitri"].rumors
    from aivillage.run import view  # the viewer's dossier reads rumors from the log's view
    social = view(w)["social"]
    assert social["Boris"]["rumors"][-1]["about"] == "Dmitri" and "Anna" not in social


def test_gossip_to_one_person_and_errors(w):
    put(w, "square", "Anna", "Boris", "Clara")
    act(w, "Anna", "gossip", about="Elena", text="pays every debt", to="Boris")
    assert w.agents["Boris"].rumors and not w.agents["Clara"].rumors
    before = w.hash()
    for bad in ({"about": "Anna", "text": "x"}, {"about": "Nobody", "text": "x"},
                {"about": "Elena", "text": "   "}, {"about": "Elena", "text": "x", "to": "Dmitri"},
                {"about": "Boris", "text": "x", "to": "Boris"}):
        ev = act(w, "Anna", "gossip", **bad)
        assert any(e.kind == "error" for e in ev), bad
    assert w.agents["Boris"].rumors == [w.agents["Boris"].rumors[0]]
    assert before != w.hash()  # time moved, but no rumor was added


def test_rumors_and_notes_are_capped(w):
    cap = w.config["reputation"]["rumors_kept"]
    put(w, "square", "Anna", "Boris")
    for i in range(cap + 3):
        act(w, "Anna", "gossip", about="Clara", text=f"rumor {i}")
    assert len(w.agents["Boris"].rumors) == cap and w.agents["Boris"].rumors[-1]["text"] == f"rumor {cap + 2}"


def test_disabled_and_old_state_load(w):
    off = engine.new_world({"reputation": {"enabled": False}})
    put(off, "square", "Anna", "Boris")
    act(off, "Anna", "gossip", about="Clara", text="hi")
    assert not off.agents["Boris"].rumors and "rumors" not in engine.observe(off, "Boris")
    d = w.to_dict()
    for a in d["agents"].values():
        del a["reputation"], a["rumors"]
    assert World.from_dict(d).agents["Anna"].reputation == {}
