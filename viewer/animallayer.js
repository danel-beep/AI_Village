// Game animals on the map (aivillage/animals.py), drawn from `view.animals`: hares and ducks, deer, boars and
// elk wander inside the place they live in (a few per herd, more animals = more of them shown), the animal
// just caught or brought down lies at the hunters' feet for the tick of the catch, and a horn sign marks a
// place with an open hunt party. Pixel art drawn here in code. PixelMap.draw calls AnimalLayer.draw after
// the villagers.
const AnimalLayer = (() => {
  const PAL = { k: '#1b1b24', g: '#9a8670', G: '#c8b8a0', w: '#f4efe6', e: '#111111', o: '#e8902a', v: '#2e7d4f',
    b: '#b9a58a', d: '#9a6a3c', D: '#c28a52', a: '#e3d6b8', p: '#4a3a30', P: '#6b5444', n: '#2a2018',
    m: '#5e4128', M: '#7d5a3a', h: '#c79a5a' };
  const HARE = [
    '......kk.kk',
    '......kgkgk',
    '.......kggk',
    '..kkkkkgggek',
    '.kwgggggggk',
    '.kGggggggk',
    '..kGkkkGk',
    '..kk...kk'];
  const DUCK = [
    '......kkk',
    '.....kvvvk',
    '.....kvevoo',
    '.....kvvk',
    '.kkkkkwwk',
    'kwwwwwwwwk',
    'kbwwwwwwbk',
    '.kkkkkkkk'];
  const DEER = [
    '...........a..a',
    '...........aaaa',
    '............kk',
    '...........kddk',
    '...........kdedk',
    '...........kdddk',
    '.kkkkkkkkkkkddk',
    'kdddddddddddddk',
    'kdDDDDDDDDDDddk',
    'kddddddddddddk',
    '..kdkkdk..kdkkdk',
    '..kdkkdk..kdkkdk',
    '..kk..kk..kk..kk'];
  const ELK = ['.........a.a.a.a.a', '..........aaaaaa', ...DEER.slice(2)].map(r => r.replace(/d/g, 'm').replace(/D/g, 'M'));
  const BOAR = [
    '....kkkkkkk.k.k',
    '...kppppppkpkpk',
    '..kppppppppppppk',
    '.kppPPPPpppppepk',
    '.kppppppppppppppk',
    '.kpppppppppppppwnk',
    '..kppppppppppppwk',
    '...kppppppppppk',
    '...kpk..kpk.kpk',
    '...kk...kk..kk'];
  const HORN = ['...kk', '..khk', 'kkhhk', 'khhhk', 'kkhhk', '..khk', '...kk'];
  const ART = { hare: [HARE, 1, 1.1], duck: [DUCK, 1, 0.6], deer: [DEER, 1.6, 0.7], boar: [BOAR, 1.5, 0.8], elk: [ELK, 2, 0.5] };

  const cache = {};
  function sprite(rows, flip, down) {
    const key = rows.join('') + (flip ? 'f' : '') + (down ? 'd' : '');
    if (cache[key]) return cache[key];
    const c = document.createElement('canvas');
    c.width = Math.max(...rows.map(r => r.length)); c.height = rows.length;
    const g = c.getContext('2d');
    rows.forEach((row, y) => [...row].forEach((ch, x) => {
      if (ch === '.') return;
      g.fillStyle = PAL[ch] || ch;
      g.fillRect(flip ? c.width - 1 - x : x, down ? c.height - 1 - y : y, 1, 1);
    }));
    return (cache[key] = c);
  }
  const put = (b, img, x, y, k = 1) => (b.imageSmoothingEnabled = false, b.drawImage(img, Math.round(x - img.width * k / 2),
    Math.round(y - img.height * k), Math.round(img.width * k), Math.round(img.height * k)));
  // stable pseudo-random 0..1 from a string, so each animal keeps its own spot and pace
  const rnd = s => { let h = 2166136261; for (const ch of s) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return ((h >>> 0) % 1000) / 1000; };

  function draw(b, t, layout, sec) {
    const an = t.view && t.view.animals;
    if (!an) return;
    for (const [loc, herd] of Object.entries(an.herds || {})) {
      const bx = layout.box[loc];
      if (!bx) continue;
      const [x0, y0, w, h] = bx;
      for (const [sp, count] of Object.entries(herd)) {
        const art = ART[sp];
        if (!art || count <= 0) continue;
        const shown = Math.min(count, sp === 'hare' || sp === 'duck' ? 3 : 2);
        for (let i = 0; i < shown; i++) {
          const id = loc + sp + i, r1 = rnd(id), r2 = rnd(id + 'y'), pace = art[2] * (0.6 + r1);
          const sway = Math.sin(sec * pace * 0.5 + r1 * 6.3), x = x0 + w * (0.12 + 0.76 * r1) + sway * 10;
          const y = y0 + h * (0.35 + 0.6 * r2), hop = sp === 'hare' ? Math.round(Math.abs(Math.sin(sec * 4 + r2 * 9)) * 2) : 0;
          put(b, sprite(art[0], Math.cos(sec * pace * 0.5 + r1 * 6.3) < 0), x, y - hop, art[1]);
        }
      }
    }
    for (const p of an.parties || []) {   // a hunting horn over a place with an open hunt party
      const bx = layout.box[p.location];
      if (!bx) continue;
      const [x0, y0, w] = bx;
      put(b, sprite(HORN, false), x0 + w / 2, y0 + 6 + Math.round(Math.sin(sec * 3) * 1.5), 2);
    }
    for (const ev of t.events || []) {      // the catch lies at the hunter's feet
      if (ev.kind !== 'hunt_kill' && ev.kind !== 'hunt_catch') continue;
      const art = ART[ev.data && ev.data.species], bx = layout.box[ev.location];
      if (!art || !bx) continue;
      const [x0, y0, w, h] = bx;
      put(b, sprite(art[0], false, true), x0 + w * (0.3 + 0.4 * rnd(ev.actor || '')), y0 + h * 0.9, art[1]);
    }
  }
  return { draw };
})();
window.AnimalLayer = AnimalLayer;
