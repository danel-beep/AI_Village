// Seasons on the map: yellowed grass and trees in autumn, snow and ice in winter, falling leaves and snowflakes.
// The calendar mirrors aivillage/seasons.py (header.config.seasons: length_days, order, start, offset_days).
// pixelmap.js calls ground() for the background, tint() over the map layers and weather() over the villagers;
// without this file the map is the same in every season.
(function () {
  const SEASON_RU = { spring: '🌱 Весна', summer: '☀️ Лето', autumn: '🍂 Осень', winter: '❄️ Зима' };
  let base = null, cache = {};
  const memos = {};

  function seasonOf(header, day) {
    const s = header && header.config && header.config.seasons;
    if (!s || s.enabled === false || !s.order) return null;
    const first = Math.max(0, s.order.indexOf(s.start || s.order[0]));
    const pos = first * s.length_days + (s.offset_days || 0) + day - 1;
    return s.order[Math.floor(pos / s.length_days) % s.order.length];
  }

  // Per-pixel recolour of the painted background (code art and sprites alike): greens and olives are grass and leaves,
  // blue-dominant pixels are water. Colours are cached, pixel art has few of them.
  function recolor(src, season) {
    const c = document.createElement('canvas'); c.width = src.width; c.height = src.height;
    const g = c.getContext('2d'); g.drawImage(src, 0, 0);
    recolorRect(g, season, 0, 0, c.width, c.height);
    return c;
  }
  function recolorRect(g, season, x, y, w, h) {
    x = Math.max(0, x | 0); y = Math.max(0, y | 0);
    w = Math.min(g.canvas.width - x, Math.ceil(w)); h = Math.min(g.canvas.height - y, Math.ceil(h));
    if (w <= 0 || h <= 0) return;
    const img = g.getImageData(x, y, w, h), d = img.data, memo = memos[season] || (memos[season] = new Map());
    for (let i = 0; i < d.length; i += 4) {
      if (!d[i + 3]) continue;
      const key = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
      let out = memo.get(key);
      if (out === undefined) { out = shift(d[i], d[i + 1], d[i + 2], season); memo.set(key, out); }
      if (out) { d[i] = out[0]; d[i + 1] = out[1]; d[i + 2] = out[2]; }
    }
    g.putImageData(img, x, y);
  }
  function shift(r, gr, b, season) {
    const lum = (r + gr + b) / 765, green = gr >= r * .85 && gr > b * 1.35 && gr > 30, water = b > r + 25 && b > gr - 10;
    if (season === 'winter') {
      if (green) { const v = .62 + lum * .55; return [Math.min(255, 214 * v + 20), Math.min(255, 224 * v + 20), Math.min(255, 240 * v + 15)]; }
      if (water) return [Math.round(r * .4 + 120), Math.round(gr * .4 + 140), Math.round(b * .3 + 170)];
      return null;
    }
    if (season === 'autumn' && green) return [Math.min(255, gr * 1.05 + 28), Math.round(gr * .8), Math.round(b * .5)];
    return null;
  }

  function ground(bg, header, day) {
    const season = seasonOf(header, day);
    if (season !== 'winter' && season !== 'autumn') return bg;
    if (bg !== base) { base = bg; cache = {}; }
    return cache[season] || (cache[season] = recolor(bg, season));
  }

  // The map layers draw live trees, bushes and beds over the background every frame: recolour their boxes
  // (viewer/maplayer.js plantBoxes), then a light cold veil over everything in winter.
  function tint(g, header, day, W, H) {
    const season = seasonOf(header, day);
    if (season !== 'winter' && season !== 'autumn') return;
    if (window.MapLayer && MapLayer.plantBoxes) for (const [x0, y0, x1, y1] of MapLayer.plantBoxes()) recolorRect(g, season, x0, y0, x1 - x0, y1 - y0);
    if (season === 'winter') { g.fillStyle = 'rgba(214,228,255,.12)'; g.fillRect(0, 0, W, H); }
  }

  function hash(i, k) { let h = Math.imul(i + 1, 374761393) ^ Math.imul(k + 7, 668265263); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
  // Snowflakes in winter, a few leaves in autumn; positions are a function of time, nothing to keep.
  function weather(g, header, day, sec, W, H) {
    const season = seasonOf(header, day);
    if (season === 'winter') {
      const n = Math.round(W * H / 2600);
      g.fillStyle = 'rgba(255,255,255,.9)';
      for (let i = 0; i < n; i++) {
        const speed = 12 + hash(i, 1) * 14, y = (hash(i, 2) * H + sec * speed) % H;
        const x = (hash(i, 3) * W + Math.sin(sec * .7 + i) * 6 + sec * 4) % W, big = hash(i, 4) < .25;
        g.fillRect(x | 0, y | 0, big ? 2 : 1, big ? 2 : 1);
      }
    } else if (season === 'autumn') {
      const n = Math.round(W * H / 16000), cols = ['#d9822b', '#c4532d', '#e0b040'];
      for (let i = 0; i < n; i++) {
        const y = (hash(i, 2) * H + sec * (8 + hash(i, 1) * 8)) % H, x = (hash(i, 3) * W + Math.sin(sec * 1.3 + i) * 10) % W;
        g.fillStyle = cols[i % 3]; g.fillRect(x | 0, y | 0, 2, 1); g.fillRect((x | 0) + (Math.sin(sec * 3 + i) > 0 ? 1 : 0), (y | 0) + 1, 1, 1);
      }
    }
  }

  function label(header, day) { const s = seasonOf(header, day); return s ? SEASON_RU[s] || s : ''; }

  window.SeasonLayer = { seasonOf, ground, tint, weather, label, shift };
})();
