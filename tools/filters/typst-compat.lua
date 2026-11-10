--[[
typst-compat.lua — math symbol names that Pandoc's Typst writer (texmath) still emits but the pinned Typst
(requirements.txt) no longer knows. Loaded by tr-book.lua (formulas in the text) and tr-env.lua (formulas in
environment titles); used only for Typst output.

Without it a single `\cap` fails the whole PDF ("unknown variable: sect"), and `\odot`, `\otimes`, `\ominus`,
`\circleddash` fail with "unknown symbol modifier". tools/tests/test_pandoc.py compiles every symbol KaTeX
renders (the HTML side) through Pandoc, these filters and Typst, so a new rename shows up as a failing test.
]]

local M = {}

-- {name Pandoc writes, name Typst knows}; matched as whole names (a longer name is not touched), and the
-- modifiers that follow (sect.big → inter.big) are kept.
M.RENAMES = {
  { "sect", "inter" },             -- \cap \Cap \bigcap \sqcap: sect, sect.double, sect.big, sect.sq
  { "dot.circle", "dot.o" },       -- \odot \bigodot
  { "times.circle", "times.o" },   -- \otimes \bigotimes
  { "minus.circle", "minus.o" },   -- \ominus
  { "dash.circle", "dash.o" },     -- \circleddash
}

local function pattern(name)
  -- %f[%w.]: not preceded by a letter, digit or dot (so x.sect and intersect stay); %f[^%w]: a whole name
  return "%f[%w.]" .. name:gsub("%.", "%%.") .. "%f[^%w]"
end

-- Rename in Typst math code, outside string literals ("…" is text: \text{sect} stays "sect").
function M.rename(code)
  local out, i, n = {}, 1, #code
  while i <= n do
    local q = code:find('"', i, true)
    local chunk = code:sub(i, (q or n + 1) - 1)
    for _, r in ipairs(M.RENAMES) do
      chunk = chunk:gsub(pattern(r[1]), r[2])
    end
    -- texmath puts fixed-size delimiters in scale's markup body. Named symbols
    -- there are literal text unless explicitly interpolated (chevron.l, ceil.l, ...).
    -- Quoted TeX text is handled separately below and must remain literal.
    chunk = chunk:gsub("(#scale%b())%[([%a][%w%.]*)%]", "%1[#sym.%2]")
    out[#out + 1] = chunk
    if not q then break end
    local j = q + 1
    while j <= n do
      local c = code:sub(j, j)
      if c == "\\" then
        j = j + 2
      elseif c == '"' then
        break
      else
        j = j + 1
      end
    end
    out[#out + 1] = code:sub(q, j)
    i = j + 1
  end
  return table.concat(out)
end

-- A Math element written as Typst, renamed; nil (keep the element) when nothing needed renaming.
function M.math(el)
  local typ = pandoc.write(pandoc.Pandoc({ pandoc.Plain({ el }) }), "typst", { wrap_text = "wrap-none" })
  typ = typ:gsub("%s+$", "")
  local fixed = M.rename(typ)
  if fixed == typ then return nil end
  return pandoc.RawInline("typst", fixed)
end

-- `inlines` with every formula that needs a rename replaced by raw Typst.
function M.inlines(inlines)
  return pandoc.Inlines(inlines):walk({ Math = M.math })
end

return M
