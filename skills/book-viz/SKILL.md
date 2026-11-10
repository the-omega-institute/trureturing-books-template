---
name: book-viz
description: 为书做交互可视化时使用：按 trureturing-visualize 与 books/example-monograph/viz/golden-carry/ 范式新建、编写、测试、登记并嵌入书内可视化（三栏网格、左栏步进器+滑块与 6+1+2 读数、中栏规则徽章+分步 HTML 账本 .drow+符号带 #tape+底部播放栏 footer.rail、右栏 1:1 二维相图 #heatPanel[data-thumb]+标准依据徽章 #evidence、?thumb=1 无文字左右分栏封面 drawCover()），或嵌入 trureturing-visualize 的现成页面。
---

# 交互可视化

## 适用范围

**用**：书中某一节需要可操作的对象（步进器、滑块、分步推演账本、二维相图、逐步动画）帮助理解；修改或排查已有可视化；把可视化嵌入章节。

**不用**：静态插图（放 `books/<slug>/assets/`，章节里写图片）；视频（`book-film`）；演示文稿（`book-slides`）。

**权威**：`books/example-monograph/viz/golden-carry/{index.html,style.css,main.js}`（唯一视觉与结构样板）、`templates/viz/README.md`（登记表字段与页面契约）、`tools/tbook/viz.py`。

## 原则

1. **可视化只改变看法，不证明任何东西。** 页面上能写 `LEAN ✓` 的只有锁文件中的 `theorem`（`.lean`）；页面上的数值计算标 `NUM`（`.lean.num`），示意模型标 `MODEL`（`.lean.model`），有纸面证明但未在本书形式化的文献结论标 `ARGUED`（`.lean.argued`），开放问题标 `OPEN`（`.lean.open`）。严禁自创 `.lean.interp`、`LIT`、`.lean-badge`、`.tier` 等非标类名。
2. **结构与元素对齐 `golden-carry`。** 每个书内可视化页面都采用 `books/example-monograph/viz/golden-carry/` 的三栏结构与元素体系（见下节“三栏结构与视觉元素规范”），不自创脱离示例框架的私有布局、顶栏主题切换按钮或额外运行时脚本。
3. **数字必须真实。** 页面上显示的每个数都由页面精确算出（或取自所钉提交），不编造“实验结果”。
4. **双语逐条成对。** 每段可见文字都写成 `<span class="zh">…</span><span class="en">…</span>`（`.zh` 与 `.en` 数量相等）；脚本文字用 `TRV.L('中文', 'English')`，并在 `TRV.onLang(…)` 中重绘。
5. **颜色只来自令牌**（`var(--cyan)` 等，脚本用 `TRV.palette` / `TRV.rgb`，不在 `style.css` 或 `main.js` 中硬编码 `#rrggbb`）。绿色只给 Lean 已验证；琥珀色只给“现在/当前选择”；红色标开放问题。
6. **只用相对链接**；Lean 与 trureturing 文件链接写成 `data-lean-gid` / `data-trureturing-path`，由构建固定到所钉提交。

## 三栏结构与视觉元素规范（对齐 `golden-carry`）

1. **入口与顶栏（`header.top`）**
   - 页面只加载 `../assets/theme.css`、`style.css`、`../assets/shell.js`（`<head>` 内）与底部的 `<script src="main.js"></script>`。
   - `<header class="top">` 含 `.brand`（`<a class="crumb" href="../">`、`<h1 class="logo" data-text="CODE//NAME">`、`.tagline`）与 `.status`（状态 `span.pill` 及 `<div class="langs">` 中英切换按钮 `data-lang-set="zh|en"`）。
2. **三栏 `.app` 网格（`style.css`）**
   - 桌面端：`grid-template-columns: minmax(270px, 310px) minmax(0, 1fr) minmax(320px, 400px)`，`grid-template-rows: auto minmax(0, 1fr)`；`1180px` 以下折为双栏，`760px` 以下及 `:root[data-embed]` 折为紧凑布局。直接沿用 `templates/viz/style.css`（与 `golden-carry/style.css` 一致）。
3. **左栏：输入与精炼读数（`<aside class="col deck">`）**
   - **`<section class="panel sec" id="inputs">`**：
     - 2–3 组 `.num-field`：顶部 `.row`（`<label>` + `.stepper` `−` / `<input type="number">` / `+`），下方 `<input type="range">` 滑块；
     - `<div class="chips presets" id="presets">`：预设按钮 + `Swap` / `Random` / `Reset` 动作按钮。
   - **`<section class="panel sec" id="readouts">`**：
     - `<dl class="ro">` 采用 **6 + 1 + 2** 精炼结构（避免十余行长列表）：6 个半宽 `<div><dt>…</dt><dd>…</dd></div>` 读数 + **1 个全宽主读数 `<div class="wide deficit">`**（`24px` 发光主值 `<b class="vpos|vneg|vzero">`、副说明 `<span class="sub">`、绿色校验勾 `<span class="okmark">✓</span>`）+ 2 个全宽 `.wide` 定理核验行；
     - 底部 `<p class="note" id="roNote">`。
4. **中栏：分步交互账本与底部播放栏（`<main class="center">`）**
   - **`<section class="panel ledger" id="ledgerPanel">`**：
     - `.head`：`<h2 id="ledgerTitle">` + `<span class="aside" id="ledgerSub">`；
     - `.rules`：4 枚 `.rule`（`.r0`、`.r1`、`.rj`、`.ra`）核心公式/改写规则徽章（`<b>符号</b> 条件 <i>效果</i>`）；
     - 可选几何舞台 `.stage`（含 `<canvas>`、`.scan`、四角 `.bracket.tl/.tr/.bl/.br`、`.hud-tl`、`.hud-tr.chips`）：画布内只绘制干净的几何图形，**不在 `<canvas>` 内手绘多框文字表格或产生文字重叠**；
     - **分步 HTML 账本 `.sheetwrap > .digits#ledger > .drow`**：用真实 HTML DOM 渲染表头 `.drow.hdr`、输入/初态行 `.drow.input`、逐轮推演行 `.drow.pass`（带 `[data-pass]` 点击跳步、当前步琥珀色发光 `.drow.now`、未来步半透明 `.drow.future`、触发格 `.touch`、右侧动作徽章 `<span class="what"><span class="sgn pos|neg|zero"><code><span class="name">`）与终态行 `.drow.final`；
     - **底部符号带 `.tape-row`**：`<span class="tape-label">` + `<div class="tape" id="tape">`（可点击 `<i class="pos|neg|zero now|future" data-pass="…">` 方块序列）+ `<span class="tape-sum" id="tapeSum">`；
     - `<div class="toast" id="toast">`。
   - **`<footer class="rail" id="rail">`**：
     - `.transport`：`#first`（`⏮`）、`#prev`（`◀`）、`#play`（`▶`）、`#next`（`▶▶`）、`#last`（`⏭`）；
     - `.clock`：`<span class="tau" id="passLabel">` + `<input type="range" id="pass">`；
     - `.keys`：键盘快捷键提示（`Space`、`←/→`、`Home/End`、`R`）。
5. **右栏：二维交互相图与依据面板（`<aside class="col side">`）**
   - **`<section class="panel sec heatpanel" id="heatPanel" data-thumb>`**：
     - `<h2 class="thumb-hide">…<span class="aside" id="heatRange">…</span></h2>`；
     - `<div class="heatwrap"><canvas id="heat"></canvas><div class="scan"></div></div>`：1:1 交互二维相图/参数热图/矩阵图，带琥珀色十字准星与当前选中格琥珀色发光框，支持点击/拖拽选点；
     - `<div class="chips thumb-hide" id="nChips">` 范围/维度切换按钮；
     - `<ul class="legend thumb-hide">` 四色图例（`.sw.pos`、`.sw.zero`、`.sw.neg`、`.sw.cur`）；
     - `<p class="note thumb-hide" id="heatCounts">` 与 `<p class="note thumb-hide" id="heatHover">`。
   - **`<section class="panel sec" id="evidence">`**：
     - `.lean`（含 `data-lean-gid`）、`.lean.num`、`.lean.model`、`.lean.argued`、`.lean.open` 依据框；
     - `<button class="chip" id="infoBtn">` 打开 `<div class="drawer" id="drawer" hidden><div class="sheet">…</div></div>` 理论接口。
6. **无文字左右分栏缩略图封面（`?thumb=1` `drawCover()`）**
   - 当 `TRV.thumbMode` 为真时，在 `canvas#heat`（`1280×720`）上绘制左右分栏缩略图（并注册 `window.TRV_THUMB = drawCover`）：左半幅（`ox = 64*u, side = 600*u`）为二维相图/矩阵 + 琥珀色十字准星与选中框；右半幅（`x0 = 760*u`）为账本行 `#1..#k` + 青/品红格 + 琥珀色发光末行边框；**不在缩略图上绘制自然语言标题或散文说明**。

## 流程

```bash
./tbook viz new <book> <id> "<CODE//NAME>" "<中文标题>" "<English title>"   # 从 templates/viz/ 生成三栏骨架与测试，登记为 draft
node tools/node/viz-server.mjs                       # http://127.0.0.1:8766/site/<book>/viz/<id>/（?embed=1、?thumb=1、?lang=en）
```

1. 在 `books/<book>/viz/<id>/` 中对照 `golden-carry` 编写 `index.html`、`style.css`、`main.js`。
2. 支持 `?embed=1`（书中 iframe，隐藏页眉）与 `?thumb=1`（缩略图，`[data-thumb]` 充满画面，`window.TRV_THUMB = drawCover`）；手机宽度 390px 无横向滚动；尊重 `prefers-reduced-motion`。
3. 完善登记表 `books/<book>/viz/visualizations.json`：`title_en`、`summary`/`summary_en`、`tags`/`tags_en`、至少一条 `theory`（本书章节写 `../zh/<chapter>.html`，trureturing 文件写 `{trureturing}/<path>`）、`lean`（GID 列表）。
4. 写浏览器测试 `books/<book>/viz/tests/<id>.test.mjs`（参照 `golden-carry.test.mjs`：交互、双语、无控制台错误、无横向滚动、关键数值与独立实现互证）。
5. 生成缩略图并转为发布状态：

   ```bash
   node tools/node/viz-test.mjs <book>
   node tools/node/viz-thumbs.mjs <book> <id>      # 1280×720 thumb.jpg，提交入库
   ```

   把登记表中的 `"status"` 改为 `"live"`（`draft` 不发布，也不能嵌入书中）。
6. 新引用了 GID 时运行 `./tbook pin --refresh`（它收集可视化引用的 GID），然后：

   ```bash
   node tools/node/viz-validate.mjs <book>
   ./tbook check
   ```

7. 嵌入章节——**所有语言版本都要加**，位置与 `src` 相同，只翻译图注：

   ```markdown
   ::: {.viz src="<id>" height="560"}
   图注（可含数学与 [@thm-…] 引用）。
   :::
   ```

   外部页面：`::: {.viz src="trureturing-visualize:<id>"}`。HTML 中为 iframe + “全屏打开”；PDF/EPUB 中为缩略图、图注与在线地址。
8. 构建并查看：`./tbook build html site --book <book> && ./tbook serve`，在中英文、深浅主题、手机宽度下各看一次；`./tbook build pdf --book <book>` 检查 PDF 中的缩略图面板。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `check` 报 draft 不能嵌入 | 完成第 5 步，把状态改为 `live` |
| `LEAN ✓` 链接 404 或 GID 未登记 | GID 不在锁文件中：`./tbook pin --refresh`；GID 必须是已冻结的声明 |
| “is a Lean def, not a theorem” | 登记表 `lean` 与页面 `data-lean-gid` 只能引用种类为 `theorem` 的声明（显示为 LEAN ✓）；定义写成 `data-trureturing-path="<module>.lean"` 或 `theory` 中的 `{trureturing}/<path>` |
| iframe 内显示完整页眉 | 页面没有处理 `?embed=1`（共享运行时会处理，确认引用了 `shell.js`） |
| 缩略图过期或含杂乱文字 | 在 `drawCover()` 中按 `golden-carry` 左右分栏绘制无字图形，重新运行 `viz-thumbs.mjs` |
| 手机宽度横向滚动 | 网格列用 `minmax(0, 1fr)`，长数字允许换行 |

## 完成标准

结构与元素对齐 `golden-carry`；`viz-validate`、`viz-test`、`./tbook check` 全部通过；登记表为 `live` 且有缩略图；各语言章节都已嵌入；在站点与 PDF 中实际看过。
