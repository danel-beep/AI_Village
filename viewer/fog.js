// Fog over unexplored places (aivillage/explore.py), drawn from `view.known`: every place no villager has stood
// in yet sits under a drifting cloud, and its sign reads "?". Without `view.known` (exploration off) nothing is
// drawn. Pixel art in code: each place's cloud is drawn once into its own small canvas, then drifts a little.
// PixelMap.draw calls Fog.draw after the villagers and threats, before the night shade.
const Fog = (() => {
  const CELL = 4, PAD = 10, cache = {};
  const COLS = ['#d9dce4', '#c8ccd7', '#b6bbc8', '#e9ebf0'];
  const hash = (a, b) => { let h = (a * 374761393 + b * 668265263) | 0; h = (h ^ (h >>> 13)) * 1274126177; return ((h ^ (h >>> 16)) >>> 0) / 4294967296; };
  const seedOf = id => { let s = 7; for (const ch of id) s = (s * 31 + ch.charCodeAt(0)) | 0; return s; };

  function cloud(w, h, id) {
    const key = id + ':' + w + 'x' + h;
    if (cache[key]) return cache[key];
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d'), s = seedOf(id), cx = w / 2, cy = h / 2;
    for (let y = 0; y < h; y += CELL) for (let x = 0; x < w; x += CELL) {
      // a soft oval, ragged at the rim: cells near the edge drop out by noise
      const dx = (x + CELL / 2 - cx) / cx, dy = (y + CELL / 2 - cy) / cy, d = Math.sqrt(dx * dx + dy * dy);
      const n = hash(s + x, y);
      if (d > 1 || d > .72 + n * .3) continue;
      g.globalAlpha = d < .6 ? .94 : .78;
      g.fillStyle = COLS[(hash(x, s + y) * COLS.length) | 0];
      g.fillRect(x, y, CELL, CELL);
    }
    return (cache[key] = c);
  }

  // Location ids no villager knows yet; null when exploration is off.
  function unknown(t, layout) {
    const k = t.view.known; if (!k) return null;
    const known = new Set(k), ids = new Set([...Object.keys(layout.box), ...Object.keys(layout.anchors)]);
    return [...ids].filter(id => !known.has(id));
  }

  function hidden(t, id) { const k = t.view.known; return !!k && !k.includes(id); }

  function draw(b, t, layout, sec) {
    const ids = unknown(t, layout); if (!ids) return;
    for (const id of ids) {
      let [x, y, w, h] = layout.box[id] || [...layout.anchors[id].map(v => v - 20), 40, 40];
      x -= PAD; y -= PAD; w = Math.round(w + 2 * PAD); h = Math.round(h + 2 * PAD);
      const ph = seedOf(id) % 7, dx = Math.round(Math.sin(sec * .15 + ph) * 3), dy = Math.round(Math.cos(sec * .11 + ph) * 2);
      b.drawImage(cloud(w, h, id), Math.round(x) + dx, Math.round(y) + dy);
      // a second, thinner layer drifting the other way, so the fog breathes
      b.globalAlpha = .35; b.drawImage(cloud(w, h, id + '~'), Math.round(x) - dx, Math.round(y) - dy); b.globalAlpha = 1;
    }
  }

  return { draw, hidden, unknown };
})();
window.Fog = Fog;
