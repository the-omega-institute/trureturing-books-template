# 可视化起始模板 · Visualization starter

`./tbook viz new <book> <id> "<CODE//NAME>" "<中文标题>" "<English title>"`（或 `node tools/node/viz-new.mjs …`）从本目录生成
`books/<book>/viz/<id>/{index.html,style.css,main.js}` 与 `books/<book>/viz/tests/<id>.test.mjs`，并在注册表里登记为 `draft`。
本 README 不会被复制。运行时与页面契约沿用 [trureturing-visualize](https://github.com/the-omega-institute/trureturing-visualize)：
纯 HTML/CSS/JS，无构建步骤，只用相对链接；共享运行时在 `theme/viz/`（发布为 `<slug>/viz/assets/`）。怎样设计一个好的页面，见 `skills/book-viz/SKILL.md`。

`./tbook viz new …` scaffolds a working stage-first page from this directory and registers it as a draft: plain HTML/CSS/JS, no build step, relative links only; the shared runtime lives in `theme/viz/` and is published as `<slug>/viz/assets/`. For how to design a good page, read `skills/book-viz/SKILL.md`.

## 起始页面 · The starter

生成的页面可以直接运行并通过它自带的测试：一个单位圆上的点、它的影子与高度。把主题换成你的，保留它的形状：

- **舞台就是页面**：`<div class="app lab">` 的中间一栏是 `.stage`，画对象本身，读者直接拖它；下面的 `.strip` 小图回答“沿时间轴什么在变”。
- **实验卡**：`.presets.cards > button.preset[data-preset]`，每张是一个有名字的情形加一句解释。章节可以按卡引用（见下）。
- **导览条**：`.tour`，在书内和手机上让读者不离开舞台就能逐张看卡。
- **读数与依据**：右栏少量读数（一行 `.key` 放大）与依据框；`#infoBtn` 打开理论接口抽屉。
- **时间轴**：`footer.rail`，只驱动一个量。

The generated page runs as it is and passes its own test: a point on the unit circle, its shadow and its height. Replace the subject and keep the shape: the stage is the page; experiment cards are named situations a chapter can cite; the tour bar steps through them next to the stage; few readouts with the evidence close by; one rail driving one quantity.

完整的成品示例是 `books/example-monograph/viz/golden-carry/`：同一套版式与工具包，四个场景共用一条时间轴，十张实验卡，四张在第一章按卡引用，测试先过质量门再用独立算法核对。起始页面是它的最小形态。

The finished example is `books/example-monograph/viz/golden-carry/`: the same layout and kit, four scenes on one rail, ten experiment cards, four of them cited from chapter 1, and a suite that runs the quality gates and then checks every claim independently. The starter is its smallest form.

## 实体舞台 · Lit solids

对象本身是面或体、画成受光的实体确实更清楚时（带、环面、多面体、可行域、球里有东西的布洛赫球），在舞台上调用 `TRV.kit.solid(stage, { canvas, onChange: paint, … })`；它不是统一风格，曲线、格点、矩阵、记号串照旧。页面不多加载任何脚本：`kit.js` 在第一次调用时才取造型核心 `assets/solid-core.js` 与它导入的、`assets/vendor/` 里钉版的 three.js，所以页面契约不变（两者都是运行时自己的文件，`vendor/` 不做语法检查）。用法、取舍与测试（`stageFirstChecks(…, { solid: true })`）见 `skills/book-viz/SKILL.md` 的“具象”一节；成品示例是 `books/example-monograph/viz/phase-torus/`。

When the object itself is a surface or a body and a lit solid makes it clearer, call `TRV.kit.solid(stage, { canvas, onChange: paint, … })` on the stage; it is one more option, not a house style. The page loads no extra script: `kit.js` fetches the modelling core `assets/solid-core.js`, and with it the pinned three.js from `assets/vendor/`, on the first call, so the page contract is unchanged. See the section on solids in `skills/book-viz/SKILL.md`; the finished example is `books/example-monograph/viz/phase-torus/`.

## 注册表 · Registry (`books/<book>/viz/visualizations.json`)

```json
{
  "version": 1,
  "visualizations": [
    {
      "id": "golden-carry",
      "code": "GOLDEN//CARRY",
      "title": "黄金进位 · …", "title_en": "Golden carry · …",
      "summary": "…", "summary_en": "…",
      "path": "golden-carry/", "thumbnail": "golden-carry/thumb.jpg",
      "status": "live",
      "added": "2026-11-08",
      "tags": ["进位"], "tags_en": ["carries"],
      "theory": [
        { "label": "本书第一章", "label_en": "Chapter 1", "href": "../zh/ch01-golden-deficit.html", "href_en": "../en/ch01-golden-deficit.html" },
        { "label": "Blueprint", "label_en": "Blueprint", "href": "{trureturing}/Blueprint/D5/S1/Deficit/DeficitThreeValued.md" }
      ],
      "lean": [ { "gid": "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued" } ]
    }
  ]
}
```

| 字段 field | 规则 rule |
| --- | --- |
| `id` | kebab-case，等于目录名；不能是 `tests`、`assets` |
| `path` / `thumbnail` | 相对 `viz/`：`<id>/` 与 `<id>/thumb.jpg`（1280×720 无字封面，`node tools/node/viz-thumbs.mjs <book> <id>`；同一命令为章节引用到的每张卡生成 `<id>/fig-<卡>.<语言>.jpg`） |
| `status` | `draft`（不发布，不可嵌入书中）或 `live`（需要 `title_en`、`summary`、`summary_en`、至少一条 `theory`、缩略图；应有浏览器测试） |
| `tags_en` | 逐条翻译 `tags` |
| `theory[].href` | `https://…`；`{trureturing}/<path>`（所钉提交上的该文件，必须存在）；或本书章节，相对 `viz/`：`../zh/<chapter>.html`；`href_en` 可选 |
| `lean[].gid` | 本可视化引用的定理（显示为绿色 LEAN ✓）：必须在 `trureturing.lock.json` 中且种类为 `theorem`（写好后运行 `./tbook pin --refresh`，它也收集可视化引用的 GID）；链接由构建固定到所钉提交；`label` 可选 |

## 页面契约 · Page contract (checked by `./tbook check` and `node tools/node/viz-validate.mjs`)

- `<body data-viz-id="<id>">`；`<html data-title-en="…">` 与 `<title>`。
- `<link rel="stylesheet" href="../assets/theme.css">`；`<head>` 内 `<script src="../assets/shell.js"></script>`（`window.TRV`），其后可加 `<script src="../assets/kit.js"></script>`（`TRV.kit`：舞台、小图、时间轴、实验卡等辅助，见 skill 的速查表）。
- 页面自己的脚本是底部的 `main.js`；与视频共用造型时，可在它之前加载同目录的 `model.js`（经典脚本，见 `skills/book-viz` 的“具象”）。
- `<a class="crumb" href="../">` 返回本书的可视化索引；语言切换 `data-lang-set="zh"` / `data-lang-set="en"`。
- 所有可见文字成对：`<span class="zh">…</span><span class="en">…</span>`；脚本文字用 `TRV.L('中文', 'English')` 并在语言切换时重绘（`kit.painter` 已代办）；`aria-label` 写中文、`data-aria-en` 写英文。
- Lean 定理引用写成 `<a data-lean-gid="<GID>" href="…">`（GID 须是锁文件中种类为 `theorem` 的声明）；定义等其他 trureturing 文件写成 `<a data-trureturing-path="<path>" href="…">`：构建与本地预览把 href 固定到所钉提交。依据框：

  ```html
  <div class="lean"><span class="ok">LEAN ✓</span><span><span class="zh">陈述，与 Lean 一致。已冻结：</span><span class="en">The statement, as in Lean. Frozen: </span><a class="leanref" data-lean-gid="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued" href="https://github.com/the-omega-institute/trureturing/blob/dev/D5/S1/Deficit/DeficitThreeValued.lean" target="_blank" rel="noopener"><code>deficit_three_valued</code></a></span></div>
  ```

  只有 Lean 已验证的定理用绿色 `LEAN ✓`；页面计算用 `.lean.num`（NUM）；示意模型与诠释 `.lean.model`（MODEL）；文献结果 `.lean.argued`（ARGUED）；开放问题 `.lean.open`（OPEN）。
- 颜色只来自令牌：CSS 用 `var(--cyan)` 等（映射到 `--tr-*`），脚本用 `TRV.palette` / `TRV.rgb`。琥珀色只给“现在/当前选择”。
- 运行模式（`shell.js` 按网址设置，页面不必自己解析）：

  | 网址 | 含义 | 页面看到的 |
  | --- | --- | --- |
  | `?embed=1` | 书内 iframe：隐藏页眉，舞台在最前 | `TRV.embed` |
  | `?embed=1&preset=<卡>` | 章节引用的一张图：舞台、一句说明、时间轴，不滚动 | `TRV.figure`、`TRV.preset` |
  | `?thumb=1` | 无字封面（1280×720）：`[data-thumb]` 充满画面，调用 `window.TRV_THUMB()` | `TRV.thumbMode`、`TRV.still` |
  | `?shot=1&preset=<卡>&lang=<语言>` | 被引用卡的带标签静态图，供 PDF/EPUB | `TRV.shot`、`TRV.still` |

  `TRV.still` 为真时不播放动画，直接显示那张卡的关键帧。
- 停帧（still frame）：会自己播放的卡在页面的卡片表里声明 `still`（时间轴上的值，或 `'end'`），把表交给 `kit.cards(el, { presets: PRESETS, … })`，它把声明写到卡上的 `data-still`（也可直接写在 HTML 里）；`TRV.still` 为真时页面把时钟放到那里。A card that plays by itself declares the frame its still shows as `still` in the page's table of cards; `kit.cards({ presets })` writes it onto the card as `data-still`, and the page puts its clock there when `TRV.still` is set. `stageFirstChecks` warns about a card that plays without one; a suite opens the still with `openStill(T, book, id, card, lang)` and checks that the frame carries the numbers of its caption.
- 手机宽度（390px）无横向滚动；尊重 `prefers-reduced-motion`。

## 嵌入书中 · Embedding in a chapter

```markdown
::: {.viz src="my-viz" preset="half" height="500"}
**一句标题。** 引用一张实验卡：图贴在讲到它的那句话旁边。
:::

::: {.viz src="my-viz" height="620"}
完整实验室的图注（可选，可含数学）。
:::
```

带 `preset`：HTML 中是开在那张卡上的一张图（`?embed=1&lang=<lang>&preset=<卡>`，不带内部滚动），附“全屏打开”；PDF/EPUB 中是 `viz/<id>/fig-<卡>.<语言>.jpg`、图注与在线地址。不带 `preset`：HTML 中是完整实验室的 iframe；PDF/EPUB 中是封面 `thumb.jpg`、图注与在线地址。各语言版本的 `src` 与 `preset` 必须相同。

With `preset` the chapter shows one card as a figure that does not scroll inside its frame, and PDF/EPUB print that card's labelled still in the language of the edition; without it the chapter embeds the whole lab and print shows the cover.

## 工具 · Tools

```bash
node tools/node/viz-server.mjs                 # local preview at http://127.0.0.1:8766/site/<book>/viz/
node tools/node/viz-shots.mjs <book> <id>      # review screenshots (desktop, in-book frame, phone, cover) → build/viz-shots/
node tools/node/viz-validate.mjs [book]        # registry + page contract + links + JS syntax
node tools/node/viz-test.mjs [book] [--shard i/n] [--slow]   # browser suites books/*/viz/tests/*.test.mjs (--slow: a frame a second)
node tools/node/viz-thumbs.mjs <book> [id …]   # thumb.jpg and the stills fig-<card>.<lang>.jpg of cited cards (honours PW_CHROMIUM_PATH)
./tbook viz list
```
