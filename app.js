const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const I = {
news:'<path d="M4 5h13v14H6a2 2 0 0 1-2-2z"/><path d="M17 9h3v8a2 2 0 0 1-2 2"/><path d="M8 9h5M8 13h5"/>',
bulb:'<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
quiz:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7"/><path d="M12 17h.01"/>',
spk:'<path d="M4 10v4h4l5 4V6L8 10z"/><path d="M16.5 9a4 4 0 0 1 0 6"/>',
lnk:'<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5H5V6h5"/>',
set:'<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
rnd:'<path d="M3 7h4l10 10h4M3 17h4l3-3M14 10l3-3h4M18 4l3 3-3 3M18 14l3 3-3 3"/>',
day:'<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16M9 3v4M15 3v4"/>',
rev:'<path d="M4 12a8 8 0 1 0 3-6.2M4 4v4h4"/>',
rf:'<path d="M20 12a8 8 0 1 1-2.5-5.8M20 4v4h-4"/>'
};
const ic = n => '<svg class="i" viewBox="0 0 24 24">' + I[n] + '</svg>';
const store = {
  get(k, d) {
    try {
      const v = localStorage.getItem(k);
      return v == null ? d : JSON.parse(v);
    } catch (e) { return d; }
  },
  set(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
  }
};
const hm = s => {
  try {
    return new Date(s).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
  } catch (e) { return ''; }
};
let D = null, B = [], tab = 'actus', tok = 0, queue = [];

const frVoices = () => {
  const all = ('speechSynthesis' in window) ? speechSynthesis.getVoices() : [];
  return all.filter(v => (v.lang || '').toLowerCase().replace('_', '-').startsWith('fr'));
};
function voiceScore(v) {
  let s = 0;
  if (/premium|haute qualit/i.test(v.name)) s += 30;
  if (/siri/i.test(v.name)) s += 25;
  if (/enhanced|am[ée]lior/i.test(v.name)) s += 20;
  if (v.lang.replace('_', '-') === 'fr-FR') s += 5;
  if (v.localService) s += 1;
  return s;
}
function pickVoice() {
  const vs = frVoices();
  const saved = store.get('voice', '');
  const f = vs.find(v => v.voiceURI === saved);
  if (f) return f;
  return vs.slice().sort((a, b) => voiceScore(b) - voiceScore(a))[0] || null;
}
function stopSay() {
  tok++;
  queue = [];
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  document.querySelectorAll('.say.on').forEach(b => b.classList.remove('on'));
}
function say(text, btn) {
  const was = btn.classList.contains('on');
  stopSay();
  if (was) return;
  btn.classList.add('on');
  const t = tok;
  queue = (text.match(/[^.!?]+[.!?]*\s*/g) || [text]).filter(s => s.trim());
  setTimeout(() => nxt(btn, t), 80);
}
function nxt(btn, t) {
  if (t !== tok) return;
  if (!queue.length) { btn.classList.remove('on'); return; }
  const u = new SpeechSynthesisUtterance(queue.shift().trim());
  const v = pickVoice();
  if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = 'fr-FR'; }
  u.rate = store.get('rate', 0.95);
  u.onend = () => nxt(btn, t);
  u.onerror = () => nxt(btn, t);
  speechSynthesis.speak(u);
}
if ('speechSynthesis' in window) {
  speechSynthesis.onvoiceschanged = () => { if (tab === 'reglages') render(); };
}

const getG = () => store.get('g', {answered:0, correct:0, quizzes:0});
function record(id, ok) {
  const st = store.get('stats', {});
  const s = st[id] || {ok:0, ko:0};
  if (ok) s.ok++; else s.ko++;
  st[id] = s;
  store.set('stats', st);
  const g = getG();
  g.answered++;
  if (ok) g.correct++;
  store.set('g', g);
}
function countQuiz() {
  const g = getG();
  g.quizzes++;
  store.set('g', g);
}
function statsHTML() {
  const g = getG();
  const pct = g.answered ? Math.round(g.correct / g.answered * 100) : 0;
  const C = 138.23;
  const bg = g.answered ? '#ff7a8a' : '#23232c';
  return '<div class="card stat"><svg viewBox="0 0 56 56">'
    + '<circle cx="28" cy="28" r="22" fill="none" stroke="' + bg + '" stroke-width="6"/>'
    + '<circle cx="28" cy="28" r="22" fill="none" stroke="#5ad19a" stroke-width="6" stroke-dasharray="' + (pct / 100 * C) + ' ' + C + '" transform="rotate(-90 28 28)"/></svg>'
    + '<div><b>' + (g.answered ? pct + ' % de réussite' : 'Pas encore de quiz') + '</b>'
    + '<span class="sm">' + g.quizzes + ' quiz terminé' + (g.quizzes > 1 ? 's' : '')
    + ' · ' + g.correct + '/' + g.answered + ' bonnes réponses</span></div></div>';
}

function card(a) {
  const t = [a.titre, a.resume, a.contexte ? 'Pourquoi : ' + a.contexte : ''].filter(Boolean).join('. ');
  let h = '<article class="card"><div class="meta">' + esc(a.source) + ' · ' + hm(a.date) + '</div>';
  h += '<h3>' + esc(a.titre) + '</h3><p>' + esc(a.resume) + '</p>';
  if (a.contexte) {
    h += '<div class="ctx"><b>Pourquoi c\'est important</b>' + esc(a.contexte) + '</div>';
  }
  h += '<div class="acts"><button class="say" data-t="' + esc(t) + '">' + ic('spk') + 'Écouter</button>';
  if (a.lien) {
    h += '<a href="' + esc(a.lien) + '" target="_blank" rel="noopener">' + ic('lnk') + 'Lire</a>';
  }
  return h + '</div></article>';
}
function sec(t, l) {
  return l && l.length ? '<h2>' + t + '</h2>' + l.map(card).join('') : '';
}
function vActus() {
  if (!D) return '<div class="empty">Pas encore de données. Lance le workflow dans GitHub (onglet Actions).</div>';
  const auj = D.aujourdhui || [];
  const all = auj.map(a => a.titre + '. ' + a.resume).join(' ');
  let h = '';
  if (auj.length) {
    h += '<div class="acts" style="margin:12px 4px 0"><button class="say" data-t="' + esc(all) + '">' + ic('spk') + 'Tout écouter</button></div>';
  }
  h += sec('Depuis hier', D.depuis_hier) + sec("Aujourd'hui", D.aujourdhui);
  const dj = D.deja_presente || [];
  if (dj.length) {
    h += '<details><summary>Déjà présenté (' + dj.length + ')</summary>' + dj.map(card).join('') + '</details>';
  }
  return h || '<div class="empty">Aucune actu pour le moment.</div>';
}
function fiche(c) {
  const tu = c.type === 'tuto';
  const et = c.etapes || [];
  const er = c.erreurs || [];
  const parts = [c.titre, c.texte];
  et.forEach((e, i) => parts.push('Étape ' + (i + 1) + ' : ' + e));
  if (er.length) parts.push('Erreurs à éviter : ' + er.join('. '));
  if (c.a_retenir) parts.push('À retenir : ' + c.a_retenir);
  const t = parts.filter(Boolean).join('. ');
  let h = '<article class="card"><span class="chip ' + (tu ? 'tuto' : '') + '">' + esc(c.theme) + '</span>';
  h += '<h3 style="margin-top:10px">' + esc(c.titre) + '</h3><p>' + esc(c.texte) + '</p>';
  if (et.length) {
    h += '<ol class="steps">' + et.map(e => '<li>' + esc(e) + '</li>').join('') + '</ol>';
  }
  if (er.length) {
    h += '<div class="ctx bad"><b>À éviter</b>' + er.map(e => esc(e)).join('<br>') + '</div>';
  }
  if (c.a_retenir) h += '<div class="keep">À retenir : ' + esc(c.a_retenir) + '</div>';
  h += '<div class="acts"><button class="say" data-t="' + esc(t) + '">' + ic('spk') + 'Écouter</button></div></article>';
  return h;
}
function vCult() {
  const l = (D && D.culture) || [];
  if (!l.length) return '<div class="empty">Les fiches de culture arrivent avec le brief du matin.</div>';
  return l.map(fiche).join('');
}

const jour = () => ((D && D.quiz_jour) || []).filter(q => q.type === 'actu');
function allQ() {
  const m = {};
  B.concat((D && D.quiz_jour) || []).forEach(q => { m[q.id] = q; });
  return m;
}
function weakN() {
  const st = store.get('stats', {});
  return Object.keys(allQ()).filter(i => st[i] && st[i].ko > st[i].ok).length;
}
function pickRev() {
  const st = store.get('stats', {});
  return Object.values(allQ()).map(q => {
    const s = st[q.id];
    let w = 2;
    if (s) w = s.ko > s.ok ? 4 : (s.ko > 0 && s.ok - s.ko < 2 ? 3 : 1);
    return {q: q, w: w + Math.random() * 1.5};
  }).sort((a, b) => b.w - a.w).slice(0, 10).map(x => x.q).sort(() => Math.random() - 0.5);
}
function start(mode) {
  let list, title;
  if (mode === 'jour') { list = jour(); title = 'Du jour'; }
  else if (mode === 'hasard') {
    list = Object.values(allQ()).sort(() => Math.random() - 0.5).slice(0, 10);
    title = 'Au hasard';
  } else { list = pickRev(); title = 'Révision'; }
  if (!list.length) return;
  store.set('qs', {list: list, i: 0, answers: [], done: false, counted: false, title: title});
  render();
  scrollTo(0, 0);
}
function bigBtn(a, icon, title, sub) {
  return '<button class="card big" data-a="' + a + '">' + ic(icon) + '<div><b>' + title + '</b><span>' + sub + '</span></div></button>';
}
function vQuiz() {
  const S = store.get('qs', null);
  if (!S) {
    const nj = jour().length;
    const nb = Object.keys(allQ()).length;
    const nw = weakN();
    let h = statsHTML() + '<h2>Choisis ton quiz</h2>';
    h += bigBtn('jour', 'day', 'Quiz du jour', nj ? nj + ' questions sur les infos du jour' : 'Disponible après la mise à jour du soir');
    h += bigBtn('hasard', 'rnd', 'Quiz au hasard', nb ? '10 questions parmi les ' + nb + ' depuis le début' : 'Pas encore de questions');
    if (nb >= 3) h += bigBtn('rev', 'rev', 'Révision', nw + ' question' + (nw > 1 ? 's' : '') + ' à retravailler');
    return h;
  }
  const L = S.list;
  if (S.done) {
    const sc = L.filter((q, k) => S.answers[k] === q.reponse).length;
    const pct = Math.round(sc / L.length * 100);
    let h = '<div class="card" style="text-align:center;margin-top:12px"><div class="meta">' + esc(S.title) + ' terminé</div>';
    h += '<div style="font-size:48px;font-weight:700;color:var(--ac)">' + sc + '/' + L.length + '</div><p>' + pct + ' % de bonnes réponses</p></div>';
    L.forEach((q, k) => {
      const ok = S.answers[k] === q.reponse;
      h += '<div class="card rec ' + (ok ? 'ok' : 'ko') + '"><b>' + (ok ? '✓' : '✗') + ' ' + esc(q.question) + '</b>';
      if (!ok) h += '<div class="sm">Bonne réponse : ' + esc(q.choix[q.reponse]) + '</div>';
      if (q.explication) h += '<div class="sm">' + esc(q.explication) + '</div>';
      h += '</div>';
    });
    return h + '<button class="nx" data-a="menu">Terminer</button>';
  }
  const q = L[S.i];
  const ch = S.answers[S.i];
  const ans = ch != null;
  let h = '<div class="meta" style="display:flex;justify-content:space-between"><span>' + esc(S.title) + ' · ' + (S.i + 1) + '/' + L.length + ' · ' + (q.type === 'actu' ? 'Actu' : 'Culture') + '</span>';
  h += '<button data-a="menu" class="sm">Quitter</button></div>';
  h += '<div class="prog"><i style="width:' + (S.i / L.length * 100) + '%"></i></div>';
  h += '<div class="q">' + esc(q.question) + '</div>';
  q.choix.forEach((c, k) => {
    let cls = '';
    if (ans) cls = k === q.reponse ? 'ok' : (k === ch ? 'bad' : '');
    h += '<button class="ch ' + cls + '" data-a="pick" data-k="' + k + '" ' + (ans ? 'disabled' : '') + '>' + esc(c) + '</button>';
  });
  if (ans) {
    h += '<div class="ctx"><b>' + (ch === q.reponse ? 'Bonne réponse' : 'Raté') + '</b>' + esc(q.explication || '');
    if (q.lien) h += ' <a href="' + esc(q.lien) + '" target="_blank" rel="noopener" style="color:var(--ac)">Lire</a>';
    h += '</div><button class="nx" data-a="next">' + (S.i + 1 >= L.length ? 'Voir mon résultat' : 'Question suivante') + '</button>';
  }
  return h;
}

function vSet() {
  const vs = frVoices();
  const cur = pickVoice();
  const r = store.get('rate', 0.95);
  let h = '<h2>Voix de lecture</h2><div class="card">';
  if (vs.length) {
    h += '<select id="vs">' + vs.map(v => '<option value="' + esc(v.voiceURI) + '" ' + (cur && cur.voiceURI === v.voiceURI ? 'selected' : '') + '>' + esc(v.name) + ' (' + esc(v.lang) + ')</option>').join('') + '</select>';
  } else {
    h += '<p class="sm">Aucune voix française détectée.</p>';
  }
  h += '<div class="sm">Vitesse</div><input type="range" id="rt" min="0.7" max="1.2" step="0.05" value="' + r + '">';
  h += '<div class="acts"><button class="say" data-t="Bonjour, voici un exemple de la voix qui te lira ton brief.">' + ic('spk') + 'Tester</button></div></div>';
  h += '<div class="card"><b>Voix plus naturelle</b><p class="sm" style="margin-top:6px">Réglages iPhone › Accessibilité › Contenu énoncé › Voix › Français, puis télécharge une voix « Améliorée » ou « Premium ». Recharge l\'app, puis choisis-la ici.</p></div>';
  h += '<h2>Statistiques</h2><div class="card"><p class="sm" style="margin:0 0 6px">Efface le camembert, le compteur et la progression de révision.</p><button class="nx alt" data-a="reset">Réinitialiser mes statistiques</button></div>';
  return h;
}

function render() {
  const tabs = [['actus', 'news', 'Actus'], ['culture', 'bulb', 'Culture'], ['quiz', 'quiz', 'Quiz'], ['reglages', 'set', 'Réglages']];
  $('#n').innerHTML = tabs.map(t => '<button data-tab="' + t[0] + '" class="' + (tab === t[0] ? 'on' : '') + '">' + ic(t[1]) + t[2] + '</button>').join('');
  $('#rf').innerHTML = ic('rf');
  let v;
  if (tab === 'actus') v = vActus();
  else if (tab === 'culture') v = vCult();
  else if (tab === 'quiz') v = vQuiz();
  else v = vSet();
  $('#m').innerHTML = v;
}

document.addEventListener('click', e => {
  if (e.target.closest('#rf')) { load(); return; }
  const s = e.target.closest('.say');
  if (s && s.dataset.t) { say(s.dataset.t, s); return; }
  const t = e.target.closest('[data-tab]');
  if (t) { tab = t.dataset.tab; stopSay(); render(); scrollTo(0, 0); return; }
  const a = e.target.closest('[data-a]');
  if (!a) return;
  const x = a.dataset.a;
  if (x === 'jour' || x === 'hasard' || x === 'rev') start(x);
  else if (x === 'menu') { store.set('qs', null); render(); scrollTo(0, 0); }
  else if (x === 'next') {
    const S = store.get('qs');
    if (S.i + 1 >= S.list.length) {
      S.done = true;
      if (!S.counted) { S.counted = true; countQuiz(); }
    } else { S.i++; }
    store.set('qs', S);
    render();
    scrollTo(0, 0);
  } else if (x === 'pick') {
    const S = store.get('qs');
    if (!S || S.answers[S.i] != null) return;
    const k = +a.dataset.k;
    S.answers[S.i] = k;
    record(S.list[S.i].id, k === S.list[S.i].reponse);
    store.set('qs', S);
    render();
  } else if (x === 'reset') {
    if (confirm('Effacer toutes tes statistiques de quiz ?')) {
      store.set('g', {answered:0, correct:0, quizzes:0});
      store.set('stats', {});
      store.set('qs', null);
      render();
    }
  }
});
document.addEventListener('change', e => {
  if (e.target.id === 'vs') store.set('voice', e.target.value);
  if (e.target.id === 'rt') store.set('rate', +e.target.value);
});

async function load() {
  const j = async f => {
    try {
      const r = await fetch('data/' + f + '?t=' + Date.now(), {cache: 'no-store'});
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  };
  D = await j('latest.json');
  const b = await j('quiz_bank.json');
  B = (b && b.questions) || [];
  let dt = '';
  if (D && D.date) {
    dt = new Date(D.date + 'T12:00:00').toLocaleDateString('fr-FR', {weekday:'long', day:'numeric', month:'long'});
  }
  $('#d').innerHTML = 'Brief<small>' + esc(dt) + (D && D.updated ? ' · maj ' + hm(D.updated) : '') + '</small>';
  render();
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
render();
load();
