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
rf:'<path d="M20 12a8 8 0 1 1-2.5-5.8M20 4v4h-4"/>',
chev:'<path d="M6 9l6 6 6-6"/>'
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
const hash = s => {
  s = String(s);
  let n = 0;
  for (let i = 0; i < s.length; i++) n = (n * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(n);
};
let D = null, B = [], tab = 'actus', tok = 0, queue = [], O = {};

/* ---- Images : celles des articles (ou de Wikipédia), rien si absentes ---- */
const ill = img => img ? '<div class="ill" data-src="' + esc(img) + '"></div>' : '';
function fillImgs(root) {
  root.querySelectorAll('.ill:not(.ld)').forEach(d => {
    const f = d.closest('.fold');
    if (f && !f.classList.contains('open')) return;
    d.classList.add('ld');
    const im = new Image();
    im.alt = '';
    im.referrerPolicy = 'no-referrer';
    im.onload = () => d.classList.add('ok');
    im.onerror = () => d.remove();
    im.src = d.dataset.src;
    d.appendChild(im);
  });
}
function toggleFold(el) {
  if (!el) return;
  const on = el.classList.toggle('open');
  if (el.dataset.id) O[el.dataset.id] = on;
  if (on) fillImgs(el);
}

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
function n
