// Shared helpers for the slide-deck scripts (slides-check, slides-build, slides-new) and the
// Slidev theme's Vite plugin (theme/slides/setup/vite-plugins.ts).
//
// Layout (docs/ARCHITECTURE.md §2), the same as tools/tbook/slides.py:
//   books/<slug>/slides/<deck>/slides.md         the book's first language (book.toml editions[0], zh by default)
//   books/<slug>/slides/<deck>/slides.<lang>.md  every other edition language of the book (e.g. slides.en.md)
// slides.<first language>.md is not an edition (slides.md would shadow it; the checks report it).
// Directories whose name starts with "_" or "." are ignored.
//
// Adapted from chrono-company-slides scripts/lib.mjs (Apache-2.0, The Omega Institute / Chrono AI).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

// tools/node/slides-lib.mjs -> repository root (TBOOK_ROOT overrides, as in tools/tbook/paths.py)
export const ROOT = resolve(process.env.TBOOK_ROOT || join(dirname(fileURLToPath(import.meta.url)), '..', '..'));
export const BOOKS = join(ROOT, 'books');
export const THEME_DIR = join(ROOT, 'theme', 'slides');
export const TEMPLATES = join(ROOT, 'templates', 'slides');
export const LOCK_FILE = join(ROOT, 'trureturing.lock.json');
export const PRIMARY_FILE = 'slides.md'; // the edition of the book's first language
export const DECK_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const LANG_RE = /^[a-z]{2,3}(?:-[A-Za-z0-9]+)*$/;
const toPosix = (p) => p.split(sep).join('/');

// --------------------------------------------------------------------------- TOML (subset)
// Enough TOML for site.toml, book.toml and theme/i18n/*.toml: tables, dotted keys, basic and
// literal strings (also multi-line), numbers, booleans, dates (kept as strings), arrays
// (also multi-line) and inline tables. Anything else raises with the line number.

export function parseToml(text, where = 'toml') {
  const root = {};
  let table = root;
  let i = 0;
  const n = text.length;
  let line = 1;
  const fail = (msg) => { throw new Error(`${where}:${line}: ${msg}`); };
  const peek = () => text[i];
  const skipWs = () => { while (i < n && (text[i] === ' ' || text[i] === '\t')) i++; };
  const skipWsNl = () => {
    for (;;) {
      skipWs();
      if (text[i] === '#') { while (i < n && text[i] !== '\n') i++; }
      if (text[i] === '\r') { i++; continue; }
      if (text[i] === '\n') { i++; line++; continue; }
      break;
    }
  };
  const ESC = { b: '\b', t: '\t', n: '\n', f: '\f', r: '\r', '"': '"', '\\': '\\', e: '\x1b' };
  function basicString() {
    const multi = text.startsWith('"""', i);
    i += multi ? 3 : 1;
    if (multi && text[i] === '\n') { i++; line++; }
    let out = '';
    for (;;) {
      if (i >= n) fail('unterminated string');
      const c = text[i];
      if (multi ? text.startsWith('"""', i) && text[i + 3] !== '"' : c === '"') { i += multi ? 3 : 1; return out; }
      if (c === '\n') { if (!multi) fail('newline in string'); line++; }
      if (c === '\\') {
        const d = text[i + 1];
        if (d === 'u' || d === 'U') {
          const len = d === 'u' ? 4 : 8;
          out += String.fromCodePoint(parseInt(text.slice(i + 2, i + 2 + len), 16));
          i += 2 + len;
          continue;
        }
        if (multi && (d === '\n' || d === ' ' || d === '\r')) { // line-ending backslash
          i++;
          while (i < n && /[\s]/.test(text[i])) { if (text[i] === '\n') line++; i++; }
          continue;
        }
        if (!(d in ESC)) fail(`bad escape \\${d}`);
        out += ESC[d];
        i += 2;
        continue;
      }
      out += c;
      i++;
    }
  }
  function literalString() {
    const multi = text.startsWith("'''", i);
    i += multi ? 3 : 1;
    if (multi && text[i] === '\n') { i++; line++; }
    const end = text.indexOf(multi ? "'''" : "'", i);
    if (end < 0) fail('unterminated string');
    const s = text.slice(i, end);
    if (!multi && s.includes('\n')) fail('newline in string');
    line += (s.match(/\n/g) || []).length;
    i = end + (multi ? 3 : 1);
    return s;
  }
  function key() {
    skipWs();
    if (peek() === '"') return basicString();
    if (peek() === "'") return literalString();
    const m = /^[A-Za-z0-9_-]+/.exec(text.slice(i, i + 256));
    if (!m) fail('expected a key');
    i += m[0].length;
    return m[0];
  }
  function dottedKey() {
    const parts = [key()];
    for (;;) {
      skipWs();
      if (peek() !== '.') return parts;
      i++;
      parts.push(key());
    }
  }
  function value() {
    skipWs();
    const c = peek();
    if (c === '"') return basicString();
    if (c === "'") return literalString();
    if (c === '[') {
      i++;
      const arr = [];
      for (;;) {
        skipWsNl();
        if (peek() === ']') { i++; return arr; }
        arr.push(value());
        skipWsNl();
        if (peek() === ',') { i++; continue; }
        if (peek() === ']') { i++; return arr; }
        fail('expected , or ] in array');
      }
    }
    if (c === '{') {
      i++;
      const obj = {};
      skipWs();
      if (peek() === '}') { i++; return obj; }
      for (;;) {
        const k = dottedKey();
        skipWs();
        if (peek() !== '=') fail('expected = in inline table');
        i++;
        setPath(obj, k, value());
        skipWs();
        if (peek() === ',') { i++; continue; }
        if (peek() === '}') { i++; return obj; }
        fail('expected , or } in inline table');
      }
    }
    const m = /^[^\s,\]}#]+(?: [0-9:.+\-Z]+)?/.exec(text.slice(i, i + 128));
    if (!m) fail('expected a value');
    i += m[0].length;
    const raw = m[0];
    if (raw === 'true') return true;
    if (raw === 'false') return false;
    if (/^[+-]?(?:0|[1-9][0-9_]*)$/.test(raw)) return Number(raw.replace(/_/g, ''));
    if (/^[+-]?[0-9_]+(?:\.[0-9_]+)?(?:[eE][+-]?[0-9]+)?$/.test(raw)) return Number(raw.replace(/_/g, ''));
    if (/^\d{4}-\d{2}-\d{2}/.test(raw) || /^\d{2}:\d{2}/.test(raw)) return raw; // dates stay strings
    fail(`unsupported value ${JSON.stringify(raw)}`);
  }
  function setPath(obj, parts, v) {
    let o = obj;
    for (const p of parts.slice(0, -1)) {
      if (o[p] === undefined) o[p] = {};
      if (typeof o[p] !== 'object' || Array.isArray(o[p])) fail(`key ${parts.join('.')} redefined`);
      o = o[p];
    }
    o[parts.at(-1)] = v;
  }
  function tableAt(parts, arrayOfTables) {
    let o = root;
    parts.forEach((p, idx) => {
      const last = idx === parts.length - 1;
      if (last && arrayOfTables) {
        if (o[p] === undefined) o[p] = [];
        if (!Array.isArray(o[p])) fail(`${parts.join('.')} is not an array of tables`);
        o[p].push({});
        o = o[p].at(-1);
        return;
      }
      if (o[p] === undefined) o[p] = {};
      o = Array.isArray(o[p]) ? o[p].at(-1) : o[p];
      if (typeof o !== 'object') fail(`${parts.join('.')} is not a table`);
    });
    return o;
  }
  for (;;) {
    skipWsNl();
    if (i >= n) break;
    if (peek() === '[') {
      const aot = text[i + 1] === '[';
      i += aot ? 2 : 1;
      const parts = dottedKey();
      skipWs();
      if (!text.startsWith(aot ? ']]' : ']', i)) fail('expected ] after table name');
      i += aot ? 2 : 1;
      table = tableAt(parts, aot);
    } else {
      const parts = dottedKey();
      skipWs();
      if (peek() !== '=') fail('expected =');
      i++;
      setPath(table, parts, value());
    }
    skipWs();
    if (peek() === '#') { while (i < n && text[i] !== '\n') i++; }
    if (i < n && text[i] !== '\n' && text[i] !== '\r') fail(`unexpected ${JSON.stringify(text[i])}`);
  }
  return root;
}

export const readToml = (path) => parseToml(readFileSync(path, 'utf8'), toPosix(relative(ROOT, path)) || path);

function deepMerge(base, extra) {
  const out = { ...base };
  for (const [k, v] of Object.entries(extra)) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object' ? deepMerge(out[k], v) : v;
  }
  return out;
}

// --------------------------------------------------------------------------- site, books, i18n, lock

// Strings for `lang`: theme/i18n/<lang>.toml (English when missing) overridden by i18n/<lang>.toml,
// exactly as tbook.config.i18n() does.
export function i18n(lang, root = ROOT) {
  let base = join(root, 'theme', 'i18n', `${lang}.toml`);
  if (!existsSync(base)) base = join(root, 'theme', 'i18n', 'en.toml');
  let table = existsSync(base) ? parseToml(readFileSync(base, 'utf8'), base) : {};
  const local = join(root, 'i18n', `${lang}.toml`);
  if (existsSync(local)) table = deepMerge(table, parseToml(readFileSync(local, 'utf8'), local));
  return table;
}

export const bcp47 = (lang, root = ROOT) => String(i18n(lang, root)?.meta?.bcp47 || lang);

export function loadSite(root = ROOT) {
  const file = join(root, 'site.toml');
  const raw = existsSync(file) ? parseToml(readFileSync(file, 'utf8'), 'site.toml') : {};
  const site = raw.site ?? {};
  let baseUrl = process.env.TBOOK_BASE_URL || site.base_url || '';
  if (baseUrl && !baseUrl.endsWith('/')) baseUrl += '/';
  return { raw, languages: site.languages ?? ['zh', 'en'], baseUrl };
}

const localized = (v) => (v == null ? {} : typeof v === 'string' ? { '*': v } : { ...v });
export const pick = (text, lang, fallback = []) => {
  if (lang in text) return text[lang];
  if ('*' in text) return text['*'];
  for (const l of fallback) if (l in text) return text[l];
  return Object.values(text)[0] ?? '';
};

export function loadBook(slug, root = ROOT) {
  const dir = join(root, 'books', slug);
  const file = join(dir, 'book.toml');
  if (!existsSync(file)) throw new Error(`books/${slug}/book.toml not found`);
  const raw = parseToml(readFileSync(file, 'utf8'), `books/${slug}/book.toml`);
  const meta = raw.book ?? {};
  const languages = meta.editions?.length ? meta.editions : loadSite(root).languages;
  return {
    slug,
    dir,
    slidesDir: join(dir, 'slides'),
    version: String(meta.version ?? '0.1.0'),
    code: String(meta.code ?? slug.toUpperCase().replace('-', '//')),
    title: localized(meta.title),
    languages,
  };
}

// --------------------------------------------------------------------------- books and [books].hide
// site.toml [books].hide lists glob patterns of books that every command and output treats as absent (they
// stay in books/, so merging template changes never conflicts over deleted example books). The same rules as
// tools/tbook/config.py (hide_patterns, book_slugs, hidden_books, hidden_error, load_book): a pattern matches
// the slug as Python's fnmatch.fnmatchcase does (*, ?, [seq], [!seq], case-sensitive); listings skip hidden
// books, naming one explicitly is an error. tools/tests/test_hide.py compares the two implementations.

const fnmatchCache = new Map();
const REGEXP_SPECIAL = /[\\^$.*+?()[\]{}|/]/g;

// Python's fnmatch.translate (3.12, 3.13) as a JavaScript RegExp: an unclosed [ is literal, a ] right after
// [ or [! belongs to the set, a set's reversed range (z-a) matches nothing, backslashes are literal.
function fnmatchRegExp(pat) {
  const STAR = {};
  const res = [];
  const n = pat.length;
  let i = 0;
  while (i < n) {
    const c = pat[i++];
    if (c === '*') {
      if (res.at(-1) !== STAR) res.push(STAR);
    } else if (c === '?') {
      res.push('.');
    } else if (c === '[') {
      let j = i;
      if (j < n && pat[j] === '!') j++;
      if (j < n && pat[j] === ']') j++;
      while (j < n && pat[j] !== ']') j++;
      if (j >= n) {
        res.push('\\[');
        continue;
      }
      let stuff = pat.slice(i, j);
      if (!stuff.includes('-')) {
        stuff = stuff.replaceAll('\\', '\\\\');
      } else {
        const chunks = [];
        let k = pat[i] === '!' ? i + 2 : i + 1;
        for (;;) {
          k = pat.indexOf('-', k);
          if (k < 0 || k >= j) break;
          chunks.push(pat.slice(i, k));
          i = k + 1;
          k += 3;
        }
        const chunk = pat.slice(i, j);
        if (chunk) chunks.push(chunk);
        else chunks[chunks.length - 1] += '-';
        for (let m = chunks.length - 1; m > 0; m--) { // drop empty (reversed) ranges
          if (chunks[m - 1].at(-1) > chunks[m][0]) {
            chunks[m - 1] = chunks[m - 1].slice(0, -1) + chunks[m].slice(1);
            chunks.splice(m, 1);
          }
        }
        stuff = chunks.map((x) => x.replaceAll('\\', '\\\\').replaceAll('-', '\\-')).join('-');
      }
      i = j + 1;
      if (!stuff) {
        res.push('(?!)'); // empty range: never matches
      } else if (stuff === '!') {
        res.push('.'); // negated empty range: any character
      } else {
        if (stuff[0] === '!') stuff = `^${stuff.slice(1)}`;
        else if (stuff[0] === '^' || stuff[0] === '[') stuff = `\\${stuff}`;
        res.push(`[${stuff.replaceAll(']', '\\]')}]`); // a ] only leads a set; JavaScript needs it escaped
      }
    } else {
      res.push(c.replace(REGEXP_SPECIAL, '\\$&'));
    }
  }
  return new RegExp(`^(?:${res.map((x) => (x === STAR ? '.*' : x)).join('')})$`, 's');
}

/** Python's fnmatch.fnmatchcase(name, pattern). */
export function fnmatchcase(name, pattern) {
  let re = fnmatchCache.get(pattern);
  if (!re) fnmatchCache.set(pattern, (re = fnmatchRegExp(pattern)));
  return re.test(name);
}

/** site.toml [books].hide, validated as tools/tbook/config.py hide_patterns validates it ([] when unset). */
export function hidePatterns(root = ROOT) {
  const books = loadSite(root).raw.books ?? {};
  if (typeof books !== 'object' || Array.isArray(books)) throw new Error('site.toml: books must be a table ([books])');
  const hide = books.hide;
  if (hide === undefined) return [];
  if (!Array.isArray(hide)) {
    throw new Error(`site.toml: [books].hide must be a list of glob patterns, e.g. hide = ["example-*"]; got ${JSON.stringify(hide)}`);
  }
  for (const item of hide) {
    if (typeof item !== 'string' || !item) {
      throw new Error(`site.toml: [books].hide entries must be non-empty strings (glob patterns such as "example-*"); got ${JSON.stringify(item)}`);
    }
  }
  return [...hide];
}

/** The first of `patterns` that hides the book `slug`, or '' when it is visible. */
export const hiddenBy = (slug, patterns) => patterns.find((p) => fnmatchcase(slug, p)) ?? '';

/** The error for naming hidden books explicitly (the same text as tools/tbook/config.py hidden_error). */
export function hiddenError(slugs, patterns) {
  const pats = [...new Set(slugs.map((s) => hiddenBy(s, patterns)))];
  const one = slugs.length === 1;
  const err = new Error(`book${one ? '' : 's'} ${slugs.join(', ')} ${one ? 'is' : 'are'} hidden by site.toml [books].hide `
    + `(${pats.map((p) => JSON.stringify(p)).join(', ')}); to use ${one ? 'it' : 'them'}, remove `
    + `${pats.length === 1 ? 'that pattern' : 'those patterns'} from hide, then run ./tbook pin --refresh `
    + '(the lock file keeps only the declarations that visible books cite)');
  err.hidden = slugs;
  return err;
}

/** For a "not in trureturing.lock.json" message about a book read by path: when site.toml [books].hide hides
 *  `slug`, why ./tbook pin --refresh cannot help yet; '' otherwise (the same text as tools/tbook/config.py). */
export function unhideHint(slug, root = ROOT) {
  let pattern = '';
  try { pattern = hiddenBy(slug, hidePatterns(root)); } catch { return ''; }
  if (!pattern) return '';
  return ` (book ${slug} is hidden by site.toml [books].hide ${JSON.stringify(pattern)}: remove that pattern `
    + 'from hide first, since ./tbook pin --refresh collects the citations of visible books only)';
}

/** Slugs of every directory of books/ with a book.toml, hidden ones included, sorted. */
export function bookDirs(root = ROOT) {
  const dir = join(root, 'books');
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((n) => existsSync(join(dir, n, 'book.toml'))).sort();
}

/** Slugs of the books that site.toml [books].hide hides, sorted. */
export function hiddenBooks(root = ROOT) {
  const hide = hidePatterns(root);
  return bookDirs(root).filter((s) => hiddenBy(s, hide));
}

/** Every book that site.toml [books].hide does not hide, sorted by slug. */
export function listBooks(root = ROOT) {
  const hide = hidePatterns(root);
  return bookDirs(root).filter((s) => !hiddenBy(s, hide)).map((n) => loadBook(n, root));
}

/** The book a command was given by slug (tools/tbook/config.py named_book): loadBook, but a hidden book is an
 * error. loadBook itself loads any book, hidden or not. */
export function namedBook(slug, root = ROOT) {
  if (hiddenBooks(root).includes(slug)) throw hiddenError([slug], hidePatterns(root));
  return loadBook(slug, root);
}

export function loadLock(root = ROOT) {
  const file = join(root, 'trureturing.lock.json');
  if (!existsSync(file)) return null;
  return JSON.parse(readFileSync(file, 'utf8'));
}

// Source permalink of a locked declaration at the pinned commit (same as tbook.lean.Lock.source_url).
export function leanSourceUrl(lock, gid) {
  if (!lock) return '';
  const module = gid.slice(0, gid.indexOf('.')) || gid;
  const line = lock.declarations?.[gid]?.line;
  return `https://github.com/${lock.repo}/blob/${lock.commit}/${module}.lean${line ? `#L${line}` : ''}`;
}

export const GID_RE = /^D[0-9]+\/S[0-9]+\/(?:[A-Za-z_][A-Za-z0-9_]*\/)*[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$/;

// --------------------------------------------------------------------------- decks

// `book` is anything with `languages` (the book's edition languages, the first one owning slides.md).
export const primaryLang = (book) => book.languages[0];
export const editionFile = (book, lang) => (lang === primaryLang(book) ? PRIMARY_FILE : `slides.${lang}.md`);
// The edition language of a deck file, or null when it is not an edition (slides.<first language>.md is not).
export function langOfFile(book, name) {
  if (name === PRIMARY_FILE) return primaryLang(book) ?? null;
  const m = /^slides\.([a-z]{2,3}(?:-[A-Za-z0-9]+)*)\.md$/.exec(name);
  return m && m[1] !== primaryLang(book) ? m[1] : null;
}

// The `theme:` value every deck must use: the relative path from the deck to theme/slides.
export const themeRef = (deckDir, root = ROOT) => toPosix(relative(deckDir, join(root, 'theme', 'slides')));

export function deckNames(book) {
  if (!existsSync(book.slidesDir)) return [];
  return readdirSync(book.slidesDir)
    .filter((n) => !/^[_.]/.test(n) && statSync(join(book.slidesDir, n)).isDirectory()
      && !existsSync(join(book.slidesDir, n, 'deck.toml'))) // academic decks are checked/built by tbook.academic
    .sort();
}

// Languages present in a deck directory, the book's own order first.
export function deckLangs(book, deck) {
  const dir = join(book.slidesDir, deck);
  const found = [...new Set(readdirSync(dir).map((n) => langOfFile(book, n)).filter(Boolean))];
  const rank = (l) => (book.languages.includes(l) ? book.languages.indexOf(l) : book.languages.length);
  return found.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

// One language edition of a deck, parsed with Slidev's own parser.
export async function readEdition(book, deck, lang) {
  const { parseSync } = await import('@slidev/parser');
  const dir = join(book.slidesDir, deck);
  const file = join(dir, editionFile(book, lang));
  const md = readFileSync(file, 'utf8');
  const all = parseSync(md, file).slides;
  // Slidev drops slides marked hide/disabled from the presentation and the PDF.
  const slides = all.filter((s) => !(s.frontmatter?.hide || s.frontmatter?.disabled));
  const head = all[0]?.frontmatter ?? {};
  return {
    book: book.slug,
    deck,
    lang,
    dir,
    file,
    rel: toPosix(relative(ROOT, file)),
    md,
    head,
    meta: head.deck ?? {},
    title: String(head.title ?? ''),
    info: String(head.info ?? ''),
    all,
    slides,
    count: slides.length,
  };
}

// --------------------------------------------------------------------------- code in a slide (as Slidev's Markdown)
// Slidev 53 renders a slide with markdown-exit (markdown-it 14) as unplugin-vue-markdown sets it up: HTML on, the
// HTML block rule of @mdit-vue/plugin-component (a Vue component tag such as <v-click> or <LeanBadge> starts an
// HTML block that may interrupt a paragraph, a self-closing one fills just its line), GFM tables, footnotes
// (markdown-it-footnote) and Slidev's own block rules: `<<< file` snippet imports, `::name::` slot markers and
// `$$` math (on in every deck that has a `$$`). A tag inside a code block (fenced, indented or imported) is shown
// as text; every other tag is rendered. codeLines() runs those block rules as markdown-it does (same rule order,
// same lists of rules that may interrupt a paragraph, block quote, list or table, same container offsets) and
// records the lines of the code blocks; it is the same port as code_lines() in tools/tbook/slides.py (keep them
// in step: test_slides compares both with the parser Slidev builds). Not modelled: what a deck adds itself
// (mdc/comark syntax, setup/transformers.ts, Markdown options in vite.config).

const NEWLINE_RE = /\r\n?|\n/; // line ends as markdown-it reads them
const BLOCK_TAGS = 'address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|'
  + 'dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|'
  + 'html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|'
  + 'summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul';
// HTML's inline elements, less Vue's own (template, component, slot, …): any other tag is a component
const INLINE_TAGS = 'a|abbr|acronym|audio|b|bdi|bdo|big|br|button|canvas|cite|code|data|datalist|del|dfn|em|embed|i|'
  + 'iframe|img|input|ins|kbd|label|map|mark|meter|noscript|object|output|picture|progress|q|ruby|s|'
  + 'samp|script|select|small|span|strong|sub|sup|svg|textarea|time|u|tt|var|video|wbr';
const ATTR = '(?:\\s+[a-zA-Z_:@][a-zA-Z0-9:._-]*(?:\\s*=\\s*(?:[^"\'=<>`\\x00-\\x20]+|\'[^\']*\'|"[^"]*"))?)';
const OPEN_TAG = `<[A-Za-z][A-Za-z0-9\\-]*${ATTR}*\\s*\\/?>`;
const CLOSE_TAG = '<\\/[A-Za-z][A-Za-z0-9\\-]*\\s*>';
// HTML blocks: [start, end (null: a blank line), may interrupt a paragraph]. ``` inside one is HTML, not code.
const HTML_BLOCKS = [
  [/^<(?:script|pre|style)(?=\s|>|$)/i, /<\/(?:script|pre|style)>/i, true],
  [/^<!--/, /-->/, true],
  [/^<\?/, /\?>/, true],
  [/^<![A-Z]/, />/, true],
  [/^<!\[CDATA\[/, /\]\]>/, true],
  [new RegExp(`^</?(?:${BLOCK_TAGS})(?=\\s|/?>|$)`, 'i'), null, true],
  [new RegExp(`^</?(?!(?:${INLINE_TAGS})(?![\\w-]))[A-Za-z][A-Za-z0-9\\-]*(?=\\s|/?>|$)`), null, true],
  [new RegExp(`^(?:${OPEN_TAG}|${CLOSE_TAG})\\s*$`), null, false],
];
const COMPONENT = 6; // its tag alone on a line, self-closing or closed on the line, is just that line
const ONE_LINE_TAG = new RegExp(`^(?:<[A-Za-z][A-Za-z0-9\\-]*${ATTR}*\\s*\\/>`
  + `|<([A-Za-z][A-Za-z0-9\\-]*)${ATTR}*\\s*>.*<\\/\\1\\s*>)`);
const SLOT_RE = /^::\s*[\w.\-:]+\s*::\s*$/; // Slidev's ::slot:: line
// Slidev's <<< file import: path, #region, language, {meta}
const SNIPPET_RE = /^<<<[ \t]*(\S.*?)(#[\w-]+)?[ \t]*(?:[ \t](\S+?))?[ \t]*(\{.*)?$/;
const DELIMITER_CELL_RE = /^:?-+:?$/;
const BAD_PROTO_RE = /^(?:vbscript|javascript|file|data):/;
const GOOD_DATA_RE = /^data:image\/(?:gif|png|jpeg|webp);/;
// the named character references that can make a link destination start with one of those schemes
const NAMED_REFS = {
  Tab: '\t', NewLine: '\n', nbsp: '\u00a0', NonBreakingSpace: '\u00a0', ensp: '\u2002', emsp: '\u2003',
  emsp13: '\u2004', emsp14: '\u2005', numsp: '\u2007', puncsp: '\u2008', thinsp: '\u2009', ThinSpace: '\u2009',
  hairsp: '\u200a', VeryThinSpace: '\u200a', MediumSpace: '\u205f', ThickSpace: '\u205f\u200a', colon: ':', semi: ';',
  sol: '/', fjlig: 'fj',
};
const UNESCAPE_RE = new RegExp(String.raw`\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_${'`'}{|}~])|&#([0-9A-Za-z]{1,31});`
  + `|&(${Object.keys(NAMED_REFS).sort((a, b) => b.length - a.length).join('|')});`, 'g');
const NUMERIC_RE = /^(?:[xX]([0-9a-fA-F]{1,8})|([0-9]{1,8}))$/;
const NUMERIC_PREFIX_RE = /^(?:[xX]([0-9a-fA-F]+)|([0-9]+))/;

const space = (c) => c === ' ' || c === '\t';

const validEntity = (c) => !((c >= 0xD800 && c <= 0xDFFF) || (c >= 0xFDD0 && c <= 0xFDEF) || (c & 0xFFFF) === 0xFFFF
  || (c & 0xFFFF) === 0xFFFE || c <= 0x08 || c === 0x0B || (c >= 0x0E && c <= 0x1F) || (c >= 0x7F && c <= 0x9F)
  || c > 0x10FFFF);

// A link destination as markdown-it unescapes it, as far as it can decide whether the link is allowed: backslash
// escapes, numeric character references (&#58;; &#58x; as the entities decoder reads it, any character that cannot
// matter as U+FFFD) and the named references in NAMED_REFS.
const unescape = (s) => s.replace(UNESCAPE_RE, (m, escaped, numeric, named) => {
  if (escaped) return escaped;
  if (named) return NAMED_REFS[named];
  const exact = NUMERIC_RE.exec(numeric);
  if (exact) {
    const c = exact[1] ? parseInt(exact[1], 16) : parseInt(exact[2], 10);
    return validEntity(c) ? String.fromCodePoint(c) : m;
  }
  const lead = NUMERIC_PREFIX_RE.exec(numeric);
  if (!lead) return m;
  const c = lead[1] ? parseInt(lead[1], 16) : parseInt(lead[2], 10);
  const rest = numeric.slice(lead[0].length);
  const bad = c === 0 || (c >= 0x80 && c <= 0x9F) || (c >= 0xD800 && c <= 0xDFFF) || c > 0x10FFFF;
  return (bad ? '\ufffd' : String.fromCodePoint(c)) + (rest ? `${rest};` : '');
});

// A table row's cells: split at | unless escaped (markdown-it's escapedSplit).
function escapedSplit(s) {
  const out = [];
  let cur = '';
  let last = 0;
  let escaped = false;
  for (let pos = 0; pos < s.length; pos++) {
    const c = s[pos];
    if (c === '|') {
      if (!escaped) {
        out.push(cur + s.slice(last, pos));
        cur = '';
        last = pos + 1;
      } else {
        cur += s.slice(last, pos - 1);
        last = pos;
      }
    }
    escaped = c === '\\';
  }
  out.push(cur + s.slice(last));
  if (out.length && out[0] === '') out.shift();
  if (out.length && out.at(-1) === '') out.pop();
  return out;
}

// markdown-it's block state (StateBlock): per line its start (bm), end (em), first non-space (ts), indent in
// columns (sc) and tab offset (bs), as the containers met so far have shifted them.
class Blocks {
  constructor(src) {
    this.src = src;
    this.bm = [];
    this.em = [];
    this.ts = [];
    this.sc = [];
    this.bs = [];
    for (let start = 0; start < src.length;) {
      const nl = src.indexOf('\n', start);
      const end = nl < 0 ? src.length : nl;
      let pos = start;
      let offset = 0;
      while (pos < end && space(src[pos])) {
        offset += src[pos] === '\t' ? 4 - (offset % 4) : 1;
        pos++;
      }
      this.bm.push(start);
      this.em.push(end);
      this.ts.push(pos - start);
      this.sc.push(offset);
      this.bs.push(0);
      start = end + 1;
    }
    this.bm.push(src.length);
    this.em.push(src.length);
    this.ts.push(0);
    this.sc.push(0);
    this.bs.push(0);
    this.lineMax = this.bm.length - 1;
    this.line = 0;
    this.blk = 0; // blkIndent
    this.listIndent = -1;
    this.parent = 'root';
    this.level = 0;
    this.code = new Array(this.lineMax).fill(false);
  }

  at(pos) { return this.src.slice(pos, pos + 1); }

  empty(line) { return line < this.bm.length && this.bm[line] + this.ts[line] >= this.em[line]; }

  skipEmpty(line) {
    while (line < this.lineMax && this.bm[line] + this.ts[line] >= this.em[line]) line++;
    return line;
  }

  skipSpaces(pos) {
    while (pos < this.src.length && space(this.src[pos])) pos++;
    return pos;
  }

  skipChars(pos, c) {
    while (pos < this.src.length && this.src[pos] === c) pos++;
    return pos;
  }

  text(line) { return this.src.slice(this.bm[line] + this.ts[line], this.em[line]); }

  mark(start, end) {
    for (let i = start; i < Math.min(end, this.lineMax); i++) this.code[i] = true;
  }

  interrupts(chain, line, end) { return chain.some((rule) => rule(this, line, end, true)); }

  tokenize(start, end) {
    let line = start;
    while (line < end) {
      this.line = line = this.skipEmpty(line);
      if (line >= end || this.sc[line] < this.blk) break;
      if (this.level >= 100) { // markdown-it's maxNesting
        this.line = end;
        break;
      }
      for (const rule of RULES) if (rule(this, line, end, false)) break;
      line = this.line;
      if (line < end && this.empty(line)) {
        line++;
        this.line = line;
      }
    }
  }
}

function table(s, start, end, silent) {
  if (start + 2 > end) return false;
  let nxt = start + 1;
  if (s.sc[nxt] < s.blk || s.sc[nxt] - s.blk >= 4) return false;
  const pos = s.bm[nxt] + s.ts[nxt];
  const mx = s.em[nxt];
  if (pos >= mx) return false;
  const first = s.src[pos];
  if (!'|-:'.includes(first) || pos + 1 >= mx) return false;
  const second = s.src[pos + 1];
  if ((!'|-:'.includes(second) && !space(second)) || (first === '-' && space(second))) return false;
  for (const c of s.src.slice(pos + 2, mx)) if (!'|-:'.includes(c) && !space(c)) return false;
  const cells = s.text(nxt).split('|');
  let aligns = 0;
  for (let i = 0; i < cells.length; i++) {
    const t = cells[i].trim();
    if (!t) {
      if (i === 0 || i === cells.length - 1) continue;
      return false;
    }
    if (!DELIMITER_CELL_RE.test(t)) return false;
    aligns++;
  }
  const head = s.text(start).trim();
  if (!head.includes('|') || s.sc[start] - s.blk >= 4) return false;
  const columns = escapedSplit(head).length;
  if (columns === 0 || columns !== aligns) return false;
  if (silent) return true;
  const oldParent = s.parent;
  s.parent = 'table';
  let autocompleted = 0;
  for (nxt = start + 2; nxt < end; nxt++) {
    if (s.sc[nxt] < s.blk || s.interrupts(QUOTE_BREAKS, nxt, end)) break;
    const row = s.text(nxt).trim();
    if (!row || s.sc[nxt] - s.blk >= 4) break;
    autocompleted += columns - escapedSplit(row).length;
    if (autocompleted > 65536) break;
  }
  s.parent = oldParent;
  s.line = nxt;
  return true;
}

function code(s, start, end) {
  if (s.sc[start] - s.blk < 4) return false;
  let nxt = start + 1;
  let last = nxt;
  while (nxt < end) {
    if (s.empty(nxt)) nxt++;
    else if (s.sc[nxt] - s.blk >= 4) last = ++nxt;
    else break;
  }
  s.line = last;
  s.mark(start, last);
  return true;
}

function snippet(s, start, end, silent) {
  const m = SNIPPET_RE.exec(s.text(start));
  if (!m) return false;
  if (!silent) {
    s.line = start + 1;
    if (!(m[4] ?? '').includes('{monaco-write}')) s.mark(start, start + 1); // that one is an editor
  }
  return true;
}

function slot(s, start, end, silent) {
  if (s.sc[start] - s.blk > 0 || !SLOT_RE.test(s.text(start))) return false;
  if (!silent) s.line = start + 1;
  return true;
}

function fence(s, start, end, silent) {
  let pos = s.bm[start] + s.ts[start];
  let mx = s.em[start];
  if (s.sc[start] - s.blk >= 4 || pos + 3 > mx) return false;
  const marker = s.src[pos];
  if (marker !== '~' && marker !== '`') return false;
  let mem = pos;
  pos = s.skipChars(pos, marker);
  const size = pos - mem;
  if (size < 3 || (marker === '`' && s.src.slice(pos, mx).includes('`'))) return false;
  if (silent) return true;
  let nxt = start;
  let closed = false;
  for (;;) {
    nxt++;
    if (nxt >= end) break;
    pos = mem = s.bm[nxt] + s.ts[nxt];
    mx = s.em[nxt];
    if (pos < mx && s.sc[nxt] < s.blk) break;
    if (s.at(pos) !== marker || s.sc[nxt] - s.blk >= 4) continue;
    pos = s.skipChars(pos, marker);
    if (pos - mem < size || s.skipSpaces(pos) < mx) continue;
    closed = true;
    break;
  }
  s.line = nxt + (closed ? 1 : 0);
  s.mark(start, s.line);
  return true;
}

function blockquote(s, start, end, silent) {
  let pos = s.bm[start] + s.ts[start];
  if (s.sc[start] - s.blk >= 4 || s.at(pos) !== '>') return false;
  if (silent) return true;
  const oldLineMax = s.lineMax;
  const oldParent = s.parent;
  s.parent = 'blockquote';
  const saved = []; // [bm, bs, sc, ts] of the lines from `start` on
  let lastEmpty = false;
  let nxt = start;
  while (nxt < end) {
    const outdented = s.sc[nxt] < s.blk;
    pos = s.bm[nxt] + s.ts[nxt];
    const mx = s.em[nxt];
    if (pos >= mx) break;
    if (s.src[pos] === '>' && !outdented) {
      pos++;
      let initial = s.sc[nxt] + 1;
      let adjust = false;
      let spaceAfter = false;
      if (s.at(pos) === ' ') {
        pos++;
        initial++;
        spaceAfter = true;
      } else if (s.at(pos) === '\t') {
        spaceAfter = true;
        if ((s.bs[nxt] + initial) % 4 === 3) {
          pos++;
          initial++;
        } else adjust = true;
      }
      let offset = initial;
      saved.push([s.bm[nxt], s.bs[nxt], s.sc[nxt], s.ts[nxt]]);
      s.bm[nxt] = pos;
      while (pos < mx && space(s.src[pos])) {
        offset += s.src[pos] === '\t' ? 4 - ((offset + s.bs[nxt] + (adjust ? 1 : 0)) % 4) : 1;
        pos++;
      }
      lastEmpty = pos >= mx;
      s.bs[nxt] = s.sc[nxt] + 1 + (spaceAfter ? 1 : 0);
      s.sc[nxt] = offset - initial;
      s.ts[nxt] = pos - s.bm[nxt];
      nxt++;
      continue;
    }
    if (lastEmpty) break;
    if (s.interrupts(QUOTE_BREAKS, nxt, end)) {
      s.lineMax = nxt;
      if (s.blk !== 0) {
        saved.push([s.bm[nxt], s.bs[nxt], s.sc[nxt], s.ts[nxt]]);
        s.sc[nxt] -= s.blk;
      }
      break;
    }
    saved.push([s.bm[nxt], s.bs[nxt], s.sc[nxt], s.ts[nxt]]);
    s.sc[nxt] = -1; // a lazy line: text going on with a paragraph
    nxt++;
  }
  const oldIndent = s.blk;
  s.blk = 0;
  s.level++;
  s.tokenize(start, nxt);
  s.level--;
  s.lineMax = oldLineMax;
  s.parent = oldParent;
  saved.forEach(([bm, bs, sc, ts], i) => {
    s.bm[start + i] = bm;
    s.bs[start + i] = bs;
    s.sc[start + i] = sc;
    s.ts[start + i] = ts;
  });
  s.blk = oldIndent;
  return true;
}

function math(s, start, end, silent) {
  let pos = s.bm[start] + s.ts[start];
  let mx = s.em[start];
  if (pos + 2 > mx || s.src.slice(pos, pos + 2) !== '$$') return false;
  if (silent) return true;
  let found = s.src.slice(pos + 2, mx).trim().slice(-2) === '$$';
  let nxt = start;
  while (!found) {
    nxt++;
    if (nxt >= end) break;
    pos = s.bm[nxt] + s.ts[nxt];
    mx = s.em[nxt];
    if (pos < mx && s.ts[nxt] < s.blk) break;
    found = s.src.slice(pos, mx).trim().slice(-2) === '$$';
  }
  s.line = nxt + 1; // sic: the line that ended the block goes with it
  return true;
}

function hr(s, start, end, silent) {
  const pos = s.bm[start] + s.ts[start];
  const mx = s.em[start];
  const marker = s.at(pos);
  if (s.sc[start] - s.blk >= 4 || (marker !== '*' && marker !== '-' && marker !== '_')) return false;
  let count = 1;
  for (const c of s.src.slice(pos + 1, mx)) {
    if (c !== marker && !space(c)) return false;
    if (c === marker) count++;
  }
  if (count < 3) return false;
  if (!silent) s.line = start + 1;
  return true;
}

function bullet(s, line) {
  const pos = s.bm[line] + s.ts[line];
  const mx = s.em[line];
  const c = s.at(pos);
  if ((c !== '*' && c !== '-' && c !== '+') || (pos + 1 < mx && !space(s.src[pos + 1]))) return -1;
  return pos + 1;
}

function ordered(s, line) {
  const start = s.bm[line] + s.ts[line];
  const mx = s.em[line];
  let pos = start;
  if (pos + 1 >= mx || !(s.src[pos] >= '0' && s.src[pos] <= '9')) return -1;
  pos++;
  for (;;) {
    if (pos >= mx) return -1;
    const c = s.src[pos++];
    if (c >= '0' && c <= '9') {
      if (pos - start >= 10) return -1;
      continue;
    }
    if (c === ')' || c === '.') break;
    return -1;
  }
  if (pos < mx && !space(s.src[pos])) return -1;
  return pos;
}

function list(s, start, end, silent) {
  let nxt = start;
  if (s.sc[nxt] - s.blk >= 4) return false;
  // a list marker indented 4 columns past its list is text
  if (s.listIndent >= 0 && s.sc[nxt] - s.listIndent >= 4 && s.sc[nxt] < s.blk) return false;
  const interrupting = silent && s.parent === 'paragraph' && s.sc[nxt] >= s.blk;
  let after = ordered(s, nxt);
  let isOrdered;
  if (after >= 0) {
    isOrdered = true;
    if (interrupting && Number(s.src.slice(s.bm[nxt] + s.ts[nxt], after - 1)) !== 1) return false;
  } else {
    after = bullet(s, nxt);
    if (after < 0) return false;
    isOrdered = false;
  }
  if (interrupting && s.skipSpaces(after) >= s.em[nxt]) return false;
  if (silent) return true;
  const marker = s.src[after - 1];
  const oldParent = s.parent;
  s.parent = 'list';
  s.level++;
  while (nxt < end) {
    let pos = after;
    const mx = s.em[nxt];
    const initial = s.sc[nxt] + after - (s.bm[nxt] + s.ts[nxt]);
    let offset = initial;
    while (pos < mx && space(s.src[pos])) {
      offset += s.src[pos] === '\t' ? 4 - ((offset + s.bs[nxt]) % 4) : 1;
      pos++;
    }
    const content = pos;
    const gap = content >= mx ? 1 : offset - initial;
    const indent = initial + (gap > 4 ? 1 : gap);
    const oldTs = s.ts[nxt];
    const oldSc = s.sc[nxt];
    const oldListIndent = s.listIndent;
    s.listIndent = s.blk;
    s.blk = indent;
    s.ts[nxt] = content - s.bm[nxt];
    s.sc[nxt] = offset;
    s.level++;
    if (content >= mx && s.empty(nxt + 1)) s.line = Math.min(s.line + 2, end);
    else s.tokenize(nxt, end);
    s.level--;
    s.blk = s.listIndent;
    s.listIndent = oldListIndent;
    s.ts[nxt] = oldTs;
    s.sc[nxt] = oldSc;
    nxt = s.line;
    if (nxt >= end || s.sc[nxt] < s.blk || s.sc[nxt] - s.blk >= 4 || s.interrupts(LIST_BREAKS, nxt, end)) break;
    after = isOrdered ? ordered(s, nxt) : bullet(s, nxt);
    if (after < 0 || s.src[after - 1] !== marker) break;
  }
  s.level--;
  s.line = nxt;
  s.parent = oldParent;
  return true;
}

function footnote(s, start, end, silent) {
  const first = s.bm[start] + s.ts[start];
  const mx = s.em[start];
  if (first + 4 > mx || s.src.slice(first, first + 2) !== '[^') return false;
  let pos = first + 2;
  while (pos < mx && s.src[pos] !== ']') {
    if (s.src[pos] === ' ') return false;
    pos++;
  }
  if (pos === first + 2 || pos + 1 >= mx || s.src[pos + 1] !== ':') return false;
  if (silent) return true;
  pos += 2;
  const old = [s.bm[start], s.ts[start], s.sc[start], s.parent];
  const afterColon = pos;
  const initial = s.sc[start] + pos - first;
  let offset = initial;
  while (pos < mx && space(s.src[pos])) {
    offset += s.src[pos] === '\t' ? 4 - (offset % 4) : 1;
    pos++;
  }
  s.ts[start] = pos - afterColon;
  s.sc[start] = offset - initial;
  s.bm[start] = afterColon;
  s.blk += 4;
  s.parent = 'footnote';
  if (s.sc[start] < s.blk) s.sc[start] += s.blk;
  s.level++;
  s.tokenize(start, end);
  s.level--;
  s.blk -= 4;
  [s.bm[start], s.ts[start], s.sc[start], s.parent] = old;
  return true;
}

function linkDestination(st, start, mx) {
  let pos = start;
  if (st[pos] === '<') {
    pos++;
    while (pos < mx) {
      const c = st[pos];
      if (c === '\n' || c === '<') return null;
      if (c === '>') return [pos + 1, unescape(st.slice(start + 1, pos))];
      pos += c === '\\' && pos + 1 < mx ? 2 : 1;
    }
    return null;
  }
  let level = 0;
  while (pos < mx) {
    const c = st[pos];
    if (c === ' ' || st.charCodeAt(pos) < 0x20 || c === '\x7f') break;
    if (c === '\\' && pos + 1 < mx) {
      if (st[pos + 1] === ' ') break;
      pos += 2;
      continue;
    }
    if (c === '(') {
      level++;
      if (level > 32) return null;
    }
    if (c === ')') {
      if (level === 0) break;
      level--;
    }
    pos++;
  }
  if (start === pos || level !== 0) return null;
  return [pos, unescape(st.slice(start, pos))];
}

// markdown-it's parseLinkTitle; `text` is kept raw (only whether it is empty matters here).
function linkTitle(st, start, mx, prev) {
  let pos = start;
  const res = { ok: false, more: false, pos: 0, text: '', marker: '' };
  if (prev) {
    res.text = prev.text;
    res.marker = prev.marker;
  } else {
    if (pos >= mx || !'"\'('.includes(st[pos])) return res;
    res.marker = st[pos] === '(' ? ')' : st[pos];
    start++;
    pos++;
  }
  while (pos < mx) {
    const c = st[pos];
    if (c === res.marker) return Object.assign(res, { pos: pos + 1, ok: true, text: res.text + st.slice(start, pos) });
    if (c === '(' && res.marker === ')') return res;
    if (c === '\\' && pos + 1 < mx) pos++;
    pos++;
  }
  return Object.assign(res, { more: true, text: res.text + st.slice(start, pos) });
}

function reference(s, start, end, silent) {
  let pos = s.bm[start] + s.ts[start];
  if (s.sc[start] - s.blk >= 4 || s.at(pos) !== '[') return false;
  let nxt = start + 1;
  const nextLine = (line) => { // the next line, when the definition may go on there
    if (line >= s.lineMax || s.empty(line)) return null;
    if (!(s.sc[line] - s.blk > 3 || s.sc[line] < 0)) {
      const old = s.parent;
      s.parent = 'reference';
      const stop = s.interrupts(PARAGRAPH_BREAKS, line, s.lineMax);
      s.parent = old;
      if (stop) return null;
    }
    return s.src.slice(s.bm[line] + s.ts[line], s.em[line] + 1);
  };
  let st = s.src.slice(pos, s.em[start] + 1);
  let mx = st.length;
  const more = () => {
    const tail = nextLine(nxt);
    if (tail !== null) {
      st += tail;
      mx = st.length;
      nxt++;
    }
  };
  let labelEnd = -1;
  for (pos = 1; pos < mx; pos++) {
    const c = st[pos];
    if (c === '[') return false;
    if (c === ']') {
      labelEnd = pos;
      break;
    }
    if (c === '\n') more();
    else if (c === '\\') {
      pos++;
      if (pos < mx && st[pos] === '\n') more();
    }
  }
  if (labelEnd < 0 || st[labelEnd + 1] !== ':') return false;
  for (pos = labelEnd + 2; pos < mx && (st[pos] === '\n' || space(st[pos])); pos++) if (st[pos] === '\n') more();
  const dest = linkDestination(st, pos, mx);
  if (dest === null) return false;
  const url = dest[1].trim().toLowerCase();
  if (BAD_PROTO_RE.test(url) && !GOOD_DATA_RE.test(url)) return false;
  pos = dest[0];
  const destEnd = pos;
  const destLine = nxt;
  const begin = pos;
  for (; pos < mx && (st[pos] === '\n' || space(st[pos])); pos++) if (st[pos] === '\n') more();
  let title = linkTitle(st, pos, mx, null);
  while (title.more) {
    const tail = nextLine(nxt);
    if (tail === null) break;
    st += tail;
    pos = mx;
    mx = st.length;
    nxt++;
    title = linkTitle(st, pos, mx, title);
  }
  let hasTitle = false;
  if (pos < mx && begin !== pos && title.ok) {
    hasTitle = Boolean(title.text);
    pos = title.pos;
  } else {
    pos = destEnd;
    nxt = destLine;
  }
  while (pos < mx && space(st[pos])) pos++;
  if (pos < mx && st[pos] !== '\n' && hasTitle) { // text after the title: the definition ends before it
    pos = destEnd;
    nxt = destLine;
    while (pos < mx && space(st[pos])) pos++;
  }
  if ((pos < mx && st[pos] !== '\n') || !st.slice(1, labelEnd).trim()) return false;
  if (!silent) s.line = nxt;
  return true;
}

function html(s, start, end, silent) {
  const pos = s.bm[start] + s.ts[start];
  if (s.sc[start] - s.blk >= 4 || s.at(pos) !== '<') return false;
  const text = s.text(start);
  const kind = HTML_BLOCKS.findIndex(([open]) => open.test(text));
  if (kind < 0) return false;
  const [, close, interrupts] = HTML_BLOCKS[kind];
  if (silent) return interrupts;
  let nxt = start + 1;
  if (kind === COMPONENT && ONE_LINE_TAG.test(text)) {
    s.line = nxt;
    return true;
  }
  if (!(close && close.test(text))) {
    for (; nxt < end && s.sc[nxt] >= s.blk; nxt++) {
      const line = s.text(nxt);
      if (close ? close.test(line) : !line) {
        if (line) nxt++;
        break;
      }
    }
  }
  s.line = nxt;
  return true;
}

function heading(s, start, end, silent) {
  let pos = s.bm[start] + s.ts[start];
  const mx = s.em[start];
  if (s.sc[start] - s.blk >= 4 || s.at(pos) !== '#' || pos >= mx) return false;
  let level = 1;
  pos++;
  while (s.at(pos) === '#' && pos < mx && level <= 6) {
    level++;
    pos++;
  }
  if (level > 6 || (pos < mx && !space(s.at(pos)))) return false;
  if (!silent) s.line = start + 1;
  return true;
}

function setext(s, start, end) {
  if (s.sc[start] - s.blk >= 4) return false;
  const oldParent = s.parent;
  s.parent = 'paragraph';
  let level = 0;
  let nxt = start + 1;
  for (; nxt < end && !s.empty(nxt); nxt++) {
    if (s.sc[nxt] - s.blk > 3) continue;
    if (s.sc[nxt] >= s.blk) {
      const pos = s.bm[nxt] + s.ts[nxt];
      const mx = s.em[nxt];
      if (pos < mx && (s.src[pos] === '-' || s.src[pos] === '=')
          && s.skipSpaces(s.skipChars(pos, s.src[pos])) >= mx) {
        level = s.src[pos] === '=' ? 1 : 2;
        break;
      }
    }
    if (s.sc[nxt] >= 0 && s.interrupts(PARAGRAPH_BREAKS, nxt, end)) break;
  }
  s.parent = oldParent;
  if (!level) return false;
  s.line = nxt + 1;
  return true;
}

function paragraph(s, start, end) {
  const oldParent = s.parent;
  s.parent = 'paragraph';
  let nxt = start + 1;
  for (; nxt < end && !s.empty(nxt); nxt++) {
    if (s.sc[nxt] - s.blk <= 3 && s.sc[nxt] >= 0 && s.interrupts(PARAGRAPH_BREAKS, nxt, end)) break;
  }
  s.line = nxt;
  s.parent = oldParent;
  return true;
}

// markdown-it's block rules in Slidev's order, and the rules that may end a paragraph (or a link reference
// definition), a block quote's lazy text or a table, and a list
const RULES = [table, code, snippet, slot, fence, blockquote, math, hr, list, footnote, reference, html, heading,
  setext, paragraph];
const PARAGRAPH_BREAKS = [table, snippet, slot, fence, blockquote, math, hr, list, footnote, html, heading];
const QUOTE_BREAKS = [snippet, slot, fence, blockquote, math, hr, list, html, heading];
const LIST_BREAKS = [snippet, slot, fence, blockquote, math, hr];

// For each line of a slide's Markdown, whether Slidev shows it as code: a line of a fenced code block (fences
// included), of an indented code block or a `<<< file` import, as markdown-exit set up as Slidev sets it up parses
// the slide (see the comment above). ``` in an HTML block (<div>, a component tag such as <v-click> up to the next
// blank line, …), a math block or a table is not a fence.
export function codeLines(text) {
  const src = text.replace(/\r\n?/g, '\n').replaceAll('\0', '\uFFFD');
  const blocks = new Blocks(src);
  if (src) blocks.tokenize(0, blocks.lineMax);
  return blocks.code.concat(new Array(src.split('\n').length - blocks.lineMax).fill(false));
}

// `text` with the lines Slidev shows as code emptied (codeLines).
export function stripCode(text) {
  const mask = codeLines(text);
  return text.split(NEWLINE_RE).map((line, i) => (mask[i] ? '' : line)).join('\n');
}

// --------------------------------------------------------------------------- component tags (as Slidev reads them)
// The same scan as citations() in tools/tbook/slides.py (keep them in step: test_slides compares both, and with the
// components Vue compiles from Slidev's Markdown). Slidev's Markdown hands a tag to Vue only where a complete open
// tag starts at the '<' (OPEN_TAG: a name, attributes — name, or name=value with the value in quotes or free of ASCII
// spaces, control characters and "'=<>` —, an optional '/', then '>'); any other '<' is text, so `$a <b + 1$` starts
// no tag and does not run on to the next '>'. citations() tries a complete tag at every '<', also inside the quoted
// values of a complete tag: a '<' in a code span, in $…$ or after a backslash is text, and a tag inside quotes that
// open there is rendered. A '<' and a citing component's name that start no complete tag are reported: in a
// paragraph they are text, but in an HTML block Vue may render the tag (e.g. with a #slot attribute) unchecked. Vue
// ends a tag name at a space, \t, \n, \f, \r, '/' or '>' (NAME_RE); component() resolves the name.
export const COMPONENTS = new Set(['LeanBadge', 'TheoremCard']);
const TAG_RE = new RegExp(`<([A-Za-z][A-Za-z0-9\\-]*)(${ATTR}*)\\s*\\/?>`, 'y');
const NAME_RE = /<([A-Za-z][A-Za-z0-9-]*)(?=[\t\n\f\r />]|$)/y;
// one attribute of ATTR: name, unquoted, '…', "…"
const ATTR_RE = /\s+([a-zA-Z_:@][a-zA-Z0-9:._-]*)(?:\s*=\s*(?:([^"'=<>`\x00-\x20]+)|'([^']*)'|"([^"]*)"))?/g;
// The gid prop as Vue's compiler passes it: of the attributes that may set gid (gid, :gid and v-bind:gid with or
// without modifiers, v-model:gid) the first in the tag wins; citations() reads gid and a string literal in :gid or
// v-bind:gid and reports the others (also .prop and .attr, which set no prop) when they come first. A v-bind without
// an argument (v-bind="{…}", :="…", v-bind.prop=…) merges an object whose gid wins over the attributes before it:
// always reported. A v-on without one (v-on="{…}", @="…", v-on.x=…) starts a new group of props that Vue merges
// over the earlier ones (mergeProps), so the first gid source after it wins instead.
const GID_ATTR_RE = /^(?:gid|(?::|v-bind:|v-model:)gid(?:\..*)?)$/;
const SPREAD_RE = /^(?::|v-bind:?)(?:\..*)?$/;
const ON_SPREAD_RE = /^(?:@|v-on:?)(?:\..*)?$/;

// The component name a template tag resolves to, as Vue resolves it (capitalize(camelize(tag))): lean-badge and
// leanBadge are LeanBadge.
export const component = (tag) => { const n = tag.replace(/-(\w)/g, (_, c) => c.toUpperCase()); return n[0].toUpperCase() + n.slice(1); };

// <LeanBadge> / <TheoremCard> tags of a slide (in any spelling Vue accepts, e.g. <lean-badge>) outside code blocks
// (codeLines), in order, and problems found: [[{ tag, gid, attrs }], [message]]. `tag` is the PascalCase name, `gid`
// the gid as Vue passes it (GID_ATTR_RE), '' where it cannot be read.
export function citations(content) {
  const out = [];
  const problems = [];
  const text = stripCode(content);
  for (let lt = text.indexOf('<'); lt >= 0; lt = text.indexOf('<', lt + 1)) {
    TAG_RE.lastIndex = lt;
    const m = TAG_RE.exec(text);
    if (!m) {
      NAME_RE.lastIndex = lt;
      const name = NAME_RE.exec(text);
      if (name && COMPONENTS.has(component(name[1]))) {
        problems.push(`<${name[1]} …> is not a complete tag (attributes are name or name=value, the value in quotes or `
          + 'free of spaces and "\'=<>`), so it is not checked, yet Vue may render it in an HTML block; write it as a '
          + 'complete tag');
      }
      continue;
    }
    const tag = component(m[1]);
    if (!COMPONENTS.has(tag)) continue;
    const attrs = {};
    let first = null; // the attribute Vue takes gid from (GID_ATTR_RE): [name, value]
    let group = false; // a v-on object began a new group of props since: its first gid source wins
    for (const a of m[2].matchAll(ATTR_RE)) {
      const name = a[1];
      attrs[name] = a[2] ?? a[3] ?? a[4] ?? true;
      if (SPREAD_RE.test(name)) {
        problems.push(`<${m[1]} ${name}=…>: an object bound with v-bind can set gid, which cannot be checked; bind each `
          + 'prop on its own');
      } else if (ON_SPREAD_RE.test(name)) {
        group = true;
      } else if ((!first || group) && GID_ATTR_RE.test(name)) {
        first = [name, attrs[name]];
        group = false;
      }
    }
    let gid = first?.[0] === 'gid' ? first[1] : '';
    if (first && first[0] !== 'gid') {
      const [name, expr] = first;
      const lit = name === ':gid' || name === 'v-bind:gid' ? /^\s*(['"`])(.*)\1\s*$/.exec(String(expr)) : null;
      if (lit) gid = lit[2];
      else if (name === ':gid' || name === 'v-bind:gid') {
        problems.push(`<${m[1]} ${name}="${expr}">: write gid as a literal string so it can be checked`);
      } else {
        problems.push(`<${m[1]} ${name}="${expr}">: write gid="<GID>" (or :gid with a literal string, without `
          + 'modifiers) so it can be checked');
      }
    }
    out.push({ tag, gid: typeof gid === 'string' ? gid.trim() : '', attrs });
  }
  return [out, problems];
}

// Publication paths, shared with tools/tbook/slides.py (keep in sync):
//   site:  _site/<slug>/slides/<deck>/        the book's first language
//          _site/<slug>/slides/<deck>/<lang>/ every other language
//          _site/<slug>/slides/<deck>/<slug>-<deck>-<lang>.pdf
//   build: build/slides/<slug>/<deck>/<lang>/ and build/slides/<slug>/<deck>-<lang>.pdf
export const sitePathOf = (book, deck, lang) => (lang === primaryLang(book) ? `${deck}/` : `${deck}/${lang}/`);
export const pdfName = (slug, deck, lang) => `${slug}-${deck}-${lang}.pdf`;
export const buildPdfName = (deck, lang) => `${deck}-${lang}.pdf`;

// URL path of the site root (from site.toml base_url) such as "/books/"; "/" when unknown.
export function basePath(baseUrl) {
  if (!baseUrl) return '/';
  let p = baseUrl;
  try { p = new URL(baseUrl).pathname; } catch {}
  if (!p.startsWith('/')) p = '/' + p;
  return p.endsWith('/') ? p : p + '/';
}

export const deckBase = (base, book, deck, lang) => `${basePath(base)}${book.slug}/slides/${sitePathOf(book, deck, lang)}`;

// --------------------------------------------------------------------------- slidev

export function slidevBin(root = ROOT) {
  const bin = join(root, 'node_modules', '.bin', process.platform === 'win32' ? 'slidev.cmd' : 'slidev');
  if (!existsSync(bin)) throw new Error('Slidev is not installed: run `npm ci` at the repository root');
  return bin;
}

// Run a slidev sub-command; throw with its output on failure. The last argument may be { env }.
export function slidev(cmd, ...rest) {
  const opts = rest.length && typeof rest.at(-1) === 'object' ? rest.pop() : {};
  const env = { ...process.env, ...(opts.env ?? {}) };
  const r = spawnSync(slidevBin(), [cmd, ...rest], { cwd: ROOT, env, encoding: 'utf8', maxBuffer: 1 << 28 });
  if (r.status !== 0) {
    process.stderr.write((r.stdout ?? '') + (r.stderr ?? ''));
    throw new Error(`slidev ${cmd} ${rest[0] ?? ''} failed (exit ${r.status ?? r.signal})`);
  }
  return r.stdout ?? '';
}

// Command-line helpers: --name value (repeatable) and --flag.
export function argParser(argv) {
  const args = [...argv];
  return {
    all(name) {
      const out = [];
      for (let i = args.indexOf(name); i >= 0; i = args.indexOf(name)) {
        if (i + 1 >= args.length) throw new Error(`${name} needs a value`);
        out.push(args[i + 1]);
        args.splice(i, 2);
      }
      return out;
    },
    one(name, dflt) { const v = this.all(name); return v.length ? v.at(-1) : dflt; },
    flag(name) { const i = args.indexOf(name); if (i < 0) return false; args.splice(i, 1); return true; },
    rest: () => args,
  };
}

// Books (optionally restricted to slugs) that have at least one deck.
export function booksWithDecks(slugs = []) {
  const books = listBooks();
  const hidden = hiddenBooks();
  const named = [...new Set(slugs.filter((s) => hidden.includes(s)))];
  if (named.length) throw hiddenError(named, hidePatterns());
  const unknown = slugs.filter((s) => !books.some((b) => b.slug === s));
  if (unknown.length) throw new Error(`unknown book(s): ${unknown.join(', ')}; known: ${books.map((b) => b.slug).join(', ') || 'none'}`);
  return books.filter((b) => (!slugs.length || slugs.includes(b.slug)) && deckNames(b).length);
}

export { toPosix };
