from pathlib import Path

import pytest

from aivillage import engine
from aivillage.run import main, replay
from aivillage.runconfig import ConfigError, load, parse

EXAMPLE = Path(__file__).parent.parent / "configs" / "example.yaml"


def test_example_config_runs_and_replays(tmp_path):
    log = tmp_path / "x.jsonl"
    assert main(["--config", str(EXAMPLE), "--days", "2", "--log", str(log)]) == 0
    w = replay(log)
    assert sorted(w.agents) == ["Anna", "Boris", "Clara"]
    assert w.config["start_coins"] == 30 and w.config["disabled_actions"] == ["lend"]


def test_brains_and_god_ticks():
    rc = parse({"model": "stub", "agents": [{"name": "A", "profession": "farmer", "bot": "thief"},
                                             {"name": "B", "profession": "smith"}],
                "god": [{"day": 1, "hour": 6, "name": "fire", "args": {"person": "A"}},
                        {"day": 2, "hour": 10, "name": "fire", "args": {"person": "B"}}]})
    assert rc.brains(["A", "B"]) == {"A": ("bot", "thief"), "B": ("model", "stub")}
    w = engine.new_world(rc.world_override())
    assert sorted(rc.god_script(w.config)) == [0, 16 + 4]


@pytest.mark.parametrize("data,msg", [
    ({"dayz": 3}, "dayz"),
    ({"world": {"start_coin": 5}}, "start_coin"),
    ({"mechanics": {"disabled": ["fly"]}}, "fly"),
    ({"mechanics": {"disabled": ["wait"]}}, "wait"),
    ({"agents": [{"name": "A", "profession": "pilot"}]}, "pilot"),
    ({"agents": [{"name": "A", "profession": "farmer", "model": "m", "bot": "worker"}]}, "not both"),
    ({"bot": "ninja"}, "ninja"),
    ({"god": [{"day": 1, "hour": 3, "name": "fire", "args": {"person": "Anna"}}]}, "hour"),
    ({"god": [{"day": 1, "hour": 8, "name": "meteor"}]}, "meteor"),
    ({"god": [{"day": 1, "hour": 8, "name": "rumor", "args": {"text": "x"}}]}, "bad args"),
])
def test_bad_configs_fail_early(data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse(data)


def test_bad_yaml(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("days: [", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(p)


def test_disabled_action_is_rejected_and_hidden():
    w = engine.new_world({"disabled_actions": ["steal"]})
    a = sorted(w.agents)[0]
    assert "steal" not in engine.observe(w, a)["available_actions"]
    events = engine.step(w, {a: {"action": {"name": "steal", "args": {}}}})
    assert any(e.kind == "error" and "not possible" in e.text for e in events)
