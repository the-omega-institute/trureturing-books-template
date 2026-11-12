// Shared Node helpers for the film pipeline (render.js, poster.js, shot.js). ES module.
// A tiny static server for <film>/out/ (fonts load by relative URL, which file:// pages may not do),
// Chromium launch through Playwright honouring PW_CHROMIUM_PATH, and the film page lifecycle.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.css': 'text/css', '.jpg': 'image/jpeg', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.wav': 'audio/wav', '.mp4': 'video/mp4'
};

/** Serve `dir` on 127.0.0.1 at an ephemeral port. Resolves to { url, close() }. */
export async function serve(dir) {
  const root = resolve(dir);
  const server = createServer(async (req, res) => {
    try {
      const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
      const file = normalize(join(root, path.endsWith('/') ? path + 'index.html' : path));
      if (file !== root && !file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
      if (!(await stat(file)).isFile()) throw new Error('not a file');
      res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
      res.end(await readFile(file));
    } catch {
      res.writeHead(404, { 'content-type': 'text/plain' }).end('not found');
    }
  });
  await new Promise((ok, fail) => { server.once('error', fail); server.listen(0, '127.0.0.1', ok); });
  const { port } = server.address();
  return { url: `http://127.0.0.1:${port}/`, close: () => new Promise(r => server.close(r)) };
}

/* Solid shots (theme/film/engine.js solid()) need WebGL. Headless Chromium has no GPU and draws WebGL with SwiftShader,
   its CPU renderer, which newer versions only allow with --enable-unsafe-swiftshader (the pages are our own). It does
   not change the 2D canvas: frames without a solid stay identical, and every frame stays independent of the frames
   drawn before it (--use-angle=swiftshader would move the 2D canvas onto ANGLE and break both). FILM_CHROMIUM_ARGS
   adds arguments, separated by spaces (e.g. --disable-3d-apis to see how a film with solid shots fails without WebGL). */
export const CHROMIUM_ARGS = ['--disable-gpu-vsync', '--font-render-hinting=none', '--enable-unsafe-swiftshader'];

/** Launch Chromium. PW_CHROMIUM_PATH overrides Playwright's own browser download. */
export async function launch() {
  let chromium;
  try {
    ({ chromium } = await import('playwright-chromium'));
  } catch {
    try { ({ chromium } = await import('playwright')); } catch {
      throw new Error('Playwright is not installed: run `npm ci` at the repository root');
    }
  }
  const extra = (process.env.FILM_CHROMIUM_ARGS || '').split(/\s+/).filter(Boolean);
  const opts = { args: [...CHROMIUM_ARGS, ...extra] };
  if (process.env.PW_CHROMIUM_PATH) opts.executablePath = process.env.PW_CHROMIUM_PATH;
  try {
    return await chromium.launch(opts);
  } catch (e) {
    throw new Error(`cannot start Chromium (${String(e.message).split('\n')[0]}); set PW_CHROMIUM_PATH to a Chromium ` +
      'binary or run `npx playwright install --with-deps chromium`');
  }
}

/** Open <out>/index.html and wait for window.ready. Throws on page errors, so a broken film never renders. */
export async function openFilm(browser, outDir) {
  const srv = await serve(outDir);
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(srv.url + 'index.html?t=0', { waitUntil: 'load' });
  try {
    await page.evaluate(() => window.ready);
  } catch (e) {
    errors.push(String(e));
  }
  const pageErrors = await page.evaluate(() => window.FILM_ERRORS || []).catch(() => []);
  errors.push(...pageErrors);
  if (errors.length) {
    await srv.close();
    throw new Error(`the film page has errors:\n  ${errors.slice(0, 8).join('\n  ')}`);
  }
  page.on('close', () => srv.close());
  return { page, errors, close: async () => { await page.close(); await srv.close(); } };
}

/** Render frame time t and return it as a JPEG Buffer of size w×h (the canvas is scaled when smaller). */
export async function frameJPEG(page, t, { width = 1920, height = 1080, quality = 0.95, poster = false } = {}) {
  const b64 = await page.evaluate(({ t, width, height, quality, poster }) => {
    if (poster) window.poster(); else window.renderAt(t);
    let c = document.getElementById('c');
    if (width !== c.width || height !== c.height) {
      const s = window.__scaled || (window.__scaled = document.createElement('canvas'));
      s.width = width; s.height = height;
      const x = s.getContext('2d'); x.imageSmoothingQuality = 'high'; x.drawImage(c, 0, 0, width, height);
      c = s;
    }
    return c.toDataURL('image/jpeg', quality).slice('data:image/jpeg;base64,'.length);
  }, { t, width, height, quality, poster });
  return Buffer.from(b64, 'base64');
}

/** Parse `--key value` / `--flag` options after positional arguments. */
export function parseArgs(argv) {
  const pos = [], opt = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      if (i + 1 < argv.length && !argv[i + 1].startsWith('--')) opt[key] = argv[++i]; else opt[key] = true;
    } else pos.push(a);
  }
  return { pos, opt };
}

/** "960x540" → [960, 540] (even sizes, as x264 requires). */
export function parseSize(s, def = [1920, 1080]) {
  if (!s) return def;
  const m = /^(\d+)x(\d+)$/.exec(String(s));
  if (!m) throw new Error(`bad size ${s}; expected WxH such as 960x540`);
  const w = +m[1], h = +m[2];
  if (w % 2 || h % 2 || w < 64 || h < 36) throw new Error(`size ${s}: width and height must be even and at least 64x36`);
  return [w, h];
}
