---
name: book-export
description: 构建或排查书的导出产物时使用：mdBook HTML、Typst PDF（屏幕版/印刷版）、Apple Books 兼容的 EPUB 3，以及书库站点；包括字体、数学、封面、epubcheck 与 Apple Books 显示问题。
---

# 导出 HTML、PDF、EPUB

## 适用范围

**用**：本地构建、检查导出效果、CI 构建失败、PDF/EPUB 排版或字体问题、Apple Books 显示问题。

**权威**：`docs/PDF-TYPOGRAPHY.md`（学术预印本排印与 arXiv PDF 要求）、`docs/PUBLISHING.md`、`docs/ARCHITECTURE.md` §5–§8、`./tbook doctor` 的输出。

## 命令

```bash
./tbook doctor                               # 工具链体检（缺什么、怎么装）
./tbook build html --book <slug> [--lang zh] # mdBook → build/html/<slug>/<lang>/
./tbook build pdf  --book <slug> [--variant screen|print|academic]
./tbook build epub --book <slug>
./tbook build all                            # 全部书、全部产物，并组装 _site/
./tbook serve                                # 在 Pages 子路径下本地预览 _site/
```

`--book` 与 `--lang` 都可重复；所选的书都没有 `--lang` 指定的语言版本时，构建报错退出，不会静默跳过。

下载文件在 `build/dist/<slug>/`：`<slug>-<version>-<lang>-screen.pdf`、`…-print.pdf`、可选的 `…-academic.pdf`、`<slug>-<version>-<lang>.epub`。

## 三种产物

| 产物 | 链路 | 说明 |
| --- | --- | --- |
| HTML | 章节 → `render`（mdbook target）→ KaTeX 预渲染 → mdBook 0.5.4 | 深色霓虹为默认主题，浅色主题切换为“纸面”配色；菜单栏有语言切换 |
| PDF screen | 章节 → `render`（pandoc target）→ Pandoc → Typst | 深色整页、霓虹强调色，适合屏幕阅读 |
| PDF print | 同上，`tr-paper` 配色 | 白纸黑字，深化的强调色，适合打印 |
| PDF academic | 同上，`tr-paper` 配色与预印本版式 | A4 单栏、11 pt 衬线正文、题名与摘要同页、连续页码、章部随文、传统定理与证明；在 `[outputs] pdf` 中加 `"academic"` 启用 |
| EPUB | Pandoc EPUB 3，MathML，封面 PNG | 适配 Apple Books 的白/米/灰/夜间主题；`epubcheck` 0 错误 |

## 排错清单

1. **先跑 `./tbook check`。** 导出不修内容错误；未解析的引用会渲染成 `[@id?]`。
2. **字体**：PDF 用 Typst，只认 TTF/OTF。中文需要 Noto Serif/Sans CJK SC（CI 装 `fonts-noto-cjk`）；标题字体 Chakra Petch 与 JetBrains Mono 由 `tools/fetch-fonts.sh` 拉到 `.cache/fonts/`。缺字体时会回退，但字形会变——`./tbook doctor` 会提示。
3. **数学**：标题使用 `$…$`；章节标题、SUMMARY 链接标题与部分标题、菜单栏书名由构建工具预渲染，侧栏的 JS 与无 JS 目录都支持公式，浏览器标签和搜索索引用可见文字。不要手改暂存 SUMMARY 或在浏览器另加 MathJax。HTML 端 KaTeX 渲染失败的公式显示为代码并在构建日志中警告；PDF 端是 Pandoc 的 TeX→Typst 转换，复杂环境（`aligned`、`cases`）若出错，先在小文件中用 `pandoc -t typst` 复现。EPUB 端是 MathML。标题含公式时，PDF/EPUB 构建也调用 Node（KaTeX）算出与 HTML 相同的标题 id；日志出现“ids of headings with math follow their TeX”时先 `npm ci`，否则指向这类标题的链接会变成纯文字。
4. **EPUB 校验**：构建后运行 epubcheck；Apple Books 对 XHTML 很严格，任何原始 HTML 都必须是合法 XHTML。
5. **Apple Books 显示**：不要在 CSS 中强制页面背景色；夜间主题由 `prefers-color-scheme: dark` 和 Apple 的主题选择器切换霓虹配色。用 Books（macOS/iOS）打开实测一次。
6. **图片**：放在 `books/<slug>/assets/`，章节中写 `../assets/x.svg`；构建会复制进 `_book/`。PDF 支持 SVG/PNG/JPG。
7. **mdBook**：版本须为 0.5.4（`MDBOOK` 环境变量或 PATH）。0.4.x 的预处理协议不同。
8. **PDF 重叠与越界**：检查书中启用的全部 PDF 变体及语言；启用 academic 时按 `PDF-TYPOGRAPHY.md` 检查中英文预印本首页、连续页码与无框定理，尤其是窄表格中的 Lean 标识符、公式及长章名页眉。模板会让表格内代码换行，并把超宽公式缩至当前单元格、列表或定理框宽度；缩得过小的公式应在正文用 `aligned` 显式分行，源码换行本身不会产生公式换行。宽审计表可用 Pandoc 的管道表格列宽：分隔行总宽超过 72 字符时，各列横线数量决定 PDF 列宽比例，把更多空间留给精确契约。实际渲染问题页，确认内容完整可读后再交付，不能只检查编译是否成功。
9. **PDF 里印出了源码或颜色值**：`pdftotext <pdf> - | grep -n 'rgb(\|\\[a-zA-Z]\{2,\}\|\$\$\|#box\|class("'`（poppler-utils）扫一遍所有启用的 PDF，正常结果是没有命中（书里贴的代码清单除外）。两种来源：(a) 公式里有 Pandoc 不认识的命令（`\over`、`\genfrac`、未登记的宏），整条公式连同 `$` 原样印出，构建日志里有 `Could not convert TeX math`，换一种写法或把宏登记进 `TEX_MACROS`；(b) 主题 `theme/typst/book.typ` 新定义的名字与 Typst 数学函数重名（主题是整体导入文档的，`accent`、`mono` 都出过事），公式里印出主题变量的值，`tools/tests/test_pdf_math.py` 的重名检查会拦住，改主题里的名字。
10. **PDF 里公式的间距、大小或结构与 HTML 不同**（符号相叠、多出或缺少空格、上下标位置不对、分式层次不对、矩阵散开）：这是 TeX→Typst 转换的问题，不改正文。按第 12 条取得这条公式的 Typst 代码，对照 `tools/filters/typst-compat.lua` 文件头列出的七类差异找到缺的那条规则，补上并在 `tools/tests/test_pdf_math.py` 加用例。这类问题不会让构建失败，文字扫描也发现不了，只能渲染页面与 HTML 并排看。
11. **epubcheck 报 RSC-005 `maxsize`/`minsize`/`stretchy` not allowed**：定尺寸命令套在了括号以外的符号上（典型是 `a\big/b`），MathML 里成了带尺寸属性的 `<mi>`。报错给出 `chNNN.xhtml`，到对应章节搜 `\big/`、`\Big/`，改成 `\frac` 或普通的 `/`。
12. **最小复现**：把出问题的公式单独送过真实的转换链，比读整本书的中间文件快。PDF 端：`PYTHONPATH=tools:tools/tests python3 -c "from test_pdf_math import typst_code; print(typst_code([r'\exp\!\left(x\right)'])[0])"` 打印这条公式最终写进 PDF 的 Typst 代码（已展开预设宏、经过 Lua 过滤器）；`typst_code([...], display=True)` 对应独立公式。EPUB 端：`printf '%s\n' '$a\big/b$' | pandoc -f markdown -t html --mathml`（没有全局 `pandoc` 时用 `python3 -c "import pypandoc; print(pypandoc.get_pandoc_path())"` 给出的路径；预设宏要写展开后的形式，见 `tools/tbook/mathrender.py` 的 `TEX_MACROS`）。要看排出来的样子，把 Typst 代码写进 `t.typ` 后用 `python3 -c "import typst; typst.compile('t.typ', output='t.png', format='png', ppi=170)"` 渲染成图；主题相关的问题要像 `test_pdf_math.py` 那样在暂存目录里连主题一起编译。
13. **越界扫描**：`pdftotext -bbox <pdf> out.html` 给出每个词的坐标。正文各行 `xMax` 的众数就是版心右缘；`xMax` 明显超过它的词即越界（封面的彩色叠印除外）。它只能发现文字越界，发现不了第 10 条那类重叠。

14. **预印本投稿检查**：按 `docs/PDF-TYPOGRAPHY.md` 核对字体嵌入、占位字体（尤其 LastResort）、组合标记、文本检索与完整图件；不能只以“提取文本没有乱码”判定图中不缺字。确认 PDF 小于 50,000,000 字节，或在真实投稿后申请超限例外。默认 academic 省略可选结构标签，需结构标签时设 `[pdf] academic_tags = true` 并重新核对体积。

## 完成标准

目标产物在 `build/` 下生成；HTML 无原始 `$`；每个定理都有 `LEAN ✓` 徽章与指向所钉提交的 Lean 链接；PDF 首页、目录、定理与账本符合对应变体规范；academic 的字体嵌入、文本检索与活动内容检查通过，文字扫描无源码泄漏、无越界，改动过的公式所在页面已渲染查看；EPUB epubcheck 无错误。
