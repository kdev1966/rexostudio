/* Rexo Studio - interface web locale (vanilla JS, aucune dependance) */
'use strict';

const S = {
  project: null,
  plan: [],
  candidates: [],
  busy: false,
  es: null,
  filter: 'all',
};

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

function setProgress(value, step) {
  $('#job-bar-fill').style.width = Math.round((value || 0) * 100) + '%';
  $('#job-label').textContent = (step || '') +
    (value !== undefined ? ' — ' + Math.round((value || 0) * 100) + ' %' : '');
}

function addLog(line) {
  const box = $('#job-log');
  box.textContent += line + '\n';
  box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* Onglets                                                             */
/* ------------------------------------------------------------------ */

function showTab(name) {
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tabpane').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
}

$$('.tab').forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.tab)));

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

    const sel = $('#whisper-model');
    const LABELS = { tiny: 'Très rapide', base: 'Rapide', small: 'Précise', medium: 'Très précise' };
    // "Automatique" par defaut : le serveur choisit le modele selon la
    // langue (small pour l'arabe). Le choix fait est conserve : ce menu
    // est reconstruit a chaque rafraichissement de l'etat (15 s).
    const current = sel.value;
    sel.innerHTML = '<option value="">Automatique (selon la langue)</option>' +
      s.whisper_models.map((m) => '<option value="' + m.name + '">' +
        (LABELS[m.name] || m.name) + ' (' + m.name + ')</option>').join('');
    sel.value = s.whisper_models.some((m) => m.name === current) ? current : '';
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
/* Televersement                                                       */
/* ------------------------------------------------------------------ */

const dz = $('#dropzone');
dz.addEventListener('click', () => $('#fileInput').click());
$('#browseBtn').addEventListener('click', (e) => { e.stopPropagation(); $('#fileInput').click(); });
['dragenter', 'dragover'].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('drag'); }));
['dragleave', 'drop'].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('drag'); }));
dz.addEventListener('drop', (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) upload(f);
});
$('#fileInput').addEventListener('change', (e) => {
  const f = e.target.files && e.target.files[0];
  if (f) upload(f);
  e.target.value = '';
});

async function upload(file) {
  if (S.busy) { toast('Un traitement est en cours', true); return; }
  // Meme video deja importee (meme nom, meme taille) : on rouvre son projet
  // au lieu d'en creer une copie.
  try {
    const list = (await api('/api/projects')).projects || [];
    const same = list.find((p) => p.name === file.name && p.size === file.size && !p.media_missing);
    if (same) {
      await openProject(same.id);
      toast('Cette vidéo est déjà dans vos projets : projet rouvert');
      return;
    }
  } catch (e) { /* liste indisponible : on televerse */ }

  $('#upload-progress').classList.remove('hidden');
  $('#upload-bar-fill').style.width = '0%';
  $('#upload-label').textContent = 'Import de ' + file.name + '…';
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const pct = (e.loaded / e.total) * 100;
      $('#upload-bar-fill').style.width = pct + '%';
      $('#upload-label').textContent = 'Import — ' + Math.round(pct) + ' % (' + fmtSize(e.loaded) + ')';
    }
  };
  xhr.onload = () => {
    let data = null;
    try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
    if (xhr.status >= 200 && xhr.status < 300 && data && data.project) {
      $('#upload-label').textContent = 'Importée : ' + data.size_human;
      setTimeout(() => $('#upload-progress').classList.add('hidden'), 1200);
      setProject(data.project);
      loadProjects();
      toast('Vidéo prête : cliquez sur « Préparer le montage »');
    } else {
      $('#upload-progress').classList.add('hidden');
      toast((data && data.error) || 'Échec de l’import', true);
    }
  };
  xhr.onerror = () => {
    $('#upload-progress').classList.add('hidden');
    toast('Erreur réseau pendant l’import', true);
  };
  xhr.send(file);
}

/* ------------------------------------------------------------------ */
/* Projets                                                             */
/* ------------------------------------------------------------------ */

const LAST_PROJECT_KEY = 'montagia.lastProject';

function rememberProject(id) {
  try {
    if (id) localStorage.setItem(LAST_PROJECT_KEY, id);
    else localStorage.removeItem(LAST_PROJECT_KEY);
  } catch (e) { /* stockage indisponible */ }
}

function lastProject() {
  try { return localStorage.getItem(LAST_PROJECT_KEY); } catch (e) { return null; }
}

async function loadProjects() {
  let list = [];
  try { list = (await api('/api/projects')).projects || []; } catch (e) { return; }
  $('#recent-box').classList.toggle('hidden', !list.length);
  $('#recent-list').innerHTML = list.slice(0, 20).map((p) => {
    const badges = [fmtTime(p.duration)];
    if (p.planned) badges.push('montage prêt');
    else if (p.transcribed) badges.push('transcrit');
    if (p.exports) badges.push(p.exports + ' export' + (p.exports > 1 ? 's' : ''));
    const active = S.project && S.project.id === p.id ? ' active' : '';
    return '<div class="recent-row">' +
      '<button class="recent-item' + active + '" data-project="' + escapeHtml(p.id) + '">' +
      '<span class="rn">' + escapeHtml(p.name) + '</span>' +
      (p.media_missing ? '<span class="rb warn">vidéo introuvable</span>'
                       : '<span class="rb">' + escapeHtml(badges.join(' · ')) + '</span>') +
      '</button>' +
      '<button class="del" data-delete="' + escapeHtml(p.id) + '" data-name="' + escapeHtml(p.name) +
      '" title="Supprimer ce projet">&times;</button></div>';
  }).join('');
  $$('#recent-list [data-project]').forEach((b) =>
    b.addEventListener('click', () => openProject(b.dataset.project)));
  $$('#recent-list [data-delete]').forEach((b) =>
    b.addEventListener('click', () => deleteProject(b.dataset.delete, b.dataset.name)));
}

async function deleteProject(id, name) {
  if (S.busy) { toast('Un traitement est en cours', true); return; }
  if (!confirm('Supprimer le projet « ' + name + ' » ?\n' +
               'La vidéo importée est effacée ; vos exports sont gardés.')) return;
  try {
    await post('/api/project/delete', { project_id: id });
  } catch (e) { toast(e.message, true); return; }
  if (S.project && S.project.id === id) {
    rememberProject(null);
    location.reload();
    return;
  }
  toast('Projet supprimé');
  loadProjects();
}

async function openProject(id) {
  if (S.busy) { toast('Une opération est en cours', true); return; }
  let proj;
  try {
    proj = (await api('/api/project?id=' + encodeURIComponent(id))).project;
  } catch (e) { toast(e.message, true); return; }
  setProject(proj);
  loadProjects();
  if (proj.media_missing) toast('Le fichier vidéo de ce projet est introuvable', true);
}

function setProject(proj) {
  S.project = proj;
  rememberProject(proj.id);
  showMedia();
  loadPlayer();
  applyProject();
}

function showMedia() {
  const p = S.project;
  const i = p.info || {};
  $('#media-info').classList.remove('hidden');
  $('#media-info').innerHTML =
    '<dl class="info-grid">' +
    '<dt>Fichier</dt><dd>' + escapeHtml(p.name) + '</dd>' +
    '<dt>Durée</dt><dd>' + fmtDuration(i.duration) + '</dd>' +
    '<dt>Image</dt><dd>' + (i.width || '?') + '×' + (i.height || '?') +
      (i.fps ? ' · ' + Math.round(i.fps) + ' images/s' : '') + '</dd>' +
    '<dt>Taille</dt><dd>' + fmtSize(i.size || 0) + (i.acodec ? '' : ' · <span class="warn">sans son</span>') + '</dd>' +
    '</dl>';
}

async function refreshProject() {
  if (!S.project) return;
  try {
    S.project = (await api('/api/project?id=' + S.project.id)).project;
    applyProject();
  } catch (e) { /* ignore */ }
}

function applyProject() {
  const p = S.project;
  S.plan = p.plan || [];
  S.candidates = p.candidates || [];
  const ok = !p.media_missing;
  const hasTrans = (p.transcript_segments || []).length > 0;
  $('#btn-prepare').disabled = !ok;
  $('#btn-prepare').textContent = S.plan.length ? 'Refaire le montage automatique' : 'Préparer le montage';
  $('#btn-analyze').disabled = !ok;
  $('#btn-transcribe').disabled = !ok;
  $('#btn-plan').disabled = !hasTrans;
  $('#btn-subs').disabled = !hasTrans;
  renderPlan();
  renderIa();
  renderExports();
}

/* ------------------------------------------------------------------ */
/* Traitements (SSE)                                                   */
/* ------------------------------------------------------------------ */

function runJob(url, body, onDone) {
  if (S.busy) { toast('Un traitement est déjà en cours', true); return; }
  S.busy = true;
  document.body.classList.add('busy');
  $('#job-box').classList.remove('hidden');
  $('#job-log').textContent = '';
  setProgress(0, 'Démarrage');

  const finish = () => { S.busy = false; document.body.classList.remove('busy'); };
  post(url, body).then((data) => {
    const es = new EventSource('/api/jobs/' + data.job_id + '/events');
    S.es = es;
    es.onmessage = (ev) => {
      let e;
      try { e = JSON.parse(ev.data); } catch (err) { return; }
      if (e.type === 'snapshot') {
        applyJobState(e.job);
      } else if (e.type === 'progress') {
        setProgress(e.progress, e.step);
      } else if (e.type === 'log') {
        addLog(e.message);
      } else if (e.type === 'done') {
        setProgress(1, 'Terminé');
        es.close();
        finish();
        refreshProject().then(() => { loadProjects(); if (onDone) onDone(e.result); });
      } else if (e.type === 'error') {
        addLog('ERREUR : ' + e.error);
        setProgress(0, 'Échec');
        toast(e.error, true);
        es.close();
        finish();
      }
    };
    es.onerror = () => { es.close(); finish(); };
  }).catch((err) => {
    toast(err.message, true);
    finish();
  });
}

function applyJobState(job) {
  if (!job) return;
  setProgress(job.progress, job.step);
  if (job.log) {
    const box = $('#job-log');
    box.textContent = job.log.join('\n') + '\n';
    box.scrollTop = box.scrollHeight;
  }
}

function planOptions() {
  return {
    project_id: S.project.id,
    model: $('#whisper-model').value || null,
    language: $('#whisper-lang').value,
    instruction: $('#plan-instruction').value,
    style: $('#plan-style').value,
  };
}

function afterPlan() {
  showTab('plan');
  const n = countToCheck();
  toast(n ? 'Montage prêt : ' + n + ' passage' + (n > 1 ? 's' : '') + ' à vérifier'
          : 'Montage prêt');
}

$('#btn-prepare').addEventListener('click', () => runJob('/api/prepare', planOptions(), afterPlan));
$('#btn-analyze').addEventListener('click', () => runJob('/api/analyze', planOptions()));
$('#btn-transcribe').addEventListener('click', () => runJob('/api/transcribe', planOptions()));
$('#btn-plan').addEventListener('click', () => runJob('/api/plan', planOptions(), afterPlan));

$('#btn-pack').addEventListener('click', () => runJob('/api/pack', { project_id: S.project.id }));
$('#btn-summary').addEventListener('click', () => runJob('/api/summary', { project_id: S.project.id }));
$('#btn-trailer').addEventListener('click', () => {
  runJob('/api/trailer', {
    project_id: S.project.id,
    target_seconds: Number($('#trailer-target').value) || 30,
    instruction: $('#trailer-instruction').value,
  });
});
$('#btn-fixsubs').addEventListener('click', () => {
  runJob('/api/fixsubs', { project_id: S.project.id }, () => toast('Sous-titres corrigés'));
});

$('#btn-render169').addEventListener('click', () => renderVideo('16:9'));
$('#btn-render916').addEventListener('click', () => renderVideo('9:16'));

function renderVideo(format) {
  runJob('/api/render', {
    project_id: S.project.id,
    segments: S.plan,
    format: format,
    encoder: $('#enc').value,
    quality: $('#qual').value,
    focus_x: Number($('#focus').value),
    burn_subtitles: $('#burn').checked,
    normalize_audio: $('#normalize').checked,
  }, () => {
    toast('Vidéo ' + format + ' prête');
    showTab('exports');
  });
}

$('#btn-filmcraft').addEventListener('click', () => {
  runJob('/api/filmcraft', { project_id: S.project.id, segments: S.plan, profile: '16:9' }, (result) => {
    // Le projet est deja ouvert dans FilmCraft a la fin du traitement.
    if (result && result.valid) toast('Projet ouvert dans FilmCraft');
    else toast((result && result.message) || 'Projet FilmCraft à vérifier', true);
  });
});

$('#btn-subs').addEventListener('click', () => {
  post('/api/subs', { project_id: S.project.id, segments: S.plan }).then((d) => {
    toast('Sous-titres enregistrés : ' + d.srt_path.split('/').pop());
    refreshProject();
  }).catch((e) => toast(e.message, true));
});

$('#focus').addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('#focus-val').textContent = v < 0.25 ? 'sujet à gauche' : (v > 0.75 ? 'sujet à droite' : 'centre');
});

async function openIn(target, path) {
  try { await post('/api/open', { target: target, path: path }); } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------------ */
/* Lecteur : ecouter un passage, apercu du montage                     */
/* ------------------------------------------------------------------ */

const player = $('#player');
let playlist = [];      // passages a enchainer : [{start, end, id}]
let playIndex = -1;

function loadPlayer() {
  const p = S.project;
  stopPlaylist();
  if (!p || p.media_missing) {
    $('#player-box').classList.add('hidden');
    player.removeAttribute('src');
    return;
  }
  const src = '/api/file?path=' + encodeURIComponent(p.path);
  if (player.getAttribute('src') !== src) player.setAttribute('src', src);
  $('#player-box').classList.remove('hidden');
}

player.addEventListener('error', () => {
  if (player.getAttribute('src')) {
    $('#player-label').textContent = 'Ce format ne peut pas être lu dans le navigateur (le montage fonctionne quand même).';
  }
});

function playItems(items, label) {
  if (!items.length) return;
  playlist = items;
  playIndex = 0;
  $('#player-label').textContent = label;
  $('#player-box').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  player.currentTime = items[0].start;
  player.play().catch(() => {});
  highlightPlaying();
}

function stopPlaylist() {
  playlist = [];
  playIndex = -1;
  highlightPlaying();
}

player.addEventListener('timeupdate', () => {
  if (playIndex < 0) return;
  const item = playlist[playIndex];
  if (player.currentTime < item.end) return;
  playIndex += 1;
  if (playIndex >= playlist.length) {
    player.pause();
    stopPlaylist();
    return;
  }
  player.currentTime = playlist[playIndex].start;      // saute la partie coupee
  highlightPlaying();
});
player.addEventListener('seeking', () => {
  // L'utilisateur deplace la tete de lecture : on sort du mode passage.
  if (playIndex >= 0) {
    const item = playlist[playIndex];
    if (player.currentTime < item.start - 0.3 || player.currentTime > item.end + 0.3) stopPlaylist();
  }
});

function highlightPlaying() {
  const current = playIndex >= 0 ? playlist[playIndex].id : null;
  $$('#cand-table tbody tr').forEach((tr) => tr.classList.toggle('playing', tr.dataset.id === current));
}

$('#btn-preview-cut').addEventListener('click', () => {
  if (!S.plan.length) return;
  playItems(S.plan.map((s) => ({ start: s.start, end: s.end, id: null })),
            'Aperçu du montage : ' + S.plan.length + ' morceaux enchaînés, parties coupées sautées.');
});

/* ------------------------------------------------------------------ */
/* Montage : passages et decisions                                     */
/* ------------------------------------------------------------------ */

const TYPE_LABELS = {
  contenu: 'contenu', introduction: 'introduction', conclusion: 'conclusion',
  illustration: 'illustration', digression: 'digression', hors_sujet: 'hors sujet',
  remplissage: 'remplissage', hesitation: 'hésitation', faux_depart: 'faux départ',
  repetition: 'répétition', boucle: 'transcription douteuse',
};

function decisionsById() {
  const out = {};
  ((S.project && S.project.results && S.project.results.plan_decisions) || [])
    .forEach((d) => { out[d.id] = d; });
  return out;
}

function toCheck(d) {
  return !!d && (d.suggested || d.doubt) && d.keep && !d.by_user;
}

function countToCheck() {
  return Object.values(decisionsById()).filter(toCheck).length;
}

function decisionLabel(d) {
  if (!d) return 'gardé';
  const t = TYPE_LABELS[d.type] || d.type || '';
  if (d.by_user) return d.keep ? 'gardé (votre choix)' : 'coupé (votre choix)';
  if (d.doubt) return 'à vérifier : transcription douteuse';
  if (d.suggested) return 'à vérifier : l’IA propose de couper (' + t + ')';
  if (!d.keep) return (d.by === 'regle' ? 'coupé : ' : 'coupé par l’IA : ') + t;
  return d.by === 'ia' && t !== 'contenu' ? 'gardé : ' + t : 'gardé';
}

function renderPlan() {
  const hasProject = !!S.project;
  const decisions = decisionsById();
  const kept = S.plan.reduce((a, s) => a + (s.end - s.start), 0);
  const total = (S.project && S.project.info && S.project.info.duration) || 0;
  $('#plan-summary').textContent = S.plan.length
    ? 'Montage : ' + fmtDuration(kept) + ' gardées sur ' + fmtDuration(total) +
      (total ? ' (' + Math.round(kept / total * 100) + ' %)' : '')
    : '';
  const rationale = (S.project && S.project.results && S.project.results.plan_rationale) || '';
  $('#plan-reason').textContent = rationale;
  $('#plan-reason').classList.toggle('hidden', !rationale || !S.plan.length);
  $('#btn-preview-cut').disabled = !S.plan.length;
  ['btn-render169', 'btn-render916', 'btn-filmcraft'].forEach((id) => {
    $('#' + id).disabled = !S.plan.length;
  });

  // Lignes : les passages (avec decisions) ; a defaut, les segments du plan.
  let rows = S.candidates.map((c) => ({ c: c, d: decisions[c.id] }));
  if (!Object.keys(decisions).length) {
    rows = S.plan.map((s, i) => ({ c: { id: 'P' + (i + 1), start: s.start, end: s.end,
                                        text: s.reason || '', kind: 'parole' }, d: null }));
  }
  const nCheck = rows.filter((r) => toCheck(r.d)).length;
  const nCut = rows.filter((r) => r.d && !r.d.keep).length;
  $('#count-check').textContent = nCheck ? '(' + nCheck + ')' : '';
  $('#count-cut').textContent = nCut ? '(' + nCut + ')' : '';
  $('.filter[data-filter="check"]').classList.toggle('alert', nCheck > 0);

  $('#passages-box').classList.toggle('hidden', !rows.length);
  $('#plan-empty').classList.toggle('hidden', !!rows.length);
  $('#plan-empty').textContent = hasProject
    ? 'Cliquez sur « Préparer le montage » : la liste des passages apparaîtra ici.'
    : 'Déposez une vidéo puis cliquez sur « Préparer le montage ».';

  const visible = rows.filter((r) => S.filter === 'all' ||
    (S.filter === 'check' && toCheck(r.d)) || (S.filter === 'cut' && r.d && !r.d.keep));
  const tbody = $('#cand-table tbody');
  tbody.innerHTML = visible.length ? visible.map(({ c, d }) => {
    const keep = d ? d.keep : true;
    const check = toCheck(d);
    const cls = (keep ? '' : 'cut') + (check ? ' suggest' : '');
    const text = c.kind === 'visuel' ? '<em class="muted">plan sans parole</em>'
                                     : escapeHtml((c.text || '').slice(0, 220));
    return '<tr class="' + cls + '" data-id="' + escapeHtml(c.id) + '" title="Passage ' + escapeHtml(c.id) + '">' +
      '<td>' + (d ? '<input type="checkbox" data-keep="' + escapeHtml(c.id) + '"' +
                (keep ? ' checked' : '') + ' title="Garder ce passage">' : '') + '</td>' +
      '<td><button class="play" data-play="' + escapeHtml(c.id) + '" title="Écouter ce passage">▶</button></td>' +
      '<td>' + fmtTime(c.start) + '</td><td>' + fmtDuration(c.end - c.start) + '</td>' +
      '<td class="dec' + (check ? ' suggest' : '') + '">' + escapeHtml(decisionLabel(d)) + '</td>' +
      '<td class="txt" dir="auto">' + text + '</td></tr>';
  }).join('') : '<tr><td colspan="6" class="empty">Aucun passage dans cette catégorie.</td></tr>';

  const byId = {};
  rows.forEach((r) => { byId[r.c.id] = r.c; });
  $$('#cand-table [data-keep]').forEach((cb) =>
    cb.addEventListener('change', () => setKeep(cb.dataset.keep, cb.checked)));
  $$('#cand-table [data-play]').forEach((b) => b.addEventListener('click', () => {
    const c = byId[b.dataset.play];
    playItems([{ start: c.start, end: c.end, id: c.id }],
              'Écoute du passage de ' + fmtTime(c.start) + ' à ' + fmtTime(c.end));
  }));
  highlightPlaying();
}

$$('#passages-box .filter').forEach((b) => b.addEventListener('click', () => {
  S.filter = b.dataset.filter;
  $$('#passages-box .filter').forEach((x) => x.classList.toggle('active', x === b));
  renderPlan();
}));

async function setKeep(id, keep) {
  try {
    const r = await post('/api/plan/keep', { project_id: S.project.id, id: id, keep: keep });
    S.plan = r.plan;
    S.project.plan = r.plan;
    S.project.results.plan_decisions = r.decisions;
    S.project.results.plan_rationale = r.rationale;
  } catch (e) {
    toast(e.message, true);
  }
  renderPlan();
}

/* ------------------------------------------------------------------ */
/* Textes IA                                                           */
/* ------------------------------------------------------------------ */

function renderIa() {
  const r = (S.project && S.project.results) || {};
  const blocks = [];
  if (r.pack) {
    const p = r.pack;
    blocks.push('<div class="ia-block"><h4>Titres</h4><ol>' +
      (p.titles || []).map((t) => '<li dir="auto">' + escapeHtml(t) + '</li>').join('') + '</ol></div>');
    if (p.description) {
      blocks.push('<div class="ia-block"><h4>Description</h4><p dir="auto">' + escapeHtml(p.description) + '</p></div>');
    }
    if (p.short_description) {
      blocks.push('<div class="ia-block"><h4>Version courte</h4><p dir="auto">' +
        escapeHtml(p.short_description) + '</p></div>');
    }
    if ((p.hashtags || []).length) {
      blocks.push('<div class="ia-block"><h4>Hashtags</h4>' +
        p.hashtags.map((h) => '<span class="tag">#' + escapeHtml(h) + '</span>').join('') + '</div>');
    }
    if ((p.chapters || []).length) {
      blocks.push('<div class="ia-block"><h4>Chapitres</h4><ul>' +
        p.chapters.map((c) => '<li dir="auto">' + escapeHtml(c.title || '') + '</li>').join('') + '</ul></div>');
    }
    if (p.hook) {
      blocks.push('<div class="ia-block"><h4>Accroche</h4><p dir="auto">' + escapeHtml(p.hook) + '</p></div>');
    }
  }
  if (r.summary) {
    const s = r.summary;
    blocks.push('<div class="ia-block"><h4>Résumé</h4><p dir="auto">' + escapeHtml(s.summary || '') + '</p></div>');
    if ((s.key_points || []).length) {
      blocks.push('<div class="ia-block"><h4>Points clés</h4><ul>' +
        s.key_points.map((k) => '<li dir="auto">' + escapeHtml(k) + '</li>').join('') + '</ul></div>');
    }
    if ((s.topics || []).length) {
      blocks.push('<div class="ia-block"><h4>Thèmes</h4>' +
        s.topics.map((t) => '<span class="tag">' + escapeHtml(t) + '</span>').join('') + '</div>');
    }
  }
  if (r.trailer) {
    const t = r.trailer;
    blocks.push('<div class="ia-block"><h4>Meilleurs moments</h4><ul>' +
      (t.segments || []).map((s) =>
        '<li>' + fmtTime(s.start) + ' → ' + fmtTime(s.end) +
        ' <span class="muted" dir="auto">(' + escapeHtml(s.reason || '') + ')</span></li>').join('') + '</ul></div>');
    if (t.rationale) {
      blocks.push('<div class="ia-block"><h4>Pourquoi ces moments</h4><p dir="auto">' + escapeHtml(t.rationale) + '</p></div>');
    }
  }
  $('#ia-out').innerHTML = blocks.length ? blocks.join('')
    : '<p class="empty">Les textes rédigés par l’IA s’afficheront ici.</p>';
}

/* ------------------------------------------------------------------ */
/* Exports                                                             */
/* ------------------------------------------------------------------ */

function renderExports() {
  const list = (S.project && S.project.exports) || [];
  const box = $('#exports-list');
  if (!list.length) {
    box.innerHTML = '<p class="empty">Aucun export pour l’instant.</p>';
    return;
  }
  box.innerHTML = list.slice().reverse().map((p) => {
    const isVideo = /\.mp4$/i.test(p);
    const isFc = /\.fcproj$/i.test(p);
    const icon = isVideo ? '🎬' : (isFc ? '🎞️' : '📄');
    const url = '/api/file?path=' + encodeURIComponent(p);
    return '<div class="export-item"><span class="fi">' + icon + '</span>' +
      '<span class="fn"><b>' + escapeHtml(p.split('/').pop()) + '</b>' +
      '<span>' + escapeHtml(p) + '</span></span>' +
      (isVideo ? '<button class="btn btn-mini" data-preview="' + escapeHtml(url) + '">Lire</button>' : '') +
      (isFc ? '<button class="btn btn-mini" data-open-fc="' + escapeHtml(p) + '">FilmCraft</button>' : '') +
      '<button class="btn btn-mini" data-reveal="' + escapeHtml(p) + '">Afficher dans le Finder</button></div>';
  }).join('');
  box.querySelectorAll('[data-preview]').forEach((b) => b.addEventListener('click', () => {
    $('#preview').src = b.dataset.preview;
    $('#preview-box').classList.remove('hidden');
  }));
  box.querySelectorAll('[data-open-fc]').forEach((b) =>
    b.addEventListener('click', () => openIn('filmcraft', b.dataset.openFc)));
  box.querySelectorAll('[data-reveal]').forEach((b) =>
    b.addEventListener('click', () => openIn('reveal', b.dataset.reveal)));
}

/* ------------------------------------------------------------------ */
/* Questions (streaming SSE via fetch)                                 */
/* ------------------------------------------------------------------ */

$('#btn-chat').addEventListener('click', sendChat);
$('#chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

async function sendChat() {
  const input = $('#chat-input');
  const question = input.value.trim();
  if (!question) return;
  if (!S.project) { toast('Ouvrez d’abord une vidéo', true); return; }
  input.value = '';
  const log = $('#chat-log');
  const empty = log.querySelector('.empty');
  if (empty) empty.remove();
  log.insertAdjacentHTML('beforeend',
    '<div class="msg user"><div class="who">Vous</div><div class="body" dir="auto">' +
    escapeHtml(question) + '</div></div>');
  const id = 'ai-' + Date.now();
  log.insertAdjacentHTML('beforeend',
    '<div class="msg" id="' + id + '"><div class="who">Rexo Studio</div><div class="body" dir="auto"></div></div>');
  const body = log.querySelector('#' + id + ' .body');
  log.scrollTop = log.scrollHeight;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: S.project.id, question: question }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data: /, '').trim();
        if (!line) continue;
        try {
          const ev = JSON.parse(line);
          if (ev.token) {
            body.textContent += ev.token;
            log.scrollTop = log.scrollHeight;
          } else if (ev.error) {
            body.textContent += '\n[erreur] ' + ev.error;
          }
        } catch (e) { /* fragment incomplet */ }
      }
    }
  } catch (err) {
    body.textContent += '\n[erreur] ' + err.message;
  }
}


/* ------------------------------------------------------------------ */
/* Vues : Evenements (accueil) / Montage video                         */
/* ------------------------------------------------------------------ */

function showView(name) {
  // La page de derushage d'un evenement fait partie de l'onglet Evenements.
  const tab = name === 'event' ? 'events' : name;
  $$('.view-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === tab));
  $('#view-events').classList.toggle('hidden', name !== 'events');
  $('#view-event').classList.toggle('hidden', name !== 'event');
  $('#view-montage').classList.toggle('hidden', name !== 'montage');
  if (name !== 'event') $('#evd-player').pause();
  if (name === 'events') loadEvents();
}

$$('.view-btn').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));

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
      '<button class="btn btn-primary btn-small ev-derush" data-id="' + id + '">🎬 Dérushage</button>' +
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
/* Derushage d'un evenement (M1)                                       */
/* ------------------------------------------------------------------ */

const EVD = { id: '', event: null, clips: [], photos: [], cards: [], issues: {}, filter: 'all', effects: [], studio: null };

function fileUrl(path) {
  return '/api/file?path=' + encodeURIComponent(path);
}

async function openDerush(id) {
  EVD.id = id;
  showView('event');
  $('#evd-player-box').classList.add('hidden');
  $('#evd-player').pause();
  await loadDerush();
  loadSources();
}

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
    const e = data.event;
    $('#evd-type').textContent = e.type_label;
    $('#evd-type').className = 'ev-type t-' + e.type;
    $('#evd-names').textContent = e.names;
    $('#evd-date').textContent = evDate(e.date).text + (e.place ? ' — ' + e.place : '');
    renderDerush();
    renderCards();
    renderFolders();
    renderPhotos();
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
  toast('Sélection ouverte dans FilmCraft : ' + r.clips + ' rushes, ' + fmtDuration(r.duration))));


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
  $('#evd-photo-count').textContent = EVD.photos.length ? '(' + EVD.photos.length + ')' : '';
  $('#evd-photos').innerHTML = !EVD.photos.length
    ? '<p class="empty">Aucune photo : elles arrivent avec l’import d’une carte, dans 02_Photos.</p>'
    : EVD.photos.map((p) =>
      '<div class="photo" title="' + escapeHtml(p.rel) + '">' +
      '<a ' + (p.viewable ? 'href="' + fileUrl(p.path) + '" target="_blank" rel="noopener"' : 'class="noview"') + '>' +
      (p.thumb ? '<img loading="lazy" src="' + fileUrl(p.thumb) + '" alt="">' : '<span class="muted">' + escapeHtml(p.name) + '</span>') +
      '</a><div class="photo-bar"><span>' + escapeHtml(p.name) + '</span>' +
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

$('#evd-photos').addEventListener('click', (ev) => {
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
  studioForm();
  fxRender();
  $('#fx').classList.remove('hidden');
}

/* -- chaine de production : clip drone 3D (Rexo + Blender + EffectCraft) -- */

function studioForm() {
  const st = EVD.studio;
  const info = $('#st-info');
  const opts = (items, key, label) => items.map((x) =>
    '<option value="' + escapeHtml(x[key]) + '">' + escapeHtml(x[label]) + '</option>').join('');
  $('#st-motion').innerHTML = st ? opts(st.motions, 'id', 'label') : '';
  // Sans modele de scene, le jardin simple est construit au premier clip
  $('#st-scene').innerHTML = st && st.scenes.length ? opts(st.scenes, 'id', 'name')
    : '<option value="jardin_nuit">Jardin nuit (simple)</option>';
  $('#st-title').value = (EVD.event && EVD.event.names) || '';
  $('#st-subtitle').value = frenchDate((EVD.event && EVD.event.date) || '');
  const ready = !!(st && st.blender && st.detourage && st.effectcraft);
  $('#st-filmcraft').disabled = !(st && st.filmcraft);
  $('#st-filmcraft').checked = !!(st && st.filmcraft);
  $('#st-run').disabled = !ready;
  info.className = 'tiny' + (ready ? ' muted' : ' err');
  info.textContent = !st ? '' : !st.blender ? 'Blender 3.6 absent : ./scripts/install_blender.sh'
    : !st.detourage ? 'Outil de détourage absent : ./scripts/build_native.sh'
      : !st.effectcraft ? 'EffectCraft absent : il place les photos dans la scène'
        : st.generics.length ? 'Bibliothèque : ' + st.generics.length + ' animation(s) générique(s) déjà prête(s)'
          : 'Première fois : Blender prépare l’animation générique (quelques minutes, une seule fois)';
}

function frenchDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return '';
  const months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
    'octobre', 'novembre', 'décembre'];
  return (+m[3]) + ' ' + months[+m[2] - 1] + ' ' + m[1];
}

$('#st-run').addEventListener('click', () => {
  if (FX.busy || !FX.photo) return;
  const body = { recipe: 'clip-drone', rel: FX.photo.rel, scene: $('#st-scene').value,
    motion: $('#st-motion').value, seconds: +$('#st-seconds').value, quality: $('#st-quality').value,
    title: $('#st-title').value.trim(), subtitle: $('#st-subtitle').value.trim(),
    filmcraft: $('#st-filmcraft').checked };
  closeFx();
  toast('Clip drone lancé en tâche de fond : il arrivera dans 06_Rendus/Clips_3D');
  derushJob('/api/events/studio', body);
});

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
    }
    fxRender();
  };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', up);
});

$('#fx-frame').addEventListener('click', () => {
  if (FX.busy) return;
  if (FX.box) { FX.box = null; FX.framing = false; fxInvalidate(); } else { FX.framing = !FX.framing; FX.view = 'orig'; }
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
renderPlan();
loadProjects().then(() => {
  const id = lastProject();
  if (id && !S.project && document.querySelector('[data-project="' + CSS.escape(id) + '"]')) {
    openProject(id);
  }
});
