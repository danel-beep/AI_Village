"""Hiring (aivillage/hire.py): contracts between villagers, outsiders at the town hall, guards."""

import random

from test_neutrality import evaluative

from aivillage import construction, engine, hire, llm, modes, ops, progress
from aivillage.invariants import check
from aivillage.ops import Ctx
from aivillage.run import bots_decider, replay, run, view

ON = {"seed": 1, "hire": {"enabled": True}}


def world(**kw):
    w = engine.new_world({**ON, **kw})
    for a in w.agents.values():
        a.busy_until = 0
    return w


def act(w, name, action, **args):
    a = w.agents[name]
    a.busy_until, a.task, a.asleep = w.tick, None, False
    events = engine.step(w, {name: {"action": {"name": action, "args": args}}})
    check(w)
    return events


def errors(events):
    return [e.text for e in events if e.kind == "error"]


def hour(w):
    hire.end_of_hour(Ctx(w, random.Random(0)))
    check(w)


def only_job(w):
    return next(iter(hire.jobs(w).values()))


def test_off_by_default_and_in_the_ordinary_mode():
    w = engine.new_world({"seed": 1})
    assert not hire.enabled(w.config) and "hire" not in w.to_dict()
    assert errors(act(w, "Anna", "offer_job", to="Clara", task="wood", hours=2, wage={"coins": 4}))
    assert not hire.enabled(engine.new_world(modes.world_override("crafts", {"seed": 1})).config)
    assert hire.enabled(engine.new_world(modes.world_override("survival", {"seed": 1})).config)


def test_ordinary_prompt_has_no_hiring():
    from aivillage import runconfig
    from aivillage.run import llm_agents
    for mode, shown in (("crafts", False), ("survival", True)):
        over = runconfig.RunConfig(mode=mode, characters="off").world_override()
        if mode == "survival":
            over["progress"] = {**over.get("progress", {}), "start_stage": "town"}
        w = engine.new_world(over)
        a = next(iter(llm_agents(w, {n: "stub" for n in w.agents}).values()))
        prompt = a.system_prompt(engine.observe(w, a.name, consume_inbox=False))
        assert ("offer_job(" in prompt) == shown and ("hire_npc(" in prompt) == shown


def test_gathering_job_paid_after():
    w = world()
    w.agents["Clara"].location = "forest"
    act(w, "Anna", "offer_job", to="Clara", task="wood", hours=2, wage={"coins": 4}, pay="after")
    j = only_job(w)
    assert j["status"] == "offered" and w.agents["Anna"].coins == 20
    ev = act(w, "Clara", "accept_job", job_id=j["id"])
    assert any(e.kind == "job_signed" and e.visibility == "public" for e in ev)
    assert w.agents["Clara"].coins == 20  # nothing paid yet
    wood0 = ops.count(w.agents["Anna"].inventory, "wood")
    act(w, "Clara", "work", resource="wood", hours=1)
    act(w, "Clara", "work", resource="wood", hours=1)
    assert ops.count(w.agents["Anna"].inventory, "wood") > wood0  # carried to the employer at once
    assert ops.count(w.agents["Clara"].inventory, "wood") == 0
    assert j["status"] == "owed" and j["owes"] == "Anna" and j["owed"] == {"coins": 4}
    assert any(x["id"] == j["id"] for x in engine.observe(w, "Boris")["job_board"])  # everyone sees it
    ev = act(w, "Anna", "pay_job", job_id=j["id"])
    assert any(e.kind == "job_paid" for e in ev)
    assert w.agents["Clara"].coins == 24 and w.agents["Anna"].coins == 16 and j["status"] == "closed"


def test_paid_before_and_quit_early_leaves_a_debt_nobody_forces():
    w = world()
    w.agents["Clara"].location = "forest"
    act(w, "Anna", "offer_job", to="Clara", task="wood", hours=4, wage={"coins": 8}, pay="before")
    j = only_job(w)
    act(w, "Clara", "accept_job", job_id=j["id"])
    assert w.agents["Clara"].coins == 28 and w.agents["Anna"].coins == 12
    act(w, "Clara", "work", resource="wood", hours=1)
    ev = act(w, "Clara", "end_job", job_id=j["id"])
    assert any(e.kind == "job_ended" for e in ev)
    assert j["owes"] == "Clara" and j["owed"] == {"coins": 6}  # 3 of 4 hours not done
    assert w.agents["Clara"].coins == 28  # nothing is taken back by force
    j["owed_day"] = w.day - 1
    ctx = Ctx(w, random.Random(0))
    hire.end_of_hour(ctx)
    assert [e for e in ctx.events if e.kind == "job_unpaid" and e.visibility == "public"]
    hire.end_of_hour(ctx)
    assert sum(e.kind == "job_unpaid" for e in ctx.events) == 1  # announced once
    assert errors(act(w, "Anna", "pay_job", job_id=j["id"]))  # only the one who owes pays
    act(w, "Clara", "pay_job", job_id=j["id"])
    assert w.agents["Anna"].coins == 18 and j["status"] == "closed"


def test_goods_wage_unpaid_before_fails_and_deadline_settles():
    w = world()
    act(w, "Anna", "offer_job", to="Boris", task="stone", hours=3, wage={"bread": 50}, pay="before")
    j = only_job(w)
    assert errors(act(w, "Boris", "accept_job", job_id=j["id"]))  # Anna has no 50 bread
    act(w, "Anna", "offer_job", to="Boris", task="stone", hours=3, wage={"coins": 3}, pay="after")
    j2 = [x for x in hire.jobs(w).values() if x["id"] != j["id"]][0]
    act(w, "Boris", "accept_job", job_id=j2["id"])
    assert errors(act(w, "Boris", "accept_job", job_id=j["id"]))  # one job at a time
    w.day = j2["due_day"] + 1
    hour(w)
    assert j2["ended"].startswith("the deadline") and j2["status"] == "closed"  # 0 hours: nothing owed


def test_offers_expire_and_bad_tasks_are_refused():
    w = world()
    assert "unknown task" in errors(act(w, "Anna", "offer_job", to="Boris", task="dance", hours=1,
                                        wage={"coins": 1}))[0]
    assert errors(act(w, "Anna", "offer_job", to="Anna", task="wood", hours=1, wage={"coins": 1}))
    assert errors(act(w, "Anna", "offer_job", to="Boris", task="wood", hours=20, wage={"coins": 1}))
    act(w, "Anna", "offer_job", to="Boris", task="wood", hours=1, wage={"coins": 1})
    j = only_job(w)
    assert engine.observe(w, "Boris")["jobs_offered_to_you"][0]["id"] == j["id"]
    w.tick = j["expires_tick"]
    hour(w)
    assert not hire.jobs(w)


def test_building_job_counts_hours_on_the_employers_site():
    w = engine.new_world({**ON, "construction": {"enabled": True}})
    for a in w.agents.values():
        a.busy_until = 0
    assert not errors(act(w, "Anna", "start_building", kind="house"))
    s = next(iter(construction.sites(w).values()))
    act(w, "Anna", "offer_job", to="Boris", task="build", hours=2, wage={"coins": 2})
    j = only_job(w)
    act(w, "Boris", "accept_job", job_id=j["id"])
    w.agents["Boris"].location = "home_Anna"
    act(w, "Boris", "construct", site_id=s["id"])
    assert j["done"] == 1


def test_villager_guard_counts_hours_and_fights_a_thief():
    w = world()
    act(w, "Anna", "offer_job", to="Boris", task="guard", hours=3, wage={"coins": 3})
    j = only_job(w)
    act(w, "Boris", "accept_job", job_id=j["id"])
    w.agents["Boris"].location = "home_Anna"
    hour(w)
    assert j["done"] == 1
    w.agents["Dmitri"].location = "home_Anna"
    ops.mint_coins(w, w.chests["chest_Anna"], 5)
    ev = act(w, "Dmitri", "steal", target="chest", item="coins", qty=2)
    fights = [e for e in ev if e.kind == "guard_fight"]
    assert fights and fights[0].data["guard"] == "Boris" and fights[0].data["intruder"] == "Dmitri"
    stole = [e for e in ev if e.kind == "steal" and e.data.get("success")]
    assert bool(stole) == (fights[0].data["winner"] == "Dmitri")  # the act happens only if the guard loses
    assert "Anna" in fights[0].to


def test_outsider_guard_stops_a_thief_and_leaves_when_paid_days_end():
    w = world(hire={"enabled": True, "npc": {"guard": {"attack": 30, "damage": 30, "health": 200}}})
    w.agents["Anna"].location = "square"
    assert "outsiders_for_hire" in engine.observe(w, "Anna")
    ev = act(w, "Anna", "hire_npc", kind="guard", days=1)
    assert any(e.kind == "npc_hired" and e.visibility == "public" for e in ev)
    assert w.agents["Anna"].coins == 8  # 12 coins left the village
    chest = w.chests["chest_Anna"]
    ops.mint_coins(w, chest, 5)
    coins = chest.coins
    for thief in ("Dmitri", "Elena"):
        w.agents[thief].location = "home_Anna"
    hp = w.agents["Dmitri"].health
    ev = act(w, "Dmitri", "steal", target="chest", item="coins", qty=2)
    f = [e for e in ev if e.kind == "guard_fight"][0]
    assert f.data["npc"] and f.data["winner"] != "Dmitri"
    assert chest.coins == coins and w.agents["Dmitri"].health < hp
    ev = act(w, "Elena", "set_fire")
    assert any(e.kind == "guard_fight" for e in ev) and "home_Anna" not in w.fires
    w.agents["Elena"].location = "home_Boris"  # nobody guards Boris
    assert not [e for e in act(w, "Elena", "steal", target="chest", item="coins", qty=1) if e.kind == "guard_fight"]
    w.day += 1
    hour(w)
    assert not hire.npcs(w)


def test_outsider_worker_gathers_for_coins():
    w = world()
    w.agents["Anna"].location = "square"
    assert errors(act(w, "Anna", "hire_npc", kind="worker", resource="air", hours=2))
    wood0 = ops.count(w.agents["Anna"].inventory, "wood")
    ledger0 = w.ledger.get("coins", 0)
    act(w, "Anna", "hire_npc", kind="worker", resource="wood", hours=2)
    assert w.ledger["coins"] == ledger0 - 8
    assert view(w)["hire"]["npcs"][0]["kind"] == "worker"
    hour(w)
    hour(w)
    assert ops.count(w.agents["Anna"].inventory, "wood") == wood0 + 4
    assert not hire.npcs(w)
    w.agents["Boris"].location = "forest"
    assert errors(act(w, "Boris", "hire_npc", kind="worker", resource="wood", hours=1))  # only at the town hall


def test_survival_opens_jobs_at_hamlet_and_outsiders_with_the_town_hall():
    camp = engine.new_world(modes.world_override("survival", {"seed": 1}))
    a = camp.agents["Anna"]
    a.busy_until = 0
    assert not progress.unlocked(camp, "action:offer_job")
    assert "offer_job" not in engine.observe(camp, "Anna")["available_actions"]
    hamlet = engine.new_world(modes.world_override("survival", {"seed": 1, "progress": {"start_stage": "hamlet"}}))
    assert progress.unlocked(hamlet, "action:offer_job") and not progress.unlocked(hamlet, "action:hire_npc")
    town = engine.new_world(modes.world_override("survival", {"seed": 1, "progress": {"start_stage": "town"}}))
    assert progress.unlocked(town, "action:hire_npc")


def test_texts_are_neutral():
    w = world()
    w.agents["Clara"].location = "forest"
    texts = [hire.facts(w.config), llm.world_facts(w.config)]
    act(w, "Anna", "offer_job", to="Clara", task="wood", hours=1, wage={"coins": 2}, pay="before")
    ev = act(w, "Clara", "accept_job", job_id=only_job(w)["id"])
    ev += act(w, "Clara", "work", resource="wood", hours=1)
    texts += [e.text for e in ev] + [str(engine.observe(w, "Anna"))]
    assert not [t for t in texts if evaluative(t)]


def test_bots_in_survival_with_hiring_replay(tmp_path):
    w = engine.new_world(modes.world_override("survival", {"seed": 3, "progress": {"start_stage": "town"},
                                                           "population": {"size": 6}}))
    log = tmp_path / "h.jsonl"
    run(w, bots_decider(w, ["random", "builder", "thief"], 3), 3, None, log, check_every_tick=True)
    check(w)
    assert replay(log).hash() == w.hash()
