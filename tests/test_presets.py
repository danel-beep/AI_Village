"""«С нуля» is the only world; presets (presets/*.yaml) are knob values on top of it (modes.py, Danel 2026-10-08)."""
import pytest

from aivillage import engine, knobs, modes, runconfig
from aivillage.config import DEFAULT_CONFIG, make_config
from aivillage.llm import world_facts
from aivillage.registry import ACTIONS
from aivillage.run import main
from aivillage.state import World


def _keys_known(override: dict, base: dict, path: str = "") -> list[str]:
    bad = []
    for k, v in override.items():
        if k not in base:
            bad.append(path + k)
        elif isinstance(v, dict) and isinstance(base[k], dict) and k not in ("items", "locations", "inputs"):
            bad += _keys_known(v, base[k], path + k + ".")
    return bad


def test_only_new_presets_left():
    assert list(modes.PRESETS) == ["normal", "village", "harsh", "lawless"]
    assert not hasattr(modes, "MODES")
    assert _keys_known(modes.WORLD, DEFAULT_CONFIG) == []


@pytest.mark.parametrize("preset", list(modes.PRESETS))
def test_preset_settings_exist_and_world_builds(preset):
    spec = modes.PRESETS[preset]
    assert spec["title"] and spec["about"]
    assert _keys_known(spec["world"], DEFAULT_CONFIG) == []
    by_key = {k["key"]: k for k in knobs.KNOBS}
    assert set(spec["knobs"]) <= set(by_key) and set(spec["disabled"]) <= set(ACTIONS.specs)
    w = engine.new_world(runconfig.parse({"preset": preset, "days": 1}).world_override())
    assert w.config["preset"] == preset and w.config["bare_start"]["enabled"] and w.config["labor"]["mastery"]["enabled"]
    assert set(spec["disabled"]) <= set(w.config.get("disabled_actions") or [])
    # the screen's sliders show the preset's values
    d = knobs.preset_defaults(preset)
    for key, v in spec["knobs"].items():
        assert d[key] == v


def test_presets_change_what_they_say():
    normal = make_config(modes.world_override("normal"))
    assert normal["progress"]["start_stage"] == 0 or normal["progress"]["start_stage"] == "camp"
    assert make_config(modes.world_override("village"))["progress"]["start_stage"] == "village"
    harsh = make_config(modes.world_override("harsh"))
    assert harsh["food_supply"] == "scarce" and harsh["satiety_start"] <= 50
    assert harsh["seasons"]["night_hunger"]["winter"] > normal["seasons"]["night_hunger"]["winter"]
    assert harsh["threats"]["hostile"]["max_gap_days"] < normal["threats"]["hostile"]["max_gap_days"]
    assert harsh["threats"]["kinds"]["raid"]["hp"] > normal["threats"]["kinds"]["raid"]["hp"]
    assert (harsh["plots"]["buildings"]["garden_bed"]["yield"]
            == normal["plots"]["buildings"]["garden_bed"]["yield"] // 2)  # halved once, not twice
    lawless = make_config(modes.world_override("lawless"))
    assert lawless["steal_notice_chance"] == 0.05 and lawless["max_steal_qty"] == 10
    assert lawless["debts"]["auto_collect"] is False and lawless["laws"]["enforcement"] == "voluntary"


def test_user_world_overrides_preset_and_disabled_merge():
    rc = runconfig.parse({"preset": "lawless", "world": {"max_steal_qty": 2}, "mechanics": {"disabled": ["lend"]}})
    cfg = engine.new_world(rc.world_override()).config
    assert cfg["max_steal_qty"] == 2 and cfg["steal_notice_chance"] == 0.05
    assert cfg["disabled_actions"] == ["demand_debt", "install_lock", "lend", "report_theft", "rule_debt"]


def test_unknown_preset_and_old_modes_rejected():
    with pytest.raises(runconfig.ConfigError):
        runconfig.parse({"preset": "chaos"})
    with pytest.raises(runconfig.ConfigError):
        runconfig.parse({"mode": "crafts"})
    assert main(["--preset", "chaos", "--days", "1"]) == 2
    with pytest.raises(ValueError):
        knobs.to_run({"preset": "scarcity"})


def test_start_screen_logs_preset_and_knobs():
    r = knobs.to_run({"brains": "bots", "preset": "harsh", "max_steal_qty": 7})
    o = r["override"]
    assert r["preset"] == o["preset"] == "harsh"
    assert r["values"]["food"] == "scarce" and r["values"]["max_steal_qty"] == 7 and "start_knobs" not in o
    assert knobs.changed({"config": o, "start_knobs": r["values"]}) == {"brains": "bots", "max_steal_qty": 7}
    # the screen applies the preset like the run config does
    plain = make_config(modes.world_override("harsh"))
    cfg = make_config(o)
    for path in ("food_supply", "satiety_start", "npc_sell_ratio"):
        assert cfg[path] == plain[path]
    assert cfg["plots"]["buildings"]["garden_bed"]["yield"] == plain["plots"]["buildings"]["garden_bed"]["yield"]
    # food back to normal on the screen undoes the preset's scarce food
    o2 = knobs.to_run({"brains": "bots", "preset": "harsh", "food": "normal"})["override"]
    assert "food_supply" not in o2 or o2["food_supply"] != "scarce"


def test_rules_visible_to_agents_differ_by_preset():
    a = world_facts(engine.new_world(modes.world_override("normal")).config)
    b = world_facts(engine.new_world(modes.world_override("lawless")).config)
    assert a != b


def test_each_preset_runs_and_replays(tmp_path):
    from aivillage.run import replay
    for preset in modes.PRESETS:
        log = tmp_path / f"{preset}.jsonl"
        assert main(["--preset", preset, "--days", "2", "--bots", "trader,worker,thief,random", "--log", str(log)]) == 0
        w = replay(log)
        assert isinstance(w, World) and w.config["preset"] == preset
