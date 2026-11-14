// Content-based freshness of committed visualization stills. No browser is needed to check it.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { ROOT, THEME_VIZ, TOKENS_CSS, FONTSOURCE } from './viz-common.mjs';

export const digest = (data) => crypto.createHash('sha256').update(data).digest('hex');
export const fileDigest = (file) => fs.existsSync(file) ? digest(fs.readFileSync(file)) : null;
export function writeChanged(file, data) {
  const bytes = Buffer.from(data);
  if (fs.existsSync(file) && fs.readFileSync(file).equals(bytes)) return false;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, bytes);
  fs.renameSync(tmp, file);
  return true;
}

export function inputKey(book, v) {
  const hash = crypto.createHash('sha256');
  const dir = path.join(book.dir, 'viz', v.id);
  const cover = path.resolve(book.dir, 'viz', v.thumbnail || `${v.id}/thumb.jpg`);
  function add(file, label) {
    if (path.resolve(file) === cover || /^(fig-.*\.jpg|\.stills\.json)$/.test(path.basename(file))) return;
    if (!fs.existsSync(file)) { hash.update(`${label}\0missing\0`); return; }
    if (fs.statSync(file).isDirectory()) {
      for (const name of fs.readdirSync(file).sort()) {
        if (['node_modules', '__pycache__', '.cache', '.git'].includes(name)) continue;
        add(path.join(file, name), `${label}/${name}`);
      }
    } else {
      hash.update(`${label}\0${fileDigest(file)}\0`);
    }
  }
  add(dir, 'page');
  add(THEME_VIZ, 'runtime');
  add(TOKENS_CSS, 'tokens');
  add(path.join(ROOT, 'trureturing.lock.json'), 'lock');
  add(path.join(ROOT, 'package-lock.json'), 'packages');
  // Common book assets may be referenced from page CSS, SVG or JavaScript.
  add(path.join(book.dir, 'assets'), 'book-assets');
  add(FONTSOURCE, 'fonts');
  for (const name of ['viz-thumbs.mjs', 'viz-still-cache.mjs', 'viz-common.mjs', 'viz-server.mjs', 'viz-testkit.mjs']) {
    add(fileURLToPath(new URL(name, import.meta.url)), `capture/${name}`);
  }
  hash.update(JSON.stringify({ schema: 1, thumbnail: v.thumbnail || null }));
  return hash.digest('hex');
}

export function readManifest(dir) {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(dir, '.stills.json'), 'utf8'));
    return data.schema === 1 && data.images && typeof data.images === 'object' ? data : { schema: 1, images: {} };
  } catch { return { schema: 1, images: {} }; }
}
export function fresh(entry, key, file) {
  return Boolean(entry && entry.input === key && entry.output && entry.output === fileDigest(file));
}
