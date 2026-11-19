// Build, check and export the slide decks of the books.
//
//   node tools/node/slides-build.mjs [--book <slug>]… [--deck <name>]… [--lang <lang>]…
//        [--out <dir>] [--base <site base path>] [--no-pdf] [--no-check] [--shots <dir>]
//
// For every deck and language edition (books/<slug>/slides/<deck>/slides.md for the book's first
// language, slides.<lang>.md for the others):
//   1. slidev build → <out>/<deck>/<lang>/, with --base <base><slug>/slides/<deck>/[<lang>/] and hash
//      routing (GitHub Pages has no fallback for client-side routes). <base> is the URL path of the
//      site root, e.g. "/books/" for https://owner.github.io/books/ (default "/").
//   2. open every slide in Chromium from a local static server under that base and check it: body
//      overflow, content running into the source line or the footer, content leaving the canvas,
//      fonts not loaded, text falling back to a system font (a glyph the bundled fonts lack),
//      runtime errors. --shots <dir> also saves a PNG of every slide.
//   3. slidev export → <out>/<deck>-<lang>.pdf and verify its page count equals the slide count and that
//      it draws the theme's print backdrop (one image, theme/slides/styles/backdrop.jpg) instead of the
//      backdrop layers, which PDF readers render slowly. A backdrop.jpg that no longer matches
//      backdrop.css or the tokens is rendered again first (slides-backdrop.mjs; commit the result).
// <out> defaults to build/slides/<slug>/ (docs/ARCHITECTURE.md §5); it also receives manifest.json,
// which tools/tbook/slides.py reads to publish the decks. Chromium: $PW_CHROMIUM_PATH when set,
// otherwise Playwright's own download. Exit status 1 when any check fails.
//
// Adapted from chrono-company-slides scripts/build.mjs and scripts/site.mjs (Apache-2.0).
import http from 'node:http';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, rmdirSync, writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { extname, join, relative, resolve } from 'node:path';
import {
  ROOT, argParser, basePath, booksWithDecks, buildPdfName, deckBase, deckLangs, deckNames,
  i18n, pdfName, primaryLang, readEdition, sitePathOf, slidev, toPosix,
} from './slides-lib.mjs';
import { backdropState, renderBackdrop } from './slides-backdrop.mjs';

const TOLERANCE = 12; // px of body overflow tolerated; crossing the source line or the footer never is
const FONTS = ['Chakra Petch', 'Noto Sans SC', 'JetBrains Mono']; // must be loaded by the last slide

const cli = argParser(process.argv.slice(2));
const bookSlugs = cli.all('--book');
const deckFilter = cli.all('--deck');
const langFilter = cli.all('--lang');
const outArg = cli.one('--out', null);
const BASE = basePath(cli.one('--base', '/'));
const shotsArg = cli.one('--shots', null);
const SHOTS = shotsArg && resolve(shotsArg);
const NO_PDF = cli.flag('--no-pdf');
const NO_CHECK = cli.flag('--no-check');
if (cli.rest().length) {
  console.error(`slides-build: unexpected arguments ${cli.rest().join(' ')}`);
  process.exit(2);
}

// An unknown or hidden (site.toml [books].hide) --book is a usage error.
function selectBooks() {
  try {
    return booksWithDecks(bookSlugs);
  } catch (e) {
    console.error(`slides-build: ${e.message}`);
    return process.exit(2);
  }
}

const failures = [];
const books = selectBooks();
if (outArg && books.length > 1) {
  console.error('slides-build: --out names one book\'s output directory; pass a single --book with it');
  process.exit(2);
}

// --------------------------------------------------------------------------- static server
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2',
  '.woff': 'font/woff', '.ttf': 'font/ttf', '.svg': 'image/svg+xml', '.json': 'application/json',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.pdf': 'application/pdf',
};
// Serve `dir` at URL path `base` (the deck was built for that base); unknown paths fall back to index.html.
function serve(dir, base) {
  const server = http.createServer(async (req, res) => {
    let path = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (!path.startsWith(base)) { res.writeHead(404).end(); return; }
    path = path.slice(base.length);
    for (const file of [join(dir, path), join(dir, path, 'index.html'), join(dir, 'index.html')]) {
      try {
        const body = await readFile(file);
        res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' });
        res.end(body);
        return;
      } catch {}
    }
    res.writeHead(404).end();
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok({ port: server.address().port, close: () => server.close() })));
}

// --------------------------------------------------------------------------- browser checks
async function launch() {
  const { chromium } = await import('playwright-chromium');
  const executablePath = process.env.PW_CHROMIUM_PATH || undefined;
  try {
    return await chromium.launch({ executablePath });
  } catch (e) {
    throw new Error(`cannot start Chromium (${e.message.split('\n')[0]}); set PW_CHROMIUM_PATH to a Chromium binary or run \`npx playwright install chromium\``);
  }
}

// Checks the slides of an edition in Chromium; returns the numbers of the slides with a background of their
// own (class tr-own-bg), whose PDF pages keep the backdrop layers.
async function checkEdition(browser, ed, dir, base) {
  const ownBackgrounds = new Set();
  const { port, close } = await serve(dir, base);
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  // Presenting asks for a screen wake lock, which headless Chromium refuses: not an error.
  page.on('pageerror', (e) => { if (!/Wake Lock/i.test(e.message)) failures.push(`${ed.rel}: page error ${e.message}`); });
  page.on('console', (m) => { if (m.type() === 'error' && !/Wake Lock|favicon/i.test(m.text())) failures.push(`${ed.rel}: console error ${m.text()}`); });
  const shotDir = SHOTS && join(SHOTS, ed.book, `${ed.deck}-${ed.lang}`);
  if (shotDir) { rmSync(shotDir, { recursive: true, force: true }); mkdirSync(shotDir, { recursive: true }); }
  // Ask DevTools which font renders each node: isCustomFont false means a system font, i.e. a glyph
  // missing from the bundled fonts — another machine would render it differently.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('DOM.enable');
  await cdp.send('CSS.enable');
  try {
    for (let n = 1; n <= ed.count; n++) {
      await page.goto(`http://127.0.0.1:${port}${base}#/${n}`, { waitUntil: 'networkidle' });
      const slide = page.locator(`.slidev-page-${n} .slide`);
      await slide.waitFor({ state: 'visible', timeout: 30000 });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForFunction(() => !document.documentElement.classList.contains('fonts-pending'), null, { timeout: 10000 }).catch(() => {});
      const r = await slide.evaluate((s, { tol, fonts }) => {
        const out = [];
        const scale = s.getBoundingClientRect().height / 1080;
        const box = s.getBoundingClientRect();
        const body = s.querySelector(':scope > .body');
        if (body && body.scrollHeight - body.clientHeight > tol) out.push(`body overflows by ${body.scrollHeight - body.clientHeight}px`);
        const limitEl = s.querySelector(':scope > .src') || s.querySelector(':scope > .ftr') || s.querySelector(':scope > .cover-meta');
        if (body) {
          let bottom = 0;
          let right = 0;
          body.querySelectorAll('*').forEach((el) => {
            // KaTeX's inner boxes (struts, the hidden MathML copy) are not content; its outer box is
            if (el.parentElement?.closest('.katex')) return;
            const r = el.getBoundingClientRect();
            if (!r.width && !r.height) return;
            bottom = Math.max(bottom, r.bottom);
            right = Math.max(right, r.right);
          });
          if (limitEl) {
            const limit = limitEl.getBoundingClientRect().top;
            const what = limitEl.classList.contains('src') ? 'the source line' : 'the footer';
            if (bottom > limit + 1) out.push(`content runs into ${what} by ${Math.round((bottom - limit) / scale)}px`);
          }
          if (right > box.right - 60 * scale) out.push(`content reaches the right edge (${Math.round((right - box.left) / scale)}px of 1920)`);
        }
        // the chapter numeral of the section layout is decoration: text must not run under it
        const numeral = s.querySelector(':scope > .divider-n');
        if (body && numeral?.firstChild) {
          const range = document.createRange();
          range.selectNodeContents(numeral);
          const left = range.getBoundingClientRect().left;
          let right = 0;
          body.querySelectorAll('*').forEach((el) => { if (!el.parentElement?.closest('.katex')) right = Math.max(right, el.getBoundingClientRect().right); });
          if (right > left - 16 * scale) out.push(`content runs into the chapter numeral by ${Math.round((right - left) / scale) + 16}px`);
        }
        const src = s.querySelector(':scope > .src');
        const ftr = s.querySelector(':scope > .ftr');
        if (src && ftr && src.getBoundingClientRect().bottom > ftr.getBoundingClientRect().top) out.push('the source line runs into the footer');
        const loaded = new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/"/g, '')));
        return { out, missing: fonts.filter((f) => !loaded.has(f)) };
      }, { tol: TOLERANCE, fonts: FONTS });
      for (const msg of r.out) failures.push(`${ed.rel} slide ${n}: ${msg}`);
      const { root } = await cdp.send('DOM.getDocument', { depth: -1 });
      const { nodeIds } = await cdp.send('DOM.querySelectorAll', { nodeId: root.nodeId, selector: `.slidev-page-${n} .slide *:not(.katex-mathml, .katex-mathml *)` }); // MathML copies are invisible
      const system = new Map();
      for (const nodeId of nodeIds) {
        let fonts = [];
        try { ({ fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId })); }
        catch { continue; }
        for (const f of fonts) {
          if (f.isCustomFont) continue;
          const { outerHTML } = await cdp.send('DOM.getOuterHTML', { nodeId });
          system.set(f.familyName, outerHTML.replace(/<[^>]+>/g, '').trim().slice(0, 40));
        }
      }
      for (const [family, text] of system) failures.push(`${ed.rel} slide ${n}: text falls back to the system font ${family} (e.g. “${text}”); use characters the theme fonts cover`);
      // The print view (PDF export) shows backdrop.jpg instead of the backdrop layers (backdrop.css) on every
      // slide with the theme's background; a slide with a background of its own (class tr-own-bg) keeps them.
      const bg = await slide.evaluate((s) => {
        const keys = ['backgroundColor', 'backgroundImage', 'backgroundSize', 'backgroundPosition', 'backgroundRepeat',
          'backgroundBlendMode', 'backgroundClip', 'backgroundOrigin'];
        const probe = document.createElement('div'); // the theme's background, unaffected by any deck rule on .slide
        probe.style.cssText = 'position:absolute;width:0;height:0;background-color:var(--tr-void);'
          + 'background-image:var(--tr-fx-aurora);background-size:100% 100%';
        s.parentElement.appendChild(probe);
        const theme = getComputedStyle(probe);
        const own = getComputedStyle(s);
        const differs = keys.filter((k) => own[k] !== theme[k]).map((k) => `${k} ${own[k].slice(0, 80)}`);
        probe.remove();
        const html = document.documentElement;
        const had = html.classList.contains('print');
        html.classList.add('print');
        const image = getComputedStyle(s).backgroundImage;
        const fx = s.querySelector(':scope > .tr-fx');
        const fxDisplay = fx ? getComputedStyle(fx).display : 'none';
        if (!had) html.classList.remove('print');
        return { differs, ownBg: s.classList.contains('tr-own-bg'), image, fx: !!fx, fxDisplay };
      });
      if (bg.ownBg) {
        ownBackgrounds.add(n);
        if (bg.fx && bg.fxDisplay === 'none') failures.push(`${ed.rel} slide ${n}: class tr-own-bg, yet the print view hides the backdrop layers`);
        if (!bg.differs.length) console.log(`${ed.rel} slide ${n}: note: class tr-own-bg on the theme's own background; its PDF page draws the backdrop layers, which readers render slowly`);
      } else if (bg.differs.length) {
        failures.push(`${ed.rel} slide ${n}: the slide has a background of its own (${bg.differs.join('; ')}), but not the class `
          + 'tr-own-bg: the PDF would draw the print backdrop (theme/slides/styles/backdrop.jpg) over it and leave out the '
          + 'scanlines, corner brackets and vignette; add tr-own-bg to the slide\'s class (theme/slides/README.md)');
      } else if (!/backdrop[^/)]*\.jpg/.test(bg.image) || bg.fxDisplay !== 'none') {
        failures.push(`${ed.rel} slide ${n}: the print view does not show the print backdrop (background ${bg.image.slice(0, 80)}, `
          + `.tr-fx display ${bg.fxDisplay}); the PDF would draw the backdrop layers, which readers render slowly`);
      }
      if (n === ed.count && r.missing.length) failures.push(`${ed.rel}: fonts not loaded: ${r.missing.join(', ')}`);
      if (shotDir) await slide.screenshot({ path: join(shotDir, `${String(n).padStart(2, '0')}.png`) });
    }
  } finally {
    await page.close();
    close();
  }
  return ownBackgrounds;
}

// --------------------------------------------------------------------------- export
// ownBackgrounds: slide numbers whose pages keep the backdrop layers (checkEdition), null when not checked.
async function exportPdf(ed, path, ownBackgrounds = null) {
  rmSync(path, { force: true });
  const args = [toPosix(relative(ROOT, ed.file)), '--output', path, '--format', 'pdf', '--wait-until', 'networkidle', '--wait', '800', '--timeout', '120000'];
  if (process.env.PW_CHROMIUM_PATH) args.push('--executable-path', process.env.PW_CHROMIUM_PATH);
  slidev('export', ...args);
  const { PDFDocument, PDFDict, PDFName } = await import('pdf-lib');
  const doc = await PDFDocument.load(readFileSync(path));
  const pages = doc.getPageCount();
  if (pages !== ed.count) failures.push(`${ed.rel}: PDF has ${pages} pages, the deck ${ed.count} slides`);
  // the print backdrop: an image of the canvas size on the page (backdrop.css), not the layers
  const key = (d, k) => d.get(PDFName.of(k))?.toString();
  const drawsBackdrop = (page) => {
    const xobjects = page.node.Resources()?.lookupMaybe(PDFName.of('XObject'), PDFDict);
    return !!xobjects && [...xobjects.entries()].some(([, ref]) => {
      const d = doc.context.lookup(ref)?.dict;
      return d && key(d, 'Subtype') === '/Image' && key(d, 'Width') === '1920' && key(d, 'Height') === '1080';
    });
  };
  const without = doc.getPages().map((p, i) => (drawsBackdrop(p) ? 0 : i + 1)).filter(Boolean);
  const unexpected = ownBackgrounds ? without.filter((n) => !ownBackgrounds.has(n)) : without.length === pages ? without : [];
  if (unexpected.length) {
    failures.push(`${ed.rel}: PDF page${unexpected.length > 1 ? 's' : ''} ${unexpected.join(', ')} ${unexpected.length > 1 ? 'do' : 'does'} not draw the print backdrop `
      + '(theme/slides/styles/backdrop.jpg) but the backdrop layers, which PDF readers render slowly (theme/slides/styles/backdrop.css)');
  } else if (without.length && !ownBackgrounds) {
    console.log(`${ed.rel}: note: PDF pages ${without.join(', ')} have a background of their own instead of the print backdrop`);
  }
  return pages;
}

// Slidev writes import-glob proxies to <deck>/node_modules/.slidev; keep the source tree clean.
function cleanDeckDir(dir) {
  const nm = join(dir, 'node_modules');
  rmSync(join(nm, '.slidev'), { recursive: true, force: true });
  rmSync(join(nm, '.vite'), { recursive: true, force: true });
  try { if (!readdirSync(nm).length) rmdirSync(nm); } catch {}
}

// --------------------------------------------------------------------------- main
let browser = null;
try {
  const backdrop = backdropState();
  if (books.length && backdrop.problems.length) {
    failures.push(backdrop.message);
  } else if (books.length && !backdrop.fresh && (NO_CHECK && NO_PDF)) {
    console.log(`slides-build: note: ${backdrop.message}`); // nothing here uses a browser to render it again
  } else if (books.length && !backdrop.fresh) {
    browser ??= await launch();
    for (const p of await renderBackdrop(browser)) {
      console.log(`slides-build: ${toPosix(relative(ROOT, p))} did not match backdrop.css and the tokens: rendered again; commit it`);
    }
  }
  for (const book of books) {
    const OUT = resolve(outArg ?? join(ROOT, 'build', 'slides', book.slug));
    const manifestPath = join(OUT, 'manifest.json');
    const previous = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : null;
    const manifest = { schema: 'trureturing-books.slides.v1', book: book.slug, base: BASE, decks: {} };
    // a partial run (--deck/--lang) keeps the entries it does not rebuild, if built for the same base
    const present = new Set(deckNames(book));
    if ((deckFilter.length || langFilter.length) && previous?.base === BASE) {
      for (const [d, e] of Object.entries(previous.decks ?? {})) if (present.has(d)) manifest.decks[d] = e;
    }
    const names = [...present].filter((d) => !deckFilter.length || deckFilter.includes(d));
    for (const deck of names) {
      const langs = deckLangs(book, deck).filter((l) => book.languages.includes(l) && (!langFilter.length || langFilter.includes(l)));
      // the primary language first: other languages are published inside its directory
      const editions = [];
      for (const lang of langs) editions.push(await readEdition(book, deck, lang));
      const siteLangs = deckLangs(book, deck).filter((l) => book.languages.includes(l));
      const entry = manifest.decks[deck] ?? { langs: {} };
      for (const ed of editions) {
        const failedBefore = failures.length;
        delete entry.langs[ed.lang]; // recorded again below only if this edition builds cleanly
        const dir = join(OUT, deck, ed.lang);
        const base = deckBase(BASE, book, deck, ed.lang);
        // the first language is published at <deck>/, the others at <deck>/<lang>/
        const primary = primaryLang(book);
        const up = ed.lang === primary ? '' : '../';
        const env = {
          VITE_SITE_INDEX: `${up}../`,
          VITE_SITE_LANG: ed.lang,
          VITE_SITE_LANGS: JSON.stringify(siteLangs.map((l) => ({ lang: l, name: String(i18n(l)?.meta?.name ?? l), href: `${up}${l === primary ? '' : `${l}/`}` || './' }))),
          VITE_SITE_PDF: NO_PDF || process.env.TBOOK_SLIDES_RELEASE_ONLY === '1' ? '' : `${up}${pdfName(book.slug, deck, ed.lang)}`,
        };
        rmSync(dir, { recursive: true, force: true });
        mkdirSync(dir, { recursive: true });
        try {
          slidev('build', toPosix(relative(ROOT, ed.file)), '--out', dir, '--base', base, '--router-mode', 'hash', { env });
        } finally {
          cleanDeckDir(ed.dir);
        }
        rmSync(join(dir, '_redirects'), { force: true }); // Netlify-only file
        let note = `${ed.count} slides → ${toPosix(relative(ROOT, dir))}/`;
        let ownBackgrounds = null;
        if (!NO_CHECK) {
          browser ??= await launch();
          ownBackgrounds = await checkEdition(browser, ed, dir, base);
          note += ', checked';
        }
        const pdfPath = join(OUT, buildPdfName(deck, ed.lang));
        if (!NO_PDF) {
          try {
            const pages = await exportPdf(ed, pdfPath, ownBackgrounds);
            note += `; PDF ${pages} pages → ${toPosix(relative(ROOT, pdfPath))}`;
          } finally {
            cleanDeckDir(ed.dir);
          }
        }
        if (failures.length > failedBefore) {
          console.log(`${ed.rel}: ${note} — FAILED`);
          continue;
        }
        entry.langs[ed.lang] = {
          title: ed.title,
          info: ed.info,
          blurb: String(ed.meta.blurb ?? ''),
          slides: ed.count,
          dir: `${deck}/${ed.lang}/`,
          site_path: sitePathOf(book, deck, ed.lang),
          base,
          pdf: NO_PDF ? '' : buildPdfName(deck, ed.lang), // --no-pdf: never publish an older PDF
          pdf_name: pdfName(book.slug, deck, ed.lang),
        };
        console.log(`${ed.rel}: ${note}`);
      }
      manifest.decks[deck] = entry;
    }
    mkdirSync(OUT, { recursive: true });
    const sorted = Object.fromEntries(Object.keys(manifest.decks).sort().map((k) => [k, manifest.decks[k]]));
    writeFileSync(manifestPath, JSON.stringify({ ...manifest, decks: sorted }, null, 2) + '\n');
  }
} catch (e) {
  failures.push(e.message);
} finally {
  await browser?.close();
}

if (failures.length) {
  console.error(`\nslides-build failed (${failures.length}):\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
if (!books.length) console.log('slides-build: no decks found');
