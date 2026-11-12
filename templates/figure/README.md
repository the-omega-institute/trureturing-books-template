# 静态图起始脚本 · Starter script for a static figure

`./tbook fig new <book> <name>` 把 `figure.py` 复制为 `books/<book>/figures/<name>.py`。它本身能运行：画一支箭头在另一支上的影子，用到了角色颜色、按语言取标签、角度与直角标记。

脚本的契约（`tools/tbook/figure.py`）：

| 名字 | 含义 |
| --- | --- |
| `SIZE = (宽, 高)` | 自然尺寸（CSS 像素），也是图在页面上的最大尺寸；宽不超过 760 |
| `ALT = {"zh": …, "en": …}` | 给看不见图的读者的描述，每个语言版本一条 |
| `WRAP = True`（可选） | 图由 `fig.row()` / `fig.panel()` 的各栏组成，手机上各栏叠放 |
| `MARKUP = 2`（可选） | 下标、上标里可以再写 `*斜体*` 等标记，斜体 `I` 用衬线字形；不写时按旧规则 |
| `draw(fig)` | 在 `fig`（`tbook.figkit.Figure`）上画；`fig.t("中文", "English")` 取当前语言的标签 |

同一目录下以下划线开头的 `.py` 是各图共用的辅助模块，不算图。生成：`./tbook fig build --book <book>`；看图：`./tbook fig shots <book> <name>`；引用：各语言章节里写 `::: {.figure src="<name>"}` 加图注。

画图库里除了线、面、文字、坐标系与球，还有这些现成的形状（详见速查表）：

| 形状 | 调用 |
| --- | --- |
| 流程图的方框与箭头 | `a = fig.box(x, y, "文字", note="lemma")`、`fig.box(…, dashed=True)`、`fig.link(a, b, elbow=True)` |
| 球上的转动弧与带箭头的小圆弧 | `sp.turn(轴, 起点, 角度, arrow=True)`、`sp.small_circle(轴, 角, start=v, span=90, arrow=True)` |
| 球上的扇形、区域与凸多面体 | `sp.sector(轴, 起点, 角度, "area")`、`sp.patch(点, "cyan")`、`sp.polytope(点)` |
| 对数坐标 | `fig.axes(…, logx=True, logy=True)`，`ax.decades("y")` |
| 阶梯线与柱状图 | `ax.step(pts)`、`ax.bars(pts, "cyan")` |
| 凸包 | `figkit.hull(点)`、`figkit.hull3(点)` |
| 文字标记 | `***粗斜体***`、`\bar{z}`；`MARKUP = 2` 时标记可嵌套 |
| 等宽文字的宽度 | `fig.measure(s, 13, mono=True)`（每字 0.6 em） |
| 镜面反射的折线箭头 | `fig.bounce(a, 镜面点, b)` |

方法、画图库速查、反模式与完成标准见 `skills/book-figure/SKILL.md`；成品示例是 `books/example-monograph/figures/`。
