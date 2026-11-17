// Types of the build-time module provided by setup/vite-plugins.ts.
declare module 'virtual:trureturing' {
  interface LockedDecl { name: string, kind: string, line: number, commit: string }
  const data: {
    lang: string
    book: string
    deck: string
    lock: { repo: string, commit: string, decls: Record<string, LockedDecl> } | null
    text: Record<string, any>
  }
  export default data
}
