"""Seasons calendar fitted to the run, frost on growing beds, start-screen knobs, viewer calendar parity."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from aivillage import engine, knobs, llm, seasons
from aivillage.config import make_config
from aivillage.invariants import check

VIEWER = Path(__file__).resolve().parent.parent / "viewer"
FARM = [{"name": "Anna", "profession": "farmer"}, {"name": "Boris", "profession": "fisher"}]


def calendar_of(days, length=0):
    cfg = make_config({"seasons": seasons.calendar(days, length)})
    return cfg, [seasons.season_of(cfg, d) for d in range(1, days + 1)]


@pytest.mark.parametrize("days,length,expect", [
    (1, 0, ["winter"]),
    (2, 0, ["autumn", "winter"]),
    (3, 0, ["summer", "autumn", "winter"]),
    (7, 0, ["spring", "summer", "summer", "autumn", "autumn", "winter", "winter"]),
    (2, 7, ["autumn", "winter"]),
    (3, 7, ["autumn", "autumn", "winter"]),
])
def test_short_runs_end_in_winter(days, length, expect):
    assert calendar_of(days, length)[1] == expect


def test_longer_than_a_year_starts_in_spring():
    cfg, s = calendar_of(30, 7)
    assert s[0] == "spring" and s[-1] == "spring" and s.count("winter") == 7


def test_days_left_and_announcement_follow_the_offset():
    cfg, _ = calendar_of(3, 7)  # late autumn, 2 days left, then winter
    assert [seasons.days_left(cfg, d) for d in (1, 2, 3)] == [2, 1, 7]
    w = engine.new_world({"agents": FARM, "seasons": seasons.calendar(3, 7)})
    t = engine.observe(w, "Anna", consume_inbox=False)["time"]
    assert (t["season"], t["season_days_left"], t["next_season"]) == ("autumn", 2, "winter")
    while w.day < 3:
        engine.step(w, {})
    assert any("Winter has come" in n for n in engine.observe(w, "Anna", consume_inbox=False)["news"])


def test_frost_kills_growing_beds_but_not_ripe_stock():
    w = engine.new_world({"agents": FARM, "seasons": seasons.calendar(2)})  # autumn, then winter on day 2
    beds = [b for b in w.plots["home_Anna"].buildings if b["kind"] == "garden_bed"]
    assert beds and all(b["crop"] == "grain" for b in beds)  # farmer starts with sown beds, ripe on day 2
    while w.day < 2:
        engine.step(w, {})
    check(w)
    assert all(b["crop"] is None and not b["items"] for b in beds)
    news = engine.observe(w, "Anna", consume_inbox=False)["news"]
    assert any("Frost killed the grain" in n for n in news)

    w = engine.new_world({"agents": FARM, "seasons": {**seasons.calendar(3), "frost": []}})  # no frost: ripens
    beds = [b for b in w.plots["home_Anna"].buildings if b["kind"] == "garden_bed"]
    while w.day < 3:
        engine.step(w, {})
    assert all(b["items"].get("grain") for b in beds)


def test_winter_start_has_no_sown_beds():
    w = engine.new_world({"agents": FARM, "seasons": seasons.calendar(1)})
    assert all(not b.get("crop") for b in w.plots["home_Anna"].buildings)


def test_start_screen_fits_the_calendar_to_the_run():
    o = knobs.to_run({"days": 3})["override"]["seasons"]
    assert (o["length_days"], o["start"], o["offset_days"]) == (1, "summer", 0)
    o = knobs.to_run({"days": 3, "season_days": 7})["override"]["seasons"]
    assert (o["length_days"], o["start"], o["offset_days"]) == (7, "autumn", 5)
    o = knobs.to_run({"days": 3, "season_days": 2, "season_start": "spring"})["override"]["seasons"]
    assert (o["length_days"], o["start"], o["offset_days"]) == (2, "spring", 0)
    assert "length_days" not in knobs.to_run({"days": 3, "seasons": False})["override"].get("seasons", {})


def test_prompt_mentions_seasons():
    cfg = make_config({})
    facts = llm.world_facts(cfg)
    assert "Seasons: spring, summer, autumn, winter, 7 day(s) each" in facts and "freezes" in facts
    assert seasons.fact(make_config({"seasons": {"enabled": False}})) == ""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_viewer_calendar_matches_python():
    js = (VIEWER / "seasonlayer.js").read_text(encoding="utf-8")
    cases = [seasons.calendar(d, n) for d, n in [(3, 0), (7, 0), (3, 7), (30, 7), (10, 3)]]
    probe = "const window = {};\n" + js + f"""
    const cases = {json.dumps(cases)}, order = ['spring', 'summer', 'autumn', 'winter'];
    console.log(JSON.stringify(cases.map(c => Array.from({{length: 30}}, (_, d) =>
      window.SeasonLayer.seasonOf({{config: {{seasons: {{enabled: true, order, ...c}}}}}}, d + 1)))));
    """
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    for c, js_days in zip(cases, out):
        cfg = make_config({"seasons": c})
        assert js_days == [seasons.season_of(cfg, d) for d in range(1, 31)]
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert '<script src="seasonlayer.js"></script>' in html
