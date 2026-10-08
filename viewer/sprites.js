// Sprite art for the pixel map: SpriteCook sheets (viewer/art/) cut into one atlas by scripts/build_sprites.py
// and embedded in viewer/sprites_data.js. Every drawing hook calls Sprites.draw() first and falls back to the
// code-drawn pixel art in viewer/pixelmap.js when it returns false: no atlas, not decoded yet, or ?sprites=0.
const Sprites = (() => {
  const A = window.SPRITE_ATLAS, waiting = [];
  let img = null, ok = false;
  if (A && !/[?&]sprites=0\b/.test(location.search)) {
    img = new Image();
    img.onload = () => { ok = true; waiting.splice(0).forEach(f => f()); };
    img.src = A.src;
  }
  const has = n => ok && !!A.frames[n];
  const size = n => { const f = A && A.frames[n]; return f ? [f[2], f[3]] : [0, 0]; };
  const onReady = f => { if (ok) f(); else if (img) waiting.push(f); };

  // Draw sprite n with its bottom-centre at (x, y). o.s scales it, o.flip mirrors it, o.alpha fades it.
  function draw(g, n, x, y, o = {}) {
    if (!has(n)) return false;
    const [sx, sy, w, h] = A.frames[n], s = o.s || 1, dw = Math.max(1, Math.round(w * s)), dh = Math.max(1, Math.round(h * s));
    const dx = Math.round(x - dw / 2), dy = Math.round(y - dh);
    if (o.alpha != null) g.globalAlpha = o.alpha;
    if (o.flip) { g.save(); g.translate(dx + dw, dy); g.scale(-1, 1); g.drawImage(img, sx, sy, w, h, 0, 0, dw, dh); g.restore(); }
    else g.drawImage(img, sx, sy, w, h, dx, dy, dw, dh);
    if (window.Depth) Depth.sprite(g, n, img, sx, sy, w, h, dx, dy, dw, dh, o.flip);   // tall objects hide villagers behind them
    if (o.alpha != null) g.globalAlpha = 1;
    return true;
  }

  // One sprite on its own canvas (cached): ground textures are read pixel by pixel and used as fill patterns.
  const canvases = {};
  function canvas(n) {
    if (!has(n)) return null;
    if (!canvases[n]) {
      const [sx, sy, w, h] = A.frames[n], c = document.createElement('canvas');
      c.width = w; c.height = h; c.getContext('2d').drawImage(img, sx, sy, w, h, 0, 0, w, h); canvases[n] = c;
    }
    return canvases[n];
  }
  const pixels = n => { const c = canvas(n); return c && c.getContext('2d').getImageData(0, 0, c.width, c.height); };
  const pattern = (g, n) => { const c = canvas(n); return c && g.createPattern(c, 'repeat'); };

  // Fight effects for whoever shows a brawl (dice rolls, hits): a dust cloud with stars and sparks over (x, y), t in
  // seconds drives the wobble. Names of the separate pieces: fight_dust, hit_star, dizzy, d20, d6, heart, heart_broken.
  function brawl(g, x, y, t, o = {}) {
    if (!has('fight_dust')) return false;
    const k = Math.floor(t * 8);
    draw(g, 'fight_dust', x + Math.sin(t * 13) * 2, y + 4, { s: (o.s || 1) * (1 + .06 * Math.sin(t * 17)), flip: k % 2 === 1 });
    draw(g, 'hit_star', x + [-9, 8, -3, 10][k % 4], y - [14, 8, 18, 16][k % 4], { s: .7 + (k % 3) * .2 });
    if (o.dice) draw(g, 'd20', x, y - 26 - Math.abs(Math.sin(t * 6)) * 6);
    return true;
  }

  // A villager sheet in the layout viewer/actors.js expects: rows down / up / side (facing right), columns stand /
  // step / step. The art has one step per view, so the second step is the first one mirrored (down) or bobbed.
  const LOOKS = 24;
  // Which looks are women (by the art in viewer/art/chars1..4.png); the rest are men.
  const FEMALE_LOOKS = [1, 3, 5, 7, 8, 11, 13, 15, 19, 21, 23];
  const lookIsFemale = k => FEMALE_LOOKS.includes(k % LOOKS);
  // Names that do not follow the ending rule below (population.py NAMES, the default five, common Russian ones).
  const F_NAMES = new Set(['agnes', 'alice', 'beatrice', 'camille', 'edith', 'irene', 'judith', 'mabel', 'ingrid',
    'astrid', 'ruth', 'esther', 'kate', 'grace', 'rachel', 'hannah', 'sarah', 'deborah', 'любовь', 'нинель', 'ruby', 'lily', 'emily', 'daisy', 'ivy']);
  const M_NAMES = new Set(['ilya', 'nikita', 'luka', 'foma', 'kuzma', 'savva', 'sasha', 'misha', 'kolya', 'vanya',
    'илья', 'никита', 'лука', 'фома', 'кузьма', 'савва', 'саша', 'миша', 'коля', 'ваня', 'andrea', 'joshua', 'noah']);
  // Best guess from a first name: known lists, else names ending in a / я / ia are women's.
  function femaleName(name) {
    const n = String(name || '').trim().split(/\s+/)[0].toLowerCase();
    if (F_NAMES.has(n)) return true;
    if (M_NAMES.has(n)) return false;
    return /[aая]$/.test(n);
  }

  // A villager sheet in the layout viewer/actors.js expects: rows down / up / side (facing right), columns stand /
  // step / step. The art has one step per view, so the second step is the first one mirrored (down) or bobbed.
  // `variant` > 0 recolours clothes and hair (a second villager with the same look still looks different).
  function villager(k, variant = 0) {
    const id = 'v' + (k % LOOKS), poses = ['down', 'step', 'up', 'side'].map(p => id + '_' + p);
    if (!poses.every(has)) return null;
    const fw = 2 * Math.ceil(Math.max(...poses.map(p => size(p)[0])) / 2) + 2, fh = Math.max(...poses.map(p => size(p)[1])) + 1;
    const c = document.createElement('canvas'); c.width = fw * 3; c.height = fh * 3;
    const g = c.getContext('2d'), at = (col, row, n, o = {}) => draw(g, n, col * fw + fw / 2, row * fh + fh - (o.bob || 0), o);
    at(0, 0, id + '_down'); at(1, 0, id + '_step'); at(2, 0, id + '_step', { flip: true });
    at(0, 1, id + '_up'); at(1, 1, id + '_up', { bob: 1 }); at(2, 1, id + '_up', { flip: true, bob: 1 });
    at(0, 2, id + '_side'); at(1, 2, id + '_side', { bob: 1 }); at(2, 2, id + '_side');
    if (variant) recolor(g, c.width, c.height, variant);
    c.fw = fw; c.fh = fh;
    return c;
  }

  // Rotate the hue of strongly coloured pixels (clothes, hair), leaving skin tones, greys and outlines alone.
  function recolor(g, w, h, variant) {
    const im = g.getImageData(0, 0, w, h), d = im.data, turn = [.5, .3, .7, .15, .85][(variant - 1) % 5];
    for (let i = 0; i < d.length; i += 4) {
      if (!d[i + 3]) continue;
      const r = d[i] / 255, gg = d[i + 1] / 255, b = d[i + 2] / 255, mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), l = (mx + mn) / 2;
      if (mx - mn < .18 || l < .12) continue;
      const s = (mx - mn) / (1 - Math.abs(2 * l - 1));
      let hh = mx === r ? ((gg - b) / (mx - mn)) % 6 : mx === gg ? (b - r) / (mx - mn) + 2 : (r - gg) / (mx - mn) + 4;
      hh = ((hh / 6) + 1) % 1;
      if (hh > .02 && hh < .15) continue;   // skin, blond and brown hair, leather
      hh = (hh + turn) % 1;
      const q = (1 - Math.abs(2 * l - 1)) * s * .85, x = q * (1 - Math.abs(((hh * 6) % 2) - 1)), m = l - q / 2, seg = Math.floor(hh * 6);
      const [r2, g2, b2] = [[q, x, 0], [x, q, 0], [0, q, x], [0, x, q], [x, 0, q], [q, 0, x]][seg];
      d[i] = (r2 + m) * 255; d[i + 1] = (g2 + m) * 255; d[i + 2] = (b2 + m) * 255;
    }
    g.putImageData(im, 0, 0);
  }

  // A look of each villager's sex (guessed from the name) that fits the profession (straw hat for the farmer, apron
  // for the smith...), each look once while there are enough of them, then recoloured repeats: {name: [look,
  // variant]}. A look set in the start screen (config agents[].look) wins. The map (viewer/pixelmap.js) and the
  // start screen's skin preview (viewer/setup.js) both use this, so the preview is the villager in the game.
  const PROF_LOOK = { farmer: [0, 5, 23, 1], smith: [4, 10, 13], fisher: [9, 6, 11], woodcutter: [16, 6, 2, 13],
                      miner: [12, 10, 3], trader: [18, 19], merchant: [18, 19] };
  function pickLooks(agents) {
    const n = LOOKS, count = {}, out = {};
    const take = (name, look) => { out[name] = [look, count[look] || 0]; count[look] = (count[look] || 0) + 1; };
    agents.forEach(a => { if (Number.isInteger(a.look) && a.look >= 0 && a.look < n) take(a.name, a.look); });
    agents.forEach((a, k) => {
      if (out[a.name]) return;
      const fits = i => lookIsFemale(i) === femaleName(a.name);
      const all = Array.from({ length: n }, (_, i) => (k + i) % n).filter(fits);
      const pref = [...(PROF_LOOK[a.profession] || []).filter(fits), ...all];
      const look = pref.find(i => !count[i]) ?? pref.reduce((m, i) => (count[i] < count[m] ? i : m), pref[0] ?? k % n);
      take(a.name, look);
    });
    return out;
  }

  const meta = n => (A.meta || {})[n];

  return { get ok() { return ok; }, has, size, meta, draw, onReady, villager, canvas, pixels, pattern, brawl, LOOKS,
           lookIsFemale, femaleName, pickLooks };
})();
window.Sprites = Sprites;
