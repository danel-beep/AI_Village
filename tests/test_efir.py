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


# ---------- «Часы судьбы» (viewer/fate.js) ----------

CFG = {"tick_minutes": 15, "day_start_hour": 6, "day_end_hour": 22, "satiety_loss_per_hour": 2,
       "satiety_loss_asleep_per_hour": 2, "satiety_loss_night": 10, "starving_health_loss_per_hour": 5,
       "starving_health_loss_night": 20, "fire_spread_hours": 6, "fire_night_hours": 4, "lives": 2,
       "polity": {"vote_hours": 24, "law_vote_hours": 24}}


def test_index_loads_fate():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert '<script src="fate.js"></script>' in html and html.index("fate.js") < html.index("efir.js")


def _fate_scene():
    """Day 1 from 06:00, 15-minute ticks. Elena hungry on her last life; a fire that jumps at tick 24 (its 6th hour);
    Boris starts a petition for a single ruler twice; a theft nobody saw, reported at tick 30; a leader ballot."""
    T = []
    for n in range(40):
        ag = {"Elena": {**_agent("camp", 6), "health": 40, "hospital_stays": 1},
              "Boris": _agent("camp", 70), "Dmitri": _agent("camp", 70)}
        t = _tick(n, ag)
        t["view"]["locations"] = {"home_Anna": "Anna's house", "home_Clara": "Clara's house", "camp": "Camp"}
        if n >= 1:
            t["view"]["fire_info"] = {"home_Anna": {"water_needed": 3, "hours_left": 10 - n // 4, "hours": n // 4}}
        T.append(t)
    ev = lambda n, kind, actor=None, text="", **d: T[n]["events"].append({"kind": kind, "actor": actor, "text": text, "data": d})
    ev(1, "fire", victim="Anna", house="home_Anna", cause="accident")
    ev(24, "fire", victim="Clara", house="home_Clara", cause="spread", spread_from="home_Anna")
    ev(2, "polity_founded", polity="p1")
    ev(3, "polity_form", polity="p1", form="assembly", votes={"assembly": 3})
    ev(3, "polity_leaders", polity="p1", rulers=[], keeper="Dmitri", votes={"Dmitri": 2, "Boris": 1})
    ev(4, "polity_petition", "Boris", polity="p1", form="ruler", signed=["Boris"], needed=2)
    ev(6, "polity_form", "Dmitri", polity="p1", form="assembly", old_form="assembly", signed=["Dmitri", "Elena"])
    ev(6, "polity_leaders", polity="p1", rulers=[], keeper=None)
    ev(8, "polity_petition", "Boris", polity="p1", form="ruler", signed=["Boris"], needed=2)
    ev(10, "steal", "Boris", victim="Dmitri", success=True, item="bread", qty=1, witnesses=[])
    ev(30, "theft_report", "Dmitri", thief="Boris", victim="Dmitri", fine=0)
    return T


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_fate_clocks():
    js = (VIEWER / "fate.js").read_text(encoding="utf-8")
    probe = js + """
    const T = %s, cfg = %s;
    const F = Fate.create(cfg);
    T.forEach((t, k) => F.add(T, k));
    const at = k => F.lines(T, k, { item: x => x === 'bread' ? 'хлеб' : x }).map(l => l.icon + ' ' + l.text);
    const G = Fate.create({ ...cfg, lives: 0 });
    T.forEach((t, k) => G.add(T, k));
    const lives0 = k => G.lines(T, k, { item: x => x === 'bread' ? 'хлеб' : x }).map(l => l.icon + ' ' + l.text);
    console.log(JSON.stringify({
      a5: at(5), a9: at(9), a12: at(12), a31: at(31),
      b9: lives0(9), b12: lives0(12), b31: lives0(31),
      // hunger: satiety 6 at 06:00 → 0 at 09:00, then -5 health an hour: 40 health lasts 8 more hours
      starve: F.collapse({ satiety: 6, health: 40 }, { day: 1, hour: 6, minute: 0 }, null, 24),
      night: F.collapse({ satiety: 4, health: 30 }, { day: 1, hour: 18, minute: 0 }, null, 24),
      fed: F.collapse({ satiety: 80, health: 100 }, { day: 1, hour: 6, minute: 0 }, null, 24),
      burn: [F.burnsIn(10, { hour: 8, minute: 0 }), F.burnsIn(5, { hour: 20, minute: 0 })],
      time: F.timeOf(64 + 4 * 13 + 2),
    }));
    """ % (json.dumps(_fate_scene()), json.dumps(CFG))
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out["starve"] == {"hours": 10, "night": False}         # satiety 0 at 09:00, health 35 → 0 at 16:00
    assert out["night"] == {"hours": 4, "night": True}            # health 15 at 22:00, the night takes 20
    assert out["fed"] is None
    assert out["burn"] == [{"hours": 10, "night": False}, {"hours": 2, "night": True}]
    assert out["time"] == {"day": 2, "hour": 19, "minute": 30}
    # never more than three clocks, the most urgent first: the last life, then the fire
    assert all(len(v) <= 3 for v in (out["a5"], out["a9"], out["a12"], out["a31"]))
    assert out["a5"][0].startswith("☠ Elena · последняя жизнь")
    assert out["a5"][1] == "🔥 Дом Anna · сгорит через 9 ч · перекинется через 5 ч · 🪣 3"
    # after the jump (tick 24) the first fire no longer says it will spread; before it, it does (no peeking ahead)
    assert not any("перекинется" in x for x in out["a31"])
    # the Nth petition for a single ruler is the Nth coup attempt; a leader ballot names the one who lost before
    assert out["a5"][2] == "📜 Петиция «один правитель» · 1 из 2 · 👑 Boris: переворот, попытка №1"
    assert out["b9"][1:] == ["📜 Петиция «один правитель» · 1 из 2 · 👑 Boris: переворот, попытка №2",
                             "🗳 Выбор казначея · до завтра, 15:30 · 👑 Boris, попытка №2"]
    # a theft nobody saw: only the viewer knows, until it is reported
    assert "🤫 Boris → хлеб у Dmitri · знает только зритель" in out["b12"]
    assert not any("🤫" in x for x in out["b31"])
