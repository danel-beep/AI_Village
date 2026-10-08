// Fights on the pixel map, played from the tick's events: villager against villager (`fight`, conflict.py),
// villagers against bandits or the beast (`defend`, threats.py), the beast or bandits striking a house
// (`beast_attack`, `plundered`), hunters striking at game (`hunt_*`, animals.py) and thefts (`steal`).
// Every blow of the log is played in order on wall-clock time from the moment its tick shows: wind-up, lunge,
// a flash and a star where it lands, the one hit recoils and shakes, a red number floats up (or «мимо» and a
// dodge). A brawl ends with the loser lying with dizzy stars and the winner cheering. A theft shows the item
// flying into the thief's pocket and a red «!» over whoever saw it. A fight plays on after its tick (see below).
// Combat.plan(t) is pure (tests run it with node); PixelMap calls frame / stand / pose / draw / overlay, Actors
// paints the pose (weapon swing, fist, lying down) and ThreatLayer asks Combat.threat() how its sprite jolts.
const Combat = (() => {
  const T = id => 'T:' + id;   // a threat as a fighter
  const MISS = 'мимо';

  // ---------- the choreography of tick t (pure) ----------
  function plan(t) {
    const duels = [], raids = {}, strikes = [], hunts = [], thefts = [];
    for (const e of (t && t.events) || []) {
      const d = e.data || {};
      if (e.kind === 'fight' && d.attacker && d.defender) {
        const blows = (d.rounds || []).map(r => ({ by: r.by, on: r.by === d.attacker ? d.defender : d.attacker, hit: !!r.hit, dmg: r.damage || 0 }));
        if (!blows.length) blows.push({ by: d.attacker, on: d.defender, hit: true, dmg: 0 });
        const winner = d.winner || d.attacker;
        duels.push({ a: d.attacker, d: d.defender, loc: e.location, blows, winner, loser: winner === d.attacker ? d.defender : d.attacker,
          weapons: d.weapons || {} });
      } else if (e.kind === 'defend' && e.actor && d.threat) {
        const r = raids[d.threat] || (raids[d.threat] = { threat: d.threat, kind: d.threat_kind, loc: e.location, fighters: [], blows: [], weapons: {} });
        if (!r.fighters.includes(e.actor)) r.fighters.push(e.actor);
        r.weapons[e.actor] = d.weapon || null;
        r.blows.push({ by: e.actor, on: T(d.threat), hit: !!d.hit, dmg: d.damage || 0 });
        if (d.hurt) r.blows.push({ by: T(d.threat), on: e.actor, hit: true, dmg: d.hurt });
      } else if (e.kind === 'beast_attack' && d.threat && d.victim) {   // the beast mauls someone at the house
        const r = raids[d.threat] || (raids[d.threat] = { threat: d.threat, kind: 'beast', loc: d.home, fighters: [], blows: [], weapons: {} });
        if (!r.fighters.includes(d.victim)) r.fighters.push(d.victim);
        r.blows.push({ by: T(d.threat), on: d.victim, hit: true, dmg: d.damage || 0 });
      } else if ((e.kind === 'beast_attack' || e.kind === 'plundered') && d.threat) {
        strikes.push({ threat: d.threat, kind: e.kind === 'plundered' ? 'raid' : 'beast', loc: d.home || d.location || e.location });
      } else if (/^hunt_(catch|miss|kill)$/.test(e.kind)) {
        const who = d.hunters || [e.actor], w = d.weapons || { [e.actor]: d.weapon };
        for (const n of who) if (n && !hunts.some(h => h.n === n))
          hunts.push({ n, loc: e.location, weapon: w[n] || null, win: e.kind !== 'hunt_miss' && (e.kind !== 'hunt_kill' || d.killer === n) });
      } else if (e.kind === 'steal' && e.actor && d.success) {
        thefts.push({ n: e.actor, victim: d.victim, item: d.item || 'coins', loc: e.location,
          seen: [...new Set([...(d.witnesses || []), ...(d.seen_by || [])])] });
      }
    }
    return { duels, raids: Object.values(raids), strikes, hunts, thefts };
  }

  // ---------- fights on screen ----------
  // A fight outlives its tick: the log puts all its blows in one quarter hour, which replay shows for a fraction of a
  // second. So each fight plays at a readable beat from the moment its tick shows; the next tick's blows against the
  // same bandits or beast join the queue (the oldest are skipped when it grows long); scrubbing clears everything.
  const BEAT = .55, QUEUE = 8, AFTER = 2.5, LINGER = 2.5;
  let live = [], tickId = null, now = 0, spots = {};
  let threatSpot = () => null, anchor = () => null;
  const endOf = f => f.born + f.blows.length * f.beat;

  function absorb(p, sec) {
    for (const d of p.duels) {
      const key = 'd:' + d.a + ':' + d.d, prev = live.filter(f => f.key === key).pop();
      live.push({ ...d, type: 'duel', key, beat: BEAT, born: prev ? Math.max(sec, endOf(prev)) : sec });
    }
    for (const r of p.raids) {
      const key = 'r:' + r.threat, f = live.find(x => x.key === key && sec < endOf(x) + .5);
      if (!f) { live.push({ ...r, type: 'raid', key, beat: BEAT, born: sec }); continue; }
      for (const n of r.fighters) if (!f.fighters.includes(n)) f.fighters.push(n);
      Object.assign(f.weapons, r.weapons); f.blows.push(...r.blows);
      const left = f.blows.length - Math.max(0, Math.floor((sec - f.born) / f.beat));
      if (left > QUEUE) f.born -= (left - QUEUE) * f.beat;   // fast playback: skip ahead, keep the newest blows
    }
    for (const [type, list, id] of [['strike', p.strikes, x => x.threat], ['hunt', p.hunts, x => x.n], ['theft', p.thefts, x => x.n]])
      for (const x of list) {
        const key = type + ':' + id(x), f = live.find(y => y.key === key);
        if (f) Object.assign(f, x, { until: sec + LINGER }); else live.push({ ...x, type, key, born: sec, until: sec + LINGER });
      }
  }

  // Called once per frame before the villagers are placed: takes in a newly shown tick, drops finished fights and
  // works out where every fighter stands.
  function frame(t, layout, sec, hourSec, spotOfThreat) {
    now = sec;
    const id = t ? t.tick : null;
    if (id !== tickId) {
      if (id == null || tickId == null || id < tickId || id > tickId + 8) live = [];   // a jump: start clean
      tickId = id; if (t) absorb(plan(t), sec);
    }
    live = live.filter(f => f.until != null ? sec < f.until : sec < endOf(f) + (f.type === 'duel' ? AFTER : .5));
    anchor = loc => layout.anchors[loc];
    threatSpot = id => spotOfThreat && spotOfThreat(id);
    spots = {};
    const used = {};
    for (const d of live) if (d.type === 'duel' && sec >= d.born && !spots[d.a]) {   // the pair squares off at the place
      const a = anchor(d.loc); if (!a) continue;
      const k = used[d.loc] = (used[d.loc] || 0) + 1, x = a[0] + (k - 1) * 40 - 4, y = a[1] + 30 + (k - 1) * 8;   // below the spot where the others stand
      spots[d.a] = { x: x - 11, y, dir: 'right' }; spots[d.d] = { x: x + 11, y, dir: 'left' };
    }
    for (const r of live) if (r.type === 'raid') {   // defenders line up facing the bandits or the beast
      const s = threatSpot(r.threat); if (!s) continue;
      r.fighters.forEach((n, i) => {
        const side = r.kind === 'beast' ? 1 : (i % 2 ? -1 : 1), j = r.kind === 'beast' ? i : i >> 1;
        spots[n] = spots[n] || { x: s.x + side * (s.half + 10 + (j % 3) * 14), y: s.y + 2 + Math.floor(j / 3) * 9, dir: side > 0 ? 'left' : 'right' };
      });
    }
  }

  // Where a fighting villager stands now (map pixels, feet) or null.
  const stand = n => spots[n] || null;

  // The blow fight f is at now, and the part `who` plays in it.
  function phase(f, who) {
    const el = now - f.born, i = Math.floor(el / f.beat);
    if (el < 0) return { wait: true, el };
    if (i >= f.blows.length) return { done: true, el: el - f.blows.length * f.beat };
    const b = f.blows[i], u = (el - i * f.beat) / f.beat;
    return { b, u, i, me: b.by === who ? 'by' : b.on === who ? 'on' : null };
  }

  const ease = u => u * u * (3 - 2 * u);
  // The swing of one blow for the striker: dx forward, weapon angle; for the one struck: recoil or dodge.
  function motion(ph, face) {
    const { u, b, me } = ph;
    if (me === 'by') {
      const fwd = u < .3 ? -ease(u / .3) * 1.5 : u < .45 ? -1.5 + ease((u - .3) / .15) * 6.5 : 5 * (1 - ease((u - .45) / .55));
      const ang = u < .3 ? -.4 - ease(u / .3) * 1.9 : u < .45 ? -2.3 + ease((u - .3) / .15) * 3.1 : .8 - ease((u - .45) / .55) * 1.2;
      return { dx: face * fwd, dy: u > .3 && u < .45 ? -1 : 0, ang, jab: u > .38 && u < .62 };
    }
    if (me === 'on') {
      if (u < .45) return { dx: 0, dy: 0, ang: -.4, guard: true };
      const p = (u - .45) / .55;
      if (!b.hit) return { dx: -face * Math.sin(p * Math.PI) * 3, dy: -Math.round(Math.sin(p * Math.PI) * 3), ang: -.4, guard: true };
      const shake = p < .35 ? ((Math.floor(now * 40) % 2) ? 1 : -1) : 0;
      return { dx: -face * (1 - ease(p)) * 4 + shake, dy: 0, ang: .4, hurt: p < .5 };
    }
    return { dx: 0, dy: Math.floor(now * 4) % 2, ang: -.4, guard: true };   // waiting its turn, on guard
  }

  // The pose of villager n this frame ({dx, dy, ang, weapon, lying, cheer, ...}) or null when not fighting.
  function pose(n) {
    for (const f of live) {
      if (f.type === 'duel' && (n === f.a || n === f.d)) {
        const face = (spots[n] || {}).dir === 'left' ? -1 : 1, ph = phase(f, n), weapon = f.weapons[n] || null;
        if (ph.wait) continue;
        if (ph.done) {
          if (n === f.loser) return { dx: 0, dy: 0, lying: true, weapon, face };
          return { dx: 0, dy: -Math.round(Math.abs(Math.sin(ph.el * 7)) * 2), cheer: true, weapon, face };
        }
        return { ...motion(ph, face), weapon, face };
      }
      if (f.type === 'raid' && f.fighters.includes(n)) {
        const face = (spots[n] || {}).dir === 'left' ? -1 : 1, ph = phase(f, n), weapon = f.weapons[n];
        if (ph.done || ph.wait) return { dx: 0, dy: 0, ang: -.4, guard: true, weapon, face };
        return { ...motion(ph, face), weapon, face };
      }
      if (f.type === 'hunt' && f.n === n) {   // hunters jab at the game again and again
        const u = ((now - f.born) / .9 + (n.length % 3) * .3) % 1;
        return { ...motion({ u, b: { hit: true }, me: 'by' }, 1), weapon: f.weapon, face: 1, hunt: true };
      }
    }
    return null;
  }

  // How a threat's sprite moves now: {dx, flash, face, act}. dx: lunge or recoil; flash: a blow just landed on it
  // (white); face: -1 left / 1 right, towards whoever it fights; act: 'strike' while it hits, 'hit' while it reels.
  function threat(id) {
    const me = T(id), s = threatSpot(id);
    for (const f of live) {
      if (f.type === 'raid' && f.threat === id) {
        const xs = f.fighters.map(n => spots[n] && spots[n].x).filter(x => x != null);
        const side = s && xs.length ? Math.sign(xs.reduce((a, x) => a + x, 0) / xs.length - s.x) || -1 : -1;
        const ph = phase(f, me);
        if (ph.done || ph.wait || !ph.me) return { dx: 0, flash: false, face: side, act: null, busy: true };
        const target = ph.me === 'by' ? spots[ph.b.on] : spots[ph.b.by];
        const face = target && s ? Math.sign(target.x - s.x) || side : side, m = motion(ph, face);
        const hit = ph.me === 'on' && ph.b.hit && ph.u > .45;
        return { dx: m.dx * (ph.me === 'by' ? 1.6 : 1), flash: hit && ph.u < .6, face, target: target ? target.x : null, busy: true,
          act: ph.me === 'by' && ph.u > .25 && ph.u < .75 ? 'strike' : hit && ph.u < .85 ? 'hit' : null };
      }
      if (f.type === 'strike' && f.threat === id) {   // at the house, which is on its left
        const u = ((now - f.born) / .8) % 1;
        return { dx: motion({ u, b: { hit: true }, me: 'by' }, -1).dx * 1.6, flash: false, face: -1, act: u > .25 && u < .75 ? 'strike' : null };
      }
    }
    return { dx: 0, flash: false, face: -1, act: null };
  }

  // ---------- drawing into the low-res map buffer (after villagers and threats) ----------
  const STAR = [[0, -3], [0, -2], [0, 2], [0, 3], [-3, 0], [-2, 0], [2, 0], [3, 0], [-2, -2], [2, -2], [-2, 2], [2, 2], [0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]];
  function star(b, x, y, k) {
    if (window.Sprites && (Sprites.draw(b, 'fx_star', x, y + 4, { s: .7 + k * .5, alpha: 1 - k * .5 }) || Sprites.draw(b, 'hit_star', x, y + 6, { s: .55 + k * .25 }))) return;
    b.fillStyle = '#fff6b0'; STAR.forEach(([dx, dy]) => b.fillRect(Math.round(x + dx * (1 + k)), Math.round(y + dy * (1 + k)), 1, 1));
  }
  function dust(b, x, y, p) {
    if (window.Sprites && Sprites.draw(b, 'fx_dust', x, y + 2, { s: .6 + p * .6, alpha: .8 * (1 - p) })) return;
    b.globalAlpha = .55 * (1 - p); b.fillStyle = '#d8ccb4';
    for (let i = 0; i < 5; i++) b.fillRect(Math.round(x + (i - 2) * (2 + p * 4)), Math.round(y - p * 3 - (i % 2)), 2, 1);
    b.globalAlpha = 1;
  }
  function dizzy(b, x, y) {
    if (window.Sprites && Sprites.draw(b, 'fx_dizzy', x, y + 3, { s: .8 + Math.sin(now * 6) * .08, flip: Math.floor(now * 3) % 2 === 1 })) return;
    for (let i = 0; i < 3; i++) { const a = now * 4 + i * 2.1;
      b.fillStyle = i % 2 ? '#ffd23f' : '#fff6b0'; b.fillRect(Math.round(x + Math.cos(a) * 5), Math.round(y + Math.sin(a) * 2), 2, 2); }
  }
  // Where a fighter is drawn (villager mid-body, or a threat's body centre), given the villagers' positions.
  function at(who, posOf) {
    if (who.startsWith('T:')) { const s = threatSpot(who.slice(2)); return s && { x: s.x, y: s.y - s.h / 2 }; }
    const p = posOf(who); return p && { x: p[0], y: p[1] };   // posOf: mid-body, feet are 16 px lower
  }
  function blowsFx(b, f, posOf) {
    const ph = phase(f, null); if (ph.done || ph.wait) return;
    const { b: bl, u } = ph, by = at(bl.by, posOf), on = at(bl.on, posOf);
    if (by && u > .3 && u < .7) dust(b, by.x, by.y + 15, (u - .3) / .4);
    if (by && on && u > .3 && u < .45 && f.weapons && f.weapons[bl.by] === 'bow' && window.Sprites) {   // the arrow in flight
      const q = (u - .3) / .15;
      Sprites.draw(b, 'fx_arrow', by.x + (on.x - by.x) * q, by.y + 2 + (on.y - by.y) * q, { s: .8, flip: on.x < by.x });
    }
    if (!on || u < .45) return;
    const p = (u - .45) / .55;
    const S = window.Sprites, side = by ? Math.sign(by.x - on.x) || 1 : 1;
    if (bl.hit && p < .45 && S && (bl.by.startsWith('T:') || f.weapons && f.weapons[bl.by]))   // a slash across the one hit
      S.draw(b, bl.by.startsWith('T:') ? 'fx_slash_red' : 'fx_slash', on.x - side * 2, on.y + 6, { s: .8, flip: side > 0, alpha: 1 - p / .45 });
    if (!bl.hit && p < .5 && S) S.draw(b, 'fx_puff', on.x - side * 6, on.y + 10, { s: .7, flip: side > 0, alpha: 1 - p / .5 });
    if (bl.hit && p < .45) {
      star(b, on.x + side * 3, on.y - 1, p / .45);
      if (p < .2) { b.globalAlpha = .7; b.fillStyle = '#ffffff'; b.fillRect(Math.round(on.x) - 4, Math.round(on.y) - 4, 9, 9); b.globalAlpha = 1; }
    }
  }
  function arc(b, x0, y0, x1, y1, p, h, col) {   // a small thing flying in an arc
    const x = x0 + (x1 - x0) * p, y = y0 + (y1 - y0) * p - Math.sin(p * Math.PI) * h;
    b.fillStyle = '#1b1b24'; b.fillRect(Math.round(x) - 2, Math.round(y) - 2, 5, 5);
    b.fillStyle = col; b.fillRect(Math.round(x) - 1, Math.round(y) - 1, 3, 3);
    b.fillStyle = '#ffffff'; b.fillRect(Math.round(x) - 1, Math.round(y) - 1, 1, 1);
  }
  const ITEM_COL = { coins: '#ffd23f', bread: '#d9a066', fish: '#c8d8e8', berries: '#e4572e', meat: '#c0392b', wood: '#9c6b40', ore: '#8a8a9a' };

  function draw(b, posOf) {
    for (const f of live) {
      if (f.type === 'duel' || f.type === 'raid') blowsFx(b, f, posOf);
      if (f.type === 'duel' && phase(f, null).done) { const p = posOf(f.loser); if (p) dizzy(b, p[0], p[1] + 6); }
      if (f.type === 'strike') {   // the beast or bandits hit the house: a star on its wall every lunge
        const sp = threatSpot(f.threat), a = anchor(f.loc), u = ((now - f.born) / .8) % 1;
        if (sp && u > .45 && u < .7) star(b, sp.x - sp.half - 4, sp.y - sp.h / 2, (u - .45) / .25);
        else if (!sp && a && u > .45 && u < .7) star(b, a[0], a[1] - 10, (u - .45) / .25);
      }
      if (f.type === 'theft') {   // the item leaves the victim (or the place) and lands in the thief's pocket
        const to = posOf(f.n); if (!to) continue;
        const v = f.victim && posOf(f.victim), a = anchor(f.loc), from = v || (a && [a[0], a[1] + 4]) || [to[0] + 14, to[1]];
        const p = ((now - f.born) / 1.6) % 1;
        if (p < .7) arc(b, from[0], from[1] - 4, to[0], to[1] - 2, p / .7, 10, ITEM_COL[f.item] || '#e8c090');
      }
    }
  }

  // ---------- full-resolution text: damage numbers, «мимо», «!» over witnesses ----------
  function overlay(ctx, toScreen, posOf) {
    const text = (s, x, y, size, col) => {
      ctx.font = `900 ${size}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.lineWidth = 4; ctx.strokeStyle = '#1b1b24';
      ctx.strokeText(s, x, y); ctx.fillStyle = col; ctx.fillText(s, x, y); ctx.textAlign = 'left';
    };
    for (const f of live) {
      if (f.blows) f.blows.forEach((bl, i) => {   // every blow that landed keeps its number for a second
        const p = now - f.born - (i + .45) * f.beat, w = p >= 0 && p < 1 && at(bl.on, posOf); if (!w) return;
        const [sx, sy] = toScreen(w.x, w.y - 8);
        ctx.globalAlpha = Math.min(1, 2.5 * (1 - p));
        text(bl.hit ? (bl.dmg ? '-' + bl.dmg : '!') : MISS, sx, sy - p * 22, 15, bl.hit ? '#ff5a4a' : '#d0d0d8');
        ctx.globalAlpha = 1;
      });
      if (f.type === 'theft') for (const n of f.seen) {
        const p = posOf(n); if (!p) continue;
        const [sx, sy] = toScreen(p[0], p[1] - 22);
        text('!', sx, sy + Math.round(Math.sin(now * 12)), 18, '#ff4136');
      }
    }
  }

  return { plan, frame, stand, pose, threat, draw, overlay, MISS };
})();
if (typeof window !== 'undefined') window.Combat = Combat;
if (typeof module !== 'undefined') module.exports = Combat;
