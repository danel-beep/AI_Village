"""Villager motion on the map (viewer/actors.js Actors.place): the drawn villager walks after the spot the log puts
them at, at a steady pace, however unevenly game time runs (fast replay walks, late or bursty live ticks), checked
with node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def _run(frames):
    """frames: [[tick, x, y], ...] targets at 60 fps -> [[x, y, moving], ...] drawn positions."""
    probe = (f"const src = require('fs').readFileSync({json.dumps(str(VIEWER / 'actors.js'))}, 'utf8');"
             "const A = new Function(src + '; return Actors;')();"
             f"const out = {json.dumps(frames)}.map(([t, x, y]) => {{ const p = A.place('n', t, {{x, y}}, 1 / 60);"
             " return [p.x, p.y, p.moving]; });"
             "console.log(JSON.stringify(out));")
    return json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)


def _speeds(out):
    return [((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** .5 * 60 for a, b in zip(out, out[1:])]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_a_jump_is_walked_not_teleported():
    # a new hour puts the work spot 300 px away: no teleport, no sprint, they arrive and stand still
    frames = [[1, 0, 0]] * 10 + [[2, 300, 0]] * 600
    out = _run(frames)
    assert max(_speeds(out)) < 100
    assert out[-1][:2] == [300, 0] and out[-1][2] is False


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_a_fast_replay_walk_is_slowed_to_a_steady_pace():
    # the game walks 400 px in half a second (one quarter-hour tick at replay speed): drawn at a walking pace
    frames = [[1, 0, 0]] * 5 + [[2 + k // 8, 400 * k / 30, 0] for k in range(31)] + [[6, 400, 0]] * 900
    out = _run(frames)
    sp = _speeds(out)
    assert max(sp) < 150
    assert out[-1][0] == 400 and out[-1][2] is False
    moving = [m for _, _, m in out[6:]]
    assert moving.index(False) > 300   # one walk from start to end, no stop on the way
    assert all(moving[:moving.index(False)])


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_a_scrub_snaps():
    out = _run([[1, 0, 0]] * 5 + [[40, 500, 200]] * 2)
    assert out[-1][:2] == [500, 200]
