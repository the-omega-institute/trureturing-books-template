#!/usr/bin/env node
// Run the browser regression suites books/<slug>/viz/tests/*.test.mjs, one after another, against one shared server:
//   node tools/node/viz-test.mjs                         every suite of every book
//   node tools/node/viz-test.mjs example-monograph       the suites of one book (slug or directory; repeatable)
//   node tools/node/viz-test.mjs --shard 2/4             suites 2, 6, 10, … of the sorted list (CI runs shards in parallel)
//   node tools/node/viz-test.mjs --shard 2/4 --list      print the selection without running it
//   node tools/node/viz-test.mjs --slow                  the same with animation frames a second apart (VIZ_SLOW_FRAMES=1000,
//                                                        as on a busy runner; see viz-testkit.mjs): before trusting a new
//                                                        or changed suite, and weekly in CI (ci.yml, viz-slow)
// Each suite is a standalone script that exits non-zero when a check fails (see tools/node/viz-testkit.mjs).
// Needs Playwright with Chromium (playwright-chromium devDependency, or PW_CHROMIUM_PATH pointing at a Chromium).
// Adapted from trureturing-visualize/scripts/test-browser.mjs (Apache-2.0, the-omega-institute).
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { listBooks, resolveBook, rel } from './viz-common.mjs';
import { startServer } from './viz-server.mjs';

const args = process.argv.slice(2);
let shard = [1, 1];
const books = [];
let list = false, slow = false;
for (let k = 0; k < args.length; k++) {
  const a = args[k];
  if (a === '--shard') {
    const m = /^(\d+)\/(\d+)$/.exec(args[++k] || '');
    if (!m || +m[1] < 1 || +m[1] > +m[2]) { console.error('usage: --shard i/n with 1 ≤ i ≤ n'); process.exit(2); }
    shard = [+m[1], +m[2]];
  } else if (a === '--list') list = true;
  else if (a === '--slow') slow = true;
  else if (a === '-h' || a === '--help') { console.log('usage: node tools/node/viz-test.mjs [book ...] [--shard i/n] [--slow] [--list]'); process.exit(0); }
  else {
    try { books.push(resolveBook(a)); } catch (e) { console.error(e.message); process.exit(2); }
  }
}
const all = [];
for (const book of books.length ? books : listBooks()) {
  const dir = path.join(book.dir, 'viz', 'tests');
  if (!fs.existsSync(dir)) continue;
  for (const f of fs.readdirSync(dir).filter((f) => f.endsWith('.test.mjs')).sort()) all.push(path.join(dir, f));
}
const suites = all.filter((_, k) => k % shard[1] === shard[0] - 1);
if (list) { console.log(suites.map(rel).join('\n')); process.exit(0); }
if (!suites.length) { console.log(all.length ? `shard ${shard[0]}/${shard[1]} has no suites` : 'no browser suites under books/*/viz/tests/'); process.exit(0); }

const { server, origin } = await startServer(0);
const env = { ...process.env, VIZ_ORIGIN: origin, ...(slow ? { VIZ_SLOW_FRAMES: '1000' } : {}) };
const frames = Number(env.VIZ_SLOW_FRAMES) || 0;
if (frames) console.log(`slow frames: an animation frame every ${frames} ms (VIZ_SLOW_FRAMES=${env.VIZ_SLOW_FRAMES})`);
const run = (file) => new Promise((resolve) => {
  const child = spawn(process.execPath, [file], { stdio: 'inherit', env });
  child.on('exit', (code, signal) => resolve(code === 0 && !signal));
  child.on('error', () => resolve(false));
});
let failed = 0;
for (const f of suites) {
  console.log(`\n=== ${rel(f)}`);
  if (!(await run(f))) { failed++; console.log(`--- FAILED ${rel(f)}`); }
}
server.close();
console.log(`\n${suites.length - failed}/${suites.length} suites passed${shard[1] > 1 ? ` (shard ${shard[0]}/${shard[1]})` : ''}${frames ? `, with slow frames (${frames} ms)` : ''}`);
process.exit(failed ? 1 : 0);
