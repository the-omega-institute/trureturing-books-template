// Scholarly monograph layout. All theorem text and numbering come from the shared model.
// The paper palette supplies ink and the two verification states; the text has no accent colour.
#import "../generated/tokens.typ": tr-paper

#let meta = json(sys.inputs.at("tr-meta", default: "/meta.json"))
#let S = meta.strings
#let cjk = meta.at("cjk", default: false)
#let ink = tr-paper.ink
#let secondary = ink.lighten(28%)
#let rule = ink.lighten(65%)
#let f-latin = ("Libertinus Serif", "New Computer Modern", "Noto Serif")
#let f-cjk = ("Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong")
#let f-body = if cjk {
  (..f-latin.map(n => (name: n, covers: "latin-in-cjk")), ..f-cjk)
} else { (..f-latin, ..f-cjk) }
#let f-mono = ("JetBrains Mono", "DejaVu Sans Mono", ..f-cjk)
#let f-symbol = ("DejaVu Sans", "Noto Sans Symbols 2", "Libertinus Serif")
#let base-size = 10.5pt
#let tr-fig-ext = ".print.svg"
#let chapter-start = <tr-academic-chapter-start>
#let chapter-end = <tr-academic-chapter-end>
#let main-start = <tr-academic-main-start>
#let in-main() = {
  let starts = query(main-start)
  starts.len() > 0 and here().page() >= starts.first().location().page()
}
#let page-label-at(loc) = {
  let starts = query(main-start)
  let style = if starts.len() > 0 and loc.page() >= starts.first().location().page() { "1" } else { "i" }
  numbering(style, ..counter(page).at(loc))
}
#let folio-numbering(n) = context numbering(if in-main() { "1" } else { "i" }, n)
#let main-boundary() = {
  [#metadata("main")#main-start]
  context {
    if query(main-start).first().location().page() == here().page() { counter(page).update(1) }
  }
}

#let fit-width(body, width) = {
  let natural = measure(body)
  if natural.width > width {
    scale(x: width / natural.width * 100%, y: width / natural.width * 100%, reflow: true, body)
  } else { body }
}

#let breakable-name(name) = name.replace(".", ".\u{200B}").replace("/", "/\u{200B}").replace("_", "_\u{200B}")
#let title-text(s) = s.replace(regex("\\s*=\\s*"), "\u{A0}=\u{A0}")
#let horizontalrule = block(above: 1em, below: 1em, align(center, line(length: 25%, stroke: 0.4pt + rule)))

#let new-recto() = {
  [#metadata("end")#chapter-end]
  pagebreak(weak: true, to: "odd")
}

#let on-opener-page() = {
  let pg = here().page()
  query(chapter-start).any(m => m.location().page() == pg)
}

#let on-blank-page() = {
  let pg = here().page()
  let last-end = none
  let blank = false
  for m in query(selector(chapter-end).or(chapter-start)) {
    if m.value == "end" { if last-end == none { last-end = m.location().page() } } else {
      if last-end != none and last-end < pg and pg < m.location().page() { blank = true }
      last-end = none
    }
  }
  blank
}

#let running-header = context {
  if not in-main() or on-opener-page() or on-blank-page() { return }
  let before = query(heading.where(level: 1).before(here()))
  let chapter = if before.len() > 0 { before.last().body } else { [] }
  let folio = text(size: 8.5pt, counter(page).display(here().page-numbering()))
  let title = text(size: 7.5pt, style: if cjk { "normal" } else { "italic" },
    if calc.even(here().page()) { meta.title } else { chapter })
  set par(justify: false, first-line-indent: 0pt, leading: 0.25em)
  if calc.even(here().page()) {
    grid(columns: (auto, 1fr), column-gutter: 12pt, align: (left, right), folio, title)
  } else {
    grid(columns: (1fr, auto), column-gutter: 12pt, align: (left, right), title, folio)
  }
}

#let opening-footer = context {
  if not on-blank-page() and (not in-main() or on-opener-page()) {
    align(center, text(size: 9pt, counter(page).display(here().page-numbering())))
  }
}

#let front-footer = context {
  if not on-blank-page() {
    align(center, text(size: 9pt, counter(page).display(here().page-numbering())))
  }
}

#let title-page() = page(header: none, footer: none, {
  set par(first-line-indent: 0pt, justify: false, leading: 0.45em)
  v(14mm)
  block(text(size: 14pt, meta.authors.join(if cjk { "、" } else { ", " })))
  v(19mm)
  block(text(size: if cjk { 27pt } else { 28pt }, weight: "bold", hyphenate: false, title-text(meta.title)))
  if meta.subtitle != "" {
    v(10mm)
    block(text(size: 14pt, hyphenate: false, title-text(meta.subtitle)))
  }
  v(1fr)
  block(text(size: 10pt, meta.publisher))
  v(3mm)
  block(text(size: 9pt, fill: secondary, [#S.lang_name · #meta.date.year]))
  v(9mm)
})

#let colophon-page() = page(header: none, footer: none, {
  set par(first-line-indent: 0pt, justify: false, leading: 0.45em, spacing: 0.6em)
  set text(size: 8.5pt)
  v(1fr)
  block(text(weight: "bold", meta.title))
  if meta.subtitle != "" { block(meta.subtitle) }
  block(meta.authors.join(if cjk { "、" } else { ", " }))
  v(5mm)
  block([#S.variant_academic · #S.version #meta.version · #meta.date.iso])
  if meta.isbn != "" { block([#S.isbn: #meta.isbn]) }
  if meta.license != "" { block([#S.license: #meta.license]) }
  v(4mm)
  block(S.verified_statement)
  if S.open_statement != "" { block(S.open_statement) }
  if meta.trureturing.commit != "" {
    block([#S.pinned_at: #link(meta.trureturing.url, text(font: f-mono, size: 7.6pt, meta.trureturing.short))])
  }
  if meta.online_url != "" { block([#S.online: #link(meta.online_url)]) }
  if meta.repo_url != "" { block([#S.source: #link(meta.repo_url)]) }
  v(5mm)
  block(text(size: 7.5pt, fill: secondary, S.typeset_value))
  v(6mm)
})

#let abstract-page() = {
  if meta.description != "" {
    block(above: 7mm, below: 8mm, text(size: 18pt, weight: "bold", S.abstract))
    set par(first-line-indent: 0pt)
    meta.description
    pagebreak()
  }
}

#let contents-page() = {
  block(above: 7mm, below: 9mm, text(size: 18pt, weight: "bold", S.contents))
  outline(title: none, depth: 2, indent: 1.3em)
}

#let tr-chapter(id: "", kicker: "", section: "", outlined: true, title: []) = {
  new-recto()
  [#metadata(section)#chapter-start]
  if section != "prefix" { main-boundary() }
  v(10mm)
  let hd = heading(level: 1, outlined: outlined, bookmarked: outlined, title)
  if id != "" [#hd#label(id)] else { hd }
  v(8mm)
}

#let tr-part(id: "", kicker: "", section: "", outlined: true, title: []) = {
  new-recto()
  [#metadata("part")#chapter-start]
  main-boundary()
  v(1fr)
  let hd = heading(level: 1, outlined: outlined, bookmarked: outlined, title)
  align(center, if id != "" [#hd#label(id)] else { hd })
  v(2fr)
  pagebreak(weak: true)
}

#let tr-env(kind: "", status: "", label: "", number: "", ref: "", title: none,
  badge: "", badge-url: "", lean: (), id: "", body) = {
  block(width: 100%, above: 1.15em, below: 1em, breakable: true, {
    set par(first-line-indent: 0pt)
    block(below: 0.4em, sticky: true, {
      text(weight: "bold", ref)
      if title != none { text([#S.title_open#title#S.title_close]) }
      if badge != "" {
        h(0.7em)
        let mark = box(text(size: 7pt,
          fill: if status == "lean" { tr-paper.ok } else if status == "open" { tr-paper.warn } else { secondary }, badge))
        if badge-url != "" { link(badge-url, mark) } else { mark }
      }
    })
    {
      set text(style: if not cjk and kind in ("theorem", "lemma", "proposition", "corollary") { "italic" } else { "normal" })
      body
    }
    if lean.len() > 0 {
      block(above: 0.45em, {
        set text(size: 7pt, fill: secondary)
        set par(first-line-indent: 0pt, justify: false, leading: 0.35em)
        text(style: "italic", S.lean_label + ": ")
        for (i, e) in lean.enumerate() {
          if i > 0 { [; ] }
          let name = text(font: f-mono, size: 6.7pt, breakable-name(e.name))
          if e.url != "" { link(e.url, name) } else { name }
        }
      })
    }
  })
}

#let tr-proof-label(label) = text(style: if cjk { "normal" } else { "italic" }, [#label#if not cjk { [.] }#h(0.4em)])
#let tr-qed() = { h(1fr); text(font: f-symbol, size: 0.85em)[□] }
#let tr-proof(label: "", id: "", body) = block(width: 100%, above: 0.6em, below: 1em, breakable: true, {
  set par(first-line-indent: 0pt)
  body
})

#let tr-media(kind: "media", body) = block(width: 100%, above: 1.2em, below: 1.2em, breakable: true, {
  set par(first-line-indent: 0pt, justify: false, leading: 0.45em, spacing: 0.5em)
  set text(size: if kind == "figure" { 8.5pt } else { 9pt })
  show link: it => if type(it.dest) == str and it.body == text(it.dest) {
    text(size: 7.5pt, fill: secondary, it)
  } else { it }
  body
})

#let tr-book(doc) = {
  let d = meta.date
  set document(title: meta.title, author: meta.authors, keywords: meta.keywords,
    date: datetime(year: d.year, month: d.month, day: d.day), description: meta.description)
  set page(paper: meta.at("academic_paper", default: "iso-b5"),
    margin: (inside: 23mm, outside: 19mm, top: 23mm, bottom: 23mm),
    fill: none, numbering: "i", header: none, footer: none, header-ascent: 35%, footer-descent: 35%)
  set text(font: f-body, size: base-size, fill: ink, lang: meta.lang,
    region: if meta.region != "" { lower(meta.region) } else { none }, hyphenate: not cjk)
  set par(justify: true, leading: if cjk { 0.65em } else { 0.48em }, spacing: 0.35em,
    first-line-indent: (amount: if cjk { 2em } else { 1em }, all: false))
  set raw(theme: "/_theme/typst/code-academic.tmTheme")
  show raw: set text(font: f-mono, size: 0.84em, fill: ink)
  show raw.where(block: false): it => text(font: f-mono, size: 0.84em, breakable-name(it.text))
  show raw.where(block: true): it => block(width: 100%, breakable: true, above: 0.8em, below: 0.8em,
    inset: (left: 8pt), stroke: (left: 0.5pt + rule), {
      set par(justify: false, first-line-indent: 0pt, leading: 0.4em)
      it
    })
  show math.equation: set text(font: ("New Computer Modern Math",), fallback: true)
  set math.accent(dotless: false)
  set math.mat(column-gap: 1em)
  show math.equation.where(block: true): set block(above: 0.8em, below: 0.8em)
  show math.equation.where(block: true): it => layout(size => fit-width(it, size.width))
  show link: set text(fill: ink)
  set footnote.entry(separator: line(length: 25%, stroke: 0.4pt + rule), gap: 0.5em, indent: 0em)
  show footnote.entry: set text(size: 8pt)
  show footnote.entry: set par(first-line-indent: 0pt, leading: 0.4em)
  set list(marker: ([•], [–]), indent: 0.2em, body-indent: 0.65em, spacing: 0.35em)
  set enum(indent: 0pt, body-indent: 0.65em, spacing: 0.35em)
  show list: set par(first-line-indent: 0pt)
  show enum: set par(first-line-indent: 0pt)
  show terms.item: it => block(above: 0.6em, {
    set par(first-line-indent: 0pt)
    strong(it.term)
    block(inset: (left: 1em), it.description)
  })
  show quote.where(block: true): it => block(inset: (x: 1.3em), above: 0.9em, below: 0.9em, {
    set text(size: 0.94em, style: if cjk { "normal" } else { "italic" })
    set par(first-line-indent: 0pt)
    it.body
  })

  set table(stroke: none, inset: (x: 4pt, y: 4pt), fill: none)
  set table.hline(stroke: 0.4pt + rule)
  show table: set text(size: 8.6pt)
  show table: set align(start)
  show table: set par(justify: false, first-line-indent: 0pt, leading: 0.35em)
  show table: it => block(stroke: (top: 0.6pt + ink, bottom: 0.6pt + ink), inset: (y: 3pt), {
    show raw.where(block: false): code => text(code.text.clusters().join("\u{200B}"))
    show table.cell: cell => layout(size => {
      show math.equation.where(block: false): equation => fit-width(equation, size.width)
      cell
    })
    it
  })
  show table.cell.where(y: 0): set text(weight: "bold")
  show figure.where(kind: table): set figure.caption(position: top)
  show figure.where(kind: table): set block(breakable: true)
  show figure.where(kind: image): it => block(width: 100%, above: 1em, below: 0.6em, breakable: false, {
    set par(first-line-indent: 0pt, justify: false)
    align(center, it.body)
    if it.caption != none { v(5pt); it.caption }
  })
  show figure.caption: it => align(left, block({
    set par(first-line-indent: 0pt, justify: false, leading: 0.4em)
    text(size: 8.5pt, {
      text(weight: "bold")[#it.supplement #context it.counter.display(it.numbering).]
      h(0.4em)
      it.body
    })
  }))

  set heading(numbering: none)
  show heading: set text(hyphenate: false)
  show heading: set par(first-line-indent: 0pt, justify: false)
  show heading.where(level: 1): it => block(below: 0pt, {
    set par(leading: 0.45em)
    text(size: if cjk { 21pt } else { 22pt }, weight: "bold", it.body)
  })
  show heading.where(level: 2): it => block(above: 1.6em, below: 0.7em, sticky: true,
    text(size: 13pt, weight: "bold", it.body))
  show heading.where(level: 3): it => block(above: 1.3em, below: 0.6em, sticky: true,
    text(size: 11.5pt, weight: "bold", it.body))
  show heading.where(level: 4): it => block(above: 1.1em, below: 0.5em, sticky: true,
    text(size: 10.5pt, weight: "bold", it.body))
  show heading.where(level: 5): it => block(above: 1em, below: 0.4em, sticky: true,
    text(size: 10.5pt, style: if cjk { "normal" } else { "italic" }, it.body))
  set outline.entry(fill: repeat([.], gap: 0.2em))
  show outline.entry: it => context {
    set par(first-line-indent: 0pt, justify: false)
    set text(size: if it.level == 1 { 10pt } else { 9pt }, weight: if it.level == 1 { "bold" } else { "regular" }, hyphenate: false)
    let target = it.element.location()
    block(above: if it.level == 1 { 0.8em } else { 0pt }, below: 0.3em,
      link(target, it.indented(it.prefix(), [#it.body() #box(width: 1fr, it.fill) #sym.wj#box(page-label-at(target))])))
  }

  title-page()
  colophon-page()
  set page(footer: front-footer)
  counter(page).update(1)
  abstract-page()
  contents-page()
  [#metadata("end")#chapter-end]
  pagebreak(weak: true, to: "odd")
  set page(numbering: folio-numbering, header: running-header, footer: opening-footer)
  doc
}
