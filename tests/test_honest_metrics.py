"""Honest measurements: days played (not the next morning), code version in the header, who answered each call."""

from aivillage import engine, metrics, scorecard, social_metrics as SM
from aivillage.run import bots_decider, llm_agents, read_log, run


def _run(tmp_path, days, **cfg):
    log = tmp_path / "run.jsonl"
    w = engine.new_world({"seed": 5, **cfg})
    run(w, bots_decider(w, ["worker", "worker", "random"], 5), days=days, log_path=log)
    return list(read_log(log)), len(w.agents)


def test_three_days_are_three_days(tmp_path):
    recs, n = _run(tmp_path, 3)
    assert recs[-1]["view"]["day"] == 4  # the last view is already the next morning, which nobody played
    sm = SM.compute(recs)
    assert sm["days"] == 3 and sm["villager_days"] == 3 * n  # was 4 and 4n: every rate 25% too low
    assert metrics.compute(recs)["days"] == [1, 2, 3]
    assert all(v["days"] == 3 for v in scorecard.compute([tmp_path / "run.jsonl"])["villagers"])


def test_one_day(tmp_path):
    recs, n = _run(tmp_path, 1)
    assert SM.compute(recs)["days"] == 1 and SM.compute(recs)["villager_days"] == n


def test_stop_mid_day_counts_the_day_started(tmp_path):
    recs, n = _run(tmp_path, 2)
    first_of_day2 = next(i for i, r in enumerate(recs) if (r.get("view") or {}).get("day") == 2)
    part = recs[:first_of_day2 + 3]  # the night tick and two ticks of day 2
    assert SM.compute(part)["days"] == 2 and metrics.compute(part)["days"] == [1, 2]


def test_resumed_log_starts_on_its_day_and_the_dead_stop_counting():
    agents = {"Anna": {"status": "active", "coins": 1}, "Boris": {"status": "active", "coins": 1}}
    dead = {"Anna": {"status": "active", "coins": 1}, "Boris": {"status": "dead", "coins": 0}}

    def tick(t, day, who):
        return {"type": "tick", "tick": t, "decisions": {}, "events": [],
                "view": {"day": day, "hour": 8, "agents": who, "chests": {}}}
    head = {"type": "header", "config": {"agents": [{"name": "Anna"}, {"name": "Boris"}], "items": {}},
            "start": {"day": 5, "agents": {n: {"inventory": {}, "location": "square"} for n in agents}}}
    # day 5: both alive; Boris dies in the night; day 6: only Anna; the run stops on the morning of day 7
    recs = [head, tick(1, 5, agents), tick(2, 6, dead), tick(3, 6, dead), tick(4, 7, dead)]
    sm = SM.compute(recs)
    assert sm["days"] == 2 and sm["villager_days"] == 3
    assert metrics.compute(recs)["days"] == [5, 6]


def test_header_names_the_code(tmp_path):
    recs, _ = _run(tmp_path, 1)
    code = recs[0]["code"]
    assert len(code["source"]) == 16 and "commit" in code


def test_each_llm_decision_says_who_answered_and_how_long():
    w = engine.new_world({"seed": 2})
    agents = llm_agents(w, ["stub"])
    name = next(iter(agents))
    dec = agents[name].decide(engine.observe(w, name))
    assert dec["call"]["model"] == "stub" and dec["call"]["ms"] >= 0 and dec["call"]["tries"] in (1, 2)
