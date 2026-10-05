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

  // A villager sheet in the layout viewer/actors.js expects: rows down / up / side (facing right), columns stand /
  // step / step. The art has one step per view, so the second step is the first one mirrored (down) or bobbed.
  const LOOKS = 12;
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

  return { get ok() { return ok; }, has, size, meta, draw, onReady, villager };
})();
window.Sprites = Sprites;
