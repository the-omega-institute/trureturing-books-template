# slidev-theme-trureturing · 演示文稿主题

Slidev 53 主题（chrono-company-slides 方案的赛博朋克版本）。每份演示文稿在 `books/<slug>/slides/<deck>/`：`slides.md` 是书的第一语言（`book.toml` 的 `editions` 第一项，默认中文），其他语言各一个 `slides.<lang>.md`（如 `slides.en.md`），逐页对应，headmatter 写 `theme: ../../../../theme/slides`。不要再建 `slides.<第一语言>.md`（它会被 `slides.md` 遮蔽，检查会报错），也不要用 `src:` 从别的文件导入幻灯片（检查读不到导入的页面，会报错）。

```bash
./tbook slides new <book> <deck> "<中文标题>" "<English title>"   # 从 templates/slides/ 新建
npx slidev books/<book>/slides/<deck>/slides.md                  # 本地预览（改动即时生效）
./tbook check                                                    # 含幻灯片的静态检查
node tools/node/slides-check.mjs                                 # 同上（Node 版，含 UnoCSS 冲突检查）
./tbook build slides --book <book>                               # 构建、逐页版面检查、导出 PDF
```

画布 1920×1080，配色只来自 `theme/generated/tokens.css`；字体随主题打包（Chakra Petch、Noto Sans SC、JetBrains Mono，`@fontsource`，只发 woff2）。绿色只给 Lean 已验证，琥珀色只给“当前”，红色标开放问题，紫色标“有论证、未经内核验证”。

## Headmatter（第一页的 frontmatter）

| 字段 | 说明 |
| --- | --- |
| `theme` | `../../../../theme/slides`（由检查核对） |
| `title` | 浏览器标题与目录页标题；不得含 `<`、`>`、`{{` |
| `info` | 一句话说明 |
| `htmlAttrs.lang` | 语言的 BCP 47 标签：`zh-CN`、`en`（取自 `theme/i18n/<lang>.toml` 的 `meta.bcp47`） |
| `deck.code` | 书代号，如 `GOLDEN//OBSERVE`（页眉、封面） |
| `deck.book` | 书名（页脚、封面） |
| `deck.title` | 这份演示的短标题（页眉、目录页） |
| `deck.version` | 版本（页脚、封面）；各语言一致 |
| `deck.blurb` | 目录页与书落地页上的一句话简介 |

## 版式与每页 frontmatter

- `layout: cover`：封面与结尾。无页眉页脚；自带书代号、所钉 trureturing 提交、HUD 表盘与页码。正文放 `p.kicker`、`h1.display`、`p.lead`。
- `layout: section`：章节页。`chapter: "01"` 为大号描边编号；正文放 `p.kicker`、`h2.t`、`p.lead`，可再放一张卡片。
- 默认版式：页眉（书代号 // 标题，右侧 `section`）与页脚（书名 · 版本、所钉提交、页码）。`bare: true` 去掉页眉页脚。
- 各语言版本逐页的 `layout`、`bare`、`chapter`、`class` 与 `section` 是否存在必须一致。

## 组件

| 组件 | 用法 |
| --- | --- |
| `<LeanBadge gid="<GID>" />` | 绿色 `LEAN ✓`（链接到所钉提交上的 Lean 源码），仅当 `trureturing.lock.json` 把该 GID 解析为 Lean `theorem`；锁文件中没有的 GID 显示红色 `UNVERIFIED`。`kind="definition"` → 青色 `LEAN DEF`（Lean 定义，中性样式，不是“已验证”）。`status="open"` → 红色 `OPEN`；`status="argued"` → 紫色 `ARGUED`。 |
| `<TheoremCard label="定理1.3" title="…" gid="<GID>" cite="thm-…">` | 定理卡：编号、标题、徽章、陈述（默认插槽，前后空一行，可写 Markdown 与 `$…$`）、Lean 名。`cite` 指向书中的环境 id，`./tbook check` 据此核对编号与 GID。`kind="definition"` 用于定义：`gid` 可以是 Lean 定义，卡片为青色中性样式与 `LEAN DEF`，从不显示绿色 `LEAN ✓`；`status="open"` 用于开放问题（不得带 `gid`）。 |
| `<Stat value="4" label="…" tone="ok" />` | 大号数字。`tone`：`cyan`（默认）、`magenta`、`ok`、`warn`、`violet`、`amber`。 |
| `<Source>…</Source>` | 页面底部的出处行。 |
| `<Tex t="\beta(n)" />`、`<Tex display t="…" />` | HTML 块里的 KaTeX（HTML 块中 `$…$` 不会被处理）。 |
| `<PageNo />` | 自带版式页面的“当前页 / 总页数”。 |

GID 只能引用锁文件中已有的声明，且必须是 Lean `theorem`，除非写了 `kind="definition"`：写好后运行 `./tbook pin --refresh`（它也收集幻灯片引用的 GID），再 `./tbook check`。组件写成 `<lean-badge>`、`<theorem-card>` 等 Vue 认可的其他写法时同样受检查。

代码块里的标签只作为代码显示，不受检查；其余每个标签都受检查，包括两个代码块之间、表格之后与 HTML 块里的标签。代码块指围栏代码块、缩进四列的代码块与 `<<<` 代码片段导入。哪些行属于代码块，按 Slidev 53 实际使用的解析器判断：`tools/tbook/slides.py` 的 `code_lines` 与 `tools/node/slides-lib.mjs` 的 `codeLines` 是同一份移植，照搬 Slidev 配置下 markdown-exit（markdown-it 14）的块规则，连同规则顺序、哪些块能打断段落、块引用、列表或表格，以及块引用、列表项与脚注的缩进和懒惰续行。其中：

- GFM 表格：表头行加分隔行开始一张表；表格不接懒惰续行，遇到空行、缩进四列的行、所在容器之外的行或能打断块引用的块就结束。
- HTML 块按 `@mdit-vue/plugin-component` 的规则：`<v-click>`、`<TheoremCard>` 等组件标签可以打断段落，到空行为止；自闭合或在同一行闭合的组件标签只占这一行；`<span>` 等行内标签不能打断段落。HTML 块、`$$` 公式块与表格里的 ```` ``` ```` 都不是围栏。
- 空白与大小写按 JavaScript：标签名后的空白按 `\s` 判断（全角空格、不换行空格也算），标签名只按 ASCII 折叠大小写；切分幻灯片、去掉每页首尾的空白也与 `@slidev/parser` 一致。
- 演示文稿自己加入的语法不在其中：`mdc: true`、`setup/transformers.ts`、`vite.config` 里的 Markdown 选项都会让检查与渲染不一致，不要使用。

标签也按 Slidev 的 Markdown 读取（`@mdit-vue/plugin-component`）：只有从 `<` 起是一个完整的开始标签时，它才把标签交给 Vue。完整的开始标签是标签名，接着若干属性（`名` 或 `名=值`；值放在单引号或双引号里，或者不含 ASCII 空白与控制字符、`"'=<>` 和反引号），可选的 `/`，最后是 `>`；其余的 `<` 都是文字。所以 `$a <b + 1$`、`$0 <x <1$` 里的 `<` 不会一直读到下一个 `>`，其后的徽章与定理卡照常渲染，也照常受检查。检查在每个 `<` 处尝试读取完整的开始标签，其他标签引号里的 `<` 也不跳过：行内代码里、`$…$` 里或反斜杠后的 `<` 是文字，从那里开始的引号就不是属性值，引号里的标签会被渲染。名字解析为 `LeanBadge` 或 `TheoremCard` 的标签（Vue 的标签名到空格、`\t`、`\n`、`\f`、`\r`、`/` 或 `>` 为止）若不是完整的开始标签，例如带 `#slot`、`v-bind:[参数]` 这类属性或写成 `/ >`，检查报错：它在段落里显示为文字，在 HTML 块里却可能被 Vue 渲染，而无法核对。`tools/tbook/slides.py` 的 `citations` 与 `tools/node/slides-lib.mjs` 的 `citations` 逐条对应。

检查读取的 GID 就是 Vue 编译器传给组件的 `gid`。`gid`、`:gid`、`v-bind:gid` 都设置它，`v-model:gid` 和带修饰符的 `:gid.…`、`v-bind:gid.…`（`.prop`、`.attr` 除外）也设置它；同一个标签里写在最前面的那个生效，后面的不起作用。检查读取 `gid="…"` 和 `:gid`、`v-bind:gid` 里的字符串字面量（如 `:gid="'D5/…'"`）；写在最前面的若是别的表达式、`v-model:gid` 或带修饰符的绑定（包括 `.prop`、`.attr`），无法静态核对，检查报错。不带参数的 `v-bind`（`v-bind="{ … }"`、`:="…"`、`v-bind.prop="…"`）把一个对象合并进属性，对象里的 `gid` 会覆盖写在它前面的属性，同样无法核对：徽章或定理卡上出现这种写法，检查一律报错。不带参数的 `v-on`（`v-on="{ … }"`、`@="…"`）把其后的属性分成新的一组，Vue 用后一组覆盖前一组，所以它后面最前面的那个 `gid` 生效；检查也这样读取。

`test_slides` 用 `@slidev/parser` 切分随机生成的演示文稿，再用 Slidev 构建出的解析器与两种实现逐行比对，并比对两种实现找到的标签；另把随机生成的幻灯片用 Slidev 的 Markdown 渲染、由 Vue 编译，确认编译出的 `LeanBadge`、`TheoremCard` 依次都受检查，检查读到的 GID 正是 Vue 传给组件的 `gid`；做不到的，所在的幻灯片会报告问题（不完整的标签，或无法核对的 `gid`）。

## 背景与 PDF 导出（`styles/backdrop.css`）

每页的背景（底色、极光、扫描线、四角折角框、暗角）在 `styles/backdrop.css`。在屏幕上它们是几层 CSS；导出 PDF 时（Slidev 的打印视图给 `<html>` 加上 `print` 类）换成一张图 `styles/backdrop.jpg`：这几层整页的半透明渐变写进 PDF 后成为软蒙版与渐变，阅读器每翻一页都要重新合成（约两秒一页），一张图则几乎即时画出，文字与其余图形仍是矢量。图由 `node tools/node/slides-backdrop.mjs` 在 Chromium 中按 `backdrop.css` 与 `theme/generated/tokens.css` 渲染（1920×1080），所用输入的指纹记在 `styles/backdrop.json`：

- 改了 `backdrop.css` 或配色（`./tbook theme`）后，运行 `node tools/node/slides-backdrop.mjs`（`./tbook theme` 会自动调用）并提交 `backdrop.jpg` 与 `backdrop.json`；`backdrop.css` 只能用 `tokens.css` 中定义的变量，不能引用 `url()`（图只由这两个文件渲染，检查会报错）；
- `./tbook theme --check` 与 `node tools/node/slides-check.mjs` 发现图与输入不符时报错；`./tbook build slides` 构建前会自动重新渲染，并逐页检查打印视图与导出的 PDF 确实用了这张图。

某一页要换背景（底色、背景图或其他背景属性）时，写一条带类名的规则，放在演示文稿目录的 `style.css` 里（如 `.slide.my-bg { background-color: #401028; }`），并在这一页的 frontmatter 写 `class: tr-own-bg my-bg`。`tr-own-bg` 让这一页在 PDF 中保留 CSS 的背景层，与屏幕上一致（这一页翻页会慢一些）；没有它，PDF 会用背景图盖住这页的底色、去掉扫描线与折角框。`./tbook build slides` 会逐页比较每页的背景与主题的默认背景，背景不同却没有 `tr-own-bg` 的页面报错。

## 样式类（`styles/deck.css`）

`.body`（正文区，`.center` 垂直居中）、`.kicker`、`.display`、`h2.t`（`em` 高亮；`em.warn`、`em.ok`、`em.magenta`）、`.lead`、`.card`（`.hot`、`.ok`、`.warn`、`.violet`）、`.tile`（`.now` 表示“当前”）、`.flow > .step`（`.ok`）、`.readout`（`dt`/`dd`，`dd.cy`、`dd.hot`）、`.g2`/`.g3`/`.g4`/`.g6`/`.split`/`.row`、`ul.plain`、`table.t`、`.eq`、`.mono`、`.muted`、`.dim`、`.sm`、`.xs`、`.hl-cyan`/`.hl-ok`/`.hl-warn`/`.hl-violet`/`.hl-amber`/`.hl-magenta`、`.mt-s`/`.mt`/`.mt-l`。其中与 UnoCSS 工具类同名的主题类（`mt`、`mb-0`、`grow`）已列入 `uno.config.ts` 的 `blocklist`，可以放心使用。不要自创与 UnoCSS 工具类同名的类（如 `c-*`、`p-4`）：`node tools/node/slides-check.mjs` 会报出不在 `blocklist` 中的冲突；确需新增主题类时，同时把它加入 `blocklist`。

## 界面文字

徽章、页脚标签与站点按钮的文字取自 `theme/i18n/<lang>.toml` 的 `[slides]` 表（书库可在 `i18n/<lang>.toml` 覆盖）；`i18n.ts` 中的默认值只作后备。

### 书面证明

书面证明使用 `<TheoremCard status="written-proof" cite="书中结果 id" label="…" doi="…" source="…" request="…">`，显示紫色“书面证明 / WRITTEN PROOF”。来源字段与书中一致，不得有 `gid`（空值也不行）；被引用的结果须关联本语言的非空证明。徽章本身不带链接，来源与形式化请求在卡片页脚提供链接，不计入 Lean 数量。独立 LeanBadge 不能代替带证明关联的定理卡。

`argued` 保留给非正式论证；不能用它代替书中明确的书面证明状态，或把书面已证结果当作开放问题。

状态及来源属性只用单个字面值，不使用动态绑定或重复属性。见 [形式化请求规范](../../docs/FORMALIZATION-REQUESTS.md)。
