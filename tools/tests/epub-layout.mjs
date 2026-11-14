// Exercise the exported XHTML, native MathML and stylesheet without injecting layout fixes.
import { pathToFileURL } from 'node:url';
import { loadChromium, chromiumOptions } from '../node/viz-common.mjs';

const browser = await (await loadChromium()).launch(chromiumOptions());
const rows = [];
try {
  for (const width of [390, 1000]) {
    const page = await browser.newPage({ viewport: { width, height: 850 } });
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message));
    await page.goto(pathToFileURL(process.argv[2]).href);
    await page.evaluate(() => document.fonts.ready);
    const row = await page.evaluate(() => {
      const math = [...document.querySelectorAll('.tr-math-scroll')].filter(e => e.scrollWidth > e.clientWidth + 1);
      const tables = [...document.querySelectorAll('.tr-table-scroll')].filter(e => e.scrollWidth > e.clientWidth + 1);
      let inaccessibleEnds = 0;
      for (const e of [...math, ...tables]) {
        if (getComputedStyle(e).overflowX !== 'auto') inaccessibleEnds++;
        const child = e.firstElementChild;
        const left = child.getBoundingClientRect().left;
        // The left edge and the far right edge must both be reachable, at full font size.
        if (left < e.getBoundingClientRect().left - 1) inaccessibleEnds++;
        e.scrollLeft = e.scrollWidth;
        if (e.scrollLeft < 1 || child.getBoundingClientRect().right > e.getBoundingClientRect().right + 2) inaccessibleEnds++;
        if (getComputedStyle(child).transform !== 'none') inaccessibleEnds++;
        e.scrollLeft = 0;
      }
      // Confining the table must not squeeze prose into one-character columns.
      const narrowCells = [...document.querySelectorAll('th,td')].filter(e =>
        e.getBoundingClientRect().width < 6 * parseFloat(getComputedStyle(e).fontSize));
      return { documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        mathScrolls: math.length, tableScrolls: tables.length, inaccessibleEnds, narrowCells: narrowCells.length };
    });
    rows.push({ width, ...row, pageErrors });
    await page.close();
  }
} finally { await browser.close(); }
console.log(JSON.stringify(rows));
