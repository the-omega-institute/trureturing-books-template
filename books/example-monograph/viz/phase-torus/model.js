/* PHASE//TORUS · the model: the phase square glued into a torus, and how it is drawn as a solid.
   One file for the two places that show this object: the page (index.html loads it before main.js) and film 001 of
   the book (film.json "scripts": ["viz/phase-torus/model.js"], inlined before its scenes.js). Change the shape, the
   colours of the regions or the beads here and both change. It draws through the primitives that kit.solid (page) and
   the film engine's solid() shot (film) share: surface, tube, bead. No DOM, no clock: a classic script that defines
   window.PHASE_TORUS.

   A phase p(v) = {(v + 1)φ} only sees the fractional part, so the left and right edges of the square are the same line,
   and so are the top and the bottom. The glue g goes from 0 (the square) through 1 (rolled into a tube, top to bottom)
   to 2 (bent round into a torus, left to right). The colours are the three regions of the phase criterion; the two
   diagonal lines p₁ + p₂ = 1/φ and p₁ + p₂ = φ meet end to end on the torus, because φ = 1 + 1/φ. The beads are the
   64 phase pairs with 0 ≤ v₁, v₂ ≤ 7, coloured by c(v₁, v₂) from the Beatty form. */
(function (root) {
  'use strict';
  const PHI = (1 + Math.sqrt(5)) / 2, TAU = 2 * Math.PI, SIZE = 1.25;
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const len = (a) => Math.hypot(a[0], a[1], a[2]);
  const unit = (a) => { const n = len(a); return n > 1e-12 ? scale(a, 1 / n) : [0, 0, 1]; };
  const frac = (x) => x - Math.floor(x);
  const phase = (v) => frac((v + 1) * PHI);
  const beatty = (v) => Math.floor((v + 1) * PHI) - 1;
  /** The deficit from the Beatty form, and the region of the phase criterion it falls in. */
  const deficit = (v1, v2) => beatty(v1) + beatty(v2) - beatty(v1 + v2);
  const region = (p1, p2) => (p1 + p2 < 1 / PHI ? 1 : p1 + p2 >= PHI ? -1 : 0);
  const PAIRS = [];
  for (let v1 = 0; v1 <= 7; v1++) for (let v2 = 0; v2 <= 7; v2++) PAIRS.push({ v1, v2, p1: phase(v1), p2: phase(v2), c: deficit(v1, v2) });

  /* The square is 2 wide (p₁) and 1 high (p₂), so that the torus has its hole. Rolling wraps p₂ round a circle of
     circumference 1 about an axis along p₁; bending wraps that axis round a circle of circumference 2. */
  function shape(p1, p2, g) {
    const a = Math.min(1, Math.max(0, g)), b = Math.min(1, Math.max(0, g - 1));
    if (a < 1e-6) return [SIZE * 2 * (p1 - 0.5), SIZE * (p2 - 0.5), 0];
    // rolled downwards, so that the side facing up stays the outside of the tube and of the torus
    const r = 1 / (TAU * a), th = TAU * a * (p2 - 0.5), y = r * Math.sin(th), z = -2 * r * Math.sin(th / 2) ** 2;
    if (b < 1e-6) return [SIZE * 2 * (p1 - 0.5), SIZE * y, SIZE * (z + r * (1 - Math.cos(Math.PI * a)) / 2)];
    const Rb = 2 / (TAU * b), ph = TAU * b * (p1 - 0.5);
    return [SIZE * (Rb - y) * Math.sin(ph), SIZE * (Rb - (Rb - y) * Math.cos(ph) - Rb * (1 - Math.cos(Math.PI * b)) / 2), SIZE * (z + r)];
  }
  /** The unit normal of the surface at (p₁, p₂), from its partial derivatives; it points away from the torus' tube axis. */
  function normal(p1, p2, g) {
    const h = 1e-4, a = shape(p1 + h, p2, g), b = shape(p1 - h, p2, g), c = shape(p1, p2 + h, g), d = shape(p1, p2 - h, g);
    return unit(cross(sub(a, b), sub(c, d)));
  }
  const onSurface = (p1, p2, g, lift) => add(shape(p1, p2, g), scale(normal(p1, p2, g), lift));
  /** The two pieces of the curve p₁ + p₂ ≡ 1/φ (mod 1): p₂ = 1/φ − p₁ for p₁ ≤ 1/φ, and p₂ = φ − p₁ for p₁ ≥ 1/φ. */
  const lineA = (k, n) => { const p1 = (1 / PHI) * k / n; return [p1, 1 / PHI - p1]; };
  const lineB = (k, n) => { const p1 = 1 / PHI + (1 - 1 / PHI) * k / n; return [p1, PHI - p1]; };
  /** How far apart the ends of the two pieces are (they are the same points of the torus). */
  const gap = (g) => Math.max(len(sub(shape(1 / PHI, 0, g), shape(1 / PHI, 1, g))), len(sub(shape(0, 1 / PHI, g), shape(1, 1 / PHI, g))));

  /**
   * Draw the solid at glue g into st (kit.solid on a page, a solid() shot in a film), between its begin() and end():
   * the surface coloured by region, the two violet lines, the 64 pair beads and the current pair `pick` in amber.
   * colors: { magenta, dim, cyan, violet, amber } (token colours of the host). Returns [{ i, p }] (index into PAIRS
   * and world point of each bead, the current one last), for picking and labels.
   */
  function draw(st, g, pick, colors) {
    const lift = 0.005, K = colors;
    st.surface('square', (p1, p2) => shape(p1, p2, g), { u: [0, 1], v: [0, 1], nu: 120, nv: 120, value: region, colors: [K.magenta, K.dim, K.cyan], range: [-1, 1], grid: { every: [12, 12] } });
    const A = [], B = [];
    for (let k = 0; k <= 60; k++) { const a = lineA(k, 60), b = lineB(k, 60); A.push(onSurface(a[0], a[1], g, lift)); B.push(onSurface(b[0], b[1], g, lift)); }
    st.tube('lineA', A, { color: K.violet, width: 3.4 });
    st.tube('lineB', B, { color: K.violet, width: 3.4 });
    const drawn = [];
    PAIRS.forEach((q, i) => {
      if (i === pick) return;
      const p = onSurface(q.p1, q.p2, g, lift * 1.5);
      drawn.push({ i, p });
      st.bead(p, { color: q.c > 0 ? K.cyan : q.c < 0 ? K.magenta : K.dim, r: 3.2, glow: 0.3, key: `${q.v1},${q.v2}` });
    });
    const cur = PAIRS[pick], cp = onSurface(cur.p1, cur.p2, g, lift * 1.5);
    drawn.push({ i: pick, p: cp });
    st.bead(cp, { color: K.amber, r: 6.5, key: 'current' });
    return drawn;
  }

  root.PHASE_TORUS = { PHI, SIZE, phase, deficit, region, PAIRS, shape, normal, onSurface, lineA, lineB, gap, draw };
})(typeof window !== 'undefined' ? window : globalThis);
