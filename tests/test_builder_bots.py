"""Builder bots (bots.BuilderBot) in the «С нуля» mode: from an empty camp they feed themselves, raise houses
and the village climbs stages; the run replays exactly. Balance numbers: docs/runs/survival-bots.md."""

from aivillage import engine, modes, progress
from aivillage.bots import BuilderBot, WorkerBot
from aivillage.run import bots_decider, replay, run


def survival(n=6, seed=2, **extra):
    return engine.new_world(modes.world_override("survival", {"seed": seed, "population": {"size": n},
                                                              "map": {"procedural": True}, "tick_minutes": 15, **extra}))


def test_builders_climb_from_camp_and_replay(tmp_path):
    w = survival()
    log = tmp_path / "b.jsonl"
    run(w, bots_decider(w, ["builder"], 2), 9, None, log, check_every_tick=True)
    assert progress.stage_index(w) >= 2  # hamlet and village stand by day 9
    assert all(a.status == "active" for a in w.agents.values())
    assert sum(1 for p in w.plots.values() if p.kind == "home" and p.house >= 1) >= 3
    assert replay(log).hash() == w.hash()


def test_builder_is_a_worker_outside_survival():
    w = engine.new_world(modes.world_override("crafts", {"seed": 1}))
    name = sorted(w.agents)[0]
    obs = engine.observe(w, name, consume_inbox=False)
    assert "building_sites" not in obs
    assert BuilderBot(name, 1).decide(obs) == WorkerBot(name, 1).decide(obs)
