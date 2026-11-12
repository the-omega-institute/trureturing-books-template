--[[
tr-env.lua — render trureturing environment divs for Pandoc outputs.

Input (produced by tools/tbook/render.py `pandoc_env`, see docs/ARCHITECTURE.md §7):

  :::::: {#thm-x .tr-env .theorem tr-kind="theorem" tr-status="lean" tr-label="定理"
          tr-number="1.2" tr-ref="定理 1.2" tr-title="…" tr-badge="LEAN ✓"
          tr-badge-title="tooltip" tr-badge-url="URL" tr-unverified="1"
          tr-lean="GID …" tr-lean-name="Lean 名 …" tr-lean-url="URL …"}
  content
  ::::::

`tr-badge-url` is present only when the badge links (a LEAN ✓ badge, to the first
declaration); `tr-unverified` marks a formal result the lock does not back (red UNVERIFIED
badge, never a link, while the footer still links each declaration the lock resolves).

Output per FORMAT:

* typst — raw Typst calling functions of theme/typst/book.typ:
    #tr-env(kind: "theorem", status: "lean", ref: "定理 1.2", title: [...], badge: "LEAN ✓",
            badge-url: "…", lean: ((gid: "…", name: "…", url: "…"),), id: "thm-x")[content] <thm-x>
  so that internal links `#link(<thm-x>)` written by Pandoc resolve to Typst labels.
  Proofs become #tr-proof(label: "证明")[…] with an inline label and a ∎ at the end.
* html / html5 / epub / epub3 — semantic XHTML:
    <section id="thm-x" class="tr-env tr-theorem tr-status-lean" data-kind="theorem">
      <header class="tr-env-head">label · title · badge</header>
      content
      <footer class="tr-env-lean">Lean links</footer>
    </section>
  The section keeps its id in the AST, so the EPUB writer resolves links across chapter files.
* anything else — a portable AST fallback (bold heading paragraph, content, Lean links).

`tr-title` is parsed as Markdown inlines (it may contain $math$). Strings that are not
carried by the div (title punctuation, the Lean footer label, fallback badge tooltips when
`tr-badge-title` is absent) come from document metadata set by tools/tbook/pandoc.py:
tr-punct-open, tr-punct-close, tr-lean-label, tr-badge-lean-title, tr-badge-open-title, and
tr-tex-macros (the book's \newcommand definitions, applied to math in titles).
]]

-- Symbol names the pinned Typst renamed (tools/filters/typst-compat.lua).
local compat = dofile(pandoc.path.join({ pandoc.path.directory(PANDOC_SCRIPT_FILE), "typst-compat.lua" }))
local stringify = pandoc.utils.stringify

local META = {}

local function meta_str(meta, key, default)
  local v = meta[key]
  if v == nil then return default end
  return stringify(v)
end

local function words(s)
  local out = {}
  for w in (s or ""):gmatch("%S+") do out[#out + 1] = w end
  return out
end

local function is_typst()
  return FORMAT == "typst"
end

local function is_html()
  return FORMAT:match("^html") ~= nil or FORMAT:match("^epub") ~= nil or FORMAT == "chunkedhtml"
end

-- Markdown inlines from an attribute value (titles may contain math or emphasis). Read
-- like book.md: no citations (a leftover "[@x]" or "@x" stays text), and the book's TeX
-- macros (tr-tex-macros, \newcommand lines) are defined first so latex_macros expands them.
local function parse_inlines(text)
  if text == nil or text == "" then return pandoc.Inlines({}) end
  local source = text
  if META.tex_macros ~= nil and META.tex_macros ~= "" then
    source = META.tex_macros .. "\n\n" .. text
  end
  local ok, doc = pcall(pandoc.read, source, "markdown-auto_identifiers-citations")
  if ok then
    for _, block in ipairs(doc.blocks) do
      if block.t == "Para" or block.t == "Plain" then return block.content end
      if block.t ~= "RawBlock" then break end
    end
  end
  return pandoc.Inlines({ pandoc.Str(text) })
end

-- ------------------------------------------------------------------ Typst helpers

local function typst_str(s)
  s = tostring(s or "")
  s = s:gsub("\\", "\\\\")
  s = s:gsub('"', '\\"')
  s = s:gsub("\r?\n", " ")
  return '"' .. s .. '"'
end

local function typst_content(inlines)
  if #inlines == 0 then return "none" end
  local out = pandoc.write(pandoc.Pandoc({ pandoc.Plain(compat.inlines(inlines)) }), "typst")
  out = out:gsub("[ \t\r\n]+$", "")
  return "[" .. out .. "]"
end

local function typst_label(id)
  if id == nil or id == "" then return "" end
  if id:match("^[%w_%-:%.]+$") then return " <" .. id .. ">" end
  return " #label(" .. typst_str(id) .. ")"
end

local function lean_entries(attr)
  local gids = words(attr["tr-lean"])
  local names = words(attr["tr-lean-name"])
  local urls = words(attr["tr-lean-url"])
  local out = {}
  for i, gid in ipairs(gids) do
    local url = urls[i] or "-"
    if url == "-" then url = "" end
    out[#out + 1] = { gid = gid, name = names[i] or gid, url = url }
  end
  return out
end

local function typst_lean(entries)
  if #entries == 0 then return "()" end
  local parts = {}
  for _, e in ipairs(entries) do
    parts[#parts + 1] = "(gid: " .. typst_str(e.gid) .. ", name: " .. typst_str(e.name)
      .. ", url: " .. typst_str(e.url) .. ")"
  end
  return "(" .. table.concat(parts, ", ") .. ",)"
end

-- Insert an inline at the start of the first paragraph and another at the end of the
-- last one (creating paragraphs when the proof starts or ends with something else).
local function wrap_paragraphs(blocks, first_inline, last_inline)
  local b = pandoc.Blocks(blocks)
  if first_inline then
    local first = b[1]
    if first and (first.t == "Para" or first.t == "Plain") then
      first.content:insert(1, pandoc.Space())
      first.content:insert(1, first_inline)
    else
      b:insert(1, pandoc.Para({ first_inline }))
    end
  end
  if last_inline then
    local last = b[#b]
    if last and (last.t == "Para" or last.t == "Plain") then
      last.content:insert(pandoc.Space())
      last.content:insert(last_inline)
    else
      b:insert(pandoc.Para({ last_inline }))
    end
  end
  return b
end

local function render_typst(div, a)
  local kind = a["tr-kind"] or ""
  local id = div.identifier
  if kind == "proof" then
    local body = wrap_paragraphs(div.content,
      pandoc.RawInline("typst", "#tr-proof-label(" .. typst_str(a["tr-label"]) .. ")"),
      pandoc.RawInline("typst", "#tr-qed()"))
    local out = pandoc.Blocks({ pandoc.RawBlock("typst", "#tr-proof(label: " .. typst_str(a["tr-label"])
      .. ", id: " .. typst_str(id) .. ")[") })
    out:extend(body)
    out:insert(pandoc.RawBlock("typst", "]" .. typst_label(id)))
    return out
  end
  local args = {
    "kind: " .. typst_str(kind),
    "status: " .. typst_str(a["tr-status"]),
    "label: " .. typst_str(a["tr-label"]),
    "number: " .. typst_str(a["tr-number"]),
    "ref: " .. typst_str(a["tr-ref"]),
    "title: " .. typst_content(parse_inlines(a["tr-title"])),
    "badge: " .. typst_str(a["tr-badge"]),
    "badge-url: " .. typst_str(a["tr-badge-url"]),
    "lean: " .. typst_lean(lean_entries(a)),
    "id: " .. typst_str(id),
  }
  local out = pandoc.Blocks({ pandoc.RawBlock("typst", "#tr-env(" .. table.concat(args, ", ") .. ")[") })
  out:extend(div.content)
  out:insert(pandoc.RawBlock("typst", "]" .. typst_label(id)))
  return out
end

-- ------------------------------------------------------------------ HTML / EPUB

local function render_html(div, a)
  local kind = a["tr-kind"] or ""
  local status = a["tr-status"] or ""
  local unverified = (a["tr-unverified"] or "") ~= ""
  local classes = { "section", "tr-env", "tr-" .. kind, "tr-status-" .. status }
  if unverified then classes[#classes + 1] = "tr-unverified" end
  local attr = pandoc.Attr(div.identifier, classes, { { "data-kind", kind } })

  if kind == "proof" then
    local label = pandoc.Span({ pandoc.Str(a["tr-label"] or "") }, pandoc.Attr("", { "tr-env-label", "tr-proof-label" }))
    local qed = pandoc.Span({ pandoc.Str("∎") }, pandoc.Attr("", { "tr-qed" }, { { "aria-hidden", "true" } }))
    return pandoc.Div(wrap_paragraphs(div.content, label, qed), attr)
  end

  local head = pandoc.Inlines({})
  head:insert(pandoc.Span({ pandoc.Str(a["tr-ref"] or a["tr-label"] or "") }, pandoc.Attr("", { "tr-env-label" })))
  local title = parse_inlines(a["tr-title"])
  if #title > 0 then
    local t = pandoc.Inlines({ pandoc.Str(META.punct_open) })
    t:extend(title)
    t:insert(pandoc.Str(META.punct_close))
    head:insert(pandoc.Span(t, pandoc.Attr("", { "tr-env-title" })))
  end
  local leans = lean_entries(a)
  local badge = a["tr-badge"] or ""
  if badge ~= "" then
    local classes = { "tr-badge", "tr-badge-" .. status }
    if unverified then classes[#classes + 1] = "tr-badge-unverified" end
    local tip = a["tr-badge-title"] or (status == "lean" and META.badge_lean_title or META.badge_open_title)
    local url = status == "lean" and (a["tr-badge-url"] or "") or ""  -- only a LEAN ✓ badge links; UNVERIFIED never does
    head:insert(pandoc.Space())
    if url ~= "" then
      head:insert(pandoc.Link({ pandoc.Str(badge) }, url, tip, pandoc.Attr("", classes)))
    else
      head:insert(pandoc.Span({ pandoc.Str(badge) }, pandoc.Attr("", classes, { { "title", tip } })))
    end
  end

  local blocks = pandoc.Blocks({
    pandoc.RawBlock("html", '<header class="tr-env-head">'),
    pandoc.Plain(head),
    pandoc.RawBlock("html", "</header>"),
  })
  blocks:extend(div.content)
  if #leans > 0 then
    local foot = pandoc.Inlines({ pandoc.Span({ pandoc.Str(META.lean_label) }, pandoc.Attr("", { "tr-lean-label" })) })
    for _, e in ipairs(leans) do
      foot:insert(pandoc.Space())
      local code = pandoc.Code(e.name)
      if e.url ~= "" then
        foot:insert(pandoc.Link({ code }, e.url, e.gid, pandoc.Attr("", { "tr-lean-decl" })))
      else
        foot:insert(pandoc.Span({ code }, pandoc.Attr("", { "tr-lean-decl" })))
      end
    end
    blocks:insert(pandoc.RawBlock("html", '<footer class="tr-env-lean">'))
    blocks:insert(pandoc.Plain(foot))
    blocks:insert(pandoc.RawBlock("html", "</footer>"))
  end
  return pandoc.Div(blocks, attr)
end

-- ------------------------------------------------------------------ fallback

local function render_generic(div, a)
  local kind = a["tr-kind"] or ""
  if kind == "proof" then
    return pandoc.Div(wrap_paragraphs(div.content, pandoc.Emph({ pandoc.Str(a["tr-label"] or "") }), pandoc.Str("∎")),
      pandoc.Attr(div.identifier, { "tr-env", "tr-proof" }))
  end
  local head = pandoc.Inlines({ pandoc.Strong({ pandoc.Str(a["tr-ref"] or "") }) })
  local title = parse_inlines(a["tr-title"])
  if #title > 0 then
    head:insert(pandoc.Str(META.punct_open))
    head:extend(title)
    head:insert(pandoc.Str(META.punct_close))
  end
  if (a["tr-badge"] or "") ~= "" then
    head:insert(pandoc.Space())
    head:insert(pandoc.Code(a["tr-badge"]))
  end
  local blocks = pandoc.Blocks({ pandoc.Para(head) })
  blocks:extend(div.content)
  local leans = lean_entries(a)
  if #leans > 0 then
    local foot = pandoc.Inlines({ pandoc.Str(META.lean_label .. ":") })
    for _, e in ipairs(leans) do
      foot:insert(pandoc.Space())
      if e.url ~= "" then
        foot:insert(pandoc.Link({ pandoc.Code(e.name) }, e.url))
      else
        foot:insert(pandoc.Code(e.name))
      end
    end
    blocks:insert(pandoc.Para(foot))
  end
  return pandoc.Div(blocks, pandoc.Attr(div.identifier, { "tr-env", "tr-" .. kind }))
end

-- ------------------------------------------------------------------ filter

local function Div(div)
  if not div.classes:includes("tr-env") then return nil end
  local a = div.attributes
  if is_typst() then return render_typst(div, a) end
  if is_html() then return render_html(div, a) end
  return render_generic(div, a)
end

function Pandoc(doc)
  META.punct_open = meta_str(doc.meta, "tr-punct-open", " (")
  META.punct_close = meta_str(doc.meta, "tr-punct-close", ")")
  META.lean_label = meta_str(doc.meta, "tr-lean-label", "Lean")
  META.badge_lean_title = meta_str(doc.meta, "tr-badge-lean-title", "")
  META.badge_open_title = meta_str(doc.meta, "tr-badge-open-title", "")
  META.tex_macros = meta_str(doc.meta, "tr-tex-macros", "")
  -- Bottom-up traversal renders nested environments (e.g. a proof inside a remark) first.
  return doc:walk({ Div = Div })
end
