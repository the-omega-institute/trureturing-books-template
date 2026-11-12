// theme/typst/cover.typ — the trureturing cyberpunk book cover.
//
// `tr-cover(meta, variant: "screen" | "print" | "academic")` fills the current container (use a page
// with zero margins). Everything is drawn in Typst: void background, aurora glows, a neon
// perspective grid under a striped horizon sun, scanlines, a cut-corner frame, the book
// code CODE//NAME with a chromatic glitch, title, subtitle, authors, the edition language
// tag, a LEAN ✓ <N> stamp (N = formal environments) and the pinned trureturing commit.
// "print" keeps the same composition on white paper with the darkened paper accents.
//
// `meta` is the JSON written by tools/tbook/pandoc.py (book_meta); tools/tbook/cover.py
// renders the cover alone (PNG 1600×2560 for EPUB and book cards, PDF, SVG) and
// theme/typst/book.typ draws it as the first page of the PDF. Colours come only from
// theme/generated/tokens.typ.

#import "../generated/tokens.typ": tr-screen, tr-paper

#let cover-display = ("Chakra Petch", "Inter", "DejaVu Sans")
#let cover-cjk-sans = ("Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "PingFang SC", "WenQuanYi Zen Hei")
#let cover-mono = ("JetBrains Mono", "DejaVu Sans Mono", ..cover-cjk-sans)

// A small "signal meter" drawn with boxes (no glyph fallbacks): `on` lit of `n` cells.
#let meter(on, n, size, lit, dark) = box(baseline: 0.1em, stack(dir: ltr, spacing: size * 0.35,
  ..range(n).map(i => box(width: size * 0.42, height: size * 0.8,
    fill: if i < on { lit } else { none }, stroke: 0.5pt + (if i < on { lit } else { dark })))))
#let cover-heading(cjk) = if cjk {
  ((name: "Chakra Petch", covers: "latin-in-cjk"), (name: "Inter", covers: "latin-in-cjk"), ..cover-cjk-sans, "DejaVu Sans")
} else { (..cover-display, ..cover-cjk-sans) }

// Text scaled so that its natural width is `width` (capped at `max`).
#let fit-size(body-fn, width, max) = {
  let probe = measure(body-fn(10pt))
  if probe.width == 0pt { max } else { calc.min(max, 10pt * (width / probe.width)) }
}

#let tr-cover(meta, variant: "screen") = layout(size => {
  let W = size.width
  let H = size.height
  let dark = variant == "screen"
  let pal = if dark { tr-screen } else { tr-paper }
  let S = meta.strings
  let cjk = meta.at("cjk", default: false)
  let u = W / 100
  let horizon = H * 0.665
  let cx = W / 2
  let fade(c, pct) = c.transparentize(pct)
  // independent of the book's paragraph settings (indent, justification, CJK spacing)
  set par(first-line-indent: 0pt, justify: false, spacing: 0.6em)
  set text(hyphenate: false)

  if variant == "academic" {
    place(rect(width: W, height: H, fill: pal.void))
    place(dx: W * 0.13, dy: H * 0.15, block(width: W * 0.75, height: H * 0.72, {
      set par(first-line-indent: 0pt, justify: false, leading: 0.45em)
      set text(font: ("Libertinus Serif", "New Computer Modern", "Noto Serif CJK SC", "Noto Serif SC"), fill: pal.ink)
      block(text(size: W * 0.028, meta.authors.join(", ")))
      v(H * 0.08)
      block(text(size: W * 0.056, weight: "bold", meta.title))
      v(H * 0.035)
      block(text(size: W * 0.027, meta.subtitle.replace(regex("\\s*=\\s*"), "\u{A0}=\u{A0}")))
      v(1fr)
      block(text(size: W * 0.021, meta.publisher))
      v(H * 0.012)
      block(text(size: W * 0.018, [#S.lang_name · #meta.date.year]))
    }))
    return
  }
  // ---------------------------------------------------------------- background
  if dark {
    place(rect(width: W, height: H, fill: pal.void-deep))
    place(rect(width: W, height: H, fill: gradient.radial(
      (fade(pal.cyan, 86%), 0%), (fade(pal.cyan, 100%), 100%), center: (50%, 40%), radius: 62%)))
    place(rect(width: W, height: H, fill: gradient.radial(
      (fade(pal.magenta, 84%), 0%), (fade(pal.magenta, 100%), 100%), center: (88%, 100%), radius: 70%)))
  } else {
    place(rect(width: W, height: H, fill: gradient.linear(
      (pal.void, 0%), (pal.void, 55%), (pal.void-deep, 100%), angle: 90deg)))
  }

  // ---------------------------------------------------------------- horizon sun
  // The sun is drawn as horizontal bands of one gradient disc, leaving gaps that thicken
  // towards the horizon (the gaps show whatever lies behind, so nothing overhangs).
  let sun-r = W * 0.27
  let sun = circle(radius: sun-r, fill: gradient.linear(
    (fade(pal.magenta, if dark { 40% } else { 70% }), 0%),
    (fade(pal.cyan, if dark { 62% } else { 82% }), 100%), angle: 90deg))
  let sun-top = horizon - sun-r
  let cuts = range(6).map(i => {
    let y = horizon - sun-r * (0.08 + 0.085 * i)
    let h = sun-r * (0.045 - 0.006 * i)
    (y - h / 2, y + h / 2)
  }).rev()
  let edges = (sun-top,) + cuts.map(c => c).flatten() + (horizon,)
  for b in range(calc.div-euclid(edges.len(), 2)) {
    let y0 = edges.at(2 * b)
    let y1 = edges.at(2 * b + 1)
    place(dx: cx - sun-r, dy: y0, box(width: 2 * sun-r, height: y1 - y0, clip: true,
      move(dy: sun-top - y0, sun)))
  }

  // ---------------------------------------------------------------- perspective grid
  let floor-h = H - horizon
  place(dy: horizon, rect(width: W, height: floor-h, fill: gradient.linear(
    (fade(pal.cyan, if dark { 94% } else { 96% }), 0%), (fade(pal.void-deep, if dark { 0% } else { 100% }), 100%),
    angle: 90deg)))
  let rows = 14
  for k in range(1, rows + 1) {
    let tt = k / rows
    let y = horizon + floor-h * calc.pow(tt, 2.1)
    let alpha = 100% - (18% + 52% * tt) * (if dark { 1 } else { 0.8 })
    place(line(start: (0pt, y), end: (W, y), stroke: (paint: fade(pal.cyan, alpha), thickness: 0.35pt + 0.9pt * tt)))
  }
  let cols = 13
  for j in range(-cols, cols + 1) {
    let xb = cx + j * W * 0.16
    place(line(start: (cx, horizon), end: (xb, H), stroke: (
      paint: fade(pal.cyan, if dark { 55% } else { 65% }), thickness: 0.55pt)))
  }
  // fade the far end of the grid into the horizon
  place(dy: horizon, rect(width: W, height: floor-h * 0.16, fill: gradient.linear(
    (if dark { pal.void-deep } else { pal.void }, 0%), (fade(if dark { pal.void-deep } else { pal.void }, 100%), 100%),
    angle: 90deg)))
  // darken the nearest rows so the authors, stamp and commit stay readable
  let base = if dark { pal.void-deep } else { pal.void }
  place(dy: H * 0.72, rect(width: W, height: H * 0.28, fill: gradient.linear(
    (fade(base, 100%), 0%), (fade(base, if dark { 45% } else { 35% }), 55%), (fade(base, if dark { 25% } else { 20% }), 100%),
    angle: 90deg)))
  // horizon line with a soft glow
  for (th, a) in ((7pt, 92%), (3.5pt, 82%), (1.2pt, 20%)) {
    place(line(start: (0pt, horizon), end: (W, horizon), stroke: (paint: gradient.linear(
      (fade(pal.magenta, a), 0%), (fade(pal.cyan, a), 50%), (fade(pal.magenta, a), 100%)), thickness: th)))
  }

  // ---------------------------------------------------------------- scanlines
  if dark {
    place(rect(width: W, height: H, fill: tiling(size: (6pt, 2.4pt),
      place(rect(width: 6pt, height: 0.6pt, fill: white.transparentize(95%))))))
  }

  // ---------------------------------------------------------------- frame
  let m = 5 * u
  let c = 4.5 * u
  place(polygon(stroke: 0.6pt + (if dark { pal.line-hot } else { pal.panel-edge }),
    (m, m), (W - m - c, m), (W - m, m + c), (W - m, H - m), (m + c, H - m), (m, H - m - c)))
  // corner ticks
  let tick = 6 * u
  for (x, y, dx, dy) in ((m, m, 1, 0), (m, m, 0, 1), (W - m, H - m, -1, 0), (W - m, H - m, 0, -1)) {
    place(line(start: (x, y), end: (x + dx * tick, y + dy * tick), stroke: 1.6pt + pal.cyan))
  }
  place(line(start: (W - m - c, m), end: (W - m, m + c), stroke: 1.6pt + pal.magenta))

  // ---------------------------------------------------------------- top strip
  let ink = pal.ink
  let mono(sz, fill, body) = text(font: cover-mono, size: sz, fill: fill, tracking: 0.12em, body)
  place(dx: m + 3 * u, dy: m + 3.2 * u, mono(2.1 * u, pal.cyan, upper(S.series)))
  let tag = box(stroke: 0.7pt + pal.magenta, inset: (x: 1.2 * u, y: 0.8 * u),
    mono(2.1 * u, pal.magenta, [#S.lang_short #text(fill: pal.dim)[· #S.lang_name]]))
  place(top + right, dx: -(m + 6.5 * u), dy: m + 2.3 * u, tag)
  place(dx: m + 3 * u, dy: m + 6.6 * u, line(length: W - 2 * m - 6 * u, stroke: 0.4pt + pal.panel-edge))

  // ---------------------------------------------------------------- book code with glitch
  let code = meta.code
  let code-parts = code.split("//")
  let code-body(sz, fill-a, fill-b) = text(font: cover-display, weight: 700, size: sz, tracking: 0.04em, {
    if code-parts.len() > 1 {
      text(fill: fill-a, code-parts.first())
      text(fill: fill-b, "//")
      text(fill: fill-a, code-parts.slice(1).join("//"))
    } else { text(fill: fill-a, code) }
  })
  let code-w = W - 2 * m - 8 * u
  let csz = fit-size(sz => code-body(sz, ink, ink), code-w, 12 * u)
  let code-y = m + 10.5 * u
  let off = 0.55 * u
  place(dx: m + 3 * u - off, dy: code-y, code-body(csz, fade(pal.cyan, 35%), fade(pal.cyan, 35%)))
  place(dx: m + 3 * u + off, dy: code-y + off * 0.3, code-body(csz, fade(pal.magenta, 30%), fade(pal.magenta, 30%)))
  place(dx: m + 3 * u, dy: code-y, code-body(csz, ink, pal.magenta))
  // displaced slices (the "glitch")
  let ch = measure(code-body(csz, ink, ink)).height
  for (top, hh, dx, col) in ((0.22, 0.13, 1.6, pal.cyan), (0.63, 0.09, -1.1, pal.magenta)) {
    place(dx: m + 3 * u + dx * u, dy: code-y + ch * top, box(height: ch * hh, clip: true,
      move(dy: -ch * top, code-body(csz, col, col))))
  }
  // thin data line under the code
  let data-y = code-y + ch + 2.4 * u
  place(dx: m + 3 * u, dy: data-y, mono(1.8 * u, pal.dim,
    [v#meta.version #h(1.2 * u) #meter(3, 5, 1.8 * u, pal.line-hot, pal.faint) #h(1.2 * u) #meta.date.iso]))

  // ---------------------------------------------------------------- title block
  let title-font = cover-heading(cjk)
  let tw = W - 2 * m - 10 * u
  let title-size = if cjk { 7.4 * u } else { 7.0 * u }
  let title-y = H * 0.235
  place(dx: m + 3 * u, dy: title-y, block(width: tw, {
    set par(leading: if cjk { 0.42em } else { 0.32em }, justify: false)
    text(font: title-font, weight: 700, size: title-size, fill: ink, hyphenate: false, meta.title)
    if meta.subtitle != "" {
      v(2.6 * u)
      block(width: tw * 0.92, {
        set par(leading: 0.55em)
        text(font: title-font, weight: 400, size: if cjk { 2.9 * u } else { 2.8 * u }, fill: pal.sigma, meta.subtitle)
      })
    }
    v(2.4 * u)
    box(width: 9 * u, height: 0.45 * u, fill: pal.magenta)
    h(0.8 * u)
    box(width: 2 * u, height: 0.45 * u, fill: pal.cyan)
  }))

  // ---------------------------------------------------------------- authors + publisher
  let authors = meta.authors.join(if cjk { "、" } else { ", " })
  place(dx: m + 3 * u, dy: H * 0.775, block(width: W * 0.5, {
    set par(leading: 0.5em)
    text(font: title-font, weight: 600, size: 2.9 * u, fill: ink, authors)
    v(0.6 * u)
    mono(1.7 * u, pal.dim, meta.publisher)
  }))

  // ---------------------------------------------------------------- LEAN ✓ stamp
  let ok = pal.ok
  let stamp = box(stroke: 1.1pt + ok, inset: 0.7 * u, box(stroke: 0.5pt + ok, inset: (x: 2 * u, y: 1.4 * u),
    fill: if dark { fade(pal.void-deep, 25%) } else { pal.void }, align(center, {
      text(font: cover-display, weight: 700, size: 4.6 * u, fill: ok, tracking: 0.06em)[LEAN ✓ #meta.formal_count]
      v(0.4 * u, weak: true)
      text(font: title-font, size: 1.55 * u, fill: ok, tracking: 0.08em, upper(S.stamp_caption))
    })))
  place(top + right, dx: -(m + 4 * u), dy: H * 0.755, rotate(-7deg, reflow: true, stamp))

  // ---------------------------------------------------------------- bottom strip
  let commit = meta.trureturing.short
  place(dx: m + 3 * u, dy: H - m - 5.2 * u, line(length: W - 2 * m - 6 * u, stroke: 0.4pt + pal.panel-edge))
  place(dx: m + 3 * u, dy: H - m - 4 * u, mono(1.75 * u, pal.dim, {
    [#S.pinned_short #text(fill: pal.cyan)[#meta.trureturing.repo.split("/").last()\@#if commit != "" { commit } else { "unpinned" }]]
  }))
  place(top + right, dx: -(m + 4 * u), dy: H - m - 4 * u, mono(1.75 * u, pal.faint,
    [#meter(2, 3, 1.75 * u, pal.line-hot, pal.faint) #h(0.8 * u) #meta.date.year]))
})
