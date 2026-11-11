---
name: book-slides
description: 为书做演示文稿时使用：按 chrono-company-slides 方案（Slidev 53，赛博朋克主题）新建、编写、检查、构建并导出 PDF 的中英逐页对应幻灯片，用 TheoremCard/LeanBadge 引用已验证定理，并嵌入书中与站点。
---

# 演示文稿

## 适用范围

**用**：为书做讲座、答辩或概览幻灯片；修改已有幻灯片；排查幻灯片构建、版面溢出或 PDF 导出。

**不用**：可交互的探索（`book-viz`）；动画讲解（`book-film`）。

**权威**：`theme/slides/README.md`（headmatter、版式、组件、样式类）、`tools/tbook/slides.py`、示例 `books/example-monograph/slides/overview/`。

## 原则

1. **定理卡只引用已验证的定理。** `<TheoremCard cite="thm-…" gid="…">` 的编号、GID 由 `./tbook check` 对照书核对；`<LeanBadge gid>` 与定理卡只有在锁文件把 GID 解析为 Lean `theorem` 时才是绿色 `LEAN ✓`，锁文件中没有的 GID 显示红色 `UNVERIFIED`。定义卡写 `kind="definition"`：可以引用 Lean 定义，显示青色中性的 `LEAN DEF`，不是“已验证”；不写 `kind="definition"` 却引用非定理，检查会报错。开放问题用 `status="open"`，不带 `gid`。`<lean-badge>`、`<theorem-card>` 等写法同样受检查。GID 写成 `gid="…"`；用 `:gid` 或 `v-bind:gid` 时只写字符串字面量，一个标签只写一处 `gid`（Vue 取写在最前面的那个，检查也取它）。带修饰符的 `:gid.…` 与 `v-model:gid` 写在最前面时无法核对，不带参数的 `v-bind="{…}"` 写在哪里都无法核对，检查都会报错。代码块（围栏、缩进四列、`<<<` 导入）里的标签只作为代码显示、不受检查；其余每个标签都受检查（包括两个代码块之间、表格之后与 HTML 块里的标签），代码块的识别与 Slidev 53 的 Markdown 解析器一致。正文里不成标签的 `<`（如 `$a <b + 1$`）是文字，不影响其后标签的检查。徽章与定理卡要写成完整的开始标签：属性写成 `名` 或 `名="值"`，以 `>` 或 `/>` 结束；带 `#slot`、`v-bind:[参数]` 这类属性的不完整写法在 HTML 块里仍可能被 Vue 渲染，检查无法核对，会报错（`theme/slides/README.md`）。要把标签当代码展示，就放进围栏代码块，并在它前面空一行：紧跟在 `<div>`、`<v-click>` 这类开始标签之后（中间没有空行）的 ```` ``` ```` 属于 HTML 块，其中的标签会渲染，也会受检查。
2. **各语言逐页对应。** `slides.md` 是书的第一语言（`book.toml` 的 `editions` 第一项），其他语言各一个 `slides.<lang>.md`，页数相同，逐页的 `layout`、`bare`、`chapter`、`class` 与 `section` 是否存在一致；英文自然，不逐字硬译。不要建 `slides.<第一语言>.md`（会被 `slides.md` 遮蔽，检查报错），不要用 `src:` 导入别的文件的幻灯片（检查读不到，报错）。
3. **颜色只来自令牌**；绿色只给 Lean 已验证，琥珀色只给“当前”（`.tile.now`），红色标开放问题，紫色标论证未验证，青色是中性（定义）。主题类 `.mt`、`.mb-0`、`.grow` 与 UnoCSS 工具类同名，已列入 `theme/slides/uno.config.ts` 的 `blocklist`，可以用；不要自创其他与 UnoCSS 工具类同名的类（如 `c-*`），`slides-check` 会报出不在 `blocklist` 中的冲突。
4. **画布 1920×1080，不能溢出**：构建会逐页检查版面溢出与系统字体回退，任何一项失败都会让构建失败。

## 流程

```bash
./tbook slides new <book> <deck> "<中文标题>" "<English title>"   # 从 templates/slides/ 新建 slides.md（第一语言）与 slides.<lang>.md
npx slidev books/<book>/slides/<deck>/slides.md                  # 本地预览，改动即时生效
```

1. 第一页的 headmatter：`theme: ../../../../theme/slides`、`title`、`info`、`htmlAttrs.lang`（`zh-CN` / `en`）、`deck.code`、`deck.book`、`deck.title`、`deck.version`、`deck.blurb`。
2. 每页用 `layout: cover`（封面、结尾）、`layout: section`（章节页，`chapter: "01"`）或默认版式（带 `section: "…"` 页眉）。正文用 `.body`、`.kicker`、`h2.t`、`.lead`、`.card`、`.flow`、`.g2`/`.g3` 等类。
3. 数学：Markdown 段落里写 `$…$`；HTML 块里写 `<Tex t="…" />`。组件插槽中的 Markdown 不缩进，前后空一行。
4. 先写第一语言，再逐页同步其他语言。新引用了 GID 时运行 `./tbook pin --refresh`（它收集幻灯片引用的 GID）。
5. 要用书里的静态图（`books/<book>/figures/<name>.py`），就在 `books/<book>/slides/<deck>/img/` 放一个同名文件 `<name>.<lang>.svg`，页面里写 `<img src="./img/<name>.zh.svg" …>`。不要手工拷贝：`./tbook fig build --book <book>` 把它写成这张图的深色配色版（`figure.materialize(svg, "screen")`），图重画后也跟着更新；`./tbook check` 发现它过期或带着纸面配色时报错。演示文稿是纯深色的，而 `<img>` 里的 SVG 跟随浏览者的系统配色，原样拷贝的规范 SVG 在浅色系统和无头导出里会用纸面配色画在深色背景上。
6. 检查与构建：

   ```bash
   node tools/node/slides-check.mjs
   ./tbook check
   ./tbook build slides --book <book>       # 构建、逐页版面检查、导出 PDF（需要 Chromium）
   ```

   输出在 `build/slides/<book>/<deck>/<lang>/` 与 `build/slides/<book>/<deck>-<lang>.pdf`。PDF 的每页背景是一张图（`theme/slides/styles/backdrop.jpg`，见 `theme/slides/README.md`“背景与 PDF 导出”），翻页因此不卡；它与 `backdrop.css`、配色不符时构建会重新渲染，提交更新后的 `backdrop.jpg` 与 `backdrop.json`。某一页换了背景，就在它的 frontmatter 写 `class: tr-own-bg <类名>`，否则构建报错。快速迭代时可设 `TBOOK_SLIDES_NO_PDF=1` 跳过 PDF；此时不发布 PDF，章节卡片、幻灯片目录与演示页都不给 PDF 链接，发布前去掉它重新构建。
7. 嵌入章节——**所有语言版本都要加**，`src` 相同，只翻译说明：

   ```markdown
   ::: {.slides src="<deck>"}
   一句话说明。
   :::
   ```

   HTML 中为链接卡片（在线演示、下载 PDF）；PDF/EPUB 中为标题与在线地址。
8. `./tbook build site --book <book> && ./tbook serve`：站点在 `<slug>/slides/` 发布索引、各语言演示（第一语言在 `<deck>/`，其他语言在 `<deck>/<lang>/`）与 PDF（`<slug>-<deck>-<lang>.pdf`）；Release 也附上这些 PDF。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 构建报 overflow | 精简该页文字或改用更紧凑的版式；不要缩小字号到难以阅读 |
| 构建报 system-font fallback | 字符不在主题字体中：数学用 `<Tex>`，符号换成主题字体覆盖的字形 |
| `TheoremCard` 编号或 GID 不符 | 以书为准：改 `label`/`gid`，或修正 `cite` |
| 预览后出现 `<deck>/node_modules/` | Slidev 的临时文件，已被 `.gitignore` 忽略 |
| 站点上的演示路径错误 | 构建时的子路径取自 `site.toml` 的 `base_url` 或 `GITHUB_REPOSITORY`，各语言的位置取决于书的第一语言（第一语言在 `<deck>/`，其他在 `<deck>/<lang>/`）。换了地址、调整了 `editions` 的顺序或增删了语言后，`./tbook build site` 会发现已有构建过期并重新构建幻灯片 |

## 完成标准

`slides-check`、`./tbook check`、`./tbook build slides` 全部通过（PDF 页数与幻灯片页数一致）；各语言页数与版式对应；在站点上逐页看过；章节已嵌入。
