/* Film 001 · The Golden Deficit · 黄金亏量 (book example-monograph, chapter 1).
   Scenes for theme/film/engine.js. Everything on screen is computed here, exactly, from the definitions that
   trureturing formalizes (D5/S1/Digit/Normalize.lean, D5/S1/Deficit/DeficitInteger.lean):
     weights W_i = F_{i+2} (1, 2, 3, 5, 8, …), beta(n) = sum of phi^(i+2) over the Zeckendorf digits of n;
     carryPass: the lowest digit >= 2 first (2W0 -> W1, 2W1 -> W0 + W2, 2W(i+2) -> Wi + W(i+3)),
     else the lowest pair of adjacent ones (Wi + W(i+1) -> W(i+2));
     the deficit c(v1, v2) = beta(v1) + beta(v2) - beta(v1 + v2) equals the signed count of the two bottom
     rules (+1 for 2W0 -> W1, -1 for 2W1 -> W0 + W2): theorem deficit_integer; c in {-1, 0, 1}: deficit_three_valued.
   On load, FILM.init recomputes c for 0 <= a, b < 89 both ways (carry count and exact Z[phi] arithmetic) and
   reports any disagreement as a page error, which stops the render. */
'use strict';

const GD = (() => {
  const fib = [0, 1];
  while (fib.length < 40) fib.push(fib[fib.length - 1] + fib[fib.length - 2]);
  const N = 24;
  const weight = i => fib[i + 2];
  function zeck(n) {
    const d = new Array(N).fill(0);
    let i = N - 3;
    while (n > 0) { while (weight(i) > n) i--; d[i] = 1; n -= weight(i); i -= 2; }
    return d;
  }
  function carryPass(r) {
    for (let i = 0; i < r.length; i++) {
      if (r[i] < 2) continue;
      const s = r.slice(); s[i] -= 2;
      if (i === 0) { s[1] += 1; return { r: s, rule: 'rep0', i, sign: 1 }; }
      if (i === 1) { s[0] += 1; s[2] += 1; return { r: s, rule: 'rep1', i, sign: -1 }; }
      s[i - 2] += 1; s[i + 1] += 1; return { r: s, rule: 'rep', i, sign: 0 };
    }
    for (let i = 0; i + 1 < r.length; i++) {
      if (r[i] === 1 && r[i + 1] === 1) { const s = r.slice(); s[i] = 0; s[i + 1] = 0; s[i + 2] += 1; return { r: s, rule: 'adj', i, sign: 0 }; }
    }
    return null;
  }
  function add(a, b) {
    const za = zeck(a), zb = zeck(b), raw = za.map((x, i) => x + zb[i]);
    const steps = []; let r = raw, count = 0;
    for (let s = carryPass(r); s; s = carryPass(r)) { steps.push(s); count += s.sign; r = s.r; }
    return { za, zb, raw, steps, r, count };
  }
  /* exact beta in Z[phi] as [x, y] = x + y*phi, using phi^k = F(k-1) + F(k)*phi */
  function beta(d) { let x = 0, y = 0; d.forEach((v, i) => { if (v) { x += v * fib[i + 1]; y += v * fib[i + 2]; } }); return [x, y]; }
  function deficitExact(a, b) {
    const p = beta(zeck(a)), q = beta(zeck(b)), s = beta(zeck(a + b));
    return [p[0] + q[0] - s[0], p[1] + q[1] - s[1]];
  }
  return { fib, weight, zeck, add, beta, deficitExact, N };
})();

const PHI = (1 + Math.sqrt(5)) / 2;
const SUP = '⁰¹²³⁴⁵⁶⁷⁸⁹', SUB = '₀₁₂₃₄₅₆₇₈₉';
const sup = n => String(n).split('').map(c => SUP[+c]).join('');
const sub = n => String(n).split('').map(c => SUB[+c]).join('');
const HEAT_N = 89;
const EX = GD.add(4, 4);  // the worked example: 4 + 4 = 8 with four carries, c(4, 4) = +1
let heat = null;
const SIGN_COL = s => (s > 0 ? C.cyan : s < 0 ? C.mag : C.dim);
const fmtSign = s => (s > 0 ? '+1' : s < 0 ? '−1' : '0');

const CELL = 6;  // heat-map cell pitch in px (5 px LED + 1 px gap)
const ZERO_COL = () => mix(C.blue, C.bg, 0.7);
FILM.init.push(() => {
  heat = mk(HEAT_N * CELL, HEAT_N * CELL);
  const hx = heat.getContext('2d');
  const col = { '1': C.cyan, '0': ZERO_COL(), '-1': C.mag };
  let bad = 0;
  for (let a = 0; a < HEAT_N; a++) for (let b = 0; b < HEAT_N; b++) {
    const r = GD.add(a, b), ex = GD.deficitExact(a, b), z = GD.zeck(a + b);
    if (ex[1] !== 0 || ex[0] !== r.count || Math.abs(r.count) > 1 || r.r.some((v, i) => v !== z[i])) {
      if (bad++ < 3) window.FILM_ERRORS.push(`deficit check failed at (${a}, ${b}): carries ${r.count}, exact ${ex}`);
    }
    hx.fillStyle = col[String(r.count)];
    hx.fillRect(b * CELL, (HEAT_N - 1 - a) * CELL, CELL - 1, CELL - 1);
  }
  if (EX.count !== 1 || EX.steps.length !== 4) window.FILM_ERRORS.push('worked example 4 + 4 changed');
});
Object.assign(FILM.speed, { zeck: 0.03, beta: 0.014, carry: 0.02, lean: 0.012, close: 0.025 });

/* ---------- the Zeckendorf register: 8 weights F2..F9, digits of n, labels morphing to phi powers ---------- */
function register(n, a, o = {}) {
  if (a <= 0.003) return;
  const ks = GD.zeck(n), K = 8, bw = 166, gap = 18, tot = K * bw + (K - 1) * gap, x0 = W / 2 - tot / 2, y0 = o.y || 540;
  const morph = o.morph || 0;
  for (let i = 0; i < K; i++) {
    const on = ks[i] === 1, x = x0 + i * (bw + gap), w = GD.weight(i);
    box(x, y0, bw, 132, on ? C.now : C.cyan, a * (on ? 1 : 0.45), on ? 2.5 : 1.2, on ? rgba(C.now, 0.14) : 'rgba(4,10,24,0.6)');
    txt(String(w), x + bw / 2, y0 + 86, { size: 54, fam: F.orb, w: 700, align: 'center', c: on ? C.now : C.dim, a: a * (1 - morph) });
    txt('φ' + sup(i + 2), x + bw / 2, y0 + 90, { size: 58, fam: F.math, w: 700, align: 'center', c: on ? C.now : C.dim, a: a * morph });
    txt('F' + sub(i + 2), x + bw / 2, y0 - 18, { size: 22, fam: F.math, align: 'center', c: C.dim, a: a * 0.9 });
    txt(String(ks[i]), x + bw / 2, y0 + 190, { size: 40, fam: F.mono, w: 700, align: 'center', c: on ? C.now : C.dim, a: a * (o.digits == null ? 1 : o.digits) });
  }
  txt('W' + sub(0) + ' … W' + sub(7), x0 - 26, y0 + 190, { size: 20, fam: F.mono, align: 'right', c: C.dim, a: a * 0.8 * (o.digits == null ? 1 : o.digits) });
}

SCENES.zeck = S => {
  const u = S.u, L0 = lineAt(S, 0);
  /* opening title, decoding in during the lead */
  const ta = clamp(u / 0.5) * (1 - clamp((u - L0.s - 0.1) / 0.6));
  if (ta > 0) {
    const p = clamp(u / 1.3);
    txt(`${DATA.book.code} · FILM ${DATA.film.number}`, W / 2, 360, { size: 26, fam: F.mono, w: 700, align: 'center', c: C.cyan, a: ta, ls: 10 });
    txt(DATA.film.title_zh, W / 2, 500, { size: 120, fam: F.zh, w: 900, align: 'center', c: C.white, a: ta * clamp(p * 1.6), ab: 4 });
    txt(scramble(DATA.film.title.toUpperCase(), p, 3), W / 2, 600, { size: 56, fam: F.orb, w: 900, align: 'center', c: C.white, a: ta, ls: 10, ab: 2 });
  }
  /* the register: n counts up to 42 while line 0 is spoken */
  const ra = at(S, 0, 0.8, 0.2);
  if (ra > 0) {
    const n = Math.max(1, Math.min(42, Math.floor(1 + 41 * ease(clamp((u - L0.s - 0.3) / Math.max(1, L0.e - L0.s - 0.2))))));
    const parts = GD.zeck(n).map((v, i) => (v ? GD.weight(i) : 0)).filter(Boolean).reverse();
    const settle = at(S, 1, 0.4);
    txt(`${n} = ${parts.join(' + ')}`, W / 2, 400, { size: 92, fam: F.orb, w: 900, align: 'center', c: C.white, a: ra, ab: 2 + 2 * settle });
    txt('non-adjacent · unique · Zeckendorf', W / 2, 462, { size: 26, fam: F.mono, w: 700, align: 'center', c: C.cyan, a: ra, ls: 2 });
    register(n, ra);
  }
};

SCENES.beta = S => {
  const u = S.u;
  const out = 1 - at(S, 1, 0.7, 0.4);
  const morph = ease(at(S, 0, 1.4, 1.2));
  const a = clamp(u / 0.4) * out;
  if (a > 0) {
    txt('42 = 34 + 8', W / 2, 400, { size: 92, fam: F.orb, w: 900, align: 'center', c: C.white, a: a * (1 - morph), ab: 2 });
    txt('β(42) = φ⁹ + φ⁶ ≈ 93.957', W / 2, 400, { size: 84, fam: F.math, w: 700, align: 'center', c: C.white, a: a * morph, ab: 2 });
    txt('replace each weight Fₖ by φᵏ  ·  φ = (1 + √5) / 2 ≈ 1.618', W / 2, 462, { size: 26, fam: F.mono, w: 700, align: 'center', c: C.cyan, a: a * morph });
    register(42, a, { morph });
  }
  /* the deficit */
  const p = at(S, 1, 0.7, 0.5);
  if (p > 0) {
    const q1 = Q(S, 1, 'But beta does not add', 0.6), q2 = Q(S, 1, 'The gap', 0.6);
    panel(260, 250, 1400, 470, p, C.cyan, 'DEFICIT · 亏量');
    txt('β(1) + β(1)  =  φ² + φ²', 360, 380, { size: 48, fam: F.math, w: 700, c: C.white, a: p * q1 });
    txt('≠', 1000, 380, { size: 56, fam: F.math, w: 700, c: C.mag, a: p * q1 });
    txt('β(2)  =  φ³', 1110, 380, { size: 48, fam: F.math, w: 700, c: C.white, a: p * q1 });
    txt('c(v₁, v₂)  =  β(v₁) + β(v₂) − β(v₁ + v₂)', W / 2, 515, { size: 56, fam: F.math, w: 700, align: 'center', c: C.white, a: p * q2, ab: 2 });
    txt('c(1, 1)  =  2φ² − φ³  =', 1000, 640, { size: 46, fam: F.math, w: 700, align: 'right', c: C.white, a: p * Q(S, 1, 'The gap', 0.6, 0.9) });
    txt('1', 1030, 644, { size: 66, fam: F.math, w: 700, c: C.cyan, a: p * Q(S, 1, 'The gap', 0.6, 1.5), ab: 3 });
  }
};

/* ---------- the worked example 4 + 4 ---------- */
const COLS = 7, X0 = 330, CW = 84;  // digit columns W0..W6
function digitRow(label, d, y, a, o = {}) {
  if (a <= 0.003) return;
  txt(label, X0 - 44, y, { size: 30, fam: F.math, w: 700, align: 'right', c: o.lc || C.white, a });
  for (let i = 0; i < COLS; i++) {
    const v = d[i], hot = o.hot && o.hot.includes(i);
    const col = hot ? C.now : v >= 2 ? C.mag : v === 1 ? C.white : C.dim;
    if (hot) fillBox(X0 + i * CW - 32, y - 38, 64, 50, rgba(C.now, 0.16), a);
    txt(String(v), X0 + i * CW, y, { size: 38, fam: F.mono, w: 700, align: 'center', c: col, a: a * (v ? 1 : 0.55) });
  }
}
const RULES = [
  ['adj', 'Wᵢ + Wᵢ₊₁ → Wᵢ₊₂', '1 + 2 → 3 · 3 + 5 → 8', 0],
  ['rep', '2·Wᵢ₊₂ → Wᵢ + Wᵢ₊₃', '2·3 → 1 + 5 · 2·5 → 2 + 8', 0],
  ['rep0', '2·W₀ → W₁', '1 + 1 → 2', 1],
  ['rep1', '2·W₁ → W₀ + W₂', '2 + 2 → 1 + 3', -1]
];
function ruleText(s) {
  const i = s.i;
  if (s.rule === 'adj') return `W${sub(i)} + W${sub(i + 1)} → W${sub(i + 2)}`;
  if (s.rule === 'rep0') return '2·W₀ → W₁';
  if (s.rule === 'rep1') return '2·W₁ → W₀ + W₂';
  return `2·W${sub(i)} → W${sub(i - 2)} + W${sub(i + 1)}`;
}
SCENES.carry = S => {
  const u = S.u, L1 = lineAt(S, 1);
  badgeQ(S, [[0, null, 'computed']]);
  const a0 = at(S, 0, 0.6, -0.3);
  /* column heads: the weights */
  for (let i = 0; i < COLS; i++) {
    txt(String(GD.weight(i)), X0 + i * CW, 214, { size: 24, fam: F.orb, w: 700, align: 'center', c: C.cyan, a: a0 * 0.9 });
    txt('W' + sub(i), X0 + i * CW, 242, { size: 18, fam: F.mono, align: 'center', c: C.dim, a: a0 * 0.8 });
  }
  digitRow('4', EX.za, 300, a0);
  digitRow('+ 4', EX.zb, 352, a0);
  const qs = Q(S, 0, 'sum the digits', 0.5);
  const right = 1230;
  line(X0 - 64, 372, right, 372, C.dim, qs, 1.5);
  digitRow('Σ', EX.raw, 418, qs);
  txt('sum, digit by digit', 900, 414, { size: 22, fam: F.mono, c: C.dim, a: qs });
  /* carries, one per beat, from "then carry" to just after line 1 starts */
  const c0 = phraseAt(S, 0, 'then carry'), c1 = L1.s + 1.2, n = EX.steps.length, beat = (c1 - c0) / n;
  EX.steps.forEach((s, k) => {
    const ts = c0 + beat * k, p = clamp((u - ts) / 0.45);
    if (p <= 0) return;
    const y = 470 + k * 52;
    const prev = k ? EX.steps[k - 1].r : EX.raw;
    const hot = [];
    for (let i = 0; i < COLS; i++) if (prev[i] !== s.r[i]) hot.push(i);
    const now = u < ts + beat;
    digitRow('→', s.r, y, p, { hot: now ? hot : [], lc: C.dim });
    txt(ruleText(s), 900, y - 4, { size: 26, fam: F.mono, w: 700, c: now ? C.now : C.white, a: p * (now ? 1 : 0.75) });
    txt(fmtSign(s.sign), right, y - 4, { size: 30, fam: F.mono, w: 700, align: 'right', c: SIGN_COL(s.sign), a: p });
  });
  /* result */
  const done = clamp((u - c1 - 0.2) / 0.6);
  if (done > 0) {
    const y = 470 + n * 52 + 34;
    line(X0 - 64, y - 46, right, y - 46, C.dim, done, 1.5);
    txt('4 + 4 = 8', X0 - 64, y + 4, { size: 34, fam: F.orb, w: 700, c: C.white, a: done });
    txt('c(4, 4) = +1', 900, y + 4, { size: 36, fam: F.math, w: 700, c: C.cyan, a: done, ab: 2 });
  }
  /* the four rules: during line 1 the two bottom doubling rules take the focus */
  const rp = Q(S, 1, 'Every carry keeps beta', 0.6);
  if (rp > 0) {
    const out = 1 - clamp((u - S.d + 0.8) / 0.6);
    const x = 1300, w = 420, y0 = 200, focus = Q(S, 1, 'except the two lowest', 0.6);
    panel(x, y0, w, 584, rp * out, C.cyan, 'CARRY RULES · 进位规则');
    RULES.forEach(([id, rule, eg, sign], k) => {
      const y = y0 + 84 + k * 126, bottom = sign !== 0;
      const a = rp * out * (bottom ? 1 : 1 - 0.4 * focus);
      if (bottom && focus > 0) box(x + 12, y - 38, w - 24, 104, C.now, a * focus, 2, rgba(C.now, 0.06 * focus));
      txt(rule, x + 28, y, { size: 24, fam: F.mono, w: 700, c: bottom ? C.white : mix(C.white, C.dim, 0.35), a });
      txt(eg, x + 28, y + 38, { size: 18, fam: F.mono, c: C.dim, a });
      txt(bottom ? fmtSign(sign) : 'β kept', x + w - 28, y + 38, { size: bottom ? 32 : 18, fam: F.mono, w: 700, align: 'right', c: SIGN_COL(sign), a });
    });
  }
};

/* ---------- three values, Lean-verified ---------- */
function heatmap(x, y, sz, a, rev) {
  if (a <= 0 || !heat) return;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.globalAlpha = a;
  ctx.beginPath(); ctx.moveTo(x, y + sz); ctx.lineTo(x + sz * 2 * rev, y + sz); ctx.lineTo(x, y + sz - sz * 2 * rev); ctx.closePath(); ctx.clip();
  ctx.drawImage(heat, x, y, sz, sz);
  ctx.restore();
  box(x - 6, y - 6, sz + 12, sz + 12, C.cyan, a * 0.8, 1.2);
}
function heatLegend(x, y, a) {
  [['−1', C.mag], ['0', ZERO_COL()], ['+1', C.cyan]].forEach(([l, c], i) => {
    fillBox(x + i * 150, y - 26, 34, 34, c, a); box(x + i * 150, y - 26, 34, 34, C.dim, a * 0.6, 1);
    txt(l, x + 46 + i * 150, y, { size: 28, fam: F.math, w: 700, c: C.white, a });
  });
}
SCENES.lean = S => {
  const u = S.u;
  badgeQ(S, [[0, null, 'lean']]);
  const hp = clamp(u / 0.8), out = clamp((S.d - u) / 0.6);
  const hx = 200, hy = 236, sz = HEAT_N * CELL;
  heatmap(hx, hy, sz, hp * out, eo(clamp((u - 0.2) / 3.2)));
  txt('c(a, b) · 0 ≤ a, b < 89 · computed here, exactly', hx, hy - 24, { size: 18, fam: F.mono, c: C.dim, a: hp * out });
  txt('b →', hx + sz - 50, hy + sz + 38, { size: 20, fam: F.mono, c: C.dim, a: hp * out });
  txt('a ↑', hx - 64, hy + 22, { size: 20, fam: F.mono, c: C.dim, a: hp * out });
  heatLegend(hx + 40, hy + sz + 92, hp * out);
  const fx = 870;
  const q0 = at(S, 0, 0.6, 0.2) * out;
  txt('c(v₁, v₂)  ∈  ℤ', fx, 300, { size: 58, fam: F.math, w: 700, c: C.white, a: q0, ab: 2 });
  txt('= signed count of the two bottom carry rules', fx, 352, { size: 24, fam: F.mono, w: 700, c: C.cyan, a: Q(S, 0, 'an integer', 0.6, 0.6) * out });
  leanChip(fx, 414, 'D5/S1/Deficit/DeficitInteger.deficit_integer', Q(S, 0, 'the signed count', 0.6, 0.3) * out);
  const q1 = at(S, 1, 0.6) * out;
  txt('c(v₁, v₂)  ∈  { −1, 0, 1 }', fx, 548, { size: 62, fam: F.math, w: 700, c: C.white, a: q1, ab: 3 });
  txt('∀ v₁ v₂ : ℕ', fx, 606, { size: 32, fam: F.mono, w: 700, c: C.cyan, a: Q(S, 1, 'For every input', 0.6, 0.4) * out });
  leanChip(fx, 668, 'D5/S1/Deficit/DeficitThreeValued.deficit_three_valued', Q(S, 1, 'or one', 0.6, 0.2) * out);
  stamp('PROVED FOR ALL INPUTS', 1290, 778, Q(S, 1, 'Lean has checked', 0.4, 0.2) * out, C.lean, 30, -0.05);
};
/* one Lean citation, by its GID (two citations may share a short name): LEAN ✓ chip + the declaration's name */
function leanChip(x, y, gid, a) {
  if (a <= 0) return;
  const r = leanCite(gid);
  if (!r || r.kind !== 'theorem') { window.FILM_ERRORS.push(`film.json does not cite the theorem ${gid}`); return; }
  const head = STR.en.lean || 'LEAN ✓', wh = tw(head, 18, F.mono, 700, 1) + 20;
  fillBox(x, y - 24, wh, 32, C.lean, a);
  txt(head, x + 10, y - 2, { size: 18, fam: F.mono, w: 700, c: C.bg, a, ls: 1 });
  txt(r.label, x + wh + 14, y, { size: 26, fam: F.mono, w: 700, c: C.lean, a });
}

/* ---------- the phase torus of chapter 1, a solid shot ----------
   The object of the page viz/phase-torus: its model (shape, regions, pairs, how it is drawn) is
   books/example-monograph/viz/phase-torus/model.js, inlined here by film.json "scripts", so the page and the film
   draw one object. The square glues into the torus while the card comes in, then the torus turns; the label of the
   amber pair (2, 2) follows its bead and dims while the torus hides it. A computed picture, not a Lean result. */
const TORUS_PICK = 18;   // PHASE_TORUS.PAIRS[18] = (2, 2): p(2) + p(2) ≈ 1.708 ≥ φ, c(2, 2) = −1
FILM.init.push(() => {
  const q = PHASE_TORUS.PAIRS[TORUS_PICK], E = window.FILM_ERRORS;
  if (q.v1 !== 2 || q.v2 !== 2 || q.c !== -1 || PHASE_TORUS.region(q.p1, q.p2) !== -1) E.push('phase torus: the pair (2, 2) changed');
  if (PHASE_TORUS.gap(2) > 1e-9) E.push('phase torus: the two diagonal pieces do not meet on the torus');
  /* c from the Beatty form agrees with the region of the phase criterion for all 64 pairs */
  if (PHASE_TORUS.PAIRS.some(r => r.c !== PHASE_TORUS.region(r.p1, r.p2))) E.push('phase torus: a pair outside its region');
});
const TORUS_RECT = { x: 110, y: 170, w: 760, h: 680 };
function phaseTorus(S, a) {
  if (a <= 0.003) return;
  const u = S.u, g = 2 * ease(clamp((u - 0.3) / 2.8));
  const sh = solid('torus', Object.assign({ yaw: -0.5 + 0.32 * u, pitch: 0.78, zoom: 0.95 + 0.8 * ease(clamp(g - 1)), radius: 0.36, cy: 0.52 }, TORUS_RECT));
  sh.begin();
  const drawn = PHASE_TORUS.draw(sh, g, TORUS_PICK, { magenta: C.mag, dim: C.dim, cyan: C.cyan, violet: C.vio, amber: C.now });
  sh.end(a);
  /* 2D layer on top of the solid: the label of the current pair follows its bead */
  const q = PHASE_TORUS.PAIRS[TORUS_PICK], at3 = sh.anchor(drawn[drawn.length - 1].p), la = a * (at3.hidden ? 0.28 : 1);
  line(at3.x, at3.y - 12, at3.x - 34, at3.y - 52, C.now, la * 0.9, 1.5);
  txt(`(${q.v1}, ${q.v2}) · c = −1`, at3.x - 40, at3.y - 58, { size: 24, fam: F.mono, w: 700, align: 'right', c: C.now, a: la });
  txt(g < 1.995 ? `GLUE ${g.toFixed(2)} / 2` : 'PHASE TORUS · 相位环面', TORUS_RECT.x + 30, TORUS_RECT.y + TORUS_RECT.h - 28, { size: 20, fam: g < 1.995 ? F.mono : F.zh, w: 700, c: C.cyan, a: a * 0.9, ls: 2 });
  txt('p₁ + p₂ = 1/φ ≡ φ (mod 1) · computed here', TORUS_RECT.x + 30, TORUS_RECT.y + TORUS_RECT.h + 4, { size: 17, fam: F.mono, c: C.dim, a: a * 0.9 });
}

SCENES.close = S => {
  badgeQ(S, [[0, null, 'lean']]);
  phaseTorus(S, clamp(S.u / 0.6) * clamp((S.d - S.u) / 1.2));
  closingCard(S, { from: 0.1, y: 330, x: 1250, hyper: false });
};

/* ---------- poster ---------- */
FILM.poster = () => {
  const t = 31.0;
  background(t, TL.scenes[3], 3, 6);
  drawHyper(CUBE4, [[0, 3, t * 0.21], [1, 2, t * 0.13], [2, 3, t * 0.17]], { scale: 1.5, a: 0.3, cx: 1240, cy: 430, camZ: 7, lw: 1.4, dots: false });
  heatmap(150, 256, HEAT_N * CELL, 1, 1);
  heatLegend(190, 880, 1);
  txt('c(a, b) · 0 ≤ a, b < 89', 150, 232, { size: 18, fam: F.mono, c: C.dim });
  txt(DATA.film.title_zh, 1270, 360, { size: 132, fam: F.zh, w: 900, align: 'center', c: C.white, ab: 4 });
  txt(DATA.film.title.toUpperCase(), 1270, 460, { size: 58, fam: F.orb, w: 900, align: 'center', c: C.white, ab: 4, ls: 8 });
  txt('c(v₁, v₂)  ∈  { −1, 0, 1 }', 1270, 600, { size: 64, fam: F.math, w: 700, align: 'center', c: C.cyan, ab: 2 });
  bloom(0.6);
  leanList(1270, 700, 1, { align: 'center', size: 24, gap: 48 });
  txt(`${DATA.book.code} · FILM ${DATA.film.number}`, 1270, 860, { size: 24, fam: F.mono, w: 700, align: 'center', c: C.cyan, ls: 8 });
  txt(`${DATA.book.title.zh} · ${DATA.book.title.en}`, 1270, 910, { size: 28, fam: F.zh, w: 700, align: 'center', c: C.white, a: 0.9 });
  hud(t, 930, 3, TL.scenes[3]);
  post(3);
};
