// SPDX-License-Identifier: Apache-2.0
// Paper stills for academic decks; reuse the visualization server, font routing,
// card/still contract and screenshot path used by viz-shots/viz-thumbs.
import fs from 'node:fs';
import { ROOT, resolveBook, loadChromium, chromiumOptions, TOKENS_JSON } from './viz-common.mjs';
import { startServer, vizUrl } from './viz-server.mjs';
import { routeLocalFonts, settle } from './viz-testkit.mjs';

const jobs = JSON.parse(process.argv[2] || '[]');
const paper = JSON.parse(fs.readFileSync(TOKENS_JSON, 'utf8')).paper;
const chromium = await loadChromium();
const { server, origin } = await startServer(0);
let browser;
try {
  browser = await chromium.launch(chromiumOptions());
  for (const job of jobs) {
    resolveBook(job.book); // respect hidden-book selection
    const context = await browser.newContext({ viewport: { width: 800, height: 450 }, deviceScaleFactor: 4,
      colorScheme: 'light', reducedMotion: 'reduce', locale: job.lang });
    await routeLocalFonts(context, origin);
    await context.addInitScript((palette) => {
      // Set tokens before shell.js reads/caches the palette, including canvas paints.
      const style = document.createElement('style');
      style.textContent = ':root{' + Object.entries(palette).map(([k,v]) => `--tr-${k}:${v}!important`).join(';')
        + ';--tr-fx-vignette:none!important;--tr-fx-scanlines:none!important;--tr-fx-glow-cyan:none!important;--tr-fx-glow-amber:none!important}';
      const install = () => document.documentElement.append(style);
      if (document.documentElement) install(); else new MutationObserver((_, ob) => { if (document.documentElement) { install(); ob.disconnect(); } }).observe(document, { childList:true });
    }, paper);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(vizUrl(origin, job.book, job.id, `?shot=1&lang=${job.lang}&preset=${job.preset}`), { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await settle(page);
    const state = await page.evaluate((preset) => {
      const button = document.querySelector(`[data-preset="${preset}"]`);
      return button?.getAttribute('aria-pressed') === 'true';
    }, job.preset);
    if (!state || errors.length) throw new Error(`${job.book}/${job.id}/${job.preset}: ${errors.join('; ') || 'card not selected'}`);
    // Reject a nominally high-resolution PNG whose main stage canvas was upscaled.
    // Supporting plots can remain laid out behind the full-page shot stage.
    const undersampled = await page.evaluate(() => [...document.querySelectorAll('canvas')]
      .filter(cv => {
        const r = cv.getBoundingClientRect();
        return cv.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
          && r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
      })
      .sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight).slice(0, 1)
      .filter(cv => cv.width < cv.clientWidth * devicePixelRatio || cv.height < cv.clientHeight * devicePixelRatio)
      .map(cv => cv.id || 'canvas'));
    if (undersampled.length) throw new Error(`paper snapshot has undersampled canvases: ${undersampled.join(', ')}`);
    await page.screenshot({ path: job.out });
    console.log(`paper snapshot → ${job.out.replace(ROOT + '/', '')}`);
    await context.close();
  }
} finally {
  if (browser) await browser.close();
  server.close();
}
