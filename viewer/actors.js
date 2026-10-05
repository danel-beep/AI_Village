// Villagers on the pixel map: what each one is doing this hour, how it looks, and their speech/thought bubbles.
// The activity comes only from the log (the villager's own events in the tick: work, move, craft, eat, extinguish...).
// Loops run on wall-clock time, so villagers keep chopping, fishing or strolling while the next tick is awaited.
// Drawing helpers and the map layout come from PixelMap (viewer/pixelmap.js), which calls in here every frame.
const Actors = (() => {
  // Event kind -> animation. Work events name the resource in their text ("You gathered 3 wood.").
  const WORK = { grain: 'farm', wood: 'chop', berries: 'gather', stone: 'mine', ore: 'mine', fish: 'fish', water: 'water' };
  const KIND = { move: 'walk', extinguish: 'pour', fire_out: 'pour', pour_water: 'pour', craft: 'craft', eat: 'eat',
    buy: 'trade', sell: 'trade', fulfill_order: 'trade', contribute: 'trade', say: 'talk', whisper: 'talk', offer: 'talk',
    trade: 'talk', decline: 'talk', give: 'talk', lend: 'talk', repay: 'talk', steal: 'sneak', theft: 'sneak',
    plant: 'sow', harvest: 'farm' };
  const PRI = { walk: 9, pour: 8, sneak: 7, craft: 6, sow: 5, chop: 5, mine: 5, farm: 5, fish: 5, water: 5, gather: 5, eat: 4,
                trade: 3, talk: 2 };
  const SHADOW = ['rgba(0,0,0,.25)', 'rgba(0,0,0,.25)', 'rgba(0,0,0,.25)'];
  const gx = () => PixelMap.gfx;
  const ease = u => u * u * (3 - 2 * u);

  // ---------- what everyone is doing during tick t ----------
  function activities(t) {
    const out = {};
    for (const e of t.events || []) {
      if (!e.actor) continue;
      const d = e.data || {}, res = d.resource || (/gathered \d+ (\w+)|no (\w+) left/.exec(e.text) || []).slice(1).find(Boolean);
      const act = e.kind === 'work' ? WORK[res] : KIND[e.kind], slot = e.kind === 'plant' ? d.slot : (d.slots || [])[0];
      if (act && (!out[e.actor] || PRI[act] > PRI[out[e.actor].act])) out[e.actor] = { act, text: e.text || '', res, slot };
    }
    for (const [n, d] of Object.entries(t.decisions || {})) {
      const args = (d.action || {}).args || {}, to = args.to || args.person || args.target;
      if (out[n] && to) out[n].to = to;
      if (!out[n] && d.say) out[n] = { act: 'talk', text: '' };
    }
    return out;
  }

  // Where a villager stands for an activity: [x, y, dir, atObject] in map pixels, or null for the usual spot.
  // With the map layer (viewer/maplayer.js) work happens at the very tree, bed, bush or rock the log names.
  function workSpot(act, loc, k, L, info = {}) {
    const o = info.slot != null && window.MapLayer && MapLayer.spotOf && MapLayer.spotOf(loc, info.res, info.slot);
    if (o && act === 'chop') return [o[0] + 6, o[1] + 23, 'right', true];
    if (o && (act === 'farm' || act === 'sow')) return [o[0] + 6 + (k * 9) % Math.max(1, o[2] - 12), o[1] + o[3] / 2 - 4, k % 2 ? 'left' : 'right', true];
    if (o && (act === 'gather' || act === 'mine')) return [o[0] - 3, o[1] + (act === 'mine' ? 7 : 5), 'right', true];
    const a = L.anchors[loc]; if (!a) return null;
    const ring = (pts) => { const [dx, dy, dir] = pts[k % pts.length]; return [a[0] + dx, a[1] + dy, dir]; };
    const rv = loc === 'river' && L.gen && L.gen.river;   // generated map: the river can be on either side
    if (rv && (act === 'fish' || act === 'water')) {
      const T = L.T || 16, left = rv.side === 'left', face = left ? 'left' : 'right', d = rv.dock;
      if (act === 'fish') {   // on the dock planks, the outermost first, facing the water
        const xs = [...d.x].sort((p, q) => left ? p - q : q - p), x = xs[k % xs.length];
        return [x * T + 8 + (left ? -2 : 2), d.y * T + 6 + (k >= xs.length ? 10 : 0), face];
      }
      const y = Math.max(0, Math.min(rv.x.length - 1, d.y + 2 + (k % 3)));   // on the bank just below the dock
      return [left ? (rv.x[y] + 3) * T + 4 : rv.x[y] * T - 4, y * T + 8, face];
    }
    if (act === 'fish' && loc === 'river') return [24 + (k % 4) * 9, 148, 'left'];
    if (act === 'water' && loc === 'river') return [56, 118 + (k % 3) * 9, 'left'];
    if (act === 'farm' && loc === 'field') return [[96, 112, 154, 168][k % 4], 60 + ((k >> 2) % 3) * 22, k % 2 ? 'left' : 'right'];
    if (act === 'chop') return ring([[-16, 2, 'right'], [16, 2, 'left'], [-18, 16, 'right'], [18, 16, 'left'], [0, 18, 'right']]);
    if (act === 'gather') return ring([[-30, 18, 'left'], [30, 18, 'right'], [-30, 30, 'left'], [30, 30, 'right']]);
    if (act === 'mine') return ring([[-14, 4, 'right'], [12, 6, 'right'], [-24, 12, 'left'], [22, 12, 'right']]);
    if (act === 'craft' && loc === 'smithy') return ring([[13, -2, 'right'], [-6, 4, 'right'], [-18, 2, 'right']]);
    if (act === 'trade' && loc === 'market') return ring([[-36, -12, 'up'], [0, -12, 'up'], [36, -12, 'up'], [-18, -6, 'up']]);
    if (act === 'pour') return ring([[-12, -2, 'up'], [12, -2, 'up'], [0, 2, 'up'], [-24, 2, 'up'], [24, 2, 'up']]);
    return null;
  }

  // Idle stroll: a new small target every ~4 s, walked to in 1.2 s, then a look around. Stateless and continuous.
  function wander(seed, sec) {
    const { rnd } = gx(), L = 4, s = sec / L + seed * 7.3, k = Math.floor(s), u = s - k;
    const pt = j => [(rnd(j, seed, 31) - .5) * 22, (rnd(j, seed, 32) - .5) * 10];
    const [ax, ay] = pt(k - 1), [bx, by] = pt(k), w = Math.min(1, u * L / 1.2), f = ease(w);
    const dx = bx - ax, dy = by - ay, moving = w < 1 && Math.hypot(dx, dy) > 2;
    const dir = moving ? (Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : dy > 0 ? 'down' : 'up')
                       : ['down', 'left', 'down', 'right', 'down'][rnd(k, seed, 33) * 5 | 0];
    return { dx: ax + dx * f, dy: ay + dy * f, moving, dir };
  }

  // ---------- small drawing helpers (low-res buffer, local coordinates: forward is +x) ----------
  function line(b, x0, y0, x1, y1, c) {
    const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) | 0 || 1;
    for (let i = 0; i <= n; i++) gx().P(b, Math.round(x0 + (x1 - x0) * i / n), Math.round(y0 + (y1 - y0) * i / n), c);
  }
  // A tool on a handle from the hand (hx, hy) at angle `ang` (radians, screen coords, 0 = forward).
  function tool(b, hx, hy, ang, len, kind) {
    const { P, C } = gx(), c = Math.cos(ang), s = Math.sin(ang), nx = -s, ny = c;
    line(b, hx, hy, hx + c * len, hy + s * len, C.wood);
    const ex = hx + c * len, ey = hy + s * len, at = (i, j, col) => P(b, Math.round(ex + c * i + nx * j), Math.round(ey + s * i + ny * j), col);
    if (kind === 'axe') { for (let i = -1; i <= 0; i++) for (let j = 0; j <= 2; j++) at(i, j, j === 2 ? '#e8e8f0' : '#8a8a94'); }
    else if (kind === 'pick') { for (let j = -2; j <= 2; j++) at(0, j, Math.abs(j) === 2 ? '#c4c4cc' : '#7c7c88'); at(-1, 0, '#7c7c88'); }
    else if (kind === 'hoe') { for (let j = 0; j <= 2; j++) at(0, j, '#6f6f78'); at(1, 2, '#9a9aa2'); }
    else if (kind === 'hammer') { for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) at(i, j, '#5d5d6b'); }
  }
  // Swing cycle: slow raise, fast strike; impact at the start of each cycle. `since` = seconds since the last impact.
  function swing(sec, period, up, down) {
    const u = (sec / period) % 1, k = Math.floor(sec / period);
    const ang = u < .65 ? down + (up - down) * ease(u / .65) : up + (down - up) * ((u - .65) / .35) ** 2;
    return { ang, since: u * period, k };
  }
  // A short burst of flying bits (chips, sparks, clods, drops) from (ox, oy).
  function burst(b, ox, oy, since, n, cols, seed, spread = 22, life = .4) {
    if (since > life) return;
    const { rnd, P } = gx();
    b.globalAlpha = 1 - since / life;
    for (let i = 0; i < n; i++) {
      const vx = (rnd(i, seed, 41) - .25) * spread, vy = -(rnd(i, seed, 42) * .8 + .2) * spread;
      P(b, Math.round(ox + vx * since), Math.round(oy + vy * since + 60 * since * since), cols[i % cols.length]);
    }
    b.globalAlpha = 1;
  }
  function bucket(b, x, y, full) {
    const { R, P, C } = gx();
    R(b, x, y, 5, 4, C.k); R(b, x + 1, y, 3, 3, C.wood); if (full) R(b, x + 1, y, 3, 1, C.waterL);
    P(b, x - 1, y - 1, C.k); P(b, x + 5, y - 1, C.k); R(b, x, y - 2, 5, 1, C.k);
  }

  // ---------- poses: each returns optional back()/front() painters and a crouch/bob offset ----------
  const POSES = {
    chop(b, x, y, sec, a) {
      const { R, C } = gx(), s = swing(sec, .9, -2.3, .55);
      return { dy: s.since < .08 ? 1 : 0, front() {
        if (!a.real) { R(b, x + 7, y + 3, 7, 5, C.k); R(b, x + 8, y + 3, 5, 4, C.wood); R(b, x + 8, y + 3, 5, 1, '#e8c090'); }
        tool(b, x + 1, y + 1, s.ang, 7, 'axe');
        burst(b, x + 10, y + 2, s.since, 6, [C.woodL, '#e8c090', C.wood], s.k);
      } };
    },
    mine(b, x, y, sec, a) {
      const { blob, C } = gx(), s = swing(sec, 1, -2.2, .5), ore = a.loc === 'mine' && /ore/.test(a.text);
      return { dy: s.since < .08 ? 1 : 0, front() {
        if (!a.real) blob(b, x + 11, y + 5, 4, 3, [C.stoneL, C.stone, C.stoneD]);
        tool(b, x + 1, y + 1, s.ang, 7, 'pick');
        burst(b, x + 10, y + 3, s.since, 7, ore ? ['#fff6b0', '#ffd23f', C.stoneL] : [C.stoneL, '#fff6b0', C.stone], s.k, 26, .3);
      } };
    },
    sow(b, x, y, sec, a) {
      const { P } = gx(), u = (sec / 1.2) % 1, k = Math.floor(sec / 1.2);
      return { crouch: 1, front() { P(b, x + 4, y + (u < .3 ? 0 : 2), '#f2c9a0');
        burst(b, x + 6, y + 2, u * 1.2, 4, ['#e0c040', '#b8962c'], k, 8, .5); } };
    },
    farm(b, x, y, sec, a) {
      const { R, C } = gx(), s = swing(sec, 1.1, -1.9, .9);
      return { dy: s.since < .1 ? 1 : 0, back() { R(b, x + 5, y + 7, 9, 2, C.soilD); },
        front() { tool(b, x + 1, y + 1, s.ang, 8, 'hoe'); burst(b, x + 9, y + 7, s.since, 5, [C.soil, C.soilD, C.sprout], s.k, 16); } };
    },
    gather(b, x, y, sec, a) {
      const { blob, P, C } = gx(), u = (sec / 1.4) % 1, k = Math.floor(sec / 1.4);
      return { crouch: 2, front() {
        if (!a.real) { blob(b, x + 10, y + 3, 5, 4, [C.leafL, C.leaf, C.leafD]); P(b, x + 9, y + 2, '#e4572e'); P(b, x + 12, y + 4, '#e4572e'); }
        P(b, x + 5 + (u < .5 ? 2 : 0), y + 2, '#f2c9a0');
        if (u > .5) P(b, Math.round(x + 9 - (u - .5) * 10), Math.round(y + 1 - Math.sin((u - .5) * 6) * 3), '#ff4d3a');
        burst(b, x + 10, y + 1, (u * 1.4) % 1.4, 3, [C.leafL], k, 10, .25);
      } };
    },
    fish(b, x, y, sec, a) {
      const { P, R, C } = gx(), u = (sec / 6) % 1, k = Math.floor(sec / 6), catching = u > .82;
      const ang = catching ? -1.35 : -.85 + Math.sin(sec * 1.3) * .05, tx = x + 1 + Math.cos(ang) * 10, ty = y + 1 + Math.sin(ang) * 10;
      const bx = x + 14, by = y + 15 + Math.round(Math.sin(sec * 3) * .6 + (u > .7 && u < .82 ? 1 : 0));
      return { front() {
        line(b, x + 1, y + 1, tx, ty, C.woodD);
        if (!catching) { line(b, tx, ty, bx, by, 'rgba(230,230,230,.8)'); P(b, bx, by, '#e4572e'); P(b, bx, by - 1, '#f4f4f4'); }
        else { const p = (u - .82) / .18, fx = bx + (tx - bx) * p, fy = by + (ty - by) * p - Math.sin(p * Math.PI) * 8;
          line(b, tx, ty, fx, fy, 'rgba(230,230,230,.8)'); R(b, Math.round(fx) - 1, Math.round(fy), 3, 1, '#c8d8e8'); P(b, Math.round(fx) + 1, Math.round(fy) - 1, '#9ab0c8');
          burst(b, bx, by, (u - .82) * 6, 6, [C.waterL, '#ffffff'], k, 14, .35); }
      } };
    },
    water(b, x, y, sec, a) {
      const { C } = gx(), u = (sec / 1.8) % 1, k = Math.floor(sec / 1.8), down = u > .3 && u < .6;
      return { crouch: 3, front() {
        bucket(b, x + (down ? 7 : 4), y + (down ? 5 : 1), u > .6);
        if (u > .45) burst(b, x + 9, y + 6, (u - .45) * 1.8, 5, [C.waterL, '#ffffff'], k, 14, .35);
      } };
    },
    craft(b, x, y, sec, a) {
      const { blob, P, C } = gx();
      if (a.loc === 'smithy') { const s = swing(sec, .7, -1.9, .35);
        return { dy: s.since < .06 ? 1 : 0, front() { tool(b, x + 1, y + 1, s.ang, 6, 'hammer');
          burst(b, x + 8, y + 1, s.since, 8, ['#ffd23f', '#ff7b1c', '#fff6b0'], s.k, 30, .3); } };
      }
      const r = sec * 4;
      return { front() {
        blob(b, x + 10, y + 5, 4, 3, ['#5d5d6b', '#44444f', '#2a2a33']); P(b, x + 9, y + 3, '#d9a066'); P(b, x + 11, y + 3, '#e8c090');
        line(b, x + 3, y + 1, x + 10 + Math.cos(r) * 2, y + 3 + Math.sin(r), C.woodL);
        burst(b, x + 10, y + 1, (sec * .9) % 1, 3, ['#e8e8ee', '#d0d0d8'], Math.floor(sec * .9), 6, 1);
      } };
    },
    eat(b, x, y, sec, a) {
      const { R, P } = gx(), u = (sec / 1.6) % 1, f = u < .5 ? ease(u * 2) : 1 - ease((u - .5) * 2);
      const col = /soup/.test(a.text) ? '#c47a2c' : /fish/.test(a.text) ? '#c8d8e8' : /berr/.test(a.text) ? '#e4572e' : '#d9a066';
      return { front() { R(b, Math.round(x + 3 - f * 3), Math.round(y + 3 - f * 4), 3, 2, col);
        if (u > .45 && u < .55) { P(b, x - 2, y + 2, col); P(b, x + 2, y + 3, col); } } };
    },
    trade(b, x, y, sec, a) {
      const { P } = gx(), u = (sec / 1.2) % 1, cy = y - 4 - Math.round(Math.sin(u * Math.PI) * 6);
      return { dy: Math.round(Math.sin(sec * 3)) > 0 ? 1 : 0, front() { P(b, x + 4, cy, '#ffd23f'); P(b, x + 5, cy, u < .5 ? '#f7e26b' : '#b8962c'); } };
    },
    talk(b, x, y, sec, a) {
      const { P } = gx(), up = Math.floor(sec * 2.5) % 2;
      return { dy: Math.floor(sec * 3) % 3 === 0 ? 1 : 0, front() { if (a.dir !== 'up') P(b, x + 4, y + (up ? -1 : 1), '#f2c9a0'); } };
    },
    sneak(b, x, y, sec, a) { return { crouch: 2, dy: Math.floor(sec * 2) % 2 }; },
    pour(b, x, y, sec, a) {
      const { C, blob } = gx(), u = (sec / 1.5) % 1, k = Math.floor(sec / 1.5), [fx, fy] = a.target || [x, y - 30];
      return { front() {
        bucket(b, x - 2, y - 13 + (u < .55 ? Math.round(Math.sin(u * 12)) : -1), u < .55);
        if (u >= .55) {
          const p = (u - .55) / .45;
          for (let i = 0; i < 14; i++) {
            const q = Math.min(1, p * 1.6 - i * .045); if (q <= 0) continue;
            const wx = x + (fx - x) * q + Math.sin(i * 7.1) * 1.5, wy = y - 13 + (fy - y + 13) * q - Math.sin(q * Math.PI) * 14;
            gx().P(b, Math.round(wx), Math.round(wy), i % 3 ? C.waterL : '#ffffff');
          }
          if (p > .55) { b.globalAlpha = .55 * (1 - p); blob(b, fx, fy - (p - .55) * 30, 4 + p * 4, 3 + p * 3, ['#f4f4f8', '#dcdce4', '#c4c4cc'], null); b.globalAlpha = 1; }
          burst(b, fx, fy, (p - .6) * 1.5, 6, [C.waterL, '#ffffff'], k, 18, .35);
        }
      } };
    },
  };

  // Paint one villager (shadow, sprite, tool, particles) at its displayed position into the low-res buffer.
  function paint(b, sheet, a, sec, selected) {
    const { blob, R } = gx(), x = Math.round(a.x), y = Math.round(a.y), dir = a.dir;
    blob(b, x, y + 7, 5, 2, SHADOW, null);
    if (selected) { b.fillStyle = '#f2c14e'; for (const [dx, dy] of [[-7, 7], [6, 7], [-6, 8], [5, 8]]) b.fillRect(x + dx, y + dy, 2, 1); }
    const row = dir === 'up' ? 1 : dir === 'down' ? 0 : 2, frame = a.moving ? 1 + (Math.floor(sec * 7) % 2) : 0;
    b.save();
    if (dir === 'left') { b.translate(x, 0); b.scale(-1, 1); b.translate(-x, 0); }
    const pose = !a.moving && POSES[a.act] ? POSES[a.act](b, x, y, sec + a.k * .37, a) : {};
    const crouch = pose.crouch || 0, dy = (pose.dy || 0) + crouch;
    if (pose.back) pose.back();
    const fw = sheet.fw || 12, fh = sheet.fh || 16;   // sprite villagers (viewer/sprites.js) are bigger than code ones
    b.drawImage(sheet, frame * fw, row * fh, fw, fh - crouch, x - fw / 2, y + 8 - fh + dy, fw, fh - crouch);
    if (pose.front) pose.front();
    if (a.moving && a.carry) bucket(b, x + 4, y + 3 + (Math.floor(sec * 7) % 2), true);
    b.restore();
  }

  // ---------- displayed positions: smooth over every jump (new hour, new work spot, end of a walk) ----------
  const st = {};
  function place(name, tickId, target, onRoute, dt) {
    let s = st[name];
    if (!s) s = st[name] = { x: target.x, y: target.y, ox: 0, oy: 0, tick: tickId, tx: target.x, ty: target.y };
    const jump = Math.hypot(target.x - s.tx, target.y - s.ty);
    if (s.tick !== tickId || (!onRoute && jump > 1.5)) { s.ox = s.x - target.x; s.oy = s.y - target.y; s.tick = tickId; }
    if (Math.hypot(s.ox, s.oy) > 160) { s.ox = s.oy = 0; }   // scrubbed far away: snap
    const k = Math.exp(-dt * 5); s.ox *= k; s.oy *= k;
    if (Math.hypot(s.ox, s.oy) < .3) s.ox = s.oy = 0;
    s.tx = target.x; s.ty = target.y; s.x = target.x + s.ox; s.y = target.y + s.oy;
    const sliding = Math.hypot(s.ox, s.oy) > 2;
    const sdir = Math.abs(s.ox) > Math.abs(s.oy) ? (s.ox < 0 ? 'right' : 'left') : s.oy < 0 ? 'down' : 'up';
    return { x: s.x, y: s.y, sliding, sdir };
  }

  // ---------- bubbles (full-resolution canvas, constant size whatever the zoom) ----------
  // A bubble does not pop up at the start of the hour for everyone at once: each villager speaks at their own moment
  // in the hour (the decision's own minute if the log has one, else a stable per-villager spread over the hour).
  const said = {}, pending = {}; let lastTick = null, clock = 0, lastStamp = null;
  const hash = s => { let h = 7; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 9973; return h / 9973; };
  function noteTick(t, frac, dt) {
    const stamp = t.tick + '|' + frac;
    if (stamp !== lastStamp) clock += dt;   // bubbles age only while the replay moves (pause keeps them readable)
    lastStamp = stamp;
    if (t.tick !== lastTick) {
      if (lastTick === null || Math.abs(t.tick - lastTick) > 3) for (const n in said) delete said[n];
      for (const n in pending) delete pending[n];
      const jumped = lastTick === null || t.tick !== lastTick + 1;
      lastTick = t.tick;
      for (const [n, d] of Object.entries(t.decisions || {})) {
        const act = d.action || {}, args = act.args || {};
        let b = null;
        if (d.say) b = { kind: 'say', text: d.say };
        else if (act.name === 'say' && args.text) b = { kind: 'say', text: args.text };
        else if (act.name === 'whisper' && args.text) b = { kind: 'whisper', text: args.text, to: args.to };
        else if (d.thought) b = { kind: 'think', text: d.thought };
        if (!b) continue;
        const m = d.minute != null ? d.minute : d.at != null ? d.at : null;
        b.at = jumped ? 0 : m != null ? Math.min(.9, m / 60) : .05 + hash(n + t.tick) * .65;
        b.life = Math.min(10, (b.kind === 'think' ? 4 : 5) + String(b.text).length * .04);
        pending[n] = b;
      }
      if ((t.events || []).some(e => e.kind === 'fire'))
        for (const n of Object.keys(t.view.agents)) if (!t.view.agents[n].asleep) said[n + '!'] = { kind: 'alarm', born: clock, life: 2.5 };
    }
    for (const [n, b] of Object.entries(pending)) if (frac >= b.at) { said[n] = { ...b, born: clock }; delete pending[n]; }
  }
  function wrap(ctx, text, maxW, maxLines) {
    const words = String(text).split(/\s+/), lines = [];
    let cur = '';
    for (const w of words) {
      const next = cur ? cur + ' ' + w : w;
      if (ctx.measureText(next).width <= maxW || !cur) cur = next; else { lines.push(cur); cur = w; }
    }
    if (cur) lines.push(cur);
    if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, '') + '…'; }
    return lines;
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  // shown: [{n, sx, sy}] head positions in canvas pixels. Speech first (never hidden), then thoughts where they fit.
  function bubbles(ctx, shown, selected, tr, canvasW) {
    const placed = [], items = [];
    for (const a of shown) {
      const s = said[a.n]; if (s && clock - s.born < s.life) items.push({ a, s });
      const al = said[a.n + '!']; if (al && clock - al.born < al.life) items.push({ a, s: al });
    }
    const rank = it => (it.a.n === selected ? 0 : 3) + (it.s.kind === 'think' ? 1 : 0) + (it.s.kind === 'alarm' ? -1 : 0);
    items.sort((p, q) => rank(p) - rank(q) || q.a.sy - p.a.sy);
    for (const { a, s } of items) {
      const alpha = Math.min(1, (s.life - (clock - s.born)) / .6);
      ctx.globalAlpha = Math.max(0, alpha);
      if (s.kind === 'alarm') {
        ctx.font = '900 18px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
        const yy = a.sy - 18 - Math.abs(Math.sin(clock * 8)) * 4;
        ctx.lineWidth = 4; ctx.strokeStyle = '#1b1b24'; ctx.strokeText('!', a.sx, yy); ctx.fillStyle = '#ffd23f'; ctx.fillText('!', a.sx, yy);
        ctx.globalAlpha = 1; continue;
      }
      const think = s.kind === 'think', sel = a.n === selected;
      ctx.font = think ? 'italic 12px system-ui, sans-serif' : '12px system-ui, sans-serif';
      const prefix = s.kind === 'whisper' ? `🤫 ${s.to || ''}: ` : '';
      const lines = wrap(ctx, prefix + tr(String(s.text)), sel ? 260 : 200, sel ? 5 : think ? 2 : 3);
      const w = Math.max(...lines.map(l => ctx.measureText(l).width)) + 14, h = lines.length * 15 + 8;
      let bx = Math.max(4, Math.min(canvasW - w - 4, a.sx - w / 2)), by = a.sy - h - (think ? 22 : 16);
      const hit = r => placed.find(p => r.x < p.x + p.w && p.x < r.x + r.w && r.y < p.y + p.h && p.y < r.y + r.h);
      let r = { x: bx, y: by, w, h }, tries = 0, o;
      while ((o = hit(r)) && tries++ < 4) r = { ...r, y: o.y - h - 3 };
      if (hit(r) && think && !sel) { ctx.globalAlpha = 1; continue; }
      placed.push(r); by = r.y;
      if (think) {
        ctx.fillStyle = 'rgba(244,248,245,.92)'; ctx.strokeStyle = '#6f8a7a'; ctx.lineWidth = 1.5;
        roundRect(ctx, bx, by, w, h, 9); ctx.fill(); ctx.stroke();
        for (const [dx, dy, rr] of [[0, 6, 4], [3, 14, 2.5]]) { ctx.beginPath(); ctx.arc(a.sx + dx, Math.min(a.sy - 6, by + h + dy), rr, 0, 7); ctx.fill(); ctx.stroke(); }
        ctx.fillStyle = '#34463c';
      } else {
        const bgc = s.kind === 'whisper' ? '#ece2fb' : '#fffbe8';
        ctx.fillStyle = '#1b1b24'; ctx.fillRect(bx - 2, by, w + 4, h); ctx.fillRect(bx, by - 2, w, h + 4);
        ctx.fillStyle = bgc; ctx.fillRect(bx, by, w, h);
        if (by + h < a.sy - 8) { const tx = Math.max(bx + 6, Math.min(bx + w - 6, a.sx));
          ctx.fillStyle = '#1b1b24'; ctx.fillRect(tx - 4, by + h, 8, 4); ctx.fillStyle = bgc; ctx.fillRect(tx - 2, by + h, 4, 3); }
        ctx.fillStyle = '#222';
      }
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      lines.forEach((l, j) => ctx.fillText(l, bx + 7, by + 5 + j * 15));
      ctx.globalAlpha = 1;
    }
  }

  return { activities, workSpot, wander, paint, place, noteTick, bubbles };
})();
