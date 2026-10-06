"""Dice for coins (aivillage/dice.py): challenge, answer, stake moves, losing on credit, replay."""

import pytest

from aivillage import engine
from aivillage.invariants import check
from aivillage.run import bots_decider, replay, run


@pytest.fixture
def w():
    w = engine.new_world({"seed": 3, "crises": {"enabled": False}})
    for a in w.agents.values():
        a.location = "square"
    return w


def act(w, name, action, args=None):
    w.agents[name].last_error = None
    events = engine.step(w, {name: {"thought": "", "action": {"name": action, "args": args or {}}}})
    check(w)
    return w.agents[name].last_error, events


def test_challenge_then_answer_plays_and_moves_the_stake(w):
    a, b = list(w.agents)[:2]
    before = w.agents[a].coins + w.agents[b].coins
    err, ev = act(w, a, "dice", {"person": b, "stake": 5})
    assert err is None and any(e.kind == "dice_challenge" for e in ev)
    obs = engine.observe(w, b)
    assert obs["dice_challenges_to_you"] == [{"from": a, "stake": 5}]
    assert "dice" in obs["available_actions"]
    err, ev = act(w, b, "dice", {"person": a, "stake": 5})
    game = next(e for e in ev if e.kind == "dice")
    assert err is None and w.agents[a].dice_offer is None
    assert w.agents[a].coins + w.agents[b].coins == before
    if game.data["winner"]:
        assert w.agents[game.data["winner"]].coins > w.agents[game.data["loser"]].coins - 1


def test_counter_offer_does_not_play(w):
    a, b = list(w.agents)[:2]
    act(w, a, "dice", {"person": b, "stake": 5})
    err, ev = act(w, b, "dice", {"person": a, "stake": 9})
    assert err is None and [e.kind for e in ev if e.kind.startswith("dice")] == ["dice_challenge"]
    assert w.agents[b].dice_offer["stake"] == 9


def test_loser_short_of_coins_owes_the_rest(w):
    a, b = list(w.agents)[:2]
    w.config["dice"]["rerolls"] = 50
    stake = w.config["dice"]["credit"]
    for name in (a, b):  # empty pockets: the whole stake is on credit
        w.ledger["coins"] -= w.agents[name].coins
        w.agents[name].coins = 0
    act(w, a, "dice", {"person": b, "stake": stake})
    _, ev = act(w, b, "dice", {"person": a, "stake": stake})
    game = next(e for e in ev if e.kind == "dice")
    d = w.debts[game.data["debt"]]
    assert (d.lender, d.borrower, d.coins_owed) == (game.data["winner"], game.data["loser"], stake)


def test_limits(w):
    a, b = list(w.agents)[:2]
    c = w.config["dice"]
    assert act(w, a, "dice", {"person": b, "stake": c["max_stake"] + 1})[0]
    assert act(w, a, "dice", {"person": b, "stake": w.agents[b].coins + c["credit"] + 1})[0]
    w.agents[a].location = "market"
    assert "dice" not in engine.observe(w, a)["available_actions"]
    assert act(w, a, "dice", {"person": b, "stake": 1})[0]


def test_challenge_expires(w):
    a, b = list(w.agents)[:2]
    act(w, a, "dice", {"person": b, "stake": 5})
    for _ in range(w.config["dice"]["offer_hours"] * 4 + 1):
        engine.step(w, {})
    assert engine.observe(w, b)["dice_challenges_to_you"] == []


def test_random_bots_gamble_and_replay(tmp_path):
    log = str(tmp_path / "run.jsonl")
    w = engine.new_world({"seed": 5, "crises": {"enabled": False},
                          "dice": {"places": ["square", "market", "forest", "river"]}})
    run(w, bots_decider(w, ["random"], 5), days=2, log_path=log)
    assert replay(log).hash() == w.hash()
