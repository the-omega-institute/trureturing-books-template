#!/usr/bin/env node
// Capture the still images of visualizations with Playwright + Chromium (software WebGL):
//   node tools/node/viz-thumbs.mjs                          every registered entry of every book
//   node tools/node/viz-thumbs.mjs example-monograph        every entry of one book (slug or directory)
//   node tools/node/viz-thumbs.mjs example-monograph golden-carry [more ids]
// Two kinds of image are written into books/<slug>/viz/<id>/ (commit them):
//   thumb.jpg                 the wordless 1280×720 cover for the hub, the landing page and uncited embeds
//   fig-<card>.<lang>.jpg     the labelled still (1600×900) of every experiment card that a chapter cites with
//                             `::: {.viz src="<id>" preset="<card>"}`, one per language edition citing it; PDF and
//                             EPUB show it in place of the cover. Stills that no chapter cites any more are removed.
// The page is opened as <id>/?thumb=1&lang=zh, served with the runtime mounted at ../assets like the published site.
// shell.js then sets <html data-thumb-mode>, theme.css makes the page's [data-thumb] region (else its .stage) fill the
// viewport and hides toasts and HUD text, so one cover serves both languages. A page may define window.TRV_THUMB()
// (sync or async) to put itself into a representative cover state first. A still is the page opened as
// <id>/?shot=1&lang=<lang>&preset=<card>: the same region with its title, labels and legend kept (TRV.still is set, so
// the page shows the card's telling frame instead of playing): a card that plays by itself declares that frame as
// `still` in the page's table of cards (kit.cards({ presets }) writes it onto the card as data-still; see
// templates/viz/README.md). Chromium honours PW_CHROMIUM_PATH.
// Adapted from trureturing-visualize/scripts/thumbs.mjs (Apache-2.0, the-omega-institute).
import path from 'node:path';
import fs from 'node:fs';
import { listBooks, resolveBook, readRegistry, registryPath, chromiumOptions, loadChromium, rel, citedCards } from './viz-common.mjs';
import { startServer, vizUrl } from './viz-server.mjs';
import { routeLocalFonts, STILL, stillQuery, prepareStill } from './viz-testkit.mjs';

export const WIDTH = 1280, HEIGHT = 720;
/** Stills use the same capture setup as openStill() of viz-testkit.mjs. */
export { STILL, citedCards };
const args = process.argv.slice(2);
let books = listBooks(), ids = [];
if (args.length) {
  try { books = [resolveBook(args[0])]; ids = args.slice(1); } catch (e) {
    if (e.hidden) { console.error(e.message); process.exit(2); } // a book that site.toml [books].hide hides
    // not a book: treat every argument as an id across all books
    ids = args;
  }
}
const jobs = [];
for (const book of books) {
  if (!fs.existsSync(registryPath(book))) continue;
  for (const v of readRegistry(book).visualizations || []) if (!ids.length || ids.includes(v.id)) jobs.push({ book, v });
}
if (!jobs.length) { console.error(`no matching registry entries${ids.length ? ` for ${ids.join(', ')}` : ''}`); process.exit(2); }

const chromium = await loadChromium();
const { server, origin } = await startServer(0);
const browser = await chromium.launch(chromiumOptions());
let failures = 0;
try {
  for (const { book, v } of jobs) {
    const context = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1, locale: 'zh-CN', reducedMotion: 'reduce' });
    await routeLocalFonts(context, origin);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(vizUrl(origin, book.slug, v.id, '?thumb=1&lang=zh'), { waitUntil: 'load' });
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(600);
    // a [data-thumb] region, else the page's stage, fills the viewport (theme.css); give layout and canvases a resize
    await page.evaluate(() => {
      if (!document.querySelector('[data-thumb]')) { const s = document.querySelector('.stage'); if (s) s.setAttribute('data-thumb', ''); }
      window.dispatchEvent(new Event('resize'));
    });
    const hooked = await page.evaluate(async () => { if (typeof window.TRV_THUMB === 'function') { await window.TRV_THUMB(); return true; } return false; });
    await page.waitForTimeout(hooked ? 1500 : 1000);
    if (!(await page.$('[data-thumb]'))) { console.error(`${book.slug}/${v.id}: no [data-thumb] or .stage element to capture`); failures++; await context.close(); continue; }
    const out = path.join(book.dir, 'viz', v.thumbnail || `${v.id}/thumb.jpg`);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    await page.screenshot({ path: out, type: 'jpeg', quality: 84, clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT } });
    console.log(`${book.slug}/${v.id} → ${rel(out)}${errors.length ? `  (page errors: ${errors.join('; ')})` : ''}`);
    if (errors.length) failures++;
    await context.close();

    // the labelled stills of the cards that chapters cite
    const dir = path.join(book.dir, 'viz', v.id), cited = citedCards(book, v.id), keep = new Set(cited.map((c) => `fig-${c.preset}.${c.lang}.jpg`));
    for (const old of fs.existsSync(dir) ? fs.readdirSync(dir).filter((n) => /^fig-.*\.jpg$/.test(n) && !keep.has(n)) : []) { fs.unlinkSync(path.join(dir, old)); console.log(`${book.slug}/${v.id}: removed ${old} (no chapter cites it)`); }
    for (const { preset, lang } of cited) {
      const ctx = await browser.newContext({ viewport: { width: STILL.width, height: STILL.height }, deviceScaleFactor: STILL.scale, locale: lang === 'zh' ? 'zh-CN' : lang, reducedMotion: 'reduce' });
      await routeLocalFonts(ctx, origin);
      const pg = await ctx.newPage();
      const errs = [];
      pg.on('pageerror', (e) => errs.push(e.message));
      pg.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });
      await pg.goto(vizUrl(origin, book.slug, v.id, stillQuery(preset, lang)), { waitUntil: 'load' });
      const state = await prepareStill(pg, preset);
      const file = path.join(dir, `fig-${preset}.${lang}.jpg`);
      if (!state.has) { console.error(`${book.slug}/${v.id}: no card data-preset="${preset}" (cited by a ${lang} chapter)`); failures++; await ctx.close(); continue; }
      if (!state.on) errs.push(`the page did not open on card "${preset}" (does it call cards.initial()?)`);
      await pg.screenshot({ path: file, type: 'jpeg', quality: 82, clip: { x: 0, y: 0, width: STILL.width, height: STILL.height } });
      console.log(`${book.slug}/${v.id} [${preset} · ${lang}] → ${rel(file)}${errs.length ? `  (page errors: ${errs.join('; ')})` : ''}`);
      if (errs.length) failures++;
      await ctx.close();
    }
  }
} finally {
  await browser.close();
  server.close();
}
process.exit(failures ? 1 : 0);
