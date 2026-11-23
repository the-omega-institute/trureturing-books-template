# trureturing 书库 · agent 工作守则

本仓库出版专著：每本书显式区分 Lean 验证、书面证明与开放问题；Lean 验证定理对应 [trureturing](https://github.com/the-omega-institute/trureturing) 中一条已被 Lean 内核验证并冻结的声明。Lean 验证依赖冻结声明；书面证明由作者与评审负责。本仓库不写 Lean。书以 HTML（mdBook）、PDF（屏幕版/印刷版）与 EPUB（Apple Books）发布到 GitHub Pages 与 Release，可配交互可视化、视频与演示文稿。

本文件由模板托管（`./tbook template update` 会更新它）。本书库自己的规则写在 `PROJECT.md`：

@PROJECT.md

## 结构

- `books/<slug>/`：一本书。`book.toml` 元数据；`<lang>/` 每个语言版本一个目录（默认 `zh`、`en`，第一个为权威版本）；`figures/` 静态图（脚本与生成的 SVG）；`assets/` 共享图片；`viz/` 可视化；`films/` 视频；`slides/` 演示文稿。
- `site.toml`：站点配置。`trureturing.lock.json`：trureturing 分支或固定提交及其声明索引（只由 `./tbook pin` 写）。
- `tools/tbook/`：构建与校验（`./tbook <命令>`）。`theme/`：赛博朋克主题，配色唯一来源 `theme/tokens.json`。`skills/`：内置 skills。
- 架构与契约：`docs/ARCHITECTURE.md`；写作手册：`docs/AUTHORING.md`；验证模型：`docs/VERIFICATION.md`；发布：`docs/PUBLISHING.md`；升级：`docs/UPGRADING.md`。

## 规则

1. **定理必须声明证据。** `theorem / lemma / proposition / corollary` 默认必须带 `lean="<GID>"`，GID 在所钉提交上必须存在于 trureturing 的 `Golden/Frozen/state/<module>.lean.json` 且种类为 `theorem`。必须先检索匹配的冻结声明；已有匹配 Lean 验证时必须引用 Lean。仅在没有匹配验证、源文已有证明时，用 `status="written-proof" proof="<proof-id>" doi="<裸 DOI>" source="<原文定位>" request="<issue URL>"`；尚无 DOI 的新论文省略 `doi`，改填 `repository="<源论文仓库 HTTPS 地址>"`。两者至少填一个且不带 `lean`，每版提供同 id 的非空 proof 块；DOI 或源仓库必须支持同一陈述，issue 指向 trureturing-requests，先搜索并复用已有问题，在英文正文或评论登记本书用途、源仓库（如有）和书库仓库，没有才新建。请求标题、正文与登记评论统一用英文；标题有 DOI 时为 `[Formalization] <Result name> | DOI:<bare DOI> | <Source location>`，无 DOI 时为 `[Formalization] <Result name> | No DOI | <Source location>`，登记方式见 `docs/FORMALIZATION-REQUESTS.md`；紫色“书面证明”不计入 Lean 验证。真正未证结论只能写成 `conjecture` 或 `problem`。需要新定理时，先在 trureturing 中形式化并冻结（`skills/theorem-formalize`）。
2. **陈述忠实。** Lean 验证结果的书面陈述与 Lean 陈述一致，书面证明结果忠实于源文；不夸大（存在性 ≠ 算法，反例 ≠ 最小反例）。Lean 结果的 `proof` 用于解释；书面证明结果的 proof 是作者与评审负责的论证。颜色有语义：绿色只给 Lean 已验证，琥珀色只给“现在/当前选择”，红色标开放问题，紫色标书面证明。
3. **多语言逐条对齐。** 各语言版本章节文件名与顺序相同，每章环境序列（种类、`#id`、`lean`、`status`、`proof`、`doi`、`source`、`repository`、`request`）与媒体序列相同。先改权威版本，再同步其他版本；英文自然准确，不逐字硬译。
4. **锁文件只由工具写。** `./tbook pin --follow` 将配置的分支写入锁文件，运行时解析完整 SHA 与引用。`./tbook pin` 更新所钉提交；`./tbook pin --refresh` 解析新增引用。升级提交时复核“陈述摘要变化”的定理（`skills/trureturing-pin`）。所钉提交必须在 `site.toml` 的 trureturing 分支（默认 `dev`）上，`./tbook pin` 与 `./tbook check` 都会核对；不要钉未合入的 PR 提交。
5. **托管文件不在书库里改。** `template.toml` 的 `[managed].paths` 下的文件归模板所有；改进请回馈模板仓库（`skills/template-update`）。书库自己的 skill 放 `skills/local-<name>/`，自己的文档放 `docs/project/`。
6. **版式服从内容，契约不可改。** 交互可视化按 `skills/book-viz` 的方法做：舞台就是页面，每张实验卡都是正文可以单独引用的图（`::: {.viz src=… preset=…}`）；按对象选舞台，不把所有主题套进同一副骨架。共享运行时（`theme/viz/`）、页面契约、依据标注类名与质量门（`stageFirstChecks`）是硬约束，不自造私有运行时或非标徽章。静态图按 `skills/book-figure` 由脚本生成（`books/<slug>/figures/`），只写颜色角色、不写色值，在讲到它的那句话旁用 `::: {.figure src=…}` 引用。视频与演示文稿对齐 `books/example-monograph/` 的示例（`films/golden-deficit/`、`slides/overview/`）与 `templates/`。
7. **只用相对链接。** 站点挂在 `/<repo>/` 下，以 `/` 开头的站内链接会断。

全书统计作为编译产物按需生成，源码只保留选择与引用；正文可用 `::: {.stats src="…"}` 嵌入表格或链接独立产物，命令行用 `./tbook stats --write` 导出。下游自行选择视图、格式与分区，不在正文、程序或文档里维护统计副本。
8. **按改动范围验证，本地与 CI 一致。** 先用 `./tbook test --list` 查看范围，再运行 `./tbook test`；默认比较 `origin/main` 分支点至当前工作区，包含已提交、暂存、未暂存与未跟踪文件，`--base <ref>` 可指定基准。**只改正文文字时本地不运行测试：**改动仅限章节 Markdown 的文字（叙述、公式、定理环境及其属性、交叉引用），以及为解析其中 Lean 引用而由 `./tbook pin` 更新的锁文件时，本地只做受影响书籍的结构检查，不运行 `./tbook test`，也不为此安装浏览器或导出依赖；`--list` 选中的浏览器套件、影片、幻灯片与导出检查由 PR 的 CI 执行。增删或修改媒体引用块（`.figure`、`.viz`、`.film`、`.slides`），或改动可视化、静态图、视频、幻灯片、工具、主题与工作流，不属于此例。只运行改动直接影响及其依赖的单元、页面与媒体测试，尤其不因工具、文档或某章文字修改而重跑无关浏览器套件；共享运行时覆盖其实际读者。结构检查限受影响书籍（`./tbook check --book <slug>`，0 错误），输出改动仅构建受影响格式。浏览器、截图、静帧与慢帧复查都限受影响对象，复用依赖未变且范围适用的既有证据；慢帧用 `./tbook test --slow` 显式选择。普通 HTML/PDF/EPUB 以自动检查与相关构建验收，仅在相关错误、警告或明确视觉任务时按 `skills/book-export` 查看受影响页面；可视化与静态图的画面改动仍按对应 skill 看图。**如果 `--list` 显示本地选择扩展到大部分或全部浏览器套件，立即停止本地运行并交给 CI 的并行矩阵；禁止把这种广泛选择串行跑完。** 全量测试仅在用户明确要求时用 `./tbook test --full`，不把全量单元测试、全书构建或遍历全部语言／主题／屏宽作为常规前置。
9. **不在文档或书中写模型标识。** 提交记录与 PR 描述不受此限。
10. **保持文档语言。** 修改现有文档（包括 README、`docs/` 与 `SKILL.md`）时，新增或修订的标题、正文、示例说明与示例注释沿用该文档的主要语言；新文档遵循所在目录的语言约定，未约定时默认中文。命令、代码标识符、引文和明确的外语示例保留原文。多语言文档分别遵循各自语言并同步更新。

11. **源文件入库，派生产物按需生成。** SVG、可视化封面/静帧与 `.stills.json`、主题令牌及打印背景均不提交；校验与构建从源文件准备所需输出。书库自己的生成器在 `[derived].outputs` 列出输出，并用书内 `.gitignore` 忽略。锁文件、稳定编号与模板同步基线仍是必须提交的证据或身份数据。迁移与命令见 `docs/SOURCE-ONLY.md`；`./tbook artifacts check` 拒绝重新跟踪产物。
12. **写书不写流水账，保持正文流畅，大节与细密推导下沉附录，新增章节按主题归位。** 正文编号主章只承担中心问题、直觉图像、关键算例、核心结论与证明骨架，按读者理解次序保持浅层可读（可由 `book.max_chapter_depth` 限制编号主章嵌套深度，如设为 `2`，即“章 → 节 → 至多一级子节”）；严禁按研究、形式化或 PR 提交的时间顺序往页末、章末或书末顺手追加结果与新章节，严禁连续堆砌缺乏动机与过渡的“定理—证明”清单，严禁把研究回合、补丁过程或工作流视角写进正文，严禁为规避 `max_page_lines` 在正文主章内连续拆出四五级深层子页、空壳中转目录或微型子页，**更严禁把全书末尾或收官总纲章当作万能缓冲区无脑追加新章、新节**。未来新增或整理内容按四级次序落位：（1）深化、推广或修正既有命题时直接在原小节融合改写并收束旧段落，不新建页面；（2）独立完备且推动主线的子论题须归入其学科主题真正所属的既有主章，用 `./tbook new-chapter … --parent <章> --before|--after <相邻节>` 插在该章论证递进的自然位置（且不突破 `book.max_chapter_depth`），同步改写前后过渡与章导言；（3）超长技术节、多页引理链、穷举分类／参数族变体与资源账本一律下沉至 `[numbering.unnumbered]` 专题附录（豁免主章深度上限），正文保留核心结论、直觉阐释、主线交互实验／静图与流畅过渡，下沉既有页面时保留原文件名、`#id`、`lean` 属性与既有锚点；阶段性副产物留上游仓库或 Issue；（4）成熟专著技术体量膨胀时优先下沉专题附录、不动既定主章框架与不轻拆新书；仅当既有各章均无法承载全新一级板块且未达 `book.max_chapters` 上限时，才用 `--before|--after` 在全书结构的逻辑位置增设主章（不得排在收官章或终章之后充当时间线尾巴）；已达 `book.max_chapters` 或结构定型的专著须通过章内融合、附录下沉或跨章主题重整吸纳新内容。详见 `docs/AUTHORING.md` 的“论证结构与禁止流水账”“正文流畅与超大技术节下沉附录”与“新增章节与子节的归位原则”。

## 协作流程

开展长推理或研究前，先查相关 Issue 和 PR，在已有或新建的 Issue 中认领具体范围。遇到重叠先分工，结束时留下结果并及时关闭已完成的 Issue。详见[贡献规范的长推理与研究流程](CONTRIBUTING.md#长推理与研究)。

协作遵循 [CONTRIBUTING.md](CONTRIBUTING.md)：Issue 与 PR 使用 `type(scope): 摘要`，普通分支使用 `<type>/<lowercase-topic>`；自动模板升级与钉版保留规范中列出的专用分支。所有修改通过 PR 合入 `main`，不得直接推送。

## 常用命令

```bash
./tbook doctor                      # 工具链体检
./tbook test [--list|--base <ref>|--slow|--full]  # 仅测试改动影响的部分
./tbook check                       # 结构、多语言对齐、Lean 引用与形式化请求
./tbook requests [--json]            # 按 issue 汇总书面证明的形式化需求
./tbook pin [--refresh|<sha>|<branch>|<tag>]  # 钉 trureturing 提交并解析声明
./tbook new-book <slug> --title zh=… --title en=…
./tbook new-chapter <slug> <name> [--parent <ch>] [--before <ch>|--after <ch>] --title zh=… --title en=…
./tbook build [html|pdf|epub|slides|viz|films|site|all] [--book <slug>] [--lang zh]
./tbook serve                       # 本地预览 _site/
./tbook viz|slides|film new …       # 新建可视化、演示文稿、视频（list 列出）
./tbook fig new|build|list|shots …  # 静态图：新建脚本、生成 SVG、列出、四种画面的预览图
theme/film/film.sh <dir> <step>     # 视频流水线：setup、timeline、shot、serve、clip、poster、all
./tbook theme                       # 由 theme/tokens.json 重新生成配色文件
./tbook template status|update      # 模板版本
```

## Skills

| skill | 何时用 |
| --- | --- |
| `book-new` | 新建书、章节、语言版本；新书库初始化 |
| `book-write` | 写章节：环境、Lean 引用、数学、引用、对齐 |
| `theorem-formalize` | 书中需要的定理尚未在 trureturing 冻结 |
| `trureturing-pin` | 升级/刷新所钉的 trureturing 提交，处理 bump PR |
| `book-figure` | 做静态图：一张图一件事，脚本生成，随主题与印刷版变化，按语言出标签 |
| `book-viz` | 做交互可视化：舞台优先，按实验卡在正文中引用 |
| `book-film` | 按 trureturing-film 方案做视频 |
| `book-slides` | 按 chrono-company-slides 方案做演示文稿 |
| `book-export` | 导出 HTML/PDF/EPUB 与排错 |
| `book-release` | 发版、Release 与 Pages |
| `template-update` | 升级模板版本；把改进（含 skills 修订）回馈模板 |

## 完成标准

改动经 PR 合入 `main`，CI 通过，Pages 部署成功；涉及发版时 Release 附件齐全。
