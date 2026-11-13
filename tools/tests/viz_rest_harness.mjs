#!/usr/bin/env node
// Browser regression of kit.solid inside a book (?embed=1), run by tools/tests/test_viz_runtime.py: the stage takes a
// WebGL context only once it is on screen, gives it back after a rest or when it leaves the screen, and takes it back
// on a touch. Whether the stage is on screen is told by an IntersectionObserver, whose deliveries ride on rendering
// updates; a busy machine can hold those back until after three.js is in, so the suites' settle() (kit.ready(), then
// flush()) must not run the first frame before that verdict, or a rest check reads a context that was never taken as
// one given back. The harness holds the verdict back on purpose (?hold=1, released by the harness: the order a busy
// machine produced) and reads the stage at fixed points of that order, not after a guessed delay.
// A fixture page under the viz/ of a visible book is served by the same viz server as the books (assets from
// theme/viz/). Without such a book, a single { skip } line.
import fs from 'node:fs';
import path from 'node:path';
import { session, settle } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';

const book = listBooks().find((b) => fs.existsSync(path.join(b.dir, 'viz')));
if (!book) { console.log(JSON.stringify({ skip: 'no visible book with a viz/ directory to serve the runtime from' })); process.exit(0); }
const T = await session({ viewport: { width: 740, height: 620 } });
const FIXTURE = `${T.origin}/site/${book.slug}/viz/__rest__/`;
// ?below=1 starts the stage out of view; ?rest=0 turns the rest off, so that only leaving the screen parks
const HTML = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="../assets/theme.css">
<script src="../assets/shell.js"></script><script src="../assets/kit.js"></script>
<style>body { margin: 0; } #st { position: relative; width: 720px; height: 480px; } #st canvas { position: absolute; inset: 0; width: 100%; height: 100%; }</style>
</head><body><div id="above"></div><div id="st" class="stage"><canvas id="cv"></canvas></div><div style="height: 2400px"></div>
<script>
  const kit = TRV.kit, q = new URLSearchParams(location.search);
  if (q.get('below') === '1') document.getElementById('above').style.height = '2000px';
  const sc = kit.solid(document.getElementById('st'), { canvas: document.getElementById('cv'), radius: 0.34, park: q.get('rest') === '0' ? 0 : undefined, onChange: () => paint() });
  const paint = kit.painter(() => {
    sc.begin();
    sc.surface('ellipsoid', (u, v) => [0.65 * Math.sin(v) * Math.cos(u), 0.65 * Math.sin(v) * Math.sin(u), 1.2 * Math.cos(v)], { u: [0, 2 * Math.PI], v: [0, Math.PI], nu: 48, nv: 24 });
    sc.end();
  });
  // a story that never finishes by itself, started by kit.autoplay once the stage is seen, as a card that plays does
  const clock = kit.clock({ max: 360, t: 45, rate: 0.000001, keys: false, onChange: () => paint() });
  kit.autoplay(clock, document.getElementById('st'));
  window.SC = sc; window.CLOCK = clock;
  // whether kit.ready() resolved while the harness still held the verdict back, read once the core is in
  kit.ready().then(() => { window.READY = { held: window.__io.held() }; });
  sc.ready.then(() => setTimeout(() => { window.CORE_IN = { ready: window.READY || null }; }, 0));
  paint();
</script></body></html>`;
await T.context.route(`${FIXTURE}**`, (r) => r.fulfill({ contentType: 'text/html', body: HTML }));
// With ?hold=1 every IntersectionObserver delivery waits in a queue until __io.release(), which hands them over in
// the order they came; after that they are delivered as the browser makes them.
await T.context.addInitScript(() => {
  const IO = window.IntersectionObserver, queue = [];
  let hold = /[?&]hold=1(&|$)/.test(location.search);
  window.__io = {
    held: () => hold,
    queued: () => queue.length,
    release() { hold = false; const due = queue.splice(0); due.forEach((f) => f()); return due.length; }
  };
  window.IntersectionObserver = function (cb, opts) {
    return new IO((entries, obs) => { if (hold) queue.push(() => cb(entries, obs)); else cb(entries, obs); }, opts);
  };
  window.IntersectionObserver.prototype = IO.prototype;
});

const { check } = T, page = T.page;
const wait = (fn, arg) => page.waitForFunction(fn, arg, { timeout: 30000, polling: 50 }).then(() => true, () => false);
const state = () => page.evaluate(() => {
  const cv = document.getElementById('cv');
  return { contexts: SC.contexts, parked: SC.parked(), gl: !!SC.el.querySelector('canvas.solid-gl'), still: cv.style.visibility,
    playing: CLOCK.playing, held: __io.held(), queued: __io.queued() };
});
/** Open the fixture with the verdict held back, start settle() and bring it to the point where three.js is in.
    Returns the pending settle() and whether kit.ready() had already resolved by then. */
async function openHeld(query) {
  await page.goto(FIXTURE + query);
  await page.evaluate(() => document.fonts && document.fonts.ready);
  let settled = false;
  const s = settle(page).then(() => { settled = true; });
  const coreIn = await wait(() => window.CORE_IN);
  const core = coreIn ? await page.evaluate(() => window.CORE_IN) : null;
  return { s, core, coreIn, settled: () => settled };
}

/* 1. the stage is on screen, its verdict arrives after three.js (the order of the failed rest check) */
{
  const { s, core, coreIn } = await openHeld('?embed=1&hold=1');
  check('three.js comes in while the visibility verdict is held back', coreIn && (await page.evaluate(() => __io.held() && __io.queued() > 0)));
  check('kit.ready() waits for the first visibility verdict of a solid inside a book', coreIn && core.ready === null, JSON.stringify(core));
  // read the stage where settle() leaves it: at once if it did not wait for the verdict, else after the verdict
  let atSettle;
  if (core && core.ready) { await s; atSettle = await state(); await page.evaluate(() => __io.release()); }
  else { await page.evaluate(() => __io.release()); await s; atSettle = await state(); }
  check('after settle() the stage on screen holds a WebGL context and covers its still',
    atSettle.contexts === 1 && !atSettle.parked && atSettle.gl && atSettle.still === 'hidden', JSON.stringify(atSettle));
  check('the story starts once the stage is seen', atSettle.playing, JSON.stringify(atSettle));
  await page.evaluate(() => { TRV.kit.pause(); TRV.kit.flush(); });
  const rested = await wait(() => SC.parked());
  const r = await state();
  const ink = await page.evaluate(() => {
    const c = document.getElementById('cv'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n / (d.length / 4);
  });
  check('after a pause the context taken on screen is given back and the frame stays as a picture',
    rested && r.contexts === 1 && r.parked && !r.gl && r.still === 'visible' && !r.playing && ink > 0.05, `${JSON.stringify(r)}, still inked ${(ink * 100).toFixed(1)}%`);
  const box = await page.evaluate(() => { const b = SC.el.getBoundingClientRect(); return [b.left + 8, b.top + b.height - 8]; });
  await page.mouse.move(box[0], box[1]); await page.mouse.down(); await page.mouse.up();
  await settle(page);
  const t = await state();
  // contexts counts every context taken: the touch's own, whether or not a later rest has given it back again
  check('a touch takes the context back', t.contexts === 2, JSON.stringify(t));
}

/* 2. the stage starts out of view: the verdict lets kit.ready() resolve without a context; on screen it takes one,
      and leaving the screen gives it back (rest off, so only visibility parks) */
{
  const { s, core, coreIn } = await openHeld('?embed=1&hold=1&below=1&rest=0');
  check('out of view: kit.ready() waits for the first visibility verdict', coreIn && core.ready === null, JSON.stringify(core));
  if (core && core.ready) { await s; await page.evaluate(() => __io.release()); } else { await page.evaluate(() => __io.release()); await s; }
  const off = await state();
  check('out of view: settle() resolves and no WebGL context is taken', off.contexts === 0 && off.parked && !off.gl, JSON.stringify(off));
  await page.evaluate(() => { document.getElementById('above').style.height = '0px'; });
  const taken = await wait(() => !SC.parked());
  await settle(page);
  const on = await state();
  check('scrolled into view: the stage takes a context', taken && on.contexts === 1 && !on.parked && on.gl, JSON.stringify(on));
  await page.evaluate(() => { document.getElementById('above').style.height = '2000px'; });
  const gone = await wait(() => SC.parked());
  const away = await state();
  check('scrolled out of view: the context is given back', gone && away.contexts === 1 && away.parked && !away.gl, JSON.stringify(away));
}

check('no page error, console error or failed request', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
await T.finish();
