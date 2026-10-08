"""Real danger (plan after the villain run, thread «Опасность»): bandits from the hamlet in «С нуля», a hostile
threat at a random moment but never more than `threats.hostile.max_gap_days` calm days, its own slot apart from
travelers, yard produce plundered, the hospital discharge from config, «wounded» seen by others."""

from aivillage import engine, knobs, modes, ops, progress, run, threats
from aivillage.invariants import check
from aivillage.llm import world_facts
from aivillage.run import bots_decider, replay

QUIET = {"lives": 0, "crises": {"enabled": False}, "illness": {"per_day": 0.0}}
FED = {"satiety_loss_per_hour": 0, "satiety_loss_asleep_per_hour": 0, "satiety_loss_night": 0}  # idle, not starving


def world(**over):
    return engine.new_world({"seed": 1, **QUIET, **over})


def survival(stage="camp", **extra):
    return engine.new_world(modes.world_override("survival", {"seed": 3, **QUIET,
                                                              "progress": {"start_stage": stage}, **extra}))


def until_day(w, day):
    events = []
    while w.day < day:
        events += engine.step(w, {})
        check(w)
    return events


def gap(top, raid=0.0, beast=0.0, traveler=0.0, **extra):
    return {"threats": {"first_day": 2, "warn_chance": 0.0, "hostile": {"max_gap_days": top, "min_gap_days": 2},
                        "kinds": {"raid": {"per_day": raid}, "beast": {"per_day": beast},
                                  "traveler": {"per_day": traveler}}, **extra}}


def hostile_days(w):
    return sorted(t["arrive_day"] for t in w.threats if t["kind"] in threats.HOSTILE)


def test_raids_open_at_the_hamlet_in_survival_and_at_the_town_elsewhere():
    assert not progress.unlocked(survival("camp"), threats.RAIDS)
    assert progress.unlocked(survival("hamlet"), threats.RAIDS)
    cfg = modes.world_override("crafts", {"progress": {"enabled": True, "start_stage": "village"}})
    assert not progress.unlocked(engine.new_world(cfg), threats.RAIDS)
    assert "bandits (once the village is a hamlet)" in world_facts(survival().config)
    stage = knobs.to_run({"mode": "survival", "raids_from_stage": "village"})["override"]
    assert stage["progress"]["unlocks"]["feature:raids"] == {"stage": "village"}


def test_hostile_gap_is_never_longer_than_the_max_and_falls_on_different_days():
    seen = set()
    for seed in range(8):
        w = engine.new_world({"seed": seed, **QUIET, **FED, **gap(6, raid=0.01, beast=0.01)})
        days = set()
        while w.day < 40:  # finished threats are trimmed from the world: collect them as they come
            engine.step(w, {})
            days.update(hostile_days(w))
        days = sorted(days)
        assert days and days[0] <= 1 + 6
        assert all(b - a <= 6 for a, b in zip(days, days[1:])), days
        assert all(b - a >= 2 for a, b in zip(days, days[1:])), days  # min_gap_days
        assert 40 - days[-1] <= 6
        seen.update(b - a for a, b in zip(days, days[1:]))
    assert len(seen) >= 3  # random moments, not a schedule


def test_no_chances_no_guarantee():
    w = world(**gap(3))
    until_day(w, 15)
    assert not hostile_days(w)


def test_beasts_only_when_raids_are_locked():
    w = survival("camp", **gap(4, raid=0.5, beast=0.01))
    until_day(w, 20)
    assert w.threats and all(t["kind"] == "beast" for t in w.threats if t["kind"] in threats.HOSTILE)


def test_traveler_does_not_block_the_hostile_slot():
    w = world(**FED, **gap(3, raid=0.01, traveler=1.0))
    until_day(w, 12)
    assert hostile_days(w) and any(t["kind"] == "traveler" for t in w.threats)


def test_old_dice_unchanged_without_a_gap():
    cfg = {"threats": {"first_day": 2, "kinds": {"raid": {"per_day": 0.3}, "traveler": {"per_day": 0.3}}}}
    a, b = world(**cfg), world(threats={**cfg["threats"], "hostile": {"max_gap_days": 0}})
    until_day(a, 12)
    until_day(b, 12)
    assert a.hash() == b.hash()


def test_last_hostile_threat_survives_trimming():
    w = world(**FED, **gap(30, raid=0.01, traveler=1.0))
    until_day(w, 3)
    engine.step(w, {}, [{"name": "raid", "args": {"target": "Anna", "warn": False}}])
    last, travelers = 0, 0
    while w.day < 25:  # a traveler a day comes and goes, more than KEEP_FINISHED
        ev = engine.step(w, {})
        travelers += sum(e.kind == "threat_arrived" and e.data["threat_kind"] == "traveler" for e in ev)
        last = max([last, *hostile_days(w)])
    assert travelers > threats.KEEP_FINISHED
    assert hostile_days(w)[-1] == last and threats.calm_days(w) == 25 - last


def test_bandits_take_ripe_yard_produce():
    w = survival("hamlet")
    name = sorted(w.agents)[0]
    home = w.agents[name].home
    plot = w.plots[home]
    plot.buildings.append({"id": "b_test", "kind": "garden_bed", "built_day": 1, "items": {}, "crop": None,
                           "ripe_day": 0})
    ops.mint(w, plot.buildings[-1]["items"], "grain", 10)
    engine.step(w, {}, [{"name": "raid", "args": {"target": name, "warn": False}}])
    ev = []
    for _ in range(6):
        ev += engine.step(w, {})
        check(w)
    plunder = [e for e in ev if e.kind == "plundered" and e.data["home"] == home]
    assert plunder and plunder[0].data["items"].get("grain") == 5  # half of it


def test_discharge_reads_config_and_says_when_no_stays_are_left():
    w = world(lives=2, hospital_discharge={"health": 50, "satiety": 25})
    a = w.agents["Anna"]
    a.status, a.status_until_day, a.hospital_stays = "hospital", 2, 1
    ev = until_day(w, 2)
    out = [e for e in ev if e.kind == "discharged"][0]
    assert (a.health, a.satiety) == (50, 25)
    assert out.data.get("no_stays_left") and "next collapse is death" in out.text
    assert modes.world_override("survival")["hospital_discharge"]["satiety"] == 30
    assert world().config["hospital_discharge"] == {"health": 60, "satiety": 60}


def test_wounded_is_seen_only_where_turned_on():
    w = world(wounded_seen_below=40)
    w.agents["Boris"].health = 30
    w.agents["Boris"].location = w.agents["Anna"].location
    people = engine.observe(w, "Anna", consume_inbox=False)["here"]["people"]
    assert next(p for p in people if p["name"] == "Boris").get("wounded")
    w2 = world()
    w2.agents["Boris"].health = 30
    w2.agents["Boris"].location = w2.agents["Anna"].location
    people = engine.observe(w2, "Anna", consume_inbox=False)["here"]["people"]
    assert "wounded" not in next(p for p in people if p["name"] == "Boris")


def test_prompt_states_the_gap_only_when_danger_can_come():
    assert "rarely more than 10 days" not in world_facts(survival().config)  # all chances 0: nothing comes
    cfg = survival(**{"threats": {"kinds": {"beast": {"per_day": 0.04}}}}).config
    assert "rarely more than 10 days pass without one" in world_facts(cfg)


def test_fair_preset_turns_the_guarantee_off():
    assert knobs.to_run({"chaos": "fair"})["override"]["threats"]["hostile"]["max_gap_days"] == 0
    assert knobs.to_run({"mode": "survival"})["override"]["threats"]["hostile"]["max_gap_days"] == 10


def test_gap_run_replays_exactly(tmp_path):
    log = tmp_path / "run.jsonl"
    w = engine.new_world(modes.world_override("survival", {"seed": 5, "progress": {"start_stage": "hamlet"},
                                                           **gap(4, raid=0.05, beast=0.05, traveler=0.2)}))
    run.run(w, bots_decider(w, ["worker", "thief", "random"], 5), days=8, log_path=log)
    assert replay(log).hash() == w.hash()
    assert hostile_days(w)
