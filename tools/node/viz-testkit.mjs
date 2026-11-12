// Helpers for the browser regression suites books/<slug>/viz/tests/<id>.test.mjs (Playwright + Chromium).
//
//   import { session } from '../../../../tools/node/viz-testkit.mjs';
//   const T = await session();                       // server + browser + page (zh-CN, 1440×900)
//   await T.goto('example-monograph', 'golden-carry', '?lang=zh');
//   T.check('c(1, 1) = 1', value === 1, `got ${value}`);
//   await stageFirstChecks(T, 'my-book', 'my-viz');  // the quality gates every stage-first page must pass (see below)
//   await T.finish();                                // prints the tally and exits non-zero on any failure
//
// The suite reuses the server started by tools/node/viz-test.mjs (env VIZ_ORIGIN) or starts its own, so a suite also
// runs alone:  node books/<slug>/viz/tests/<id>.test.mjs.  Chromium honours PW_CHROMIUM_PATH. Google Fonts requests are
// answered with the local @fontsource files, so pages render with their real fonts offline.
import { FORMAL_KINDS, chromiumOptions, leanUrl, loadChromium, localFontsCss, readLock, readRegistry, resolveBook } from './viz-common.mjs';
import { startServer, vizUrl } from './viz-server.mjs';

/** Route Google Fonts to the local @fontsource copies served by the viz server at `origin`. */
export async function routeLocalFonts(context, origin) {
  const css = localFontsCss(`${origin}/__fonts/`);
  await context.route(/^https:\/\/fonts\.googleapis\.com\//, (route) => route.fulfill({ status: 200, contentType: 'text/css; charset=utf-8', body: css }));
  await context.route(/^https:\/\/fonts\.gstatic\.com\//, (route) => route.fulfill({ status: 204, body: '' }));
}

/** Visible text nodes containing CJK characters (language-switch leftovers). */
export async function cjkLeftovers(page) {
  return page.evaluate(() => {
    const bad = []; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) {
      const t = n.textContent.trim(); if (!/[　-〿㐀-鿿＀-￯]/.test(t)) continue;
      const el = n.parentElement; if (!el || el.closest('[hidden]') || el.closest('.langs')) continue;
      let hidden = false; for (let a = el; a; a = a.parentElement) { const s = getComputedStyle(a); if (s.opacity === '0' || s.visibility === 'hidden') { hidden = true; break; } }
      if (hidden || getComputedStyle(el).display === 'none' || (el.offsetParent === null && getComputedStyle(el).position !== 'fixed')) continue;
      bad.push(t.slice(0, 40));
    }
    for (const el of document.querySelectorAll('[aria-label]')) if (/[㐀-鿿]/.test(el.getAttribute('aria-label')) && !el.closest('.langs') && el.offsetParent !== null) bad.push('aria-label: ' + el.getAttribute('aria-label').slice(0, 40));
    if (/[㐀-鿿]/.test(document.title)) bad.push('title: ' + document.title);
    return bad;
  });
}

/** Horizontal overflow of the document in CSS pixels (0 = no sideways scrolling). */
export const overflowX = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/** Bring the page's DOM and canvases up to date now (kit.flush), then wait `ms`. Headless Chromium may render only a
    few frames per second, so a suite should settle the page rather than hope that a frame has passed. */
export async function settle(page, ms = 0) {
  if (ms) await page.waitForTimeout(ms);
  await page.evaluate(() => { if (window.TRV && window.TRV.kit && window.TRV.kit.flush) window.TRV.kit.flush(); });
}

/** Wait until `fn`, evaluated in the page with `arg`, returns something truthy: resolves true as soon as it does and
    false when `timeout` ms pass first, so the result can be the check itself. Use it for whatever moves by itself on
    animation frames, playback above all: settle() finishes transitions but does not advance a clock, and a busy
    runner delivers frames late, so "press Space, wait 700 ms, read t" fails there although the page is right.
      check('Space plays', await until(page, () => window.MY_DEBUG.state.t > 0)); */
export const until = (page, fn, arg, timeout = 30000) => page.waitForFunction(fn, arg, { timeout }).then(() => true, () => false);

/** The fraction of the viewport covered by the visible part of an element (0 when it is absent or off-screen). */
export const viewportShare = (page, selector) => page.evaluate((sel) => {
  const el = document.querySelector(sel); if (!el) return 0;
  const r = el.getBoundingClientRect();
  const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)), h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
  return (w * h) / (innerWidth * innerHeight);
}, selector);

/** The fraction of a 2D canvas that is drawn on (sampled pixels with non-zero alpha): 0 for a blank canvas. */
export const inkShare = (page, selector) => page.evaluate((sel) => {
  const cv = document.querySelector(sel); if (!cv || !cv.width || !cv.height) return 0;
  const data = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let drawn = 0, total = 0;
  for (let i = 3; i < data.length; i += 4 * 5) { total++; if (data[i] > 8) drawn++; }
  return total ? drawn / total : 0;
}, selector);

/** Visible stage labels whose boxes overlap by more than `share` of the smaller box: [[textA, textB], …]. */
export const labelOverlaps = (page, selector = '.stage .tag', share = 0.5) => page.evaluate(([sel, tol]) => {
  const boxes = [...document.querySelectorAll(sel)].filter((el) => !el.hidden && el.offsetParent !== null && el.textContent.trim())
    .map((el) => ({ r: el.getBoundingClientRect(), t: el.textContent.trim() })).filter((b) => b.r.width > 0 && b.r.height > 0);
  const bad = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].r, b = boxes[j].r;
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (w > 0 && h > 0 && (w * h) / Math.min(a.width * a.height, b.width * b.height) > tol) bad.push([boxes[i].t, boxes[j].t]);
  }
  return bad;
}, [selector, share]);

/**
 * Open a browser session. Options: viewport, locale, reducedMotion ('reduce' | 'no-preference').
 * Returns { page, context, browser, origin, errors, check, goto, url, newPage, finish }.
 */
/** VIZ_SLOW_FRAMES=<ms> delivers animation frames that far apart, as a busy CI runner does. A suite that waits a fixed
    time for a transition or for playback passes on a fast machine and fails there; run it once with 1000 (a frame a
    second, longer than any fixed wait a suite is likely to hold) before trusting it. */
async function slowFrames(context) {
  const ms = Number(process.env.VIZ_SLOW_FRAMES) || 0;
  if (!ms) return;
  await context.addInitScript((gap) => {
    const raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (cb) => setTimeout(() => raf(cb), gap);
    window.cancelAnimationFrame = (id) => clearTimeout(id);
  }, ms);
}

export async function session(opts = {}) {
  let origin = process.env.VIZ_ORIGIN, server = null;
  if (!origin) ({ server, origin } = await startServer(0));
  const chromium = await loadChromium();
  const browser = await chromium.launch(chromiumOptions());
  const context = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 900 }, locale: opts.locale || 'zh-CN',
    reducedMotion: opts.reducedMotion || 'no-preference', deviceScaleFactor: opts.deviceScaleFactor || 1
  });
  await routeLocalFonts(context, origin);
  await slowFrames(context);
  const results = [], errors = [];
  const watch = (page) => {
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });
    // net::ERR_ABORTED = cancelled by a navigation (e.g. late font requests); missing files surface as HTTP 404 below
    page.on('requestfailed', (r) => {
      const why = r.failure() ? r.failure().errorText : '';
      if (!/^https:\/\/fonts\./.test(r.url()) && !/ERR_ABORTED/.test(why)) errors.push(`requestfailed: ${r.url()} ${why}`);
    });
    page.on('response', (r) => { if (r.status() >= 400 && r.url().startsWith(origin)) errors.push(`HTTP ${r.status()}: ${r.url()}`); });
    return page;
  };
  const page = watch(await context.newPage());
  const check = (name, ok, detail = '') => {
    results.push({ name, ok: !!ok, detail });
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail && !ok ? '  — ' + detail : ''}`);
    return !!ok;
  };
  const url = (slug, id, query = '') => vizUrl(origin, slug, id, query);
  const goto = async (slug, id, query = '', p = page) => { await p.goto(url(slug, id, query), { waitUntil: 'load' }); return p; };
  const newPage = async () => watch(await context.newPage());
  /** A watched page in its own context (another viewport, locale or motion preference), already at the visualization. */
  const open = async (slug, id, query = '', o = {}) => {
    const ctx = await browser.newContext({
      viewport: o.viewport || { width: 1440, height: 900 }, locale: o.locale || 'zh-CN',
      reducedMotion: o.reducedMotion || 'no-preference', deviceScaleFactor: 1
    });
    await routeLocalFonts(ctx, origin);
    await slowFrames(ctx);
    const p = watch(await ctx.newPage());
    await p.goto(url(slug, id, query), { waitUntil: 'load' });
    await p.evaluate(() => document.fonts && document.fonts.ready);
    return p;
  };
  async function finish() {
    await browser.close();
    if (server) server.close();
    const failed = results.filter((r) => !r.ok).length;
    console.log(`\n${results.length - failed}/${results.length} passed`);
    process.exit(failed || !results.length ? 1 : 0);
  }
  return { page, context, browser, origin, errors, results, check, goto, url, newPage, open, finish };
}

/**
 * Honest labels (skills/book-viz, "如实标注"), checked on the page as served. `page` is open on the visualization.
 *   every Lean link names a theorem of trureturing.lock.json and points at its pinned commit, file and line;
 *   the registry entry lists exactly the theorems the page cites;
 *   green boxes (.lean without .num / .model / .argued / .open) are exactly the boxes that cite a Lean theorem;
 *   the theory drawer says in both languages that the page is not a proof.
 */
export async function evidenceChecks(T, slug, id, page) {
  const { check } = T, lock = readLock();
  const entry = (readRegistry(resolveBook(slug)).visualizations || []).find((v) => v.id === id) || {};
  const links = await page.$$eval('a[data-lean-gid]', (as) => as.map((a) => [a.dataset.leanGid, a.href]));
  const bad = links.find(([gid, href]) => { const d = lock && (lock.declarations || {})[gid]; return !d || !FORMAL_KINDS.includes(d.kind) || href !== leanUrl(lock, gid); });
  check('evidence: every Lean link names a frozen theorem and points at its pinned commit, file and line', !bad, bad ? bad.join(' → ') : '');
  const cited = [...new Set(links.map(([g]) => g))].sort(), listed = (entry.lean || []).map((l) => l.gid).sort();
  const diff = [...cited.filter((g) => !listed.includes(g)).map((g) => `page only: ${g}`), ...listed.filter((g) => !cited.includes(g)).map((g) => `registry only: ${g}`)];
  check('evidence: the registry lists exactly the theorems the page cites', diff.length === 0, diff.slice(0, 3).join(' | '));
  const boxes = await page.$$eval('.lean', (els) => els.map((b) => ({ green: !/(^|\s)(num|model|argued|open)(\s|$)/.test(b.className), link: !!b.querySelector('a[data-lean-gid]'), text: b.textContent.trim().slice(0, 48) })));
  const wrong = boxes.find((b) => b.green !== b.link);
  check('evidence: green boxes are exactly the boxes that cite a Lean theorem', !wrong, wrong ? `${wrong.green ? 'green without a Lean link' : 'Lean link in a box of another colour'}: ${wrong.text}` : '');
  const drawer = await page.$eval('#drawer', (d) => d.textContent).catch(() => null);
  if (drawer != null) check('evidence: the drawer says in both languages that the page is not a proof', /不是证明/.test(drawer) && /not a proof/.test(drawer));
}

const RAIL_RANGE = 'footer.rail .clock input[type=range]';
/** Frame widths of the whole lab inside a chapter: phones (a 390px page leaves the frame 334px), and both sides of
    the 600px breakpoint of theme.css. */
const RAIL_WIDTHS = [320, 334, 360, 600, 601];

/** The clock rail as laid out now: sideways overflow of the document and of the body (in a book's frame the body is
    the scroller, so the document alone reports 0 for a rail that sticks out), the slider, and what is wrong with the
    rendered controls. null when the page has no rail. */
const railState = (page) => page.evaluate((sel) => {
  const rail = document.querySelector('footer.rail'); if (!rail) return null;
  const root = document.documentElement, body = document.body, vw = root.clientWidth, range = document.querySelector(sel);
  const bad = [];
  for (const el of rail.querySelectorAll('.transport button, .clock .tau, .clock input')) {
    if (!el.getClientRects().length) continue;   // not rendered (a cited figure hides the speed chips)
    const r = el.getBoundingClientRect(), what = el.id || el.dataset.speed || el.className;
    if (r.width < 1 || r.height < 1 || r.left < -0.5 || r.right > vw + 0.5) bad.push(`${what}: ${r.left.toFixed(0)} … ${r.right.toFixed(0)} × ${r.height.toFixed(0)} of ${vw}`);
    if (!el.matches('.tau') && !(el.getAttribute('aria-label') || el.textContent).trim()) bad.push(`${what}: no name`);
  }
  if (!range) bad.push('no slider');
  const tau = rail.querySelector('.clock .tau');
  const num = (s, empty) => (s === '' ? empty : parseFloat(s));   // an absent min is the default 0
  return {
    overflow: Math.max(root.scrollWidth - root.clientWidth, body.scrollWidth - body.clientWidth), bad,
    width: range ? range.getBoundingClientRect().width : 0, value: range ? parseFloat(range.value) : NaN, max: range ? parseFloat(range.max) : NaN,
    min: range ? num(range.min, 0) : NaN, disabled: !!range && range.matches(':disabled'),
    focused: !!range && document.activeElement === range, readout: tau ? tau.textContent.trim() : null
  };
}, RAIL_RANGE);

/** A range input reports its value as a decimal string, and the browser writes the values it sets itself (End, a
    drag to the edge) with RANGE_DIGITS significant digits: End on a clock whose max is 2π = 6.283185307179586 reads
    6.28318530717959. Two readings are the same number when they agree to that precision (one unit in the last
    serialized digit; the rounding itself moves a value by at most half of it). A clock that stops a keyboard step or
    a pixel short of its end is many orders of magnitude outside this. */
const RANGE_DIGITS = 15;
const sameNumber = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b)) * 10 ** (1 - RANGE_DIGITS);
/** The slider runs from 0 over a finite positive range and its value lies in it. */
const railDomain = (s) => s.min === 0 && Number.isFinite(s.max) && s.max > 0 && Number.isFinite(s.value) && s.value >= 0 && (s.value <= s.max || sameNumber(s.value, s.max));

/** A page may open on a card that has nothing to run (an empty program) and disable its clock until there is
    something. Do what a reader does then: pick the experiment cards in turn (the card itself where it is rendered,
    else the ▶ of the tour bar) until one enables the slider. Returns that card, or null when none does. */
async function enableRail(page, wait) {
  const disabled = async () => { await settle(page, wait); const s = await railState(page); return !s || s.disabled; };
  const usable = (sel) => page.evaluate((s) => { const el = document.querySelector(s); return !!el && !el.disabled && el.getClientRects().length > 0; }, sel);
  const press = (sel) => page.click(sel, { timeout: 5000 }).then(() => true, () => false);
  const pressed = () => page.evaluate(() => { const b = document.querySelector('[data-preset][aria-pressed="true"]'); return b ? b.dataset.preset : null; });
  const cards = await page.$$eval('[data-preset]', (els) => els.map((e) => e.dataset.preset));
  for (const c of cards) {
    const sel = `[data-preset="${c}"]`;
    if (!(await usable(sel)) || !(await press(sel))) continue;
    if (!(await disabled())) return c;
  }
  const next = '.tour [data-tour="next"]';
  for (let i = 0; i < cards.length; i++) {
    if (!(await usable(next)) || !(await press(next))) break;
    if (!(await disabled())) return (await pressed()) || 'tour';
  }
  return null;
}

/** The rail of the whole lab in narrow frames of a book, in one language (see stageFirstChecks, "rail"). */
async function railChecks(T, slug, id, lang, wait = 120) {
  const { check } = T;
  const page = await T.open(slug, id, `?embed=1&lang=${lang}`, { viewport: { width: 334, height: 620 }, locale: lang === 'zh' ? 'zh-CN' : 'en-US' });
  await settle(page, 400);
  if (!(await railState(page))) { await page.context().close(); return; }
  const layout = async (state) => {
    for (const w of RAIL_WIDTHS) {
      await page.setViewportSize({ width: w, height: 620 }); await settle(page, 60);
      const g = await railState(page), tag = `rail (${lang}, ${w}px frame${state})`;
      check(`${tag}: neither the document nor the body scrolls sideways`, g.overflow <= 0, `${g.overflow}px`);
      check(`${tag}: the transport, the readout and the slider are inside the frame and named`, g.bad.length === 0, g.bad.slice(0, 4).join(' | '));
    }
    await page.setViewportSize({ width: 334, height: 620 }); await settle(page, 60);
  };
  await layout('');   // as the page opens, whatever its clock has to run

  // use it as a reader does, in the frame of a 390px page: press at a quarter, drag to 70%, then the keyboard
  const tag = `rail (${lang}, 334px frame)`;
  const unusable = async (why) => {   // say so instead of waiting for a control that never becomes usable
    check(`${tag}: dragging the slider moves the clock`, false, why);
    check(`${tag}: Home, → and End move the clock and the readout`, false, why);
    await page.context().close();
  };
  if ((await railState(page)).disabled) {
    // nothing to run yet: a reader picks an experiment, and the rail must work then (and still fit)
    const card = await enableRail(page, wait);
    check(`${tag}: a slider that starts disabled is enabled by an experiment card`, !!card, card ? `card ${card}` : 'no experiment card enables the slider');
    if (!card) return unusable('the slider stays disabled');
    await layout(`, card ${card}`);
  }
  const at = await page.evaluate((sel) => {
    const el = document.querySelector(sel); if (!el) return null;
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect(), y = r.top + r.height / 2, x = (f) => r.left + r.width * f;
    return { x25: x(0.25), x70: x(0.7), y, width: r.width, hit: [0.25, 0.7].every((f) => document.elementFromPoint(x(f), y) === el) };
  }, RAIL_RANGE);
  check(`${tag}: the slider can be pressed where it is drawn`, !!at && at.hit, JSON.stringify(at));
  if (!at || !at.hit) return unusable('the slider cannot be pressed');
  const start = await railState(page);
  check(`${tag}: the slider runs from 0 over a finite positive range`, railDomain(start), JSON.stringify({ min: start.min, max: start.max, value: start.value }));
  await page.mouse.move(at.x25, at.y); await page.mouse.down(); await settle(page);
  const a = await railState(page);
  await page.mouse.move(at.x70, at.y, { steps: 6 }); await page.mouse.up(); await settle(page);
  const b = await railState(page);
  const near = (s, f) => railDomain(s) && Math.abs(s.value / s.max - f) < 0.08;
  check(`${tag}: dragging the slider moves the clock`, near(a, 0.25) && near(b, 0.7), `${a.value} → ${b.value} of ${b.max}`);
  await page.keyboard.press('Home'); await settle(page); const home = await railState(page);
  await page.keyboard.press('ArrowRight'); await settle(page); const right = await railState(page);
  await page.keyboard.press('End'); await settle(page); const end = await railState(page);
  // the end is compared at the precision the browser serializes it with (sameNumber); the start is exactly 0
  check(`${tag}: Home, → and End move the clock and the readout`,
    b.focused && [home, right, end].every(railDomain) && home.value === 0 && right.value > 0 && right.value < end.value
      && !sameNumber(right.value, end.value) && sameNumber(end.value, end.max) && home.readout !== end.readout,
    JSON.stringify({ focused: b.focused, home: [home.value, home.readout], right: right.value, end: [end.value, end.readout], max: end.max }));
  await page.context().close();
}

/**
 * The checks every stage-first page must pass, whatever it shows (skills/book-viz, "质量门"). They cannot tell a good
 * picture from a bad one, but they catch the regressions that make a page unreadable inside a book:
 *   desktop   the stage holds at least `minShare` of the viewport; every experiment card applies and explains itself;
 *             the theory drawer opens and closes; no stage labels sit on top of each other
 *   evidence  honest labels: see evidenceChecks above
 *   English   no Chinese left on screen after going through every card
 *   embed     (740 × 620, ?embed=1) the page chrome is gone, the stage starts at the top and fills most of the first
 *             screen, the tour bar is on that first screen, nothing scrolls sideways
 *   rail      (?embed=1 in frames 320 … 601 wide, the whole lab inside a chapter on a phone, in both languages)
 *             neither the document nor the body scrolls sideways; every transport control, the readout and the
 *             slider are rendered (not collapsed), inside the frame and named; the slider can be pressed, runs from 0
 *             over a finite positive range, follows a pointer drag and answers Home / → / End (the end compared at
 *             the precision a range input serializes numbers with), and the readout follows. A page that opens
 *             with nothing to run and its slider disabled is laid out as it opens, then an experiment card is
 *             picked as a reader would and the same checks run on the enabled rail; no card enabling it is a failure
 *   figure    (740 × 500, ?embed=1&preset=<card>, what a chapter shows when it cites one card) the page opens on
 *             that card; the stage, the one-sentence note and ◀ ▶ fit the frame and nothing scrolls inside it;
 *             ?shot=1 (the still that PDF/EPUB print) fills the frame on the same card, labels kept, in one language
 *   phone     (390 × 844) nothing scrolls sideways and the stage comes before the control deck
 *   cover     (?thumb=1) [data-thumb] fills 1280 × 720, window.TRV_THUMB runs, and the cover canvas is not blank
 *   motion    under prefers-reduced-motion the page loads and a card still applies
 * and no page error, console error or failed request anywhere.
 * opts: stage ('.stage'), cover (selector of the canvas the cover draws on; default '[data-thumb] canvas'),
 *       minShare (0.28), minEmbedShare (0.4), cards (true), tour (true), labels (true), evidence (true),
 *       rail (true; a page without footer.rail is not checked), settle (ms to wait after a click).
 */
export async function stageFirstChecks(T, slug, id, opts = {}) {
  const o = { stage: '.stage', cover: '[data-thumb] canvas', minShare: 0.28, minEmbedShare: 0.4, cards: true, tour: true, labels: true, evidence: true, rail: true, settle: 120, ...opts };
  const { check } = T;
  const cardIds = (page) => page.$$eval('[data-preset]', (els) => els.map((e) => e.dataset.preset));
  const runCards = async (page, tag) => {
    for (const c of await cardIds(page)) {
      await page.click(`[data-preset="${c}"]`); await settle(page, o.settle);
      const state = await page.evaluate((cid) => {
        const b = document.querySelector(`[data-preset="${cid}"]`), note = document.querySelector('#presetNote, .presets + .note');
        return { pressed: b.getAttribute('aria-pressed'), note: note ? note.textContent.trim().length : -1 };
      }, c);
      check(`${tag}: card ${c} applies and explains itself`, state.pressed === 'true' && state.note !== 0, JSON.stringify(state));
    }
  };

  // desktop
  const page = await T.goto(slug, id, '?lang=zh');
  await page.evaluate(() => document.fonts && document.fonts.ready); await settle(page, 400);
  const share = await viewportShare(page, o.stage);
  check(`desktop: the stage holds ≥ ${Math.round(o.minShare * 100)}% of the viewport`, share >= o.minShare, `${(share * 100).toFixed(1)}%`);
  check('desktop: no sideways scrolling', (await overflowX(page)) <= 0);
  if (o.cards) {
    const n = (await cardIds(page)).length;
    check('desktop: at least four experiment cards', n >= 4, `${n}`);
    await runCards(page, 'desktop');
  }
  if (o.labels) { const bad = await labelOverlaps(page, `${o.stage} .tag`); check('desktop: stage labels do not sit on top of each other', bad.length === 0, JSON.stringify(bad.slice(0, 4))); }
  if (await page.$('#infoBtn')) {
    await page.click('#infoBtn');
    check('desktop: the theory drawer opens', await page.evaluate(() => !document.getElementById('drawer').hidden));
    const pinned = await page.$$eval('a[data-lean-gid]', (as) => as.map((a) => a.href));
    check('desktop: every Lean theorem cited on the page links to the pinned commit', pinned.every((h) => /\/blob\/[0-9a-f]{40}\//.test(h)), pinned.find((h) => !/\/blob\/[0-9a-f]{40}\//.test(h)) || `${pinned.length} links`);
    await page.keyboard.press('Escape');
    check('desktop: Escape closes the drawer', await page.evaluate(() => document.getElementById('drawer').hidden));
  }
  if (o.evidence) await evidenceChecks(T, slug, id, page);

  // English
  await page.click('[data-lang-set="en"]'); await settle(page, 150);
  if (o.cards) for (const c of await cardIds(page)) { await page.click(`[data-preset="${c}"]`); await settle(page, o.settle); const left = await cjkLeftovers(page); check(`English: no Chinese left with card ${c}`, left.length === 0, left.slice(0, 3).join(' | ')); }
  else { const left = await cjkLeftovers(page); check('English: no Chinese left on screen', left.length === 0, left.slice(0, 3).join(' | ')); }
  if (await page.$('#infoBtn')) {
    await page.click('#infoBtn'); const left = await cjkLeftovers(page);
    check('English: no Chinese left in the theory drawer', left.length === 0, left.slice(0, 3).join(' | '));
    await page.keyboard.press('Escape');
  }
  await page.click('[data-lang-set="zh"]');

  // embed: the first screen of the iframe inside a chapter
  const embed = await T.open(slug, id, '?embed=1&lang=zh', { viewport: { width: 740, height: 620 } });
  await settle(embed, 400);
  const e = await embed.evaluate((sel) => {
    const st = document.querySelector(sel).getBoundingClientRect(), head = document.querySelector('header.top'), tour = document.querySelector('.tour');
    const tr = tour && getComputedStyle(tour).display !== 'none' ? tour.getBoundingClientRect() : null;
    return { top: st.top, header: head ? getComputedStyle(head).display : 'none', tourBottom: tr ? tr.bottom : null, vh: innerHeight };
  }, o.stage);
  check('embed: the page chrome is hidden', e.header === 'none');
  check('embed: the stage starts at the top of the frame', e.top < 40, `top ${e.top.toFixed(0)}px`);
  const eshare = await viewportShare(embed, o.stage);
  check(`embed: the stage fills ≥ ${Math.round(o.minEmbedShare * 100)}% of the first screen`, eshare >= o.minEmbedShare, `${(eshare * 100).toFixed(1)}%`);
  if (o.tour) check('embed: the tour bar is on the first screen', e.tourBottom != null && e.tourBottom <= e.vh + 1, `bottom ${e.tourBottom} of ${e.vh}`);
  check('embed: no sideways scrolling', (await overflowX(embed)) <= 0);
  if (o.tour && e.tourBottom != null) {
    const before = await embed.evaluate(() => (document.querySelector('[data-preset][aria-pressed="true"]') || {}).dataset?.preset || null);
    await embed.click('.tour [data-tour="next"]'); await settle(embed, o.settle);
    const after = await embed.evaluate(() => (document.querySelector('[data-preset][aria-pressed="true"]') || {}).dataset?.preset || null);
    check('embed: the tour bar steps to the next experiment', after && after !== before, `${before} → ${after}`);
    check('embed: the tour bar names the experiment', (await embed.textContent('.tour .what')).trim().length > 8);
  }
  await embed.context().close();

  // rail: the whole lab in the narrow frame of a chapter read on a phone
  if (o.rail) for (const lang of ['zh', 'en']) await railChecks(T, slug, id, lang, o.settle);

  // cited figure: a chapter cites one card with `::: {.viz src=… preset=…}`
  if (o.cards) {
    const cards = await cardIds(page), cite = cards[Math.min(1, cards.length - 1)];
    const fig = await T.open(slug, id, `?embed=1&lang=zh&preset=${cite}`, { viewport: { width: 740, height: 500 } });
    await settle(fig, 400);
    const f = await fig.evaluate(([sel, card]) => {
      const b = document.querySelector(`[data-preset="${card}"]`), tour = document.querySelector('.tour'), st = document.querySelector(sel).getBoundingClientRect();
      return { figure: document.documentElement.dataset.figure === '1', pressed: !!b && b.getAttribute('aria-pressed') === 'true', scrollY: document.documentElement.scrollHeight - innerHeight,
        tour: tour ? tour.getBoundingClientRect().bottom : null, stageBottom: st.bottom, vh: innerHeight };
    }, [o.stage, cite]);
    check(`cited figure: ?preset=${cite} opens on that card`, f.figure && f.pressed, JSON.stringify(f));
    check('cited figure: nothing scrolls inside the frame', f.scrollY <= 0 && (await overflowX(fig)) <= 0, `${f.scrollY}px`);
    const fshare = await viewportShare(fig, o.stage);
    check('cited figure: the stage fills ≥ 60% of the frame', fshare >= 0.6, `${(fshare * 100).toFixed(1)}%`);
    check('cited figure: the one-sentence note and ◀ ▶ are in the frame', f.tour != null && f.tour <= f.vh + 1 && (await fig.textContent('.tour .what')).trim().length > 8);
    await fig.context().close();
    const shot = await T.open(slug, id, `?shot=1&lang=en&preset=${cite}`, { viewport: { width: 800, height: 450 }, locale: 'en-US', reducedMotion: 'reduce' });
    await settle(shot, 400);
    const sh = await shot.evaluate(([card]) => {
      const el = document.querySelector('[data-thumb]'), r = el ? el.getBoundingClientRect() : null, b = document.querySelector(`[data-preset="${card}"]`), hud = document.querySelector('.hud-tl');
      return { fills: !!r && r.left === 0 && r.top === 0 && Math.abs(r.width - innerWidth) < 1 && Math.abs(r.height - innerHeight) < 1, pressed: !!b && b.getAttribute('aria-pressed') === 'true',
        title: hud ? getComputedStyle(hud).opacity !== '0' && hud.textContent.trim().length > 0 : true, still: !!(window.TRV && window.TRV.still) };
    }, [cite]);
    check('still for PDF/EPUB: ?shot=1 fills the frame on the cited card, with its title kept', sh.fills && sh.pressed && sh.title && sh.still, JSON.stringify(sh));
    const leftovers = await cjkLeftovers(shot);
    check('still for PDF/EPUB: the English still carries no Chinese', leftovers.length === 0, leftovers.slice(0, 3).join(' | '));
    await shot.context().close();
  }

  // phone
  const phone = await T.open(slug, id, '?lang=zh', { viewport: { width: 390, height: 844 } });
  await settle(phone, 400);
  check('phone: no sideways scrolling', (await overflowX(phone)) <= 0, `${await overflowX(phone)}px`);
  const order = await phone.evaluate((sel) => { const s = document.querySelector(sel), d = document.querySelector('.deck'); return { stage: s.getBoundingClientRect().top, deck: d ? d.getBoundingClientRect().top : Infinity }; }, o.stage);
  check('phone: the stage comes before the controls', order.stage < order.deck, JSON.stringify(order));
  if (o.cards) await runCards(phone, 'phone');
  check('phone: still no sideways scrolling after every card', (await overflowX(phone)) <= 0, `${await overflowX(phone)}px`);
  await phone.context().close();

  // cover
  const thumb = await T.open(slug, id, '?thumb=1&lang=zh', { viewport: { width: 1280, height: 720 }, reducedMotion: 'reduce' });
  await thumb.waitForTimeout(300);
  const hooked = await thumb.evaluate(async () => { if (typeof window.TRV_THUMB !== 'function') return false; await window.TRV_THUMB(); return true; });
  await settle(thumb, 500);
  check('cover: the page defines window.TRV_THUMB', hooked);
  const box = await thumb.evaluate(() => { const el = document.querySelector('[data-thumb]'); if (!el) return null; const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; });
  check('cover: [data-thumb] fills 1280 × 720', !!box && box[0] === 0 && box[1] === 0 && Math.abs(box[2] - 1280) < 1 && Math.abs(box[3] - 720) < 1, JSON.stringify(box));
  const ink = await inkShare(thumb, o.cover);
  check('cover: the cover canvas is not blank', ink > 0.01, `${(ink * 100).toFixed(2)}% drawn`);
  await thumb.context().close();

  // reduced motion
  const calm = await T.open(slug, id, '?lang=zh', { reducedMotion: 'reduce' });
  await calm.waitForTimeout(300);
  if (o.cards) { const ids = await cardIds(calm); await calm.click(`[data-preset="${ids[ids.length - 1]}"]`); await calm.waitForTimeout(700); }
  check('reduced motion: the page loads and a card applies', (await calm.evaluate(() => !!document.querySelector('[data-preset][aria-pressed="true"]'))) || !o.cards);
  await calm.context().close();

  check('no page error, console error or failed request', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
}
