"""Reputation and rumors: subjective tallies from seen deeds, rumors stored but never scored."""

import pytest

from aivillage import engine, ops
from aivillage.invariants import check
from aivillage.state import World


@pytest.fixture
def w():
    w = engine.new_world({"seed": 1})
    # Word of mouth off by default here: each test of it turns on what it checks.
    w.config["reputation"].update(mishear_number=0, mishear_name=0, overhear=0)
    return w


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
        assert r == {"id": f"r{w.tick - 1}.Anna", "day": 1, "from": "Anna", "about": "Dmitri",
                     "text": "Dmitri steals from chests", "started_by": "Anna", "retold": 0}
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


# ---- word of mouth: retelling, mishearing, overhearing ----

def test_retold_rumor_keeps_id_and_loses_its_author(w):
    w.config["reputation"]["origin_hops"] = 2
    put(w, "square", "Anna", "Boris")
    act(w, "Anna", "gossip", about="Dmitri", text="Dmitri owes 4 coins", to="Boris")
    rid = w.agents["Boris"].rumors[-1]["id"]
    put(w, "market", "Boris", "Clara")
    act(w, "Boris", "gossip", rumor=rid, to="Clara")  # repeats it word for word
    c = w.agents["Clara"].rumors[-1]
    assert c["id"] == rid and c["from"] == "Boris" and c["started_by"] == "Anna" and c["retold"] == 1
    assert c["text"] == "Dmitri owes 4 coins" and c["about"] == "Dmitri"
    put(w, "river", "Clara", "Elena")
    ev = act(w, "Clara", "gossip", rumor=rid, text="Dmitri never pays back", to="Elena")
    e = w.agents["Elena"].rumors[-1]
    assert e["id"] == rid and e["started_by"] is None and e["retold"] == 2 and e["text"] == "Dmitri never pays back"
    assert any("heard it from someone" in x.text for x in ev if x.kind == "gossip_heard")
    # hearing the same rumor from another mouth: one entry, both tellers remembered
    put(w, "river", "Boris")
    act(w, "Boris", "gossip", rumor=rid, to="Elena")
    mine = [r for r in w.agents["Elena"].rumors if r["id"] == rid]
    assert len(mine) == 1 and mine[0]["from"] == "Boris" and mine[0]["also_from"] == ["Clara"]


def test_retell_errors(w):
    put(w, "square", "Anna", "Boris")
    for bad in ({"rumor": "r999.Nobody"}, {"rumor": "r999.Nobody", "about": "Clara", "text": "x"}):
        ev = act(w, "Anna", "gossip", **bad)
        assert any(e.kind == "error" for e in ev), bad
    ev = act(w, "Anna", "gossip", text="no subject")
    assert any(e.kind == "error" for e in ev)


def test_mishearing_changes_numbers_and_names_and_is_logged(w):
    w.config["reputation"].update(mishear_number=1.0, mishear_name=1.0)
    put(w, "square", "Anna", "Boris")
    ev = act(w, "Anna", "gossip", about="Dmitri", text="Dmitri stole 3 fish", to="Boris")
    r = w.agents["Boris"].rumors[-1]
    assert r["about"] not in ("Dmitri", "Anna", "Boris") and r["about"] in r["text"] and "3 fish" not in r["text"]
    heard = next(e for e in ev if e.kind == "gossip_heard")
    assert heard.data["said"] == "Dmitri stole 3 fish" and len(heard.data["misheard"]) == 2
    assert next(e for e in ev if e.kind == "gossip").data["text_raw"] == "Dmitri stole 3 fish"  # teller's own view


def test_whisper_and_private_gossip_can_be_overheard(w):
    w.config["reputation"]["overhear"] = 1.0
    put(w, "square", "Anna", "Boris", "Clara", "Dmitri")
    ev = act(w, "Anna", "whisper", to="Boris", text="meet me at the mine")
    got = {e.to[0] for e in ev if e.kind == "overheard"}
    assert got == {"Clara", "Dmitri"}
    assert any("meet me at the mine" in x for x in w.agents["Clara"].inbox)
    act(w, "Anna", "gossip", about="Dmitri", text="Dmitri cheats at dice", to="Boris")
    c = w.agents["Clara"].rumors[-1]
    assert c["overheard"] and c["from"] == "Anna" and c["about"] == "Dmitri"
    assert not w.agents["Dmitri"].rumors  # the subject hears it but does not store a rumor about themselves
    assert any("about you" in x for x in w.agents["Dmitri"].inbox)
    w.config["reputation"]["overhear"] = 0
    put(w, "square", "Elena")
    act(w, "Anna", "whisper", to="Boris", text="again")
    assert not any("again" in x for x in w.agents["Elena"].inbox)


@pytest.mark.parametrize("seed", [3, 7])
def test_word_of_mouth_fuzz_replay(tmp_path, seed):
    """Villagers meet at the square and gossip, retell and whisper at random: invariants hold every
    tick, rumors travel several mouths, replay is exact."""
    import random
    from aivillage.run import bots_decider, replay, run
    w = engine.new_world({"seed": seed, "reputation": {"mishear_number": 0.5, "mishear_name": 0.2, "overhear": 0.5},
                          "disabled_actions": ["attack", "set_fire"]})
    rnd, r = bots_decider(w, ["random"], seed), random.Random(seed)

    def decide(name, obs):
        others = [p["name"] for p in obs["here"]["people"] if not p["asleep"]]
        if obs["you"]["location"] != "square":
            return {"action": {"name": "move", "args": {"to": "square"}}} if r.random() < 0.7 else rnd(name, obs)
        if not others or r.random() < 0.3:
            return rnd(name, obs)
        heard = [x["id"] for x in obs.get("rumors", [])]
        to = {"to": r.choice(others)} if r.random() < 0.5 else {}
        if heard and r.random() < 0.6:
            return {"action": {"name": "gossip", "args": {"rumor": r.choice(heard), **to}}}
        if r.random() < 0.3:
            return {"action": {"name": "whisper", "args": {"to": r.choice(others), "text": f"{r.randint(1, 9)} coins"}}}
        about = r.choice([n for n in w.agents if n != name])
        return {"action": {"name": "gossip", "args": {"about": about, "text": f"{about} took {r.randint(1, 9)} fish", **to}}}

    log = tmp_path / "r.jsonl"
    run(w, decide, days=2, log_path=log)
    assert replay(log).hash() == w.hash()
    rumors = [x for a in w.agents.values() for x in a.rumors]
    assert max(x["retold"] for x in rumors) >= 2 and any(x.get("overheard") for x in rumors)


def test_announce_reaches_everyone_and_costs_coins(w):
    cost = w.config["reputation"]["announce_cost"]
    put(w, "square", "Anna")
    put(w, "river", "Boris")
    w.agents["Clara"].asleep = True
    coins = w.agents["Anna"].coins
    assert "announce" in engine.observe(w, "Anna", consume_inbox=False)["available_actions"]
    act(w, "Anna", "announce", text="Funeral for old Ivan tomorrow at noon, square")
    assert w.agents["Anna"].coins == coins - cost
    for n in w.agents:
        assert any("NOTICE from Anna" in x and "Funeral" in x for x in w.agents[n].inbox), n
    assert engine.observe(w, "Boris")["notice_board"] == {"at": "square", "notice_cost": cost}


def test_announce_errors(w):
    put(w, "river", "Anna")
    assert any(e.kind == "error" for e in act(w, "Anna", "announce", text="hi"))  # not at the board
    put(w, "square", "Anna")
    ops.burn_coins(w, w.agents["Anna"], w.agents["Anna"].coins)
    assert "announce" not in engine.observe(w, "Anna")["available_actions"]
    assert any(e.kind == "error" for e in act(w, "Anna", "announce", text="hi"))
