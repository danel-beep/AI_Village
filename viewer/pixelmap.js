// Pixel-art map renderer for the AI Village viewer.
// Art: SpriteCook sprites (viewer/sprites.js) where the atlas has them, else drawn in code here (the fallback).
// The world is painted on a low-res buffer (16 px tiles), upscaled 2x with no smoothing; text goes on top at full res.
// Positions are viewer-only: the engine has no coordinates, only a graph of locations.
const PixelMap = (() => {
  const T = 16, S = 2, COLS = 30, PER_ROW = 6, LOTS = [3, 7, 11, 17, 21, 25], ROW_H = 7;
  const C = {
    k: '#1b1b24', grass: '#5a9a3c', grassL: '#6cb04a', grassD: '#4b8a35', grassDD: '#3d7530',
    dirt: '#c8a26a', dirtD: '#b48c55', dirtL: '#d9b880', water: '#3f7fbf', waterD: '#2f6299', waterL: '#a8d4f0',
    wood: '#8a5a35', woodD: '#6b4226', woodL: '#a8743f', stone: '#9a9aa2', stoneD: '#6f6f78', stoneL: '#c4c4cc',
    leaf: '#2f7a3a', leafD: '#22582c', leafL: '#4a9a48', soil: '#7a5532', soilD: '#5e3f24', wheat: '#e0c040',
    wheatD: '#b8962c', sprout: '#7ab648', plaster: '#e8d4a8', plasterD: '#cbb488', glass: '#6fb3d9', lit: '#ffd36b',
  };
  const ROOFS = [['#b8483a', '#8f3328', '#d46a4f'], ['#3f6fa8', '#2d5280', '#5a8cc4'], ['#5c8a3a', '#43692a', '#7aa852'],
                 ['#8a5aa8', '#684382', '#a77cc4'], ['#c47a2c', '#9a5c1c', '#de9a4a'], ['#5d5d6b', '#44444f', '#7c7c8c']];
  const HAIR = ['#3b2a20', '#e8c060', '#a0452a', '#1d1d24', '#7a5030', '#d8d8d8', '#c96b9a', '#5a3a8a'];
  const SKIN = [['#f2c9a0', '#d9a77e'], ['#d9a066', '#b98049'], ['#a8724a', '#865633'], ['#ffd9b8', '#e8b48e']];
  const PANTS = ['#3e4a6b', '#5a4632', '#2f3a2f', '#4a3a5a'];

  // Character templates, 12x16. 1 skin, 2 skin shade, 3 hair, 4 hair shade, 5 shirt, 6 shirt shade, 7 pants, 8 shoes.
  const HEAD = {
    down: ['...kkkkkk...', '..k333333k..', '.k33333333k.', '.k33333333k.', '.k31111113k.', '.k1k1111k1k.',
           '.k11111111k.', '..k112211k..', '...kk11kk...'],
    up:   ['...kkkkkk...', '..k333333k..', '.k33333333k.', '.k33333333k.', '.k33333333k.', '.k33333333k.',
           '.k43333334k.', '..k444444k..', '...kk11kk...'],
    side: ['...kkkkkk...', '..k333333k..', '.k33333333k.', '.k33333311k.', '.k33331111k.', '.k3331111kk.',
           '..k3111111k.', '...k11111k..', '....k11k....'],
  };
  const BODY = { front: ['..k555555k..', '.k15555551k.', '.k15555551k.', '..k666666k..'],
                 side:  ['...k5555k...', '...k5515k...', '...k5515k...', '...k6666k...'] };
  const LEGS = {
    front: [['..k77kk77k..', '..k88kk88k..', '...kk..kk...'], ['..k77kk77k..', '..k88k.kk...', '...kk.......'],
            ['..k77kk77k..', '...kk.k88k..', '.......kk...']],
    side:  [['...k7777k...', '...k8888k...', '....kkkk....'], ['..k77kk77k..', '.k88k..k88k.', '..kk....kk..'],
            ['...k7777k...', '...k8888k...', '....kkkk....']],
  };

  let W, H, names, bg, buf, b, layout, color = {}, sheets = {}, lastPos = {}, lastTime = null, cols = COLS, genLay = null, pendingInit = null, looks = {}, hdr = null, day = null, built = false, bare = false;

  function rnd(x, y, s = 0) {
    let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(s | 0, 1442695041);
    h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  function shade(hex, f) {
    const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.max(0, Math.min(255, Math.round(v * f))));
    return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
  }
  const R = (g, x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x | 0, y | 0, w, h); };
  const P = (g, x, y, c) => R(g, x, y, 1, 1, c);

  // Filled ellipse with top-left light, bottom-right shade and a dark outline.
  function blob(g, cx, cy, rx, ry, [light, mid, dark], outline = C.k) {
    const inside = (x, y) => ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1;
    for (let y = Math.floor(cy - ry); y <= cy + ry; y++) for (let x = Math.floor(cx - rx); x <= cx + rx; x++) {
      if (!inside(x, y)) continue;
      const edge = !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1) || !inside(x, y + 1);
      const l = (x - cx) / rx + (y - cy) / ry;
      P(g, x, y, edge && outline ? outline : l < -.7 || (l < -.4 && (x + y) % 2) ? light : l > .6 || (l > .3 && (x + y) % 2) ? dark : mid);
    }
  }

  // ---------- layout: where every location sits, and the walkable paths between them (pixels) ----------
  const px = (tx, ty) => [tx * T + 8, ty * T + 8];
  function buildLayout() {
    if (genLay && window.GenMap) {  // generated village (aivillage/mapgen.py, viewer/mapgen.js)
      layout = GenMap.layout(genLay, names, T, ROOFS); W = layout.W; H = layout.H; cols = layout.cols; return;
    }
    cols = COLS;
    const rows = Math.max(1, Math.ceil(names.length / PER_ROW));
    W = COLS * T; H = (19 + ROW_H * rows) * T;
    const kind = {}, set = (x, y, k) => { kind[x + ',' + y] = k; };
    const area = (x0, y0, x1, y1, k) => { for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) set(x, y, k); };
    const anchors = { river: px(4, 9), field: px(8, 6), market: px(15, 4), square: px(15, 9), forest: px(24, 5),
                      mine: px(27, 12), smithy: px(21, 12) };
    const box = { river: [0, 7 * T, 4 * T, 4 * T], field: [5 * T, 2 * T, 6 * T, 6 * T], market: [12 * T, T, 7 * T, 3 * T],
                  square: [12 * T, 7 * T, 7 * T, 5 * T], forest: [21 * T, 0, 9 * T, 8 * T], mine: [25 * T, 8 * T, 5 * T, 4 * T],
                  smithy: [20 * T, 8 * T, 4 * T, 4 * T] };
    const routes = { 'square|market': [px(15, 9), px(15, 4)], 'square|field': [px(15, 9), px(8, 9), px(8, 6)],
                     'square|river': [px(15, 9), px(4, 9)], 'field|river': [px(8, 6), px(8, 9), px(4, 9)],
                     'square|forest': [px(15, 9), px(19, 9), px(19, 5), px(24, 5)],
                     'square|smithy': [px(15, 9), px(15, 12), px(21, 12)],
                     'forest|mine': [px(24, 5), px(24, 12), px(27, 12)] };
    const houses = [];
    names.forEach((n, k) => {
      // Each house has a yard (private plot, viewer/plotlayer.js) of 3x3 tiles behind it.
      const r = Math.floor(k / PER_ROW), x0 = LOTS[k % PER_ROW], y0 = 18 + ROW_H * r, id = 'home_' + n;
      houses.push({ name: n, x: x0 * T, y: y0 * T, roof: ROOFS[k % ROOFS.length] });
      anchors[id] = px(x0 + 1, y0 + 3); box[id] = [x0 * T, y0 * T, 3 * T, 3 * T];
      routes[id + '|square'] = [px(x0 + 1, y0 + 3), px(15, y0 + 3), px(15, 9)];
      area(x0, y0 - 3, x0 + 2, y0 + 2, 'block');
    });
    area(0, 0, 2, H / T, 'water');
    area(12, 7, 18, 11, 'cobble');
    area(5, 2, 10, 7, 'soil');
    area(12, 1, 18, 3, 'block'); area(20, 8, 23, 11, 'block'); area(25, 8, 29, 11, 'block'); area(21, 0, 29, 7, 'forest');
    // Carve paths along every route (tile by tile), then a street in front of each row of houses.
    const carve = pts => {
      for (let j = 1; j < pts.length; j++) {
        let [x, y] = pts[j - 1].map(v => (v - 8) / T); const [x1, y1] = pts[j].map(v => (v - 8) / T);
        for (;;) { if (kind[x + ',' + y] !== 'cobble' && kind[x + ',' + y] !== 'water') set(x, y, 'path');
                   if (x === x1 && y === y1) break; x += Math.sign(x1 - x); y += Math.sign(y1 - y); }
      }
    };
    Object.values(routes).forEach(carve);
    for (let r = 0; r < rows; r++) carve([px(4, 21 + ROW_H * r), px(26, 21 + ROW_H * r)]);
    set(3, 9, 'dock'); set(2, 9, 'dock'); set(1, 9, 'dock');
    for (let y = 5; y <= 9; y++) set(8, y, 'path');
    layout = { kind, anchors, box, routes, houses, rows };
  }
  const kindAt = (x, y) => layout.kind[x + ',' + y] || 'grass';

  // ---------- static background ----------
  function paintGround(g) {
    for (let ty = 0; ty < H / T; ty++) for (let tx = 0; tx < cols; tx++) {
      const k = kindAt(tx, ty), x0 = tx * T, y0 = ty * T;
      for (let y = 0; y < T; y++) for (let x = 0; x < T; x++) {
        const X = x0 + x, Y = y0 + y, r = rnd(X, Y);
        let c;
        if (k === 'water' || k === 'dock') {
          const bank = layout.bank ? layout.bank(X, Y) : 3 * T - X, deep = layout.bank ? bank >= T - 1 : X < T * 1.5;
          c = bank < 2 + rnd(0, Y >> 2) * 3 ? C.waterL : deep ? C.waterD : C.water;
          if (r < .02) c = C.waterL;
        } else if (k === 'path') c = r < .12 ? C.dirtD : r < .2 ? C.dirtL : C.dirt;
        else if (k === 'trail') c = r < .45 ? (r < .1 ? C.dirtD : C.dirt) : r < .55 ? C.grassD : C.grass;   // trodden grass
        else if (k === 'cobble') {
          const sx = (X + ((Y >> 2) % 2) * 3) % 6, sy = Y % 4;
          c = sx === 0 || sy === 0 ? C.stoneD : rnd(X / 6 | 0, Y >> 2, 7) < .5 ? C.stone : C.stoneL;
        } else if (k === 'soil') c = Y % 4 === 3 ? C.soilD : r < .1 ? C.soilD : C.soil;
        else c = r < .07 ? C.grassL : r < .14 ? C.grassD : C.grass;
        P(g, X, Y, c);
      }
      // Soften path edges with grass tufts; sprinkle grass detail.
      if (k === 'path') for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        if (kindAt(tx + dx, ty + dy) !== 'grass') continue;
        for (let s = 0; s < T; s++) if (rnd(tx * 31 + s, ty * 17 + dx * 3 + dy) < .55) {
          const x = dx ? (dx > 0 ? T - 1 : 0) : s, y = dy ? (dy > 0 ? T - 1 : 0) : s;
          P(g, x0 + x, y0 + y, C.grass);
        }
      }
      if (k === 'grass') {
        if (rnd(tx, ty, 1) < .35) { const x = x0 + 3 + (rnd(tx, ty, 2) * 9 | 0), y = y0 + 4 + (rnd(tx, ty, 3) * 8 | 0);
          P(g, x, y, C.grassDD); P(g, x + 2, y, C.grassDD); P(g, x + 1, y - 1, C.grassDD); }
        if (rnd(tx, ty, 4) < .08) { const x = x0 + 4 + (rnd(tx, ty, 5) * 8 | 0), y = y0 + 4 + (rnd(tx, ty, 6) * 8 | 0),
          f = ['#f06a8a', '#f7e26b', '#f4f4f4', '#9ad0f0'][rnd(tx, ty, 8) * 4 | 0];
          P(g, x, y, f); P(g, x + 3, y + 2, f); P(g, x - 2, y + 3, f); }
      }
    }
  }

  // Ground from the SpriteCook textures (tex_* in the atlas). Every kind of ground is a layer; a pixel takes the top
  // layer whose tile plan, blended bilinearly between tile centres plus one shared value noise, is over one half,
  // so edges come out rounded and a little ragged instead of square. Then edges get shading: a wet bank and foam
  // along water, a dark rim on cobbles and beds, a soft shadow along roads. Returns false without the textures.
  const LAYER = { grass: 0, block: 0, forest: 1, soil: 2, path: 3, trail: 3, cobble: 4, water: 5, dock: 5 };
  const LAYER_TEX = ['tex_grass2', 'tex_moss', 'tex_soil', 'tex_dirt', 'tex_cobble', 'tex_water'];
  // A camp village repaints the background whenever a trail or a home appears (campUpdate): only the tiles that
  // changed since the last paint, and a margin for the blending and the edge shading, are computed again.
  let terr = null;   // the last paint: {W, H, code (tile layer * 2 + trail), lay, deepAt, img}
  function terrain(g) {
    if (!window.Sprites || !Sprites.has('tex_grass2')) return false;
    const tex = {}; [...LAYER_TEX, 'tex_grass', 'tex_flowers', 'tex_deep'].forEach(n => { tex[n] = Sprites.pixels(n); });
    const tc = Math.ceil(W / T) + 2, tr = Math.ceil(H / T) + 2, tl = new Int8Array(tc * tr);
    const tile = (x, y) => tl[(Math.max(-1, Math.min(tc - 2, y)) + 1) * tc + Math.max(-1, Math.min(tc - 2, x)) + 1];
    for (let y = -1; y < tr - 1; y++) for (let x = -1; x < tc - 1; x++) {
      const k = layout.kind[x + ',' + y] || (x < 0 && kindAt(0, Math.max(0, y)) === 'water' ? 'water' : 'grass');
      tl[(y + 1) * tc + x + 1] = LAYER[k] ?? 0;
    }
    // roads drawn with diagonal steps touch only at corners: fill one side so they stay connected
    for (let y = -1; y < tr - 2; y++) for (let x = -1; x < tc - 2; x++) for (const L of [3, 4]) {
      const a = tile(x, y) === L, b = tile(x + 1, y + 1) === L, c = tile(x + 1, y) === L, d = tile(x, y + 1) === L;
      if (a && b && !c && !d && tile(x + 1, y) < L) tl[(y + 1) * tc + x + 2] = L;
      if (c && d && !a && !b && tile(x, y) < L) tl[(y + 1) * tc + x + 1] = L;
    }
    const deep = (x, y) => { for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) if (tile(x + i, y + j) !== 5) return 0; return 1; };
    const smooth = t => t * t * (3 - 2 * t);
    const noise = (X, Y, s, seed) => {
      const u = X / s, v = Y / s, i = Math.floor(u), j = Math.floor(v), fx = smooth(u - i), fy = smooth(v - j);
      const a = rnd(i, j, seed), b = rnd(i + 1, j, seed), c = rnd(i, j + 1, seed), d = rnd(i + 1, j + 1, seed);
      return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy;
    };
    // A pixel's layer depends on the tiles up to 2 around its own (bilinear blend over the next tile, deep water one
    // more) and its colour on the layers 2 pixels around it: a changed tile redoes layers 2 tiles around, colours 3.
    const code = new Int8Array(tc * tr);
    for (let y = -1; y < tr - 1; y++) for (let x = -1; x < tc - 1; x++)
      code[(y + 1) * tc + x + 1] = tl[(y + 1) * tc + x + 1] * 2 + (layout.kind[x + ',' + y] === 'trail');
    const fresh = !terr || terr.W !== W || terr.H !== H || terr.tc !== tc;
    const layMask = new Uint8Array(tc * tr), colMask = new Uint8Array(tc * tr);
    let dirty = 0;
    if (fresh) { layMask.fill(1); colMask.fill(1); }
    else for (let k = 0; k < tc * tr; k++) {
      if (code[k] === terr.code[k]) continue;
      dirty++;
      const x0 = k % tc, y0 = (k / tc) | 0;
      for (let y = Math.max(0, y0 - 3); y <= Math.min(tr - 1, y0 + 3); y++)
        for (let x = Math.max(0, x0 - 3); x <= Math.min(tc - 1, x0 + 3); x++) {
          colMask[y * tc + x] = 1;
          if (Math.abs(x - x0) <= 2 && Math.abs(y - y0) <= 2) layMask[y * tc + x] = 1;
        }
    }
    if (!fresh && !dirty) { g.putImageData(terr.img, 0, 0); return true; }
    const lay = fresh ? new Int8Array(W * H) : terr.lay, deepAt = fresh ? new Uint8Array(W * H) : terr.deepAt;
    const img = fresh ? g.createImageData(W, H) : terr.img, out = img.data;
    // every pixel of the grid tiles marked in mask (grid tile k covers map tile x = k % tc - 1)
    const each = (mask, fn) => {
      for (let k = 0; k < tc * tr; k++) if (mask[k]) {
        const tx = k % tc - 1, ty = ((k / tc) | 0) - 1;
        for (let Y = Math.max(0, ty * T); Y < Math.min(H, ty * T + T); Y++)
          for (let X = Math.max(0, tx * T); X < Math.min(W, tx * T + T); X++) fn(X, Y);
      }
    };
    each(layMask, (X, Y) => {
      const v = (Y + .5) / T - .5, ty = Math.floor(v), fy = v - ty;
      const u = (X + .5) / T - .5, tx = Math.floor(u), fx = u - tx;
      const t00 = tile(tx, ty), t10 = tile(tx + 1, ty), t01 = tile(tx, ty + 1), t11 = tile(tx + 1, ty + 1);
      const n = (noise(X, Y, 6, 1) - .5) * .32 + (rnd(X, Y, 2) - .5) * .06;
      let L = 0;
      for (let l = Math.max(t00, t10, t01, t11); l > 0; l--) {
        const w = ((t00 >= l) * (1 - fx) + (t10 >= l) * fx) * (1 - fy) + ((t01 >= l) * (1 - fx) + (t11 >= l) * fx) * fy;
        if (w + n > .5) { L = l; break; }
      }
      lay[Y * W + X] = L; deepAt[Y * W + X] = 0;
      if (L === 5) {
        const w = (deep(tx, ty) * (1 - fx) + deep(tx + 1, ty) * fx) * (1 - fy) + (deep(tx, ty + 1) * (1 - fx) + deep(tx + 1, ty + 1) * fx) * fy;
        deepAt[Y * W + X] = Math.round(255 * Math.max(0, Math.min(1, (w + (noise(X, Y, 9, 3) - .5) * .5 - .25) * 1.6)));
      }
    });
    const at = (n, X, Y) => { const t = tex[n], i = ((Y % t.height) * t.width + X % t.width) * 4; return t.data.subarray(i, i + 3); };
    const near = (X, Y, r, test) => {   // is any pixel within r (4-neighbour rings) passing test?
      for (let d = 1; d <= r; d++) for (const [dx, dy] of [[d, 0], [-d, 0], [0, d], [0, -d]]) {
        const x = X + dx, y = Y + dy;
        if (x >= 0 && y >= 0 && x < W && y < H && test(lay[y * W + x])) return d;
      }
      return 0;
    };
    each(colMask, (X, Y) => {
      const i = Y * W + X, L = lay[i];
      let c = at(LAYER_TEX[L], X, Y), f = 1, mix = null, mixA = 0;
      if (L === 5 && deepAt[i]) { mix = at('tex_deep', X, Y); mixA = deepAt[i] / 255 * .85; }
      if (L === 3 && layout.kind[(X / T | 0) + ',' + (Y / T | 0)] === 'trail') {   // a footpath: dirt half grown over
        mix = at('tex_grass2', X, Y); mixA = noise(X, Y, 4, 11) > .45 ? .75 : .2;
      }
      if (L === 0) {   // soft patches of lighter grass and a few flower meadows break the repetition
        const m = noise(X, Y, 40, 5);
        mix = at('tex_grass', X, Y); mixA = Math.max(.2, Math.min(.6, .2 + (m - .5) * 2));
        if (noise(X, Y, 24, 6) > .8) { mix = at('tex_flowers', X, Y); mixA = 1; }
      }
      if (L === 5) {
        const d = near(X, Y, 2, l => l !== 5);
        if (d === 1) { mix = [214, 236, 246]; mixA = .55; } else if (d === 2) { mix = [190, 224, 240]; mixA = .25; }
      } else {
        const w = near(X, Y, 2, l => l === 5);
        if (w) f = w === 1 ? .62 : .8;   // wet bank
        else if (L === 4 && near(X, Y, 1, l => l < 4)) f = .62;
        else if ((L === 2 || L === 3) && near(X, Y, 1, l => l < L)) f = .82;
        else if (L < 3 && near(X, Y, 1, l => l === 3 || l === 4)) f = .86;
      }
      const o = i * 4;
      for (let k = 0; k < 3; k++) out[o + k] = Math.round(((mix ? c[k] * (1 - mixA) + mix[k] * mixA : c[k])) * f);
      out[o + 3] = 255;
    });
    terr = { W, H, tc, code, lay, deepAt, img };
    g.putImageData(img, 0, 0);
    return true;
  }

  // Sprite art (viewer/sprites.js) when the atlas is loaded; the code-drawn art below is the fallback.
  const SP = (g, n, x, y, o) => window.Sprites && Sprites.draw(g, n, x, y, o);
  const ORE = { '#d4a83a': 'gold_rock', '#7ad0e0': 'crystal_rock' };
  function tree(g, x, y, pine) {
    if (SP(g, pine ? 'pine' : rnd(x, y, 5) < .15 ? 'apple_tree' : 'oak', x + 16, y + 32)) return;
    if (window.Depth) Depth.add(g, 'tree', x + 2, y, 28, 32, c => treeArt(c, x, y, pine));
    treeArt(g, x, y, pine);
  }
  function treeArt(g, x, y, pine) {
    blob(g, x + 16, y + 30, 11, 3, ['rgba(0,0,0,.18)', 'rgba(0,0,0,.18)', 'rgba(0,0,0,.18)'], null);
    R(g, x + 13, y + 20, 6, 10, C.k); R(g, x + 14, y + 20, 4, 9, C.wood); R(g, x + 14, y + 20, 1, 9, C.woodL);
    if (pine) {
      for (let layer = 0; layer < 3; layer++) for (let i = 0; i < 11; i++) {
        const yy = y + 2 + layer * 7 + i, half = 3 + i + layer * 2;
        if (yy > y + 24) break;
        for (let xx = -half; xx <= half; xx++) {
          const edge = Math.abs(xx) === half || i === 10;
          P(g, x + 16 + xx, yy, edge ? C.k : xx < -half / 3 ? C.leafL : xx > half / 2 ? C.leafD : C.leaf);
        }
      }
    } else {
      const pal = [C.leafL, C.leaf, C.leafD];
      blob(g, x + 16, y + 13, 13, 11, pal); blob(g, x + 10, y + 12, 7, 7, pal, null); blob(g, x + 20, y + 9, 7, 6, pal, null);
      for (let i = 0; i < 6; i++) P(g, x + 8 + rnd(x, y, i) * 16, y + 6 + rnd(y, x, i) * 12, C.leafL);
    }
  }
  function bush(g, x, y) { if (SP(g, rnd(x, y) < .4 ? 'berry_bush' : 'bush', x + 8, y + 16)) return;
    blob(g, x + 8, y + 10, 7, 5, [C.leafL, C.leaf, C.leafD]);
    if (rnd(x, y) < .4) { P(g, x + 5, y + 8, '#e4572e'); P(g, x + 10, y + 10, '#e4572e'); } }
  function rock(g, x, y, ore) { if (SP(g, ore ? ORE[ore] || 'copper_rock' : 'boulder', x + 8, y + 16)) return;
    blob(g, x + 8, y + 10, 6, 5, [C.stoneL, C.stone, C.stoneD]);
    if (ore) { P(g, x + 6, y + 9, ore); P(g, x + 9, y + 11, ore); P(g, x + 10, y + 8, ore); } }
  // Wooden planks (dock, bridge) from the tex_planks texture, code-drawn without it.
  function planks(g, x, y, w, h) {
    const pat = window.Sprites && Sprites.has('tex_planks') && Sprites.pattern(g, 'tex_planks');
    if (pat) { g.fillStyle = pat; g.fillRect(x, y, w, h); R(g, x, y, w, 1, C.k); R(g, x, y + h - 1, w, 1, C.k); R(g, x, y + h, w, 1, 'rgba(0,0,0,.25)'); }
    else for (let xx = x; xx < x + w; xx++) for (let yy = y; yy < y + h; yy++)
      P(g, xx, yy, yy === y || yy === y + h - 1 ? C.k : xx % 5 === 0 ? C.woodD : C.woodL);
  }
  // Fence around a rectangle (x0, y0)-(x1, y1) with a gap in the bottom side at gapX: sprite rails and posts.
  function fenceSprite(g, x0, y0, x1, y1, gapX) {
    if (!window.Sprites || !Sprites.has('fence_h') || !Sprites.has('fence_v')) return false;
    const [, vh] = Sprites.size('fence_v'), step = Math.max(8, vh - 4);
    for (let y = y0 + step; y < y1; y += step) { SP(g, 'fence_v', x0 + 1, Math.min(y + 4, y1 + 2)); SP(g, 'fence_v', x1, Math.min(y + 4, y1 + 2)); }
    const xs = []; for (let x = x0; x < x1 - 4; x += 16) xs.push(Math.min(x, x1 - 16));
    for (const x of xs) {
      SP(g, 'fence_h', x + 8, y0 + 5);
      if (gapX == null || Math.abs(x + 8 - gapX) >= 12) SP(g, 'fence_h', x + 8, y1 + 5);
    }
    return true;
  }
  function fence(g, x0, y0, x1, y1, gapX) {
    if (fenceSprite(g, x0, y0, x1, y1, gapX)) return;
    for (let x = x0; x <= x1; x++) for (const y of [y0, y1]) if (!(y === y1 && Math.abs(x - gapX) < 9)) {
      P(g, x, y + 2, C.woodD); P(g, x, y + 5, C.woodD); if (x % 8 === 0) R(g, x, y, 2, 8, C.wood); }
    for (let y = y0; y <= y1; y += 8) for (const x of [x0, x1]) R(g, x, y, 2, 8, C.wood);
  }

  // A house sprite of the given level (1-3) in the owner's roof colour, standing on the 3x3 lot; sets the chimney
  // (smoke) and windows (night lights) to the sprite's. Returns false when there is no sprite art.
  function houseSprite(g, h, level) {
    // four looks per level: the first generated house or one of the three templates, picked by the owner's name
    const style = h.name ? [...h.name].reduce((a, ch) => a * 31 + ch.charCodeAt(0), 7) % 4 : 0;
    let n = 'house' + level + (style ? 'abc'[style - 1] : '');
    if (!window.Sprites || !Sprites.has(n + '_r0')) n = 'house' + level;
    const k = Math.max(0, ROOFS.indexOf(h.roof)), bx = h.x + 24, by = h.y + 47;
    if (!window.Sprites || !Sprites.has(n + '_r' + k)) return false;
    if (level > 1 && layout.ground) {   // in the season's colours, or a green square shows behind the roof in autumn / winter
      const gr = window.SeasonLayer && hdr && day != null ? SeasonLayer.ground(layout.ground, hdr, day) : layout.ground;
      g.drawImage(gr, h.x, h.y - 2, 3 * T, 3 * T + 2, h.x, h.y - 2, 3 * T, 3 * T + 2);
    }
    SP(g, n + '_r' + k, bx, by);
    const m = Sprites.meta(n);
    h.chimney = [bx + m.chimney[0], by + m.chimney[1]];
    h.windows = m.windows.map(([dx, dy]) => [bx + dx - 4, by + dy - 3]);
    return true;
  }
  function house(g, h) {
    if (houseSprite(g, h, 1)) return;
    const { x, y, roof: [rm, rd, rl] } = h;
    R(g, x + 4, y + 46, 44, 2, 'rgba(0,0,0,.2)');
    // walls
    R(g, x + 2, y + 24, 44, 22, C.k); R(g, x + 3, y + 24, 42, 21, C.plaster);
    for (let yy = y + 28; yy < y + 45; yy += 4) R(g, x + 3, yy, 42, 1, C.plasterD);
    R(g, x + 3, y + 43, 42, 2, C.plasterD);
    // door and windows
    R(g, x + 19, y + 31, 10, 15, C.k); R(g, x + 20, y + 32, 8, 14, C.wood); R(g, x + 20, y + 32, 1, 14, C.woodL);
    P(g, x + 26, y + 39, C.wheat);
    h.windows = [[x + 7, y + 31], [x + 33, y + 31]];
    for (const [wx, wy] of h.windows) { R(g, wx, wy, 9, 8, C.k); R(g, wx + 1, wy + 1, 7, 6, C.glass);
      R(g, wx + 4, wy + 1, 1, 6, C.k); R(g, wx + 1, wy + 4, 7, 1, C.k); P(g, wx + 2, wy + 2, '#d8f0ff'); R(g, wx - 1, wy + 8, 11, 2, C.woodD); }
    // chimney
    R(g, x + 34, y + 1, 8, 12, C.k); R(g, x + 35, y + 2, 6, 11, C.stoneD); R(g, x + 35, y + 2, 6, 2, C.stone);
    h.chimney = [x + 38, y];
    // roof: trapezoid with shingle rows
    for (let i = 0; i < 26; i++) {
      const inset = Math.round(8 - i * 10 / 25), yy = y + 2 + i;
      R(g, x + inset - 1, yy, 50 - 2 * inset, 1, C.k);
      if (i === 0 || i === 25) continue;
      R(g, x + inset, yy, 48 - 2 * inset, 1, i % 5 === 0 ? rd : i < 4 ? rl : rm);
      if (i % 5 !== 0) for (let xx = x + inset + ((i / 5 | 0) % 2) * 3; xx < x + 48 - inset; xx += 6) P(g, xx, yy, rd);
    }
  }

  function market(g) {
    if (bare) return;
    const awn = [['#c93c3c', '#f2ead8'], ['#3f6fa8', '#f2ead8'], ['#d9a020', '#f2ead8']];
    const goods = [['#e4572e', '#ff9f1c'], ['#76b041', '#f7e26b'], ['#c47ac0', '#e4572e']];
    for (let s = 0; s < 3; s++) {
      const x = 12 * T + 4 + s * 36, y = T + 2;
      if (SP(g, 'market', x + 16, y + 34)) continue;
      R(g, x + 2, y + 6, 2, 26, C.woodD); R(g, x + 28, y + 6, 2, 26, C.woodD);
      R(g, x, y + 22, 32, 12, C.k); R(g, x + 1, y + 22, 30, 11, C.wood); R(g, x + 1, y + 22, 30, 2, C.woodL);
      for (let i = 0; i < 10; i++) { const gx = x + 3 + i * 3, c = goods[s][i % 2]; P(g, gx, y + 20, c); P(g, gx + 1, y + 20, c); P(g, gx, y + 19, c); }
      for (let i = 0; i < 12; i++) for (let xx = 0; xx < 34; xx++) {
        const c = i === 0 || i === 11 ? C.k : awn[s][(xx >> 2) % 2];
        if (i === 11 && (xx >> 2) % 2) continue;
        P(g, x - 1 + xx, y + i, c);
      }
    }
    for (const [cx, cy] of [[12 * T - 4, 3 * T], [19 * T - 6, 2 * T + 6]]) {
      R(g, cx, cy, 12, 11, C.k); R(g, cx + 1, cy + 1, 10, 9, C.woodL); R(g, cx + 1, cy + 5, 10, 1, C.woodD); }
  }

  function square(g) {
    if (bare) { layout.lamps = []; return; }   // camp start (viewer/buildlayer.js): nothing built on the square yet
    // well
    const x = 12 * T + 10, y = 7 * T + 4;
    if (!SP(g, 'well', x + 10, y + 26)) {
    blob(g, x + 10, y + 19, 10, 6, [C.stoneL, C.stone, C.stoneD]); blob(g, x + 10, y + 18, 6, 3, ['#1d3550', '#1d3550', '#1d3550'], null);
    R(g, x + 2, y + 3, 2, 16, C.woodD); R(g, x + 16, y + 3, 2, 16, C.woodD);
    for (let i = 0; i < 6; i++) R(g, x - 1 + i, y + 3 - i, 22 - 2 * i, 1, i ? '#8f3328' : C.k);
    R(g, x - 1, y + 3, 22, 1, C.k); R(g, x + 9, y + 8, 2, 7, C.wood);
    }
    // benches and lamps
    for (const bx of [16 * T + 2, 13 * T + 6]) { R(g, bx, 10 * T + 6, 22, 4, C.k); R(g, bx + 1, 10 * T + 6, 20, 3, C.woodL); R(g, bx + 2, 10 * T + 10, 2, 3, C.k); R(g, bx + 18, 10 * T + 10, 2, 3, C.k); }
    layout.lamps = [[12 * T + 2, 11 * T + 2], [18 * T + 12, 7 * T + 2]];
    for (const [lx, ly] of layout.lamps) if (!SP(g, 'lamp', lx + 1, ly + 3)) { R(g, lx, ly - 14, 2, 16, C.k); R(g, lx - 2, ly - 18, 6, 5, C.k); R(g, lx - 1, ly - 17, 4, 3, '#f7e26b'); }
  }

  function field(g) {
    if (!window.MapLayer) for (let y = 2 * T + 3; y < 8 * T - 4; y += 4) for (let x = 5 * T + 3; x < 11 * T - 3; x += 4) {
      if (Math.abs(x - (8 * T + 8)) < 9) continue;
      const ripe = rnd(x, y, 9) < .7;
      P(g, x, y, ripe ? C.wheatD : C.sprout); P(g, x, y - 1, ripe ? C.wheat : C.sprout); P(g, x + 1, y - 2, ripe ? C.wheat : '#9ad060');
      P(g, x - 1, y - 2, ripe ? C.wheat : C.sprout); if (ripe) P(g, x, y - 3, C.wheat);
    }
    fence(g, 5 * T - 2, 2 * T - 6, 11 * T, 8 * T - 4, 8 * T + 8);
    // scarecrow
    const x = 6 * T + 4, y = 5 * T - 2; if (SP(g, 'scarecrow', x + 4, y + 17)) return; R(g, x + 3, y + 4, 1, 12, C.woodD); R(g, x, y + 6, 8, 1, C.woodD);
    R(g, x + 1, y + 6, 6, 5, '#c47a2c'); blob(g, x + 3.5, y + 3, 3, 3, ['#f2d38a', '#e8c060', '#c9a040']); R(g, x, y, 8, 1, '#5a3a2a');
  }

  function river(g) {
    // dock planks
    planks(g, T, 9 * T + 3, 3 * T, T - 5);
    for (const x of [T + 2, 2 * T + 6]) R(g, x, 10 * T - 2, 2, 4, C.woodD);
    for (let y = 0; y < H; y += 9) if (rnd(3, y) < .45 && Math.abs(y - 9 * T) > 20) {
      const x = 3 * T - 2 + (rnd(y, 3) * 3 | 0);
      if (rnd(y, 4) < .5 && SP(g, 'reeds', x + 2, y + 8)) continue;
      R(g, x, y, 1, 5, C.leafD); R(g, x + 2, y + 1, 1, 4, C.leaf); P(g, x, y - 1, '#7a5030'); }
    for (let y = 2 * T; y < H; y += 5 * T) SP(g, 'lilypads', T + (rnd(y, 6) * T | 0), y + (rnd(y, 7) * 2 * T | 0));
    rock(g, 2 * T + 2, 13 * T, null); rock(g, 2 * T + 6, 4 * T, null);
  }

  function smithy(g) {
    if (bare) { layout.forge = layout.smithyChimney = null; return; }
    const x = 20 * T, y = 8 * T;
    if (SP(g, 'smithy', x + 32, y + 64)) {   // spots measured on the 60 px wide sprite, scaled to its size now
      const k = Sprites.size('smithy')[0] / 60;
      layout.forge = [x + 32 - 3 * k, y + 64 - 15 * k]; layout.smithyChimney = [x + 32 + 15 * k, y + 64 - 63 * k]; return;
    }
    R(g, x + 2, y + 62, 60, 2, 'rgba(0,0,0,.2)');
    R(g, x + 2, y + 26, 60, 36, C.k);
    for (let yy = y + 27; yy < y + 61; yy++) for (let xx = x + 3; xx < x + 61; xx++)
      P(g, xx, yy, (yy - y) % 5 === 0 || (xx + ((yy - y) / 5 | 0) * 4) % 8 === 0 ? C.stoneD : rnd(xx >> 3, yy / 5 | 0) < .5 ? C.stone : C.stoneL);
    R(g, x + 22, y + 40, 20, 22, C.k); R(g, x + 23, y + 41, 18, 21, '#2a1a14');
    R(g, x + 26, y + 52, 12, 6, '#ff7b1c'); R(g, x + 28, y + 50, 8, 3, '#ffd23f'); layout.forge = [x + 32, y + 52];
    R(g, x + 6, y + 36, 9, 8, C.k); R(g, x + 7, y + 37, 7, 6, '#ff9f4c');
    R(g, x + 48, y - 2, 10, 20, C.k); R(g, x + 49, y - 1, 8, 19, C.stoneD); R(g, x + 49, y - 1, 8, 2, C.stoneL); layout.smithyChimney = [x + 53, y - 3];
    for (let i = 0; i < 26; i++) { const inset = Math.round(10 - i * 12 / 25);
      R(g, x + inset - 1, y + 2 + i, 66 - 2 * inset, 1, C.k);
      if (i && i < 25) R(g, x + inset, y + 2 + i, 64 - 2 * inset, 1, i % 4 === 0 ? '#3a3a48' : i < 4 ? '#6a6a7c' : '#4e4e5e'); }
    // anvil
    const ax = 23 * T, ay = 12 * T + 2;
    R(g, ax, ay, 12, 4, C.k); R(g, ax + 1, ay + 1, 10, 2, '#5d5d6b'); R(g, ax + 4, ay + 4, 4, 5, C.k); R(g, ax + 2, ay + 8, 8, 3, C.k);
  }

  function mine(g) {
    const x0 = 25 * T, y0 = 8 * T;
    if (SP(g, 'mine', x0 + 38, y0 + 62)) {   // a cart of ore and a coal crate by the shared mine's mouth
      SP(g, 'mine_cart', x0 + 68, y0 + 62); SP(g, 'coal_crate', x0 + 8, y0 + 60);
      if (!window.MapLayer) { rock(g, 29 * T - 4, 12 * T, '#d4a83a'); rock(g, 25 * T + 2, 12 * T + 2, '#7ad0e0'); rock(g, 28 * T, 13 * T + 4, null); }
      return;
    }
    const pal = [C.stoneL, C.stone, C.stoneD];
    for (let i = 0; i < 14; i++) blob(g, x0 + 6 + rnd(i, 1) * 68, y0 + 6 + rnd(i, 2) * 40, 10 + rnd(i, 3) * 8, 8 + rnd(i, 4) * 6, pal);
    blob(g, x0 + 40, y0 + 30, 30, 22, pal);
    // entrance
    const ex = 27 * T - 4, ey = 10 * T - 4;
    blob(g, ex + 12, ey + 14, 11, 14, ['#14141a', '#14141a', '#14141a'], C.k); R(g, ex, ey + 14, 25, 22, C.stone);
    R(g, ex + 2, ey + 6, 20, 30, '#14141a');
    R(g, ex, ey + 4, 3, 32, C.wood); R(g, ex + 21, ey + 4, 3, 32, C.wood); R(g, ex - 1, ey + 2, 26, 4, C.woodD);
    for (let y = ey + 30; y < 12 * T + 14; y += 3) { R(g, ex + 6, y, 12, 1, C.woodD); }
    R(g, ex + 7, ey + 30, 1, 12 * T + 14 - ey - 30, '#8a8a92'); R(g, ex + 16, ey + 30, 1, 12 * T + 14 - ey - 30, '#8a8a92');
    if (!window.MapLayer) { rock(g, 29 * T - 4, 12 * T, '#d4a83a'); rock(g, 25 * T + 2, 12 * T + 2, '#7ad0e0'); rock(g, 28 * T, 13 * T + 4, null); }
  }

  function forest(g) {
    const o = (layout.off || {}).forest || [0, 0], list = [];  // drawn at the hand-made spot, shifted by o
    const cx = layout.anchors.forest[0] - o[0], cy = layout.anchors.forest[1] - o[1];
    for (let ty = -1; ty < 6; ty += 2) for (let tx = 21; tx < 30; tx += 2) {
      const x = tx * T + (rnd(tx, ty, 11) * 10 | 0) - 6, y = ty * T + (rnd(tx, ty, 12) * 8 | 0) - 4;
      if (Math.hypot(x + 16 - cx, y + 28 - cy) < 30) continue;
      if (Math.abs(x + 16 - cx) < 14 && y + 24 > cy) continue;
      list.push([x, y, rnd(tx, ty, 13) < .5]);
    }
    const live = window.MapLayer ? MapLayer.claimTrees(list, cx, cy) : new Set();
    list.filter(t => !live.has(t)).sort((a, b) => a[1] - b[1]).forEach(([x, y, pine]) => tree(g, x, y, pine));
    R(g, cx - 18, cy + 4, 10, 6, C.k); R(g, cx - 17, cy + 5, 8, 4, C.wood); R(g, cx - 16, cy + 5, 6, 1, '#e8c090');
    P(g, cx + 12, cy - 6, '#e4572e'); P(g, cx + 13, cy - 6, '#e4572e'); P(g, cx + 12, cy - 5, '#f4f4f4');
  }

  function decor(g) {
    const items = [];
    for (let ty = 0; ty < H / T; ty++) for (let tx = 3; tx < cols; tx++) {
      let free = true;
      for (let dy = -1; dy <= 2 && free; dy++) for (let dx = -1; dx <= 2; dx++) if (kindAt(tx + dx, ty + dy) !== 'grass') { free = false; break; }
      if (!free) continue;
      let r = rnd(tx, ty, 21);
      if (campLay) {   // camp start: an open meadow around the camp, the wild thickening further out
        const [cx, cy] = layout.anchors.square || [0, 0], d = Math.hypot(tx - cx / T, ty - cy / T);
        r /= Math.max(.15, Math.min(1, (d - 5) / 14));
      }
      if (r < .12) items.push([tx * T, ty * T - 8, 'tree']); else if (r < .2) items.push([tx * T, ty * T, 'bush']);
      else if (r < .23) items.push([tx * T, ty * T, 'rock']);
    }
    items.sort((a, b) => a[1] - b[1]).forEach(([x, y, k]) => k === 'tree' ? tree(g, x, y, rnd(x, y) < .3) : k === 'bush' ? bush(g, x, y) : rock(g, x, y));
  }

  // The background as it is before houses go on it: a bigger house (level 2-3) first wipes the small one with it.
  function groundCopy() {
    const c = document.createElement('canvas'); c.width = W; c.height = H; c.getContext('2d').drawImage(bg, 0, 0);
    layout.ground = c;
  }
  function paintBackground() {
    if (window.Depth) Depth.begin('bg');   // trees, houses and buildings that can stand in front of a villager
    paintScene();
    if (window.Depth) Depth.end();
  }
  function paintScene() {
    layout.shimmer = [];   // glints on open water (the river, wherever it runs, and ponds)
    for (let y = 2; y < H; y += 7) for (let x = 2; x < W - 4; x += 11)
      if (kindAt(x / T | 0, y / T | 0) === 'water' && kindAt((x + 4) / T | 0, y / T | 0) === 'water') layout.shimmer.push([x, y]);
    bg = document.createElement('canvas'); bg.width = W; bg.height = H;
    const g = bg.getContext('2d');
    if (layout.gen) return paintGenerated(g);
    terrain(g) || paintGround(g); river(g); field(g); square(g); market(g); smithy(g); mine(g); decor(g);
    groundCopy(); if (!built) layout.houses.forEach(h => house(g, h)); forest(g);
  }

  // Generated village: the same landmark art, each shifted to where the generator put it.
  function paintGenerated(g) {
    const at = (id, fn) => { const [dx, dy] = layout.off[id] || [0, 0]; g.save(); g.translate(dx, dy); fn(g); g.restore(); return [dx, dy]; };
    const move = ([x, y], [dx, dy]) => [x + dx, y + dy];
    terrain(g) || paintGround(g); GenMap.paint(g, layout, { T, C, R, P, blob, rnd, rock, SP, fence, planks, tree });
    if (layout.off.field) at('field', field);  // newer villages have no common field
    const sq = at('square', square); layout.lamps = layout.lamps.map(p => move(p, sq));
    at('market', market);
    const sm = at('smithy', smithy); if (layout.forge) { layout.forge = move(layout.forge, sm); layout.smithyChimney = move(layout.smithyChimney, sm); }
    at('mine', mine); decor(g);
    groundCopy(); if (!built) layout.houses.forEach(h => house(g, h)); at('forest', forest);
    if (campLay) GenMap.camp(g, layout, { C, R, P, blob });
  }

  // ---------- characters ----------
  // Sprite villagers: a look of the villager's sex (guessed from the name) that fits the profession (straw hat for
  // the farmer, apron for the smith...), each look once while there are enough of them, then recoloured repeats.
  // A look set in the start screen (config agents[].look) wins.
  const PROF_LOOK = { farmer: [0, 5, 23, 1], smith: [4, 10, 13], fisher: [9, 6, 11], woodcutter: [16, 6, 2, 13],
                      miner: [12, 10, 3], trader: [18, 19], merchant: [18, 19] };
  function pickLooks(agents) {
    const S = window.Sprites, n = (S && S.LOOKS) || 12, count = {}, out = {};
    const take = (name, look) => { out[name] = [look, count[look] || 0]; count[look] = (count[look] || 0) + 1; };
    agents.forEach(a => { if (Number.isInteger(a.look) && a.look >= 0 && a.look < n) take(a.name, a.look); });
    agents.forEach((a, k) => {
      if (out[a.name]) return;
      const fits = i => !S || !S.lookIsFemale || S.lookIsFemale(i) === S.femaleName(a.name);
      const all = Array.from({ length: n }, (_, i) => (k + i) % n).filter(fits);
      const pref = [...(PROF_LOOK[a.profession] || []).filter(fits), ...all];
      const look = pref.find(i => !count[i]) ?? pref.reduce((m, i) => (count[i] < count[m] ? i : m), pref[0] ?? k % n);
      take(a.name, look);
    });
    return out;
  }
  function sheetFor(name, k) {
    const [look, variant] = looks[name] || [k, 0], art = window.Sprites && Sprites.ok && Sprites.villager(look, variant);
    if (art) return art;
    const shirt = color[name], skin = SKIN[k % SKIN.length], hair = HAIR[(k * 3 + 1) % HAIR.length];
    const map = { k: C.k, 1: skin[0], 2: skin[1], 3: hair, 4: shade(hair, .75), 5: shirt, 6: shade(shirt, .75),
                  7: PANTS[k % PANTS.length], 8: '#3a2a20' };
    const c = document.createElement('canvas'); c.width = 12 * 3; c.height = 16 * 3;
    const g = c.getContext('2d');
    ['down', 'up', 'side'].forEach((dir, d) => [0, 1, 2].forEach(f => {
      const rows = [...HEAD[dir], ...BODY[dir === 'side' ? 'side' : 'front'], ...LEGS[dir === 'side' ? 'side' : 'front'][f]];
      const bob = f ? 1 : 0;
      rows.forEach((row, y) => [...row].forEach((ch, x) => {
        if (ch === '.') return;
        const yy = y < 13 ? y + bob : y;   // body bobs while walking, feet stay
        if (yy < 16) P(g, f * 12 + x, d * 16 + yy, map[ch]);
      }));
    }));
    return c;
  }

  function init(header, colors) {
    if (window.Sprites && !Sprites.ok) {   // paint with code art now, repaint once the sprite atlas is decoded
      if (!pendingInit) Sprites.onReady(() => pendingInit && init(...pendingInit));
      pendingInit = [header, colors];
    } else pendingInit = null;
    hdr = header; names = header.config.agents.map(a => a.name); color = colors; genLay = (header.config.map || {}).layout || null;
    campLay = genLay && (header.config.map || {}).camp ? genLay : null; campSig = null;
    if (campLay) genLay = campLayout({}, false);   // camp start: the empty valley until the first tick says more
    buildLayout(); campAnchors();
    if (window.MapLayer) MapLayer.init({ layout, C, T, R, P, blob, tree, bush, rock, rnd });
    // «С нуля» (construction on): houses and buildings come from the log, drawn by viewer/buildlayer.js
    built = !!(window.BuildLayer && BuildLayer.init({ layout, C, T, R, P, blob, rnd }, header)); bare = built && BuildLayer.empty(header);
    if (window.PlotLayer) PlotLayer.init({ layout, C, T, R, P, blob, rnd, fence, houseSprite, built });
    paintBackground();
    buf = document.createElement('canvas'); buf.width = W; buf.height = H; b = buf.getContext('2d');
    looks = pickLooks(header.config.agents);
    sheets = {}; names.forEach((n, k) => sheets[n] = sheetFor(n, k));
    return { width: W * S, height: H * S };
  }

  // ---------- camp start (aivillage/settle.py): the map grows with the village ----------
  // The header's layout has free house sites (kind homesite) and every road there could be. Shown is only what
  // the villagers made: a site becomes home_<Name> once taken (view.settle.homes), a road shows as a footpath once
  // walked and as a road from settle.road_at walks (view.settle.trails), the square is paved once something
  // stands on it. Until they settle, villagers sleep in a ring around the camp. When that picture changes, the
  // layout is rebuilt and the background repainted (rare: a few times a day at most).
  let campLay = null, campSig = null;
  function campLayout(st, paved) {
    const lay = { ...campLay, places: {}, routes: [] }, owner = {}, tr = st.trails || {};
    const roadAt = ((hdr.config.settle || {}).road_at) || 12;
    for (const [n, sid] of Object.entries(st.homes || {})) owner[sid] = n;
    for (const [id, pl] of Object.entries(campLay.places)) {
      if (pl.kind !== 'homesite') lay.places[id] = id === 'square' && !paved ? { ...pl, bare: true } : pl;
      else if (owner[id]) lay.places['home_' + owner[id]] = { kind: 'home', box: pl.box, anchor: pl.anchor, plot: pl.plot, owner: owner[id] };
    }
    const id = x => owner[x] ? 'home_' + owner[x] : x, passed = new Set();
    for (const r of campLay.routes) {
      const a = id(r.a), b = id(r.b), n = tr[[a, b].sort().join('|')] || 0;
      if (n) { lay.routes.push({ ...r, a, b, trail: n < roadAt }); passed.add(a); passed.add(b); }
    }
    for (const [pid, pl] of Object.entries(lay.places))   // a signpost stands where a path runs
      if (pl.kind === 'waypoint' && !passed.has(pid)) lay.places[pid] = { ...pl, hidden: true };
    lay.campers = st.camp || names.slice();
    return lay;
  }
  // Bedrolls of those without a house site, in a ring around the camp fire.
  function campAnchors() {
    if (!campLay) return;
    const [cx, cy] = layout.anchors[(hdr.config.settle || {}).camp || 'square'] || [W / 2, H / 2], n = names.length;
    layout.bedrolls = [];
    names.forEach((nm, k) => {
      const a = Math.PI * 2 * k / n, at = [Math.round(cx + Math.cos(a) * 46), Math.round(cy + 6 + Math.sin(a) * 30)];
      if (!genLay.campers.includes(nm)) return;
      layout.anchors['home_' + nm] = at; layout.bedrolls.push(at);
    });
    layout.campfire = genLay.places.square && genLay.places.square.bare ? [cx, cy + 6] : null;
  }
  function campUpdate(t) {
    const st = t.view.settle; if (!campLay || !st) return;
    const paved = (t.view.buildings || []).some(b => b.location === ((hdr.config.settle || {}).camp || 'square') && b.kind !== 'campfire');
    const roadAt = ((hdr.config.settle || {}).road_at) || 12;
    const sig = JSON.stringify([st.homes, Object.entries(st.trails || {}).map(([k, n]) => k + (n < roadAt ? ':t' : ':r')).sort(), paved]);
    if (sig === campSig) return;
    campSig = sig; genLay = campLayout(st, paved); buildLayout(); campAnchors();
    if (window.MapLayer) MapLayer.init({ layout, C, T, R, P, blob, tree, bush, rock, rnd });
    if (built) BuildLayer.relayout(layout);
    if (window.PlotLayer) PlotLayer.init({ layout, C, T, R, P, blob, rnd, fence, houseSprite, built });
    paintBackground();
  }

  // Standing spots around a location so several villagers don't overlap.
  function spot(loc, k) {
    const ring = [[0, 0], [-13, 3], [13, 3], [-7, -9], [7, -9], [0, 11], [-20, -4], [20, -4], [-14, 13], [14, 13],
                  [-24, 8], [24, 8], [0, -16], [-28, -10], [28, -10], [-20, 18], [20, 18], [0, 22], [-30, 2], [30, 2]];
    const [x, y] = layout.anchors[loc] || layout.anchors.square, [dx, dy] = ring[Math.max(0, k) % ring.length];   // k = -1: not active in that tick (hospital)
    const at = [x + Math.round(dx * 1.8), y + Math.round(dy * 1.2)];
    return window.Depth ? Depth.free(...at) : at;   // not inside a trunk or a well
  }
  function here(view, name) {
    const loc = view.agents[name].location;
    return names.filter(n => view.agents[n].location === loc && view.agents[n].status === 'active').indexOf(name);
  }
  function route(a, b) {
    if (layout.routes[a + '|' + b]) return layout.routes[a + '|' + b].slice(1, -1);
    if (layout.routes[b + '|' + a]) return layout.routes[b + '|' + a].slice(1, -1).reverse();
    return [];
  }
  // Position along the walking route between the previous and the current location.
  // Villagers walk at a steady pace (WALK map pixels per second on screen): a short walk ends early in the hour and
  // they get to work; a leg of a longer trip (t._goal says they walk on next hour) fills the whole hour, so the walk
  // flows into the next leg instead of stopping at a crossroads.
  const WALK = 34, ease = u => u * u * (3 - 2 * u);
  function agentAt(prev, t, name, e, hourSec = 2) {
    const hop = (t._hop || {})[name], bLoc = t.view.agents[name].location;
    const a = hop ? hop.from : prev.view.agents[name].location;
    const p1 = spot(bLoc, here(t.view, name));
    if (a === bLoc) return { x: p1[0], y: p1[1], moving: false, dir: 'down' };   // a shifted spot is smoothed, not walked
    const p0 = spot(a, hop ? hop.fk : here(prev.view, name));
    const pts = [p0, ...route(a, bLoc), p1];
    const seg = pts.slice(1).map((p, j) => Math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]));
    const total = seg.reduce((s, v) => s + v, 0), onward = (t._goal || {})[name];
    const of = hop ? hop.of : 1, P = hop ? (hop.k + e) / of : e;   // progress over the whole hop
    const cont = hop && hop.k ? false : (prev._goal || {})[name];
    let f = P;
    if (!onward) {
      const span = Math.min(1, Math.max(.15 / of, total / WALK / Math.max(.1, hourSec * of))), u = Math.min(1, P / span);
      f = cont ? u : ease(u);   // a trip's last leg keeps the pace it arrived with; a short walk eases in and out
    }
    let d = total * f;
    for (let j = 0; j < seg.length; j++) {
      if (d <= seg[j] || j === seg.length - 1) {
        const k = seg[j] ? Math.min(1, d / seg[j]) : 1, [x0, y0] = pts[j], [x1, y1] = pts[j + 1];
        const dx = x1 - x0, dy = y1 - y0, moving = seg[j] > 0 && f < 1;
        return { x: x0 + dx * k, y: y0 + dy * k, moving, dir: !moving ? 'down' : Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : dy > 0 ? 'down' : 'up' };
      }
      d -= seg[j];
    }
    return { x: p1[0], y: p1[1], moving: false, dir: 'down' };
  }

  function darkness(h) {
    if (h < 5) return .55; if (h < 7) return .55 - (h - 5) * .25; if (h < 18) return 0;
    if (h < 22) return (h - 18) * .12; return .5;
  }

  // ---------- per-frame drawing ----------
  function draw(ctx, { t, prev, frac, selected, time, tr, hourSec }) {
    const e = Math.min(1, frac), sec = time / 1000, SL = window.SeasonLayer;
    day = t.view.day; campUpdate(t);
    b.drawImage(SL ? SL.ground(bg, hdr, t.view.day) : bg, 0, 0);   // autumn / winter colours (viewer/seasonlayer.js)
    // water shimmer
    for (const [x, y] of layout.shimmer) {
      const ph = (sec * .8 + rnd(x, y) * 6) % 6; if (ph > 1.2) continue;
      R(b, x + (ph * 3 | 0), y, 3, 1, C.waterL);
    }
    if (window.Depth) Depth.begin('live');
    if (window.MapLayer) MapLayer.draw(b, t, e, sec);
    if (window.PlotLayer) PlotLayer.draw(b, t, e, sec);
    if (built) BuildLayer.draw(b, t, e, sec);
    if (window.Depth) Depth.end();
    if (SL) SL.tint(b, hdr, t.view.day, W, H);
    const fires = new Set(t.view.fires || []);
    const homeNow = new Set(names.filter(n => t.view.agents[n].location === 'home_' + n && t.view.agents[n].status === 'active'));
    // chimney smoke
    const smoke = (x, y, k) => { for (let i = 0; i < 4; i++) { const p = (sec * .5 + i / 4 + k) % 1;
      const r = 1 + p * 3, sx = x + Math.sin((p + k) * 6) * 3, sy = y - p * 18;
      b.globalAlpha = .5 * (1 - p); blob(b, sx, sy, r, r, ['#e8e8ee', '#d0d0d8', '#b8b8c4'], null); b.globalAlpha = 1; } };
    if (layout.smithyChimney) smoke(...layout.smithyChimney, .3);
    layout.houses.forEach((h, k) => { if (homeNow.has(h.name) && h.chimney) smoke(...h.chimney, k * .37); });
    // fire, before villagers so buckets of water land on top of it (the map layer sizes it by the water still needed)
    if (window.MapLayer) MapLayer.drawTop(b, t, e, sec);
    else for (const id of fires) {
      const bx = layout.box[id]; if (!bx) continue;
      const [x0, y0, w, h] = bx;
      for (let i = 0; i < 26; i++) {
        const p = (sec * 1.6 + rnd(i, 3)) % 1, fx = x0 + 4 + rnd(i, 1) * (w - 8), fy = y0 + h * (.25 + rnd(i, 2) * .7) - p * 20;
        const r = (1 - p) * 6 + 1.5;
        blob(b, fx, fy, r, r * 1.4, ['#ffe066', '#ff9f1c', '#e4572e'], null);
      }
      for (let i = 0; i < 4; i++) { const p = (sec * .6 + i / 4) % 1;
        b.globalAlpha = .45 * (1 - p); blob(b, x0 + w / 2 + Math.sin(p * 8 + i) * 6, y0 - p * 26, 3 + p * 5, 3 + p * 5, ['#555', '#444', '#333'], null); b.globalAlpha = 1; }
    }
    // villagers, back to front (poses, tools, idle strolls and bubbles live in viewer/actors.js)
    const dt = lastTime === null ? 0 : Math.min(.1, Math.max(0, (time - lastTime) / 1000)); lastTime = time;
    const acts = t._acts || Actors.activities(t), prevPos = lastPos, shown = [];
    names.forEach((n, idx) => {
      const v = t.view.agents[n]; if (v.status !== 'active') return;
      const r = agentAt(prev, t, n, e, hourSec), info = v.asleep ? { act: 'sleep', text: '' } : acts[n] || { act: 'idle', text: '' };
      if (v.asleep && v.location === 'home_' + n && !r.moving) return;
      const k = here(t.view, n), a = { n, k: idx, loc: v.location, text: info.text, act: r.moving ? 'walk' : info.act === 'walk' ? 'idle' : info.act,
        dir: r.dir, moving: r.moving, carry: r.moving && fires.size > 0 && (v.inventory.water || 0) > 0 };
      let tx = r.x, ty = r.y;
      if (!r.moving) {
        const ws = Actors.workSpot(a.act, v.location, k, layout, info);
        if (ws) [tx, ty, a.dir, a.real] = ws;
        else if (a.act === 'idle') { const w = Actors.wander(idx + 1, sec); tx += w.dx; ty += w.dy; a.dir = w.dir; a.moving = w.moving; }
        const other = info.to && prevPos[info.to];
        if (a.act === 'talk' && other && Math.abs(other[0] - tx) > 2) a.dir = other[0] > tx ? 'right' : 'left';
        if (a.act === 'pour' && layout.box[v.location]) { const [x0, y0, w, h] = layout.box[v.location]; a.target = [x0 + w / 2 + (k % 3 - 1) * 10, y0 + h * .45]; }
      }
      const p = Actors.place(n, t.tick, { x: tx, y: ty }, r.moving, dt);
      if (p.sliding && !a.moving) { a.moving = true; a.dir = p.sdir; }
      shown.push(Object.assign(a, { x: p.x, y: p.y }));
    });
    shown.sort((p, q) => p.y - q.y);
    lastPos = {};
    for (const a of shown) lastPos[a.n] = [Math.round(a.x), Math.round(a.y) - 8];
    const one = a => { Actors.paint(b, sheets[a.n], a, sec, a.n === selected);
      if (built) BuildLayer.gear(b, a, t.view.agents[a.n].inventory); };   // «С нуля»: weapon and armor carried
    if (window.AnimalLayer) AnimalLayer.draw(b, t, layout, sec);   // hares, ducks, deer, boars, elk (animals.py)
    if (window.Depth) Depth.paint(b, shown, one); else shown.forEach(one);   // trees and houses in front cover them
    if (window.ThreatLayer) ThreatLayer.draw(b, t, layout, sec);   // bandits, beast, traveler, warned targets
    if (window.Fog) Fog.draw(b, t, layout, sec);   // places nobody has explored yet (viewer/fog.js)
    if (window.Omens) Omens.draw(b, t, layout, n => lastPos[n] && [lastPos[n][0], lastPos[n][1] + 8], sec);   // god actions on their way
    if (SL) SL.weather(b, hdr, t.view.day, sec, W, H);   // snowflakes, falling leaves
    // night
    const h0 = prev.view.hour + (prev.view.minute || 0) / 60, h1 = t.view.hour + (t.view.minute || 0) / 60;
    const hour = h1 > h0 && h1 - h0 <= 1 ? h0 + e * (h1 - h0) : h0, dark = darkness(hour);
    if (dark > 0) {
      b.fillStyle = `rgba(16,20,56,${dark})`; b.fillRect(0, 0, W, H);
      b.globalCompositeOperation = 'lighter';
      const glow = (x, y, r, a) => { const gr = b.createRadialGradient(x, y, 0, x, y, r);
        gr.addColorStop(0, `rgba(255,190,90,${a})`); gr.addColorStop(1, 'rgba(255,190,90,0)'); b.fillStyle = gr; b.fillRect(x - r, y - r, 2 * r, 2 * r); };
      layout.lamps.forEach(([x, y]) => glow(x + 1, y - 15, 22, dark * .9));
      if (layout.forge) glow(...layout.forge, 26, dark);
      layout.houses.forEach(h => { if (homeNow.has(h.name) && h.windows) h.windows.forEach(([x, y]) => glow(x + 4, y + 4, 12, dark)); });
      for (const id of fires) { const [x0, y0, w, hh] = layout.box[id] || [0, 0, 0, 0]; glow(x0 + w / 2, y0 + hh / 2, 48, .8); }
      b.globalCompositeOperation = 'source-over';
      layout.houses.forEach(h => { if (homeNow.has(h.name) && h.windows && !built) h.windows.forEach(([x, y]) => R(b, x + 1, y + 1, 7, 6, C.lit)); });
    }
    Camera.attach(ctx.canvas, W, H, S);
    const posOf = n => lastPos[n] && [lastPos[n][0], lastPos[n][1] + 8];
    Camera.direct(dt, t, posOf, loc => layout.anchors[loc], tr || String);
    Camera.update(dt, selected, posOf);
    const cam = Camera.view();
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(buf, cam.x0, cam.y0, W / cam.z, H / cam.z, 0, 0, W * S, H * S);
    labels(ctx, t, shown, selected, sec);
    Actors.noteTick(t, frac, dt);
    const heads = shown.map(a => { const [sx, sy] = Camera.toScreen(a.x, a.y + 8 - ((sheets[a.n] || {}).fh || 16)); return { n: a.n, sx, sy }; });
    // Bubbles and icons grow with the zoom too, but less than the map (x1 at the whole village, up to x1.7).
    const k = Math.max(1, Math.min(1.7, Math.pow(cam.z, .45))), hk = heads.map(h => ({ n: h.n, sx: h.sx / k, sy: h.sy / k }));
    ctx.save(); ctx.scale(k, k);
    Actors.badges(ctx, hk, t);
    Actors.bubbles(ctx, hk, selected, tr || String, W * S / k, Camera.focus && Camera.focus());
    ctx.restore();
    if (built) BuildLayer.banner(ctx, t, time);   // «Новая стадия» banner (village_stage)
  }

  // ---------- full-resolution text (placed through the camera, constant size at any zoom) ----------
  function plaque(ctx, x, y, text) {
    ctx.font = '600 12px system-ui, sans-serif'; const w = ctx.measureText(text).width + 12;
    ctx.fillStyle = '#3a2416'; ctx.fillRect(x - w / 2 - 2, y - 10, w + 4, 20);
    ctx.fillStyle = '#8a5a35'; ctx.fillRect(x - w / 2, y - 8, w, 16);
    ctx.fillStyle = '#fbefd5'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, x, y + 1);
  }
  function labels(ctx, t, shown, selected, sec) {
    const at = Camera.toScreen, z = Camera.view().z;
    const top = { market: -34, field: -44, river: -40, square: -38, forest: -26, mine: -58, smithy: -82 };
    for (const [id, dy] of [...Object.entries(top), ...(layout.labels || [])]) {
      if (!layout.anchors[id]) continue;  // e.g. no common field on newer maps
      if (bare && (id === 'smithy' || (id === 'market' && !BuildLayer.standing(t, 'market_square')))) continue;   // not built yet
      const [x, y] = layout.anchors[id]; plaque(ctx, ...at(x, y + dy), window.Fog && Fog.hidden(t, id) ? '?' : t.view.locations[id] || id);
    }
    for (const h of layout.houses) {
      const v = t.view.agents[h.name], asleepHome = v.asleep && v.location === 'home_' + h.name && !shown.some(a => a.n === h.name);
      if (asleepHome) { ctx.font = `700 ${Math.round(14 * Math.sqrt(z))}px system-ui`; ctx.fillStyle = '#e8efe9'; ctx.textAlign = 'center';
        const p = (sec * .7) % 1, [zx, zy] = at(h.x + 24, h.y + 8), [Zx, Zy] = at(h.x + 30, h.y + 2); ctx.globalAlpha = 1 - p;
        ctx.fillText('z', zx + p * 10, zy - p * 20); ctx.fillText('Z', Zx + p * 12, Zy - p * 24); ctx.globalAlpha = 1; }
      const [nx, ny] = at(h.x + 24, h.y + 50);
      ctx.font = '600 11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(20,16,12,.75)'; const w = ctx.measureText(h.name).width + 10;
      ctx.fillRect(nx - w / 2, ny - 1, w, 16); ctx.fillStyle = color[h.name]; ctx.fillText(h.name, nx, ny + 7);
    }
    for (const a of shown) {
      const [x, y] = at(a.x, a.y + 8);
      ctx.font = '600 11px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      const w = ctx.measureText(a.n).width + 8;
      ctx.fillStyle = a.n === selected ? 'rgba(242,193,78,.95)' : 'rgba(20,16,12,.7)'; ctx.fillRect(x - w / 2, y + 2, w, 14);
      ctx.fillStyle = a.n === selected ? '#1b1b24' : '#fff'; ctx.fillText(a.n, x, y + 9);
      if (a.act === 'sleep') { ctx.fillStyle = '#e8efe9'; ctx.fillText('z z', x + 16, y - 46); }
    }
  }

  // Name of the villager under a point in canvas pixels, or null.
  function pick(cx, cy) {
    const [wx, wy] = Camera.toWorld(cx, cy);
    let best = null, bd = 12;
    for (const [n, [x, y]] of Object.entries(lastPos)) { const d = Math.hypot(wx - x, wy - y); if (d < bd) { bd = d; best = n; } }
    return best;
  }

  const gfx = { C, R, P, blob, rnd };
  // Where a villager was last drawn, in map pixels (head height), or undefined; used by viewer/clip.js.
  const where = n => lastPos[n];
  return { init, draw, pick, where, gfx, sheet: n => sheets[n], layout: () => layout, T };
})();
