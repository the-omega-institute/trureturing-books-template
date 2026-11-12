#!/usr/bin/env node
// Review screenshots of a book-local visualization, for looking at the page the way a reader will see it:
//   node tools/node/viz-shots.mjs <book> <id> [more ids] [--out DIR] [--lang zh|en|both] [--views desk,embed,phone,thumb]
//                                             [--do "<js>"] [--wait MS] [--name SUFFIX] [--width PX] [--height PX] [--preset CARD]
// Writes PNG files to DIR (default build/viz-shots/<book>/):
//   <id>-desk-<lang>.png    1440×900   the full page
//   <id>-embed-<lang>.png   740×620    ?embed=1, the first screen of the iframe inside a chapter
//   <id>-phone-<lang>.png   390×844    full-page capture at phone width
//   <id>-thumb.png          1280×720   ?thumb=1 after window.TRV_THUMB(), i.e. the cover the hub and the PDF show
// --do runs a snippet in the page before the capture (after load), e.g. --do "document.querySelector('[data-preset=area]').click()"
// so that a particular state can be reviewed; --name adds a suffix to the file names of that run.
// Open the files and look at them: tests cannot tell a clear picture from a cluttered one (skills/book-viz, "看图").
// Needs Playwright with Chromium (as viz-test.mjs); honours PW_CHROMIUM_PATH.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, resolveBook, readRegistry, chromiumOptions, loadChromium, rel } from './viz-common.mjs';
import { startServer, vizUrl } from './viz-server.mjs';
import { routeLocalFonts, settle } from './viz-testkit.mjs';

const VIEWS = {
  desk: { width: 1440, height: 900, query: '' },
  embed: { width: 740, height: 620, query: 'embed=1' },
  phone: { width: 390, height: 844, query: '', fullPage: true },
  thumb: { width: 1280, height: 720, query: 'thumb=1', once: true }
};
const args = process.argv.slice(2);
const opt = { out: null, lang: 'both', views: Object.keys(VIEWS), do: null, wait: 700, name: '', width: null, height: null, preset: null };
const rest = [];
for (let k = 0; k < args.length; k++) {
  const a = args[k];
  if (a === '--out') opt.out = args[++k];
  else if (a === '--lang') opt.lang = args[++k];
  else if (a === '--views') opt.views = String(args[++k] || '').split(',').filter(Boolean);
  else if (a === '--width' || a === '--height') opt[a.slice(2)] = Number(args[++k]);
  else if (a === '--preset') opt.preset = args[++k];
  else if (a === '--do') opt.do = args[++k];
  else if (a === '--wait') opt.wait = Number(args[++k]) || 0;
  else if (a === '--name') opt.name = args[++k] || '';
  else if (a === '-h' || a === '--help') { console.log('usage: node tools/node/viz-shots.mjs <book> <id> [ids…] [--out DIR] [--lang zh|en|both] [--views desk,embed,phone,thumb] [--do "<js>"] [--wait MS] [--name SUFFIX] [--width PX] [--height PX] [--preset CARD]'); process.exit(0); }
  else rest.push(a);
}
if (!rest.length) { console.error('usage: node tools/node/viz-shots.mjs <book> <id> [ids…]   (see the header of this file)'); process.exit(2); }
for (const key of ['width', 'height']) if (opt[key] !== null && (!Number.isInteger(opt[key]) || opt[key] <= 0)) {
  console.error(`--${key} must be a positive integer`); process.exit(2);
}
if (opt.preset !== null && !/^[A-Za-z0-9][\w-]*$/.test(opt.preset || '')) { console.error('--preset must name an experiment card'); process.exit(2); }
let book;
try { book = resolveBook(rest[0]); } catch (e) { console.error(e.message); process.exit(2); }
const known = (readRegistry(book).visualizations || []).map((v) => v.id);
const ids = rest.slice(1).length ? rest.slice(1) : known;
for (const id of ids) if (!known.includes(id)) { console.error(`${book.slug}: no registered visualization "${id}" (have: ${known.join(', ') || 'none'})`); process.exit(2); }
for (const v of opt.views) if (!VIEWS[v]) { console.error(`unknown view "${v}" (have: ${Object.keys(VIEWS).join(', ')})`); process.exit(2); }
const langs = opt.lang === 'both' ? ['zh', 'en'] : [opt.lang];
const outDir = path.resolve(opt.out || path.join(ROOT, 'build', 'viz-shots', book.slug));
fs.mkdirSync(outDir, { recursive: true });

const chromium = await loadChromium();
const { server, origin } = await startServer(0);
const browser = await chromium.launch(chromiumOptions());
let failures = 0;
try {
  for (const id of ids) for (const view of opt.views) {
    const V = { ...VIEWS[view], width: opt.width || VIEWS[view].width, height: opt.height || VIEWS[view].height };
    for (const lang of V.once ? ['zh'] : langs) {
      const context = await browser.newContext({ viewport: { width: V.width, height: V.height }, deviceScaleFactor: 1, locale: lang === 'zh' ? 'zh-CN' : 'en-US', reducedMotion: view === 'thumb' ? 'reduce' : 'no-preference' });
      await routeLocalFonts(context, origin);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
      await page.goto(vizUrl(origin, book.slug, id, `?${[V.query, `lang=${lang}`, opt.preset ? `preset=${encodeURIComponent(opt.preset)}` : ''].filter(Boolean).join('&')}`), { waitUntil: 'load' });
      await page.evaluate(() => document.fonts && document.fonts.ready);
      await settle(page);
      if (opt.preset && !(await page.locator(`[data-preset="${opt.preset}"]`).count())) throw new Error(`no experiment card "${opt.preset}"`);
      if (view === 'thumb') {
        await page.evaluate(() => {
          if (!document.querySelector('[data-thumb]')) { const s = document.querySelector('.stage'); if (s) s.setAttribute('data-thumb', ''); }
          window.dispatchEvent(new Event('resize'));
        });
        await page.evaluate(async () => { if (typeof window.TRV_THUMB === 'function') await window.TRV_THUMB(); });
      } else if (opt.do) {
        try { await page.evaluate(opt.do); } catch (e) { errors.push(`--do: ${e.message}`); }
      }
      await settle(page, opt.wait);
      const file = path.join(outDir, `${id}-${view}${V.once ? '' : `-${lang}`}${opt.preset ? `-${opt.preset}` : ''}${opt.width ? `-w${V.width}` : ''}${opt.height ? `-h${V.height}` : ''}${opt.name ? `-${opt.name}` : ''}.png`);
      await page.screenshot({ path: file, fullPage: !!V.fullPage });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      const notes = [];
      if (overflow > 0 && view !== 'thumb') { notes.push(`horizontal overflow ${overflow}px`); failures++; }
      if (errors.length) { notes.push(`page errors: ${errors.join('; ')}`); failures++; }
      console.log(`${rel(file)}${notes.length ? `  ! ${notes.join(' · ')}` : ''}`);
      await context.close();
    }
  }
} finally {
  await browser.close();
  server.close();
}
process.exit(failures ? 1 : 0);
