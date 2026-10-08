"""«С нуля» on the map (viewer/buildlayer.js, viewer/itemicons.js): every building of the construction catalog has
art, a world with houses, yard buildings, common buildings and sites draws without errors, «Обычный» is left alone,
item icons exist for the survival items, and index.html loads the files in the right order."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from aivillage import modes
from aivillage.config import make_config

VIEWER = Path(__file__).resolve().parent.parent / "viewer"
node = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")

# A fake canvas world: contexts count what is drawn, document.createElement makes fake canvases.
FAKE = """
const window = globalThis;
function ctx() {
  const c = { draws: 0, rects: 0, fillStyle: '', globalAlpha: 1, imageSmoothingEnabled: true,
    save() {}, restore() {}, translate() {}, scale() {}, fillRect() { c.rects++; }, drawImage() { c.draws++; },
    getTransform() { return { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }; } };
  return c;
}
const document = { createElement: () => { const g = ctx(); return { width: 0, height: 0, getContext: () => g,
  toDataURL: () => 'data:image/png;base64,x' }; } };
globalThis.document = document;
"""


def run_node(src):
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def js(*names):
    return "\n".join((VIEWER / n).read_text(encoding="utf-8") for n in names)


def survival():
    return make_config(modes.world_override("normal"))


@node
def test_every_catalog_kind_has_art():
    kinds = list(survival()["construction"]["catalog"])
    res = run_node(FAKE + js("buildart.js", "buildlayer.js") + f"""
    const kinds = {json.dumps(kinds)};
    console.log(JSON.stringify(kinds.filter(k => !BuildArt.KINDS[BuildLayer.art(k)])));""")
    assert res == []


@node
def test_survival_world_draws_and_normal_mode_is_left_alone():
    res = run_node(FAKE + js("buildart.js", "buildlayer.js") + """
    const T = 16, layout = { houses: [{ name: 'A', x: 32, y: 32 }, { name: 'B', x: 160, y: 32 }],
      plots: { home_A: [16, 16, 80, 64] }, box: { square: [200, 120, 112, 80], market: [200, 20, 112, 48] },
      anchors: { square: [256, 160] } };
    const kit = { layout, T, C: {}, R: (g, x, y, w, h, c) => g.fillRect(x, y, w, h), P() {}, blob() {}, rnd: () => .5 };
    const hdr = mode => ({ config: { construction: { enabled: mode === 'survival' }, bare_start: { applied: mode === 'survival' },
      progress: { stages: [{ id: 'camp' }, { id: 'hamlet', requires: { buildings: { house: 3, workbench: 1 } } }] } } });
    const out = {};
    out.normal = BuildLayer.init(kit, hdr('crafts'));
    out.on = BuildLayer.init(kit, hdr('survival'));
    out.empty = BuildLayer.empty(hdr('survival'));
    const view = { day: 1, plots: {
        home_A: { house: 3, cells: 6, buildings: [{ id: 'b1', kind: 'workbench', level: 1, items: {} }, { id: 'b2', kind: 'garden_bed', items: {} }] },
        home_B: { house: 0, cells: 6, buildings: [{ id: 'b3', kind: 'shelter', level: 1, items: {} }] } },
      buildings: [{ id: 'c1', kind: 'campfire', level: 2, location: 'square' }, { id: 'c2', kind: 'market_square', level: 1, location: 'square' }],
      sites: [{ id: 's1', kind: 'house', level: 1, location: 'home_B', done: .5, workers: ['B'] },
              { id: 's2', kind: 'town_hall', level: 1, location: 'square', done: .1, workers: [] },
              { id: 's3', kind: 'granary', level: 1, location: 'home_A', done: .9, workers: [] }] };
    const g = ctx();
    BuildLayer.draw(g, { view, events: [{ kind: 'building_done', location: 'square', data: { what: 'campfire' } }] }, .3);
    out.draws = g.draws;
    const s = ctx(); s.canvas = { width: 800 }; s.measureText = t => ({ width: t.length * 8 }); s.fillText = () => { s.texts = (s.texts || 0) + 1; };
    BuildLayer.banner(s, { view, events: [{ kind: 'village_stage', data: { stage: 'camp' } }] }, 1000);
    BuildLayer.banner(s, { view, events: [] }, 1500);
    out.texts = s.texts;
    const w = ctx(); BuildLayer.gear(w, { x: 10, y: 10, dir: 'right', act: 'idle' }, { club: 1 });
    out.gear = w.draws;
    console.log(JSON.stringify(out));""")
    assert res["normal"] is False and res["on"] is True and res["empty"] is True
    # house 3, shelter under its house site, workbench, granary site, campfire, market, town hall site
    assert res["draws"] >= 7
    assert res["texts"] >= 2  # stage title and what the next stage needs
    assert res["gear"] == 0  # no Icons loaded here: nothing to draw, and no error


@node
def test_survival_items_have_icons():
    items = sorted(survival()["items"])
    no_icon = {"water", "lock", "pancakes", "honey_cake"}
    res = run_node(FAKE + js("icons.js", "itemicons.js") + f"""
    const items = {json.dumps(items)};
    console.log(JSON.stringify({{ missing: items.filter(k => !Icons.ITEMS[ItemIcons.MAP[k] || k]),
      html: ItemIcons.list({{ wood: 2, water: 1, stone_axe: 0 }}, k => k === 'wood' ? 'древесина' : k) }}));""")
    assert set(res["missing"]) <= no_icon, res["missing"]
    assert "<img" in res["html"] and "2 древесина" in res["html"] and "1 water" in res["html"] and "stone_axe" not in res["html"]


def test_index_loads_art_before_the_layers_that_use_it():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    pos = {n: html.index(f'<script src="{n}"></script>') for n in
           ("buildart.js", "icons.js", "buildlayer.js", "itemicons.js", "pixelmap.js", "dossier.js", "inspect.js", "hero.js")}
    assert pos["buildart.js"] < pos["buildlayer.js"] < pos["pixelmap.js"]
    assert pos["icons.js"] < pos["itemicons.js"] < min(pos["dossier.js"], pos["inspect.js"], pos["hero.js"])
