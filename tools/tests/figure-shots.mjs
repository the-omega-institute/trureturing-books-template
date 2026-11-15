// Measure the screenshot tool's actual pages, independently of its CSS selectors.
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import { loadChromium, chromiumOptions } from '../node/viz-common.mjs';

const chromium = await loadChromium();
const browser = await chromium.launch(chromiumOptions(['--allow-file-access-from-files']));
const report = [];
try {
  for (const job of JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))) {
    const context = await browser.newContext({ viewport: { width: job.viewport, height: 900 },
      colorScheme: ['dark', 'phone'].includes(job.view) ? 'dark' : 'light' });
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message));
    await page.goto(pathToFileURL(job.page).href);
    const measured = await page.evaluate(job => {
      const errors = [];
      const near = (label, actual, expected, tolerance = 0.05) => {
        if (Math.abs(actual - expected) > tolerance) errors.push(`${label}: ${actual} != ${expected}`);
      };
      const roots = [...document.querySelectorAll('svg')].filter(s => !s.ownerSVGElement);
      const stacked = job.name === 'wrapped' && job.view !== 'print';
      near('root count', roots.length, stacked ? 2 : 1);
      for (const root of roots) {
        const box = root.getBoundingClientRect();
        const naturalWidth = stacked ? 200 : job.width;
        const naturalHeight = stacked ? 160 : job.height;
        const expectedWidth = job.view === 'print'
          ? 728 * Math.round(100 * job.width / 760) / 100
          : Math.min(naturalWidth, job.viewport - 32);
        near('outer width', box.width, expectedWidth);
        near('outer height', box.height, expectedWidth * naturalHeight / naturalWidth);
        // Check the authored nested viewport AND where its corners/edge marks land on screen.
        // A nested SVG's bounding box alone measures ink, not its viewport or clipping.
        for (const panel of root.querySelectorAll('svg')) {
          const authored = key => Number(panel.getAttribute(key));
          near('panel width', parseFloat(getComputedStyle(panel).width), authored('width'));
          near('panel height', parseFloat(getComputedStyle(panel).height), authored('height'));
          const vb = panel.viewBox.baseVal;
          const actualMatrix = panel.getScreenCTM(), outerMatrix = root.getScreenCTM();
          const point = (x, y, matrix) => new DOMPoint(x, y).matrixTransform(matrix);
          const compare = (label, x, y) => {
            const actual = point(x, y, actualMatrix);
            const expected = point(authored('x') + (x - vb.x) * authored('width') / vb.width,
              authored('y') + (y - vb.y) * authored('height') / vb.height, outerMatrix);
            near(`${label} x`, actual.x, expected.x);
            near(`${label} y`, actual.y, expected.y);
          };
          compare('panel origin', vb.x, vb.y);
          compare('panel end', vb.x + vb.width, vb.y + vb.height);
          for (const rect of panel.querySelectorAll('rect')) {
            compare('mark origin', rect.x.baseVal.value, rect.y.baseVal.value);
            compare('mark end', rect.x.baseVal.value + rect.width.baseVal.value,
              rect.y.baseVal.value + rect.height.baseVal.value);
          }
        }
      }
      if (job.name === 'wrapped' && job.view === 'phone') {
        const [first, second] = roots.map(s => s.getBoundingClientRect());
        if (second.top < first.bottom) errors.push('phone panels did not stack');
      }
      near('page overflow', document.documentElement.scrollWidth - job.viewport, 0);
      return { errors };
    }, job);
    report.push({ name: job.name, view: job.view, errors: [...pageErrors, ...measured.errors] });
    await context.close();
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify(report));
