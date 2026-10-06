// Highlight video ("🎞 Видео"): records one game day's highlights (viewer/highlights.js) as a short vertical clip
// (720x1280, 9:16) for social media, right in the browser: the viewer replays each moment with the camera on its
// villager (or the director camera when nobody is named), this module crops the map canvas to 9:16, draws the
// title, the highlight line and the villager's thought (translated when RU is on), and MediaRecorder saves it.
// Sound: the music and ambience of viewer/sound.js (Sound.captureStream()) are recorded too, as the sound button sets them.
// Uses the viewer globals ticks / i / frac / playing / userPaused / selected / lastPanel / header / tr / Camera.
const Clip = (() => {
  const OW = 720, OH = 1280, FPS = 30, INTRO = 2.5, MOMENT = 7, OUTRO = 2.5;
  const css = document.createElement('style');
  css.textContent = `
    #clip-box { position:fixed; inset:0; z-index:60; display:flex; align-items:center; justify-content:center;
      background:rgba(0,0,0,.55); font:14px/1.45 system-ui, sans-serif; color:#e8efe9; pointer-events:none; }
    #clip-box[hidden] { display:none; }
    #clip-box .card { pointer-events:auto; background:#252c29; border-radius:12px; padding:14px; box-shadow:0 4px 16px rgba(0,0,0,.6);
      max-width:calc(100vw - 32px); display:flex; flex-direction:column; gap:8px; align-items:center; }
    #clip-box.rec { background:none; align-items:flex-start; padding-top:12px; }
    #clip-box video { max-height:min(70vh, 640px); max-width:100%; border-radius:8px; background:#000; }
    #clip-box .row { display:flex; gap:8px; flex-wrap:wrap; justify-content:center; }
    #clip-box a, #clip-box button { background:#34403b; color:#e8efe9; border:0; padding:7px 12px; border-radius:8px;
      cursor:pointer; text-decoration:none; font-weight:600; }
    #clip-box .main { background:#f2c14e; color:#1d2321; }
    #clip-box .muted { color:#9db0a4; font-size:12px; text-align:center; }
    .hl-video { float:right; background:#34403b; color:#e8efe9; border:0; border-radius:12px; padding:2px 8px;
      font:600 11px system-ui; cursor:pointer; text-transform:none; }
  `;
  document.head.appendChild(css);
  const box = Object.assign(document.createElement('div'), { id: 'clip-box', hidden: true });
  const out = Object.assign(document.createElement('canvas'), { width: OW, height: OH });
  const o = out.getContext('2d');
  let job = null;

  function mime() {
    if (!window.MediaRecorder) return null;
    for (const m of ['video/mp4;codecs=avc1.42E01F,mp4a.40.2', 'video/mp4', 'video/webm;codecs=vp9,opus',
                     'video/webm;codecs=vp8,opus', 'video/webm'])
      if (MediaRecorder.isTypeSupported(m)) return m;
    return null;
  }
  const supported = () => !!(mime() && out.captureStream);

  // ---------- drawing ----------
  function wrap(text, maxW, maxLines) {
    const words = String(text || '').split(/\s+/).filter(Boolean), lines = [];
    let cur = '';
    for (const w of words) {
      const t = cur ? cur + ' ' + w : w;
      if (o.measureText(t).width <= maxW || !cur) cur = t; else { lines.push(cur); cur = w; }
      if (lines.length === maxLines) break;
    }
    if (cur && lines.length < maxLines) lines.push(cur);
    if (lines.length === maxLines && words.join(' ').length > lines.join(' ').length)
      lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, '') + '…';
    return lines;
  }
  function text(lines, x, y, lh, fill) {
    o.lineJoin = 'round'; o.lineWidth = 6; o.strokeStyle = 'rgba(10,12,10,.85)'; o.fillStyle = fill;
    lines.forEach((l, k) => { o.strokeText(l, x, y + k * lh); o.fillText(l, x, y + k * lh); });
    return y + lines.length * lh;
  }
  function band(y0, y1, down) {
    const gr = o.createLinearGradient(0, y0, 0, y1);
    gr.addColorStop(down ? 0 : 1, 'rgba(14,18,16,.88)'); gr.addColorStop(down ? 1 : 0, 'rgba(14,18,16,0)');
    o.fillStyle = gr; o.fillRect(0, y0, OW, y1 - y0);
  }
  // The map canvas cropped to 9:16 around (fx, fy) canvas pixels.
  function map(cv, fx, fy) {
    const cw = Math.min(cv.width, cv.height * 9 / 16), ch = cw * 16 / 9;
    const sx = Math.max(0, Math.min(cv.width - cw, fx - cw / 2)), sy = Math.max(0, Math.min(cv.height - ch, fy - ch / 2));
    o.imageSmoothingEnabled = false; o.fillStyle = '#2a3a24'; o.fillRect(0, 0, OW, OH);
    o.drawImage(cv, sx, sy, cw, ch, 0, 0, OW, OH);
  }
  function clock(t) {
    const m = (t.view.minute || 0);
    return `День ${t.view.day}, ${String(t.view.hour).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
  // A card over the dimmed map: intro and outro.
  function card(big, small, alpha) {
    o.fillStyle = `rgba(14,18,16,${.72 * alpha})`; o.fillRect(0, 0, OW, OH);
    o.globalAlpha = alpha; o.textAlign = 'center'; o.textBaseline = 'alphabetic';
    o.font = '800 64px system-ui, sans-serif';
    let y = text(big.split('\n').flatMap(l => wrap(l, OW - 80, 2)), OW / 2, OH / 2 - 40, 74, '#f2c14e');
    o.font = '600 34px system-ui, sans-serif'; text(wrap(small, OW - 100, 4), OW / 2, y + 20, 44, '#e8efe9');
    o.globalAlpha = 1;
  }
  function overlay(it, k, n, t, thought) {
    band(0, 330, true); band(OH - 420, OH, false);
    o.textAlign = 'left'; o.textBaseline = 'alphabetic';
    o.font = '600 26px system-ui, sans-serif'; text([`AI Village · ${clock(t)}`], 40, 64, 30, '#9db0a4');
    o.font = '800 50px system-ui, sans-serif'; text(wrap('⭐ ' + it.title, OW - 80, 3), 40, 128, 58, '#f2c14e');
    for (let j = 0; j < n; j++) { o.fillStyle = j === k ? '#f2c14e' : 'rgba(232,239,233,.35)'; o.fillRect(40 + j * 34, 88, 26, 6); }
    o.font = '600 34px system-ui, sans-serif';
    let y = text(wrap(it.line, OW - 80, 4), 40, OH - 330, 44, '#e8efe9');
    if (thought && !it.line.includes(thought.raw)) { o.font = 'italic 30px system-ui, sans-serif'; text(wrap(`💭 ${thought.who}: ${thought.text}`, OW - 80, 3), 40, y + 20, 38, '#cfe3d6'); }
  }

  // ---------- playback ----------
  // Latest thought or line of the moment's villager, up to the tick on screen.
  function thoughtOf(who, upto, from) {
    if (!who) return null;
    for (let k = upto; k >= from; k--) {
      const d = (ticks[k].decisions || {})[who]; if (!d) continue;
      const a = d.action || {}, args = a.args || {};
      const said = d.say || (a.name === 'say' || a.name === 'whisper') && args.text;
      if (said) return { who, raw: said, text: '«' + tr(said) + '»' };
      if (d.thought) return { who, raw: d.thought, text: tr(d.thought) };
    }
    return null;
  }
  function plan(day, items) {
    const per = ticks.length ? 60 / (ticks[0].view.tick_minutes || 60) : 1;   // ticks per game hour
    const shots = [];
    for (const it of items) {
      const k = ticks.findIndex(t => t.tick === it.tick); if (k < 0) continue;
      const a = Math.max(0, k - per), b = Math.min(ticks.length - 1, k + per);   // an hour before to an hour after
      shots.push({ it, a, b, k });
    }
    return shots.sort((p, q) => p.k - q.k);
  }

  function record(dayRec) {
    if (job) return;
    if (!supported()) return message('Этот браузер не умеет записывать видео. Откройте деревню в Chrome или Edge.');
    const items = dayRec.items || [], shots = plan(dayRec.day, items);
    if (!shots.length) return message('Моменты этого дня ещё не загружены в окно просмотра.');
    const cv = document.getElementById('c');
    let dir = false; try { dir = localStorage.getItem('aiv-director') === '1'; } catch (e) {}
    const saved = { i, frac, playing, userPaused, selected, dir };
    playing = false; userPaused = true;   // the clip drives i / frac itself; live ticks keep arriving but do not move it
    const m = mime(), stream = out.captureStream(FPS);
    const snd = window.Sound && Sound.captureStream && Sound.captureStream();
    if (snd) snd.getAudioTracks().forEach(a => stream.addTrack(a));
    const rec = new MediaRecorder(stream, { mimeType: m, videoBitsPerSecond: 5e6 }), chunks = [];
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    const total = INTRO + shots.length * MOMENT + OUTRO;
    job = { rec, chunks, shots, saved, total, t0: 0, last: -1, fx: cv.width / 2, fy: cv.height / 2, cancelled: false, day: dayRec.day, m };
    box.className = 'rec'; box.hidden = false;
    box.innerHTML = `<div class="card"><b>🎞 Записываю видео дня ${dayRec.day}…</b><span class="muted" id="clip-pr"></span>
      <span class="muted">Не сворачивайте вкладку, пока идёт запись.</span><button id="clip-stop">Отменить</button></div>`;
    box.querySelector('#clip-stop').onclick = () => { job.cancelled = true; finish(); };
    rec.onstop = () => done(job);
    rec.start(500);
    requestAnimationFrame(ts => { job.t0 = ts; frame(ts); });
  }

  function cue(s) {   // jump the viewer to a shot and frame it
    if (s.it.who && s.it.who.length) { Camera.setDirector(false); selected = s.it.who[0]; }
    else { selected = null; Camera.setDirector(true); }
    lastPanel = -1; i = s.a; frac = 1;
  }

  function frame(ts) {
    const J = job; if (!J || J !== job) return;
    const cv = document.getElementById('c'), el = (ts - J.t0) / 1000, dt = Math.min(.1, J.last < 0 ? 0 : el - J.last);
    J.last = el;
    if (el >= J.total) return finish();
    const n = J.shots.length;
    let s = null, k = -1, local = 0;
    if (el < INTRO) { s = J.shots[0]; k = 0; local = -1; }
    else if (el < INTRO + n * MOMENT) { k = Math.floor((el - INTRO) / MOMENT); s = J.shots[k]; local = el - INTRO - k * MOMENT; }
    else { s = J.shots[n - 1]; k = n - 1; local = MOMENT; }
    if (J.cur !== k) { J.cur = k; cue(s); }
    if (local >= 0) {   // play the shot: from an hour before the moment to an hour after it, over MOMENT seconds
      const p = Math.min(1, local / (MOMENT - .5)) * (s.b - s.a);
      i = s.a + Math.min(s.b - s.a, Math.floor(p)); frac = i === s.b ? 1 : p - Math.floor(p);
      if (frac === 0) frac = .001;
    }
    // Focus: the moment's villager on screen, else the camera's centre; eased so the crop does not jump.
    let fx = cv.width / 2, fy = cv.height / 2;
    const spot = selected && PixelMap.where && PixelMap.where(selected);
    if (spot) [fx, fy] = Camera.toScreen(spot[0], spot[1]);
    const f = J.fresh === k ? 1 - Math.exp(-dt * 5) : 1; J.fresh = k;
    J.fx += (fx - J.fx) * f; J.fy += (fy - J.fy) * f;
    map(cv, J.fx, J.fy);
    const t = ticks[i] || ticks[s.a];
    if (el < INTRO) {
      const pop = header && header.config.agents.length;
      card(`AI Village\nДень ${J.day}`, `Главное за день в деревне, где живут ${pop ? pop + ' ' : ''}ИИ-жителей`, Math.min(1, (INTRO - el) / .6 + .2));
    } else if (el >= INTRO + n * MOMENT) {
      card('AI Village', 'Деревня, где живут ИИ. Что будет завтра?', Math.min(1, (el - INTRO - n * MOMENT) / .5));
    } else overlay(s.it, k, n, t, thoughtOf(s.it.who && s.it.who[0], i, s.a));
    const pr = document.getElementById('clip-pr');
    if (pr) pr.textContent = `${Math.floor(el)} из ${Math.ceil(J.total)} с`;
    requestAnimationFrame(frame);
  }

  function finish() {
    const J = job; if (!J || J.stopping) return; J.stopping = true;
    const s = J.saved;
    i = s.i; frac = s.frac; selected = s.selected; lastPanel = -1; Camera.setDirector(s.dir);
    playing = s.playing; userPaused = s.userPaused;
    if (J.rec.state !== 'inactive') J.rec.stop(); else done(J);
  }
  function done(J) {
    job = null;
    if (J.cancelled) { box.hidden = true; return; }
    const type = J.m.split(';')[0], ext = type === 'video/mp4' ? 'mp4' : 'webm';
    const blob = new Blob(J.chunks, { type }), url = URL.createObjectURL(blob);
    const name = `aivillage-den-${J.day}.${ext}`, file = new File([blob], name, { type });
    window.lastClip = { blob, name, url, seconds: J.total };   // for tests and the console
    box.className = ''; box.hidden = false;
    box.innerHTML = `<div class="card"><b>🎞 Видео дня ${J.day} готово</b><video src="${url}" controls autoplay muted playsinline></video>
      <div class="row"><a class="main" href="${url}" download="${name}">⬇ Скачать</a><button id="clip-share" hidden>Поделиться</button>
      <button id="clip-close">Закрыть</button></div>
      <span class="muted">${ext === 'mp4' ? 'Файл MP4' : 'Файл WebM (в TikTok и Reels лучше загрузить из Chrome свежей версии, там MP4)'}, вертикальный 9:16, ${Math.round(J.total)} с.</span></div>`;
    const share = box.querySelector('#clip-share');
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      share.hidden = false; share.onclick = () => navigator.share({ files: [file], title: `AI Village, день ${J.day}` }).catch(() => {});
    }
    box.querySelector('#clip-close').onclick = () => { box.hidden = true; URL.revokeObjectURL(url); };
  }
  function message(s) {
    box.className = ''; box.hidden = false;
    box.innerHTML = `<div class="card"><span>${s}</span><button id="clip-close">Понятно</button></div>`;
    box.querySelector('#clip-close').onclick = () => { box.hidden = true; };
  }

  // A "🎞 Видео" button for a day header of the highlights panel. items: [{tick, title, line, who}].
  function button(dayRec) {
    const b = document.createElement('button');
    b.className = 'hl-video'; b.textContent = '🎞 Видео'; b.title = 'вертикальное видео из хайлайтов этого дня (9:16, для соцсетей)';
    b.onclick = e => { e.stopPropagation(); document.getElementById('hl-panel').hidden = true; record(dayRec); };
    return b;
  }

  if (document.body) document.body.append(box); else window.addEventListener('DOMContentLoaded', () => document.body.append(box));
  return { record, button, supported, busy: () => !!job, canvas: out };
})();
