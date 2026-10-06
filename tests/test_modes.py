import pytest

from aivillage import engine, modes, runconfig
from aivillage.config import DEFAULT_CONFIG
from aivillage.llm import world_facts
from aivillage.run import main
from aivillage.state import World


def _keys_known(override: dict, base: dict, path: str = "") -> list[str]:
    bad = []
    for k, v in override.items():
        if k not in base:
            bad.append(path + k)
        elif isinstance(v, dict) and isinstance(base[k], dict) and k not in ("items", "locations"):
            bad += _keys_known(v, base[k], path + k + ".")
    return bad


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_mode_settings_exist_and_world_builds(mode):
    spec = modes.MODES[mode]
    assert spec["title"] and spec["about"]
    assert _keys_known(spec["world"], DEFAULT_CONFIG) == []
    rc = runconfig.parse({"mode": mode, "days": 1})
    w = engine.new_world(rc.world_override())
    assert w.config["economy_mode"] == mode
    for k, v in spec["world"].items():
        if not isinstance(v, dict):
            assert w.config[k] == v
    assert set(modes.disabled(mode)) <= set(w.config.get("disabled_actions") or [])


def test_user_world_overrides_mode_and_disabled_merge():
    rc = runconfig.parse({"mode": "lawless", "world": {"max_steal_qty": 2}, "mechanics": {"disabled": ["lend"]}})
    cfg = engine.new_world(rc.world_override()).config
    assert cfg["max_steal_qty"] == 2 and cfg["steal_notice_chance"] == modes.MODES["lawless"]["world"]["steal_notice_chance"]
    assert cfg["disabled_actions"] == ["install_lock", "lend", "report_theft"]


def test_partial_location_override_keeps_other_resources():
    cfg = engine.new_world(modes.world_override("scarcity")).config
    assert cfg["locations"]["river"]["resources"]["fish"]["regen"] == 3
    assert cfg["plots"]["buildings"]["garden_bed"]["yield"] == 3 and "crop" in cfg["plots"]["buildings"]["garden_bed"]
    assert "wood" in cfg["locations"]["forest"]["resources"] and "water" in cfg["locations"]["river"]["resources"]


def test_unknown_mode_rejected():
    with pytest.raises(runconfig.ConfigError):
        runconfig.parse({"mode": "chaos"})
    assert main(["--mode", "chaos", "--days", "1"]) == 2


def test_rules_visible_to_agents_differ_by_mode():
    a = world_facts(engine.new_world(modes.world_override("peaceful")).config)
    b = world_facts(engine.new_world(modes.world_override("lawless")).config)
    assert "90%" in a and "5%" in b and a != b


def test_each_mode_runs_and_replays(tmp_path):
    from aivillage.run import replay
    for mode in modes.MODES:
        log = tmp_path / f"{mode}.jsonl"
        assert main(["--mode", mode, "--days", "2", "--bots", "trader,worker,thief,random", "--log", str(log)]) == 0
        assert isinstance(replay(log), World)
