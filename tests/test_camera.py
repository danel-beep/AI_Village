"""The auto camera (viewer/camera.js), checked with node: it glides without jerks, stays with a villager when nothing
happens, pulls back only as far as the villagers need, and frames the first picture at once (the loading screen
waits for that)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"

# A tiny DOM, enough for Camera.attach.
STUB = """
const el = () => ({ style: {}, appendChild() {}, setAttribute() {}, addEventListener() {}, querySelector() {} });
global.document = { createElement: el, activeElement: null };
global.window = { addEventListener() {} };
global.getComputedStyle = () => ({ position: 'relative' });
global.localStorage = { getItem: () => null, setItem() {} };
"""


def _run(body):
    src = json.dumps(str(VIEWER / "camera.js"))
    probe = (STUB + f"const Camera = new Function(require('fs').readFileSync({src}, 'utf8') + '; return Camera;')();"
             "const canvas = Object.assign(el(), { width: 1600, height: 1200, parentElement: el(), offsetTop: 0, offsetHeight: 600 });"
             "Camera.attach(canvas, 800, 600, 2);" + body)
    return json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)


# Frames at 60 fps; villagers given as {name: [x, y]}; events can be added per tick.
SIM = """
function sim(frames, pos, evAt = {}) {
  const out = [];
  for (let f = 0; f < frames; f++) {
    const tick = 1 + Math.floor(f / 30), P = typeof pos === 'function' ? pos(f) : pos;
    const agents = Object.fromEntries(Object.keys(P).map(n => [n, {}]));
    const t = { tick, events: evAt[tick] || [], view: { agents, locations: {}, threats: [], fires: [] } };
    Camera.direct(1 / 60, t, n => P[n], () => null, String);
    Camera.update(1 / 60, null, n => P[n]);
    const v = Camera.view(); out.push([v.x0 + 400 / v.z, v.y0 + 300 / v.z, v.z, Camera.ready()]);
  }
  return out;
}
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_first_picture_is_framed_at_once_and_quiet_time_follows_a_villager():
    out = _run(SIM + "console.log(JSON.stringify(sim(60 * 40, { Anna: [200, 200], Boris: [260, 240] })));")
    assert out[0][3] is True                        # ready on the first frame: the loading screen can go
    assert out[0][2] == 2                           # two villagers close together: not the whole village (z 1)
    assert abs(out[0][0] - 230) < 1 and abs(out[0][1] - 195) < 1   # framed around them
    zs = [o[2] for o in out]
    assert min(zs) > 1.5                            # never pulled back to the whole map
    end = out[-1]                                   # after the opening group shot: on one of them, close
    assert end[2] == pytest.approx(2, abs=.01)
    assert min(abs(end[0] - 200) + abs(end[1] - 200), abs(end[0] - 260) + abs(end[1] - 240)) < 5


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_far_apart_villagers_pull_back_further_but_only_now_and_then():
    out = _run(SIM + "console.log(JSON.stringify(sim(60 * 120, { Anna: [80, 80], Boris: [720, 520] })));")
    zs = [o[2] for o in out]
    assert zs[0] == pytest.approx(1, abs=.05)        # the opening shot holds both: the whole map here
    wide = sum(z < 1.5 for z in zs[60 * 10:]) / len(zs[60 * 10:])
    assert 0 < wide < .2                             # later: mostly on one villager, a short wide shot now and then


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_moving_to_a_new_shot_eases_in_and_out():
    # quiet on Anna, then a theft by Boris far away: the camera glides there with no jump in speed
    out = _run(SIM + "console.log(JSON.stringify(sim(60 * 16, { Anna: [150, 150], Boris: [600, 400] },"
               " { 10: [{ kind: 'theft', actor: 'Boris' }] })));")
    sp = [((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** .5 * 60 for a, b in zip(out, out[1:])]
    acc = [abs(b - a) * 60 for a, b in zip(sp, sp[1:])]
    assert max(acc) < 1500                           # map px/s²: no sudden start or stop (a snap would be ~10^5)
    assert abs(out[-1][0] - 600) < 5 and abs(out[-1][1] - 400) < 5
    assert out[-1][2] == pytest.approx(2.6, abs=.05)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_a_walking_villager_stays_in_the_middle():
    # the only villager walks 60 map px/s to the right: the camera keeps up instead of trailing far behind
    out = _run(SIM + "console.log(JSON.stringify(sim(60 * 14, f => ({ Anna: [200 + Math.max(0, f / 60 - 8) * 60, 300] }))));")
    assert abs(out[-1][0] - (200 + 6 * 60)) < 40
