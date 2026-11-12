# 学术 Beamer 演示稿

`beamerthemeTBookAcademic.sty` 是使用 Beamer 公共接口编写的原创 Apache-2.0 主题，不含 Lin Zhang/HDU 主题代码、机构图形或默认标识。参考报告提供了版式约定：白底 4:3 页面、单一蓝色主色（RGB 14,44,142）、衬线数学与无衬线正文、带阴影的圆角块、红色提醒、紧凑的节与小节导航，以及左右分列的短作者和短标题页脚。`appendixnumberbeamer` 让正文总帧数不计附录，原创主题在附录页脚显示“Appendix”。标题、导航与页脚使用蓝底白字，未选中导航用较淡白字；圆角块的标题用主色，正文用 12% 浅色底，开放问题与提醒使用纸面语义红色。验证标签有白底，标题框的模糊阴影居中且均匀，导航按钮默认隐藏。

```bash
./tbook slides new example-monograph seminar "Golden integers" --academic --editions en
./tbook slides snapshots example-monograph
./tbook check
./tbook build slides --book example-monograph
```

一份演示稿可以选择书中语言版本的非空子集。按声明顺序为每个所选语言提供一个标题：`slides.tex` 属于该**演示稿**的第一个语言，后续语言使用 `slides.<lang>.tex`。各语言仅在本演示稿内逐帧对齐，与其他演示稿独立。Slidev 原有的文件名、必需语言版本与主题规则保持不变。

配置文件为 `books/<book>/slides/<deck>/deck.toml`。以下示例创建英文报告：

```toml
kind = "academic"
editions = ["en"]
aspect = "4:3"                         # 也可选 "16:9"
structure_colour = "#0e2c8e"
short_author = "W. Zhang, H. Ma"
short_title = "Seminar"
institution = "Example Mathematics Seminar"  # 可选；覆盖 \institute
coauthors = "the seminar contributors"        # 可选；显示 Joint work with …
date = "Seminar overview"                      # 可选；覆盖 \date
navigation_symbols = false                     # true 时恢复 Beamer 导航按钮
# institution_graphic = "assets/institution.pdf"  # 相对于演示目录；无默认图片
# theme_dir = "my-theme"               # 相对于演示目录；本地也可使用绝对路径
# theme_name = "MyTheme"               # 设置 theme_dir 后默认使用 LinZhang
[title]
en = "Seminar title"
```

用普通的 `\author` / `\institute` 字段填写报告人、合作者及核实过的机构信息。Wenlin Zhang 的机构为新加坡国立大学（NUS，Singapore）与 Chrono AI（Singapore）；Haobo Ma 的机构为 Chrono AI（Singapore）。机构图片由演示稿作者提供并取得相应授权。`theme_dir` 通过 TeX 搜索路径加载其中的 `beamertheme<theme_name>.sty`；这些文件归演示稿所有，内容进入缓存键，配套图片也可放在该目录下。自有主题控制自己的导航版式、页脚、标识与颜色；两种主题都默认隐藏导航按钮，设 `navigation_symbols = true` 才显示。原创标题页支持配置中的可选 `coauthors` 行，自有标题页可用 `\TBookCoauthors` 读取它。生成的结果包、备注开关与附录计数继续生效；自有字体与额外宏包须能被固定版本的引擎读取。

每个语言版本以 `\documentclass{beamer}` 和 `\input{tbook-deck}` 开始。构建工具提供画幅与紧凑导航选项，在 `build/stage/<book>/beamer/<deck>/<lang>/` 中生成 `tbook-deck.tex` 和 `tbook-lean.sty`，不要提交这两个文件。使用节、小节与普通 `frame` 环境，每帧写 `% Manuscript: ...` 注释并在源码保留 `\note{...}`。可选技术内容放在 `\appendix` 之后。以下仍为英文报告示例：

```tex
% Manuscript: Chapter 1, Theorem 1.3
\begin{frame}{The carry deficit}
  \begin{bookresult}{thm-deficit-three-valued}
    For all natural numbers $v_1,v_2$, $c(v_1,v_2)\in\{-1,0,1\}$.
  \end{bookresult}
  \note{Recall the normalization before stating the bound.}
\end{frame}
```

`bookresult` 在对应语言的书模型中查找结果。块标题包含书中的环境种类、编号与标题，正文由报告人撰写。形式结论的每个 GID 都须解析为冻结的 Lean 定理，才显示带链接的绿色 `Lean ✓`。开放问题与猜想显示红色 `OPEN`，不得带 GID；带已解析 Lean 引用的定义显示中性 `LEAN DEF`。未解析引用显示不带链接的红色 `UNVERIFIED`，检查与构建会拒绝它。没有 Lean 引用的定义不显示验证徽章。源码选项不能覆盖结果的种类、编号、GID 或验证状态。

`\PinnedCommit` 把所钉提交的短 SHA 链接到该提交的源码树。通常在附录末尾用 `\FormalVerification` 生成账本：按首次引用顺序列出不同结果，每帧最多十二条，紧凑排列结果、GID 与状态，列出所有 GID 及其固定源码链接。较长 GID 用较小等宽字换行，每帧底部标出所钉提交。开放条目明确没有 GID。链接行号只来自锁文件，缺失时不推测。

```tex
\begin{frame}{A positive carry}
  \centering
  \BookViz{golden-carry}{plus}
\end{frame}
\begin{frame}{The phase square}
  \centering
  \BookFigure{phase-square}
\end{frame}
\appendix
\FormalVerification
```

`BookViz` 接受已注册的本地可视化及已有实验卡名称。`./tbook slides snapshots <book>` 复用 `viz-shots` 的可视化服务器、停帧与实验卡状态、本地字体和 Chromium，生成 `viz/<id>/fig-<card>.<lang>.paper.png`。静态图使用 800 × 450 CSS 视口和 4 倍设备像素比（3200 × 1800 像素），占满幻灯片正文宽度。工具在页面绘制前设置纸面令牌，移除屏幕暗角与扫描线效果。这些静态图须提交；检查拒绝未知可视化、未知实验卡和缺失的纸面静态图。PDF 中的图片链接到已发布页面的同一卡片与语言。可视化改动后须重新生成静态图。

`BookFigure` 接受绘图脚本名称。检查比较规范 SVG 与脚本输出，报告过期或缺失的图件；用 `./tbook fig build --book <book>` 重新生成。构建调用 `figure.materialize(svg, "paper", ground=True)`，再通过现有 Typst 工作进程和字体配置把 SVG 转成 PDF 图件；这些字体也进入幻灯片缓存输入。图件始终来自书中脚本，不使用演示目录中手工维护的副本。可用 `\BookFigure[width=.8\linewidth]{phase-square}` 调整尺寸。两种媒体命令都保留比例；可视化占满正文宽度，4:3 页面中的额外图注应简短。

## 源码解析契约

检查器对 TeX 字面量做词法分析，不逐行用正则搜索。它处理转义的百分号与花括号、嵌套的必选与可选参数、逐步显示参数、跨行调用、注释、行内 `\verb` / `\verb*` / `\lstinline`，以及 `verbatim`、`Verbatim`、`lstlisting`、`minted`、`comment` 环境。字面量帧和生成的账本帧只在同一演示稿的语言版本之间比较。逐步显示与备注可能产生额外 PDF 页，但不改变帧对齐规则。

引用与媒体 id 须直接以字面量写在该语言的源码中，各帧正文也放在同一文件。除 `\input{tbook-deck}` 外的源码导入、动态计算的 id、字符类别码修改与 `\csname` 均会被拒绝。不要定义用于构造引用、媒体命令或帧的别名与宏：任意 TeX 宏展开不属于静态检查契约。听众版与备注版使用同一源码，构建工具切换 `hide notes` / `show notes`；备注版交替显示报告帧与相应备注，听众版不含讲者备注。

## 引擎与可复现性

学术演示稿要求 **Tectonic 0.16.9**，它基于 XeTeX，支持 Unicode 与 Beamer。工具显式选择 `default_bundle_v33.tar` 资源包，不使用随时间变化的默认资源包；缓存位于仓库内，或使用工具链镜像中已预热的 `TECTONIC_CACHE_DIR`。除非明确覆盖，否则时间基准为 `SOURCE_DATE_EPOCH=946684800`；构建入口文件名固定，并启用 `-Z deterministic-mode`。Tectonic 仅下载所需 TeX 资源，中文版本使用资源包中的 `ctex` / Fandol 字体，其他文字可能需要在演示稿中声明字体。CI 无需安装完整的系统 TeX Live。

用 `TECTONIC=/path/to/tectonic` 指定可执行文件，构建工具拒绝其他版本。`tools/install-tectonic.sh DESTINATION` 把经过哈希校验的 Linux 发布二进制安装到显式指定的目录，支持 amd64/arm64。可选容器预热带版本的资源包，其离线冒烟测试会编译一帧 Beamer。托管运行器仅在包含学术稿配置的浏览器/媒体作业中把引擎安装到本地。默认运行器与现有必需检查保持不变。

按此配置，两次无缓存构建英文示例得到逐字节相同的听众版 PDF 与备注版 PDF。时间基准进入缓存键。自有主题字体、平台字体替换或外部资源可能影响输出；需要跨平台逐字节一致时，应避免依赖系统字体选择。Tectonic 按资源包索引校验下载内容，冷构建需要访问资源包服务器。缓存仅保存资源包内容，不保存生成的验证事实。

听众版与备注版分别写入 `build/slides/<book>/<deck>-<lang>.pdf` 和 `<deck>-<lang>-notes.pdf`，沿用现有的逐书幻灯片缓存，进入站点索引、章节链接与书籍 Release 附件。站点为每个学术稿语言版本发布一个简单的 PDF 入口页与两种下载文件。现有跳过 PDF 的开关只作用于 Slidev；学术演示稿始终构建两种 PDF。
