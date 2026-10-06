"""Village structures built together and the mayor's treasury (aivillage/works.py, governance.py)."""

import pytest

from aivillage import engine, governance, ops, works
from aivillage.invariants import check

NAMES = ["Anna", "Boris", "Clara", "Dmitri", "Elena"]


@pytest.fixture
def w():
    return engine.new_world({"seed": 1})


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def act(w, name, action, **args):
    return step(w, {name: (action, args)})


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def until_day(w, day):
    events = []
    while w.day < day:
        events += step(w)
    return events


def at_square(w, *names):
    for n in names:
        w.agents[n].location = "square"


def elect(w, mayor):
    act(w, mayor, "run_for_mayor", pitch="a well for all")
    until_day(w, 2)
    step(w, {n: ("vote", {"candidate": mayor}) for n in NAMES})
    until_day(w, 3)
    assert w.governance.mayor == mayor


def finish_well(w, builder="Anna"):
    p = w.projects["well_1"]
    a = w.agents[builder]
    a.inventory.update({"wood": 10, "stone": 10})
    w.ledger["wood"] = w.ledger.get("wood", 0) + 10
    w.ledger["stone"] = w.ledger.get("stone", 0) + 10
    act(w, builder, "contribute", project_id=p.id, items={"wood": 10, "stone": 10, "coins": 20})
    for _ in range(p.needs["labor"]):
        act(w, builder, "build_work", project_id=p.id)
    return p


def test_anyone_builds_without_mayor_and_idle_are_named(w):
    at_square(w, "Anna", "Boris")
    ev = act(w, "Boris", "propose_build", structure="well")
    assert not errors(ev) and "well_1" in w.projects
    obs = engine.observe(w, "Clara")
    assert any(p["id"] == "well_1" for p in obs["board"]["projects"])
    p = finish_well(w)
    assert p.done and works.level(w, "well") == 1
    assert p.contributed["wood"] == p.needs["wood"] and w.agents["Anna"].inventory["wood"] == 10 - p.needs["wood"]
    assert "water" in w.locations["square"].resources  # the well gives water at the square
    act(w, "Boris", "work", resource="water")
    assert w.agents["Boris"].inventory.get("water") == 2


def test_finished_project_names_helpers_and_shirkers(w):
    at_square(w, "Anna")
    act(w, "Anna", "propose_build", structure="well")
    p = w.projects["well_1"]
    w.agents["Anna"].inventory.update({"wood": 10, "stone": 10})
    w.ledger["wood"] = w.ledger.get("wood", 0) + 10
    w.ledger["stone"] = w.ledger.get("stone", 0) + 10
    act(w, "Anna", "contribute", project_id=p.id, items={"wood": 10, "stone": 10, "coins": 20})
    for _ in range(p.needs["labor"] - 1):
        act(w, "Anna", "build_work", project_id=p.id)
    ev = act(w, "Anna", "build_work", project_id=p.id)
    done = next(e for e in ev if e.kind == "project_done")
    assert "Built by: Anna" in done.text and "Did not help: Boris, Clara, Dmitri, Elena" in done.text
    assert errors(act(w, "Anna", "build_work", project_id=p.id))  # nothing left to do


def test_only_mayor_proposes_and_funds_from_treasury(w):
    elect(w, "Anna")
    at_square(w, "Anna", "Boris")
    assert "propose_build" not in engine.observe(w, "Boris")["available_actions"]
    assert errors(act(w, "Boris", "propose_build", structure="wall"))
    assert not errors(act(w, "Anna", "propose_build", structure="wall"))
    w.governance.coins = 100
    w.ledger["coins"] += 100
    act(w, "Anna", "fund_project", project_id="wall_1", coins=500)
    assert w.projects["wall_1"].contributed["coins"] == w.projects["wall_1"].needs["coins"]
    assert w.governance.coins == 100 - w.projects["wall_1"].needs["coins"]
    assert errors(act(w, "Anna", "propose_build", structure="wall"))  # already being built
    assert errors(act(w, "Anna", "propose_build", structure="castle"))


def test_embezzle_hidden_until_audit_then_reportable(w):
    elect(w, "Anna")
    w.governance.coins = 100
    w.ledger["coins"] += 100
    coins = w.agents["Anna"].coins
    ev = act(w, "Anna", "embezzle", coins=30)
    assert [e for e in ev if e.kind == "embezzle"][0].to == ["Anna"]  # nobody else learns
    assert w.agents["Anna"].coins == coins + 30 and w.governance.coins == 70
    assert engine.observe(w, "Boris")["government"]["treasury"] == 100  # the books
    mayor_view = engine.observe(w, "Anna")["government"]
    assert mayor_view["treasury"] == 70 and mayor_view["you_took_unnoticed"] == 30
    at_square(w, "Boris")
    ev = act(w, "Boris", "audit_treasury")
    found = [e for e in ev if e.kind == "embezzlement_found"]
    assert found and found[0].visibility == "public" and found[0].data["mayor"] == "Anna"
    assert engine.observe(w, "Clara")["government"]["treasury"] == 70
    assert w.agents["Boris"].reputation["Anna"]["score"] < 0
    w.governance.laws["theft_fine"] = 5
    act(w, "Clara", "report_theft", person="Anna")
    assert w.governance.coins == 70 + 30 + 5  # returned and fined
    assert errors(act(w, "Boris", "audit_treasury")) == []


def test_new_mayor_counts_the_treasury(w):
    elect(w, "Anna")
    w.governance.coins = 50
    w.ledger["coins"] += 50
    act(w, "Anna", "embezzle", coins=20)
    w.governance.candidates = {"Boris": "honest books"}
    w.governance.votes = {n: "Boris" for n in NAMES}
    ctx = ops.Ctx(w, engine.rng_for(w, "test"))
    governance._count_election(ctx, w.day)
    ev = ctx.events
    assert w.governance.mayor == "Boris"
    assert any(e.kind == "embezzlement_found" and e.data["mayor"] == "Anna" for e in ev)
    assert w.governance.hidden == 0


def test_embezzle_off_by_config():
    w = engine.new_world({"seed": 1, "treasury": {"embezzle": False}})
    elect(w, "Anna")
    w.governance.coins = 10
    w.ledger["coins"] += 10
    assert "embezzle" not in engine.observe(w, "Anna")["available_actions"]
    assert errors(act(w, "Anna", "embezzle", coins=5))


def test_structure_effects(w):
    assert works.defense(w) == 0 and works.sell_factor(w, "sell") == 1.0
    w.works.levels.update({"wall": 2, "bridge": 3, "watchtower": 1, "well": 3})
    assert works.defense(w) == 2
    assert works.sell_factor(w, "sell") == pytest.approx(1.3) and works.sell_factor(w, "buy") == 1.0
    assert works.notice_bonus(w) == pytest.approx(0.1)
    assert works.fire_grow_bonus(w) == 2
    prices = engine.observe(w, "Anna")["board"]["trader_prices"]
    w.works.levels["bridge"] = 0
    assert engine.observe(w, "Anna")["board"]["trader_prices"]["fish"]["sell"] >= prices["fish"]["sell"]


def test_council_suggests_when_village_is_idle():
    w = engine.new_world({"seed": 1})
    w.projects.clear()
    until_day(w, 1 + w.config["works"]["council_idle_days"])
    opened = works.open_projects(w)
    assert len(opened) == 1 and opened[0].proposer == "council"


def test_old_bridge_project_builds_bridge_level_1(w):
    p = w.projects["bridge"]
    assert p.structure == "bridge"
    at_square(w, "Anna")
    a = w.agents["Anna"]
    a.inventory.update(dict(p.needs))
    for k, v in p.needs.items():
        w.ledger[k] = w.ledger.get(k, 0) + v
    act(w, "Anna", "contribute", project_id="bridge", items=dict(p.needs))
    assert p.done and works.level(w, "bridge") == 1
    assert "bridge" in works.next_options(w) and works.next_options(w)["bridge"] == 2


def test_bots_run_with_works_and_replay(tmp_path):
    from aivillage.run import bots_decider, replay, run
    log = tmp_path / "r.jsonl"
    w = engine.new_world({"seed": 3})
    run(w, bots_decider(w, ["random", "worker", "random", "thief", "random"], seed=3), days=4, log_path=log)
    replay(log)


def test_structures_not_offered_before_a_town_hall_with_stages():
    w = engine.new_world({"seed": 1, "progress": {"enabled": True}})
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "village_structures" not in obs and "propose_build" not in obs["available_actions"]
    assert works.facts(w.config).startswith("- Village structures (once a town_hall stands in the village):")
    plain = engine.new_world({"seed": 1})
    assert engine.observe(plain, "Anna", consume_inbox=False)["village_structures"]["you_can_start"]
    assert works.facts(plain.config).startswith("- Village structures: ")
