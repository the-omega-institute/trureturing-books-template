// Scroll translations must not change local HUD measurements or the ownership of the original corner samples.
import { session, stageView } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';
const T = await session({ viewport: { width: 390, height: 844 } });
const page = T.page, book = listBooks()[0];
const url = `${T.origin}/site/${book.slug}/viz/__scroll__/`;
await T.context.route(`${url}**`, r => r.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head>
<link rel="stylesheet" href="../assets/theme.css"><script src="../assets/shell.js"></script><script src="../assets/kit.js"></script>
<style>body{overflow:auto}.center{display:block;margin-top:120px}.stage{height:500px}.tail{height:3000px}</style></head><body>
<main class="center"><div class="stage"><div class="hud-tl"><b class="big">A complete title</b><span class="sub">The title and legend stay inside the stage</span></div>
<div class="hud-tr"><button class="chip">Scene one</button><button class="chip">Scene two</button></div>
<div class="hud-bl"><span>The complete legend remains visible and is never shortened</span></div></div></main><div class="tail"></div></body></html>` }));
await page.goto(url); await page.evaluate(() => document.fonts.ready);
for (let mask = 0; mask < 8; mask++) {
  await page.evaluate(mask => {
    scrollTo(0, 0);
    ['.hud-tl', '.hud-tr', '.hud-bl'].forEach((q, i) => { document.querySelector(q).style.display = mask & (1 << i) ? 'none' : ''; });
    TRV.hudFit();
  }, mask);
  const measure = () => page.evaluate(() => {
    TRV.hudFit();
    const st = document.querySelector('.stage'), r = st.getBoundingClientRect();
    const parts = [...st.children].map(el => { const q = el.getBoundingClientRect(); return { height: q.height, bottom: q.bottom - r.top }; });
    return { min: parseFloat(st.style.getPropertyValue('--hud-min-height')), top: r.top, scroll: scrollY, parts };
  });
  const top = await measure();
  for (const y of [1000, 2000, 0]) {
    await page.evaluate(y => scrollTo(0, y), y);
    const moved = await measure();
    T.check(`HUD mask=${mask} scroll=${y}: local height is translation invariant`, moved.min === top.min, JSON.stringify({ top, moved }));
    T.check(`HUD mask=${mask} scroll=${y}: rendered content still fits its minimum`, moved.min >= moved.parts[2].height && moved.parts.slice(0, 2).every(p => !p.height || p.bottom + moved.parts[2].height <= moved.min), JSON.stringify(moved));
  }
}

// Real browser hit testing at fractional edges, with an independently positioned corner and a child hit target.
// No runtime is involved in these fixtures: only the shared quality gate decides ownership and scrollability.
for (const [width, height] of [[390, 844], [334, 320]]) {
  await page.setViewportSize({ width, height });
  for (const axis of ['x', 'y']) for (const edge of [-0.25, 0, 0.49, 0.5, 0.734375, 0.99, 1.25]) {
    await page.goto('about:blank');
    await page.setContent(`<!doctype html><style>html{overflow:auto}html,body{margin:0}.center{${axis === 'y' ? `margin-top:${height - 98 + edge}px` : `margin-left:${width - 91 + edge}px`}}.stage{height:100px;width:100px}.stage>span{display:block;width:100%;height:100%}.tail{height:1000px;width:1000px}</style><main class="center"><div class="stage"><span>Owned child</span></div></main><div class="tail"></div>`);
    const initial = await page.evaluate(axis => {
      const r = document.querySelector('.stage').getBoundingClientRect(), x = r.left + r.width * (axis === 'x' ? .9 : .1), y = axis === 'y' ? r.bottom - 3 : r.top + 3;
      return { x, y, hit: document.elementFromPoint(x, y)?.tagName || null, viewport: [innerWidth, innerHeight] };
    }, axis);
    // Record the gate's actual calls; do not replace the browser's hit results.
    await page.evaluate(() => { window.hits = []; const real = document.elementFromPoint.bind(document); document.elementFromPoint = (x, y) => { const hit = real(x, y); hits.push({ x, y, scroll: [scrollX, scrollY], hit: hit?.tagName || null }); return hit; }; });
    const v = await stageView(page, '.stage');
    const hits = await page.evaluate(() => hits);
    T.check(`${width}×${height} fractional ${axis} edge ${edge}: same corners hit owner or child after allowed scroll`, !v.layout.length, JSON.stringify({ initial, hits, layout: v.layout }));
    T.check(`${width}×${height} fractional ${axis} edge ${edge}: all four original corners were tested`, hits.length === 4 && hits.every(h => h.hit === 'SPAN'), JSON.stringify(hits));
  }
}
for (const kind of ['overlay', 'clipping', 'unscrollable', 'fractional-unscrollable', 'figure', 'null']) {
  await page.goto('about:blank');
  await page.setContent(`<!doctype html><style>html,body{margin:0;${kind.includes('unscrollable') ? 'overflow:hidden' : ''}${kind === 'null' ? 'pointer-events:none' : ''}}.center{margin-top:${kind === 'fractional-unscrollable' ? 222.75 : kind === 'unscrollable' || kind === 'figure' ? 224 : 20}px;${kind === 'clipping' ? 'height:40px;overflow:hidden' : ''}}.stage{height:100px;width:100%}.tail{height:1000px}#overlay{position:fixed;inset:0;z-index:100}</style><main class="center"><div class="stage"></div></main><div class="tail"></div>${kind === 'overlay' ? '<div id="overlay"></div>' : ''}`);
  const v = await stageView(page, '.stage', kind === 'figure');
  T.check(`negative ${kind}: obstructed or unreachable original corners fail`, v.layout.some(s => kind === 'unscrollable' || kind === 'figure' ? /cannot be/.test(s) : /painted over/.test(s)), JSON.stringify(v));
  if (kind === 'figure') T.check('a cited figure never scrolls and still requires complete content', await page.evaluate(() => scrollY === 0) && v.layout.some(s => /frame scrolls/.test(s)), JSON.stringify(v));
}
T.check('no page or request errors', T.errors.length === 0, JSON.stringify(T.errors));
await T.finish();
