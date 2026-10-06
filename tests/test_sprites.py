"""Sprite atlas (viewer/sprites_data.js, built by scripts/build_sprites.py) matches what the viewer draws."""
import base64
import json
import re
import struct
from pathlib import Path

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def atlas():
    text = (VIEWER / "sprites_data.js").read_text()
    return json.loads(text[text.index("{"):text.rindex(";")])


def test_frames_inside_atlas_png():
    data = atlas()
    png = base64.b64decode(data["src"].split(",", 1)[1])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    for name, (x, y, fw, fh) in data["frames"].items():
        assert fw > 0 and fh > 0 and x + fw <= w and y + fh <= h, name


def test_every_sprite_the_viewer_names_exists():
    frames = atlas()["frames"]
    code = "".join((VIEWER / f).read_text() for f in ("pixelmap.js", "maplayer.js", "plotlayer.js", "mapgen.js", "sprites.js"))
    named = set(re.findall(r"SP\(g, '(\w+)'", code))   # literal names; the conditional ones below
    for a, b in re.findall(r"\? '(\w+)' : '(\w+)'", "\n".join(ln for ln in code.splitlines() if "SP(g" in ln)):
        named |= {a, b}
    named |= {"pine", "oak", "apple_tree", "copper_rock", "gold_rock", "crystal_rock", "boulder", "fire0", "fire3"}
    assert named <= set(frames), named - set(frames)
    named |= set(re.findall(r"'(tex_\w+)'", code))
    for level in (1, 2, 3):
        for style in ("", "a", "b", "c"):
            for roof in range(6):
                assert f"house{level}{style}_r{roof}" in frames
    for look in range(24):
        for pose in ("down", "step", "up", "side"):
            assert f"v{look}_{pose}" in frames


def test_house_meta_for_smoke_and_lights():
    meta = atlas()["meta"]
    for name in [f"house{level}{style}" for level in (1, 2, 3) for style in ("", "a", "b", "c")]:
        m = meta[name]
        assert m["chimney"][1] < 0 and (m["windows"] or name[-1] in "abc"), name   # a template may have shutters only
