#!/usr/bin/env node
// Browser regression suite for GOLDEN//CARRY (books/example-monograph/viz/golden-carry/), the worked example of
// skills/book-viz:
//   node books/example-monograph/viz/tests/golden-carry.test.mjs      (or: node tools/node/viz-test.mjs example-monograph)
// It first runs the quality gates every stage-first page must pass, then reads the page through the read-only probe
// window.GC_DEBUG and checks every claim against an independent implementation written here: Zeckendorf digits from a
// different greedy loop, powers of φ by multiplying pairs in ℤ[φ] (no Fibonacci identity), the carry rules of
// trureturing's carryPass on a sparse map of digits, the Beatty form of the deficit, and brute-force counts.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { session, stageFirstChecks, settle, cjkLeftovers } from '../../../../tools/node/viz-testkit.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const BOOK = 'example-monograph', ID = 'golden-carry';
const lock = JSON.parse(fs.readFileSync(path.join(ROOT, 'trureturing.lock.json'), 'utf8'));

/* ---------- independent implementation (BigInt, ℤ[φ] pairs) ---------- */
const fibs = [1n, 2n]; // F₂, F₃, … — the Zeckendorf weights
while (fibs.length < 40) fibs.push(fibs[fibs.length - 1] + fibs[fibs.length - 2]);
/** Zeckendorf digits, index i ↔ weight F_(i+2), by repeatedly removing the largest weight that fits. */
function zeckendorf(n) {
  let rest = BigInt(n); const set = new Set();
  while (rest > 0n) { let k = 0; while (k + 1 < fibs.length && fibs[k + 1] <= rest) k++; set.add(k); rest -= fibs[k]; }
  const top = set.size ? Math.max(...set) : -1;
  return Array.from({ length: top + 1 }, (_, i) => (set.has(i) ? 1 : 0));
}
/** (a + bφ)(c + dφ) with φ² = φ + 1. */
const mul = ([a, b], [c, d]) => [a * c + b * d, a * d + b * c + b * d];
const phiPow = [[1n, 0n]];
for (let k = 1; k < 48; k++) phiPow.push(mul(phiPow[k - 1], [0n, 1n]));
function betaPair(n) {
  let a = 0n, b = 0n;
  zeckendorf(n).forEach((x, i) => { if (x) { a += phiPow[i + 2][0]; b += phiPow[i + 2][1]; } });
  return [a, b];
}
const betaCache = new Map();
const beta = (n) => { if (!betaCache.has(n)) betaCache.set(n, betaPair(n)); return betaCache.get(n); };
/** c(v₁, v₂) as an exact pair; the second component must be 0. */
function deficit(v1, v2) { const [a1, b1] = beta(v1), [a2, b2] = beta(v2), [a3, b3] = beta(v1 + v2); return [a1 + a2 - a3, b1 + b2 - b3]; }
/** trureturing carryPass on a sparse digit map: returns the rule sequence, signed count and normal form. */
function carryRun(v1, v2) {
  const r = new Map();
  const add = (i, k) => { const x = (r.get(i) || 0) + k; if (x) r.set(i, x); else r.delete(i); };
  zeckendorf(v1).forEach((x, i) => x && add(i, 1));
  zeckendorf(v2).forEach((x, i) => x && add(i, 1));
  const rules = []; let count = 0;
  for (;;) {
    const twos = [...r.keys()].filter((i) => r.get(i) >= 2).sort((x, y) => x - y);
    if (twos.length) {
      const i = twos[0]; add(i, -2);
      if (i === 0) { add(1, 1); rules.push('R0'); count += 1; }
      else if (i === 1) { add(0, 1); add(2, 1); rules.push('R1'); count -= 1; }
      else { add(i - 2, 1); add(i + 1, 1); rules.push('R'); }
      continue;
    }
    const adj = [...r.keys()].filter((i) => r.get(i) === 1 && r.get(i + 1) === 1).sort((x, y) => x - y);
    if (!adj.length) break;
    const i = adj[0]; add(i, -1); add(i + 1, -1); add(i + 2, 1); rules.push('A');
  }
  const top = r.size ? Math.max(...r.keys()) : -1;
  return { rules, count, normal: Array.from({ length: top + 1 }, (_, i) => r.get(i) || 0) };
}
const PHI = (1 + Math.sqrt(5)) / 2, PSI = (1 - Math.sqrt(5)) / 2;
/** The Beatty form of the deficit (chapter 1, thm-beatty-deficit): s(v) = ⌊(v + 1)φ⌋ − 1. */
const s = (v) => Math.floor((v + 1) * PHI) - 1, beatty = (a, b) => s(a) + s(b) - s(a + b);
const phase = (v) => { const x = (v + 1) * PHI; return x - Math.floor(x); };
/** β′(v) as a sum of powers of ψ over the Zeckendorf digits. */
const contraction = (v) => zeckendorf(v).reduce((t, x, i) => t + x * PSI ** (i + 2), 0);
const eq = (x, y) => JSON.stringify(x) === JSON.stringify(y);
const near = (x, y, tol = 1e-9) => Math.abs(x - y) <= tol;

const T = await session();
const { check } = T;

/* ---------- the quality gates of every stage-first page ---------- */
await stageFirstChecks(T, BOOK, ID);

const page = await T.goto(BOOK, ID, '?lang=zh');
await page.evaluate(() => document.fonts && document.fonts.ready); await settle(page, 300);
const D = (fn, arg) => page.evaluate(fn, arg);
const state = async () => { await settle(page); return D(() => window.GC_DEBUG.state); };
const info = async () => { await settle(page); return D(() => window.GC_DEBUG.info()); };
const seek = async (t) => { await D((v) => window.GC_DEBUG.seek(v), t); return state(); };
const pick = async (id) => { await page.click(`[data-preset="${id}"]`); await settle(page, 60); };
const scene = async (id) => { await page.click(`#sceneChips [data-scene="${id}"]`); await settle(page, 60); };
const text = (sel) => page.textContent(sel);

/* ---------- opening view; the carries ---------- */
let st = await state();
check('opens on the card CANCEL: 6 + 6 with its three carries finished', st.preset === 'cancel' && st.scene === 'carry' && st.v1 === 6 && st.v2 === 6 && st.passes === 3 && st.pass === 3 && !st.playing, JSON.stringify(st));
check('page carries its id and the runtime language', (await D(() => document.body.dataset.vizId)) === ID && (await D(() => TRV.lang())) === 'zh');
let x = await info();
check('6 + 6: R₀, then an inner carry, then R₁; +1 and −1 cancel and c = 0', eq(x.passes.map((p) => p.rule), ['R0', 'R', 'R1']) && eq(x.partial, [0, 1, 1, 0]) && x.c === 0 && deficit(6, 6)[0] === 0n);
await pick('plus'); x = await info();
check('PLUS-ONE: c(1, 1) = +1 through one R₀ carry, on the page and in the independent computation', x.c === 1 && x.cPhi === 0 && eq(x.passes.map((p) => p.rule), ['R0']) && deficit(1, 1)[0] === 1n && deficit(1, 1)[1] === 0n);
check('PLUS-ONE: the readouts and the pill say +1', /\+1/.test(await text('#roC')) && /\+1/.test(await text('#pillC')) && (await text('#roR0')).trim() === '1' && (await text('#roR1')).trim() === '0');
await pick('minus'); x = await info();
check('MINUS-ONE: c(2, 2) = −1 through one R₁ carry', x.c === -1 && x.count === -1 && eq(x.passes.map((p) => p.rule), ['R1']) && deficit(2, 2)[0] === -1n);
await pick('long'); st = await state(); x = await info();
check('LONGEST: 986 + 986 takes 50 carries, only the first counts, c = −1', st.passes === 50 && x.c === -1 && x.passes[0].rule === 'R1' && x.passes.slice(1).every((p) => p.sign === 0) && carryRun(986, 986).rules.length === 50);
let longest = 0; for (let a = 0; a <= 987; a++) for (let b = a; b <= 987; b += 1 + (a % 3)) longest = Math.max(longest, carryRun(a, b).rules.length);
check('no sampled pair below 988 needs more than 50 carries', longest === 50, String(longest));
check('a card that plays starts its rail from the beginning when clicked', st.playing || st.t < st.max, JSON.stringify([st.playing, st.t]));

/* ---------- many pairs: digits, β, the carry run, the signed count, the Beatty form ---------- */
const pairs = [[0, 0], [0, 5], [1, 1], [2, 2], [6, 6], [17, 17], [88, 88], [609, 609], [986, 986], [987, 987], [987, 0], [500, 377]];
let seed = 7; const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed; };
for (let k = 0; k < 120; k++) pairs.push([rnd() % 988, rnd() % 988]);
let pairOK = true, pairBad = '';
for (const [v1, v2] of pairs) {
  await D(([a, b]) => window.GC_DEBUG.set(a, b), [v1, v2]);
  const q = await D(() => window.GC_DEBUG.info());
  const run = carryRun(v1, v2), [c, phi] = deficit(v1, v2);
  const ok = q.v1 === v1 && q.v2 === v2 && eq(q.z1, zeckendorf(v1)) && eq(q.z2, zeckendorf(v2)) && eq(q.z3, zeckendorf(v1 + v2))
    && eq(q.beta1, beta(v1).map(Number)) && eq(q.beta2, beta(v2).map(Number)) && eq(q.beta3, beta(v1 + v2).map(Number))
    && BigInt(q.c) === c && phi === 0n && q.cPhi === 0 && q.count === run.count && BigInt(run.count) === c && q.c === beatty(v1, v2)
    && eq(q.passes.map((p) => p.rule), run.rules) && eq(q.final, run.normal) && eq(run.normal, zeckendorf(v1 + v2)) && q.canonicalOk
    && near(q.contraction[0] + q.contraction[1] - q.contraction[2], q.c, 1e-9);
  if (!ok) { pairOK = false; pairBad = `(${v1}, ${v2}) ${JSON.stringify({ page: [q.c, q.count, q.passes.length], mine: [String(c), run.count, run.rules.length] })}`; break; }
}
check(`${pairs.length} pairs: digits, β in ℤ[φ], carry rules, normal form, signed count = c = Beatty form = reading on the contraction face`, pairOK, pairBad);
const real = (n) => zeckendorf(n).reduce((t, v, i) => t + v * PHI ** (i + 2), 0);
check('floating-point β agrees with the exact c to 1e−9 (v ≤ 200)', pairs.filter(([a, b]) => a <= 200 && b <= 200).every(([a, b]) => near(real(a) + real(b) - real(a + b), Number(deficit(a, b)[0]))));

/* ---------- the rail of the carries ---------- */
await D(() => window.GC_DEBUG.set(17, 17)); st = await state();
check('choosing a pair shows its carries finished: 17 + 17 has nine', st.v1 === 17 && st.passes === 9 && st.pass === 9 && st.max === 9);
st = await seek(0); check('the rail goes back to the digitwise sum', st.pass === 0 && /0/.test(await text('#tau')));
await page.click('body', { position: { x: 5, y: 5 } });
await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight'); st = await state();
check('→ steps one carry at a time', st.pass === 2, JSON.stringify(st.t));
await page.keyboard.press('ArrowLeft'); check('← steps back', (await state()).pass === 1);
await page.keyboard.press('End'); check('End jumps to the normal form', (await state()).pass === 9);
await page.keyboard.press('Home'); await page.keyboard.press('Space'); await page.waitForTimeout(700); st = await state();
check('Space plays the carries', st.playing && st.t > 0);
await page.keyboard.press('Space'); check('Space pauses', !(await state()).playing);
await page.click('#rew'); check('⏮ returns to the start', (await state()).t === 0);
await seek(9);
const row = await D(() => window.GC_DEBUG.point.row(5));
await page.mouse.click(row.x, row.y); st = await state();
check('clicking a row of the carries goes to that pass', st.pass === 5, JSON.stringify(st.t));
check('the HUD names the pass and the count so far', /第 5 步/.test(await text('#hudSub')));

/* ---------- the pair: number boxes, sliders, steppers ---------- */
await page.fill('#v1Num', '34'); await page.press('#v1Num', 'Enter'); await settle(page);
await page.fill('#v2Num', '21'); await page.press('#v2Num', 'Enter'); st = await state();
check('typing into both number boxes sets v₁ = 34 and v₂ = 21', st.v1 === 34 && st.v2 === 21 && (await D(() => document.getElementById('v1').value)) === '34' && (await D(() => document.getElementById('v2').value)) === '21');
await D(() => { const el = document.getElementById('v2'); el.value = '13'; el.dispatchEvent(new Event('input', { bubbles: true })); }); st = await state();
check('the slider sets v₂ and the number box follows', st.v2 === 13 && (await D(() => document.getElementById('v2Num').value)) === '13');
await page.click('#v1Inc'); await settle(page); await page.click('#v2Dec'); st = await state();
check('steppers move v₁ up and v₂ down by one', st.v1 === 35 && st.v2 === 12);
await page.click('#swap'); st = await state(); check('swap exchanges the pair', st.v1 === 12 && st.v2 === 35);
await page.click('#random'); st = await state();
check('random picks another pair in 0 … 987', st.v1 >= 0 && st.v1 <= 987 && st.v2 >= 0 && st.v2 <= 987 && !(st.v1 === 12 && st.v2 === 35));
await page.fill('#v1Num', '5000'); await page.press('#v1Num', 'Enter'); st = await state();
check('out-of-range input is clamped to 987, in the state and in the box', st.v1 === 987 && (await D(() => document.getElementById('v1Num').value)) === '987');
check('moving a control leaves the card: free play', st.preset === null && /自由探索/.test(await text('#presetNote')));

/* ---------- the deficit map ---------- */
await pick('map'); st = await state();
check('MAP: the scene switches to the map of 0 … 34 with the pair (17, 17)', st.scene === 'map' && st.N === 34 && st.v1 === 17 && st.v2 === 17);
for (const [t, N] of [[0, 8], [3, 34], [5, 89], [7, 233], [10, 987]]) {
  st = await seek(t);
  const grid = await D((n) => window.GC_DEBUG.grid(n), N), n = N + 1;
  let agree = grid.length === n * n && /^[012]+$/.test(grid), bad = '', pos = 0, neg = 0;
  for (let yy = 0; yy <= N && agree; yy++) for (let xx = 0; xx <= N; xx++) {
    const c = beatty(xx, yy), g = grid.charCodeAt(yy * n + xx) - 49;
    if (g !== c) { agree = false; bad = `(${xx}, ${yy}) page ${g} Beatty ${c}`; break; }
    if (c === 1) pos++; else if (c === -1) neg++;
  }
  check(`map 0 … ${N}: all ${n * n} cells lie in {−1, 0, 1} and agree with the Beatty form`, st.N === N && agree, bad);
  check(`map 0 … ${N}: the page counts ${pos} cells of +1 and ${neg} of −1, as counted here`, st.cells.pos === pos && st.cells.neg === neg && st.cells.odd === 0 && (await text('#hudSub')).includes(String(pos)), JSON.stringify(st.cells));
}
let exact = true; for (let yy = 0; yy <= 60 && exact; yy++) for (let xx = 0; xx <= 60; xx++) { const [c, phi] = deficit(xx, yy); if (phi !== 0n || Number(c) !== beatty(xx, yy)) { exact = false; break; } }
check('the Beatty form used above equals the exact ℤ[φ] deficit for all pairs up to 60', exact);
check('the map is symmetric (c(v₁, v₂) = c(v₂, v₁)) over 0 … 233', await D(() => { const g = window.GC_DEBUG.grid(233), n = 234; for (let yy = 0; yy < n; yy++) for (let xx = 0; xx < yy; xx++) if (g[yy * n + xx] !== g[xx * n + yy]) return false; return true; }));
await seek(3);
let pt = await D(() => window.GC_DEBUG.point.map(5, 8));
await page.mouse.click(pt.x, pt.y); st = await state();
check('clicking a cell of the map picks that pair', st.v1 === 5 && st.v2 === 8, JSON.stringify([st.v1, st.v2]));
await page.mouse.move(pt.x + 40, pt.y); await settle(page);
check('pointing at a cell reads out its c', /^c\(\d+, \d+\) = /.test((await text('#hudSub')).trim()), await text('#hudSub'));
pt = await D(() => window.GC_DEBUG.point.mini(21, 3));
await page.mouse.click(pt.x, pt.y); st = await state();
check('clicking the small map under the stage picks a pair too', st.v1 === 21 && st.v2 === 3, JSON.stringify([st.v1, st.v2]));
check('the row plot under the stage follows v₂', (await text('#pATitle')).includes('c(v₁, 3)'));
await pick('zoom'); await page.waitForTimeout(500); st = await state();
check('ZOOM-OUT plays the range outward', st.scene === 'map' && (st.playing || st.t > 0));
await page.keyboard.press('End'); st = await state();
check('at the end the map covers 0 … 987: 976144 cells, three colours', st.N === 987 && st.cells.odd === 0 && (await text('#hudSub')).includes('976144'));

/* ---------- the phase square ---------- */
await pick('phase'); st = await state();
const countShares = (n) => { let pos = 0, neg = 0, mism = 0; for (let b = 0; b < n; b++) for (let a = 0; a < n; a++) { const c = beatty(a, b), sum = phase(a) + phase(b), pred = sum < 1 / PHI ? 1 : sum >= PHI ? -1 : 0; if (c === 1) pos++; else if (c === -1) neg++; if (pred !== c) mism++; } return { pos, neg, mism }; };
let cs = countShares(8);
check('PHASE: 64 points with v₁, v₂ < 8, ten with c = +1 and six with c = −1', st.scene === 'phase' && st.n === 8 && cs.pos === 10 && cs.neg === 6 && near(st.shares.pos, 10 / 64) && near(st.shares.neg, 6 / 64));
const readings = await D(() => window.GC_DEBUG.readings(233));
check('the phases on the page are {(v + 1)φ} and the readings are β′(v), for v ≤ 233', readings.every(([bc, ph], v) => near(ph, phase(v), 1e-9) && near(bc, contraction(v), 1e-9)));
let critOK = true; for (const n of [8, 34, 100, 233]) { cs = countShares(n); st = await seek(n); if (cs.mism || !near(st.shares.pos, cs.pos / (n * n)) || !near(st.shares.neg, cs.neg / (n * n))) critOK = false; }
check('the phase criterion sorts every pair with v < 233 as its c says, and the shares on the page match the counts here', critOK);
st = await seek(10); check('n = 10: the shares 0.1700 and 0.0600 of the chapter', near(st.shares.pos, 0.17) && near(st.shares.neg, 0.06) && (await text('#hudSub')).includes('0.1700'));
st = await seek(100); check('n = 100: the shares 0.1885 and 0.0719 of the chapter', near(st.shares.pos, 0.1885) && near(st.shares.neg, 0.0719));
const P = 1 / (2 * PHI ** 2), N = 1 / (2 * PHI ** 4);
st = await seek(233); check('n = 233: both shares are within 0.002 of the areas 1/(2φ²) and 1/(2φ⁴)', Math.abs(st.shares.pos - P) < 0.002 && Math.abs(st.shares.neg - N) < 0.002, JSON.stringify(st.shares));
check('the HUD prints the two areas', (await text('#hudSub')).includes(P.toFixed(4)) && (await text('#hudSub')).includes(N.toFixed(4)));
await seek(21); pt = await D(() => window.GC_DEBUG.point.phase(4, 7));
await page.mouse.click(pt.x, pt.y); st = await state();
check('clicking a point of the phase square picks that pair', st.v1 === 4 && st.v2 === 7, JSON.stringify([st.v1, st.v2]));
await pick('fill'); await page.waitForTimeout(500); st = await state();
check('FILL plays n upward', st.scene === 'phase' && (st.playing || st.n > 2));
await page.keyboard.press('Space');

/* ---------- the window on the contraction face ---------- */
await pick('window'); st = await state(); x = await info();
const lo = -1 / PHI ** 2, hi = 1 / PHI;
check('WINDOW: the pair (2, 2), readings of v ≤ 34', st.scene === 'window' && st.m === 34 && x.v1 === 2 && x.v2 === 2);
check('the three readings of (2, 2) are β′(2), β′(2), β′(4) and combine to c = −1', near(x.contraction[0], contraction(2)) && near(x.contraction[2], contraction(4)) && near(2 * contraction(2) - contraction(4), -1));
let inside = true, least = 9, greatest = -9; for (let v = 0; v <= 233; v++) { const b = contraction(v); least = Math.min(least, b); greatest = Math.max(greatest, b); if (b < lo - 1e-12 || b > hi + 1e-12) inside = false; }
st = await seek(233);
check('every β′(v) with v ≤ 233 lies in [−1/φ², 1/φ], here and on the page', inside && near(st.least, least) && near(st.greatest, greatest) && (await text('#hudSub')).includes('✓'));
check('the window is exactly 1 long and leaves room for −1, 0, 1 only', near(hi - lo, 1) && Math.ceil(2 * lo - hi) === -1 && Math.floor(2 * hi - lo) === 1);
await pick('sweep'); await page.waitForTimeout(500); st = await state();
check('SWEEP plays v upward', st.scene === 'window' && (st.playing || st.m > 0));
await page.keyboard.press('Space');

/* ---------- scenes from the keyboard ---------- */
await page.click('body', { position: { x: 5, y: 5 } });
for (const [key, sc] of [['2', 'map'], ['3', 'phase'], ['4', 'window'], ['1', 'carry']]) { await page.keyboard.press(key); check(`key ${key} switches to the scene ${sc}`, (await state()).scene === sc); }
await D(() => window.GC_DEBUG.set(20, 35)); await page.keyboard.press('s'); st = await state();
check('S swaps the pair from the keyboard', st.v1 === 35 && st.v2 === 20);
await scene('map'); check('the scene chips switch scenes and show the evidence of that scene', (await state()).scene === 'map' && (await D(() => !document.querySelector('.lean[data-scenes="map"]').hidden && document.querySelector('.lean[data-scenes="carry"]').hidden)));

/* ---------- evidence: Lean links at the pinned commit; honest labels ---------- */
const links = await D(() => [...document.querySelectorAll('a[data-lean-gid]')].map((a) => [a.dataset.leanGid, a.href]));
check('every Lean link points at the pinned commit, file and line of trureturing.lock.json', links.length >= 7 && links.every(([gid, href]) => {
  const d = lock.declarations[gid]; return d && d.kind === 'theorem' && href === `https://github.com/${lock.repo}/blob/${lock.commit}/${gid.slice(0, gid.lastIndexOf('.'))}.lean#L${d.line}`;
}), JSON.stringify(links.find(([gid, href]) => { const d = lock.declarations[gid]; return !d || href !== `https://github.com/${lock.repo}/blob/${lock.commit}/${gid.slice(0, gid.lastIndexOf('.'))}.lean#L${d.line}`; }) || ''));
const cites = new Set(links.map(([g]) => g));
check('the page cites the theorems of its four scenes', ['D5/S1/Deficit/DeficitInteger.deficit_integer', 'D5/S1/Deficit/DeficitThreeValued.deficit_three_valued', 'D5/S1/Deficit/GoldenPhaseDeficit.golden_phase_deficit', 'D5/S1/Words/Expansions/BasePhiNegativeBridge.betaContraction_mem_window'].every((g) => cites.has(g)));
const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'books', BOOK, 'viz', 'visualizations.json'), 'utf8')).visualizations.find((v) => v.id === ID);
check('the registry lists exactly the theorems the page cites', eq([...cites].sort(), registry.lean.map((l) => l.gid).sort()), JSON.stringify([...cites].filter((g) => !registry.lean.some((l) => l.gid === g))));
check('green boxes are only the ones with a Lean link', await D(() => [...document.querySelectorAll('.lean:not(.num):not(.model):not(.argued):not(.open)')].every((b) => b.querySelector('a[data-lean-gid]'))));
await scene('phase');
check('the limit of the shares is labelled as a literature result, not as verified', await D(() => { const b = document.querySelector('.lean.argued[data-scenes="phase"]'); return !!b && !b.hidden && /文献结果，未在本书形式化/.test(b.textContent) && !b.querySelector('a[data-lean-gid]'); }));
await page.click('#infoBtn');
check('the drawer says the page is a numerical illustration, not a proof', /数值演示，不是证明/.test(await text('#drawer div.zh')) && /numerical illustration, not a proof/.test(await text('#drawer div.en')));
await page.keyboard.press('Escape');
check('Esc closes the drawer and focus returns to its button', (await D(() => document.getElementById('drawer').hidden)) && (await D(() => document.activeElement.id)) === 'infoBtn');

/* ---------- English; the hub ---------- */
await page.click('[data-lang-set="en"]'); await settle(page, 150);
check('English title', (await D(() => document.title)).startsWith('GOLDEN//CARRY · Golden carry'));
for (const sc of ['carry', 'map', 'phase', 'window']) { await scene(sc); const left = await cjkLeftovers(page); check(`English: no Chinese left in the scene ${sc} after free play`, left.length === 0, left.slice(0, 4).join(' | ')); }
await page.click('.crumb'); await page.waitForLoadState('load');
check('the crumb opens the hub, which keeps the language and lists this visualization with its cover', (await D(() => document.documentElement.dataset.lang)) === 'en'
  && (await D(() => document.querySelectorAll('.card[data-viz="golden-carry"]').length)) === 1 && (await D(() => !!document.querySelector('.card[data-viz="golden-carry"] img[src="golden-carry/thumb.jpg"]'))));
await page.click('.card[data-viz="golden-carry"] .enter'); await page.waitForLoadState('load');
check('the hub card opens this page', (await D(() => document.body.dataset.vizId)) === ID);
await D(() => localStorage.removeItem('tr-lang'));

check('no page error, console error or failed request (page-specific part)', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
await T.finish();
