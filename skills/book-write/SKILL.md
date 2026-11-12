---
name: book-write
description: 撰写或修改 books/<slug>/<lang>/ 下的章节时使用：定理环境、Lean 引用、数学、交叉引用、媒体嵌入的写法，多语言逐条对齐，以及 Lean 优先、带 DOI 的书面证明与形式化请求登记规则。
---

# 撰写章节

## 适用范围

**用**：写新章节、改正文、加定理/定义/例子、翻译另一语言版本、在章节里嵌入可视化/视频/幻灯片。

**不用**：新建书或章节文件（`skills/book-new`）；让一条新定理在 Lean 中成立（`skills/theorem-formalize`）；导出与排错（`skills/book-export`）。

**权威**：语法与校验规则以 `docs/ARCHITECTURE.md` §3–§4 和 `./tbook check` 的实际输出为准；与本文件冲突时，本文件是 bug。

## 先读

- `docs/ARCHITECTURE.md` §3（写作语法）、§4（校验）
- `docs/AUTHORING.md`（完整写作手册与示例）
- 本书 `book.toml`（语言版本、第一个为权威版本）与 `<lang>/SUMMARY.md`
- `books/example-monograph/`（每种写法都有示例；本书库用 `site.toml` 的 `[books] hide` 隐藏了示例书时，它仍在原处；删掉了时，看模板仓库中的同一目录）

## 硬规则

1. **显式区分验证状态。** `theorem / lemma / proposition / corollary` 默认带 `lean="<GID>"`，且锁文件解析为 Lean `theorem`。先检索并优先引用匹配的冻结 Lean 声明。仅在没有匹配验证、源文有书面证明且能引用 DOI 时，用 `status="written-proof" proof="<proof-id>" doi="<裸 DOI>" source="<原文定位>" request="<issue URL>"`，不得带 `lean`，每个语言版本必须有同 id 的非空 proof 块（可跨章）。只有真正开放的结果才用 `conjecture/problem`。书面证明由作者评审负责，工具不检查数学正确性或自动判定是否已有匹配 Lean 证明。必须在 trureturing-requests 搜索复用或新建 issue，并用英文标题、正文与评论登记书籍用途，标题与标记见 `docs/FORMALIZATION-REQUESTS.md`。见 AUTHORING §2。
2. **陈述要忠实。** Lean 验证结果的书面陈述必须与 Lean 声明一致；written-proof 结果必须忠实于源文的陈述与论证（改写须保持同一结果；特例或变体只作明确比较，不当作该结果的验证）。引用 Lean 前先读源文件（锁文件里有行号：`./tbook check` 通过后，链接指向 `blob/<commit>/<module>.lean#L<line>`）和 trureturing 的 `Blueprint/<module>.md`。不夸大：存在性定理不写成算法，反例不写成“最小反例”。
3. **证明块按证据负责。** Lean 结果的 proof 用于解释，可指向完整内核证明。written-proof 的关联 proof 必须忠实给出源文论证并注明出处，由作者与评审核对；不得声称由 Lean 检查。
4. **多语言逐条对齐。** 每个语言版本的章节文件名、顺序相同；每章的环境序列（种类、`#id`、`lean`、`status`、`proof`、`doi`、`source`、`request`）与媒体序列完全相同。先改权威版本（`editions` 的第一个，默认中文），再同步其他版本。英文要自然、准确，不逐字硬译。
5. **颜色与徽章有语义。** `LEAN ✓`（绿）只由构建根据锁文件生成；锁文件不能把所引 GID 全部解析为 Lean `theorem` 时，构建显示红色 `UNVERIFIED`（`./tbook check` 报错）。正文里不要手写“已验证”“✓”之类的标记，也不要写“已冻结”，除非它就是指构建生成的账本。

## 写法速查

```markdown
::: {.theorem #thm-name title="标题" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
陈述 $c(v_1,v_2)\in\{-1,0,1\}$。
:::

::: proof
思路……完整证明由 Lean 内核检查。
:::

::: {.definition #def-name title="…" lean="D5/S1/Deficit/DeficitInteger.deficit"}
:::

::: {.problem #prob-name title="…"}
尚未解决的问题；不要带 lean。
:::

见 [@thm-name]；Lean 名为 [`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)。

![图注](../assets/figure.svg)

::: {.viz src="golden-carry" height="560"}
图注。
:::

讲到某个情形的那句话，下面紧跟引用它的实验卡。

::: {.viz src="my-viz" preset="half" height="500"}
**一句标题。** 引用可视化的一张实验卡，贴在讲到它的那句话旁边（见 `skills/book-viz`）。
:::
```

- 形式结论、定义、开放条目必须有 `#id`；id 一经发布不要改（外链依赖它）。
- 数学：行内 `$…$`，块级 `$$` 独占一行、前后空行；不用 `\(`、`\[`。
- 标题（`title="…"` 与 SUMMARY 章节标题）是行内 Markdown：`$…$` 外写 `C\*-代数`、`\$5` 时各端都显示 C*-代数、$5；不要在标题里用强调或行内代码（`docs/AUTHORING.md` §2）。
- 待补的图或链接可以先放在 HTML 注释 `<!-- … -->` 里：注释内容不输出，也不检查。行内注释可以跨行，但要在同一段落内闭合；否则 `<!--` 是普通文字（`docs/AUTHORING.md` §4）。
- 代码块中的链接、`[@id]` 与公式照原样显示、不检查；列表项里的缩进代码要比项的内容再缩进四格（`1. ` 下七格），代码块前空一行。
- 图片放 `books/<slug>/assets/`，各语言共享；只在一种语言里出现的图放该语言目录。
- 媒体块（`.figure`、`.viz`、`.film`、`.slides`）各自紧跟讲到它的那句话，相邻两块之间要隔着正文；只隔着空行或注释的两块，`./tbook check` 报出这一对的种类、`src`（实验卡带 `preset`）与行号。最常见的是不带 `preset` 的完整实验室紧跟同一页面的最后一张卡：把实验室挪到章末最后一段之后，或在两者之间用一句正文交代实验室多给了什么。

## 容易踩的坑

以下各条都来自实际写书时出过的问题；`./tbook check` 不会替你发现它们。

### 同一个公式要过三条链路

HTML 是 KaTeX，PDF 是 Pandoc 的 TeX→Typst 转换，EPUB 是 MathML。KaTeX 渲染正常不代表另外两端正确。

PDF 一端由 `tools/filters/typst-compat.lua` 负责与 KaTeX 保持一致：空格（`\;`、`\!`、`\,=\,` 两侧的自动间距）、竖线与范数（`\lvert`、`\|`、`\norm{x}^2`）、算符名（`\operatorname`、`\Tr`）、定尺寸括号（`\bigl(`）、分式（嵌套、`\tfrac`、`\dfrac`）、多符号重音、`\mathbin{…}`、`\xrightarrow{…}`、`smallmatrix` 等都按 TeX 的含义排。正文照常写 LaTeX，不要为了 PDF 改写公式。仍需留意的只有这几条：

- **Pandoc 不认识的命令会让整条公式原样印成 TeX 源码。** `\over`、`\genfrac`、`\tiny`、未在 `TEX_MACROS` 登记的自定义宏都属此类；构建不失败，只在日志里留一行 `Could not convert TeX math`。`./tbook check` 用 KaTeX 判断，发现不了。
- **定尺寸命令只用于括号。** `\bigl( … \bigr)`、`\Bigl| … \Bigr|` 没有问题；`a\big/b` 在 EPUB 中生成带 `maxsize` 的 `<mi>`，epubcheck 报 RSC-005。写 `\frac{a}{b}` 或普通的 `/`。
- **`\mathcal` 只套大写字母。** 小写字母在 HTML 的字体里没有花体，退回斜体；PDF 的字体有，两端字形不同。
- **一行里并排几个等式的独立公式要分行。** 用 `aligned` 显式换行（源码换行不产生公式换行）；这类公式在手机宽度和 PDF 定理框里最先出问题。表头也尽量短：宽表靠容器横向滚动，页面本身不应出现横向滚动条。

改动了公式就三种产物都构建一遍（`./tbook build html pdf epub --book <slug>`）。发现 PDF 与 HTML 排得不一样时，不在正文里绕开，而是修转换：给 `tools/filters/typst-compat.lua` 加一条规则，并在 `tools/tests/test_pdf_math.py` 里加一条按排版结果实测的用例，回馈模板（`skills/template-update`）。排查方法见 `skills/book-export` 的排错清单。

### 写“文献结果”之前先搜冻结库

把源文已证结果写成显式 written-proof 之前，先在所钉提交上搜索匹配的冻结声明；真正未证才用 conjecture。经典结论常常已经冻结，只是换了名字，或以有限维、固定参数、等价改写的形式出现。trureturing 每个 `D5/**/*.lean` 文件头有一行英文 `digest:` 摘要：

```bash
T="${TRURETURING_DIR:-../trureturing}"
C=$(python3 -c "import json; print(json.load(open('trureturing.lock.json'))['commit'])")
git -C "$T" grep -n -i -E 'digest: .*(stinespring|trace distance)' "$C" -- D5
git -C "$T" cat-file -e "$C:Golden/Frozen/state/<模块路径>.lean.json" && echo frozen
```

- 关键词用英文术语及其变体：人名、对象名、结论的形状（`contract`、`no continuous section`、`iff critical line`）都试。
- 也搜本书自己：`grep -rn '<声明名或关键词>' books/<slug>/ trureturing.lock.json`。别的章节可能已经引用了同一结论的更一般形式，这时注记里不能再把它列为未形式化，应改为交叉引用。
- 找到的若是特例或等价改写，就照它的原样引用，并在正文写明它与经典表述之间还差哪一步、那一步仍是文献结果。
- “猜想 ⟺ X”这类冻结定理是等价改写，不是证明：定理框里写等价，`conjecture` 环境照旧保留，正文明说猜想仍然开放。

### 忠实陈述最容易漏掉的细节

- **Lean 的全函数约定。** 除以零得 `0`、`Real.log 0 = 0`、`ZMod` 的 `.val` 取标准代表元、自然数减法截断。陈述涉及这些边界时，把约定写进定义或紧随其后的说明，否则书面陈述在边界情形与 Lean 不一致。
- **模块里的局部实例与记号。** 同一个 `‖·‖` 可能是算子范数，也可能是模块用 `local instance` 指定的希尔伯特—施密特范数；`star`、`•`、`*ᵥ` 同理。读源文件的 `open`、`variable` 与 `local instance`，不要只读定理那几行。
- **库里的命题名照定义展开。** 引用 Mathlib 的命名命题（如 `RiemannHypothesis`）时写出它的定义；它与教科书表述的等价若依赖未形式化的事实，要说出来。
- **Lean 没有陈述的推论不能冒用 Lean 徽章。** 模块文档写明“不陈述某推论”时，不能把该推论当作 Lean 已验证；无 DOI 来源时作为“手工推导，未在本书形式化”的注记，满足书面证明与请求登记要求时才可使用紫色定理框。

### 手写的计数、清单与数值

- 新增或删除定理级环境后，更新正文里手写的条数与清单：章首导言、各部小结、文献注记里“本章已验证的 N 条”、附录的对照表。先 `grep -rn '条正式\|条定理\|Lean-verified' books/<slug>/` 找一遍，各语言版本都要改。
- “GID—源码行—摘要”这类对照行从 `trureturing.lock.json` 生成，不手抄。
- 算例里的数值独立复算；写“四舍五入到所示位数”时确实是四舍五入而不是截断。各语言版本的数字应当逐个相同，而环境对齐检查不比较数字：把两版同一环境里的数字序列抽出来比对一次。

## 步骤

1. 确认要写的每条形式结论在 trureturing 中已有冻结声明：在 trureturing checkout 中搜索 `D5/`，或读 `Golden/Frozen/state/<module>.lean.json`。没有 → 若源文有证明，按 DOI、原文定位和对应 issue 登记显式书面证明，并关联每版证明；没有 DOI 时保留注明边界的注记，不使用书面证明徽章；若确实开放，用 conjecture/problem。需要内核验证且已获授权时再走 `skills/theorem-formalize`。
2. 在权威版本中写作；新增 GID 后运行 `./tbook pin --refresh`（不移动提交，只解析新引用）。
3. 同步其他语言版本（同样的 id、lean、顺序）。
4. `./tbook check` 必须 0 错误；处理警告（未列入 SUMMARY 的文件、未使用的锁条目）。
5. `./tbook build html --book <slug>`，用 `./tbook serve` 打开改动的页面，在中英两个版本、深浅两种主题、桌面与手机宽度（约 390 px）下看一遍。改动了公式或表格时，`./tbook build pdf epub --book <slug>` 也要跑：epubcheck 的错误与 PDF 的转换问题只在各自的构建里暴露（见“容易踩的坑”）。
6. 提交：说明改了哪些章节、新增了哪些 GID。提交说明与 PR 正文不写模型或生成工具的标识；创建 PR 的工具若在正文末尾自动追加了署名页脚，创建后把正文原样再保存一次，去掉它。

## 禁止

- 把未冻结结果当作 Lean 已验证；删掉 `lean` 而不声明 written-proof 与关联书面证明；编造 GID、改变数学来匹配声明，或把变体当作同一结果。
- 用绿色或手写 LEAN ✓ 标记书面证明；其紫色“书面证明 / WRITTEN PROOF”徽章由构建生成、不带链接、不计入 Lean 数量。
- 手改 `trureturing.lock.json`（只能由 `./tbook pin` 写）。
- 在本仓库写 `.lean` 文件或 Lean 证明。
- 让各语言版本的环境序列不一致，或只改一种语言。

当前版本来自 `trureturing.lock.json`，不复制 SHA 到源码。正文与审计表用 `docs/AUTHORING.md` 的保留链接标签；幻灯片用 `<PinnedCommit />`（复用主题的 `pinned`）；可视化锚点用 `data-lean-gid` / `data-trureturing-path` 和 `href="#"`，由构建与本地预览解析。动态声明数据可从 `../assets/trureturing.json` 取得（构建生成、本地预览从锁读取；不提交该文件）。真实历史版本仍按历史事实保留。钉版后复核摘要变化与媒体陈述，再重建；纯提交或行号变化不要求改正文或媒体源码。
