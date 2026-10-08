"""Polities (survival plan task 16, aivillage/polity.py): a town hall founds a polity, members vote on its name,
coin name and form of government, laws pass the way the form says, petitions change the form, each polity
taxes only its own members. «Обычный» is unchanged."""

import json

from aivillage import construction, engine, governance, handbook, modes, ops, polity
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, replay, run

from test_neutrality import evaluative

QUIET = {"lives": 0, "crises": {"enabled": False}, "illness": {"per_day": 0.0}, "threats": {"kinds": {}},
         "random_fires": {"per_day": 0.0}}


def world(mode="survival", **extra):
    # no minted treasury income here: these tests count the treasury coin by coin (test_treasury.py has it)
    extra["polity"] = {"income_per_member_per_day": 0, **extra.get("polity", {})}
    w = engine.new_world(modes.world_override(mode, {"seed": 5, **QUIET, "progress": {"start_stage": "village"},
                                                     **extra}))
    for a in w.agents.values():
        ops.mint_coins(w, a, 40 - a.coins)
    return w


def names(w):
    return sorted(w.agents)


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def act(w, name, action, **args):
    """Wait until `name` can act (awake, not busy), then do the action. Returns that tick's events."""
    for _ in range(200):
        if engine.needs_decision(w, name):
            return step(w, {name: (action, args)})
        step(w)
    raise AssertionError(f"{name} never got a turn")


def errors(events, name=None):
    return [e.text for e in events if e.kind == "error" and (name is None or name in e.to)]


def hall(w, location="square", builders=()):
    construction.place(w, "town_hall", location, builders=list(builders))
    return step(w)


def until(w, cond, limit=400):
    events = []
    for _ in range(limit):
        if cond():
            return events
        events += step(w)
    raise AssertionError("condition never held")


def found(w, builders, **votes):
    """A polity founded by `builders`, its founding ballot voted by all of them and closed."""
    hall(w, builders=builders)
    p = next(p for p in w.polities.values() if p["members"] == sorted(builders) or p["members"] == list(builders))
    for n in builders:
        for topic, choice in votes.items():
            act(w, n, "polity_vote", topic=topic, choice=choice(n) if callable(choice) else choice)
    until(w, lambda: "form" not in p["ballot"] and ("leader" not in p["ballot"]))
    return p


def test_town_hall_founds_a_polity_with_its_builders():
    w = world()
    a, b, c, *_ = names(w)
    events = hall(w, builders=[a, b])
    p = next(iter(w.polities.values()))
    assert p["members"] == [a, b] and p["form"] is None and p["name"] is None
    assert sorted(p["options"]) == sorted(polity.FORMS)
    ev = next(e for e in events if e.kind == "polity_founded")
    assert ev.visibility == "public" and a in ev.text
    obs = engine.observe(w, a, consume_inbox=False)
    row = obs["polities"][0]
    assert row["you_are_member"] and set(row["open_ballot"]["form"]["options"]) == set(polity.FORMS)
    assert "you_are_member" not in engine.observe(w, c, consume_inbox=False)["polities"][0]


def test_founding_ballot_names_the_polity_its_coins_and_form():
    w = world()
    a, b, c, *_ = names(w)
    p = found(w, [a, b, c], name="Oakvale", coin=lambda n: "acorn" if n != c else "leaf", form="ruler",
              leader=lambda n: b)
    assert (p["name"], p["coin"], p["form"], p["rulers"]) == ("Oakvale", "acorn", "ruler", [b])
    row = next(r for r in engine.observe(w, a, consume_inbox=False)["polities"])
    assert row["ruler"] == b and row["votes_on_laws"] == [b]


def test_a_question_nobody_voted_on_stays_open():
    w = world()
    a, b, *_ = names(w)
    hall(w, builders=[a, b])
    p = next(iter(w.polities.values()))
    act(w, a, "polity_vote", topic="name", choice="Riverside")
    closes = p["closes"]
    until(w, lambda: w.tick > closes)
    assert p["name"] == "Riverside" and set(p["ballot"]) == {"coin", "form", "leader"} and p["closes"] > closes


def test_ruler_decides_alone_and_the_tax_goes_to_the_polity_from_members_only():
    w = world()
    a, b, c, d, *_ = names(w)
    p = found(w, [a, b, c], name="North", coin="mark", form="ruler", leader=lambda n: a)
    errs = errors(act(w, b, "polity_propose", law="tax", value=5), b)
    assert errs and "only the ruler" in errs[0]
    events = act(w, a, "polity_propose", law="tax", value=5)
    assert any(e.kind == "polity_law_passed" for e in events) and p["laws"]["tax"] == 5
    coins_d = w.agents[d].coins
    every = w.config["tax_every_days"]
    until(w, lambda: w.day == every + 1)
    assert p["coins"] == 15 and w.agents[d].coins == coins_d  # d is in no polity: no tax


def test_assembly_needs_more_than_half_of_the_members():
    w = world()
    a, b, c, d, *_ = names(w)
    p = found(w, [a, b, c, d], form="assembly", leader=lambda n: d)
    assert p["form"] == "assembly" and p["rulers"] == [] and p["keeper"] == d  # d holds the treasury, no more
    act(w, a, "polity_propose", law="tax", value=3)
    pid = next(iter(p["proposals"]))
    act(w, b, "polity_vote_law", proposal_id=pid, vote="yes")
    assert pid in p["proposals"]  # 2 of 4 is not more than half
    events = act(w, c, "polity_vote_law", proposal_id=pid, vote="yes")
    assert any(e.kind == "polity_law_passed" for e in events) and p["laws"]["tax"] == 3


def test_council_proposes_and_votes():
    w = world(polity={"council_size": 2})
    a, b, c, d, e, *_ = names(w)
    p = found(w, [a, b, c, d, e], form="council", leader=lambda n: a if n in (a, b, c) else b)
    assert p["rulers"] == sorted([a, b]) and p["keeper"] == a
    assert errors(act(w, c, "polity_propose", law="grant", value=1, person=c), c)
    act(w, a, "give_to_polity", coins=10)
    act(w, a, "polity_propose", law="grant", value=4, person=c)
    pid = next(iter(p["proposals"]))
    assert errors(act(w, d, "polity_vote_law", proposal_id=pid, vote="no"), d)
    coins_c = w.agents[c].coins
    act(w, b, "polity_vote_law", proposal_id=pid, vote="yes")
    assert w.agents[c].coins == coins_c + 4 and p["coins"] == 6


def test_voluntary_tax_is_a_bill_paid_into_the_polity_treasury():
    w = world(laws={"enforcement": "voluntary", "bill_days": 2})
    a, b, *_ = names(w)
    p = found(w, [a, b], form="ruler", leader=lambda n: a)
    act(w, a, "polity_propose", law="tax", value=7)
    every = w.config["tax_every_days"]
    events = until(w, lambda: w.day == every + 1)
    assert any(e.kind == "polity_tax_bills" and e.visibility == "public" for e in events)
    bills = [d for d in w.debts.values() if d.id in p["bills"]]
    assert {d.borrower for d in bills} == {a, b} and p["coins"] == 0
    bill_b = next(d for d in bills if d.borrower == b)
    act(w, b, "pay_bill", debt_id=bill_b.id)
    assert p["coins"] == 7 and bill_b.status == "repaid" and w.governance.coins == 0
    events = until(w, lambda: w.day == every + 4)
    assert any(e.kind == "bill_overdue" and e.data.get("borrower") == a for e in events)


def test_join_leave_and_expel():
    w = world()
    a, b, c, *_ = names(w)
    p = found(w, [a, b], form="ruler", leader=lambda n: a)
    act(w, c, "join_polity", polity=p["id"])
    assert c in p["members"]
    act(w, a, "polity_propose", law="expel", person=c)
    assert c not in p["members"] and c in p["expelled"]
    assert "expelled you" in errors(act(w, c, "join_polity", polity=p["id"]), c)[0]
    act(w, b, "leave_polity")
    assert p["members"] == [a]


def test_a_second_town_hall_is_a_second_polity_and_joining_leaves_the_old_one():
    w = world()
    a, b, c, *_ = names(w)
    p1 = found(w, [a, b], name="East", form="ruler", leader=lambda n: a)
    other = next(loc for loc in w.locations if loc != "square" and not construction._is_private(w, loc))
    hall(w, other, builders=[b, c])
    p2 = next(p for p in w.polities.values() if p is not p1)
    assert p2["members"] == [c] and p2["location"] == other  # b already belongs to East
    act(w, b, "join_polity", polity=p2["id"])
    assert b in p2["members"] and b not in p1["members"]
    act(w, a, "give_to_polity", coins=5)
    assert p1["coins"] == 5 and p2["coins"] == 0


def test_town_hall_can_be_started_away_from_the_square_in_survival():
    w = world("survival", progress={"start_stage": "town"})
    a = w.agents[names(w)[0]]
    other = next(loc for loc in w.locations if loc != "square" and not construction._is_private(w, loc))
    a.location = other
    assert "town_hall" in construction.startable(w, a)


def test_petition_of_more_than_half_changes_the_form():
    w = world()
    a, b, c, *_ = names(w)
    p = found(w, [a, b, c], form="ruler", leader=lambda n: a)
    act(w, b, "sign_petition", form="assembly")
    assert p["form"] == "ruler"
    events = act(w, c, "sign_petition", form="assembly")
    assert p["form"] == "assembly" and p["rulers"] == [] and any(e.kind == "polity_form" for e in events)
    act(w, a, "sign_petition", form="council")
    act(w, b, "sign_petition", form="council")
    assert p["form"] == "council" and "leader" in p["ballot"]  # a new council is elected


def test_village_wide_government_is_off_with_polities():
    w = world()
    a, *_ = names(w)
    hall(w, builders=[a])
    obs = engine.observe(w, a, consume_inbox=False)
    assert set(governance.REPLACED) <= set(obs["locked_actions"])
    assert not set(governance.REPLACED) & set(obs["available_actions"])
    text = handbook.text(set(obs["locked_actions"]))
    assert "run_for_mayor" not in text and "polity_vote" in text
    assert "no village-wide government" in errors(act(w, a, "run_for_mayor", pitch="x"), a)[0]
    assert "Polities" in world_facts(w.config) and "Government (" not in world_facts(w.config)


def test_ordinary_mode_has_no_polities():
    w = world("crafts")
    a = names(w)[0]
    step(w)
    assert not w.config["polity"]["enabled"] and "polities" not in w.to_dict()
    obs = engine.observe(w, a, consume_inbox=False)
    assert "polities" not in obs and "next_election_day" in obs["government"]


def scripted(name, obs):
    """A villager who joins the polity, votes, proposes a tax, signs a petition: every polity action in a run."""
    def do(action, **args):
        return {"thought": "", "action": {"name": action, "args": args}}
    rows = obs.get("polities") or []
    mine = next((r for r in rows if r.get("you_are_member")), None)
    if mine is None:
        return do("join_polity", polity=rows[0]["id"]) if rows else do("wait")
    ballot = mine.get("open_ballot") or {}
    for topic, choice in (("name", "Dale"), ("coin", "bit"), ("form", "council"), ("leader", mine["members"][0])):
        if topic in ballot and ballot[topic]["your_vote"] is None:
            return do("polity_vote", topic=topic, choice=choice)
    if mine.get("proposals") and name in mine.get("votes_on_laws", []):
        pr = mine["proposals"][0]
        if name not in pr["yes"] + pr["no"]:
            return do("polity_vote_law", proposal_id=pr["id"], vote="yes")
    if name in mine.get("votes_on_laws", []) and not mine.get("proposals") and mine["tax_per_member"] == 0:
        return do("polity_propose", law="tax", value=2)
    if mine["form"] == "council" and mine["tax_per_member"] and name not in str(mine.get("petition")):
        return do("sign_petition", form="ruler")
    return do("wait")


def test_polity_run_replays_and_its_texts_are_neutral(tmp_path):
    w = engine.new_world(modes.world_override("survival", {"seed": 5, **QUIET, "progress": {"start_stage": "town"}}))
    found_texts = []

    def decide(name, obs):
        found_texts.extend(evaluative(json.dumps(obs)))
        return scripted(name, obs)
    log = tmp_path / "polity.jsonl"
    run(w, decide, days=w.config["tax_every_days"] + 1, log_path=log)
    p = next(iter(w.polities.values()))
    assert p["name"] == "Dale" and p["coin"] == "bit" and p["laws"]["tax"] == 2 and p["coins"] > 0
    assert p["form"] == "ruler" and p["rulers"]  # the petition passed and a ruler was elected
    assert found_texts == [] and evaluative(world_facts(w.config)) == [] and evaluative(handbook.text()) == []
    assert replay(log).hash() == w.hash()


def test_random_bots_keep_invariants_and_replay_with_polities(tmp_path):
    w = engine.new_world(modes.world_override("survival", {"seed": 9, **QUIET, "progress": {"start_stage": "town"}}))
    log = tmp_path / "fuzz.jsonl"
    run(w, bots_decider(w, ["random"], 9), days=3, log_path=log)
    assert w.polities and replay(log).hash() == w.hash()


def test_the_treasury_holder_can_embezzle_until_an_audit_at_the_town_hall():
    w = world()
    a, b, c, *_ = names(w)
    p = found(w, [a, b, c], form="ruler", leader=lambda n: a)
    act(w, b, "give_to_polity", coins=20)
    assert errors(act(w, b, "polity_embezzle", coins=5), b)  # only the holder
    events = act(w, a, "polity_embezzle", coins=8)
    ev = next(e for e in events if e.kind == "polity_embezzle")
    assert ev.to == [a] and ev.visibility == "private"
    assert p["coins"] == 12 and w.agents[a].coins == 48
    row_b = engine.observe(w, b, consume_inbox=False)["polities"][0]
    row_a = engine.observe(w, a, consume_inbox=False)["polities"][0]
    assert row_b["treasury"] == 20 and "you_took_unnoticed" not in row_b
    assert row_a["treasury"] == 12 and row_a["treasury_books"] == 20 and row_a["you_took_unnoticed"] == 8
    w.agents[c].location = p["location"]
    events = act(w, c, "polity_audit")
    found_ev = next(e for e in events if e.kind == "polity_embezzlement_found")
    assert found_ev.visibility == "public" and found_ev.data["keeper"] == a and found_ev.data["coins"] == 8
    assert engine.observe(w, b, consume_inbox=False)["polities"][0]["treasury"] == 12 and p["hidden"] == 0


def test_a_change_of_holder_counts_the_treasury():
    w = world()
    a, b, c, *_ = names(w)
    p = found(w, [a, b, c], form="assembly", leader=lambda n: a)
    act(w, b, "give_to_polity", coins=10)
    act(w, a, "polity_embezzle", coins=4)
    events = act(w, a, "leave_polity")
    assert any(e.kind == "polity_embezzlement_found" and e.data["keeper"] == a for e in events)
    assert p["keeper"] is None and "leader" in p["ballot"]  # a new treasurer is elected
