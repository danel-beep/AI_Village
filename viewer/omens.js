// God-mode omens: the viewer plays slightly behind the simulation, so a god action pressed now lands in the world a
// little later on screen. Instead of nothing happening, an omen starts right away where it will strike (smoke and
// sparks on the house about to burn, a glint where treasure will lie, sparkles around a villager...) and grows
// until the tick that carries the god event (row.god) is on screen; then the real effect takes over.
// viewer/god.js fires `god-pending` {name, args}; PixelMap.draw calls Omens.draw every frame.
const Omens = (() => {
  const list = [];
  window.addEventListener('god-pending', e => list.push({ ...e.detail, born: performance.now() / 1000 }));
  const key = o => o.name + '|' + ((o.args || {}).person || (o.args || {}).location || (o.args || {}).to || '');
  // Person target -> sparkle colours.
  const TINT = { gift: ['#ffd23f', '#fff6b0'], sickness: ['#9bd65a', '#5e8c31'], rumor: ['#e8e8f0', '#c4c4cc'] };

  function draw(b, t, L, posOf, sec) {
    const { R, P, blob, rnd } = PixelMap.gfx, done = new Set((t.god || []).map(key));
    for (let k = list.length - 1; k >= 0; k--) if (done.has(key(list[k])) || sec - list[k].born > 120) list.splice(k, 1);
    for (const o of list) {
      const a = sec - o.born, u = Math.min(1, a / 8), args = o.args || {};
      if (o.name === 'fire') {
        const bx = L.box['home_' + args.person]; if (!bx) continue;
        const [x0, y0, w, h] = bx;
        for (let i = 0; i < 4 + Math.round(6 * u); i++) {   // dark smoke thickening over the roof
          const p = (sec * .45 + i / 10) % 1, r = 2.5 + p * (4 + 4 * u);
          b.globalAlpha = (.45 + .4 * u) * (1 - p);
          blob(b, x0 + w * (.3 + .4 * rnd(i, 5)) + Math.sin((p + i) * 5) * 3, y0 + h * .2 - p * (16 + 14 * u), r, r, ['#6a6a76', '#4e4e5a', '#34343f'], null);
        }
        b.globalAlpha = 1;
        for (let i = 0; i < 4 + Math.round(8 * u); i++) {   // sparks flicker at the walls
          if (rnd(i, Math.floor(sec * 8)) > .35 + .4 * u) continue;
          R(b, Math.round(x0 + 3 + rnd(i, 7) * (w - 6)), Math.round(y0 + h * (.5 + .45 * rnd(i, 8)) - (sec * 9 + i * 3) % 8), 2, 2, i % 2 ? '#ffd23f' : '#ff7b1c');
        }
        continue;
      }
      const at = args.person && posOf(args.person) || args.location && L.anchors[args.location];
      if (!at) continue;
      const cols = TINT[o.name] || (o.name === 'treasure' ? ['#ffd23f', '#ffffff'] : ['#bfe3ff', '#ffffff']);
      const [cx, cy] = args.person ? [at[0], at[1] - 10] : at, n = 4 + Math.round(4 * u), rr = args.person ? 9 : 14;
      for (let i = 0; i < n; i++) {
        const ang = sec * 2 + i / n * 6.28, x = Math.round(cx + Math.cos(ang) * rr), y = Math.round(cy + Math.sin(ang) * rr * .5);
        R(b, x, y, 2, 2, cols[i % 2]);
        if ((i + Math.floor(sec * 6)) % 3 === 0) { P(b, x - 1, y, cols[1]); P(b, x + 2, y + 1, cols[1]); P(b, x, y - 1, cols[1]); P(b, x + 1, y + 2, cols[1]); }
      }
      if (o.name === 'drought') { b.globalAlpha = .12 + .15 * u; R(b, cx - 24, cy - 14, 48, 28, '#e8b04a'); b.globalAlpha = 1; }
    }
  }
  return { draw, pending: () => list.length };
})();
if (typeof window !== 'undefined') window.Omens = Omens;
