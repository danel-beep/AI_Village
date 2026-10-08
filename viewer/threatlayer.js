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
  function sprite(rows, flip, white) {   // white: the whole silhouette in white (the flash of a landed blow)
    const key = rows.join('') + (flip ? 'f' : '') + (white ? 'w' : '');
    if (cache[key]) return cache[key];
    const c = document.createElement('canvas');
    c.width = Math.max(...rows.map(r => r.length)); c.height = rows.length;
    const g = c.getContext('2d');
    rows.forEach((row, y) => [...row].forEach((ch, x) => {
      if (ch === '.') return;
      g.fillStyle = white ? '#ffffff' : PAL[ch] || ch; g.fillRect(flip ? c.width - 1 - x : x, y, 1, 1);
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

  // Sprite art from the atlas (viewer/sprites.js); a white silhouette of it for the flash of a landed blow.
  const art = n => window.Sprites && Sprites.has(n);
  const whites = {};
  function pic(b, n, x, y, flip, white) {
    if (!white) return Sprites.draw(b, n, x, y, { flip });
    if (!whites[n]) {
      const c = Sprites.canvas(n), w = document.createElement('canvas'), g = w.getContext('2d');
      w.width = c.width; w.height = c.height; g.drawImage(c, 0, 0);
      g.globalCompositeOperation = 'source-in'; g.fillStyle = '#ffffff'; g.fillRect(0, 0, w.width, w.height);
      whites[n] = w;
    }
    const img = whites[n], dx = Math.round(x - img.width / 2), dy = Math.round(y - img.height);
    b.save(); if (flip) { b.translate(dx + img.width, dy); b.scale(-1, 1); b.drawImage(img, 0, 0); } else b.drawImage(img, dx, dy); b.restore();
  }

  // Where a threat that is here stands: {x, y: feet, half: half width, h: height} in map pixels (viewer/combat.js
  // lines the defenders up beside it), or null.
  function spot(th, layout) {
    const bx = th && th.state === 'here' && layout.box[th.location];
    if (!bx) return null;
    const [x0, y0, w, h] = bx;
    if (th.kind === 'raid') { const n = Math.max(1, Math.ceil(4 * th.hp / (th.max_hp || 1))), k = art('b0_down') ? 6.5 : 5.5;
      return { x: x0 + w / 2, y: y0 + h + 6, half: (n - 1) * k + (art('b0_down') ? 11 : 7), h: art('b0_down') ? 22 : 16 }; }
    if (th.kind === 'beast') return art('beast_stand') ? { x: x0 + w + 6, y: y0 + h + 4, half: 27, h: 44 } : { x: x0 + w + 6, y: y0 + h + 2, half: 26, h: 30 };
    return null;
  }

  function draw(b, t, layout, sec) {
    const list = (t.view && t.view.threats) || [];
    for (const th of list) {
      const id = th.state === 'here' ? th.location : th.target, bx = id && layout.box[id];
      if (!bx) continue;
      const jolt = (window.Combat && th.state === 'here' && Combat.threat(th.id)) || { dx: 0, flash: false }, jx = Math.round(jolt.dx);
      const [x0, y0, w, h] = bx, cx = x0 + w / 2 + jx, foot = y0 + h + 6;
      if (th.state === 'coming') {               // warned: a red pennant flutters over the target house
        const img = sprite(FLAG, Math.sin(sec * 5) > 0);
        put(b, img, cx + 10, y0 + 4 + Math.round(Math.sin(sec * 2) * 1), 2);
        continue;
      }
      if (th.kind === 'raid') {
        const n = Math.max(1, Math.ceil(4 * th.hp / (th.max_hp || 1)));
        if (art('b0_down')) {   // the bandit sheet (viewer/art/bandits.png): six looks, picked by the band's id
          const seed = [...String(th.id)].reduce((a, c) => a + c.charCodeAt(0), 0);
          for (let i = 0; i < n; i++) {
            const x = cx + (i - (n - 1) / 2) * 13, k = (seed + i) % 6, fight = jolt.busy;
            const face = jolt.target != null ? Math.sign(jolt.target - x) || jolt.face : jolt.face;
            const pose = fight ? 'side' : Math.floor(sec * 3 + i) % 2 ? 'step' : 'down';
            const bob = Math.round(Math.abs(Math.sin(sec * 5 + i * 1.7)) * (jolt.act === 'strike' ? 0 : 1));
            pic(b, `b${k}_${pose}`, x, foot + (i % 2) * 3 - bob, pose === 'side' && face < 0, jolt.flash);
            if (i === 0) Sprites.draw(b, 'fx_torch', x + (pose === 'side' && face < 0 ? -6 : 6), foot - 7 - bob, { s: .9 + .1 * Math.sin(sec * 17) });
          }
          bar(b, cx, foot - 28, th.hp, th.max_hp);
          continue;
        }
        for (let i = 0; i < n; i++) {
          const x = cx + (i - (n - 1) / 2) * 11, bob = Math.round(Math.abs(Math.sin(sec * 5 + i * 1.7)) * 2);
          put(b, sprite(BANDIT, i % 2 === 1, jolt.flash), x, foot + (i % 2) * 3 - bob);
        }
        bar(b, cx, foot - 20, th.hp, th.max_hp);
        // a torch in the first raider's hand
        const fx = cx - (n - 1) * 5.5 + 7, fy = foot - 15 - Math.round(Math.abs(Math.sin(sec * 5)) * 2);
        b.fillStyle = '#7a5232'; b.fillRect(Math.round(fx), fy, 1, 6);
        b.fillStyle = (sec * 8 | 0) % 2 ? '#ffd23f' : '#ff9f1c'; b.fillRect(Math.round(fx) - 1, fy - 3, 3, 3);
        b.fillStyle = '#e4572e'; b.fillRect(Math.round(fx), fy - 4, 1, 1);
      } else if (th.kind === 'beast') {
        const step = Math.round(Math.sin(sec * 1.3) * 4), bob = Math.round(Math.abs(Math.sin(sec * 4)) * 1);
        const bxs = x0 + w + 6 + (jolt.dx || jolt.flash ? jx : step / 2);   // beside the house, so the defenders at the door face it
        if (art('beast_stand')) {   // the beast sheet (viewer/art/beast.png): drawn facing left
          const hurt = th.hp < (th.max_hp || 1) * .3, roar = !jolt.act && sec % 7 < .7;
          const f = jolt.act === 'hit' ? 'beast_flinch' : jolt.act === 'strike' ? (Math.floor(sec / 1.6) % 2 ? 'beast_bite' : 'beast_swipe')
            : roar ? 'beast_roar' : hurt ? 'beast_limp' : ['beast_walk1', 'beast_walk2', 'beast_walk3', 'beast_walk2'][Math.floor(sec * 4) % 4];
          pic(b, f, bxs, y0 + h + 4, jolt.face > 0, jolt.flash);
          bar(b, bxs, y0 + h - 50, th.hp, th.max_hp);
          continue;
        }
        put(b, sprite(BEAST, false, jolt.flash), bxs, y0 + h + 2 - bob, 2);
        bar(b, bxs, y0 + h - 36, th.hp, th.max_hp);
      } else if (th.kind === 'traveler') {
        const bob = Math.round(Math.abs(Math.sin(sec * 2)) * 1);
        put(b, sprite(TRAVELER), x0 + w * 0.7, y0 + h * 0.75 - bob);
      }
    }
  }
  return { draw, spot };
})();
window.ThreatLayer = ThreatLayer;
