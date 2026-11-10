---
name: book-write
description: 撰写或修改 books/<slug>/<lang>/ 下的章节时使用：定理环境、Lean 引用、数学、交叉引用、媒体嵌入的写法，多语言逐条对齐，以及“未经 Lean 验证不得称定理”的诚实标注规则。
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

1. **定理只引用，不证明。** `theorem / lemma / proposition / corollary` 必须带 `lean="<GID>"`，且 GID 在 `trureturing.lock.json` 中解析为 Lean `theorem`。没有 Lean 证明的结论只能写成 `conjecture` 或 `problem`。
2. **陈述要忠实。** 书中陈述必须与 Lean 声明的陈述一致（或是它的忠实特例/改写，并在正文说明关系）。写之前先读 Lean 源文件（锁文件里有行号：`./tbook check` 通过后，链接指向 `blob/<commit>/<module>.lean#L<line>`）和 trureturing 的 `Blueprint/<module>.md`。不夸大：存在性定理不写成算法，反例不写成“最小反例”。
3. **证明块不是证明。** `::: proof` 只做解释或证明思路，结尾说明“完整证明由 Lean 内核检查”。
4. **多语言逐条对齐。** 每个语言版本的章节文件名、顺序相同；每章的环境序列（种类、`#id`、`lean`）与媒体序列完全相同。先改权威版本（`editions` 的第一个，默认中文），再同步其他版本。英文要自然、准确，不逐字硬译。
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

## 步骤

1. 确认要写的每条形式结论在 trureturing 中已有冻结声明：在 trureturing checkout 中搜索 `D5/`，或读 `Golden/Frozen/state/<module>.lean.json`。没有 → 先走 `skills/theorem-formalize`，或把它写成 `conjecture`。
2. 在权威版本中写作；新增 GID 后运行 `./tbook pin --refresh`（不移动提交，只解析新引用）。
3. 同步其他语言版本（同样的 id、lean、顺序）。
4. `./tbook check` 必须 0 错误；处理警告（未列入 SUMMARY 的文件、未使用的锁条目）。
5. `./tbook build html --book <slug>`，用 `./tbook serve` 打开改动的页面，在中英两个版本、深浅两种主题下看一遍；需要时 `./tbook build pdf epub --book <slug>` 检查版面。
6. 提交：说明改了哪些章节、新增了哪些 GID。

## 禁止

- 把未在 trureturing 冻结的结论写成 `theorem/lemma/proposition/corollary`，或删掉 `lean` 属性来让检查通过。
- 手改 `trureturing.lock.json`（只能由 `./tbook pin` 写）。
- 在本仓库写 `.lean` 文件或 Lean 证明。
- 让各语言版本的环境序列不一致，或只改一种语言。
