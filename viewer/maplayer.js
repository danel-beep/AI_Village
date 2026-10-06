// Map objects layer: trees, field beds, berry bushes, fish shoals, rocks and fires, drawn from the log.
// Every object is one engine "slot" (view.map[loc].slots[resource][i], see aivillage/tiles.py), so what you see
// is what is left: a chopped tree is a stump, a harvested bed is bare soil, a sown bed sprouts, then turns gold.
// Fires grow with view.fire_info[house].water_needed; pour_water / fire_out events splash water on the house.
// pixelmap.js calls init() before painting the background, draw() under the villagers and drawTop() over them.
const MapLayer = (() => {
  let K, spots = {}, claimed = [];
  const shift = (pts, [dx, dy] = [0, 0]) => pts.map(p => [p[0] + dx, p[1] + dy, ...p.slice(2)]);
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
    // On a generated map (viewer/mapgen.js) the landmarks moved by layout.off; the river and patches are new.
    const off = K.layout.off || {};
    spots = { field: { grain: shift(field, off.field) }, forest: { wood: claimed, berries: shift(bushes, off.forest) },
              river: { fish }, mine: { stone: shift(rocks.slice(0, 6), off.mine), ore: shift(rocks.slice(6), off.mine) } };
    if (K.layout.gen && window.GenMap) Object.assign(spots, GenMap.spots(K.layout.gen, T));
  }

  // The background forest hands over the trees nearest the clearing; those become choppable.
  function claimTrees(list, cx, cy, n = 8) {
    const near = list.slice().sort((a, b) => Math.hypot(a[0] + 16 - cx, a[1] + 28 - cy) - Math.hypot(b[0] + 16 - cx, b[1] + 28 - cy))
      .slice(0, n).sort((a, b) => a[0] - b[0]);
    claimed = shift(near, (K.layout.off || {}).forest); if (spots.forest) spots.forest.wood = claimed;
    return new Set(near);
  }

  const amounts = (t, loc, r) => ((t.view.map || {})[loc] || {}).slots?.[r] || [];
  const capOf = (t, loc, r) => ((t.view.map || {})[loc] || {}).cap?.[r] || 1;
  const felled = (t, loc, r) => new Set((t.events || []).filter(e => e.kind === 'slot_empty' && e.location === loc && e.data?.resource === r)
    .map(e => e.data.slot));

  function bed(g, [x, y, w, h], have, cap, sown, sec) {
    const { R, P, C, rnd } = K;
    if (window.Sprites && Sprites.has('soil_ripe')) {   // a row of SpriteCook soil patches at the crop's stage
      const f = have / cap, n = Math.max(1, Math.round(w / 14)),
            name = have >= cap ? 'soil_ripe' : have ? (f < .5 ? 'soil_sprout' : 'soil_growing') : sown ? 'soil_sprout' : 'soil';
      for (let k = 0; k < n; k++) SP(g, name, x + (k + .5) * w / n, y + h + 1, { s: Math.min(1, (w / n + 2) / 16) });
      return;
    }
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

  const SP = (g, n, x, y, o) => window.Sprites && Sprites.draw(g, n, x, y, o);
  function stump(g, x, y) {
    const { blob, R } = K;
    if (SP(g, 'stump', x + 16, y + 31)) return;
    blob(g, x + 16, y + 29, 7, 3, STUMP); R(g, x + 12, y + 24, 8, 5, '#1b1b24'); R(g, x + 13, y + 24, 6, 4, '#8a5a35');
    blob(g, x + 16, y + 24, 4, 2, ['#e8c090', '#d9a870', '#a8743f']);
  }

  function sapling(g, x, y, f) {
    const { R, blob, C } = K, s = 3 + f * 6;
    if (SP(g, 'sapling', x + 16, y + 31, { s: .6 + f * .5 })) return;
    R(g, x + 15, y + 30 - s - 4, 2, s + 4, C.wood);
    blob(g, x + 16, y + 30 - s - 4, s * .8 + 2, s * .6 + 2, [C.leafL, C.leaf, C.leafD]);
  }

  function fallingTree(g, [x, y, pine], e) {
    g.save(); g.globalAlpha = 1 - e; g.translate(x + 16, y + 30); g.rotate(e * Math.PI / 2); g.translate(-x - 16, -y - 30);
    K.tree(g, x, y, pine); g.restore();
  }

  function draw(g, t, e, sec) {
    const { R, P, blob, C } = K;
    if (!t.view.map) return;
    const locs = r => Object.keys(spots).filter(l => (spots[l][r] || []).length);
    // field beds
    for (const loc of locs('grain')) {
      const sown = new Set(Object.keys(t.view.map[loc]?.planted || {}).map(Number));
      amounts(t, loc, 'grain').forEach((v, i) => spots[loc].grain[i] && bed(g, spots[loc].grain[i], v, capOf(t, loc, 'grain'), sown.has(i), sec));
    }
    // berry bushes: red dots = berries left
    for (const loc of locs('berries')) amounts(t, loc, 'berries').forEach((v, i) => { const s = spots[loc].berries[i]; if (!s) return;
      const [x, y] = s; if (SP(g, v ? 'berry_bush' : 'bush', x + 8, y + 16, { alpha: v ? 1 : .75 })) return;
      blob(g, x + 8, y + 10, 7, 5, v ? [C.leafL, C.leaf, C.leafD] : ['#8a9a5a', '#6f7f48', '#566238']);
      for (let k = 0; k < v; k++) P(g, x + 4 + (k * 5) % 10, y + 8 + (k % 2) * 3, '#e4572e'); });
    // fish shoals: little fish circling, one per unit left
    for (const loc of locs('fish')) amounts(t, loc, 'fish').forEach((v, i) => { const s = spots[loc].fish[i]; if (!s) return;
      for (let k = 0; k < v; k++) { const a = sec * .9 + k * 1.3 + i, fx = s[0] + Math.cos(a) * 5, fy = s[1] + Math.sin(a) * 3;
        R(g, fx, fy, 3, 1, '#dfe9f2'); P(g, fx + (Math.cos(a + 1.6) > 0 ? 3 : -1), fy, '#9fb4c6'); } });
    // rocks shrink as they are mined; empty = pebbles
    for (const [r, ore] of [['stone', null], ['ore', '#d4a83a']]) for (const loc of locs(r)) amounts(t, loc, r).forEach((v, i) => {
      const s = spots[loc][r][i]; if (!s) return; const f = v / capOf(t, loc, r);
      if (v && SP(g, ore ? 'gold_rock' : 'boulder', s[0] + 8, s[1] + 16, { s: .55 + .45 * f })) return;
      if (!v) { P(g, s[0] + 5, s[1] + 12, C.stoneD); P(g, s[0] + 9, s[1] + 13, C.stone); P(g, s[0] + 11, s[1] + 11, C.stoneD); return; }
      blob(g, s[0] + 8, s[1] + 14 - 4 * f, 2 + 4 * f, 1.5 + 3.5 * f, [C.stoneL, C.stone, C.stoneD]);
      if (ore) { P(g, s[0] + 7, s[1] + 13 - 4 * f, ore); if (f > .5) P(g, s[0] + 9, s[1] + 11 - 4 * f, ore); } });
    // trees: full, growing sapling, or stump; a tree felled this hour topples
    for (const loc of locs('wood')) {
      const down = felled(t, loc, 'wood'), cap = capOf(t, loc, 'wood');
      const order = amounts(t, loc, 'wood').map((v, i) => [v, i]).filter(([, i]) => spots[loc].wood[i])
        .sort((a, b) => spots[loc].wood[a[1]][1] - spots[loc].wood[b[1]][1]);
      for (const [v, i] of order) {
        const s = spots[loc].wood[i], [x, y, pine] = s;
        if (v === 0) { stump(g, x, y); if (down.has(i) && e < 1) fallingTree(g, s, e); }
        else if (v * 2 < cap) sapling(g, x, y, v / cap * 2);
        else K.tree(g, x, y, pine);
      }
    }
  }

  function drawTop(g, t, e, sec) {
    const { blob, layout } = K, info = t.view.fire_info || {};
    for (const id of t.view.fires || []) {
      const bx = layout.box[id]; if (!bx) continue;
      const [x0, y0, w, h] = bx, need = (info[id] || {}).water_needed || 3, n = 8 + need * 4, tall = 12 + need * 2.5;
      if (window.Sprites && Sprites.has('fire0')) {   // sprite flames: more and bigger the more water is still needed
        const m = 2 + need;
        for (let i = 0; i < m; i++) {
          const fx = x0 + 6 + (w - 12) * (m > 1 ? i / (m - 1) : .5) + (K.rnd(i, 7) - .5) * 6, fy = y0 + h * (.45 + K.rnd(i, 8) * .4);
          Sprites.draw(g, 'fire' + (Math.floor(sec * 9 + i * 1.7) % 4), fx, fy, { s: .8 + need * .12 + K.rnd(i, 9) * .3, flip: i % 2 === 1 });
        }
      } else for (let i = 0; i < n; i++) {
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
      if (!window.Actors) for (let i = 0; i < 10; i++) {   // with viewer/actors.js the villager throws the water
        const p = Math.min(1, e * 1.6 - i * .04); if (p <= 0) continue;
        const dx = ax + (x0 + w / 2 - ax) * p + (i % 3 - 1) * 3, dy = ay - 10 - Math.sin(p * Math.PI) * 18 + (y0 + h / 2 - ay + 10) * p;
        g.globalAlpha = p < 1 ? 1 : Math.max(0, 1.6 - e * 1.6); blob(g, dx, dy, 1.5, 2, ['#cfe9ff', '#7fb8e8', '#3f7fbf'], null); g.globalAlpha = 1;
      }
      for (let i = 0; i < 5; i++) { const p = (e + i / 5) % 1;
        g.globalAlpha = .5 * (1 - p) * Math.min(1, e * 2); blob(g, x0 + w / 2 + Math.sin(i * 2 + p * 4) * 10, y0 + h / 3 - p * 24, 3 + p * 4, 3 + p * 4, ['#ffffff', '#e8eef4', '#cdd6e0'], null); g.globalAlpha = 1; }
    }
  }

  // Map pixels of one resource slot (tree [x, y, pine], bed [x, y, w, h], bush/rock [x, y]) for viewer/actors.js.
  const spotOf = (loc, res, slot) => ((spots[loc] || {})[res] || [])[slot];

  // Boxes around the live plants (trees, bushes, beds) per location, for viewer/seasonlayer.js to recolour.
  function plantBoxes() {
    const out = [];
    for (const loc of Object.keys(spots)) {
      const pts = [];
      for (const [x, y] of spots[loc].wood || []) pts.push([x - 10, y - 30, x + 42, y + 36]);
      for (const [x, y] of spots[loc].berries || []) pts.push([x - 2, y - 2, x + 18, y + 18]);
      for (const [x, y, w, h] of spots[loc].grain || []) pts.push([x - 2, y - 6, x + w + 2, y + h + 2]);
      if (pts.length) out.push([Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1])),
                                Math.max(...pts.map(p => p[2])), Math.max(...pts.map(p => p[3]))]);
    }
    return out;
  }

  return { init, claimTrees, draw, drawTop, spotOf, plantBoxes };
})();
if (typeof window !== 'undefined') window.MapLayer = MapLayer;
