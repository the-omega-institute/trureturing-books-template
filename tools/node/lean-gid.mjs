// Lean source GIDs and permalinks shared by visualization tools and the Slidev theme.
export const GID_RE = /^(D[0-9]+\/S[0-9]+\/(?:[A-Za-z_][A-Za-z0-9_]*\/)*[A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*)$/;

// The identifier ranges match tbook.lean.is_identifier.
const ID_START = 'A-Za-z_α-κμ-ωΑ-ΟΡΤ-Ω\\u03ca-\\u03fb\\u1f00-\\u1ffe\\u2100-\\u214f\\u{1d49c}-\\u{1d59f}';
const IDENTIFIER = `[${ID_START}][${ID_START}0-9'!?₀-₉ₐ-ₜᵢ-ᵪ]*`;
const MODULE_COMPONENT = new RegExp(`^${IDENTIFIER}$`, 'u');
const NAME_COMPONENT = `(?:${IDENTIFIER}|«[^«»]+»)`;
const NAME = new RegExp(`^${NAME_COMPONENT}(?:\\.${NAME_COMPONENT})*$`, 'u');

export function parseGid(gid, lock = null) {
  const text = String(gid || '').trim();
  const mode = lock?.mode || 'frozen-state';
  if (mode === 'frozen-state') {
    const match = GID_RE.exec(text);
    return match ? { module: match[1], name: match[2] } : null;
  }
  if (mode !== 'lean-source' || /[\s,]/u.test(text)) return null;
  const slash = text.lastIndexOf('/');
  const dot = text.indexOf('.', slash + 1);
  if (dot <= slash + 1 || dot === text.length - 1) return null;
  const module = text.slice(0, dot);
  const name = text.slice(dot + 1);
  return module.split('/').every((part) => MODULE_COMPONENT.test(part)) && NAME.test(name)
    ? { module, name }
    : null;
}

export function blobUrl(lock, path, line = 0) {
  if (lock.mode === 'lean-source' || lock.source_root) {
    path = path.split('/').map(encodeURIComponent).join('/');
  }
  return `https://github.com/${lock.repo}/blob/${lock.commit}/${path}${line ? `#L${line}` : ''}`;
}

export function sourceUrl(lock, module, line = 0) {
  const root = lock.source_root?.replace(/\/+$/, '');
  return blobUrl(lock, `${root ? `${root}/` : ''}${module}.lean`, line);
}
