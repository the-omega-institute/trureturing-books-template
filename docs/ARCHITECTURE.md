# 架构与契约 · Architecture and contracts

本文件描述 trureturing 书籍模板的结构，以及各组件之间的接口契约。改动任一组件前先读这里；改动契约时同步更新本文件。

## 1. 原则

1. **Lean 验证只来自 trureturing。** 书中 `theorem / lemma / proposition / corollary` 默认引用 trureturing 中已被 Lean 内核验证并冻结的声明；源文有证明但无匹配声明时必须显式标为 `status="written-proof" proof="id"` 且不带 `lean`，每版关联非空书面证明，并提供 DOI、原文定位与 trureturing-requests issue，见 [形式化请求规范](FORMALIZATION-REQUESTS.md)。已有匹配 Lean 验证时必须引用 Lean。冻结成员身份的唯一判据是所钉提交上存在 `Golden/Frozen/state/<module>.lean.json` 且其中列有该声明（trureturing CLAUDE.md §1.3 冻结律）。Lean 代码只写在 trureturing，本仓库不含 `.lean` 文件。
2. **证据状态不可混淆。** Lean 结果由冻结声明支撑；书面证明由作者与评审负责，紫色徽章不带验证链接、不计入 Lean 数量。真正开放的结论用 `conjecture` 或 `problem`。
3. **一次编写，多端导出。** 同一份 Markdown 生成 HTML（mdBook）、PDF（Typst，屏幕版与印刷版）、EPUB 3（Apple Books）。编号、标签、徽章与 Lean 链接由 `tools/tbook/render.py` 统一计算，各端一致。
4. **多语言，默认中文与英文。** 每本书有若干语言版本（edition），第一个为权威版本；`./tbook check` 要求各版本的章节文件、环境序列（种类、id、Lean 引用、证据状态、证明关联与来源字段）逐条一致。
5. **配色单一来源。** 赛博朋克配色只在 `theme/tokens.json` 定义，`./tbook theme` 派生出各端使用的 CSS / Typst / JS（幻灯片的打印背景图由 Chromium 按派生的 CSS 渲染，见 §2 的 `slides/`）。绿色只留给 Lean 已验证，琥珀色只留给“现在/当前选择”，红色标开放问题。
6. **模板可升级。** `template.toml` 列出模板托管的路径；下游只改自己的路径（`books/`、`site.toml`、`trureturing.lock.json`、`i18n/`、`PROJECT.md`、`README.md`）。`./tbook template update` 把托管路径同步到模板的新版本。

## 2. 目录

```
site.toml                 站点配置（下游所有）
trureturing.lock.json     所钉的 trureturing 提交与已解析的声明（由 ./tbook pin 生成，提交入库）
template.toml             模板版本与托管路径（模板所有）
template-manifest.json    托管文件清单与 sha256（模板发布时生成，用于检测下游本地改动）
tbook                     CLI 入口（bash → python3 -m tbook）
books/<slug>/
  book.toml               书的元数据、语言版本、输出开关
  <lang>/SUMMARY.md       每个语言版本一个目录，mdBook SUMMARY 格式
  <lang>/*.md             章节；各版本文件名相同
  figures/<name>.py       静态图脚本（tbook.figkit）；figures/<name>.<lang>.svg 是它生成并提交的图
  assets/                 各语言共享的图片等（章节中写 ../assets/x.svg）
  viz/<id>/               交互可视化（trureturing-visualize 方案）
  viz/visualizations.json 本书可视化注册表
  slides/<deck>/          演示文稿（Slidev，chrono-company-slides 方案）：slides.md（书的第一语言，即 editions 第一项）、slides.<lang>.md（其他语言）
  films/<NNN>-<name>/     视频（trureturing-film 方案）：film.json、script.json、scenes.js
theme/
  tokens.json             设计令牌（唯一来源）
  generated/              由 tokens.json 派生：tokens.css、tokens.typ、tokens.mjs
  i18n/<lang>.toml        界面与排版用语（下游可在 i18n/<lang>.toml 覆盖或新增语言）
  mdbook/                 mdBook 主题（CSS/JS）
  typst/                  PDF 模板（book.typ、cover.typ）
  epub/                   EPUB 样式
  site/                   书库首页与每本书落地页的样式/脚本
  viz/                    可视化共享运行时（theme.css、shell.js、kit.js；solid-core.js 是实体的造型核心，与 vendor/ 里钉版的 three.js 一起只在 kit.solid 首次调用时动态加载）
  slides/                 Slidev 主题；styles/backdrop.css 是每页的背景层（底色、极光、扫描线、四角折角框、暗角），
                          导出 PDF 时换成 styles/backdrop.jpg 一张图（整页半透明渐变在 PDF 阅读器里每页要合成约两秒），
                          由 tools/node/slides-backdrop.mjs 按 backdrop.css 与 tokens.css 渲染，指纹记在 backdrop.json
  film/                   视频共享引擎与流水线脚本
templates/                新书、新静态图、新可视化、新 deck、新视频的起始模板
tools/tbook/              Python 包（构建、校验、发布）
tools/filters/            Pandoc Lua 过滤器
tools/node/               Node 脚本（KaTeX 渲染、可视化校验/测试/缩略图、静态图预览、幻灯片构建）
skills/                   内置 agent skills（.claude/skills → ../skills）
.github/workflows/        CI、Pages、Release、模板同步、Lean 深度验证
```

### 2.1 `site.toml`

| 键 | 说明 |
| --- | --- |
| `[site] repo` | GitHub 仓库 `owner/name`；留空时 CI 用 `GITHUB_REPOSITORY`，本地由 git remote 推断（`TBOOK_REPO` 优先） |
| `[site] base_url` | Pages 根地址，PDF/EPUB 的外链用它拼绝对地址；留空则由 `repo` 推断（`TBOOK_BASE_URL` 优先） |
| `[site] languages` | 站点界面语言，第一个为默认语言，不得重复；默认 `["zh", "en"]` |
| `[site.title]`、`[site.tagline]` | 站名与标语，每种语言一行 |
| `[site] logo`、`[site] branch` | 可选：站点品牌（§6）；“建议修改”链接指向的分支（§5） |
| `[trureturing] repo`、`branch` | 形式化仓库；`./tbook pin` 跟随、`./tbook check` 核对的分支（默认 `dev`） |
| `[books] order` | 书库首页的顺序；未列出的书按目录名排在后面 |
| `[books] hide` | 隐藏的书：glob 模式的列表，默认 `[]`（不隐藏）；书库用 `["example-*"]` 隐藏模板附带的示例书 |
| `[figures] phone_labels` | 静态图在手机上的最小标签不到 10 px 时的级别：`"warning"`（默认）或 `"error"`（`./tbook check` 与 `./tbook fig build` 失败）；其他值报错（§4 第 7 项） |

`[books] hide` 的每一项是非空字符串，按 Python 的 `fnmatch.fnmatchcase` 与书的目录名（slug）匹配：`*`、`?`、`[seq]`、`[!seq]`，区分大小写；类型不对时 `site.toml` 报错。被隐藏的书仍留在 `books/` 中，但所有命令与产物都当它不存在，这样从模板创建的书库不必删除示例书，以后用 git 合并模板改动时就不会因示例书冲突（`docs/UPGRADING.md` §6）：

- 列出书的唯一来源是 `config.book_slugs()` / `config.load_books()`（Node 端是 `tools/node/slides-lib.mjs` 的 `listBooks()`，`viz-common.mjs` 的 `listBooks()` 用同一套规则，`tools/tests/test_hide.py` 核对两端的模式匹配一致），它们跳过隐藏的书。因此 `./tbook check`、`./tbook pin` 与 `pin --refresh`（只收集可见书的引用，只被隐藏的书引用的声明从锁文件中删去）、`./tbook build` 的各个目标、站点首页与 `manifest.json`、构建缓存的单元（`./tbook cache status|prune|export`；`prune` 删去隐藏书的条目）、`./tbook lean-project` 的引用说明、`release.yml` 的发版计划、`viz-validate`、`viz-test`、`slides-check`、`slides-build` 都看不到它；工作流中找视频与幻灯片的步骤用 `./tbook books --files <glob>`（只需 Python 标准库，在安装工具链之前也能运行）。`./tbook serve` 只伺服已构建的 `_site/`，不受影响。
- 按 slug 点名一本隐藏的书是错误，并说明怎样取消隐藏（从 `hide` 中去掉该模式，再运行 `./tbook pin --refresh` 把它引用的声明解析回锁文件；Python 的 `config.hidden_error()` 与 Node 的 `hiddenError()` 文字相同）：`--book <slug>`、`./tbook new-chapter <slug>`、`./tbook viz|slides|film new <slug> …`、`./tbook slides|film list <slug>`、`<slug>-v<version>` 的发版 tag、Node 脚本的书参数（`slides-check --book`、`viz-validate <slug>` 等）。目录路径不是名字：`config.load_book()`、视频流水线（`theme/film/film.sh <dir>`）与 `viz-validate <dir>` 照常读取任何书，但隐藏的书的 Lean 引用只在锁文件仍收录它们时才能解析：隐藏期间运行过 `./tbook pin --refresh` 后，只被它引用的声明已不在锁文件中，按路径读取它时这些引用报“不在锁文件中”。
- `./tbook check` 输出一行列出被隐藏的书（提示，不是警告）；`./tbook new-book` 新建的 slug 匹配 `hide` 时照常创建并警告；`./tbook doctor` 列出可见与隐藏的书；`./tbook books [--hidden] [--files GLOB]` 列出可见（或隐藏）的书，或它们的文件 `books/<slug>/GLOB`。

## 3. 写作语法

全部是 Pandoc Markdown 的子集，GitHub 上可直接预览。

### 3.1 环境

```markdown
::: {.theorem #thm-deficit title="亏量只取三个值" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
对所有自然数 $v_1, v_2$，$c(v_1, v_2) \in \{-1, 0, 1\}$。
:::
```

| 种类 | 类名 | Lean 引用 | 编号 | 徽章 |
| --- | --- | --- | --- | --- |
| 形式结论 | `theorem` `lemma` `proposition` `corollary` | 默认**必须**，且解析为 Lean `theorem` | 是 | `LEAN ✓`（绿，链接到第一条声明）；所引 GID 不能全部经锁文件解析为 Lean `theorem` 时，构建显示红色 `UNVERIFIED`，各端徽章都不是链接，页脚与账本只链接锁文件解析了的声明（`./tbook check` 报错） |
| 书面证明 | 上述形式结论 + `status="written-proof" proof="id"` | **禁止**，每版关联非空 proof，必须有 DOI、原文定位和已登记的请求 issue | 是 | `书面证明 / WRITTEN PROOF`（紫，无链接，不计入 Lean 数量） |
| 定义 | `definition` | 可选；给出则必须解析 | 是 | — |
| 开放 | `conjecture` `problem` | **禁止** | 是 | `OPEN`（红） |
| 非形式 | `example` `remark` | 可选；给出则必须解析 | 是 | — |
| 证明 | `proof` | 可选 | 否 | ∎ |
| 媒体 | `viz` `film` `slides` `figure` | 可选 | 否 | — |

- `#id`：形式结论、定义、开放条目必须有 id；id 以字母开头，可含字母、数字、`-`、`_`、`:`。
- `title="…"`：可选，单行行内 Markdown，可含行内数学；属性值里反斜杠与花括号原样保留（`title="$\mathbb{N}$ 上的 $\{-1,0,1\}$"`）。值内的双引号写 `\"`；`\\` 读作一个反斜杠，所以 TeX 的 `\\` 要写成 `\\\\`。标题中可以写 `[@id]`（见 §3.3）。
- 标题的统一读法（环境标题与 SUMMARY 中的章节标题）：`$…$` 内的 TeX 不变；`$…$` 与行内代码之外，反斜杠加 ASCII 标点是 Markdown 转义，所有输出都显示标点本身（`C\*-代数` → C*-代数，`\$5` → $5，不是公式）。标题文字用 `mdscan.unescape_markdown()` 的结果；站点落地页的验证摘要与目录（包括部分、嵌套与草稿章节）列出标题时，标题文字照此读，公式在构建时由 KaTeX 渲染（`site.title_html()`，全站一次 Node 进程；Node 或 KaTeX 不可用、或某个公式渲染失败时显示其 TeX 源码并警告），有公式的页面才加载站点自带的 KaTeX 样式与字体（`assets/katex/`）；mdBook 页头由 `render.title_html()` 写出，字面的 `$`、`\`、反引号写成字符引用，所以页头里的公式与 Pandoc 看到的完全相同；mdBook 的章节标题、部分标题和书名中的公式与正文一起预渲染；暂存的 SUMMARY 与书名配置使用公式的可见文字（`<title>` 与搜索索引因此不带 TeX），其余 ASCII 标点加反斜杠（`html._escape_title()`）。mdBook 会剥去 SUMMARY 的 HTML 并转义目录文字，所以构建后 `html.restore_title_math()` 按条目顺序把公式 HTML 写回 `toc.html` 与 `toc-*.js`（含草稿和章节编号），同时恢复菜单栏书名；目录脚本重新计算内容哈希，各页引用随之更新；Pandoc、账本拿到的是原 Markdown（`model.title_markdown()`、`Chapter.title_md`）。
- `lean="GID [GID …]"`：一条或多条，空格或逗号分隔。
- 只有显示 `LEAN ✓` 的形式结论计入各输出中的“LEAN ✓ n”与定理数（账本、版权页、封面、站点）；显示 `UNVERIFIED` 的不计入。
- 编号：同一顶层章节内，所有编号种类共用一个计数器：`定理2.1`、`定义2.2`（中文、日文不加空格；英文为 `Theorem 2.1`）……前言类（prefix）章节用 `0.n`，附录类（suffix）章节用 `A.n`、`B.n`。
- 简写 `::: proof`（单个类名，无花括号）也可以。

### 3.2 GID

与 trureturing Blueprint 相同：`<模块路径>.<声明名>`，如 `D5/S1/Deficit/DeficitThreeValued.deficit_three_valued`。声明名是 Lean 名：分量可以是 Lean 标识符（含希腊字母等类字母符号、下标与 `'` `!` `?`），其他分量写成 `«…»`；GID 中不得含空白或逗号。按名称分量匹配完整名或其后缀，在该模块的冻结状态片中必须恰好匹配一个非私有声明。

### 3.3 引用与链接

- `[@thm-deficit]` → `定理1.2`（链接到该环境；跨章节有效）。环境标题中的 `[@id]` 显示为被引条目的引用文字（如 `定理1.2`；HTML 中是纯文字，PDF/EPUB 中链接到该条目）；与正文一样，id 不存在时 `./tbook check` 报错。
- `` [`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued) `` → 指向所钉提交上 Lean 源文件（含行号）的永久链接。尖括号 `(<lean:GID>)`、任意标题（`"…"`、`'…'`、`(…)`；Pandoc 的 Markdown 不认 `(…)` 标题，改写链接时一律写成 `"…"`）、链接文字中成对的方括号（至多三层，链接里的图片照常处理）、引用式（`[x][lt]` + `[lt]: lean:GID`，定义也可以在列表项或块引用里）与自动链接 `<lean:GID>`（显示为 GID）相同：`model` 逐行收集每种写法的 GID（`mdscan.lean_link_gids()`），`check` 核对、`pin --refresh` 收录。锁文件不能解析时，行内链接只保留文字，引用式定义的地址写成 `#`（PDF/EPUB 显示为文字），从不输出 `lean:` 地址。逐行读不到的 `lean:` 地址（链接文字、地址或标题跨行，定义的标签跨行或地址在下一行，原始 HTML 的 `href`/`src`）由 `mdscan.stray_lean_links()` 按段落找出（定义只算能开始定义的行上、地址后只有可选标题的，见下条：`[1]: <lean:GID> 文字` 与段落续行上的 `[x]:` 不是定义，其后的 `<lean:GID>` 是自动链接，照常收集、改写）：`model` 报错，`render` 去掉这些地址（链接只留文字，定义与属性写成 `#`）并警告；`tr-book.lua` 再把漏到 Pandoc 的 `lean:` 链接与图片换成文字。这样的地址写成 `<lean:GID>` 时，逐行看去像自动链接（`b](<lean:GID>)`，或单独一行的 `<lean:GID>`），CommonMark 却把它读作该链接或定义的地址：`mdscan.text_views()` 与 `map_text()` 在逐行处理时把它的 `<` 换成私用字符 U+E000（`hide_lean_destinations()`，`map_text()` 处理后换回），所以 `model` 不把它算作引用，`render` 不改写它，随后照样报错、去掉。环境标题中的 `lean:` 链接只保留文字（`model.title_markdown()`），`check` 报错。
- 图片：`![说明](../assets/figure.svg)`。指向书目录内、语言目录外的文件会被复制进构建目录 `_book/`。引用式 `![说明][fig]` + `[fig]: ../assets/x.svg`、尖括号 `![说明](<../assets/有 空格.svg>)` 与百分号编码的路径同样处理（输出为百分号编码的 `_book/…`）。引用式定义按 CommonMark 判定（`mdscan.REFDEF_RE`）：独占一行，可以在块引用标记、列表标记或列表续行的缩进之后（`mdscan.CONTAINER`），地址后只能有可选标题（可含反斜杠转义），不带尖括号的地址不能以 `<` 开头；`[注]: 见 [图](x.svg)`、`[1]: Knuth, TAOCP.` 是段落（Pandoc 的 Markdown 允许多个词的地址，会把这样的行当作定义吞掉，所以 pandoc 目标转义标签的 `[`，在列表项、块引用与列表续行中也一样，各端都显示这一段）。定义不能打断段落（mdBook 与 Pandoc 相同）：`mdscan.definition_roles()` 按 `scan_blocks` 的 `BlockScan.cont`（即 `Text.cont`：该行接续上一行的段落）给每行一个角色，`DEF_START` 是段落的第一行或紧接在段落开头的定义之后（标题跨行的定义也算），只有这样的行才读作定义；`DEF_DEST` 是只有标签的 `[x]:` 的下一行、内容是地址加可选标题。`mdscan.iter_text()` 逐行给出角色，`model`（`lean_link_gids()`）、`render.rewrite_links()`（因而 `check`）、`stray_lean_links()` 与 `label_only_as_text()` 都按角色读：接在段落文字下一行的 `[fig]: ../assets/x.svg` 是文字，不改写、不收集、不报错，Pandoc 也读作文字，所以不转义（跨行公式中的 `[0,1]:` 行同样是段落续行，不会被转义而弄坏公式）。逐行看是段落、自动链接改写后却像定义的行（`[3]: <lean:GID>，文字` 写成 `[3]: [GID](url)，文字` 后，`[` 开头的地址合法）转义标签的 `[`。地址在下一行的定义 mdBook 与 Pandoc 都读，两行都不显示，但 `render` 不读这样的地址：带协议的（`lean:` 由 `stray_lean_links()` 处理）以外，记入 `ctx.issues`，`check` 与构建都给出警告。冒号后没有内容、下一行（同一文本块中）也不是“地址加可选标题”的 `[x]:` 同样是段落，Pandoc 却读成空地址的定义（或把下一行当作地址）并丢掉这些行，所以 pandoc 目标也转义它的 `[`（`render.label_only_as_text()`）。地址为空的链接与图片（`[x]()`、`![x]()`、`[x]: <>`）照原样输出（定义的 `<>` 不能改写成空地址，否则就不是定义了），`check` 警告：HTML 链接到本页、图片是破图，而 Typst 不接受空 URL、epubcheck 不接受空图片地址，所以 `tr-book.lua` 在 PDF/EPUB 中把它们换成链接文字或图片说明并警告。HTML 中，指向 `README.md` 章节的链接与指向其中条目的 `[@id]` 输出为 `index.html`（mdBook 把 README 发布为 index.html）。
- HTML 注释不出现在任何输出中。以 `<!--` 开头（在所在容器内缩进不超过三格）且未在本行闭合的行开始注释块，到含 `-->` 的行为止（`mdscan.scan_blocks()`，见下条），按原样输出；没有 `-->` 时报错。其他 `<!--` 是行内注释：同一行闭合的像行内代码一样跳过；未在本行闭合的延续到同一段落后面的行，直到 `-->`（CommonMark 的原始 HTML 可以跨行，mdBook 与 Pandoc 都隐藏它）。GFM 表格（含 `|` 的行后接单元格数相同的分隔行，按 pulldown-cmark 的规则）的每一行各算一个段落：mdBook 不让单元格里的注释延续到下一行。`BlockScan.carry` / `Text.carry` 记录每行开头与结尾是否在这样的注释里，逐行处理的函数经 `mdscan.map_closed()`、`text_views()`、`iter_text_lines()` 看到的是注释在本行闭合的行（行首补 `<!--`、行尾补 `-->`，处理后再去掉），因此不必知道上下文。段落在 `-->` 之前结束时，这个 `<!--` 是文字：HTML 显示它，Pandoc 却隐藏到后文的下一个 `-->`，所以后文有 `-->` 时报警告。注释中的链接、`[@id]`、`lean:` 链接与环境都不改写、不检查、不编号。
- 块结构只有一个模型：`mdscan.scan_blocks()` 按 CommonMark 的块规则（mdBook 与 Pandoc 在这些结构上一致）逐行判定哪些行是围栏代码、缩进代码或注释块，哪些行接续段落。容器有块引用、列表项（内容从标记后的第一个字算起）、定义（`:`、`~`，同列表项；只有 `:` 的行从冒号后一列算起，两端一致）与脚注（正文缩进 4 列）；缩进代码是比容器内容再缩进 4 列、且不接续段落的行；围栏在容器结束时随之结束。定义跟在术语（同一容器中只有一行的段落，紧挨着或隔一个空行）或同一术语的上一条定义之后。跨行的公式把到结束定界符为止的行都留在所在段落，其中不开始列表项、块引用、标题、缩进代码或注释：Pandoc 先读公式，HTML 端在 mdBook 之前渲染公式。公式不跨过在所在段落的容器中开始围栏代码块的行：代码块上方未配对的 `$` 若与代码里的 `$` 配对，结束围栏就会在 mdBook 中开始一个直到文末的代码块。配对 `$` 的是 `mdscan._Formulas`，规则同 `mathrender.find_math`（不跨空行或只含 `>` 的行，不跨行内代码、注释、HTML 标签、自动链接与链接地址，这些模式只定义在 `mdscan.MATH_OPAQUE`），只是逐行读：跨行的 HTML 标签或元素它看不到。从某行行首起公式在何处闭合，每行（按段落的容器）只算一次；`find_math` 也把可作结束定界符的位置、遮蔽区与空行各找一次再二分查找，所以一个段落或表格里大量未配对的 `$`（每行一个价格）耗时与文本长度成正比。`parse_blocks()`（因而 `check`、`model` 与两个渲染目标）、PDF/EPUB 暂存（`pandoc._code_mask`）与 KaTeX 预渲染（`mathrender._mask`）都读它。mdBook 与 Pandoc 读法不同之处，模型取其一，记入 `BlockScan.notes`，由 `parse_blocks()` 报警告：随容器结束或到文末仍未闭合的围栏代码块（按 mdBook：代码块在此结束，或到文末都是代码；Pandoc 可能把缩进不足的围栏当作结束围栏，未闭合的围栏不当作代码块），多于一行的术语或术语与定义之间多于一个空行（按 Pandoc：不是定义；mdBook 读作定义），`~` 开头的定义（按 Pandoc：是定义；mdBook 不认），只有 `:` 的定义行后隔空行才写正文（按 Pandoc：仍是该定义的正文；mdBook 在空行处结束定义），围栏代码块前未闭合、Pandoc 却跨过围栏配对的 `$`（按 mdBook：是代码块；Pandoc 的配对按它自己的规则判断：`$` 之后第一个 `$` 前面不是空白、后面不是数字，`$$` 之后第一个 `$$`，中间没有空行；警告指出这个 `$` 的行与列）。未建模：原始 HTML 块的内部（Pandoc 在其中读 Markdown，mdBook 不读）、跨行的引用式定义（`definition_roles()` 只用它判断下一行能否开始定义）、Pandoc 独有的列表标记（`a.`、`(1)`、`#.`）。
- 链接（非图片）到书内或语言目录内的文件（如 `../assets/data.csv`）：HTML 链接到构建目录中的副本；PDF/EPUB 改为指向网站上的同一副本（地址由 `site.book_url` 拼出），`base_url` 未知时只保留链接文字并警告。
- 脚注标签与无显式 id 的标题按章节独立（与 HTML 每章一页一致）：PDF/EPUB 合并全书时，脚注标签变为 `[^<章节 id>--<标签>]`（`pandoc.scope_footnotes()`：改名的只有本章的定义，也包括块引用与列表项里的，以及 mdBook 读作脚注引用、标签与定义完全相同的引用；其余 `[^x]` 原样保留。各章 mdBook 读作定义的行都已改名，HTML 端不当作脚注的 `[^x]` 在 PDF/EPUB 中因此也不是脚注），标题得到全书唯一的 id（重名时为 `<章节 id>--<slug>`），`other.md#x` 与 `#x` 在所指章节内解析（`pandoc._Linker.anchor()`）：环境 id 原样保留，其余片段依次查该章的显式 `{#id}`、标题的 slug（先 mdBook 的，再 Pandoc 的）与原始 HTML 里的 `id="…"`（Typst 不输出原始 HTML，`tr-book.lua` 在 PDF 中该处放一个同名的标签；标题里的空锚点 `<a id="x"></a>` 移到标题之后，因为大纲、页眉与 EPUB 目录都会重复标题文字）。块引用与列表项里的标题（`pandoc.contained_headings()`）与顶层标题一起按文档顺序编号，同样得到全书唯一的 id，写在其标记之后（`pandoc.with_heading_id()`）。该章没有的片段在 HTML 中只打开该页，在 PDF/EPUB 中也不落到别章的同名 id 上：它写成 `#<章节文件>#<片段>`，`tr-book.lua` 找不到这个 id，把链接显示为文字并警告。slug 就是 mdBook 给该标题的 id：标题中的公式按 KaTeX 显示的文字计算（`## 关于 $\beta$ 的估计` → `关于-β-的估计`，构建 PDF/EPUB 因此也调用 Node；不可用时退回 TeX 源码并警告），脚注引用按 mdBook 显示的编号计算（本章各标签按首次被引用的先后编号，正文、标题与脚注定义里的引用都算；紧挨着的两个引用之间有一个空格：`## 注释[^a][^b]` → `注释1-2`；本章没有定义的引用是普通文字，mdBook 不读的位置也不算：转义的 `\[^x]`、代码与 HTML 注释、公式（HTML 端已由 KaTeX 预渲染）、CommonMark 的原始 HTML 块（含 `:::` 行，HTML 端把它们写成 HTML，环境标题在其中；HTML 块没有惰性续行，随所在的块引用或列表项结束：容器取块首行上的 `>` 与列表标记，以及块首行缩进进去的、前面各行打开的列表项（`- 项`、空行、`  <div>`），块首行其余的缩进不是容器；主题分隔线 `---`、`***` 结束段落，不是惰性续行，块引用段落下不在该块引用里的 `===` 则是惰性续行，不是标题下划线）、HTML 标签（属性名按 CommonMark：`<b and [^x] c>` 不是标签）、自动链接、链接地址与标题，以及紧接 `(…)` 或 `[x]`（x 含非空白字符）、被 mdBook 读成链接的 `[^x]`；`pandoc.footnote_numbers()`，`./tbook check` 用 `pandoc.footnote_problems()` 对两端读法不同的写法给出警告），标题里的 HTML 注释不计入（`## 注释[^a]<!-- c -->[^b]` → `注释12`，两个引用之间隔着注释，不算紧挨着），`{-}`（即 `.unnumbered`）等属性块也照此处理；Pandoc 自己的 slug（公式取 TeX，脚注取标签，上例为 `注释ab`）作为后备片段。
- PDF/EPUB 合并时，围栏代码块、缩进代码块（任何容器中，`mdscan.scan_blocks`）、HTML 注释与行内代码原样保留：其中的链接、脚注与公式都不改写（HTML 端的 KaTeX 预渲染同样跳过它们）。紧贴在文字行下的标题前补一个空行：mdBook 本来就把它当作标题，Pandoc（`blank_before_header`）需要空行，否则 `{#id}` 会作为正文出现。`:::` 开头行与脚注定义同理：HTML 端的环境是能打断段落的 HTML 块，mdBook 也在文字行下读脚注定义，Pandoc 却只在空行后开始 div、读定义，否则整段（环境的页头、编号与徽章在内）作为正文出现；块引用里的定义前补的是 `>` 行，紧接在另一条定义下或带列表标记的定义不动。HTML 端每个 div 的输出后跟一个空行：mdBook 的 HTML 块延续到下一个空行，结束行 `:::` 后紧接的文字或标题因此仍按 Markdown 读，与 Pandoc 相同。

### 3.4 媒体

```markdown
::: {.viz src="golden-carry" height="560"}
图注（可选）。
:::

::: {.viz src="my-viz" preset="half" height="500"}
引用一张实验卡：HTML 中开在那张卡上（`&preset=half`，不带内部滚动），PDF/EPUB 中用 `viz/my-viz/fig-half.<lang>.jpg`。
:::

::: {.viz src="trureturing-visualize:robin-lattice"}
:::

::: {.film src="001-golden-deficit"}
:::

::: {.film src="trureturing-film:film-001-v1"}
:::

::: {.slides src="overview"}
:::

::: {.figure src="phase-square"}
**一句标题。** 图注（必须有）：只说图里看得见的东西。
:::
```

- 静态图（`tbook.figure`，`skills/book-figure`）：`src` 是图名，对应脚本 `books/<slug>/figures/<name>.py`。脚本定义 `SIZE`、`ALT`（每种语言一条给看不见图的读者的描述）与 `draw(fig)`，用 `tbook.figkit` 画，只写颜色角色（`figkit.ROLES` 把角色对到 `theme/tokens.json` 两套配色里同名的令牌，`ALIASES` 是语义名）。`./tbook fig build` 对每个语言版本运行脚本，写出规范 SVG `figures/<name>.<lang>.svg`（提交入库）：形状用角色类 `ts-<角色>`（描边）、`tf-<角色>`（填充），样式表里是浅色配色，`prefers-color-scheme: dark` 时为深色配色（文件单独打开或在 GitHub 上预览时用）。各端都不直接显示这个文件：
  - mdBook：`figure.inline_html()` 去掉样式表与固定尺寸，把图内联进 `<figure class="tr-media tr-figure">`；`tr/tr-figure.css`（`figure.mdbook_css()`，构建时生成）让角色类取页面的 `--tr-*` 令牌，所以图随主题切换、随浏览器打印变成浅色。内联的 SVG 中没有空行（空行会结束 Markdown 的 HTML 块）。脚本写 `WRAP = True` 时各栏（`fig.row()` / `fig.panel()`，规范文件里是嵌套的 `<svg class="tr-fig-panel">`）各成一个 `<svg>`，放在弹性盒里：宽度不小于 700 像素时同一行的各栏并排（一起缩放），否则叠放；各栏排成几行时每行各成一个弹性盒（外层 `tr-fig-rows`），宽屏上行还是行，手机上逐栏叠放。图注是块后的 Markdown，写在 `<figcaption class="tr-media-caption">` 中。
  - Pandoc（PDF/EPUB）：`figure.materialize()` 把一套配色写进样式表，经 `RenderContext.book_texts`（书目录下的相对路径 → 内容）由 `pandoc.stage()` 写到 `_book/figures/`：`<name>.<lang>.svg`（浅色，加不透明底，EPUB 用）、`.print.svg`（浅色）、`.screen.svg`（深色）。块输出为 `::: {.tr-media .tr-figure}`，其中的图片带 `tr-fig=1` 与按自然宽度算出的 `width`（760 单位对应版心宽度）；`tr-book.lua` 在 Typst 输出中把它换成 `image("<…不带扩展名>" + tr-fig-ext, …)`，`theme/typst/book.typ` 的 `tr-fig-ext` 按变体取 `.screen.svg` 或 `.print.svg`，`tr-media(kind: "figure")` 不画面板，只排图与图注。
  - 画图库强制的标准（`figkit.FigureError`）：字号 ≥ 12、线宽 ≥ 1、文字不出画布（按估计的字宽）、角色名已知、宽度 ≤ 760；坐标保留两位小数，输出可复现。
- HTML：可视化以 iframe 嵌入（`height` 160–2400，默认 560），附“全屏打开”；视频以 `<video controls preload="metadata" playsinline>` 播放站内的 `films/<id>/<outputs.narrated_720p>`（海报为提交的 `poster.jpg`），附 `film.json` 的 `outputs` 所列视频的下载（默认只有 720p 旁白版；列出时另有 1080p、纯配乐）；站点没有该视频时，`site.mark_films` 给 `<figure>` 加 `tr-film-unbuilt`，样式改为显示海报与“视频未构建”，并把隐藏的播放器改为 `preload="none"`，浏览器就不去请求不存在的文件（视频构建后复原为 `metadata`）；幻灯片为链接卡片（在线演示、PDF）。
- PDF / EPUB：静态缩略图或海报 + 图注 + 在线地址（由 `site.toml` 的 `base_url` 拼出；没有 `base_url` 时视频只有海报）。
- 书内媒体的源文件：
  - 可视化：`books/<slug>/viz/visualizations.json`（登记表）+ `viz/<id>/`（`index.html`、`style.css`、`main.js`、`thumb.jpg`）与 `viz/tests/<id>.test.mjs`；页面契约见 `templates/viz/README.md`。
  - 视频：`books/<slug>/films/<NNN>-<name>/`（`film.json`、`script.json`、`scenes.js`、`poster.jpg`）；规范见 `templates/film/README.md`。成片是构建产物（见下文“视频构建”），没有单独的 Release；`film.json` 中旧的 `release_tag`、`published_tag` 不再使用，`./tbook check` 给出警告。
  - 幻灯片：`books/<slug>/slides/<deck>/slides.md`（第一语言）与 `slides.<lang>.md`，逐页对应；不得有 `slides.<第一语言>.md`（会被 `slides.md` 遮蔽），也不得用 `src:` 导入别的文件的幻灯片（检查无法读取导入的内容），二者都报错；写法见 `theme/slides/README.md`。
- 媒体中引用的 Lean GID 与章节引用一样必须在锁文件中，由 `./tbook pin --refresh` 解析、`./tbook check` 复核：登记表的 `lean`、页面的 `data-lean-gid`、`film.json` 的 `lean`、幻灯片的 `<LeanBadge>` / `<TheoremCard>`（`<lean-badge>`、`<theorem-card>` 等 Vue 认可的写法同样受检查；代码块之外的每个标签都受检查。代码块指围栏代码块、缩进代码块与 `<<<` 导入，按 Slidev 53 配置下 markdown-exit 的块规则识别：表格、组件 HTML 块、脚注、`$$` 公式块与各容器的规则都在内。Python 的 `slides.code_lines` 与 Node 的 `codeLines` 是同一份移植，测试用 Slidev 构建出的解析器比对二者）。它们显示为绿色 `LEAN ✓`，因此必须是种类为 `theorem` 的声明：页面中的定义用 `data-trureturing-path="<module>.lean"` 链接；幻灯片写 `kind="definition"` 时可以引用 Lean 定义，显示中性的 `LEAN DEF` 而不是绿色 `LEAN ✓`。
- 可视化页面的绿色对勾 `.okmark` 只在 `.lean` 依据框里；页面里没有 `.lean` 祖先的 `.okmark`，以及脚本里写入 `.okmark`、却没有点名某个位于 `.lean` 框中的元素的那一行，`./tbook check`（`viz.okmarks_outside_lean`）与 `viz-validate`（`okmarksOutsideLean`）给警告；页面自己核对的数用中性的 `.nummark`。
- `[@id]` 只能指向编号环境，不能指向媒体块。

### 3.5 数学

`$…$` 行内、`$$…$$` 独行显示（与 trureturing 理论卷一致；不用 `\(` `\)`）。HTML 端由 KaTeX 在构建时渲染；PDF 端由 Pandoc 转为 Typst 数学；EPUB 端输出 MathML（Apple Books 原生支持）。

预设宏表只有一份：`tools/tbook/mathrender.py` 的 `TEX_MACROS`。KaTeX 通过 `tools/node/katex-render.mjs --macros <json>` 得到它；Pandoc 读取 `book.md` 开头的 `\newcommand` 定义（`latex_macros` 扩展），环境标题经 `tr-env.lua` 以元数据 `tr-tex-macros` 得到同一组定义。Pandoc 读取时关闭 `citations` 扩展（`[@id]` 已由 render 解析，正文里的 `@name` 是普通文字）。

## 4. 校验（`./tbook check`）

1. 配置：`site.toml`（含 `[books] hide`，§2.1；隐藏的书不检查，输出一行列出它们）、`book.toml` 字段，语言代码（不得重复），i18n 表存在；没有内置表（`theme/i18n/<lang>.toml`）的语言，`i18n/<lang>.toml` 的 `[meta]` 须设 `name`、`bcp47`、`short`，且 `bcp47`、`short` 不与其他语言重复。
2. 结构：SUMMARY 可解析、章节文件存在、未列入 SUMMARY 的 `.md`（警告）、fenced div 与 HTML 注释块闭合、无法解析的 div 开头行（报错）；行内 `<!--` 未在所在段落内闭合而后文另有 `-->`，围栏代码块随容器结束或从未闭合，mdBook 与 Pandoc 读法不同的定义，围栏代码块前未闭合、Pandoc 跨过围栏配对的 `$`（警告）；章节中链接或嵌入的本地文件（图片、`../assets/…`、引用式链接定义）不存在、或链接离开书目录，引用式定义的地址写在标签的下一行（警告）。
3. 环境规则（见 §3.1 表）。
4. 交叉引用 `[@id]`（正文与环境标题中）指向本版本存在的编号环境。
5. 多语言对齐：各版本章节文件与顺序相同；每章环境序列（种类、id、Lean 引用、证据状态、证明关联与来源字段）与媒体序列逐条相同；SUMMARY 结构（前言/编号/附录章节、嵌套、草稿条目）一致，使同一章在各语言中编号相同。
6. Lean：每个被引用的 GID 都在锁文件中；形式结论引用的必须是 `theorem`；在锁定提交上重新读取冻结状态片，名称、种类、模块、`statement_id` 与锁文件一致（防止锁文件过期或被手改）；所钉提交可从 `site.toml` 的 trureturing 分支到达（本地 checkout 用 `git merge-base --is-ancestor`，否则用 GitHub compare API；无法判定时 GitHub Actions 中为错误，本地或 `--offline` 下为警告）；锁文件的 `branch` 与该分支相同，且该分支是分支名而不是 SHA 或 `refs/…`（错误）；未被引用的锁条目（警告；`--book` 时也计入其他书的引用）。
7. 媒体：`tbook.viz/film/slides/figure.check(book)` 与 `check_ref(book, src)`。静态图：脚本不能运行、提交的 `figures/<name>.<lang>.svg` 与脚本现在画出的不一致或缺失（错误，`./tbook fig build`）；没有脚本的 `figures/*.svg`、没有任何章节引用的图（`check.check_unused_figures`）（警告）；`.figure` 块没有图注，或图注、图片说明（`![…](x.svg)`）只是编号（`figure.caption_problem`，错误）；`assets/` 下没有被任何语言的章节链接、文件名也不出现在本书幻灯片、视频、可视化源文件中的文件（`check.check_unused_assets`，警告）；各语言版本同一章的图片（`![…](…)`）张数不同（`check.check_image_parity`，警告；图片可以是各语言自己的文件，所以只比张数，`.figure` 块则逐条比对）；用图片语法引用、位于 `assets/`、写死颜色（有 `fill`/`stroke`/`stop-color`/`color` 的色值，却既没有 `ts-`/`tf-` 角色类也没有 `prefers-color-scheme`）的 SVG，以及被两种以上语言的章节共用、含 `<text>` 的 SVG（`check.check_drawn_images`，警告；位图不报）；图在手机上的最小标签：取提交的各语言 SVG 中最小的数值 `font-size`（上下标的 `72%` 随所在标签，不另计），乘以 `min(1, 358 / 宽度)`（`WRAP = True` 的分栏图取最宽一栏），低于 10 px（`figure.phone_problem`，默认警告，`[figures] phone_labels` 可升为错误；`./tbook fig build` 同样报出，`./tbook fig list` 列出该值）；两块 `.figure`/`.viz`/`.film`/`.slides` 在同一层只隔着空行或 HTML 注释相邻（`check.check_media_runs`，警告，每一对报在第二块，点名两块的种类、`src`、`preset` 与行号；完整实验室紧跟同一页面的卡时另给隔开的办法）。
8. 主题：`theme/generated/*` 与 `tokens.json` 同步（`./tbook theme --check`）；幻灯片的打印背景图 `theme/slides/styles/backdrop.jpg` 与 `backdrop.css`、`tokens.css` 同步（`./tbook theme --check` 与 `slides-check` 核对指纹）。
9. 缓存：`.cache/` 下的文件不得提交入库，`.cache` 本身（例如符号链接）也不得提交（错误；缓存只在本地可信；`git ls-files` 查询字面路径 `.cache`，不解析符号链接）。

冻结状态片的读取顺序：`$TRURETURING_DIR` 或 `../trureturing` 的 git checkout（`git show <commit>:<path>`）→ `.cache/trureturing/<commit>/` → `https://raw.githubusercontent.com/<repo>/<commit>/<path>`。

分支可达性依次查 `.cache/trureturing/<commit>/.tbook-on-branch-v2.json`（只存肯定结果）→ 本地 checkout（只认恰好同名的 ref）→ `api.github.com/repos/<repo>/branches/<branch>` 取分支头 `<head>`，再 `repos/<repo>/compare/<head>...<commit>`（`behind` 或 `identical` 才算在分支上；仓库可读而分支端点回答 404 即没有这个分支，为错误；令牌依次取 `$TRURETURING_TOKEN`、`$GITHUB_TOKEN`、`$GH_TOKEN`；详见 `docs/VERIFICATION.md` §1、§2）。CI 中没有 trureturing checkout，各工作流的检查步骤把 `github.token` 作为 `GITHUB_TOKEN` 传入。

PR 的运行不读缓存（`lean.cache_trusted()`）：`$GITHUB_EVENT_NAME` 为 `pull_request`、`pull_request_target`、`pull_request_review` 或 `pull_request_review_comment` 时，上面两个顺序都跳过 `.cache/trureturing`（下载的内容仍写入），因为同一 PR 先前的运行执行的是 PR 自己的代码，可能写入伪造的缓存。工作流也只在可信的 ref（默认分支、tag）上用 `actions/cache` 恢复和保存 `.cache/trureturing`（`docs/VERIFICATION.md` §2）。

**深度验证**（`./tbook lean-project` + `.github/workflows/lean-verify.yml`）：生成一个依赖所钉 trureturing 的 Lake 工程，导入被引用的模块，逐条检查声明存在、位于预期模块、种类正确，且公理闭包只含 `propext`、`Classical.choice`、`Quot.sound`（无 `sorryAx`）。需要完整 Lean 构建，耗时长，故定期与发版前运行，而不是每个 PR。

## 5. 构建目录契约

```
build/stage/<slug>/<lang>/mdbook/   mdBook 工程：book.toml、src/（章节、SUMMARY、404.md、_book/ 书内文件、
                                    tr/katex/fonts）、theme/head.hbs、tr/（tokens.css、纸面配色、KaTeX CSS、
                                    tr-editions.js、tr-book.css/js）
build/stage/<slug>/<lang>/pandoc/   Pandoc 输入：book.md、_book/、_theme/（Typst 主题副本与 code-<variant>.tmTheme）、
                                    meta.json、main.typ（PDF）、cover.png（EPUB 封面 1600×2560）、
                                    epub/（book.css、metadata.json、colophon.md）
build/html/<slug>/<lang>/           mdBook 输出（含 tr/ 下带哈希的 CSS/JS）
build/dist/<slug>/                  下载文件，文件名由 Book.artifact() 决定：
                                    <slug>-<version>-<lang>-screen.pdf
                                    <slug>-<version>-<lang>-print.pdf
                                    <slug>-<version>-<lang>.epub
build/slides/<slug>/<deck>/<lang>/  Slidev 输出；PDF 在 build/slides/<slug>/<deck>-<lang>.pdf；
                                    manifest.json（schema trureturing-books.slides.v1：base、
                                    decks.<deck>.langs.<lang>.{title,info,blurb,slides,dir,site_path,base,pdf,pdf_name}）；
                                    发布时 base、各语言的 site_path（随书的第一语言而变）或语言集合
                                    与当前不符即为过期，slides.publish 先重新构建
books/<slug>/films/<NNN>-<name>/out/  视频流水线的工作文件（git 忽略）；入口 theme/film/film.sh <film dir> <step>
build/films/<slug>/<id>/            一部视频的成片：film.json outputs 所列的文件，必有 narrated_720p 与 cover，
                                    列出时另有 narrated、music_only、music_only_720p（构建单元 films <slug>/<id>，
                                    渲染或从缓存恢复）
.cache/film/                        视频工具链：venv/（theme/film/requirements.txt）、models/（Kokoro）、fonts/
build/lean-verify/                  ./tbook lean-project 生成的深度验证 Lake 工程
_site/                              GitHub Pages 产物（见 §6）
.cache/artifacts/<target>/<unit>/<key>/  构建缓存的本地存储（git 忽略，见 §5.1）：entry.json 与 files/<i>/
```

HTML 专有选项：`book.toml` 的 `[html] section-labels = true` 恢复 mdBook 侧栏的 “1.2.” 编号（默认关闭，因为标题已写“第一章 / Chapter 1”）；`site.toml` 的 `[site] branch = "main"` 决定“建议修改”链接指向的分支；链接指向 `books/<slug>/<lang>/<章节>.md`（mdBook 写出的 `src/` 前缀在构建后去掉），生成的验证账本页没有该链接。语言切换按 `_site/<slug>/<lang>/` 的布局链接到 `../<lang>/<同一页>`。

环境变量：`MDBOOK`（mdBook 路径）、`PANDOC`、`PW_CHROMIUM_PATH`（已有的 Chromium）、`TBOOK_EPUBCHECK=1|warn|0`、`TBOOK_SLIDES_NO_PDF=1`（不导出、不发布幻灯片 PDF；`slides.publish` 会去掉章节卡片中指向未发布 PDF 的链接）、`TBOOK_SLIDES_NO_CHECK=1`、`SOURCE_DATE_EPOCH`（可复现的时间戳）、`TBOOK_REPO` / `TBOOK_BASE_URL`（覆盖仓库与站点地址）、`TRURETURING_DIR`（本地 trureturing 检出）、`TRURETURING_TOKEN`（读取私有 trureturing；GitHub API 也依次用 `GITHUB_TOKEN`、`GH_TOKEN`）、`TBOOK_LANG=zh|en`（模板升级摘要语言）。

视频构建：每部视频是一个构建单元（目标 `films`，单元 `<slug>/<id>`，`tbook.film.units`），由 `./tbook build films|site|all` 经 `film.build_videos` 运行。键覆盖视频依赖的全部输入，而不含无关输入：视频目录中 git 会提交的文件（不含 `out/`、`poster.jpg`、`README.md`）、`theme/film/`（不含视频页资源 `site/`，含 `requirements.txt`）、`theme/generated/tokens.mjs`、`tools/tbook/film.py`、引擎绘制的数据（`film.engine_data`：书的代号、版本与标题，所钉提交与引用声明的名称、陈述摘要，片内文字）、`package-lock.json` 中字体与 Playwright（它决定 Chromium）的版本、Kokoro 模型版本（`film.KOKORO_RELEASE`）与 Node 主版本，`film.json` 的 `scripts` 所列脚本，有实体镜头（`"solid": true`）时还有造型核心 `theme/viz/solid-core.js` 与 `theme/viz/vendor/` 的 three.js（没有实体镜头的视频不依赖它们）；不含站点地址，所以 CI、Pages 与 Release 的构建共用同一份视频。也不含探测到的 ffmpeg、Chromium 与视频 Python：没有视频工具链的构建（`TBOOK_FILMS=auto|skip`）须算出同一个键才能恢复视频，运行器上 ffmpeg 包的新修订也不改变视频的内容。缓存未命中时按 `TBOOK_FILMS` 处理：`auto`（默认）在工具链齐全（`film.toolchain_missing`：ffmpeg、Node 与 Playwright、Chromium、视频 Python 的包、Kokoro 模型、字体）时渲染，否则警告并删去该视频的旧构建目录；`require` 失败；`skip` 从不渲染。渲染即 `FILM_STRICT=1 theme/film/film.sh <dir> all <outputs 的键…>`（`film.render_videos` 明确传入 `film.json` 所列的输出），在 `out/` 中工作，只把这些文件复制到 `build/films/<slug>/<id>/`，缺少任何一个即失败（`buildcache.MissingOutput`，不存入缓存），不写入库文件（提交的 `poster.jpg` 只由手工的 `poster` 步骤生成）。`film.json` 在键中，改动 `outputs` 会重新渲染。流水线只编码所需（`film.render_plan`，`theme/film/plan.py` 给各步骤）：Chromium 按 1920×1080 截取每帧一次，各渲染进程在同一遍中编码——720p 视频（`narrated_720p`、`music_only_720p`）由帧直接缩放（hqdn3d、lanczos，x264 CRF 19、preset slow），只有列出 1080p 视频（`narrated`、`music_only`）时才另编码 1080p 母版（CRF 17）；`mux` 只做拼接与混入音频（AAC 48 kHz，`+faststart`），不再重新编码；纯配乐混音只在列出纯配乐视频时生成。同一台机器、同样的进程数，产物逐字节相同；720p 旁白版无论是否列出 1080p 都相同。默认（720p 旁白版与封面）渲染 50 秒的示例约 80 秒；另列出 1080p 视频时约 140 秒（帧截取不变，多编码 1080p 母版）。视频工具链由 `theme/film/setup.sh` 安装：钉死的包进 `$FILM_CACHE/venv`（默认 `.cache/film/venv`，`PYTHON` 可指定别的解释器），模型进 `$KOKORO_MODEL_DIR`（默认 `.cache/film/models`）；ffmpeg 来自系统（`FFMPEG` 可覆盖）。

### 5.1 构建缓存

耗时产物按**构建单元**缓存（`tools/tbook/buildcache.py`）：输入没有变化的单元不再构建，而是把存下的产物复制回构建写出的位置，路径相同，文件或目录的形状相同，站点组装与发布看不出区别。

| target | 单元名 | 产物 |
| --- | --- | --- |
| `html` | `<slug>/<lang>` | `build/html/<slug>/<lang>/` |
| `pdf` | `<slug>/<lang>/<variant>` | `build/dist/<slug>/` 下该语言版本、该变体的 PDF |
| `epub` | `<slug>/<lang>` | `build/dist/<slug>/` 下该语言版本的 EPUB |
| `slides` | `<slug>` | `build/slides/<slug>/`（全部 deck、语言与 PDF） |
| `films` | `<slug>/<film id>` | `build/films/<slug>/<film id>/`（单元由 `film.units(site, book)` 给出） |

**键**是单元全部输入（`Inputs`）的 SHA-256，再并入 target 与单元名。输入按“标签 + 摘要”逐项计入：

- 文件：仓库是 git 工作树时，取所列目录下 git 会提交的文件（已跟踪的，以及未跟踪且未被忽略的），构建产物与被忽略的文件不计入；git 整体忽略的目录（如 `.cache/fonts/`）与仓库外的目录逐个文件计入。仓库外的文件记为 `<outside>/<目录名>/<相对路径>`，键与目录所在位置无关。不是 git 工作树时遍历目录，跳过 `build/`、`_site/`、`.cache/`、`node_modules/`、`out/`、`frames/`、`tts/` 等。
- HTML、PDF、EPUB：`tools/tbook/`、`tools/filters/`、`tools/node/`、`theme/`（不含只供视频用的 `theme/film/`）、`i18n/`、`site.toml`、锁文件、`requirements.txt`、`package-lock.json`，整个书目录 `books/<slug>/`（各语言版本互相引用，改动任一语言都会重建这本书的全部单元），站点地址与仓库、Python 主次版本、Node 主版本。HTML 另计 mdBook 的精确版本；PDF 与 EPUB 另计 Pandoc 与 `typst` 模块的版本系列、`.cache/fonts/` 的字体文件、Typst 找到的字体族（含系统字体，所以构建 PDF/EPUB 的工作流都装同一套字体：`.github/actions/setup` 的 `fonts: 'true'` 包含 Playwright `--with-deps` 会装的字体）与 `$SOURCE_DATE_EPOCH`；EPUB 还计 epubcheck 是否真能运行（`$TBOOK_EPUBCHECK`，以及缺 Java 或 epubcheck 包时记为跳过），未经检查存下的 EPUB 不会恢复到要求检查的构建中。`.cache/fonts-fontsource/` 由构建从 `@fontsource` 包派生，不计入。
- 幻灯片：书的 `book.toml`、`slides/`、`assets/`，`theme/slides/`、`theme/generated/`、`theme/i18n/`、`i18n/`、`tools/node/`、`tools/tbook/slides.py`、锁文件、`site.toml`、`package-lock.json`，站点基路径与地址，`TBOOK_SLIDES_NO_PDF`、`TBOOK_SLIDES_NO_CHECK`，Node 主版本（Chromium 由 `package-lock.json` 中的 Playwright 决定）。

工具只按**版本系列**计入（`buildcache.series`：Node 取主版本，Pandoc 与 Typst 取“主.次”，如 Pandoc `3.1`；Chromium 由 `package-lock.json` 中的 Playwright 决定，不单独计入）。决定产物的版本已钉在键覆盖的文件中（`requirements.txt` 钉 Pandoc 与 Typst，`package-lock.json` 钉 Playwright、Slidev 与字体，`theme/film/requirements.txt`）；若这些工具计入精确版本，键就随运行器镜像而变，Node 的一个补丁版本或 Ubuntu 的 ffmpeg 修订就会让全部条目与已发布的 Release 失效。mdBook 例外：各处都装同一个精确版本（`.github/actions/setup` 钉 0.5.4），按精确版本计入，升级它即重建 HTML。

`buildcache.VERSION` 也计入每个键，改动它即全部重建一次。

**本地存储** `.cache/artifacts/<target>/<unit>/<key>/`：`entry.json`（schema `trureturing-books.build-cache.v1`：`target`、`unit`、`key`、`created`、`outputs[{path, kind}]`、`files{相对路径: {sha256, size}}`、`dirs[]`、`inputs[[标签, 摘要]]`）与 `files/<i>/`（第 i 个产物）。条目先写在同一目录的 `.tmp-*` 中，写完再改名，构建中断不会留下半个条目；两个进程同时存同一个键时保留先写成的。恢复也是先复制到产物旁的临时名再改名。每个单元保留最近存入或恢复的 2 个条目。

**查找顺序**（`buildcache.run(unit, build)`）：

1. 本地存储：逐个文件核对 `entry.json` 记下的摘要、目录与产物形状（没有多余文件，没有符号链接），记下的产物路径须与当前一致；不符即删除该条目并构建。
2. `TBOOK_CACHE_REMOTE=1` 时，查仓库（`site.toml` 的 `repo`、`TBOOK_REPO` 或 `GITHUB_REPOSITORY`）最新 5 个附有 `build-cache.json` 的已发布 Release（草稿与没有该文件的 Release，例如手工发的，不算在内；只看最新的 100 个 Release）中的 `build-cache.json`，从新到旧取第一个有该键的条目：设置了 `GITHUB_TOKEN` 或 `GH_TOKEN` 时经 API 的资产地址下载（私有仓库也可用；跳转到存储地址时不带令牌），否则用公开下载地址；核对大小不超过声明值、SHA-256 与 `build-cache.json` 和 GitHub 报告的 `digest` 一致；只解出 `entry.json` 与 `files/` 下的普通文件和目录，链接、设备文件、`..`、绝对路径、重复成员一律拒绝（逐个写出，不依赖 Python 3.11.4 才有的解包过滤器）；再按第 1 步校验后放入本地存储并恢复。API 地址取 `$GITHUB_API_URL`（默认 `https://api.github.com`）。
3. 都没有：构建，成功后存入；构建失败则什么也不存，构建声明的产物缺失是错误。

缓存不会让本来能成功的构建失败：Release 不可达、限流、条目损坏、磁盘写满都只打印一行原因，然后照常构建（或只是不存）。每个进程只列一次 Release。

**环境变量**：`TBOOK_CACHE=0` 关闭缓存（每个单元都构建，既不恢复也不存）；`TBOOK_CACHE_REMOTE=1` 允许从 Release 恢复，未设置时不访问网络。

**命令**：

```
./tbook cache status [--book <slug>]       每个单元、当前键的前 16 位、本地是否已存
./tbook cache key                          本地存储内容的摘要 build-cache-v1-<sha256>（条目不变，摘要不变）；
                                           Actions 缓存以它加 -r<运行号>-<尝试次数> 为键保存（见 docs/PUBLISHING.md §5）
./tbook cache prune                        只留各单元当前键的条目；删除损坏条目、中断留下的临时目录与空目录
./tbook cache export DIR [--book <slug>]   把各单元当前键的条目写成 DIR/cache-<target>-<unit>-<键前 16 位>.tar
                                           与 DIR/build-cache.json（unit、key、asset、sha256、size）；
                                           有单元不在本地存储中时列出它们，退出码为 1
```

导出的 tar 可复现：成员排序，不含属主与时间，权限只有 0644/0755。工作流如何保存、恢复本地存储，整站 Release 如何附带这些文件，见 `docs/PUBLISHING.md`。

**接口**（`film.units` 等用它描述新单元）：

```python
Inputs().files(*paths, exclude=()).text(label, value).add(other)   # .key()；text 的值按 JSON 计入
Unit(target, name, inputs, outputs: list[Path])                     # .key、.label、.entry_dir()
run(unit, build_fn, *, repo=None) -> "cached" | "release" | "built"
run(unit, None) -> "cached" | "release" | "missing"                 # 只恢复，不构建
units(site, books) -> list[Unit]       # html/pdf/epub/slides 单元，加上 film.units(site, book)
tool_version(*cmd), package_version(name), series(version, parts=2), node_version()
store(unit), restore_local(unit), restore_remote(unit, repo), stored(), prune(units), actions_key(), export(dir, units)
```

## 6. 站点结构（`_site/`）

```
index.html                 书库首页（双语切换，书卡片：封面、简介、在线阅读、下载、媒体计数）
404.html                   自包含的 404 页
.nojekyll
assets/                    站点共享样式、tokens.css、site.js、favicon；katex/（KaTeX 样式与 WOFF2 字体，定理标题含公式时才有）
manifest.json              机器可读清单（schema trureturing-books.site.v1，见下）
<slug>/index.html          书的落地页：版本、语言、下载、目录、验证摘要、可视化/视频/幻灯片
<slug>/cover-<lang>.png    站点封面（640×1024，tbook.cover 生成）
<slug>/<lang>/             mdBook HTML
<slug>/downloads/          PDF、EPUB
<slug>/viz/                index.html（可视化索引）、visualizations.json、assets/（共享运行时）、<id>/
<slug>/films/              index.html、films.json、assets/{tokens.css,films.css,films.js}、<NNN>-<name>/poster.jpg
                           与 <NNN>-<name>/<outputs 所列的文件>（构建有该视频时；同源托管，iOS Safari 需要正确的
                           Content-Type 与按字节范围请求；没有时视频页、落地页与章节只显示海报与“视频未构建”）
<slug>/slides/             index.html；<deck>/（第一语言）、<deck>/<lang>/（其他语言）、
                           <deck>/<slug>-<deck>-<lang>.pdf
```

`manifest.json` 字段：`generated_at`、`site{title,languages,base_url,repo}`、`template{name,version}`、`trureturing{repo,commit,branch}`、`formalization_requests`（按 issue 汇总 DOI、定位、书籍/结果及去重计数）、`books[{slug, version, code, title{lang}, editions[{lang,bcp47,primary,html}], landing, verified, open, declarations[], media{viz,films,slides}, files[{path,size,sha256,kind(pdf|epub|cover|slides-pdf),lang,variant}]}]`。设置 `SOURCE_DATE_EPOCH` 可使 `generated_at` 可复现。

站点品牌：`site.toml` 可选 `[site] logo = "TRURETURING//BOOKS"`；缺省时用英文站名生成 `FIRST//REST`。

所有站内链接都是相对链接（站点挂在 `/<repo>/` 下）。`./tbook serve` 在同样的子路径下预览（`TBOOK_SERVE_HOST=0.0.0.0` 可供局域网访问）；`./tbook build site --book x` 只装配选定的书；`./tbook build viz|films [--book x]` 只重新发布（选定书的）这些部分，书库首页与 `manifest.json` 仍列出 `_site/` 中已有的全部书；被 `[books] hide` 隐藏的书的 `_site/<slug>/` 在每次站点构建时删除（完整构建本来就先清空 `_site/`），其他内容不动。媒体发布失败时，站点其余部分仍会写出，命令以非零退出。

mdBook 的 `<lang>/print.html` 不改写 iframe 的 `src` 与 video 的 `poster`；媒体块把相对本书的目标写在 `data-tr-src` / `data-tr-poster`，`site.publish_html` 据此修正。界面语言记在 localStorage 的 `tr-lang`，书库首页、落地页、可视化、视频页与幻灯片共用。

## 7. Python 组件接口

核心（不依赖外部工具）：

| 模块 | 职责 |
| --- | --- |
| `config` | `load_site()`、`load_book()`、`load_books()`、`book_slugs()`（可见的书，站点顺序）、`hidden_books()`、`named_book(slug)`（命令点名的书；隐藏的书报错）、`Site.hidden_by(slug)`、`i18n()`、`s(lang, key)`、`i18n_problems(langs)`、`Book.artifact()` |
| `summary` | 解析 SUMMARY，章节编号前缀 |
| `mdscan` | 块结构（`scan_blocks`：任何容器中的围栏代码、缩进代码与注释块，跨行的行内注释与公式，mdBook 与 Pandoc 读法不同处的警告 `notes`；`fenced_code_lines`、`indented_code_lines`、`map_closed`）、fenced div、属性、行内代码、`[@id]`、链接与引用式定义（`LINK_RE`、`REFDEF_RE`，容器前缀 `CONTAINER`；定义只能开始于哪些行：`definition_roles`、`text_roles`，逐行连同角色：`iter_text`）、`lean:` 链接（`lean_link_gids`；逐行读不到的 `stray_lean_links`，其 `<lean:…>` 地址由 `hide_lean_destinations` 对逐行读取隐藏）、标题的纯文字（`unescape_markdown`） |
| `model` | `load_edition()` → `EditionModel`（章节、环境、编号、引用；`title_text()` 给出标题的纯文字，`title_markdown()` 保留 Markdown，二者都把 `[@id]` 换成引用文字）；`Issue` |
| `lean` | 名称键解码、GID、冻结状态来源、`resolve()`、`Lock` 与永久链接 |
| `render` | `RenderContext`、`env_view()`、`chapter_markdown()`（mdbook / pandoc 两种 target）；环境标题中的 `[@id]`（`env_title()`）；`rewrite_links()`（图片与文件链接，`check` 也用它找缺失文件）；Lean 声明未被锁文件解析时显示 `UNVERIFIED`、不给链接；`verified_envs()` 是所有 `LEAN ✓ n` 计数的唯一口径 |
| `ledger` | 生成“形式化验证账本”章节 |
| `figkit` | 静态图的画图库：`Figure`（`Canvas` 的方法：线、箭头、面、文字、标记，`axes()` 坐标系，`sphere()` 球面正交投影，`row()`/`panel()` 分栏），角色与语义名（`ROLES`、`ALIASES`），标准的下限（`MIN_FONT`、`MIN_STROKE`、`MAX_WIDTH`） |
| `figure` | 静态图：`names()`、`render()`、`build(book, only, check=)`、`style_sheet()`、`materialize()`、`inline_html()`、`mdbook_css()`、`caption_problem()`、`shots()`，以及媒体接口 |
| `check` / `pin` / `theme` / `newbook` / `build` / `cli` | 命令 |

组件（各自实现，签名固定）：

```python
# tbook/html.py
def build_edition(site, book, edition, model, lock, out_dir: Path) -> Path
# tbook/pandoc.py
def build_pdf(site, book, edition, model, lock, variant: str, out_path: Path, *, stage_dir=None) -> Path  # screen | print | academic
def build_epub(site, book, edition, model, lock, out_path: Path, *, stage_dir=None) -> Path
# tbook/cover.py
def render_cover(site, book, edition, out_path: Path, *, fmt: str = "png", variant: str = "screen",
                 model=None, lock=None, meta=None, width_px: int = 1600) -> Path
# tbook/viz.py, tbook/film.py, tbook/slides.py, tbook/figure.py（figure 只有 check_ref、check、items、cited_gids、render_embed、cli）
def check_ref(book, src: str) -> str | None          # 错误信息或 None
def check(book) -> list[Issue]
def items(book) -> list[dict]                         # 落地页用的条目
def cited_gids(book) -> list[tuple[Path, int, str]]   # 媒体引用的 GID；pin --refresh 与锁文件校验都计入
def render_embed(env, ctx, inner: str, doc) -> str    # 替换媒体块；ctx.target 为 "mdbook" 或 "pandoc"
def build(site, book, out_dir: Path)                  # viz/film：发布到 _site/<slug>/<viz|films>/（film 先渲染
                                                      # 或恢复视频）；slides：构建到 build/slides/<slug>/（发布用 publish）
def units(site, book) -> list[buildcache.Unit]        # 仅 film：每部视频一个构建单元
def publish(site, book, site_dir: Path, *, build_missing=True) -> list[dict]   # 仅 slides
def cli(args) -> int                                  # ./tbook viz|slides|film new|list …
# tbook/site.py
def build(site, books, out_dir: Path, only: set[str] | None = None, *, build_root: Path | None = None) -> Path
# tbook/template.py
def main(args) -> int                                 # status | update | manifest
# tbook/serve.py, tbook/doctor.py, tbook/leanverify.py
def serve(port: int, directory: str) -> int
def run() -> int
def generate(out_dir) -> Path
```

媒体块的输出：mdbook 目标以块级 `<figure class="tr-media tr-viz|tr-film|tr-figure">`（slides 为链接卡片 `.tr-slides`）开头；pandoc 目标输出 Markdown，包在 `::: {.tr-media .tr-viz|.tr-film|.tr-slides|.tr-figure}` 中得到 PDF/EPUB 的媒体面板，图片路径指向 `_book/…` 并加入 `ctx.book_files`（静态图为该输出生成的文件写入 `ctx.book_texts`）。

`render.pandoc_env()` 输出的富属性 fenced div（Lua 过滤器 `tools/filters/tr-env.lua` 按输出格式渲染）：

```
:::::: {#thm-x .tr-env .theorem tr-kind="theorem" tr-status="lean" tr-label="定理" tr-number="1.2"
        tr-ref="定理1.2" tr-title="…" tr-badge="LEAN ✓" tr-badge-title="…" tr-badge-url="URL"
        tr-lean="GID …" tr-lean-name="Lean 名 …" tr-lean-url="URL …"}
内容
::::::
```

`tr-badge-title` 是徽章的提示文字（与 mdBook 相同）；`tr-badge-url` 只在徽章是链接时出现（`LEAN ✓`，指向第一条声明）；锁文件不能确认的形式结论另带 `tr-unverified="1"`，其 `UNVERIFIED` 徽章在 EPUB 与 PDF（Typst `tr-env` 的 `badge-url: ""`）中都不是链接，`tr-lean-url` 仍给出锁文件解析了的声明的地址。

`render.mdbook_env()` 输出的 HTML（样式在 `theme/mdbook/`）：

```html
<section class="tr-env tr-theorem tr-status-lean" id="thm-x" data-kind="theorem">
<header class="tr-env-head"><span class="tr-env-label">定理1.2</span><span class="tr-env-title">（…）</span><a class="tr-badge tr-badge-lean" href="…">LEAN ✓</a></header>

内容

<footer class="tr-env-lean"><a class="tr-lean-decl" href="…"><code>D5.S1.Deficit.deficit_three_valued</code></a></footer>
</section>
```

## 8. 工具链版本

| 工具 | 版本 | 来源 |
| --- | --- | --- |
| Python | ≥ 3.11 | 系统 / `actions/setup-python` |
| Pandoc | 3.9（`pypandoc_binary==1.17`） | `requirements.txt` |
| Typst | `typst==0.15.2`（Python 模块） | `requirements.txt` |
| epubcheck | 5.3.0（Python 包内含 jar，需 Java） | `requirements.txt` |
| mdBook | 0.5.4 | CI 用 `taiki-e/install-action`；本地 `cargo install mdbook --version 0.5.4 --locked` |
| Node | ≥ 22.12 | `package.json` |
| KaTeX | 0.18.10 | `package.json` |
| Slidev | 53.0.0 | `package.json` |
| Playwright | `playwright-chromium@1.56.1` | `package.json`；本地可用 `PW_CHROMIUM_PATH` 指向已有 Chromium |

字体：网页用 Google Fonts（Chakra Petch、JetBrains Mono、Noto Sans SC，以及英文等非中日韩文字用的 Source Sans 3：令牌 `font.body-latin`。Noto Sans SC 把弯引号与撇号画成全角，中文需要这样，英文里却与词隔开，所以 mdBook、站点、视频页与可视化在语言不是中日韩时把 `--tr-font-body` 换成它；PDF 的英文正文本来用拉丁字体，EPUB 正文用阅读器的字体）；PDF 用系统字体加 `tools/fetch-fonts.sh` 拉取的 TTF（`.cache/fonts/`）；幻灯片与视频用 `@fontsource` 自托管。

## 9. 学术演示稿（Beamer）

`tools/tbook/academic.py` 在现有 `slides` 组件中实现学术演示稿。演示目录中的 `deck.toml` 选择这条构建路径；Node 端发现 Slidev 演示时跳过带此配置的目录，Python 端检查两种格式，无效配置会报错。学术演示稿可以选择书中语言版本的非空子集，并独立指定顺序：`slides.tex` 属于第一个所选语言，其他语言使用 `slides.<lang>.tex`。可选的 `theme_dir` 与机构图片路径相对于演示目录解析；本地接入也支持自有主题的绝对路径。现有托管目录 `theme/`、`templates/`、`tools/`、`skills/`、`docs/` 与 `.github/` 已覆盖新增模板文件；`books/` 仍归下游所有。

TeX 词法分析器读取字面量命令，处理成对嵌套的必选、可选与逐步显示参数并保留源码行号，跳过注释与原样文本，拒绝未受检查的源码导入和动态计算的结果或媒体 id。`bookresult` 通过 `model.load_edition()` 与 `lean.Lock` 解析书中 id，沿用形式结论、定义和开放问题的验证规则。源码中的引用进入 `slides.cited_gids()`，继而接受现有的钉版、分支与冻结状态检查。生成的 `tbook-lean.sty` 包含书中标题和编号、纸面语义色、固定到所钉提交的链接、`PinnedCommit` 与去重账本；它不绑定具体版式，也可用于演示稿自有主题。静态检查不验证报告人撰写的陈述，也不展开任意 TeX 宏。

纸面可视化静态图位于 `viz/<id>/fig-<card>.<lang>.paper.png`；`slides snapshots` 复用现有服务器、停帧、实验卡、字体与浏览器接口，在绘制前应用纸面配色。未知可视化或实验卡、缺失静态图都会使检查失败。`BookFigure` 先比较规范 SVG 与绘图脚本的输出，再通过 `figure.materialize(...,"paper",ground=True)` 和固定版本的 Typst 生成 PDF 图件，继续以现有绘图脚本为唯一图源。

构建暂存目录为 `build/stage/<slug>/beamer/<deck>/<lang>/`。Tectonic 0.16.9 使用固定名称的听众版与备注版入口、固定的 v33 资源包、`SOURCE_DATE_EPOCH` 与确定性模式编译，不启用 shell escape。输出为 `build/slides/<slug>/<deck>-<lang>.pdf` 与 `…-notes.pdf`。现有的逐书幻灯片缓存涵盖学术稿源码、书模型、静态图、图件、令牌、代码、引擎、资源包、时间基准及外部主题和图片内容。构建清单为这些演示稿记录 `kind="academic"` 和 `notes_pdf`；站点复制两种 PDF 及各语言入口页，`manifest.json` 增加 `slides-notes-pdf` 条目，书籍 Release 也收集备注版 PDF。两种 PDF 来自同一份源码，正文总帧数不计附录。账本每帧最多列出十二条不同的引用结果，解析器按相同规则计数。配置还可声明机构、合作者和日期；两种主题都默认隐藏导航按钮，按需启用。纸面静态图按 4 倍像素比截取（3200 × 1800）；共享画布运行时允许这种带标签的印刷静态图使用 4 倍像素比，交互模式仍上限为 2 倍。
