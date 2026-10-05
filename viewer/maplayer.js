// Map objects layer: trees, field beds, berry bushes, fish shoals, rocks and fires, drawn from the log.
// Every object is one engine "slot" (view.map[loc].slots[resource][i], see aivillage/tiles.py), so what you see
// is what is left: a chopped tree is a stump, a harvested bed is bare soil, a sown bed sprouts, then turns gold.
// Fires grow with view.fire_info[house].water_needed; pour_water / fire_out events splash water on the house.
// pixelmap.js calls init() before painting the background, draw() under the villagers and drawTop() over them.
const MapLayer = (() => {
  let K, spots = {};
  const STUMP = ['#a8743f', '#8a5a35', '#6b4226'];

  function init(kit) {
    K = kit;
    const { T } = K;
    const field = [], bushes = [], fish = [], rocks = [];
    for (let k = 0; k < 4; k++) field.push([5 * T + 2, 2 * T + 3 + k * 20, 40, 14]);
    for (let k = 0; k < 4; k++) field.push([9 * T + 2, 2 * T + 3 + k * 20, 26, 14]);
    for (let k = 0; k < 5; k++) bushes.push([21 * T + 2 + k * 26 + (k > 1 ? 16 : 0), 7 * T - 2]);
    for (let k = 0; k < 6; k++) fish.push([10 + (k % 2) * 14, 2 * T + k * 30 + (k % 2) * 12]);
    for (const y of [12 * T + 2, 13 * T + 2, 14 * T]) for (const x of [25 * T - 2, 26 * T + 10, 28 * T + 4, 29 * T]) rocks.push([x, y]);
    spots = { field: { grain: field }, forest: { wood: spots.trees || [], berries: bushes }, river: { fish },
              mine: { stone: rocks.slice(0, 6), ore: rocks.slice(6) } };
  }

  // The background forest hands over the trees nearest the clearing; those become choppable.
  function claimTrees(list, cx, cy, n = 8) {
    const near = list.slice().sort((a, b) => Math.hypot(a[0] + 16 - cx, a[1] + 28 - cy) - Math.hypot(b[0] + 16 - cx, b[1] + 28 - cy))
      .slice(0, n).sort((a, b) => a[0] - b[0]);
    spots.trees = near; if (spots.forest) spots.forest.wood = near;
    return new Set(near);
  }

  const amounts = (t, loc, r) => ((t.view.map || {})[loc] || {}).slots?.[r] || [];
  const capOf = (t, loc, r) => ((t.view.map || {})[loc] || {}).cap?.[r] || 1;
  const felled = (t, loc, r) => new Set((t.events || []).filter(e => e.kind === 'slot_empty' && e.location === loc && e.data?.resource === r)
    .map(e => e.data.slot));

  function bed(g, [x, y, w, h], have, cap, sown, sec) {
    const { R, P, C, rnd } = K;
    R(g, x - 1, y - 1, w + 2, h + 2, C.soilD); R(g, x, y, w, h, C.soil);
    for (let yy = y + 3; yy < y + h; yy += 4) R(g, x + 1, yy, w - 2, 1, C.soilD);
    const ripe = have >= cap, f = have / cap;
    for (let xx = x + 3; xx < x + w - 2; xx += 4) for (let yy = y + 4; yy < y + h; yy += 5) {
      if (sown) { P(g, xx, yy - 1, C.sprout); if (rnd(xx, yy) < .5) P(g, xx + 1, yy - 2, '#9ad060'); continue; }
      if (!have || rnd(xx, yy, 3) > f + .15) continue;
      const sway = Math.sin(sec * 2 + xx * .3) > .6 ? 1 : 0;
      if (ripe) { P(g, xx, yy, C.wheatD); P(g, xx, yy - 1, C.wheat); P(g, xx + sway, yy - 2, C.wheat); P(g, xx + sway, yy - 3, C.wheat); }
      else { const hgt = 1 + Math.round(f * 3); for (let i = 0; i < hgt; i++) P(g, xx + (i > 1 ? sway : 0), yy - i, i === hgt - 1 ? '#9ad060' : C.sprout); }
    }
  }

  function stump(g, x, y) {
    const { blob, R } = K;
    blob(g, x + 16, y + 29, 7, 3, STUMP); R(g, x + 12, y + 24, 8, 5, '#1b1b24'); R(g, x + 13, y + 24, 6, 4, '#8a5a35');
    blob(g, x + 16, y + 24, 4, 2, ['#e8c090', '#d9a870', '#a8743f']);
  }

  function sapling(g, x, y, f) {
    const { R, blob, C } = K, s = 3 + f * 6;
    R(g, x + 15, y + 30 - s - 4, 2, s + 4, C.wood);
    blob(g, x + 16, y + 30 - s - 4, s * .8 + 2, s * .6 + 2, [C.leafL, C.leaf, C.leafD]);
  }

  function fallingTree(g, [x, y, pine], e) {
    g.save(); g.globalAlpha = 1 - e; g.translate(x + 16, y + 30); g.rotate(e * Math.PI / 2); g.translate(-x - 16, -y - 30);
    K.tree(g, x, y, pine); g.restore();
  }

  function draw(g, t, e, sec) {
    const { R, P, blob, C, bush, rock } = K;
    if (!t.view.map) return;
    // field beds
    const sown = new Set(Object.keys(t.view.map.field?.planted || {}).map(Number));
    amounts(t, 'field', 'grain').forEach((v, i) => spots.field.grain[i] && bed(g, spots.field.grain[i], v, capOf(t, 'field', 'grain'), sown.has(i), sec));
    // berry bushes: red dots = berries left
    amounts(t, 'forest', 'berries').forEach((v, i) => { const s = spots.forest.berries[i]; if (!s) return;
      const [x, y] = s; blob(g, x + 8, y + 10, 7, 5, v ? [C.leafL, C.leaf, C.leafD] : ['#8a9a5a', '#6f7f48', '#566238']);
      for (let k = 0; k < v; k++) P(g, x + 4 + (k * 5) % 10, y + 8 + (k % 2) * 3, '#e4572e'); });
    // fish shoals: little fish circling, one per unit left
    amounts(t, 'river', 'fish').forEach((v, i) => { const s = spots.river.fish[i]; if (!s) return;
      for (let k = 0; k < v; k++) { const a = sec * .9 + k * 1.3 + i, fx = s[0] + Math.cos(a) * 5, fy = s[1] + Math.sin(a) * 3;
        R(g, fx, fy, 3, 1, '#dfe9f2'); P(g, fx + (Math.cos(a + 1.6) > 0 ? 3 : -1), fy, '#9fb4c6'); } });
    // rocks shrink as they are mined; empty = pebbles
    for (const [r, ore] of [['stone', null], ['ore', '#d4a83a']]) amounts(t, 'mine', r).forEach((v, i) => {
      const s = spots.mine[r][i]; if (!s) return; const f = v / capOf(t, 'mine', r);
      if (!v) { P(g, s[0] + 5, s[1] + 12, C.stoneD); P(g, s[0] + 9, s[1] + 13, C.stone); P(g, s[0] + 11, s[1] + 11, C.stoneD); return; }
      blob(g, s[0] + 8, s[1] + 14 - 4 * f, 2 + 4 * f, 1.5 + 3.5 * f, [C.stoneL, C.stone, C.stoneD]);
      if (ore) { P(g, s[0] + 7, s[1] + 13 - 4 * f, ore); if (f > .5) P(g, s[0] + 9, s[1] + 11 - 4 * f, ore); } });
    // trees: full, growing sapling, or stump; a tree felled this hour topples
    const down = felled(t, 'forest', 'wood'), cap = capOf(t, 'forest', 'wood');
    const order = amounts(t, 'forest', 'wood').map((v, i) => [v, i]).filter(([, i]) => spots.forest.wood[i])
      .sort((a, b) => spots.forest.wood[a[1]][1] - spots.forest.wood[b[1]][1]);
    for (const [v, i] of order) {
      const s = spots.forest.wood[i], [x, y, pine] = s;
      if (v === 0) { stump(g, x, y); if (down.has(i) && e < 1) fallingTree(g, s, e); }
      else if (v * 2 < cap) sapling(g, x, y, v / cap * 2);
      else K.tree(g, x, y, pine);
    }
  }

  function drawTop(g, t, e, sec) {
    const { blob, layout } = K, info = t.view.fire_info || {};
    for (const id of t.view.fires || []) {
      const bx = layout.box[id]; if (!bx) continue;
      const [x0, y0, w, h] = bx, need = (info[id] || {}).water_needed || 3, n = 8 + need * 4, tall = 12 + need * 2.5;
      for (let i = 0; i < n; i++) {
        const p = (sec * 1.6 + K.rnd(i, 3)) % 1, fx = x0 + 4 + K.rnd(i, 1) * (w - 8), fy = y0 + h * (.25 + K.rnd(i, 2) * .7) - p * tall;
        const r = (1 - p) * (3 + need * .6) + 1.5;
        blob(g, fx, fy, r, r * 1.4, ['#ffe066', '#ff9f1c', '#e4572e'], null);
      }
      for (let i = 0; i < 2 + need; i++) { const p = (sec * .6 + i / (2 + need)) % 1;
        g.globalAlpha = .45 * (1 - p); blob(g, x0 + w / 2 + Math.sin(p * 8 + i) * 6, y0 - p * (20 + need * 3), 3 + p * 5, 3 + p * 5, ['#555', '#444', '#333'], null); g.globalAlpha = 1; }
    }
    // water poured this hour: an arc of drops onto the house, then steam
    for (const ev of (t.events || []).filter(ev => ev.kind === 'pour_water' || ev.kind === 'fire_out')) {
      const bx = layout.box[ev.data?.house || ev.location]; if (!bx) continue;
      const [x0, y0, w, h] = bx, [ax, ay] = layout.anchors[ev.data?.house || ev.location];
      for (let i = 0; i < 10; i++) {
        const p = Math.min(1, e * 1.6 - i * .04); if (p <= 0) continue;
        const dx = ax + (x0 + w / 2 - ax) * p + (i % 3 - 1) * 3, dy = ay - 10 - Math.sin(p * Math.PI) * 18 + (y0 + h / 2 - ay + 10) * p;
        g.globalAlpha = p < 1 ? 1 : Math.max(0, 1.6 - e * 1.6); blob(g, dx, dy, 1.5, 2, ['#cfe9ff', '#7fb8e8', '#3f7fbf'], null); g.globalAlpha = 1;
      }
      for (let i = 0; i < 5; i++) { const p = (e + i / 5) % 1;
        g.globalAlpha = .5 * (1 - p) * Math.min(1, e * 2); blob(g, x0 + w / 2 + Math.sin(i * 2 + p * 4) * 10, y0 + h / 3 - p * 24, 3 + p * 4, 3 + p * 4, ['#ffffff', '#e8eef4', '#cdd6e0'], null); g.globalAlpha = 1; }
    }
  }

  return { init, claimTrees, draw, drawTop };
})();
if (typeof window !== 'undefined') window.MapLayer = MapLayer;
