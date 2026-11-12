// Static checks of the slide decks (no browser; layout, fonts and PDF page counts are checked by
// slides-build.mjs):
//
//   node tools/node/slides-check.mjs [--book <slug>]… [--deck <name>]…
//
// For every books/<slug>/slides/<deck>/:
//   - an edition file for every language of the book (slides.md for its first language, slides.<lang>.md
//     for the others), no file for a language the book does not have, no slides.<first language>.md
//     (slides.md would shadow it) and no `src:` slide imports (the checks would not see those slides);
//   - headmatter: theme is the relative path to theme/slides, title, htmlAttrs.lang equal to the
//     language's BCP 47 tag (theme/i18n/<lang>.toml meta.bcp47), deck.code / deck.title / deck.version;
//     deck.code and deck.version identical in every language;
//   - every language page for page: same slide count, and on each slide the same layout, bare, chapter,
//     hide/disabled flags, presence of a section, and the same sequence of cited Lean GIDs;
//   - every <LeanBadge gid> / <TheoremCard gid> (in any spelling Vue resolves, e.g. <lean-badge>) outside
//     code blocks (citations and stripCode in slides-lib.mjs: complete tags as Slidev's Markdown reads them,
//     Slidev's own Markdown block rules; a component tag that is not complete is reported) is a GID
//     present in trureturing.lock.json and a Lean theorem unless kind="definition" (only theorems get the
//     green LEAN ✓); status="open" cites no GID. The gid is the one Vue passes the component: the first of
//     gid, :gid and v-bind:gid (a string literal); a gid bound otherwise, or a v-bind object, is reported;
//   - no root-relative or file: links outside code blocks (the site is served under /<repo>/), no
//     index.html in the deck;
//   - no class name or attribute on an HTML element that UnoCSS (bundled with Slidev) would turn into
//     a utility that overrides the theme;
//   - the theme's print backdrop (theme/slides/styles/backdrop.jpg, which the PDF export shows instead of
//     the backdrop layers) matches backdrop.css and theme/generated/tokens.css (slides-backdrop.mjs).
// Exit status 1 when any check fails; with no deck in any book, only the theme's print backdrop is checked.
//
// Adapted from chrono-company-slides scripts/check.mjs (Apache-2.0).
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import {
  DECK_RE, GID_RE, PRIMARY_FILE, ROOT, argParser, bcp47, booksWithDecks, citations, deckLangs, deckNames, editionFile,
  loadLock, primaryLang, readEdition, stripCode, themeRef, toPosix,
} from './slides-lib.mjs';
import { backdropState } from './slides-backdrop.mjs';

const cli = argParser(process.argv.slice(2));
const bookSlugs = cli.all('--book');
const deckFilter = cli.all('--deck');
const errors = [];
const fail = (msg) => errors.push(msg);

const ABS_LINK = [
  /\b(?:href|src|poster|data)\s*=\s*["'](\/(?!\/)[^"']*|file:[^"']*)["']/gi,
  /\]\((\/(?!\/)[^)\s]*|file:[^)\s]*)\)/g,
  /url\(\s*["']?(\/(?!\/)[^"')]*)/gi,
];

const backdrop = backdropState();
if (!backdrop.fresh) fail(backdrop.message);

// An unknown or hidden (site.toml [books].hide) --book is a usage error.
function selectBooks() {
  try {
    return booksWithDecks(bookSlugs);
  } catch (e) {
    console.error(`slides-check: ${e.message}`);
    return process.exit(2);
  }
}

const books = selectBooks();
const lock = loadLock();
if (!lock && books.length) fail('trureturing.lock.json not found: run ./tbook pin');
const decls = lock?.declarations ?? {};

// UnoCSS collisions (see theme/slides/uno.config.ts, whose blocklist is honoured here).
const unoConfig = readFileSync(join(ROOT, 'theme', 'slides', 'uno.config.ts'), 'utf8');
const UNO_BLOCKLIST = [...(/blocklist:\s*\[([^\]]*)\]/.exec(unoConfig)?.[1] ?? '').matchAll(/['"]([^'"]+)['"]/g)].map((m) => m[1]);
const UNO_HARMLESS = new Set(['grow']); // same effect as the theme rule of that name
let uno = null;
async function unoConflicts(md) {
  if (!uno) {
    const { createGenerator, presetWind3, presetAttributify } = await import('unocss');
    uno = await createGenerator({ presets: [presetWind3(), presetAttributify()], blocklist: UNO_BLOCKLIST });
  }
  const classes = new Set();
  const attrs = [];
  for (const [, , rest] of md.matchAll(/<([a-z][\w-]*)\b([^>]*)>/g)) {
    for (const [, name, val] of rest.matchAll(/([\w:.-]+)="([^"]*)"/g)) {
      if (name === 'class') val.split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
      else if (!/^(style|href|src|id|role|lang|title|alt|xmlns|target|rel|data-|aria-)/.test(name)) attrs.push(`${name}="${val}"`);
    }
  }
  const out = [];
  for (const u of (await uno.generate([...classes].join(' '), { preflights: false })).matched) {
    if (!UNO_HARMLESS.has(u)) out.push(`class ${u} is also a UnoCSS utility and its generated style overrides the theme; rename it or add it to the blocklist in theme/slides/uno.config.ts`);
  }
  for (const u of (await uno.generate(`<div ${attrs.join(' ')}>`, { preflights: false })).matched) {
    out.push(`attribute ${u} is read by UnoCSS (attributify) as a style; use style="…" instead`);
  }
  return out;
}

let editionCount = 0;
let deckCount = 0;
for (const book of books) {
  for (const deck of deckNames(book).filter((d) => !deckFilter.length || deckFilter.includes(d))) {
    deckCount++;
    const dir = join(book.slidesDir, deck);
    const at = toPosix(join('books', book.slug, 'slides', deck));
    if (!DECK_RE.test(deck)) fail(`${at}: deck names are kebab-case (a-z, 0-9, -)`);
    if (existsSync(join(dir, 'index.html'))) fail(`${at}/index.html: Slidev merges it into every page; delete it`);
    const langs = deckLangs(book, deck);
    const primary = primaryLang(book);
    for (const name of readdirSync(dir)) {
      if (name === `slides.${primary}.md`) fail(`${at}/${name}: ${primary} is the book's first language, whose edition is ${PRIMARY_FILE}; this file is never read (move its slides into ${PRIMARY_FILE} and delete it)`);
      else if (/^slides\..+\.md$/.test(name) && !langs.some((l) => editionFile(book, l) === name)) fail(`${at}/${name}: not an edition file (${PRIMARY_FILE} for ${primary}, the book's first language, or slides.<lang>.md)`);
    }
    for (const lang of langs) if (!book.languages.includes(lang)) fail(`${at}/${editionFile(book, lang)}: ${lang} is not an edition of this book (book.toml editions: ${book.languages.join(', ')})`);
    for (const lang of book.languages) if (!langs.includes(lang)) fail(`${at}: missing ${editionFile(book, lang)} (every deck has an edition for each language of the book: ${book.languages.join(', ')}; ${PRIMARY_FILE} is ${primary})`);
    const eds = [];
    for (const lang of book.languages.filter((l) => langs.includes(l))) eds.push(await readEdition(book, deck, lang));
    if (!eds.length) continue;
    const theme = themeRef(dir);
    for (const ed of eds) {
      editionCount++;
      const where = ed.rel;
      if (ed.head.theme !== theme) fail(`${where}: headmatter must say theme: ${theme} (the shared theme)`);
      if (!ed.title) fail(`${where}: headmatter title is missing`);
      else if (/[<>]|\{\{/.test(ed.title)) fail(`${where}: title must not contain <, > or {{ (Slidev renders it as a Vue template)`);
      const want = bcp47(ed.lang);
      if (ed.head.htmlAttrs?.lang !== want) fail(`${where}: headmatter must set htmlAttrs.lang: "${want}" (the language of the file)`);
      for (const k of ['code', 'title', 'version']) if (!ed.meta[k]) fail(`${where}: deck.${k} is missing (header and footer need it)`);
      if (!ed.count) fail(`${where}: no slides`);
      ed.all.forEach((s, i) => {
        if (s.frontmatter && 'src' in s.frontmatter) fail(`${where} slide ${i + 1}: src: imports slides from another file, which the checks (Lean citations, page-for-page parity) do not read; write the slides in this file`);
      });
      ed.cites = ed.slides.map((s, i) => {
        const [found, problems] = citations(s.content ?? '');
        for (const msg of problems) fail(`${where} slide ${i + 1}: ${msg}`);
        return found;
      });
      ed.slides.forEach((s, i) => {
        const here = `${where} slide ${i + 1}`;
        for (const c of ed.cites[i]) {
          if (c.attrs.status === 'written-proof' && c.attrs.kind != null && !['theorem', 'lemma', 'proposition', 'corollary'].includes(c.attrs.kind)) fail(`${here}: written-proof is only for formal results`);
          if (c.attrs.status === 'written-proof' && Object.hasOwn(c.attrs, 'gid')) fail(`${here}: written-proof must not have gid`);
          if (c.attrs.status === 'written-proof') {
            if (c.tag !== 'TheoremCard' || !c.attrs.cite) fail(`${here}: written-proof needs a TheoremCard with cite="<book-result-id>"`);
            if (!/^10\.[0-9]{4,9}\/\S+$/u.test(c.attrs.doi ?? '') || /\p{C}/u.test(c.attrs.doi ?? '')) fail(`${here}: written-proof requires a bare DOI`);
            if (typeof c.attrs.source !== 'string' || !c.attrs.source || c.attrs.source.trim() !== c.attrs.source || /[|\r\n]|\p{C}/u.test(c.attrs.source)) fail(`${here}: written-proof requires the original source location`);
            if (!/^https:\/\/github\.com\/the-omega-institute\/trureturing-requests\/issues\/[1-9][0-9]*$/.test(c.attrs.request ?? '')) fail(`${here}: written-proof requires a trureturing-requests issue URL`);
          }
          if (c.attrs.status != null && !['open', 'argued', 'written-proof'].includes(c.attrs.status)) fail(`${here}: unknown result status ${c.attrs.status}`);
          if (c.attrs.status === 'open' && c.gid) fail(`${here}: <${c.tag} status="open"> must not cite Lean (open problems have no proof); drop gid`);
          if (!c.gid) {
            if (!c.attrs.status) fail(`${here}: <${c.tag}> needs gid="<GID>" or status="open|argued|written-proof"`);
            continue;
          }
          if (!GID_RE.test(c.gid)) { fail(`${here}: ${c.gid} is not a GID (<module path>.<name>, e.g. D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)`); continue; }
          const d = decls[c.gid];
          if (!d) fail(`${here}: ${c.gid} is not in trureturing.lock.json; slides may only cite declarations the lock resolves (cite it in the book and run ./tbook pin --refresh)`);
          // LEAN ✓ means a kernel-checked theorem; a definition gets the neutral badge only with kind="definition"
          else if (c.attrs.kind !== 'definition' && d.kind !== 'theorem') fail(`${here}: ${c.gid} is a Lean ${d.kind}; a ${c.tag} must cite a theorem (or say kind="definition")`);
        }
        const body = stripCode(s.content ?? '');
        for (const re of ABS_LINK) for (const m of body.matchAll(re)) fail(`${here}: link ${m[1]} is absolute; the site lives under /<repo>/, use a relative or https:// link`);
      });
      for (const msg of await unoConflicts(ed.md)) fail(`${where}: ${msg}`);
    }
    // page-for-page parity with the primary language
    const [main, ...rest] = eds;
    for (const ed of rest) {
      if (ed.count !== main.count) fail(`${ed.rel}: ${ed.count} slides, ${main.rel} has ${main.count}; editions correspond page for page`);
      for (const k of ['code', 'version']) if (String(ed.meta[k] ?? '') !== String(main.meta[k] ?? '')) fail(`${ed.rel}: deck.${k} differs from ${main.rel} (${main.meta[k] ?? '—'})`);
      for (let i = 0; i < Math.min(ed.count, main.count); i++) {
        const a = main.slides[i].frontmatter ?? {};
        const b = ed.slides[i].frontmatter ?? {};
        for (const key of ['layout', 'bare', 'chapter', 'class']) {
          if (String(a[key] ?? '') !== String(b[key] ?? '')) fail(`${ed.rel} slide ${i + 1}: ${key} is ${JSON.stringify(b[key] ?? null)}, ${main.rel} has ${JSON.stringify(a[key] ?? null)}`);
        }
        if (!!a.section !== !!b.section) fail(`${ed.rel} slide ${i + 1}: section ${b.section ? 'present' : 'missing'}, unlike ${main.rel}`);
        const citationKey = (c) => (c.gid || `(${c.attrs.status})`) + (c.attrs.status === 'written-proof' ? JSON.stringify(['cite', 'doi', 'source', 'request'].map(k => c.attrs[k] ?? null)) : '');
        const ga = main.cites[i].map(citationKey).join(' ');
        const gb = ed.cites[i].map(citationKey).join(' ');
        if (ga !== gb) fail(`${ed.rel} slide ${i + 1}: cites [${gb}], ${main.rel} cites [${ga}]`);
      }
    }
    for (const ed of eds) console.log(`${ed.rel}: ${ed.lang}, ${ed.count} slides`);
  }
}

if (errors.length) {
  console.error(`\nslides-check failed (${errors.length}):\n- ${errors.join('\n- ')}`);
  process.exit(1);
}
console.log(`slides-check: ${deckCount} deck(s), ${editionCount} edition(s), ok`);
