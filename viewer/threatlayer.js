// Threats on the map (aivillage/threats.py), drawn from `view.threats`: bandits around the house they are
// plundering (fewer as they lose strength), the beast prowling at a house, a traveler at the square, a red
// pennant over the house a warned raid or beast is headed for. All pixel art is drawn here in code, in the
// palette of the villagers (no external sprites). PixelMap.draw calls ThreatLayer.draw after the villagers.
const ThreatLayer = (() => {
  // one char = one pixel; '.' transparent
  const PAL = { k: '#1b1b24', h: '#3b2a22', H: '#56402f', m: '#1f2a2a', s: '#e0ac7e', e: '#ffffff', r: '#c0392b',
    b: '#4a3a2e', B: '#6a5440', l: '#2b2b38', c: '#7a5232', C: '#9c6b40', f: '#6e5a48', F: '#9a8166', d: '#4a3c30', g: '#d8d0c0',
    E: '#ff3b2f', w: '#f4efe6', n: '#2a2420', y: '#5b7fa8', Y: '#86a7cc', o: '#c79a5a', t: '#e6c06a' };
  const BANDIT = [
    '....kkkk....',
    '...kHhhHk...',
    '..kHhhhhHk..',
    '..khssssHk..',
    '..ksekkesk..',
    '..krrrrrrk..',
    '...krrrrk.cc',
    '..kbBBBBbkCk',
    '.kbbBoBBbbk.',
    '.kskbbbbksk.',
    '..kkbttbkk..',
    '...kbbbbk...',
    '...kllkllk..',
    '...kllkllk..',
    '...knnknnk..',
    '....kk.kk...'];
  const BEAST = [   // a wolf-bear facing left: ears and mane, red eyes, fangs (rows padded to the widest)
    '..k..k',
    '.kFk.kFk.......k..k..k',
    '.kFFkkFFk.....kFkkFkkFk',
    'kFFFFFFFFk..kkFFFFFFFFFkk',
    'kFEEFFFFFFkkFFffffffffffFk',
    'kFEEFFfFFFFFffffffffffffffk',
    'nFFFFFfffffffffffffffffffffk',
    'nkFFFffffffffffffffffffffffkk',
    '.kwkwfffffffffffffffffffffkFk',
    '..k.kdfffffffffffffffffffdk.k',
    '.....kddffddddddddffddddk',
    '.....kdfffk......kdfffk',
    '.....kdffk.......kdffk',
    '.....kdffk.......kdffk',
    '.....kgkgk.......kgkgk',
    '......k.k.........k.k'];
  const TRAVELER = [
    '....kkkk....',
    '...kyYYyk.o.',
    '..kyyyyyykok',
    '..kyssssyko.',
    '..kysekeyko.',
    '..kyssssyko.',
    '...kyyyyk.o.',
    '..kyYyyYyko.',
    '.kyyYyyYyyo.',
    '.kyyyyyyykt.',
    '.kyyyyyyyo..',
    '..kyyyyyyo..',
    '..kyyyyyyo..',
    '...kyyyyk...',
    '...knnknnk..',
    '....kk.kk...'];
  const FLAG = ['k....', 'krrr.', 'krwr.', 'krrr.', 'kr.r.', 'k....', 'k....', 'k....'];

  const cache = {};
  function sprite(rows, flip) {
    const key = rows.join('') + (flip ? 'f' : '');
    if (cache[key]) return cache[key];
    const c = document.createElement('canvas');
    c.width = Math.max(...rows.map(r => r.length)); c.height = rows.length;
    const g = c.getContext('2d');
    rows.forEach((row, y) => [...row].forEach((ch, x) => {
      if (ch === '.') return;
      g.fillStyle = PAL[ch] || ch; g.fillRect(flip ? c.width - 1 - x : x, y, 1, 1);
    }));
    return (cache[key] = c);
  }
  // bottom-centre at (x, y)
  const put = (b, img, x, y, k = 1) => (b.imageSmoothingEnabled = false, b.drawImage(img, Math.round(x - img.width * k / 2), Math.round(y - img.height * k),
    img.width * k, img.height * k));

  function bar(b, x, y, hp, max) {
    const w = 26, f = Math.max(0, Math.min(1, hp / (max || 1)));
    b.fillStyle = '#1b1b24'; b.fillRect(Math.round(x - w / 2) - 1, y - 1, w + 2, 4);
    b.fillStyle = '#5b2020'; b.fillRect(Math.round(x - w / 2), y, w, 2);
    b.fillStyle = '#e4572e'; b.fillRect(Math.round(x - w / 2), y, Math.round(w * f), 2);
  }

  function draw(b, t, layout, sec) {
    const list = (t.view && t.view.threats) || [];
    for (const th of list) {
      const id = th.state === 'here' ? th.location : th.target, bx = id && layout.box[id];
      if (!bx) continue;
      const [x0, y0, w, h] = bx, cx = x0 + w / 2, foot = y0 + h + 6;
      if (th.state === 'coming') {               // warned: a red pennant flutters over the target house
        const img = sprite(FLAG, Math.sin(sec * 5) > 0);
        put(b, img, cx + 10, y0 + 4 + Math.round(Math.sin(sec * 2) * 1), 2);
        continue;
      }
      if (th.kind === 'raid') {
        const n = Math.max(1, Math.ceil(4 * th.hp / (th.max_hp || 1)));
        for (let i = 0; i < n; i++) {
          const x = cx + (i - (n - 1) / 2) * 11, bob = Math.round(Math.abs(Math.sin(sec * 5 + i * 1.7)) * 2);
          put(b, sprite(BANDIT, i % 2 === 1), x, foot + (i % 2) * 3 - bob);
        }
        bar(b, cx, foot - 20, th.hp, th.max_hp);
        // a torch in the first raider's hand
        const fx = cx - (n - 1) * 5.5 + 7, fy = foot - 15 - Math.round(Math.abs(Math.sin(sec * 5)) * 2);
        b.fillStyle = '#7a5232'; b.fillRect(Math.round(fx), fy, 1, 6);
        b.fillStyle = (sec * 8 | 0) % 2 ? '#ffd23f' : '#ff9f1c'; b.fillRect(Math.round(fx) - 1, fy - 3, 3, 3);
        b.fillStyle = '#e4572e'; b.fillRect(Math.round(fx), fy - 4, 1, 1);
      } else if (th.kind === 'beast') {
        const step = Math.round(Math.sin(sec * 1.3) * 4), bob = Math.round(Math.abs(Math.sin(sec * 4)) * 1);
        const bxs = x0 + w + 6 + step / 2;   // beside the house, so the defenders at the door face it
        put(b, sprite(BEAST), bxs, y0 + h + 2 - bob, 2);
        bar(b, bxs, y0 + h - 36, th.hp, th.max_hp);
      } else if (th.kind === 'traveler') {
        const bob = Math.round(Math.abs(Math.sin(sec * 2)) * 1);
        put(b, sprite(TRAVELER), x0 + w * 0.7, y0 + h * 0.75 - bob);
      }
    }
  }
  return { draw };
})();
window.ThreatLayer = ThreatLayer;
