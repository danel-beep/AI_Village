// Buildings of the «С нуля» mode on the map (aivillage/construction.py), drawn with viewer/buildart.js.
// Only when the run has `construction.enabled`; older logs are drawn exactly as before.
// - Houses come from view.plots[home].house: level 1..3 look different (sticks and thatch, logs and shingles,
//   stone and tiles); level 0 is bare ground, or a shelter once one is built in the yard.
// - Other yard buildings (view.plots[home].buildings with a level: workbench, granary, smokehouse, smithy) stand
//   beside the house, smaller; common ones (view.buildings) stand around their place (square, forest...).
// - Building sites (view.sites) are drawn in three stages by how far they are (`done`), with a progress bar; a
//   site for the next level of something standing covers it with scaffolding.
// - A finished building raises dust (event building_done); a new village stage (event village_stage) shows a
//   banner with what the next stage needs.
// - Camp start (config bare_start.applied): pixelmap.js skips the ready-made houses, market, smithy and well;
//   the valley is empty until the villagers build.
// pixelmap.js calls init() once, draw() under the villagers and banner() on top of the screen.
const BuildLayer = (() => {
  let K, on = false, bare = false, cache = {}, shown = null, lastTick = null, hdr = null;
  // construction kind -> BuildArt kind
  const ART = { shelter: 'shelter', house: 'house', campfire: 'campfire', workbench: 'workbench', granary: 'barn',
    smokehouse: 'smokehouse', market_square: 'market', smithy: 'forge', town_hall: 'council', tavern: 'tavern',
    palisade: 'wall', kiln: 'kiln', mill: 'mill', tannery: 'tannery', loom: 'loom', well: 'well', gate: 'gate',
    watchtower: 'watchtower', bridge: 'bridge', barn: 'barn', pen: 'pen', garden: 'garden' };
  const NAME = { shelter: 'шалаш', house: 'дом', campfire: 'костёр', workbench: 'верстак', granary: 'амбар',
    smokehouse: 'коптильня', market_square: 'рыночная площадь', smithy: 'кузница', town_hall: 'ратуша',
    tavern: 'таверна', palisade: 'частокол' };
  const STAGE = { camp: 'Лагерь', hamlet: 'Хутор', village: 'Деревня', town: 'Посёлок' };
  const STAGE_ICON = { camp: '🏕', hamlet: '🛖', village: '🏘', town: '🏰' };
  // Yard kinds the code-drawn PlotLayer already draws in cells (beds, coops, pens, hives, fences) stay there.
  const YARD_SMALL = new Set(['garden_bed', 'chicken_coop', 'cow_pen', 'beehive', 'fence']);
  // Fixed order, so a building keeps its spot when others appear.
  const ORDER = ['campfire', 'market_square', 'town_hall', 'tavern', 'palisade', 'workbench', 'granary', 'smokehouse',
    'smithy', 'kiln', 'mill', 'tannery', 'loom', 'well', 'gate', 'watchtower'];
  const art = k => ART[k] || (window.BuildArt && BuildArt.KINDS[k] ? k : 'workshop');
  const rank = k => { const i = ORDER.indexOf(k); return i < 0 ? ORDER.length : i; };

  function enabled(h) { return !!(h && ((h.config || {}).construction || {}).enabled); }
  function empty(h) { return enabled(h) && !!((h.config || {}).bare_start || {}).applied; }

  function init(kit, header) {
    K = kit; hdr = header; on = enabled(header) && !!window.BuildArt; bare = on && empty(header);
    cache = {}; shown = null; lastTick = null;
    return on;
  }

  // Camp start (pixelmap.js): the layout was rebuilt as the villagers settled and walked; keep the banner state.
  function relayout(layout) { if (K) K = { ...K, layout }; }

  // An offscreen picture of one kind and level (BuildArt.canvas pads 8 px on top for flags and smoke).
  function pic(kind, level) {
    const key = kind + '@' + level;
    return cache[key] || (cache[key] = BuildArt.canvas(kind, level, 1));
  }
  function sitePic(w, h, stage) {
    const key = 'site:' + w + 'x' + h + ':' + stage;
    if (cache[key]) return cache[key];
    const c = document.createElement('canvas'); c.width = w + 8; c.height = h + 8;
    BuildArt.site(c.getContext('2d'), w, h, stage, 4, 8);
    return cache[key] = c;
  }
  // Draw a picture with its bottom centre at (bx, by), scaled by s, and tell Depth it can hide villagers behind it.
  function put(g, c, bx, by, s, key) {
    const w = Math.round(c.width * s), h = Math.round(c.height * s), x = Math.round(bx - w / 2), y = Math.round(by - h);
    g.drawImage(c, x, y, w, h);
    if (window.Depth) Depth.add(g, key, x, y, w, h, m => m.drawImage(c, x, y, w, h));
    return [x, y, w, h];
  }

  function bar(g, x, y, w, share) {
    const { R } = K;
    R(g, x - 1, y - 1, w + 2, 5, '#1b1b24'); R(g, x, y, w, 3, '#5a4632');
    R(g, x, y, Math.max(1, Math.round(w * Math.min(1, share))), 3, share >= 1 ? '#9ad870' : '#f2c14e');
  }
  const stageOf = done => (done < 1 / 3 ? 1 : done < 2 / 3 ? 2 : 3);

  function dust(g, x, y, e) {
    if (e >= 1) return;
    g.globalAlpha = .7 * (1 - e);
    for (let i = 0; i < 7; i++) K.blob(g, x + Math.cos(i * .9) * (6 + e * 18), y - e * 10 + Math.sin(i * .9) * 3, 3 + e * 5, 2 + e * 4,
      ['#eee2c4', '#d6c8a6', '#bcae8c'], null);
    g.globalAlpha = 1;
  }

  // Where a common building stands: [place, bottom-centre x, y, scale] from its place's box. The market square goes
  // to the trader's market place when the map has one (that is where trading happens); the town hall heads the
  // square, the campfire burns in it, tavern and palisade take its lower corners; anything else lines up below.
  function placeSpot(loc, kind, k) {
    if (kind === 'market_square' && K.layout.box.market) loc = 'market';
    const bx = K.layout.box[loc];
    if (!bx) { const a = K.layout.anchors[loc] || K.layout.anchors.square; return [a[0] + (k % 2 ? 1 : -1) * 40 * Math.ceil(k / 2), a[1] - 6, .75]; }
    const [x, y, w, h] = bx, cx = x + w / 2;
    const fixed = { market_square: [cx, y + h - 4, .9], town_hall: [cx, y + 14, .8], campfire: [cx - 24, y + h * .55, .9],
      tavern: [x + w - 26, y + h - 2, .65], palisade: [x + 24, y + h - 2, .7] };
    if (loc === 'square' || loc === 'market') { if (fixed[kind]) return fixed[kind]; }
    else if (kind === 'campfire') return [cx, y + h * .6, .9];
    const spots = [[x + 18, y + h + 26], [x + w - 18, y + h + 26], [cx, y + h + 30], [x - 18, y + h * .8], [x + w + 18, y + h * .8]];
    return [...spots[k % spots.length], .6];
  }

  // Yard buildings (workbench, granary, smokehouse, smithy) in a column beside the house, which moves aside for them.
  // Generated map: the fenced plot around the house; hand-made map: the yard rows behind (above) the house.
  function yardSpots(hs, home) {
    const pl = (K.layout.plots || {})[home];
    if (pl) { const [x, y, w, h] = pl, rx = x + w - 17; return { house: [x + 25, y + h - 1, .72], spots: [[rx, y + h - 2], [rx, y + h - 26], [rx, y + h - 50], [x + 8, y + 18]] }; }
    const T = K.T, y0 = hs.y - 3 * T + 2;
    return { house: [hs.x + 24, hs.y + 47, .82], spots: [[hs.x + 10, y0 + 20], [hs.x + 38, y0 + 20], [hs.x + 10, y0 + 42], [hs.x + 38, y0 + 42]] };
  }

  // Draw one house spot: the house at its level, a shelter at level 0 if one is built, else nothing.
  function house(g, hs, level, shelter, [bx, by, sc]) {
    hs.chimney = null; hs.windows = [];
    if (level >= 1) {
      const c = pic('house', Math.min(3, level)), r = put(g, c, bx, by, sc, 'house');
      if (level >= 2) hs.chimney = [r[0] + r[2] * .72, r[1] + 10];
      hs.windows = [[bx - 14 * sc / .82, by - 22 * sc / .82], [bx + 6 * sc / .82, by - 22 * sc / .82]];
    } else if (shelter) put(g, pic('shelter', 1), bx, by, 1, 'b_shelter');
  }

  function draw(g, t, e) {
    if (!on || !K || !t.view) return;
    const v = t.view, plots = v.plots || {}, houses = {};
    for (const h of K.layout.houses) houses['home_' + h.name] = h;
    const fresh = (t.events || []).filter(ev => ev.kind === 'building_done');
    const sites = v.sites || [];
    const siteFor = (loc, kind) => sites.find(s => s.location === loc && s.kind === kind);
    // homes
    for (const [home, p] of Object.entries(plots)) {
      const hs = houses[home];
      if (!hs) continue;
      const big = (p.buildings || []).filter(b => !YARD_SMALL.has(b.kind) && b.kind !== 'shelter' && b.kind !== 'house');
      const shelter = (p.buildings || []).some(b => b.kind === 'shelter');
      const hsite = siteFor(home, 'house') || (!p.house && siteFor(home, 'shelter'));
      // yard buildings and their sites
      const own = big.map(b => ({ kind: b.kind, level: b.level || 1 }));
      for (const s of sites) if (s.location === home && s.kind !== 'house' && s.kind !== 'shelter' && !own.some(b => b.kind === s.kind))
        own.push({ kind: s.kind, level: 0 });
      own.sort((a, b) => rank(a.kind) - rank(b.kind) || a.kind.localeCompare(b.kind));
      const ys = yardSpots(hs, home), at = own.length ? ys.house : [hs.x + 24, hs.y + 47, .82];
      if (hsite) {
        // a house going up (or its next level): the old one shows through scaffolding
        if (p.house >= 1) house(g, hs, p.house, shelter, at);
        else if (shelter && hsite.kind === 'house') put(g, pic('shelter', 1), at[0], at[1], 1, 'b_shelter');
        const [w, h] = BuildArt.KINDS[art(hsite.kind)].size;
        const r = put(g, sitePic(w, h, stageOf(hsite.done)), at[0], at[1], hsite.kind === 'shelter' ? 1 : at[2], 'b_site');
        bar(g, r[0] + 6, r[1] + r[3] + 2, r[2] - 12, hsite.done);
      } else house(g, hs, p.house || 0, shelter, at);
      own.forEach((b, k) => {
        const [x, y] = ys.spots[k % ys.spots.length], s = siteFor(home, b.kind), [w, h] = BuildArt.KINDS[art(b.kind)].size;
        const sc = Math.min(.5, 32 / w);
        if (b.level) put(g, pic(art(b.kind), b.level), x, y, sc, 'b_' + b.kind);
        if (s) { const r = put(g, sitePic(w, h, stageOf(s.done)), x, y, sc, 'b_site'); bar(g, r[0] + 2, r[1] + r[3] + 1, r[2] - 4, s.done); }
      });
      if (fresh.some(ev => ev.location === home || (ev.data || {}).owner === hs.name)) dust(g, hs.x + 24, hs.y + 40, e);
    }
    // common buildings and sites, per place
    const byLoc = {};
    for (const b of v.buildings || []) (byLoc[b.location] = byLoc[b.location] || {})[b.kind] = { kind: b.kind, level: b.level };
    for (const s of sites) if (!houses[s.location] && !(plots[s.location])) {
      const m = byLoc[s.location] = byLoc[s.location] || {};
      if (!m[s.kind]) m[s.kind] = { kind: s.kind, level: 0 };
    }
    for (const [loc, kinds] of Object.entries(byLoc)) {
      const list = Object.values(kinds).sort((a, b) => rank(a.kind) - rank(b.kind));
      let k = 0;
      for (const b of list) {
        const a = art(b.kind), [w, h] = BuildArt.KINDS[a].size, [x, y, sc] = placeSpot(loc, b.kind, k++), s = siteFor(loc, b.kind);
        if (b.level) put(g, pic(a, b.level), x, y, sc, 'b_' + b.kind);
        if (s) { const r = put(g, sitePic(w, h, stageOf(s.done)), x, y, sc, 'b_site'); bar(g, r[0] + 4, r[1] + r[3] + 2, r[2] - 8, s.done); }
        if (fresh.some(ev => ev.location === loc && (ev.data || {}).what === b.kind)) dust(g, x, y - 10, e);
      }
    }
  }

  // The market stall, smithy and square lamps exist only once built (camp start); pixelmap.js asks here.
  function standing(t, kind) {
    return !!(((t || {}).view || {}).buildings || []).some(b => b.kind === kind);
  }

  // ---------- weapon and armor on villagers (conflict.py gear: the best one carried is the one others see) ----------
  const WEAPONS = ['sword', 'bow', 'iron_spear', 'spear', 'club'], ARMOR = ['iron_armor', 'leather_armor'];
  function iconPic(id) {
    const key = 'icon:' + id;
    if (key in cache) return cache[key];
    return cache[key] = window.Icons && Icons.ITEMS[id] ? Icons.canvas(id, 1) : null;
  }
  // a = an Actors villager ({x, y, dir, act, moving}); feet at y + 8. Hidden while a work pose holds its own tool.
  function gear(g, a, inv) {
    if (!on || !inv) return;
    const w = WEAPONS.find(k => inv[k] > 0), ar = ARMOR.find(k => inv[k] > 0);
    const free = a.moving || a.act === 'idle' || a.act === 'talk' || a.act === 'walk';
    const x = Math.round(a.x), y = Math.round(a.y), flip = a.dir === 'left' ? -1 : 1;
    if (ar && iconPic(ar)) g.drawImage(iconPic(ar), x - 4 - 3 * flip, y - 3, 8, 8);   // a badge at the hip
    if (w && free && iconPic(w) && a.dir !== 'up') {
      g.save(); g.translate(x + 6 * flip, y - 6); g.scale(flip, 1); g.drawImage(iconPic(w), -2, -5, 10, 10); g.restore();
    }
  }

  // ---------- new stage banner (screen space, on top) ----------
  function needs(sid) {
    const st = ((hdr.config.progress || {}).stages || []), k = st.findIndex(s => s.id === sid), nx = st[k + 1];
    if (!nx) return '';
    const b = (nx.requires || {}).buildings || {};
    const list = Object.entries(b).map(([kk, q]) => {
      const [kind, lvl] = kk.split('@');
      return (q > 1 ? q + ' × ' : '') + (NAME[kind] || kind) + (lvl ? ' ' + lvl + '-го уровня' : '');
    });
    return list.length ? `Дальше ${STAGE[nx.id] || nx.id}: ${list.join(', ')}` : '';
  }
  function banner(ctx, t, time) {
    if (!on || !t) return;
    if (t !== lastTick) {
      lastTick = t;
      const ev = (t.events || []).find(e => e.kind === 'village_stage');
      if (ev) shown = { sid: (ev.data || {}).stage, at: time };
    }
    if (!shown) return;
    const age = (time - shown.at) / 1000, LIFE = 5;
    if (age > LIFE || age < 0) { if (age > LIFE) shown = null; return; }
    const a = Math.min(1, age * 3, (LIFE - age) * 1.5), W = ctx.canvas.width, drop = Math.min(1, age * 4);
    const title = `${STAGE_ICON[shown.sid] || '🏘'} Новая стадия: ${STAGE[shown.sid] || shown.sid}`, sub = needs(shown.sid);
    ctx.save(); ctx.globalAlpha = a;
    ctx.font = '700 26px system-ui, sans-serif';
    const tw = Math.max(ctx.measureText(title).width, (ctx.font = '500 14px system-ui, sans-serif', ctx.measureText(sub).width)) + 70;
    const x = (W - tw) / 2, y = 40 * drop - 10, h = sub ? 78 : 56;
    ctx.fillStyle = '#3a2416'; ctx.fillRect(x - 4, y - 4, tw + 8, h + 8);
    ctx.fillStyle = '#c08850'; ctx.fillRect(x, y, tw, h);
    ctx.fillStyle = '#f3e2b8'; ctx.fillRect(x + 6, y + 6, tw - 12, h - 12);
    for (const sx of [x - 22, x + tw + 4]) { ctx.fillStyle = '#8f3328'; ctx.fillRect(sx, y + 12, 18, h - 24); ctx.fillStyle = '#b8483a'; ctx.fillRect(sx + 2, y + 14, 14, h - 28); }
    ctx.fillStyle = '#3a2416'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = '700 26px system-ui, sans-serif'; ctx.fillText(title, W / 2, y + (sub ? 28 : h / 2));
    if (sub) { ctx.font = '500 14px system-ui, sans-serif'; ctx.fillStyle = '#5a3a20'; ctx.fillText(sub, W / 2, y + 56); }
    ctx.restore();
  }

  return { init, relayout, draw, banner, gear, standing, enabled, empty, art, ART, NAME, STAGE };
})();
window.BuildLayer = BuildLayer;
