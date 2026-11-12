// Single-column research preprint. The shared model owns all text and numbering.
// The paper palette supplies ink and the two verification states; the text has no accent colour.
#import "../generated/tokens.typ": tr-paper

#let meta = json(sys.inputs.at("tr-meta", default: "/meta.json"))
#let S = meta.strings
#let cjk = meta.at("cjk", default: false)
#let ink = tr-paper.ink
#let secondary = ink.lighten(28%)
#let rule = ink.lighten(65%)
#let f-latin = ("New Computer Modern", "Libertinus Serif", "Noto Serif")
#let f-cjk = ("Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong")
#let f-body = if cjk {
  (..f-latin.map(n => (name: n, covers: "latin-in-cjk")), ..f-cjk)
} else { (..f-latin, ..f-cjk) }
#let f-mono = ("JetBrains Mono", "DejaVu Sans Mono", ..f-cjk)
#let f-symbol = ("DejaVu Sans", "Noto Sans Symbols 2", "Libertinus Serif")
#let base-size = 11pt
#let tr-fig-ext = ".print.svg"
#let page-label-at(loc) = numbering("1", ..counter(page).at(loc))

#let fit-width(body, width) = {
  let natural = measure(body)
  if natural.width > width {
    scale(x: width / natural.width * 100%, y: width / natural.width * 100%, reflow: true, body)
  } else { body }
}

#let breakable-name(name) = name.replace(".", ".\u{200B}").replace("/", "/\u{200B}").replace("_", "_\u{200B}")
#let title-text(s) = s.replace(regex("\\s*=\\s*"), "\u{A0}=\u{A0}")
#let horizontalrule = block(above: 1em, below: 1em, align(center, line(length: 25%, stroke: 0.4pt + rule)))

#let title-block() = block(width: 100%, above: 8mm, below: 9mm, {
  set align(center)
  set par(first-line-indent: 0pt, justify: false, leading: 0.45em)
  block(text(size: 22pt, hyphenate: false, title-text(meta.title)))
  if meta.subtitle != "" {
    v(5pt)
    block(text(size: 13pt, hyphenate: false, title-text(meta.subtitle)))
  }
  v(11pt)
  block(text(size: 12pt, meta.authors.join(if cjk { "、" } else { ", " })))
  v(7pt)
  block(text(size: 10pt, meta.date.iso))
})

#let abstract-block() = {
  if meta.description != "" {
    block(inset: (x: 8mm), below: 1.2em, {
      set text(size: 10pt)
      set par(first-line-indent: 0pt, justify: not cjk, leading: if cjk { 0.6em } else { 0.45em })
      align(center, text(weight: "bold", S.abstract))
      v(5pt)
      meta.description
    })
  }
}

#let publication-note() = block(inset: (x: 8mm), above: 0.6em, {
  set text(size: 8pt, fill: secondary)
  set par(first-line-indent: 0pt, justify: false, leading: 0.4em, spacing: 0.3em)
  S.verified_statement
  parbreak()
  [#S.version #meta.version]
  if meta.license != "" { [ · #meta.license] }
  if meta.trureturing.commit != "" {
    [ · #S.pinned_at: #link(meta.trureturing.url, text(font: f-mono, size: 7.5pt, meta.trureturing.short))]
  }
})

#let contents-page() = {
  block(above: 0.5em, below: 1em, text(size: 15pt, weight: "bold", S.contents))
  outline(title: none, depth: 2, indent: 1.3em)
}

#let tr-chapter(id: "", kicker: "", section: "", outlined: true, title: []) = {
  let hd = heading(level: 1, outlined: outlined, bookmarked: outlined, title)
  if id != "" [#hd#label(id)] else { hd }
}

#let tr-part(id: "", kicker: "", section: "", outlined: true, title: []) = {
  block(above: 2.2em, below: 0.8em, sticky: true, {
    let hd = heading(level: 1, outlined: outlined, bookmarked: outlined, title)
    align(center, if id != "" [#hd#label(id)] else { hd })
  })
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
        set text(size: 8pt, fill: secondary)
        set par(first-line-indent: 0pt, justify: false, leading: 0.35em)
        text(style: "italic", S.lean_label + ": ")
        for (i, e) in lean.enumerate() {
          if i > 0 { [; ] }
          let name = text(font: f-mono, size: 7.5pt, breakable-name(e.name))
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
  set text(size: if kind == "figure" { 10pt } else { 9.5pt })
  show link: it => if type(it.dest) == str and it.body == text(it.dest) {
    text(size: 7.5pt, fill: secondary, it)
  } else { it }
  body
})

#let tr-book(doc) = {
  let d = meta.date
  set document(title: meta.title, author: meta.authors, keywords: meta.keywords,
    date: datetime(year: d.year, month: d.month, day: d.day), description: meta.description)
  set page(paper: meta.at("academic_paper", default: "a4"),
    margin: 25.4mm, fill: none, numbering: "1", header: none,
    footer: context align(center, text(size: 10pt, counter(page).display("1"))),
    footer-descent: 35%)
  set text(font: f-body, size: base-size, fill: ink, lang: meta.lang,
    region: if meta.region != "" { lower(meta.region) } else { none }, hyphenate: not cjk)
  set par(justify: not cjk, leading: if cjk { 0.6em } else { 0.45em }, spacing: if cjk { 0.6em } else { 0.45em },
    first-line-indent: (amount: if cjk { 2em } else { 1.5em }, all: false))
  set raw(theme: "/_theme/typst/code-academic.tmTheme")
  show raw: set text(font: f-mono, size: 0.9em, fill: ink)
  show raw.where(block: false): it => text(font: f-mono, size: 0.9em, breakable-name(it.text))
  show raw.where(block: true): it => block(width: 100%, breakable: true, above: 0.8em, below: 0.8em,
    {
      set par(justify: false, first-line-indent: 0pt, leading: 0.4em)
      it
    })
  show math.equation: set text(font: ("New Computer Modern Math",), fallback: true)
  set math.accent(dotless: false)
  set math.mat(column-gap: 1em)
  show math.equation.where(block: true): set block(above: 0.8em, below: 0.8em)
  show math.equation.where(block: true): it => layout(size => fit-width(it, size.width))
  // Give the paragraph the fitted box width before it chooses line breaks.
  // Pandoc supplies stable identities; a precise selector avoids a quadratic width lookup.
  show math.equation.where(block: false): equation => if not equation.has("label") { equation } else { context {
    let loc = equation.location()
    let width-label = label("tr-academic-inline-measure-" + str(equation.label))
    let entry = query(width-label).find(item => item.value.loc == loc)
    let width = if entry == none { none } else { entry.value.width }
    if width != none and measure(equation).width > width { linebreak(justify: false) }
    box(width: if width == none { auto } else { width }, layout(size => {
      // Closing punctuation cannot break away from a formula. Reserve its width
      // so a nearly full-line expression does not overflow with its suffix.
      let container = if entry == none { size.width } else { calc.max(size.width, entry.value.container) }
      let target = calc.min(measure(equation).width, calc.max(1pt, container - (1em).to-absolute()))
      [#metadata((loc: loc, width: target, container: container))#width-label]
      fit-width(equation, target)
    }))
  } }
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
  show table: set text(size: 9.5pt)
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
    text(size: 10pt, {
      text(weight: "bold")[#it.supplement #context it.counter.display(it.numbering).]
      h(0.4em)
      it.body
    })
  }))

  set heading(numbering: none)
  show heading: set text(hyphenate: false)
  show heading: set par(first-line-indent: 0pt, justify: false)
  show heading.where(level: 1): it => block(above: 1.8em, below: 0.7em, sticky: true, {
    set par(leading: 0.45em)
    text(size: 15pt, weight: "bold", it.body)
  })
  show heading.where(level: 2): it => block(above: 1.6em, below: 0.7em, sticky: true,
    text(size: 12pt, weight: "bold", it.body))
  show heading.where(level: 3): it => block(above: 1.3em, below: 0.6em, sticky: true,
    text(size: 11pt, weight: "bold", it.body))
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

  title-block()
  abstract-block()
  publication-note()
  v(2em)
  contents-page()
  v(2em)
  doc
}
