// Procedural maps (aivillage/mapgen.py): the log header carries config.map.layout, a tile plan of the village.
// GenMap.layout() turns it into pixelmap's layout (anchors, boxes, routes, houses, ground kinds) plus `off`:
// how far each hand-drawn landmark (field, square, market, smithy, mine, forest) moved from its place on the
// hand-made map, so pixelmap can paint the same art shifted. GenMap.paint() draws what only generated maps
// have: a winding river with its dock, fenced plots, groves, ponds, quarries, hamlet greens, road signposts.
// GenMap.spots() gives viewer/maplayer.js the pixel spots of resource objects outside the old landmarks.
// A large map (map.size) adds far wild zones: deep forest, lake, cave, clay hills.
const GenMap = (() => {
  const LABEL = { grove: -34, pond: -30, quarry: -34, hamlet: -30, waypoint: -26, lot: -30,
                  deepwood: -40, lake: -30, cave: -40, clayhill: -34 };
  const CLAY = ['#d08a58', '#b0683c', '#86492a'];
  // water tiles of a lake: the ellipse inscribed in its box (mapgen.lake_tiles)
  const lakeTiles = ([x, y, w, h]) => {
    const out = [];
    for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++)
      if (((i + .5 - x - w / 2) / (w / 2)) ** 2 + ((j + .5 - y - h / 2) / (h / 2)) ** 2 <= 1) out.push([i, j]);
    return out;
  };

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
      if (pl.kind in LABEL && !pl.hidden) labels.push([id, LABEL[pl.kind]]);
      const b = pl.box;
      if (pl.kind === 'square') { if (!pl.bare) fill(b, 'cobble'); }   // camp start: grass until something is built
      else if (pl.kind === 'field') { fill(b, 'soil'); for (let y = b[1] + 3; y < b[1] + 6; y++) set(b[0] + 3, y, 'path'); }
      else if (pl.kind === 'forest') fill(b, 'forest');
      else if (pl.kind === 'market' || pl.kind === 'smithy' || pl.kind === 'mine') fill(b, 'block');
      else if (pl.kind === 'pond') fill(b, 'water');
      else if (pl.kind === 'lake') lakeTiles(b).forEach(([x, y]) => set(x, y, 'water'));
      else if (pl.kind === 'deepwood') fill([b[0] - 1, b[1] - 1, b[2] + 2, b[3] + 1], 'forest');
      else if (pl.kind === 'clayhill') fill(b, 'soil');
      else if (pl.kind === 'cave') fill(b, 'block');
      else if (pl.kind === 'grove' || pl.kind === 'quarry' || pl.kind === 'hamlet') fill(b, 'block');
      else if (pl.kind === 'home' || pl.kind === 'lot') fill(pl.plot, 'block');
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
        // a camp start's footpath (viewer/pixelmap.js campLayout) is lighter than a road; a road wins over a footpath
        const kd = r.trail ? 'trail' : 'path';
        for (;;) { const k = kind[x + ',' + y]; if (k !== 'cobble' && k !== 'water' && k !== 'block' && k !== 'path') set(x, y, kd);
                   if (x === x1 && y === y1) break; x += Math.sign(x1 - x); y += Math.sign(y1 - y); }
      }
    }
    lay.river.dock.x.forEach(x => set(x, lay.river.dock.y, 'dock'));
    if (lay.places.square && lay.places.square.bare) set(lay.places.square.anchor[0], lay.places.square.anchor[1], 'trail');   // trodden ground at the camp fire
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
    const lots = {};  // empty land for sale (aivillage/land.py), drawn by viewer/plotlayer.js once someone builds there
    for (const [id, pl] of Object.entries(lay.places)) if (pl.kind === 'lot') lots[id] = plots[id] = pl.plot.map(v => v * T);
    return { gen: lay, plots, lots, cols: lay.cols, W: lay.cols * T, H: lay.rows * T, kind, anchors, box, routes, houses, off, labels, bank, rows: 0 };
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
      else if (pl.kind === 'deepwood') {   // 12 trees fill the wood (4 x 3), more go in the gaps between them
        const wood = [];
        for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++)
          wood.push([x0 - 4 + c * 40 + (r % 2) * 14, y0 - 20 + r * 34, (r + c) % 3 !== 0]);
        for (let r = 0; r < 2; r++) for (let c = 0; c < 4; c++)
          wood.push([x0 + 14 + c * 40 - (r % 2) * 14, y0 - 3 + r * 34, (r + c) % 2 === 0]);
        out[id] = { wood, berries: [0, 1, 2, 3, 4, 5, 6, 7].map(i => [x0 + 4 + i * 19, y0 + h + (i % 2) * 5]) };
      } else if (pl.kind === 'lake') out[id] = {
        fish: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => [x0 + w * (.22 + .14 * (i % 5)), y0 + h * (.3 + .3 * (i > 4)) + (i % 2) * 6]) };
      else if (pl.kind === 'cave') {   // rocks on the hill around the mouth
        const ring = [];
        for (let i = 0; i < 16; i++) { const a = Math.PI * (1.05 + i * 0.86 / 15 * 1.0), r = i % 2 ? .62 : .78;
          ring.push([x0 + w / 2 - 8 + Math.cos(a + Math.PI * .1 * (i % 4)) * w * r * .6, y0 + h * .55 - 10 + Math.sin(a) * h * r * .55 + (i % 3) * 8]); }
        out[id] = { stone: ring.filter((_, i) => i % 3 === 0), ore: ring.filter((_, i) => i % 3 !== 0) };
      } else if (pl.kind === 'clayhill') {
        const clay = [];
        for (let i = 0; i < 6; i++) clay.push([x0 + 6 + (i % 3) * 30, y0 + 8 + (i / 3 | 0) * 28]);   // 6 fill the hills,
        for (let i = 0; i < 6; i++) clay.push([x0 + 20 + (i % 3) * 30 - (i > 2) * 6, y0 + 20 + (i / 3 | 0) * 22]);  // more in between
        out[id] = { clay };
      }
    }
    return out;
  }

  function paint(g, L, K) {
    const { T, C, R, P, blob, rnd, rock } = K, lay = L.gen;
    const SP = K.SP || (() => false), pat = n => window.Sprites && Sprites.has(n) && Sprites.pattern(g, n);
    // dock, reeds and lily pads along the river
    const d = lay.river.dock, dx0 = Math.min(...d.x) * T, y = d.y * T;
    if (K.planks) K.planks(g, dx0, y + 3, 3 * T, T - 5);
    else for (let x = dx0; x < dx0 + 3 * T; x++) for (let yy = y + 3; yy < y + T - 2; yy++)
      P(g, x, yy, yy === y + 3 || yy === y + T - 3 ? C.k : x % 5 === 0 ? C.woodD : C.woodL);
    for (const x of [dx0 + 2, dx0 + 2 * T + 6]) R(g, x, y + T - 2, 2, 4, C.woodD);
    lay.river.x.forEach((x0, ty) => {
      if (Math.abs(ty - d.y) < 2) return;
      if (rnd(x0, ty, 8) < .12) SP(g, 'lilypads', (x0 + 1) * T + (rnd(ty, 9) * T | 0), ty * T + 12);
      if (rnd(x0, ty, 5) > .45) return;
      const bx = (lay.river.side === 'left' ? x0 + 3 : x0) * T + (lay.river.side === 'left' ? -3 : 1) + (rnd(ty, 3) * 3 | 0), by = ty * T + 4;
      if (rnd(ty, 4) < .5 && SP(g, 'reeds', bx + 1, by + 8)) return;
      R(g, bx, by, 1, 5, C.leafD); R(g, bx + 2, by + 1, 1, 4, C.leaf); P(g, bx, by - 1, '#7a5030');
    });
    for (const pl of Object.values(lay.places)) {
      if ((!pl.box && pl.kind !== 'waypoint') || pl.hidden) continue;   // hidden: a camp start's signpost nobody passed yet
      if (pl.kind === 'waypoint') { // signpost
        const [x, yy] = [pl.anchor[0] * T + 12, pl.anchor[1] * T - 2];
        if (SP(g, 'signpost', x + 1, yy + 12)) continue;
        R(g, x, yy, 2, 12, C.woodD); R(g, x - 5, yy + 1, 12, 4, C.k); R(g, x - 4, yy + 2, 10, 2, C.woodL);
        continue;
      }
      const [x0, y0, w, h] = pl.box.map(v => v * T);
      if (pl.kind === 'hamlet') { // a small green with a well
        blob(g, x0 + w / 2, y0 + h / 2, w / 2 - 2, h / 2 - 3, [C.grassL, C.grass, C.grassD], null);
        const cx = x0 + w / 2, cy = y0 + h / 2 - 4;
        if (SP(g, 'well', cx, cy + 14, { s: .8 })) continue;
        blob(g, cx, cy + 9, 7, 4, [C.stoneL, C.stone, C.stoneD]); blob(g, cx, cy + 8, 4, 2, ['#1d3550', '#1d3550', '#1d3550'], null);
        R(g, cx - 7, cy - 3, 2, 11, C.woodD); R(g, cx + 5, cy - 3, 2, 11, C.woodD); R(g, cx - 8, cy - 4, 16, 2, '#8f3328');
      } else if (pl.kind === 'pond') {
        if (SP(g, 'lilypads', x0 + w * .3, y0 + h * .45)) { SP(g, 'lilypads', x0 + w * .72, y0 + h * .8, { flip: true }); SP(g, 'reeds', x0 + 4, y0 + h + 4); SP(g, 'reeds', x0 + w - 2, y0 + 6); continue; }
        for (let i = 0; i < 5; i++) { const bx = x0 + rnd(i, 7) * w | 0, by = y0 + h - 4 + (i % 2) * 3;
          R(g, bx, by, 1, 5, C.leafD); R(g, bx + 2, by + 1, 1, 4, C.leaf); }
      } else if (pl.kind === 'lake') {   // reeds along the shore, lily pads
        SP(g, 'lilypads', x0 + w * .3, y0 + h * .4); SP(g, 'lilypads', x0 + w * .7, y0 + h * .65, { flip: true });
        for (let i = 0; i < 9; i++) { const a = Math.PI * (.15 + i * .3), bx = x0 + w / 2 + Math.cos(a) * w * .47, by = y0 + h / 2 + Math.sin(a) * h * .47;
          if (SP(g, 'reeds', bx, by + 6)) continue; R(g, bx, by, 1, 5, C.leafD); R(g, bx + 2, by + 1, 1, 4, C.leaf); }
      } else if (pl.kind === 'deepwood') {   // old pines all round the edge, behind the trees that can be cut
        if (K.tree) for (let i = 0; i < 16; i++) {
          const a = Math.PI * 2 * i / 16, px = x0 + w / 2 - 16 + Math.cos(a) * (w / 2 + 14), py = y0 + h / 2 - 34 + Math.sin(a) * (h / 2 + 8);
          if (py > y0 + h - 40) continue;  // keep the way in open
          K.tree(g, px + (rnd(i, x0, 3) * 8 | 0), py, true);
        }
      } else if (pl.kind === 'cave') {   // a rocky hill with a dark mouth at the bottom
        blob(g, x0 + w / 2, y0 + h * .55, w / 2 + 6, h / 2 + 4, [C.stoneL, C.stone, C.stoneD]);
        blob(g, x0 + w * .3, y0 + h * .35, w / 4, h / 4, [C.stoneL, C.stone, C.stoneD], null);
        blob(g, x0 + w * .72, y0 + h * .4, w / 4, h / 4, [C.stoneL, C.stone, C.stoneD], null);
        blob(g, x0 + w / 2, y0 + h - 8, 10, 9, ['#2a2622', '#1a1714', '#0e0c0a'], C.k);
        R(g, x0 + w / 2 - 11, y0 + h - 17, 2, 14, C.woodD); R(g, x0 + w / 2 + 9, y0 + h - 17, 2, 14, C.woodD);
        R(g, x0 + w / 2 - 12, y0 + h - 18, 24, 2, C.woodD);   // timber frame of the entrance
      } else if (pl.kind === 'clayhill') {   // low reddish mounds
        for (let i = 0; i < 3; i++) blob(g, x0 + w * (.25 + .25 * i), y0 + h * (.45 + .15 * (i % 2)), w / 4 + 4, h / 3, CLAY, null);
      } else if (pl.kind === 'quarry') {   // a gravel pit with a dark rim
        const gp = pat('tex_gravel');
        if (gp) { g.beginPath(); g.ellipse(x0 + w / 2, y0 + h / 2 + 2, w / 2 + 3, h / 2 + 1, 0, 0, Math.PI * 2);
                  g.fillStyle = gp; g.fill(); g.lineWidth = 1.5; g.strokeStyle = 'rgba(40,34,28,.65)'; g.stroke(); SP(g, 'rubble', x0 + w - 4, y0 + h + 2); }
        else blob(g, x0 + w / 2, y0 + h / 2 + 2, w / 2 + 2, h / 2, ['#b0a898', '#9a9284', '#7a7466'], null);
      } else if (pl.kind === 'grove') {   // forest floor under the birches
        const mp = pat('tex_moss');
        if (mp) { g.beginPath(); g.ellipse(x0 + w / 2, y0 + h / 2, w / 2 + 4, h / 2 + 2, 0, 0, Math.PI * 2); g.fillStyle = mp; g.globalAlpha = .7; g.fill(); g.globalAlpha = 1; }
        else blob(g, x0 + w / 2, y0 + h / 2, w / 2 + 4, h / 2 + 2, [C.grassL, C.grassD, C.grassDD], null);
      } else if (pl.kind === 'home' || pl.kind === 'lot') { // fenced yard around the house; a lot is bare tilled land
        const [px0, py0, pw, ph] = pl.plot.map(v => v * T);
        if (pl.kind === 'lot') for (let yy = py0 + 3; yy < py0 + ph - 2; yy += 4) R(g, px0 + 3, yy, pw - 6, 2, rnd(px0, yy, 9) < .5 ? '#8a6a44' : '#7a5c3a');
        for (let yy = py0 + 2; yy < py0 + ph - 1; yy += 6) for (let xx = px0 + 2; xx < px0 + pw - 2; xx += 6)
          if (rnd(xx, yy, 31) < .35) P(g, xx, yy, C.grassL);
        const gate = pl.anchor[0] * T + 8;
        if (K.fence) { K.fence(g, px0, py0, px0 + pw - 1, py0 + ph - 1, gate); continue; }
        for (let xx = px0; xx < px0 + pw; xx++) for (const yy of [py0, py0 + ph - 1]) if (!(yy > py0 && Math.abs(xx - gate) < 6)) {
          P(g, xx, yy, C.woodD); if (xx % 6 === 0) R(g, xx, yy - 3, 2, 5, C.wood); }
        for (let yy = py0; yy < py0 + ph; yy++) for (const xx of [px0, px0 + pw - 1]) { P(g, xx, yy, C.woodD); if (yy % 6 === 0) R(g, xx - 1, yy, 2, 4, C.wood); }
      }
    }
  }

  // Camp start (pixelmap.js campAnchors): a ring of stones with a fire, bedrolls of those without a house site.
  function camp(g, L, K) {
    const { C, R, P, blob } = K;
    for (const [x, y] of L.bedrolls || []) {
      R(g, x - 7, y - 2, 14, 6, C.k); R(g, x - 6, y - 1, 12, 4, '#8a5a3a'); R(g, x - 6, y - 1, 4, 4, '#c8b48a');
    }
    if (!L.campfire) return;
    const [cx, cy] = L.campfire;
    for (let i = 0; i < 8; i++) { const a = Math.PI * 2 * i / 8; blob(g, cx + Math.cos(a) * 7, cy + Math.sin(a) * 4, 2, 2, [C.stoneL, C.stone, C.stoneD], null); }
    R(g, cx - 4, cy - 1, 8, 2, C.woodD); R(g, cx - 2, cy - 4, 4, 4, '#e4572e'); P(g, cx, cy - 6, '#f2c14e'); P(g, cx - 1, cy - 5, '#f2c14e');
  }

  return { layout, spots, paint, camp, lakeTiles };
})();
if (typeof window !== 'undefined') window.GenMap = GenMap;
