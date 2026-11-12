# Changelog

本文件记录 trureturing-books-template 的版本变化，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。下游升级时请阅读跨越的所有版本，处理标为“需要手动操作”的条目。

## [Unreleased]

## [0.6.0] - 2026-11-12

### 新增

- 可选学术专著 PDF `academic`：独立的 B5 学术专著版式、衬线正文、分开的标题/版权/内容提要/目录、对开页眉、传统定理与证明、三线表及无框图注，保留 Lean 徽记、永久链接、公式适宽与验证账本；图件与代码高亮复用浅色配色。在 `[outputs] pdf` 中加 `"academic"` 后用 `./tbook build pdf --variant academic` 导出，站点与 Release 自动收录；已有书省略配置或 `pdf = true` 仍默认原两版。来源：下游《量子计算的几何直觉》学术专著导出。

- 画图库补上下游用到却没有的形状，均为新增接口，已有的图逐字节不变：流程图的 `fig.box(…)`（自动定宽与换行、虚线框、强调色框与 `chip`/`chip_size`，返回锚点；默认字号按不宽于 358 的一栏设计）与 `fig.link(a, b, elbow=…)`；球上的 `sp.turn(轴, 起点, 角度, arrow=True)`、`sp.small_circle(…, start=, span=, arrow=True)`、`sp.sector(…)`、`sp.patch(…)`、`sp.polytope(…)`；`fig.axes(…, logx=True, logy=True)`（自动十的幂刻度与细刻度、`ax.decades()`）；`ax.step(…)`、`ax.bars(…)`；`figkit.hull(…)`、`figkit.hull3(…)`；`fig.bounce(a, 镜面点, b)`；文字标记 `***粗斜体***` 与 `\bar{z}`；脚本可选 `MARKUP = 2`，让下标、上标里的标记嵌套、斜体 `I` 用衬线字形（不写时按旧规则）；等宽文字按每字 0.6 em 估宽（组合附加符不计），`fig.measure()`、`fig.wrap_text()`。示例专著第四章新增三张图（证明骨架、黄金旋转、回归得分的对数图）。来源：下游《量子计算的几何直觉》150 张图中各章各写一遍的辅助代码（#35）。
- `viz-validate` 与 `./tbook check` 对 `viz/tests/*.test.mjs` 里的每一处 `waitForTimeout(…)` 报警告（行号与改法：过渡用 `settle(page)`，播放用 `until(page, …)`）。
- `node tools/node/viz-test.mjs --slow`：等价于 `VIZ_SLOW_FRAMES=1000`，以一秒一帧跑浏览器测试。`ci.yml` 新增 `viz-slow` 作业（8 片，同 `viz`），只在手动运行（输入 `slow_frames`，默认勾选）与每周三定时运行中出现，定时运行只跑它；PR 与推送的 CI 不变。何时跑见 `docs/PUBLISHING.md` §4。**需要手动操作（仅当分支保护列出所有检查时）**：新检查 “Visualization browser tests, slow frames (i/8)” 不在 PR 上运行，不要把它设为必需检查。

### 变更

- `./tbook check` 拦住不按标准做的图（均为警告）：章节用图片语法引用、放在 `assets/`、写死颜色（没有角色类、也没有 `prefers-color-scheme`）的 SVG，提示改用 `::: {.figure}` 与 `figures/<name>.py`（照片与位图不报）；两种语言的章节共用一个带 `<text>` 的 SVG，提示每种语言一版标签；三块以上 `.figure`、`.viz`、`.film`、`.slides` 只隔着空行连排，从第三块起报位置。
- 图在手机上的最小标签：`./tbook fig build` 与 `./tbook check` 按 `min(1, 358 / 宽度)`（`WRAP = True` 的分栏图按最宽一栏）算出手机上的最小字号，低于 10 px 时给出警告（图名、当前值与做窄、分栏、加大字号三种改法）；`site.toml` 的 `[figures]` `phone_labels = "error"` 可升为错误；`./tbook fig list` 增加一列“手机上的最小标签”。起始脚本 `templates/figure/figure.py` 与示例专著的 `carry-rules` 已调到不低于 10 px。`skills/book-figure`、`skills/book-viz` 与 `docs/AUTHORING.md` 写明手机上的字号下限、图片语法只用于照片一类、媒体块不连排。来源：《量子计算的几何直觉》有 9 张手绘图、73 张手机上标签不到 10 px 的图与 8 处媒体连排，`check` 均未报出（#34）。

### 修复

- 可视化注册表单元测试采用独立的测试套件样本，避免下游保留旧版示例书时，示例中的固定等待让模板升级后的工具测试失败；实际书籍的浏览器测试与检查继续覆盖原始套件。
- 可视化：用指针点过实验卡、场景按钮（`kit.chips`）或导览条之后，空格键直接播放或暂停时钟，不再把那张卡重新按一遍（回到起点重播）。`theme/viz/kit.js` 在指针点击（`detail > 0`）后把焦点交给舞台（`.stage` 加 `tabindex="-1"`，按键时不画焦点框）；用 Tab 走到按钮上的读者，空格与回车仍由按钮响应。`stageFirstChecks` 新增 `keyboard: after a card is clicked, Space plays and pauses the clock`（没有 `footer.rail #play`、或没有一张卡能启用它的页面跳过；页面另有空格用法时传 `{ keys: false }`；也单独导出为 `spaceAfterCard(T, page)`），示例 `golden-carry` 补浏览器回归测试，单元测试在起始模板的副本上核对通过、失败（点击后焦点仍留在卡上）与跳过三种情形。来源：下游《量子计算的几何直觉》核查（trureturing-books#147），#36。

## [0.5.2] - 2026-11-12

### 修复

- CI 的 PR 构建可以复用默认分支成功 Pages 运行的缓存工件，无须等待 Release。通过 API 核对来源运行的 workflow、仓库、分支、事件和成功状态，按 run ID / artifact ID 下载；不读 PR 的 Actions 缓存或工件，缺权限或工件过期时退回构建。Pages 工件保留 7 天，调用 CI 的工作流增加 `actions: read`。来源：下游《量子计算的几何直觉》一次 PR 的八部视频串行重建耗时 30 分 40 秒，整轮 CI 约 36 分钟。
- 开发分支只由 PR 触发完整 CI，消除同一提交的 push / PR 重复运行；无 PR 时可手动触发。main 的旧 CI 允许被新提交取消，Pages 保持串行。
- 视频独立分 4 片严格构建，书籍 HTML、屏幕 PDF、印刷 PDF、EPUB 分格式并行，可视化浏览器测试从 4 片增为 8 片。空书库、隐藏示例书、空分片保持可用，分片复用正常构建缓存键。**需要手动操作（若分支保护要求旧检查名）**：将旧的书籍构建、四片可视化和 “Slides and films” 检查更新为 “Build books (html/pdf-screen/pdf-print/epub)”、八个 “Visualization browser tests (i/8)”、“Slides” 与四个 “Films (i/4)”；CI 下载工件名改为按格式区分（见 `docs/PUBLISHING.md` §3）。

## [0.5.1] - 2026-11-12

### 修复

- 可视化完整实验室在手机宽度的书内嵌入中保留可操作的时间轴与全部播放控件，避免传输栏把滑块挤成零宽；共享浏览器质量门补查窄嵌入、正文横向溢出及时间轴的指针与键盘操作。来源：《量子计算的几何直觉》第 14–15 章的四个完整实验室。
- 修正新增的时间轴质量门：终点比较容许原生滑块的数字序列化舍入；开场空线路禁用时间轴时，先检查版式，再通过实验卡启用并验证拖动、键盘与读数。补充正常及故障状态的浏览器回归测试。

### 变更

- `./tbook check` 新增一种“mdBook 与 Pandoc 读法不同”的警告：顶层段落的下一行直接开始列表（`- 甲` 或 `1. 一`）。HTML 版（mdBook）把它显示为列表，PDF/EPUB（Pandoc）却把各项并进上一段，成了“…… - 甲 ……”；在列表前空一行即可。列表项里紧跟的子列表、跨行公式里以 `-` 开头的行不报。来源：《量子计算的几何直觉》有 20 处这样的列表在 PDF 里并进了段落（#30）。

## [0.5.0] - 2026-11-12

### 新增


- 当前 trureturing pin 以锁文件为唯一来源：正文复用 `lean:` 解析器的 `{source}` / `{statement_id}` 标签和 `[{commit}](trureturing:)`，幻灯片增加复用 `pinned` 的 `<PinnedCommit />`，可视化构建与本地预览提供生成的 `assets/trureturing.json`。视频新增 `publication_basis: "pinned"`；可选的 `subject_commit` 保留真实制作历史。旧格式继续受支持。
- 幂等迁移只移除已明确标记为锁引用的 HTML 锚点的版本回退链接。正文审计表、动态地图与历史记录的选择性迁移见 `docs/UPGRADING.md`，不会自动抹去历史。来源：下游更新 pin 时，当前版本曾复制到正文、八部视频、幻灯片与声明地图，造成同步冲突和行号/摘要漂移。

### 变更

- 静态图：演示文稿里的图副本由 `./tbook fig build` 维护。`books/<slug>/slides/<deck>/img/<name>.<lang>.svg` 若与某张图同名，就写成它的深色配色版（`figure.materialize(svg, "screen")`），图重画后跟着更新；`./tbook check` 发现副本过期、或是原样拷贝的规范 SVG 时报错。演示文稿是纯深色的，而 `<img>` 里的 SVG 跟随浏览者的系统配色；原样拷贝的规范 SVG 在浅色系统和无头导出里会用纸面配色画在深色背景上（浅灰色底带、看不清的标签）。来源：《量子计算的几何直觉》的总览演示文稿里，3 张图是原样拷贝，1 张在锁文件更新后停在旧的数字上（#28）。**需要手动操作（仅当演示文稿手工拷贝过图）**：运行 `./tbook fig build --book <slug>` 并提交。

- CI 的可视化浏览器测试从 `media` 作业移到新的 `viz` 作业，分 4 片并行运行（`tools/node/viz-test.mjs --shard i/4` 早已支持分片，工作流此前没有用）。下游《量子计算的几何直觉》的页面由 8 个增到 36 个之后，串行跑一轮要四五十分钟，默认分支上后续的运行都排在它后面被取代。`media` 作业改名为 “Slides and films”，只构建幻灯片与视频。**需要手动操作（仅当分支保护按名字要求了旧的检查）**：把必需检查 “Visualizations, slides and films” 换成 “Slides and films” 与四个 “Visualization browser tests (i/4)”。
- 静态图：`WRAP = True` 的图多次调用 `fig.row(…, y=…)` 把各栏排成几行时，网页版每行各成一个弹性盒（外层 `tr-fig-rows`）：宽屏上行还是行、同一行的各栏一起缩放，手机上逐栏叠放。此前所有栏都在同一个弹性盒里，宽屏上被压成一行。来源：《量子计算的几何直觉》里要并排比较的小图集超过三张时，一行放不下。

### 修复

- 本地可视化预览在缺少 `trureturing.lock.json` 时，对 `assets/trureturing.json` 返回 404，避免声明地图把成功响应的 `null` 当作锁数据；锁文件出现后，同一服务即可正常提供数据。

## [0.4.0] - 2026-11-12

### 新增


- 完整出版工具链容器：在固定版本与摘要的官方 Playwright 镜像上预装 Python、Node、mdBook、Pandoc、Typst、EPUB 校验器、中英文字体及视频与语音工具。上游 `Toolchain image` 工作流实际验证断网 PDF/EPUB/语音/浏览器及完整示例构建后发布 GHCR 镜像；组合动作自动核对依赖指纹并复用预装环境，采用容器的作业不再逐次运行 apt。容器为可选接入，默认 CI 与 Pages 继续使用现有的 Ubuntu 工具安装与缓存流程。使用与升级方式见 `docs/CONTAINERS.md`。来源：trureturing-books 的 CI 与 Pages 在 Ubuntu 软件源 DNS 解析失败时连续无法安装字体和浏览器依赖。

- 静态图的标准、工具与检查（`skills/book-figure`）。此前模板对静态图只有 `![图注](../assets/x.svg)` 一种写法，没有标准、工具与检查；下游《量子计算的几何直觉》的 29 张图因此全部把深色底写死在文件里、两种语言共用一个文件、四章的图注只有“图 13”这样的编号。现在：
  - **脚本生成**：一张图是一个脚本 `books/<slug>/figures/<name>.py`，用画图库 `tools/tbook/figkit.py` 画（线、箭头、面、文字、坐标系、球面投影、分栏）。脚本只写颜色的角色名（`ink`、`cyan`、`lean`、`now`…），不写色值；每种语言生成一份 `figures/<name>.<语言>.svg` 并提交入库，输出逐字节可复现。画图库拒绝不合标准的图：字号小于 12、线宽小于 1、文字超出画布、未知角色、宽度超过 760。
  - **引用**：`::: {.figure src="<name>"}` 加图注（普通 Markdown，可含数学与 `[@id]`），与可视化、视频一样是媒体块，各语言版本的图序列由 `./tbook check` 逐条核对。
  - **各端渲染**：HTML 中图内联进页面，角色类取页面的 `--tr-*` 令牌，随主题切换与浏览器打印变化；带分栏的图（`WRAP = True`）在宽屏并排、在手机上叠放。PDF 的屏幕版与印刷版各用自己的配色（`theme/typst/book.typ` 的 `tr-fig-ext` 按变体取文件），EPUB 用浅色配色加不透明底。
  - **命令**：`./tbook fig new <book> <name>`（起始脚本 `templates/figure/figure.py`）、`./tbook fig build [--book <slug>] [--check] [<name> …]`、`./tbook fig list`、`./tbook fig shots <book> [<name> …]`（深色、浅色、手机、印刷四种画面与拼版图，`tools/node/fig-shots.mjs`）。`./tbook build html|pdf|epub` 先重画图，再构建。
  - **检查**（`./tbook check`）：`.figure` 块没有图注、或图注与图片说明只是编号（“图 13”“Figure 2.1”），报错；提交的 SVG 与脚本现在画出的不一致，报错；`assets/` 里没有任何章节、幻灯片、视频或可视化用到的文件，没有脚本的 `figures/*.svg`，以及没有任何章节引用的图，警告；各语言版本同一章的图片（`![…](…)`）张数不同，警告（`.figure` 块与其他媒体一样逐条比对）。
  - 示例专著的两张图（`phase-square`、`carry-rules`）改由脚本生成，作为示例；`books/example-monograph/assets/` 中的两个旧 SVG 删除。
  - **需要手动操作（仅当书里有只写编号的图注时）**：`![图 13](…)` 这样的图片说明现在是错误，请改成一句说明这张图的话。原有的 `![图注](../assets/x.svg)` 写法照常构建，不需要改；要让旧图随主题变化，按 `skills/book-figure` 的“把旧图换成标准图”重做。

### 修复

- 静态图 SVG 的坐标与圆弧分段数在舍入前消除浮点计算的微小误差，避免 macOS 与 Ubuntu 将同一脚本绘成不同字节、使 `./tbook check` 误报图片过期。补充跨舍入边界的回归测试；升级后运行 `./tbook fig build` 并提交更新的 SVG。
- `tools/fetch-fonts.sh` 的 Noto CJK tag 改为实际存在的 `Sans2.004` 与 `Serif2.003`（旧值多了 `R`，四个下载地址均返回 404），并补齐四个字体文件的 SHA-256。容器构建要求这些字体全部下载并通过校验。

## [0.3.2] - 2026-11-11

### 修复

- PDF 数学排版（`tools/filters/typst-compat.lua`，承接 0.3.1）：合并前的独立审查（三个视角各自构造反例，每条由另一方复现）确认了 14 类问题，其中 3 类会让 PDF 编译失败；它们都不出现在据以实测的那本书里，现已全部修复并各有回归用例。
  - 括号不配对或缺参数的 TeX（`\frac{a}{b`、`\frac1\sqrt{2}`）不再被“修”成能转换的东西：公式原样交给 Pandoc，像以前一样印出源码。
  - `\boxed{…}`、`\phantom{…}` 内部的公式被改写却没有还原（印出标记字符，或被推到页外）；现在与外层公式同样处理，`\phantom` 的占位宽度也按公式而不是按文字计算。
  - 注释分隔符紧跟在 `*` 之后会结束一个并未开始的注释（`f * \text{g}` 使 PDF 编译失败）；空的 `\mathop{}`、`\mathrel{}`、`\overset{x}{}`、`\frac{a}{}` 生成没有内容的调用（`\mathop{}\!\mathrm{d}x` 这一常见写法因此编译失败，现在保留它该有的细空格）。
  - `x^\frac{1}{2}`、`\sqrt\frac{a}{b}`：不带花括号作参数的分式散开；单列的 `matrix`、`array`、`smallmatrix`、`vmatrix` 被加上圆括号；`\operatorname{arg\;max}` 的名字被当作公式改写；`\not` 后面跟被改写的符号时否定的是标记字符。
  - 同一公式里两处互不相干的 `\|`（`P(A \| B) \cdot \frac{…}{…} = P(B \| A)`）被配成一对并拉伸到两者之间内容的高度。`\|` 现在与 TeX 一样是普通符号，只有 `\left\|…\right\|` 与 `\norm{…}` 随内容伸长。
  - 单侧定界 `\left\{…\right.` 包住 `aligned` 时关系符前的间距丢失；`\underset{n}{A}^2` 的指数被排到正上方；`\iff -x`、`\sum_i \; -a_i` 的负号被当作二元运算符；冒号后面的算符名（`B : \operatorname{Space}(d)`）仍按文字排。
  同时补完了对书中全部 TeX 构造逐类排查的余项：缺操作数的运算符按普通符号排（`= \star I`、`\langle\cdot,\cdot\rangle`、`|+\rangle`、`\rho_{|+}`），`\cdots`、`\ldots` 两侧补上细空格，多列 `aligned` 的列对之间留 1em，矩阵列距由 0.5em 改为与 TeX 一致的 1em（主题），`array` 的列对齐（全 `l` 或全 `r`）得以保留，`\square` 不再印成极小的方块。TeX 扫描部分与词法分析一样改用写明的 ASCII 字符类，不受 ctype 区域设置影响。作为最后一道防线，结果里若仍有内部标记或编码宽度，就改用作者原文的转换结果。`tools/tests/test_pdf_math.py` 增至 19 个用例。

## [0.3.1] - 2026-11-11

### 新增


- `until(page, fn)`（`tools/node/viz-testkit.mjs`）：等页面自己报告某件事发生了，成立返回 `true`，超时返回 `false`，可以直接作为一条检查的结果。用于靠动画帧自己前进的东西，首先是播放：`settle(page)` 走完过渡，但不替时钟往前走。

### 修复

- PDF 数学排版：公式在 PDF 中按 TeX（以及 HTML 版的 KaTeX）的含义排，不再因 Pandoc 的 TeX→Typst 转换与 Typst 自身的规则走样。`tools/filters/typst-compat.lua` 由“改几个符号名”扩成两遍处理：转换前改写 TeX（`M.tex`），转换后在词法单元层面改写 Typst 代码（`M.rename`）。此前不会让构建失败、只能靠渲染页面才看得出的问题，在《量子计算的几何直觉》一书中逐类实测后修复：
  - 空格：`\;` 被写成零宽、`\!` 被写成 `-1em`（符号相叠），`\thinspace`、`\mkern`、`\kern` 等使整条公式原样印成源码；Typst 让显式空格取代相邻关系符、运算符与逗号的自动间距（`a \;=\; b` 排得与 `a = b` 一样，`a \,=\, b` 反而更挤）。现在显式空格按 TeX 的宽度叠加在自动间距之上，空格后的正负号保持一元或二元不变。
  - 竖线与范数：`\|`、`\norm{x}` 被写成关系符 ∥（两侧多出间距、相邻关系符失去间距、指数叠在竖线正上方）；单竖线保留源码里的空白（`| ψ⟩`、`| x |²`）。
  - 算符名与文本：`\operatorname{Tr}(ρ)`、`\Tr(ρ)` 排成 “Tr (ρ)”（该书 PDF 中 248 处，修复后为 0）；`\text{…}` 两侧多出词间空格，其中 `\&`、`\%` 之后的空格被吞、`\^{}` 被丢。
  - 定尺寸括号：`\bigl(` 等被写成缩放的盒子，不占位、两侧带词间空格、不分开闭；`\bigm`、`\Bigm` 不能转换。
  - 分式：`\frac{1}{\frac{1}{2}}` 被写成 `1 / 1 / 2` 而排成 (1/1)/2，`\frac{a}{b}^2` 的指数落到分母上，`\tfrac`、`\dfrac`、`\tbinom`、`\dbinom` 的大小被忽略（后两者与 `\cfrac` 原先不能转换）。
  - 关系符的上下标：`E \to_L E`、`\simeq_{…}` 的下标被排到箭头正下方；`\stackrel`、`\overset`、`\underset` 则相反，被排在一旁；`\xrightarrow{…}` 的箭头不随标注伸长；`\limits`、`\nolimits` 被忽略。
  - 符号：长箭头（`\longrightarrow`、`\Longleftrightarrow`、`\longmapsto`、`\iff` 等）印成短箭头且 `\iff`、`\implies` 缺两侧的间距；公式里的 `\&` 成了对齐点而不印出；`\succeq`、`\preceq` 印成弯曲变体；`\backslash` 印成差集运算符；`\mathsf` 印成斜体；`\{…\}` 被自动放大。
  - 结构：`smallmatrix`、`matrix`、`array` 在 `\left…\right` 之外被写成裸露的行（行内矩阵断成两行），`vmatrix`、`Vmatrix` 的定界符使 PDF 编译失败；`\left. … \right|` 的竖线不随内容伸长；`\mathbin{…}` 等的类别被丢弃；`\pmod`、`\bmod` 的间距不对；`cases` 两列之间没有间隔；`\middle|` 两侧多出间距。
  - 主题：`theme/typst/book.typ` 整体导入文档，其中的 `accent`（颜色）与 `mono`（文字样式）盖住了 Typst 的同名数学函数，多符号重音（`\widetilde{AB}`、`\vv{AB}`）印成颜色值文字，`\mathtt` 印成灰色小字；两个名字改为 `accent-colour`、`mono-text`。重音下的 i、j 保留圆点（与 TeX 一致）。
  - 转换不了的公式照作者原文交给 Pandoc（与原先一样原样印出），不会被改写后的文本替换。
  - 跨平台：Typst 词法分析使用明确的 ASCII 语法规则，避免 macOS 的 locale 把 UTF-8 字节误判为字母或空白，使分式、竖线等公式构建失败。
  新增 `tools/tests/test_pdf_math.py`：把 TeX 送过真实的转换链并用 Typst 实测排出的宽度（空格宽度、叠加关系、源码空白不产生间距、范数、定尺寸括号、分组、分式、矩阵、文本转义），并检查主题没有定义与 Typst 数学函数重名的名字。下游书库升级后无需改正文；此前为 PDF 绕开的写法（删 `\!`、拆多符号重音、把 `\norm{x}^2` 改写为 `\lVert x\rVert^2`）可以保留，也可以改回。

- 示例页 `golden-carry` 的测试与可视化起始模板（`templates/viz/test.mjs`）不再为播放等固定的时间。原先“按空格、等 700 毫秒、再读状态”的写法在动画帧被拉开到 900 毫秒时失败（页面本身没有错）；现在等状态本身，在一秒一帧下通过。三张自动播放的卡（`zoom`、`fill`、`sweep`）的检查同时收紧：原先只看“正在播放”的标志，现在要看到时间轴确实前进。
- `skills/book-viz`：区分过渡与播放的等待方式，交付前的慢帧复查改为 `VIZ_SLOW_FRAMES=1000`（350 毫秒照不出 700 毫秒的固定等待）。

### 变更

- skills：把 trureturing-books 为《量子计算的几何直觉》补全内容时遇到的问题写进指引。`book-write` 新增“容易踩的坑”：同一公式过三条渲染链路时仍需留意的写法（Pandoc 不认识的命令使公式原样印成源码、`\big/` 使 epubcheck 报 RSC-005、`\mathcal` 小写字母两端字形不同、并排等式分行），以及“PDF 与 HTML 不一致时修转换而不是改正文”；写“文献结果”之前在所钉提交上按 `digest:` 搜索冻结库并核对本书已有引用、忠实陈述时的 Lean 全函数约定与局部实例、手写的定理计数与数值的同步核对；步骤中加入手机宽度与三种产物都构建的要求。`book-export` 排错清单新增 PDF 源码泄漏与越界的文字扫描、公式走样时的处理路径、epubcheck RSC-005 的定位，以及用真实转换链做最小复现的命令。`trureturing-pin` 说明浅克隆 checkout 会让分支可达性判断失败及补救命令。`book-viz` 说明浏览器测试里连续两次输入之间必须等待渲染帧，否则数字框被重写、CI 偶发失败（trureturing-books 的 `sphere-escape` 测试即如此，已用延迟渲染帧的方式确定性复现）。

## [0.3.0] - 2026-11-11

### 新增


- 可视化：每张实验卡都可以在章节里单独引用，`::: {.viz src="<id>" preset="<卡>" height="500"}`。HTML 中它是开在那张卡上、不带内部滚动的一张图（舞台、一句说明、◀ ▶、时间轴），“全屏打开”进入同一状态的完整实验室；PDF/EPUB 中它是那张卡的带标签静态图 `viz/<id>/fig-<卡>.<语言>.jpg`，取代通用封面。`./tbook check` 核对被引用的卡存在、各语言版本引用同一张卡、静态图齐全；`node tools/node/viz-thumbs.mjs` 在生成封面的同时为被引用的卡生成静态图，并删除不再被引用的。运行时新增 `TRV.preset`、`TRV.figure`、`TRV.shot`、`TRV.still`。
- 可视化运行时 `theme/viz/kit.js`（`TRV.kit`，可选）：二维画布上的三维舞台（轨道相机、深度淡化、球面拾取、DOM 标签）、二维舞台与小图、时间轴、实验卡与导览条、进入视野才播放、过渡、互斥按钮组、滑块绑定、快捷键与数字格式。`theme/viz/theme.css` 新增舞台优先的实验室版式 `.app.lab`、实验卡 `.presets.cards`、条带小图 `.strip`、导览条 `.tour`、舞台图例 `.hud-bl` 与关键读数 `dl.ro .key`，以及书内引用图与静态图两种模式的样式。
- 质量门 `stageFirstChecks`（`tools/node/viz-testkit.mjs`）：舞台占视口的比例、每张卡可点且有说明、舞台标签不重叠、如实标注（`evidenceChecks`：Lean 链接与锁文件逐条相符、登记表与页面引用的定理一致、绿色框恰好是引用 Lean 定理的框、抽屉写明不是证明）、英文无残留中文、书内第一屏、被引用的图不滚动、PDF 静态图、手机无横向滚动、封面非空白、减少动效。另有 `settle`（让页面立即重绘，测试不靠等待）、`viewportShare`、`inkShare`、`labelOverlaps`。
- `node tools/node/viz-shots.mjs <book> <id>`：按读者会看到的样子截图（桌面、书内、手机、封面，中英各一），可用 `--do` 先切到某个状态。
- `kit.flush()`（测试里的 `settle(page)`）先把进行中的过渡走完再重绘，测试不必为过渡等固定的时间。`VIZ_SLOW_FRAMES=<毫秒>` 让测试在动画帧被拉开的条件下运行，用来在本地复现只在忙碌的 CI 机器上出现的失败。起因：下游一个页面的卡片先用 420 毫秒的过渡把矢量移到起点再生效，测试固定等 560 毫秒，CI 上结束过渡的那一帧来得更晚，两条检查读到了尚未生效的状态。

### 变更

- `skills/book-viz/SKILL.md` 重写。起因：0.2.3 把起始模板与技能统一成 `golden-carry` 的三栏账本骨架之后，下游书库的四个可视化主题各异（布洛赫球、对角线、佩尔方程、格拉姆行列式），却都被套进同一副骨架，舞台只剩一小块，读者看到的是数字墙，并且每个可视化只在章末整台嵌入一次，正文讲到某个情形时图不在旁边。新的技能给出方法而不是骨架：先写一句话与几张实验卡，按对象选舞台，每张卡都是正文可引用的图，诚实标注，亲眼看截图，再过质量门；并列出反模式。
- 起始模板 `templates/viz/` 换成一个可运行、可通过自带测试的舞台优先页面（单位圆上的影子与高度）；`templates/viz/README.md` 与 `docs/AUTHORING.md` 相应更新。`CLAUDE.md` 第 6 条改为“版式服从内容，契约不可改”。示例可视化 `books/example-monograph/viz/golden-carry/` 用同一套方法重做，成为这套方法的成品示例：四个场景（筹码与进位、亏量图、相位正方形、收缩面的窗口）共用一条时间轴，十张实验卡；第一章在正文讲到的地方引用其中四张（`window`、`cancel`、`map`、`fill`），章末保留完整的实验室。页面引用的冻结定理由两条增加到八条（都已在第一章引用，锁文件不变）；测试 `golden-carry.test.mjs` 先过 `stageFirstChecks`，再用独立实现核对每条声称。旧的三栏账本版式不再存在：起始模板、示例与下游页面用同一套版式、工具包与质量门。
- 站点构建不再发布 `fig-*.jpg`（只供 PDF/EPUB 使用）。
- `skills/book-viz/SKILL.md` 补入下游用这套方法新做四个页面时遇到的情形：几个场景共用同一个对象；二维舞台何时不必两轴等比、按真实比例看不见的对象换一种表示；舞台标题要短、标题里不写单个字母的变量（按大写排版）；引用块顶格写、不放进列表项；页面不替章节转述的新近文献背书；封面里二维舞台要自己加粗；`kit.clock` 的 `format` 在构造时即被调用；同一页混用二维与三维场景的写法；随机抽样核对极值时的收敛。

### 下游需要手动操作

- 自己的页面无强制迁移：已有页面与嵌入照常工作（旧的三栏版式写在各页面自己的 `style.css` 里，不受影响）。
- 保留着示例专著的书库（包括用 `site.toml [books].hide` 隐藏着的）：`books/` 归书库所有，`./tbook template update` 不会更新它。请把示例书同步到本版本，例如 `git checkout refs/template-tags/v0.3.0 -- books/example-monograph`（或按 `docs/UPGRADING.md` §6 合并模板的 tag）。托管的单元测试中有几项按示例页面的内容断言（它引用的定理、第一章引用的卡），示例书停在旧版本时会失败。建议按新技能检查已有可视化；要在正文里按卡引用，页面需改用 `cards.pick(cards.initial('<默认卡>'))` 开场并在 `TRV.still` 时显示关键帧（起始模板演示了写法）。

## [0.2.5] - 2026-11-11

### 修复

- PDF：修复 trureturing-books 审计表中长 Lean 标识符跨列重叠、长公式越出版心的问题；表格内代码允许在字符间换行，公式按实际单元格、列表和定理框宽度等比缩小并重新计算占用高度。屏幕版页眉为书名和章名分配固定比例的栏宽，避免长章名把书名挤出纸张。新增四种语言/配色组合的真实 Typst 几何回归，并补充导出技能中的分行与表格列宽指引。
- PDF：Pandoc 对固定尺寸的角括号、上取整与下取整括号会输出 `scale[…chevron.l…]` 等标识符文字；兼容过滤器现在在缩放内容中显式插入数学符号，覆盖正文及环境标题，并以实际渲染宽度回归核对。

## [0.2.4] - 2026-11-11

### 修复

- mdBook：中文加粗中含括号、引号或公式，且标记外紧接汉字时，按 PDF/EPUB 的语义保留加粗。HTML 暂存阶段以不可见注释隔开 CommonMark 的标点边界，不给中文正文插入空格；代码、转义、公式内部、链接地址与原始 HTML 保持原样。新增真实 mdBook 构建回归，覆盖正文、引用、表格、公式和嵌套斜体。

## [0.2.3] - 2026-11-11

### 变更

- 可视化模板与技能（`templates/viz/`、`skills/book-viz/SKILL.md`、`CLAUDE.md`、`theme/viz/theme.css`）：将 `./tbook viz new` 生成的起始脚手架从双栏干涉示例升级为与 `books/example-monograph/viz/golden-carry/` 完全一致的三栏结构（左栏 `.deck` 步进器+滑块输入与 `dl.ro` 主读数，中栏 `.ledger` 规则徽章、真实 HTML `.drow` 分步可点击账本、`#tape` 符号带与底部 `footer.rail` 播放控制栏，右栏 `#heatPanel[data-thumb]` 二维交互相图与 `#evidence` 标准依据徽章，以及 `?thumb=1` 左右分栏无字缩略图 `drawCover()`）；在 `skills/book-viz/SKILL.md`、`templates/viz/README.md` 与 `CLAUDE.md` 中明确三栏元素与标准依据类名规范，并在 `theme/viz/theme.css` 补齐 `--grid-line` 与 `--radius` 令牌映射。

## [0.2.2] - 2026-11-11

### 修复

- mdBook：校对 trureturing-books 时发现中文搜索摘要把整段无空格正文算成一个单词，单条结果占据多屏；改为从索引原文截取命中词附近最多 160 字符的摘要，保留高亮和省略标记，英文摘要沿用原行为。浏览器回归覆盖长段落、深处命中、混排、HTML 字面量与重复搜索。
- 书籍入口页：目录中的章节、子章节、草稿与部分标题公式同样预渲染为 KaTeX；部分标题的大写样式保留公式的大小写。
- mdBook：窄屏中超过行宽的行内公式与不可断行标识符独占可横向滚动的一行，完整表达式可达；适配视口变化与字体加载，普通行内公式保持原排版。

## [0.2.1] - 2026-11-10

### 修复

- mdBook：SUMMARY 中的章节标题、部分标题与草稿标题的公式在侧栏目录中保留 KaTeX 排版，菜单栏书名同样支持公式；浏览器标签和搜索索引用公式的可见文字。此前目录显示 TeX 源码，直接在 SUMMARY 预渲染又会被 mdBook 剥去排版。修复同时覆盖 JavaScript 目录与无 JavaScript 的 `toc.html`，目录脚本重新计算内容哈希。

## [0.2.0] - 2026-11-10

升级时迁移 `tools/migrations/v0.2.0.py` 自动处理书库自有的内容：给每个 `books/*/films/*/film.json` 补上缺少的 `outputs.narrated_720p` 与 `outputs.cover`（默认文件名），删除不再使用的 `release_tag`、`published_tag`；已列出的 1080p 与纯配乐输出保持不变。它还在升级摘要中提示：视频如何改用 720p 默认、书库保留示例书时用 `[books] hide = ["example-*"]` 隐藏它们、调用 `ci.yml` 的书库工作流须授予 `pages: read`。

### 新增


- 示例书扩充为四章加一个附录：收缩面与相位判据（附图与小数值表）、有限证书与反驳（Detlefs、反例搜索、Farkas）、细化与目标风险、遗忘与熵、黄金词与回归得分、$\lambda_-$ 的几乎可加性、齐肯多夫表示与进位（附图）；33 条定理类结论都引用所钉提交上已冻结的 Lean 声明，另有 2 个开放问题与 1 个猜想；Detlefs 刻画补上漏掉的剩余类后得到的修正刻画写成注记（两个方向都有纸面证明，尚无 Lean 证明），不算开放问题。定理 2.1 改为只陈述 Lean 证明的内容（该取整公式并非对所有 $n \ge 1$ 成立），见证值移到证明中。
- 新增第二本示例书 `books/example-primer/`《斐波那契与卢卡斯：一本可验证的入门小书》：两章、11 条定理与一个开放问题，没有媒体，演示一本书最少需要什么。两本示例书都以 `example-` 开头，书库用 `hide = ["example-*"]` 一并隐藏。
- 构建缓存（`tools/tbook/buildcache.py`，`docs/ARCHITECTURE.md` §5.1、`docs/PUBLISHING.md` §5）：每个构建单元（每个语言版本的 HTML、每种 PDF、EPUB、每本书的幻灯片、每个视频）按全部输入的 SHA-256 定键，输入没有变化就恢复存下的产物，不再构建。示例书 `./tbook build html pdf epub slides` 从约 50 秒降到约 0.5 秒，视频从约 3 分钟降到约 0.3 秒。查找顺序：本地存储 `.cache/artifacts/` → Actions 缓存（只由 `pages.yml` 在默认分支上保存，PR 事件不读不写）→ 最新 5 个附有 `build-cache.json` 的已发布 Release（`TBOOK_CACHE_REMOTE=1`，逐个核对 SHA-256 与 GitHub 的 `digest`）→ 构建。新命令 `./tbook cache status|key|prune|export`；`TBOOK_CACHE=0` 关闭缓存。
- 每个 Release 都是整站的恢复点：`release.yml` 无论 tag 是单本还是全部书都构建整个站点，把每个单元的 tar 与清单 `build-cache.json` 与读者下载一并附上；先建草稿、上传全部附件再发布，兼容 immutable releases。模板仓库的 `template-release.yml` 为示例站点做同样的事。没有 Actions 缓存的构建（新仓库、缓存被淘汰、PR）由此恢复。
- 视频是构建产物：`./tbook build films|site|all` 渲染或从缓存恢复每个视频（`TBOOK_FILMS=auto|require|skip`；CI 与 Pages 用 `require`，视频渲染失败则构建失败），成片随站点发布在 `_site/<slug>/films/<id>/`（同源，iOS Safari 可播放），书中播放器用 720p 版本。视频工具链由 `theme/film/setup.sh`（不再需要视频参数）装入 `.cache/film/`，Python 包钉在 `theme/film/requirements.txt`。渲染不再改写提交入库的 `poster.jpg`。站点没有某个视频时，章节显示海报与说明，首页不显示“观看”。
- `site.toml` 的 `[books] hide`：隐藏的书（glob 模式的列表，按书的目录名匹配，区分大小写，规则同 Python 的 `fnmatch.fnmatchcase`；默认 `[]`，不隐藏任何书）留在 `books/` 中，但所有命令与产物都当它不存在：`./tbook check`、`./tbook pin` 与 `pin --refresh`（只收集可见书的引用，只被隐藏的书引用的声明从锁文件中删去）、`./tbook build` 的各个目标与站点、构建缓存（`./tbook cache status|prune|export`）、`./tbook lean-project`、`release.yml` 的发版计划，以及 `viz-validate`、`viz-test`、`slides-check`、`slides-build`。按 slug 点名隐藏的书（`--book`、`new-chapter`、`viz|slides|film new`、`<slug>-v*` tag 等）报错并说明如何取消隐藏；`./tbook check` 输出一行列出被隐藏的书；`./tbook new-book` 新建的书被隐藏时警告。从模板创建的书库设 `hide = ["example-*"]` 隐藏模板附带的示例书，而不是删除它们：以后用 git 合并模板改动时不再因示例书冲突（`skills/book-new`、`docs/UPGRADING.md` §6、`docs/ARCHITECTURE.md` §2.1）。新命令 `./tbook books [--hidden] [--files GLOB]`（只需 Python 标准库）；`.github/actions/setup` 的“Find films”与 `ci.yml` 的“Find slide decks”用它跳过隐藏的书。模板仓库的 CI 另在隐藏示例书的工作树中重跑检查与单元测试。

### 变更

- 视频不再单独发 Release（**需要手动操作**）：删除了 `.github/workflows/film.yml` 与 `theme/film/release.py`（`./tbook template update` 会删除托管副本），`film-*` tag 不再发布任何东西（`release.yml` 遇到不指向任何书的 `film-*` tag 只提示并跳过，这类旧 tag 可以删除）；`film.json` 的 `release_tag`、`published_tag` 不再使用，`./tbook check` 警告；升级迁移会删除它们。GitHub Pages 站点上限 1 GB：视频默认只发布 720p 旁白版，每分钟约 8 MB；列出全部输出时每分钟约 84 MB（见下一条），视频多的书库留意站点大小。
- 视频默认只构建 720p 旁白版（**需要手动操作**，见下文）：`film.json` 的 `outputs` 列出什么就构建、托管、链接什么。必需 `narrated_720p`（播放器播放的 720p 旁白版）与 `cover`；`narrated`（1080p 旁白版）、`music_only`（1080p 纯配乐）、`music_only_720p` 只在列出时构建；`outputs` 中的其他键与写成 `null` 的值由 `./tbook check` 报错。`resolution` 是发布的视频尺寸：默认 `1280x720@<fps>`，列出 1080p 视频时为 `1920x1080@<fps>`，与 `outputs` 不符时报错。`./tbook film new` 与示例视频只列 `narrated_720p` 与 `cover`。流水线只编码所需（`theme/film/plan.py`）：Chromium 仍按 1920×1080 截取每帧，各渲染进程在同一遍中把帧缩放编码为 720p（hqdn3d、lanczos，x264 CRF 19、preset slow，画质与原来两遍 900 kb/s 的 720p 相当、码率略低），只在列出 1080p 视频时另编码 1080p 母版，纯配乐混音只在列出纯配乐视频时生成；`mux` 只拼接并混入音频（AAC 48 kHz，faststart）。删除 `small` 步骤与 `theme/film/small.sh`：720p 不再由 1080p 母版重新编码。`film.sh <dir> all [<输出>…]` 与 `FILM_OUTPUTS` 指定要做的输出，默认是 `film.json` 所列，构建明确传入它们；渲染缺少所列文件时构建失败，不存入缓存。50 秒的示例视频渲染从约 155 秒降到约 80 秒，站点上它的文件（视频与封面）从约 71 MB 降到约 6.5 MB；列出 1080p 视频时约 140 秒，1080p 文件与原来逐字节相同，720p 旁白版无论是否列出 1080p 都相同。章节播放器的下载链接、视频页、落地页与 `films.json` 只指向所列文件；下载标签“纯配乐”改为“纯配乐 1080p”，新增“纯配乐 720p”。下游书库：原先省略了 `narrated_720p`（曾可省略、取默认名）的 `film.json` 由升级迁移补上（手工维护时 `./tbook check` 给出默认文件名）；列出全部五个输出的视频照旧构建全部五个；要改用新默认，删去 `narrated`、`music_only`、`music_only_720p`，把 `resolution` 改为 `1280x720@30`。
- 以 `workflow_call` 调用 `ci.yml` 的书库工作流须授予 `pages: read`（**需要手动操作**）：`build` 与 `media` 作业用 `actions/configure-pages` 取得 Pages 地址，使 CI 的缓存键与 `pages.yml` 一致。
- `.github/actions/setup` 的 `fonts: 'true'` 也安装 Playwright `--with-deps` 会装的字体（`fonts-liberation`、`fonts-ipafont-gothic`、`fonts-wqy-zenhei`、`fonts-freefont-ttf` 等）：PDF 与 EPUB 的键包含系统字体族，构建它们的作业（`ci.yml` 的 build、`pages.yml`、发版）因此看到同一套字体，键一致。
- `./tbook serve` 支持 HTTP 字节范围请求（`Range`，206），本地预览的视频在 Safari/iOS 中也能播放；`./tbook doctor` 按 `$FFMPEG` 查找 ffmpeg，与视频构建一致。
- `ci.yml` 的 `media` 作业也构建视频（PR 中验证改动的视频能渲染）；在默认分支与 tag 的推送上不构建，由 `pages.yml` 与发版工作流构建，同一次推送不会把一个视频渲染两次。`pages.yml` 的构建步骤有短于作业的时限，超时后已完成的单元照常保存。

- 标题按行内 Markdown 读：环境标题与 SUMMARY 章节标题中 `$…$` 之外的反斜杠转义（`C\*-代数`、`\$5`）在 HTML 页头、侧栏、`<title>`、站点、PDF、EPUB 与账本中都显示为标点本身，`$…$` 内的 TeX 不变。此前 HTML 与站点保留反斜杠；SUMMARY 中 `$…$` 外的 `\{` 现在显示为 `{`。
- HTML 注释中的内容不再被改写、检查或编号（含注释块里的环境）；以 `<!--` 开头的注释块没有 `-->` 时 `./tbook check` 报错。行内注释可以跨行，到同一段落内的 `-->` 为止，HTML、PDF、EPUB 都隐藏它；段落在 `-->` 之前结束时 `<!--` 是普通文字，后文还有 `-->` 时 `./tbook check` 警告（Pandoc 会一直隐藏到那里）。
- 跨行的公式（`$$…$$`，或跨行的 `$…$`）整个属于所在段落，其中以 `+`、`-`、`>`、`#`、`=` 或四个空格开头的行不再开始列表、标题或代码块。公式不跨过开始围栏代码块的行：代码块上方未配对的 `$`（“加入 $PATH：”下接含 `$HOME` 的代码）不再把代码与其后的正文吞进公式；Pandoc 仍会跨过围栏配对这个 `$`，`./tbook check` 因此警告，字面美元号写 `\$`。
- mdBook 与 Pandoc 读法不同的块结构由 `./tbook check` 警告：随容器结束或到文末仍未闭合的围栏代码块、多于一行的术语或术语与定义之间隔了多个空行、`~` 开头的定义；定义只跟在一行的术语之后。表格的每一行各算一个段落，单元格里未闭合的 `<!--` 不再隐藏后面的行。
- 脚注：定义可以写在块引用或列表项里；mdBook 不当作脚注引用的 `[^x]`（转义的，代码、注释、公式、原始 HTML、自动链接、链接地址与标题、环境标题里的，紧接 `(…)` 或 `[x]` 的）在 PDF/EPUB 中也不加章节前缀，也不计入标题锚点的编号；标签只差大小写、紧接 `(…)`/`[x]`、标签含空格或 `^` 时 `./tbook check` 警告。
- 代码块按 CommonMark 判定，各端一致：缩进代码块在任何容器（列表项、块引用、脚注、定义）中都是代码，其中的 `[@id]`、`lean:` 链接、图片、链接与公式各端原样显示，`./tbook check` 不再检查它们（此前列表外的缩进代码会被检查与改写）；列表项内容从标记后的第一个字算起（`1. ` 下的代码缩进七格）；定义（`:   …`）的后续段落是正文。
- 引用式链接定义按 CommonMark 判定：以 `[x]:` 开头、后接正文的行（如 `[1]: Knuth, TAOCP.`）是段落，HTML、PDF、EPUB 都显示，其中的链接照常改写与检查；在列表项、块引用与列表续行中也一样。定义可以在这些容器里，标题可以是 `"…"`、`'…'` 或 `(…)` 并含反斜杠转义；引用式图片与带标题的图片复制进构建目录。
- `lean:` 链接的每种单行写法（行内、尖括号地址、带标题、链接文字含成对方括号、引用式定义，含列表项与块引用中的定义，以及自动链接 `<lean:GID>`）由 `./tbook check` 核对、`./tbook pin --refresh` 收录；锁文件不能解析的引用式定义输出 `#`，不再输出 `lean:` 地址。工具读不到的写法（链接跨行、定义的地址在下一行、原始 HTML 的 `href`/`src`）由 `./tbook check` 报错，构建时去掉其中的 `lean:` 地址（地址写成 `<lean:…>` 时也一样，不再被当作自动链接）；环境标题中的 `lean:` 链接报错，只显示文字。冒号后为空的 `[x]:` 只有下一行是地址时才是定义，否则是普通段落，各端都显示。
- 引用式链接定义只能开始于段落开头，或紧接在段落开头的另一条定义之后（含标题写在下一行、或跨行的定义），与 mdBook 和 Pandoc 一致：接续段落的 `[fig]: ../assets/x.svg`、`[x]: lean:…` 是正文，不改写、不核对；`<div>` 这类 HTML 块中的行照旧可以是定义（Pandoc 读其中的 Markdown），`<pre>`、`<script>`、`<style>`、`<textarea>` 中的行原样保留。`[1]: <lean:GID> 文字`、`> [3]: <lean:GID>，文字` 是含自动链接的段落，照常核对并改写为永久链接；公式里的 `[0,1]:` 不再被转义。`[x]:` 下一行的地址不是 URL 时 `./tbook check` 警告：两端都读作定义，构建却不复制、不解析它。只含 `:` 的定义行，其正文从冒号后一列算起，与两端一致；冒号行后隔空行再写正文时警告。
- 幻灯片按 Vue 编译器传给组件的值读取 `gid`：`gid`、`:gid`、`v-bind:gid` 中写在最前面的生效（此前 `:gid` 总是优先，`v-bind:gid` 不被读取）；不带参数的 `v-bind="{…}"` 报错；不带参数的 `v-on="{…}"` 之后另起一组属性，组里最前面的 `gid` 覆盖前面的。
- `site.toml` 的 trureturing 分支不存在时，`./tbook check` 把错误归在 `site.toml` 下并说明改法，不再报成“所钉提交不在该分支上”。
- `UNVERIFIED` 徽章在 PDF 与 EPUB 中也不是链接，EPUB 提示文字为“未经验证”而非“开放问题”；Typst 的 `tr-env` 新增 `badge-url` 参数。
- `trureturing.lock.json` 的 `branch` 必须等于 `site.toml` 的 trureturing 分支，不一致时 `./tbook check` 报错（**需要手动操作**：改过 `site.toml` 的分支而没有重新钉版的书库运行 `./tbook pin`，或在所钉提交也在新分支上时运行 `./tbook pin --refresh`）。分支名必须是 `git check-ref-format --branch` 接受的分支名，且不能是提交 SHA（含缩写）、`refs/…`、`@` 或修订表达式（`<sha>^0`、`dev~1`、`owner:dev`、`dev@{0}`、`HEAD`），还必须是确实存在的分支：本地只认同名的 ref，GitHub 上先问分支端点，再拿分支头的 SHA 去比较（形如 describe 输出的 `dev-12-g7bbf30f`、`pull/123/head` 会被 git 与 GitHub 读成某个提交）。否则 `./tbook check` 报错、`./tbook pin` 拒绝。分支结论的缓存文件改名为 `.tbook-on-branch-v2.json`，旧版工具缓存的结论不再采信。

### 安全

- CI 的 PR 运行不再信任自己先前运行写下的缓存：工作流只在默认分支与 tag 上恢复和保存 `.cache/trureturing`，`tbook` 在 `pull_request*` 事件中也不读取它（状态片取自 `raw.githubusercontent.com`，分支可达性每次问 compare API）；`.github/actions/setup` 的工具链缓存（pip、Playwright 的 Chromium、字体）在 `pull_request*` 事件中既不恢复也不保存，PR 运行每次从网络下载（只拦保存不够：PR 能改自己的工作流，一次推送就能写入 PR 作用域的缓存，下一次推送再恢复它）。npm 缓存按 `package-lock.json` 的完整性校验，照常使用。见 `docs/VERIFICATION.md` §2。
- 提交入库的 `.cache` 符号链接按其自身的名字报错，不再跟随链接去问 git。
- `lean-verify.yml` 的 pip 缓存与 Lake 工作区缓存（公理检查读其中已构建的 `.olean`）在 `pull_request*` 事件中既不恢复也不保存：它可以经 `workflow_call` 被书库的 PR 工作流调用。

### 修复

- 下游书库隐藏 `example-*` 并重新钉版后，依赖示例声明或提交的集成测试跳过，使用合成锁文件的测试照常运行；CI 在隐藏示例书时同时更换锁文件提交并清空声明，覆盖真实的下游状态。
- 可视化、视频与新书脚手架的默认日期统一使用 UTC，书籍缺省日期也保持一致；补充 UTC+14、UTC−11 跨日边界测试，确保 Python 与 Node 生成的可视化文件相同。
- PDF：`\cap`、`\bigcap`、`\sqcap`、`\odot`、`\otimes`、`\ominus`、`\circleddash` 等不再使整本 PDF 构建失败。Pandoc 的 Typst 输出仍用旧名 `sect` 与修饰符 `.circle`，所钉的 Typst 已改名为 `inter` 与 `.o`；`tools/filters/typst-compat.lua` 在正文与环境标题的公式中改写它们。测试把 KaTeX 支持的每个数学符号经 Pandoc、过滤器与 Typst 编译一遍。
- HTML 与幻灯片：主题以大写显示的表头、SUMMARY 部分标题与幻灯片表头中，公式与代码保持原样（此前 $\varphi$ 显示为 $\Phi$，$n$ 显示为 $N$）。
- PDF/EPUB：带 `{-}`（`.unnumbered`）的标题不再与 Pandoc 的自动 id 冲突、导致 Typst 失败；缩进代码块中的脚注、链接与公式原样保留；紧贴在文字行下的标题也是标题，不再显示字面的 `{#id}`；含公式的标题按 HTML 显示的文字生成 id（`#关于-β-的估计`），含脚注引用的标题按 mdBook 显示的编号生成 id（`## 注释[^a]` → `#注释1`），从 HTML 版复制来的片段链接在 PDF/EPUB 中同样可达（构建 PDF/EPUB 时用 Node 渲染标题中的公式，不可用时退回 TeX 源码并警告）。
- PDF/EPUB：紧贴在段落行下的环境（`::: {.theorem …}`）不再被 Pandoc 读成正文，保留标题、编号与徽章；地址为空的链接与图片（`[x]()`、`![x]()`）不再使 Typst 构建失败，显示为文字并警告（`./tbook check` 也警告）。
- PDF/EPUB：列表项与块引用中以 `[1]:` 开头的文献行不再被 Pandoc 当作链接定义吞掉；定义列表的后续段落不再被当作缩进代码（公式照常渲染，EPUB 通过 epubcheck）。
- PDF/EPUB：块引用或列表项中的 HTML 块随所在容器结束（HTML 块没有惰性续行），其后正文中的脚注照常编号，标题锚点的编号与 HTML 一致；块首行的缩进只在前面确有列表项时算作容器（块引用中只含 `>` 的行不结束其中的列表项），主题分隔线（`---`、`***`、`* * *`）结束段落，段落下空的列表项只在同一列表已打开时开始新项；`[^a][ ]`、`<b and [^a] c>`、`#标签` 下的 `<b>` 按 mdBook 读取；标题中的 HTML 注释不计入 id；公式里的 `=`、`---` 行不再被当作标题下划线。
- PDF/EPUB：`other.md#x` 只在 `other.md` 内解析，该章没有的片段显示为文字并警告，不再落到别章的同名 id 上；块引用与列表项里的标题也得到全书唯一的 id，照常可达。链接到原始 HTML 的 id（`<a id="x"></a>`）不再使 PDF 构建失败（Typst 不输出原始 HTML，现在该处有同名标签）；标题末尾的空锚点（`## 小结 <a id="x"></a>`）移到标题之后，不再使 PDF 与 EPUB 失败；`data-id="…"` 不再算作 id。
- 扫描器在大章节上保持线性：`$` 配对、脚注编号与 HTML 块的读取不再随未配对的 `$`、脚注或容器数量平方增长（含数千个 `$5` 价格的表格从数秒降到零点几秒）。
- 幻灯片：`slides-check` 与 `./tbook check` 只跳过真正位于代码块中的标签，两个代码块之间、GFM 表格之后与 HTML 块里的 `LeanBadge`/`TheoremCard` 不再漏检；代码块按 Slidev 53 所用解析器的块规则识别（含表格与全角空格等 Unicode 空白），缩进代码块与 `<<<` 导入行中的标签显示为代码，不再检查；标签按 Slidev 的规则只在完整的开始标签处读取，正文或公式中的 `<`（`$a <b + 1$`）不再吞掉其后的 `LeanBadge`，不完整的引用标签报错；书的第一语言、语言集合或站点地址变化后，`./tbook build slides` 重新构建，不再复用过期的产物。
- 幻灯片 PDF 翻页不再卡顿：每页整页的半透明背景层（极光、扫描线、暗角）在 PDF 中是软蒙版与渐变，阅读器每页要合成约两秒；导出时它们换成一张预先渲染的背景图 `theme/slides/styles/backdrop.jpg`（各页共用、只嵌入一次），示例演示文稿在 Chrome 的 PDF 引擎中渲染 10 页从约 27 秒降到约 1 秒（MuPDF、poppler 也快数倍），文字仍是矢量，每份 PDF 多出约 100 KB（这张图）。背景层移入 `theme/slides/styles/backdrop.css`；图由 `node tools/node/slides-backdrop.mjs` 渲染，`./tbook theme`（改配色后）会自动调用，`./tbook theme --check` 与 `slides-check` 核对它与 CSS、配色同步，`./tbook build slides` 逐页检查打印视图与导出的 PDF 用了它。换了背景的页面须在 class 中写 `tr-own-bg`（在 PDF 中保留背景层），否则 `./tbook build slides` 报错。
- 幻灯片四角的折角框各自朝外（⌜ ⌝ ⌞ ⌟）：此前泛指的类名 `.br` 与右下角的 `.br` 同名，四个角都画成了右下角的形状；泛指的类名改为 `.bracket`。
- 模板升级：在以合并提交并入的分支上删除的托管文件，此后保持删除，不再被每次升级重新安装（`git log --full-history`）；squash 合并不保留这样的删除，见 `docs/UPGRADING.md` §2。
- `release.yml`：以日期开头的版本（如同一天第二次发布的 `v2026.11.08-2`）是正式发布，不再标为 pre-release；只有严格的语义化版本预发布（`v3.0.0-rc.1`）才是。
- 站点：书的落地页在验证摘要中列出的定理标题，其中的公式在构建时由 KaTeX 渲染（此前显示 TeX 源码，如 `$\lambda_-$`）；有公式的页面才加载站点自带的 KaTeX 样式与 WOFF2 字体（`_site/assets/katex/`）。没有 Node 或 KaTeX 时仍显示 TeX 源码并警告。
- 英文页面的弯引号与撇号（mdBook 的智能标点写出的 ’ “ ”）不再是 Noto Sans SC 的全角字形：新令牌 `font.body-latin`（Source Sans 3 在前，Google Fonts 地址随之加入它），mdBook、站点、视频页与可视化在语言不是中日韩时用它作正文字体；中文页面不变。视频的缓存键包含 `theme/generated/tokens.mjs`，所以升级后各视频重新渲染一次。
- 书库首页的书卡不再裁切封面：简介较长、卡片高于封面时，封面按 5:8 完整显示在左栏顶部，此前被拉伸裁去两侧（标题只剩一部分）。
- mdBook 中点击放大的插图显示在主题背景上（此前是 mdBook 的灰底 `#999`，插图的浅色线条几乎看不见），SVG 插图放大到窗口宽度（至多 960px），不再停在原始尺寸。
- 站点没有某个视频时，章节页（含 `print.html`）中隐藏的播放器改为 `preload="none"`，浏览器不再请求不存在的视频（此前每页一个 404）；视频构建后恢复 `preload="metadata"`。
- `./tbook build viz|films` 只重新发布媒体时，删除 `[books] hide` 隐藏的书在 `_site/` 中留下的页面，`./tbook serve` 不再提供它们。

## [0.1.0] - 2026-11-08

### 新增


- 多本书、多语言（默认中文、英文）的书库结构：`books/<slug>/<lang>/`，`./tbook check` 校验各语言版本逐条对齐。
- 定理验证：形式结论必须引用 trureturing 中在所钉提交上已冻结（`Golden/Frozen/state`）的 Lean `theorem`；`trureturing.lock.json` 由 `./tbook pin` 生成并在 CI 中复核；`lean-verify` 工作流做公理闭包深度验证。
- 导出：mdBook HTML（KaTeX 预渲染、语言切换）、Typst PDF（深色屏幕版与白底印刷版）、EPUB 3（Apple Books，MathML）；自动生成“形式化验证账本”。
- 媒体：trureturing-visualize 方案的书内交互可视化；trureturing-film 方案的视频流水线；chrono-company-slides 方案（Slidev）的演示文稿；统一的赛博朋克主题，配色唯一来源 `theme/tokens.json`。
- 站点：书库首页、每本书的落地页、下载、`manifest.json`，经 GitHub Pages 发布；`release.yml` 按 tag 发布 PDF/EPUB/幻灯片 PDF。
- 内置 skills（`skills/`，`.claude/skills` 指向它）与 `CLAUDE.md` / `AGENTS.md`。
- 模板升级：`template.toml`、`template-manifest.json`、`./tbook template status|update|manifest`、`template-sync` 与 `trureturing-bump` 工作流。不带 `--to` 的升级从不降级，也不会用同一版本号下的另一个快照覆盖较新的托管文件；迁移脚本取自新版本模板，在新的 Python 进程中运行。
- 钉版与校验：`./tbook pin` 接受完整或缩写的 SHA、分支或 tag，但所钉提交必须在 `site.toml` 的 trureturing 分支（默认 `dev`）上，`./tbook pin` 与 `./tbook check` 都会核对（本地 checkout 或 GitHub compare API；GitHub Actions 中无法判定即为错误，工作流的检查步骤因此传入 `github.token`）；被拒绝的自动 bump 以 `[refused]` 草稿 PR 报告，不改锁文件。GID 的名称分量支持 Unicode 与 `«…»`；源码行号按 `namespace`/`section` 解析出的完整名定位；各语言版本的 SUMMARY 结构必须一致；提交入库的 `.cache/` 文件是错误。
- 徽章与引用：锁文件不能确认的形式结论显示红色 `UNVERIFIED`，不给链接，也不计入“LEAN ✓ n”等统计；环境标题可以含 `[@id]`（显示为引用文字，未知 id 是错误）与 TeX（反斜杠原样保留）；幻灯片用 `kind="definition"` 引用 Lean 定义时显示中性的 `LEAN DEF`。
- 导出：预设数学宏只在 `tools/tbook/mathrender.py` 的 `TEX_MACROS` 中定义，HTML、PDF、EPUB 渲染一致；PDF/EPUB 中脚注与标题 id 按章节独立，指向书内文件的链接改为指向网站上的副本。
- 视频：`film.json` 的 `published_tag` 记录已发布的 Release，未设置时书中只显示海报与“尚未发布”；`film.yml` 发布后在作业摘要中提醒设置它。
- 多语言：没有内置界面表的语言须在 `i18n/<lang>.toml` 的 `[meta]` 中设 `name`、`bcp47`、`short`（不得与其他语言重复）；所选的书都没有 `--lang` 指定的语言版本时，构建以退出码 2 报错，不会静默跳过。
