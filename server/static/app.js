/* Rexo Studio - interface web locale (vanilla JS, aucune dependance) */
'use strict';

const S = { busy: false };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ------------------------------------------------------------------ */
/* Utilitaires                                                         */
/* ------------------------------------------------------------------ */

function toast(msg, isError) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' err' : ' ok');
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = 'toast'; }, 4200);
}

function fmtTime(s) {
  s = Math.max(0, Number(s) || 0);
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, '0');
  return m + ':' + sec;
}

function fmtDuration(s) {
  s = Math.max(0, Number(s) || 0);
  if (s < 60) return s.toFixed(1).replace('.', ',') + ' s';
  const m = Math.floor(s / 60);
  return m + ' min ' + String(Math.round(s % 60)).padStart(2, '0') + ' s';
}

function fmtSize(bytes) {
  const u = ['o', 'Ko', 'Mo', 'Go'];
  let i = 0, n = bytes;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(1).replace('.', ',') + ' ' + u[i];
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function api(url, options) {
  const res = await fetch(url, options);
  let data = null;
  let invalid = false;
  try { data = await res.json(); } catch (e) { invalid = true; }
  if (!res.ok) throw new Error((data && data.error) || ('Erreur HTTP ' + res.status));
  if (invalid) throw new Error('Réponse illisible du serveur (' + url.split('?')[0] + ')');
  return data;
}

function post(url, body) {
  return api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

/* ------------------------------------------------------------------ */
/* Etat du systeme                                                     */
/* ------------------------------------------------------------------ */

function chip(text, on, title) {
  return '<span class="chip ' + (on ? 'on' : 'off') + '" title="' + escapeHtml(title || '') + '">' +
    escapeHtml(text) + '</span>';
}

const STATUS = { effects: true, photocraft: true };

async function loadStatus() {
  try {
    const s = await api('/api/status');
    const o = s.llm || {};
    const engine = o.backend === 'llama' ? 'llama.cpp' : 'Ollama';
    const names = s.whisper_models.map((m) => m.name).join(', ');
    $('#status-bar').innerHTML = [
      chip(o.up ? 'IA prête' : 'IA indisponible', o.up, 'Modèle ' + (o.model || '') + ' (' + engine + ')' +
           (o.up ? (o.running ? ', en mémoire' : ', démarre à la première demande') : ' : moteur absent ou arrêté')),
      chip('Vidéo', !!(s.ffmpeg && s.ffprobe), 'ffmpeg : ' + (s.ffmpeg || 'introuvable')),
      chip('Transcription', !!s.whisper && s.whisper_models.length > 0,
           'whisper.cpp, modèles : ' + (names || 'aucun') + (s.vad_model ? ', détection de la parole' : '')),
      chip('FilmCraft', !!s.filmcraft, s.filmcraft ? 'FilmCraft installé' : 'FilmCraft non installé'),
      chip('PhotoCraft', !!s.photocraft, s.photocraft ? 'PhotoCraft installé (moteur sans interface prêt)' : 'PhotoCraft non installé'),
    ].join('');
    STATUS.effects = !!s.effects;
    STATUS.photocraft = !!s.photocraft;
  } catch (e) {
    $('#status-bar').innerHTML = chip('Serveur injoignable', false, 'Relancez Rexo Studio');
  }
}

/* ------------------------------------------------------------------ */
/* Quitter                                                             */
/* ------------------------------------------------------------------ */

$('#btn-quit').addEventListener('click', async () => {
  if (S.busy) { toast('Un traitement est en cours : attendez la fin avant de quitter', true); return; }
  if (!confirm('Quitter Rexo Studio ?\nLe modèle IA sera retiré de la mémoire.')) return;
  try {
    await post('/api/quit');
  } catch (e) { toast(e.message, true); return; }
  document.body.innerHTML =
    '<div class="bye"><div class="logo">🎬</div><h1>Rexo Studio est arrêté</h1>' +
    '<p>La mémoire est libérée. Vous pouvez fermer cet onglet.</p>' +
    '<p class="muted">Pour revenir, double-cliquez sur l’icône Rexo Studio du bureau.</p></div>';
});

/* ------------------------------------------------------------------ */
/* Vues : la liste des evenements, ou un evenement                     */
/* ------------------------------------------------------------------ */

function showView(name) {
  $('#view-events').classList.toggle('hidden', name !== 'events');
  $('#view-event').classList.toggle('hidden', name !== 'event');
  if (name !== 'event') { $('#evd-player').pause(); $('#mt-player').pause(); }
  if (name === 'events') loadEvents();
}

/* ------------------------------------------------------------------ */
/* Evenements : un evenement = un dossier (docs/adr/0001)              */
/* ------------------------------------------------------------------ */

const EV = { items: [], types: [], type: '', root: '' };
const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
  'septembre', 'octobre', 'novembre', 'décembre'];
const DAYS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];

// Recherche sans accents ni majuscules : "henne" trouve "Henné", "fevrier" trouve "février".
function fold(s) {
  return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function evDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
  if (!m) return { text: iso || '', words: '' };
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  const text = DAYS[d.getDay()] + ' ' + (+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1];
  return { text: text, words: text + ' ' + m[3] + '/' + m[2] + '/' + m[1] };
}

function evHaystack(e) {
  return fold([e.names, e.place, e.notes, e.type_label, e.type, e.date, evDate(e.date).words, e.id]
    .join(' '));
}

function evMatches(e, words) {
  if (EV.type && e.type !== EV.type) return false;
  const hay = evHaystack(e);
  return words.every((w) => hay.includes(w));
}

// Surligne les mots cherches (comparaison sans accents).
function highlight(text, words) {
  text = String(text || '');
  const folded = fold(text);
  // NFD peut changer la longueur (lettres composees) : pas de surlignage alors.
  if (!words.length || folded.length !== text.length) return escapeHtml(text);
  const marks = [];
  words.forEach((w) => {
    let i = folded.indexOf(w);
    while (i >= 0) { marks.push([i, i + w.length]); i = folded.indexOf(w, i + w.length); }
  });
  marks.sort((a, b) => a[0] - b[0]);
  let out = '';
  let pos = 0;
  marks.forEach(([a, b]) => {
    if (a < pos) return;
    out += escapeHtml(text.slice(pos, a)) + '<mark>' + escapeHtml(text.slice(a, b)) + '</mark>';
    pos = b;
  });
  return out + escapeHtml(text.slice(pos));
}

const PLURALS = { rush: 'rushes', proxy: 'proxies' };

function plural(n, word) {
  return n + ' ' + (n > 1 ? (PLURALS[word] || word + 's') : word);
}

function evStats(e) {
  const files = {};
  (e.folders || []).forEach((f) => { files[f.name] = f.files; });
  const parts = [
    plural(files['01_Rushes'] || 0, 'rush'),
    plural(files['02_Photos'] || 0, 'photo'),
    plural(files['06_Rendus'] || 0, 'rendu'),
  ];
  if (files['07_Livraison']) parts.push('livré');
  return parts.join(' · ') + (e.size ? ' — ' + fmtSize(e.size) : '');
}

function renderEventTypes() {
  const counts = {};
  EV.items.forEach((e) => { counts[e.type] = (counts[e.type] || 0) + 1; });
  const chips = [{ key: '', label: 'Tous', n: EV.items.length }]
    .concat(EV.types.map((t) => ({ key: t.key, label: t.label, n: counts[t.key] || 0 })));
  $('#ev-types').innerHTML = chips.map((c) =>
    '<button class="filter' + (EV.type === c.key ? ' active' : '') + '" data-type="' +
    escapeHtml(c.key) + '">' + escapeHtml(c.label) + ' <span class="muted">' + c.n + '</span></button>'
  ).join('');
}

$('#ev-types').addEventListener('click', (ev) => {
  const b = ev.target.closest('.filter');
  if (!b) return;
  EV.type = b.dataset.type;
  renderEventTypes();
  renderEvents();
});

function renderEvents() {
  const q = $('#ev-search').value;
  const words = fold(q).split(/\s+/).filter(Boolean);
  const shown = EV.items.filter((e) => evMatches(e, words));
  const list = $('#ev-list');
  if (!EV.items.length) {
    $('#ev-count').textContent = '';
    list.innerHTML = '<p class="empty">Aucun événement pour l’instant. Cliquez sur ' +
      '« Nouvel événement » pour créer le dossier du premier.</p>';
    return;
  }
  $('#ev-count').textContent = shown.length === EV.items.length
    ? plural(EV.items.length, 'événement')
    : shown.length + ' sur ' + plural(EV.items.length, 'événement');
  if (!shown.length) {
    list.innerHTML = '<p class="empty">Aucun événement ne correspond' +
      (q.trim() ? ' à « ' + escapeHtml(q.trim()) + ' »' : '') + '.</p>';
    return;
  }
  list.innerHTML = shown.map((e) => {
    const id = escapeHtml(e.id);
    const folders = (e.folders || []).map((f) =>
      '<button class="ev-folder" data-id="' + id + '" data-sub="' + escapeHtml(f.name) +
      '" title="Ouvrir ' + escapeHtml(f.name) + ' dans le Finder">' + escapeHtml(f.label) +
      (f.files ? ' <b>' + f.files + '</b>' : '') + '</button>').join('');
    return '<div class="ev-card" data-id="' + id + '">' +
      '<div class="ev-head"><span class="ev-date">' + highlight(evDate(e.date).text, words) + '</span>' +
      '<span class="ev-type t-' + escapeHtml(e.type) + '">' + escapeHtml(e.type_label) + '</span></div>' +
      '<p class="ev-names" dir="auto">' + highlight(e.names, words) + '</p>' +
      (e.place ? '<p class="ev-place" dir="auto">📍 ' + highlight(e.place, words) + '</p>' : '') +
      (e.notes ? '<p class="ev-notes" dir="auto">' + highlight(e.notes, words) + '</p>' : '') +
      '<div class="ev-stats">' + escapeHtml(evStats(e)) + '</div>' +
      '<div class="ev-folders">' + folders + '</div>' +
      '<div class="btn-row ev-actions">' +
      '<button class="btn btn-primary btn-small ev-derush" data-id="' + id + '">🎬 Ouvrir</button>' +
      '<button class="btn btn-sec btn-small ev-open" data-id="' + id + '">📂 Dossier</button>' +
      '<button class="btn btn-sec btn-small ev-trash" data-id="' + id + '" title="Mettre tout l’événement à la Corbeille">🗑</button></div>' +
      '</div>';
  }).join('');
}

async function openEvent(id, sub) {
  try {
    await post('/api/events/open', { id: id, sub: sub || '' });
  } catch (e) { toast(e.message, true); }
}

$('#ev-list').addEventListener('click', (ev) => {
  const del = ev.target.closest('.ev-trash');
  if (del) { trashEvent(del.dataset.id); return; }
  const derush = ev.target.closest('.ev-derush, .ev-names');
  if (derush) { openDerush(derush.dataset.id || derush.closest('.ev-card').dataset.id); return; }
  const btn = ev.target.closest('.ev-folder, .ev-open');
  if (btn) openEvent(btn.dataset.id, btn.dataset.sub);
});

async function loadEvents() {
  try {
    const data = await api('/api/events');
    EV.items = data.events || [];
    EV.types = data.types || [];
    EV.root = data.root || '';
    if (!$('#ev-type').options.length) {
      $('#ev-type').innerHTML = EV.types.map((t) =>
        '<option value="' + escapeHtml(t.key) + '">' + escapeHtml(t.label) + '</option>').join('');
    }
    $('#ev-root').textContent = 'Dossiers rangés dans ' + EV.root;
    renderEventTypes();
    renderEvents();
  } catch (e) {
    $('#ev-list').innerHTML = '<p class="empty">' + escapeHtml(e.message) + '</p>';
  }
}

$('#ev-search').addEventListener('input', renderEvents);
$('#ev-search').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.target.value = ''; renderEvents(); }
});

/* -- creation -- */

// Meme nettoyage que montagia/events.clean_names (apercu seulement :
// le serveur fait foi et ajoute _2, _3 si le dossier existe deja).
function cleanNames(text) {
  return String(text || '').normalize('NFC').replace(/&/g, ' et ')
    .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, ' ').trim().replace(/\s+/g, '-')
    .replace(/-{2,}/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 60).replace(/[-.]+$/, '');
}

function folderPreview() {
  const names = cleanNames($('#ev-names').value);
  const date = $('#ev-date').value;
  $('#ev-folder-preview').textContent = names && date
    ? date + '_' + $('#ev-type').value + '_' + names : '—';
}

function todayIso() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

function showEventForm(show) {
  $('#ev-form').classList.toggle('hidden', !show);
  if (show) {
    if (!$('#ev-date').value) $('#ev-date').value = todayIso();
    folderPreview();
    $('#ev-names').focus();
  }
}

$('#btn-ev-new').addEventListener('click', () =>
  showEventForm($('#ev-form').classList.contains('hidden')));
$('#btn-ev-cancel').addEventListener('click', () => showEventForm(false));
['#ev-names', '#ev-date', '#ev-type'].forEach((sel) => {
  $(sel).addEventListener('input', folderPreview);
  $(sel).addEventListener('change', folderPreview);
});

$('#ev-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('#btn-ev-create');
  btn.disabled = true;
  try {
    const ev = await post('/api/events/create', {
      type: $('#ev-type').value, date: $('#ev-date').value, names: $('#ev-names').value,
      place: $('#ev-place').value, notes: $('#ev-notes').value,
    });
    ['#ev-names', '#ev-place', '#ev-notes'].forEach((sel) => { $(sel).value = ''; });
    showEventForm(false);
    $('#ev-search').value = '';
    EV.type = '';
    await loadEvents();
    toast('Dossier créé : ' + ev.id);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
});


/* ------------------------------------------------------------------ */
/* Un evenement, en trois parties : Video, Photo, Montage              */
/* ------------------------------------------------------------------ */

const EVD = { id: '', event: null, clips: [], photos: [], cards: [], issues: {}, filter: 'all', effects: [],
  studio: null, moments: null, renders: [], part: 'video', photoFilter: 'all', photo: '', titled: false };

function fileUrl(path) {
  return '/api/file?path=' + encodeURIComponent(path);
}

async function openDerush(id) {
  const other = EVD.id !== id;
  EVD.id = id;
  showView('event');
  $('#evd-player-box').classList.add('hidden');
  $('#evd-player').pause();
  $('#mt-player-box').classList.add('hidden');
  if (other) { EVD.photo = ''; EVD.titled = false; }
  showPart(other ? 'video' : EVD.part);
  await loadDerush();
  loadSources();
}

// L'import d'une carte sert aux deux premieres parties : la meme carte est placee dans
// la partie affichee (une carte d'appareil contient souvent videos et photos).
function showPart(part) {
  EVD.part = part;
  $$('#evd-tabs .evd-tab').forEach((b) => b.classList.toggle('active', b.dataset.part === part));
  ['video', 'photo', 'montage'].forEach((p) => $('#part-' + p).classList.toggle('hidden', p !== part));
  const slot = document.querySelector('.evd-slot[data-slot="' + part + '"]');
  const card = $('#evd-import-card');
  if (slot) { slot.appendChild(card); card.classList.remove('hidden'); } else card.classList.add('hidden');
  card.querySelector('.evd-step').textContent = '1 · ';
  if (part !== 'video') $('#evd-player').pause();
  if (part !== 'montage') $('#mt-player').pause();
}

$('#evd-tabs').addEventListener('click', (ev) => {
  const b = ev.target.closest('.evd-tab');
  if (b) showPart(b.dataset.part);
});

async function loadDerush() {
  if (!EVD.id) return;
  try {
    const data = await api('/api/events/detail?id=' + encodeURIComponent(EVD.id));
    EVD.event = data.event;
    EVD.clips = data.clips || [];
    EVD.issues = data.issues || {};
    EVD.photos = data.photos || [];
    EVD.cards = data.cards || [];
    EVD.imports = data.imports || [];
    EVD.effects = data.effects || [];
    EVD.studio = data.studio || null;
    EVD.moments = data.moments || null;
    EVD.renders = data.renders || [];
    const e = data.event;
    $('#evd-type').textContent = e.type_label;
    $('#evd-type').className = 'ev-type t-' + e.type;
    $('#evd-names').textContent = e.names;
    $('#evd-date').textContent = evDate(e.date).text + (e.place ? ' — ' + e.place : '');
    renderDerush();
    renderCards();
    renderFolders();
    renderPhotos();
    renderMoments();
    renderMontage();
  } catch (err) {
    toast(err.message, true);
  }
}

function clipState(c) {
  if (!c.analyzed) return 'new';
  return c.kept ? 'kept' : 'out';
}

function renderDerush() {
  const clips = EVD.clips;
  const count = { all: clips.length, kept: 0, out: 0, new: 0 };
  let keptSeconds = 0;
  clips.forEach((c) => {
    count[clipState(c)]++;
    if (clipState(c) === 'kept') keptSeconds += c.duration || 0;
  });
  $$('#evd-filters .filter').forEach((b) => {
    b.classList.toggle('active', b.dataset.f === EVD.filter);
    b.querySelector('span').textContent = count[b.dataset.f];
  });
  const total = clips.reduce((t, c) => t + (c.duration || 0), 0);
  $('#evd-summary').textContent = !clips.length
    ? 'Aucun rush : importez une carte mémoire (ou copiez des vidéos dans 01_Rushes, puis « Analyser »).'
    : plural(clips.length, 'rush') + ' (' + fmtDuration(total) + ') · ' + count.kept + ' gardé' +
      (count.kept > 1 ? 's' : '') + ' (' + fmtDuration(keptSeconds) + ') · ' + count.out + ' écarté' +
      (count.out > 1 ? 's' : '') + (count.new ? ' · ' + count.new + ' à analyser' : '');
  $('#evd-filmcraft').disabled = !count.kept;
  $('#evd-tab-video').textContent = clips.length ? clips.length : '';

  const shown = clips.filter((c) => EVD.filter === 'all' || clipState(c) === EVD.filter);
  const box = $('#evd-clips');
  if (!shown.length) {
    box.innerHTML = clips.length ? '<p class="empty">Aucun rush dans ce filtre.</p>' : '';
    return;
  }
  box.innerHTML = shown.map((c) => {
    const st = clipState(c);
    const issues = !c.analyzed ? '<span class="issue">À analyser</span>'
      : c.issues.length ? c.issues.map((i) => '<span class="issue">' + escapeHtml(EVD.issues[i] || i) + '</span>').join('')
        : '<span class="issue ok">Bon</span>';
    const time = (c.shot_at || '').slice(11, 19);
    // Definition = petit cote (une video verticale 720x1280 est du 720p).
    const side = Math.min(c.width || 0, c.height || 0);
    const res = side ? (side >= 2160 ? '4K' : side + 'p') + (c.width < c.height ? ' vertical' : '') +
      ' ' + Math.round(c.fps || 0) + ' i/s' : '';
    const auto = c.keep === null && c.analyzed ? '<span class="auto">(proposé)</span>' : '';
    return '<div class="rush ' + st + '">' +
      '<div class="rush-thumb" data-rel="' + escapeHtml(c.rel) + '">' +
      (c.thumb ? '<img loading="lazy" src="' + fileUrl(c.thumb) + '" alt="">' : '') +
      '<span class="play">▶</span>' +
      (c.duration ? '<span class="dur">' + fmtDuration(c.duration) + '</span>' : '') + '</div>' +
      '<div class="rush-body">' +
      '<div class="rush-name">' + escapeHtml(c.name) +
      (c.thumb ? '<button class="dv-open" data-rel="' + escapeHtml(c.rel) + '" title="Détourer une personne (EffectCraft, SAM 2.1)">✂</button>' : '') +
      '<button class="sub-open" data-rel="' + escapeHtml(c.rel) + '" title="Sous-titrer un discours (transcription locale)">💬</button>' +
      '<button class="del" data-rel="' + escapeHtml(c.rel) + '" title="Mettre à la Corbeille">🗑</button></div>' +
      '<div class="rush-meta">' + escapeHtml([c.card.replace('_', ' '), time, res].filter(Boolean).join(' · ')) + '</div>' +
      '<div class="rush-issues">' + issues + '</div>' +
      (c.analyzed ? '<label class="rush-keep"><input type="checkbox" data-rel="' + escapeHtml(c.rel) + '"' +
        (c.kept ? ' checked' : '') + '> Garder ' + auto + '</label>' : '') +
      '</div></div>';
  }).join('');
}

$('#evd-filters').addEventListener('click', (ev) => {
  const b = ev.target.closest('.filter');
  if (!b) return;
  EVD.filter = b.dataset.f;
  renderDerush();
});

$('#evd-clips').addEventListener('click', (ev) => {
  const thumb = ev.target.closest('.rush-thumb');
  if (!thumb) return;
  const c = EVD.clips.find((x) => x.rel === thumb.dataset.rel);
  if (!c) return;
  const player = $('#evd-player');
  player.src = fileUrl(c.proxy || c.path);
  $('#evd-player-label').textContent = c.name + (c.proxy ? ' (proxy)' : '') + ' — ' + c.rel;
  $('#evd-player-box').classList.remove('hidden');
  $('#evd-player-box').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  player.play().catch(() => {});        // lecture auto refusee : le bouton ▶ du lecteur reste
});

// Format que le navigateur ne sait pas lire (XAVC 4K, HEVC 10 bits, MXF...).
$('#evd-player').addEventListener('error', () => {
  if ($('#evd-player').getAttribute('src')) {
    toast('Lecture impossible dans le navigateur : créez les proxies', true);
  }
});

$('#evd-clips').addEventListener('change', async (ev) => {
  const box = ev.target.closest('input[type=checkbox]');
  if (!box) return;
  try {
    await post('/api/events/keep', { id: EVD.id, rel: box.dataset.rel, keep: box.checked });
    const c = EVD.clips.find((x) => x.rel === box.dataset.rel);
    if (c) { c.keep = box.checked; c.kept = box.checked; }
    renderDerush();
  } catch (err) {
    toast(err.message, true);
    box.checked = !box.checked;
  }
});

/* -- traitements de fond -- */

function derushJob(url, body, onDone) {
  if (S.busy) { toast('Un traitement est déjà en cours', true); return; }
  S.busy = true;
  document.body.classList.add('busy');
  const fill = $('#evd-job-fill');
  const label = $('#evd-job-label');
  const log = $('#evd-job-log');
  const setP = (v, step) => {
    fill.style.width = Math.round((v || 0) * 100) + '%';
    label.textContent = (step || '') + ' — ' + Math.round((v || 0) * 100) + ' %';
  };
  $('#evd-job').classList.remove('hidden');
  log.textContent = '';
  setP(0, 'Démarrage');
  const finish = () => { S.busy = false; document.body.classList.remove('busy'); loadDerush(); };
  post(url, Object.assign({ id: EVD.id }, body || {})).then((data) => {
    const es = new EventSource('/api/jobs/' + data.job_id + '/events');
    es.onmessage = (m) => {
      let e;
      try { e = JSON.parse(m.data); } catch (err) { return; }
      if (e.type === 'snapshot' && e.job) {
        setP(e.job.progress, e.job.step);
        if (e.job.log) log.textContent = e.job.log.join('\n') + '\n';
      } else if (e.type === 'progress') {
        setP(e.progress, e.step);
      } else if (e.type === 'log') {
        log.textContent += e.message + '\n';
        log.scrollTop = log.scrollHeight;
      } else if (e.type === 'done') {
        setP(1, 'Terminé');
        es.close();
        finish();
        if (onDone) onDone(e.result || {});
      } else if (e.type === 'error') {
        log.textContent += 'ERREUR : ' + e.error + '\n';
        setP(0, 'Échec');
        toast(e.error, true);
        es.close();
        finish();
      }
    };
    es.onerror = () => { es.close(); finish(); };
  }).catch((err) => { toast(err.message, true); finish(); });
}

async function loadSources() {
  const sel = $('#evd-source');
  sel.innerHTML = '<option value="">Recherche des cartes…</option>';
  try {
    const data = await api('/api/sources');
    const list = data.sources || [];
    sel.innerHTML = list.length
      ? list.map((s) => '<option value="' + escapeHtml(s.path) + '">💾 ' + escapeHtml(s.name) + ' — ' +
          s.videos + ' vidéo' + (s.videos > 1 ? 's' : '') + ', ' + s.photos + ' photo' + (s.photos > 1 ? 's' : '') +
          ' (' + fmtSize(s.size) + ')</option>').join('')
      : '<option value="">Aucune carte détectée : branchez-la puis ↻</option>';
  } catch (err) {
    sel.innerHTML = '<option value="">' + escapeHtml(err.message) + '</option>';
  }
}

$('#evd-refresh').addEventListener('click', loadSources);
$('#evd-back').addEventListener('click', () => { $('#evd-player').pause(); showView('events'); });
$('#evd-open').addEventListener('click', () => openEvent(EVD.id, ''));

$('#evd-import').addEventListener('click', () => {
  const source = $('#evd-path').value.trim() || $('#evd-source').value;
  if (!source) { toast('Choisissez une carte ou indiquez un dossier', true); return; }
  derushJob('/api/events/import', { source: source }, (r) => {
    if (!r.copied) { toast('Rien de nouveau : cette carte est déjà importée'); return; }
    toast(r.copied + ' fichier' + (r.copied > 1 ? 's' : '') + ' copié' + (r.copied > 1 ? 's' : '') +
      ' et vérifié' + (r.copied > 1 ? 's' : '') + ' dans ' + r.card);
    $('#evd-path').value = '';
  });
});
$('#evd-analyze').addEventListener('click', () => derushJob('/api/events/analyze', {}, (r) =>
  toast(r.analyzed + ' rush' + (r.analyzed > 1 ? 's' : '') + ' analysé' + (r.analyzed > 1 ? 's' : '') +
    ', ' + r.issues + ' avec un défaut')));
$('#evd-proxies').addEventListener('click', () => derushJob('/api/events/proxies', {}, (r) =>
  toast(plural(r.made, 'proxy') + ' créé' + (r.made > 1 ? 's' : ''))));
$('#evd-filmcraft').addEventListener('click', () => derushJob('/api/events/filmcraft', {}, (r) =>
  toast('Montage ouvert dans FilmCraft : ' + r.clips + ' rushes (' + fmtDuration(r.duration) + ')' +
    (r.renders ? ', ' + plural(r.renders, 'rendu') : ''))));


/* ------------------------------------------------------------------ */
/* Corbeille : supprimer un evenement, une carte, un dossier, un media */
/* ------------------------------------------------------------------ */

const TRASH_NOTE = '\n\nLes fichiers vont dans la Corbeille du Mac : récupérables tant qu’elle n’est pas vidée.';

async function trashEvent(id) {
  const e = EV.items.find((x) => x.id === id);
  if (!e) return;
  const files = (e.folders || []).reduce((t, f) => t + f.files, 0);
  const typed = prompt('Mettre TOUT l’événement « ' + e.names + ' » (' + e.type_label + ', ' +
    evDate(e.date).text + ') à la Corbeille ?\n' + plural(files, 'fichier') +
    (e.size ? ', ' + fmtSize(e.size) : '') + ' : rushes, photos, montages, rendus.' + TRASH_NOTE +
    '\n\nTapez SUPPRIMER pour confirmer :');
  if (typed === null) return;
  if (typed.trim().toUpperCase() !== 'SUPPRIMER') { toast('Suppression annulée', true); return; }
  try {
    await post('/api/events/delete', { id: id });
    toast('Événement mis à la Corbeille : ' + e.names);
    if (EVD.id === id) { EVD.id = ''; showView('events'); } else { loadEvents(); }
  } catch (err) { toast(err.message, true); }
}

async function trashInEvent(body, question) {
  if (S.busy) { toast('Un traitement est en cours : attendez la fin', true); return; }
  if (!confirm(question + TRASH_NOTE)) return;
  try {
    const r = await post('/api/events/trash', Object.assign({ id: EVD.id }, body));
    toast(plural(r.trashed.length, 'élément') + ' mis à la Corbeille');
  } catch (err) { toast(err.message, true); }
  $('#evd-player').pause();
  $('#evd-player').removeAttribute('src');
  $('#evd-player-box').classList.add('hidden');
  loadDerush();
}

function renderCards() {
  const box = $('#evd-cards');
  if (!EVD.cards.length) { box.innerHTML = ''; return; }
  const source = {};
  (EVD.imports || []).forEach((i) => { source[i.card] = i.source; });
  box.innerHTML = '<p class="tiny muted">Cartes importées :</p>' + EVD.cards.map((c) =>
    '<div class="evd-card-row"><span>💾 <b>' + escapeHtml(c.name.replace('_', ' ')) + '</b> — ' +
    plural(c.videos, 'vidéo') + ', ' + plural(c.photos, 'photo') +
    (source[c.name] ? ' <span class="muted">(' + escapeHtml(source[c.name]) + ')</span>' : '') + '</span>' +
    '<button class="del" data-card="' + escapeHtml(c.name) + '" title="Mettre cette carte à la Corbeille">🗑</button></div>'
  ).join('');
}

function renderFolders() {
  const e = EVD.event;
  $('#evd-folders').innerHTML = (e.folders || []).map((f) =>
    '<div class="evd-folder"><button class="ev-folder" data-sub="' + escapeHtml(f.name) + '" title="Ouvrir dans le Finder">📂 ' +
    escapeHtml(f.label) + ' <b>' + f.files + '</b>' + (f.size ? ' <span class="muted">' + fmtSize(f.size) + '</span>' : '') +
    '</button>' + (f.files ? '<button class="del" data-folder="' + escapeHtml(f.name) + '" data-label="' + escapeHtml(f.label) +
      '" data-files="' + f.files + '" data-size="' + f.size + '" title="Vider ce dossier (Corbeille)">🗑</button>' : '') +
    '</div>').join('');
}

function renderPhotos() {
  const chosen = EVD.photos.filter((p) => p.montage).length;
  $('#evd-photo-count').textContent = EVD.photos.length ? '(' + EVD.photos.length + ')' : '';
  $('#evd-tab-photo').textContent = EVD.photos.length ? EVD.photos.length : '';
  const counts = { all: EVD.photos.length, montage: chosen };
  $$('#evp-filters .filter').forEach((b) => {
    b.classList.toggle('active', b.dataset.f === EVD.photoFilter);
    b.querySelector('span').textContent = counts[b.dataset.f];
  });
  const shown = EVD.photos.filter((p) => EVD.photoFilter === 'all' || p.montage);
  $('#evd-photos').innerHTML = !EVD.photos.length
    ? '<p class="empty">Aucune photo : importez la carte de l’appareil photo (étape 1), elles vont dans 02_Photos.</p>'
    : !shown.length ? '<p class="empty">Aucune photo cochée ★ pour le montage.</p>'
    : shown.map((p) =>
      '<div class="photo' + (p.montage ? ' chosen' : '') + '" title="' + escapeHtml(p.rel) + '">' +
      '<a ' + (p.viewable ? 'href="' + fileUrl(p.path) + '" target="_blank" rel="noopener"' : 'class="noview"') + '>' +
      (p.thumb ? '<img loading="lazy" src="' + fileUrl(p.thumb) + '" alt="">' : '<span class="muted">' + escapeHtml(p.name) + '</span>') +
      '</a><div class="photo-bar">' +
      '<button class="star' + (p.montage ? ' on' : '') + '" data-rel="' + escapeHtml(p.rel) + '" title="' +
      (p.montage ? 'Retirer du montage' : 'Utiliser dans le montage (clips 3D)') + '">' + (p.montage ? '★' : '☆') + '</button>' +
      '<span>' + escapeHtml(p.name) + (p.box ? ' <span class="muted" title="Cadre des mariés tracé">▭</span>' : '') + '</span>' +
      '<button class="fx-open" data-rel="' + escapeHtml(p.rel) + '" title="Effets IA : détourage, fond noir et blanc, fond flou">✨</button>' +
      '<button class="del" data-rel="' + escapeHtml(p.rel) + '" title="Mettre à la Corbeille">🗑</button></div></div>'
    ).join('');
}

$('#evd-clips').addEventListener('click', (ev) => {
  const b = ev.target.closest('.del');
  if (!b) return;
  ev.stopPropagation();
  const c = EVD.clips.find((x) => x.rel === b.dataset.rel);
  trashInEvent({ rel: b.dataset.rel }, 'Mettre le rush « ' + (c ? c.name : b.dataset.rel) + ' » à la Corbeille ?' +
    (c && c.proxy ? '\nSon proxy part avec lui.' : ''));
}, true);

async function setPhoto(rel, changes) {
  const r = await post('/api/events/photo', Object.assign({ id: EVD.id, rel: rel }, changes));
  const p = EVD.photos.find((x) => x.rel === rel);
  if (p) { p.montage = r.montage; p.box = r.box; }
  renderPhotos();
  renderMontage();
  return r;
}

$('#evp-filters').addEventListener('click', (ev) => {
  const b = ev.target.closest('.filter');
  if (!b) return;
  EVD.photoFilter = b.dataset.f;
  renderPhotos();
});

$('#evd-photos').addEventListener('click', (ev) => {
  const star = ev.target.closest('.star');
  if (star) {
    const p = EVD.photos.find((x) => x.rel === star.dataset.rel);
    setPhoto(star.dataset.rel, { montage: !(p && p.montage) }).catch((err) => toast(err.message, true));
    return;
  }
  const fx = ev.target.closest('.fx-open');
  if (fx) { openFx(fx.dataset.rel); return; }
  const b = ev.target.closest('.del');
  if (!b) return;
  trashInEvent({ rel: b.dataset.rel }, 'Mettre la photo « ' + b.dataset.rel.split('/').pop() + ' » à la Corbeille ?');
});

$('#evd-cards').addEventListener('click', (ev) => {
  const b = ev.target.closest('.del');
  if (!b) return;
  const c = EVD.cards.find((x) => x.name === b.dataset.card) || { videos: 0, photos: 0 };
  trashInEvent({ card: b.dataset.card }, 'Mettre toute la ' + b.dataset.card.replace('_', ' ') + ' à la Corbeille ?\n' +
    plural(c.videos, 'vidéo') + ', ' + plural(c.photos, 'photo') + ' et leurs proxies.');
});

$('#evd-folders').addEventListener('click', (ev) => {
  const del = ev.target.closest('.del');
  if (del) {
    const d = del.dataset;
    trashInEvent({ rel: d.folder }, 'Vider le dossier ' + d.label + ' (' + d.folder + ') ?\n' +
      plural(+d.files, 'fichier') + ', ' + fmtSize(+d.size) + '. Le dossier lui-même reste en place.');
    return;
  }
  const open = ev.target.closest('.ev-folder');
  if (open) openEvent(EVD.id, open.dataset.sub);
});

/* ------------------------------------------------------------------ */
/* Effets IA sur une photo (M5) : apercu, cadre PhotoCraft, rendu      */
/* ------------------------------------------------------------------ */

const FX = { photo: null, effect: 'detourage', framing: false, box: null, drag: null,
  result: null, saved: '', busy: false, view: 'orig', plan: null, boxes: {}, target: null };

const TOOL_LABELS = {
  detourer: 'Détourer les personnes (fond transparent)',
  ameliorer: 'Améliorer la photo (lumière, couleurs, blancs, relief)',
  cadre_maries: 'Cadre autour des mariés (robe et traîne)',
  fond_noir_et_blanc: 'Mariés en couleur, fond noir et blanc',
  fond_flou: 'Arrière-plan flou',
  fond_uni: 'Fond uni',
  effacer_objet: 'Effacer',
  style: 'Style',
  recadrer: 'Recadrer',
};

function stepLabel(s) {
  const param = s.cible || s.couleur || s.style || s.format;
  return (TOOL_LABELS[s.outil] || s.outil) + (param ? ' : ' + param : '');
}

/* Suit une tache de fond ; handlers : log(message), done(resultat), error(message) */
function followJob(jobId, h) {
  const es = new EventSource('/api/jobs/' + jobId + '/events');
  es.onmessage = (m) => {
    let e;
    try { e = JSON.parse(m.data); } catch (err) { return; }
    if (e.type === 'log' && h.log) h.log(e.message);
    else if (e.type === 'progress' && h.log && e.step) h.log(e.step);
    else if (e.type === 'done') { es.close(); h.done(e.result || {}); }
    else if (e.type === 'error') { es.close(); h.error(e.error || 'Échec'); }
  };
  es.onerror = () => { es.close(); h.error('Connexion au suivi perdue'); };
}

function openFx(rel) {
  const p = EVD.photos.find((x) => x.rel === rel);
  if (!p) return;
  Object.assign(FX, { photo: p, framing: false, box: null, drag: null, result: null, saved: '', view: 'orig',
    plan: null, boxes: {}, target: null });
  $('#fx-plan').classList.add('hidden');
  $('#fx-name').textContent = p.name;
  if (!fxSpec()) FX.effect = 'detourage';
  $('#fx-effects').innerHTML = EVD.effects.map((e) =>
    '<button class="filter" data-effect="' + escapeHtml(e.key) + '"' +
    (e.available ? '' : ' disabled title="Non installé : voir docs/DEPLOIEMENT.md"') + '>' +
    escapeHtml(e.label) + '</button>').join('');
  const info = $('#fx-info');
  info.className = 'tiny' + (STATUS.effects ? '' : ' err');
  info.textContent = STATUS.effects ? '' : 'Outil d’effets absent : lancez ./scripts/build_native.sh';
  $('#fx-photocraft').disabled = !STATUS.photocraft;
  $('#fx-montage').checked = !!p.montage;
  // Cadre des maries deja trace pour cette photo (garde pour le clip 3D)
  if (p.box && !(fxSpec() || {}).needs_box) FX.box = p.box.slice();
  fxRender();
  $('#fx').classList.remove('hidden');
}

/* ------------------------------------------------------------------ */
/* Partie Video : moments forts ; sous-titres d'un discours            */
/* ------------------------------------------------------------------ */

function renderMoments() {
  const list = (EVD.moments && EVD.moments.moments) || [];
  $('#mo-list').innerHTML = !list.length
    ? '<p class="tiny muted">Pas encore de moments forts : analysez et gardez des rushes, puis lancez la recherche.</p>'
    : '<p class="tiny">' + plural(list.length, 'moment') + ' retenu' + (list.length > 1 ? 's' : '') +
      ', dans l’ordre du tournage :</p>' + list.map((m, i) =>
      '<button class="mo-item" data-i="' + i + '" title="Voir ce passage">▶ ' + escapeHtml(m.name) + ' <span class="muted">' +
      fmtTime(m.start) + ' → ' + fmtTime(m.end) + ' · qualité ' + Math.round(100 * (m.score || 0)) + ' %' +
      (m.people ? ' · personnes ' + Math.round(100 * m.people) + ' %' : '') + '</span></button>').join('');
}

$('#mo-run').addEventListener('click', () => derushJob('/api/events/moments', { count: +$('#mo-count').value },
  (r) => toast(plural((r.moments || []).length, 'moment') + ' fort' + ((r.moments || []).length > 1 ? 's' : '') +
    ' : le générique est prêt à être créé (onglet Montage)')));

$('#mo-list').addEventListener('click', (ev) => {
  const b = ev.target.closest('.mo-item');
  if (!b) return;
  const m = EVD.moments.moments[+b.dataset.i];
  const c = EVD.clips.find((x) => x.rel === m.rel);
  const player = $('#evd-player');
  player.src = fileUrl((c && c.proxy) || (c ? c.path : m.rel));
  player.currentTime = m.start;
  $('#evd-player-label').textContent = 'Moment fort : ' + m.name + ', ' + fmtTime(m.start) + ' → ' + fmtTime(m.end);
  $('#evd-player-box').classList.remove('hidden');
  player.addEventListener('loadedmetadata', () => { player.currentTime = m.start; }, { once: true });
  player.play().catch(() => {});
  $('#evd-player-box').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});

$('#evd-clips').addEventListener('click', (ev) => {
  const b = ev.target.closest('.sub-open');
  if (!b) return;
  ev.stopPropagation();
  const c = EVD.clips.find((x) => x.rel === b.dataset.rel);
  if (!confirm('Sous-titrer le discours de « ' + (c ? c.name : b.dataset.rel) + ' » ?\n' +
    'La parole est transcrite sur cet ordinateur (langue reconnue automatiquement) ; le fichier .srt ' +
    'arrive dans 06_Rendus/Sous-titres, à poser sur le discours dans FilmCraft.')) return;
  derushJob('/api/events/studio', { recipe: 'sous-titres', rel: b.dataset.rel },
    (r) => toast('Sous-titres : ' + r.lines + ' lignes → ' + r.path));
}, true);

/* ------------------------------------------------------------------ */
/* Partie Montage : titres, generique, clip 3D, rendus, FilmCraft      */
/* ------------------------------------------------------------------ */

// Modeles de titres EffectCraft (modeles/titres) ; le titre simple est fait au besoin
function titleOptions(select) {
  const titles = (EVD.studio && EVD.studio.titles) || [];
  const items = [{ id: 'titre_simple', name: 'Titre simple' }].concat(titles.filter((t) => t.id !== 'titre_simple'));
  const current = select.value;
  select.innerHTML = items.map((t) => '<option value="' + escapeHtml(t.id) + '">' + escapeHtml(t.name) + '</option>').join('');
  if (items.some((t) => t.id === current)) select.value = current;
}

function renderMontage() {
  const st = EVD.studio || {};
  const e = EVD.event || {};
  // Titres du projet : preremplis une fois par evenement, puis laisses a la main du monteur
  if (!EVD.titled) {
    $('#mt-title').value = e.names || '';
    $('#mt-subtitle').value = frenchDate(e.date || '');
    EVD.titled = true;
  }
  titleOptions($('#mt-title-model'));
  $('#mt-filmcraft').disabled = !st.filmcraft;
  if (!st.filmcraft) $('#mt-filmcraft').checked = false;
  $('#mt-info').className = 'tiny err';
  $('#mt-info').textContent = !st.effectcraft ? 'EffectCraft n’est pas installé : générique et clips 3D impossibles.' : '';

  // Generique
  const moments = (EVD.moments && EVD.moments.moments) || [];
  const kept = EVD.clips.filter((c) => c.kept && c.analyzed).length;
  $('#gen-moments').className = 'tiny' + (moments.length || kept ? '' : ' err');
  $('#gen-moments').textContent = moments.length
    ? plural(moments.length, 'moment') + ' fort' + (moments.length > 1 ? 's' : '') + ' choisi' +
      (moments.length > 1 ? 's' : '') + ' dans l’onglet Vidéo.'
    : kept ? 'Moments forts pas encore cherchés : le générique les cherchera d’abord (6 moments).'
      : 'Aucun rush gardé : commencez par l’onglet Vidéo.';
  $('#gen-run').disabled = !st.effectcraft || !(moments.length || kept);

  // Clip 3D : animation de la bibliotheque + photo cochee dans la partie Photo
  const list = st.animations || [];
  const current = $('#st-animation').value;
  $('#st-animation').innerHTML = list.map((a) => '<option value="' + escapeHtml(a.id) + '">' +
    escapeHtml(a.titre + (a.duree ? ' — ' + Math.round(a.duree) + ' s' : '')) + '</option>').join('');
  if (list.some((a) => a.id === current)) $('#st-animation').value = current;
  studioPreview();
  const chosen = EVD.photos.filter((p) => p.montage);
  if (!chosen.some((p) => p.rel === EVD.photo)) EVD.photo = chosen.length ? chosen[0].rel : '';
  $('#st-photos').innerHTML = !chosen.length
    ? '<p class="tiny err">Aucune photo cochée ★ : choisissez-en dans l’onglet Photo.</p>'
    : chosen.map((p) => '<button class="st-photo' + (p.rel === EVD.photo ? ' active' : '') + '" data-rel="' +
      escapeHtml(p.rel) + '" title="' + escapeHtml(p.name) + (p.box ? ' (cadre des mariés tracé)' : '') + '">' +
      (p.thumb ? '<img loading="lazy" src="' + fileUrl(p.thumb) + '" alt="">' : escapeHtml(p.name)) +
      (p.box ? '<span>▭</span>' : '') + '</button>').join('');
  const ready = !!(st.detourage && st.effectcraft && list.length && EVD.photo);
  $('#st-run').disabled = !ready;
  const info = $('#st-info');
  info.className = 'tiny' + (ready ? ' muted' : ' err');
  info.textContent = !st.detourage ? 'Outil de détourage absent : ./scripts/build_native.sh'
    : !list.length ? 'Aucune animation dans la bibliothèque : demandez-en à l’atelier (scripts/installer_animations.py)'
      : plural(list.length, 'animation') + ' dans la bibliothèque';

  // Rendus
  $('#mt-renders').innerHTML = !EVD.renders.length
    ? '<p class="tiny muted">Pas encore de rendu : générique, clips 3D, détourages et sous-titres arriveront ici (06_Rendus).</p>'
    : EVD.renders.map((r) => {
      const video = /\.(mp4|mov|m4v)$/i.test(r.name);
      return '<div class="mt-render"><span class="ev-type">' + escapeHtml(r.kind) + '</span>' +
        (video ? '<button class="btn btn-mini mt-play" data-path="' + escapeHtml(r.path) + '">▶</button>' : '') +
        '<span dir="auto">' + escapeHtml(r.name) + '</span><span class="muted tiny">' + fmtSize(r.size) + '</span></div>';
    }).join('');
  $('#evd-tab-montage').textContent = EVD.renders.length ? EVD.renders.length : '';
}

function montageTitles() {
  return { title: $('#mt-title').value.trim(), subtitle: $('#mt-subtitle').value.trim(),
    title_model: $('#mt-title-model').value, filmcraft: $('#mt-filmcraft').checked };
}

$('#gen-run').addEventListener('click', () => {
  derushJob('/api/events/studio', Object.assign({ recipe: 'generique' }, montageTitles()),
    (r) => toast('Générique prêt : ' + r.path));
});

$('#st-photos').addEventListener('click', (ev) => {
  const b = ev.target.closest('.st-photo');
  if (!b) return;
  EVD.photo = b.dataset.rel;
  renderMontage();
});

$('#st-run').addEventListener('click', () => {
  if (!EVD.photo) return;
  toast('Clip 3D lancé en tâche de fond : il arrivera dans 06_Rendus/Clips_3D');
  derushJob('/api/events/studio', Object.assign({ recipe: 'clip-drone', rel: EVD.photo,
    animation: $('#st-animation').value }, montageTitles()), (r) => toast('Clip 3D prêt : ' + r.path));
});

$('#mt-renders').addEventListener('click', (ev) => {
  const b = ev.target.closest('.mt-play');
  if (!b) return;
  const player = $('#mt-player');
  player.src = fileUrl(b.dataset.path);
  $('#mt-player-box').classList.remove('hidden');
  player.play().catch(() => {});
});

function studioPreview() {
  const a = ((EVD.studio && EVD.studio.animations) || []).find((x) => x.id === $('#st-animation').value);
  const img = $('#st-vignette');
  img.classList.toggle('hidden', !a);
  if (a) img.src = fileUrl(a.vignette);
}

$('#st-animation').addEventListener('change', studioPreview);

function frenchDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return '';
  const months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
    'octobre', 'novembre', 'décembre'];
  return (+m[3]) + ' ' + months[+m[2] - 1] + ' ' + m[1];
}

// Dans la fenetre d'une photo : choisie pour le montage, et cadre des maries garde pour le clip 3D
$('#fx-montage').addEventListener('change', () => {
  if (!FX.photo) return;
  setPhoto(FX.photo.rel, { montage: $('#fx-montage').checked })
    .catch((err) => { toast(err.message, true); $('#fx-montage').checked = !$('#fx-montage').checked; });
});

function keepCoupleBox() {
  if (!FX.photo || (fxSpec() || {}).needs_box) return;          // cadre d'un objet a effacer : pas garde
  const box = FX.box;
  const before = FX.photo.box;
  if (JSON.stringify(box || null) === JSON.stringify(before || null)) return;
  setPhoto(FX.photo.rel, { box: box }).catch((err) => toast(err.message, true));
}

function fxSpec() {
  return EVD.effects.find((e) => e.key === FX.effect);
}

function closeFx() {
  if (FX.busy) return;
  $('#fx').classList.add('hidden');
  $('#fx-img').removeAttribute('src');
  $('#fx-video').pause();
  $('#fx-video').removeAttribute('src');
  FX.photo = null;
}

function fxRender() {
  const p = FX.photo;
  if (!p) return;
  const showResult = FX.view === 'result' && FX.result;
  const isVideo = !!(FX.result && FX.result.video);
  const src = showResult ? fileUrl(FX.result.path) + '&t=' + FX.result.stamp
    : (p.viewable ? fileUrl(p.path) : (p.thumb ? fileUrl(p.thumb) : ''));
  // Photo animee en 3D : le resultat est une video, jouee en boucle dans l'apercu
  const img = $('#fx-img');
  const video = $('#fx-video');
  const playVideo = showResult && isVideo;
  img.classList.toggle('hidden', playVideo);
  video.classList.toggle('hidden', !playVideo);
  if (playVideo) {
    if (video.getAttribute('src') !== src) { video.setAttribute('src', src); video.play().catch(() => {}); }
  } else {
    video.pause();
    if (img.getAttribute('src') !== src) img.setAttribute('src', src);
  }
  $$('#fx .fx-view .filter[data-view]').forEach((b) => {
    b.classList.toggle('active', b.dataset.view === FX.view);
    if (b.dataset.view === 'result') b.disabled = !FX.result;
  });
  $$('#fx-effects .filter').forEach((b) => b.classList.toggle('active', b.dataset.effect === FX.effect));
  $('#fx-stage').classList.toggle('framing', FX.framing && !showResult);
  $('#fx-frame').classList.toggle('active', FX.framing);
  const erase = !!(fxSpec() || {}).needs_box;
  $('#fx-frame-label').textContent = erase ? 'Désignez l’objet à effacer :' : 'La robe ou la traîne est coupée ?';
  $('#fx-frame').textContent = FX.box ? '✕ Retirer le cadre'
    : (FX.framing ? 'Tracez le cadre sur la photo…'
      : (erase ? '▭ Tracer un cadre autour de l’objet' : '▭ Tracer un cadre autour des mariés'));
  $('#fx-frame').disabled = FX.busy || (!erase && !STATUS.photocraft);
  $('#fx-frame-hint').textContent = erase
    ? 'Glissez sur la photo pour entourer l’objet ou la personne à effacer, au plus près. Le décor est reconstitué à sa place.'
    : 'Glissez sur la photo pour entourer les mariés, robe et traîne comprises. PhotoCraft complète alors le détourage.';
  $('#fx-frame-hint').classList.toggle('hidden', !FX.framing);
  const box = $('#fx-box');
  const b = FX.drag || (FX.plan ? null : FX.box);
  box.classList.toggle('hidden', !b || !!showResult);
  $('#fx-boxes').innerHTML = (!FX.plan || showResult) ? '' : Object.keys(FX.boxes).map((i) => {
    const r = FX.boxes[i];
    return '<div class="fx-box" style="left:' + r[0] * 100 + '%;top:' + r[1] * 100 + '%;width:' + r[2] * 100 +
      '%;height:' + r[3] * 100 + '%"><span>' + (+i + 1) + '</span></div>';
  }).join('');
  fxRenderPlan();
  if (b) {
    box.style.left = (b[0] * 100) + '%';
    box.style.top = (b[1] * 100) + '%';
    box.style.width = (b[2] * 100) + '%';
    box.style.height = (b[3] * 100) + '%';
  }
  $('#fx-run').disabled = FX.busy || !STATUS.effects;
  $('#fx-run').textContent = FX.busy ? 'Calcul en cours…' : 'Calculer l’aperçu';
  $('#fx-save').disabled = FX.busy || !FX.result || !!FX.saved;
  $('#fx-save').textContent = FX.saved ? 'Enregistré ✓' : 'Enregistrer dans Rendus';
  $('#fx-photocraft').disabled = !STATUS.photocraft || FX.busy || isVideo;
  $('#fx-save').textContent = FX.saved ? 'Enregistré ✓'
    : (isVideo ? 'Enregistrer dans Rendus (Photos_animees)' : 'Enregistrer dans Rendus');
  $('#fx-photocraft').textContent = FX.result ? 'Affiner dans PhotoCraft (PSD à calques)' : 'Ouvrir la photo dans PhotoCraft';
  $('#fx-photocraft').title = FX.result
    ? 'Crée un PSD : la photo originale + le calque de l’effet avec un masque modifiable au pinceau'
    : 'Ouvre la photo originale dans PhotoCraft';
}

function fxInvalidate() {
  FX.result = null;
  FX.saved = '';
  FX.view = 'orig';
}

function fxPoint(ev) {
  const r = $('#fx-img').getBoundingClientRect();
  return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)),
    Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))];
}

$('#fx-stage').addEventListener('mousedown', (ev) => {
  if (!FX.framing || FX.view !== 'orig' || FX.busy) return;
  ev.preventDefault();
  const start = fxPoint(ev);
  FX.drag = [start[0], start[1], 0, 0];
  const move = (e) => {
    const pt = fxPoint(e);
    FX.drag = [Math.min(start[0], pt[0]), Math.min(start[1], pt[1]),
      Math.abs(pt[0] - start[0]), Math.abs(pt[1] - start[1])];
    fxRender();
  };
  const up = () => {
    window.removeEventListener('mousemove', move);
    window.removeEventListener('mouseup', up);
    const d = FX.drag;
    FX.drag = null;
    if (FX.target !== null) {
      if (d && d[2] > 0.01 && d[3] > 0.01) { FX.boxes[FX.target] = d; FX.result = null; FX.saved = ''; }
      FX.target = null;
      FX.framing = false;
    } else if (d && d[2] > 0.03 && d[3] > 0.03) {
      FX.box = d;
      FX.framing = false;
      fxInvalidate();
      keepCoupleBox();
    }
    fxRender();
  };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
});

$('#fx-frame').addEventListener('click', () => {
  if (FX.busy) return;
  if (FX.box) { FX.box = null; FX.framing = false; fxInvalidate(); keepCoupleBox(); } else { FX.framing = !FX.framing; FX.view = 'orig'; }
  fxRender();
});

['#fx-enhance', '#fx-couple'].forEach((sel) => $(sel).addEventListener('change', () => {
  if (FX.busy) return;
  fxInvalidate();          // l'apercu calcule ne correspond plus a la case
  fxRender();
}));

$('#fx-effects').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-effect]');
  if (!b || b.disabled || FX.busy || b.dataset.effect === FX.effect) return;
  const wasErase = !!(fxSpec() || {}).needs_box;
  FX.effect = b.dataset.effect;
  // Le cadre n'a pas le meme sens : autour des maries (les garder) ou d'un objet (l'effacer)
  if (wasErase !== !!(fxSpec() || {}).needs_box) { FX.box = null; FX.framing = false; }
  fxInvalidate();
  fxRender();
});

/* Fond de l'apercu (clair par defaut, comme PhotoCraft), garde d'une fois sur l'autre */
function fxBackground(bg) {
  const stage = $('#fx-stage');
  stage.classList.toggle('bg-light', bg === 'light');
  stage.classList.toggle('bg-white', bg === 'white');
  $$('#fx [data-bg]').forEach((b) => b.classList.toggle('active', b.dataset.bg === bg));
  try { localStorage.setItem('rexo-fx-bg', bg); } catch (e) { /* stockage indisponible */ }
}
$$('#fx [data-bg]').forEach((b) => b.addEventListener('click', () => fxBackground(b.dataset.bg)));
let savedBg = 'light';
try { savedBg = localStorage.getItem('rexo-fx-bg') || 'light'; } catch (e) { /* stockage indisponible */ }
fxBackground(savedBg);

$$('#fx .fx-view .filter[data-view]').forEach((b) => b.addEventListener('click', () => {
  if (b.disabled) return;
  FX.view = b.dataset.view;
  fxRender();
}));

$('#fx-run').addEventListener('click', async () => {
  if (FX.busy || !FX.photo) return;
  const info = $('#fx-info');
  const erase = !!(fxSpec() || {}).needs_box;
  if (erase && !FX.box) {
    info.className = 'tiny err';
    info.textContent = 'Tracez d’abord un cadre autour de l’objet à effacer.';
    FX.framing = true;
    fxRender();
    return;
  }
  FX.busy = true;
  FX.framing = false;
  info.className = 'tiny muted';
  info.textContent = erase ? 'MobileSAM sélectionne l’objet, MI-GAN reconstitue le décor…'
    : (FX.box ? 'Vision + PhotoCraft (sélection dans le cadre)…' : 'Vision : détourage des personnes…');
  fxRender();
  try {
    const r = await post('/api/events/effect', { id: EVD.id, rel: FX.photo.rel, effect: FX.effect, box: FX.box,
      enhance: $('#fx-enhance').checked, couple: $('#fx-couple').checked });
    FX.result = Object.assign(r, { stamp: Date.now() });
    FX.saved = '';
    FX.view = 'result';
    const secs = (r.ms / 1000).toFixed(1).replace('.', ',');
    if (erase) {
      info.className = 'tiny muted';
      info.textContent = 'Objet effacé en ' + secs + ' s. Comparez avec l’original : si le décor reconstitué ' +
        'se voit, resserrez le cadre et recalculez, ou retouchez dans PhotoCraft.';
    } else if (r.coverage < 0.01) {
      info.className = 'tiny err';
      info.textContent = 'Personne n’a été trouvé sur cette photo : effet non conseillé.';
    } else {
      info.className = 'tiny muted';
      info.textContent = 'Aperçu calculé en ' + secs + ' s' + (r.framed ? ' (avec le cadre PhotoCraft)' : '') +
        '. Vérifiez les contours, puis enregistrez.' + (r.framed ? '' : ' Robe coupée : tracez un cadre et recalculez.');
    }
  } catch (err) {
    info.className = 'tiny err';
    info.textContent = err.message;
  }
  FX.busy = false;
  fxRender();
});

$('#fx-save').addEventListener('click', async () => {
  if (!FX.result || FX.busy) return;
  try {
    const r = FX.result.kind === 'assistant'
      ? await post('/api/events/assistant/save', { id: EVD.id, rel: FX.photo.rel })
      : await post('/api/events/effect/save',
        { id: EVD.id, rel: FX.photo.rel, effect: FX.result.effect, framed: FX.result.framed,
          enhanced: !!FX.result.enhanced, couple: !!FX.result.couple });
    FX.saved = r.rel;
    toast('Enregistré : ' + r.rel);
    loadDerush();
  } catch (err) { toast(err.message, true); }
  fxRender();
});

$('#fx-photocraft').addEventListener('click', async () => {
  if (!FX.photo || FX.busy) return;
  // Apres un effet : PSD a calques (original + calque d'effet au masque modifiable)
  const body = { id: EVD.id, rel: FX.photo.rel };
  if (FX.result && FX.result.kind === 'assistant') body.assistant = true;
  else if (FX.result) {
    Object.assign(body, { effect: FX.result.effect, framed: FX.result.framed, enhanced: !!FX.result.enhanced,
      couple: !!FX.result.couple });
  }
  const btn = $('#fx-photocraft');
  btn.disabled = true;
  btn.textContent = FX.result ? 'Préparation du PSD…' : 'Ouverture…';
  try {
    const r = await post('/api/events/photocraft', body);
    toast(FX.result ? 'PSD à calques ouvert dans PhotoCraft : ' + r.rel.split('/').pop() : 'Ouverture dans PhotoCraft…');
    if (FX.result) loadDerush();
  } catch (err) { toast(err.message, true); }
  btn.disabled = false;
  fxRender();
});

/* -- assistant dans la fenetre d'une photo -- */

function planHtml(plan, boxes, withBoxes) {
  if (!plan.faisable) return '<p class="msg err">' + escapeHtml(plan.message) + '</p>';
  return '<p class="msg">' + escapeHtml(plan.message) + ' <span class="tiny">(' +
    String(plan.secondes).replace('.', ',') + ' s)</span></p><ol>' +
    plan.etapes.map((s, i) => '<li class="' + (boxes[i] ? 'ok' : '') + '">' + escapeHtml(stepLabel(s)) +
      (s.cadre && withBoxes ? '<button class="btn btn-mini" data-box="' + i + '">' +
        (boxes[i] ? '✓ cadre (refaire)' : '▭ tracer le cadre') + '</button>' : '') + '</li>').join('') + '</ol>';
}

function fxRenderPlan() {
  const box = $('#fx-plan');
  if (!FX.plan) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  const missing = FX.plan.etapes.some((s, i) => s.cadre && !FX.boxes[i]);
  box.innerHTML = planHtml(FX.plan, FX.boxes, true) + (FX.plan.faisable
    ? '<button class="btn btn-primary" id="fx-plan-run"' + (missing || FX.busy ? ' disabled' : '') + '>' +
      (FX.busy ? 'Exécution…' : missing ? 'Tracez les cadres demandés' : 'Exécuter le plan') + '</button>' : '');
  if (FX.target !== null) {
    $('#fx-frame-hint').classList.remove('hidden');
    $('#fx-frame-hint').textContent = 'Étape ' + (FX.target + 1) + ' : glissez sur la photo pour entourer ' +
      (FX.plan.etapes[FX.target].cible || 'les mariés, robe et traîne comprises') + '.';
  }
}

$('#fx-ask-go').addEventListener('click', async () => {
  const text = $('#fx-ask').value.trim();
  if (!text || FX.busy) return;
  const info = $('#fx-info');
  info.className = 'tiny muted';
  info.textContent = 'L’IA lit la consigne…';
  $('#fx-ask-go').disabled = true;
  try {
    FX.plan = await post('/api/events/assistant/plan', { text: text });
    FX.boxes = {};
    FX.target = null;
    if (FX.plan.maries_seulement) $('#fx-couple').checked = true;   // « garde seulement les mariés »
    info.textContent = '';
  } catch (err) {
    info.className = 'tiny err';
    info.textContent = err.message;
  }
  $('#fx-ask-go').disabled = false;
  fxRender();
});

$('#fx-plan').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-box]');
  if (b && !FX.busy) {
    FX.target = +b.dataset.box;
    FX.framing = true;
    FX.view = 'orig';
    fxRender();
    return;
  }
  if (ev.target.id !== 'fx-plan-run' || FX.busy) return;
  const info = $('#fx-info');
  FX.busy = true;
  info.className = 'tiny muted';
  info.textContent = 'Exécution en tâche de fond…';
  fxRender();
  const fail = (msg) => { FX.busy = false; info.className = 'tiny err'; info.textContent = msg; fxRender(); };
  post('/api/events/assistant/run', { id: EVD.id, rel: FX.photo.rel, steps: FX.plan.etapes, boxes: FX.boxes,
    enhance: $('#fx-enhance').checked, couple: $('#fx-couple').checked })
    .then((data) => followJob(data.job_id, {
      log: (m) => { info.textContent = m; },
      done: (r) => {
        FX.busy = false;
        FX.result = { path: r.path, stamp: Date.now(), kind: 'assistant' };
        FX.saved = '';
        FX.view = 'result';
        info.className = 'tiny muted';
        info.textContent = 'Plan exécuté en ' + String(r.secondes).replace('.', ',') +
          ' s. Comparez avec l’original, puis enregistrez.';
        fxRender();
      },
      error: fail,
    }))
    .catch((err) => fail(err.message));
});

/* -- assistant pour toute la serie -- */

const SERIES = { plan: null };

$('#evd-ask-go').addEventListener('click', async () => {
  const text = $('#evd-ask').value.trim();
  if (!text) return;
  const box = $('#evd-plan');
  box.classList.remove('hidden');
  box.innerHTML = '<p class="msg">L’IA lit la consigne…</p>';
  try {
    SERIES.plan = await post('/api/events/assistant/plan', { text: text });
  } catch (err) {
    box.innerHTML = '<p class="msg err">' + escapeHtml(err.message) + '</p>';
    return;
  }
  const plan = SERIES.plan;
  if (plan.maries_seulement) $('#evd-couple').checked = true;
  const n = EVD.photos.length;
  const needsBox = plan.faisable && plan.etapes.some((s) => s.cadre);
  box.innerHTML = planHtml(plan, {}, false) + (!plan.faisable ? ''
    : needsBox ? '<p class="msg err">Ce plan demande de tracer un cadre : ouvrez une photo (✨) pour l’appliquer.</p>'
      : '<button class="btn btn-primary" id="evd-plan-run"' + (n ? '' : ' disabled') + '>Appliquer à ' +
        plural(n, 'photo') + '</button> <span class="tiny muted">Résultats dans 06_Rendus/Photos_effets, originaux intacts.</span>');
});

$('#evd-ask').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#evd-ask-go').click(); });

$('#evd-plan').addEventListener('click', (ev) => {
  if (ev.target.id !== 'evd-plan-run' || !SERIES.plan) return;
  derushJob('/api/events/assistant/run', { all: true, steps: SERIES.plan.etapes,
    enhance: $('#evd-enhance').checked, couple: $('#evd-couple').checked }, (r) => {
    toast(plural(r.done, 'photo') + ' traitée' + (r.done > 1 ? 's' : '') + ' → ' + r.folder +
      (r.failed && r.failed.length ? ' (' + r.failed.length + ' en échec)' : ''), r.failed && r.failed.length > 0);
    $('#evd-plan').classList.add('hidden');
  });
});

$('#fx-close').addEventListener('click', closeFx);
$('#fx').addEventListener('click', (ev) => { if (ev.target.id === 'fx') closeFx(); });
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && !$('#fx').classList.contains('hidden')) closeFx();
});

/* ------------------------------------------------------------------ */

loadStatus();
setInterval(loadStatus, 15000);
loadEvents();

/* -- chaine de production : detourage video d'un rush -- */

const DV = { clip: null, point: null };

$('#evd-clips').addEventListener('click', (ev) => {
  const b = ev.target.closest('.dv-open');
  if (!b) return;
  ev.stopPropagation();
  const c = EVD.clips.find((x) => x.rel === b.dataset.rel);
  if (!c) return;
  DV.clip = c;
  DV.point = null;
  DV.box = null;
  DV.drag = null;
  $('#dv-box').classList.add('hidden');
  // La vignette du rush est prise a la moitie, au plus a 3 s : le suivi part de la
  DV.start = Math.min((c.duration || 0) / 2, 3);
  $('#dv-name').textContent = c.name;
  $('#dv-at').textContent = String(Math.round(DV.start * 10) / 10).replace('.', ',') + ' s';
  $('#dv-img').src = fileUrl(c.thumb);
  $('#dv-dot').classList.add('hidden');
  $('#dv-run').disabled = true;
  const st = EVD.studio;
  $('#dv-filmcraft').disabled = !(st && st.filmcraft);
  $('#dv-filmcraft').checked = !!(st && st.filmcraft);
  $('#dv').classList.remove('hidden');
}, true);

// Clic : la personne ; glisser : un cadre autour d'elle seule (laisse dehors un voisin colle)
function dvPos(ev) {
  const r = $('#dv-img').getBoundingClientRect();
  return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)),
    Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))];
}

function dvRender() {
  const dot = $('#dv-dot');
  dot.classList.toggle('hidden', !DV.point);
  if (DV.point) { dot.style.left = (100 * DV.point[0]) + '%'; dot.style.top = (100 * DV.point[1]) + '%'; }
  const b = DV.drag ? DV.drag.box : DV.box;
  const el = $('#dv-box');
  el.classList.toggle('hidden', !b);
  if (b) {
    el.style.left = (100 * b[0]) + '%'; el.style.top = (100 * b[1]) + '%';
    el.style.width = (100 * b[2]) + '%'; el.style.height = (100 * b[3]) + '%';
  }
  $('#dv-run').disabled = !(DV.point || DV.box) || !(EVD.studio && EVD.studio.effectcraft);
}

$('#dv-stage').addEventListener('mousedown', (ev) => {
  ev.preventDefault();
  DV.drag = { from: dvPos(ev), box: null };
});

document.addEventListener('mousemove', (ev) => {
  if (!DV.drag) return;
  const [x, y] = dvPos(ev);
  const [x0, y0] = DV.drag.from;
  DV.drag.box = [Math.min(x, x0), Math.min(y, y0), Math.abs(x - x0), Math.abs(y - y0)];
  dvRender();
});

document.addEventListener('mouseup', (ev) => {
  if (!DV.drag) return;
  const b = DV.drag.box;
  if (b && b[2] > 0.03 && b[3] > 0.03) {
    DV.box = b;                     // cadre trace
  } else {
    DV.point = dvPos(ev);           // simple clic
  }
  DV.drag = null;
  dvRender();
});

function closeDv() { $('#dv').classList.add('hidden'); }
$('#dv-close').addEventListener('click', closeDv);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#dv').classList.contains('hidden')) closeDv(); });

$('#dv-run').addEventListener('click', () => {
  if (!DV.clip || !(DV.point || DV.box)) return;
  const body = { recipe: 'detour-video', rel: DV.clip.rel, point: DV.point, box: DV.box, start: DV.start,
    duration: +$('#dv-duration').value, filmcraft: $('#dv-filmcraft').checked };
  closeDv();
  toast('Détourage vidéo lancé en tâche de fond : il arrivera dans 06_Rendus/Videos_detourees');
  derushJob('/api/events/studio', body);
});
