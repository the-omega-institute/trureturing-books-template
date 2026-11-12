#!/usr/bin/env node
// Browser checks of the solid shots of the film engine (theme/film/engine.js solid()), run by
// tools/tests/test_film_solid.py on a fixture film whose page theme/film/build.py assembled.
//   node film_solid_harness.mjs <out dir> <t> <t> …   one JSON line: { hashes: {t: sha256}, checks: [{ name, ok, detail }] }
// The frames are hashed as RGBA pixels, in the order given (a second process with another order must agree: frames
// are a pure function of t, which is what parallel segments rely on). The anchors are checked against the camera
// basis of kit.stage3 computed here independently: the fixture scene is a unit sphere at the origin seen with
// yaw 0.4, pitch 0.3, in the rectangle x 560, y 140, 800 × 800, radius 0.3 (unit = 240 px).
// Without WebGL (FILM_CHROMIUM_ARGS=--disable-3d-apis) it prints { boot: "<the error>" } when the page refuses to boot.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [outDir, ...times] = process.argv.slice(2);
const lib = await import(pathToFileURL(resolve(new URL('.', import.meta.url).pathname, '../../theme/film/lib.js')).href);
const browser = await lib.launch();
try {
  let film;
  try {
    film = await lib.openFilm(browser, outDir);
  } catch (e) {
    console.log(JSON.stringify({ boot: String(e.message) }));
    process.exit(0);
  }
  const page = film.page;
  const hash = (t) => page.evaluate(async (t) => {
    window.renderAt(t);
    const c = document.getElementById('c'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    const b = await crypto.subtle.digest('SHA-256', d);
    return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
  }, t);
  const hashes = {};
  for (const t of times) hashes[t] = await hash(+t);
  const checks = [];
  const ok = (name, cond, detail = '') => checks.push({ name, ok: !!cond, detail: String(detail) });
  ok('the same t drawn again gives the same pixels', (await hash(+times[0])) === hashes[times[0]]);

  const yaw = 0.4, pitch = 0.3, X = 560, Y = 140, Wd = 800, unit = 0.3 * 800;
  const R = [Math.cos(yaw), -Math.sin(yaw), 0], U = [Math.sin(yaw) * Math.sin(pitch), Math.cos(yaw) * Math.sin(pitch), Math.cos(pitch)];
  const D = [-Math.sin(yaw) * Math.cos(pitch), -Math.cos(yaw) * Math.cos(pitch), Math.sin(pitch)];
  const sc = (v, k) => v.map((x) => x * k), add = (a, b) => a.map((x, i) => x + b[i]);
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const probe = (pts) => page.evaluate((pts) => { window.renderAt(1); return pts.map((p) => window.SHOT.anchor(p)); }, pts);
  const pts = { front: sc(D, 1.25), back: sc(D, -1.25), side: sc(R, 1.4), above: add(sc(U, 0.5), sc(D, -1.1)), centre: [0, 0, 0] };
  const got = await probe(Object.values(pts));
  const a = Object.fromEntries(Object.keys(pts).map((k, i) => [k, got[i]]));
  for (const [k, p] of Object.entries(pts)) {
    const x = X + Wd / 2 + unit * dot(p, R), y = Y + Wd / 2 - unit * dot(p, U);
    ok(`anchor ${k} projects to the frame`, Math.abs(a[k].x - x) < 0.5 && Math.abs(a[k].y - y) < 0.5, `${a[k].x},${a[k].y} vs ${x},${y}`);
  }
  ok('a point in front of the sphere is not hidden', a.front.hidden === false);
  ok('a point behind the sphere is hidden', a.back.hidden === true);
  ok('a point beside the sphere is not hidden', a.side.hidden === false);
  ok('a point behind the sphere near its top is hidden', a.above.hidden === true);
  ok('the centre of the sphere is hidden', a.centre.hidden === true);
  const px = await page.evaluate(() => { window.renderAt(1); const g = document.getElementById('c').getContext('2d');
    const f = (x, y) => Array.from(g.getImageData(x, y, 1, 1).data); return { ball: f(960, 540), off: f(300, 540) }; });
  ok('the solid is composited into the frame', px.ball[1] + px.ball[2] > px.off[1] + px.off[2] + 120, JSON.stringify(px));
  const errs = await page.evaluate(() => window.FILM_ERRORS || []);
  ok('no page errors', !errs.length, errs.join(' | '));
  console.log(JSON.stringify({ hashes, checks }));
  await film.close();
} finally {
  await browser.close();
}
