-- Pandoc's MathML writer accepts TeX points in \hspace, but rejects metric
-- lengths. Convert physical units before writing, including math in titles.
local points = { mm = 72.27 / 25.4, cm = 72.27 / 2.54, ["in"] = 72.27 }

function Math(math)
  local text, changes = math.text:gsub(
    [[(\+)hspace%s*{%s*([+-]?%d*%.?%d+)%s*(%a+)%s*}]],
    function(slashes, amount, unit)
      if #slashes % 2 == 1 and points[unit] then
        return slashes .. string.format("hspace{%.6fpt}", tonumber(amount) * points[unit])
      end
    end)
  if changes > 0 then
    math.text = text
    return math
  end
end
