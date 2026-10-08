// Camera for the pixel map: wheel / pinch / +/- buttons / keys zoom, drag pans, a selected villager is followed.
// Director mode (🎬, on by default) moves by itself to the most interesting thing happening (fire, theft, fight, wedding, election...).
// PixelMap attaches it to its canvas on the first draw; everything here is in map pixels (W x H) or canvas pixels.
const Camera = (() => {
  const MAXZ = 6;
  let cv = null, box = null, W = 1, H = 1, S = 2, z = 1, zt = 1, cx = 0, cy = 0, follow = null, down = null, dragged = false;
  let anchor = null;   // [wx, wy, px, py]: the map point that stays under the cursor while a zoom animates
  // goal: where the auto camera wants to be {x, y, z, w}; update() glides there on a critically damped spring (no
  // sudden starts or stops, w = stiffness). vx, vy, vz: the glide's speed (vz in log zoom). placed: the first frame
  // was framed (the loading screen waits for it, viewer/setup.js).
  // aim: the goal itself eased first, so even the glide's acceleration starts softly.
  let goal = null, aim = null, vx = 0, vy = 0, vz = 0, placed = false;

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
  // The viewer zoomed by hand: the auto camera lets them look for a while, like after a drag.
  function zoomAt(f, px = cv.width / 2, py = cv.height / 2) {
    const [wx, wy] = toWorld(px, py);
    if (goal) zt = z;
    goal = null; director.hold = 8; director.pin = null;
    zt = clampZ(zt * f); anchor = [wx, wy, px, py];
  }
  function reset() { follow = null; zt = 1; anchor = null; goal = null; director.on && setDirector(false, false); }
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
      dragged = true; follow = null; anchor = null; goal = null; director.hold = 8; director.pin = null; canvas.style.cursor = 'grabbing';
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
    box.id = 'cam-tools'; box.style.cssText = 'position:absolute;left:8px;display:flex;gap:4px;z-index:5';   // bottom-left of the map, kept there in update()
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
    threat_left: 5, threat_warning: 5, help_stranger: 4, chase_stranger: 5,
    // a polity (aivillage/polity.py): coups, elections, laws, the treasury; and what else happens to people
    polity_founded: 7, polity_form: 7, polity_leaders: 7, polity_law_passed: 6, polity_law_failed: 6, polity_law_proposed: 4,
    polity_petition: 5, polity_embezzle: 9, polity_embezzlement_found: 8, polity_audit: 5, polity_tax_set: 4,
    theft_report: 6, overheard: 5, crisis: 5, sick: 4, place_lost: 4, project_done: 5, village_stage: 6, law_failed: 6,
    discharged: 4, stranger_thanks: 4 };
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
    threat_warning: '⚠ Предупреждение', help_stranger: '🍞 Кормят путника', chase_stranger: '🚪 Прогнали путника',
    polity_founded: '🏛 Основано общество', polity_form: '🏛 Форма правления', polity_leaders: '🏛 Казначей',
    polity_law_passed: '📜 Закон принят', polity_law_failed: '📜 Закон не прошёл', polity_law_proposed: '📜 Предлагают закон',
    polity_petition: '✍ Петиция', polity_embezzle: '💰 Казну тайно обокрали', polity_embezzlement_found: '🚨 Растрата раскрыта',
    polity_audit: '🔍 Ревизия казны', polity_tax_set: '💰 Налог', theft_report: '📢 Донос о краже', overheard: '👂 Подслушал',
    crisis: '⚠ Беда в деревне', sick: '🤒 Заболел', place_lost: '🪓 Остался без работы', project_done: '🏗 Стройка готова',
    village_stage: '🏘 Деревня растёт', law_failed: '📜 Закон не прошёл', discharged: '🏥 Вернулся из больницы',
    stranger_thanks: '🎒 Путник благодарит' };
  const THREAT = { beast: '🐺 Зверь', raid: '🗡 Бандиты', traveler: '🎒 Путник' };
  // d (the event's data, optional) refines a few kinds: a traveler is milder than a beast, an election result is news
  // but the "vote until ..." notice is not.
  const score = (k, d) => {
    if (d && k === 'threat_arrived' && d.threat_kind === 'traveler') return 6;
    if (d && k === 'polity_leaders') return d.keeper || (d.rulers || []).length ? 8 : 4;
    return DRAMA[k] || (/fight|attack|duel|brawl|hit/.test(k) ? 9 : 0);
  };
  const label = k => LABEL[k] || (/fight|attack|duel|brawl|hit/.test(k) ? '⚔ Драка' : '👀');
  // On by default: only an explicit "off" from the viewer (stored under a new key) keeps it off.
  // ahead: a shot of something about to happen, set every frame by the «Эфир» replay (viewer/efir.js) so the camera is
  // there before it happens; it carries no caption (the countdown plaque speaks instead).
  const director = { on: false, shot: null, age: 0, hold: 0, seen: null, btn: null, ahead: null };
  let caption = null;
  // persist: the viewer pressed the button (clip.js toggles it while recording and must not change the choice).
  function setDirector(on, persist = true) {
    director.on = on; director.shot = null; director.hold = 0; director.ahead = null;
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
      if (!director.on) { goal = null; placed = true; if (caption) { flashT -= dt; caption.style.opacity = flashT > 0 ? 1 : 0; } return; }
      director.age += dt; if (director.hold > 0) { director.hold -= dt; goal = null; placed = true; return; }   // the viewer just dragged: let them look
      if (lastSel) { goal = null; placed = true; return; }                                                      // a picked villager is followed instead
    }
    const ah = !pinned && director.ahead;
    if (ah) {   // the «Эфир» replay knows what comes next: go there now
      const cur = director.shot;
      if (!cur || !cur.ahead || cur.loc !== ah.loc || cur.who !== ah.who) { director.shot = { ...ah, ahead: true }; director.age = 0; }
      director.seen = null;
    } else if (!pinned && director.seen !== t.tick) {
      director.seen = t.tick;
      for (const e of t.events || []) if (e.actor && pos(e.actor)) idle.next = e.actor;   // who did something last
      const was = director.shot;   // a look-ahead shot: it is happening now, so label it (one with no kind just ends)
      if (was && was.ahead) { if (was.kind) was.ahead = false; else director.shot = null; }
      let best = null;
      for (const e of t.events || []) {
        const sc = score(e.kind, e.data); if (!sc) continue;
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
      const cur = director.shot, same = cur && best && (cur.loc || null) === (best.loc || null) && cur.who === best.who;
      if (best && same) { Object.assign(cur, best, { sc: Math.max(cur.sc, best.sc) }); }    // same spot: keep the shot going
      else if (best && best.sc < 3 && cur && director.age < CHAT_HOLD) {}                  // chatter never cuts a shot
      else if (best && (!cur || director.age > MIN_HOLD || best.sc >= cur.sc + 3)) { director.shot = best; director.age = 0; }
      else if (!best && cur && director.age > QUIET) director.shot = null;
    }
    const s = pinned ? pinned.shot : director.shot;
    if (caption && flashT > 0) { flashT -= dt; caption.style.opacity = 1; caption.textContent = flashText; caption.style.top = (cv.offsetTop + 8) + 'px'; }
    else if (caption) {
      caption.style.opacity = s && !s.ahead ? 1 : 0;
      if (s && !s.ahead) caption.textContent = (s.kind === 'threat_here' ? s.what : label(s.kind) + (s.what ? ' · ' + s.what : '')) +
        (s.who ? ': ' + s.who : '') + (s.loc && t.view.locations[s.loc] ? ' · ' + tr(t.view.locations[s.loc]) : '');
      caption.style.top = (cv.offsetTop + 8) + 'px';
    }
    const p = s && (s.who ? pos(s.who) : at(s.loc));
    if (p) { goal = { x: p[0], y: p[1], z: s.sc >= 6 ? 2.6 : 2, w: pinned ? 3 : 1.8 }; idle.quiet = 0; idle.wide = 0; }
    else quiet(dt, t, pos);
    follow = null; anchor = null;
    if (!placed) { cx = goal.x; cy = goal.y; z = zt = goal.z; vx = vy = vz = 0; placed = true; }   // the first frame is framed already
  }

  // Nothing worth a shot: stay with one villager (the one who did something last, held a while so the picture is
  // calm), and only now and then pull back for a few seconds to show everyone, just far enough to fit them all.
  const IDLE_HOLD = 20, WIDE_EVERY = 75, WIDE_HOLD = 7;
  const idle = { who: null, age: 0, quiet: 0, wide: 5, next: null };   // wide: the first seconds show the whole group
  function quiet(dt, t, pos) {
    idle.quiet += dt; idle.age += dt;
    if (idle.wide <= 0 && idle.quiet > WIDE_EVERY) { idle.wide = WIDE_HOLD; idle.quiet = 0; }
    const names = Object.keys(t.view.agents || {}).filter(n => pos(n));
    if (idle.wide > 0 || !names.length) { idle.wide -= dt; goal = group(names, pos); return; }
    if (!pos(idle.who) || (idle.age > IDLE_HOLD && idle.next && idle.next !== idle.who && pos(idle.next))) {
      idle.who = pos(idle.next) ? idle.next : names[Math.floor(Math.random() * names.length)]; idle.age = 0;
    }
    const p = pos(idle.who);
    goal = { x: p[0], y: p[1], z: 2, w: 1.4 };
  }
  // The smallest view (at most as close as a shot) that holds all these villagers, with room for their bubbles.
  function group(names, pos) {
    if (!names.length) return { x: W / 2, y: H / 2, z: 1, w: 1.2 };
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of names) { const [x, y] = pos(n); x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    x0 -= 70; x1 += 70; y0 -= 90; y1 += 40;
    return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: clampZ(Math.min(2, W / (x1 - x0), H / (y1 - y0))), w: 1.2 };
  }
  // The loading screen (viewer/setup.js) stays up until the camera has framed the first picture.
  const ready = () => placed;

  // Manual replay control (viewer/replay.js): show this event now and hold it `sec` seconds, whatever the
  // director would pick (works with the auto camera off too). ev: a log event; t: the tick that holds it.
  function pin(ev, t, sec = 9) {
    const d = ev.data || {}, th = d.threat && ((t && t.view.threats) || []).find(x => x.id === d.threat && x.state === 'here');
    director.pin = { left: sec, shot: { sc: score(ev.kind) || 6, who: ev.actor || null, kind: ev.kind,
      loc: (th && th.location) || ev.location || d.house || d.location || d.target, what: d.threat_kind && THREAT[d.threat_kind] } };
    director.shot = null; director.age = 0; director.hold = 0; director.ahead = null; follow = null;
  }
  // «Эфир» (viewer/efir.js): shot = {who, loc, sc} of what is about to happen, or null. Kept until changed.
  function ahead(shot) { director.ahead = shot && director.on ? shot : null; }
  // The villager the picture is about: the one picked, else the director's current shot.
  function focus() {
    if (lastSel) return lastSel;
    const s = director.pin ? director.pin.shot : director.on ? director.shot : null;
    return s && s.who || null;
  }
  let flashT = 0, flashText = '';
  function flash(text, sec = 2.5) { flashText = text; flashT = sec; if (caption) { caption.textContent = text; caption.style.top = (cv.offsetTop + 8) + 'px'; } }
  const toolbar = () => box;

  // Called every frame. sel: selected villager name; pos(name) -> [x, y] map pixels or undefined.
  let lastSel = null;
  function update(dt, sel, pos) {
    if (sel !== lastSel) { lastSel = sel; follow = sel; anchor = null; if (sel && zt < 2.5) zt = Math.max(2.5, z); director.shot = null; if (sel) director.pin = null; }
    if (goal && !follow && !anchor) {   // the auto camera: a soft spring, so it eases in and out instead of jerking
      const w = goal.w, wz = w * .7, lz = Math.log(z), f = 1 - Math.exp(-dt * w * 1.5);
      if (!aim) aim = { x: cx, y: cy, z: lz, gx: goal.x, gy: goal.y, vx: 0, vy: 0 };
      // how fast the goal itself walks (a cut to another spot is not walking), so a walking villager stays in the
      // middle of the picture instead of being trailed
      const gdx = goal.x - aim.gx, gdy = goal.y - aim.gy, walk = dt && Math.hypot(gdx, gdy) < 10, g = 1 - Math.exp(-dt * 4);
      aim.vx += ((walk ? gdx / dt : 0) - aim.vx) * g; aim.vy += ((walk ? gdy / dt : 0) - aim.vy) * g; aim.gx = goal.x; aim.gy = goal.y;
      aim.x += (goal.x - aim.x) * f; aim.y += (goal.y - aim.y) * f; aim.z += (Math.log(goal.z) - aim.z) * f;
      const hw = W / (2 * z), hh = H / (2 * z);   // aim inside the map, so the glide never runs into the edge and stops dead
      aim.x = Math.max(hw, Math.min(W - hw, aim.x)); aim.y = Math.max(hh, Math.min(H - hh, aim.y));
      vx += (w * w * (aim.x - cx) + 2 * w * (aim.vx - vx)) * dt; vy += (w * w * (aim.y - cy) + 2 * w * (aim.vy - vy)) * dt;
      vz += (wz * wz * (aim.z - lz) - 2 * wz * vz) * dt;
      cx += vx * dt; cy += vy * dt; z = zt = clampZ(Math.exp(lz + vz * dt));
      const ox = cx, oy = cy; clampC(); if (cx !== ox) vx = 0; if (cy !== oy) vy = 0;   // at the map edge: no wind-up
    } else {
      vx = vy = vz = 0; aim = null;
      if (Math.abs(zt - z) > .001) z += (zt - z) * (1 - Math.exp(-dt * 14)); else z = zt;
    }
    if (anchor) { const [wx, wy, px, py] = anchor; cx = wx - px / (S * z) + W / (2 * z); cy = wy - py / (S * z) + H / (2 * z);
      if (z === zt) anchor = null; }
    const p = follow && pos(follow);
    if (p && !anchor) { const f = 1 - Math.exp(-dt * 4); cx += (p[0] - cx) * f; cy += (p[1] - cy) * f; }
    clampC();
    if (box) box.style.top = (cv.offsetTop + cv.offsetHeight - 38) + 'px';
  }

  return { attach, update, direct, view, toWorld, toScreen, setDirector, directorOn, score, label, pin, flash, toolbar, ahead, focus, captionEl: () => caption, ready };
})();
