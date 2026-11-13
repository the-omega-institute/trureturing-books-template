#!/usr/bin/env node
// Browser checks that the modelling core (theme/viz/solid-core.js) keeps the shader programs of its frame-local
// primitives from one frame to the next, run by tools/tests/test_viz_solid.py: one line of JSON per check,
// { name, ok, detail }, then one { counts } line with what was measured.
// Lines, circles, arrows, beads, rings and fans are made anew each frame. three.js deletes a program when the last
// material using it is disposed, so a core that disposes the materials of the last frame before drawing the next one
// links the same programs again on every frame, and a played page stalls on a busy machine (getProgramInfoLog waits
// for each link). Here every frame is really drawn (draw calls, pixels read back) and the WebGL calls are counted per
// context in the page (linkProgram, live programs and buffers, draws); materials are counted through the THREE that
// the core exports. Link counts are deterministic; nothing here depends on wall-clock time.
// SOLID_CORE=<file> serves that file as assets/solid-core.js: a counterfactual run against another version of the core.
// The fixture page lives under the viz/ of the first visible book with one (see solid_harness.mjs); without one, a
// single { skip } line.
import fs from 'node:fs';
import path from 'node:path';
import { session, settle } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';

const out = (name, ok, detail = '') => console.log(JSON.stringify({ name, ok: !!ok, detail: String(detail) }));
const book = listBooks().find((b) => fs.existsSync(path.join(b.dir, 'viz')));
if (!book) { console.log(JSON.stringify({ skip: 'no visible book with a viz/ directory to serve the runtime from' })); process.exit(0); }
const T = await session({ viewport: { width: 800, height: 600 } });
const page = T.page;
const FIXTURE = `${T.origin}/site/${book.slug}/viz/__programs__/`;
const HTML = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="../assets/theme.css">
<script src="../assets/shell.js"></script><script src="../assets/kit.js"></script>
<style>#st { position: absolute; left: 0; top: 0; width: 720px; height: 480px; } #st canvas { position: absolute; inset: 0; width: 100%; height: 100%; }</style>
</head><body><div id="st" class="stage"><canvas id="cv"></canvas></div></body></html>`;
await page.route(`${FIXTURE}**`, (r) => r.fulfill({ contentType: 'text/html', body: HTML }));
if (process.env.SOLID_CORE) {
  const body = fs.readFileSync(process.env.SOLID_CORE);
  await page.route('**/assets/solid-core.js', (r) => r.fulfill({ contentType: 'text/javascript', body }));
}
/* WebGL calls, per context (gl.__n) and for the whole page (window.__gl) */
await T.context.addInitScript(() => {
  const all = window.__gl = { link: 0, draws: 0 };
  const of = (gl) => gl.__n || (gl.__n = { link: 0, programs: 0, buffers: 0, draws: 0 });
  for (const C of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
    if (!C) continue;
    const P = C.prototype;
    const wrap = (name, f) => { const o = P[name]; if (o) P[name] = function (...a) { const r = o.apply(this, a); f(of(this), a, r); return r; }; };
    wrap('linkProgram', (n) => { n.link++; all.link++; });
    wrap('createProgram', (n, a, r) => { if (r) n.programs++; });
    wrap('deleteProgram', (n, a) => { if (a[0]) n.programs--; });
    wrap('createBuffer', (n, a, r) => { if (r) n.buffers++; });
    wrap('deleteBuffer', (n, a) => { if (a[0]) n.buffers--; });
    for (const d of ['drawElements', 'drawArrays']) wrap(d, (n) => { n.draws++; all.draws++; });
  }
});
await page.goto(FIXTURE);

/* ---------- the core on its own, as the film engine drives it: begin, primitives, end, render ---------- */
const core = await page.evaluate(async () => {
  const mod = await import(new URL('../assets/solid-core.js', location.href).href);
  const T = mod.THREE, P = TRV.palette, TAU = Math.PI * 2;
  const cv = document.createElement('canvas'); cv.width = 480; cv.height = 320;
  const r = mod.createRenderer(cv, { pixelRatio: 1 }), gl = r.getContext();
  const sc = mod.createScene({ palette: { stage: P.stage, ink: P.ink, cyan: P.cyan, violet: P.violet, amber: P.amber } });
  /* live materials: created (material ids are consecutive, a probe is one more) less disposed */
  let disposed = 0, probes = 0;
  const dispose = T.Material.prototype.dispose;
  T.Material.prototype.dispose = function () { disposed++; return dispose.call(this); };
  const made = () => { probes++; return new T.Material().id + 1 - probes; };
  const base = made(), mats = () => made() - base - disposed;
  const n = () => gl.__n || { link: 0, programs: 0, buffers: 0, draws: 0 };
  const pix = () => {
    const c = document.createElement('canvas'); c.width = cv.width; c.height = cv.height;
    const g = c.getContext('2d'); g.drawImage(cv, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let h = 0, ink = 0;
    for (let i = 0; i < d.length; i += 4) { h = (h * 31 + d[i] + 7 * d[i + 1] + 13 * d[i + 2] + 17 * d[i + 3]) >>> 0; if (d[i + 3] > 0) ink++; }
    return { h, ink: ink / (d.length / 4), size: [cv.width, cv.height] };
  };
  /* the state repeats every 8 frames; every kind of primitive (opaque and translucent) is in every frame */
  const S = { W: 480, H: 320, nu: 24, nv: 16, colors: [P.cyan, P.violet], alpha: 1, loose: true, extra: false };
  const draw = (k, render) => {
    const ph = TAU * (k % 8) / 8;
    sc.camera({ W: S.W, H: S.H, yaw: 0.35 + 0.12 * Math.sin(ph), pitch: 0.4, radius: 0.26 });
    sc.begin();
    sc.surface('sheet', (u, v) => [u, v, 0.25 * Math.sin(2.2 * u + ph) * Math.cos(1.7 * v)], { u: [-1, 1], v: [-1, 1], nu: S.nu, nv: S.nv, value: (u) => u, colors: S.colors, range: [-1, 1], grid: { every: [4, 4] }, alpha: S.alpha });
    sc.tube('path', Array.from({ length: 40 }, (_, i) => { const a = TAU * i / 39; return [0.9 * Math.cos(a + ph), 0.9 * Math.sin(a + ph), 0.35 + 0.1 * Math.sin(3 * a)]; }), { color: P.amber, width: 3, alpha: (t) => 0.35 + 0.65 * t });
    sc.poly('tet', { vertices: [[1.3, 0, 0.1], [1.6, 0.2, 0.1], [1.4, -0.3, 0.1], [1.43, -0.03, 0.5]], faces: [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]] }, { color: P.violet });
    sc.glass('shell', [-1.25, 0, 0.4], 0.35);
    if (S.loose) {
      sc.line([[-1, -1, 0.6], [1, -1, 0.6 + 0.2 * Math.sin(ph)]], { color: P.cyan, width: 2 });
      sc.line([[-1, 1, 0.6], [1, 1, 0.6]], { color: P.ink, width: 1.5, dash: [8, 6], alpha: 0.6 });
      sc.circle([0, 0, 0.2], [0, 0, 1], 1.05, { color: P.violet, width: 1.5 });     // its far side dimmed
      sc.arrow([0, 0, 0.3], [0.8 * Math.cos(ph), 0.8 * Math.sin(ph), 0.7], { color: P.amber });
      sc.bead([0.9 * Math.cos(ph), 0.9 * Math.sin(ph), 0.45], { color: P.amber, key: 'now' });
      sc.bead([-0.5, 0.5, 0.5], { color: P.cyan, alpha: 0.5 + 0.2 * Math.sin(ph), r: 4 });
      sc.ring([0.5, -0.5, 0.3], { color: P.violet, normal: [0, 0, 1] });
      sc.fan([[-0.8, -0.8, 0.05], [-0.2, -0.8, 0.05], [-0.5, -0.3, 0.05]], { fill: P.cyan, alpha: 0.3, color: P.cyan });
      if (S.extra) {
        sc.arrow([0, 0, -0.2], [-0.7, 0.4, -0.4], { color: P.violet, alpha: 0.5, dash: [5, 4] });
        sc.fan([[0.2, 0.2, -0.1], [0.7, 0.2, -0.1], [0.45, 0.6, -0.1]], { fill: P.amber, alpha: 1 });
      }
    }
    sc.end();
    if (render) sc.render(r);
  };
  const run = (k0, count, render = true) => {
    const rows = [];
    for (let k = k0; k < k0 + count; k++) {
      const a = { ...n() };
      draw(k, render);
      const b = n();
      rows.push({ k, link: b.link - a.link, draws: b.draws - a.draws, calls: render ? r.info.render.calls : 0, programs: b.programs, progs: r.info.programs.length, buffers: b.buffers, mats: mats(), geos: r.info.memory.geometries, px: render ? pix() : null });
    }
    return rows;
  };
  const res = {};
  res.warm = run(0, 8);                         // one cycle: every program is linked here
  res.steady = run(8, 16);                      // two more cycles
  res.again = run(8, 1)[0];                     // the state of frame 8 drawn again
  Object.assign(S, { nu: 40, nv: 30, colors: [P.amber, P.cyan], alpha: 0.8, extra: true });
  res.change = run(24, 9);                      // geometry, colours, a translucent sheet, new kinds of primitive
  Object.assign(S, { W: 400, H: 400 }); res.resize = run(33, 4);
  Object.assign(S, { W: 560, H: 300 }); res.resize.push(...run(37, 4));
  Object.assign(S, { loose: false }); res.release = run(41, 2);    // only the keyed objects (7 materials)
  Object.assign(S, { loose: true }); res.back = run(43, 4);
  res.undrawn = [];                             // the same frame built six times and never drawn
  for (let i = 0; i < 6; i++) res.undrawn.push(run(47, 1, false)[0]);
  res.redrawn = run(43, 1)[0];                  // then drawn again: the state of the first frame of res.back
  sc.dispose();
  res.disposed = { mats: mats(), geos: r.info.memory.geometries };
  return res;
});
const links = (rows) => rows.map((x) => x.link);
const sum = (a) => a.reduce((s, x) => s + x, 0);
const allDrawn = (rows) => rows.every((x) => x.draws >= 12 && x.calls >= 12 && x.px.ink > 0.04);
out('core: the first frame links the programs it needs (the counter sees links)', core.warm[0].link > 0 && allDrawn(core.warm), `links ${links(core.warm)}, draws ${core.warm.map((x) => x.draws)}`);
out('core: after one cycle, frames that draw the same kinds of primitive link no program', sum(links(core.steady)) === 0 && allDrawn(core.steady),
  `links ${links(core.steady)}; draws ${core.steady.map((x) => x.draws)}; ink ${core.steady.map((x) => x.px.ink.toFixed(2))}`);
{
  const s = core.steady, keys = ['programs', 'progs', 'buffers', 'mats', 'geos'];
  const bad = s.slice(0, 8).filter((x, i) => keys.some((key) => x[key] !== s[i + 8][key]));
  out('core: live programs, buffers, materials and geometries are the same one cycle later (nothing piles up)', bad.length === 0,
    bad.length ? JSON.stringify(bad.map((x) => keys.map((key) => x[key]))) : `per phase ${s.slice(0, 8).map((x) => `${x.programs}p/${x.buffers}b/${x.mats}m/${x.geos}g`).join(' ')}`);
  out('core: the same state gives the same pixels, the next state other pixels', s[0].px.h === s[8].px.h && core.again.px.h === s[0].px.h && s[0].px.h !== s[1].px.h,
    `${s[0].px.h} ${s[8].px.h} ${core.again.px.h} / ${s[1].px.h}`);
}
out('core: a change of geometry, colours and kinds of primitive links on its first frame only', sum(links(core.change.slice(1))) === 0 && allDrawn(core.change) && core.change[0].px.h !== core.steady[0].px.h,
  `links ${links(core.change)}; first-frame pixels ${core.change[0].px.h} vs ${core.steady[0].px.h}`);
{
  const z = core.resize, last = z[z.length - 1];
  out('core: resizing the canvas links no program', sum(links(z)) === 0 && allDrawn(z) && z[0].px.size.join() === '400,400' && last.px.size.join() === '560,300',
    `links ${links(z)}; sizes ${z[0].px.size} → ${last.px.size}`);
}
{
  const [a, b] = core.release, s = core.steady[0];
  out('core: primitives no longer drawn are released with their materials, buffers and programs', a.mats === 7 && b.mats === 7 && a.programs < s.programs && b.programs === a.programs && a.buffers < s.buffers && b.buffers === a.buffers,
    `materials ${s.mats} → ${a.mats}, ${b.mats}; programs ${s.programs} → ${a.programs}, ${b.programs}; buffers ${s.buffers} → ${a.buffers}, ${b.buffers}`);
  out('core: when they come back, their programs are linked on the first frame only', core.back[0].link > 0 && sum(links(core.back.slice(1))) === 0 && allDrawn(core.back), `links ${links(core.back)}`);
}
{
  const u = core.undrawn, m = u.map((x) => x.mats);
  out('core: frames built but not drawn keep at most one frame of materials, and the next drawn frame lets them go',
    m.slice(1).every((x) => x === m[1]) && core.redrawn.mats === core.back[0].mats && allDrawn([core.redrawn]),
    `materials ${m} → ${core.redrawn.mats} (the same state drawn before: ${core.back[0].mats})`);
}
out('core: dispose() frees every material and geometry', core.disposed.mats === 0 && core.disposed.geos === 0, JSON.stringify(core.disposed));

/* ---------- the interactive shell: kit.solid, its painter, parking and waking, resizing ---------- */
await page.evaluate(() => {
  const kit = TRV.kit, P = TRV.palette, TAU = Math.PI * 2;
  window.K = 0;
  const sc = kit.solid(document.getElementById('st'), { canvas: document.getElementById('cv'), radius: 0.2, yaw: 0.3, pitch: 0.25, onChange: () => paint() });
  window.SC = sc;
  const paint = kit.painter(() => {
    const ph = TAU * (window.K % 8) / 8;
    sc.begin();
    sc.surface('ball', (u, v) => [Math.sin(v) * Math.cos(u), Math.sin(v) * Math.sin(u), Math.cos(v)], { u: [0, TAU], v: [0, Math.PI], nu: 48, nv: 24, color: P.cyan });
    sc.line([[-1.6, -1.2, 0], [1.6, -1.2, 0.3 * Math.sin(ph)]], { color: P.ink, width: 2 });
    sc.circle([0, 0, 0], [0, 0, 1], 1.25, { color: P.violet, dash: [6, 5] });
    sc.arrow([0, 0, 1], [0.6 * Math.cos(ph), 0.6 * Math.sin(ph), 1.6], { color: P.amber });
    sc.bead(sc.facing().map((x) => x * 1.3), { color: P.amber, key: 'front' });
    sc.bead(sc.facing().map((x) => -x * 1.3), { color: P.magenta, key: 'back' });
    sc.bead([1.5, 0, 0.8], { color: P.cyan, alpha: 0.5, key: 'faint' });
    sc.ring([0, 0, 1], { color: P.violet, normal: [0, 0, 1] });
    sc.fan([[1.3, -0.4, -0.6], [1.8, -0.4, -0.6], [1.55, 0.1, -0.6]], { fill: P.amber, alpha: 0.35, color: P.amber });
    sc.end();
  });
  window.PAINT = paint;
});
await settle(page);
/* count frames drawn by the painter: links and draw calls of the page per frame */
const frames = (count) => page.evaluate((count) => {
  const rows = [];
  for (let i = 0; i < count; i++) { window.K++; const l = window.__gl.link, d = window.__gl.draws; window.PAINT.now(); rows.push([window.__gl.link - l, window.__gl.draws - d]); }
  return rows;
}, count);
const drawn = (rows) => rows.every(([, d]) => d >= 8);
const grab = () => page.evaluate(() => {
  const cv = SC.el.querySelector('canvas.solid-gl') || SC.el.querySelector('canvas:not(.solid-gl)');
  const c = document.createElement('canvas'); c.width = cv.width; c.height = cv.height; c.getContext('2d').drawImage(cv, 0, 0);
  return Array.from(c.getContext('2d').getImageData(0, 0, c.width, c.height).data.filter((_, i) => i % 97 === 0));
});
const md = (a, b) => (a.length === b.length ? a.reduce((s, x, i) => s + Math.abs(x - b[i]), 0) / a.length : Infinity);
const warm = await frames(3), steady = await frames(16);
out('kit.solid: played frames link no program after warm-up', (await page.evaluate(() => SC.mode)) === 'webgl' && sum(steady.map((x) => x[0])) === 0 && drawn(steady),
  `warm-up links ${warm.map((x) => x[0])}; then links ${steady.map((x) => x[0])}, draws ${steady.map((x) => x[1])}`);
const picks = await page.evaluate(() => {
  const c = SC.p([0, 0, 0]), h = SC.hitAt(c[0], c[1]), f = SC.facing();
  const m = Object.fromEntries(SC.marks().filter((x) => x.key).map((x) => [x.key, x.hidden]));
  return { id: h && h.id, off: h ? Math.hypot(h.point[0] - f[0], h.point[1] - f[1], h.point[2] - f[2]) : null, marks: m };
});
out('kit.solid: picking and hidden marks are unchanged', picks.id === 'ball' && picks.off < 1e-4 && picks.marks.front === false && picks.marks.back === true && picks.marks.faint === false, JSON.stringify(picks));
const before = await grab();
await page.evaluate(() => SC.park());
const parked = await page.evaluate(() => SC.parked()), l0 = await page.evaluate(() => window.__gl.link);
await page.evaluate(() => PAINT.now());             // the same state: wakes with a new context
await settle(page);
const after = await grab(), wakeLinks = (await page.evaluate(() => window.__gl.link)) - l0;
const wakeWarm = await frames(2), wakeSteady = await frames(16);
const contexts = await page.evaluate(() => SC.contexts);
out('kit.solid: after parking and waking, the new context draws the same picture and links nothing once warm',
  parked && contexts === 2 && wakeLinks > 0 && md(before, after) < 1 && sum(wakeSteady.map((x) => x[0])) === 0 && drawn(wakeSteady),
  `parked ${parked}, contexts ${contexts}, links on waking ${wakeLinks}, mean |Δ| ${md(before, after).toFixed(3)}; warm-up links ${wakeWarm.map((x) => x[0])}; then ${wakeSteady.map((x) => x[0])}`);
const size = () => page.evaluate(() => { const g = SC.el.querySelector('canvas.solid-gl'); return [SC.W, SC.H, g.width, g.height, g.clientWidth, g.clientHeight]; });
const size0 = await size();
await page.evaluate(() => { const st = document.getElementById('st'); st.style.width = '560px'; st.style.height = '360px'; });
const resized = await frames(8), size1 = await size();
out('kit.solid: resizing the stage links no program', size1[0] < size0[0] && size1[1] < size0[1] && size1[2] === size1[4] && size1[3] === size1[5] && sum(resized.map((x) => x[0])) === 0 && drawn(resized),
  `size ${size0} → ${size1}; links ${resized.map((x) => x[0])}`);
out('no page error, console error or failed request', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
console.log(JSON.stringify({ counts: {
  core: Object.fromEntries(Object.entries(core).map(([k, v]) => [k, Array.isArray(v) ? v.map(({ px, ...x }) => ({ ...x, h: px && px.h })) : v])),
  kit: { warm, steady, wakeLinks, wakeWarm, wakeSteady, resized }
} }));
await T.browser.close();
process.exit(0);
