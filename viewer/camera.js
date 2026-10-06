// Camera for the pixel map: wheel / pinch / +/- buttons / keys zoom, drag pans, a selected villager is followed.
// Director mode (🎬, on by default) moves by itself to the most interesting thing happening (fire, theft, fight, wedding, election...).
// PixelMap attaches it to its canvas on the first draw; everything here is in map pixels (W x H) or canvas pixels.
const Camera = (() => {
  const MAXZ = 6;
  let cv = null, box = null, W = 1, H = 1, S = 2, z = 1, zt = 1, cx = 0, cy = 0, follow = null, down = null, dragged = false;
  let anchor = null;   // [wx, wy, px, py]: the map point that stays under the cursor while a zoom animates

  const clampZ = v => Math.max(1, Math.min(MAXZ, v));
  function clampC() {
    const hw = W / (2 * z), hh = H / (2 * z);
    cx = Math.max(hw, Math.min(W - hw, cx)); cy = Math.max(hh, Math.min(H - hh, cy));
  }
  function view() { clampC(); return { x0: cx - W / (2 * z), y0: cy - H / (2 * z), z }; }
  // Client (mouse) coordinates -> canvas pixels; the canvas uses object-fit: contain, so undo the letterboxing.
  function toCanvas(e) {
    const r = cv.getBoundingClientRect(), k = Math.min(r.width / cv.width, r.height / cv.height);
    return [(e.clientX - r.left - (r.width - cv.width * k) / 2) / k, (e.clientY - r.top - (r.height - cv.height * k) / 2) / k];
  }
  function toWorld(px, py) { const v = view(); return [v.x0 + px / (S * z), v.y0 + py / (S * z)]; }
  function toScreen(wx, wy) { const v = view(); return [(wx - v.x0) * S * z, (wy - v.y0) * S * z]; }
  // Zoom keeping the map point under (px, py) canvas pixels in place; the zoom itself glides there in update().
  function zoomAt(f, px = cv.width / 2, py = cv.height / 2) {
    const [wx, wy] = toWorld(px, py);
    zt = clampZ(zt * f); anchor = [wx, wy, px, py];
  }
  function reset() { follow = null; zt = 1; anchor = null; director.on && setDirector(false, false); }
  function attach(canvas, w, h, s) {
    W = w; H = h; S = s;
    if (cv === canvas) return;
    cv = canvas; cx = W / 2; cy = H / 2;
    // Mouse wheel: about x1.5 per notch. Trackpad pinch arrives as ctrl+wheel with small deltas, so it is scaled up.
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const d = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      zoomAt(Math.exp(-Math.max(-300, Math.min(300, d)) * (e.ctrlKey ? .012 : .004)), ...toCanvas(e));
    }, { passive: false });
    canvas.addEventListener('pointerdown', e => { down = { p: toCanvas(e), cx, cy }; dragged = false; });
    window.addEventListener('pointermove', e => {
      if (!down || !(e.buttons & 1)) return;
      const [px, py] = toCanvas(e), dx = px - down.p[0], dy = py - down.p[1];
      if (!dragged && Math.hypot(dx, dy) < 6) return;
      dragged = true; follow = null; anchor = null; director.hold = 8; director.pin = null; canvas.style.cursor = 'grabbing';
      cx = down.cx - dx / (S * z); cy = down.cy - dy / (S * z); clampC();
    });
    window.addEventListener('pointerup', () => { down = null; canvas.style.cursor = ''; });
    // A drag must not count as a click on a villager.
    window.addEventListener('click', e => { if (dragged && e.target === canvas) { e.stopImmediatePropagation(); dragged = false; } }, true);
    window.addEventListener('keydown', e => {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName)) return;
      if (e.key === '+' || e.key === '=') zoomAt(1.5); else if (e.key === '-') zoomAt(1 / 1.5); else if (e.key === '0') reset();
      else if (e.key === 'd' || e.key === 'в') setDirector(!director.on);
    });
    box = document.createElement('div'); const parent = canvas.parentElement;
    if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
    box.style.cssText = 'position:absolute;left:8px;display:flex;gap:4px;z-index:5';   // bottom-left of the map, kept there in update()
    for (const [t, title, fn] of [['+', 'приблизить (колесо мыши, щипок)', () => zoomAt(1.6)], ['−', 'отдалить', () => zoomAt(1 / 1.6)],
                                  ['⤢', 'вся деревня (клавиша 0)', reset], ['🎬', 'авто-камера: сама едет туда, где что-то происходит (клавиша D)', () => setDirector(!director.on)]]) {
      const bt = document.createElement('button'); bt.textContent = t; bt.title = title; bt.onclick = fn;
      bt.style.cssText = 'min-width:30px;height:30px;padding:0 4px;font:600 16px system-ui;opacity:.9';
      box.appendChild(bt); if (t === '🎬') director.btn = bt;
    }
    caption = document.createElement('div');
    caption.style.cssText = 'position:absolute;left:50%;transform:translateX(-50%);z-index:5;padding:4px 12px;border-radius:6px;' +
      'font:600 13px system-ui;background:rgba(27,27,36,.85);color:#ffe9a8;pointer-events:none;opacity:0;transition:opacity .4s';
    parent.appendChild(box); parent.appendChild(caption);
    let on = true; try { on = localStorage.getItem('aiv-director2') !== '0'; } catch (e) {}
    setDirector(on, false);
  }

  // ---------- director: pick the most interesting event and frame it ----------
  // Score per event kind; unknown kinds score 0 and are never chosen. Fights/attacks are matched by name, so new
  // combat events from the engine are picked up without changes here.
  const DRAMA = { feast: 6, fire: 10, fire_grows: 7, burned_down: 9, extinguish: 8, fire_out: 8, pour_water: 6, death: 10,
    steal: 9, theft: 9, steal_attempt: 8, robbed: 8, witness: 6, caught: 8, report_theft: 6, eviction: 7, hospital: 7,
    wedding: 8, proposal: 7, proposal_refused: 6, divorce: 7, inheritance: 6, exile: 8, elected: 7, law_passed: 6,
    law_proposed: 4, election: 7, starving: 5, run_for_mayor: 4, candidate: 4, election_day: 3, vote: 2, default: 6, lend: 3, trade: 3, give: 3, gift: 3, whisper: 2,
    gossip: 3, praise: 4, title_given: 7, say: 1, offer: 2, set_fire: 9, arson_seen: 9, land_bought: 5, land_sold: 5, land_offer: 2,
    // threats from outside (aivillage/threats.py)
    threat_arrived: 10, beast_attack: 9, plundered: 9, defend: 9, threat_defeated: 9, threat_moves: 6,
    threat_left: 5, threat_warning: 5, help_stranger: 4, chase_stranger: 5 };
  const LABEL = { fire: '🔥 Пожар', fire_grows: '🔥 Пожар разгорается', burned_down: '🔥 Дом сгорел', extinguish: '💧 Тушат пожар',
    fire_out: '💧 Пожар потушен', pour_water: '💧 Тушат пожар', death: '✝ Смерть', steal: '🕵 Кража', theft: '🕵 Кража',
    steal_attempt: '🕵 Кража', robbed: '🕵 Кража', caught: '🚨 Вора поймали', witness: '👀 Свидетель', eviction: '🏚 Выселение',
    hospital: '🏥 В больницу', wedding: '💍 Свадьба', proposal: '💍 Предложение', divorce: '💔 Развод', exile: '⛔ Изгнание',
    elected: '🏛 Выборы', law_passed: '📜 Новый закон', law_proposed: '📜 Закон', run_for_mayor: '🏛 Выборы', candidate: '🏛 Выборы', election_day: '🗳 День выборов', vote: '🗳 Выборы',
    default: '💸 Долг не вернули', election: '🏛 Итоги выборов', starving: '😫 Голод', offer: '💬 Торгуются',
    say: '💬 Разговор', whisper: '🤫 Шепчутся', decline: '💬 Отказ', lend: '💰 Заём', trade: '🤝 Сделка', give: '🎁 Подарок', gift: '🎁 Подарок', gossip: '🗣 Сплетня', praise: '🏅 Похвала', title_given: '🏅 Звание',
    set_fire: '🔥 Поджог', arson_seen: '🔥 Поджог', land_bought: '🏡 Купил землю', land_sold: '🏡 Продал землю', land_offer: '🏡 Продаёт землю',
    threat_arrived: '⚠ Беда пришла', beast_attack: '🐺 Зверь нападает', plundered: '🗡 Грабят', defend: '⚔ Отбиваются',
    threat_defeated: '🏆 Отбились', threat_moves: '👣 Идёт к следующему дому', threat_left: '🌲 Ушёл',
    threat_warning: '⚠ Предупреждение', help_stranger: '🍞 Кормят путника', chase_stranger: '🚪 Прогнали путника' };
  const THREAT = { beast: '🐺 Зверь', raid: '🗡 Бандиты', traveler: '🎒 Путник' };
  const score = k => DRAMA[k] || (/fight|attack|duel|brawl|hit/.test(k) ? 9 : 0);
  const label = k => LABEL[k] || (/fight|attack|duel|brawl|hit/.test(k) ? '⚔ Драка' : '👀');
  // On by default: only an explicit "off" from the viewer (stored under a new key) keeps it off.
  const director = { on: false, shot: null, age: 0, hold: 0, seen: null, btn: null };
  let caption = null;
  // persist: the viewer pressed the button (clip.js toggles it while recording and must not change the choice).
  function setDirector(on, persist = true) {
    director.on = on; director.shot = null; director.hold = 0;
    if (director.btn) { director.btn.style.background = on ? '#f2c14e' : ''; director.btn.style.color = on ? '#1b1b24' : '';
      director.btn.setAttribute('aria-pressed', on); director.btn.textContent = on ? '🎬 Авто' : '🎬 Авто: выкл'; }
    if (caption) caption.style.opacity = 0;
    if (persist) try { localStorage.setItem('aiv-director2', on ? '1' : '0'); } catch (e) {}
  }
  const directorOn = () => director.on;
  // t: the tick on screen; pos(name) -> villager [x, y]; at(loc) -> location [x, y]. A shot is held at least
  // MIN_HOLD s; only a clearly bigger event (+3) cuts it short. Small talk (score < 3) is shown only when nothing
  // else happens, and a quiet stretch drifts back out to the whole village. Threats on the map (a beast, bandits,
  // a traveler) and burning houses stay worth watching for as long as they are there.
  const MIN_HOLD = 7, CHAT_HOLD = 10, QUIET = 14;
  function direct(dt, t, pos, at, tr) {
    if (!t) return;
    if (director.pin && (director.pin.left -= dt) <= 0) director.pin = null;
    const pinned = director.pin;
    if (!pinned) {   // a pinned shot (⏮ ⏭) wins over everything below
      if (!director.on) { if (caption) { flashT -= dt; caption.style.opacity = flashT > 0 ? 1 : 0; } return; }
      director.age += dt; if (director.hold > 0) { director.hold -= dt; return; }   // the viewer just dragged: let them look
      if (lastSel) return;                                                           // a picked villager is followed instead
    }
    if (!pinned && director.seen !== t.tick) {
      director.seen = t.tick;
      let best = null;
      for (const e of t.events || []) {
        const sc = score(e.kind); if (!sc) continue;
        const d = e.data || {}, who = e.actor && pos(e.actor) ? e.actor : null,
          th = d.threat && (t.view.threats || []).find(x => x.id === d.threat && x.state === 'here'),   // where the beast is now
          loc = (th && th.location) || e.location || d.house || d.location || d.target;
        if (!who && !(loc && at(loc))) continue;
        const what = d.threat_kind && THREAT[d.threat_kind];
        if (!best || sc > best.sc) best = { sc, who, loc, kind: e.kind, what };
      }
      for (const th of (t.view.threats || [])) if (th.state === 'here' && at(th.location) && (!best || best.sc < 8))
        best = { sc: 8, who: null, loc: th.location, kind: 'threat_here', what: THREAT[th.kind] };
      const fire = (t.view.fires || []).find(at);   // a house still burning stays worth watching
      if (fire && (!best || best.sc < 7)) best = { sc: 7, who: null, loc: fire, kind: 'fire' };
      const cur = director.shot, same = cur && best && cur.loc === best.loc && cur.who === best.who;
      if (best && same) { Object.assign(cur, best, { sc: Math.max(cur.sc, best.sc) }); }    // same spot: keep the shot going
      else if (best && best.sc < 3 && cur && director.age < CHAT_HOLD) {}                  // chatter never cuts a shot
      else if (best && (!cur || director.age > MIN_HOLD || best.sc >= cur.sc + 3)) { director.shot = best; director.age = 0; }
      else if (!best && cur && director.age > QUIET) director.shot = null;
    }
    const s = pinned ? pinned.shot : director.shot;
    if (caption && flashT > 0) { flashT -= dt; caption.style.opacity = 1; caption.textContent = flashText; caption.style.top = (cv.offsetTop + 8) + 'px'; }
    else if (caption) {
      caption.style.opacity = s ? 1 : 0;
      if (s) caption.textContent = (s.kind === 'threat_here' ? s.what : label(s.kind) + (s.what ? ' · ' + s.what : '')) +
        (s.who ? ': ' + s.who : '') + (s.loc && t.view.locations[s.loc] ? ' · ' + tr(t.view.locations[s.loc]) : '');
      caption.style.top = (cv.offsetTop + 8) + 'px';
    }
    const p = s && (s.who ? pos(s.who) : at(s.loc));
    if (p) { follow = null; zt = s.sc >= 6 ? 2.6 : 2; anchor = null;
      const f = 1 - Math.exp(-dt * (pinned ? 3 : 1.6)); cx += (p[0] - cx) * f; cy += (p[1] - cy) * f; }
    else { zt = 1; anchor = null; }
  }

  // Manual replay control (viewer/replay.js): show this event now and hold it `sec` seconds, whatever the
  // director would pick (works with the auto camera off too). ev: a log event; t: the tick that holds it.
  function pin(ev, t, sec = 9) {
    const d = ev.data || {}, th = d.threat && ((t && t.view.threats) || []).find(x => x.id === d.threat && x.state === 'here');
    director.pin = { left: sec, shot: { sc: score(ev.kind) || 6, who: ev.actor || null, kind: ev.kind,
      loc: (th && th.location) || ev.location || d.house || d.location || d.target, what: d.threat_kind && THREAT[d.threat_kind] } };
    director.shot = null; director.age = 0; director.hold = 0; follow = null;
  }
  let flashT = 0, flashText = '';
  function flash(text, sec = 2.5) { flashText = text; flashT = sec; if (caption) { caption.textContent = text; caption.style.top = (cv.offsetTop + 8) + 'px'; } }
  const toolbar = () => box;

  // Called every frame. sel: selected villager name; pos(name) -> [x, y] map pixels or undefined.
  let lastSel = null;
  function update(dt, sel, pos) {
    if (sel !== lastSel) { lastSel = sel; follow = sel; anchor = null; if (sel && zt < 2.5) zt = 2.5; director.shot = null; if (sel) director.pin = null; }
    if (Math.abs(zt - z) > .001) z += (zt - z) * (1 - Math.exp(-dt * 14)); else z = zt;
    if (anchor) { const [wx, wy, px, py] = anchor; cx = wx - px / (S * z) + W / (2 * z); cy = wy - py / (S * z) + H / (2 * z);
      if (z === zt) anchor = null; }
    const p = follow && pos(follow);
    if (p && !anchor) { const f = 1 - Math.exp(-dt * 4); cx += (p[0] - cx) * f; cy += (p[1] - cy) * f; }
    clampC();
    if (box) box.style.top = (cv.offsetTop + cv.offsetHeight - 38) + 'px';
  }

  return { attach, update, direct, view, toWorld, toScreen, setDirector, directorOn, score, label, pin, flash, toolbar };
})();
