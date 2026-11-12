/* PHASE//TORUS · 相位环面 · Phase torus
   The phase square of Chapter 1 as a lit solid. A phase p(v) = {(v + 1)φ} only sees the fractional part, so the left
   and right edges of the square are the same line, and so are the top and the bottom. The rail glues them: from 0 to 1
   the square rolls up into a tube (top to bottom), from 1 to 2 the tube bends round into a torus (left to right). The
   colours are the three regions of the phase criterion (Theorem thm-golden-phase); the two diagonal lines
   p₁ + p₂ = 1/φ and p₁ + p₂ = φ meet end to end on the torus, because φ = 1 + 1/φ. The beads are the 64 phase pairs
   with 0 ≤ v₁, v₂ ≤ 7, coloured by c(v₁, v₂) from the Beatty form; click one to make it the current pair.
   The stage is drawn with kit.solid (theme/viz/kit.js). Read-only probe for the browser suite: window.TORUS_DEBUG. */
(() => {
  'use strict';
  const { kit, L } = TRV, { v3, fix } = kit, P = TRV.palette;
  const $ = (id) => document.getElementById(id);
  const PHI = (1 + Math.sqrt(5)) / 2, TAU = 2 * Math.PI, SIZE = 1.25;
  const frac = (x) => x - Math.floor(x);
  const phase = (v) => frac((v + 1) * PHI);
  const s = (v) => Math.floor((v + 1) * PHI) - 1;
  /** The deficit from the Beatty form, and the region of the phase criterion it falls in. */
  const deficit = (v1, v2) => s(v1) + s(v2) - s(v1 + v2);
  const region = (p1, p2) => (p1 + p2 < 1 / PHI ? 1 : p1 + p2 >= PHI ? -1 : 0);
  const PAIRS = [];
  for (let v1 = 0; v1 <= 7; v1++) for (let v2 = 0; v2 <= 7; v2++) PAIRS.push({ v1, v2, p1: phase(v1), p2: phase(v2), c: deficit(v1, v2) });

  /* ---------- the gluing: square (g = 0) → tube (g = 1) → torus (g = 2) ----------
     The square is 2 wide (p₁) and 1 high (p₂), so that the torus has its hole. Rolling wraps p₂ round a circle of
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
    return v3.unit(v3.cross(v3.sub(a, b), v3.sub(c, d)));
  }
  const onSurface = (p1, p2, g, lift) => v3.add(shape(p1, p2, g), v3.scale(normal(p1, p2, g), lift));
  /** The two pieces of the curve p₁ + p₂ ≡ 1/φ (mod 1): p₂ = 1/φ − p₁ for p₁ ≤ 1/φ, and p₂ = φ − p₁ for p₁ ≥ 1/φ. */
  const lineA = (k, n) => { const p1 = (1 / PHI) * k / n; return [p1, 1 / PHI - p1]; };
  const lineB = (k, n) => { const p1 = 1 / PHI + (1 - 1 / PHI) * k / n; return [p1, PHI - p1]; };
  /** How far apart the ends of the two pieces are (they are the same points of the torus). */
  const gap = (g) => Math.max(v3.len(v3.sub(shape(1 / PHI, 0, g), shape(1 / PHI, 1, g))), v3.len(v3.sub(shape(0, 1 / PHI, g), shape(1, 1 / PHI, g))));

  /* ---------- state and stage ---------- */
  const S = { pick: 18 };   // index into PAIRS: (2, 2)
  let drawn = [];
  const stage = kit.solid($('stage'), {
    canvas: $('cv'), radius: TRV.thumbMode ? 0.4 : 0.36, cy: 0.54, yaw: -0.5, pitch: 0.75,
    onChange: () => paint(),
    onPick: (ev, st) => {
      const k = st.nearest(ev, drawn.map((d) => d.p), 12);
      if (k < 0) return false;
      cards.mark(null); S.pick = drawn[k].i; paint(); return true;
    }
  });
  function drawStage() {
    const st = stage, g = clock.t, lift = 0.005;
    st.begin();
    st.surface('square', (p1, p2) => shape(p1, p2, g), { u: [0, 1], v: [0, 1], nu: 120, nv: 120, value: region, colors: [P.magenta, P.dim, P.cyan], range: [-1, 1], grid: { every: [12, 12] } });
    const A = [], B = [];
    for (let k = 0; k <= 60; k++) { const a = lineA(k, 60), b = lineB(k, 60); A.push(onSurface(a[0], a[1], g, lift)); B.push(onSurface(b[0], b[1], g, lift)); }
    st.tube('lineA', A, { color: P.violet, width: 3.4 });
    st.tube('lineB', B, { color: P.violet, width: 3.4 });
    drawn = [];
    PAIRS.forEach((q, i) => {
      if (i === S.pick) return;
      const p = onSurface(q.p1, q.p2, g, lift * 1.5);
      drawn.push({ i, p });
      st.bead(p, { color: q.c > 0 ? P.cyan : q.c < 0 ? P.magenta : P.dim, r: 3.2, glow: 0.3, key: `${q.v1},${q.v2}` });
    });
    const cur = PAIRS[S.pick], cp = onSurface(cur.p1, cur.p2, g, lift * 1.5);
    drawn.push({ i: S.pick, p: cp });
    st.bead(cp, { color: P.amber, r: 6.5, key: 'current' });
    st.tag('cur', cp, `(${cur.v1}, ${cur.v2})`, 'raw', { dx: 0, dy: -18 });
    st.end();
    $('hudBig').textContent = g < 0.995 ? L(`粘合 ${fix(g, 2)} · 上下两边${g > 0.005 ? '正在靠拢' : '还没粘'}`, `glue ${fix(g, 2)} · top and bottom ${g > 0.005 ? 'closing in' : 'not glued yet'}`)
      : g < 1.995 ? L(`粘合 ${fix(g, 2)} · 管子的两端正在靠拢`, `glue ${fix(g, 2)} · the ends of the tube closing in`) : L('环面 · 两条斜线首尾相接', 'torus · the two lines meet end to end');
    $('hudSub').textContent = L(`两段斜线端点之间的距离 ${fix(gap(g) / SIZE, 3)}`, `distance between the ends of the two pieces ${fix(gap(g) / SIZE, 3)}`);
  }

  /* ---------- strip: the flat net with the glued edges ---------- */
  function drawPlot() {
    const g = kit.plot($('plot'), { x: [-0.08, 1.08], y: [-0.12, 1.12], pad: [8, 8, 6, 6], equal: true });
    g.poly([[0, 0], [1 / PHI, 0], [0, 1 / PHI]], P.cyan, { alpha: 0.35 });
    g.poly([[1, 1], [PHI - 1, 1], [1, PHI - 1]], P.magenta, { alpha: 0.35 });
    g.line([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], P.lineHot, { width: 1 });
    g.line([[0, 1 / PHI], [1 / PHI, 0]], P.violet, { width: 2.4 }); g.line([[PHI - 1, 1], [1, PHI - 1]], P.violet, { width: 2.4 });
    const glued = clock.t;
    const mark = (x0, y0, x1, y1, n, on) => { for (let k = 1; k <= n; k++) { const t = 0.5 + (k - (n + 1) / 2) * 0.05; g.text(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, '›', on ? P.amber : P.dim, { align: 'center', size: 12 }); } };
    mark(0, 0, 0, 1, 1, glued >= 1.995); mark(1, 0, 1, 1, 1, glued >= 1.995);
    mark(0, 0, 1, 0, 2, glued >= 0.995); mark(0, 1, 1, 1, 2, glued >= 0.995);
    const c = PAIRS[S.pick]; g.dot(c.p1, c.p2, P.amber, 4.5);
    $('plotMeta').textContent = L('同样记号的两条边粘在一起', 'edges with the same mark are glued');
  }

  /* ---------- readouts ---------- */
  function drawText() {
    const c = PAIRS[S.pick];
    $('roC').textContent = `c(${c.v1}, ${c.v2}) = ${c.c > 0 ? '+1' : c.c < 0 ? '−1' : '0'}`;
    $('roCSub').textContent = L(` · p₁ + p₂ = ${fix(c.p1 + c.p2, 3)}`, ` · p₁ + p₂ = ${fix(c.p1 + c.p2, 3)}`);
    $('roP').textContent = `${fix(c.p1, 3)}, ${fix(c.p2, 3)}`;
    $('roPlus').textContent = fix(1 / (2 * PHI * PHI), 4);
    $('roMinus').textContent = fix((2 - PHI) ** 2 / 2, 4);
    $('roNote').textContent = c.c > 0 ? L('p₁ + p₂ < 1/φ：在青色三角形里。', 'p₁ + p₂ < 1/φ: inside the cyan triangle.')
      : c.c < 0 ? L('p₁ + p₂ ≥ φ：在品红三角形里；环面上它与青色三角形只隔着那条紫色曲线。', 'p₁ + p₂ ≥ φ: inside the magenta triangle, which on the torus faces the cyan one across the violet curve.')
        : L('1/φ ≤ p₁ + p₂ < φ：在中间的带里。', '1/φ ≤ p₁ + p₂ < φ: in the band between.');
    $('pillGlue').querySelector('strong').textContent = fix(clock.t, 2);
    $('pillPair').querySelector('strong').textContent = `(${c.v1}, ${c.v2})`;
  }

  const paint = kit.painter(() => { drawStage(); drawPlot(); drawText(); }, [$('stage'), $('plot')]);

  /* ---------- controls: the rail is the gluing ---------- */
  const clock = kit.clock({
    range: $('now'), play: $('play'), label: $('tau'), speeds: $('speedChips'), max: 2, t: 2, rate: 0.5, step: 0.25,
    format: (t) => `${L('粘合', 'glue')} ${t.toFixed(2)} <small>/ 2</small>`,
    onChange: (t) => { fGlue.set(Math.round(t * 100) / 100); paint(); }
  });
  const fGlue = kit.field($('glue'), { fmt: (v) => fix(v, 2), onInput: (v) => { cards.mark(null); clock.pause(); clock.set(v); } });
  $('rew').addEventListener('click', () => { clock.pause(); clock.set(0); });

  /* ---------- experiment cards ---------- */
  const PRESETS = {
    square: { at: 0, view: [-0.3, 1.0, 0.95] },
    tube: { at: 1, view: [-0.45, 0.5, 1.2] },
    torus: { at: 0, play: true, still: 2, view: [-0.5, 0.8, 1.9] },
    pair: { at: 2, pick: 18, view: [-0.5, -0.85, 1.9] }
  };
  const NOTES = {
    square: ['平铺的相位正方形（横向 p₁，纵向 p₂）：青色三角形里 c = +1，品红三角形里 c = −1，其余 c = 0；两条紫色斜线是 p₁ + p₂ = 1/φ 与 p₁ + p₂ = φ。',
      'The phase square laid flat (p₁ across, p₂ up): c = +1 in the cyan triangle, c = −1 in the magenta one, c = 0 elsewhere; the two violet lines are p₁ + p₂ = 1/φ and p₁ + p₂ = φ.'],
    tube: ['p₂ = 0 与 p₂ = 1 是同一个相位：把上下两边粘起来，正方形卷成一根管子。品红三角形的上边贴到了青色三角形的下边上。',
      'p₂ = 0 and p₂ = 1 are the same phase: glue the top to the bottom and the square rolls into a tube. The top of the magenta triangle now lies against the bottom of the cyan one.'],
    torus: ['再把左右两边粘起来：管子弯成环面。两条紫色斜线首尾相接，成了环面上的一条闭曲线（φ = 1 + 1/φ），青色与品红两块三角形隔着它相对。',
      'Then glue left to right: the tube bends round into a torus. The two violet lines meet end to end into one closed curve on the torus (φ = 1 + 1/φ), with the cyan and magenta triangles facing each other across it.'],
    pair: ['琥珀色的珠子是 (v₁, v₂) = (2, 2)：p(2) + p(2) ≈ 1.708 ≥ φ，落在品红三角形里，c(2, 2) = −1。点环面上别的珠子换一对。',
      'The amber bead is (v₁, v₂) = (2, 2): p(2) + p(2) ≈ 1.708 ≥ φ, inside the magenta triangle, so c(2, 2) = −1. Click another bead on the torus to change the pair.']
  };
  let booting = true;
  function applyPreset(id) {
    const p = PRESETS[id];
    if (p.pick != null) S.pick = p.pick;
    clock.pause(); clock.set(p.at);
    if (booting || TRV.still) { stage.cam.yaw = p.view[0]; stage.cam.pitch = p.view[1]; stage.cam.zoom = p.view[2]; } else stage.view(p.view, 600);
    if (p.play) { if (TRV.still || (booting && !TRV.embed)) clock.set(p.still); else if (booting) kit.autoplay(clock, $('stage')); else clock.play(); }
    paint();
  }
  const cards = kit.cards($('presets'), { notes: NOTES, noteEl: $('presetNote'), tour: $('tour'), onPick: applyPreset,
    idle: ['自由探索：拖动时间轴或滑块改变粘合程度，拖动舞台转动环面，点一颗珠子换一对数。', 'Free play: move the rail or the slider to glue, drag the stage to turn the torus, click a bead to change the pair.'] });

  TRV.drawer({ drawer: $('drawer'), open: $('infoBtn'), close: $('drawerClose') });
  TRV.startGlitch(document.querySelector('.brand'));

  /* ---------- probe, cover, start ---------- */
  window.TORUS_DEBUG = {
    get state() { const c = PAIRS[S.pick]; return { preset: cards.current, glue: clock.t, playing: clock.playing, pick: { v1: c.v1, v2: c.v2, p1: c.p1, p2: c.p2, c: c.c }, gap: gap(clock.t) / SIZE, mode: stage.mode }; },
    /** The point of the solid at phases (p₁, p₂) and glue g, as the page draws it. */
    shape: (p1, p2, g) => shape(p1, p2, g == null ? clock.t : g),
    /** The region the page colours at (p₁, p₂): +1, 0 or −1. */
    region,
    /** The pairs as the page computes them. */
    pairs: () => PAIRS.map((q) => ({ ...q })),
    /** Viewport coordinates of the bead of pair index i (and whether a solid hides it). */
    bead: (i) => { const d = drawn.find((x) => x.i === i), q = stage.p(d.p), b = $('stage').getBoundingClientRect(); return { x: b.left + q[0], y: b.top + q[1], hidden: stage.occluded(d.p, 0.02) }; },
    hit: (x, y) => { const h = stage.hit({ clientX: x, clientY: y }); return h && { id: h.id, u: h.u, v: h.v }; },
    view: (v) => { stage.cam.yaw = v[0]; stage.cam.pitch = v[1]; stage.cam.zoom = v[2] || 1; paint.now(); },
    seek: (t) => { clock.pause(); clock.set(t); }
  };
  window.TRV_THUMB = async () => { cards.pick('torus'); clock.pause(); clock.set(2); stage.cam.yaw = -0.5; stage.cam.pitch = 0.8; stage.cam.zoom = 1.9; await stage.ready; paint.now(); };
  cards.pick(cards.initial('torus'));   // a chapter may cite another card: ::: {.viz src="phase-torus" preset="tube"}
  booting = false;
  paint();
})();
