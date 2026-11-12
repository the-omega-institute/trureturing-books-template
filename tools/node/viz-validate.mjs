#!/usr/bin/env node
// Check each book's visualization registry against the files on disk and every page against the page contract.
//   node tools/node/viz-validate.mjs                      every book under books/
//   node tools/node/viz-validate.mjs example-monograph    one book (slug or directory; repeatable)
//   options: --json (machine-readable problems on stdout), --only=registry,lean,pages,links,dirs,thumbs,tests,scripts
// Exit code 1 when there is an error (warnings alone exit 0). Group "tests": a live visualization without a browser
// suite, and fixed waits (waitForTimeout) in a suite, are warnings. ./tbook check runs the same rules in Python
// (tools/tbook/viz.py) and calls this script with --only=scripts for the JavaScript syntax check.
// Adapted from trureturing-visualize/scripts/validate.mjs (Apache-2.0, the-omega-institute).
//
// Registry (books/<slug>/viz/visualizations.json):
//   { "version": 1, "visualizations": [ { id, code, title, title_en, summary, summary_en, path: "<id>/",
//     thumbnail: "<id>/thumb.jpg", status: "live"|"draft", added: "YYYY-MM-DD", tags, tags_en,
//     theory: [{ label, label_en, href, href_en? }], lean: [{ gid, label? }] } ] }
//   theory hrefs: https://…, {trureturing}/<path> (pinned commit), or ../<lang>/<chapter>.html (this book).
//   lean gids (and page data-lean-gid links) must be theorems of trureturing.lock.json; pages and the hub link them
//   at the pinned commit and mark them LEAN ✓.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import {
  ROOT, THEME_VIZ, TEMPLATES, ID_RE, STATUSES, RESERVED, RUNTIME_FILES, FORMAL_KINDS,
  listBooks, resolveBook, vizDir, registryPath, readLock, parseGid, pinnedRefs, rel
} from './viz-common.mjs';
import { unhideHint } from './slides-lib.mjs';

export const GROUPS = ['registry', 'lean', 'pages', 'links', 'dirs', 'thumbs', 'tests', 'scripts'];
const THUMB_EXT = /\.(jpe?g|png|webp)$/i;
const isHttps = (u) => typeof u === 'string' && /^https:\/\/\S+$/.test(u);
const nonEmpty = (s) => typeof s === 'string' && s.trim() !== '';
/** Count of elements whose class list contains `name` (paired-language fragments). */
const classCount = (html, name) => (html.match(new RegExp(`class="(?:[^"]*\\s)?${name}(?:\\s[^"]*)?"`, 'g')) || []).length;

/** Chapter file for a published path such as "zh/ch01-golden-deficit.html" (or null). */
function chapterFor(book, published) {
  const m = /^([a-z]{2,3}(?:-[A-Za-z0-9]+)*)\/(.+)\.html$/.exec(published);
  if (!m) return null;
  const cands = [path.join(book.dir, m[1], `${m[2]}.md`)];
  if (m[2] === 'index' || m[2].endsWith('/index')) cands.push(path.join(book.dir, m[1], m[2].replace(/index$/, 'README.md')));
  return cands.find((f) => fs.existsSync(f)) || cands[0];
}

/** Problems of one relative link written in the registry (base "viz/") or in a page (base "viz/<id>/"). */
function linkProblem(book, base, url, ids) {
  if (/^(https?:|mailto:|data:|#|\{trureturing\}\/)/.test(url)) return null;
  if (url.startsWith('/')) return `root-absolute link "${url}" breaks under /<repo>/ on GitHub Pages; use a relative link`;
  const p = url.split(/[?#]/)[0];
  if (!p) return null;
  const target = path.posix.normalize(path.posix.join(base, p)).replace(/\/+$/, '') + (p.endsWith('/') ? '/' : '');
  if (target.startsWith('../')) return `link "${url}" leaves the published book`;
  if (target === './' || target === '.' || target === 'index.html') return null; // book landing page
  if (target === 'viz/' || target === 'viz' || target === 'viz/index.html') return null; // the hub
  if (target.startsWith('viz/assets/')) {
    const name = target.slice('viz/assets/'.length);
    if (name === 'tokens.css') return null;
    if ((RUNTIME_FILES.includes(name) || name.startsWith('vendor/')) && fs.existsSync(path.join(THEME_VIZ, name))) return null;
    return `link "${url}" names ${target}, which is not part of the shared runtime theme/viz/`;
  }
  if (target.startsWith('viz/')) {
    const [id] = target.slice(4).split('/');
    if (ids && !ids.has(id)) return `link "${url}" points to ${id}, which is not registered`;
    let file = path.join(vizDir(book), target.slice(4));
    if (target.endsWith('/')) file = path.join(file, 'index.html');
    return fs.existsSync(file) ? null : `link "${url}" does not resolve (${rel(file)})`;
  }
  const chapter = chapterFor(book, target);
  if (chapter) return fs.existsSync(chapter) ? null : `link "${url}" names a chapter that does not exist (${rel(chapter)})`;
  return `link "${url}" resolves to ${target}, which the build does not publish`;
}

/** Fixed waits in a browser suite: [line, …] of each waitForTimeout( call outside comment lines. A suite waits for what
    the page reports (settle for a transition, until for playback), never for a fixed time (skills/book-viz). */
export function fixedWaits(text) {
  const lines = [];
  text.split('\n').forEach((line, k) => {
    const t = line.trim();
    if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return;
    for (const _ of line.matchAll(/\bwaitForTimeout\s*\(/g)) lines.push(k + 1);
  });
  return lines;
}
export const FIXED_WAIT_MESSAGE = (line) => `waitForTimeout(…) at line ${line} waits a fixed time, which passes on a fast machine and fails on a busy runner; `
  + 'wait for what the page reports instead: settle(page) after a click or a transition, until(page, () => …) for playback (skills/book-viz)';

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
/** Green ticks outside the evidence boxes: [{ where: 'index.html' | 'main.js', line }]. Green (.okmark) belongs to a
    Lean-verified statement, inside a .lean box; a number the page checked itself is marked .nummark (neutral). In the
    page, an element with class okmark and no .lean ancestor; in its script, a line that writes okmark unless it names
    (by $('id'), getElementById or querySelector('#id')) an element of the page that sits in a .lean box.
    tools/tbook/viz.py applies the same rule. */
export function okmarksOutsideLean(html, js = '') {
  const out = [], inLean = new Map(), stack = [];
  const lineAt = (i) => html.slice(0, i).split('\n').length;
  const body = html.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' ')).replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, (m) => m.replace(/[^\n]/g, ' '));
  for (const m of body.matchAll(/<(\/?)([a-zA-Z][\w-]*)([^>]*?)(\/?)>/g)) {
    const tag = m[2].toLowerCase();
    if (m[1]) { const k = stack.map((e) => e.tag).lastIndexOf(tag); if (k >= 0) stack.length = k; continue; }
    const cls = (/\bclass\s*=\s*"([^"]*)"/.exec(m[3]) || [, ''])[1].split(/\s+/).filter(Boolean);
    const id = (/\bid\s*=\s*"([^"]*)"/.exec(m[3]) || [])[1];
    const lean = (stack.length && stack[stack.length - 1].lean) || cls.includes('lean');
    if (cls.includes('okmark') && !lean) out.push({ where: 'index.html', line: lineAt(m.index) });
    if (id) inLean.set(id, lean);
    if (!m[4] && !VOID_TAGS.has(tag)) stack.push({ tag, lean });
  }
  js.split('\n').forEach((line, k) => {
    const t = line.trim();
    if (!/\bokmark\b/.test(line) || t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return;
    const ids = [...line.matchAll(/\$\(\s*['"]([\w-]+)['"]\s*\)|getElementById\(\s*['"]([\w-]+)['"]|querySelector(?:All)?\(\s*['"]#([\w-]+)/g)].map((x) => x[1] || x[2] || x[3]);
    if (!ids.some((i) => inLean.get(i))) out.push({ where: 'main.js', line: k + 1 });
  });
  return out;
}
export const OKMARK_MESSAGE = (where, line) => `.okmark (a green ✓) at ${where} line ${line} is outside a .lean box: green belongs to `
  + 'Lean-verified statements; mark a number the page checked itself with .nummark (neutral) (skills/book-viz)';

function scriptsOf(dir, out) {
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir).sort()) {
    const p = path.join(dir, name), st = fs.statSync(p);
    if (st.isDirectory()) { if (!['vendor', 'node_modules'].includes(name)) scriptsOf(p, out); }
    else if (/\.m?js$/.test(name)) out.push(p);
  }
  return out;
}

/** Validate one book. Returns [{ severity, path, message }]. */
export function validateBook(book, { only = GROUPS, lock = readLock() } = {}) {
  const problems = [];
  const on = (g) => only.includes(g);
  const vdir = vizDir(book), regFile = registryPath(book);
  const err = (file, message) => problems.push({ severity: 'error', path: rel(file), message });
  const warn = (file, message) => problems.push({ severity: 'warning', path: rel(file), message });

  if (on('scripts')) {
    const files = [...scriptsOf(vdir, []), ...scriptsOf(THEME_VIZ, []), ...scriptsOf(TEMPLATES, [])];
    for (const f of files) {
      try { execFileSync(process.execPath, ['--check', f], { stdio: 'pipe' }); }
      catch (e) { err(f, `JavaScript does not parse: ${String(e.stderr || e.message).trim().split('\n').slice(0, 5).join(' | ')}`); }
    }
  }
  if (!fs.existsSync(vdir)) return problems;
  const structural = only.some((g) => g !== 'scripts');
  if (!structural) return problems;
  if (!fs.existsSync(regFile)) { err(vdir, 'viz/ exists but has no visualizations.json registry (create one with ./tbook viz new)'); return problems; }
  let reg;
  try { reg = JSON.parse(fs.readFileSync(regFile, 'utf8')); } catch (e) { err(regFile, `not valid JSON: ${e.message}`); return problems; }
  if (on('registry')) {
    if (reg.version !== 1) err(regFile, 'version must be 1');
    if (!Array.isArray(reg.visualizations)) err(regFile, 'visualizations must be an array');
  }
  const entries = Array.isArray(reg.visualizations) ? reg.visualizations : [];
  const ids = new Set(entries.map((v) => v && v.id).filter(Boolean));
  const seen = new Set();
  for (const [i, v] of entries.entries()) {
    if (!v || typeof v !== 'object') { if (on('registry')) err(regFile, `visualizations[${i}] must be an object`); continue; }
    const at = `visualizations[${i}]${v.id ? ` (${v.id})` : ''}`;
    const live = v.status === 'live';
    if (on('registry')) {
      for (const key of ['id', 'code', 'title', 'path', 'thumbnail', 'status', 'added']) if (!nonEmpty(v[key])) err(regFile, `${at}: missing string field "${key}"`);
      if (!ID_RE.test(v.id || '') || RESERVED.includes(v.id)) err(regFile, `${at}: id must be kebab-case and not ${RESERVED.join(' or ')}`);
      if (seen.has(v.id)) err(regFile, `${at}: duplicate id`);
      if (v.path !== `${v.id}/`) err(regFile, `${at}: path must be "${v.id}/"`);
      if (nonEmpty(v.thumbnail) && (!v.thumbnail.startsWith(`${v.id}/`) || !THUMB_EXT.test(v.thumbnail))) err(regFile, `${at}: thumbnail must be an image in ${v.id}/ (normally "${v.id}/thumb.jpg")`);
      if (!STATUSES.includes(v.status)) err(regFile, `${at}: status must be one of ${STATUSES.join(', ')}`);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(v.added || '')) err(regFile, `${at}: added must be YYYY-MM-DD`);
      if (live) {
        for (const key of ['title_en', 'summary', 'summary_en']) if (!nonEmpty(v[key])) err(regFile, `${at}: a live entry needs "${key}"`);
        if (!Array.isArray(v.theory) || !v.theory.length) err(regFile, `${at}: a live entry names at least one theory reference`);
      }
      for (const key of ['tags', 'tags_en']) if (v[key] !== undefined && (!Array.isArray(v[key]) || v[key].some((t) => !nonEmpty(t)))) err(regFile, `${at}: ${key} must be a list of strings`);
      if (live && Array.isArray(v.tags) && v.tags.length && (!Array.isArray(v.tags_en) || v.tags_en.length !== v.tags.length)) err(regFile, `${at}: tags_en must translate every tag`);
      if (v.theory !== undefined && !Array.isArray(v.theory)) err(regFile, `${at}: theory must be a list`);
      for (const [k, t] of (Array.isArray(v.theory) ? v.theory : []).entries()) {
        if (!t || !nonEmpty(t.label) || !nonEmpty(t.href)) { err(regFile, `${at}: theory[${k}] needs a label and an href`); continue; }
        if (live && !nonEmpty(t.label_en)) err(regFile, `${at}: theory reference "${t.label}" needs label_en`);
        for (const key of ['href', 'href_en']) {
          if (t[key] === undefined) continue;
          if (/^https?:/.test(t[key]) && !isHttps(t[key])) err(regFile, `${at}: theory[${k}].${key} must use https`);
          const problem = on('links') ? linkProblem(book, 'viz/', t[key], ids) : null;
          if (problem) err(regFile, `${at}: theory[${k}].${key}: ${problem}`);
        }
      }
    }
    if (v.lean !== undefined && !Array.isArray(v.lean)) { if (on('registry')) err(regFile, `${at}: lean must be a list of {gid, label?}`); }
    else for (const [k, ref] of (v.lean || []).entries()) {
      if (!ref || !nonEmpty(ref.gid)) { if (on('registry')) err(regFile, `${at}: lean[${k}] needs a "gid" (e.g. D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)`); continue; }
      if (ref.label !== undefined && !nonEmpty(ref.label) && on('registry')) err(regFile, `${at}: lean[${k}].label must be a non-empty string when given`);
      if (!on('lean')) continue;
      if (!parseGid(ref.gid)) err(regFile, `${at}: lean[${k}]: not a declaration GID: ${ref.gid}`);
      else if (!lock) err(regFile, `${at}: lean[${k}]: ${ref.gid} cannot be linked: trureturing.lock.json is missing (run ./tbook pin)`);
      else if (!(lock.declarations || {})[ref.gid]) err(regFile, `${at}: lean[${k}]: ${ref.gid} is not in trureturing.lock.json; cite it in a chapter and run ./tbook pin --refresh${unhideHint(book.slug)}`);
      else if (!FORMAL_KINDS.includes(lock.declarations[ref.gid].kind)) err(regFile, `${at}: lean[${k}]: ${ref.gid} is a Lean ${lock.declarations[ref.gid].kind}, not a theorem; lean lists the theorems the visualization cites (shown as LEAN ✓)`);
    }
    seen.add(v.id);
    if (!ID_RE.test(v.id || '')) continue;
    const dir = path.join(vdir, v.id), page = path.join(dir, 'index.html');
    if (on('thumbs') && live && nonEmpty(v.thumbnail) && !fs.existsSync(path.join(vdir, v.thumbnail))) {
      err(path.join(vdir, v.thumbnail), `${at}: thumbnail does not exist (run node tools/node/viz-thumbs.mjs ${book.slug} ${v.id})`);
    }
    if (on('tests') && live && !fs.existsSync(path.join(vdir, 'tests', `${v.id}.test.mjs`))) {
      warn(path.join(vdir, 'tests'), `${at}: a live visualization should have a browser test tests/${v.id}.test.mjs`);
    }
    if (!(on('pages') || on('links') || on('lean'))) continue;
    if (!fs.existsSync(page)) { if (on('pages')) err(page, `${at}: page does not exist`); continue; }
    const html = fs.readFileSync(page, 'utf8');
    if (on('pages')) {
      const need = [
        [`data-viz-id="${v.id}"`, 'body carries data-viz-id'],
        ['href="../assets/theme.css"', 'loads the shared theme'],
        ['class="crumb" href="../"', 'links back to the visualization index'],
        ['<title>', 'has a <title>'],
        ['data-title-en="', 'gives an English title on <html>'],
        ['data-lang-set="zh"', 'offers the Chinese switch'],
        ['data-lang-set="en"', 'offers the English switch']
      ];
      for (const [needle, why] of need) if (!html.includes(needle)) err(page, `${why} (expected ${needle})`);
      const head = html.slice(0, Math.max(0, html.indexOf('</head>')));
      if (!head.includes('src="../assets/shell.js"')) err(page, 'loads the shared runtime in <head> (expected src="../assets/shell.js" before </head>)');
      const zh = classCount(html, 'zh'), en = classCount(html, 'en');
      if (zh !== en) err(page, `${zh} .zh fragments but ${en} .en fragments; every text fragment needs both languages`);
    }
    if (on('lean')) {
      const js = path.join(dir, 'main.js');
      for (const o of okmarksOutsideLean(html, fs.existsSync(js) ? fs.readFileSync(js, 'utf8') : '')) warn(o.where === 'main.js' ? js : page, OKMARK_MESSAGE(o.where, o.line));
      for (const r of pinnedRefs(html)) {
        if (r.kind === 'gid') {
          if (!parseGid(r.value)) err(page, `data-lean-gid="${r.value}" is not a declaration GID`);
          else if (lock && !(lock.declarations || {})[r.value]) err(page, `data-lean-gid="${r.value}" is not in trureturing.lock.json; cite it in a chapter and run ./tbook pin --refresh${unhideHint(book.slug)}`);
          else if (lock && !FORMAL_KINDS.includes(lock.declarations[r.value].kind)) err(page, `data-lean-gid="${r.value}" names a Lean ${lock.declarations[r.value].kind}, not a theorem; data-lean-gid cites verified theorems (LEAN ✓); link a definition with data-trureturing-path="<module>.lean"`);
        } else if (!r.value || r.value.includes('..') || r.value.startsWith('/')) err(page, `data-trureturing-path="${r.value}" must be a repository-relative path`);
      }
    }
    if (on('links')) {
      for (const m of html.matchAll(/\s(?:src|href)="([^"]+)"/g)) {
        const problem = linkProblem(book, `viz/${v.id}/`, m[1], ids);
        if (problem) err(page, problem);
      }
    }
  }
  if (on('dirs')) {
    for (const name of fs.readdirSync(vdir).sort()) {
      const p = path.join(vdir, name);
      if (!fs.statSync(p).isDirectory() || RESERVED.includes(name)) continue;
      if (!seen.has(name)) err(p, `viz/${name}/ is not registered in visualizations.json`);
    }
    const tdir = path.join(vdir, 'tests');
    if (fs.existsSync(tdir)) for (const f of fs.readdirSync(tdir).sort()) {
      const m = /^(.+)\.test\.mjs$/.exec(f);
      if (m && !seen.has(m[1])) warn(path.join(tdir, f), `tests/${f} belongs to no registered visualization`);
    }
  }
  if (on('tests')) {
    const tdir = path.join(vdir, 'tests');
    if (fs.existsSync(tdir)) for (const f of fs.readdirSync(tdir).sort()) {
      if (!f.endsWith('.test.mjs')) continue;
      for (const line of fixedWaits(fs.readFileSync(path.join(tdir, f), 'utf8'))) warn(path.join(tdir, f), FIXED_WAIT_MESSAGE(line));
    }
  }
  return problems;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  const json = args.includes('--json');
  const onlyArg = args.find((a) => a.startsWith('--only='));
  const only = onlyArg ? onlyArg.slice(7).split(',').filter(Boolean) : GROUPS;
  const bad = only.filter((g) => !GROUPS.includes(g));
  if (bad.length) { console.error(`unknown group(s) ${bad.join(', ')}; groups: ${GROUPS.join(', ')}`); process.exit(2); }
  let books;
  try { books = args.filter((a) => !a.startsWith('--')).map(resolveBook); } catch (e) { console.error(e.message); process.exit(2); }
  if (!books.length) books = listBooks();
  const lock = readLock();
  const problems = [];
  let entries = 0, live = 0;
  const reported = new Set();
  for (const book of books) {
    for (const p of validateBook(book, { only, lock })) {
      // the shared runtime and templates are checked with every book; report each problem once
      const key = `${p.path}\n${p.message}`;
      if (reported.has(key)) continue;
      reported.add(key);
      problems.push(p);
    }
    if (fs.existsSync(registryPath(book))) {
      try { const r = JSON.parse(fs.readFileSync(registryPath(book), 'utf8')); entries += (r.visualizations || []).length; live += (r.visualizations || []).filter((v) => v.status === 'live').length; } catch { /* reported */ }
    }
  }
  const errors = problems.filter((p) => p.severity === 'error');
  if (json) process.stdout.write(JSON.stringify(problems, null, 2) + '\n');
  else {
    for (const p of problems) console.error(`${p.severity === 'error' ? 'ERROR  ' : 'WARNING'} ${p.path}: ${p.message}`);
    console.log(`viz-validate: ${books.length} book(s) · ${entries} registered (${live} live) · ${errors.length} error(s), ${problems.length - errors.length} warning(s)`);
  }
  process.exit(errors.length ? 1 : 0);
}
