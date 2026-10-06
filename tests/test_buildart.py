"""Code-drawn building and item art (viewer/buildart.js, viewer/icons.js): every kind and level draws inside
its box, levels look different, every icon is a valid 16x16 template, and the gallery page loads both."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parent.parent / "viewer"

# A fake 2D context that records the painted pixels (fillRect after translate / scale) for each drawing.
PROBE = """
const window = {};
function ctx() {
  const st = [], px = new Map(); let tx = 0, ty = 0, s = 1, fill = '';
  return { px, set fillStyle(c) { fill = c; }, get fillStyle() { return fill; },
    save() { st.push([tx, ty, s]); }, restore() { [tx, ty, s] = st.pop(); },
    translate(x, y) { tx += x * s; ty += y * s; }, scale(k) { s *= k; },
    fillRect(x, y, w, h) { for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) px.set((tx + (x + i) * s) + ',' + (ty + (y + j) * s), fill); } };
}
"""


def run_node(src):
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_every_building_level_draws_inside_its_box_and_levels_differ():
    js = (VIEWER / "buildart.js").read_text(encoding="utf-8")
    res = run_node(PROBE + js + """
    const out = {};
    for (const id of BuildArt.LIST) {
      const k = BuildArt.KINDS[id], [w, h] = k.size, looks = [];
      for (let l = 1; l <= k.levels; l++) {
        const g = ctx(); BuildArt.draw(g, id, l, 0, 0);
        const keys = [...g.px.keys()].map(p => p.split(',').map(Number));
        const out_of_box = keys.filter(([x, y]) => x < 0 || x >= w || y < -8 || y >= h).length;
        looks.push({ n: g.px.size, out: out_of_box, sig: [...[...g.px].sort().join(';')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7) });
      }
      out[id] = { levels: k.levels, group: k.group, looks };
    }
    for (const stage of [1, 2, 3]) { const g = ctx(); BuildArt.site(g, 56, 52, stage); out['site' + stage] = g.px.size; }
    console.log(JSON.stringify(out));
    """)
    kinds = [k for k in res if not k.startswith("site")]
    assert len(kinds) >= 20
    assert {res[k]["group"] for k in kinds} == {"personal", "craft", "shared"}
    assert sum(res[k]["levels"] == 3 for k in kinds) >= 20
    for k in kinds:
        looks = res[k]["looks"]
        for lv, look in enumerate(looks, 1):
            assert look["n"] > 60, (k, lv)
            assert look["out"] == 0, (k, lv, look["out"])
        assert len({look["sig"] for look in looks}) == len(looks), k
    assert res["site1"] > 0 and res["site1"] < res["site2"] < res["site3"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_icons_are_16x16_templates_with_known_colours():
    js = (VIEWER / "icons.js").read_text(encoding="utf-8")
    res = run_node(PROBE + js + """
    const out = {};
    for (const id of Icons.LIST) {
      const rows = Icons.rows(id), g = ctx(); Icons.draw(g, id, 0, 0, 1);
      out[id] = { group: Icons.ITEMS[id].group, rows: rows.length, widths: [...new Set(rows.map(r => r.length))],
        bad: [...rows.join('')].filter(c => c !== '.' && !Icons.PAL[c]), n: g.px.size,
        out: [...g.px.keys()].filter(p => p.split(',').some(v => +v < 0 || +v > 15)).length };
    }
    console.log(JSON.stringify(out));
    """)
    groups = {v["group"] for v in res.values()}
    assert groups == {"res", "tool", "weapon", "armor", "food"}
    for want in ["wood", "stone", "ore", "iron", "stone_axe", "iron_axe", "stone_pickaxe", "iron_pickaxe",
                 "club", "spear", "bow", "sword", "leather_armor", "iron_armor", "bread", "fish", "berries"]:
        assert want in res, want
    for id_, v in res.items():
        assert v["rows"] == 16 and v["widths"] == [16] and not v["bad"], id_
        assert v["n"] > 20 and v["out"] == 0, id_


def test_gallery_loads_both_scripts():
    html = (VIEWER / "gallery.html").read_text(encoding="utf-8")
    assert '<script src="buildart.js"></script>' in html and '<script src="icons.js"></script>' in html
