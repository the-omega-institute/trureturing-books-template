// Types of the build-time module provided by setup/vite-plugins.ts.
declare module 'virtual:trureturing' {
  interface LockedDecl { name: string, kind: string, line: number }
  const data: {
    lang: string
    book: string
    deck: string
    lock: { repo: string, commit: string, mode?: 'frozen-state' | 'lean-source', source_root?: string, decls: Record<string, LockedDecl> } | null
    text: Record<string, any>
  }
  export default data
}
