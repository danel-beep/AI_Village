// Private plots layer: each house's yard with what its family built (aivillage/plots.py), drawn from view.plots.
// The yard is a 6x4 grid of 8x11 px cells behind the house (layout.plots[home] = [x, y, w, h] overrides it, e.g. from a
// generated map). Owned cells are mown lawn, the rest wild grass; buildings are packed into owned cells in build order:
// garden beds (soil, sprouts, gold when ripe), a chicken coop with hens, a cow pen, beehives with bees, a fence round
// the owned land. Whatever lies ready (eggs, milk, honey, grain) is shown, so a thief's target is visible.
// House level 2 adds a roof dormer, level 3 a second chimney with a golden cap. A new building raises a dust puff.
// pixelmap.js calls init() once and draw() under the villagers.
const PlotLayer = (() => {
  let K, yards = {};
  const COLS = 6, ROWS = 4, CELL = 8;
  const SIZE = { garden_bed: [1, 1], chicken_coop: [2, 1], cow_pen: [2, 2], beehive: [1, 1], fence: [0, 0] };

  function init(kit) {
    K = kit;
    const { layout, T } = K;
    yards = {};
    for (const h of layout.houses) {
      const id = 'home_' + h.name;
      yards[id] = { rect: (layout.plots || {})[id] || [h.x, h.y - 3 * T + 2, 3 * T, 3 * T - 4], house: h };
    }
  }

  // Owned cells fill from the house side (bottom row) upwards, left to right.
  function cellXY(rect, i) {
    const [x, y, w, h] = rect, cw = w / COLS, ch = h / ROWS;
    return [x + (i % COLS) * cw, y + h - ch * (1 + Math.floor(i / COLS)), cw, ch];
  }

  // Greedy packing in build order; deterministic, so a building never jumps between ticks.
  function pack(buildings, cells) {
    const n = Math.min(cells, COLS * ROWS), used = new Set(), out = [];
    const free = (c, r) => c < COLS && r < ROWS && r * COLS + c < n && !used.has(r * COLS + c);
    for (const b of buildings) {
      const [bw, bh] = SIZE[b.kind] || [1, 1];
      if (!bw) continue;
      let spot = null;
      for (let i = 0; i < n && !spot; i++) {
        const c = i % COLS, r = Math.floor(i / COLS);
        let ok = true;
        for (let dr = 0; dr < bh && ok; dr++) for (let dc = 0; dc < bw && ok; dc++) ok = free(c + dc, r + dr);
        if (ok) spot = [c, r];
      }
      if (!spot) continue;
      for (let dr = 0; dr < bh; dr++) for (let dc = 0; dc < bw; dc++) used.add((spot[1] + dr) * COLS + spot[0] + dc);
      out.push({ b, c: spot[0], r: spot[1], w: bw, h: bh });
    }
    return out;
  }

  function yardGround(g, rect, cells, fenced) {
    const { R, P, C } = K;
    const [x, y, w, h] = rect;
    const n = Math.min(cells, COLS * ROWS);
    for (let i = 0; i < n; i++) {
      const [cx, cy, cw, ch] = cellXY(rect, i);
      R(g, cx, cy, cw, ch, (i + Math.floor(i / COLS)) % 2 ? C.grassL : '#74b852');
    }
    // Corner stakes mark the land the family owns; a fence encloses it.
    const rowsOwned = Math.ceil(n / COLS);
    const x1 = x + w - 1, y0 = y + h - rowsOwned * (h / ROWS);
    if (fenced) {
      for (let xx = x; xx <= x1; xx++) { P(g, xx, y0 + 1, C.woodD); P(g, xx, y0 + 3, C.woodD); if (xx % 4 === 0) R(g, xx, y0, 1, 5, C.wood); }
      for (let yy = y0; yy < y + h; yy++) { P(g, x, yy, C.wood); P(g, x1, yy, C.wood); if (yy % 3 === 0) { P(g, x + 1, yy, C.woodD); P(g, x1 - 1, yy, C.woodD); } }
    } else {
      for (const [sx, sy] of [[x, y0], [x1 - 1, y0]]) { R(g, sx, sy, 2, 4, C.wood); P(g, sx, sy, C.woodL); }
    }
  }

  // ---------- buildings (each drawn in its cell box [x, y, w, h]; a cell is 8x11 px) ----------
  function bed(g, [x, y, w, h], b, day) {
    const { R, P, C } = K;
    R(g, x + 1, y + 1, w - 2, h - 2, C.soilD); R(g, x + 1, y + 1, w - 2, h - 3, C.soil);
    for (let yy = y + 3; yy < y + h - 2; yy += 3) R(g, x + 1, yy, w - 2, 1, C.soilD);
    const ripe = (b.items || {}).grain, left = b.crop ? b.ripe_day - day : 0;
    for (let i = 0; i < 3; i++) {
      const sx = x + 2 + i * 2, base = y + h - 3;
      if (ripe) { R(g, sx, base - 6, 1, 6, C.wheatD); R(g, sx, base - 8, 1, 2, C.wheat); P(g, sx + (i % 2 ? -1 : 1), base - 7, C.wheat); }
      else if (b.crop) { const tall = left <= 1 ? 5 : 2; R(g, sx, base - tall, 1, tall, C.sprout); P(g, sx + 1, base - tall + 1, C.leafL); }
    }
  }

  function coop(g, [x, y, w, h], b, sec) {
    const { R, P, C } = K;
    R(g, x + 1, y + 3, 10, 8, C.k); R(g, x + 2, y + 4, 8, 6, C.woodL);
    for (let yy = y + 5; yy < y + 10; yy += 2) R(g, x + 2, yy, 8, 1, C.wood);
    R(g, x, y + 1, 12, 3, C.k); R(g, x + 1, y + 2, 10, 1, '#b8483a'); R(g, x + 1, y + 1, 10, 1, '#d46a4f');
    R(g, x + 5, y + 7, 3, 3, C.k); R(g, x + 4, y + 9, 5, 1, C.woodD);   // door + ramp
    for (let k = 0; k < 2; k++) {   // hens pecking in front
      const hx = x + 12 + k * 2, peck = Math.sin(sec * 4 + k * 2) > .6 ? 1 : 0, hy = y + 4 + k * 4;
      R(g, hx, hy + 1, 3, 2, '#f4f0e6'); P(g, hx + 2, hy + peck, '#f4f0e6'); P(g, hx + 2, hy - 1 + peck, '#d8402c');
      P(g, hx + 1, hy + 3, '#e0a030');
    }
    const eggs = (b.items || {}).egg || 0;
    for (let i = 0; i < Math.min(eggs, 5); i++) { R(g, x + 1 + i * 2, y + h - 1, 2, 1, '#fff6e0'); }
  }

  function cowPen(g, [x, y, w, h], b, sec) {
    const { R, P, C } = K;
    R(g, x + 1, y + 2, w - 2, h - 3, '#8ab84e');
    for (const yy of [y + 2, y + h - 2]) { R(g, x, yy, w, 1, C.wood); R(g, x, yy - 1, w, 1, C.woodL); }
    for (let xx = x; xx < x + w; xx += 5) R(g, xx, y + 1, 1, h - 2, C.woodD);
    R(g, x + w - 1, y + 1, 1, h - 2, C.woodD);
    const sway = Math.sin(sec * 1.3) > 0 ? 1 : 0, cx = x + 2, cy = y + 8;
    R(g, cx, cy, 9, 5, C.k); R(g, cx + 1, cy + 1, 7, 3, '#f4f0e6'); R(g, cx + 2, cy + 1, 2, 2, C.k); R(g, cx + 6, cy + 2, 2, 1, C.k);
    R(g, cx + 9, cy - 1 + sway, 4, 4, C.k); R(g, cx + 10, cy + sway, 3, 3, '#f4f0e6'); P(g, cx + 12, cy + 2 + sway, '#f0a0b0');
    P(g, cx + 10, cy - 2 + sway, '#c8b48a'); P(g, cx + 12, cy - 2 + sway, '#c8b48a');
    for (const lx of [cx + 1, cx + 3, cx + 5, cx + 7]) R(g, lx, cy + 5, 1, 3, '#5a4632');
    P(g, cx + 5, cy + 4, '#f0a0b0');
    const milk = (b.items || {}).milk || 0;   // milk cans by the fence
    for (let i = 0; i < Math.min(3, Math.ceil(milk / 3)); i++) { R(g, x + 2 + i * 4, y + h - 7, 3, 4, '#e8e8f0'); R(g, x + 2 + i * 4, y + h - 7, 3, 1, C.stoneD); }
  }

  function hive(g, [x, y, w, h], b, sec) {
    const { R, P, C } = K;
    R(g, x + 3, y + h - 3, 2, 3, C.woodD);   // stand
    R(g, x + 1, y + 2, 6, 7, C.k); R(g, x + 2, y + 3, 4, 2, '#e0b040'); R(g, x + 2, y + 5, 4, 1, '#a87820'); R(g, x + 2, y + 6, 4, 2, '#e0b040');
    R(g, x, y + 1, 8, 2, C.woodD); P(g, x + 4, y + 7, C.k);
    if (((b.items || {}).honey || 0) > 0) { R(g, x + 6, y + h - 3, 2, 3, '#ffb020'); P(g, x + 6, y + h - 3, '#ffe080'); }
    for (let i = 0; i < 3; i++) {
      const a = sec * 3 + i * 2.1;
      P(g, Math.round(x + 4 + Math.cos(a) * 5), Math.round(y + 3 + Math.sin(a * 1.7) * 3), i % 2 ? '#ffe060' : '#1b1b24');
    }
  }

  // House level: a dormer on level 2+, a second (gilded) chimney on level 3.
  function houseLevel(g, h, level) {
    const { R, P, C } = K;
    if (level < 2) return;
    const x = h.x, y = h.y;
    R(g, x + 19, y + 9, 11, 10, C.k); R(g, x + 20, y + 10, 9, 9, C.plaster);
    R(g, x + 22, y + 12, 5, 5, C.k); R(g, x + 23, y + 13, 3, 3, C.glass); R(g, x + 18, y + 8, 13, 2, C.woodD);
    if (level < 3) return;
    R(g, x + 8, y + 3, 6, 10, C.k); R(g, x + 9, y + 4, 4, 9, C.stoneD); R(g, x + 9, y + 4, 4, 2, C.stone);
    R(g, x + 12, y + 1, 4, 2, '#e0c040');   // a golden cap on the new chimney
  }

  function puff(g, x, y, e) {
    const { blob } = K;
    if (e >= 1) return;
    g.globalAlpha = .6 * (1 - e);
    for (let i = 0; i < 4; i++) blob(g, x + Math.cos(i * 1.6) * (3 + e * 8), y - e * 6 + Math.sin(i * 1.6) * 2, 2 + e * 3, 2 + e * 2,
      ['#e8dcc0', '#d0c4a8', '#b8ac90'], null);
    g.globalAlpha = 1;
  }

  function draw(g, t, e, sec) {
    const plots = (t.view || {}).plots;
    if (!plots || !K) return;
    const built = new Set((t.events || []).filter(ev => ev.kind === 'build').map(ev => ev.data && ev.data.building));
    for (const [home, p] of Object.entries(plots)) {
      const yd = yards[home];
      if (!yd) continue;
      const fenced = p.buildings.some(b => b.kind === 'fence');
      yardGround(g, yd.rect, p.cells, fenced);
      for (const { b, c, r, w, h } of pack(p.buildings, p.cells)) {
        const [x0, y0] = cellXY(yd.rect, r * COLS + c), cw = yd.rect[2] / COLS, ch = yd.rect[3] / ROWS;
        const box = [x0, y0 - (h - 1) * ch, w * cw, h * ch];
        if (b.kind === 'garden_bed') bed(g, box, b, t.view.day);
        else if (b.kind === 'chicken_coop') coop(g, box, b, sec);
        else if (b.kind === 'cow_pen') cowPen(g, box, b, sec);
        else if (b.kind === 'beehive') hive(g, box, b, sec);
        if (built.has(b.id)) puff(g, box[0] + box[2] / 2, box[1] + box[3] / 2, e);
      }
      houseLevel(g, yd.house, p.house || 1);
    }
  }

  return { init, draw, pack };
})();
window.PlotLayer = PlotLayer;
