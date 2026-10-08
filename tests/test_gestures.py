"""Things passing between people and emotes on the map (viewer/gestures.js), planned from a tick's events with node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"
NAMES = ["bread", "fish", "wood", "berries"]


def test_viewer_loads_gestures():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert html.index("combat.js") < html.index("gestures.js") < html.index("camera.js")
    pm = (VIEWER / "pixelmap.js").read_text(encoding="utf-8")
    assert "GS.frame(" in pm and "GS.draw(" in pm and "GS.overlay(" in pm


def _ev(kind, actor, text="", to=(), **data):
    return {"kind": kind, "actor": actor, "location": "square", "text": text, "to": list(to), "data": data}


def _plan(events):
    probe = (f"const G = require({json.dumps(str(VIEWER / 'gestures.js'))});"
             f"console.log(JSON.stringify(G.plan({{tick: 1, events: {json.dumps(events)}}}, {json.dumps(NAMES)})));")
    return json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_plan_moves_and_emotes():
    p = _plan([
        _ev("give", "Anna", "Anna gave 2 bread to Boris.", ["Boris"]),
        _ev("trade", "Clara", "Dmitri and Clara traded: 3 fish for 4 wood.", ["Dmitri"], partner="Dmitri"),
        _ev("trade", "Elena", "Anna and Elena traded: 2 berries for 5 coins.", ["Anna"], partner="Anna"),
        _ev("lend", "Elena", "Elena lent 5 coins to Anna", ["Anna"]),
        _ev("sell", "Boris", "Boris sold 2 wood to the trader for 4 coins."),
        _ev("wedding", "Boris", "Clara and Boris are married!", ["Clara"]),
        _ev("proposal_refused", "Elena", "Elena refused to marry Dmitri.", ["Dmitri"]),
        _ev("say", "Anna", "hello"),
    ])
    moves = [(m["from"], m["to"], m["place"], m["item"]) for m in p["moves"]]
    assert moves == [("Anna", "Boris", None, "bread"),
                     ("Dmitri", "Clara", None, "fish"), ("Clara", "Dmitri", None, "wood"),
                     ("Anna", "Elena", None, "berries"), ("Elena", "Anna", None, "coins"),
                     ("Elena", "Anna", None, "coins"),
                     ("Boris", None, "market", "wood"), (None, "Boris", "market", "coins")]
    assert [(e["n"], e["sign"]) for e in p["emotes"]] == [("Boris", "😊"), ("Boris", "💞"), ("Clara", "💞"), ("Dmitri", "💔")]
