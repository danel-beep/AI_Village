"""«Эфир» replay (viewer/foresight.js + viewer/efir.js): countdowns found in the log, checked with node if present."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def test_index_loads_efir():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    for s in ("camera.js", "foresight.js", "efir.js"):
        assert f'<script src="{s}"></script>' in html
    assert html.index("foresight.js") < html.index("efir.js")
    assert "Efir.add(ticks.length - 1)" in html and "Efir.tick(hourSec, speed)" in html and "Efir.frame()" in html


def _agent(loc, sat=60, inv=None, asleep=False):
    return {"location": loc, "status": "active", "asleep": asleep, "satiety": sat, "health": 80, "coins": 0,
            "inventory": inv or {}}


def _tick(n, agents, events=(), decisions=None):
    return {"type": "tick", "tick": n, "decisions": decisions or {}, "events": list(events),
            "view": {"day": 1, "hour": 6 + n // 4, "minute": n % 4 * 15, "tick_minutes": 15, "agents": agents,
                     "locations": {"forest": "Forest", "river": "River"}}}


def _scene():
    """Boris hungry next to Dmitri's bread for 4 ticks, then steals it; later Clara (hungry) waits by Anna's fish and
    walks off; at the end a fire with no build-up."""
    T = []
    for n in range(4):
        T.append(_tick(n, {"Boris": _agent("forest", 25), "Dmitri": _agent("forest", 70, {"bread": 1})},
                       decisions={"Boris": {"thought": "hungry", "action": {"name": "whisper", "args": {"to": "Dmitri", "text": "bread?"}}}} if n == 1 else None))
    steal = {"kind": "steal", "actor": "Boris", "to": ["Boris"], "text": "You stole 1 bread from Dmitri.",
             "data": {"victim": "Dmitri", "success": True, "item": "bread", "qty": 1, "witnesses": [], "seen_by": ["Dmitri"]}}
    T.append(_tick(4, {"Boris": _agent("forest", 25, {"bread": 1}), "Dmitri": _agent("forest", 70)}, [steal]))
    for n in range(5, 30):
        T.append(_tick(n, {"Boris": _agent("forest", 60), "Dmitri": _agent("forest", 70)}))
    for n in range(30, 36):   # Clara: 6 ticks hungry at the river next to Anna's fish
        T.append(_tick(n, {"Clara": _agent("river", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    T.append(_tick(36, {"Clara": _agent("forest", 10), "Anna": _agent("river", 70, {"fish": 2})}))   # she walks off
    for n in range(37, 50):
        T.append(_tick(n, {"Clara": _agent("forest", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    fire = {"kind": "fire", "actor": None, "to": [], "text": "Smoke! Anna's house is on fire!", "data": {"victim": "Anna", "house": "home_Anna"}}
    T.append(_tick(50, {"Clara": _agent("forest", 10), "Anna": _agent("river", 70, {"fish": 2})}, [fire]))
    for n in range(51, 60):
        T.append(_tick(n, {"Clara": _agent("forest", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    return T


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_foresight_countdowns():
    js = (VIEWER / "foresight.js").read_text(encoding="utf-8")
    probe = js + """
    const T = %s;
    const score = (k, d) => ({steal: 9, fire: 10}[k] || 0);
    const F = Foresight.create(score);
    T.forEach((t, k) => F.add(T, k));
    const at = k => { const x = F.at(k); return x && [x.c.type, x.c.real, x.wait]; };
    console.log(JSON.stringify({
      list: F.list.map(c => [c.type, c.s, c.k, c.hero || null, c.owner || null, c.real]),
      at: [0, 3, 4, 6, 7, 31, 36, 44, 49, 50].map(at),
      theft: Foresight.outcome(T, F.list[0], x => x === 'bread' ? 'хлеб' : x),
      decoy: Foresight.outcome(T, F.list[1]),
      spoke: [F.spoke('Boris', 'Dmitri', 0, 3), F.spoke('Boris', 'Dmitri', 2, 3)],
      eta: Foresight.eta(k => k === 1 ? 3 : 2, 1, .5, 4),
      quiet: [F.next(10, 12, 5), F.next(40, 12, 5)],
    }));
    """ % json.dumps(_scene())
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out["list"] == [
        ["temptation", 0, 4, "Boris", "Dmitri", True],     # hungry by the bread from tick 0, steals at 4
        ["temptation", 30, 36, "Clara", "Anna", False],    # the same wait, but she walks off: a decoy
        ["fate", 44, 50, "Anna", None, True],              # a fire with no build-up: EV_LEAD (6) ticks ahead
    ]
    assert out["at"] == [
        ["temptation", True, True], ["temptation", True, True],    # counting down
        ["temptation", True, False], ["temptation", True, False],  # zero, then a short aftermath
        None,
        ["temptation", False, True], ["temptation", False, False],
        ["fate", True, True], ["fate", True, True], ["fate", True, False],
    ]
    assert out["theft"] == {"title": "🕵 Кража! Boris → хлеб у Dmitri", "line": "👁 Видели: Dmitri"}
    assert out["decoy"]["title"] == "🚶 Clara уходит ни с чем"
    assert out["spoke"] == [True, False]
    assert out["eta"] == 1.5 + 2 + 2
    assert out["quiet"] == [-1, 50]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_short_waits_and_overlaps():
    """A hungry moment of 2 ticks is no story; a decoy never hides a real countdown that overlaps it."""
    js = (VIEWER / "foresight.js").read_text(encoding="utf-8")
    T = []
    for n in range(2):
        T.append(_tick(n, {"Clara": _agent("river", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    for n in range(2, 6):
        T.append(_tick(n, {"Clara": _agent("forest", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    for n in range(6, 11):   # Elena waits by Anna's fish for 5 ticks and goes home ...
        T.append(_tick(n, {"Elena": _agent("river", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    T.append(_tick(11, {"Elena": _agent("forest", 10), "Anna": _agent("river", 70, {"fish": 2})}))
    death = {"kind": "death", "actor": None, "to": [], "text": "Anna died.", "data": {}}
    for n in range(12, 14):  # ... and Anna dies two ticks later: the real moment wins
        T.append(_tick(n, {"Elena": _agent("forest", 10), "Anna": _agent("river", 70)}, [death] if n == 13 else []))
    probe = js + """
    const T = %s, F = Foresight.create(k => k === 'death' ? 10 : 0);
    T.forEach((t, k) => F.add(T, k));
    console.log(JSON.stringify(F.list.map(c => [c.type, c.s, c.k, c.hero, c.real])));
    """ % json.dumps(T)
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out == [["fate", 7, 13, "Anna", True]]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_camera_scores_politics():
    js = (VIEWER / "camera.js").read_text(encoding="utf-8")
    probe = js + """
    console.log(JSON.stringify([
      Camera.score('polity_leaders', {keeper: 'Anna'}), Camera.score('polity_leaders', {keeper: null}),
      Camera.score('threat_arrived', {threat_kind: 'traveler'}), Camera.score('threat_arrived', {threat_kind: 'beast'}),
      Camera.score('polity_embezzle'), Camera.score('theft_report'), Camera.score('village_fight')]));
    """
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out == [8, 4, 6, 10, 9, 6, 9]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_overlaps_proposals_and_places():
    """What just happened keeps the screen; a coin theft is no food temptation; answers find their own proposal;
    a death follows the villager, a beast attack its house."""
    js = (VIEWER / "foresight.js").read_text(encoding="utf-8")
    ag = lambda: {"Boris": _agent("forest", 20), "Anna": _agent("forest", 70, {"bread": 1}), "Clara": _agent("river"),
                  "Dmitri": _agent("river")}
    ev = lambda kind, **kw: {"kind": kind, "to": [], "text": "", "data": {}, "actor": None, **kw}
    T = [_tick(n, ag()) for n in range(40)]
    T[10]["events"] = [ev("fire", data={"victim": "Anna", "house": "home_Anna"})]
    T[12]["events"] = [ev("beast_attack", text="The beast at Clara's house found nothing.", data={"home": "home_Clara"})]
    coins = ev("steal", actor="Boris", to=["Boris"], data={"victim": "Anna", "success": True, "item": "coins", "witnesses": []})
    T[20]["events"] = [coins]
    T[24]["events"] = [ev("proposal", actor="Dmitri", to=["Clara"]), ev("proposal", actor="Boris", to=["Clara"])]
    T[26]["events"] = [ev("wedding", actor="Clara", to=["Dmitri"])]
    T[34]["events"] = [ev("death", text="Anna died of hunger.", location="home_Anna")]
    probe = js + """
    const T = %s, F = Foresight.create(k => ({fire: 10, beast_attack: 9, steal: 9, death: 10, proposal: 7}[k] || 0));
    T.forEach((t, k) => F.add(T, k));
    const at = k => { const x = F.at(k); return x && [x.c.ev ? x.c.ev.kind : x.c.type, x.wait]; };
    console.log(JSON.stringify({
      list: F.list.map(c => [c.type, c.k, c.hero || null, c.owner || null, c.loc || null]),
      at: [9, 10, 11, 12, 13].map(at),
    }));
    """ % json.dumps(T)
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out["list"] == [
        ["fate", 10, "Anna", None, "home_Anna"],
        ["fate", 12, "Clara", None, "home_Clara"],      # the attacked house, not wherever its owner is
        ["choice", 20, "Boris", None, None],            # coins: a plain theft, not "hungry by the bread"
        ["choice", 24, "Dmitri", None, None],
        ["answer", 26, "Clara", "Dmitri", None],        # Clara answers Dmitri, not Boris who asked later
        ["fate", 34, "Anna", None, None],               # a death follows the villager, not their home (the grave)
    ]
    # the fire's zero and aftermath stay on screen although the beast's countdown is already running
    assert out["at"] == [["fire", True], ["fire", False], ["fire", False], ["beast_attack", False], ["beast_attack", False]]
