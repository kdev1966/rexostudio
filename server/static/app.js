/* MontageIA - interface web locale (vanilla JS, aucune dependance) */
'use strict';

const S = {
  project: null,
  plan: [],
  candidates: [],
  busy: false,
  es: null,
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
  el._t = setTimeout(() => { el.className = 'toast'; }, 3600);
}

function fmtTime(s) {
  s = Math.max(0, Number(s) || 0);
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, '0');
  return m + ':' + sec;
}

function fmtSize(bytes) {
  const u = ['o', 'Ko', 'Mo', 'Go'];
  let i = 0, n = bytes;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + ' ' + u[i];
}

async function api(url, options) {
  const res = await fetch(url, options);
  let data = null;
  try { data = await res.json(); } catch (e) { /* pas de JSON */ }
  if (!res.ok) throw new Error((data && data.error) || ('Erreur HTTP ' + res.status));
  return data;
}

function setProgress(value, step) {
  $('#job-bar-fill').style.width = Math.round((value || 0) * 100) + '%';
  $('#job-label').textContent = (step || '') + (value !== undefined ? ' — ' + Math.round((value || 0) * 100) + '%' : '');
}

function addLog(line) {
  const box = $('#job-log');
  box.textContent += line + '\n';
  box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* Onglets                                                             */
/* ------------------------------------------------------------------ */

$$('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    $$('.tab').forEach((t) => t.classList.remove('active'));
    $$('.tabpane').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    $('#tab-' + tab.dataset.tab).classList.add('active');
  });
});

/* ------------------------------------------------------------------ */
/* Statut systeme                                                      */
/* ------------------------------------------------------------------ */

async function loadStatus() {
  try {
    const s = await api('/api/status');
    const chips = [];
    const o = s.ollama || {};
    chips.push(chip(o.up ? 'IA ' + (s.model || '') + ' · prête' : 'Ollama hors ligne', o.up));
    chips.push(chip('ffmpeg', !!s.ffmpeg));
    chips.push(chip('Whisper ' + (s.whisper_models.map(m => m.name).join('/') || 'absent'), !!s.whisper));
    chips.push(chip('VAD', !!s.vad_model));
    chips.push(chip('FilmCraft', !!s.filmcraft));
    $('#status-bar').innerHTML = chips.join('');

    const sel = $('#whisper-model');
    if (s.whisper_models.length) {
      // "Automatique" par defaut : le serveur choisit le modele selon la
      // langue detectee (small pour l'arabe). Le choix fait est conserve :
      // ce menu est reconstruit a chaque rafraichissement de l'etat (15 s).
      const current = sel.value;
      sel.innerHTML = '<option value="">Automatique (selon la langue)</option>' +
        s.whisper_models
          .map(m => '<option value="' + m.name + '">' + m.name + ' (' + fmtSize(m.size) + ')</option>')
          .join('');
      sel.value = s.whisper_models.some(m => m.name === current) ? current : '';
    } else {
      sel.innerHTML = '<option value="">aucun modèle</option>';
    }
  } catch (e) {
    $('#status-bar').innerHTML = chip('Serveur injoignable', false);
  }
}

function chip(text, on) {
  return '<span class="chip ' + (on ? 'on' : 'off') + '">' + text + '</span>';
}

/* ------------------------------------------------------------------ */
/* Upload                                                              */
/* ------------------------------------------------------------------ */

const dz = $('#dropzone');
dz.addEventListener('click', () => $('#fileInput').click());
$('#browseBtn').addEventListener('click', (e) => { e.stopPropagation(); $('#fileInput').click(); });

['dragenter', 'dragover'].forEach(ev =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('drag'); }));
['dragleave', 'drop'].forEach(ev =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('drag'); }));
dz.addEventListener('drop', (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) upload(f);
});
$('#fileInput').addEventListener('change', (e) => {
  const f = e.target.files && e.target.files[0];
  if (f) upload(f);
});

function upload(file) {
  $('#upload-progress').classList.remove('hidden');
  $('#upload-bar-fill').style.width = '0%';
  $('#upload-label').textContent = 'Envoi de ' + file.name + '…';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const pct = (e.loaded / e.total) * 100;
      $('#upload-bar-fill').style.width = pct + '%';
      $('#upload-label').textContent = 'Envoi — ' + Math.round(pct) + '% (' + fmtSize(e.loaded) + ')';
    }
  };
  xhr.onload = () => {
    let data = null;
    try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
    if (xhr.status >= 200 && xhr.status < 300 && data && data.project) {
      S.project = data.project;
      $('#upload-label').textContent = 'Téléversé : ' + data.size_human;
      setTimeout(() => $('#upload-progress').classList.add('hidden'), 1200);
      rememberProject(S.project.id);
      showMedia();
      refreshProject();
      loadProjects();
      toast('Média prêt : ' + data.project.name);
    } else {
      $('#upload-progress').classList.add('hidden');
      toast((data && data.error) || 'Échec du téléversement', true);
    }
  };
  xhr.onerror = () => {
    $('#upload-progress').classList.add('hidden');
    toast('Erreur réseau pendant le téléversement', true);
  };
  xhr.send(file);
}

/* ------------------------------------------------------------------ */
/* Projets recents (persistants cote serveur)                          */
/* ------------------------------------------------------------------ */

const LAST_PROJECT_KEY = 'montagia.lastProject';

function rememberProject(id) {
  try { localStorage.setItem(LAST_PROJECT_KEY, id); } catch (e) { /* stockage indisponible */ }
}

function lastProject() {
  try { return localStorage.getItem(LAST_PROJECT_KEY); } catch (e) { return null; }
}

async function loadProjects() {
  let list = [];
  try { list = (await api('/api/projects')).projects || []; } catch (e) { return; }
  $('#recent-box').classList.toggle('hidden', !list.length);
  $('#recent-list').innerHTML = list.slice(0, 12).map((p) => {
    const badges = [fmtTime(p.duration)];
    if (p.transcribed) badges.push('transcrit');
    if (p.planned) badges.push('plan');
    if (p.exports) badges.push(p.exports + ' export' + (p.exports > 1 ? 's' : ''));
    const active = S.project && S.project.id === p.id ? ' active' : '';
    return '<button class="recent-item' + active + '" data-project="' + escapeHtml(p.id) + '">' +
      '<span class="rn">' + escapeHtml(p.name) + '</span>' +
      (p.media_missing ? '<span class="rb warn">média introuvable</span>'
                       : '<span class="rb">' + escapeHtml(badges.join(' · ')) + '</span>') +
      '</button>';
  }).join('');
  $$('#recent-list [data-project]').forEach((b) =>
    b.addEventListener('click', () => openProject(b.dataset.project)));
}

async function openProject(id) {
  if (S.busy) { toast('Une opération est en cours', true); return; }
  try {
    S.project = (await api('/api/project?id=' + encodeURIComponent(id))).project;
  } catch (e) { toast(e.message, true); return; }
  rememberProject(id);
  showMedia();
  await refreshProject();
  loadProjects();
  if (S.project.media_missing) toast('Le fichier vidéo de ce projet est introuvable', true);
}

function showMedia() {
  const p = S.project;
  if (!p) return;
  const i = p.info || {};
  $('#media-info').classList.remove('hidden');
  $('#media-info').innerHTML =
    '<dl class="info-grid">' +
    '<dt>Durée</dt><dd>' + fmtTime(i.duration) + '</dd>' +
    '<dt>Résolution</dt><dd>' + (i.width || '?') + '×' + (i.height || '?') +
      ' · ' + (i.fps ? i.fps.toFixed(2) : '?') + ' fps</dd>' +
    '<dt>Codecs</dt><dd>' + (i.vcodec || '-') + ' / ' + (i.acodec || 'aucun son') + '</dd>' +
    '<dt>Taille</dt><dd>' + fmtSize(i.size || 0) + '</dd>' +
    '<dt>Fichier</dt><dd>' + escapeHtml(p.name) + '</dd>' +
    '</dl>';
  ['btn-analyze', 'btn-transcribe'].forEach(id => { $('#' + id).disabled = false; });
  $('#btn-plan').disabled = !p.transcript_segments.length;
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ------------------------------------------------------------------ */
/* Lancement des jobs (SSE)                                            */
/* ------------------------------------------------------------------ */

function runJob(url, body, onDone) {
  if (S.busy) { toast('Une opération est déjà en cours', true); return; }
  S.busy = true;
  $('#job-box').classList.remove('hidden');
  $('#job-log').textContent = '';
  setProgress(0, 'Démarrage');

  api(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((data) => {
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
        S.busy = false;
        refreshProject().then(() => { loadProjects(); if (onDone) onDone(e.result); });
      } else if (e.type === 'error') {
        addLog('ERREUR : ' + e.error);
        toast(e.error, true);
        es.close();
        S.busy = false;
      }
    };
    es.onerror = () => { es.close(); S.busy = false; };
  }).catch((err) => {
    toast(err.message, true);
    S.busy = false;
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

async function refreshProject() {
  if (!S.project) return;
  try {
    const d = await api('/api/project?id=' + S.project.id);
    S.project = d.project;
    S.plan = d.project.plan || [];
    S.candidates = d.project.candidates || [];
    renderPlan();
    renderCandidates();
    renderExports();
    const hasTrans = (S.project.transcript_segments || []).length > 0;
    $('#btn-plan').disabled = !hasTrans;
    $('#btn-render169').disabled = !S.plan.length;
    $('#btn-render916').disabled = !S.plan.length;
    $('#btn-filmcraft').disabled = !S.plan.length;
    $('#btn-subs').disabled = !hasTrans;
  } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

$('#btn-analyze').addEventListener('click', () => {
  runJob('/api/analyze', { project_id: S.project.id });
});

$('#btn-transcribe').addEventListener('click', () => {
  runJob('/api/transcribe', {
    project_id: S.project.id,
    model: $('#whisper-model').value || null,
    language: $('#whisper-lang').value,
  });
});

$('#btn-plan').addEventListener('click', () => {
  runJob('/api/plan', {
    project_id: S.project.id,
    instruction: $('#plan-instruction').value,
    style: $('#plan-style').value,
  }, (result) => {
    if (result && result.rationale) {
      $('#plan-reason').textContent = result.rationale;
      $('#plan-reason').classList.remove('hidden');
    }
  });
});

$('#btn-pack').addEventListener('click', () => {
  runJob('/api/pack', { project_id: S.project.id }, () => renderIa());
});

$('#btn-summary').addEventListener('click', () => {
  runJob('/api/summary', { project_id: S.project.id }, () => renderIa());
});

$('#btn-trailer').addEventListener('click', () => {
  runJob('/api/trailer', {
    project_id: S.project.id,
    target_seconds: Number($('#trailer-target').value) || 30,
    instruction: $('#trailer-instruction').value,
  }, () => renderIa());
});

$('#btn-fixsubs').addEventListener('click', () => {
  runJob('/api/fixsubs', { project_id: S.project.id }, () => {
    toast('Sous-titres corrigés');
  });
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
    toast('Export ' + format + ' terminé');
    showTab('exports');
  });
}

$('#btn-filmcraft').addEventListener('click', () => {
  runJob('/api/filmcraft', {
    project_id: S.project.id,
    segments: S.plan,
    profile: '16:9',
  }, (result) => {
    // Le projet est deja ouvert dans FilmCraft a la fin du job.
    if (result && result.valid) toast('Projet ouvert dans FilmCraft');
    else toast((result && result.message) || 'Projet FilmCraft à vérifier', true);
  });
});

$('#btn-subs').addEventListener('click', () => {
  api('/api/subs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: S.project.id, segments: S.plan }),
  }).then((d) => {
    toast('Sous-titres : ' + d.srt_path.split('/').pop());
    refreshProject();
  }).catch((e) => toast(e.message, true));
});

$('#btn-reset-plan').addEventListener('click', () => {
  S.plan = [];
  renderPlan();
});

$('#focus').addEventListener('input', (e) => {
  const v = Number(e.target.value);
  const label = v < 0.25 ? 'gauche' : (v > 0.75 ? 'droite' : 'centre');
  $('#focus-val').textContent = label;
});

function showTab(name) {
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tabpane').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
}

async function openIn(target, path) {
  try {
    await api('/api/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target, path: path }),
    });
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------------ */
/* Plan de coupe                                                       */
/* ------------------------------------------------------------------ */

function renderPlan() {
  const tbody = $('#plan-table tbody');
  tbody.innerHTML = '';
  $('#plan-empty').style.display = S.plan.length ? 'none' : 'block';

  S.plan.forEach((seg, idx) => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + (idx + 1) + '</td>' +
      '<td><input type="number" step="0.1" value="' + seg.start + '" data-i="' + idx + '" data-f="start"></td>' +
      '<td><input type="number" step="0.1" value="' + seg.end + '" data-i="' + idx + '" data-f="end"></td>' +
      '<td>' + fmtTime(seg.end - seg.start) + '</td>' +
      '<td class="reason-cell">' + escapeHtml(seg.reason || '') + '</td>' +
      '<td><button class="del" title="Supprimer">&times;</button></td>';
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('input').forEach((inp) => {
    inp.addEventListener('change', () => {
      const i = Number(inp.dataset.i);
      const f = inp.dataset.f;
      const v = parseFloat(inp.value);
      if (!isNaN(v)) {
        S.plan[i][f] = v;
        renderPlan();
        savePlan();
      }
    });
  });
  tbody.querySelectorAll('.del').forEach((btn) => {
    btn.addEventListener('click', () => {
      const i = Number(btn.closest('tr').querySelector('input').dataset.i);
      S.plan.splice(i, 1);
      renderPlan();
      savePlan();
    });
  });

  const kept = S.plan.reduce((a, s) => a + (s.end - s.start), 0);
  const total = (S.project && S.project.info && S.project.info.duration) || 0;
  $('#plan-summary').textContent = S.plan.length
    ? S.plan.length + ' segments · ' + fmtTime(kept) + ' conservés'
      + (total ? ' sur ' + fmtTime(total) + ' (' + Math.round(kept / total * 100) + '%)' : '')
    : 'Aucun plan pour l’instant.';

  const rationale = (S.project && S.project.results && S.project.results.plan_rationale) || '';
  $('#plan-reason').textContent = rationale;
  $('#plan-reason').classList.toggle('hidden', !rationale);

  $('#btn-render169').disabled = !S.plan.length;
  $('#btn-render916').disabled = !S.plan.length;
  $('#btn-filmcraft').disabled = !S.plan.length;
}

function savePlan() {
  if (!S.project) return;
  api('/api/subs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: S.project.id, segments: S.plan }),
  }).catch(() => {});
}

const TYPE_LABELS = {
  contenu: 'contenu', introduction: 'introduction', conclusion: 'conclusion',
  illustration: 'illustration', digression: 'digression', hors_sujet: 'hors sujet',
  remplissage: 'remplissage', hesitation: 'hésitation', faux_depart: 'faux départ',
  repetition: 'répétition',
};

function decisionLabel(d) {
  if (!d) return '';
  const t = TYPE_LABELS[d.type] || d.type || '';
  if (d.by_user) return 'choix manuel';
  if (d.suggested) return 'suggestion IA : ' + t;
  if (d.by === 'regle') return 'règle : ' + t;
  if (d.by === 'ia') return 'IA : ' + t;
  return t;
}

function renderCandidates() {
  const box = $('#candidates-box');
  if (!S.candidates.length) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  $('#cand-count').textContent = S.candidates.length;
  const decisions = {};
  ((S.project && S.project.results && S.project.results.plan_decisions) || [])
    .forEach((d) => { decisions[d.id] = d; });
  const pending = Object.values(decisions).filter((d) => d.suggested && d.keep && !d.by_user).length;
  $('#suggest-count').textContent = pending + ' suggestion' + (pending > 1 ? 's' : '') + ' à valider';
  $('#suggest-count').classList.toggle('hidden', !pending);
  if (pending) $('#cand-details').open = true;
  const tbody = $('#cand-table tbody');
  tbody.innerHTML = S.candidates.map((c) => {
    const d = decisions[c.id];
    const kept = d ? d.keep : true;
    const suggest = d && d.suggested && d.keep && !d.by_user;
    const cls = (kept ? '' : 'cut') + (suggest ? ' suggest' : '');
    const text = c.kind === 'visuel' ? '<em class="muted">plan sans parole</em>'
                                     : escapeHtml((c.text || '').slice(0, 160));
    return '<tr class="' + cls + '">' +
      '<td>' + (d ? '<input type="checkbox" data-keep="' + escapeHtml(c.id) + '"' +
                (kept ? ' checked' : '') + ' title="Garder ce passage">' : '') + '</td>' +
      '<td>' + c.id + '</td><td>' + fmtTime(c.start) + '</td><td>' + fmtTime(c.end) + '</td>' +
      '<td class="dec' + (suggest ? ' suggest' : '') + '">' + escapeHtml(decisionLabel(d)) + '</td>' +
      '<td class="txt">' + text + '</td></tr>';
  }).join('');
  $$('#cand-table [data-keep]').forEach((cb) =>
    cb.addEventListener('change', () => setKeep(cb.dataset.keep, cb.checked)));
}

async function setKeep(id, keep) {
  try {
    const r = await api('/api/plan/keep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: S.project.id, id: id, keep: keep }),
    });
    S.plan = r.plan;
    S.project.plan = r.plan;
    S.project.results.plan_decisions = r.decisions;
    S.project.results.plan_rationale = r.rationale;
    $('#plan-reason').textContent = r.rationale;
    $('#plan-reason').classList.remove('hidden');
    renderPlan();
    renderCandidates();
  } catch (e) {
    toast(e.message, true);
    renderCandidates();
  }
}

/* ------------------------------------------------------------------ */
/* Resultats IA                                                        */
/* ------------------------------------------------------------------ */

function renderIa() {
  const r = (S.project && S.project.results) || {};
  const out = $('#ia-out');
  const blocks = [];

  if (r.pack) {
    const p = r.pack;
    blocks.push('<div class="ia-block"><h4>Titres accrocheurs</h4><ol>' +
      (p.titles || []).map(t => '<li>' + escapeHtml(t) + '</li>').join('') + '</ol></div>');
    if (p.description) {
      blocks.push('<div class="ia-block"><h4>Description YouTube</h4><p>' +
        escapeHtml(p.description) + '</p></div>');
    }
    if (p.short_description) {
      blocks.push('<div class="ia-block"><h4>Version courte</h4><p>' +
        escapeHtml(p.short_description) + '</p></div>');
    }
    if ((p.hashtags || []).length) {
      blocks.push('<div class="ia-block"><h4>Hashtags</h4>' +
        p.hashtags.map(h => '<span class="tag">#' + escapeHtml(h) + '</span>').join('') + '</div>');
    }
    if ((p.chapters || []).length) {
      blocks.push('<div class="ia-block"><h4>Chapitres</h4><ul>' +
        p.chapters.map(c => '<li>' + escapeHtml(c.title || '') + '</li>').join('') + '</ul></div>');
    }
    if (p.hook) {
      blocks.push('<div class="ia-block"><h4>Accroche</h4><p>' + escapeHtml(p.hook) + '</p></div>');
    }
  }

  if (r.summary) {
    const s = r.summary;
    blocks.push('<div class="ia-block"><h4>Résumé</h4><p>' + escapeHtml(s.summary || '') + '</p></div>');
    if ((s.key_points || []).length) {
      blocks.push('<div class="ia-block"><h4>Points clés</h4><ul>' +
        s.key_points.map(k => '<li>' + escapeHtml(k) + '</li>').join('') + '</ul></div>');
    }
    if ((s.topics || []).length) {
      blocks.push('<div class="ia-block"><h4>Thèmes</h4>' +
        s.topics.map(t => '<span class="tag">' + escapeHtml(t) + '</span>').join('') + '</div>');
    }
  }

  if (r.trailer) {
    const t = r.trailer;
    blocks.push('<div class="ia-block"><h4>Meilleurs moments</h4><ul>' +
      (t.segments || []).map(s =>
        '<li>' + fmtTime(s.start) + ' → ' + fmtTime(s.end) +
        ' <span class="muted">(' + escapeHtml(s.reason || '') + ')</span></li>').join('') + '</ul></div>');
    if (t.rationale) {
      blocks.push('<div class="ia-block"><h4>Justification</h4><p>' + escapeHtml(t.rationale) + '</p></div>');
    }
  }

  out.innerHTML = blocks.length ? blocks.join('') :
    '<p class="empty">Aucun résultat IA pour l’instant.</p>';
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
  box.innerHTML = list.map((p) => {
    const isVideo = /\.mp4$/i.test(p);
    const icon = isVideo ? '🎬' : (/\.fcproj$/i.test(p) ? '🎞️' : '📄');
    const url = '/api/file?path=' + encodeURIComponent(p);
    return '<div class="export-item"><span class="fi">' + icon + '</span>' +
      '<span class="fn"><b>' + escapeHtml(p.split('/').pop()) + '</b>' +
      '<span>' + escapeHtml(p) + '</span></span>' +
      (isVideo ? '<button class="btn btn-mini" data-preview="' + escapeHtml(url) + '">Lire</button>' : '') +
      (/\.fcproj$/i.test(p) ? '<button class="btn btn-mini" data-open-fc="' + escapeHtml(p) + '">FilmCraft</button>' : '') +
      '<button class="btn btn-mini" data-reveal="' + escapeHtml(p) + '">Finder</button>' +
      '<a class="btn btn-mini" href="' + url + '" download>Télécharger</a></div>';
  }).join('');

  box.querySelectorAll('[data-preview]').forEach(b =>
    b.addEventListener('click', () => {
      $('#preview').src = b.dataset.preview;
      $('#preview-box').classList.remove('hidden');
    }));
  box.querySelectorAll('[data-open-fc]').forEach(b =>
    b.addEventListener('click', () => openIn('filmcraft', b.dataset.openFc)));
  box.querySelectorAll('[data-reveal]').forEach(b =>
    b.addEventListener('click', () => openIn('reveal', b.dataset.reveal)));
}

/* ------------------------------------------------------------------ */
/* Chat (streaming SSE via fetch)                                      */
/* ------------------------------------------------------------------ */

$('#btn-chat').addEventListener('click', sendChat);
$('#chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendChat();
});

async function sendChat() {
  const input = $('#chat-input');
  const question = input.value.trim();
  if (!question || !S.project) return;
  input.value = '';

  const log = $('#chat-log');
  const empty = log.querySelector('.empty');
  if (empty) empty.remove();

  log.insertAdjacentHTML('beforeend',
    '<div class="msg user"><div class="who">Vous</div><div class="body">' +
    escapeHtml(question) + '</div></div>');
  const id = 'ai-' + Date.now();
  log.insertAdjacentHTML('beforeend',
    '<div class="msg" id="' + id + '"><div class="who">MontageIA</div><div class="body"></div></div>');
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

loadStatus();
setInterval(loadStatus, 15000);
loadProjects().then(() => {
  const id = lastProject();
  if (id && !S.project && document.querySelector('[data-project="' + CSS.escape(id) + '"]')) {
    openProject(id);
  }
});
