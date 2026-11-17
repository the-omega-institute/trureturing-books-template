// Build-time data for the trureturing Slidev theme, exposed as the virtual module
// `virtual:trureturing` (typed in ../env.d.ts):
//
//   lang      edition language derived from the entry file name (slides.md → the book's first language,
//             book.toml editions[0]; slides.<lang>.md → lang)
//   book/deck from the entry path books/<slug>/slides/<deck>/
//   lock      {repo, commit, decls: {gid: {name, kind, line}}} read from trureturing.lock.json — the
//             only source that decides whether <LeanBadge> shows the green LEAN ✓
//   text      the merged i18n table for `lang` (theme/i18n/<lang>.toml overridden by i18n/<lang>.toml)
//
// It also drops the legacy `.woff`/`.ttf` fallbacks from the @fontsource and KaTeX stylesheets, so
// a build ships each self-hosted font face once (woff2 only; every browser Slidev supports reads
// woff2), and keeps Vite's dependency cache out of the deck directory.
import { basename, dirname, join, relative, sep } from 'node:path'
import { ROOT, i18n, langOfFile, loadBook, loadLock, loadSite } from '../../../tools/node/slides-lib.mjs'

const ID = 'virtual:trureturing'
const RESOLVED = `\0${ID}`
const FONT_CSS = /[\\/](?:@fontsource[\\/][^?]+|katex[\\/]dist[\\/]katex(?:\.min)?)\.css(?:\?.*)?$/
const LEGACY_FONT = /,\s*url\([^)]*\.(?:woff|ttf)\)\s*format\(['"](?:woff|truetype)['"]\)/g

interface Options { entry: string, userRoot: string }

// The book's edition languages (the site's outside a book, e.g. when previewing a template).
function languagesOf(book: string): string[] {
  try {
    return book ? loadBook(book).languages : loadSite().languages
  }
  catch {
    return loadSite().languages
  }
}

function data(entry: string) {
  const parts = relative(join(ROOT, 'books'), dirname(entry)).split(sep)
  const inBook = parts.length === 3 && parts[1] === 'slides'
  const book = inBook ? parts[0] : ''
  const deck = inBook ? parts[2] : ''
  const languages = languagesOf(book)
  const name = basename(entry)
  // slides.<lang>.md names its language even outside a book (templates/slides/slides.zh.md)
  const lang = langOfFile({ languages }, name) ?? /^slides\.([a-z]{2,3}(?:-[A-Za-z0-9]+)*)\.md$/.exec(name)?.[1] ?? languages[0] ?? 'zh'
  const lock = loadLock()
  const decls: Record<string, { name: string, kind: string, line: number, commit: string }> = {}
  for (const [gid, d] of Object.entries<any>(lock?.declarations ?? {}))
    decls[gid] = { name: String(d.name ?? ''), kind: String(d.kind ?? ''), line: Number(d.line ?? 0), commit: String(d.commit ?? lock?.commit ?? '') }
  return {
    lang,
    book,
    deck,
    lock: lock ? { repo: String(lock.repo), commit: String(lock.commit), decls } : null,
    text: i18n(lang),
  }
}

export default function setupVitePlugins(options: Options) {
  const watched = [join(ROOT, 'trureturing.lock.json'), join(ROOT, 'trureturing-lock'), join(ROOT, 'theme', 'i18n'), join(ROOT, 'i18n')]
  return [
    {
      name: 'trureturing:data',
      config() {
        const parts = relative(ROOT, options.userRoot).split(sep).filter(p => p && p !== '..')
        return { cacheDir: join(ROOT, 'node_modules', '.vite', `slidev-${parts.join('-') || 'deck'}`) }
      },
      resolveId(id: string) {
        return id === ID ? RESOLVED : undefined
      },
      load(id: string) {
        if (id !== RESOLVED)
          return undefined
        return `export default ${JSON.stringify(data(options.entry))}`
      },
      configureServer(server: any) {
        server.watcher.add(watched)
        server.watcher.on('change', (file: string) => {
          if (!watched.some(w => file === w || file.startsWith(w + sep)))
            return
          const mod = server.moduleGraph.getModuleById(RESOLVED)
          if (mod) {
            server.moduleGraph.invalidateModule(mod)
            server.ws.send({ type: 'full-reload' })
          }
        })
      },
    },
    {
      name: 'trureturing:woff2-only-fonts',
      enforce: 'pre' as const,
      transform(code: string, id: string) {
        if (!FONT_CSS.test(id))
          return undefined
        return { code: code.replace(LEGACY_FONT, ''), map: null }
      },
    },
  ]
}
