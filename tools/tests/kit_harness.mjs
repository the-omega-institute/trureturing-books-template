#!/usr/bin/env node
// Browser checks of the 2D helpers of theme/viz (kit.js, shell.js, theme.css), run by tools/tests/test_viz_kit.py: one
// line of JSON per check, { name, ok, detail }. A fixture page under the viz/ of a visible book is served by the same
// viz server as the books (so assets/ come from theme/viz/), and every claim is checked against what the canvas and the
// layout really show, with the expectations computed here: dashed paths keep their dash however finely they are
// sampled, an undashed path draws exactly as the per-segment algorithm the runtime used before, kit.plot draws arrows,
// the ink swatch, capitals that keep Greek letters and one-letter variables, and the stage HUD that stacks only when
// its title and its buttons would meet. Without a visible book with a viz/ directory, a single { skip } line.
import fs from 'node:fs';
import path from 'node:path';
import { session, settle, capitalGreek } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';

const out = (name, ok, detail = '') => console.log(JSON.stringify({ name, ok: !!ok, detail: String(detail) }));
const book = listBooks().find((b) => fs.existsSync(path.join(b.dir, 'viz')));
if (!book) { console.log(JSON.stringify({ skip: 'no visible book with a viz/ directory to serve the runtime from' })); process.exit(0); }
const T = await session({ viewport: { width: 1000, height: 700 } });
const FIXTURE = `${T.origin}/site/${book.slug}/viz/__kit__/`;
const HTML = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="../assets/theme.css">
<script src="../assets/shell.js"></script><script src="../assets/kit.js"></script>
<style>body { margin: 0; } #st { position: relative; width: 600px; height: 400px; } #st canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
#pl { width: 400px; height: 300px; display: block; } #hud { position: relative; width: 100%; height: 300px; }</style>
</head><body>
<div id="st" class="stage"><canvas id="cv"></canvas></div>
<canvas id="pl"></canvas>
<i class="sw ik" id="swIk"></i><i class="sw cy" id="swCy"></i>
<section class="sec"><h2 id="h2">phase δ and u · it's Δ · the x axis · μs · e^{iθ}</h2></section>
<section class="sec"><h2 id="h2a"><span>moves in a straight line · radius a · a + b</span></h2></section>
<button class="preset"><span class="code" id="code">δ-shift</span></button>
<button class="chip" id="chip">φ gate</button>
<p id="plain">phase δ stays as written in body text</p>
<div id="hud" class="stage">
  <div class="hud-tl" id="tl"><span class="big" id="big">Cut · u = +0.30 window and title</span><span class="sub">the window is shifted by u · four points selected</span></div>
  <div class="hud-tr" id="tr"><button class="chip">Cut</button><button class="chip">Cassini</button><button class="chip">Returns</button><button class="chip">Window</button><button class="chip">Gaps</button></div>
</div>
</body></html>`;
await T.page.route(`${FIXTURE}**`, (r) => r.fulfill({ contentType: 'text/html', body: HTML }));
const page = T.page;
await page.goto(FIXTURE, { waitUntil: 'load' });
await page.evaluate(() => document.fonts && document.fonts.ready);
await settle(page);

/* ---------- dashed paths on kit.stage3 ----------
   The ink along a projected path is read back from the canvas: at points of the projected polyline spaced 0.5 px
   apart, whether the pixel is drawn (alpha above a threshold). Equal when sampled with 2 and with 400 points; about
   on / (on + off) of the length (the old per-segment dash drew a densely sampled path solid). */
await page.evaluate(() => {
  const kit = TRV.kit;
  window.ST = kit.stage3(document.getElementById('st'), { canvas: document.getElementById('cv'), yaw: 0, pitch: Math.PI / 2 - 0.001, rotate: false });
  /** Draw pts with s, then return the ink profile along the projection of `along` (default: pts). */
  window.INK = (pts, s, along, thr) => {
    const st = window.ST, ctx = st.begin(), cv = st.canvas, dpr = cv.width / cv.clientWidth;
    st.path(pts, s);
    const q = (along || pts).map((v) => st.p(v)), img = ctx.getImageData(0, 0, cv.width, cv.height).data, ink = [];
    for (let i = 1; i < q.length; i++) {
      const [ax, ay] = q[i - 1], [bx, by] = q[i], L = Math.hypot(bx - ax, by - ay);
      for (let d = 0; d < L; d += 0.5) {
        const x = Math.round((ax + (bx - ax) * d / L) * dpr - 0.5), y = Math.round((ay + (by - ay) * d / L) * dpr - 0.5);
        ink.push(img[(y * cv.width + x) * 4 + 3] > (thr == null ? 60 : thr) ? 1 : 0);
      }
    }
    return ink;
  };
  window.LINE = (n) => Array.from({ length: n }, (_, i) => [-1 + 2 * i / (n - 1), 0.2, 0]);
  window.RING = (n, z) => Array.from({ length: n }, (_, i) => { const a = 2 * Math.PI * i / n; return [0.8 * Math.cos(a), 0.8 * Math.sin(a), z || 0]; });
});
const share = (a) => a.reduce((s, x) => s + x, 0) / Math.max(1, a.length);
const differ = (a, b) => { const n = Math.min(a.length, b.length); let d = 0; for (let i = 0; i < n; i++) d += a[i] !== b[i]; return d / Math.max(1, n); };
const dashS = { color: '#ffffff', width: 1.5, dash: [6, 6] };
{
  const r = await page.evaluate((s) => ({ sparse: INK(LINE(2), s, LINE(2)), dense: INK(LINE(400), s, LINE(2)) }), dashS);
  out('stage3: a dashed straight path looks the same sampled with 2 and with 400 points',
    differ(r.sparse, r.dense) < 0.03 && Math.abs(share(r.dense) - 0.5) < 0.12,
    `differ ${(differ(r.sparse, r.dense) * 100).toFixed(1)}% · inked ${(share(r.sparse) * 100).toFixed(0)}% / ${(share(r.dense) * 100).toFixed(0)}%`);
}
{
  // the regression: a densely sampled ring (720 points, each segment ~ 1.5 px, shorter than a dash) stays dashed
  const r = await page.evaluate((s) => ({ ring: INK(RING(720), Object.assign({ close: true }, s), RING(720).concat([RING(720)[0]])),
    coarse: INK(RING(90), Object.assign({ close: true }, s), RING(720).concat([RING(720)[0]])) }), dashS);
  out('stage3: a densely sampled dashed ring stays dashed (about half its length inked)', Math.abs(share(r.ring) - 0.5) < 0.12 && Math.abs(share(r.coarse) - 0.5) < 0.15,
    `720 points: ${(share(r.ring) * 100).toFixed(0)}% · 90 points: ${(share(r.coarse) * 100).toFixed(0)}%`);
  const viaCircle = await page.evaluate((s) => { const st = window.ST; st.begin(); st.circle([0, 0, 0], [0, 0, 1], 0.8, Object.assign({ n: 720 }, s)); const cv = st.canvas; return cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data.filter((_, i) => i % 4 === 3 && _ > 60).length; }, dashS);
  const solidRing = await page.evaluate((s) => { const st = window.ST; st.begin(); st.circle([0, 0, 0], [0, 0, 1], 0.8, Object.assign({ n: 720 }, s, { dash: null })); const cv = st.canvas; return cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data.filter((_, i) => i % 4 === 3 && _ > 60).length; }, dashS);
  out('stage3: st.circle(…, { dash }) with 720 points draws about half the ink of the solid circle', viaCircle / solidRing > 0.35 && viaCircle / solidRing < 0.7,
    `${viaCircle} / ${solidRing} px`);
}
{
  // a tilted ring: half in front of the centre plane, half behind (drawn dimmer); the dash runs on across the break
  const r = await page.evaluate((s) => {
    const st = window.ST; st.cam.pitch = 0.5; st.cam.yaw = 0.3;
    const pts = RING(720), ctx = st.begin(); st.path(pts, Object.assign({ close: true }, s));
    const cv = st.canvas, dpr = cv.width / cv.clientWidth, img = ctx.getImageData(0, 0, cv.width, cv.height).data, front = [], back = [];
    for (let i = 0; i < pts.length; i++) {   // each point weighted by the projected length of its segment
      const q = st.p(pts[i]), n = st.p(pts[(i + 1) % pts.length]), a = img[(Math.round(q[1] * dpr - 0.5) * cv.width + Math.round(q[0] * dpr - 0.5)) * 4 + 3];
      (q[2] >= 0 ? front : back).push([a, Math.hypot(n[0] - q[0], n[1] - q[1])]);
    }
    st.cam.pitch = Math.PI / 2 - 0.001; st.cam.yaw = 0;
    const inked = (side, thr) => side.reduce((s, [a, w]) => s + (a > thr ? w : 0), 0) / side.reduce((s, [, w]) => s + w, 0);
    const median = (side) => { const a = side.map(([x]) => x).filter((x) => x > 0).sort((u, v) => u - v); return a[Math.floor(a.length / 2)]; };
    return { front: inked(front, 40), back: inked(back, 8), aFront: median(front), aBack: median(back) };
  }, dashS);
  out('stage3: a dashed ring through the centre plane stays dashed on both sides and dimmer behind',
    // on 6 px, off 6 px, round caps 1.5 px wide: (6 + 1.5) / 12 of the length; a dash restarted at every segment of
    // 720 inks all of it
    [r.front, r.back].every((x) => x > 0.4 && x < 0.8) && r.aBack < r.aFront * 0.6, JSON.stringify(r));
}
{
  // undashed paths draw exactly as before: the per-segment algorithm of the earlier runtime, written out here
  const same = await page.evaluate(() => {
    const st = window.ST; st.cam.pitch = 0.5; st.cam.yaw = 0.3;
    const s = { color: '#ffffff', width: 2, back: 0.3, close: true }, pts = RING(90, 0.1);
    const ctx = st.begin(); st.path(pts, s);
    const a = ctx.getImageData(0, 0, st.canvas.width, st.canvas.height).data.slice();
    st.begin();
    const q = pts.map(st.p);
    for (const front of [false, true]) {
      ctx.strokeStyle = s.color; ctx.lineWidth = s.width * st.lw; ctx.globalAlpha = front ? 1 : s.back; ctx.setLineDash([]); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath();
      const n = q.length + 1;
      for (let i = 1; i < n; i++) { const p0 = q[i - 1], p1 = q[i % q.length]; if (((p0[2] + p1[2]) / 2 >= 0) === front) { ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]); } }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    const b = ctx.getImageData(0, 0, st.canvas.width, st.canvas.height).data;
    let diff = 0; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
    st.cam.pitch = Math.PI / 2 - 0.001; st.cam.yaw = 0;
    return diff;
  });
  out('stage3: an undashed path is drawn pixel for pixel as before', same === 0, `${same} bytes differ`);
}

/* ---------- kit.plot: arrows in data coordinates ---------- */
{
  const r = await page.evaluate(() => {
    const g = TRV.kit.plot(document.getElementById('pl'), { x: [0, 10], y: [0, 10], pad: [10, 10, 10, 10] });
    g.arrow([1, 1], [8, 8], { color: '#ffffff', width: 2, headSize: 12 });
    const cv = g.ctx.canvas, dpr = cv.width / cv.clientWidth, img = g.ctx.getImageData(0, 0, cv.width, cv.height).data;
    const at = (x, y) => img[(Math.round(y * dpr - 0.5) * cv.width + Math.round(x * dpr - 0.5)) * 4 + 3];
    // the head: a filled triangle just behind the tip, wider than the shaft
    const tip = [g.X(8), g.Y(8)], ux = Math.SQRT1_2, uy = -Math.SQRT1_2, back = 8;
    const side = (k) => at(tip[0] - ux * back - uy * k, tip[1] - uy * back + ux * k);
    return { mid: at(g.X(4.5), g.Y(4.5)), off: at(g.X(4.5), g.Y(6.5)), start: at(g.X(1), g.Y(1)), past: at(g.X(9), g.Y(9)), head: [side(-1.8), side(1.8)], shaftSide: at(g.X(4.5) - uy * 2.5, g.Y(4.5) + ux * 2.5) };
  });
  out('plot: g.arrow([x0, y0], [x1, y1], s) draws a shaft in data coordinates and a head at the far end',
    r.mid > 100 && r.start > 100 && r.off === 0 && r.past === 0 && r.head.every((a) => a > 100) && r.shaftSide < 100, JSON.stringify(r));
  const api = await page.evaluate(() => { const g = TRV.kit.plot(document.getElementById('pl'), { x: [0, 1], y: [0, 1] }); return typeof g.arrow === 'function' && g.arrow.length === 3; });
  out('plot: g.arrow takes (a, b, s) as st.arrow of kit.stage3', api);
}

/* ---------- the ink swatch ---------- */
{
  const r = await page.evaluate(() => {
    const probe = document.createElement('i'); probe.style.background = 'var(--tr-ink)'; document.body.appendChild(probe);
    const want = getComputedStyle(probe).backgroundColor; probe.remove();
    return { ik: getComputedStyle(document.getElementById('swIk')).backgroundColor, cy: getComputedStyle(document.getElementById('swCy')).backgroundColor, want };
  });
  out('theme: .sw.ik is the ink swatch (the --tr-ink token)', r.ik === r.want && r.ik !== r.cy, JSON.stringify(r));
}

/* ---------- capitals that keep Greek letters and one-letter variables ---------- */
{
  await page.evaluate(() => { ST.begin(); ST.tag('d', [0, 0, 0], 'δ-shift of u by φ', ''); ST.tag('n', [0.5, 0, 0], 'Δ step', ''); ST.end(); });
  const r = await page.evaluate(() => ({
    h2: document.getElementById('h2').innerText, code: document.getElementById('code').innerText, chip: document.getElementById('chip').innerText,
    plain: document.getElementById('plain').innerText, tag: document.querySelector('#st .tag').innerText, upper: document.querySelectorAll('#st .tag')[1].innerText,
    text: document.getElementById('h2').textContent, article: document.getElementById('h2a').innerText
  }));
  out('capitals: headings keep δ, u, x, μ and θ as written and set words in capitals', r.h2 === "PHASE δ AND u · IT'S Δ · THE x AXIS · μs · e^{iθ}" && r.text === "phase δ and u · it's Δ · the x axis · μs · e^{iθ}", JSON.stringify([r.h2, r.text]));
  out('capitals: the article "a" between two words is set in capitals, the variable a is not', r.article === 'MOVES IN A STRAIGHT LINE · RADIUS a · a + b', r.article);
  out('capitals: card codes and chips keep Greek letters', r.code === 'δ-SHIFT' && r.chip === 'φ GATE', JSON.stringify([r.code, r.chip]));
  out('capitals: stage labels written by st.tag keep δ, u and φ; Δ stays Δ', r.tag === 'δ-SHIFT OF u BY φ' && r.upper === 'Δ STEP', JSON.stringify([r.tag, r.upper]));
  out('capitals: text that is not set in capitals is left alone', r.plain === 'phase δ stays as written in body text', r.plain);
  await page.evaluate(() => { document.getElementById('h2').textContent = 'ratio ψ over k'; });
  await settle(page);
  const later = await page.evaluate(() => document.getElementById('h2').innerText);
  out('capitals: text the page writes later is kept as well', later === 'RATIO ψ OVER k', later);
  out('capitals: the quality gate finds no lowercase Greek letter set in capitals', (await capitalGreek(page)).length === 0, JSON.stringify(await capitalGreek(page)));
  await page.addStyleTag({ content: '.keepcase { text-transform: uppercase !important; }' });
  const caught = await capitalGreek(page);
  out('capitals: the quality gate finds lowercase Greek letters set in capitals once the guard is overridden', caught.length >= 3 && caught.some((t) => t.includes('ψ')), JSON.stringify(caught));
}

/* ---------- the stage HUD: title below the buttons only where they would meet ---------- */
const hud = () => page.evaluate(() => {
  const tl = document.getElementById('tl'), tr = document.getElementById('tr'), st = document.getElementById('hud');
  const lines = [], range = document.createRange(), w = document.createTreeWalker(tl, NodeFilter.SHOW_TEXT);
  for (let t = w.nextNode(); t; t = w.nextNode()) { range.selectNodeContents(t); for (const r of range.getClientRects()) lines.push(r); }
  const buttons = [...tr.children].map((c) => c.getBoundingClientRect());
  const meet = buttons.some((a) => lines.some((b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1));
  const s = st.getBoundingClientRect();
  return { stack: st.classList.contains('hud-stack'), meet, top: getComputedStyle(tl).top, tlTop: tl.getBoundingClientRect().top - s.top, trBottom: tr.getBoundingClientRect().bottom - s.top,
    tlBottom: tl.getBoundingClientRect().bottom - s.top, height: s.height };
});
{
  const wide = await hud();
  out('HUD: on a wide stage the title stays at the top left, next to the buttons', !wide.stack && !wide.meet && wide.top === '14px', JSON.stringify(wide));
  for (const width of [390, 334]) {
    await page.setViewportSize({ width, height: 700 }); await settle(page); await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    const narrow = await hud();
    out(`HUD: in a ${width}px frame the title goes below the buttons, and nothing overlaps`, narrow.stack && !narrow.meet && narrow.tlTop >= narrow.trBottom && narrow.tlBottom < narrow.height * 0.6, JSON.stringify(narrow));
  }
  await page.setViewportSize({ width: 1000, height: 700 }); await settle(page); await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  const back = await hud();
  out('HUD: widening the frame again puts the title back at the top', !back.stack && back.top === '14px', JSON.stringify(back));
}
out('no page error, console error or failed request', T.errors.length === 0, T.errors.slice(0, 3).join(' | '));
await T.browser.close();
process.exit(0);
