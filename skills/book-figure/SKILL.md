---
name: book-figure
description: 为书做静态图时使用：一张图只讲一件事，由脚本按数学生成（books/<slug>/figures/<name>.py），随深浅主题与印刷版变化，每种语言一版标签，在讲到它的那句话旁用 ::: {.figure src=…} 引用；也用于修改、排查已有静态图，把旧的手绘 SVG 换成标准图。
---

# 静态图

## 适用范围

**用**：正文某一句话需要一张不动的图（一个构造、一条曲线、一张对照表、一个流程）；修改或排查已有静态图；把 `assets/` 里写死颜色的旧 SVG 重做成标准图。

**不用**：读者需要亲手推一下才看得见的想法（`book-viz`）；讲“怎样一步步变过去”（`book-film`）；演示文稿（`book-slides`）。照片、截图等不能由脚本画出的图片仍放 `books/<slug>/assets/`，章节里写 `![图注](../assets/x.png)`。

**权威**：`tools/tbook/figkit.py`（画图库与它强制的标准）、`tools/tbook/figure.py`（生成、各端渲染、检查）、`templates/figure/figure.py`（起始脚本，本身能运行）、`theme/tokens.json`（颜色的唯一来源）。

**成品示例**：`books/example-monograph/figures/phase-square.py`（坐标系、区域、按公式算出的 64 个点，脚本里断言了正文给出的计数）与 `carry-rules.py`（由一张数据表排出的图）；它们在 `books/example-monograph/{zh,en}/` 的第一章与附录 A 中被引用。

## 什么算好

读者读到那句话，往旁边看一眼，三秒之内看见这句话说的那一件事；合上书还能凭记忆把图画出来。

1. **一张图只讲一件事。** 写不出“这张图让读者看见 ……”这一句话，就还不该动笔。一张图里出现第二件事时，拆成两张，各放在讲到它的那句话旁。三联的总览图只留给章首的“本章地图”。
2. **图是算出来的，不是摆出来的。** 角度、长度、曲线、点的位置都由脚本按正文的公式计算；正文给出的数（“左下三角形里有 10 个点”）在脚本里用 `assert` 核对。示意图不冒充数据：不按公式画的曲线在图注里说明是示意。
3. **颜色是角色，不是装饰。** 只写角色名，不写色值。绿色（`lean`）只给正文用 `lean=` 引用的已验证结论，琥珀色（`now`）只给“现在/当前选择”，红色（`open`）只标开放问题，紫色（`argued`）标有纸面证明而未在本书形式化的结论。同一本书里同一种对象始终用同一种颜色（各书在自己的 `skills/local-*` 里写下约定）。
4. **图注只说图里看得见的东西**，用与图上相同的颜色词和符号；先用一句加粗的话说出这张图讲的那件事，再解释。

## 方法（按顺序做）

### 0. 先读正文，写下这张图的一句话

读完那一节，定下：这张图讲哪一句话、放在哪两个段落之间、图上需要哪几个对象、哪些量要按公式算。同一节里已经有讲同一件事的图或实验卡时，引用它，不重复画。

### 1. 新建脚本

```bash
./tbook fig new <book> <name>        # 生成 books/<book>/figures/<name>.py（起始脚本，可直接运行）
```

名字用小写字母、数字与连字符，建议以章节开头（`ch02-shadow`）。脚本的三样东西：

```python
SIZE = (480, 290)                        # 自然尺寸（CSS 像素）：图最大显示成这么大；宽 ≤ 760
ALT = {"zh": "……", "en": "…"}             # 给看不见图的读者的描述，每种语言一条，把图讲的那件事说完整
def draw(fig):                           # 在 fig 上画；fig.t("中文", "English") 取当前语言的标签
    ...
```

几张图共用的画法（同一颗球、同一套坐标）写进 `figures/_<name>.py`（下划线开头的文件不是图），各图 `import` 它；辅助模块里要用画图库时写 `from tbook import figkit`。

### 2. 用画图库画（`tools/tbook/figkit.py`）

坐标以左上角为原点、`y` 向下，单位是 CSS 像素；`arc`、`angle` 的角度按纸上的习惯（度，从 x 正方向逆时针）。

| 用途 | 调用 |
| --- | --- |
| 线、折线、曲线 | `fig.line(x1, y1, x2, y2, "ink", 1.6, dash="4 3")`、`fig.polyline(pts, …)`、`fig.curve(fn, t0, t1)`、`fig.path(d, …)` |
| 箭头 | `fig.arrow(x1, y1, x2, y2, "now", 2.2)`、`fig.curve_arrow(pts, …)`、`fig.arrow_head(x, y, 角度, …)` |
| 面 | `fig.polygon(pts, "cyan", fill_opacity=0.18)`、`fig.rect(x, y, w, h, color="edge", fill="panel", rx=4)`、`fig.circle(…)`、`fig.ellipse(…)`、`fig.arc(cx, cy, r, a0, a1, …, fill=…)` |
| 点 | `fig.dot(x, y, 3.6, "cyan", ring="bg")` |
| 文字 | `fig.text(x, y, "影子 cos θ", size=14, color="line", anchor="middle", middle=True, halo=True)`；`*x*` 斜体，`**b**` 加粗，`_{i}` 下标，`^{2}` 上标；数学写 Unicode 符号（θ、φ、·、∧、√、≤） |
| 标记 | `fig.angle(cx, cy, r, a0, a1, "θ")`、`fig.right_angle(x, y, 方向)`、`fig.brace(x1, y1, x2, y2, "标签")`、`fig.cross(x, y)`（划掉）、`fig.legend(x, y, [("line", "线"), ("area", "面积")])`、`fig.chip(x, y, "LEAN ✓", "lean")` |
| 坐标系 | `ax = fig.axes(x, y, w, h, (x0, x1), (y0, y1))`；`ax.frame()`、`ax.xaxis(ticks=…, labels=…, label=…)`、`ax.yaxis(…)`、`ax.grid(…)`、`ax.plot(fn, color="cyan")`、`ax.path(pts)`、`ax.points(pts)`、`ax.area(pts)`、`ax.hline(y)`、`ax.vline(x)`、`ax.text(x, y, …)`、`ax.pt(x, y)` |
| 球 | `sp = fig.sphere(cx, cy, r)`（+z 向上，+x 朝向读者偏左下，+y 向右）；`sp.outline()`、`sp.great_circle(法向)`、`sp.small_circle(轴, 角)`、`sp.arc(u, v, arrow=True)`、`sp.path([…])`、`sp.arrow(v, "now")`、`sp.dot(v)`、`sp.label(v, "…", dx=…, dy=…)`、`sp.axes(labels=("x", "y", "z"))`、`sp.disc(法向)`、`sp.segment(a, b)`；背面的线自动画成虚线。向量工具：`figkit.sph(θ, φ)`、`slerp`、`rotate`、`cross`、`dot3`、`unit` |
| 分栏 | `left, right = fig.row([220, 220], 240)`：每一栏是一块自己的画布（方法与 `fig` 相同）；脚本里写 `WRAP = True` 时各栏在宽屏并排、在手机上自动上下叠放，此时所有内容都画在栏里 |

角色名：`ink`（主线与正文色）、`dim`（次要线与标签）、`faint`（辅助线）、`edge`、`panel`、`bg`，强调色 `cyan`、`magenta`、`amber`、`violet`、`blue`、`orange`、`sigma`，语义名 `lean`、`open`、`argued`、`now`、`model`、`line`、`area`、`axis`。

画图库会拒绝不合标准的图（`./tbook fig build` 报错并指出是哪一句）：字号小于 12、线宽小于 1、文字超出画布边缘、未知的角色名、宽度超过 760。字号 12 是下限而不是常用值：正文标签用 14，次要标签 13；手机上图会缩到约六成，14 的字仍然读得出。

### 3. 生成与看图

```bash
./tbook fig build --book <book> [<name> …]     # 每种语言生成 figures/<name>.<语言>.svg，提交入库
./tbook fig shots <book> <name> [<name> …]     # 深色、浅色、手机、印刷四种画面，中英各一，写到 build/fig-shots/<book>/
```

`fig shots` 另外给出拼版图 `sheet-<语言>-<画面>.png`，一次看很多张。检查分不清清楚的图和杂乱的图，必须亲眼看，逐条问：

- 不读图注，看得出这张图讲的那一件事吗？主角够大吗？
- 标签有没有压在线上、压在一起、贴着边？英文版比中文版长，两种语言都要看。
- 浅色与印刷画面里，细线和浅色的面还看得见吗？深色画面里，半透明的面有没有糊成一片？
- 手机画面里最小的字还读得出吗？读不出就删标签或拆图，而不是缩小字号。
- 颜色是否只按角色使用：绿色只在已验证的结论上，琥珀色只在“当前”上？

### 4. 在章节里引用

顶格写在讲到它的那句话之后、两个段落之间，各语言版本位置相同、`src` 相同，只翻译图注：

```markdown
::: {.figure src="ch02-shadow"}
**b 落在 a 上的影子。** 青色的线是 $\vv{c} = (\vv{a}\cdot\vv{b})\vv{a}$，长度为 $\cos\theta$；见 [@thm-born-pairing]。
:::
```

图注是普通的 Markdown：可以有行内数学、`[@id]` 引用与加粗；必须有，且不能只是编号（“图 13”）。HTML 中图内联在页面里，颜色随主题切换；PDF 的屏幕版与印刷版各用自己的配色；EPUB 用浅色配色。

### 5. 检查

```bash
./tbook check          # 图注为空或只有编号（错误）；提交的 SVG 与脚本不一致（错误）；各语言的图序列不一致（错误）；
                       # assets/ 里没有被引用的文件、没有脚本的 SVG、没有章节引用的图（警告）
./tbook build html pdf epub --book <book>     # 实际构建，在站点与 PDF 里看一眼
```

## 反模式

| 现象 | 为什么不行 | 改法 |
| --- | --- | --- |
| 一张图三联并排，讲三件事 | 读到任何一句话时，图上有两块是无关的 | 拆成三张，各放在那句话旁；总览图只放章首 |
| 图上以公式和文字为主，形状很小 | 那是一段排了版的正文，不是图 | 把对象本身画大；公式留在正文和图注里 |
| 在脚本里写 `#19f0ff` 或自己拼 SVG 字符串上色 | 换主题、出印刷版时颜色不跟着变 | 只用角色名；库里没有的形状用 `fig.path(d, 角色…)` |
| 两种语言共用一张图，标签中英混排 | 每个读者都看到半张看不懂的图 | 标签全部走 `fig.t("中文", "English")` |
| 图注复述正文，或说到图上没有的东西 | 读者对着图找不到 | 只说图里看得见的，用图上的颜色词 |
| 曲线是随手画的，图注却给了数值 | 示意图冒充了数据 | 按公式算；确属示意就在图注里写明 |
| 为了放下标签把字号调到 12 以下 | 手机上读不出，库也会报错 | 删次要标签、加宽画布，或拆图 |

## 把旧图换成标准图

1. 为它写脚本（`./tbook fig new`），按上面的方法重画；不是逐笔临摹，而是先问这张图讲哪一件事。
2. 各语言章节里把 `![图注](../assets/old.svg)` 换成 `::: {.figure src="<name>"}` 加图注。
3. `git rm` 旧文件；`./tbook check` 不再对它报“没有被引用”。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `text '…' runs past the right edge` | 标签比估计的画布宽：换位置、换短说法或加宽 `SIZE`；英文常比中文长 |
| `is stale: its script draws something else` | 改了脚本没有重新生成：`./tbook fig build --book <book>` 后提交 SVG |
| `no figure books/<book>/figures/<name>.py` | 章节引用的名字不存在；核对拼写，各语言一致 |
| `figure … has a placeholder caption` | 图注写成一句说明这张图的话 |
| 手机上分栏的图挤成一行 | 脚本里加 `WRAP = True`，并把所有内容画进各栏 |
| 下标里的负号像一条下划线 | 下标、上标里的正负号写 Unicode 的 `₊`、`₋`、`⁺`、`⁻`（`_{−}` 缩小并下移后贴着基线） |
| `‖r‖`、`⋆` 在图上间距过大或太小 | 范数写单竖线 `|r|`；少见的符号换成文字或常见的记号 |
| 并排的两栏在手机上缩得太小 | 改成 `WRAP = True` 的分栏图，手机上自动上下叠放 |
| PDF 里中文标签成了方框 | 构建机器缺中文字体：`./tools/fetch-fonts.sh`（见 `book-export`） |

## 完成标准

每张图对应正文里的一句话，并放在它旁边；四种画面、两种语言都亲眼看过；`./tbook fig build --check`、`./tbook check` 通过；各语言章节的引用位置与 `src` 一致；在 HTML 与 PDF 中实际看过。
