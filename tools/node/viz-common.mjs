// Shared facts about book-local visualizations, used by the other tools/node/viz-*.mjs scripts.
// Adapted from trureturing-visualize/scripts/site.mjs (Apache-2.0, the-omega-institute).
//
// Source layout (per book)                      Published layout (tbook.viz.build)
//   books/<slug>/viz/visualizations.json          _site/<slug>/viz/visualizations.json (live entries, links resolved)
//   books/<slug>/viz/<id>/{index.html,…}          _site/<slug>/viz/<id>/…
//   books/<slug>/viz/tests/<id>.test.mjs          (not published)
//   theme/viz/{theme.css,shell.js,…}              _site/<slug>/viz/assets/…  (+ tokens.css from theme/generated/)
//                                                 _site/<slug>/viz/index.html (the hub of the book's live entries)
// Pages reference the runtime as ../assets/… and the hub as ../ (relative links only).
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { bookDirs, hiddenBy, hiddenError, hidePatterns } from './slides-lib.mjs';

export const ROOT = path.resolve(process.env.TBOOK_ROOT || path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..'));
export const BOOKS = path.join(ROOT, 'books');
export const THEME_VIZ = path.join(ROOT, 'theme', 'viz');
export const TOKENS_CSS = path.join(ROOT, 'theme', 'generated', 'tokens.css');
export const TOKENS_JSON = path.join(ROOT, 'theme', 'tokens.json');
export const TEMPLATES = path.join(ROOT, 'templates', 'viz');
export const LOCK_FILE = path.join(ROOT, 'trureturing.lock.json');
export const ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const STATUSES = ['live', 'draft'];
/** Lean kinds that may be cited as verified results (LEAN ✓); same as tbook.lean.FORMAL_KINDS. */
export const FORMAL_KINDS = ['theorem'];
/** Directory names inside books/<slug>/viz/ that are not visualizations. */
export const RESERVED = ['tests', 'assets'];
/** Files of theme/viz/ published into <slug>/viz/assets/ (hub.html is a template, not an asset). */
export const RUNTIME_FILES = ['theme.css', 'shell.js', 'kit.js', 'solid-core.js', 'hub.css', 'hub.js', 'favicon.svg'];
export const EXTERNAL_PREFIX = 'trureturing-visualize:';
export const EXTERNAL_BASE = 'https://the-omega-institute.github.io/trureturing-visualize/viz/';
const GID_RE = /^(D[0-9]+\/S[0-9]+\/(?:[A-Za-z_][A-Za-z0-9_]*\/)*[A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)$/;

export const rel = (p) => path.relative(ROOT, p).split(path.sep).join('/') || '.';

/** Every book of the repository that site.toml [books].hide does not hide: [{ slug, dir }], sorted by slug. */
export function listBooks() {
  const hide = hidePatterns(ROOT);
  return bookDirs(ROOT).filter((slug) => !hiddenBy(slug, hide)).map((slug) => ({ slug, dir: path.join(BOOKS, slug) }));
}

/** Whether books/<slug>/ is a book that site.toml [books].hide does not hide. */
export function isBook(slug) {
  return fs.existsSync(path.join(BOOKS, slug, 'book.toml')) && !hiddenBy(slug, hidePatterns(ROOT));
}

/** A book from a slug or a directory path; throws with a helpful message. A slug of a book that site.toml
 * [books].hide hides is an error, as in tools/tbook/config.py named_book; a directory path is not a name and
 * loads any book. */
export function resolveBook(arg) {
  if (!arg.includes('/') && !arg.includes(path.sep)) {
    const hide = hidePatterns(ROOT);
    if (hiddenBy(arg, hide) && bookDirs(ROOT).includes(arg)) throw hiddenError([arg], hide);
  }
  const cands = [path.resolve(arg), path.join(BOOKS, arg)];
  for (const dir of cands) if (fs.existsSync(path.join(dir, 'book.toml'))) return { slug: path.basename(dir), dir };
  const known = listBooks().map((b) => b.slug).join(', ') || 'none';
  throw new Error(`no book "${arg}" (expected a slug under books/ or a directory with book.toml; known: ${known})`);
}

export const vizDir = (book) => path.join(book.dir, 'viz');
export const registryPath = (book) => path.join(vizDir(book), 'visualizations.json');

export function readRegistry(book) {
  return JSON.parse(fs.readFileSync(registryPath(book), 'utf8'));
}
export function writeRegistry(book, reg) {
  fs.mkdirSync(vizDir(book), { recursive: true });
  fs.writeFileSync(registryPath(book), JSON.stringify(reg, null, 2) + '\n');
}

/** trureturing.lock.json, or null when it does not exist. */
export function readLock() {
  if (!fs.existsSync(LOCK_FILE)) return null;
  return JSON.parse(fs.readFileSync(LOCK_FILE, 'utf8'));
}

export function parseGid(gid) {
  const m = GID_RE.exec(String(gid || '').trim());
  return m ? { module: m[1], name: m[2] } : null;
}

/** Permalink of a declaration's Lean source at the pinned commit (same as tbook.lean.Lock.source_url). */
export function leanUrl(lock, gid) {
  const g = parseGid(gid);
  if (!lock || !g) return '';
  const d = (lock.declarations || {})[gid];
  const line = d && d.line ? `#L${d.line}` : '';
  return `https://github.com/${lock.repo}/blob/${lock.commit}/${g.module}.lean${line}`;
}
/** Permalink of any path of the trureturing repository at the pinned commit. */
export function trureturingUrl(lock, p) {
  return lock ? `https://github.com/${lock.repo}/blob/${lock.commit}/${String(p).replace(/^\/+/, '')}` : '';
}
/** Short Lean name of a locked declaration (`deficit_three_valued`). */
export function leanShortName(lock, gid) {
  const d = lock && (lock.declarations || {})[gid];
  const full = d ? d.name : (parseGid(gid) || {}).name || gid;
  return String(full).split('.').pop();
}

const TAG_RE = /<a\b[^>]*>/g;
const ATTR = (name) => new RegExp(`\\s${name}="([^"]*)"`);
/** Every `<a data-lean-gid="…">` / `<a data-trureturing-path="…">` of a page: [{ kind, value }]. */
export function pinnedRefs(html) {
  const out = [];
  for (const m of html.matchAll(TAG_RE)) {
    const g = ATTR('data-lean-gid').exec(m[0]);
    if (g) out.push({ kind: 'gid', value: g[1] });
    const p = ATTR('data-trureturing-path').exec(m[0]);
    if (p) out.push({ kind: 'path', value: p[1] });
  }
  return out;
}
/** Point `<a data-lean-gid>` / `<a data-trureturing-path>` links at the pinned commit (mirrors tbook.viz.pin_links). */
export function pinLinks(html, lock) {
  if (!lock) return html;
  return html.replace(TAG_RE, (tag) => {
    const g = ATTR('data-lean-gid').exec(tag), p = ATTR('data-trureturing-path').exec(tag);
    const url = g ? leanUrl(lock, g[1]) : p ? trureturingUrl(lock, p[1]) : '';
    if (!url) return tag;
    const safe = url.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    return ATTR('href').test(tag) ? tag.replace(ATTR('href'), ` href="${safe}"`) : tag.replace(/^<a\b/, `<a href="${safe}"`);
  });
}

/** `{trureturing}/path` in registry theory links → the path at the pinned commit. */
export function resolveHref(href, lock) {
  if (typeof href === 'string' && href.startsWith('{trureturing}/')) return trureturingUrl(lock, href.slice('{trureturing}/'.length));
  return href;
}

/* ---------- chapter citations: `::: {.viz src="<id>" preset="<card>" height="<px>"}` ---------- */
// The chapters are read by the book tools themselves (tbook.viz.citations over tbook.model.load_edition), so the cards
// that the quality gate opens and that viz-thumbs.mjs captures (and keeps) are the ones the published book cites: the
// same editions, SUMMARY selection, Markdown grammar, kind and attributes. The interpreter is chosen as ./tbook does.
const CODE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const CITATIONS_PY = 'import json, sys\nfrom tbook import config, viz\n'
  + 'json.dump(viz.citations(config.load_book(sys.argv[1]), sys.argv[2]), sys.stdout)\n';
function tbookPython() {
  if (process.env.TBOOK_PYTHON) return process.env.TBOOK_PYTHON;
  const venv = path.join(CODE_ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : 'python3';
}
/** Every embed of `vizId` in the published chapters of `book`, as `./tbook build` reads them (tbook.viz.citations):
    [{ lang, preset, height }] by edition (book.toml order), SUMMARY.md chapter and position; preset is null for the
    whole lab, height is the frame height in pixels. Throws when the book tools cannot run or cannot read the book. */
export function vizCitations(book, vizId) {
  const py = tbookPython();
  const pythonPath = [path.join(CODE_ROOT, 'tools'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  const r = spawnSync(py, ['-c', CITATIONS_PY, book.dir, vizId], {
    cwd: ROOT, encoding: 'utf8', maxBuffer: 1 << 26, env: { ...process.env, PYTHONPATH: pythonPath, TBOOK_ROOT: ROOT }
  });
  const why = r.error ? r.error.message : r.status !== 0 ? (r.stderr || `exit ${r.status ?? r.signal}`).trim() : '';
  const fail = (detail) => new Error(`cannot read the citations of viz "${vizId}" in ${rel(book.dir)} with ${py} (tbook.viz.citations): ${detail}`);
  if (why) throw fail(why);
  try { return JSON.parse(r.stdout); } catch (e) { throw fail(`unreadable output (${e.message})`); }
}
/** The cards of `vizId` that the chapters of `book` cite: [{ preset, lang }], one per card and language. */
export function citedCards(book, vizId) {
  const out = new Map();
  for (const { preset, lang } of vizCitations(book, vizId)) if (preset) out.set(`${preset}.${lang}`, { preset, lang });
  return [...out.values()];
}

/** theme/viz/favicon.svg with its @@colour@@ placeholders filled from the screen palette. */
export function favicon() {
  const tokens = JSON.parse(fs.readFileSync(TOKENS_JSON, 'utf8'));
  return fs.readFileSync(path.join(THEME_VIZ, 'favicon.svg'), 'utf8').replace(/@@([a-z-]+)@@/g, (m, k) => tokens.screen[k] || m);
}

/* ---------- local fonts: serve @fontsource files in place of Google Fonts (tests and thumbnails run offline) ---------- */
const FONT_SETS = [
  ['chakra-petch', ['400', '500', '600', '700']],
  ['jetbrains-mono', ['400', '600']],
  ['noto-sans-sc', ['400', '500', '700']]
];
export const FONTSOURCE = path.join(ROOT, 'node_modules', '@fontsource');
/** CSS equivalent to the pages' Google Fonts link, with url()s under `prefix` (e.g. "/__fonts/"). */
export function localFontsCss(prefix) {
  const parts = [];
  for (const [pkg, weights] of FONT_SETS) {
    for (const w of weights) {
      const f = path.join(FONTSOURCE, pkg, `${w}.css`);
      if (!fs.existsSync(f)) continue;
      parts.push(fs.readFileSync(f, 'utf8').replace(/url\(\.\/files\//g, `url(${prefix}${pkg}/files/`));
    }
  }
  return parts.join('\n');
}

/* ---------- Chromium (Playwright) ---------- */
/** Launch options: PW_CHROMIUM_PATH overrides Playwright's own browser download. */
export function chromiumOptions(extraArgs = []) {
  const opts = { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', ...extraArgs] };
  if (process.env.PW_CHROMIUM_PATH) opts.executablePath = process.env.PW_CHROMIUM_PATH;
  return opts;
}
export async function loadChromium() {
  try { return (await import('playwright-chromium')).chromium; } catch { /* try the full package */ }
  try { return (await import('playwright')).chromium; } catch { /* fall through */ }
  throw new Error('Playwright is not installed: run `npm ci` at the repository root (playwright-chromium is a devDependency)');
}
