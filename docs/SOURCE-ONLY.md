# 源文件与派生产物

仓库保存作者维护的正文、模板、图形脚本、交互程序和原始图片。由这些输入可重复生成的出版文件保存在本地与发布缓存，避免正文分支反复修改同一批输出。

| 保存在 Git | 本地生成，不提交 |
| --- | --- |
| `figures/*.py`、辅助数据 | `figures/*.<lang>.svg`、幻灯片的相应 SVG 副本 |
| 可视化 HTML/CSS/JS、登记表、测试 | 常规 `thumb.jpg`、`fig-*.jpg`、`.stills.json` |
| `theme/tokens.json`、`backdrop.css` | `theme/generated/tokens.*`、`backdrop.jpg/json` |
| 必要的局部论述与源程序 | 全书统计视图、索引及数据按需生成，消费者引用编译产物 |
| `trureturing.lock.json`、`template-manifest.json` | HTML、PDF、EPUB、视频与打包文件 |

锁文件记录冻结证据，模板清单记录同步基线，两者不能当作可丢弃输出。旧书已发布且仍被引用的稳定编号也须保留；删除统计索引及其消费者后，不再维护其专用编号表。照片、扫描件、自定义封面等原始素材也保留。常规视频海报目前仍按视频流程维护。

## 日常操作

`./tbook check --book <slug>` 先刷新本书配置的派生文本与静态图，再校验结构；它不会为缺失的常规可视化图片启动浏览器。源程序、卡名与双语对齐仍然接受检查。`./tbook sync --check` 与 `./tbook fig build --check` 用于只读比较已有本地输出；刚检出时缺失是正常现象，先生成再比较。

`./tbook build html|pdf|epub|slides|site|viz` 准备其消费者需要的输出。PDF/EPUB、可视化与站点发布需要 Node、Playwright Chromium；HTML 正文构建只需文本与静态图生成。可视化图片按页面输入、所引用卡及语言计算独立缓存单元 `viz-stills`，沿用现有内容摘要、成品校验和可信缓存恢复，不把图片放回 Git。构建失败立即停止对应书籍的后续输出。

CI 将可视化静帧拆成最多 12 个互不重复的分片，每个分片复用专用图片缓存，再把校验完整的缓存单元交给所有 PDF 变体和 EPUB。导出任务要求已有图片，缺失或损坏直接失败，避免暗中重新截完整本书。每个分片只启动一次引用解析器与浏览器。

主干推送在独占 Pages 工作流中与线上版本比较，按累计改动选择出版输入。Pages 检查书稿、分片准备缺失的视频、复用已有缓存并组装站点。队列与滚动小时限额见[发布手册](PUBLISHING.md)。

手工验收单个可视化仍运行 `node tools/node/viz-thumbs.mjs <book> <id>`，缺图或输入变化才采样；`--check` 核对本地图片，`--force` 主动重采样。舞台、行为或标签变化仍按对应技能测试和看图。

静态图每次直接运行 Python 脚本生成；只写入发生变化的 SVG 与幻灯片副本。`fig build --check` 比较当前绘图结果与本地文件，报告缺失或过期输出，不写回文件。

## 书库自己的生成器

全书统计由下游选择 `.stats` 引用块按需嵌入或链接，构建只生成被引用的视图；也可用 `./tbook stats --write` 导出 `build/statistics/` 下的快照和多格式视图，选择方法见 `AUTHORING.md` 的“统计与派生产物”。删除手工维护的统计副本。下列旧生成器配置仅用于仍需兼容的既有书籍，不作为新书的默认方案；迁移时一并删除不再有消费者的模板、数据、编号表与 `[derived]` 配置。

```toml
[statistics]
exclude = ["appendix-c.md"]
templates = { "appendix-c.md" = "data/appendix-c.{lang}.md.in" }

[derived]
command = ["python3", "books/my-book/generate.py"]
outputs = ["zh/appendix-c.md", "en/appendix-c.md", "data/statistics.json", "viz/map/data.generated.json"]
```

`outputs` 是相对书目录的文件路径，必须留在本书内。生成器负责从源输入准备文本，支持只读 `--check`；不要在此处捕获浏览器图片。统计先读取论述模板的环境，排除自动索引引用，因而首次检出没有生成附录也能统计。地图程序通过 `fetch('data.generated.json')` 读取输出，避免把数据写回手工维护的 `main.js`。书内 `.gitignore` 明确列出这些输出，以及幻灯片引用的静态图副本。

## 从旧分支迁移

升级到 1.0.0 时迁移自动取消跟踪常规静态图、可视化图片和清单，保留工作区文件并补充书内忽略规则。自有统计输出需要在 `[derived].outputs` 声明后运行：

```bash
./tbook artifacts list
./tbook artifacts untrack
./tbook artifacts check
```

`untrack` 只改 Git 索引，保留本地文件；提交时必须包含删除记录和忽略规则。不要使用宽泛的 `*.svg` 或 `*.jpg` 忽略规则来覆盖原始图片。

合并迁移前的旧分支时，生成文件出现修改/删除冲突，应保留删除；只合并源文件，然后重新生成。不要逐个合并 SVG、图片、统计表或生成数据。原始内容、稳定编号、锁文件与同步基线仍需正常审阅，不能对它们使用统一的 ours/theirs 合并策略。
