#!/usr/bin/env node
// Screenshots of static figures as the editions show them. Called by `./tbook fig shots <book> [<name> …]`
// (tools/tbook/figure.py), which writes one page per figure, language and view and the job list this reads:
//   node tools/node/fig-shots.mjs <jobs.json>
// jobs.json: { jobs: [{ page, out, name, lang, view, width }], sheet: bool, out: DIR }
// Views: dark and light (the HTML edition's two palettes, 800 px wide), phone (390 px), print (the file the
// print PDF embeds, on white paper). With `sheet`, the shots of each language and view are also laid out on
// contact sheets <DIR>/sheet-<lang>-<view>[-<n>].png, twelve figures a sheet, for reviewing many figures at once.
// Open the files and look at them: no check can tell a clear figure from a cluttered one (skills/book-figure).
// Needs Playwright with Chromium (as viz-shots.mjs); honours PW_CHROMIUM_PATH.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromiumOptions, loadChromium, localFontsCss, FONTSOURCE, rel } from './viz-common.mjs';

const specFile = process.argv[2];
if (!specFile) { console.error('usage: node tools/node/fig-shots.mjs <jobs.json>   (run ./tbook fig shots <book> instead)'); process.exit(2); }
const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
const fonts = localFontsCss(pathToFileURL(FONTSOURCE).href + '/');
const chromium = await loadChromium();
const browser = await chromium.launch(chromiumOptions(['--allow-file-access-from-files']));
let failures = 0;
const PER_SHEET = 12;
try {
  const done = [];
  for (const job of spec.jobs) {
    const context = await browser.newContext({ viewport: { width: job.width, height: 80 }, deviceScaleFactor: 2,
      locale: job.lang === 'zh' ? 'zh-CN' : 'en-US', colorScheme: job.view === 'dark' || job.view === 'phone' ? 'dark' : 'light' });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(pathToFileURL(job.page).href, { waitUntil: 'load' });
    if (fonts) await page.addStyleTag({ content: fonts });
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(120);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await page.screenshot({ path: job.out, fullPage: true });
    const notes = [];
    if (overflow > 0) { notes.push(`horizontal overflow ${overflow}px`); failures++; }
    if (errors.length) { notes.push(`page errors: ${errors.join('; ')}`); failures++; }
    console.log(`${rel(job.out)}${notes.length ? `  ! ${notes.join(' · ')}` : ''}`);
    done.push(job);
    await context.close();
  }
  if (spec.sheet && done.length > 1) {
    const groups = new Map();
    for (const job of done) {
      const key = `${job.lang}-${job.view}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(job);
    }
    for (const [key, jobs] of groups) {
      if (jobs.length < 2) continue;
      for (let k = 0, n = 1; k < jobs.length; k += PER_SHEET, n++) {
        const part = jobs.slice(k, k + PER_SHEET);
        const light = /light|print/.test(key);
        const cells = part.map((j) => `<figure><img src="${pathToFileURL(j.out).href}"><figcaption>${j.name}</figcaption></figure>`).join('');
        const htmlText = `<!doctype html><meta charset="utf-8"><style>
          body{margin:0;padding:12px;background:${light ? '#dfe7ec' : '#000'};font:13px/1.3 ui-monospace,monospace;color:${light ? '#123' : '#9bd'}}
          .g{display:grid;grid-template-columns:repeat(${key.endsWith('phone') ? 4 : 3},1fr);gap:10px;align-items:start}
          figure{margin:0}img{display:block;width:100%;height:auto}figcaption{padding:3px 2px}</style><div class="g">${cells}</div>`;
        const file = path.join(spec.out, `sheet-${key}${jobs.length > PER_SHEET ? `-${n}` : ''}.png`);
        const context = await browser.newContext({ viewport: { width: 1800, height: 100 }, deviceScaleFactor: 1 });
        const page = await context.newPage();
        const tmp = path.join(path.dirname(specFile), `sheet-${key}-${n}.html`);
        fs.writeFileSync(tmp, htmlText);
        await page.goto(pathToFileURL(tmp).href, { waitUntil: 'load' });
        await page.screenshot({ path: file, fullPage: true });
        console.log(rel(file));
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
