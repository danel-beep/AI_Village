// Start screen (injected by aivillage/server.py when it runs with --setup, i.e. from the launcher).
// Before a village runs: a title menu (new village, continue a save, experiments, past villages) over the map;
// "Новая деревня" is a form drawn from GET /api/setup (aivillage/knobs.py) in two views: «Простой» (knobs.SIMPLE,
// the default) and «Расширенный» (every knob). "▶ Играть" posts the answers to /api/start and reloads into the
// live map; a loading screen covers the wait until the first hour arrives. While a village runs: a
// "🔄 Новая деревня" button that stops it (POST /api/stop) and comes back here.
// New knobs need no code here: add them to KNOBS in aivillage/knobs.py. saves.js and scenarios.js fill the
// "continue" and "experiments" pages (#su-saves-slot, #su-scen-slot) and use window.VillageLoading.
(function () {
  const STORE = 'aivillage-setup', VIEW = 'aivillage-setup-view', LOADING = 'aivillage-loading';
  const PAGES = { home: '🏡 AI Village', new: 'Новая деревня', cont: 'Продолжить деревню', lab: 'Опыты и сценарии',
    past: 'Прошлые деревни' };
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}) }).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || ('ошибка ' + r.status));
      return data;
    });
  const getJson = url => fetch(url).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const store = {  // browser storage may be blocked (private window): the screen works without it
    get(k, s) { try { return (s ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set(k, v, s) { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (e) { /* blocked */ } },
    del(k, s) { try { (s ? sessionStorage : localStorage).removeItem(k); } catch (e) { /* blocked */ } },
  };

  // --- loading screen: from "Играть" / "Продолжить" / a scenario until the first game hour is on the map ---
  const TIPS = [
    'Нажмите на жителя на карте: увидите, что он думает, что у него в карманах и с кем он дружит.',
    'Пауза останавливает и жителей: пока стоит пауза, ИИ ничего не тратит.',
    'Деревня сама сохраняется каждый игровой час. Продолжить можно с начального экрана.',
    'В режиме бога можно вмешаться: поджечь дом, устроить праздник, прислать торговца.',
    'Дойдя до бюджета в сутки, деревня встанет на паузу и сама продолжит завтра.',
    'Нажмите на дом, грядку или шахту: увидите, что там лежит и что там случилось.',
  ];
  let loadEl = null;
  function loadingCss() {
    if (document.getElementById('su-load-css')) return;
    const css = document.createElement('style');
    css.id = 'su-load-css';
    css.textContent = `
      #su-load { position:fixed; inset:0; z-index:60; background:radial-gradient(circle at 50% 40%, #26302c, #141917 70%);
        color:#e8efe9; font:15px system-ui, sans-serif; display:flex; align-items:center; justify-content:center;
        padding:16px; text-align:center; transition:opacity .4s; }
      #su-load.gone { opacity:0; pointer-events:none; }
      #su-load .box { max-width:460px; }
      #su-load canvas { image-rendering:pixelated; background:none; width:240px; height:78px; display:block; margin:0 auto 18px; }
      #su-load h2 { font-size:24px; margin:0 0 8px; color:#f2c14e; }
      #su-load .sub { color:#c9d6ce; line-height:1.45; min-height:22px; }
      #su-load .bar { height:6px; background:#2f3935; border-radius:3px; overflow:hidden; margin:20px auto 14px; width:240px; }
      #su-load .bar i { display:block; height:100%; width:40%; background:#76b041; border-radius:3px;
        animation:su-slide 1.4s ease-in-out infinite; }
      @keyframes su-slide { 0% { transform:translateX(-100%); } 100% { transform:translateX(250%); } }
      #su-load .tip { font-size:13px; color:#9db0a4; line-height:1.45; min-height:38px; }
      #su-load button { margin-top:16px; background:#34403b; color:#e8efe9; border:0; border-radius:10px;
        padding:9px 16px; font:600 14px system-ui; cursor:pointer; }
      #su-load .bad { color:#ff8a72; }`;
    document.head.appendChild(css);
  }
  // A few villagers walking in place (viewer/sprites.js), drawn when the sprites are ready.
  function walkers(canvas, n) {
    const S = window.Sprites;
    if (!S || !canvas) return;
    const looks = Array.from({ length: n }, () => Math.floor(Math.random() * (S.LOOKS || 24)));
    let f = 0;
    const sheets = [];
    const draw = () => {
      if (!canvas.isConnected) return;
      const g = canvas.getContext('2d');
      g.clearRect(0, 0, canvas.width, canvas.height);
      looks.forEach((k, j) => {
        const sheet = sheets[j] || (sheets[j] = S.villager(k));
        if (!sheet) return;
        const x = Math.round((j + 0.5) * canvas.width / n - sheet.fw / 2), col = (f + j) % 4 === 3 ? 1 : [0, 1, 0, 2][(f + j) % 4];
        g.drawImage(sheet, col * sheet.fw, 0, sheet.fw, sheet.fh, x, canvas.height - sheet.fh, sheet.fw, sheet.fh);
      });
      f++;
      setTimeout(draw, 380);
    };
    S.ok ? draw() : S.onReady && S.onReady(draw);
  }
  function showLoading(title, sub) {
    loadingCss();
    if (!loadEl) {
      loadEl = document.createElement('div');
      loadEl.id = 'su-load';
      loadEl.innerHTML = '<div class="box"><canvas width="96" height="31"></canvas><h2></h2><div class="sub"></div>' +
        '<div class="bar"><i></i></div><div class="tip"></div><button hidden>Показать карту</button></div>';
      document.body.appendChild(loadEl);
      walkers(loadEl.querySelector('canvas'), 5);
      let t = Math.floor(Math.random() * TIPS.length);
      const tip = () => { if (loadEl) { loadEl.querySelector('.tip').textContent = '💡 ' + TIPS[t++ % TIPS.length]; } };
      tip();
      loadEl._tips = setInterval(tip, 6000);
      loadEl.querySelector('button').onclick = hideLoading;
    }
    loadEl.classList.remove('gone');
    loadEl.querySelector('h2').textContent = title;
    const s = loadEl.querySelector('.sub');
    s.textContent = sub || ''; s.className = 'sub';
  }
  function hideLoading() {
    store.del(LOADING, true);
    if (!loadEl) return;
    const el = loadEl;
    loadEl = null;
    clearInterval(el._tips);
    el.classList.add('gone');
    setTimeout(() => el.remove(), 450);
  }
  function loadingFailed(text) {
    if (!loadEl) return;
    const s = loadEl.querySelector('.sub');
    s.textContent = text; s.className = 'sub bad';
    loadEl.querySelector('.bar').hidden = true;
    loadEl.querySelector('button').hidden = false;
  }
  // Before a reload into the village: the loading screen stays up across it (sessionStorage flag).
  function goLoading(title, sub) {
    showLoading(title, sub);
    store.set(LOADING, '1', true);
    if (/^#(home|new|cont|lab|past)$/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);
  }
  window.VillageLoading = { start: goLoading, fail: e => { hideLoading(); return e; } };

  // In a running village: keep the loading screen until the first game hour is on the map (viewer `ticks`) and the
  // camera has framed it (viewer/camera.js), so the map never shows first and then jumps; at most 5 s for the camera.
  let firstTick = 0;
  function waitForMap() {
    const has = () => {
      if (typeof ticks === 'undefined' || !ticks.length) return false;  // eslint-disable-line no-undef
      firstTick = firstTick || Date.now();
      return typeof Camera === 'undefined' || !Camera.ready || Camera.ready() || Date.now() - firstTick > 5000;  // eslint-disable-line no-undef
    };
    const flagged = store.get(LOADING, true);
    if (has()) return hideLoading();
    const show = () => showLoading('Деревня просыпается', 'Жители осматриваются и думают над первым шагом. ' +
      'С ИИ-жителями это занимает до минуты.');
    if (flagged) show();
    const t0 = Date.now();
    const iv = setInterval(() => {
      if (has()) { clearInterval(iv); hideLoading(); return; }
      if (!flagged && !loadEl && Date.now() - t0 > 1500) show();
      if (loadEl && Date.now() - t0 > 90000) loadEl.querySelector('button').hidden = false;
    }, 300);
    window.addEventListener('village-live', e => {
      const r = e.detail || {};
      if (r.type === 'error' && loadEl) { clearInterval(iv); loadingFailed('Деревня не запустилась: ' + (r.text || 'ошибка')); }
      if (r.type === 'budget_pause' && loadEl) { clearInterval(iv); loadingFailed(r.text || 'Бюджет на сегодня потрачен.'); }
    });
  }

  Promise.all([getJson('/api/setup'), getJson('/api/saves'), getJson('/api/scenarios')]).then(([info, sv, sc]) => {
    if (info.running) {
      if (/^#(home|new|cont|lab|past)$/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);
      restartButton(info);
      waitForMap();
    } else screen(info, sv.can_load ? (sv.saves || []) : [], sc.can_start ? (sc.scenarios || []) : []);
  });

  function restartButton(info) {
    if (!info.can_restart) return;
    const b = document.createElement('button');
    b.textContent = '🔄 Новая деревня';
    b.title = 'остановить эту деревню и настроить новую';
    b.style.cssText = 'background:#34403b;color:#e8efe9;border:0;border-radius:20px;padding:7px 12px;' +
      'font:600 13px system-ui,sans-serif;cursor:pointer';
    b.onclick = () => {
      if (!info.finished && !confirm('Остановить эту деревню и настроить новую? Она сохранится (продолжить можно с начального экрана), сводка сессии тоже.')) return;
      post('/api/stop').then(() => location.reload(), e => alert(e.message));
    };
    const bar = document.getElementById('rp-bar');
    if (bar) bar.appendChild(b);
    else { b.style.cssText += ';position:fixed;left:8px;bottom:12px;z-index:30'; document.body.appendChild(b); }
  }

  function screen(info, saves, scens) {
    const css = document.createElement('style');
    css.textContent = `
      #su { position:fixed; inset:0; z-index:31; overflow:auto; background:#1a201e; color:#e8efe9;
        font:14px system-ui, sans-serif; }
      #su .wrap { max-width:760px; margin:0 auto; padding:20px 16px 60px; box-sizing:border-box; }
      #su header { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
      #su h1 { font-size:24px; margin:0; flex:1; min-width:180px; }
      #su header #st-toggle { position:static; }
      #su .back { background:none; border:0; color:#9db0a4; font:600 14px system-ui; cursor:pointer; padding:6px 4px; }
      #su .back:hover { color:#e8efe9; }
      #su .keyline.bad { color:#ffb36b; }
      #su #su-model .small { padding:5px 10px; }
      /* title menu */
      #su .hero { text-align:center; padding:26px 0 18px; }
      #su .hero canvas { image-rendering:pixelated; background:none; cursor:default; width:min(100%, 420px); height:auto; display:block; margin:0 auto 14px; }
      #su .hero .name { font:800 40px system-ui; color:#f2c14e; letter-spacing:.5px; margin:0; }
      #su .hero .tag { color:#c9d6ce; max-width:520px; margin:8px auto 0; line-height:1.45; }
      #su .menu { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:18px; }
      #su .card { text-align:left; background:#232b28; color:#e8efe9; border:1px solid #2f3935; border-radius:14px;
        padding:16px 18px; cursor:pointer; font:14px system-ui; }
      #su .card:hover { border-color:#76b041; }
      #su .card b { display:block; font-size:17px; margin-bottom:4px; }
      #su .card span { color:#9db0a4; font-size:13px; line-height:1.4; }
      #su .card.main { grid-column:1 / -1; background:#76b041; color:#1d2321; border-color:#76b041; padding:20px 22px; }
      #su .card.main b { font-size:22px; }
      #su .card.main span { color:#24331c; }
      @media (max-width:560px) { #su .menu { grid-template-columns:1fr; } #su .hero .name { font-size:32px; } }
      /* simple / advanced */
      #su .view { display:flex; background:#232b28; border-radius:12px; padding:4px; gap:4px; margin-bottom:6px; }
      #su .view button { flex:1; background:none; color:#c9d6ce; border:0; border-radius:9px; padding:10px 8px;
        font:700 14px system-ui; cursor:pointer; }
      #su .view button.on { background:#76b041; color:#1d2321; }
      #su .view-hint { margin:0 2px 12px; }
      #su .note { background:#2b2a1f; border:1px solid #5b5426; border-radius:10px; padding:10px 12px; margin:-2px 0 12px;
        font-size:13px; color:#e9dfb5; line-height:1.45; }
      #su .note button { margin-left:6px; }
      #su h3.more { font-size:15px; margin:22px 0 2px; color:#e8efe9; }
      #su .more-hint { margin:0 0 10px; }
      #su summary .about { display:block; font-size:12px; font-weight:400; color:#9db0a4; margin-top:2px; }
      #su summary .cnt { font-size:11px; font-weight:700; color:#1d2321; background:#76b041; border-radius:9px;
        padding:1px 7px; margin-left:6px; vertical-align:2px; }
      #su section, #su details { background:#232b28; border-radius:12px; padding:12px 16px; margin-bottom:12px; }
      #su h2, #su summary { font-size:15px; margin:0 0 6px; color:#f2c14e; cursor:default; }
      #su summary { cursor:pointer; margin:0; }
      #su details[open] summary { margin-bottom:6px; }
      #su #pg-cont #su-saves > h2, #su #pg-lab #su-scen > h2 { display:none; }
      #su .k { padding:9px 0; border-top:1px solid #2f3935; }
      #su .k:first-of-type { border-top:0; }
      #su .lab { display:flex; justify-content:space-between; gap:10px; align-items:baseline; }
      #su .lab b { font-weight:600; }
      #su .val { color:#f2c14e; font-weight:700; white-space:nowrap; }
      #su .val.changed::after { content:' ●'; color:#76b041; font-size:10px; }
      #su input[type=range] { width:100%; accent-color:#76b041; margin:6px 0 0; }
      #su input[type=number] { width:160px; background:#1d2321; color:#e8efe9; border:1px solid #4a5650;
        border-radius:6px; padding:6px 8px; font:14px system-ui; margin-top:6px; }
      #su .opts { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
      #su .opts button { background:#2f3935; color:#e8efe9; border:1px solid #3e4a45; border-radius:18px;
        padding:6px 12px; font:13px system-ui; cursor:pointer; }
      #su .opts button.on { background:#76b041; color:#1d2321; border-color:#76b041; font-weight:700; }
      #su .tog { position:relative; width:42px; height:24px; flex:none; }
      #su .tog input { opacity:0; width:0; height:0; }
      #su .tog span { position:absolute; inset:0; background:#3d4a44; border-radius:12px; cursor:pointer; transition:.15s; }
      #su .tog span::before { content:''; position:absolute; width:18px; height:18px; left:3px; top:3px;
        background:#e8efe9; border-radius:50%; transition:.15s; }
      #su .tog input:checked + span { background:#76b041; }
      #su .tog input:checked + span::before { transform:translateX(18px); }
      #su .hint { font-size:12px; color:#9db0a4; margin-top:4px; line-height:1.4; }
      #su .play { position:sticky; bottom:0; background:linear-gradient(transparent, #1a201e 30%);
        padding:16px 0 4px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
      #su .go { background:#76b041; color:#1d2321; border:0; border-radius:12px; padding:14px 28px;
        font:800 18px system-ui; cursor:pointer; }
      #su .go:disabled { opacity:.6; cursor:wait; }
      #su .small { background:#2f3935; color:#e8efe9; border:0; border-radius:8px; padding:8px 12px;
        font:13px system-ui; cursor:pointer; }
      #su .msg { font-size:13px; flex-basis:100%; min-height:18px; }
      #su .bad { color:#ff8a72; }
      #su .runs a { color:#e8efe9; display:inline-block; margin:3px 10px 3px 0; }
      #su .vr { display:grid; grid-template-columns:48px 1fr 1fr 1.3fr; gap:6px; padding:8px 0; border-top:1px solid #2f3935; }
      #su .vr input, #su .vr select { width:100%; box-sizing:border-box; background:#1d2321; color:#e8efe9;
        border:1px solid #4a5650; border-radius:6px; padding:6px 8px; font:13px system-ui; }
      #su .vr .own { grid-column:2 / -1; min-height:54px; resize:vertical; font:inherit; font-size:12px; background:#1d2321;
        color:#e8efe9; border:1px solid #3a4540; border-radius:6px; padding:5px 7px; box-sizing:border-box; width:100%; }
      #su .vr select.ch { grid-column:2 / -1; }
      #su .vr select.look { grid-column:2 / 4; }
      #su .vr .face { grid-row:1 / span 4; width:40px; height:52px; image-rendering:pixelated; align-self:start;
        background:#2c3632; border-radius:8px; padding:2px; }
      @media (max-width:560px) { #su .vr { grid-template-columns:44px 1fr 1fr; } #su .vr select.mdl { grid-column:2 / -1; } }
      #su .vbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:6px 0; }
      #su textarea { width:100%; box-sizing:border-box; background:#1d2321; color:#e8efe9; border:1px solid #4a5650;
        border-radius:6px; padding:6px 8px; font:13px system-ui; min-height:54px; margin-top:6px; }
    `;
    document.head.appendChild(css);
    const drop = document.getElementById('drop');
    if (drop) drop.style.display = 'none';
    const panel = document.getElementById('st');  // the keys panel opens above the start screen
    if (panel) panel.style.zIndex = 40;

    const pad = n => String(n).padStart(2, '0');
    const latest = saves[0];
    const savedAt = s => { const m = /^\d{4}-(\d\d)-(\d\d)_(\d\d)-(\d\d)/.exec(s.name); return m ? `${m[2]}.${m[1]} ${m[3]}:${m[4]}` : ''; };
    const root = document.createElement('div');
    root.id = 'su';
    root.innerHTML = `<div class="wrap">
      <header><button class="back" id="su-back" hidden>← Меню</button><h1 id="su-title"></h1></header>
      <div class="page" id="pg-home">
        <div class="hero"><canvas id="su-folk" width="140" height="31"></canvas>
          <p class="name">AI Village</p>
          <div class="tag">Деревня, где каждый житель думает своим ИИ. Они сами строят, торгуют, дружат и ссорятся,
            а вы смотрите и, если хочется, вмешиваетесь.</div></div>
        <div class="menu">
          <button class="card main" data-go="new"><b>▶ Новая деревня</b><span>Пара простых вопросов, и жители просыпаются</span></button>
          <button class="card" data-go="cont" id="m-cont"><b>💾 Продолжить</b><span id="m-cont-txt"></span></button>
          <button class="card" data-go="lab" id="m-lab"><b>🧪 Опыты и сценарии</b><span>Готовые ситуации и сравнение моделей ИИ</span></button>
          <button class="card" data-go="past"><b>📂 Прошлые деревни</b><span>Повторы, сводки и отчёт о проблеме</span></button>
        </div>
      </div>
      <div class="page" id="pg-new" hidden>
        <div class="view"><button data-v="simple">🙂 Простой</button><button data-v="adv">🛠 Расширенный</button></div>
        <div class="hint view-hint" id="su-view-hint"></div>
        <section id="su-main">
          <div class="k" id="su-model"><div class="lab"><b>Модель ИИ</b><button class="small" id="su-model-btn"></button></div>
            <div class="hint keyline" id="su-model-txt"></div></div>
        </section>
        <div class="note" id="su-note-adv" hidden></div>
        <div id="su-adv">
          <h3 class="more">Все остальные настройки</h3>
          <p class="hint more-hint">Пресет уже выставил разумные значения, трогать их не обязательно. Изменённые помечены
            зелёной точкой ●, «Сбросить к пресету» внизу вернёт всё как было.</p>
          <div id="su-groups"></div>
          <details id="su-people"><summary>👥 Настроить каждого жителя: имя, модель, характер</summary>
            <div class="vbar"><label class="tog"><input type="checkbox" id="su-own"><span></span></label>
              <span>Настроить каждого жителя вручную</span></div>
            <div class="hint">Выключено: имена и модели подберутся сами, характер по выбору «Характер жителей».
              Включено: у каждого жителя свой характер, текст которого он получает в подсказке. Выберите готовый
              (злые, добрые, мягкие черты) и при желании поправьте текст или впишите свой.</div>
            <div id="su-vbox" hidden>
              <div class="vbar"><button class="small" id="su-rand">🎲 Случайные жители</button>
                <button class="small" id="su-neutral">😐 Всем обычный</button></div>
              <div id="su-vlist"></div>
            </div>
          </details>
        </div>
        <div class="play">
          <button class="go" id="su-go">▶ Играть</button>
          <button class="small" id="su-reset">Сбросить к пресету</button>
          <div class="msg" id="su-msg"></div>
        </div>
      </div>
      <div class="page" id="pg-cont" hidden><div id="su-saves-slot"></div></div>
      <div class="page" id="pg-lab" hidden><div id="su-scen-slot"></div></div>
      <div class="page" id="pg-past" hidden><section>
        <div class="runs" id="su-runs">загружаю…</div>
        <div class="hint" style="margin-top:14px">Что-то пошло не так в последнем прогоне? Опишите, и я соберу файл-отчёт:
          его можно перетащить в чат проекта.</div>
        <textarea id="su-note" placeholder="Например: на второй день все жители стояли на месте"></textarea>
        <button class="small" id="su-report" style="margin-top:6px">🐞 Собрать отчёт</button>
        <div class="msg" id="su-rmsg"></div>
      </section></div>
    </div>`;
    document.body.appendChild(root);
    const $ = id => document.getElementById(id);
    const st = $('st-toggle');  // settings.js button: keys and model, moved into the header
    if (st) { st.className = ''; st.style.cssText = 'background:#34403b;color:#e8efe9;border:0;border-radius:20px;' +
      'padding:8px 14px;font:600 13px system-ui,sans-serif;cursor:pointer'; root.querySelector('header').appendChild(st); }

    // --- pages: the title menu and what it opens (browser "back" works: #new, #cont, ...) ---
    $('m-cont').hidden = !latest;
    if (latest) $('m-cont-txt').textContent = `Деревня от ${savedAt(latest)}: ${latest.finished ? 'закончилась' : 'остановлена'} ` +
      `на дне ${latest.day}, ${pad(latest.hour)}:${pad(latest.minute || 0)}` + (saves.length > 1 ? ` · всего сохранений: ${saves.length}` : '');
    $('m-lab').hidden = !scens.length;
    function page(p, push) {
      if (!PAGES[p] || (p === 'cont' && !latest) || (p === 'lab' && !scens.length)) p = 'home';
      for (const k of Object.keys(PAGES)) { const el = $('pg-' + k); if (el) el.hidden = k !== p; }
      $('su-title').textContent = p === 'home' ? '' : PAGES[p];
      $('su-back').hidden = p === 'home';
      root.scrollTop = 0;
      if (push) history.pushState({ su: p }, '', p === 'home' ? location.pathname + location.search : '#' + p);
    }
    root.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => page(b.dataset.go, true); });
    $('su-back').onclick = () => page('home', true);
    window.addEventListener('popstate', () => page((location.hash || '#home').slice(1)));
    page((location.hash || '#home').slice(1));
    walkers($('su-folk'), 7);

    // --- the "new village" form ---
    const knobs = info.knobs, byKey = Object.fromEntries(knobs.map(k => [k.key, k]));
    let saved = {};
    try { saved = JSON.parse(store.get(STORE) || '{}') || {}; } catch (e) { /* broken storage */ }
    const start = Object.assign({}, info.defaults, info.last || {}, saved);
    if (!(start.preset in info.preset_defaults)) start.preset = info.defaults.preset;
    const presetDefaults = p => info.preset_defaults[p] || {};
    // config and action knobs (and «Еды в мире», which a preset may set) move with the preset
    const follows = k => !!(k.path || k.action || (info.follow || []).includes(k.key));
    // `only` (knobs.py): the knob belongs to one kind of village ("llm", "bots", "mcp") or a list of them
    const notHere = k => !!k.only && ![].concat(k.only).includes(values.brains);
    // Config knobs follow the preset until the user moves them; `touched` keeps what they set by hand.
    let touched = new Set(Object.keys(saved.__touched || {}));
    const values = {};
    // A choice with `sets` («Сколько случайностей») moves its sliders like the preset does: preset < sets < hand.
    const setsVals = () => Object.assign({}, ...knobs.filter(k => k.sets).map(k => k.sets[values[k.key]] || {}));
    const base = p => Object.assign({}, presetDefaults(p), setsVals());
    for (const k of knobs) if (!follows(k)) values[k.key] = k.key in start ? start[k.key] : k.default;
    for (const k of knobs) if (follows(k))
      values[k.key] = touched.has(k.key) && k.key in start ? start[k.key] : base(start.preset)[k.key];
    for (const k of knobs)  // a remembered answer that is no longer an option (an old mode, old food choice)
      if (k.type === 'choice' && !k.options.some(o => o[0] === values[k.key]))
        values[k.key] = follows(k) ? base(start.preset)[k.key] : k.default;
    // «Простой» (default): only knobs.SIMPLE; «Расширенный»: every knob.
    let view = store.get(VIEW) === 'adv' ? 'adv' : 'simple';

    const fmt = (k, v) => k.type === 'toggle' ? (v ? 'да' : 'нет')
      : k.type === 'choice' ? '' : (v === null || v === undefined || v === '' ? 'случайно' : v + (k.unit || ''));
    const rows = {};

    function row(k) {
      const el = document.createElement('div');
      el.className = 'k';
      const lab = document.createElement('div');
      lab.className = 'lab';
      lab.innerHTML = '<b></b><span class="val"></span>';
      lab.querySelector('b').textContent = k.label;
      el.appendChild(lab);
      const val = lab.querySelector('.val');
      let control;
      if (k.type === 'range') {
        control = document.createElement('input');
        Object.assign(control, { type: 'range', min: k.min, max: k.max, step: k.step || 1 });
        control.oninput = () => set(k, Number(control.value));
        el.appendChild(control);
      } else if (k.type === 'number') {
        control = document.createElement('input');
        Object.assign(control, { type: 'number', min: 1, placeholder: 'случайно' });
        control.oninput = () => set(k, control.value === '' ? null : Number(control.value));
        el.appendChild(control);
      } else if (k.type === 'toggle') {
        const t = document.createElement('label');
        t.className = 'tog';
        t.innerHTML = '<input type="checkbox"><span></span>';
        control = t.querySelector('input');
        control.onchange = () => set(k, control.checked);
        val.replaceWith(t);
      } else {
        control = document.createElement('div');
        control.className = 'opts';
        for (const [v, text] of k.options) {
          const b = document.createElement('button');
          b.textContent = text; b.dataset.v = v;
          b.onclick = () => set(k, v);
          control.appendChild(b);
        }
        el.appendChild(control);
      }
      const about = document.createElement('div');
      about.className = 'hint';
      el.appendChild(about);
      rows[k.key] = { el, control, val, about };
      return el;
    }

    function paint(k) {
      const r = rows[k.key], v = values[k.key];
      if (k.type === 'range') r.control.value = v;
      else if (k.type === 'number') r.control.value = v === null || v === undefined ? '' : v;
      else if (k.type === 'toggle') r.control.checked = !!v;
      else for (const b of r.control.children) b.classList.toggle('on', b.dataset.v === String(v));
      if (r.val.isConnected) {
        r.val.textContent = fmt(k, v);
        r.val.classList.toggle('changed', view === 'adv' && follows(k) && v !== base(values.preset)[k.key]);
      }
      // In «Простой» a choice explains its picked option only (its general hint talks about sliders not shown there).
      const hint = view === 'simple' && k.about ? '' : (k.hint || '');
      r.about.textContent = [k.about ? k.about[v] : '', hint].filter(Boolean).join(' ');
      // hide_if: hidden while every listed knob holds one of the listed values (knobs.py)
      const hidden = k.hide_if && Object.entries(k.hide_if).every(([c, vs]) => vs.includes(values[c]));
      const off = notHere(k) || hidden;
      r.el.style.display = off || (view === 'simple' && !k.simple) ? 'none' : '';
    }

    function set(k, v) {
      values[k.key] = v;
      if (follows(k)) touched.add(k.key);
      if (k.sets) for (const c of Object.keys(k.sets[v] || {})) touched.delete(c);  // the choice takes them back
      if (k.key === 'preset' || k.sets) {  // the preset / choice moves every slider the user has not set by hand
        for (const c of knobs) if (follows(c) && !touched.has(c.key)) values[c.key] = base(values.preset)[c.key];
      }
      repaint();
      if (k.key === 'models') fillModels(true);
      if (k.key === 'villagers' || k.key === 'brains' || k.key === 'models') syncRoster();
      remember();
    }

    function remember() {
      store.set(STORE, JSON.stringify(Object.assign({}, values,
        { seed: null, roster: roster, __touched: Object.fromEntries([...touched].map(t => [t, 1])) })));
    }

    // "Главное" on top (knobs.MAIN), every other knob in a folded section (knobs.SECTIONS); the server orders them.
    const model = $('su-model');
    for (const k of knobs.filter(k => k.section === 'main')) $('su-main').insertBefore(row(k), model);
    const boxes = {}, spot = {};
    for (const sec of info.sections || []) {
      const box = document.createElement('details');
      const h = document.createElement('summary');
      h.textContent = sec.title;
      const cnt = document.createElement('span');
      cnt.className = 'cnt';
      h.appendChild(cnt);
      if (sec.about) { const a = document.createElement('span'); a.className = 'about'; a.textContent = sec.about; h.appendChild(a); }
      box.appendChild(h);
      for (const k of knobs.filter(k => k.section === sec.title)) {
        box.appendChild(row(k));
        if (k.simple) { spot[k.key] = document.createComment(k.key); box.appendChild(spot[k.key]); }
      }
      $('su-groups').appendChild(box);
      boxes[sec.title] = { box, cnt, knobs: knobs.filter(k => k.section === sec.title) };
    }
    // Per section: hide it when none of its knobs applies here, count the knobs set away from the preset.
    function sections() {
      for (const b of Object.values(boxes)) {
        const shown = b.knobs.filter(k => rows[k.key].el.style.display !== 'none' && b.box.contains(rows[k.key].el));
        const changed = shown.filter(k => follows(k) && values[k.key] !== base(values.preset)[k.key]).length;
        b.box.style.display = shown.length ? '' : 'none';
        b.cnt.textContent = changed ? 'изменено: ' + changed : '';
        b.cnt.hidden = !changed;
      }
    }

    // What «Простой» does not show but will still apply: changes made in «Расширенный».
    const isDefault = k => follows(k) ? !touched.has(k.key) || values[k.key] === base(values.preset)[k.key]
      : k.key === 'seed' ? values.seed === null || values.seed === undefined || values.seed === ''
      : values[k.key] === info.defaults[k.key];
    function hiddenChanges() {  // how many knobs «Простой» does not show are set away from the preset
      const off = knobs.filter(k => !k.simple && !notHere(k) && !isDefault(k));
      return off.length;  // the per-villager editor is on screen in both views
    }
    function note() {
      const n = view === 'simple' ? hiddenChanges() : 0, el = $('su-note-adv');
      el.hidden = !n;
      if (el.hidden) return;
      el.textContent = `В «Расширенном» выбрано изменённых настроек: ${n}. Это тоже сработает.`;
      const b = document.createElement('button');
      b.className = 'small'; b.textContent = 'Вернуть как задумано';
      b.onclick = resetAll;
      el.appendChild(b);
    }
    function resetAll() {
      touched = new Set();
      for (const k of knobs) if (!follows(k) && !k.simple && k.key in info.defaults) values[k.key] = info.defaults[k.key];
      set(byKey.preset, values.preset);
    }

    function setView(v) {
      view = v;
      store.set(VIEW, v);
      root.querySelectorAll('.view button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
      $('su-view-hint').textContent = v === 'simple'
        ? 'Только главное. Остальное выставлено как задумано: так деревня работает лучше всего.'
        : 'Здесь можно поменять всё: еду, налоги, кражи, беды, скорость, каждого жителя.';
      for (const [key, ph] of Object.entries(spot)) {  // simple knobs from the sections join «Главное» in «Простой»
        if (v === 'simple') $('su-main').insertBefore(rows[key].el, model);
        else ph.parentNode.insertBefore(rows[key].el, ph);
      }
      $('su-adv').hidden = v === 'simple';
      $('su-reset').hidden = v === 'simple';
      repaint();
    }
    root.querySelectorAll('.view button').forEach(b => { b.onclick = () => setView(b.dataset.v); });

    function repaint() {
      knobs.forEach(paint);
      sections();
      keyLine();
      note();
    }

    let hasKey = info.has_key;
    // The model row in "Главное": which AI the villagers think with; the button opens the keys panel (settings.js).
    $('su-model-btn').onclick = () => { if (st) st.click(); };
    function keyLine() {
      const el = $('su-model-txt');
      model.style.display = values.brains === 'llm' ? '' : 'none';
      $('su-model-btn').textContent = hasKey ? '⚙️ Поменять' : '🔑 Вставить ключ';
      const mix = values.models === 'luna_haiku';
      const bad = !hasKey || (mix && !info.has_openrouter);
      el.className = 'hint keyline' + (bad ? ' bad' : '');
      el.textContent = !hasKey ? 'Для ИИ-жителей нужен ключ OpenAI или OpenRouter: нажмите кнопку справа и вставьте его.'
        : !mix ? `Жители думают через ${info.model}. Модель и ключ меняются кнопкой справа.`
        : info.has_openrouter ? 'Половина жителей на openai/gpt-6-luna, половина на anthropic/claude-haiku-5.5. Ключи меняются кнопкой справа.'
        : 'Для Haiku нужен ключ OpenRouter: нажмите кнопку справа и вставьте его.';
    }
    // The settings panel saves keys on its own; notice a new key without a reload.
    setInterval(() => fetch('/api/setup').then(r => r.json()).then(i => {
      if (i.running) return location.reload();  // started from another tab
      if (i.has_key !== hasKey || i.model !== info.model || i.has_openrouter !== info.has_openrouter) {
        hasKey = i.has_key; info.model = i.model; info.has_openrouter = i.has_openrouter; keyLine();
      }
    }).catch(() => {}), 3000);

    // --- villagers one by one (knobs.roster / clean_roster on the server) ---
    const PROF = { farmer: 'Фермер', fisher: 'Рыбак', woodcutter: 'Лесоруб', miner: 'Шахтёр', smith: 'Кузнец' };
    let roster = Array.isArray(start.roster) && start.roster.length ? start.roster : null;
    const n = () => values.villagers;
    const fetchRoster = (existing, seed) => post('/api/roster', { n: n(), existing, seed });

    // Models in the editor: «Модели жителей» fills them (an equal share, seats drawn at random), the user may change
    // any one. undefined = not filled yet; '' = the model from «⚙️ Настройки».
    function fillModels(all) {
      if (!roster) return;
      const rows = roster.slice(0, n()), mix = (info.model_mixes || {})[values.models] || [''];
      const count = Object.fromEntries(mix.map(m => [m, 0]));
      if (!all) rows.forEach(v => { if (v.model in count) count[v.model]++; });
      const todo = rows.filter(v => all || v.model === undefined).sort(() => Math.random() - .5);
      for (const v of todo) {
        const m = mix.slice().sort(() => Math.random() - .5).reduce((a, b) => (count[b] < count[a] ? b : a));
        v.model = m; count[m]++;
      }
    }
    const faces = [];
    function drawFaces() {  // the skin each villager will have in the game (Sprites.pickLooks, as the map picks)
      const S = window.Sprites;
      if (!roster || !S || !S.ok) return;
      const looks = S.pickLooks(roster.slice(0, n()));
      faces.forEach(({ v, face }) => {
        const [look, variant] = looks[v.name] || [0, 0], sheet = S.villager(look, variant);
        const g = face.getContext('2d'); g.clearRect(0, 0, face.width, face.height);
        if (sheet) g.drawImage(sheet, 0, 0, sheet.fw, sheet.fh, (face.width - sheet.fw) / 2, face.height - sheet.fh, sheet.fw, sheet.fh);
      });
    }

    function drawRoster() {
      const list = $('su-vlist');
      list.textContent = '';
      faces.length = 0;
      fillModels(false);
      $('su-own').checked = !!roster;
      $('su-vbox').hidden = !roster;
      if (!roster) return;
      roster.slice(0, n()).forEach((v, idx) => {
        const r = document.createElement('div');
        r.className = 'vr';
        const name = document.createElement('input');
        name.value = v.name; name.maxLength = 20; name.placeholder = 'Имя';
        name.oninput = () => { v.name = name.value; drawFaces(); remember(); };
        const prof = document.createElement('select');
        for (const p of info.professions) prof.add(new Option(PROF[p] || p, p, false, p === v.profession));
        prof.onchange = () => { v.profession = prof.value; drawFaces(); remember(); };
        // Model: "" = as «Модели жителей» says; otherwise this villager's own (remote.models_for).
        const mdl = document.createElement('select');
        mdl.className = 'mdl'; mdl.title = 'Модель ИИ этого жителя';
        for (const [m, label] of info.villager_models || []) mdl.add(new Option('🧠 ' + label + (m ? '' : ` (${info.model})`), m));
        mdl.value = v.model || '';
        mdl.style.display = values.brains === 'llm' ? '' : 'none';
        mdl.onchange = () => { v.model = mdl.value; remember(); };
        // Character: a preset (its exact text goes into the box) or own text; the box is what the villager gets.
        const ch = document.createElement('select');
        ch.className = 'ch';
        ch.add(new Option('😐 Обычный (без характера)', 'default'));
        for (const [g, title] of [['evil', 'Злые'], ['good', 'Добрые'], ['mild', 'Мягкие черты']]) {
          const og = document.createElement('optgroup');
          og.label = title;
          for (const [key, c] of Object.entries(info.characters)) if (c.group === g) og.appendChild(new Option(c.label, key));
          ch.appendChild(og);
        }
        ch.add(new Option('✍️ Свой текст', '__own'));
        const own = document.createElement('textarea');
        own.className = 'own'; own.maxLength = 600; own.rows = 2;
        own.placeholder = 'Пусто: обычный житель, без характера. Можно вписать свой, например: You love music and hate being alone.';
        const preset = () => info.characters[v.character];
        const show = () => {
          ch.value = v.character === 'default' || preset() ? v.character : '__own';
          own.value = preset() ? preset().text : (v.character === 'default' ? '' : v.character);
        };
        own.oninput = () => {  // the text is the truth: a preset's exact text stays that preset, anything else is own
          const t = own.value.trim();
          const hit = Object.entries(info.characters).find(([, c]) => c.text === t);
          v.character = !t ? 'default' : hit ? hit[0] : t;
          ch.value = v.character === 'default' || preset() ? v.character : '__own';
          remember();
        };
        ch.onchange = () => {
          if (ch.value === '__own') { if (preset()) v.character = own.value.trim() || 'default'; own.focus(); }
          else v.character = ch.value;
          show(); remember();
        };
        show();
        // Look (viewer/sprites.js): automatic = by the name's sex and the profession; or any of the drawn villagers.
        const look = document.createElement('select');
        look.className = 'look'; look.title = 'Внешность';
        look.add(new Option('🎲 Внешность: сама подберётся', ''));
        const S = window.Sprites, nl = (S && S.LOOKS) || 0;
        for (let k = 0; k < nl; k++) look.add(new Option(`${S.lookIsFemale(k) ? '👩' : '👨'} Внешность ${k + 1}`, String(k)));
        look.value = Number.isInteger(v.look) ? String(v.look) : '';
        const face = document.createElement('canvas');
        face.className = 'face'; face.width = 20; face.height = 26; face.title = 'Так он будет выглядеть в игре';
        faces.push({ v, face });
        look.onchange = () => { if (look.value === '') delete v.look; else v.look = +look.value; drawFaces(); remember(); };
        r.append(face, name, prof, mdl, ch, look, own);
        list.appendChild(r);
      });
      const S = window.Sprites;
      if (S && !S.ok) S.onReady(drawFaces); else drawFaces();
    }

    function syncRoster() {
      if (roster && roster.length < n()) fetchRoster(roster).then(d => { roster = d.roster; drawRoster(); remember(); },
        e => { $('su-msg').textContent = e.message; $('su-msg').className = 'msg bad'; });
      else drawRoster();
    }

    $('su-own').onchange = () => {
      if (!$('su-own').checked) { roster = null; drawRoster(); remember(); return; }
      fetchRoster().then(d => { roster = d.roster; drawRoster(); remember(); });
    };
    $('su-rand').onclick = () => fetchRoster([]).then(d => {
      const keys = Object.keys(info.characters).filter(k => info.characters[k].group === 'mild');
      roster = d.roster.map(v => Object.assign(v, { character: keys[Math.floor(Math.random() * keys.length)] }));
      drawRoster(); remember();
    });
    $('su-neutral').onclick = () => { roster.forEach(v => { v.character = 'default'; }); drawRoster(); remember(); };
    syncRoster();
    // The per-villager editor sits right under «Сколько жителей», in both views (Danel 2026-10-08).
    rows.villagers.el.after($('su-people'));


    setView(view);

    $('su-reset').onclick = () => { touched = new Set(); set(byKey.preset, values.preset); };
    $('su-go').onclick = () => {
      const go = $('su-go');
      go.disabled = true; $('su-msg').textContent = ''; $('su-msg').className = 'msg';
      const body = {};
      for (const k of knobs) if (!notHere(k)) body[k.key] = values[k.key];
      if (roster) body.roster = roster.slice(0, n());
      goLoading('Строю деревню', 'Рисую карту, расселяю жителей, раскладываю ягоды по кустам…');
      post('/api/start', body).then(() => location.reload(), e => {
        hideLoading();
        go.disabled = false; $('su-msg').textContent = e.message; $('su-msg').className = 'msg bad';
      });
    };

    // Past sessions (aivillage/session.py): the summary page, plus the replay of the map.
    fetch('/api/sessions').then(r => r.json()).then(d => {
      const box = $('su-runs');
      box.textContent = d.sessions.length ? '' : 'Прошлых деревень пока нет.';
      for (const s of d.sessions.slice(0, 10)) {
        const line = document.createElement('div');
        const a = document.createElement('a');
        a.href = '/session/' + encodeURIComponent(s.name);
        a.textContent = '📋 ' + s.name.replace('_', ' ').replace(/-(\d\d)-(\d\d)$/, ':$1');
        const info = document.createElement('span');
        info.className = 'hint';
        info.textContent = ` ${s.villagers} жит., «${s.mode}»` + (s.summary ? `, ${s.days} дн.` + (s.top ? `: ${s.top}` : '') : '') + (s.note ? ' 💬' : '') + ' ';
        const r = document.createElement('a');
        r.href = '/replay/' + encodeURIComponent(s.name); r.target = '_blank'; r.textContent = '▶ повтор';
        line.append(a, info, r);
        box.appendChild(line);
      }
      if (d.sessions.length) {
        const all = document.createElement('a');
        all.href = '/sessions'; all.textContent = 'Все сессии →';
        box.appendChild(all);
      }
    }).catch(() => { $('su-runs').textContent = ''; });
    $('su-report').onclick = () => post('/api/report-last', { note: $('su-note').value }).then(d => {
      $('su-rmsg').textContent = 'Готово: ' + d.path + '. Перетащите этот файл в чат проекта.'; $('su-rmsg').className = 'msg';
    }, e => { $('su-rmsg').textContent = e.message; $('su-rmsg').className = 'msg bad'; });
  }
})();
