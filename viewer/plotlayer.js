// Private plots layer: each house's yard with what its family built (aivillage/plots.py), drawn from view.plots.
// A yard is a grid of cells (8 px wide). On the hand-made map it is 6x4 cells of 8x11 px behind the house: owned
// cells (view.plots[home].cells) are mown lawn, filled from the house side; a fence building encloses them. On a
// generated map (viewer/mapgen.js) the yard is the fenced plot around the house (8x16 px cells, nearest the house
// first); land bought beyond it shows as staked lawn rows behind the plot, and a fence building adds a hedge.
// Buildings are packed into the yard in build order (deterministic, nothing jumps between ticks): garden beds (soil,
// sprouts, gold when ripe), a chicken coop with hens, a cow pen, beehives with bees. What lies ready (eggs, milk,
// honey, grain) is shown, so a thief's target is visible. House level 2 adds a roof dormer, level 3 a second chimney
// with a golden cap. A new building raises a dust puff. pixelmap.js calls init() once and draw() under the villagers.
const PlotLayer = (() => {
  let K, yards = {};
  const SIZE = { garden_bed: [1, 1], chicken_coop: [2, 1], cow_pen: [2, 2], beehive: [1, 1], fence: [0, 0] };
  const key = (c, r) => c + ',' + r;

  function init(kit) {
    K = kit;
    const { layout, T } = K;
    yards = {};
    for (const h of layout.houses) {
      const id = 'home_' + h.name, given = (layout.plots || {})[id] || h.plot;
      if (given) {
        const [x, y, w, hh] = given, cols = Math.round(w / 8), rows = Math.round(hh / 16), order = [];
        const dist = (c, r) => { const cx = x + c * 8 + 4, cy = y + r * 16 + 8;
          return Math.max(h.x - cx, cx - (h.x + 3 * T), 0) + Math.max(h.y - cy, cy - (h.y + 3 * T), 0); };
        for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
          const cx = x + c * 8 + 4, cy = y + r * 16 + 8;
          if (cx > h.x && cx < h.x + 3 * T && cy > h.y && cy < h.y + 3 * T) continue;   // the house itself
          order.push([c, r]);
        }
        order.sort((p, q) => dist(...p) - dist(...q) || q[1] - p[1] || p[0] - q[0]);
        yards[id] = { ox: x, oy: y, cw: 8, ch: 16, cols, order, gen: true, rect: given, house: h };
      } else {
        const order = [];
        for (let r = 3; r >= 0; r--) for (let c = 0; c < 6; c++) order.push([c, r]);
        yards[id] = { ox: h.x, oy: h.y - 3 * T + 2, cw: 8, ch: 11, cols: 6, order, gen: false, house: h };
      }
    }
    // lots for sale (aivillage/land.py): no house, cells filled from the gate row up
    for (const [id, [x, y, w, hh]] of Object.entries(layout.lots || {})) {
      const cols = Math.round(w / 8), rows = Math.round(hh / 16), order = [];
      for (let r = rows - 1; r >= 0; r--) for (let c = 0; c < cols; c++) order.push([c, r]);
      yards[id] = { ox: x, oy: y, cw: 8, ch: 16, cols, order, gen: true, rect: [x, y, w, hh], house: null };
    }
  }

  // A signpost on a lot: "for sale" while nobody owns it, else the owner's initial.
  function lotSign(g, yd, p) {
    const { R, P, C } = K, [x, y] = yd.rect, sx = x + 3, sy = y - 9;
    R(g, sx + 4, sy + 6, 2, 9, C.woodD); R(g, sx, sy, 11, 7, C.k); R(g, sx + 1, sy + 1, 9, 5, p.for_sale ? '#e8d8a0' : C.woodL);
    if (p.for_sale) { R(g, sx + 3, sy + 2, 5, 1, '#c0392b'); R(g, sx + 3, sy + 4, 3, 1, '#c0392b'); }
    else { R(g, sx + 4, sy + 2, 3, 3, '#3a6ea5'); P(g, sx + 5, sy + 3, '#e8d8a0'); }
  }

  // Cells the family may use now: on a generated map the whole fenced yard plus rows behind it for bought land.
  function owned(yd, cells) {
    if (!yd.gen) return yd.order.slice(0, Math.min(cells, yd.order.length));
    const out = yd.order.slice();
    for (let r = -1; out.length < cells && r > -4; r--) for (let c = 0; c < yd.cols && out.length < cells; c++) out.push([c, r]);
    return out;
  }

  function pack(buildings, cells, yd) {
    const own = yd ? owned(yd, cells) : [];
    const free = new Set(own.map(([c, r]) => key(c, r))), out = [];
    for (const b of buildings) {
      const [bw, bh] = SIZE[b.kind] || [1, 1];
      if (!bw) continue;
      const spot = own.find(([c, r]) => { for (let dr = 0; dr < bh; dr++) for (let dc = 0; dc < bw; dc++)
        if (!free.has(key(c + dc, r + dr))) return false; return true; });
      if (!spot) continue;
      for (let dr = 0; dr < bh; dr++) for (let dc = 0; dc < bw; dc++) free.delete(key(spot[0] + dc, spot[1] + dr));
      out.push({ b, c: spot[0], r: spot[1], w: bw, h: bh });
    }
    return out;
  }

  const cellBox = (yd, c, r, w = 1, h = 1) => [yd.ox + c * yd.cw, yd.oy + r * yd.ch, w * yd.cw, h * yd.ch];

  let lawnPat = {};   // mown lawn: the light SpriteCook grass texture as a fill pattern (one per canvas)
  function yardGround(g, yd, cells, fenced) {
    const { R, P, C } = K;
    const own = owned(yd, cells), lawn = yd.gen ? own.filter(([, r]) => r < 0) : own;
    const pat = window.Sprites && Sprites.has('tex_grass') && (lawnPat.g === g ? lawnPat.p : (lawnPat = { g, p: Sprites.pattern(g, 'tex_grass') }).p);
    for (const [c, r] of lawn) R(g, ...cellBox(yd, c, r), pat || ((c + r) % 2 ? C.grassL : '#74b852'));
    if (lawn.length) {   // stakes at the corners of the lawn (land bought beyond a generated plot, or owned cells)
      const xs = lawn.map(([c]) => c), ys = lawn.map(([, r]) => r);
      const [x0, y0] = cellBox(yd, Math.min(...xs), Math.min(...ys)), [x1, y1, cw, ch] = cellBox(yd, Math.max(...xs), Math.max(...ys));
      if (fenced && !yd.gen) {
        for (let xx = x0; xx < x1 + cw; xx++) { P(g, xx, y0 + 1, C.woodD); P(g, xx, y0 + 3, C.woodD); if (xx % 4 === 0) R(g, xx, y0, 1, 5, C.wood); }
        for (let yy = y0; yy < y1 + ch; yy++) for (const xx of [x0, x1 + cw - 1]) { P(g, xx, yy, C.wood); if (yy % 3 === 0) P(g, xx + (xx === x0 ? 1 : -1), yy, C.woodD); }
      } else for (const [sx, sy] of [[x0, y0], [x1 + cw - 2, y0]]) { R(g, sx, sy, 2, 4, C.wood); P(g, sx, sy, C.woodL); }
    }
    if (fenced && yd.gen) {   // a hedge along the generated plot's fence
      const [x, y, w, h] = yd.rect;
      for (let xx = x + 2; xx < x + w - 2; xx += 3) { P(g, xx, y + 1, C.leafD); P(g, xx + 1, y + 2, C.leaf); }
      for (let yy = y + 2; yy < y + h - 2; yy += 3) for (const xx of [x + 1, x + w - 3]) { P(g, xx, yy, C.leafD); P(g, xx + 1, yy + 1, C.leaf); }
    }
  }

  const SP = (g, n, x, y, o) => window.Sprites && Sprites.draw(g, n, x, y, o);
  // ---------- buildings (each drawn in its cell box [x, y, w, h]; a cell is 8x11 or 8x16 px) ----------
  function bed(g, [x, y, w, h], b, day) {
    const { R, P, C } = K;
    const ripe = (b.items || {}).grain, left = b.crop ? b.ripe_day - day : 0;
    if (SP(g, ripe ? 'soil_ripe' : b.crop ? (left <= 1 ? 'soil_growing' : 'soil_sprout') : 'soil', x + w / 2, y + h - 1, { s: w / 16 })) return;
    R(g, x + 1, y + 1, w - 2, h - 2, C.soilD); R(g, x + 1, y + 1, w - 2, h - 3, C.soil);
    for (let yy = y + 3; yy < y + h - 2; yy += 3) R(g, x + 1, yy, w - 2, 1, C.soilD);
    for (let i = 0; i < 3; i++) {
      const sx = x + 2 + i * 2, base = y + h - 3;
      if (ripe) { R(g, sx, base - 6, 1, 6, C.wheatD); R(g, sx, base - 8, 1, 2, C.wheat); P(g, sx + (i % 2 ? -1 : 1), base - 7, C.wheat); }
      else if (b.crop) { const tall = left <= 1 ? 5 : 2; R(g, sx, base - tall, 1, tall, C.sprout); P(g, sx + 1, base - tall + 1, C.leafL); }
    }
  }

  function coop(g, [x, y, w, h], b, sec) {
    const { R, P, C } = K;
    if (!SP(g, 'coop', x + 6, y + 12, { s: .6 })) {   // code coop; hens and eggs below either way
    R(g, x + 1, y + 3, 10, 8, C.k); R(g, x + 2, y + 4, 8, 6, C.woodL);
    for (let yy = y + 5; yy < y + 10; yy += 2) R(g, x + 2, yy, 8, 1, C.wood);
    R(g, x, y + 1, 12, 3, C.k); R(g, x + 1, y + 2, 10, 1, '#b8483a'); R(g, x + 1, y + 1, 10, 1, '#d46a4f');
    R(g, x + 5, y + 7, 3, 3, C.k); R(g, x + 4, y + 9, 5, 1, C.woodD);   // door + ramp
    }
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
    if (!SP(g, 'cow', cx + 7, cy + 8, { s: .8, flip: Math.sin(sec * .21) > .7 })) {
    R(g, cx, cy, 9, 5, C.k); R(g, cx + 1, cy + 1, 7, 3, '#f4f0e6'); R(g, cx + 2, cy + 1, 2, 2, C.k); R(g, cx + 6, cy + 2, 2, 1, C.k);
    R(g, cx + 9, cy - 1 + sway, 4, 4, C.k); R(g, cx + 10, cy + sway, 3, 3, '#f4f0e6'); P(g, cx + 12, cy + 2 + sway, '#f0a0b0');
    P(g, cx + 10, cy - 2 + sway, '#c8b48a'); P(g, cx + 12, cy - 2 + sway, '#c8b48a');
    for (const lx of [cx + 1, cx + 3, cx + 5, cx + 7]) R(g, lx, cy + 5, 1, 3, '#5a4632');
    P(g, cx + 5, cy + 4, '#f0a0b0');
    }
    const milk = (b.items || {}).milk || 0;   // milk cans by the fence
    for (let i = 0; i < Math.min(3, Math.ceil(milk / 3)); i++) { R(g, x + 2 + i * 4, y + h - 7, 3, 4, '#e8e8f0'); R(g, x + 2 + i * 4, y + h - 7, 3, 1, C.stoneD); }
  }

  function hive(g, [x, y, w, h], b, sec) {
    const { R, P, C } = K;
    if (!SP(g, 'hive', x + 4, y + h)) {
    R(g, x + 3, y + h - 3, 2, 3, C.woodD);   // stand
    R(g, x + 1, y + 2, 6, 7, C.k); R(g, x + 2, y + 3, 4, 2, '#e0b040'); R(g, x + 2, y + 5, 4, 1, '#a87820'); R(g, x + 2, y + 6, 4, 2, '#e0b040');
    R(g, x, y + 1, 8, 2, C.woodD); P(g, x + 4, y + 7, C.k);
    }
    if (((b.items || {}).honey || 0) > 0) { R(g, x + 6, y + h - 3, 2, 3, '#ffb020'); P(g, x + 6, y + h - 3, '#ffe080'); }
    for (let i = 0; i < 3; i++) {
      const a = sec * 3 + i * 2.1;
      P(g, Math.round(x + 4 + Math.cos(a) * 5), Math.round(y + 3 + Math.sin(a * 1.7) * 3), i % 2 ? '#ffe060' : '#1b1b24');
    }
  }

  // House level: a dormer on level 2+, a second (gilded) chimney on level 3.
  function houseLevel(g, h, level) {
    const { R, P, C } = K;
    // sprite houses are redrawn at every level: they are taller than their lot, and the yard rows must not cover the roof
    if (K.houseSprite && K.houseSprite(g, h, Math.min(3, level))) return;
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
      yardGround(g, yd, p.cells, p.buildings.some(b => b.kind === 'fence'));
      for (const { b, c, r, w, h } of pack(p.buildings, p.cells, yd)) {
        const box = cellBox(yd, c, r, w, h);
        if (b.kind === 'garden_bed') bed(g, box, b, t.view.day);
        else if (b.kind === 'chicken_coop') coop(g, box, b, sec);
        else if (b.kind === 'cow_pen') cowPen(g, box, b, sec);
        else if (b.kind === 'beehive') hive(g, box, b, sec);
        if (built.has(b.id)) puff(g, box[0] + box[2] / 2, box[1] + box[3] / 2, e);
      }
      if (yd.house) houseLevel(g, yd.house, p.house || 1);
      else lotSign(g, yd, p);
    }
  }

  return { init, draw, pack };
})();
window.PlotLayer = PlotLayer;
