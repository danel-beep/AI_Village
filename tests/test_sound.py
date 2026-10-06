"""Viewer sound (viewer/sound.js): wired into index.html, event -> cue mapping and mood checked with node if present."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def test_index_loads_and_calls_sound():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert '<script src="sound.js"></script>' in html
    assert "Sound.update(header, ticks, i, playing)" in html


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_cues_and_mood():
    js = (VIEWER / "sound.js").read_text(encoding="utf-8")
    probe = """
    const window = {}, document = {readyState: 'complete', getElementById: () => null, addEventListener() {}};
    window.addEventListener = () => {};
    const localStorage = {getItem: () => null, setItem() {}};
    """ + js + """
    const S = window.Sound, ev = ks => ks.map(kind => ({kind}));
    const hdr = {config: {seasons: {enabled: true, length_days: 7, order: ['spring', 'summer', 'autumn', 'winter']}}};
    console.log(JSON.stringify({
      a: S.cues(ev(['move', 'work', 'say'])),
      b: S.cues(ev(['fire_out', 'fire', 'fight', 'buy', 'sell', 'election'])),
      c: S.cues(ev(['robbed', 'witness', 'crisis'])),
      day: S.mood(hdr, {day: 1, hour: 12, agents: {A: {status: 'active', location: 'market'}}}),
      night: S.mood(hdr, {day: 22, hour: 23, agents: {}, fires: ['home_A']}),
    }));
    """
    out = json.loads(subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out["a"] == []
    assert out["b"] == ["hiss", "flare", "punch"]  # each cue once, at most 3
    assert out["c"] == ["sneak", "whistle", "omen"]
    assert out["day"] == {"season": "spring", "night": False, "dusk": False, "crowd": 1, "fires": 0, "minor": False}
    assert out["night"]["season"] == "winter" and out["night"]["night"] and out["night"]["minor"] and out["night"]["crowd"] == 0
