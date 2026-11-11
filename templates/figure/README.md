# 静态图起始脚本 · Starter script for a static figure

`./tbook fig new <book> <name>` 把 `figure.py` 复制为 `books/<book>/figures/<name>.py`。它本身能运行：画一支箭头在另一支上的影子，用到了角色颜色、按语言取标签、角度与直角标记。

脚本的契约（`tools/tbook/figure.py`）：

| 名字 | 含义 |
| --- | --- |
| `SIZE = (宽, 高)` | 自然尺寸（CSS 像素），也是图在页面上的最大尺寸；宽不超过 760 |
| `ALT = {"zh": …, "en": …}` | 给看不见图的读者的描述，每个语言版本一条 |
| `WRAP = True`（可选） | 图由 `fig.row()` / `fig.panel()` 的各栏组成，手机上各栏叠放 |
| `draw(fig)` | 在 `fig`（`tbook.figkit.Figure`）上画；`fig.t("中文", "English")` 取当前语言的标签 |

同一目录下以下划线开头的 `.py` 是各图共用的辅助模块，不算图。生成：`./tbook fig build --book <book>`；看图：`./tbook fig shots <book> <name>`；引用：各语言章节里写 `::: {.figure src="<name>"}` 加图注。

方法、画图库速查、反模式与完成标准见 `skills/book-figure/SKILL.md`；成品示例是 `books/example-monograph/figures/`。
