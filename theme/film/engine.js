/* trureturing books · film engine (theme/film/engine.js)
   Adapted from the trureturing-film engine (films/<NNN>-<name>/engine.js, Apache-2.0, the-omega-institute).

   Deterministic 1920×1080 Canvas renderer: window.renderAt(t) draws the frame at time t (seconds) as a pure
   function of t, so frames can be captured in parallel and re-rendered identically. theme/film/build.py writes
   <film>/out/index.html with, in order:
     window.FILM_TOKENS  { film, font, sem }   palette and font stacks from theme/generated/tokens.mjs
     window.DATA         { timeline, film, book, lean, pin, names, strings, data, fonts, fontText }
     this file, then the film's scenes.js (SCENES.<scene id> = S => { … }), then `window.ready = boot()`.

   Colour semantics (theme/tokens.json "semantic"): C.lean (green) only for Lean-verified results, C.now
   (amber) for the current focus, C.open (red) for open problems, C.argued (violet) for argued claims that the
   kernel has not checked. Everything else uses cyan / magenta / white / dim. */
'use strict';

const W = 1920, H = 1080, TAU = Math.PI * 2;
const DATA = window.DATA;
const TL = DATA.timeline;
const FPS = (DATA.film && DATA.film.fps) || 30;
const TOK = window.FILM_TOKENS;
const cv = document.getElementById('c');
const ctx = cv.getContext('2d');

/* ---------- palette and fonts (from the design tokens) ---------- */
const C = Object.assign({}, TOK.film, { lean: TOK.sem.lean, open: TOK.sem.open, argued: TOK.sem.argued, now: TOK.sem.now });
const GENERIC = /^(serif|sans-serif|monospace|system-ui|ui-monospace|cursive|fantasy)$/;
/* `local` names fonts present on the Linux render machines (not design tokens); they go before the generic family. */
function stack(list, local = []) {
  const named = list.filter(f => !GENERIC.test(f)), generic = list.filter(f => GENERIC.test(f));
  return [...new Set([...named, ...local, ...generic])].map(f => (GENERIC.test(f) ? f : `"${f}"`)).join(', ');
}
const F = {
  orb: stack(TOK.font['film-display'], ['DejaVu Sans']),
  raj: stack(TOK.font['film-subtitle'], ['DejaVu Sans']),
  disp: stack(TOK.font.display, ['DejaVu Sans']),
  mono: stack(TOK.font.data, ['DejaVu Sans Mono']),
  zh: stack(TOK.font.body, ['Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'DejaVu Sans']),
  math: stack(['DejaVu Sans'].concat(TOK.font.data), ['FreeSerif'])
};
const STR = DATA.strings || { zh: {}, en: {} };

/* ---------- math & randomness ---------- */
const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
const lerp = (a, b, x) => a + (b - a) * x;
const ease = x => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const eo = x => { x = clamp(x); return 1 - Math.pow(1 - x, 3); };
const ei = x => { x = clamp(x); return x * x * x; };
function rnd(i, j = 0) { const x = Math.sin(i * 127.1 + j * 311.7 + 17.13) * 43758.5453; return x - Math.floor(x); }
function hexrgb(hex) { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
const rgba = (hex, a) => { const [r, g, b] = hexrgb(hex); return `rgba(${r},${g},${b},${a})`; };
/* mix two palette colours (k = 0 → a, 1 → b) */
function mix(a, b, k) { const p = hexrgb(a), q = hexrgb(b); return '#' + p.map((v, i) => Math.round(lerp(v, q[i], k)).toString(16).padStart(2, '0')).join(''); }
function rotY(p, a) { const c = Math.cos(a), s = Math.sin(a); return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c]; }
function rotX(p, a) { const c = Math.cos(a), s = Math.sin(a); return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c]; }
function rotZ(p, a) { const c = Math.cos(a), s = Math.sin(a); return [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]]; }
function proj(p, cx = W / 2, cy = H / 2, fov = 900, camZ = 5) {
  const z = p[2] + camZ; const k = fov / Math.max(z, 0.05);
  return [cx + p[0] * k, cy + p[1] * k, k, z];
}

/* ---------- scene timing ---------- */
/* SC[id] = { i, start, end, lines: [{ s, e, en, zh }] } with line times relative to the scene start. */
const SC = {};
TL.scenes.forEach((s, i) => {
  SC[s.id] = Object.assign({}, s, {
    i, lines: TL.lines.filter(l => l.scene === s.id).map(l => ({ s: l.start - s.start, e: l.end - s.start, en: l.en, zh: l.zh }))
  });
});
function lineAt(S, k) { return S.L[k] || { s: 1e9, e: 1e9, en: '', zh: '' }; }
/* progress (0→1) of a phase starting at line k plus `off` seconds, lasting `dur` seconds */
function at(S, k, dur = 1, off = 0) { return clamp((S.u - lineAt(S, k).s - off) / dur); }
function sinceStart(S, off, dur) { return clamp((S.u - off) / dur); }
/* progress from the moment `phrase` is spoken in line k (estimated by its character offset), plus `delay` */
const _phrase = new Map();
function phraseAt(S, k, phrase) {
  const L = lineAt(S, k); if (!L.en) return 1e9;
  const key = S.id + '|' + k + '|' + phrase; let off = _phrase.get(key);
  if (off == null) {
    const i = phrase ? L.en.indexOf(phrase) : 0;
    if (i < 0) phraseMissing(S, k, phrase);
    off = i < 0 ? 0 : i / L.en.length * (L.e - L.s); _phrase.set(key, off);
  }
  return L.s + off;
}
/* A phrase line k does not contain: timing falls back to the start of the line. A page error under FILM_STRICT=1 (the
   build), else a console warning; theme/film/build.py and ./tbook check report the literal ones before any render. */
function phraseMissing(S, k, phrase) {
  const msg = `film: SCENES.${S.id}: line ${k} of scene ${S.id} does not contain the phrase ${JSON.stringify(phrase)}; ` +
    'its timing falls back to the start of the line';
  if (DATA.strict) window.FILM_ERRORS.push(msg); else console.warn(msg);
}
function Q(S, k, phrase, dur = 0.5, delay = 0) { return clamp((S.u - phraseAt(S, k, phrase) - delay) / dur); }

/* ---------- offscreen resources ---------- */
function mk(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
const small = mk(480, 270), sctx = small.getContext('2d');
const buf = mk(W, H), bctx = buf.getContext('2d');
let nebula, scan, vign;
const grains = [], pearl = {};
const PEARLS = { c: 'cyan', m: 'mag', g: 'gold', w: 'white', o: 'orange', r: 'red', v: 'vio', n: 'green', b: 'blue' };
function buildResources() {
  nebula = mk(W, H); const n = nebula.getContext('2d');
  n.fillStyle = C.bg; n.fillRect(0, 0, W, H);
  const blobs = [[0.2, 0.3, 700, C.vio, 0.18], [0.82, 0.22, 600, C.mag, 0.1], [0.7, 0.8, 800, C.blue, 0.14],
    [0.3, 0.85, 520, C.cyan, 0.07], [0.5, 0.5, 900, mix(C.vio, C.bg, 0.7), 0.3]];
  for (const [x, y, r, c, a] of blobs) {
    const g = n.createRadialGradient(x * W, y * H, 0, x * W, y * H, r);
    g.addColorStop(0, rgba(c, a)); g.addColorStop(1, rgba(c, 0));
    n.fillStyle = g; n.fillRect(0, 0, W, H);
  }
  scan = mk(W, H); const s = scan.getContext('2d');
  for (let y = 0; y < H; y += 3) { s.fillStyle = 'rgba(0,0,0,0.2)'; s.fillRect(0, y, W, 1); }
  vign = mk(W, H); const v = vign.getContext('2d');
  const g = v.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 1.0);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,0.78)');
  v.fillStyle = g; v.fillRect(0, 0, W, H);
  for (let k = 0; k < 6; k++) {
    const gc = mk(480, 270), gx = gc.getContext('2d'); const im = gx.createImageData(480, 270);
    for (let i = 0; i < im.data.length; i += 4) {
      const r = rnd(i * 0.013 + k * 91.7, k) * 255;
      im.data[i] = im.data[i + 1] = im.data[i + 2] = r; im.data[i + 3] = 20;
    }
    gx.putImageData(im, 0, 0); grains.push(gc);
  }
  for (const [name, key] of Object.entries(PEARLS)) {
    const p = mk(64, 64), px = p.getContext('2d');
    const gr = px.createRadialGradient(26, 26, 1, 32, 32, 32);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.18, rgba(C[key], 0.95));
    gr.addColorStop(0.5, rgba(C[key], 0.35)); gr.addColorStop(1, rgba(C[key], 0));
    px.fillStyle = gr; px.fillRect(0, 0, 64, 64); pearl[name] = p;
  }
}

/* ---------- drawing helpers ---------- */
function font(w, size, fam) { ctx.font = `${w} ${size}px ${fam}`; }
/* text: o = { size, fam, w, c, a, align, base, ls (letter spacing px), ab (chromatic aberration px) } */
function txt(s, x, y, o = {}) {
  const size = o.size || 28, fam = o.fam || F.mono, w = o.w || 400, a = o.a == null ? 1 : o.a;
  if (a <= 0.003 || s === '' || s == null) return;
  ctx.save();
  font(w, size, fam); ctx.textAlign = o.align || 'left'; ctx.textBaseline = o.base || 'alphabetic';
  ctx.letterSpacing = (o.ls || 0) + 'px';
  if (o.ab) {
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = a * 0.7; ctx.fillStyle = C.mag; ctx.fillText(s, x - o.ab, y);
    ctx.fillStyle = C.cyan; ctx.fillText(s, x + o.ab, y);
    ctx.globalCompositeOperation = 'source-over';
  }
  ctx.globalAlpha = a; ctx.fillStyle = o.c || C.white; ctx.fillText(s, x, y);
  ctx.restore();
}
function tw(s, size, fam, w = 400, ls = 0) { ctx.save(); font(w, size, fam); ctx.letterSpacing = ls + 'px'; const m = ctx.measureText(s).width; ctx.restore(); return m; }
const GLY = 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#$%&@∀∃λ→↔¬∧∨⊢ℕℝ∑∏φ⟨⟩≤≥≠';
/* decode-in effect: characters settle left to right as p goes 0 → 1 */
function scramble(str, p, seed = 0) {
  let out = '';
  for (let i = 0; i < str.length; i++) {
    const th = 0.15 + 0.45 * (i / Math.max(1, str.length)) + 0.25 * rnd(i, seed);
    if (str[i] === ' ' || p >= th) out += str[i];
    else if (p > th - 0.35) out += GLY[Math.floor(rnd(i + Math.floor(p * 40), seed + 3) * GLY.length)];
    else out += ' ';
  }
  return out;
}
function typed(str, p) { return str.slice(0, Math.floor(clamp(p) * str.length)); }
function line(x1, y1, x2, y2, col, a = 1, w = 1.5) {
  if (a <= 0) return;
  ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.lineWidth = w;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.globalAlpha = 1;
}
function dashed(x1, y1, x2, y2, col, a, w = 2) { if (a <= 0) return; ctx.save(); ctx.setLineDash([10, 9]); line(x1, y1, x2, y2, col, a, w); ctx.restore(); }
function arrow(x1, y1, x2, y2, col, a, w = 2.5) {
  if (a <= 0) return;
  line(x1, y1, x2, y2, col, a, w);
  const an = Math.atan2(y2 - y1, x2 - x1), L = 14;
  line(x2, y2, x2 - L * Math.cos(an - 0.4), y2 - L * Math.sin(an - 0.4), col, a, w);
  line(x2, y2, x2 - L * Math.cos(an + 0.4), y2 - L * Math.sin(an + 0.4), col, a, w);
}
function ring(x, y, r, col, a, lw = 2) { if (a <= 0) return; ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.stroke(); ctx.globalAlpha = 1; }
function fillBox(x, y, w, h, col, a) { if (a <= 0) return; ctx.globalAlpha = a; ctx.fillStyle = col; ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1; }
/* rectangle with heavier corner brackets (the trureturing-film panel frame) */
function box(x, y, w, h, col, a = 1, lw = 1.5, fill = null) {
  if (a <= 0.003) return;
  ctx.globalAlpha = a;
  if (fill) { ctx.fillStyle = fill; ctx.fillRect(x, y, w, h); }
  ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.strokeRect(x, y, w, h);
  const k = Math.min(18, w / 4, h / 4); ctx.lineWidth = lw * 2.2;
  ctx.beginPath();
  ctx.moveTo(x, y + k); ctx.lineTo(x, y); ctx.lineTo(x + k, y);
  ctx.moveTo(x + w - k, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + k);
  ctx.moveTo(x + w, y + h - k); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - k, y + h);
  ctx.moveTo(x + k, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - k);
  ctx.stroke(); ctx.globalAlpha = 1;
}
/* cut-corner path (top-right and bottom-left corners cut by k), as theme tokens' --tr-fx-cut-corner */
function cutPath(x, y, w, h, k = 16) {
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w - k, y); ctx.lineTo(x + w, y + k); ctx.lineTo(x + w, y + h);
  ctx.lineTo(x + k, y + h); ctx.lineTo(x, y + h - k); ctx.closePath();
}
/* cut-corner panel with corner brackets and an optional title strip */
function panel(x, y, w, h, a, col = C.cyan, title = null, o = {}) {
  if (a <= 0.003) return;
  const k = o.cut == null ? 16 : o.cut;
  ctx.save(); ctx.globalAlpha = a;
  cutPath(x, y, w, h, k); ctx.fillStyle = o.fill || 'rgba(4,10,24,0.74)'; ctx.fill();
  ctx.strokeStyle = rgba(col, 0.7); ctx.lineWidth = 1.2; ctx.stroke();
  ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.beginPath();
  const b = 22;
  ctx.moveTo(x, y + b); ctx.lineTo(x, y); ctx.lineTo(x + b, y);
  ctx.moveTo(x + w - b, y + h); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w, y + h - b);
  ctx.stroke();
  if (title) {
    ctx.save(); cutPath(x, y, w, h, k); ctx.clip();
    ctx.fillStyle = rgba(col, 0.16); ctx.fillRect(x, y, w, 32); ctx.restore();
  }
  ctx.restore();
  if (title) txt(title, x + 16, y + 22, { size: 15, fam: F.mono, c: col, a, w: 700, ls: 2 });
}
/* a framed label: centred text in a small bracketed box */
function chip(x, y, w, h, s, col, a, size = 24, fam = F.mono) {
  if (a <= 0) return;
  box(x - w / 2, y - h / 2, w, h, col, a, 2, 'rgba(0,0,0,0.5)');
  txt(s, x, y + size * 0.36, { size, fam, w: 700, align: 'center', c: col, a });
}
function dot(x, y, r, name = 'c', a = 1) {
  if (a <= 0.003 || r <= 0.2) return;
  ctx.globalAlpha = a; ctx.drawImage(pearl[name] || pearl.c, x - r, y - r, r * 2, r * 2); ctx.globalAlpha = 1;
}
/* a rubber stamp that slams in as p goes 0 → 1 */
function stamp(s, x, y, p, col = C.open, size = 64, rot = -0.08) {
  if (p <= 0) return;
  const k = 1 + 1.6 * (1 - eo(p)); const a = clamp(p * 3);
  ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(k, k);
  const w = tw(s, size, F.orb, 900, 6) + 60;
  ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.lineWidth = 5; ctx.strokeRect(-w / 2, -size * 0.85, w, size * 1.35);
  ctx.lineWidth = 1.5; ctx.strokeRect(-w / 2 + 9, -size * 0.85 + 9, w - 18, size * 1.35 - 18);
  ctx.restore();
  ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(k, k);
  txt(s, 0, size * 0.33, { size, fam: F.orb, w: 900, c: col, a, align: 'center', ab: 3, ls: 6 });
  ctx.restore();
}
function curve(fn, n, col, a, lw = 3) {
  if (a <= 0) return;
  ctx.globalAlpha = a; ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.beginPath();
  for (let i = 0; i <= n; i++) { const [x, y] = fn(i / n); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }
  ctx.stroke(); ctx.globalAlpha = 1;
}

/* ---------- hypercubes (title cards, posters) ---------- */
function hypercube(n) {
  const V = [], E = [];
  for (let i = 0; i < (1 << n); i++) { const v = []; for (let b = 0; b < n; b++) v.push((i >> b) & 1 ? 1 : -1); V.push(v); }
  for (let i = 0; i < V.length; i++) for (let b = 0; b < n; b++) { const j = i ^ (1 << b); if (j > i) E.push([i, j]); }
  return { V, E };
}
const CUBE4 = hypercube(4), CUBE5 = hypercube(5);
function rotN(v, a, b, ang) { const c = Math.cos(ang), s = Math.sin(ang); const x = v[a], y = v[b]; v[a] = x * c - y * s; v[b] = x * s + y * c; }
function projN(v0, planes, dist = 3.2) {
  const v = v0.slice();
  for (const [a, b, ang] of planes) rotN(v, a, b, ang);
  let p = v;
  while (p.length > 3) { const w = p[p.length - 1]; const k = dist / (dist - w * 0.55); p = p.slice(0, -1).map(x => x * k); }
  return p;
}
function drawHyper(cube, planes, o) {
  const P = cube.V.map(v => {
    let p = projN(v, planes, o.dist || 3.2);
    p = rotY(rotX(p, o.rx || 0), o.ry || 0);
    return proj(p.map(x => x * (o.scale || 1)), o.cx || W / 2, o.cy || H / 2, o.fov || 900, o.camZ || 6);
  });
  const a0 = o.a == null ? 1 : o.a;
  ctx.globalCompositeOperation = 'lighter';
  ctx.lineWidth = o.lw || 2;
  for (let e = 0; e < cube.E.length; e++) {
    const [i, j] = cube.E[e]; const a = P[i], b = P[j];
    const depth = clamp((a[2] + b[2]) / 2 / 260, 0.25, 1.4);
    ctx.globalAlpha = a0 * 0.55 * depth;
    ctx.strokeStyle = (e % 3 === 0) ? (o.c2 || C.mag) : (o.c || C.cyan);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  if (o.dots !== false) for (const p of P) dot(p[0], p[1], 5 + p[2] * 0.02, 'w', a0 * 0.9);
  ctx.globalCompositeOperation = 'source-over';
  return P;
}

/* ---------- background ---------- */
const STARS = [];
for (let i = 0; i < 700; i++) STARS.push([rnd(i, 1) * 2 - 1, rnd(i, 2) * 2 - 1, rnd(i, 3), rnd(i, 4)]);
/* star-field speed per scene id (films may set FILM.speed[id]) */
const FILM = { init: [], speed: {}, names: Object.assign({}, DATA.names || {}), poster: null, hud: true };
const starPhase = [];
function computeStarPhase() {
  starPhase.length = 0; let acc = 0;
  for (const s of TL.scenes) { starPhase.push(acc); acc += (FILM.speed[s.id] || 0.02) * (s.end - s.start); }
}
function background(t, sc, si, u) {
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  ctx.save(); ctx.translate(W / 2, H / 2); ctx.rotate(Math.sin(t * 0.02) * 0.05); ctx.scale(1.25 + 0.05 * Math.sin(t * 0.013), 1.25); ctx.globalAlpha = 0.9;
  ctx.drawImage(nebula, -W / 2, -H / 2, W, H); ctx.restore();
  const z0 = (starPhase[si] || 0) + (FILM.speed[sc.id] || 0.02) * u;
  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < STARS.length; i++) {
    const s = STARS[i]; let z = (s[2] - z0) % 1; if (z < 0) z += 1; z = z + 0.02;
    const x = W / 2 + s[0] * W * 0.55 / z, y = H / 2 + s[1] * H * 0.55 / z;
    if (x < 0 || x > W || y < 0 || y > H) continue;
    const r = clamp(1.8 / z * 0.3, 0.4, 3.2); const a = clamp((1 - z) * 1.2) * (0.4 + 0.6 * s[3]);
    ctx.globalAlpha = a; ctx.fillStyle = s[3] > 0.85 ? C.mag : s[3] > 0.7 ? C.cyan : C.white;
    ctx.fillRect(x, y, r, r);
  }
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
}
/* synthwave floor grid below the horizon hy */
function grid(t, a = 0.5, hy = H * 0.64, col = C.mag, speed = 0.3) {
  if (a <= 0) return;
  ctx.save(); ctx.globalCompositeOperation = 'lighter';
  const g = ctx.createLinearGradient(0, hy, 0, H); g.addColorStop(0, rgba(col, 0)); g.addColorStop(1, rgba(col, 0.9 * a));
  ctx.strokeStyle = g; ctx.lineWidth = 1.5;
  for (let i = -24; i <= 24; i++) { ctx.beginPath(); ctx.moveTo(W / 2 + i * 12, hy); ctx.lineTo(W / 2 + i * 260, H + 40); ctx.stroke(); }
  const ph = (t * speed) % 1;
  for (let k = 0; k < 16; k++) { const z = (k + 1 - ph); const y = hy + 1400 / (z * z + 3.5) * z * 0.9; if (y > H) continue; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  ctx.restore();
}

/* ---------- solid shots: lit solids drawn by the modelling core of the visualizations ---------- */
/* A film whose film.json says "solid": true gets theme/viz/solid-core.js (and the pinned three.js it imports) next to
   its page; boot() imports it and makes one WebGL renderer on an offscreen canvas (pixel ratio 1, antialiasing on, a
   fixed size per shot). solid(key, rect) returns the shot `key`: the primitives of kit.solid (surface, poly, glass,
   tube, line, arrow, ring, bead, fan) between begin() and end(a); end() draws the solid synchronously and composites it
   into the frame with drawImage, so whatever the scene draws after it (labels, panels, chips, stamps) and the
   subtitles lie on top. p(v) / anchor(v) project a world point to frame pixels; anchor(v).hidden is true when a
   surface or polyhedron of the shot is in front of it. No clock, animation loop or randomness: the frame stays a pure
   function of t. Without WebGL the page fails to boot (no fallback), so a film with solid shots never renders blind. */
const SOLID = { core: null, renderer: null, shots: new Map() };
const SOLID_PALETTE = { stage: C.bg, ink: C.white, cyan: C.cyan, magenta: C.mag, violet: C.vio, amber: C.now, dim: C.dim,
  lean: C.lean, blue: C.blue, orange: C.orange };
async function solidInit() {
  const id = (DATA.film && DATA.film.id) || 'film';
  try {
    SOLID.core = await import(new URL(DATA.solid.core, location.href).href);
  } catch (e) {
    throw new Error(`film ${id}: cannot load the modelling core ${DATA.solid.core} (${e && e.message})`);
  }
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2', { antialias: true, alpha: true, preserveDrawingBuffer: true });
  if (!gl) throw new Error(`film ${id} has solid shots ("solid": true in film.json) but this browser cannot create a WebGL ` +
    'context: run Chromium with WebGL enabled (theme/film/lib.js starts it with SwiftShader, ' +
    '--enable-unsafe-swiftshader; ./tbook doctor checks it); there is no fallback');
  SOLID.renderer = SOLID.core.createRenderer(canvas, { pixelRatio: 1 });
}
function makeShot(key) {
  const sc = SOLID.core.createScene({ palette: SOLID_PALETTE });
  const sh = { key, x: 0, y: 0, w: 1, h: 1, scene: sc };
  for (const name of ['surface', 'poly', 'glass', 'tube', 'line', 'arrow', 'ring', 'bead', 'fan']) sh[name] = (...a) => sc[name](...a);
  sh.begin = () => { sc.begin(); return sh; };
  /* draw the solid now and composite it at the shot's rectangle with opacity a */
  sh.end = (a = 1) => {
    sc.end(); sc.render(SOLID.renderer);
    if (a > 0.003) { ctx.save(); ctx.globalAlpha = a; ctx.drawImage(SOLID.renderer.domElement, sh.x, sh.y, sh.w, sh.h); ctx.restore(); }
    return sh;
  };
  /* world point → [x, y, depth] in frame pixels */
  sh.p = v => { const q = sc.p(v); return [sh.x + q[0], sh.y + q[1], q[2]]; };
  sh.occluded = (v, eps = 0.02) => sc.occluded(v, eps);
  /* where a 2D label should go: { x, y, depth, hidden } (hidden: a solid of this shot is in front of the point) */
  sh.anchor = (v, eps = 0.02) => { const q = sh.p(v); return { x: q[0], y: q[1], depth: q[2], hidden: sc.occluded(v, eps) }; };
  sh.marks = () => sc.marks().map(m => Object.assign(m, { x: sh.x + m.x, y: sh.y + m.y }));
  return sh;
}
/* solid(key, { x, y, w, h, yaw, pitch, zoom, radius | unit, cx, cy, lw }) → the shot, its camera set for this frame.
   x, y, w, h: the rectangle in the 1920×1080 frame; the camera options are those of kit.solid / kit.stage3. */
function solid(key, o = {}) {
  if (!SOLID.renderer) throw new Error(`solid('${key}'): this film has no solid shots; set "solid": true in film.json`);
  let sh = SOLID.shots.get(key);
  if (!sh) { sh = makeShot(key); SOLID.shots.set(key, sh); }
  sh.x = Math.round(o.x || 0); sh.y = Math.round(o.y || 0); sh.w = Math.round(o.w || W); sh.h = Math.round(o.h || H);
  sh.scene.camera(Object.assign({}, o, { W: sh.w, H: sh.h }));
  return sh;
}

/* ======================================================================= */
/*                     SCENES (registered by scenes.js)                    */
/* ======================================================================= */
const SCENES = {};
/* the safe area for scene content: clear of the HUD (top) and the subtitles (bottom) */
const SAFE = { x0: 120, x1: W - 120, y0: 165, y1: 840 };

/* Status banner, top centre. kind: lean (green) | open (red) | argued / theory (violet) | computed (cyan). */
const BADGES = {
  lean: ['badge_lean', 'lean', 'LEAN ✓'],
  open: ['badge_open', 'open', 'OPEN'],
  argued: ['badge_argued', 'argued', 'ARGUED'],
  theory: ['badge_argued', 'argued', 'ARGUED'],
  computed: ['badge_computed', 'cyan', 'NUM']
};
function badge(a, kind) {
  if (a <= 0.01) return;
  const spec = BADGES[kind] || BADGES.computed;
  const col = C[spec[1]];
  const head = kind === 'lean' ? (STR.en.lean || 'LEAN ✓') : kind === 'open' ? (STR.en.open || 'OPEN') : spec[2];
  const en = STR.en[spec[0]] || '', zh = STR.zh[spec[0]] || '';
  const wHead = tw(head, 16, F.mono, 700, 2), wEn = tw(en, 15, F.mono, 700, 2), wZh = tw(zh, 17, F.zh, 700, 1);
  const pad = 22, gap = 22, w = pad * 2 + wHead + gap + wEn + gap + wZh, x = W / 2 - w / 2, y = 112;
  ctx.save(); ctx.globalAlpha = a;
  cutPath(x, y, w, 32, 10); ctx.fillStyle = rgba(mix(col, C.bg, 0.86), 0.82); ctx.fill();
  ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.stroke();
  ctx.fillStyle = col; ctx.fillRect(x, y, pad + wHead + gap / 2, 32);
  ctx.restore();
  txt(head, x + pad, y + 22, { size: 16, fam: F.mono, w: 700, c: C.bg, a, ls: 2 });
  txt(en, x + pad + wHead + gap, y + 22, { size: 15, fam: F.mono, w: 700, c: col, a, ls: 2 });
  txt(zh, x + pad + wHead + gap + wEn + gap, y + 23, { size: 17, fam: F.zh, w: 700, c: col, a, ls: 1 });
}
/* seq = [[line index, phrase | null, kind], …]: show the latest entry that has started */
function badgeQ(S, seq) {
  let cur = seq[0], st = 0;
  seq.forEach(e => { const s0 = e[0] === 0 && !e[1] ? 0 : phraseAt(S, e[0], e[1]); if (S.u >= s0) { cur = e; st = s0; } });
  badge(clamp((S.u - st) / 0.5) * clamp(S.u / 0.8) * clamp((S.d - S.u) / 0.5), cur[2]);
}
/* LEAN ✓ declaration chips: the film's citations (DATA.lean) at the pinned commit. Only theorems get the green
   chip (./tbook check refuses any other kind in film.json "lean"). Each shows r.label: the full Lean name, or the GID
   when the declaration's namespace would name another module (tbook.film.cited_label). */
/* the citation of one GID (film.json "lean"), or null: look citations up by the whole GID, not by the short name */
function leanCite(gid) { return (DATA.lean || []).find(z => z.gid === gid) || null; }
function leanList(x, y, a, o = {}) {
  if (a <= 0) return y;
  const size = o.size || 22, gap = o.gap || 44, align = o.align || 'left';
  for (const r of DATA.lean.filter(z => z.kind === 'theorem')) {
    const name = r.label || r.name;
    const head = STR.en.lean || 'LEAN ✓', wh = tw(head, size * 0.72, F.mono, 700, 1) + 18, wn = tw(name, size, F.mono, 700);
    const total = wh + 14 + wn, x0 = align === 'center' ? x - total / 2 : x;
    fillBox(x0, y - size * 0.95, wh, size * 1.25, C.lean, a * 0.95);
    txt(head, x0 + 9, y - size * 0.12, { size: size * 0.72, fam: F.mono, w: 700, c: C.bg, a, ls: 1 });
    txt(name, x0 + wh + 14, y, { size, fam: F.mono, w: 700, c: C.lean, a });
    y += gap;
  }
  return y;
}
/* end card: book code and titles, film title, Lean citations and the pinned commit; o: from (seconds into the scene),
   y (top line), x (centre, default the frame's), hyper (false: no hypercube behind it) */
function closingCard(S, o = {}) {
  const from = o.from || 0, a = clamp((S.u - from) / 1.0) * clamp((S.d - S.u) / 1.2);
  if (a <= 0) return;
  const b = DATA.book, f = DATA.film, cy = o.y || 300, cx = o.x || W / 2;
  if (o.hyper !== false) drawHyper(CUBE4, [[0, 3, S.t * 0.21], [1, 2, S.t * 0.13], [2, 3, S.t * 0.17]], { scale: 1.2, a: 0.35 * a, cx, cy: cy - 30, camZ: 7, lw: 1.4, dots: false });
  txt(b.code, cx, cy - 70, { size: 26, fam: F.mono, w: 700, align: 'center', c: C.cyan, a, ls: 10 });
  txt(b.title.zh, cx, cy + 20, { size: 78, fam: F.zh, w: 900, align: 'center', c: C.white, a, ab: 3 });
  txt(b.title.en, cx, cy + 90, { size: 40, fam: F.disp, w: 700, align: 'center', c: C.white, a: a * 0.92, ls: 2 });
  const p2 = clamp((S.u - from - 0.8) / 0.8) * a;
  txt(`${(STR.en.film || 'FILM').toUpperCase()} ${f.number} · ${f.title.toUpperCase()}`, cx, cy + 165, { size: 22, fam: F.mono, w: 700, align: 'center', c: C.mag, a: p2, ls: 3 });
  txt(f.title_zh, cx, cy + 205, { size: 26, fam: F.zh, w: 700, align: 'center', c: C.white, a: p2 * 0.85 });
  const p3 = clamp((S.u - from - 1.6) / 0.8) * a;
  const y = leanList(cx, cy + 290, p3, { align: 'center', size: 24, gap: 46 });
  const pin = DATA.pin || {};
  if (pin.commit) txt(`github.com/${pin.repo} @ ${pin.commit.slice(0, 12)}`, cx, y + 16, { size: 20, fam: F.mono, align: 'center', c: C.dim, a: p3, ls: 1 });
}
/* placeholder for a scene of script.json that scenes.js does not define */
function missingScene(S) {
  panel(W / 2 - 560, 380, 1120, 220, 1, C.open, 'SCENES.JS');
  txt(`SCENES.${S.id} is not defined`, W / 2, 495, { size: 44, fam: F.mono, w: 700, align: 'center', c: C.open });
  txt('add it to the film\'s scenes.js', W / 2, 550, { size: 24, fam: F.mono, align: 'center', c: C.white });
}

/* ---------- post-processing, HUD, subtitles ---------- */
function bloom(strength = 0.62) {
  sctx.globalCompositeOperation = 'source-over'; sctx.filter = 'none';
  sctx.clearRect(0, 0, 480, 270);
  sctx.filter = 'blur(5px)'; sctx.drawImage(cv, 0, 0, 480, 270); sctx.filter = 'none';
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = strength; ctx.drawImage(small, 0, 0, W, H); ctx.restore();
}
function sceneName(id) { return FILM.names[id] || id.toUpperCase(); }
function hud(t, f, si, s) {
  const a = 0.75;
  ctx.globalAlpha = a; ctx.strokeStyle = C.cyan; ctx.lineWidth = 2;
  const m = 34, k = 46;
  ctx.beginPath();
  ctx.moveTo(m, m + k); ctx.lineTo(m, m); ctx.lineTo(m + k, m);
  ctx.moveTo(W - m - k, m); ctx.lineTo(W - m, m); ctx.lineTo(W - m, m + k);
  ctx.moveTo(W - m, H - m - k); ctx.lineTo(W - m, H - m); ctx.lineTo(W - m - k, H - m);
  ctx.moveTo(m + k, H - m); ctx.lineTo(m, H - m); ctx.lineTo(m, H - m - k);
  ctx.stroke(); ctx.globalAlpha = 1;
  const book = DATA.book || {}, film = DATA.film || {}, pin = DATA.pin || {};
  txt(`${book.code || 'TRURETURING'} · ${(STR.en.film || 'FILM').toUpperCase()} ${film.number || ''}`, 60, 72, { size: 16, fam: F.mono, w: 700, c: C.cyan, a: 0.8, ls: 2 });
  txt(`SEQ ${String(si + 1).padStart(2, '0')}/${String(TL.scenes.length).padStart(2, '0')} · ${sceneName(s.id)}`, 60, 96, { size: 14, fam: F.mono, w: 700, c: C.mag, a: 0.9, ls: 2 });
  const tc = x => String(Math.floor(x)).padStart(2, '0');
  txt(`T+${tc(t / 60)}:${tc(t % 60)}:${tc((t * FPS) % FPS)}`, W - 60, 72, { size: 16, fam: F.mono, w: 700, c: C.cyan, a: 0.8, align: 'right', ls: 2 });
  if (pin.commit) txt(`TRURETURING@${pin.commit.slice(0, 8)} · ${STR.en.pinned || 'PINNED'}`, W - 60, 96, { size: 14, fam: F.mono, w: 700, c: C.cyan, a: 0.6, align: 'right', ls: 1 });
  /* right edge: statement digests of the cited Lean modules, scrolling */
  const ids = (DATA.lean || []).map(r => (r.statement_id || '').replace(/^sha256:/, '')).filter(Boolean);
  if (ids.length) {
    font(400, 12, F.mono); ctx.textAlign = 'right'; ctx.fillStyle = C.cyan;
    const off = Math.floor(t * 6);
    for (let r = 0; r < 18; r++) {
      const hsh = ids[(r + off) % ids.length], o = ((r + off) * 7) % Math.max(1, hsh.length - 16);
      ctx.globalAlpha = 0.16; ctx.fillText(hsh.slice(o, o + 16), W - 58, 170 + r * 20);
    }
    ctx.globalAlpha = 1;
  }
  /* reticle and level meter, bottom left */
  const rx = 80, ry = H - 110;
  ctx.globalAlpha = 0.6; ctx.strokeStyle = C.cyan; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(rx, ry, 26, t * 1.5, t * 1.5 + 4.5); ctx.stroke();
  ctx.beginPath(); ctx.arc(rx, ry, 16, -t * 2.2, -t * 2.2 + 3.5); ctx.stroke(); ctx.globalAlpha = 1;
  for (let i = 0; i < 7; i++) { const h = 4 + 18 * Math.abs(Math.sin(t * 3 + i * 0.9) * Math.sin(t * 1.7 + i)); ctx.globalAlpha = 0.5; ctx.fillStyle = i % 3 ? C.cyan : C.mag; ctx.fillRect(116 + i * 6, ry + 12 - h, 4, h); }
  ctx.globalAlpha = 1;
}
/* line breaking for subtitles: CJK per character (Latin runs kept whole), Latin per word */
function wrap(s, size, fam, w, maxW) {
  const cjk = /[㐀-鿿豈-﫿]/.test(s);
  const words = cjk ? (s.match(/[A-Za-zÀ-ÿ0-9/()+\-−=_.^·²³⁴⁵⁶⁷⁸⁹⁰⁻ⁿ₀-₉√|α-ωΑ-Ω∞≤≥⊥'\[\]{}]+|[\s\S]/g) || []) : s.split(' ');
  const sep = cjk ? '' : ' ';
  const lines = []; let cur = '';
  for (const wd of words) {
    const tr = cur ? cur + sep + wd : wd;
    if (tw(tr, size, fam, w) > maxW && cur) { lines.push(cur.trimEnd()); cur = wd.trim() ? wd : ''; } else cur = tr;
  }
  if (cur) lines.push(cur);
  for (let i = 1; i < lines.length; i++) {
    if (/^[，。、；：！？”）》」』]/.test(lines[i])) { lines[i - 1] += lines[i][0]; lines[i] = lines[i].slice(1); }
    if (/[“（《「『]$/.test(lines[i - 1])) { lines[i] = lines[i - 1].slice(-1) + lines[i]; lines[i - 1] = lines[i - 1].slice(0, -1); }
  }
  return lines.filter(l => l.length);
}
const SUBS = { zh: true, en: true };
(DATA.film && DATA.film.subtitles ? ['zh', 'en'] : []).forEach(l => { SUBS[l] = DATA.film.subtitles.includes(l); });
const SUB_EN = mix(C.cyan, C.white, 0.55);
function subtitles(t) {
  const l = TL.lines.find(x => t >= x.start - 0.15 && t <= x.end + 0.35);
  if (!l) return;
  const a = clamp((t - (l.start - 0.15)) / 0.15) * clamp((l.end + 0.35 - t) / 0.2);
  const zh = SUBS.zh ? wrap(l.zh, 40, F.zh, 700, 1500) : [];
  const en = SUBS.en ? wrap(l.en, 27, F.raj, 600, 1560) : [];
  if (!zh.length && !en.length) return;
  const h = zh.length * 52 + en.length * 33 + 26;
  const y0 = H - 46 - h;
  const bw = Math.max(...zh.map(s => tw(s, 40, F.zh, 700)), ...en.map(s => tw(s, 27, F.raj, 600)), 200) + 70;
  ctx.globalAlpha = 0.55 * a; ctx.fillStyle = '#000'; ctx.fillRect(W / 2 - bw / 2, y0, bw, h); ctx.globalAlpha = 1;
  line(W / 2 - bw / 2, y0, W / 2 - bw / 2, y0 + h, C.cyan, a * 0.9, 3);
  line(W / 2 + bw / 2, y0, W / 2 + bw / 2, y0 + h, C.mag, a * 0.9, 3);
  let y = y0 + 50;
  zh.forEach(s => { txt(s, W / 2, y, { size: 40, fam: F.zh, w: 700, align: 'center', c: C.white, a }); y += 52; });
  if (!zh.length) y -= 12; else y -= 8;
  en.forEach(s => { txt(s, W / 2, y + 4, { size: 27, fam: F.raj, w: 600, align: 'center', c: SUB_EN, a: a * 0.96 }); y += 33; });
}
function post(f) {
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  ctx.drawImage(scan, 0, 0);
  ctx.drawImage(vign, 0, 0);
  ctx.globalCompositeOperation = 'overlay'; ctx.drawImage(grains[((f % grains.length) + grains.length) % grains.length], 0, 0, W, H);
  ctx.globalCompositeOperation = 'source-over';
}
/* RGB-split tears at scene cuts plus rare micro glitches (theme/film/music.py adds the matching sound) */
function glitchAmount(t) {
  let g = 0;
  for (let i = 1; i < TL.scenes.length; i++) { const d = t - TL.scenes[i].start; if (d > -0.3 && d < 0.45) g = Math.max(g, 1 - Math.abs(d - 0.05) / 0.4); }
  const slot = Math.floor(t / 0.2); if (rnd(slot, 77) > 0.965) g = Math.max(g, 0.3);
  return clamp(g);
}
function glitch(t, f) {
  const g = glitchAmount(t); if (g <= 0.02) return;
  bctx.globalCompositeOperation = 'copy'; bctx.drawImage(cv, 0, 0); bctx.globalCompositeOperation = 'source-over';
  const n = Math.floor(4 + g * 18);
  for (let i = 0; i < n; i++) {
    const y = Math.floor(rnd(f, i) * H), h = Math.floor(4 + rnd(f, i + 50) * 70 * g), dx = (rnd(f, i + 90) - 0.5) * 180 * g;
    ctx.drawImage(buf, 0, y, W, h, dx, y, W, h);
    if (rnd(f, i + 130) > 0.7) { ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = 0.25 * g; ctx.fillStyle = rnd(f, i + 170) > 0.5 ? C.mag : C.cyan; ctx.fillRect(0, y, W, h); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; }
  }
  ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = 0.35 * g; ctx.drawImage(buf, 10 * g, 0, W, H, 0, 0, W, H); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
}

function sceneIndex(t) {
  let si = TL.scenes.findIndex(s => t >= s.start && t < s.end);
  if (si < 0) si = t < 0 ? 0 : TL.scenes.length - 1;
  return si;
}
function sceneState(t, si) {
  const s = TL.scenes[si];
  const u = t - s.start, d = s.end - s.start;
  return { u, d, p: u / d, L: SC[s.id].lines, t, f: Math.round(t * FPS), id: s.id, i: si };
}
function resetCtx() { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; ctx.filter = 'none'; ctx.letterSpacing = '0px'; }

function renderAt(t) {
  const f = Math.round(t * FPS);
  const si = sceneIndex(t), s = TL.scenes[si], S = sceneState(t, si);
  resetCtx();
  background(t, s, si, S.u);
  ctx.save();
  (SCENES[s.id] || missingScene)(S);
  ctx.restore(); resetCtx();
  /* cross-dip between scenes */
  const fade = Math.min(clamp(S.u / 0.45), clamp((S.d - S.u) / 0.45));
  if (fade < 1) { ctx.globalAlpha = (1 - fade) * 0.85; ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
  bloom();
  if (FILM.hud) hud(t, f, si, s);
  subtitles(t);
  post(f);
  glitch(t, f);
  /* global fade in/out */
  const gIn = clamp(t / 0.8), gOut = clamp((TL.duration - t) / 1.2);
  if (gIn < 1 || gOut < 1) { ctx.globalAlpha = 1 - Math.min(gIn, gOut); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
}

/* Default poster: film and book titles over a hypercube; films may set FILM.poster = () => { … }. */
function defaultPoster() {
  const t = 23.7, si = Math.min(1, TL.scenes.length - 1);
  resetCtx();
  background(t, TL.scenes[si], si, 4);
  drawHyper(CUBE5, [[0, 4, t * 0.21], [1, 3, t * 0.17], [2, 4, t * 0.13], [3, 4, t * 0.19], [0, 2, t * 0.07]], { scale: 2.0, rx: 0.3, ry: t * 0.05, a: 0.45, lw: 1.4, camZ: 7, cy: H / 2 - 40 });
  grid(t, 0.6);
  const b = DATA.book, f = DATA.film;
  txt(f.title_zh, W / 2, 300, { size: 84, fam: F.zh, w: 900, align: 'center', c: C.white, ab: 4 });
  txt(f.title.toUpperCase(), W / 2, 420, { size: 64, fam: F.orb, w: 900, align: 'center', c: C.white, ab: 5, ls: 6 });
  bloom(0.65);
  txt(`${b.code} · ${(STR.en.film || 'FILM').toUpperCase()} ${f.number}`, W / 2, 520, { size: 30, fam: F.mono, w: 700, align: 'center', c: C.cyan, ls: 8 });
  leanList(W / 2, 680, 1, { align: 'center', size: 26, gap: 50 });
  txt(`${b.title.zh} · ${b.title.en}`, W / 2, 960, { size: 32, fam: F.zh, w: 700, align: 'center', c: C.cyan });
  hud(t, 711, si, TL.scenes[si]);
  post(3);
}
function poster() { resetCtx(); (FILM.poster || defaultPoster)(); }

/* Called once after scenes.js has loaded: fonts, resources, the film's init hooks. */
window.FILM_ERRORS = window.FILM_ERRORS || [];
async function boot() {
  const text = DATA.fontText || 'ABCabc0123';
  const faces = DATA.fonts || [];
  await Promise.all(faces.map(([fam, w]) => document.fonts.load(`${w} 40px "${fam}"`, text).catch(e => { window.FILM_ERRORS.push(`font ${fam} ${w}: ${e}`); })));
  await document.fonts.ready;
  if (DATA.solid) await solidInit();
  buildResources();
  computeStarPhase();
  for (const fn of FILM.init) fn();
  for (const s of TL.scenes) if (!SCENES[s.id]) console.warn(`film: SCENES.${s.id} is not defined in scenes.js`);
  return true;
}
window.renderAt = renderAt;
window.poster = poster;
window.SUBS = SUBS;
window.FILM = FILM;
window.solid = solid;
