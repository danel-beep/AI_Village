"""Fight animations on the map (viewer/combat.js): the choreography planned from a tick's events, checked with node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def test_viewer_loads_combat():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert '<script src="combat.js"></script>' in html
    assert html.index("actors.js") < html.index("combat.js") < html.index("camera.js")
    pm = (VIEWER / "pixelmap.js").read_text(encoding="utf-8")
    for call in ("CB.frame(", "CB.stand(", "CB.pose(", "CB.draw(", "CB.overlay("):
        assert call in pm
    assert "Combat.threat(" in (VIEWER / "threatlayer.js").read_text(encoding="utf-8")


def _ev(kind, actor=None, loc="forest", **data):
    return {"kind": kind, "actor": actor, "location": loc, "text": kind, "to": [], "data": data}


def _plan(events):
    probe = (f"const C = require({json.dumps(str(VIEWER / 'combat.js'))});"
             f"console.log(JSON.stringify(C.plan({{tick: 5, events: {json.dumps(events)}}})));")
    return json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_plan_reads_every_kind_of_fight():
    rounds = [{"round": 1, "by": "Boris", "hit": True, "damage": 6}, {"round": 1, "by": "Clara", "hit": False, "damage": 0}]
    p = _plan([
        _ev("fight", "Boris", attacker="Boris", defender="Clara", winner="Clara", rounds=rounds, weapons={"Boris": "club", "Clara": None}),
        _ev("defend", "Anna", "home_Anna", threat="t1", threat_kind="raid", hit=True, damage=5, hurt=3, weapon="spear"),
        _ev("defend", "Dmitri", "home_Anna", threat="t1", threat_kind="raid", hit=False, damage=0, hurt=0, weapon=None),
        _ev("beast_attack", None, None, threat="t2", home="home_Elena", victim="Elena", damage=7),
        _ev("plundered", None, None, threat="t1", home="home_Anna"),
        _ev("hunt_kill", "Anna", "grove", hunters=["Anna", "Boris"], killer="Anna", weapons={"Anna": "bow", "Boris": None}),
        _ev("steal", "Dmitri", victim="Elena", success=True, item="bread", witnesses=["Anna"], seen_by=["Elena"]),
        _ev("steal", "Boris", victim="Anna", success=False),
    ])
    d = p["duels"][0]
    assert [(b["by"], b["on"], b["hit"], b["dmg"]) for b in d["blows"]] == [("Boris", "Clara", True, 6), ("Clara", "Boris", False, 0)]
    assert (d["winner"], d["loser"], d["weapons"]["Boris"]) == ("Clara", "Boris", "club")
    raid, beast = sorted(p["raids"], key=lambda r: r["threat"])
    assert raid["fighters"] == ["Anna", "Dmitri"] and raid["weapons"] == {"Anna": "spear", "Dmitri": None}
    assert [(b["by"], b["on"], b["hit"]) for b in raid["blows"]] == [("Anna", "T:t1", True), ("T:t1", "Anna", True), ("Dmitri", "T:t1", False)]
    assert beast["fighters"] == ["Elena"] and beast["blows"] == [{"by": "T:t2", "on": "Elena", "hit": True, "dmg": 7}]
    assert p["strikes"] == [{"threat": "t1", "kind": "raid", "loc": "home_Anna"}]
    assert {h["n"]: (h["weapon"], h["win"]) for h in p["hunts"]} == {"Anna": ("bow", True), "Boris": (None, False)}
    assert len(p["thefts"]) == 1 and sorted(p["thefts"][0]["seen"]) == ["Anna", "Elena"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_plan_of_a_quiet_tick_is_empty():
    p = _plan([_ev("work", "Anna", resource="wood"), _ev("fight", "Boris")])   # a fight event without its people is skipped
    assert p == {"duels": [], "raids": [], "strikes": [], "hunts": [], "thefts": []}
