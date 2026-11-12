# trureturing 书库 · agent 工作守则

本仓库出版专著：每本书显式区分 Lean 验证、书面证明与开放问题；Lean 验证定理对应 [trureturing](https://github.com/the-omega-institute/trureturing) 中一条已被 Lean 内核验证并冻结的声明。Lean 验证依赖冻结声明；书面证明由作者与评审负责。本仓库不写 Lean。书以 HTML（mdBook）、PDF（屏幕版/印刷版）与 EPUB（Apple Books）发布到 GitHub Pages 与 Release，可配交互可视化、视频与演示文稿。

本文件由模板托管（`./tbook template update` 会更新它）。本书库自己的规则写在 `PROJECT.md`：

@PROJECT.md

## 结构

- `books/<slug>/`：一本书。`book.toml` 元数据；`<lang>/` 每个语言版本一个目录（默认 `zh`、`en`，第一个为权威版本）；`figures/` 静态图（脚本与生成的 SVG）；`assets/` 共享图片；`viz/` 可视化；`films/` 视频；`slides/` 演示文稿。
- `site.toml`：站点配置。`trureturing.lock.json`：所钉的 trureturing 提交与已解析的声明（只由 `./tbook pin` 写）。
- `tools/tbook/`：构建与校验（`./tbook <命令>`）。`theme/`：赛博朋克主题，配色唯一来源 `theme/tokens.json`。`skills/`：内置 skills。
- 架构与契约：`docs/ARCHITECTURE.md`；写作手册：`docs/AUTHORING.md`；验证模型：`docs/VERIFICATION.md`；发布：`docs/PUBLISHING.md`；升级：`docs/UPGRADING.md`。

## 规则

1. **定理必须声明证据。** `theorem / lemma / proposition / corollary` 默认必须带 `lean="<GID>"`，GID 在所钉提交上必须存在于 trureturing 的 `Golden/Frozen/state/<module>.lean.json` 且种类为 `theorem`。必须先检索匹配的冻结声明；已有匹配 Lean 验证时必须引用 Lean。仅在没有匹配验证、源文已有证明且能引用 DOI 时，用 `status="written-proof" proof="<proof-id>" doi="<裸 DOI>" source="<原文定位>" request="<issue URL>"` 且不带 `lean`，每版提供同 id 的非空 proof 块；DOI 必须支持同一陈述，issue 指向 trureturing-requests，先搜索并复用已有问题，在正文或评论登记本书用途，没有才新建。请求标题、正文与登记评论统一用英文；标题统一为 `[Formalization] <Result name> | DOI:<bare DOI> | <Source location>`，登记方式见 `docs/FORMALIZATION-REQUESTS.md`；紫色“书面证明”不计入 Lean 验证。真正未证结论只能写成 `conjecture` 或 `problem`。需要新定理时，先在 trureturing 中形式化并冻结（`skills/theorem-formalize`）。
2. **陈述忠实。** Lean 验证结果的书面陈述与 Lean 陈述一致，书面证明结果忠实于源文；不夸大（存在性 ≠ 算法，反例 ≠ 最小反例）。Lean 结果的 `proof` 用于解释；书面证明结果的 proof 是作者与评审负责的论证。颜色有语义：绿色只给 Lean 已验证，琥珀色只给“现在/当前选择”，红色标开放问题，紫色标书面证明。
3. **多语言逐条对齐。** 各语言版本章节文件名与顺序相同，每章环境序列（种类、`#id`、`lean`、`status`、`proof`、`doi`、`source`、`request`）与媒体序列相同。先改权威版本，再同步其他版本；英文自然准确，不逐字硬译。
4. **锁文件只由工具写。** `./tbook pin` 更新所钉提交；`./tbook pin --refresh` 解析新增引用。升级提交时复核“陈述摘要变化”的定理（`skills/trureturing-pin`）。所钉提交必须在 `site.toml` 的 trureturing 分支（默认 `dev`）上，`./tbook pin` 与 `./tbook check` 都会核对；不要钉未合入的 PR 提交。
5. **托管文件不在书库里改。** `template.toml` 的 `[managed].paths` 下的文件归模板所有；改进请回馈模板仓库（`skills/template-update`）。书库自己的 skill 放 `skills/local-<name>/`，自己的文档放 `docs/project/`。
6. **版式服从内容，契约不可改。** 交互可视化按 `skills/book-viz` 的方法做：舞台就是页面，每张实验卡都是正文可以单独引用的图（`::: {.viz src=… preset=…}`）；按对象选舞台，不把所有主题套进同一副骨架。共享运行时（`theme/viz/`）、页面契约、依据标注类名与质量门（`stageFirstChecks`）是硬约束，不自造私有运行时或非标徽章。静态图按 `skills/book-figure` 由脚本生成（`books/<slug>/figures/`），只写颜色角色、不写色值，在讲到它的那句话旁用 `::: {.figure src=…}` 引用。视频与演示文稿对齐 `books/example-monograph/` 的示例（`films/001-golden-deficit/`、`slides/overview/`）与 `templates/`。
7. **只用相对链接。** 站点挂在 `/<repo>/` 下，以 `/` 开头的站内链接会断。
8. **提交前验证。** 至少运行 `./tbook check`（0 错误）；改动影响输出时运行对应的 `./tbook build …`，用 `./tbook serve` 在中英文、深浅主题、手机宽度下实际查看。改动工具时运行 `PYTHONPATH=tools python3 -m unittest discover -s tools/tests`。
9. **不在提交、文档或书中写模型标识。**
10. **保持文档语言。** 修改现有文档（包括 README、`docs/` 与 `SKILL.md`）时，新增或修订的标题、正文、示例说明与示例注释沿用该文档的主要语言；新文档遵循所在目录的语言约定，未约定时默认中文。命令、代码标识符、引文和明确的外语示例保留原文。多语言文档分别遵循各自语言并同步更新。

## 常用命令

```bash
./tbook doctor                      # 工具链体检
./tbook check                       # 结构、多语言对齐、Lean 引用与形式化请求
./tbook requests [--json]            # 按 issue 汇总书面证明的形式化需求
./tbook pin [--refresh|<sha>|<branch>|<tag>]  # 钉 trureturing 提交并解析声明
./tbook new-book <slug> --title zh=… --title en=…
./tbook new-chapter <slug> <name> --title zh=… --title en=…
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
