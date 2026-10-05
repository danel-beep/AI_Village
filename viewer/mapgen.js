// Procedural maps (aivillage/mapgen.py): the log header carries config.map.layout, a tile plan of the village.
// GenMap.layout() turns it into pixelmap's layout (anchors, boxes, routes, houses, ground kinds) plus `off`:
// how far each hand-drawn landmark (field, square, market, smithy, mine, forest) moved from its place on the
// hand-made map, so pixelmap can paint the same art shifted. GenMap.paint() draws what only generated maps
// have: a winding river with its dock, fenced plots, groves, ponds, quarries, hamlet greens, road signposts.
// GenMap.spots() gives viewer/maplayer.js the pixel spots of resource objects outside the old landmarks.
const GenMap = (() => {
  const LABEL = { grove: -34, pond: -30, quarry: -34, hamlet: -30, waypoint: -26 };

  function layout(lay, names, T, ROOFS) {
    const px = (x, y) => [x * T + 8, y * T + 8];
    const kind = {}, set = (x, y, k) => { kind[x + ',' + y] = k; };
    const fill = ([x0, y0, w, h], k) => { for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) set(x, y, k); };
    const anchors = {}, box = {}, routes = {}, off = {}, labels = [], houses = [];
    lay.river.x.forEach((x0, y) => { for (let x = x0; x < x0 + 3; x++) set(x, y, 'water'); });
    for (const [id, pl] of Object.entries(lay.places)) {
      anchors[id] = px(...pl.anchor);
      if (pl.box) box[id] = pl.box.map(v => v * T);
      const d = lay.defaults[pl.kind];
      if (d && pl.box) off[id] = [(pl.box[0] - d[0]) * T, (pl.box[1] - d[1]) * T];
      if (pl.kind in LABEL) labels.push([id, LABEL[pl.kind]]);
      const b = pl.box;
      if (pl.kind === 'square') fill(b, 'cobble');
      else if (pl.kind === 'field') { fill(b, 'soil'); for (let y = b[1] + 3; y < b[1] + 6; y++) set(b[0] + 3, y, 'path'); }
      else if (pl.kind === 'forest') fill(b, 'forest');
      else if (pl.kind === 'market' || pl.kind === 'smithy' || pl.kind === 'mine') fill(b, 'block');
      else if (pl.kind === 'pond') fill(b, 'water');
      else if (pl.kind === 'grove' || pl.kind === 'quarry' || pl.kind === 'hamlet') fill(b, 'block');
      else if (pl.kind === 'home') fill(pl.plot, 'block');
    }
    const order = Object.values(lay.places).filter(p => p.kind === 'home')
      .sort((a, b) => names.indexOf(a.owner) - names.indexOf(b.owner));
    order.forEach((pl, k) => houses.push({ name: pl.owner, x: pl.box[0] * T, y: pl.box[1] * T, roof: ROOFS[k % ROOFS.length],
                                           plot: pl.plot.map(v => v * T) }));
    for (const r of lay.routes) {
      const pts = r.path.map(p => px(...p));
      routes[r.a + '|' + r.b] = pts;
      for (let j = 1; j < pts.length; j++) {
        let [x, y] = r.path[j - 1]; const [x1, y1] = r.path[j];
        for (;;) { const k = kind[x + ',' + y]; if (k !== 'cobble' && k !== 'water' && k !== 'block') set(x, y, 'path');
                   if (x === x1 && y === y1) break; x += Math.sign(x1 - x); y += Math.sign(y1 - y); }
      }
    }
    lay.river.dock.x.forEach(x => set(x, lay.river.dock.y, 'dock'));
    // Distance in pixels from a water pixel to the nearest bank of its tile (T = open water).
    const wet = (x, y) => { const k = kind[x + ',' + y]; return k === 'water' || k === 'dock' || x < 0 || x >= lay.cols; };
    const bank = (X, Y) => {
      const tx = X / T | 0, ty = Y / T | 0, x = X % T, y = Y % T;
      let d = T;
      if (!wet(tx - 1, ty)) d = Math.min(d, x); if (!wet(tx + 1, ty)) d = Math.min(d, T - 1 - x);
      if (ty > 0 && !wet(tx, ty - 1)) d = Math.min(d, y); if (ty < lay.rows - 1 && !wet(tx, ty + 1)) d = Math.min(d, T - 1 - y);
      return d;
    };
    const plots = {};  // yard of every house in pixels, for viewer/plotlayer.js
    houses.forEach(h => { plots['home_' + h.name] = h.plot; });
    return { gen: lay, plots, cols: lay.cols, W: lay.cols * T, H: lay.rows * T, kind, anchors, box, routes, houses, off, labels, bank, rows: 0 };
  }

  // Pixel spots of resource objects (MapLayer format) for places pixelmap has no hand-made art for.
  function spots(lay, T) {
    const out = {}, mid = lay.river.x, dy = lay.river.dock.y;
    const fish = [];
    for (let k = 0; k < 8; k++) { const y = Math.max(1, Math.min(lay.rows - 2, dy - 7 + k * 2 + (k > 3 ? 2 : 0))); fish.push([(mid[y] + 1) * T + 4, y * T + 6]); }
    out.river = { fish };
    for (const [id, pl] of Object.entries(lay.places)) {
      if (!pl.box) continue;
      const [x0, y0, w, h] = pl.box.map(v => v * T);
      if (pl.kind === 'grove') out[id] = {
        wood: [0, 1, 2, 3].map(i => [x0 - 6 + i * 18, y0 - 18 + (i % 2) * 10, i % 2 === 1]),
        berries: [0, 1, 2].map(i => [x0 + 4 + i * 20, y0 + h - 16]) };
      else if (pl.kind === 'pond') out[id] = { fish: [0, 1, 2, 3].map(i => [x0 + 12 + (i % 2) * 28, y0 + 10 + (i >> 1) * 18]) };
      else if (pl.kind === 'quarry') out[id] = {
        stone: [0, 1, 2].map(i => [x0 + 2 + i * 20, y0 + 4]), ore: [0, 1, 2].map(i => [x0 + 12 + i * 18, y0 + 22]) };
    }
    return out;
  }

  function paint(g, L, K) {
    const { T, C, R, P, blob, rnd, rock } = K, lay = L.gen;
    // dock and reeds along the river banks
    const d = lay.river.dock, dx0 = Math.min(...d.x) * T, y = d.y * T;
    for (let x = dx0; x < dx0 + 3 * T; x++) for (let yy = y + 3; yy < y + T - 2; yy++)
      P(g, x, yy, yy === y + 3 || yy === y + T - 3 ? C.k : x % 5 === 0 ? C.woodD : C.woodL);
    for (const x of [dx0 + 2, dx0 + 2 * T + 6]) R(g, x, y + T - 2, 2, 4, C.woodD);
    lay.river.x.forEach((x0, ty) => {
      if (Math.abs(ty - d.y) < 2 || rnd(x0, ty, 5) > .45) return;
      const bx = (lay.river.side === 'left' ? x0 + 3 : x0) * T + (lay.river.side === 'left' ? -3 : 1) + (rnd(ty, 3) * 3 | 0), by = ty * T + 4;
      R(g, bx, by, 1, 5, C.leafD); R(g, bx + 2, by + 1, 1, 4, C.leaf); P(g, bx, by - 1, '#7a5030');
    });
    for (const pl of Object.values(lay.places)) {
      if (!pl.box && pl.kind !== 'waypoint') continue;
      if (pl.kind === 'waypoint') { // signpost
        const [x, yy] = [pl.anchor[0] * T + 12, pl.anchor[1] * T - 2];
        R(g, x, yy, 2, 12, C.woodD); R(g, x - 5, yy + 1, 12, 4, C.k); R(g, x - 4, yy + 2, 10, 2, C.woodL);
        continue;
      }
      const [x0, y0, w, h] = pl.box.map(v => v * T);
      if (pl.kind === 'hamlet') { // a small green with a well
        blob(g, x0 + w / 2, y0 + h / 2, w / 2 - 2, h / 2 - 3, [C.grassL, C.grass, C.grassD], null);
        const cx = x0 + w / 2, cy = y0 + h / 2 - 4;
        blob(g, cx, cy + 9, 7, 4, [C.stoneL, C.stone, C.stoneD]); blob(g, cx, cy + 8, 4, 2, ['#1d3550', '#1d3550', '#1d3550'], null);
        R(g, cx - 7, cy - 3, 2, 11, C.woodD); R(g, cx + 5, cy - 3, 2, 11, C.woodD); R(g, cx - 8, cy - 4, 16, 2, '#8f3328');
      } else if (pl.kind === 'pond') {
        for (let i = 0; i < 5; i++) { const bx = x0 + rnd(i, 7) * w | 0, by = y0 + h - 4 + (i % 2) * 3;
          R(g, bx, by, 1, 5, C.leafD); R(g, bx + 2, by + 1, 1, 4, C.leaf); }
      } else if (pl.kind === 'quarry') {
        blob(g, x0 + w / 2, y0 + h / 2 + 2, w / 2 + 2, h / 2, ['#b0a898', '#9a9284', '#7a7466'], null);
      } else if (pl.kind === 'grove') {
        blob(g, x0 + w / 2, y0 + h / 2, w / 2 + 4, h / 2 + 2, [C.grassL, C.grassD, C.grassDD], null);
      } else if (pl.kind === 'home') { // fenced yard around the house
        const [px0, py0, pw, ph] = pl.plot.map(v => v * T);
        for (let yy = py0 + 2; yy < py0 + ph - 1; yy += 6) for (let xx = px0 + 2; xx < px0 + pw - 2; xx += 6)
          if (rnd(xx, yy, 31) < .35) P(g, xx, yy, C.grassL);
        const gate = pl.anchor[0] * T + 8;
        for (let xx = px0; xx < px0 + pw; xx++) for (const yy of [py0, py0 + ph - 1]) if (!(yy > py0 && Math.abs(xx - gate) < 6)) {
          P(g, xx, yy, C.woodD); if (xx % 6 === 0) R(g, xx, yy - 3, 2, 5, C.wood); }
        for (let yy = py0; yy < py0 + ph; yy++) for (const xx of [px0, px0 + pw - 1]) { P(g, xx, yy, C.woodD); if (yy % 6 === 0) R(g, xx - 1, yy, 2, 4, C.wood); }
      }
    }
  }

  return { layout, spots, paint };
})();
if (typeof window !== 'undefined') window.GenMap = GenMap;
