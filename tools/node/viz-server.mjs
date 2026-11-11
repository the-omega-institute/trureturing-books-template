#!/usr/bin/env node
// Zero-dependency static server for book-local visualizations, laid out like the published site:
//   node tools/node/viz-server.mjs [port]          (default 8766; prints the address of every page)
// Mounts, under BASE (= /site/, so root-absolute links fail as they would on GitHub Pages under /<repo>/):
//   /site/<slug>/viz/assets/…      theme/viz/… (shared runtime) and theme/generated/tokens.css
//   /site/<slug>/viz/<id>/…        books/<slug>/viz/<id>/… (drafts too); HTML links to Lean are pinned to the lock
//   /site/<slug>/viz/              the hub, rendered by tbook.viz (Python) exactly as the build writes it
//   /__fonts/google.css            local @fontsource fonts that tests/thumbnails substitute for Google Fonts
// Adapted from trureturing-visualize/scripts/serve.mjs (Apache-2.0, the-omega-institute).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  ROOT, BOOKS, THEME_VIZ, TOKENS_CSS, RUNTIME_FILES, RESERVED, FONTSOURCE, ID_RE,
  isBook, listBooks, readRegistry, readLock, pinLinks, favicon, localFontsCss
} from './viz-common.mjs';

export const BASE = '/site/';
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
  '.woff': 'font/woff', '.txt': 'text/plain; charset=utf-8', '.wasm': 'application/wasm', '.glb': 'model/gltf-binary'
};
const typeOf = (f) => TYPES[path.extname(f).toLowerCase()] || 'application/octet-stream';

function python() {
  if (process.env.TBOOK_PYTHON) return process.env.TBOOK_PYTHON;
  const venv = path.join(ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : 'python3';
}

/** The hub of one book, rendered by tbook.viz.hub_html (the same code the build uses). */
function renderHub(slug) {
  const code = 'import sys\nfrom tbook import viz\nsys.stdout.write(viz.hub_html_for(sys.argv[1]))\n';
  const r = spawnSync(python(), ['-c', code, slug], {
    cwd: ROOT, encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.join(ROOT, 'tools'), TBOOK_ROOT: ROOT }
  });
  if (r.status === 0) return { ok: true, body: r.stdout };
  return { ok: false, body: `<!doctype html><meta charset="utf-8"><title>hub unavailable</title><pre>tbook.viz.hub_html_for(${slug}) failed:\n${String(r.stderr || r.error || '').replace(/</g, '&lt;')}</pre>` };
}

function devIndex() {
  const rows = [];
  for (const book of listBooks()) {
    let reg;
    try { reg = readRegistry(book); } catch { continue; }
    rows.push(`<h2><a href="${BASE}${book.slug}/viz/">${book.slug}/viz/</a></h2><ul>`);
    for (const v of reg.visualizations || []) rows.push(`<li><a href="${BASE}${book.slug}/viz/${v.id}/">${v.id}</a> · ${v.status} · ${String(v.title || '').replace(/</g, '&lt;')}</li>`);
    rows.push('</ul>');
  }
  return `<!doctype html><meta charset="utf-8"><title>viz dev server</title><body style="font-family:sans-serif;background:#111;color:#ddd">${rows.join('\n') || '<p>no book has a viz/ registry</p>'}</body>`;
}

/** Resolve a request path to { file } | { body, type } | { redirect } | null (404). */
export function route(pathname) {
  if (pathname === '/' || pathname === BASE.slice(0, -1)) return { redirect: BASE };
  if (pathname === BASE) return { body: devIndex(), type: TYPES['.html'] };
  // fonts may be requested from other local origins (e.g. a built _site served elsewhere), hence CORS
  if (pathname === '/__fonts/google.css') return { body: localFontsCss('/__fonts/'), type: TYPES['.css'], cors: true };
  if (pathname.startsWith('/__fonts/')) {
    const file = path.resolve(FONTSOURCE, pathname.slice('/__fonts/'.length));
    return file.startsWith(FONTSOURCE + path.sep) ? { file, cors: true } : null;
  }
  if (!pathname.startsWith(BASE)) return null;
  const parts = pathname.slice(BASE.length).split('/');
  const [slug, viz, ...rest] = parts;
  if (!slug || viz !== 'viz' || !isBook(slug)) return null; // a hidden book is absent here too
  if (parts.length === 2) return { redirect: `${BASE}${slug}/viz/` };
  const tail = rest.join('/');
  if (tail === '' || tail === 'index.html') return { hub: slug };
  if (rest[0] === 'assets') {
    const name = rest.slice(1).join('/');
    if (name === 'trureturing.json') {
      const lock = readLock();
      return lock ? { body: JSON.stringify(lock), type: TYPES['.json'] } : null;
    }
    if (name === 'tokens.css') return { file: TOKENS_CSS };
    if (name === 'favicon.svg') return { body: favicon(), type: TYPES['.svg'] };
    if (RUNTIME_FILES.includes(name) || name.startsWith('vendor/')) {
      const file = path.resolve(THEME_VIZ, name);
      return file.startsWith(THEME_VIZ + path.sep) ? { file } : null;
    }
    return null;
  }
  if (!ID_RE.test(rest[0]) || RESERVED.includes(rest[0])) return null;
  const base = path.join(BOOKS, slug, 'viz');
  let file = path.resolve(base, tail);
  if (!file.startsWith(base + path.sep)) return null;
  if (tail.endsWith('/') || rest.length === 1) {
    if (rest.length === 1 && !tail.endsWith('/')) return { redirect: `${pathname}/` };
    file = path.join(file, 'index.html');
  }
  return { file, pin: file.endsWith('.html') };
}

export function createServer() {
  return http.createServer((req, res) => {
    let url;
    try { url = new URL(req.url, 'http://localhost'); } catch { res.writeHead(400); res.end(); return; }
    let r;
    try { r = route(decodeURIComponent(url.pathname)); } catch { r = null; }
    const send404 = () => { res.writeHead(404, { 'content-type': TYPES['.txt'] }); res.end(`404 ${url.pathname}\n`); };
    if (!r) return send404();
    if (r.redirect) { res.writeHead(302, { location: r.redirect + url.search }); res.end(); return; }
    if (r.hub) {
      const hub = renderHub(r.hub);
      res.writeHead(hub.ok ? 200 : 500, { 'content-type': TYPES['.html'], 'cache-control': 'no-cache' });
      res.end(hub.body);
      return;
    }
    const cors = r.cors ? { 'access-control-allow-origin': '*' } : {};
    if (r.body !== undefined) { res.writeHead(200, { 'content-type': r.type, 'cache-control': 'no-cache', ...cors }); res.end(r.body); return; }
    fs.stat(r.file, (err, st) => {
      if (err || !st.isFile()) return send404();
      const headers = { 'content-type': typeOf(r.file), 'cache-control': 'no-cache', ...cors };
      if (r.pin) {
        res.writeHead(200, headers);
        res.end(pinLinks(fs.readFileSync(r.file, 'utf8'), readLock()));
        return;
      }
      res.writeHead(200, headers);
      fs.createReadStream(r.file).pipe(res);
    });
  });
}

/** Start on 127.0.0.1 (port 0 = any free port); resolves to { server, origin }. */
export async function startServer(port = 0) {
  const server = createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  return { server, origin: `http://127.0.0.1:${server.address().port}` };
}

/** Address of a visualization page on a running server. */
export function vizUrl(origin, slug, id, query = '') {
  const q = query ? (query.startsWith('?') ? query : `?${query}`) : '';
  return `${origin}${BASE}${slug}/viz/${id ? `${id}/` : ''}${q}`;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.argv[2] || process.env.PORT || 8766);
  const { origin } = await startServer(port);
  console.log(`serving book visualizations at ${origin}${BASE}`);
  for (const book of listBooks()) {
    let reg;
    try { reg = readRegistry(book); } catch { continue; }
    console.log(`  ${vizUrl(origin, book.slug, '')}  (hub)`);
    for (const v of reg.visualizations || []) console.log(`  ${vizUrl(origin, book.slug, v.id)}  ${v.status}`);
  }
}
