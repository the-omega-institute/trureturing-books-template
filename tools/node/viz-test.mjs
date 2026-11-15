#!/usr/bin/env node
// Run the browser regression suites books/<slug>/viz/tests/*.test.mjs, one after another, against one shared server:
//   node tools/node/viz-test.mjs                         affected suites since the origin/main branch point, including working-tree edits
//   node tools/node/viz-test.mjs example-monograph       affected suites limited to one book (slug or directory; repeatable)
//   node tools/node/viz-test.mjs --base HEAD             compare with another branch point
//   node tools/node/viz-test.mjs --full                  explicitly run every suite (optionally limited to named books)
//   node tools/node/viz-test.mjs --shard 2/4             suites 2, 6, 10, … of the sorted list (CI runs shards in parallel)
//   node tools/node/viz-test.mjs --shard 2/4 --list      print the selection without running it
//   node tools/node/viz-test.mjs --slow                  the same with animation frames a second apart (VIZ_SLOW_FRAMES=1000,
//                                                        as on a busy runner; see viz-testkit.mjs): for clock/async changes,
//                                                        slow-frame investigations, and weekly in CI (ci.yml, viz-slow)
// Each suite is a standalone script that exits non-zero when a check fails (see tools/node/viz-testkit.mjs).
// Needs Playwright with Chromium (playwright-chromium devDependency, or PW_CHROMIUM_PATH pointing at a Chromium).
// Adapted from trureturing-visualize/scripts/test-browser.mjs (Apache-2.0, the-omega-institute).
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { fileURLToPath } from 'node:url';
import { ROOT, listBooks, resolveBook, rel } from './viz-common.mjs';
import { startServer } from './viz-server.mjs';

const args = process.argv.slice(2);
let shard = [1, 1];
const books = [];
let list = false, slow = false, selection = null, reportPath = null;
let full = false, base = 'origin/main', explicitBase = false;
for (let k = 0; k < args.length; k++) {
  const a = args[k];
  if (a === '--shard') {
    const m = /^(\d+)\/(\d+)$/.exec(args[++k] || '');
    if (!m || +m[1] < 1 || +m[1] > +m[2]) { console.error('usage: --shard i/n with 1 ≤ i ≤ n'); process.exit(2); }
    shard = [+m[1], +m[2]];
  } else if (a === '--selection-env') {
    try { selection = JSON.parse(process.env[args[++k]] || ''); }
    catch { console.error('invalid selection environment JSON'); process.exit(2); }
    if (!Array.isArray(selection) || selection.some((x) => typeof x !== 'string') || new Set(selection).size !== selection.length) {
      console.error('selection must be a JSON array of unique suite paths'); process.exit(2);
    }
  } else if (a === '--report') {
    reportPath = args[++k];
    if (!reportPath) { console.error('missing --report path'); process.exit(2); }
  } else if (a === '--base') {
    base = args[++k];
    if (!base || base.startsWith('-')) { console.error('missing --base ref'); process.exit(2); }
    explicitBase = true;
  } else if (a === '--full') full = true;
  else if (a === '--list') list = true;
  else if (a === '--slow') slow = true;
  else if (a === '-h' || a === '--help') {
    console.log('usage: node tools/node/viz-test.mjs [book ...] [--base ref | --full] [--shard i/n] [--slow] [--list]\n'
      + 'Default: only affected suites since the origin/main branch point, including staged, unstaged and untracked files.\n'
      + 'Named books filter that selection. Use --full to run all suites in scope.');
    process.exit(0);
  }
  else {
    try { books.push(resolveBook(a)); } catch (e) { console.error(e.message); process.exit(2); }
  }
}
if ((selection !== null && (full || explicitBase)) || (full && explicitBase)) {
  console.error('--selection-env, --full and --base are mutually exclusive'); process.exit(2);
}
const all = [];
for (const book of books.length ? books : listBooks()) {
  const dir = path.join(book.dir, 'viz', 'tests');
  if (!fs.existsSync(dir)) continue;
  for (const f of fs.readdirSync(dir).filter((f) => f.endsWith('.test.mjs')).sort()) all.push(path.join(dir, f));
}
if (selection === null && !full && all.length) {
  // Use the same old/new dependency graph as ./tbook test and CI, even when TBOOK_ROOT points at a fixture.
  const codeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
  const venv = path.join(codeRoot, '.venv', 'bin', 'python');
  const python = process.env.TBOOK_PYTHON || (fs.existsSync(venv) ? venv : 'python3');
  const code = 'import json, sys\nfrom ci import plan, testing\n'
    + 'old, current, changed = testing.working_changes(sys.argv[1], sys.argv[2])\n'
    + 'json.dump(plan.impact(current, old, changed)["suites"], sys.stdout)\n';
  const result = spawnSync(python, ['-c', code, ROOT, base], {
    cwd: ROOT, encoding: 'utf8', maxBuffer: 1 << 26,
    env: { ...process.env, PYTHONPATH: [path.join(codeRoot, 'tools'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) }
  });
  if (result.error || result.status !== 0) {
    console.error(`cannot determine affected visualization suites: ${result.error?.message || result.stderr.trim() || result.signal || result.status}\n`
      + 'Provide an available comparison ref with --base <ref>, or explicitly request --full.');
    process.exit(2);
  }
  try {
    const affected = JSON.parse(result.stdout);
    if (!Array.isArray(affected) || affected.some((s) => typeof s !== 'string')) throw new Error('expected suite paths');
    const scope = new Set(all.map(rel));
    selection = affected.filter((s) => scope.has(s));
  } catch (e) { console.error(`invalid affected suite selection: ${e.message}`); process.exit(2); }
}
// A parent path still means the complete standalone suite. CI uses explicit #part units.
const byName = new Map(all.map((f) => [rel(f), { file: f, part: '' }]));
const declared = new Map();
try {
  for (const dir of new Set(all.map((f) => path.dirname(f)))) {
    const meta = path.join(dir, 'execution-parts.json');
    if (!fs.existsSync(meta)) continue;
    const data = JSON.parse(fs.readFileSync(meta, 'utf8'));
    if (!data || Object.keys(data).sort().join() !== 'schema,suites' || data.schema !== 'tbook-viz-parts-v1' || !data.suites || Array.isArray(data.suites) || typeof data.suites !== 'object') throw new Error('invalid execution-parts.json schema');
    for (const [name, parts] of Object.entries(data.suites)) {
      const parent = rel(path.join(dir, name));
      if (path.basename(name) !== name || !byName.has(parent) || !Array.isArray(parts) || !parts.length || parts.length > 64 || new Set(parts).size !== parts.length || parts.some((p) => typeof p !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(p))) throw new Error(`invalid execution parts for ${name}`);
      declared.set(parent, parts);
      for (const part of parts) byName.set(`${parent}#${part}`, { file: byName.get(parent).file, part });
    }
  }
  if (selection && selection.some((f) => !byName.has(f))) throw new Error('unknown or hidden selected suite/part');
  if (selection && selection.some((f) => f.includes('#') && selection.includes(f.split('#')[0]))) throw new Error('overlapping whole suite and part selection');
} catch (e) { console.error(e.message); process.exit(2); }
const chosen = selection === null ? all.map(rel) : [...selection].sort();
const suites = chosen.filter((_, k) => k % shard[1] === shard[0] - 1);
if (list) { console.log(suites.join('\n')); process.exit(0); }
const frames = Number(slow ? '1000' : process.env.VIZ_SLOW_FRAMES || '0');
if (![0, 1000].includes(frames) && reportPath) { console.error('reports require normal or 1000ms slow frames'); process.exit(2); }
const report = {
  schema: 'tbook-viz-report-v1', profile: frames ? 'slow' : 'normal', frames,
  sha: process.env.GITHUB_SHA || 'local', run_id: process.env.GITHUB_RUN_ID || 'local', run_attempt: process.env.GITHUB_RUN_ATTEMPT || '1',
  runtime: Object.fromEntries(['ImageOS', 'ImageVersion', 'TBOOK_TOOLCHAIN'].map((k) => [k, process.env[k] || ''])),
  node: process.version, results: []
};
const saveReport = () => {
  if (!reportPath) return;
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath + '.tmp', JSON.stringify(report) + '\n');
  fs.renameSync(reportPath + '.tmp', reportPath);
};
if (!suites.length) {
  saveReport();
  console.log(!all.length ? 'no browser suites under books/*/viz/tests/'
    : !chosen.length ? 'no affected visualization suites' : `shard ${shard[0]}/${shard[1]} has no suites`);
  process.exit(0);
}

const { server, origin } = await startServer(0);
const env = { ...process.env, VIZ_ORIGIN: origin, ...(slow ? { VIZ_SLOW_FRAMES: '1000' } : {}) };

if (frames) console.log(`slow frames: an animation frame every ${frames} ms (VIZ_SLOW_FRAMES=${env.VIZ_SLOW_FRAMES})`);
const run = (unit) => new Promise((resolve) => {
  const { file, part } = byName.get(unit), started = performance.now();
  // Never inherit a caller's part into a standalone whole-suite run.
  const child = spawn(process.execPath, [file], { stdio: 'inherit', env: { ...env, VIZ_TEST_PART: part } });
  let done = false;
  const finish = (code, signal) => {
    if (done) return;
    done = true;
    report.results.push({ unit, seconds: Math.max(0.000001, (performance.now() - started) / 1000), exit_code: code, signal });
    saveReport();
    resolve(code === 0 && !signal);
  };
  child.on('exit', finish);
  child.on('error', () => finish(null, 'spawn-error'));
});
let failed = 0;
for (const f of suites) {
  console.log(`\n=== ${f}`);
  if (!(await run(f))) { failed++; console.log(`--- FAILED ${f}`); }
}
server.close();
console.log(`\n${suites.length - failed}/${suites.length} suites passed${shard[1] > 1 ? ` (shard ${shard[0]}/${shard[1]})` : ''}${frames ? `, with slow frames (${frames} ms)` : ''}`);
process.exit(failed ? 1 : 0);
