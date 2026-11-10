#!/usr/bin/env node
// Browser regression suite for __BOOK__/viz/__ID__ (Playwright + Chromium):
//   node books/__BOOK__/viz/tests/__ID__.test.mjs        (or node tools/node/viz-test.mjs __BOOK__)
// stageFirstChecks is the battery every stage-first page must pass (desktop, English, the frame inside a chapter, a
// cited card, the still for PDF/EPUB, phone, cover, reduced motion). After it come the checks of this page: one for
// every control, and one for each property the page claims, against an independent computation written here (never
// by calling the page's own functions).
import { session, stageFirstChecks, settle } from '../../../../tools/node/viz-testkit.mjs';

const T = await session();
const { check } = T;
await stageFirstChecks(T, '__BOOK__', '__ID__');

const page = await T.goto('__BOOK__', '__ID__', '?lang=zh');
await settle(page, 300);
const state = async () => { await settle(page); return page.evaluate(() => window.STARTER_DEBUG.state); };
const seek = async (t) => { await page.evaluate((v) => window.STARTER_DEBUG.seek(v), t); return state(); };

let s = await state();
check('page carries its id', (await page.evaluate(() => document.body.dataset.vizId)) === '__ID__');
check('opens on the EVEN card at 45°', s.preset === 'even' && s.theta === 45 && !s.playing);
let worst = 0;
for (const deg of [0, 17, 45, 90, 133, 180, 271, 360]) { s = await seek(deg); worst = Math.max(worst, Math.abs(s.cos - Math.cos(deg * Math.PI / 180)), Math.abs(s.sin - Math.sin(deg * Math.PI / 180)), Math.abs(s.sum - 1)); }
check('shadow, height and the sum of squares for eight angles', worst < 1e-12, `max error ${worst}`);
await page.click('[data-preset="height"]'); s = await state();
check('ALL-HEIGHT: θ = 90°, the shadow is zero', s.theta === 90 && Math.abs(s.cos) < 1e-12 && (await page.textContent('#roNote')).includes('高度'));
await page.evaluate(() => { const el = document.getElementById('theta'); el.value = '200'; el.dispatchEvent(new Event('input', { bubbles: true })); }); s = await state();
check('the slider sets the angle and leaves the card', s.theta === 200 && s.preset === null);
const to = await page.evaluate(() => window.STARTER_DEBUG.at(30));
await page.mouse.move(to[0], to[1]); await page.mouse.down(); await page.mouse.up(); s = await state();
check('pressing on the circle moves the point there', Math.abs(s.theta - 30) < 1.5, `θ = ${s.theta}`);
await page.locator('body').click({ position: { x: 5, y: 5 } });
await seek(30); await page.keyboard.press('ArrowRight'); check('→ steps 15°', Math.abs((await state()).theta - 45) < 1e-9);
await page.keyboard.press('Space'); await page.waitForTimeout(700); s = await state();
check('Space plays', s.playing && s.theta > 45);
await page.keyboard.press('Space'); check('Space pauses', !(await state()).playing);

check('no page error, console error or failed request (page-specific part)', T.errors.length === 0, T.errors.slice(0, 4).join(' | '));
await T.finish();
