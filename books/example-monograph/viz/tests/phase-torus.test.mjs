#!/usr/bin/env node
// Browser regression suite for example-monograph/viz/phase-torus (Playwright + Chromium):
//   node books/example-monograph/viz/tests/phase-torus.test.mjs        (or node tools/node/viz-test.mjs example-monograph)
// stageFirstChecks with { solid: true } adds the checks of a page that draws a lit solid with kit.solid. Then every
// claim of the page is recomputed here: the deficit by the Beatty form and by the phase criterion, the regions the
// page colours, the gluing (the two diagonal pieces meet only once the torus is closed), and picking a bead.
import { session, stageFirstChecks, settle, until } from '../../../../tools/node/viz-testkit.mjs';

const T = await session();
const { check } = T;
await stageFirstChecks(T, 'example-monograph', 'phase-torus', { solid: true });

const page = await T.goto('example-monograph', 'phase-torus', '?lang=zh');
await settle(page, 300);
const state = async () => { await settle(page); return page.evaluate(() => window.TORUS_DEBUG.state); };
const PHI = (1 + Math.sqrt(5)) / 2;
const frac = (x) => x - Math.floor(x);
// the deficit from Zeckendorf digits: β(v) in ℤ[φ] as a + bφ, c = β(v₁) + β(v₂) − β(v₁ + v₂) (an integer)
const F = [0, 1]; while (F.length < 40) F.push(F[F.length - 1] + F[F.length - 2]);   // F_0 = 0, F_1 = 1, F_2 = 1, F_3 = 2, …
/** β(v) = Σ φ^k over the Zeckendorf terms F_k of v (k ≥ 2), as [a, b] with a + bφ, using φ^k = F_{k−1} + F_k φ. */
function beta(v) {
  let a = 0, b = 0;
  for (let k = F.length - 1; k >= 2 && v > 0; k--) if (F[k] <= v) { v -= F[k]; a += F[k - 1]; b += F[k]; k--; }
  return [a, b];
}
const zdef = (v1, v2) => { const x = beta(v1), y = beta(v2), z = beta(v1 + v2); return { a: x[0] + y[0] - z[0], b: x[1] + y[1] - z[1] }; };

let s = await state();
check('page carries its id', (await page.evaluate(() => document.body.dataset.vizId)) === 'phase-torus');
check('opens on the TORUS card, glued, on WebGL', s.preset === 'torus' && Math.abs(s.glue - 2) < 1e-9 && s.mode === 'webgl', JSON.stringify(s));
const pairs = await page.evaluate(() => window.TORUS_DEBUG.pairs());
let bad = pairs.filter((q) => { const z = zdef(q.v1, q.v2); return z.b !== 0 || z.a !== q.c || Math.abs(q.p1 - frac((q.v1 + 1) * PHI)) > 1e-12; });
check('the 64 bead colours are the deficit computed from Zeckendorf digits in ℤ[φ]', pairs.length === 64 && bad.length === 0, JSON.stringify(bad.slice(0, 3)));
bad = pairs.filter((q) => (q.p1 + q.p2 < 1 / PHI ? 1 : q.p1 + q.p2 >= PHI ? -1 : 0) !== q.c);
check('each bead lies in the region of its deficit (phase criterion)', bad.length === 0);
const regions = await page.evaluate(() => { const out = []; for (let i = 0; i <= 40; i++) for (let j = 0; j <= 40; j++) out.push([i / 40, j / 40, window.TORUS_DEBUG.region(i / 40, j / 40)]); return out; });
check('the colours of the solid follow p₁ + p₂ against 1/φ and φ (1681 points)', regions.every(([a, b, r]) => r === (a + b < 1 / PHI ? 1 : a + b >= PHI ? -1 : 0)));
const area = (sign) => { let n = 0; const N = 2000; for (let i = 0; i < N; i++) for (let j = 0; j < N; j += 7) { const a = (i + 0.5) / N, b = (j + 0.5) / N; if ((a + b < 1 / PHI ? 1 : a + b >= PHI ? -1 : 0) === sign) n += 7; } return n / (N * N); };
const ro = await page.evaluate(() => [document.getElementById('roPlus').textContent, document.getElementById('roMinus').textContent].map(Number));
check('the areas read out agree with counting cells', Math.abs(ro[0] - area(1)) < 2e-3 && Math.abs(ro[1] - area(-1)) < 2e-3, `${ro} vs ${area(1).toFixed(4)}, ${area(-1).toFixed(4)}`);

// gluing: opposite edges become the same points exactly when glued, and the two pieces of the diagonal meet
const glue = async (g) => page.evaluate((x) => { const D = window.TORUS_DEBUG, d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  let tb = 0, lr = 0; for (let k = 0; k <= 20; k++) { tb = Math.max(tb, d(D.shape(k / 20, 0, x), D.shape(k / 20, 1, x))); lr = Math.max(lr, d(D.shape(0, k / 20, x), D.shape(1, k / 20, x))); }
  return { tb, lr, ends: d(D.shape(1 / 1.618033988749895, 0, x), D.shape(1 / 1.618033988749895, 1, x)) }; }, g);
const g0 = await glue(0), g1 = await glue(1), g2 = await glue(2);
check('flat: no edge is glued', g0.tb > 0.5 && g0.lr > 1);
check('tube: top and bottom are glued, left and right not yet', g1.tb < 1e-9 && g1.lr > 1, JSON.stringify(g1));
check('torus: both pairs of edges are glued and the two diagonal pieces meet', g2.tb < 1e-9 && g2.lr < 1e-9 && g2.ends < 1e-9, JSON.stringify(g2));
check('φ − 1 = 1/φ: the line p₁ + p₂ = φ is p₁ + p₂ ≡ 1/φ (mod 1)', Math.abs(frac(PHI) - 1 / PHI) < 1e-15);
await page.click('[data-preset="tube"]'); s = await state();
check('TUBE: glue 1', Math.abs(s.glue - 1) < 1e-9 && s.preset === 'tube');
await page.evaluate(() => { const el = document.getElementById('glue'); el.value = '0.4'; el.dispatchEvent(new Event('input', { bubbles: true })); }); s = await state();
check('the slider sets the glue and leaves the card', Math.abs(s.glue - 0.4) < 1e-9 && s.preset === null);

// picking a bead: click a visible bead, the current pair changes; a bead the torus hides is not picked
await page.click('[data-preset="pair"]'); s = await state();
check('PAIR: (2, 2), c = −1', s.pick.v1 === 2 && s.pick.v2 === 2 && s.pick.c === -1);
const beads = await page.evaluate(() => [...Array(64).keys()].filter((i) => i !== 18).map((i) => ({ i, ...window.TORUS_DEBUG.bead(i) })));
const vis = beads.find((b) => !b.hidden), hid = beads.find((b) => b.hidden);
if (vis) { await page.mouse.click(vis.x, vis.y); s = await state(); check('clicking a visible bead makes it the current pair', s.pick.v1 * 8 + s.pick.v2 === vis.i, `${JSON.stringify(s.pick)} vs ${vis.i}`); }
if (hid) {
  await page.click('[data-preset="pair"]'); await settle(page);
  const h2 = await page.evaluate((i) => ({ i, ...window.TORUS_DEBUG.bead(i) }), hid.i);
  if (h2.hidden) { await page.mouse.click(h2.x, h2.y); s = await state(); check('a bead behind the torus is not picked', s.pick.v1 * 8 + s.pick.v2 !== h2.i); }
}
await page.click('[data-preset="torus"]'); await settle(page);
await page.keyboard.press('Home'); await page.keyboard.press('Space');
check('Space plays the gluing', await until(page, () => window.TORUS_DEBUG.state.playing && window.TORUS_DEBUG.state.glue > 0.1));
await page.keyboard.press('Space'); check('Space pauses', !(await state()).playing);
check('no page error, console error or failed request (page-specific part)', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
await T.finish();
