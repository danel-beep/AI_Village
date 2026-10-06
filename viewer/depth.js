// Depth on the pixel map: a villager standing behind a tree, a house or a building is hidden by it.
// The map is painted before the villagers, so on its own every villager lands on top of everything. While the
// background and the per-frame map layers are painted, Sprites.draw() (and the code-drawn tree in pixelmap.js) report
// every tall object here with its base line. After the villagers are placed, the objects whose base is below a
// villager's feet and that overlap it are copied back over it, in base order, from a snapshot of the finished map
// (so autumn / winter colours stay), using the object's own pixels as the mask.
const Depth = (() => {
  // standing objects; flat ones (ground textures, ponds, bridges, beds, lily pads) never cover anyone
  const TALL = /^(oak|pine|apple_tree|sapling|bush|berry_bush|stump|boulder|\w+_rock|house\d|house_frame|smithy|mine|market|well|forge|bakery|bank|barn|small_barn|butcher|carpenter|chapel|fishmonger|herbalist|pottery|stable|store|tailor|tavern|town_hall|warehouse|windmill|coop|doghouse|signpost|lamp|scarecrow|notice_board|mailbox|woodpile|scaffold|stocks)/;
  const FOOT = 2;   // the bottom rows of a sprite are its shadow and roots: feet that far up still stand in front
  const bg = [], live = [];
  let sink = null, snap = null, scratch = null;

  // 'bg' while the background is painted (replaces the old list), 'live' around the map layers of each frame.
  function begin(which) { sink = which === 'bg' ? bg : live; sink.length = 0; }
  function end() { sink = null; }

  // An object drawn by mask(g) into the box (x, y, w, h) with its base at y + h, in g's current coordinates.
  function add(g, key, x, y, w, h, mask) {
    if (!sink) return;
    const m = g.getTransform(), pt = (px, py) => [m.a * px + m.c * py + m.e, m.b * px + m.d * py + m.f];
    const cs = [pt(x, y), pt(x + w, y), pt(x, y + h), pt(x + w, y + h)], xs = cs.map(c => c[0]), ys = cs.map(c => c[1]);
    const [ax, ay] = pt(x + w / 2, y + h);
    const o = { key: key + '@' + Math.round(ax) + ',' + Math.round(ay), m, mask, base: ay - FOOT,
                x0: Math.floor(Math.min(...xs)), y0: Math.floor(Math.min(...ys)), x1: Math.ceil(Math.max(...xs)), y1: Math.ceil(Math.max(...ys)) };
    if (sink === live && key === 'house') {   // a yard redraws its house every frame: that one wins over the background one
      const i = bg.findIndex(q => q.key === o.key); if (i >= 0) bg.splice(i, 1);
    }
    sink.push(o);
  }

  // Called by Sprites.draw() for every sprite it puts down.
  function sprite(g, n, img, sx, sy, w, h, dx, dy, dw, dh, flip) {
    if (!sink || !TALL.test(n)) return;
    add(g, /^house\d/.test(n) ? 'house' : n, dx, dy, dw, dh, c => {
      if (flip) { c.translate(dx + dw, dy); c.scale(-1, 1); c.drawImage(img, sx, sy, w, h, 0, 0, dw, dh); }
      else c.drawImage(img, sx, sy, w, h, dx, dy, dw, dh);
    });
  }

  // Paint the villagers (each { x, y } with feet at y + 8) back to front with the objects in front of them on top.
  // paint(a) draws one villager; b is the map buffer, already holding everything below the villagers.
  function paint(b, shown, paint) {
    const vbox = a => [a.x - 12, a.y - 22, a.x + 12, a.y + 9], feet = a => a.y + 8;
    const front = [];
    for (const o of [...bg, ...live]) {
      for (const a of shown) {
        const [x0, y0, x1, y1] = vbox(a);
        if (feet(a) < o.base && x0 < o.x1 && o.x0 < x1 && y0 < o.y1 && o.y0 < y1) { front.push(o); break; }
      }
    }
    if (front.length) {
      const W = b.canvas.width, H = b.canvas.height;
      if (!snap || snap.width !== W || snap.height !== H) { snap = document.createElement('canvas'); snap.width = W; snap.height = H; }
      const s = snap.getContext('2d'); s.clearRect(0, 0, W, H); s.drawImage(b.canvas, 0, 0);
    }
    const items = shown.map(a => ({ k: feet(a), a })).concat(front.map(o => ({ k: o.base, o })));
    items.sort((p, q) => p.k - q.k || (p.o ? 0 : 1) - (q.o ? 0 : 1));   // on a tie the villager stands in front
    for (const it of items) if (it.a) paint(it.a); else cover(b, it.o);
  }

  function cover(b, o) {
    const w = o.x1 - o.x0, h = o.y1 - o.y0;
    if (w <= 0 || h <= 0) return;
    if (!scratch) scratch = document.createElement('canvas');
    if (scratch.width < w || scratch.height < h) { scratch.width = Math.max(scratch.width, w); scratch.height = Math.max(scratch.height, h); }
    const c = scratch.getContext('2d');
    c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = 'source-over'; c.clearRect(0, 0, w, h);
    c.setTransform(1, 0, 0, 1, -o.x0, -o.y0); c.transform(o.m.a, o.m.b, o.m.c, o.m.d, o.m.e, o.m.f);
    o.mask(c);
    c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = 'source-in';
    c.drawImage(snap, o.x0, o.y0, w, h, 0, 0, w, h);
    c.globalCompositeOperation = 'source-over';
    b.drawImage(scratch, 0, 0, w, h, o.x0, o.y0, w, h);
  }

  // A standing spot (x, y; feet at y + 8) that is not inside a tree trunk, a well or a wall: a spot whose feet fall in
  // the bottom band of a background object moves just in front of it. Walking routes are left as they are.
  const BAND = 12, SMALL = /^(sapling|bush|berry_bush|stump|signpost|lamp|mailbox|boulder|\w+_rock)/;
  function free(x, y) {
    for (const o of bg) {
      if (SMALL.test(o.key)) continue;
      const f = y + 8, cx = (o.x0 + o.x1) / 2, half = Math.max(5, (o.x1 - o.x0) * .35);
      if (f > o.base - BAND && f < o.base + FOOT + 2 && Math.abs(x - cx) < half) return [x, o.base + FOOT + 2 - 8];
    }
    return [x, y];
  }

  return { begin, end, add, sprite, paint, free, get objects() { return [...bg, ...live]; } };
})();
if (typeof window !== 'undefined') window.Depth = Depth;
