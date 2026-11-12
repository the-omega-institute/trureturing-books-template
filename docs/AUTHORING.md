# 写作手册 · Authoring guide

本手册面向书的作者（人或 agent）。语法规范见 `docs/ARCHITECTURE.md` §3；这里给出完整示例与常见问题。示例书 `books/example-monograph/` 用到了这里的每一种写法，`books/example-primer/` 是一本最简单的书（书库隐藏了示例书时它们仍在原处，见 §1）。

## 1. 一本书的组成

```
books/<slug>/
  book.toml          元数据
  zh/SUMMARY.md      中文目录（权威版本，默认）
  zh/*.md            中文章节
  en/SUMMARY.md      英文目录（文件名与中文一致）
  en/*.md            英文章节
  figures/           静态图：脚本 <name>.py 与它生成的 <name>.<语言>.svg
  assets/            共享图片（照片、截图等不由脚本画的图）
  viz/ films/ slides/  可选媒体
```

### `book.toml`

| 字段 | 说明 |
| --- | --- |
| `book.version` | 语义化版本，进入下载文件名与 Release |
| `book.editions` | 语言版本，第一个为权威版本，默认 `["zh", "en"]` |
| `book.title` / `subtitle` / `description` | 每种语言一行：`zh = "…"`、`en = "…"` |
| `book.authors`、`license`、`isbn`（按语言）、`date` | 进入版权页与 EPUB 元数据 |
| `book.code` | 封面与站点卡片上的代号，形如 `GOLDEN//OBSERVE` |
| `outputs.html` / `pdf` / `epub` | 输出开关；`pdf = ["screen", "print"]`；可选加 `"academic"` 导出学术预印本版，省略配置或 `true` 仍只导出原两版 |
| `pdf.academic_paper` | 学术预印本开本，默认 `a4`；仅影响 `academic`，排印规范见 [PDF-TYPOGRAPHY.md](PDF-TYPOGRAPHY.md) |
| `pdf.academic_tags` | 预印本的可选 PDF 结构标签，默认 `false` 以控制文件体积；`true` 时保留结构标签，仍须核对投稿大小 |
| `pdf.paper` | Typst 纸张名（`a4`、`a5`、`us-letter`、`iso-b5`…） |
| `epub.embed_fonts` | 是否嵌入标题与等宽字体 |

### 书库里有哪些书

`books/` 下每个含 `book.toml` 的目录是一本书，`site.toml` 的 `[books] order` 决定书库首页的顺序。`[books] hide` 列出要隐藏的书（glob 模式，按目录名匹配）：隐藏的书仍在 `books/` 中，可以随时看它的写法，但检查、钉版、构建、站点与发版都当它不存在，按名字点它（`--book`、`./tbook new-chapter` 等）会报错。要重新使用它，从 `hide` 中去掉该模式并运行 `./tbook pin --refresh`：隐藏期间运行的 `pin --refresh` 已把只被它引用的声明从锁文件中删去。从模板创建的书库设 `hide = ["example-*"]`，隐藏模板附带的示例书，而不是删除它们（删除会让以后合并模板改动时冲突，见 `docs/UPGRADING.md` §6）。`./tbook books` 列出可见的书，`./tbook books --hidden` 列出隐藏的书。规则详见 `docs/ARCHITECTURE.md` §2.1。

### `SUMMARY.md`

与 mdBook 相同：

```markdown
# Summary

[前言](README.md)              ← 前言类（无编号；其中的定理编号为 0.n）

- [第一章 …](ch01.md)          ← 编号章节（定理编号 1.n）
  - [1.1 …](ch01/section.md)   ← 嵌套小节（编号仍归第一章）
- [第二章 …](ch02.md)

[附录 A …](appendix-a.md)      ← 附录类（无编号；其中的定理编号为 A.n）
```

书末的“形式化验证账本”由构建自动追加，不要写进 SUMMARY。章节标题按行内 Markdown 读，转义与数学的显示规则见 §2（`[C\*-代数](ch03.md)` 显示为 C*-代数）。

## 2. 环境

```markdown
::: {.theorem #thm-deficit-three-valued title="亏量只取三个值" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
对所有自然数 $v_1, v_2$，
$$
c(v_1, v_2) \in \{-1, 0, 1\}.
$$
:::
```

| 种类 | 用途 | `lean` |
| --- | --- | --- |
| `theorem` `lemma` `proposition` `corollary` | Lean 验证或显式书面证明的结论 | 默认必须；`status="written-proof"` 时禁止 |
| `definition` | 定义 | 建议（指向 Lean `def`） |
| `conjecture` `problem` | 猜想、开放问题 | 禁止 |
| `example` `remark` | 例子、注记 | 可选 |
| `proof` | 证明思路（不编号） | 可选 |

- 一个结论由多条 Lean 声明共同给出时：`lean="GID1 GID2"`。
- `title` 是一行行内 Markdown，可含行内数学：`title="$\beta$ 不保持加法"`。属性值里反斜杠与花括号原样保留；值里的双引号写 `\"`，`\\` 读作一个反斜杠（TeX 的 `\\` 要写成 `\\\\`）。
- 标题的显示规则（环境标题与 SUMMARY 中的章节标题相同）：`$…$` 内是 TeX，原样保留；`$…$` 外，反斜杠加 ASCII 标点是 Markdown 转义，各端（HTML 页头、侧栏、页面 `<title>`、站点目录、PDF、EPUB、账本）都只显示标点本身：`C\*-代数` 显示为 C*-代数，`snake\_case` 显示为 snake_case，`\$5` 显示为 $5 且不会成为公式。除行内数学与 `[@id]` 外，不要在标题里用强调、行内代码等格式：HTML 页头、侧栏与站点把它们当作纯文字，PDF/EPUB 却会排版，两端不一致。
- `title` 中可以引用别的条目：`title="[@thm-deficit-three-valued] 的推广"` 显示为“定理1.3 的推广”（PDF/EPUB 中带链接）。id 不存在时 `./tbook check` 报错。
- 环境可以嵌套（例如 `remark` 里放 `example`），但不要把 `proof` 放进定理内部——写在定理之后。

### 源文有书面证明，尚无匹配的 Lean 声明

书面证明与开放问题是两种状态。源文已证明的结论可保留正确的定理种类：

```markdown
::: {.theorem #thm-written status="written-proof" proof="pf-written" title="源文结果"}
忠实转述源文的陈述，并给出来源与适用范围。
:::

::: {.proof #pf-written}
源文的书面论证，或忠实、完整的解释；注明出处。
:::
```

`status="written-proof"` 只用于 `theorem/lemma/proposition/corollary`，不能同时有
`lean`（空值也不行）。`proof="id"` 必须指向同一语言版本里非空的 `proof` 块，
可跨章节。各语言的状态与 proof id 必须相同，且每版都要有论证；注释或代码围栏
不算书面证明内容。工具只检查结构，证明是否正确、完整、忠实于来源由作者与评审负责。

所有输出显示紫色 **书面证明 / WRITTEN PROOF**，徽章不带链接，不计入 `LEAN ✓ n`；
账本单列并链接书内的证明。Slidev 用 `<TheoremCard status="written-proof" cite="thm-written" …>`
或 `<LeanBadge status="written-proof" />`，不得给 `gid`。开放问题仍用 conjecture/problem。
未经证实却遗漏状态的形式结论仍报错并显示 UNVERIFIED。

这里不提供“最近 Lean 声明”的环境属性：特例或变体不能作为本结果的验证引用。
如需比较，在正文明确说明关系与差异，使用普通来源链接；不得给书面证明结果添加
`lean` 或绿色徽章。模板层可在独立的比较记录中保存特例/变体关系，用于后续形式化。

### 选择正确的 GID

1. 在 trureturing 中找到声明所在文件 `D5/…/Module.lean`，模块路径就是 `D5/…/Module`。
2. 声明名写完整 Lean 名或其唯一后缀：`deficit_three_valued` 或 `Deficit.deficit_three_valued`。模块的命名空间不一定等于模块路径（如 `DeficitThreeValued.lean` 的命名空间是 `D5.S1.Deficit`），后缀匹配会处理这一点。`of_ρ_eq_self`、`mk₂`、`isSome?` 这样的名字照原样写；不是 Lean 标识符的分量写成 `«…»`。
3. 确认 `Golden/Frozen/state/D5/…/Module.lean.json` 存在。不存在 → 模块未冻结，不能引用。
4. 新增 GID 后运行 `./tbook pin --refresh`。

## 3. 数学

- 行内 `$…$`；开头的 `$` 后不能是空格，结尾的 `$` 前不能是空格、后面不能紧跟数字（所以“价格 $5”不会被当作公式）。
- 块级 `$$` 各占一行，前后空行；多行推导用 `aligned`。
- 跨行的公式（`$$` 与 `$$` 之间，或跨行的 `$…$`）整个属于所在段落：其中以 `+`、`-`、`>`、`#`、`=` 或四个空格开头的行都不开始列表、块引用、标题或代码块（Pandoc 先读公式，HTML 端在 mdBook 之前渲染公式，工具也照此判断）。公式中不能有空行（块引用里也不能有只含 `>` 的行），也不能含行内代码、HTML 注释或 HTML 标签，否则不配对，按普通文字处理（`$$` 不配对时构建给出警告）。
- 公式也不跨过开始围栏代码块的行（在所在段落的列表项、块引用中缩进不超过三格的 ```` ``` ```` 或 `~~~`）：代码块上方没有配对的 `$`（如“把 bin 目录加入 $PATH：”下面紧接一段含 `export PATH=$HOME` 的代码）不会把代码吞进公式，HTML 照常显示代码块。Pandoc 却先读公式：这个 `$` 之后的第一个 `$`（`$$` 则是第一个 `$$`）在代码块里或其后、中间没有空行时（对 `$` 还要求它前面不是空白、后面不是数字），Pandoc 把两者之间连同围栏读成一个公式，PDF/EPUB 因此与 HTML 不同，`./tbook check` 给出警告并指出这个 `$` 所在的行与列：把它写成 `\$`。
- 不用 `\(`、`\)`、`\[`、`\]`。
- 字面美元号写 `\$`。
- 章节标题、`SUMMARY.md` 的链接标题与部分标题、书名都可写 `$…$`：HTML 构建时预渲染为 KaTeX，侧栏目录也保留公式排版；浏览器标签与搜索索引用公式的可见文字。例：`- [关于 $\beta_1$ 的估计](estimates.md)`，正文对应 `# 关于 $\beta_1$ 的估计`。
- 预设宏（`\norm`、`\floor`、`\ceil`、`\Tr`、`\tr`、`\diag`、`\ketbra`、`\dyad`、`\vv`、`\nicefrac` 等）只在 `tools/tbook/mathrender.py` 的 `TEX_MACROS` 中定义：HTML 端交给 KaTeX，PDF/EPUB 端由 Pandoc 作为 `\newcommand` 展开，三端渲染一致（环境标题中也可用）。其他宏请写成标准 LaTeX 数学命令。
- `\|` 是范数竖线，表格单元格里也一样；绝对值写 `|x|`。

## 4. 引用与链接

| 写法 | 结果 |
| --- | --- |
| `[@thm-deficit-three-valued]` | “定理1.3”，链接到该定理（跨章节可用） |
| ``[`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)`` | 指向所钉提交上 Lean 源文件对应行的永久链接 |
| `[该定理][lt]` + `[lt]: lean:D5/…/Module.name` | 引用式写法，同上；尖括号 `(<lean:…>)` 与自动链接 `<lean:…>`（显示为 GID）也可以。各种写法见表下说明 |
| `[第二章](ch02-refutation-observation.md)` | 章节链接（HTML 为页面链接，PDF/EPUB 为内部跳转） |
| `[观测能恢复什么](ch02-refutation-observation.md#观测能恢复什么)` | 章节内标题：片段按目标章节内的标题解析（与 HTML 相同），各章都有的同名标题（如“小结”）不会串章；片段照抄 HTML 页面上的锚点即可，标题含公式或脚注时也一样（`## 关于 $\beta$ 的估计` 的片段是 `#关于-β-的估计`；`## 注释[^a]` 的片段是 `#注释1`，数字是该脚注在本章的编号；标题里的 HTML 注释不进锚点）。片段也可以是目标章节里的显式 id（`{#id}`）或任一环境 id。目标章节没有的片段，HTML 中只打开该页，PDF/EPUB 中只显示链接文字并警告，不会落到别章的同名锚点上 |
| `![图注](../assets/figure.svg)` | 图片；放在 `assets/` 的图各语言共享 |
| `![图注][fig]` + `[fig]: ../assets/figure.svg` | 引用式图片，同上 |
| `![图注](<../assets/有 空格.svg>)` | 路径含空格时用尖括号 |
| `[数据表](../assets/data.csv)` | 文件下载：HTML 指向复制进 `_book/` 的文件；PDF/EPUB 不能内嵌非图片文件，改为指向网站上的同一文件（需要 `site.toml` 的 `base_url` 或可推断的 repo，否则只保留文字并警告） |

脚注 `[^1]` 在每章内独立（PDF/EPUB 合并全书时自动加章节前缀）。定义 `[^1]: …` 也可以写在块引用或列表项里（`> [^1]: …`、`- [^1]: …`），或紧贴在正文行下面（缩进不到四格），各端都把它当作本章的脚注。下面这些位置的 `[^1]` 在 HTML 端（mdBook）不是脚注引用；PDF/EPUB 合并时也不给它们加前缀，所以同样不指向本章的脚注；标题锚点里的脚注编号也不计它们：转义的 `\[^1]`；代码、HTML 注释与公式里的；原始 HTML（HTML 块、标签的属性）、自动链接、链接地址与链接标题里的；环境标题里的；紧接 `(…)` 或 `[x]` 的（mdBook 把 `某定理[^1](1972)` 读成链接；`[ ]` 这样只有空白的方括号不算）。HTML 块随所在的块引用或列表项结束：块引用里的 HTML 块后紧接一行不带 `>` 的文字，或列表项里的 HTML 块后紧接一行缩进不到该项内容的文字，这一行已不在 HTML 块中，其中的 `[^1]` 照常是脚注。

两端读法不同的脚注写法，`./tbook check` 给出警告：

- 引用与定义的标签只差大小写（`[^A]` 对 `[^a]:`）：HTML 显示一个链不到注文的编号，PDF/EPUB 显示文字 `[^A]`。标签照定义写。
- `[^1]` 紧接 `(…)` 或 `[x]`：HTML 是链接（`[x]` 不是链接引用时是文字），PDF/EPUB 是原文，都不是脚注。`(` 前加空格或反斜杠，`[` 前加空格。
- 标签含空格或 `^`（`[^a b]`）：mdBook 当作脚注，Pandoc 当作链接。换一个不含它们的标签。

`@` 只在 `[@id]` 中表示引用，正文里的 `@name` 是普通文字。

正文加粗用 `**…**`，标记内侧不要留空格。中文可写 `这是**术语（term）**的说明`、`这是**“重点”**后文`，也可在加粗中使用行内公式；构建会处理 mdBook 的中英文标点边界，使 HTML 与 PDF/EPUB 一致，无须在汉字之间补空格。代码和转义后的 `\*\*` 按原样显示。

代码块里的内容各端都照原样显示，其中的脚注、链接、图片、`[@id]`、`lean:` 链接与公式都不改写、不检查。代码块有两种：围栏代码块（```` ``` ```` 或 `~~~`），与缩进代码块。缩进代码块是比所在位置的内容再缩进四格（一个制表符算四格）的行，所在位置可以是顶层、列表项、块引用、脚注或定义（`:` 开头的行）的正文；列表项的内容从标记后的第一个字算起，所以 `1. 运行：` 下的代码缩进七格，`- 步骤` 下缩进六格，只与内容对齐的缩进行是该项的下一段；脚注的正文缩进四格，其中的代码缩进八格。缩进行紧接在段落行下面时仍属于该段落，代码块前要空一行。

围栏代码块以同一种字符、不短于开头的围栏结束；在列表项、块引用、脚注或定义中，代码块的各行与结束围栏都要与开头的围栏同样缩进（块引用中每行都带 `>`）。遇到缩进不足或不在块引用中的行时，mdBook 在这里结束代码块（这一行若是围栏，又开始一个新的代码块），Pandoc 却另有读法：可能把这一行当作结束围栏，也可能根本不当作代码块。从未闭合的围栏，mdBook 把其后全文显示为代码，Pandoc 不当作代码块。两种情况各端显示不同，`./tbook check` 都给出警告；工具按 mdBook 的读法处理，因此其后被当作代码的部分不再检查。

定义（`:` 开头的行，其正文同列表项）跟在术语之后：术语是同一位置（顶层、列表项、块引用等）只有一行的段落，紧挨着定义或隔一个空行；同一术语的下一条定义同样以 `:` 开头，与上一条定义之间可以隔任意空行。术语多于一行、术语与定义之间隔了不止一个空行时，mdBook 仍读作定义而 Pandoc 不读作定义；`~` 开头的定义只有 Pandoc 认。这些情况 `./tbook check` 给出警告，工具按 Pandoc 的读法处理。只有一个 `:` 的行也开始定义，正文从下一行写起，从冒号后一列算缩进（所以下一段缩进四格是段落，五格才是代码）；冒号行与正文之间不要空行：mdBook 在空行处结束定义，Pandoc 不结束，`./tbook check` 给出警告。不是定义而行首要写冒号时，写成 `\:`。

引用式链接定义（`[fig]: ../assets/x.svg "标题"`）必须独占一行（也可以在列表项或块引用里），地址后只能跟可选的标题：`"…"`、`'…'` 或 `(…)`，其中可用反斜杠转义（`"Knuth 的 \"进位\" 图"`），与 CommonMark 相同；`[注]: 原图见 [fig](../assets/x.svg)`、`[1]: Knuth, TAOCP.` 这样后接正文的行是普通段落，在列表项（`- [1]: Knuth, TAOCP.`）、块引用或列表的续行里也一样，各端都显示，其中的链接照常处理；`[3]: <lean:…>，引用中` 也是段落（`<…>` 后紧接文字；不带尖括号的地址不能以 `<` 开头），`<lean:…>` 是自动链接。定义不能打断段落：它只能是段落的第一行，或紧接在段落开头的另一条定义之后（标题跨行的定义也算）；接在段落文字下一行的 `[fig]: ../assets/x.svg` 不论缩进多少都是段落文字，各端照原样显示，其中的地址不改写、不检查。冒号后什么也没有的 `[x]:`，只有下一行是地址（可带标题）时才是定义；下一行是空行、标题或普通文字，或者没有下一行时，它也是普通段落，各端都显示为文字。下一行是地址时，mdBook 与 Pandoc 都把这两行读作定义、都不显示（“下一行”是一个词也算地址），但工具不读写在下一行的地址：不检查、不复制文件，PDF/EPUB 也不解析它（链接断开，EPUB 可能构建失败），所以 `./tbook check` 对带协议（`https:` 等）以外的这种地址给出警告：把地址写在标签那一行；这两行本是正文时，把标签的 `[` 写成 `\[`。

地址为空的链接与图片（`[文字]()`、`![图]()`、`[x]: <>`）各端都能构建，但显示不同：HTML 中链接指向本页、图片是破图，PDF/EPUB 只显示链接文字或图片说明。`./tbook check` 对写在一行内的这几种给出警告。

`lean:` 链接可以用 CommonMark 的任何单行写法：行内或尖括号地址、带 `"…"`、`'…'` 或 `(…)` 标题、链接文字里有成对的方括号（`[x [y] z](lean:…)`）、链接里套图片、自动链接 `<lean:…>`，或引用式定义（也可以在列表项或块引用里）。每种写法的 GID 都由 `./tbook check` 核对、由 `./tbook pin --refresh` 收录。链接必须写在一行内：链接文字、地址或标题跨行，定义的标签跨行或地址写在下一行，以及原始 HTML 里的 `lean:` 地址，工具都读不到，`./tbook check` 报错；地址写成 `<lean:…>` 时也一样（链接文字跨行而地址是 `(<lean:…>)`，或 `[x]:` 的下一行是 `<lean:…>`）：它是这个链接或定义的地址，不是自动链接（不是定义时仍是自动链接，照常核对：`[1]: <lean:…> 文字` 地址后跟正文，或 `[x]:` 是段落的续行）；构建时去掉这样的 `lean:` 地址（链接只留文字，定义与 HTML 属性的地址写成 `#`），任何输出都没有 `lean:` 地址。环境标题里不能放 `lean:` 链接：`./tbook check` 报错，各端只显示链接文字。

HTML 注释 `<!-- … -->` 不出现在任何输出中：其中的图片、链接、`[@id]`、`lean:` 链接与环境都不改写、不检查、不编号，适合放待补的图。注释有两种：

- 注释块：以 `<!--` 开头（最多缩进三格；在列表项等容器中从其内容算起）且本行没有 `-->` 的行，到含 `-->` 的那一行为止。这一整行都按注释处理，所以 `-->` 后面不要接正文（mdBook 会把它当作原始 HTML 原样输出，其中的链接与 `[@id]` 既不改写也不检查）。没有 `-->` 时 `./tbook check` 报错。
- 行内注释：其他位置的 `<!--`，到 `-->` 为止，可以跨行，但只在同一段落内；表格的每一行各算一个段落。段落在 `-->` 之前结束（空行、标题、新的列表项、代码块、表格的下一行等）时，这个 `<!--` 只是普通文字，HTML 照原样显示；Pandoc 却会一直隐藏到后文的下一个 `-->`，PDF/EPUB 因此与 HTML 不一致，所以后文还有 `-->` 时 `./tbook check` 给出警告。

缩进代码块与行内代码里的 `<!--` 是代码，不开始注释。

当前出版的版本只写在锁文件。正文使用 `[{commit}](trureturing:)` 显示完整提交并链接该提交；审计表使用 `[{source}](lean:GID)` 显示文件与当前行号、`[{statement_id}](lean:GID)` 显示 `sha256:` 后八位摘要前缀。这三个保留标签只用于单行行内链接（不要包进代码、图片、环境标题或引用式定义），HTML/PDF/EPUB 共用同一解析器；普通 `lean:` 链接不变。真实历史比较继续用字面的历史提交与元数据，不把它们换成当前引用。

## 5. 媒体

```markdown
::: {.viz src="golden-carry" height="560"}
图注：拖动滑块观察进位。
:::

::: {.viz src="my-viz" preset="half" height="500"}
**一句标题。** 引用可视化的一张实验卡：图贴在讲到它的那句话旁边。
:::

::: {.film src="001-golden-deficit"}
:::

::: {.slides src="overview"}
:::

::: {.figure src="phase-square"}
**相位正方形。** 青色三角形中亏量为 $+1$，品红三角形中为 $-1$。
:::
```

静态图用 `::: {.figure src="<图名>"}` 引用，图名对应脚本 `books/<slug>/figures/<图名>.py`：一张图只讲一件事，放在讲到它的那句话旁，各语言版本位置与 `src` 相同，只翻译图注。图由脚本生成（`./tbook fig new|build|shots`），每种语言一版标签；HTML 中随深浅主题变化，PDF 的屏幕版与印刷版各用自己的配色。图注必须有，且不能只是编号。标准、画图库的用法与看图的方法见 `skills/book-figure`。图片语法 `![图注](../assets/x.png)` 只用于照片、截图这类不能由脚本画的图片，图注同样不能只是编号；用图片语法引用 `assets/` 里写死颜色的 SVG（没有角色类、没有 `prefers-color-scheme`），或让两种语言共用一个带字的 SVG，`./tbook check` 都给出警告。图在手机上（正文栏宽 358 px，按 `min(1, 358 / 宽度)` 缩小，分栏图按最宽一栏）最小的标签不得小于 10 px，低于时 `./tbook fig build` 与 `./tbook check` 警告，`site.toml` 的 `[figures]` `phone_labels = "error"` 可升为错误。媒体块（`.figure`、`.viz`、`.film`、`.slides`）放在各自对应的那句话之后，相邻两块之间要隔着正文：两块只隔着空行或 HTML 注释相邻时，`./tbook check` 对这一对给出警告（两块的种类、`src`、实验卡的 `preset` 与行号）。不带 `preset` 的完整实验室紧跟同一页面的最后一张卡最常见：把实验室挪到章末最后一段之后，或在两者之间用一句正文交代。

外部资源：`src="trureturing-visualize:<id>"`、`src="trureturing-film:film-001-v1"`。HTML 中为交互嵌入或播放器；PDF/EPUB 中为缩略图/海报加在线地址。媒体块在各语言版本中也必须一一对应。

可视化的每张实验卡都可以单独引用：`preset="<卡>"`（页面里的 `data-preset`）。HTML 中它是一张不带内部滚动的图，开在那张卡上，“全屏打开”进入同一状态的完整实验室；PDF/EPUB 中它是那张卡的带标签静态图 `viz/<id>/fig-<卡>.<语言>.jpg`（`node tools/node/viz-thumbs.mjs <book> <id>` 生成，提交入库）。把图放在讲到它的那句话旁边，图注用与图例相同的颜色词和符号；不带 `preset` 的嵌入是完整实验室，通常每个可视化在章末放一处。各语言版本引用的卡必须相同，`./tbook check` 会核对卡存在、版本一致、静态图齐全。设计与制作见 `skills/book-viz`。

本书的视频是构建产物：`./tbook build films|site|all` 渲染（输入未变时从缓存恢复），站点托管在 `<slug>/films/<id>/`。章节中的播放器播放 720p 旁白版、附 `film.json` 的 `outputs` 所列视频的下载链接（默认只构建 720p 旁白版与封面，1080p 与纯配乐版本列出才构建）；站点没有该视频时（缺少视频工具链且缓存未命中）显示海报与“视频未构建”。PDF/EPUB 显示提交的 `poster.jpg`，有 `base_url` 时加视频页地址。编写与构建见 `skills/book-film`。

## 6. 多语言流程

1. 在权威版本（默认中文）中写作、通过 `./tbook check`。
2. 把改动同步到其他语言：相同的文件、相同的环境顺序、相同的 `#id` 与 `lean`。只有正文、标题、图注是翻译的。
3. 再次 `./tbook check`：任何不一致都会报出“item N differs between editions”。
4. 英文要自然、准确。理论术语以 trureturing 的英文名称为准（Lean 声明名、Blueprint 标题）。

## 7. 诚实标注

- 只有 `LEAN ✓` 的条目是已验证结论；正文中不要手写“已证明”“已验证”来修饰未引用 Lean 的命题。
- 构建只在锁文件确认每条 GID 都是已冻结的 Lean 定理时显示 `LEAN ✓`；否则显示红色 `UNVERIFIED`（徽章在各端都不是链接），也不计入“LEAN ✓ n”等统计（`./tbook check` 会报错，不能发布）。页脚与账本只给锁文件解析了的声明链接（例如误引的 Lean 定义，链接到它的源码），锁文件没有的 GID 显示为不带链接的文字。
- 不把存在性写成可构造，不把一个反例写成最小反例，不把示意图的数值写成实验或模拟结果。
- 引用文献中的结论而 trureturing 尚未形式化时，写成 `remark` 并注明“文献结果，未在本书形式化”，不要用 `theorem`。

## 8. `./tbook check` 常见报错

| 报错 | 处理 |
| --- | --- |
| `theorem #… cites no Lean declaration` | 加 `lean="…"`；若未证明，改为 `conjecture` |
| `… is not in trureturing.lock.json` | `./tbook pin --refresh` |
| `module … is not frozen at …` | 该模块在所钉提交上没有状态片：换一个已冻结的声明，或先在 trureturing 中完成冻结，再 `./tbook pin` |
| `no frozen declaration named …` / `ambiguous` | 检查名字；歧义时写更长的后缀 |
| `is a Lean def, but theorem-like environments must cite theorems` | 定义请用 `definition` 环境 |
| `item N differs between editions` | 对齐各语言版本的环境序列 |
| `[@x] refers to no environment` | 检查 id 拼写；id 只在同一语言版本内解析（正文与环境标题中的 `[@x]` 都会检查） |
| `cannot parse this fenced div opening line` | 检查 `::: {…}` 中的引号是否成对；值内的 `"` 写成 `\"` |
| `HTML comment is never closed` | 给以 `<!--` 开头的注释补上 `-->`；否则其后的全部内容都算作注释 |
| `'<!--' … is not closed in its paragraph`（警告） | 在同一段落内补上 `-->`；要显示字面的 `<!--`，写成行内代码 `` `<!--` `` |
| `the fenced code block opened on line … ends at this line without a closing fence`（警告） | 把代码块的各行与结束围栏缩进到与开头的围栏相同（见 §4） |
| `fenced code block is never closed`（警告） | 补上结束围栏 |
| `mdBook (HTML) reads this ':' line as a definition …`（警告） | 术语写成一行，与定义之间至多隔一个空行；不是定义时行首写 `\:` |
| `'~' starts a definition for Pandoc …`（警告） | 定义改用 `:` 开头 |
| `this definition's ':' line holds nothing and a blank line follows it …`（警告） | 去掉冒号行后的空行，或把定义的第一行写在冒号后（见 §4） |
| `the '$' at column … is not closed before the fenced code block on line …`（警告） | 字面美元号写 `\$`（见 §3） |
| `'…' is the destination of the reference definition whose label ends the line before …`（警告） | 把地址写在 `[x]:` 那一行；两行本是正文时写 `\[x]:`（见 §4） |
| `pinned commit … is not on branch 'dev'` | 所钉提交未合入 `site.toml` 的 trureturing 分支（默认 `dev`）：改钉该分支上的提交（`./tbook pin`） |
| `could not verify that pinned commit …` | 设置 `TRURETURING_DIR` 指向含该提交的 checkout（必要时先 `git fetch`），或联网让 GitHub API 回答（设置 `GITHUB_TOKEN` 可免匿名限额）；GitHub Actions 中这是错误 |
| `not listed in SUMMARY.md` | 加入 SUMMARY 或删除文件 |
| `figure … has no caption` / `has a placeholder caption` | 给 `.figure` 块或图片写一句说明这张图的图注；“图 13”这样的编号不算图注 |
| `… is stale: its script draws something else` / `has not been generated` | `./tbook fig build --book <slug>`，提交生成的 `figures/*.svg` |
| `figure …: its smallest label (…) is … px on a phone, below 10 px`（警告，`site.toml` 可升为错误） | 做窄、分栏（`WRAP = True`）或加大最小字号，提示里给了具体数值（见 `skills/book-figure`） |
| `… is a hand-drawn SVG with its colours written in`（警告） | 改写成图脚本 `figures/<name>.py`，用 `::: {.figure}` 引用；图片语法只留给照片一类 |
| `… has text and is shown by the zh, en editions alike`（警告） | 每种语言一版标签：改成图脚本，或各语言各用一个文件 |
| `… and … sit next to each other with no text between them`（警告） | 把两块各自挪到对应的那句话之后，块与块之间有正文；完整实验室挪到章末最后一段之后 |
| `no figure books/<slug>/figures/<name>.py` | `.figure` 的 `src` 没有对应脚本：核对图名，或 `./tbook fig new <slug> <name>` |
| `no chapter, deck, film or visualization of this book uses this file`（警告） | `assets/` 里的遗留文件：删除，或在章节里引用 |

## 9. 学术报告（Beamer）

传统学术报告用 `./tbook slides new <book> <deck> "<title>" --academic --editions en`。`deck.toml` 声明 `kind="academic"`、所选 `editions`、`aspect="4:3"`（或 `16:9`）、`structure_colour`、短作者/标题，可选 `institution`、`coauthors`（原主题显示 Joint work with …）、`date`、`navigation_symbols=true`（默认隐藏导航按钮），以及自有 `theme_dir`/`theme_name` 与 `institution_graphic`。每个所选语言给一个标题；所选第一语言是 `slides.tex`，其他为 `slides.<lang>.tex`。可以只覆盖书的一部分语言；同一 deck 内逐帧对齐。现有 Slidev deck 的格式不变。

TeX 源在导言区写 `\input{tbook-deck}`；用 `\begin{bookresult}{thm-…}` 引用书中 id，正文自己写，种类、编号、标题与 Lean 徽章由书和锁生成。开放问题没有 GID；未解析的 GID 显示 `UNVERIFIED` 并使检查失败。`\PinnedCommit` 显示当前钉版，`\FormalVerification` 生成本报告引用过的结果账本。按“标题页、提纲、section/subsection/frame、appendix”组织，逐帧写 `% Manuscript: ...`，用 `\note{...}` 保留演讲备注。

`\BookViz{golden-carry}{plus}` 插入纸面静态图并链接在线实验；先用 `./tbook slides snapshots <book>` 生成并提交 `fig-<卡>.<语言>.paper.png`。`\BookFigure{phase-square}` 经现有 `figure.materialize(...,"paper")` 路径插图，检查会拒绝过期 SVG。章节仍用 `::: {.slides src="<deck>"}`，各语言媒体序列一致；deck 缺少该语言时链接所选第一语言。完整命令、源解析边界、自有主题与排版规范见 [theme/beamer/README.md](../theme/beamer/README.md) 和 `skills/book-slides`。
