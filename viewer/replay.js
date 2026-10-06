// Replay controls, like watching a replay in a game, and a counter of the day.
// - ⏮ / ⏭ next to the camera buttons (keys [ and ]): jump to the previous / next notable event (director score
//   >= MIN in camera.js) and show it for a few seconds (Camera.pin), whether the auto camera is on or off. The auto
//   camera (🎬 Авто) switches between events by itself; these buttons are the manual switch.
// - The day counter over the top-right corner of the map: deals, talks, gifts, conflicts, deaths so far today (up to
//   the moment on screen). A click on a counter jumps to the next event of that kind. A red chip counts down to a
//   warned raid / beast / traveler.
// Reads the viewer's globals (ticks, i, go, selected, setPlaying) at run time; nothing else depends on it.
(() => {
  const MIN = 6;
  const KINDS = [
    { ic: '🤝', name: 'сделки', re: /^(trade|sell|buy|sale|order_delivered|land_bought|land_sold|lend|repay)$/ },
    { ic: '💬', name: 'разговоры', re: /^(say|whisper|gossip|letter_sent|hang_out)$/ },
    { ic: '🎁', name: 'подарки и помощь', re: /^(gift|give|share|care|help_stranger|pour_water|defend)$/ },
    { ic: '😠', name: 'ссоры, кражи, драки', re: /^(steal|steal_attempt|set_fire|default|debt_seized|evicted|divorce|proposal_refused|embezzle|dice_challenge)$|fight|attack|duel|brawl/ },
    { ic: '✝', name: 'смерти', re: /^death$/ },
  ];
  const any = e => Camera.score(e.kind) >= MIN;

  // Where the viewer is: the tick shown and, after a jump, the tick we jumped to (so ⏭ ⏭ walks event by event).
  // The same villager doing the same thing again within an hour or so is not a new event (a thief on a spree).
  let last = null, lastEv = null;
  const group = k => /^(steal|theft|steal_attempt|robbed|witness|caught)$/.test(k) ? 'theft' : /^(threat_|beast_|plundered|defend)/.test(k) ? 'threat' : k;
  const same = (e, k) => lastEv && group(e.kind) === group(lastEv.kind) && Math.abs(k - last) <= 4 &&
    (!e.actor || !lastEv.actor || e.actor === lastEv.actor);
  function find(dir, test) {
    const from = last != null && Math.abs(last - i) <= 3 ? last : i;
    for (let k = from + dir; k >= 0 && k < ticks.length; k += dir) {
      const best = (ticks[k].events || []).filter(e => test(e) && !same(e, k))
        .sort((a, b) => Camera.score(b.kind) - Camera.score(a.kind))[0];
      if (best) return [k, best];
    }
    return null;
  }
  function jump(dir, test = any, what = 'событий') {
    if (typeof ticks === 'undefined' || !ticks.length) return;
    const hit = find(dir, test);
    if (!hit) { Camera.flash(dir > 0 ? `Дальше ${what} пока нет` : `Раньше ${what} нет`); return; }
    const [k, ev] = hit;
    last = k; lastEv = ev; selected = null;
    go(Math.max(0, k - 1));                       // a moment before, so it plays out on screen
    Camera.pin(ev, ticks[k]);
    if (typeof setPlaying === 'function') setPlaying(true);
  }

  // ⏮ ⏭ in the camera toolbar (bottom-left of the map)
  let added = false;
  function addButtons() {
    const bar = Camera.toolbar && Camera.toolbar(); if (!bar || added) return; added = true;
    for (const [t, title, dir] of [['⏮', 'к прошлому событию (клавиша [)', -1], ['⏭', 'к следующему событию (клавиша ])', 1]]) {
      const bt = document.createElement('button'); bt.textContent = t; bt.title = title; bt.onclick = () => jump(dir);
      bt.style.cssText = 'min-width:30px;height:30px;padding:0 4px;font:600 16px system-ui;opacity:.9';
      bar.appendChild(bt);
    }
  }
  window.addEventListener('keydown', e => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName)) return;
    if (e.key === ']' || e.key === 'ъ') jump(1); else if (e.key === '[' || e.key === 'х') jump(-1);
  });

  // ---------- day counter ----------
  const box = document.createElement('div');
  box.style.cssText = 'position:absolute;right:8px;top:8px;z-index:5;display:flex;gap:4px;font:600 13px system-ui';
  const chips = KINDS.map(kd => {
    const b = document.createElement('button');
    b.style.cssText = 'all:unset;cursor:pointer;padding:3px 8px;border-radius:12px;background:rgba(27,27,36,.82);color:#e8efe9;' +
      'box-shadow:0 1px 4px rgba(0,0,0,.35)';
    b.title = `${kd.name} за сегодня; нажми, чтобы перейти к следующему`;
    b.onclick = () => jump(1, e => kd.re.test(e.kind), kd.name);
    box.appendChild(b); return b;
  });
  const countdown = document.createElement('span');
  countdown.style.cssText = 'padding:3px 8px;border-radius:12px;background:rgba(160,40,30,.9);color:#fff;box-shadow:0 1px 4px rgba(0,0,0,.35)';
  countdown.hidden = true; box.prepend(countdown);
  const dayOf = k => { const e = (ticks[k].events || []).find(e => e.day != null); return e ? e.day : ticks[Math.max(0, k - 1)].view.day; };
  let key = null;
  function refresh() {
    const map = document.getElementById('map');
    if (!box.parentElement && map) map.appendChild(box);
    if (typeof ticks === 'undefined' || !ticks.length || typeof Camera === 'undefined' || !Camera.pin) { box.hidden = true; return; }
    addButtons();
    box.hidden = false;
    const now = Math.min(i, ticks.length - 1), day = dayOf(now);
    const k2 = now + '|' + ticks.length + '|' + Math.round(frac * 4); if (key === k2) return; key = k2;
    const n = KINDS.map(() => 0);
    for (let k = now; k >= 0 && dayOf(k) >= day; k--)
      for (const e of ticks[k].events || []) {
        if (e.day != null && e.day !== day) continue;
        KINDS.forEach((kd, j) => { if (kd.re.test(e.kind)) n[j]++; });
      }
    chips.forEach((c, j) => { c.textContent = `${KINDS[j].ic} ${n[j]}`; c.style.opacity = n[j] ? 1 : .55; });
    // A warned raid / beast / traveler on its way: a countdown chip, so the wait is not blind.
    const v = ticks[now].view, th = (v.threats || []).filter(x => x.state === 'coming')
      .sort((a, b) => a.arrive_day - b.arrive_day || a.arrive_hour - b.arrive_hour)[0];
    countdown.hidden = !th;
    if (th) {
      const mins = ((th.arrive_day - v.day) * 24 + th.arrive_hour - v.hour) * 60 - (v.minute || 0) +   // the view is the end
        Math.round((1 - Math.min(1, frac)) * (v.tick_minutes || 60) / 15) * 15;                     // of the tick on screen
      const d = Math.floor(mins / 1440), h = Math.floor(mins % 1440 / 60), m = mins % 60;
      const left = mins <= 0 ? 'вот-вот' : 'через ' + (d ? `${d} д ` : '') + (d || h ? `${h} ч` : `${m} мин`);
      countdown.textContent = `${{ beast: '🐺', raid: '🗡', traveler: '🎒' }[th.kind] || '⚠'} ${left}`;
      countdown.title = `${{ beast: 'Зверь', raid: 'Бандиты', traveler: 'Путник' }[th.kind] || 'Угроза'} придёт в день ${th.arrive_day} около ${th.arrive_hour}:00`;
    }
  }
  setInterval(refresh, 400);
})();
