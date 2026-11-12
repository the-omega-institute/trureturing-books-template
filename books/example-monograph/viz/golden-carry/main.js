/* GOLDEN//CARRY · 黄金进位: the carry deficit c(v₁, v₂) = β(v₁) + β(v₂) − β(v₁ + v₂), in four scenes.
     carry   tokens on Fibonacci weights: the digitwise sum of Z(v₁) and Z(v₂), normalized one carry per pass, and a
             gauge that shows by how many units β of the current string exceeds β of the normal form
     map     c over 0 … N × 0 … N: three colours; the rail zooms out through the Fibonacci scales 8 … 987
     phase   the pairs (p(v₁), p(v₂)) with v < n in the unit square, cut by p₁ + p₂ = 1/φ and p₁ + p₂ = φ
     window  the contraction-face readings β′(v) for v ≤ m, all inside a window of length 1
   Everything about c is exact integer arithmetic: β(v) = a + bφ in ℤ[φ] with φ^k = F(k−1) + F(k)·φ. The carry rules
   and their order follow trureturing D5/S1/Digit/Normalize.lean (carryPass): the least position holding a 2 fires a
   repeated carry (R₀: 2W₀ → W₁, R₁: 2W₁ → W₀ + W₂, Rⱼ: 2Wⱼ → Wⱼ₋₂ + Wⱼ₊₁); otherwise the least adjacent pair of 1s
   fires the adjacent carry A: Wⱼ + Wⱼ₊₁ → Wⱼ₊₂. R₀ counts +1, R₁ counts −1, the others 0.
   Colours: cyan +1, magenta −1, amber = the current pair / pass. Read-only probe for the browser suite: GC_DEBUG. */
(() => {
  'use strict';
  const { kit, L } = TRV, { fix, clamp } = kit, P = TRV.palette;
  const $ = (id) => document.getElementById(id);
  const VMAX = 987, PH_MAX = 233, MINUS = '−';
  const PHI = (1 + Math.sqrt(5)) / 2, PSI = 1 - PHI, LO = -1 / (PHI * PHI), HI = 1 / PHI;
  const AREA_POS = 1 / (2 * PHI * PHI), AREA_NEG = 1 / (2 * Math.pow(PHI, 4));
  const FS = [8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987];   // the ranges the map rail passes through

  /* ---------- exact arithmetic ---------- */
  const F = [0, 1];
  while (F.length < 48) F.push(F[F.length - 1] + F[F.length - 2]);
  const Wt = (i) => F[i + 2]; // W_i = F_(i+2): 1, 2, 3, 5, 8, …
  const SUB = '₀₁₂₃₄₅₆₇₈₉';
  const sub = (n) => String(n).split('').map((d) => SUB[+d]).join('');
  /** Zeckendorf digits of n, index i ↔ weight W_i (greedy; the result has no two adjacent 1s). */
  function zeck(n) {
    if (n <= 0) return [];
    let top = 0;
    while (Wt(top + 1) <= n) top++;
    const d = new Array(top + 1).fill(0);
    for (let i = top; i >= 0; i--) if (Wt(i) <= n) { d[i] = 1; n -= Wt(i); }
    return d;
  }
  /** β(v) = Σ φ^(i+2) over the Zeckendorf digits of v, as the pair (a, b) meaning a + bφ. */
  function beta(v) {
    let a = 0, b = 0;
    zeck(v).forEach((x, i) => { if (x) { a += F[i + 1]; b += F[i + 2]; } });
    return { a, b };
  }
  const value = (r) => r.reduce((s, x, i) => s + x * Wt(i), 0);
  const trim = (r) => { const out = r.slice(); while (out.length && out[out.length - 1] === 0) out.pop(); return out; };
  const bump = (r, i, k) => { while (r.length <= i) r.push(0); r[i] += k; };
  /** Normalize raw digits one carry per pass, in the order of trureturing's carryPass. */
  function normalize(raw) {
    const r = raw.slice(), passes = [];
    for (let guard = 0; guard < 100000; guard++) {
      let i = r.findIndex((x) => x >= 2), step;
      if (i === 0) { r[0] -= 2; bump(r, 1, 1); step = { rule: 'R0', at: 0, sign: 1, from: [0], to: [1] }; }
      else if (i === 1) { r[1] -= 2; r[0] += 1; bump(r, 2, 1); step = { rule: 'R1', at: 1, sign: -1, from: [1], to: [0, 2] }; }
      else if (i >= 2) { r[i] -= 2; r[i - 2] += 1; bump(r, i + 1, 1); step = { rule: 'R', at: i, sign: 0, from: [i], to: [i - 2, i + 1] }; }
      else {
        i = -1;
        for (let j = 0; j + 1 < r.length; j++) if (r[j] === 1 && r[j + 1] === 1) { i = j; break; }
        if (i < 0) break;
        r[i] -= 1; r[i + 1] -= 1; bump(r, i + 2, 1); step = { rule: 'A', at: i, sign: 0, from: [i, i + 1], to: [i + 2] };
      }
      step.digits = trim(r);
      passes.push(step);
    }
    return { passes, digits: trim(r) };
  }
  /* the integer part of β(n) for every n a pair can need; c(i, j) = A[i] + A[j] − A[i + j] (the φ parts cancel) */
  const A = new Int32Array(2 * VMAX + 2), BC = new Float64Array(2 * VMAX + 2), PH = new Float64Array(VMAX + 1);
  for (let n = 0; n < A.length; n++) { const b = beta(n); A[n] = b.a; BC[n] = b.a + b.b * PSI; }   // BC = β′, the contraction face
  for (let v = 0; v <= VMAX; v++) { const x = (v + 1) * PHI; PH[v] = x - Math.floor(x); }          // the phase p(v)
  const cOf = (i, j) => A[i] + A[j] - A[i + j];
  /* how many of the n² pairs with v₁, v₂ < n have c = +1, c = −1, or a value outside {−1, 0, 1} (never, by the theorem) */
  const POS = new Uint32Array(VMAX + 2), NEG = new Uint32Array(VMAX + 2), ODDS = new Uint32Array(VMAX + 2);
  for (let n = 1; n <= VMAX + 1; n++) {
    const v = n - 1; let p = 0, q = 0, o = 0;
    for (let x = 0; x < v; x++) { const c = cOf(x, v); if (c === 1) p += 2; else if (c === -1) q += 2; else if (c !== 0) o += 2; }
    const d = cOf(v, v); if (d === 1) p++; else if (d === -1) q++; else if (d !== 0) o++;
    POS[n] = POS[n - 1] + p; NEG[n] = NEG[n - 1] + q; ODDS[n] = ODDS[n - 1] + o;
  }
  /* the smallest and largest β′(v) over v ≤ m */
  const BLO = new Float64Array(PH_MAX + 1), BHI = new Float64Array(PH_MAX + 1);
  for (let m = 0; m <= PH_MAX; m++) { BLO[m] = Math.min(m ? BLO[m - 1] : 0, BC[m]); BHI[m] = Math.max(m ? BHI[m - 1] : 0, BC[m]); }

  /* ---------- state ---------- */
  const S = { scene: 'carry', v1: 6, v2: 6, hover: null };
  let R = null, geo = {};
  const rng = TRV.mulberry32(20261108);
  function derive() {
    const { v1, v2 } = S, z1 = zeck(v1), z2 = zeck(v2), z3 = zeck(v1 + v2), raw = [];
    for (let i = 0; i < Math.max(z1.length, z2.length); i++) raw.push((z1[i] || 0) + (z2[i] || 0));
    const norm = normalize(raw), b1 = beta(v1), b2 = beta(v2), b3 = beta(v1 + v2);
    const partial = [0]; norm.passes.forEach((p) => partial.push(partial[partial.length - 1] + p.sign));
    R = { v1, v2, z1, z2, z3, raw, passes: norm.passes, final: norm.digits, b1, b2, b3, partial,
      c: { a: b1.a + b2.a - b3.a, b: b1.b + b2.b - b3.b }, count: partial[partial.length - 1],
      r0: norm.passes.filter((p) => p.rule === 'R0').length, r1: norm.passes.filter((p) => p.rule === 'R1').length,
      width: Math.max(1, raw.length, z3.length, ...norm.passes.map((p) => p.digits.length)),
      canonicalOk: norm.digits.join() === z3.join() && value(norm.digits) === v1 + v2 };
  }
  const fresh = () => { if (!R || R.v1 !== S.v1 || R.v2 !== S.v2) derive(); return R; };
  const K = () => fresh().passes.length;

  /* ---------- formatting ---------- */
  const fmtInt = (x) => (x < 0 ? MINUS + -x : String(x));
  const fmtSigned = (x) => (x > 0 ? '+' + x : x < 0 ? MINUS + -x : '0');
  const signCls = (x) => (x > 0 ? 'c-cy' : x < 0 ? 'c-mg' : '');
  const signCol = (x) => (x > 0 ? P.cyan : x < 0 ? P.magenta : P.dim);
  function fmtZphi({ a, b }) {
    if (b === 0) return fmtInt(a);
    const phi = (Math.abs(b) === 1 ? '' : Math.abs(b)) + 'φ';
    if (a === 0) return (b < 0 ? MINUS : '') + phi;
    return `${fmtInt(a)} ${b < 0 ? MINUS : '+'} ${phi}`;
  }
  const ruleCode = (p) => (p.rule === 'R0' ? 'R₀ · 2·W₀ → W₁' : p.rule === 'R1' ? 'R₁ · 2·W₁ → W₀ + W₂'
    : p.rule === 'R' ? `R${sub(p.at)} · 2·W${sub(p.at)} → W${sub(p.at - 2)} + W${sub(p.at + 1)}` : `A · W${sub(p.at)} + W${sub(p.at + 1)} → W${sub(p.at + 2)}`);
  const face = (f) => (f === 'body' ? TRV.fonts.body : f === 'display' ? TRV.fonts.display : TRV.fonts.data);
  /** Canvas text. o: size, face, weight, align, base, alpha, halo (a dark outline so that it reads over marks). */
  function text(ctx, str, x, y, color, o) {
    o = o || {};
    ctx.font = `${o.weight ? o.weight + ' ' : ''}${o.size || 11}px ${face(o.face)}`; ctx.textAlign = o.align || 'left'; ctx.textBaseline = o.base || 'middle';
    ctx.globalAlpha = o.alpha == null ? 1 : o.alpha;
    if (o.halo) { ctx.lineWidth = 4; ctx.lineJoin = 'round'; ctx.strokeStyle = P.stage; ctx.strokeText(str, x, y); }
    if (o.plate) {   // a dark plate, for a label that sits on top of many marks
      const w = ctx.measureText(str).width + 12, h = (o.size || 11) + 8, px = o.align === 'center' ? x - w / 2 : o.align === 'right' ? x - w + 6 : x - 6;
      ctx.fillStyle = TRV.alpha(P.stage, 0.86); ctx.fillRect(px, y - h / 2, w, h); ctx.strokeStyle = TRV.alpha(color, 0.6); ctx.lineWidth = 1; ctx.strokeRect(px + 0.5, y - h / 2 + 0.5, w - 1, h - 1);
    }
    ctx.fillStyle = color; ctx.fillText(str, x, y); ctx.globalAlpha = 1;
  }
  const blend = (a, b, t) => `rgb(${TRV.rgb[a].map((x, k) => Math.round(255 * (x * (1 - t) + TRV.rgb[b][k] * t))).join(',')})`;
  const cellColor = (c) => (c > 0 ? P.cyan : c < 0 ? P.magenta : c === 0 ? blend('stage', 'lineHot', 0.45) : P.warn);

  /* ---------- what the rail means in each scene ---------- */
  const mapN = (t) => { const k = Math.min(FS.length - 1, Math.floor(t + 1e-9)), f = t - k; return k >= FS.length - 1 ? VMAX : FS[k] * Math.pow(FS[k + 1] / FS[k], f); };
  const SC = {
    carry: { name: ['进位', 'CARRIES'], max: () => Math.max(K(), 1e-9), rate: () => Math.max(1.4, K() / 12), step: 1, start: () => K() },
    map: { name: ['亏量图', 'MAP'], max: () => FS.length - 1, rate: () => 0.9, step: 1, start: () => 3 },
    phase: { name: ['相位', 'PHASES'], max: () => PH_MAX, rate: () => 26, step: 8, start: () => 8 },
    window: { name: ['窗口', 'WINDOW'], max: () => PH_MAX, rate: () => 26, step: 8, start: () => 34 }
  };
  const pass = () => Math.min(K(), Math.floor(clock.t + 1e-9));
  const mapRange = () => Math.round(mapN(clock.t));
  const count = () => clamp(Math.floor(clock.t + 1e-9), 0, PH_MAX);      // n of the phase scene (at least 1), m of the window scene
  const phaseN = () => Math.max(1, count());

  /* ---------- scene: the carries ---------- */
  function drawGauge(ctx, m, D, k, f, words) {
    const next = k < D.passes.length ? D.passes[k].sign : 0, off = D.c.a - D.partial[k] - f * next;   // β(current string) − β(normal form)
    const wide = words && m.w >= 600, cx = wide ? m.x + m.w * 0.76 : m.x + m.w / 2, unit = Math.min(44, m.w * (wide ? 0.085 : 0.16)), y = m.y + m.h * 0.56;
    if (wide) {
      const tx = m.x + 4, eq = tx + 132;
      text(ctx, 'β(v₁) + β(v₂)', tx, m.y + m.h * 0.3, P.dim, { size: 12 }); text(ctx, `= ${fmtZphi({ a: D.b1.a + D.b2.a, b: D.b1.b + D.b2.b })}`, eq, m.y + m.h * 0.3, P.ink, { size: 12.5 });
      text(ctx, 'β(v₁ + v₂)', tx, m.y + m.h * 0.72, P.dim, { size: 12 }); text(ctx, `= ${fmtZphi(D.b3)}`, eq, m.y + m.h * 0.72, P.ink, { size: 12.5 });
    }
    if (words) text(ctx, L('当前数字串的 β − 规范形的 β', 'β of the current string − β of the normal form'), cx, m.y + 7, P.dim, { align: 'center', size: 10.5, face: 'body' });
    ctx.strokeStyle = P.lineHot; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(cx - 2.4 * unit, y); ctx.lineTo(cx + 2.4 * unit, y); ctx.stroke();
    for (let u = -2; u <= 2; u++) {
      ctx.strokeStyle = u ? P.lineHot : P.ink; ctx.lineWidth = u ? 1 : 1.6; ctx.beginPath(); ctx.moveTo(cx + u * unit, y - (u ? 5 : 8)); ctx.lineTo(cx + u * unit, y + (u ? 5 : 8)); ctx.stroke();
      text(ctx, fmtSigned(u), cx + u * unit, y + 17, u ? P.dim : P.ink, { align: 'center', size: 10.5 });
    }
    const x0 = cx + clamp(D.c.a, -2.3, 2.3) * unit, x1 = cx + clamp(off, -2.3, 2.3) * unit;
    ctx.strokeStyle = P.amber; ctx.globalAlpha = 0.55; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); ctx.globalAlpha = 1;
    ctx.strokeStyle = signCol(D.c.a); ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(x0, y, 6.5, 0, kit.TAU); ctx.stroke();                 // where the digitwise sum starts: at c
    ctx.fillStyle = P.amber; ctx.shadowColor = P.amber; ctx.shadowBlur = 10; ctx.beginPath(); ctx.moveTo(x1, y - 7); ctx.lineTo(x1 + 6, y); ctx.lineTo(x1, y + 7); ctx.lineTo(x1 - 6, y); ctx.closePath(); ctx.fill(); ctx.shadowBlur = 0;
  }
  function drawCarry(ctx, bx, t, words) {
    const D = fresh(), n = D.width, KK = D.passes.length, k = Math.min(KK, Math.floor(t + 1e-9)), f = k < KK ? clamp(t - k, 0, 1) : 0, e = TRV.smooth(f);
    const gaugeH = clamp(bx.h * 0.2, 52, 72), availH = bx.h - gaugeH - 8, wide = words && bx.w >= 600, labW = 34, sideW = wide ? 184 : 48, headH = 20, gapH = 6;
    let rowH = Math.min(54, (availH - headH - gapH - 8) / (KK + 3)), cap = KK + 1, first = 0;
    if (rowH < 20) { rowH = 20; cap = Math.max(2, Math.floor((availH - headH - gapH) / rowH) - 2); first = clamp(t + 2 - cap, 0, KK + 1 - cap); }
    const by = bx.y + Math.max(0, (availH - headH - gapH - (cap + 2) * rowH) / 2), top = by + gaugeH + 8;   // gauge and rows, centred in the box
    drawGauge(ctx, { x: bx.x, y: by, w: bx.w, h: gaugeH }, D, k, e, words);
    const cell = Math.min(rowH, (bx.w - labW - sideW) / n, 54), gridW = n * cell, x0 = bx.x + labW + Math.max(0, (bx.w - labW - sideW - gridW) / 2);
    const cx = (i) => x0 + (n - 1 - i) * cell + cell / 2, yIn = (r) => top + headH + r * rowH + rowH / 2;
    const y0 = top + headH + 2 * rowH + gapH, yPass = (j) => y0 + (j - first) * rowH + rowH / 2;
    geo.carry = { left: x0 - labW, right: x0 + gridW + sideW, y0, rowH, first, K: KK };
    const token = (x, y, d, alpha) => {
      if (!d) { ctx.globalAlpha = 0.6 * alpha; ctx.fillStyle = P.faint; ctx.beginPath(); ctx.arc(x, y, 1.6, 0, kit.TAU); ctx.fill(); ctx.globalAlpha = 1; return; }
      const w = cell * 0.56, gap = 2.5, h = Math.min(w * 0.72, (cell * 0.72 - (d - 1) * gap) / d), sH = d * h + (d - 1) * gap;
      ctx.globalAlpha = alpha; ctx.fillStyle = P.ink;
      for (let q = 0; q < d; q++) { ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(x - w / 2, y - sH / 2 + q * (h + gap), w, h, Math.min(3, h / 3)); else ctx.rect(x - w / 2, y - sH / 2 + q * (h + gap), w, h); ctx.fill(); }
      ctx.globalAlpha = 1;
    };
    const row = (digits, y, alpha) => { for (let i = 0; i < n; i++) token(cx(i), y, digits[i] || 0, alpha); };
    const label = (s, y, color, bold) => text(ctx, s, x0 - 8, y, color, { align: 'right', size: 11.5, weight: bold ? 600 : 0 });
    // weights, the two inputs
    const hs = clamp(cell * 0.4, 8, 11);
    for (let i = 0; i < n; i++) { ctx.font = `${hs}px ${face()}`; if (ctx.measureText(String(Wt(i))).width <= cell - 1 || i % 2 === 0) text(ctx, String(Wt(i)), cx(i), top + headH / 2, P.dim, { align: 'center', size: hs }); }
    row(D.z1, yIn(0), 0.7); label('v₁', yIn(0), P.dim); row(D.z2, yIn(1), 0.7); label('v₂', yIn(1), P.dim);
    if (wide) { text(ctx, `Z(${S.v1})`, x0 + gridW + 12, yIn(0), P.dim, { size: 11 }); text(ctx, `Z(${S.v2})`, x0 + gridW + 12, yIn(1), P.dim, { size: 11 }); }
    ctx.strokeStyle = P.lineHot; ctx.setLineDash([4, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x0 - labW, y0 - gapH / 2); ctx.lineTo(x0 + gridW + 40, y0 - gapH / 2); ctx.stroke(); ctx.setLineDash([]);
    // the passes: row j holds the digits after pass j (row 0 is the digitwise sum)
    ctx.save(); ctx.beginPath(); ctx.rect(bx.x - 4, y0 - 1, bx.w + 8, bx.y + bx.h - y0 + 3); ctx.clip();
    const now = e > 0 ? k + 1 : k;                                   // the pass drawn in amber
    for (let j = Math.max(0, Math.floor(first)); j <= Math.min(KK, k + (f > 0 ? 1 : 0)); j++) {
      const y = yPass(j), a = j === k + 1 ? e : 1, p = j ? D.passes[j - 1] : null, digits = p ? p.digits : D.raw;
      if (y < y0 - rowH || y > bx.y + bx.h + rowH) continue;
      if (p) {
        const col = j === now ? P.amber : signCol(p.sign), yA = yPass(j - 1) + cell * 0.36, yB = y - cell * 0.36;
        ctx.strokeStyle = col; ctx.lineWidth = j === now ? 1.8 : 1.2; ctx.globalAlpha = (j === now ? 0.95 : p.sign ? 0.8 : 0.4);
        for (const s of p.from) for (const d of p.to) { ctx.beginPath(); ctx.moveTo(cx(s), yA); ctx.lineTo(cx(s) + (cx(d) - cx(s)) * a, yA + (yB - yA) * a); ctx.stroke(); }
        ctx.globalAlpha = a;
        for (const d of p.to) { ctx.strokeRect(cx(d) - cell * 0.42, y - cell * 0.42, cell * 0.84, cell * 0.84); }
        ctx.globalAlpha = 1;
        const bxs = x0 + gridW + 10, bh = Math.min(rowH - 6, 20);
        ctx.globalAlpha = a; ctx.strokeStyle = p.sign ? signCol(p.sign) : P.panelEdge; ctx.lineWidth = 1.2; ctx.strokeRect(bxs, y - bh / 2, 32, bh); ctx.globalAlpha = 1;
        text(ctx, fmtSigned(p.sign), bxs + 16, y + 0.5, p.sign ? signCol(p.sign) : P.faint, { align: 'center', size: Math.min(11.5, bh * 0.62), weight: 600, alpha: a });
        if (wide) text(ctx, ruleCode(p), bxs + 42, y, j === now ? P.ink : P.dim, { size: 11, alpha: a });
      } else if (wide) text(ctx, L('逐位相加', 'digitwise sum'), x0 + gridW + 12, y, P.dim, { size: 11, face: 'body' });
      row(digits, y, a);
      label(j ? `#${j}` : 'Σ', y, j === now ? P.amber : P.dim, j === now);
    }
    if (k === KK && !f) { ctx.strokeStyle = P.amber; ctx.lineWidth = 1.6; ctx.shadowColor = P.amber; ctx.shadowBlur = 10; ctx.strokeRect(x0 - 3, yPass(KK) - rowH / 2 + 2, gridW + 6, rowH - 4); ctx.shadowBlur = 0; }
    ctx.restore();
  }

  /* ---------- scene: the deficit map ---------- */
  let tex = null;
  /** c over 0 … 987 as one image, v₁ across and v₂ up: used when the cells are too small to draw one by one. */
  function texture() {
    if (tex) return tex;
    const n = VMAX + 1; tex = document.createElement('canvas'); tex.width = tex.height = n;
    const tc = tex.getContext('2d'), img = tc.createImageData(n, n), d = img.data, to255 = (name) => TRV.rgb[name].map((x) => Math.round(x * 255));
    const Pc = to255('cyan'), Mc = to255('magenta'), st = to255('stage'), lh = to255('lineHot'), Zc = st.map((x, i) => Math.round(x * 0.55 + lh[i] * 0.45));
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) { const c = cOf(x, y), C = c > 0 ? Pc : c < 0 ? Mc : Zc, i = 4 * ((n - 1 - y) * n + x); d[i] = C[0]; d[i + 1] = C[1]; d[i + 2] = C[2]; d[i + 3] = 255; }
    tc.putImageData(img, 0, 0);
    return tex;
  }
  /** The map of 0 … N (N may be fractional while the rail zooms) in the square that fits bx; returns its geometry. */
  function drawMap(ctx, bx, N, ticks) {
    const cells = N + 1, padL = ticks ? 34 : 0, padB = ticks ? 20 : 0, side = Math.max(40, Math.min(bx.w - padL, bx.h - padB)), s = side / cells;
    const ox = bx.x + padL + (bx.w - padL - side) / 2, oy = bx.y + (bx.h - padB - side) / 2, g = { ox, oy, s, side, cells };
    ctx.save(); ctx.beginPath(); ctx.rect(ox, oy, side, side); ctx.clip();
    if (s >= 5) {
      const gap = Math.max(1, s * 0.1), top = Math.min(VMAX, Math.ceil(N));
      for (let y = 0; y <= top; y++) for (let x = 0; x <= top; x++) { ctx.fillStyle = cellColor(cOf(x, y)); ctx.fillRect(ox + x * s, oy + side - (y + 1) * s, s - gap, s - gap); }
    } else { ctx.imageSmoothingEnabled = s < 1; ctx.drawImage(texture(), 0, VMAX + 1 - cells, cells, cells, ox, oy, side, side); ctx.imageSmoothingEnabled = true; }
    if (S.v1 < cells && S.v2 < cells) {                               // the current pair: amber cross and box
      const px = ox + (S.v1 + 0.5) * s, py = oy + side - (S.v2 + 0.5) * s, box = Math.max(s, 9);
      ctx.strokeStyle = TRV.alpha(P.amber, 0.5); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(px, oy); ctx.lineTo(px, oy + side); ctx.moveTo(ox, py); ctx.lineTo(ox + side, py); ctx.stroke();
      ctx.strokeStyle = P.amber; ctx.lineWidth = 2; ctx.shadowColor = P.amber; ctx.shadowBlur = 10; ctx.strokeRect(px - box / 2, py - box / 2, box, box); ctx.shadowBlur = 0;
    }
    ctx.restore();
    if (ticks) {                                                       // Fibonacci ticks on both axes
      let lastX = -1e9, lastY = 1e9;
      for (const v of [0, ...F.slice(2).filter((q) => q <= N)]) {
        const x = ox + (v + 0.5) * s, y = oy + side - (v + 0.5) * s;
        if (x - lastX >= 22) { text(ctx, String(v), x, oy + side + 5, P.dim, { align: 'center', base: 'top', size: 10 }); lastX = x; }
        if (lastY - y >= 13) { text(ctx, String(v), ox - 6, y, P.dim, { align: 'right', size: 10 }); lastY = y; }
      }
      text(ctx, 'v₁ →', ox + side, oy + side + 5, P.dim, { align: 'right', base: 'top', size: 10, alpha: lastX < ox + side - 60 ? 1 : 0 });
    }
    return g;
  }

  /* ---------- scene: the phase square ---------- */
  function drawPhase(ctx, bx, n) {
    const padL = 42, padB = 22, side = Math.max(60, Math.min(bx.w - padL - 8, bx.h - padB - 4)), ox = bx.x + padL + (bx.w - padL - side) / 2, oy = bx.y + (bx.h - padB - side) / 2;
    const X = (p) => ox + p * side, Y = (p) => oy + (1 - p) * side;
    geo.phase = { X, Y, n };
    const tri = (pts, col) => { ctx.fillStyle = col; ctx.globalAlpha = 0.1; ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])))); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1; };
    tri([[0, 0], [HI, 0], [0, HI]], P.cyan); tri([[HI, 1], [1, 1], [1, HI]], P.magenta);
    ctx.strokeStyle = P.lineHot; ctx.lineWidth = 1.2; ctx.strokeRect(ox + 0.5, oy + 0.5, side, side);
    const seg = (a, b, col) => { ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.moveTo(X(a[0]), Y(a[1])); ctx.lineTo(X(b[0]), Y(b[1])); ctx.stroke(); };
    seg([HI, 0], [0, HI], P.cyan); seg([HI, 1], [1, HI], P.magenta);
    const r = n <= 13 ? 3.4 : n <= 34 ? 2.4 : n <= 89 ? 1.6 : 1.1, zero = TRV.alpha(P.ink, n <= 34 ? 0.55 : 0.4);
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const c = cOf(x, y); ctx.fillStyle = c > 0 ? P.cyan : c < 0 ? P.magenta : zero;
      if (n <= 34) { ctx.beginPath(); ctx.arc(X(PH[x]), Y(PH[y]), r, 0, kit.TAU); ctx.fill(); } else ctx.fillRect(X(PH[x]) - r, Y(PH[y]) - r, 2 * r, 2 * r);
    }
    ctx.strokeStyle = P.amber; ctx.lineWidth = 2; ctx.shadowColor = P.amber; ctx.shadowBlur = 10; ctx.beginPath(); ctx.arc(X(PH[S.v1]), Y(PH[S.v2]), 7, 0, kit.TAU); ctx.stroke(); ctx.shadowBlur = 0;
    for (const [v, lab] of [[0, '0'], [1 - HI, '1/φ²'], [HI, '1/φ'], [1, '1']]) {
      text(ctx, lab, X(v), oy + side + 6, P.dim, { align: 'center', base: 'top', size: 10.5 }); text(ctx, lab, ox - 7, Y(v), P.dim, { align: 'right', size: 10.5 });
    }
    text(ctx, 'p(v₁)', X(0.8), oy + side + 6, P.dim, { align: 'center', base: 'top', size: 10.5 }); text(ctx, 'p(v₂)', ox - 7, Y(0.8), P.dim, { align: 'right', size: 10.5 });
    const big = clamp(side * 0.04, 11, 14), ring = [PH[S.v1], PH[S.v2]];
    const tagAt = (str, home, away, col) => {      // a region's label, moved aside when the current pair sits under it
      const q = Math.hypot(X(home[0]) - X(ring[0]), Y(home[1]) - Y(ring[1])) < 46 ? away : home;
      text(ctx, str, X(q[0]), Y(q[1]), col, { align: 'center', size: big, weight: 600, plate: true });
    };
    tagAt('c = +1', [HI / 3, HI / 3], [0.1, 0.07], P.cyan); tagAt('c = 0', [0.5, 0.5], [0.3, 0.7], P.ink); tagAt('c = −1', [(HI + 2) / 3, (HI + 2) / 3], [0.9, 0.94], P.magenta);
  }

  /* ---------- scene: the window on the contraction face ---------- */
  function drawWindow(ctx, bx, m) {
    const D = fresh(), xa = -0.62, xb = 0.86, sx = bx.x + 44, sw = bx.w - 56, sy = bx.y + 30, cy = bx.y + bx.h - 22, lane = cy - 92, sh = lane - 30 - sy, top = Math.max(21, m);
    const X = (u) => sx + (u - xa) / (xb - xa) * sw, Yv = (v) => sy + sh - v / top * sh;
    ctx.fillStyle = TRV.alpha(P.lineHot, 0.16); ctx.fillRect(X(LO), sy - 6, X(HI) - X(LO), lane - sy + 22);
    for (const u of [LO, HI]) { ctx.strokeStyle = P.ink; ctx.globalAlpha = 0.75; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(X(u), sy - 6); ctx.lineTo(X(u), lane + 16); ctx.stroke(); ctx.globalAlpha = 1; }
    text(ctx, '−1/φ² ≈ −0.382', X(LO), sy - 16, P.ink, { align: 'center', size: 11 }); text(ctx, '1/φ ≈ 0.618', X(HI), sy - 16, P.ink, { align: 'center', size: 11 });
    if (sw > 420) text(ctx, L('← 窗口的长度恰为 1 →', '← the window is exactly 1 long →'), (X(LO) + X(HI)) / 2, sy - 16, P.dim, { align: 'center', size: 11, face: 'body' });
    ctx.strokeStyle = P.faint; ctx.globalAlpha = 0.6; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(X(0), sy); ctx.lineTo(X(0), sy + sh); ctx.stroke(); ctx.globalAlpha = 1;
    let lastY = 1e9; for (const v of [0, ...F.slice(3).filter((q) => q <= top)]) { if (lastY - Yv(v) >= 14) { text(ctx, String(v), sx - 8, Yv(v), P.dim, { align: 'right', size: 10 }); lastY = Yv(v); } }
    text(ctx, 'v', sx - 8, sy - 16, P.dim, { align: 'right', size: 10.5 });
    for (let v = 0; v <= m; v++) { ctx.fillStyle = P.ink; ctx.globalAlpha = 0.8; ctx.beginPath(); ctx.arc(X(BC[v]), Yv(v), sh > 220 ? 2.3 : 1.8, 0, kit.TAU); ctx.fill(); }
    ctx.globalAlpha = 1;
    // the three readings of the current pair
    ctx.strokeStyle = P.lineHot; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx, lane); ctx.lineTo(sx + sw, lane); ctx.stroke();
    const three = S.v1 === S.v2 ? [[BC[S.v1], 'v₁ = v₂'], [BC[S.v1 + S.v2], 'v₁ + v₂']] : [[BC[S.v1], 'v₁'], [BC[S.v2], 'v₂'], [BC[S.v1 + S.v2], 'v₁ + v₂']];
    three.forEach(([u, lab], i) => {
      ctx.fillStyle = P.amber; ctx.shadowColor = P.amber; ctx.shadowBlur = 10; ctx.beginPath(); ctx.arc(X(u), lane, 5.5, 0, kit.TAU); ctx.fill(); ctx.shadowBlur = 0;
      const up = i % 2 === 0, clash = three.some(([w], q) => q < i && q % 2 === i % 2 && Math.abs(X(w) - X(u)) < 62);
      text(ctx, lab, X(u), lane + (up ? -1 : 1) * (clash ? 26 : 14), P.amber, { align: 'center', size: 11, halo: true });
    });
    // c = β′(v₁) + β′(v₂) − β′(v₁ + v₂): three numbers of the window leave room for the integers −1, 0, 1 only
    const cw = Math.min(sw, 560), c0 = sx + sw / 2, U = (u) => c0 + u / 2.2 * (cw / 2), b = (u) => (u < 0 ? `(${fix(u, 3)})` : fix(u, 3));
    text(ctx, `c = β′(v₁) + β′(v₂) − β′(v₁ + v₂) = ${b(BC[S.v1])} + ${b(BC[S.v2])} − ${b(BC[S.v1 + S.v2])} = ${fmtSigned(D.c.a)}`, c0, cy - 42, P.ink, { align: 'center', size: sw > 520 ? 12 : 10.5 });
    ctx.fillStyle = TRV.alpha(P.lineHot, 0.3); ctx.fillRect(U(PHI - 3), cy - 7, U(PHI) - U(PHI - 3), 14);
    ctx.strokeStyle = P.lineHot; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(U(-2.2), cy); ctx.lineTo(U(2.2), cy); ctx.stroke();
    text(ctx, 'φ − 3 ≈ −1.382', U(PHI - 3), cy - 17, P.dim, { align: 'center', size: 10.5 }); text(ctx, 'φ ≈ 1.618', U(PHI), cy - 17, P.dim, { align: 'center', size: 10.5 });
    for (let u = -2; u <= 2; u++) {
      const inside = Math.abs(u) <= 1, hit = u === D.c.a;
      ctx.strokeStyle = inside ? P.ink : P.faint; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(U(u), cy, inside ? 4.5 : 2.5, 0, kit.TAU); ctx.stroke();
      if (hit) { ctx.fillStyle = u ? signCol(u) : P.ink; ctx.beginPath(); ctx.arc(U(u), cy, 4.5, 0, kit.TAU); ctx.fill(); ctx.strokeStyle = P.amber; ctx.lineWidth = 2; ctx.shadowColor = P.amber; ctx.shadowBlur = 10; ctx.beginPath(); ctx.arc(U(u), cy, 8.5, 0, kit.TAU); ctx.stroke(); ctx.shadowBlur = 0; }
      text(ctx, fmtSigned(u), U(u), cy + 16, inside ? P.ink : P.faint, { align: 'center', size: 10.5 });
    }
  }

  /* ---------- the stage ---------- */
  function drawStage() {
    const g = kit.plot($('cv'), { x: [0, 1], y: [0, 1], pad: [0, 0, 0, 0] }), ctx = g.ctx, W = g.W, H = g.H;
    geo = {};
    if (TRV.thumbMode) {   // the cover is wordless: the map of 0 … 34 beside the finished carries of the current pair
      const glow = ctx.createRadialGradient(W * 0.3, H * 0.5, 0, W * 0.3, H * 0.5, W * 0.55);
      glow.addColorStop(0, TRV.alpha(P.cyan, 0.08)); glow.addColorStop(1, TRV.alpha(P.cyan, 0)); ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
      drawMap(ctx, { x: W * 0.045, y: H * 0.08, w: W * 0.47, h: H * 0.84 }, 34, false);
      drawCarry(ctx, { x: W * 0.56, y: H * 0.1, w: W * 0.4, h: H * 0.8 }, K(), false);
      return;
    }
    const st = $('stage').getBoundingClientRect(), below = (el) => (el ? el.getBoundingClientRect().bottom - st.top : 0);
    const top = Math.max(46, below($('hudBig').parentElement), below($('sceneChips'))) + 10, bottom = Math.max(18, $('legend').offsetHeight + 20);
    const bx = { x: 18, y: top, w: W - 36, h: Math.max(80, H - top - bottom) };
    if (S.scene === 'carry') drawCarry(ctx, bx, clock.t, true);
    else if (S.scene === 'map') geo.map = drawMap(ctx, bx, mapN(clock.t), true);
    else if (S.scene === 'phase') drawPhase(ctx, bx, phaseN());
    else drawWindow(ctx, bx, count());
  }

  /* ---------- the strip: two small plots per scene ---------- */
  function plotStairs(cv) {
    const D = fresh(), KK = D.passes.length, lo = Math.min(-1, ...D.partial), hi = Math.max(1, ...D.partial);
    const g = kit.plot(cv, { x: [0, Math.max(KK, 1)], y: [lo - 0.6, hi + 0.6], pad: [30, 14, 10, 20] }), ticks = []; for (let u = lo; u <= hi; u++) ticks.push([u, fmtSigned(u)]);
    g.axes({ yTicks: ticks, xTicks: KK > 1 ? [0, KK] : [0, 1], xLabel: L('进位步', 'pass') });
    D.passes.forEach((p, j) => { g.line([[j, D.partial[j]], [j + 1, D.partial[j]]], P.dim, { width: 1.4 }); if (p.sign) g.line([[j + 1, D.partial[j]], [j + 1, D.partial[j + 1]]], signCol(p.sign), { width: 2.4 }); });
    if (S.scene === 'carry') g.vline(clamp(clock.t, 0, Math.max(KK, 1)), P.amber, { alpha: 0.8 });
    g.dot(KK, D.count, D.count ? signCol(D.count) : P.ink, 4.5, { glow: 8 });
    $('pATitle').textContent = L('带符号进位计数', 'Signed carry count'); $('pAMeta').textContent = L(`${KK} 步之后停在 ${fmtSigned(D.count)}`, `ends at ${fmtSigned(D.count)} after ${KK} pass${KK === 1 ? '' : 'es'}`);
  }
  function plotMini(cv) {
    const g = kit.plot(cv, { x: [0, 1], y: [0, 1], pad: [0, 0, 0, 0] });
    geo.mini = drawMap(g.ctx, { x: 8, y: 6, w: g.W - 16, h: g.H - 12 }, 34, false);
    $('pBTitle').textContent = L('亏量图 0 … 34：点一格换一对数', 'Deficit map 0 … 34: click a cell to change the pair');
    $('pBMeta').textContent = S.v1 <= 34 && S.v2 <= 34 ? `(${S.v1}, ${S.v2})` : L('当前一对在这张图之外', 'the current pair is off this map');
  }
  function plotShares(cv) {
    const n = phaseN(), g = kit.plot(cv, { x: [1, PH_MAX], y: [0, 0.4], pad: [34, 12, 8, 20] }), pos = [], neg = [];
    for (let q = 1; q <= PH_MAX; q++) { pos.push([q, POS[q] / (q * q)]); neg.push([q, NEG[q] / (q * q)]); }
    g.axes({ yTicks: [0, 0.1, 0.2, 0.3], xTicks: [1, 55, 89, 144, 233], xLabel: 'n' });
    g.hline(AREA_POS, P.cyan, { dash: [4, 3], alpha: 0.8 }); g.hline(AREA_NEG, P.magenta, { dash: [4, 3], alpha: 0.8 });
    g.line(pos, P.cyan); g.line(neg, P.magenta); g.vline(n, P.amber, { alpha: 0.8 });
    g.dot(n, POS[n] / (n * n), P.cyan, 4); g.dot(n, NEG[n] / (n * n), P.magenta, 4);
    g.legend([[P.cyan, L('c = +1 的比例', 'share with c = +1')], [P.magenta, L('c = −1 的比例', 'share with c = −1')], [P.dim, L('两块三角形的面积', 'areas of the two triangles'), 'dash']]);
    $('pATitle').textContent = L('比例贴近面积', 'Shares approach the areas'); $('pAMeta').textContent = `n = ${n}`;
  }
  function plotRow(cv) {
    const N = mapRange(), g = kit.plot(cv, { x: [0, N + 1], y: [0, 1], pad: [14, 14, 16, 22] });
    for (let x = 0; x <= N; x++) g.rect(x, 0.12, x + 1, 0.88, cellColor(cOf(x, S.v2)), { alpha: 1 });
    if (S.v1 <= N) g.rect(S.v1, 0.04, S.v1 + 1, 0.96, P.amber, { fill: false, stroke: P.amber, width: 2, glow: 8 });
    let last = -1e9; for (const v of [0, ...F.slice(2).filter((q) => q <= N)]) { const px = g.X(v + 0.5); if (px - last >= 24) { g.text(v + 0.5, 0, String(v), P.dim, { align: 'center', base: 'top', dy: 4, size: 10 }); last = px; } }
    $('pATitle').textContent = L(`图中的一行：c(v₁, ${S.v2})`, `One row of the map: c(v₁, ${S.v2})`); $('pAMeta').textContent = `v₁ = 0 … ${N}`;
  }
  function drawPlots() {
    if (TRV.still || TRV.figure) return;
    if (S.scene === 'phase') plotShares($('plotA')); else if (S.scene === 'map') plotRow($('plotA')); else plotStairs($('plotA'));
    plotMini($('plotB'));
  }

  /* ---------- words: HUD, legend, readouts, pills ---------- */
  const LEGEND = {
    carry: [['cy', 'R₀：记 +1', 'R₀: counts +1'], ['mg', 'R₁：记 −1', 'R₁: counts −1'], ['dm', '其余进位：记 0', 'every other carry: 0'], ['am', '当前这一步', 'the current pass']],
    map: [['cy box', 'c = +1', 'c = +1'], ['mg box', 'c = −1', 'c = −1'], ['dm box', 'c = 0', 'c = 0'], ['am', '当前一对', 'the current pair']],
    phase: [['cy', 'c = +1：p₁ + p₂ < 1/φ', 'c = +1: p₁ + p₂ < 1/φ'], ['mg', 'c = −1：p₁ + p₂ ≥ φ', 'c = −1: p₁ + p₂ ≥ φ'], ['dm', 'c = 0', 'c = 0'], ['am', '当前一对', 'the current pair']],
    window: [['dm', '每个 v 的读数 β′(v)', 'the reading β′(v) of each v'], ['am', '当前一对的三个读数', 'the three readings of the current pair']]
  };
  function drawText() {
    const D = fresh(), KK = D.passes.length, c = D.c.a, isInt = D.c.b === 0, sum = S.v1 + S.v2;
    let big, hud, note;
    if (S.scene === 'carry') {
      const k = pass();
      big = `${S.v1} + ${S.v2}`;
      hud = !KK ? L('逐位和已经是规范形：没有进位，c = 0', 'the digitwise sum is already canonical: no carry, c = 0')
        : k < KK ? L(`第 ${k} 步，共 ${KK} 步 · 带符号计数至此 ${fmtSigned(D.partial[k])}`, `pass ${k} of ${KK} · signed count so far ${fmtSigned(D.partial[k])}`)
          : L(`进位 ${KK} 次，得到 Z(${sum}) · 带符号计数 ${fmtSigned(D.count)} = c`, `${KK} carr${KK === 1 ? 'y' : 'ies'} reach Z(${sum}) · signed count ${fmtSigned(D.count)} = c`);
      note = L(`进位 ${KK} 次，其中 R₀ ${D.r0} 次、R₁ ${D.r1} 次；其余规则不改变 β。`, `${KK} carr${KK === 1 ? 'y' : 'ies'}: R₀ ${D.r0}×, R₁ ${D.r1}×; the other rules leave β unchanged.`);
    } else if (S.scene === 'map') {
      const N = mapRange(), n = N + 1, h = S.hover, ok = ODDS[n] === 0;
      big = L(`亏量图 0 … ${N}`, `Deficit map 0 … ${N}`);
      hud = h ? `c(${h[0]}, ${h[1]}) = ${fmtSigned(cOf(h[0], h[1]))}`
        : L(`${n * n} 格：+1 有 ${POS[n]} 格，−1 有 ${NEG[n]} 格，其余为 0 ${ok ? '✓' : '✗'}`, `${n * n} cells: ${POS[n]} are +1, ${NEG[n]} are −1, the rest are 0 ${ok ? '✓' : '✗'}`);
      note = L('每一格的颜色就是那一对数的 c。点一格，其余场景都换成这一对。', 'The colour of a cell is c for that pair. Click a cell and every scene switches to that pair.');
    } else if (S.scene === 'phase') {
      const n = phaseN(), s = PH[S.v1] + PH[S.v2];
      big = L(`相位正方形 · v₁, v₂ < ${n}`, `Phase square · v₁, v₂ < ${n}`);
      hud = L(`${n * n} 对：+1 占 ${fix(POS[n] / (n * n), 4)}（面积 ${fix(AREA_POS, 4)}），−1 占 ${fix(NEG[n] / (n * n), 4)}（面积 ${fix(AREA_NEG, 4)}）`,
        `${n * n} pair${n === 1 ? '' : 's'}: +1 holds ${fix(POS[n] / (n * n), 4)} (area ${fix(AREA_POS, 4)}), −1 holds ${fix(NEG[n] / (n * n), 4)} (area ${fix(AREA_NEG, 4)})`);
      note = L(`当前一对的相位之和 p(v₁) + p(v₂) = ${fix(s, 3)}：`, `For the current pair p(v₁) + p(v₂) = ${fix(s, 3)}: `)
        + (s < HI ? L('小于 1/φ ≈ 0.618，所以 c = +1。', 'below 1/φ ≈ 0.618, so c = +1.') : s >= PHI ? L('不小于 φ ≈ 1.618，所以 c = −1。', 'at least φ ≈ 1.618, so c = −1.') : L('在 1/φ 与 φ 之间，所以 c = 0。', 'between 1/φ and φ, so c = 0.'));
    } else {
      const m = count(), inside = BLO[m] >= LO - 1e-12 && BHI[m] <= HI + 1e-12;
      big = L(`收缩面的窗口 · v ≤ ${m}`, `Window on the contraction face · v ≤ ${m}`);
      hud = L(`${m + 1} 个读数都在 [−0.382, 0.618] 之内 ${inside ? '✓' : '✗'} · 最小 ${fix(BLO[m], 3)}，最大 ${fix(BHI[m], 3)}`, `all ${m + 1} readings lie in [−0.382, 0.618] ${inside ? '✓' : '✗'} · least ${fix(BLO[m], 3)}, greatest ${fix(BHI[m], 3)}`);
      note = L('三个读数都在长度为 1 的窗口里，所以 c 只能落在 −1.382 与 1.618 之间；它又是整数。', 'All three readings lie in a window of length 1, so c can only fall between −1.382 and 1.618; and it is an integer.');
    }
    $('hudBig').textContent = big; $('hudSub').textContent = hud; $('roNote').textContent = note;
    const leg = LEGEND[S.scene].map(([cl, zh, en]) => `<span><i class="sw ${cl}"></i>${L(zh, en)}</span>`).join('');
    if ($('legend')._h !== leg) { $('legend').innerHTML = leg; $('legend')._h = leg; }
    $('roC').innerHTML = `<span class="${signCls(c)}">${isInt ? fmtSigned(c) : fmtZphi(D.c)}</span> <span class="nummark">${isInt && Math.abs(c) <= 1 ? '∈ {−1, 0, 1} ✓' : '✗'}</span>`;
    $('roCSub').textContent = `= (${fmtZphi({ a: D.b1.a + D.b2.a, b: D.b1.b + D.b2.b })}) − (${fmtZphi(D.b3)})`;
    $('roR0').textContent = String(D.r0); $('roR1').textContent = String(D.r1);
    $('roCount').innerHTML = `${D.r0} − ${D.r1} = <span class="${signCls(D.count)}">${fmtSigned(D.count)}</span> <span class="nummark">${isInt && D.count === c ? '= c ✓' : '≠ c ✗'}</span>`;
    const three = [BC[S.v1], BC[S.v2], BC[sum]], inWin = three.every((x) => x >= LO - 1e-12 && x <= HI + 1e-12);
    $('roConj').innerHTML = `${three.map((x) => fix(x, 3)).join(' · ')} <small>∈ [−0.382, 0.618] ${inWin ? '✓' : '✗'}</small>`;
    $('pillPair').querySelector('strong').textContent = `${S.v1}, ${S.v2}`;
    $('pillPasses').querySelector('strong').textContent = String(KK);
    $('pillC').innerHTML = `c <strong class="${signCls(c)}">${isInt ? fmtSigned(c) : fmtZphi(D.c)}</strong>`;
    for (const k of ['v1', 'v2']) {     // never overwrite the box the reader is typing in
      for (const el of [$(k), $(k + 'Num')]) if (document.activeElement !== el) el.value = String(S[k]);
      $(k + 'Dec').disabled = S[k] <= 0; $(k + 'Inc').disabled = S[k] >= VMAX;
    }
  }

  const paint = kit.painter(() => { drawText(); drawStage(); drawPlots(); }, [$('stage'), $('plotA'), $('plotB')]);

  /* ---------- the rail, scenes, the pair ---------- */
  const clock = kit.clock({
    range: $('now'), play: $('play'), label: $('tau'), speeds: $('speedChips'), max: 1, rate: 1.4, step: 1,
    // (the label is first drawn while the clock is being built, so it reads t and never the clock itself)
    format: (t) => (S.scene === 'carry' ? `${L('第 ', 'PASS ')}${Math.min(K(), Math.floor(t + 1e-9))}${L(' 步', '')} <small>/ ${K()}</small>`
      : S.scene === 'map' ? `0 … ${Math.round(mapN(t))} <small>/ ${VMAX}</small>` : S.scene === 'phase' ? `v &lt; ${Math.max(1, Math.floor(t + 1e-9))} <small>/ ${PH_MAX}</small>` : `v ≤ ${Math.floor(t + 1e-9)} <small>/ ${PH_MAX}</small>`),
    onChange: () => paint()
  });
  function fitClock(t) {
    const sc = SC[S.scene];
    clock.pause(); clock.rate = sc.rate(); clock.step = sc.step; clock.setMax(sc.max(), true); clock.set(t == null ? sc.start() : t);
  }
  function setScene(sc, t) {
    S.scene = sc; S.hover = null; sceneChips.set(sc, true);
    document.querySelectorAll('[data-scenes]').forEach((el) => { el.hidden = !el.dataset.scenes.split(' ').includes(sc); });
    fitClock(t);
  }
  const clampV = (x) => clamp(Math.round(Number(x)) || 0, 0, VMAX);
  /** Choose the pair. The carries restart finished (step back with ← or play them again); other scenes keep their rail. */
  function setPair(v1, v2) {
    v1 = clampV(v1); v2 = clampV(v2);
    if (v1 === S.v1 && v2 === S.v2) { paint(); return; }
    S.v1 = v1; S.v2 = v2;
    if (S.scene === 'carry') fitClock(); else paint();
  }
  const leave = () => cards.mark(null);
  const sceneChips = kit.chips($('sceneChips'), 'scene', (v) => { leave(); setScene(v); });
  for (const k of ['v1', 'v2']) {
    const pick = (v) => { leave(); setPair(k === 'v1' ? v : S.v1, k === 'v2' ? v : S.v2); };
    $(k).addEventListener('input', (ev) => pick(ev.target.value));
    $(k + 'Num').addEventListener('change', (ev) => { pick(ev.target.value); ev.target.value = String(S[k]); });
    $(k + 'Num').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') ev.target.blur(); });
    $(k + 'Dec').addEventListener('click', () => pick(S[k] - 1));
    $(k + 'Inc').addEventListener('click', () => pick(S[k] + 1));
  }
  const swap = () => { leave(); setPair(S.v2, S.v1); }, random = () => { leave(); setPair(Math.floor(rng() * (VMAX + 1)), Math.floor(rng() * (VMAX + 1))); };
  $('swap').addEventListener('click', swap); $('random').addEventListener('click', random);
  $('rew').addEventListener('click', () => { clock.pause(); clock.set(0); });
  kit.keys({ 1: () => { leave(); setScene('carry'); }, 2: () => { leave(); setScene('map'); }, 3: () => { leave(); setScene('phase'); }, 4: () => { leave(); setScene('window'); }, s: swap, r: random });

  /* ---------- direct manipulation: click a cell, a point or a pass ---------- */
  const cellAt = (g, cv, ev) => {
    if (!g) return null;
    const b = cv.getBoundingClientRect(), x = Math.floor((ev.clientX - b.left - g.ox) / g.s), y = Math.floor((g.oy + g.side - (ev.clientY - b.top)) / g.s);
    return x >= 0 && y >= 0 && x < g.cells && y < g.cells && x <= VMAX && y <= VMAX ? [x, y] : null;
  };
  function wireMap(cv, geom) {
    let dragging = false, down = null;
    cv.addEventListener('pointerdown', (ev) => {
      if (!geom()) return;
      down = [ev.clientX, ev.clientY];
      if (ev.pointerType === 'mouse') { dragging = true; try { cv.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic events */ } const c = cellAt(geom(), cv, ev); if (c) { leave(); setPair(c[0], c[1]); } }
    });
    cv.addEventListener('pointermove', (ev) => {
      const g = geom(); if (!g) return;
      const c = cellAt(g, cv, ev), h = S.hover;
      if (cv === $('cv') && String(c) !== String(h)) { S.hover = c; paint(); }
      if (dragging && c) setPair(c[0], c[1]);
    });
    cv.addEventListener('pointerup', (ev) => {
      if (!dragging && down && Math.hypot(ev.clientX - down[0], ev.clientY - down[1]) < 8) { const c = cellAt(geom(), cv, ev); if (c) { leave(); setPair(c[0], c[1]); } }
      dragging = false; down = null;
    });
    cv.addEventListener('pointercancel', () => { dragging = false; down = null; });
    cv.addEventListener('pointerleave', () => { if (cv === $('cv') && S.hover) { S.hover = null; paint(); } });
  }
  wireMap($('cv'), () => (S.scene === 'map' ? geo.map : null));
  wireMap($('plotB'), () => geo.mini);
  $('cv').addEventListener('click', (ev) => {
    const b = $('cv').getBoundingClientRect(), x = ev.clientX - b.left, y = ev.clientY - b.top;
    if (S.scene === 'carry' && geo.carry) {            // a row of the carries: go to that pass
      const g = geo.carry, j = Math.round((y - g.y0 - g.rowH / 2) / g.rowH + g.first);
      if (x >= g.left && x <= g.right && j >= 0 && j <= g.K && y >= g.y0) { clock.pause(); clock.set(j); }
    } else if (S.scene === 'phase' && geo.phase) {     // the nearest point of the square: take that pair
      const g = geo.phase; let best = null, bd = 18 * 18;
      for (let q = 0; q < g.n; q++) for (let p = 0; p < g.n; p++) { const d = (g.X(PH[p]) - x) ** 2 + (g.Y(PH[q]) - y) ** 2; if (d < bd) { bd = d; best = [p, q]; } }
      if (best) { leave(); setPair(best[0], best[1]); }
    }
  });

  /* ---------- experiment cards ---------- */
  // a card that plays declares its still: the frame of the cover and of the figure a chapter cites ('end': the last pass)
  const PRESETS = {
    plus: { scene: 'carry', pair: [1, 1], play: true, still: 'end' }, minus: { scene: 'carry', pair: [2, 2], play: true, still: 'end' },
    cancel: { scene: 'carry', pair: [6, 6], play: true, still: 'end' }, long: { scene: 'carry', pair: [986, 986], play: true, still: 'end' },
    map: { scene: 'map', pair: [17, 17], at: 3 }, zoom: { scene: 'map', pair: [17, 17], at: 7, play: true, still: 7 },
    phase: { scene: 'phase', pair: [2, 2], at: 8 }, fill: { scene: 'phase', pair: [2, 2], at: 89, play: true, from: 2, still: 89 },
    window: { scene: 'window', pair: [2, 2], at: 34 }, sweep: { scene: 'window', pair: [2, 2], at: 144, play: true, still: 144 }
  };
  const NOTES = {
    plus: ['1 + 1：两枚筹码挤在权重 1 的格子里，规则 R₀ 把它们换成一枚权重 2 的筹码。数值没变，β 却少了 1：标尺从 +1 走到 0，c(1, 1) = +1。', '1 + 1: two tokens share the cell of weight 1, and rule R₀ trades them for one token of weight 2. The value is the same but β drops by 1: the gauge goes from +1 to 0, and c(1, 1) = +1.'],
    minus: ['2 + 2：权重 2 的格子里有两枚筹码，规则 R₁ 把它们换成权重 1 与权重 3 各一枚。这一次 β 多了 1：标尺从 −1 走到 0，c(2, 2) = −1。', '2 + 2: the cell of weight 2 holds two tokens, and rule R₁ trades them for one of weight 1 and one of weight 3. This time β rises by 1: the gauge goes from −1 to 0, and c(2, 2) = −1.'],
    cancel: ['6 + 6：三次进位。R₀ 让 β 少 1，中间的 R₃ 不改变 β，R₁ 又让 β 多 1。一少一多抵消，c(6, 6) = 0。', '6 + 6: three carries. R₀ lowers β by 1, the R₃ in the middle leaves it alone, and R₁ raises it by 1. One down, one up: c(6, 6) = 0.'],
    long: ['986 + 986 要进位 50 次，是 987 以内最长的一次。其中 49 次不改变 β；只有第一步的 R₁ 记了 −1，所以 c = −1。', '986 + 986 takes 50 carries, the longest run below 987. Forty-nine of them leave β unchanged; only the R₁ of the first pass counts −1, so c = −1.'],
    map: ['每一格是一对 (v₁, v₂)，颜色是它的 c：青色 +1，品红 −1，暗格 0。0 到 34 共 1225 格，只有这三种颜色；图关于对角线对称。', 'Each cell is a pair (v₁, v₂), coloured by its c: cyan +1, magenta −1, dark 0. The 1225 cells of 0 to 34 show these three colours and no other; the map is symmetric about the diagonal.'],
    zoom: ['把范围从 0 … 8 一路拉到 0 … 987：格子越来越细，到最后有 976144 格，颜色仍然只有这三种。', 'Zoom out from 0 … 8 all the way to 0 … 987: the cells get finer and finer, 976144 of them at the end, and the colours are still these three.'],
    phase: ['把 v 换成相位 p(v) = {(v + 1)φ}，一对数就是正方形里的一个点。两条斜线把正方形分成三块：左下 c = +1，右上 c = −1，中间 c = 0。这里是 v₁, v₂ < 8 的 64 个点：左下 10 个，右上 6 个。', 'Replace v by its phase p(v) = {(v + 1)φ} and a pair becomes a point of the square. Two lines cut the square into three regions: c = +1 at the lower left, c = −1 at the upper right, c = 0 in between. These are the 64 points with v₁, v₂ < 8: ten at the lower left and six at the upper right.'],
    fill: ['让 v₁、v₂ 取遍 0 到 n − 1：点逐渐铺满正方形，落在两块三角形里的比例贴近它们的面积 0.1910 与 0.0729。', 'Let v₁ and v₂ run through 0 … n − 1: the points fill the square, and the shares that land in the two triangles approach their areas, 0.1910 and 0.0729.'],
    window: ['在收缩面上把 φ 换成 ψ = 1 − φ 再读同一串数字，得到 β′(v)。每个读数都落在 [−1/φ², 1/φ] 这个长度为 1 的窗口里，所以 c = β′(v₁) + β′(v₂) − β′(v₁ + v₂) 只能在 −1.382 与 1.618 之间：其中的整数只有 −1、0、1。', 'On the contraction face the same digits are read with ψ = 1 − φ in place of φ, which gives β′(v). Every reading lies in the window [−1/φ², 1/φ] of length 1, so c = β′(v₁) + β′(v₂) − β′(v₁ + v₂) can only fall between −1.382 and 1.618: the integers in there are −1, 0 and 1.'],
    sweep: ['v 从 0 走到 233，每个 β′(v) 画成一个点：它们左右折返，却没有一个离开窗口。', 'Let v run from 0 to 233 and draw each β′(v) as a point: they swing left and right, and not one leaves the window.']
  };
  let booting = true;
  function applyPreset(id) {
    const p = PRESETS[id];
    S.v1 = p.pair[0]; S.v2 = p.pair[1];
    setScene(p.scene, p.at);
    if (TRV.still && p.still != null) clock.set(p.still === 'end' ? clock.max : p.still);
    // a still (cover, cited figure for PDF/EPUB) and the opening view of the full page show the telling frame;
    // inside a chapter the card plays once the reader has scrolled it into view; a click plays at once
    if (!p.play || TRV.still || (booting && !TRV.embed)) return;
    clock.set(p.from || 0);
    if (booting) kit.autoplay(clock, $('stage')); else clock.play();
  }
  const cards = kit.cards($('presets'), { presets: PRESETS, notes: NOTES, noteEl: $('presetNote'), tour: $('tour'), onPick: applyPreset,
    idle: ['自由探索：换一对数、换场景、拖时间轴。随时可以再选一张卡。', 'Free play: change the pair, switch scenes, scrub the rail. Pick a card again at any time.'] });

  TRV.drawer({ drawer: $('drawer'), open: $('infoBtn'), close: $('drawerClose') });
  TRV.startGlitch(document.querySelector('.brand'));

  /* ---------- probe for the browser suite, cover, start ---------- */
  const at = (cv, x, y) => { const b = cv.getBoundingClientRect(); return { x: b.left + x, y: b.top + y }; };
  window.GC_DEBUG = {
    get state() {
      const n = phaseN(), N = mapRange();
      return { scene: S.scene, v1: S.v1, v2: S.v2, t: clock.t, max: clock.max, playing: clock.playing, preset: cards.current, pass: pass(), passes: K(),
        N, cells: { pos: POS[N + 1], neg: NEG[N + 1], odd: ODDS[N + 1] }, n, shares: { pos: POS[n] / (n * n), neg: NEG[n] / (n * n) }, m: count(), least: BLO[count()], greatest: BHI[count()] };
    },
    info: () => {
      const D = fresh();
      return { v1: S.v1, v2: S.v2, c: D.c.a, cPhi: D.c.b, count: D.count, beta1: [D.b1.a, D.b1.b], beta2: [D.b2.a, D.b2.b], beta3: [D.b3.a, D.b3.b],
        z1: D.z1.slice(), z2: D.z2.slice(), z3: D.z3.slice(), raw: D.raw.slice(), final: D.final.slice(), canonicalOk: D.canonicalOk, partial: D.partial.slice(),
        contraction: [BC[S.v1], BC[S.v2], BC[S.v1 + S.v2]], phases: [PH[S.v1], PH[S.v2]],
        passes: D.passes.map((p) => ({ rule: p.rule, at: p.at, sign: p.sign, digits: p.digits.slice() })) };
    },
    /** c over 0 … N × 0 … N as a string of '0' | '1' | '2' (c + 1), index v₂ · (N + 1) + v₁. */
    grid: (n) => { let out = ''; for (let y = 0; y <= n; y++) for (let x = 0; x <= n; x++) out += String(cOf(x, y) + 1); return out; },
    /** β′(v) and p(v) as the page computes them, for v = 0 … n. */
    readings: (n) => Array.from({ length: n + 1 }, (_, v) => [BC[v], PH[v]]),
    set: (v1, v2) => setPair(v1, v2), seek: (t) => { clock.pause(); clock.set(t); }, scene: (sc, t) => setScene(sc, t),
    /** Viewport coordinates for pointer tests: a cell of the stage map or of the small map, a point of the phase square, a pass row. */
    point: {
      map: (v1, v2) => (geo.map ? at($('cv'), geo.map.ox + (v1 + 0.5) * geo.map.s, geo.map.oy + geo.map.side - (v2 + 0.5) * geo.map.s) : null),
      mini: (v1, v2) => (geo.mini ? at($('plotB'), geo.mini.ox + (v1 + 0.5) * geo.mini.s, geo.mini.oy + geo.mini.side - (v2 + 0.5) * geo.mini.s) : null),
      phase: (v1, v2) => (geo.phase ? at($('cv'), geo.phase.X(PH[v1]), geo.phase.Y(PH[v2])) : null),
      row: (j) => (geo.carry ? at($('cv'), (geo.carry.left + geo.carry.right) / 2, geo.carry.y0 + (j - geo.carry.first + 0.5) * geo.carry.rowH) : null)
    }
  };
  /** Cover: the map of 0 … 34 beside the nine carries of 17 + 17 (signed count +1). */
  window.TRV_THUMB = () => { S.v1 = 17; S.v2 = 17; setScene('carry'); paint.now(); };
  cards.pick(cards.initial('cancel'));   // a chapter may cite another card: ::: {.viz src="golden-carry" preset="window"}
  booting = false;
  paint();
})();
