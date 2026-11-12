--[[
tr-book.lua — book-level structure for the trureturing Pandoc pipeline (PDF and EPUB).

Run before tr-env.lua. tools/tbook/pandoc.py stages every chapter into one book.md and
marks each chapter title heading with `.tr-chapter` plus key-value attributes
(tr-section = prefix|numbered|suffix|back, tr-depth, tr-kicker); part titles from
SUMMARY.md become `# Part {.tr-part}` headings. This filter:

* every format — turns internal links `#id` whose target does not exist into plain text
  (with a warning on stderr), so a dangling anchor never breaks Typst compilation
  or EPUB validation; so are links and images to `lean:` (a backstop: the stager never
  writes one) and those with an empty destination (Typst refuses an empty URL);
* typst — replaces chapter and part headings with calls of `tr-chapter` / `tr-part`
  (theme/typst/book.typ draws the openers and keeps a real `heading` for the outline
  and running headers); replaces images Typst cannot load (remote URLs, missing files)
  with a link or their description; gives the verification-ledger tables fixed column
  widths; adds line-break opportunities to long inline code (Lean names); writes formulas whose symbol
  names the pinned Typst renamed (typst-compat.lua) as raw Typst with the new names;
  renders `.tr-media` divs as framed media panels;
* html / epub — marks media divs as figures for the stylesheet (theme/epub/book.css).
]]

local stringify = pandoc.utils.stringify
-- Symbol names the pinned Typst renamed (tools/filters/typst-compat.lua).
local compat = dofile(pandoc.path.join({ pandoc.path.directory(PANDOC_SCRIPT_FILE), "typst-compat.lua" }))

local function warn(msg)
  io.stderr:write("[tr-book] " .. msg .. "\n")
end

local function is_typst() return FORMAT == "typst" end

local function typst_str(s)
  s = tostring(s or "")
  s = s:gsub("\\", "\\\\")
  s = s:gsub('"', '\\"')
  s = s:gsub("\r?\n", " ")
  return '"' .. s .. '"'
end

-- A Typst label after an element: <id>, or #label("…") for an id that the <…> syntax cannot write.
local function typst_label(id)
  if id:match("^[%w_%-:%.]+$") then return " <" .. id .. ">" end
  return " #label(" .. typst_str(id) .. ")"
end

local function typst_content(inlines)
  local out = pandoc.write(pandoc.Pandoc({ pandoc.Plain(compat.inlines(inlines)) }), "typst")
  out = out:gsub("[ \t\r\n]+$", "")
  return "[" .. out .. "]"
end

local function file_exists(path)
  local fh = io.open(path, "rb")
  if fh then fh:close() return true end
  return false
end

local function url_decode(s)
  return (s:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end

-- ------------------------------------------------------------------ identifiers

-- The id="…" / id='…' attributes of raw HTML (not data-id="…"), in order.
local function raw_html_ids(text)
  local out = {}
  for _, pat in ipairs({ '%sid%s*=%s*"([^"]+)"', "%sid%s*=%s*'([^']+)'" }) do
    for id in text:gmatch(pat) do out[#out + 1] = id end
  end
  return out
end

-- The ids a fragment link may reach: those of the document's elements, and those of raw HTML
-- (<a id="x"></a>), which only HTML/EPUB keep; for Typst, typst_raw_anchors gives the latter a label.
-- Returns all ids, and the ids that only raw HTML has.
local function collect_ids(doc)
  local ids, raw_only = {}, {}
  local function add(el)
    if el.identifier and el.identifier ~= "" then ids[el.identifier] = true end
  end
  doc:walk({
    Header = add, Div = add, Span = add, Figure = add, Table = add, CodeBlock = add,
    Code = add, Image = add, Link = add,
  })
  local function raw(el)
    if el.format ~= "html" then return end
    for _, id in ipairs(raw_html_ids(el.text)) do
      if not ids[id] then raw_only[id] = true end
    end
  end
  doc:walk({ RawBlock = raw, RawInline = raw })
  for id in pairs(raw_only) do ids[id] = true end
  return ids, raw_only
end

local function fix_links(doc, ids)
  return doc:walk({
    -- tools/tbook/render.py never writes a lean: destination; should one get through, it is text
    -- (no PDF reader can open it, and epubcheck rejects the scheme). So is an empty destination
    -- (`[x]()`, `![x]()`, `[x]: <>`): Typst refuses an empty URL, epubcheck an empty image source.
    Image = function(img)
      if img.src:sub(1, 5) == "lean:" then
        warn("lean: image " .. img.src .. " rendered as its description")
        return pandoc.Span(img.caption, pandoc.Attr("", { "tr-dangling" }))
      end
      if img.src == "" then
        warn("image with an empty source (" .. stringify(img.caption) .. ") rendered as its description")
        return pandoc.Span(img.caption, pandoc.Attr("", { "tr-dangling" }))
      end
      return nil
    end,
    Link = function(link)
      local t = link.target
      if t:sub(1, 5) == "lean:" then
        warn("lean: link " .. t .. " (" .. stringify(link.content) .. ") rendered as text")
        return pandoc.Span(link.content, pandoc.Attr("", { "tr-dangling" }))
      end
      if t == "" then
        warn("link with an empty destination (" .. stringify(link.content) .. ") rendered as text")
        return pandoc.Span(link.content, pandoc.Attr("", { "tr-dangling" }))
      end
      if t:sub(1, 1) == "#" then
        local id = url_decode(t:sub(2))
        if id == "" or not ids[id] then
          warn("dangling internal link " .. t .. " (" .. stringify(link.content) .. ") rendered as text")
          return pandoc.Span(link.content, pandoc.Attr("", { "tr-dangling" }))
        end
      end
      return nil
    end,
  })
end

-- ------------------------------------------------------------------ Typst

local function typst_heading_call(fn, h)
  local a = h.attributes
  local outlined = not h.classes:includes("unlisted")
  local args = {
    "id: " .. typst_str(h.identifier),
    "kicker: " .. typst_str(a["tr-kicker"] or ""),
    "section: " .. typst_str(a["tr-section"] or ""),
    "outlined: " .. (outlined and "true" or "false"),
    "title: " .. typst_content(h.content),
  }
  return pandoc.RawBlock("typst", "#" .. fn .. "(" .. table.concat(args, ", ") .. ")")
end

local function typst_header(h)
  if h.level == 1 and h.classes:includes("tr-part") then
    return typst_heading_call("tr-part", h)
  end
  if h.level == 1 and h.classes:includes("tr-chapter") then
    return typst_heading_call("tr-chapter", h)
  end
  return nil
end

local function typst_image(img)
  local src = img.src
  if img.attributes["tr-fig"] and src:match("%.svg$") then
    -- A figure (tbook.figure): staged once per palette, theme/typst/book.typ picks the file of the variant.
    local width = img.attributes.width or "100%"
    return pandoc.RawInline("typst", "#box(image(" .. typst_str(url_decode((src:gsub("%.svg$", "")))) ..
      " + tr-fig-ext, width: " .. width .. "))")
  end
  if src:match("^[%a][%w+.-]*:") and not src:match("^file:") then
    warn("remote image " .. src .. " cannot be embedded in the PDF; linked instead")
    local text = #img.caption > 0 and img.caption or pandoc.Inlines({ pandoc.Str(src) })
    return pandoc.Link(text, src)
  end
  local path = url_decode((src:gsub("^file://", "")))
  if not file_exists(path) then
    warn("image not found: " .. src .. "; replaced by its description")
    local text = #img.caption > 0 and img.caption or pandoc.Inlines({ pandoc.Str(src) })
    return pandoc.Emph(text)
  end
  return nil
end

-- Long inline code (Lean declaration names) gets break opportunities after dots/slashes.
local function typst_code(code)
  if #code.text >= 24 and code.text:match("[%./]") and not code.text:match("%s") then
    return pandoc.RawInline("typst", "#tr-code-break(" .. typst_str(code.text) .. ")")
  end
  return nil
end

local LEDGER_WIDTHS = { 0.16, 0.30, 0.36, 0.18 }

local function ledger_table(tbl)
  if #tbl.colspecs ~= #LEDGER_WIDTHS then return tbl end
  for i, spec in ipairs(tbl.colspecs) do
    tbl.colspecs[i] = { spec[1], LEDGER_WIDTHS[i] }
  end
  return tbl
end

local function media_block(div)
  local kind = "media"
  for _, c in ipairs({ "viz", "film", "slides", "figure" }) do
    if div.classes:includes("tr-" .. c) or div.classes:includes(c) then kind = c end
  end
  local out = pandoc.Blocks({ pandoc.RawBlock("typst", "#tr-media(kind: " .. typst_str(kind) .. ")[") })
  out:extend(div.content)
  out:insert(pandoc.RawBlock("typst", "]" .. (div.identifier ~= "" and (" <" .. div.identifier .. ">") or "")))
  return out
end

-- An empty anchor in a heading (`## 小结 <a id="old"></a>`) moves to right after the heading, as
-- raw HTML of its own: Pandoc copies a heading's text into the EPUB's table of contents, where an
-- <a> inside the entry's <a> fails epubcheck (and Typst would repeat its label).
local function lift_heading_anchors(doc)
  local function anchor(c, i)
    local a, b = c[i], c[i + 1]
    return a.t == "RawInline" and a.format == "html" and a.text:match("^<[aA]%s[^>]*>$")
      and #raw_html_ids(a.text) > 0 and b and b.t == "RawInline" and b.format == "html"
      and b.text:match("^</[aA]%s*>$")
  end
  return doc:walk({
    Header = function(h)
      local kept, lifted = pandoc.Inlines({}), {}
      local i = 1
      while i <= #h.content do
        if anchor(h.content, i) then
          lifted[#lifted + 1] = h.content[i].text .. h.content[i + 1].text
          i = i + 2
        else
          kept:insert(h.content[i])
          i = i + 1
        end
      end
      if #lifted == 0 then return nil end
      while #kept > 0 and (kept[#kept].t == "Space" or kept[#kept].t == "SoftBreak") do kept:remove(#kept) end
      h.content = kept
      return { h, pandoc.RawBlock("html", table.concat(lifted)) }
    end,
  })
end

-- Typst drops raw HTML: after the first raw element that carries an id only raw HTML has, a
-- metadata element with that label, so that `#link(<id>)` lands there (a label must exist once).
-- For an id in a heading the element goes right after the heading: the outline and the running
-- headers repeat a heading's text, which would repeat the label.
local function typst_raw_anchors(doc, raw_only)
  local function anchors(el)
    if el.format ~= "html" then return "" end
    local out = {}
    for _, id in ipairs(raw_html_ids(el.text)) do
      if raw_only[id] then
        raw_only[id] = nil
        -- In a content block of its own, so that no other label can attach to it or replace it.
        out[#out + 1] = '#[#metadata("tr-anchor")' .. typst_label(id) .. ']'
      end
    end
    return table.concat(out, " ")
  end
  doc = doc:walk({
    Header = function(h)
      local found = {}
      h.content:walk({
        RawInline = function(el)
          local a = anchors(el)
          if a ~= "" then found[#found + 1] = a end
        end,
      })
      if #found == 0 then return nil end
      return { h, pandoc.RawBlock("typst", table.concat(found, " ")) }
    end,
  })
  return doc:walk({
    RawInline = function(el)
      local a = anchors(el)
      if a == "" then return nil end
      return { el, pandoc.RawInline("typst", a) }
    end,
    RawBlock = function(el)
      local a = anchors(el)
      if a == "" then return nil end
      return { el, pandoc.RawBlock("typst", a) }
    end,
  })
end

-- ------------------------------------------------------------------ HTML / EPUB

local function html_escape(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

-- Long inline code (Lean names) gets <wbr/> after dots and slashes instead of breaking
-- anywhere, so ledger columns wrap at name boundaries.
local function html_code(code)
  if #code.text >= 24 and code.text:match("[%./]") and not code.text:match("%s")
      and code.identifier == "" and #code.classes == 0 then
    local body = html_escape(code.text):gsub("([%./])", "%1<wbr/>")
    return pandoc.RawInline("html", "<code>" .. body .. "</code>")
  end
  return nil
end

-- ------------------------------------------------------------------ filter

function Pandoc(doc)
  doc = lift_heading_anchors(doc)
  local ids, raw_only = collect_ids(doc)
  doc = fix_links(doc, ids)

  if is_typst() then
    doc = typst_raw_anchors(doc, raw_only)
    -- Ledger tables: top-level blocks between a `.tr-ledger` heading and the next chapter.
    local in_ledger = false
    for i, blk in ipairs(doc.blocks) do
      if blk.t == "Header" and blk.level == 1 then
        in_ledger = blk.classes:includes("tr-ledger")
      elseif in_ledger and blk.t == "Table" then
        doc.blocks[i] = ledger_table(blk)
      elseif in_ledger and blk.t == "Figure" and blk.content[1] and blk.content[1].t == "Table" then
        blk.content[1] = ledger_table(blk.content[1])
      end
    end
    doc = doc:walk({
      Image = typst_image,
      Code = typst_code,
      Math = compat.math,
      Div = function(div)
        if div.classes:includes("tr-media") then return media_block(div) end
        return nil
      end,
    })
    doc = doc:walk({ Header = typst_header })
  else
    doc = doc:walk({
      Code = html_code,
      Div = function(div)
        if div.classes:includes("tr-media") and not div.classes:includes("section") then
          div.classes:insert(1, "section")
          return div
        end
        return nil
      end,
    })
  end
  return doc
end
