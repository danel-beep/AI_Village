"""Village stages and unlocks (aivillage/progress.py)."""

from aivillage import engine, llm, progress, state
from aivillage.invariants import check
from aivillage.registry import ACTIONS

ON = {"seed": 1, "progress": {"enabled": True}}


def step(w, decisions=None):
    events = engine.step(w, {n: {"action": {"name": a, "args": args}} for n, (a, args) in (decisions or {}).items()})
    check(w)
    return events


def stand(w, kind, n=1):
    """Pretend `n` buildings of `kind` stand in the village (as a later building module would report)."""
    src = lambda world: {kind: n}  # noqa: E731
    progress.BUILT_SOURCES.append(src)
    return src


def test_off_by_default_everything_open():
    w = engine.new_world({"seed": 1})
    assert not progress.enabled(w.config)
    assert progress.unlocked(w, "action:buy") and progress.unlocked(w, "feature:raids")
    assert progress.locked_actions(w) == []
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert "village_stage" not in obs and "locked_actions" not in obs


def test_camp_locks_market_and_government():
    w = engine.new_world(ON)
    assert progress.stage(w) == "camp"
    locked = progress.locked_actions(w)
    assert {"buy", "sell", "run_for_mayor", "dice", "install_lock"} <= set(locked)
    obs = engine.observe(w, "Anna", consume_inbox=False)
    assert not set(locked) & set(obs["available_actions"])
    assert obs["village_stage"]["stage"] == "camp"
    assert obs["village_stage"]["next_stage"] == "hamlet"
    assert obs["village_stage"]["next_stage_needs_standing"]["workbench"] == "0/1"


def test_locked_action_refused_and_world_unchanged():
    w = engine.new_world(ON)
    a = w.agents["Anna"]
    a.location = "market"
    coins = a.coins
    events = step(w, {"Anna": ("sell", {"item": "wood", "qty": 1})})
    err = [e.text for e in events if e.kind == "error"]
    assert err and "not possible in this village yet" in err[0] and "market_square" in err[0]
    assert a.coins == coins


def test_handbook_hides_locked_actions():
    w = engine.new_world(ON)
    obs = engine.observe(w, "Anna", consume_inbox=False)
    agent = llm.LLMAgent("Anna", w.agents["Anna"].profession, llm.StubClient("Anna"))
    system = agent.messages(obs)[0]["content"]
    assert "run_for_mayor(" not in system and "move(" in system
    assert "locked_actions" not in agent.messages(obs)[1]["content"]


def test_stage_climbs_by_buildings_and_unlocks_stick():
    w = engine.new_world(ON)
    srcs = [stand(w, "workbench"), stand(w, "market_square"), stand(w, "smithy")]
    try:
        events = step(w)
        stages = [e.data["stage"] for e in events if e.kind == "village_stage"]
        # 5 houses + a workbench make a hamlet; a market square and a smithy make a village
        assert stages == ["hamlet", "village"]
        assert progress.stage(w) == "village" and progress.unlocked(w, "action:sell")
        assert w.progress["reached"]["village"] == w.day
    finally:
        for s in srcs:
            progress.BUILT_SOURCES.remove(s)
    # the square is gone, but what it opened stays open; the stage never drops
    step(w)
    assert progress.unlocked(w, "action:sell") and progress.stage(w) == "village"
    assert not progress.unlocked(w, "action:run_for_mayor")


def test_start_stage_and_save_roundtrip():
    w = engine.new_world({**ON, "progress": {"enabled": True, "start_stage": "town"}})
    assert progress.stage(w) == "town"
    assert set(w.progress["reached"]) == {"camp", "hamlet", "village", "town"}
    assert progress.unlocked(w, "feature:raids")
    # a later start: the buildings its stages need count as standing, so a town has its market and town hall
    assert progress.unlocked(w, "action:buy") and progress.unlocked(w, "action:run_for_mayor")
    assert not progress.unlocked(w, "action:dice")  # no stage needs a tavern
    v = engine.new_world({**ON, "progress": {"enabled": True, "start_stage": "village"}})
    assert progress.unlocked(v, "action:buy") and "run_for_mayor" in progress.locked_actions(v)
    w2 = state.World.from_dict(w.to_dict())
    assert w2.progress == w.progress


def test_config_unlocks_override_defaults():
    w = engine.new_world({**ON, "progress": {"enabled": True, "unlocks": {"action:buy": {}, "action:say": {"stage": "hamlet"}}}})
    assert progress.unlocked(w, "action:buy")
    assert "say" in progress.locked_actions(w)


def test_leveled_kinds_counted():
    w = engine.new_world(ON)
    before = progress.built(w)
    assert before["house"] == sum(1 for p in w.plots.values() if p.kind == "home")
    home = next(p for p in w.plots.values() if p.kind == "home" and p.house == 1)
    home.house = 3
    have = progress.built(w)
    assert have["house@2"] == before["house@2"] + 1 and have["house@3"] == before["house@3"] + 1
    w.works.levels["well"] = 2
    assert progress.count(w, "well@2") == 1


def test_guard_registered_once():
    assert sum(1 for g in ACTIONS.guards if g is progress._guard) == 1


def test_rules_line_lists_what_each_stage_needs():
    from aivillage import modes
    from aivillage.config import make_config
    text = progress.facts(make_config(modes.world_override("survival")))
    assert "a hamlet once 3 house and 1 workbench stand" in text
    assert "a village once 1 market_square and 1 smithy stand" in text
    assert "3 house (level 2+)" in text
    assert progress.facts(make_config(modes.world_override("crafts"))) == ""
    assert text in llm.world_facts(make_config(modes.world_override("survival")))
