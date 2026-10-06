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
  function villager(k) {
    const id = 'v' + (k % LOOKS), poses = ['down', 'step', 'up', 'side'].map(p => id + '_' + p);
    if (!poses.every(has)) return null;
    const fw = 2 * Math.ceil(Math.max(...poses.map(p => size(p)[0])) / 2) + 2, fh = Math.max(...poses.map(p => size(p)[1])) + 1;
    const c = document.createElement('canvas'); c.width = fw * 3; c.height = fh * 3;
    const g = c.getContext('2d'), at = (col, row, n, o = {}) => draw(g, n, col * fw + fw / 2, row * fh + fh - (o.bob || 0), o);
    at(0, 0, id + '_down'); at(1, 0, id + '_step'); at(2, 0, id + '_step', { flip: true });
    at(0, 1, id + '_up'); at(1, 1, id + '_up', { bob: 1 }); at(2, 1, id + '_up', { flip: true, bob: 1 });
    at(0, 2, id + '_side'); at(1, 2, id + '_side', { bob: 1 }); at(2, 2, id + '_side');
    c.fw = fw; c.fh = fh;
    return c;
  }

  const meta = n => (A.meta || {})[n];

  return { get ok() { return ok; }, has, size, meta, draw, onReady, villager, canvas, pixels, pattern, brawl, LOOKS };
})();
window.Sprites = Sprites;
