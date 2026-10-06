// Buildings for the "from scratch" mode, drawn in code in the pixelmap.js style (16 px tiles, dark outline,
// top-left light). Every kind has levels 1..3 that differ in material, not just size:
// 1 = sticks, wattle, thatch and hides; 2 = logs and planks, shingles, shutters; 3 = stone, brick, tiles, glass.
// Plus the building site (stakes -> frame -> walls in scaffolding). Not wired into the map yet (task 13b).
// API: BuildArt.draw(g, kind, level, x, y) paints into a 2D context with (x, y) the top-left of the kind's box;
// BuildArt.site(g, w, h, stage, x, y); BuildArt.KINDS[kind] = {name, size: [w, h], levels, group}.
const BuildArt = (() => {
  const C = {
    k: '#1b1b24', wood: '#8a5a35', woodD: '#6b4226', woodL: '#a8743f', woodLL: '#c08850', end: '#d9b880',
    stone: '#9a9aa2', stoneD: '#6f6f78', stoneL: '#c4c4cc', plaster: '#e8d4a8', plasterD: '#cbb488',
    beam: '#5e3f24', straw: '#d8b46a', strawL: '#ecd08a', strawD: '#a8843e', hide: '#c8a070', hideD: '#9a7448',
    hideL: '#e0c090', brick: '#b8543a', brickL: '#d0704a', brickD: '#8f3a28', mortar: '#d8c8b0', glass: '#6fb3d9',
    glassL: '#d8f0ff', dark: '#2a1a14', iron: '#5d5d6b', ironL: '#9aa2b0', fire: '#ff7b1c', fireL: '#ffd23f',
    grass: '#5a9a3c', grassD: '#4b8a35', soil: '#7a5532', soilD: '#5e3f24', water: '#3f7fbf', waterD: '#2f6299',
    waterL: '#a8d4f0', leaf: '#2f7a3a', leafL: '#4a9a48', sprout: '#7ab648', wheat: '#e0c040', mud: '#a88458',
    mudD: '#86643c', mudL: '#c4a070', red: '#b8483a', redD: '#8f3328', redL: '#d46a4f', smoke: '#d8d8e0',
  };
  const TILE = [['#c8643c', '#9a4426', '#e08a5a']];
  const ROOF = { red: ['#b8483a', '#8f3328', '#d46a4f'], blue: ['#3f6fa8', '#2d5280', '#5a8cc4'],
    green: ['#5c8a3a', '#43692a', '#7aa852'], brown: ['#7a5a3a', '#5a4028', '#9a7650'],
    slate: ['#5d6070', '#44464f', '#7c8090'], purple: ['#8a5aa8', '#684382', '#a77cc4'] };

  function rnd(x, y, s = 0) {
    let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(s | 0, 1442695041);
    h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  const R = (g, x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x | 0, y | 0, w, h); };
  const P = (g, x, y, c) => R(g, x, y, 1, 1, c);
  const box = (g, x, y, w, h, c) => { R(g, x, y, w, h, C.k); R(g, x + 1, y + 1, w - 2, h - 2, c); };
  const shadow = (g, x, y, w) => R(g, x + 2, y, w - 2, 2, 'rgba(0,0,0,.22)');
  function line(g, x0, y0, x1, y1, c) {
    const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) || 1;
    for (let i = 0; i <= n; i++) P(g, Math.round(x0 + (x1 - x0) * i / n), Math.round(y0 + (y1 - y0) * i / n), c);
  }
  function disc(g, cx, cy, r, c, outline = C.k) {
    for (let y = -r; y <= r; y++) for (let x = -r; x <= r; x++) {
      const d = (x + .5 - .5) ** 2 + (y) ** 2;
      if (d <= r * r) P(g, cx + x, cy + y, d > (r - 1) * (r - 1) && outline ? outline : c);
    }
  }

  // ---------- surfaces: a colour for each pixel (i, j) of a w x h area ----------
  const WALL = {
    wattle: (i, j) => i % 4 === 0 ? C.woodD : ((i >> 2) + (j >> 1)) % 2 ? C.woodL : j % 2 ? C.wood : C.strawD,
    mud: (i, j) => rnd(i >> 1, j >> 1, 3) < .2 ? C.mudD : rnd(i, j, 4) < .12 ? C.mudL : C.mud,
    log: (i, j, w) => { const r = j % 4;
      if (i < 2 || i > w - 3) return r === 3 ? C.woodD : r === 0 ? C.wood : C.end;
      return r === 0 ? C.woodLL : r === 3 ? C.woodD : rnd(i >> 2, j >> 2, 5) < .08 ? C.woodD : C.wood; },
    plank: (i, j, w, h) => i % 5 === 0 ? C.woodD : i % 5 === 1 ? C.woodL : (j === 2 || j === h - 3) && i % 5 === 3 ? C.k : C.wood,
    plankH: (i, j) => j % 4 === 3 ? C.woodD : j % 4 === 0 ? C.woodLL : (i + (j >> 2) * 7) % 13 === 0 ? C.woodD : C.wood,
    plaster: (i, j, w, h) => i < 2 || i > w - 3 || j < 2 || j === (h >> 1) || j === (h >> 1) + 1 || (i % 14 === 0)
      ? C.beam : rnd(i, j, 6) < .1 ? C.plasterD : C.plaster,
    stone: (i, j) => { const r = (j / 5) | 0;
      return j % 5 === 4 || (i + r * 5) % 9 === 0 ? C.stoneD : rnd((i + r * 5) / 9 | 0, r, 7) < .45 ? C.stoneL : C.stone; },
    brick: (i, j) => j % 3 === 2 || (i + ((j / 3 | 0) % 2) * 3) % 6 === 0 ? C.mortar : j % 3 === 0 ? C.brickL
      : rnd((i + ((j / 3 | 0) % 2) * 3) / 6 | 0, j / 3 | 0, 8) < .25 ? C.brickD : C.brick,
  };
  function wall(g, x, y, w, h, mat) {
    R(g, x, y, w, h, C.k);
    const f = WALL[mat];
    for (let j = 1; j < h - 1; j++) for (let i = 1; i < w - 1; i++) P(g, x + i, y + j, f(i - 1, j - 1, w - 2, h - 2));
  }
  // Roof seen from the front: a trapezoid, the top `ins` px narrower on each side, 1 px eaves overhang.
  function roof(g, x, y, w, h, mat, col = ROOF.red, ins = 6) {
    const [m, d, l] = mat === 'thatch' ? [C.straw, C.strawD, C.strawL] : mat === 'hide' ? [C.hide, C.hideD, C.hideL]
      : mat === 'tile' ? TILE[0] : col;
    for (let r = 0; r < h; r++) {
      const inset = Math.round(ins * (1 - r / (h - 1))) - 1, xx = x + inset, ww = w - 2 * inset;
      R(g, xx, y + r, ww, 1, C.k);
      if (r === 0 || r === h - 1) continue;
      for (let i = 1; i < ww - 1; i++) {
        let c = m; const a = xx + i - x;
        if (mat === 'thatch') c = r === h - 2 && (a % 3 === 0) ? C.strawD : (a + (r >> 1)) % 5 === 0 ? C.strawD
          : rnd(a, r >> 1, 9) < .3 ? C.strawL : r % 6 === 5 ? C.strawD : m;
        else if (mat === 'hide') c = a % 9 === 0 ? (r % 2 ? C.hideD : C.k) : r < 3 ? l : rnd(a >> 2, r >> 2, 2) < .2 ? d : m;
        else if (mat === 'tile') { const rr = (r - 1) % 3, off = ((r - 1) / 3 | 0) % 2 * 2;
          c = rr === 2 ? d : (a + off) % 4 === 0 ? d : rr === 0 && (a + off) % 4 === 2 ? l : m; }
        else { const rr = r % 4, off = (r >> 2) % 2 * 3;   // shingles / slate
          c = rr === 0 ? d : (a + off) % 6 === 0 ? d : r < 3 ? l : m; }
        P(g, xx + i, y + r, c);
      }
    }
  }
  // Ragged thatch fringe under a thatch roof
  function fringe(g, x, y, w) { for (let i = 0; i < w; i++) if (i % 3 !== 1) P(g, x + i, y, i % 3 ? C.strawD : C.k); }

  // ---------- details ----------
  function door(g, x, y, w, h, kind) {
    if (kind === 'hole') { R(g, x, y + 2, w, h - 2, C.k); R(g, x + 1, y, w - 2, 2, C.k); R(g, x + 1, y + 2, w - 2, h - 2, C.dark); return; }
    if (kind === 'curtain') { box(g, x, y, w, h, C.hide); line(g, x + 1, y + 1, x + w - 2, y + h - 2, C.hideD);
      R(g, x - 1, y - 1, w + 2, 2, C.woodD); return; }
    if (kind === 'arch') {
      R(g, x - 2, y + 1, w + 4, h - 1, C.k); R(g, x - 1, y, w + 2, 1, C.k);
      R(g, x - 1, y + 1, w + 2, h - 1, C.stoneL); R(g, x, y + 2, w, h - 2, C.k);
      R(g, x + 1, y + 3, w - 2, h - 3, C.wood);
      for (let i = x + 3; i < x + w - 1; i += 3) R(g, i, y + 3, 1, h - 3, C.woodD);
      R(g, x + 1, y + 5, w - 2, 1, C.iron); R(g, x + 1, y + h - 4, w - 2, 1, C.iron); P(g, x + w - 3, y + (h >> 1) + 1, C.fireL);
      return; }
    box(g, x, y, w, h, C.wood); R(g, x + 1, y + 1, 1, h - 2, C.woodL);
    for (let i = x + 3; i < x + w - 1; i += 3) R(g, i, y + 1, 1, h - 2, C.woodD);
    P(g, x + w - 3, y + (h >> 1), C.wheat);
  }
  function win(g, x, y, kind) {
    if (kind === 'hole') { R(g, x, y, 5, 4, C.k); R(g, x + 1, y + 1, 3, 2, C.dark); return; }
    if (kind === 'shutter') { box(g, x, y, 9, 7, '#3a4a5a'); R(g, x + 3, y + 1, 1, 5, C.k);
      R(g, x - 2, y, 3, 7, C.k); R(g, x - 1, y + 1, 1, 5, C.woodL); R(g, x + 8, y, 3, 7, C.k); R(g, x + 9, y + 1, 1, 5, C.woodL);
      P(g, x + 1, y + 1, '#5a7a9a'); return; }
    box(g, x, y, 9, 8, C.glass); R(g, x + 4, y + 1, 1, 6, C.k); R(g, x + 1, y + 4, 7, 1, C.k);
    P(g, x + 2, y + 2, C.glassL); P(g, x + 6, y + 2, C.glassL);
    R(g, x - 1, y + 8, 11, 3, C.k); R(g, x, y + 9, 9, 1, C.woodD);
    for (let i = 0; i < 4; i++) P(g, x + 1 + i * 2, y + 8, ['#e04a6a', '#ffd23f', '#e04a6a', '#f2f2f2'][i]);
  }
  function chimney(g, x, y, h, mat = 'stone') {
    R(g, x, y, 7, h, C.k);
    for (let j = 1; j < h; j++) for (let i = 1; i < 6; i++) P(g, x + i, y + j, mat === 'brick' ? WALL.brick(i, j) : WALL.stone(i + 3, j));
    R(g, x - 1, y, 9, 2, C.k); R(g, x, y, 7, 1, mat === 'brick' ? C.brickL : C.stoneL);
  }
  function smoke(g, x, y, n = 3) {
    for (let i = 0; i < n; i++) disc(g, x + (i % 2 ? 2 : -1), y - i * 5, 2 + (i >> 1), i ? '#e8e8f0' : C.smoke, null);
  }
  function fire(g, x, y, s = 1) {   // x, y = bottom centre
    R(g, x - 3 * s, y - 3 * s, 6 * s, 3 * s, C.fire); R(g, x - 2 * s, y - 6 * s, 4 * s, 4 * s, C.fire);
    R(g, x - 1 * s, y - 8 * s, 2 * s, 3 * s, C.fire); R(g, x - 1 * s, y - 5 * s, 2 * s, 4 * s, C.fireL);
    P(g, x - 3 * s, y - 5 * s, C.fireL); P(g, x + 2 * s, y - 6 * s, C.fire);
  }
  function lantern(g, x, y) { R(g, x, y, 1, 2, C.k); box(g, x - 2, y + 2, 5, 5, C.fireL); P(g, x, y + 4, '#fff6c0'); }
  function banner(g, x, y, c = C.red, h = 10) {
    R(g, x, y - 2, 1, h + 6, C.k); R(g, x + 1, y, 6, h, C.k); R(g, x + 2, y + 1, 4, h - 2, c);
    P(g, x + 3, y + h - 1, c); P(g, x + 4, y + h - 1, c); P(g, x + 2, y + h - 1, C.k); P(g, x + 5, y + h - 1, C.k); P(g, x + 3, y + 3, C.fireL);
  }
  function sign(g, x, y, draw) { R(g, x + 3, y - 3, 1, 3, C.k); R(g, x + 8, y - 3, 1, 3, C.k); box(g, x, y, 12, 9, C.woodL);
    R(g, x + 1, y + 7, 10, 1, C.woodD); draw(g, x + 6, y + 4); }
  function barrel(g, x, y) { box(g, x, y, 7, 9, C.wood); R(g, x + 1, y + 2, 5, 1, C.iron); R(g, x + 1, y + 6, 5, 1, C.iron);
    R(g, x + 2, y + 1, 1, 7, C.woodL); }
  function crate(g, x, y, s = 8) { box(g, x, y, s, s, C.woodL); line(g, x + 1, y + 1, x + s - 2, y + s - 2, C.woodD);
    R(g, x + 1, y + 1, s - 2, 1, C.woodLL); }
  function sack(g, x, y, c = '#d8c8a0') { R(g, x + 1, y, 4, 2, C.k); box(g, x, y + 2, 6, 7, c); P(g, x + 2, y + 1, '#a08a60');
    R(g, x + 1, y + 7, 4, 1, '#b8a880'); }
  function logs(g, x, y, n = 3) {   // a small pile of logs seen end-on
    const pos = [[0, 4], [5, 4], [10, 4], [2, 0], [7, 0], [4, -4]].slice(0, n);
    for (const [dx, dy] of pos) { disc(g, x + dx + 2, y + dy + 2, 2, C.end); P(g, x + dx + 2, y + dy + 2, C.woodL); }
  }
  function stones(g, x, y, n = 3) {
    const pos = [[0, 3], [5, 3], [10, 3], [3, 0], [8, 0]].slice(0, n);
    for (const [dx, dy] of pos) { box(g, x + dx, y + dy, 5, 4, C.stone); P(g, x + dx + 1, y + dy + 1, C.stoneL); }
  }
  function fenceRow(g, x, y, w, kind) {   // y = bottom
    if (kind === 'stick') { for (let i = 0; i < w; i += 3) { const h = 6 + ((i * 7) % 3); R(g, x + i, y - h, 2, h, C.k); P(g, x + i, y - h + 1, C.woodL);
        R(g, x + i, y - h + 2, 1, h - 3, C.wood); }
      line(g, x, y - 4, x + w - 1, y - 4, C.strawD); return; }
    if (kind === 'stone') { for (let i = 0; i < w; i += 5) { box(g, x + i, y - 6, 6, 4, C.stone); box(g, x + i + 2, y - 3, 6, 3, C.stoneL); }
      return; }
    R(g, x, y - 8, w, 2, C.k); R(g, x, y - 4, w, 2, C.k); R(g, x, y - 7, w, 1, C.woodL); R(g, x, y - 3, w, 1, C.woodL);
    for (let i = 0; i < w; i += 8) { R(g, x + i, y - 10, 3, 10, C.k); R(g, x + i + 1, y - 9, 1, 8, C.woodL); }
  }
  function hay(g, x, y, w = 12, h = 8) {
    for (let j = 0; j < h; j++) { const ins = Math.round((h - j) * w / (3 * h)) * (j < h / 2 ? 1 : 0);
      R(g, x + ins, y + j, w - 2 * ins, 1, C.k);
      if (j && j < h - 1) for (let i = ins + 1; i < w - ins - 1; i++) P(g, x + i, y + j, (i + j) % 4 === 0 ? C.strawD : rnd(i, j) < .3 ? C.strawL : C.straw); }
  }
  function water(g, x, y, w, h) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++)
      P(g, x + i, y + j, (i + 2 * j) % 11 === 0 ? C.waterL : j < 1 ? C.waterD : C.water);
  }

  // A plain house body with a roof: walls `mat`, roof `rmat`, sized w x (wall height wh + roof height rh).
  // x, y = top-left of the roof. Returns the wall's top y.
  function hut(g, x, y, w, wh, rh, mat, rmat, col, ins = 6) {
    const wy = y + rh - 2;
    shadow(g, x + 1, wy + wh, w);
    wall(g, x + 2, wy, w - 4, wh, mat);
    roof(g, x, y, w, rh, rmat, col, ins);
    if (rmat === 'thatch') fringe(g, x, y + rh - 1, w);
    return wy;
  }
  // A two-storey shell for level 3: stone ground floor, plaster or brick upper floor, tile roof.
  function hall(g, x, y, w, h1, h2, rh, upper = 'plaster', col, ins = 7) {
    const top = y + rh - 2;
    shadow(g, x + 1, top + h2 + h1, w);
    wall(g, x + 2, top + h2 - 1, w - 4, h1 + 1, 'stone');
    wall(g, x + 3, top, w - 6, h2, upper);
    R(g, x + 1, top + h2 - 1, w - 2, 2, C.k); R(g, x + 2, top + h2 - 1, w - 4, 1, C.beam);
    roof(g, x, y, w, rh, col ? 'shingle' : 'tile', col, ins);
    return [top, top + h2 + 1];
  }

  // ---------- the catalog ----------
  // draw(g, level, W, H): everything relative to the kind's W x H box (the canvas is translated to it).
  const K = {};
  // The box is 2 px wider than the drawing area, so roof eaves may hang 1 px over either side.
  const def = (id, name, group, [w, h], levels, draw) => { K[id] = { id, name, group, size: [w + 2, h], levels, draw }; };

  // Personal
  def('shelter', 'Шалаш', 'personal', [32, 28], 1, (g, l, W, H) => {
    // an A-frame of branches thatched with leafy boughs, a dark triangular opening
    shadow(g, 3, H - 2, 28);
    for (let j = 0; j < H - 6; j++) {
      const w = 2 + Math.round(j * 26 / (H - 7)), x = 16 - (w >> 1), y = 4 + j;
      R(g, x, y, w, 1, C.k);
      for (let i = 1; i < w - 1; i++) P(g, x + i, y, (i + j) % 5 === 0 ? C.woodD : rnd(i, j, 1) < .45 ? C.leafL : rnd(i, j, 2) < .5 ? C.leaf : '#3a8a3a');
    }
    for (let j = 0; j < 12; j++) { const w = 1 + Math.round(j * 10 / 11); R(g, 16 - (w >> 1), H - 14 + j, w, 1, j ? C.dark : C.k); }
    line(g, 13, 0, 17, 5, C.woodD); line(g, 19, 0, 15, 5, C.woodD); line(g, 12, 0, 16, 5, C.k);
  });
  def('house', 'Дом', 'personal', [56, 68], 3, (g, l, W, H) => {
    if (l === 1) {   // a mud-and-wattle cottage under thatch
      const wy = hut(g, 8, 22, 40, 22, 22, 'mud', 'thatch');
      for (let j = wy + 2; j < wy + 20; j += 6) line(g, 12, j, 13, j + 3, C.mudD);
      door(g, 23, wy + 7, 9, 15, 'curtain'); win(g, 13, wy + 7, 'hole'); win(g, 38, wy + 7, 'hole');
      return; }
    if (l === 2) {   // log cabin, shingle roof, shutters, stone chimney
      chimney(g, 38, 10, 14);
      const wy = hut(g, 4, 18, 48, 26, 24, 'log', 'shingle', ROOF.brown);
      door(g, 23, wy + 9, 10, 17, 'plank'); win(g, 9, wy + 9, 'shutter'); win(g, 38, wy + 9, 'shutter');
      R(g, 21, wy + 25, 14, 2, C.k); R(g, 22, wy + 25, 12, 1, C.stone);
      smoke(g, 41, 6, 2);
      return; }
    // two storeys: stone below, timber-framed plaster above, tiled roof, glass, lantern
    chimney(g, 41, 2, 18, 'brick');
    const [top, mid] = hall(g, 1, 4, 54, 22, 18, 22);
    win(g, 10, top + 5, 'glass'); win(g, 37, top + 5, 'glass');
    door(g, 23, mid + 6, 10, 15, 'arch'); win(g, 8, mid + 6, 'glass'); win(g, 39, mid + 6, 'glass');
    lantern(g, 36, mid + 3); R(g, 20, H - 3, 16, 2, C.k); R(g, 21, H - 3, 14, 1, C.stoneL);
    smoke(g, 44, 0, 1);
  });
  def('workshop', 'Мастерская', 'personal', [56, 56], 3, (g, l, W, H) => {
    const hammer = (g, x, y) => { R(g, x - 3, y - 2, 6, 2, C.iron); R(g, x, y, 1, 3, C.woodD); };
    if (l === 1) {   // lean-to on two posts, a stump with tools
      R(g, 10, 22, 2, 26, C.k); R(g, 44, 22, 2, 26, C.k); R(g, 10, 23, 1, 24, C.woodL); R(g, 44, 23, 1, 24, C.woodL);
      roof(g, 6, 12, 44, 12, 'thatch', 0, 3); fringe(g, 6, 23, 44); shadow(g, 6, 48, 42);
      R(g, 22, 38, 12, 10, C.k); R(g, 23, 39, 10, 2, C.end); R(g, 23, 41, 10, 6, C.wood);
      R(g, 25, 34, 2, 5, C.woodD); R(g, 23, 33, 6, 2, C.stone); logs(g, 36, 40, 3);
      return; }
    if (l === 2) {
      const wy = hut(g, 4, 10, 48, 26, 18, 'plank', 'shingle', ROOF.green);
      door(g, 30, wy + 10, 16, 16, 'plank'); R(g, 37, wy + 10, 1, 16, C.k); win(g, 10, wy + 9, 'shutter');
      sign(g, 32, wy + 1, hammer); crate(g, 1, H - 10); logs(g, 44, H - 10, 2);
      return; }
    chimney(g, 8, 0, 14, 'brick');
    const [top, mid] = hall(g, 2, 6, 52, 18, 14, 18, 'brick', ROOF.green);
    win(g, 8, top + 3, 'glass'); win(g, 39, top + 3, 'glass');
    door(g, 28, mid + 4, 18, 14, 'arch'); win(g, 9, mid + 5, 'glass'); sign(g, 22, top + 4, hammer);
    crate(g, 0, H - 10); barrel(g, 48, H - 11);
  });
  def('smokehouse', 'Коптильня', 'personal', [40, 54], 3, (g, l, W, H) => {
    const fish = (x, y) => { R(g, x, y, 1, 2, C.k); R(g, x - 1, y + 2, 3, 6, C.k); R(g, x, y + 3, 1, 4, '#c08a4a'); };
    if (l === 1) {   // a pole rack over a smouldering fire
      R(g, 6, 18, 2, 28, C.k); R(g, 32, 18, 2, 28, C.k); R(g, 4, 18, 32, 2, C.k); R(g, 5, 18, 30, 1, C.woodL);
      for (let x = 10; x < 32; x += 5) fish(x, 20);
      shadow(g, 6, 46, 28); logs(g, 14, 38, 3); fire(g, 20, 43, 1); smoke(g, 20, 30, 2);
      return; }
    if (l === 2) {
      const wy = hut(g, 4, 10, 32, 28, 14, 'plankH', 'shingle', ROOF.brown, 5);
      door(g, 14, wy + 12, 11, 16, 'plank'); smoke(g, 20, 6, 3); R(g, 16, 9, 8, 2, C.k);
      for (let x = 7; x < 34; x += 24) fish(x, wy + 3);
      logs(g, 30, H - 9, 2);
      return; }
    chimney(g, 16, 0, 14);
    const wy = hut(g, 2, 10, 36, 30, 14, 'stone', 'tile', 0, 5);
    door(g, 14, wy + 14, 12, 16, 'arch'); smoke(g, 20, 0, 2);
    for (let x = 6; x < 36; x += 24) { R(g, x - 2, wy + 4, 6, 1, C.woodD); fish(x, wy + 5); }
  });
  def('barn', 'Амбар', 'personal', [64, 62], 3, (g, l, W, H) => {
    if (l === 1) {   // a raised grain store on stilts under thatch
      for (const x of [14, 26, 38, 48]) { R(g, x, 40, 3, 18, C.k); R(g, x + 1, 41, 1, 16, C.woodL); disc(g, x + 1, 41, 3, C.stone); }
      shadow(g, 10, H - 2, 44);
      wall(g, 12, 26, 40, 14, 'wattle'); roof(g, 8, 8, 48, 20, 'thatch', 0, 8); fringe(g, 8, 27, 48);
      R(g, 28, 30, 8, 10, C.k); R(g, 29, 31, 6, 9, C.dark); line(g, 30, 41, 34, 57, C.woodD); line(g, 31, 41, 35, 57, C.woodL);
      sack(g, 4, H - 11); sack(g, 54, H - 11, '#c8b890');
      return; }
    const col = l === 2 ? ROOF.red : ROOF.slate;
    const wy = hut(g, 2, 6, 60, 32, 24, l === 2 ? 'plank' : 'stone', 'shingle', col, 12);
    if (l === 3) { R(g, 6, wy, 52, 2, C.k); }
    // big double doors with X braces
    const dx = 20, dw = 24, dy = wy + 8;
    R(g, dx - 1, dy - 1, dw + 2, 25, C.k);
    for (const x of [dx, dx + dw / 2]) { R(g, x, dy, dw / 2 - 1, 24, l === 2 ? C.redL : C.wood);
      R(g, x, dy, dw / 2 - 1, 2, '#fff2e0'); R(g, x, dy + 22, dw / 2 - 1, 2, '#fff2e0');
      line(g, x, dy + 2, x + dw / 2 - 2, dy + 21, '#fff2e0'); line(g, x + dw / 2 - 2, dy + 2, x, dy + 21, '#fff2e0'); }
    // hayloft
    R(g, 26, 12, 12, 9, C.k); R(g, 27, 13, 10, 8, C.dark); hay(g, 27, 16, 10, 5);
    if (l === 3) { win(g, 6, wy + 10, 'glass'); win(g, 49, wy + 10, 'glass'); hay(g, 0, H - 10, 12, 8); sack(g, 54, H - 11); }
    else { hay(g, 2, H - 10, 12, 8); }
  });
  def('pen', 'Загон', 'personal', [66, 44], 3, (g, l, W, H) => {
    const cow = (x, y) => { R(g, x, y, 14, 8, C.k); R(g, x + 1, y + 1, 12, 6, '#f2f2f2'); R(g, x + 3, y + 2, 4, 3, C.k);
      R(g, x - 4, y - 1, 6, 6, C.k); R(g, x - 3, y, 4, 4, '#f2f2f2'); R(g, x - 3, y + 3, 4, 2, '#e8a8a8');
      for (const lx of [x + 1, x + 10]) R(g, lx, y + 8, 2, 3, C.k); };
    const sheep = (x, y) => { disc(g, x + 4, y + 3, 4, '#f2f2f2'); R(g, x - 2, y + 1, 4, 4, C.k);
      for (const lx of [x + 2, x + 6]) R(g, lx, y + 7, 1, 3, C.k); };
    R(g, 2, 14, 60, 28, l === 3 ? '#6aa848' : '#5a9a3c');
    for (let i = 0; i < 14; i++) P(g, 4 + (i * 17) % 56, 16 + (i * 11) % 24, C.grassD);
    const kind = ['stick', 'rail', 'stone'][l - 1];
    fenceRow(g, 2, 18, 60, kind); fenceRow(g, 2, H - 1, 60, kind);
    for (const x of [2, 60]) { R(g, x, 10, 2, H - 11, C.k); R(g, x, 11, 1, H - 13, l === 3 ? C.stone : C.woodL); }
    if (l === 1) { sheep(30, 24); return; }
    sheep(14, 26); cow(36, 22);
    box(g, 8, H - 12, 12, 4, C.woodL); R(g, 9, H - 11, 10, 1, C.water);   // trough
    if (l === 3) {   // a stone shelter in the corner
      roof(g, 44, 0, 20, 10, 'tile', 0, 3); wall(g, 46, 8, 16, 10, 'stone'); R(g, 50, 11, 8, 7, C.dark); hay(g, 24, 8, 12, 8);
    }
  });
  def('garden', 'Огород', 'personal', [52, 36], 3, (g, l, W, H) => {
    const rows = l === 1 ? 2 : 4, w = l === 1 ? 34 : 44, x = l === 1 ? 9 : 4;
    for (let r = 0; r < rows; r++) {
      const y = 8 + r * 6;
      R(g, x, y, w, 5, C.soilD); R(g, x + 1, y + 1, w - 2, 3, C.soil);
      for (let i = x + 3; i < x + w - 2; i += 5) {
        if (l === 1) { P(g, i, y + 1, C.sprout); continue; }
        const ripe = l === 3 && r % 2 === 0;
        R(g, i, y, 1, 2, C.leaf); P(g, i - 1, y, C.sprout); P(g, i + 1, y, C.sprout);
        if (ripe) P(g, i, y - 1, r ? '#ff9f4c' : '#e04a3a'); else if (l === 3) R(g, i - 1, y - 1, 3, 1, C.leafL);
      }
    }
    if (l === 1) { R(g, 40, 22, 1, 10, C.woodD); R(g, 38, 21, 5, 2, C.stone); return; }   // a digging stick
    fenceRow(g, 1, H - 1, 50, 'stick');
    if (l === 3) {   // scarecrow and a watering can
      R(g, 46, 6, 1, 26, C.woodD); R(g, 41, 12, 11, 2, C.k); R(g, 42, 12, 9, 1, '#5a7aa8'); disc(g, 46, 8, 3, C.straw);
      R(g, 43, 4, 7, 2, C.k); R(g, 44, 3, 5, 1, C.woodD); R(g, 43, 14, 7, 8, C.k); R(g, 44, 15, 5, 6, '#5a7aa8');
      box(g, 2, H - 10, 7, 6, C.ironL); R(g, 9, H - 9, 3, 1, C.k);
    }
  });
  def('chicken_coop', 'Курятник', 'personal', [42, 40], 3, (g, l, W, H) => {
    const hen = (x, y) => { R(g, x, y, 5, 4, C.k); R(g, x + 1, y + 1, 3, 2, '#f2f2f2'); P(g, x + 4, y - 1, C.red); P(g, x + 5, y + 1, C.fireL); };
    if (l === 1) { roof(g, 6, 14, 26, 10, 'thatch', 0, 4); wall(g, 9, 22, 20, 12, 'wattle'); fringe(g, 6, 23, 26); R(g, 16, 27, 6, 7, C.dark);
      shadow(g, 7, 34, 24); hen(30, 32); return; }
    const wy = hut(g, 4, 8, 32, 16, 12, l === 2 ? 'plankH' : 'brick', 'shingle', l === 2 ? ROOF.red : ROOF.slate, 4);
    R(g, 15, wy + 6, 8, 10, C.k); R(g, 16, wy + 7, 6, 9, C.dark); line(g, 19, wy + 16, 22, H - 2, C.woodL);
    fenceRow(g, 0, H - 1, 40, l === 2 ? 'stick' : 'rail'); hen(4, H - 8); hen(30, H - 7);
    if (l === 3) { win(g, 26, wy + 3, 'glass'); hen(10, H - 7); }
  });
  def('beehive', 'Пасека', 'personal', [36, 32], 3, (g, l, W, H) => {
    const bee = (x, y) => { P(g, x, y, C.fireL); P(g, x + 1, y, C.k); };
    if (l === 1) { R(g, 16, 6, 2, 24, C.woodD); disc(g, 12, 12, 5, '#c8a050'); R(g, 7, 12, 10, 1, C.strawD); P(g, 12, 15, C.k); bee(20, 8); bee(5, 20);
      return; }
    const n = l === 2 ? 1 : 3;
    for (let k = 0; k < n; k++) {
      const x = l === 2 ? 12 : 2 + k * 11, y = 10;
      if (l === 2) { for (let j = 0; j < 4; j++) { const w = [10, 12, 12, 10][j]; box(g, x + (12 - w) / 2, y + j * 4, w, 5, j % 2 ? C.straw : C.strawL); }
        R(g, x + 5, y + 14, 2, 2, C.k); }
      else { box(g, x, y + 2, 10, 14, '#f2e6c8'); R(g, x - 1, y, 12, 3, C.k); R(g, x, y + 1, 10, 1, C.red);
        R(g, x + 1, y + 8, 8, 1, C.k); R(g, x + 3, y + 14, 4, 1, C.k); R(g, x + 1, y + 16, 1, 4, C.k); R(g, x + 8, y + 16, 1, 4, C.k); }
    }
    bee(4, 6); bee(30, 4); bee(26, 12);
    if (l === 3) for (let i = 0; i < 6; i++) P(g, 3 + i * 6, H - 2, ['#e04a6a', '#ffd23f', '#a77cc4'][i % 3]);
  });

  // Craft
  def('workbench', 'Верстак', 'craft', [40, 36], 3, (g, l, W, H) => {
    if (l === 1) { R(g, 10, 20, 20, 12, C.k); R(g, 11, 21, 18, 2, C.end); R(g, 11, 23, 18, 8, C.wood);
      disc(g, 15, 21, 1, C.woodL, null); R(g, 22, 16, 1, 5, C.woodD); R(g, 20, 15, 5, 2, C.stone);   // stump + stone axe
      shadow(g, 10, 32, 20); logs(g, 30, 26, 2); return; }
    if (l === 3) { roof(g, 0, 0, 40, 10, 'tile', 0, 4); R(g, 3, 9, 2, 22, C.k); R(g, 35, 9, 2, 22, C.k); R(g, 3, 10, 1, 20, C.stone); R(g, 35, 10, 1, 20, C.stone);
      R(g, 6, 10, 28, 1, C.k); for (let i = 0; i < 4; i++) R(g, 8 + i * 6, 11, 1, 4, C.iron); }
    // the bench: a plank top on legs, a vice, tools
    R(g, 6, 20, 28, 4, C.k); R(g, 7, 21, 26, 1, C.woodLL); R(g, 7, 22, 26, 1, C.wood);
    for (const x of [8, 30]) R(g, x, 24, 2, 9, C.k);
    R(g, 8, 28, 24, 1, C.woodD); box(g, 27, 16, 5, 5, C.iron); R(g, 12, 18, 6, 2, C.ironL); R(g, 18, 19, 3, 1, C.woodD);
    shadow(g, 6, 32, 28); if (l === 2) { crate(g, 0, H - 9); logs(g, 30, 26, 2); } else sack(g, 33, H - 11);
  });
  def('kiln', 'Печь', 'craft', [40, 50], 3, (g, l, W, H) => {
    if (l === 1) {   // a clay mound with a fire mouth
      for (let j = 0; j < 18; j++) { const w = Math.round(28 * Math.sqrt(1 - ((18 - j) / 18) ** 2)); R(g, 20 - w / 2, 26 + j, w, 1, j === 0 ? C.k : C.k);
        if (j) R(g, 21 - w / 2, 26 + j, w - 2, 1, j < 4 ? '#d08a5a' : j % 5 === 0 ? '#9a4a2c' : '#c06a40'); }
      R(g, 15, 36, 10, 8, C.k); R(g, 16, 37, 8, 7, C.dark); fire(g, 20, 44, 1); R(g, 18, 25, 4, 2, C.k); smoke(g, 20, 20, 2);
      return; }
    if (l === 2) {   // brick dome on a stone base, a tall clay flue
      R(g, 17, 6, 6, 14, C.k); R(g, 18, 7, 4, 13, '#c06a40'); smoke(g, 20, 0, 1);
      for (let j = 0; j < 20; j++) { const w = Math.round(34 * Math.sqrt(1 - ((20 - j) / 20) ** 2)); R(g, 20 - w / 2, 18 + j, w, 1, C.k);
        if (j) for (let i = 1; i < w - 1; i++) P(g, 20 - w / 2 + i, 18 + j, WALL.brick(i, j)); }
      wall(g, 2, 38, 36, 8, 'stone'); R(g, 13, 28, 14, 12, C.k); R(g, 14, 29, 12, 11, C.dark); fire(g, 20, 40, 1);
      return; }
    chimney(g, 26, 0, 20, 'brick'); smoke(g, 29, -2, 1);
    const wy = hut(g, 0, 10, 40, 26, 14, 'brick', 'tile', 0, 4);
    R(g, 9, wy + 8, 22, 18, C.k); R(g, 10, wy + 9, 20, 17, C.brickD); R(g, 13, wy + 12, 14, 11, C.k); R(g, 14, wy + 13, 12, 10, C.dark); fire(g, 20, wy + 23, 1);
    stones(g, 0, H - 7, 2); for (let i = 0; i < 3; i++) box(g, 30, H - 4 - i * 3, 9, 3, C.brick);
  });
  def('mill', 'Мельница', 'craft', [56, 80], 3, (g, l, W, H) => {
    if (l === 1) {   // a hand quern under a little roof
      shadow(g, 14, H - 2, 28); roof(g, 12, 44, 32, 10, 'thatch', 0, 4); R(g, 14, 53, 2, 25, C.k); R(g, 40, 53, 2, 25, C.k);
      box(g, 18, 66, 20, 6, C.stone); box(g, 20, 62, 16, 5, C.stoneL); R(g, 27, 57, 2, 6, C.woodD); sack(g, 6, H - 11); sack(g, 44, H - 11);
      return; }
    const cx = 28, hub = 22;
    if (l === 2) {   // a wooden post mill
      R(g, 26, 52, 4, 26, C.k); R(g, 27, 52, 2, 26, C.woodL); line(g, 18, 78, 27, 60, C.k); line(g, 38, 78, 29, 60, C.k);
      roof(g, 14, 12, 28, 12, 'shingle', ROOF.brown, 6); wall(g, 16, 22, 24, 30, 'plankH'); door(g, 24, 38, 8, 12, 'plank');
    } else {   // a stone tower windmill
      for (let j = 0; j < 58; j++) { const w = 22 + Math.round(j * 12 / 58), x = cx - (w >> 1); R(g, x, 20 + j, w, 1, C.k);
        for (let i = 1; i < w - 1; i++) P(g, x + i, 20 + j, WALL.stone(i, j)); }
      roof(g, 14, 6, 28, 16, 'tile', 0, 10); door(g, 23, 62, 10, 16, 'arch'); win(g, 24, 42, 'glass'); banner(g, 27, -4, C.red, 6);
    }
    // the sails: four arms with lattice cloth
    const arm = (dx, dy) => {
      for (let i = 2; i < 22; i++) { const x = cx + dx * i, y = hub + dy * i; P(g, x, y, C.k); P(g, x + dy, y + dx, C.k); }
      for (let i = 7; i < 22; i++) for (let s = 2; s < 5; s++) { const x = cx + dx * i - dy * s, y = hub + dy * i + dx * s;
        P(g, x, y, i % 4 === 0 || s === 4 ? C.woodD : l === 3 ? '#f2ecd8' : '#d8c8a0'); }
    };
    arm(1, -1); arm(-1, 1); arm(1, 1); arm(-1, -1);
    disc(g, cx, hub, 3, C.woodD);
    sack(g, 4, H - 11); if (l === 3) sack(g, 44, H - 11, '#f2f2f2');
  });
  def('forge', 'Кузница', 'craft', [56, 56], 3, (g, l, W, H) => {
    const anvil = (x, y, stone) => { if (stone) { box(g, x, y, 10, 7, C.stone); P(g, x + 1, y + 1, C.stoneL); return; }
      R(g, x, y, 12, 4, C.k); R(g, x + 1, y + 1, 10, 2, C.iron); R(g, x + 4, y + 4, 4, 4, C.k); R(g, x + 2, y + 7, 8, 3, C.k); P(g, x + 2, y + 1, C.ironL); };
    if (l === 1) {   // open fire pit ringed with stones, skin bellows, a stone anvil
      shadow(g, 8, H - 4, 40);
      for (let i = 0; i < 7; i++) box(g, 12 + i * 4, H - 12 + (i % 2), 5, 4, C.stone);
      R(g, 16, H - 13, 20, 3, C.dark); fire(g, 26, H - 12, 1); smoke(g, 26, H - 26, 2);
      R(g, 4, H - 14, 8, 6, C.k); R(g, 5, H - 13, 6, 4, C.hide); line(g, 11, H - 11, 15, H - 11, C.woodD);
      anvil(40, H - 13, true); return; }
    if (l === 2) {   // open-sided shed on posts, stone hearth, iron anvil
      roof(g, 2, 8, 52, 16, 'shingle', ROOF.slate, 6);
      for (const x of [5, 49]) { R(g, x, 23, 3, 31, C.k); R(g, x + 1, 24, 1, 29, C.woodL); }
      wall(g, 10, 30, 18, 22, 'stone'); R(g, 13, 38, 12, 8, C.dark); fire(g, 19, 46, 1); chimney(g, 16, 2, 22); smoke(g, 19, 0, 1);
      anvil(34, 42, false); R(g, 30, 52, 20, 2, 'rgba(0,0,0,.22)'); barrel(g, 46, 44);
      return; }
    chimney(g, 42, 0, 20, 'brick'); smoke(g, 45, -2, 1);
    const [top, mid] = hall(g, 2, 6, 52, 22, 12, 16, 'stone', ROOF.slate);
    R(g, 18, mid + 2, 22, 20, C.k); R(g, 19, mid + 3, 20, 19, '#2a1a14'); R(g, 22, mid + 12, 14, 6, C.fire); R(g, 24, mid + 10, 10, 3, C.fireL);
    win(g, 6, mid + 6, 'shutter'); win(g, 12, top + 2, 'glass'); win(g, 36, top + 2, 'glass');
    sign(g, 23, top + 3, (g, x, y) => { R(g, x - 3, y - 2, 6, 2, C.iron); R(g, x - 1, y, 2, 2, C.iron); });
    anvil(42, H - 11, false);
  });
  def('loom', 'Ткацкая', 'craft', [48, 52], 3, (g, l, W, H) => {
    const frame = (x, y, w, h, cloth) => {   // a loom: two posts, beams, warp threads, woven cloth
      R(g, x, y, 2, h, C.k); R(g, x + w - 2, y, 2, h, C.k); R(g, x, y, w, 2, C.k); R(g, x, y + h - 8, w, 2, C.k);
      for (let i = x + 3; i < x + w - 3; i += 2) R(g, i, y + 2, 1, h - 10, '#e8e0d0');
      R(g, x + 2, y + h - 16, w - 4, 6, cloth); for (let i = x + 2; i < x + w - 2; i += 2) P(g, i, y + h - 13, shade(cloth));
    };
    if (l === 1) { frame(12, 14, 24, 32, '#c8b890'); shadow(g, 12, H - 2, 24); disc(g, 41, H - 6, 3, '#f2f2f2'); return; }
    if (l === 2) {
      const wy = hut(g, 2, 6, 44, 30, 16, 'plank', 'shingle', ROOF.purple, 5);
      R(g, 8, wy + 4, 28, 24, C.k); R(g, 9, wy + 5, 26, 23, C.dark); frame(11, wy + 6, 22, 22, '#5a7aa8');
      R(g, 37, wy + 2, 1, 22, C.k); R(g, 38, wy + 4, 6, 14, '#c060a0');
      return; }
    const [top, mid] = hall(g, 0, 2, 48, 18, 14, 16, 'plaster', ROOF.purple);
    win(g, 8, top + 2, 'glass'); win(g, 31, top + 2, 'glass'); door(g, 19, mid + 2, 10, 16, 'arch');
    // bolts of dyed cloth hanging outside
    R(g, 2, mid + 1, 14, 1, C.k); R(g, 3, mid + 2, 4, 12, '#c04a4a'); R(g, 8, mid + 2, 4, 10, '#4a7ac0');
    R(g, 34, mid + 1, 12, 1, C.k); R(g, 35, mid + 2, 4, 11, '#e0c040'); R(g, 40, mid + 2, 4, 13, '#5aa848');
  });
  def('tannery', 'Дубильня', 'craft', [56, 44], 3, (g, l, W, H) => {
    const rack = (x, y) => { R(g, x, y, 2, 18, C.k); R(g, x + 14, y, 2, 18, C.k); R(g, x - 1, y, 18, 2, C.k);
      R(g, x + 2, y + 2, 12, 10, C.k); R(g, x + 3, y + 3, 10, 8, C.hide); R(g, x + 4, y + 4, 8, 1, C.hideL); };
    const vat = (x, y, c) => { box(g, x, y, 12, 8, C.wood); R(g, x + 1, y + 1, 10, 2, c); R(g, x + 1, y + 5, 10, 1, C.iron); };
    if (l === 1) { rack(6, 20); rack(32, 22); shadow(g, 6, H - 2, 44); return; }
    if (l === 2) { roof(g, 0, 4, 34, 12, 'shingle', ROOF.brown, 4); for (const x of [3, 29]) R(g, x, 15, 2, 27, C.k);
      vat(6, 32, '#7a5a2a'); vat(18, 32, '#9a3a2a'); rack(38, 22); return; }
    const wy = hut(g, 0, 2, 36, 26, 14, 'stone', 'tile', 0, 4);
    door(g, 13, wy + 10, 10, 16, 'plank'); win(g, 4, wy + 6, 'glass');
    rack(38, 18); vat(36, H - 8, '#7a5a2a'); vat(2, H - 8, '#9a3a2a');
  });

  // Shared
  def('campfire', 'Костёр', 'shared', [44, 32], 3, (g, l, W, H) => {
    if (l === 1) { for (const d of [-1, 0, 1]) { line(g, 13, 28 + d, 29, 22 + d, C.k); line(g, 13, 22 + d, 29, 28 + d, C.k); }
      line(g, 14, 28, 28, 22, C.woodL); line(g, 14, 22, 28, 28, C.woodL); fire(g, 21, 26, 2); return; }
    for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4; box(g, 19 + Math.round(Math.cos(a) * 8), 21 + Math.round(Math.sin(a) * 4), 5, 4, C.stone); }
    fire(g, 21, 25, l === 3 ? 2 : 1);
    for (const x of [1, 33]) { R(g, x, 22, 10, 5, C.k); R(g, x + 1, 23, 8, 3, C.wood); disc(g, x + 1, 24, 2, C.end); }   // log seats
    if (l === 3) {   // a cooking spit with a pot, and a stone bench behind
      R(g, 9, 6, 2, 22, C.k); R(g, 31, 6, 2, 22, C.k); R(g, 9, 6, 24, 2, C.k); R(g, 20, 8, 1, 4, C.k);
      R(g, 16, 12, 9, 7, C.k); R(g, 17, 13, 7, 5, C.iron); R(g, 17, 12, 7, 1, '#c87a4a');
      R(g, 4, 0, 36, 5, C.k); R(g, 5, 1, 34, 3, C.stone); R(g, 5, 1, 34, 1, C.stoneL);
    }
  });
  def('market', 'Рыночная площадь', 'shared', [88, 54], 3, (g, l, W, H) => {
    const goods = (x, y) => { for (let i = 0; i < 4; i++) disc(g, x + i * 4, y, 2, ['#e04a3a', '#ffd23f', '#7ab648', '#ff9f4c'][(x + i) % 4]); };
    const stall = (x, y, c1, c2) => {
      R(g, x + 1, y + 8, 2, 20, C.k); R(g, x + 21, y + 8, 2, 20, C.k);
      R(g, x, y, 24, 9, C.k); for (let i = 1; i < 23; i++) R(g, x + i, y + 1, 1, 7, (i >> 2) % 2 ? c1 : c2);
      for (let i = 0; i < 24; i += 4) R(g, x + i, y + 9, 3, 2, C.k), R(g, x + i + 1, y + 9, 1, 1, (i >> 2) % 2 ? c1 : c2);
      box(g, x - 1, y + 18, 26, 6, C.woodL); goods(x + 4, y + 17); R(g, x, y + 24, 24, 2, 'rgba(0,0,0,.22)');
    };
    if (l === 1) {   // blankets on the ground with goods
      for (const [x, y, c] of [[10, 24, '#b8483a'], [48, 30, '#3f6fa8']]) { box(g, x, y, 28, 14, c); R(g, x + 1, y + 1, 26, 1, shade(c, 1.3));
        goods(x + 6, y + 7); sack(g, x + 20, y - 6); }
      return; }
    if (l === 3) {   // a cobbled square with a fountain
      for (let j = 4; j < H; j++) for (let i = 0; i < W; i++) P(g, i, j, (i + (j >> 2) * 3) % 6 === 0 || j % 4 === 0 ? '#8a8a92' : '#b0b0b8');
      disc(g, 44, 34, 9, C.stoneL); disc(g, 44, 34, 6, C.water); R(g, 43, 24, 2, 9, C.k); P(g, 43, 25, C.waterL); P(g, 44, 27, C.waterL);
      stall(4, 4, '#b8483a', '#f2f2f2'); stall(60, 4, '#3f6fa8', '#f2f2f2'); stall(4, 26, '#5c8a3a', '#f2e6c8'); stall(60, 26, '#c47a2c', '#f2e6c8');
      return; }
    stall(10, 12, '#b8483a', '#f2e6c8'); stall(52, 12, '#3f6fa8', '#f2e6c8'); crate(g, 38, 36); barrel(g, 80, 32);
  });
  def('council', 'Дом совета', 'shared', [88, 74], 3, (g, l, W, H) => {
    if (l === 1) {   // a big hide tent with a fire in front
      for (let j = 0; j < 40; j++) { const w = 4 + Math.round(j * 60 / 40), x = 44 - (w >> 1); R(g, x, 18 + j, w, 1, C.k);
        for (let i = 1; i < w - 1; i++) P(g, x + i, 18 + j, i === (w >> 1) ? C.hideD : (i * 9 / w | 0) % 2 ? C.hide : C.hideL); }
      line(g, 40, 10, 44, 19, C.woodD); line(g, 48, 10, 44, 19, C.woodD); R(g, 38, 42, 12, 16, C.k); R(g, 39, 43, 10, 15, C.dark);
      shadow(g, 14, 58, 60); fire(g, 70, 64, 1); for (let i = 0; i < 5; i++) box(g, 63 + i * 3, 63, 4, 3, C.stone);
      return; }
    if (l === 2) {   // a long hall of logs with carved gable ends and a totem
      const wy = hut(g, 2, 12, 84, 30, 26, 'log', 'shingle', ROOF.brown, 10);
      for (const x of [8, 76]) { line(g, x, 12, x - 4, 4, C.k); line(g, x + 1, 12, x - 3, 4, C.woodL); }
      R(g, 34, wy + 6, 20, 24, C.k); door(g, 35, wy + 7, 18, 23, 'plank'); R(g, 43, wy + 7, 1, 23, C.k);
      win(g, 12, wy + 10, 'shutter'); win(g, 67, wy + 10, 'shutter'); banner(g, 22, wy + 2, '#3f6fa8', 12); banner(g, 60, wy + 2, '#3f6fa8', 12);
      return; }
    // stone hall with a pediment, columns and a bell tower
    R(g, 38, 0, 12, 20, C.k); wall(g, 39, 4, 10, 14, 'stone'); R(g, 41, 7, 6, 6, C.dark); R(g, 42, 8, 4, 4, C.fireL);
    roof(g, 36, 0, 16, 6, 'tile', 0, 4);
    const wy = hut(g, 0, 16, 88, 36, 22, 'stone', 'tile', 0, 12);
    for (let j = 0; j < 12; j++) { const w = 4 + j * 4; R(g, 44 - w / 2, wy - 12 + j, w, 1, C.k);
      if (j) R(g, 45 - w / 2, wy - 12 + j, w - 2, 1, j < 3 ? C.stoneL : C.plaster); }
    disc(g, 44, wy - 4, 2, C.fireL);
    R(g, 2, wy, 84, 2, C.k); R(g, 3, wy, 82, 1, C.stoneL);
    for (const x of [10, 24, 58, 72]) { R(g, x, wy + 2, 6, 33, C.k); R(g, x + 1, wy + 2, 4, 33, C.plaster); R(g, x + 1, wy + 2, 1, 33, '#fff4dc'); R(g, x - 1, wy + 2, 8, 2, C.k); }
    door(g, 37, wy + 14, 14, 21, 'arch'); win(g, 15, wy + 8, 'glass') ; win(g, 63, wy + 8, 'glass');
    R(g, 30, H - 4, 28, 2, C.k); R(g, 31, H - 4, 26, 1, C.stoneL); banner(g, 2, wy + 4, '#3f6fa8', 14); banner(g, 80, wy + 4, '#3f6fa8', 14);
  });
  def('tavern', 'Таверна', 'shared', [72, 72], 3, (g, l, W, H) => {
    const mug = (g, x, y) => { R(g, x - 3, y - 2, 5, 5, C.k); R(g, x - 2, y - 1, 3, 3, '#e0b040'); R(g, x - 2, y - 2, 3, 1, '#f2f2f2'); P(g, x + 2, y, C.k); };
    if (l === 1) {   // lean-to with a barrel table and stumps
      roof(g, 8, 26, 56, 14, 'thatch', 0, 4); fringe(g, 8, 39, 56); for (const x of [12, 58]) R(g, x, 39, 2, 30, C.k);
      wall(g, 14, 40, 44, 12, 'wattle'); barrel(g, 32, 56); R(g, 30, 55, 11, 2, C.k); R(g, 31, 55, 9, 1, C.woodL);
      for (const x of [20, 46]) { R(g, x, 60, 6, 5, C.k); R(g, x + 1, 61, 4, 1, C.end); } mug(g, 36, 52); shadow(g, 10, 69, 52);
      return; }
    if (l === 2) {
      chimney(g, 50, 8, 16); smoke(g, 53, 4, 2);
      const wy = hut(g, 2, 14, 68, 34, 24, 'plankH', 'shingle', ROOF.red, 8);
      door(g, 30, wy + 16, 12, 18, 'plank'); win(g, 9, wy + 12, 'shutter'); win(g, 54, wy + 12, 'shutter');
      sign(g, 30, wy + 2, mug); barrel(g, 2, H - 10); barrel(g, 62, H - 10);
      return; }
    chimney(g, 54, 0, 20, 'brick'); smoke(g, 57, -2, 1);
    const [top, mid] = hall(g, 0, 6, 72, 26, 18, 18, 'plaster', null, 8);
    for (const x of [9, 31, 53]) win(g, x, top + 4, 'glass');
    door(g, 31, mid + 8, 10, 17, 'arch'); win(g, 10, mid + 9, 'glass'); win(g, 52, mid + 9, 'glass');
    R(g, 44, mid + 2, 10, 1, C.k); R(g, 52, mid + 2, 1, 3, C.k); sign(g, 46, mid + 5, mug); lantern(g, 26, mid + 4);
    barrel(g, 0, H - 10); barrel(g, 64, H - 10);
  });
  def('wall', 'Стена', 'shared', [56, 40], 3, (g, l, W, H) => {
    if (l === 1) {   // a palisade of sharpened stakes
      for (let x = 2; x < 54; x += 4) { const h = 26 + (x * 7) % 5; R(g, x, H - 2 - h, 4, h, C.k); R(g, x + 1, H - h, 2, h - 3, C.wood); R(g, x + 1, H - h, 1, h - 3, C.woodL);
        P(g, x + 1, H - 3 - h, C.k); P(g, x + 2, H - 3 - h, C.k); }
      R(g, 2, H - 16, 52, 2, C.k); R(g, 2, H - 15, 52, 1, C.strawD); shadow(g, 2, H - 2, 52); return; }
    if (l === 2) {   // a log palisade with a walkway and a lookout post
      for (let x = 2; x < 54; x += 5) { R(g, x, 6, 5, H - 8, C.k); R(g, x + 1, 7, 3, H - 10, C.wood); R(g, x + 1, 7, 1, H - 10, C.woodL);
        R(g, x + 1, 4, 3, 2, C.k); }
      R(g, 0, 18, 56, 4, C.k); R(g, 1, 19, 54, 2, C.woodLL); R(g, 1, H - 10, 54, 1, C.iron);
      shadow(g, 2, H - 2, 52); return; }
    // stone wall with crenellations and an arrow slit
    wall(g, 0, 10, 56, H - 12, 'stone'); for (let x = 0; x < 56; x += 10) { R(g, x, 4, 7, 8, C.k); wall(g, x, 4, 7, 7, 'stone'); }
    R(g, 0, 10, 56, 2, C.k); R(g, 1, 11, 54, 1, C.stoneL); R(g, 26, 20, 3, 9, C.k); shadow(g, 0, H - 2, 56);
  });
  def('gate', 'Ворота', 'shared', [64, 56], 3, (g, l, W, H) => {
    if (l === 1) {   // two tall stakes and a hinged hurdle of branches
      for (const x of [14, 46]) { R(g, x, 10, 4, 44, C.k); R(g, x + 1, 11, 2, 42, C.woodL); }
      R(g, 18, 26, 28, 26, C.k); for (let x = 19; x < 46; x += 3) R(g, x, 27, 2, 24, C.wood); line(g, 19, 27, 45, 51, C.woodD);
      line(g, 18, 30, 45, 30, C.strawD); line(g, 18, 46, 45, 46, C.strawD); shadow(g, 14, 54, 36); return; }
    if (l === 2) {   // a log gate between two little towers
      for (const x of [2, 46]) { roof(g, x - 2, 2, 20, 10, 'shingle', ROOF.brown, 4); wall(g, x, 10, 16, 44, 'log'); win(g, x + 5, 16, 'hole'); }
      R(g, 18, 18, 28, 2, C.k); door(g, 18, 22, 28, 32, 'plank'); R(g, 31, 22, 2, 32, C.k);
      R(g, 19, 30, 26, 2, C.iron); R(g, 19, 44, 26, 2, C.iron); return; }
    // a stone gatehouse with an arch, a portcullis and a banner
    wall(g, 0, 10, 64, 44, 'stone'); for (let x = 0; x < 64; x += 9.5) wall(g, Math.round(x), 4, 7, 7, 'stone');
    R(g, 18, 22, 28, 32, C.k);
    for (let j = 0; j < 8; j++) { const w = Math.round(26 * Math.sqrt(1 - ((8 - j) / 8) ** 2)); R(g, 32 - w / 2, 23 + j, w, 1, C.dark); }
    R(g, 19, 31, 26, 23, C.dark);
    for (let x = 21; x < 44; x += 4) R(g, x, 26, 1, 28, C.iron); for (let y = 30; y < 54; y += 5) R(g, 19, y, 26, 1, C.iron);
    banner(g, 6, 16, C.red, 14); banner(g, 52, 16, C.red, 14);
  });
  def('well', 'Колодец', 'shared', [32, 40], 3, (g, l, W, H) => {
    if (l === 1) {   // a hole ringed with stones, a bucket on a rope
      R(g, 8, 27, 16, 7, C.k); R(g, 9, 28, 14, 5, C.waterD); R(g, 10, 29, 4, 1, C.waterL);
      for (let i = 0; i < 10; i++) { const a = i * Math.PI / 5; box(g, 14 + Math.round(Math.cos(a) * 10), 29 + Math.round(Math.sin(a) * 5), 5, 4, i % 2 ? C.stone : C.stoneL); } box(g, 24, 32, 6, 6, C.wood); line(g, 27, 32, 22, 28, '#d8b878');
      return; }
    const ring = l === 2 ? 'plankH' : 'stone';
    wall(g, 4, 24, 24, 14, ring); R(g, 5, 24, 22, 3, C.k); R(g, 6, 25, 20, 1, C.waterD);
    R(g, 5, 8, 2, 18, C.k); R(g, 25, 8, 2, 18, C.k); R(g, 5, 9, 1, 16, C.woodL); R(g, 25, 9, 1, 16, C.woodL);
    R(g, 5, 13, 22, 2, C.k); R(g, 6, 13, 20, 1, C.woodLL); line(g, 16, 15, 16, 20, '#d8b878'); box(g, 13, 19, 7, 6, C.wood);
    if (l === 2) roof(g, 2, 0, 28, 10, 'shingle', ROOF.brown, 4);
    else { roof(g, 1, 0, 30, 10, 'tile', 0, 5); R(g, 26, 13, 4, 2, C.iron); R(g, 29, 13, 1, 4, C.iron); R(g, 0, H - 3, 32, 2, C.k); R(g, 1, H - 3, 30, 1, C.stoneL); }
  });
  def('bridge', 'Мост', 'shared', [72, 44], 3, (g, l, W, H) => {
    water(g, 0, 12, 72, 26); R(g, 0, 10, 72, 2, '#5a9a3c'); R(g, 0, 38, 72, 2, '#5a9a3c');
    if (l === 1) {   // two logs across, lashed
      for (const y of [20, 25]) { R(g, 0, y, 72, 5, C.k); R(g, 1, y + 1, 70, 1, C.woodLL); R(g, 1, y + 2, 70, 2, C.wood); }
      for (const x of [18, 50]) R(g, x, 20, 2, 10, C.strawD); return; }
    if (l === 2) {   // planks on piles with rope rails
      for (const x of [16, 36, 56]) { R(g, x, 22, 4, 16, C.k); R(g, x + 1, 22, 2, 15, C.woodD); }
      R(g, 0, 18, 72, 8, C.k); for (let x = 1; x < 71; x++) R(g, x, 19, 1, 6, x % 4 === 0 ? C.woodD : x % 4 === 1 ? C.woodLL : C.wood);
      for (let x = 2; x < 72; x += 12) { R(g, x, 10, 2, 9, C.k); } line(g, 2, 11, 70, 11, '#d8b878'); return; }
    // a stone arch bridge
    for (let i = 0; i < 72; i++) { const a = Math.abs(i - 36) / 36, top = 12 + Math.round(4 * a * a), under = 30 - Math.round(12 * Math.sqrt(Math.max(0, 1 - ((i - 36) / 26) ** 2)));
      R(g, i, top, 1, (i < 10 || i > 61 ? 28 : under - top), C.k);
      for (let j = top + 1; j < (i < 10 || i > 61 ? 40 : under - 1); j++) P(g, i, j, j < top + 4 ? (j === top + 1 ? C.stoneL : C.stone) : WALL.stone(i, j)); }
    for (let i = 4; i < 70; i += 6) { const a = Math.abs(i - 36) / 36; R(g, i, 8 + Math.round(4 * a * a), 4, 5, C.k); R(g, i + 1, 9 + Math.round(4 * a * a), 2, 3, C.stoneL); }
  });
  def('watchtower', 'Вышка', 'shared', [40, 88], 3, (g, l, W, H) => {
    if (l === 1) {   // a tall pole with a lookout platform and a ladder
      R(g, 18, 14, 4, 72, C.k); R(g, 19, 15, 2, 70, C.woodL); R(g, 10, 14, 20, 4, C.k); R(g, 11, 15, 18, 2, C.wood);
      for (let y = 22; y < 84; y += 5) R(g, 14, y, 4, 1, C.woodD); R(g, 13, 18, 1, 66, C.k); fenceRow(g, 10, 14, 20, 'stick');
      shadow(g, 12, 86, 16); return; }
    if (l === 2) {   // a timber tower: four legs, cross braces, a roofed cabin
      for (const x of [6, 31]) { R(g, x, 28, 3, 58, C.k); R(g, x + 1, 29, 1, 56, C.woodL); }
      for (let y = 34; y < 82; y += 16) { line(g, 8, y, 31, y + 14, C.woodD); line(g, 31, y, 8, y + 14, C.woodD); R(g, 6, y, 28, 2, C.k); }
      wall(g, 4, 16, 32, 14, 'plank'); R(g, 10, 20, 20, 4, C.dark); roof(g, 2, 4, 36, 14, 'shingle', ROOF.brown, 10);
      shadow(g, 6, 86, 28); return; }
    // a round stone tower with a slate cone and a flag
    wall(g, 6, 26, 28, 60, 'stone'); R(g, 4, 24, 32, 6, C.k); wall(g, 4, 24, 32, 6, 'stone');
    for (let x = 4; x < 36; x += 7) wall(g, x, 20, 5, 5, 'stone');
    for (let j = 0; j < 18; j++) { const w = 4 + j * 2; R(g, 20 - w / 2, 2 + j, w, 1, C.k); if (j) R(g, 21 - w / 2, 2 + j, w - 2, 1, j % 3 ? '#5d6070' : '#44464f'); }
    banner(g, 20, -4, C.red, 6); R(g, 18, 36, 4, 8, C.k); R(g, 18, 56, 4, 8, C.k); door(g, 15, 70, 10, 16, 'arch'); lantern(g, 30, 64);
  });
  def('mine', 'Шахта', 'shared', [56, 50], 3, (g, l, W, H) => {
    // a rocky hillside with an opening
    for (let j = 0; j < 36; j++) { const w = Math.round(56 * Math.sqrt(1 - ((36 - j) / 38) ** 2)); R(g, 28 - w / 2, 10 + j, w, 1, C.k);
      for (let i = 1; i < w - 1; i++) P(g, 28 - w / 2 + i, 10 + j, rnd(i >> 2, j >> 2, 11) < .3 ? C.stoneD : rnd(i, j, 12) < .2 ? C.stoneL : C.stone); }
    if (l === 1) { R(g, 20, 30, 14, 16, C.k); R(g, 21, 31, 12, 15, C.dark); stones(g, 38, H - 9, 3); R(g, 10, 38, 1, 8, C.woodD); R(g, 8, 37, 5, 2, C.stone); return; }
    // timbered entrance
    R(g, 18, 22, 20, 24, C.dark); R(g, 16, 20, 24, 4, C.k); R(g, 17, 21, 22, 2, C.woodL); for (const x of [16, 37]) { R(g, x, 22, 3, 24, C.k); R(g, x + 1, 23, 1, 22, C.woodL); }
    if (l === 2) { box(g, 42, H - 12, 12, 7, C.wood); stones(g, 43, H - 16, 2); disc(g, 45, H - 4, 2, C.iron); disc(g, 51, H - 4, 2, C.iron); lantern(g, 14, 24); return; }
    // rails out of the mine, an ore cart, and a winch headframe
    for (let x = 20; x < 56; x += 3) R(g, x, H - 4, 1, 3, C.woodD); R(g, 20, H - 4, 36, 1, C.iron); R(g, 20, H - 2, 36, 1, C.iron);
    box(g, 40, H - 13, 12, 8, C.iron); for (let i = 0; i < 3; i++) box(g, 41 + i * 3, H - 16, 4, 4, i === 1 ? '#c87a4a' : C.stoneD);
    line(g, 18, 20, 28, 2, C.k); line(g, 38, 20, 28, 2, C.k); disc(g, 28, 4, 3, C.woodD); line(g, 28, 4, 28, 20, '#d8b878');
    lantern(g, 13, 24); lantern(g, 42, 24);
  });

  function shade(hex, f = .75) {
    const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.max(0, Math.min(255, Math.round(v * f))));
    return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
  }

  // The building site: stage 1 stakes and string with materials, 2 a timber frame, 3 half-built walls in scaffolding.
  function site(g, w, h, stage, x = 0, y = 0) {
    g.save(); g.translate(x, y);
    const b = h - 4, fx = 4, fw = w - 8;
    R(g, fx, b - 6, fw, 8, '#a88a5a'); for (let i = 0; i < fw; i += 3) P(g, fx + i, b - 3 + (i % 2), '#8a6a40');   // dug ground
    if (stage === 1) {
      for (const x0 of [fx, fx + fw - 2]) { R(g, x0, b - 12, 2, 12, C.k); P(g, x0, b - 12, C.woodL); }
      R(g, fx + fw / 2 - 1, b - 10, 2, 10, C.k); line(g, fx + 1, b - 11, fx + fw - 2, b - 11, '#f2f2f2');
      logs(g, fx + 2, b - 18, 4); stones(g, fx + fw - 16, b - 12, 4); sack(g, fx + fw / 2 - 3, b - 18);
    } else {
      const top = b - Math.min(h - 10, 36);
      R(g, fx, b - 2, fw, 3, C.k); R(g, fx + 1, b - 1, fw - 2, 1, C.stone);   // footing
      if (stage === 3) {
        wall(g, fx + 1, b - 16, fw - 2, 15, 'plank'); R(g, fx + fw / 2 - 4, b - 13, 8, 12, C.dark);
      }
      for (let x0 = fx; x0 <= fx + fw - 2; x0 += Math.max(8, (fw - 2) / Math.round((fw - 2) / 12))) { R(g, x0 | 0, top, 2, b - top, C.k); R(g, (x0 | 0) + 1, top + 1, 1, b - top - 2, C.woodLL); }
      R(g, fx, top, fw, 2, C.k); R(g, fx, top + 1, fw, 1, C.woodL);
      // rafters
      const mid = fx + fw / 2;
      line(g, fx, top, mid, top - 10, C.woodD); line(g, fx + fw - 1, top, mid, top - 10, C.woodD); line(g, mid, top - 10, mid, top, C.woodD);
      if (stage === 3) {   // scaffolding poles, boards and a ladder
        for (const x0 of [fx - 3, fx + fw + 1]) { R(g, x0, top + 4, 2, b - top - 4, C.k); P(g, x0 + 1, top + 5, '#d8b878'); }
        R(g, fx - 3, b - 18, fw + 6, 2, C.k); R(g, fx - 2, b - 18, fw + 4, 1, C.woodLL);
        for (let yy = b - 14; yy < b; yy += 3) R(g, fx + fw - 6, yy, 4, 1, C.woodD); R(g, fx + fw - 7, b - 16, 1, 16, C.k); R(g, fx + fw - 2, b - 16, 1, 16, C.k);
      } else { logs(g, fx + fw - 12, b - 8, 3); }
    }
    g.restore();
  }

  function draw(g, kind, level, x = 0, y = 0) {
    const k = K[kind]; if (!k) return false;
    g.save(); g.translate(x + 1, y); k.draw(g, Math.max(1, Math.min(k.levels, level | 0)), k.size[0] - 2, k.size[1]); g.restore();
    return true;
  }
  // An offscreen canvas with one building, scaled up with no smoothing (for the gallery or a sprite cache).
  function canvas(kind, level, scale = 1, doc = document) {
    const [w, h] = K[kind].size, c = doc.createElement('canvas');
    c.width = w * scale; c.height = (h + 8) * scale;
    const g = c.getContext('2d'); g.imageSmoothingEnabled = false; g.scale(scale, scale); draw(g, kind, level, 0, 8);
    return c;
  }
  const LIST = Object.keys(K);
  const api = { KINDS: K, LIST, draw, site, canvas, GROUPS: { personal: 'Личные', craft: 'Ремесленные', shared: 'Общие' } };
  if (typeof window !== 'undefined') window.BuildArt = api;
  return api;
})();
