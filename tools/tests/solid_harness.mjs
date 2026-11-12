#!/usr/bin/env node
// Browser checks of kit.solid (theme/viz/kit.js), run by tools/tests/test_viz_solid.py: one line of JSON per check,
// { name, ok, detail }. A fixture page under the viz/ of a visible book is served by the same viz server as the books
// (so assets/kit.js and assets/vendor/ come from theme/viz/), and every claim is checked against an independent
// computation written here: rays against the analytic sphere and torus, the camera basis of kit.stage3.
// The book is the first visible one with a viz/ directory: a books repository hides the template's example books
// (site.toml hide = ["example-*"]), and the server serves visible books only. Without one, a single { skip } line.
import fs from 'node:fs';
import path from 'node:path';
import { session, settle } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';

const out = (name, ok, detail = '') => console.log(JSON.stringify({ name, ok: !!ok, detail: String(detail) }));
const book = listBooks().find((b) => fs.existsSync(path.join(b.dir, 'viz')));
if (!book) { console.log(JSON.stringify({ skip: 'no visible book with a viz/ directory to serve the runtime from' })); process.exit(0); }
const T = await session({ viewport: { width: 800, height: 600 } });
const FIXTURE = `${T.origin}/site/${book.slug}/viz/__solid__/`;
const HTML = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="../assets/theme.css">
<script src="../assets/shell.js"></script><script src="../assets/kit.js"></script>
<style>#st { position: absolute; left: 0; top: 0; width: 800px; height: 600px; } #st canvas { position: absolute; inset: 0; width: 100%; height: 100%; }</style>
</head><body><div id="st" class="stage"><canvas id="cv"></canvas></div></body></html>`;
await T.page.route(`${FIXTURE}**`, (r) => r.fulfill({ contentType: 'text/html', body: HTML }));
const requests = [];
T.page.on('request', (r) => requests.push(r.url()));
const page = T.page;
await page.goto(FIXTURE + `?park=${process.env.SOLID_PARK || ''}`);
out('no three.js before kit.solid is called', !requests.some((u) => u.includes('/vendor/') || u.includes('solid-core')));

/* the scene: a unit sphere at the origin, a torus (R = 0.6, a = 0.22) round the z axis at x = 2.2, a flat square
   at x = −2.2 facing +y; beads in front of and behind the sphere */
await page.evaluate(() => {
  const kit = TRV.kit, P = TRV.palette, TAU = Math.PI * 2;
  const sc = kit.solid(document.getElementById('st'), { canvas: document.getElementById('cv'), radius: 0.16, yaw: 0.3, pitch: 0.25, park: Number(new URLSearchParams(location.search).get('park')) || 0, onChange: () => paint() });
  window.SC = sc;
  window.SPHERE = (u, v) => [Math.sin(v) * Math.cos(u), Math.sin(v) * Math.sin(u), Math.cos(v)];
  window.TORUS = (u, v) => [2.2 + (0.6 + 0.22 * Math.cos(v)) * Math.cos(u), (0.6 + 0.22 * Math.cos(v)) * Math.sin(u), 0.22 * Math.sin(v)];
  const paint = kit.painter(() => {
    sc.begin();
    sc.surface('sphere', SPHERE, { u: [0, TAU], v: [0, Math.PI], nu: 64, nv: 32, color: P.cyan });
    sc.surface('torus', TORUS, { u: [0, TAU], v: [0, TAU], nu: 64, nv: 24, color: P.magenta });
    sc.surface('square', (u, v) => [-2.2 + u, 0, v], { u: [-0.5, 0.5], v: [-0.5, 0.5], nu: 4, nv: 4, color: P.violet });
    sc.bead([0, 0, 0], { key: 'inside', r: 4 });
    sc.end();
  });
  window.PAINT = paint;
});
await settle(page);
out('three.js is fetched by the first call of kit.solid', requests.some((u) => u.includes('/vendor/three.module.min.js')) && requests.some((u) => u.includes('/solid-core.js')));
out('the stage renders with WebGL', (await page.evaluate(() => SC.mode)) === 'webgl', await page.evaluate(() => SC.mode));

/* ---------- independent geometry ---------- */
const basis = (yaw, pitch) => {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  return { R: [cy, -sy, 0], U: [sy * sp, cy * sp, cp], D: [-sy * cp, -cy * cp, sp] };
};
const add = (a, b) => a.map((x, i) => x + b[i]), sc3 = (a, k) => a.map((x) => x * k), dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
/** The ray of an orthographic camera through stage pixel (x, y): origin far towards the viewer, direction −D. */
async function rayAt(x, y) {
  const c = await page.evaluate(() => ({ yaw: SC.cam.yaw, pitch: SC.cam.pitch, cx: SC.cx, cy: SC.cy, unit: SC.unit }));
  const { R, U, D } = basis(c.yaw, c.pitch);
  const o = add(add(sc3(R, (x - c.cx) / c.unit), sc3(U, (c.cy - y) / c.unit)), sc3(D, 20));
  return { o, d: sc3(D, -1), D };
}
/** The first hit of the ray with the unit sphere (closed form) or the torus (sampling, then bisection). */
function sphereHit(r) {
  const b = dot(r.o, r.d), c = dot(r.o, r.o) - 1, disc = b * b - c;
  return disc < 0 ? null : add(r.o, sc3(r.d, -b - Math.sqrt(disc)));
}
function torusHit(r) {
  const F = (p) => { const q = Math.hypot(p[0] - 2.2, p[1]) - 0.6; return q * q + p[2] * p[2] - 0.22 * 0.22; };
  let prev = F(r.o), t0 = 0;
  for (let t = 0.0005; t < 40; t += 0.0005) {
    const f = F(add(r.o, sc3(r.d, t)));
    if (prev > 0 && f <= 0) { let a = t0, b = t; for (let k = 0; k < 80; k++) { const m = (a + b) / 2; if (F(add(r.o, sc3(r.d, m))) > 0) a = m; else b = m; } return add(r.o, sc3(r.d, (a + b) / 2)); }
    prev = f; t0 = t;
  }
  return null;
}
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/* picking on the sphere and the torus against the analytic surfaces */
let worst = 0, worstUV = 0, n = 0, miss = '';
const sphereC = await page.evaluate(() => SC.p([0, 0, 0]));
for (let k = 0; k < 40; k++) {
  const a = k * 2.39996, r = 0.92 * Math.sqrt((k + 0.5) / 40), x = sphereC[0] + r * Math.cos(a) * (await page.evaluate(() => SC.unit)), y = sphereC[1] + r * Math.sin(a) * (await page.evaluate(() => SC.unit));
  const h = await page.evaluate(([px, py]) => SC.hitAt(px, py), [x, y]), want = sphereHit(await rayAt(x, y));
  if (!want) continue;
  if (!h || h.id !== 'sphere') { miss = `sphere at ${x.toFixed(1)}, ${y.toFixed(1)}: ${JSON.stringify(h)}`; break; }
  const fp = await page.evaluate(([u, v]) => SPHERE(u, v), [h.u, h.v]);
  worst = Math.max(worst, dist(h.point, want)); worstUV = Math.max(worstUV, dist(fp, want)); n++;
}
out('picking on the sphere agrees with the analytic intersection (point and (u, v))', !miss && n >= 30 && worst < 1e-5 && worstUV < 1e-5, miss || `${n} rays, |Δp| ≤ ${worst.toExponential(2)}, |f(u, v) − p| ≤ ${worstUV.toExponential(2)}`);
worst = 0; worstUV = 0; n = 0; miss = '';
const torC = await page.evaluate(() => SC.p([2.2, 0, 0])), unit = await page.evaluate(() => SC.unit);
for (let k = 0; k < 60; k++) {
  const a = k * 2.39996, r = 0.82 * Math.sqrt((k + 0.5) / 60), x = torC[0] + r * Math.cos(a) * unit, y = torC[1] + r * Math.sin(a) * unit * 0.6;
  const want = torusHit(await rayAt(x, y)), h = await page.evaluate(([px, py]) => SC.hitAt(px, py), [x, y]);
  if (!want) { if (h && h.id === 'torus') { miss = `torus hit where the ray misses at ${x.toFixed(1)}, ${y.toFixed(1)}`; break; } continue; }
  if (!h || h.id !== 'torus') { miss = `torus missed at ${x.toFixed(1)}, ${y.toFixed(1)}: ${JSON.stringify(h)}`; break; }
  const fp = await page.evaluate(([u, v]) => TORUS(u, v), [h.u, h.v]);
  worst = Math.max(worst, dist(h.point, want)); worstUV = Math.max(worstUV, dist(fp, want)); n++;
}
out('picking on the torus (front and inner walls) agrees with the ray–torus root', !miss && n >= 20 && worst < 1e-5 && worstUV < 1e-5, miss || `${n} rays, |Δp| ≤ ${worst.toExponential(2)}, |f(u, v) − p| ≤ ${worstUV.toExponential(2)}`);

/* occlusion flips when the camera goes round to the other side */
const occ = async () => page.evaluate(() => ({ front: SC.occluded(SC.facing().map((x) => x * 1.3)), back: SC.occluded(SC.facing().map((x) => -x * 1.3)), inside: SC.occluded([0, 0, 0]), fixed: SC.occluded([0, 1.3, 0]) }));
let o1 = await occ();
await page.evaluate(() => { SC.cam.yaw += Math.PI; PAINT.now(); });
let o2 = await occ();
out('a point in front of the sphere is visible, one behind it and its centre are hidden', !o1.front && o1.back && o1.inside && !o2.front && o2.back, JSON.stringify([o1, o2]));
out('turning the camera half round swaps what the sphere hides', o1.fixed !== o2.fixed, JSON.stringify([o1.fixed, o2.fixed]));
const marks = await page.evaluate(() => SC.marks());
out('a mark inside the sphere cannot be picked', marks.length === 1 && marks[0].hidden && (await page.evaluate((m) => SC.nearest({ clientX: m.x, clientY: m.y }, [m.p], 8), marks[0])) === -1);

/* the front and the back of a surface differ */
const pixel = (x, y) => page.evaluate(([px, py]) => {
  const cv = SC.el.querySelector('canvas.solid-gl'), c = document.createElement('canvas'); c.width = cv.width; c.height = cv.height;
  const g = c.getContext('2d'); g.drawImage(cv, 0, 0); const k = cv.width / cv.clientWidth; return [...g.getImageData(Math.round(px * k), Math.round(py * k), 1, 1).data];
}, [x, y]);
await page.evaluate(() => { SC.cam.yaw = 0; SC.cam.pitch = 0; PAINT.now(); });
let q = await page.evaluate(() => SC.p([-2.2, 0, 0]));
const front = await pixel(q[0], q[1]), hf = await page.evaluate(([x, y]) => SC.hitAt(x, y), q);
await page.evaluate(() => { SC.cam.yaw = Math.PI; PAINT.now(); });
q = await page.evaluate(() => SC.p([-2.2, 0, 0]));
const back = await pixel(q[0], q[1]), hb = await page.evaluate(([x, y]) => SC.hitAt(x, y), q);
const diff = Math.abs(front[0] - back[0]) + Math.abs(front[1] - back[1]) + Math.abs(front[2] - back[2]);
out('the two sides of a surface are told apart (colour and hit.front)', front[3] === 255 && back[3] === 255 && diff > 30 && hf && hb && hf.front !== hb.front, `${front} / ${back}; front ${hf && hf.front} / ${hb && hb.front}`);

/* lit: the sphere is shaded (not one flat colour) */
await page.evaluate(() => { SC.cam.yaw = 0.3; SC.cam.pitch = 0.25; PAINT.now(); });
const c0 = await page.evaluate(() => SC.p([0, 0, 0])), u0 = await page.evaluate(() => SC.unit);
const lit = await pixel(c0[0] - 0.4 * u0, c0[1] - 0.5 * u0), shade = await pixel(c0[0] + 0.55 * u0, c0[1] + 0.55 * u0);
out('one key light: the upper left of the sphere is brighter than the lower right', lit[0] + lit[1] + lit[2] > shade[0] + shade[1] + shade[2] + 60, `${lit} / ${shade}`);

/* giving the context back and taking it again draws the same frame */
const grab = () => page.evaluate(() => {
  const cv = SC.el.querySelector('canvas.solid-gl') || SC.el.querySelector('canvas:not(.solid-gl)');
  const c = document.createElement('canvas'); c.width = cv.width; c.height = cv.height; c.getContext('2d').drawImage(cv, 0, 0);
  return Array.from(c.getContext('2d').getImageData(0, 0, c.width, c.height).data.filter((_, i) => i % 97 === 0));
});
const before = await grab();
await page.evaluate(() => SC.park());
const parked = await page.evaluate(() => ({ parked: SC.parked(), gl: !!SC.el.querySelector('canvas.solid-gl'), still: getComputedStyle(document.getElementById('cv')).visibility }));
const still = await grab();
await page.evaluate(() => PAINT.now());
await settle(page);
const again = await grab();
const md = (a, b) => a.reduce((s, x, i) => s + Math.abs(x - b[i]), 0) / a.length;
out('parking gives the WebGL context back and leaves the frame on the 2D canvas', parked.parked && !parked.gl && parked.still === 'visible' && md(before, still) < 2, `${JSON.stringify(parked)}, mean |Δ| ${md(before, still).toFixed(2)}`);
out('the next frame takes a new context and draws the same picture', !(await page.evaluate(() => SC.parked())) && md(before, again) < 1, `mean |Δ| ${md(before, again).toFixed(3)}`);
const ctx = await page.evaluate(() => SC.contexts);
out('one context per stay on screen (2 after one park)', ctx === 2, String(ctx));

/* the modelling core on its own, as the film engine uses it: a fixed-size canvas, pixel ratio 1, one frame drawn
   synchronously; the same state drawn twice gives the same pixels; the projection agrees with the camera basis */
const core = await page.evaluate(async () => {
  const mod = await import(new URL('../assets/solid-core.js', location.href).href);
  const P = TRV.palette, cv = document.createElement('canvas'); cv.width = 640; cv.height = 360;
  const r = mod.createRenderer(cv, { pixelRatio: 1 }), sc = mod.createScene({ palette: { stage: P.stage, cyan: P.cyan, violet: P.violet, amber: P.amber, ink: P.ink } });
  const draw = (yaw) => {
    sc.camera({ W: 640, H: 360, yaw, pitch: 0.4, zoom: 1, radius: 0.3 });
    sc.begin(); sc.surface('s', (u, v) => [Math.sin(v) * Math.cos(u), Math.sin(v) * Math.sin(u), Math.cos(v)], { u: [0, 6.2832], v: [0, 3.1416], nu: 48, nv: 24, color: P.violet }); sc.bead([0, 0, 1.2], { key: 'top' }); sc.end();
    sc.render(r);
    const c = document.createElement('canvas'); c.width = 640; c.height = 360; c.getContext('2d').drawImage(cv, 0, 0);
    const d = c.getContext('2d').getImageData(0, 0, 640, 360).data; let h = 0, n = 0; for (let i = 0; i < d.length; i += 4) { h = (h * 31 + d[i] + 7 * d[i + 1] + 13 * d[i + 2] + 17 * d[i + 3]) >>> 0; if (d[i + 3] > 250) n++; }
    return { h, n, size: [cv.width, cv.height] };
  };
  const a = draw(0.3), b = draw(0.3), c = draw(1.3);
  const q = sc.p([0, 0, 1.2]), hidden = sc.occluded([0, 0, 0]), shown = sc.occluded([0, 0, 1.2]);
  return { a, b, c, q, hidden, shown };
});
out('core: one frame drawn synchronously into a 640 × 360 canvas at pixel ratio 1', core.a.size[0] === 640 && core.a.size[1] === 360 && core.a.n > 640 * 360 * 0.1, JSON.stringify(core.a));
out('core: the same state drawn twice gives the same pixels, another view different ones', core.a.h === core.b.h && core.a.h !== core.c.h, `${core.a.h} ${core.b.h} ${core.c.h}`);
{
  const { R, U } = basis(1.3, 0.4), u = 360 * 0.3, want = [320 + u * dot([0, 0, 1.2], R), 180 - u * dot([0, 0, 1.2], U)];
  out('core: the projection of an anchor agrees with the camera basis, and says which anchors a solid hides', Math.hypot(core.q[0] - want[0], core.q[1] - want[1]) < 1e-9 && core.hidden && !core.shown, JSON.stringify(core));
}

/* a dashed line of the core (kit.solid's sc.line, the film engine's solid shots) is cut along its whole length: the
   same dashes whether the curve is sampled with 2 points or 400, and about half its length inked */
const dashes = await page.evaluate(async () => {
  const mod = await import(new URL('../assets/solid-core.js', location.href).href);
  const cv = document.createElement('canvas'); cv.width = 640; cv.height = 360;
  const r = mod.createRenderer(cv, { pixelRatio: 1 }), sc = mod.createScene({ palette: { stage: '#000000', cyan: '#ffffff' } });
  const line = (n) => Array.from({ length: n }, (_, i) => [-1.4 + 2.8 * i / (n - 1), 0, 0]);
  const draw = (pts, dash) => {
    sc.camera({ W: 640, H: 360, yaw: 0, pitch: 0, zoom: 1, radius: 0.3 });
    sc.begin(); sc.line(pts, { color: '#ffffff', width: 3, dash }); sc.end(); sc.render(r);
    const c = document.createElement('canvas'); c.width = 640; c.height = 360; c.getContext('2d').drawImage(cv, 0, 0);
    const d = c.getContext('2d').getImageData(0, 180, 640, 1).data, ink = [];
    for (let x = 0; x < 640; x++) ink.push(d[x * 4] > 128 ? 1 : 0);
    return ink;
  };
  const sparse = draw(line(2), [6, 6]), dense = draw(line(400), [6, 6]), solid = draw(line(2), null);
  const n = solid.reduce((s, x) => s + x, 0), d = sparse.reduce((s, x, i) => s + (x !== dense[i]), 0);
  return { solid: n, sparse: sparse.reduce((s, x) => s + x, 0), dense: dense.reduce((s, x) => s + x, 0), differ: d };
});
out('core: a dashed line looks the same sampled with 2 and with 400 points, about half of it inked',
  dashes.solid > 300 && dashes.differ <= dashes.solid * 0.03 && Math.abs(dashes.dense / dashes.solid - 0.5) < 0.15, JSON.stringify(dashes));

/* frame time with tens of thousands of faces (software rendering in headless Chromium) */
const perf = await page.evaluate(() => {
  const P = TRV.palette, rows = [];
  for (const [nu, nv] of [[96, 48], [192, 96], [320, 160]]) {
    const ms = [];
    for (let k = 0; k < 4; k++) {
      const t0 = performance.now();
      SC.begin(); SC.surface('big', (u, v) => [Math.sin(v) * Math.cos(u), Math.sin(v) * Math.sin(u), Math.cos(v) + 0.1 * Math.sin(4 * u + k)], { u: [0, 6.283], v: [0, 3.1416], nu, nv, color: P.cyan, grid: { every: [8, 8] } }); SC.end();
      ms.push(performance.now() - t0);
    }
    rows.push(`${nu * nv * 2} faces: ${ms.slice(1).map((x) => x.toFixed(0)).join('/')} ms`);
  }
  return rows.join('; ');
});
out('frame time (informational)', true, perf);
out('no page error, console error or failed request', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
await T.browser.close();
process.exit(0);
