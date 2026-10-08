"""Theft with consequences (governance.report_theft, theft.clue): a reported thief gives back what they took,
pays a polity's theft_fine where one is set, loses standing with everyone who hears; a theft nobody saw may
leave the victim a clue that fits two or more villagers. Crimes are kept in every tick, not only the hour's last."""

from aivillage import engine, governance, ops, polity, theft
from aivillage.invariants import check

from test_polity import act as pact, hall, world as survival

SEEN = {"theft": {"enabled": True, "victim_notice_chance": 1.0, "dark_factor": 1.0}, "steal_awake_target_success": 1.0,
        "steal_notice_chance": 0.0}


def world(**over):
    return engine.new_world({"seed": 1, "crises": {"enabled": False}, "tick_minutes": 15, **SEEN, **over})


def act(w, name, action, args=None):
    """Let `name` act at once (no waiting): the tests below only need the action's own effect."""
    w.agents[name].last_error = None
    w.agents[name].busy_until = w.tick
    events = engine.step(w, {name: {"thought": "", "action": {"name": action, "args": args or {}}}})
    check(w)
    return w.agents[name].last_error, events


def rob(w, thief="Boris", victim="Anna", item="bread", qty=3):
    w.agents[thief].location = w.agents[victim].location
    if item == "coins":
        ops.mint_coins(w, w.agents[victim], qty)
    else:
        ops.mint(w, w.agents[victim].inventory, item, qty)
    err, events = act(w, thief, "steal", {"target": victim, "item": item, "qty": qty})
    assert err is None
    return events


def test_a_theft_in_any_tick_of_the_hour_can_be_reported():
    w = world()
    assert w.minute == 0 and 60 // w.config["tick_minutes"] > 1  # not the hour's last tick
    rob(w)
    assert [c["thief"] for c in w.governance.crimes] == ["Boris"]
    assert w.governance.crimes[0]["item"] == "bread" and w.governance.crimes[0]["qty"] == 3


def test_report_gives_the_loot_back_through_the_ledger():
    w = world()
    rob(w)
    anna, boris = w.agents["Anna"], w.agents["Boris"]
    assert ops.count(anna.inventory, "bread") == 0
    err, events = act(w, "Anna", "report_theft", {"person": "Boris"})
    assert err is None
    assert ops.count(anna.inventory, "bread") == 3 and ops.count(boris.inventory, "bread") == 0
    rep = next(e for e in events if e.kind == "theft_report")
    assert rep.data["returned"] == 3 and "gave back 3 bread to Anna" in rep.text
    assert not w.governance.crimes


def test_what_is_gone_is_dropped_and_no_debt_is_written():
    w = world()
    rob(w)
    boris = w.agents["Boris"]
    ops.burn(w, boris.inventory, "bread", 2)  # eaten
    chest = w.chests["chest_Boris"]
    ops.move_items(boris.inventory, chest.items, {"bread": 1})  # hidden at home
    debts_before = len(w.debts)
    err, events = act(w, "Anna", "report_theft", {"person": "Boris"})
    assert err is None and ops.count(w.agents["Anna"].inventory, "bread") == 1 and ops.count(chest.items, "bread") == 0
    assert "2 more are gone" in next(e for e in events if e.kind == "theft_report").text
    assert len(w.debts) == debts_before


def test_restitution_can_be_off():
    w2 = world(governance={"restitution": 0})
    rob(w2)
    err, events = act(w2, "Anna", "report_theft", {"person": "Boris"})
    assert err is None and ops.count(w2.agents["Anna"].inventory, "bread") == 0
    assert "returned" not in next(e for e in events if e.kind == "theft_report").data


def test_coins_restitution_is_exact():
    w = world()
    anna, boris = w.agents["Anna"], w.agents["Boris"]
    a0, b0 = anna.coins, boris.coins
    rob(w, item="coins", qty=3)
    assert anna.coins == a0 and boris.coins == b0 + 3
    act(w, "Anna", "report_theft", {"person": "Boris"})
    assert anna.coins == a0 + 3 and boris.coins == b0


def test_everyone_who_hears_thinks_less_of_the_culprit():
    w = world()
    rob(w)
    clara_before = w.agents["Clara"].reputation.get("Boris", {}).get("score", 0)
    act(w, "Anna", "report_theft", {"person": "Boris"})
    assert w.agents["Clara"].reputation["Boris"]["score"] == clara_before + w.config["reputation"]["deltas"]["theft_report"]
    assert "Boris" not in w.agents["Boris"].reputation


def test_the_crime_window_is_two_weeks():
    assert engine.new_world({"seed": 1}).config["governance"]["crime_memory_days"] == 14


def test_witnessed_treasury_theft_returns_the_coins_and_the_books_balance():
    w = world(governance={"start": {"theft_fine": 0}}, theft={"enabled": True, "treasury": True, "dark_factor": 1.0})
    g = w.governance
    ops.mint_coins(w, g, 20)
    boris, clara = w.agents["Boris"], w.agents["Clara"]
    boris.location = clara.location = "square"
    w.config["steal_notice_chance"] = 1.0
    err, _ = act(w, "Boris", "steal", {"target": "treasury", "item": "coins", "qty": 3})
    assert err is None and g.coins == 17 and g.hidden == 3
    err, events = act(w, "Clara", "report_theft", {"person": "Boris"})
    assert err is None and g.coins == 20 and g.hidden == 0 and g.embezzled.get(theft.UNKNOWN) == 0


def test_polity_theft_fine_charges_a_non_member_at_its_town_hall():
    w = survival(theft={"enabled": True, "victim_notice_chance": 1.0}, steal_awake_target_success=1.0,
                 steal_notice_chance=0.0)
    a, b, c, *_ = sorted(w.agents)
    hall(w, builders=[a, c])
    p = next(iter(w.polities.values()))
    p["laws"]["theft_fine"] = 10
    thief, victim = w.agents[b], w.agents[a]
    assert b not in p["members"]
    thief.location = victim.location = p["location"]
    ops.mint(w, victim.inventory, "bread", 2)
    pact(w, b, "steal", target=a, item="bread", qty=2)
    coins, treasury = thief.coins, p["coins"]
    events = pact(w, a, "report_theft", person=b)
    rep = next(e for e in events if e.kind == "theft_report")
    assert thief.coins == coins - 10 and p["coins"] == treasury + 10, rep.text
    assert ops.count(victim.inventory, "bread") >= 2


def test_polity_without_a_theft_fine_says_so():
    w = survival(theft={"enabled": True, "victim_notice_chance": 1.0}, steal_awake_target_success=1.0,
                 steal_notice_chance=0.0)
    a, b, c, *_ = sorted(w.agents)
    hall(w, builders=[a, c])
    p = next(iter(w.polities.values()))
    w.agents[b].location = w.agents[a].location = "forest"
    ops.mint(w, w.agents[a].inventory, "bread", 2)
    pact(w, b, "steal", target=a, item="bread", qty=2)
    coins = w.agents[b].coins
    rep = next(e for e in pact(w, a, "report_theft", person=b) if e.kind == "theft_report")
    assert w.agents[b].coins == coins and f"{polity.title(p)} has no theft_fine law" in rep.text
    assert "theft_fine" in polity.facts(w.config) and "give" in governance.facts(w.config)


def test_ruler_can_set_a_theft_fine():
    w = survival()
    a, b, *_ = sorted(w.agents)
    hall(w, builders=[a, b])
    p = next(iter(w.polities.values()))
    p["form"], p["rulers"], p["ballot"] = "ruler", [a], {}
    pact(w, a, "polity_propose", law="theft_fine", value=12)
    assert p["laws"]["theft_fine"] == 12
    row = engine.observe(w, b, consume_inbox=False)["polities"][0]
    assert row["theft_fine"] == 12


def unseen(seed, **over):
    w = engine.new_world({"seed": seed, "crises": {"enabled": False}, "steal_notice_chance": 0.0,
                          "theft": {"enabled": True, "owner_notice_chance": 0.0, "clue_chance": 1.0}, **over})
    ops.mint(w, w.chests["chest_Anna"].items, "bread", 3)
    w.agents["Boris"].location = w.agents["Anna"].home
    w.agents["Anna"].location = "square"
    err, events = act(w, "Boris", "steal", {"target": "chest", "item": "bread", "qty": 2})
    assert err is None
    return w, events


def test_a_clue_never_points_at_fewer_than_two():
    given = 0
    for seed in range(12):
        w, events = unseen(seed, start_items={"bread": 2})
        clues = [e for e in events if e.kind == "theft_clue"]
        assert all(e.to == ["Anna"] and e.data["suspects"] >= 2 for e in clues)
        given += len(clues)
    assert given  # everyone starts with 2 bread: "carries at least 2 bread" fits several


def test_no_clue_when_it_would_name_the_thief_alone_or_when_off():
    w, events = unseen(3, start_items={})
    # alone at Anna's home, the only one carrying bread, no gear: nothing fits two people
    assert not [e for e in events if e.kind == "theft_clue"]
    w, events = unseen(3, start_items={"bread": 2}, theft={"enabled": True, "owner_notice_chance": 0.0,
                                                         "clue_chance": 0.0})
    assert not [e for e in events if e.kind == "theft_clue"]


def test_a_clue_is_never_given_for_a_seen_theft():
    w = world(theft={"enabled": True, "victim_notice_chance": 1.0, "dark_factor": 1.0, "clue_chance": 1.0}, start_items={"bread": 2})
    events = rob(w)
    assert not [e for e in events if e.kind == "theft_clue"]
