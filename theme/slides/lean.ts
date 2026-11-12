// Lean verification state of a declaration, as recorded in trureturing.lock.json at build time.
// A GID is verified for the slides exactly when the lock resolves it to a Lean theorem; the build
// never guesses. A locked definition (or any other non-theorem) is only "defined in Lean".
import tr from 'virtual:trureturing'

export interface LeanInfo {
  gid: string
  /** the lock resolves the GID */
  locked: boolean
  /** ... to a Lean theorem: the only declarations that earn the green LEAN ✓ */
  theorem: boolean
  name: string
  kind: string
  url: string
}

/**
 * What a badge or card shows: 'lean' (green LEAN ✓) only for a locked Lean theorem; 'defined'
 * (neutral) for a locked definition or other non-theorem, and for anything marked kind="definition";
 * 'unverified' (red) for a GID the lock does not resolve; 'open' / 'argued' as the status says.
 */
export type LeanState = 'lean' | 'defined' | 'unverified' | 'open' | 'argued' | 'written-proof'

const GID_RE = /^(D[0-9]+\/S[0-9]+\/(?:[A-Za-z_][A-Za-z0-9_]*\/)*[A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][\w']*(?:\.[A-Za-z_][\w']*)*)$/

export function leanInfo(gid: string | undefined): LeanInfo {
  const id = (gid ?? '').trim()
  const decl = tr.lock?.decls[id]
  const m = GID_RE.exec(id)
  const module = m?.[1] ?? ''
  const fallback = m ? `${module.replaceAll('/', '.')}.${m[2]}` : id
  const url = decl && tr.lock
    ? `https://github.com/${tr.lock.repo}/blob/${tr.lock.commit}/${module}.lean${decl.line ? `#L${decl.line}` : ''}`
    : ''
  return { gid: id, locked: !!decl, theorem: decl?.kind === 'theorem', name: decl?.name || fallback, kind: decl?.kind ?? '', url }
}

export function leanState(info: LeanInfo, status?: string, kind?: string): LeanState {
  if (status === 'open' || status === 'argued' || status === 'written-proof')
    return status
  if (!info.locked)
    return 'unverified'
  return info.theorem && kind !== 'definition' ? 'lean' : 'defined'
}

/** The pinned trureturing commit (short) and its tree URL, or empty strings without a lock. */
export const pinned = tr.lock
  ? { short: tr.lock.commit.slice(0, 8), url: `https://github.com/${tr.lock.repo}/tree/${tr.lock.commit}`, repo: tr.lock.repo }
  : { short: '', url: '', repo: '' }
