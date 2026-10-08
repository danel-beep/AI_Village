// «Эфир»: the replay as a show. viewer/foresight.js knows what comes next; this file puts it on screen.
//  - Cinema mode (key F or ⛶ in the bar): the map fills the whole screen, the log column and the bar go away, the
//    buttons fade out while the mouse rests and come back when it moves. F again or Esc leaves it.
//  - Rubber time (replay with the auto camera 🎬 on): quiet hours run 4x faster ("⏩ Тихие часы"), a notable moment
//    slows down, and while the villager in the shot says or thinks something the clock waits until it can be read.
//  - Countdown (replay, 🎬 on): before a big moment the camera is already there and a plaque counts down to it in real
//    seconds, with facts about why it matters but not what will happen. At zero it says what happened.
// Live mode keeps its own pace: there the future is not known yet. Reads the viewer's globals (ticks, i, frac, live,
// tr) at run time; index.html calls Efir.reset() / Efir.add(k) as rows arrive, Efir.tick(base, speed) for the pace
// of the tick on screen and Efir.frame() every frame.
const Efir = (() => {
  const NOTE = 6, QUIET_X = 4, QUIET_LOOK = 12, PRE = 4;
  let F = null, mode = '';
  const make = () => Foresight.create((k, d) => Camera.score(k, d));
  // «Часы судьбы» (viewer/fate.js): amber clocks from the rules, in live games too.
  let G = null;
  const makeFate = () => window.Fate ? Fate.create((typeof header !== 'undefined' && header && header.config) || {}) : null;
  function reset() { F = make(); G = makeFate(); last = null; }
  function add(k) { if (!F) F = make(); if (!G) G = makeFate(); F.add(ticks, k); if (G) G.add(ticks, k); }
  const on = () => F && typeof live !== 'undefined' && !live && ticks.length > 1 && Camera.directorOn() && !(window.Clip && Clip.busy());
  const pace = speed => Math.max(.1, Math.min(2, 2 / speed));   // 1 at the default speed (2); the slider still skims
  const speedNow = () => +((document.getElementById('speed') || {}).value || 2);

  // What villager n says and thinks on tick k (their bubble), translated; seconds to read it at pace p.
  function text(n, k) {
    const d = n && ticks[k] && (ticks[k].decisions || {})[n]; if (!d) return '';
    const a = d.action || {}, args = a.args || {}, said = d.say || (/^(say|whisper)$/.test(a.name) && args.text) || '';
    return (said ? tr(String(said)) + ' ' : '') + (d.thought ? tr(String(d.thought)) : '');
  }
  const read = (n, k, p) => { const c = text(n, k).length; return c < 4 ? 0 : Math.min(8, .8 + c / 18) * p; };
  const speaks = d => !!d && (!!d.say || /^(say|whisper)$/.test((d.action || {}).name));
  const talk = k => Object.values(ticks[k].decisions || {}).some(speaks);

  // The countdown being played: its seconds per tick are fixed when it starts, so the clock on the plaque runs evenly.
  let last = null;
  function current(p) {
    const cd = F.at(i); if (!cd) { last = null; return null; }
    if (!last || last.c !== cd.c) last = { c: cd.c, sus: Math.max(.15, Math.min(6, 20 * p / Math.max(1, cd.c.k - cd.c.s))), total: 0 };
    const c = cd.c, sus = last.sus, focus = Camera.focus() || c.hero;
    last.dur = k => k < c.k ? Math.max(sus, read(c.hero, k, p)) : k === c.k ? Math.max(sus * 1.5, read(focus, k, p)) : Math.max(sus * .7, read(focus, k, p));
    return { ...cd, ...last };
  }

  // Seconds the tick on screen lasts, or null when «Эфир» is off (live, auto camera off, a clip being made).
  function tick(base, speed) {
    mode = '';
    if (!on()) { last = null; return null; }
    const p = pace(speed), cd = current(p);
    if (cd) { mode = cd.wait ? 'wait' : 'after'; return { sec: cd.dur(i), exact: true }; }
    let sec = base;
    if (F.busy(i) >= NOTE) sec = Math.max(base, .6 * p);
    else if (F.next(i, 3, NOTE) >= 0) sec = Math.max(base, .35 * p);
    else if (F.next(i, QUIET_LOOK, 5) < 0 && !F.starts(i, QUIET_LOOK) && !talk(i)) { sec = base / QUIET_X; mode = 'quiet'; }
    // Wait for the words of the villager in the shot: the one picked always, the director's hero when they speak or
    // something notable happens (every decision has a thought; waiting for all of them would stall quiet hours).
    const f = Camera.focus();
    if (f && (f === selected || speaks((ticks[i].decisions || {})[f]) || F.busy(i) >= NOTE)) {
      const r = read(f, i, p); if (r > sec) { sec = r; if (mode === 'quiet') mode = ''; }
    }
    return { sec, exact: false };
  }

  // ---------- on screen ----------
  const css = document.createElement('style');
  css.textContent = `
    #efir-cd { position:absolute; left:50%; transform:translateX(-50%); z-index:6; pointer-events:none; min-width:260px;
      max-width:min(560px, calc(100% - 24px)); padding:7px 14px 8px; border-radius:8px; background:rgba(20,22,26,.9);
      border:1px solid #e5604d; color:#f1f4f1; font:600 14px/1.3 system-ui, sans-serif; box-shadow:0 2px 10px rgba(0,0,0,.45) }
    #efir-cd.after { border-color:#f2c14e }
    #efir-cd .row { display:flex; gap:14px; align-items:baseline; justify-content:space-between }
    #efir-cd .t { font:700 22px/1 ui-monospace, Menlo, Consolas, monospace; color:#ff8a78; font-variant-numeric:tabular-nums }
    #efir-cd.hot .t { color:#ff4f3a }
    #efir-cd .why { margin-top:3px; font-weight:400; font-size:12.5px; color:#b9c8bf }
    #efir-cd.after .why { color:#ffe9a8 }
    #efir-cd .bar { margin-top:6px; height:4px; border-radius:2px; background:#3a3f45; overflow:hidden }
    #efir-cd .bar i { display:block; height:100%; width:0; background:linear-gradient(90deg, #e8a93a, #e5604d) }
    #efir-cd.after .bar { display:none }
    #efir-ff { position:absolute; left:50%; transform:translateX(-50%); z-index:6; pointer-events:none; padding:3px 10px;
      border-radius:12px; background:rgba(20,22,26,.75); color:#cfe3d6; font:600 12px system-ui, sans-serif }
    body.cinema #side { display:none }
    body.cinema #bar { position:fixed; left:0; right:0; bottom:0; z-index:25; opacity:0; pointer-events:none; transition:opacity .35s;
      padding-bottom:calc(8px + env(safe-area-inset-bottom, 0px)) }
    body.cinema:has(#god-toggle) #bar { padding-right:150px }   /* keep clear of the floating god-mode button */
    body.cinema.awake #bar, body.cinema #bar:has(:focus-visible) { opacity:1; pointer-events:auto }
    body.cinema :is(#cam-tools, #god-toggle, #hl-btn, #rp-bar, #ra-btn, #st-toggle, #ss-end) { transition:opacity .35s }
    body.cinema:not(.awake) :is(#cam-tools, #god-toggle, #hl-btn, #rp-bar, #ra-btn, #st-toggle, #ss-end) { opacity:0; pointer-events:none }
    #efir-fate { position:absolute; left:8px; z-index:6; pointer-events:none; display:flex; flex-direction:column; gap:3px;
      max-width:min(420px, calc(50% - 150px)); font:600 12px/1.3 system-ui, sans-serif }
    #efir-fate span { background:rgba(20,22,26,.85); color:#f6e7c1; border-left:3px solid #e8a93a; padding:3px 8px 3px 6px;
      border-radius:0 5px 5px 0; box-shadow:0 1px 6px rgba(0,0,0,.35) }
    #efir-fate span.hot { border-left-color:#e5604d }
    @media (max-width: 700px) { #efir-fate { max-width:calc(100% - 16px); font-size:11px } }
    #efir-btn[aria-pressed=true] { background:#f2c14e; color:#1d2321 }`;
  document.head.appendChild(css);
  const plate = document.createElement('div'); plate.id = 'efir-cd'; plate.hidden = true;
  plate.innerHTML = '<div class="row"><span class="what"></span><span class="t"></span></div><div class="why"></div><div class="bar"><i></i></div>';
  const fate = document.createElement('div'); fate.id = 'efir-fate'; fate.hidden = true;
  const ff = document.createElement('div'); ff.id = 'efir-ff'; ff.hidden = true; ff.textContent = '⏩ Тихие часы';
  const $ = s => plate.querySelector(s);
  const set = (el, v) => { if (el.textContent !== v) el.textContent = v; };
  const clock = s => { s = Math.max(0, Math.ceil(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  const item = id => window.Icons && Icons.ITEMS && Icons.ITEMS[id] ? Icons.ITEMS[id].name.toLowerCase() : id;
  const place = (loc, k) => { const n = loc && ticks[k].view.locations && ticks[k].view.locations[loc]; return n ? tr(n) : ''; };

  // The plaque while it counts: what is coming (never how it ends) and the facts behind it.
  function waiting(c) {
    const v = ticks[i].view.agents, h = v[c.hero] || {}, o = v[c.owner] || {};
    if (c.type === 'temptation') {
      const why = [`сытость ${h.satiety}`];
      if (F.spoke(c.hero, c.owner, i - 8, i)) why.push(`была просьба к ${c.owner}`);
      if (o.asleep) why.push(`${c.owner} спит`);
      return [`🍞 ${c.hero} без еды, а рядом еда ${c.owner}`, why.join(' · ')];
    }
    if (c.type === 'answer') return [`💍 ${c.hero} думает над предложением ${c.owner}`, ''];
    if (c.type === 'polity') {
      const k = c.ev.kind;
      return [k === 'polity_form' ? '🏛 Деревня решает, как ей править' : /law/.test(k) ? '📜 Решается судьба закона' : '🗳 Скоро итоги выборов', ''];
    }
    const where = place(c.loc, i);
    return [`❗ Скоро что-то случится${c.hero ? ' · ' + c.hero : where ? ' · ' + where : ''}`, c.hero && where ? where : ''];
  }
  function happened(c) {
    const o = Foresight.outcome(ticks, c, item);
    return [o.title || `${Camera.label(c.ev.kind)}${c.hero ? ' · ' + c.hero : ''}`, o.line];
  }
  // The camera's shot for what is coming: the countdown's hero or place, else a notable moment a few ticks ahead.
  // (kind: what the director labels it with once it happens; a place-bound moment is framed by its place)
  function shotOf(c) {
    if (c.type === 'polity') return null;
    const kind = c.ev ? c.ev.kind : 'steal';
    if (c.type === 'fate' && c.loc) return { who: null, loc: c.loc, sc: c.sc, kind };
    return c.hero ? { who: c.hero, loc: c.loc || null, sc: c.sc, kind } : c.loc ? { who: null, loc: c.loc, sc: c.sc, kind } : null;
  }
  function preroll() {
    const j = F.next(i, PRE, NOTE); if (j < 0) return null;
    let best = null;
    for (const e of ticks[j].events || []) {
      const sc = Camera.score(e.kind, e.data), loc = Foresight.placeOf(e), who = e.actor && ticks[i].view.agents[e.actor] ? e.actor : null;
      if (sc >= NOTE && (who || loc) && (!best || sc > best.sc)) best = { who, loc, sc, kind: e.kind };
    }
    return best;
  }

  // The amber clocks, top left of the map: replay and live alike, hidden while a clip is being made.
  const season = d => window.SeasonLayer && typeof header !== 'undefined' ? SeasonLayer.seasonOf(header, d) : null;
  let fateKey = '';
  function clocks(cv) {
    const rows = G && ticks.length && !(window.Clip && Clip.busy()) ? G.lines(ticks, i, { tr, item, seasonOf: season }) : [];
    fate.hidden = !rows.length; if (!rows.length) { fateKey = ''; return; }
    // below the floating ⭐ Highlights button and the live badge when they sit over the map's top-left corner
    let top = (cv ? cv.offsetTop : 0) + 8;
    const map = fate.parentElement;
    for (const el of [document.getElementById('hl-btn'), document.getElementById('live-badge')]) {
      if (!el || !map || !el.getClientRects().length) continue;
      const r = el.getBoundingClientRect(), m = map.getBoundingClientRect();
      if (r.left < m.left + 200 && r.bottom > m.top) top = Math.max(top, r.bottom - m.top + 6);
    }
    fate.style.top = top + 'px'; fate.style.left = (cv ? Math.max(0, cv.offsetLeft) : 0) + 8 + 'px';
    const key = rows.map(r => r.icon + r.text).join('\n'); if (key === fateKey) return; fateKey = key;
    fate.replaceChildren(...rows.map(r => {
      const el = document.createElement('span'); el.textContent = `${r.icon} ${r.text}`;
      if (r.score >= 75) el.className = 'hot'; return el;
    }));
  }

  function frame() {
    const map = document.getElementById('map'), cv = document.getElementById('c');
    if (map && !plate.parentElement) { map.appendChild(plate); map.appendChild(ff); map.appendChild(fate); }
    clocks(cv);
    if (!on()) { plate.hidden = true; ff.hidden = true; if (F && typeof Camera !== 'undefined') Camera.ahead(null); return; }
    const top = (cv ? cv.offsetTop : 0) + 8; plate.style.top = top + 'px'; ff.style.top = top + 'px';
    const p = pace(speedNow()), cd = current(p);
    ff.hidden = !playing || mode !== 'quiet' || !!cd;
    // the camera's own caption (what is on screen, ⏮ ⏭ jumps, "nothing further") goes under the plaque
    const cap = Camera.captionEl && Camera.captionEl(), over = cd ? plate : ff.hidden ? null : ff;
    if (cap && over) cap.style.top = top + over.offsetHeight + 6 + 'px';
    if (cinema) shiftTools();
    if (!cd) { plate.hidden = true; Camera.ahead(preroll()); return; }
    const c = cd.c;
    Camera.ahead(shotOf(c));
    plate.hidden = false;
    plate.classList.toggle('after', !cd.wait);
    if (cd.wait) {
      const left = Foresight.eta(cd.dur, i, frac, c.k);
      if (!last.total || left > last.total) last.total = left;
      const [what, why] = waiting(c);
      set($('.what'), what); set($('.why'), why); set($('.t'), '⏳ ' + clock(left));
      $('.bar i').style.width = (100 * (1 - left / last.total)).toFixed(1) + '%';
      plate.classList.toggle('hot', left <= 10);
    } else {
      const [what, why] = happened(c);
      set($('.what'), what); set($('.why'), why); set($('.t'), ''); plate.classList.remove('hot');
    }
  }

  // ---------- cinema mode ----------
  let cinema = false, wentFull = false, idle = null;
  const btn = document.createElement('button');
  btn.id = 'efir-btn'; btn.textContent = '⛶ Кино'; btn.title = 'Кинорежим: карта на весь экран (клавиша F, выход F или Esc)';
  btn.setAttribute('aria-pressed', 'false');
  function setCinema(v) {
    cinema = v; document.body.classList.toggle('cinema', v); btn.setAttribute('aria-pressed', v);
    const el = document.documentElement;
    if (v && !document.fullscreenElement && el.requestFullscreen)
      el.requestFullscreen().then(() => { wentFull = true; }, () => {});
    if (!v && wentFull && document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
    if (!v) { wentFull = false; const tools = document.getElementById('cam-tools'); if (tools) tools.style.transform = ''; }
    wake();
  }
  // In cinema the bar floats over the bottom of the map: lift the camera buttons (+ − ⤢ 🎬 ⏮ ⏭) above it while it shows.
  function shiftTools() {
    const tools = document.getElementById('cam-tools'), bar = document.getElementById('bar');
    if (tools) tools.style.transform = document.body.classList.contains('awake') && bar ? `translateY(-${bar.offsetHeight}px)` : '';
  }
  function wake() {
    document.body.classList.add('awake'); clearTimeout(idle);
    if (cinema) idle = setTimeout(() => document.body.classList.remove('awake'), 2500);
  }
  btn.onclick = () => { setCinema(!cinema); btn.blur(); };
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && wentFull && cinema) { wentFull = false; setCinema(false); } });
  for (const ev of ['pointermove', 'pointerdown', 'keydown', 'touchstart']) window.addEventListener(ev, wake, { passive: true });
  window.addEventListener('keydown', e => {
    const el = document.activeElement, typing = el && (/TEXTAREA|SELECT/.test(el.tagName) || el.isContentEditable ||
      (el.tagName === 'INPUT' && !/^(range|checkbox|radio|button)$/.test(el.type)));
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === 'KeyF') setCinema(!cinema);
    else if (e.key === 'Escape' && cinema && !(window.Hero && Hero.current)) setCinema(false);   // Esc closes a villager's page first
  }, true);   // capture: before hero.js closes its page on the same Esc
  function addButton() { const bar = document.getElementById('bar'), log = document.getElementById('logbtn'); if (bar && !btn.parentElement) bar.insertBefore(btn, log); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addButton); else addButton();

  return { reset, add, tick, frame, setCinema, cinema: () => cinema, mode: () => mode, foresight: () => F, fate: () => G };
})();
window.Efir = Efir;
