---
name: book-viz
description: 为书做交互可视化时使用：先定这张图要让读者看见什么，再按“舞台优先、每张实验卡都是可被正文引用的图”的方法设计、实现、看图、测试、登记，并在章节里按卡引用（::: {.viz src=… preset=…}）；也用于修改或排查已有可视化、嵌入 trureturing-visualize 的现成页面。
---

# 交互可视化

## 适用范围

**用**：书中某个想法需要读者亲手推一下才看得见（拖动、逐步、扫参数）；修改、排查或重做已有可视化；在章节里引用可视化。

**不用**：静态图（`book-figure`：脚本生成，`::: {.figure src=…}` 引用）；视频（`book-film`）；演示文稿（`book-slides`）。

**权威**：`templates/viz/`（起始模板，本身是一个能运行的舞台优先页面）与 `templates/viz/README.md`（登记表与页面契约）、`theme/viz/{theme.css,shell.js,kit.js}`（共享外观与运行时）、`tools/node/viz-testkit.mjs`（质量门）、`tools/tbook/viz.py`（校验与嵌入）。

**成品示例**：`books/example-monograph/viz/golden-carry/`。它按本文的方法从头做到尾：四个场景（进位、亏量图、相位正方形、收缩面的窗口）共用一条时间轴，十张实验卡，其中四张在 `books/example-monograph/{zh,en}/ch01-golden-deficit.md` 里按卡引用，章末是完整的实验室；测试 `viz/tests/golden-carry.test.mjs` 先过质量门，再用另写的独立算法核对页面的每条声称。起始模板、这个示例与下游书库的页面用的是同一套版式、同一个工具包、同一组质量门；不存在第二种做法。更多成品见 [trureturing-visualize](https://the-omega-institute.github.io/trureturing-visualize/)（下表“参照页面”）。

## 什么算好

读者正读到某一句话。五秒之内，他看见这句话在图上发生；三十秒之内，他亲手推了一下，发现那个量推不动。做不到这两点的页面，数字再全也没有用。

由此得到三条判断，每次动手前后都拿来对照：

1. **舞台就是页面。** 画对象本身（球、格点、矩阵、曲线、轨迹、筹码），画得大，让读者直接拖它。关于对象的数字表、读数墙不是主角。
2. **不变的东西要看得见。** 一个结论通常是“别的都在动，只有它不动”或“它出不了这个范围”。把那个量画成不动的线、推不过去的边界、永远剩下的一格。
3. **书里引用的是一张图，不是一台实验室。** 正文讲到哪个情形，旁边就该是那个情形的图。所以每张实验卡都要能被章节单独引用，并且在 PDF 里有自己的静态图。

## 方法（按顺序做）

### 0. 先读正文，写下一句话和几张卡

读完要配图的章节，在动手之前写出（放在 PR 说明里即可，不必另存文件）：

- **一句话**：读者看完能复述的结论，不带术语。它就是页面顶栏的 tagline。
- **3–8 张实验卡**：每张是一个有名字的情形，写清四件事：状态（参数取什么）、读者会看到什么、一句解释、正文哪一处会引用它。写不出“正文哪一处”的卡通常不该存在。
- **依据清单**：哪几条是锁文件里的定理（`LEAN ✓`），哪些是页面的数值（`NUM`）、示意模型（`MODEL`）、文献结果（`ARGUED`）、开放问题（`OPEN`）。

如果一个主题需要两个以上互不相同的对象，分成场景（同一页的几个舞台，共用一条时间轴），每个场景仍然回答同一个问题。

### 1. 选舞台，不选版式

版式服从内容：先问“这个结论的对象长什么样”，再决定画什么。常见的几种：

| 对象 | 舞台 | 参照页面 |
| --- | --- | --- |
| 方向、态、旋转 | 可拖动的球（`kit.stage3`） | trureturing-visualize：`zeno-watch`、`tomo-glance` |
| 整数、格点、逼近 | 格点平面加放大镜（`kit.plot` 的 `equal`） | `prime-gaps`、`robin-lattice` |
| 清单、表、矩阵 | 可点击的格子 | `perm-complement`、`hard-squares` |
| 随时间展开的过程 | 时空图或轨迹，时间轴驱动 | `chrono-slit`、`cat-ledger` |
| 逐步改写的记号串 | 画成筹码的行：一行一步，连线标出每一步把什么换成了什么 | 本模板的 `golden-carry`（场景“进位”） |
| 落在某个范围里的量 | 范围画成一条带，量画成带里的点 | `golden-carry`（场景“窗口”） |
| 被几条线分开的类别 | 一个点一个样本，线把颜色分开 | `golden-carry`（场景“相位”） |

逐步改写的过程也要画成图，不要排成表：把每一步写成一行文字、数字和规则名，读者看到的是一墙字，哪一步改了哪里要靠读；画成筹码和连线，一眼就看得见。表格留给读数面板。

“缝很小但永远不为零”这类结论，用放大镜：主图按真实比例画，旁边一个不断放大的窗口一直把那条缝放大到看得见。

一个页面的几个场景尽量画在同一个对象上（同一张格点、同一颗球）：读者换场景时不必重新认图，后一个场景的结论会落在前一个场景已经认识的点上。

二维舞台不必两轴等比。只依赖平行、共线与面积比的图（格点、窗口、带子、矩形）可以把要看的那一维拉开，让主角有足够的厚度；图里有圆、角度或正交时才必须加 `equal`。按真实比例画出来只剩一条细线的对象，换一个表示（例如把“细长平行四边形的面积”换成“双曲线下的矩形”），而不是放任它看不见。

### 2. 用共享的实验室版式

`<div class="app lab">`（`theme.css`）给出：左栏实验卡与控制、中间舞台（下面可有一条 `.strip` 小图）、右栏读数与依据、底部时间轴。它在窄屏和书内 iframe 里自动把舞台放到最前。在这个版式里：

- **舞台**占视口的三成以上（质量门会量）。舞台上只留图形、短标签（`st.tag`）、左上角一行标题一行说明（`.hud-tl`）和底边图例（`.hud-bl`）。标题与场景按钮同在一行，手机上只剩两百像素：标题写“场景 · 关键量”，解释放进下一行说明。
- **实验卡**（`.presets.cards` 里的 `button.preset[data-preset]`）：`.code` 是英文代号，`.cn` 是一句人话。点一张卡，舞台应当动起来（`kit.tween` 过渡），而不是硬切。
- **条带小图**回答“沿时间轴，什么在变、什么不变”。一到两张，每张一个问题，标题就是那个问题。面板标题与小图标题按大写排版，单个字母的变量写进去会变样（u、m、φ 变成 U、M、Φ）：标题用词，变量留给坐标轴与说明。
- **读数**不超过六项，外加一行放大的关键读数（`dl.ro .key`），用读者的话写标签（“线² + 面积²”，而不是变量名）。
- **依据**就近：紧挨着它所担保的读数放一个 `LEAN ✓` 框，其余放在依据面板和理论抽屉里。
- **时间轴**（`footer.rail` + `kit.clock`）只驱动一个量：步数、角度、时间。

### 3. 每张卡都是可引用的图

- 页面用 `cards.pick(cards.initial('<默认卡>'))` 开场：章节用 `preset` 指定了卡时就开在那张卡上。
- 每张卡在数据里写三样东西：起始状态、是否播放（`play`）、静态图该停在哪一帧（`still`）。约定：`TRV.still`（封面与静态图）和整页打开时停在 `still`；书内的图用 `kit.autoplay` 在读者滚到它时才播放；读者点卡则立即播放。
- 卡片说明只说图里看得见的东西。被引用的图只显示舞台、说明条和时间轴，条带小图和读数栏不在场。
- 章节里这样引用，各语言版本都要加，位置、`src` 与 `preset` 相同：

  ```markdown
  ::: {.viz src="<id>" preset="<卡>" height="500"}
  **一句标题。** 图注用与图例相同的颜色词和符号（“青色的线”“品红的面积”），并指向定理（[@thm-…]）。
  :::
  ```

  引用块顶格写在两个段落之间；缩进在列表项里面的 `:::` 不被识别。媒体块不连排：实验卡、完整实验室、视频与静态图之间要有正文，三块以上只隔着空行挨在一起时 `./tbook check` 从第三块起给出警告；完整实验室与紧随的视频之间也隔一段正文。要紧跟某一条列表项时，放在这一条之后、下一条之前，有序列表的编号会接着排。

  HTML 中它是不带内部滚动的一张图（舞台、一句说明、◀ ▶、时间轴）；“全屏打开”进入同一状态的完整实验室。PDF/EPUB 中它是那张卡的带标签静态图（`fig-<卡>.<语言>.jpg`）。不带 `preset` 的嵌入是完整实验室，通常每个可视化在章末放一处。

### 4. 诚实标注

- `LEAN ✓`（`.lean`，绿色）只给锁文件里种类为 `theorem` 的声明，链接写 `data-lean-gid`。陈述与 Lean 一致，不夸大。
- 页面算出的数标 `NUM`（`.lean.num`）；为画面选定的模型与本书的诠释标 `MODEL`（`.lean.model`）；有纸面证明但未在本书形式化的结论标 `ARGUED`（`.lean.argued`），正文写明“文献结果，未在本书形式化”；开放问题标 `OPEN`（`.lean.open`）。不自创别的类名。
- 页面上的每个数都是真算出来的。几个事实并排展示时，说明它们是不同的事实，页面不声称其中一个推出另一个。
- 页面只为自己算出的数负责。章节转述的新近文献（预印本、尚无定论的结果）在页面上只作为该章的转述出现，为它画的曲线标 `MODEL`，不替它背书；正文里的修辞（“永远无法”“必然”）进入页面之前先核对它在所画的例子里是否成立，不成立就只写图里成立的那一半。
- 绿色只给 Lean 已验证；琥珀色只给“现在/当前选择”；颜色只来自令牌（`var(--cyan)`、`TRV.palette`），不写十六进制色值。
- 所有可见文字中英成对（静态 `.zh`/`.en`，脚本用 `TRV.L` 并在语言切换时重绘，`kit.painter` 已代办）。

### 5. 看图

测试分不清清楚的图和杂乱的图，必须亲眼看。每做完一轮：

```bash
node tools/node/viz-shots.mjs <book> <id>                 # 桌面、书内、手机、封面，中英各一，写到 build/viz-shots/
node tools/node/viz-shots.mjs <book> <id> --views desk --do "document.querySelector('[data-preset=x]').click()" --name x
```

打开每一张，逐条问：

- 不读任何文字，能看出主角是什么吗？舞台够大吗？
- 琥珀色是不是只标着“现在”？两种对比色各自只表示一样东西吗？
- 标签有没有压在一起、压在线上、被控件挡住？
- 书内那张（740 宽）第一屏是不是舞台加一句说明？
- 英文版有没有残留中文、有没有换行把标题挤成三行？
- 封面缩成卡片大小还认得出吗？细线和小点缩小后会消失：`kit.stage3` 在封面里自动加粗，用 `kit.plot` 画的二维舞台要自己在 `TRV.thumbMode` 时把线宽与点放大约两倍、把视野收窄。

和参照页面并排比一比。不如它们清楚，就回到第 1 步，而不是加更多读数。

### 6. 测试

`books/<book>/viz/tests/<id>.test.mjs`：

```js
import { session, stageFirstChecks, settle } from '../../../../tools/node/viz-testkit.mjs';
const T = await session();
await stageFirstChecks(T, '<book>', '<id>');     // 所有舞台优先页面都要过的质量门
// 然后是这个页面自己的检查
```

- `stageFirstChecks` 检查：舞台占比、每张卡能点且有说明、标签不重叠、抽屉、点卡之后空格键控制播放、如实标注（每条 Lean 链接都是锁文件里的定理并指向所钉提交的文件与行；登记表列出的定理与页面引用的一致；绿色框恰好是引用 Lean 定理的框；抽屉用两种语言写明“不是证明”）、英文无残留中文、书内第一屏、被引用的图不滚动、静态图、手机无横向滚动、封面非空白、减少动效。
- 页面自己的检查：每个控件一条；页面声称的每条性质一条，**用测试里另写的独立算法核对**（另一种表示、暴力枚举、数值积分），不调用页面自己的函数。页面通过只读探针 `window.<NAME>_DEBUG` 暴露状态。
- 读状态前调用 `settle(page)`：无头浏览器每秒只渲染几帧，不要靠等待碰运气。它先把进行中的过渡（`kit.tween`、相机的 `st.view`）走完，再重绘：点完一张卡 `settle` 一下就能读到终态，不要为过渡等一个固定的毫秒数。过渡只在动画帧上前进，机器一忙，结束它的那一帧可能比标称时长晚得多。
- 播放不是过渡，`settle` 不替时钟往前走。检查“空格开始播放”“这张卡会自己播”时，等页面自己报告动了：`check('Space plays', await until(page, () => window.<NAME>_DEBUG.state.t > 0))`。`until` 由 `viz-testkit.mjs` 导出，条件一成立就返回 `true`，30 秒仍不成立返回 `false`，本身就是这条检查的结果。不要写“按空格、等 700 毫秒、再读 t”：播放靠动画帧推进，机器一忙，700 毫秒里可能一帧都没到，页面没错，检查却失败。
- 不写 `page.waitForTimeout(…)`：`viz-validate`（与 `./tbook check`）对测试里的每一处固定等待报警告，并给出行号与改法。
- 交付前加上 `VIZ_SLOW_FRAMES=1000` 再跑一遍测试（`VIZ_SLOW_FRAMES=1000 node books/<book>/viz/tests/<id>.test.mjs`，或整本书 `node tools/node/viz-test.mjs <book> --slow`）：它把动画帧拉开到一秒一帧，比 CI 最忙时还慢，耗时与平时几乎相同。为过渡或播放等固定时间而碰巧通过的检查在这里必然失败；间隔取得比测试里最长的固定等待短，就可能照不出来。CI 每周（与手动触发时）用 `--slow` 把全部测试跑一遍（`ci.yml` 的 `viz-slow`，`docs/PUBLISHING.md` §4），PR 不等它。
- 键盘：用指针点了实验卡、场景按钮或导览条之后，`kit` 把焦点交给舞台，空格直接播放或暂停；用 Tab 走到按钮上的读者，空格与回车仍按下那个按钮。测试里点完卡就按空格，读到的是时钟的翻转；要测按钮本身对空格的响应，先 `page.focus(…)` 或用 Tab 走到它。
- 用随机抽样做独立核对时，容差要对得上抽样的精度。落在尖点上的极值（多面体的面、绝对值之和）靠均匀抽样收敛很慢：先抽样，再在最好的点附近逐步收窄搜索。
- 每提交一次输入（`fill` 加回车、点一次步进键或一张卡）也先 `settle(page)`，再去动下一个控件：页面在下一帧按状态重写全部输入框，上一次提交排定的那一帧若落在“第二个框已填、回车未按”之间，刚填的值被覆盖，第二次提交不会发生。本地机器快，几乎不触发；CI 上表现为同一条断言偶发失败、重跑又通过。

### 7. 登记、出图、检查

```bash
./tbook viz new <book> <id> "<CODE//NAME>" "<中文标题>" "<English title>"   # 从起始模板生成，登记为 draft
node tools/node/viz-server.mjs                       # http://127.0.0.1:8766/site/<book>/viz/<id>/（?lang=en、?embed=1、?preset=…）
node tools/node/viz-test.mjs <book>
node tools/node/viz-thumbs.mjs <book> <id>           # 封面 thumb.jpg，以及章节引用到的每张卡的 fig-<卡>.<语言>.jpg；提交入库
node tools/node/viz-validate.mjs <book> && ./tbook check
./tbook build html site --book <book> && ./tbook serve
```

完善 `books/<book>/viz/visualizations.json`（`title_en`、`summary`/`summary_en`、`tags`/`tags_en`、`theory`、`lean`），把 `status` 改为 `live`；新引用了 GID 时先 `./tbook pin --refresh`。改了卡片或图注之后重新运行 `viz-thumbs.mjs`：`./tbook check` 会核对被引用的卡存在、各语言版本引用一致、静态图齐全。

## kit 速查（`theme/viz/kit.js`，在 `<head>` 里排在 `shell.js` 之后）

| 用途 | 调用 |
| --- | --- |
| 重绘 | `const paint = kit.painter(draw, [要监听尺寸的元素])`；`paint()` 请求一帧，`kit.flush()` 走完进行中的过渡并立即重绘（测试用） |
| 三维舞台（二维画布上） | `const st = kit.stage3(el, { canvas, onChange: paint, onPick, onDrag })`；每帧 `st.begin()` … `st.sphere()`、`st.arc(u, v)`、`st.arrow(a, b)`、`st.path(pts)`、`st.poly(pts)`、`st.dot(p)`、`st.circle(c, n, r)`、`st.tag(key, p, html, cls)` … `st.end()`；`st.pick(ev)` 取指针下的球面点，`st.view('iso' \| 'front' \| 'top')` |
| 二维舞台与小图 | `const g = kit.plot(canvas, { x, y, pad, equal, logY })`；`g.axes()`、`g.line()`、`g.area()`、`g.rect()`、`g.poly()`、`g.dot()`、`g.vline()`、`g.hline()`、`g.text()`、`g.legend()`；`g.invX/invY` 把指针换回数据坐标 |
| 同一页既有二维又有三维场景 | 共用一块画布和一个 `kit.stage3`：二维场景里先 `st.begin(); st.end();` 再 `kit.plot(canvas, …)`；`onPick` 在二维场景返回 `true` 接管拖动（否则拖动会悄悄转动相机），并随场景切换舞台的 `still` 类 |
| 时间轴 | `kit.clock({ range, play, label, speeds, max, rate, step, format, onChange })` → `set`、`setMax`、`play`、`pause`、`stepBy`；键盘 Space / ← → / Home / End 已绑定（用指针点过卡或 `kit.chips` 的按钮后焦点在舞台上，空格即播放）。`format(t, max)` 在构造时就被调用一次：只用这两个参数与页面状态，不引用时钟变量本身 |
| 实验卡与导览条 | `kit.cards(el, { notes, noteEl, tour, idle, onPick })` → `pick`、`mark(null)`（读者动了控件）、`initial(默认卡)`、`step(±1)` |
| 进入视野才播放 | `kit.autoplay(clock, stageEl)` |
| 过渡 | `kit.tween(ms, step, done)`（尊重 `prefers-reduced-motion`） |
| 其余 | `kit.chips`（互斥按钮组）、`kit.field`（滑块与读数）、`kit.keys`（快捷键）、`kit.v3`（向量、`rot`、`slerp`、`sph`）、`kit.fix` / `kit.sgn`（不出现 `-0.00` 的数字） |

运行时状态（`shell.js`）：`TRV.embed`（书内）、`TRV.preset`（被引用的卡）、`TRV.figure`（书内且被引用）、`TRV.thumbMode`（无字封面）、`TRV.shot`（带标签静态图）、`TRV.still`（后两者之一：不播放，直接显示关键帧）。

## 反模式

| 现象 | 为什么不行 | 改法 |
| --- | --- | --- |
| 所有页面同一副骨架，舞台只有一小块 | 版式先于内容，读者看到的是数字墙 | 回到第 1 步，按对象选舞台 |
| 读数十几行，全是符号 | 读者不知道看哪一行 | 留一行关键读数，其余进抽屉 |
| 画布里手绘表格或大段文字 | 不能缩放、不能翻译、会重叠 | 画布只画图形；文字用 `st.tag` 或 DOM |
| 卡片说明提到图里没有的东西 | 被引用时条带小图和读数栏不在场 | 说明只说舞台上看得见的 |
| 一进页面就自动播放，或在视野外播完 | 读者错过了演示 | `kit.autoplay`；整页打开停在关键帧 |
| 章末一台大实验室，正文没有图 | 读到那句话时图不在旁边 | 在那句话旁按卡引用 |
| 两三张卡、完整实验室和视频摞在一起 | 读者分不清哪张对应哪句话（`check` 警告 `media blocks in a row`） | 每张卡挪到它对应的那句话之后，块与块之间有正文 |
| 为“看起来丰富”加第三张小图、第四个场景 | 每多一样东西，主角就淡一分 | 删到每样东西都回答一个问题 |
| 用 `sleep` 等渲染、等过渡或等播放的测试 | 无头环境帧率低，时过时不过 | 过渡用 `settle(page)`，播放用 `until(page, …)`；用 `VIZ_SLOW_FRAMES=1000` 复查 |

## 嵌入 trureturing-visualize 的现成页面

`::: {.viz src="trureturing-visualize:<id>" height="560"}`。HTML 中是指向该站点的 iframe，PDF/EPUB 中是文字卡片与地址。外部页面不在本仓库，`preset` 只检查写法，不出静态图；需要按卡引用和纸面静态图时，把它做成本书的可视化。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `check` 报 draft 不能嵌入 | 完成登记表与测试，把状态改为 `live` |
| `no experiment card data-preset="…"` | 章节引用的卡在页面里不存在；核对卡名，各语言版本一致 |
| `the still of card "…" for <lang> is missing` | 运行 `node tools/node/viz-thumbs.mjs <book> <id>` 并提交生成的 `fig-*.jpg` |
| 静态图没有停在想要的画面 | 给那张卡写 `still`，并在 `TRV.still` 时跳到它 |
| `LEAN ✓` 链接 404 或 GID 未登记 | `./tbook pin --refresh`；GID 必须是已冻结的 `theorem`，定义写成 `data-trureturing-path` |
| 手机宽度横向滚动 | 网格列用 `minmax(0, 1fr)`，长数字允许换行 |
| 手机上舞台标题被场景按钮压住 | 标题太长；只写“场景 · 关键量” |
| 标题里的 φ、u 变成了 Φ、U | 标题按大写排版；变量不写进标题 |
| `Cannot access '…' before initialization`，页面一片空白 | `kit.clock` 的 `format` 在构造时被调用，里面引用了尚未赋值的时钟变量 |
| 书里的图内部出现滚动条 | 被引用的图（带 `preset`）不应滚动；检查是否有固定高度的元素撑破了舞台 |
| 测试本地通过，CI 上偶尔有几条失败 | 多半是为过渡或播放等了固定时间；用 `node tools/node/viz-test.mjs <book> --slow`（即 `VIZ_SLOW_FRAMES=1000`）在本地复现，过渡改成 `settle(page)`，播放改成 `until(page, …)` 等状态本身 |
| `viz-validate` 警告 `waitForTimeout(…) at line N waits a fixed time` | 测试第 N 行等了固定时间：点卡或过渡之后改成 `await settle(page)`，等播放改成 `check(…, await until(page, () => …))`；改完用 `--slow` 跑一遍 |
| 点过一张卡后按空格，卡又重放了一遍，没有暂停 | 页面没有用 `kit.cards` / `kit.chips` 处理点击（自己写了 `click` 监听）：改用它们，或在自己的指针点击处理里把焦点交给 `.stage`；`stageFirstChecks` 的 `keyboard: after a card is clicked, Space plays and pauses the clock` 会抓到 |
| 页面的空格不控制时钟（`kit.clock({ keys: false })`），这条键盘检查失败 | 页面另有空格的用法时，传 `stageFirstChecks(T, book, id, { keys: false })` 跳过它，并在页面自己的测试里检查那个用法 |

## 完成标准

一句话与每张卡都能在正文里找到对应的句子；看过全部截图并与参照页面比过；`stageFirstChecks` 与页面自己的检查全部通过；`viz-validate`、`./tbook check` 通过；登记表为 `live`，封面与被引用卡的静态图已提交；各语言章节的引用一致；在站点与 PDF 中实际看过。

当前版本来自 `trureturing.lock.json`，不复制 SHA 到源码。正文与审计表用 `docs/AUTHORING.md` 的保留链接标签；幻灯片用 `<PinnedCommit />`（复用主题的 `pinned`）；可视化锚点用 `data-lean-gid` / `data-trureturing-path` 和 `href="#"`，由构建与本地预览解析。动态声明数据可从 `../assets/trureturing.json` 取得（构建生成、本地预览从锁读取；不提交该文件）。真实历史版本仍按历史事实保留。钉版后复核摘要变化与媒体陈述，再重建；纯提交或行号变化不要求改正文或媒体源码。
