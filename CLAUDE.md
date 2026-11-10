# trureturing 书库 · agent 工作守则

本仓库出版专著：每本书的每一条定理都对应 [trureturing](https://github.com/the-omega-institute/trureturing) 中一条已被 Lean 内核验证并冻结的声明。书负责解释，Lean 负责成立；本仓库不写 Lean。书以 HTML（mdBook）、PDF（屏幕版/印刷版）与 EPUB（Apple Books）发布到 GitHub Pages 与 Release，可配交互可视化、视频与演示文稿。

本文件由模板托管（`./tbook template update` 会更新它）。本书库自己的规则写在 `PROJECT.md`：

@PROJECT.md

## 结构

- `books/<slug>/`：一本书。`book.toml` 元数据；`<lang>/` 每个语言版本一个目录（默认 `zh`、`en`，第一个为权威版本）；`assets/` 共享图片；`viz/` 可视化；`films/` 视频；`slides/` 演示文稿。
- `site.toml`：站点配置。`trureturing.lock.json`：所钉的 trureturing 提交与已解析的声明（只由 `./tbook pin` 写）。
- `tools/tbook/`：构建与校验（`./tbook <命令>`）。`theme/`：赛博朋克主题，配色唯一来源 `theme/tokens.json`。`skills/`：内置 skills。
- 架构与契约：`docs/ARCHITECTURE.md`；写作手册：`docs/AUTHORING.md`；验证模型：`docs/VERIFICATION.md`；发布：`docs/PUBLISHING.md`；升级：`docs/UPGRADING.md`。

## 规则

1. **定理必须经 Lean 验证。** `theorem / lemma / proposition / corollary` 必须带 `lean="<GID>"`，GID 在所钉提交上必须存在于 trureturing 的 `Golden/Frozen/state/<module>.lean.json` 且种类为 `theorem`。未证结论只能写成 `conjecture` 或 `problem`。需要新定理时，先在 trureturing 中形式化并冻结（`skills/theorem-formalize`）。
2. **陈述忠实。** 书中陈述与 Lean 陈述一致；不夸大（存在性 ≠ 算法，反例 ≠ 最小反例）。`proof` 块只做解释。颜色有语义：绿色只给 Lean 已验证，琥珀色只给“现在/当前选择”，红色标开放问题。
3. **多语言逐条对齐。** 各语言版本章节文件名与顺序相同，每章环境序列（种类、`#id`、`lean`）与媒体序列相同。先改权威版本，再同步其他版本；英文自然准确，不逐字硬译。
4. **锁文件只由工具写。** `./tbook pin` 更新所钉提交；`./tbook pin --refresh` 解析新增引用。升级提交时复核“陈述摘要变化”的定理（`skills/trureturing-pin`）。所钉提交必须在 `site.toml` 的 trureturing 分支（默认 `dev`）上，`./tbook pin` 与 `./tbook check` 都会核对；不要钉未合入的 PR 提交。
5. **托管文件不在书库里改。** `template.toml` 的 `[managed].paths` 下的文件归模板所有；改进请回馈模板仓库（`skills/template-update`）。书库自己的 skill 放 `skills/local-<name>/`，自己的文档放 `docs/project/`。
6. **严循示例与模板规范。** 交互可视化、视频与演示文稿须严格对齐 `books/example-monograph/` 示例（`viz/golden-carry/`、`films/001-golden-deficit/`、`slides/overview/`）与 `templates/` 的版式、组件和元素，不自创脱离示例框架的布局、非标徽章类名或私有运行时。
7. **只用相对链接。** 站点挂在 `/<repo>/` 下，以 `/` 开头的站内链接会断。
8. **提交前验证。** 至少运行 `./tbook check`（0 错误）；改动影响输出时运行对应的 `./tbook build …`，用 `./tbook serve` 在中英文、深浅主题、手机宽度下实际查看。改动工具时运行 `PYTHONPATH=tools python3 -m unittest discover -s tools/tests`。
9. **不在提交、文档或书中写模型标识。**

## 常用命令

```bash
./tbook doctor                      # 工具链体检
./tbook check                       # 结构、多语言对齐、Lean 引用
./tbook pin [--refresh|<sha>|<branch>|<tag>]  # 钉 trureturing 提交并解析声明
./tbook new-book <slug> --title zh=… --title en=…
./tbook new-chapter <slug> <name> --title zh=… --title en=…
./tbook build [html|pdf|epub|slides|viz|films|site|all] [--book <slug>] [--lang zh]
./tbook serve                       # 本地预览 _site/
./tbook viz|slides|film new …       # 新建可视化、演示文稿、视频（list 列出）
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
| `book-viz` | 按 trureturing-visualize 方案做交互可视化 |
| `book-film` | 按 trureturing-film 方案做视频 |
| `book-slides` | 按 chrono-company-slides 方案做演示文稿 |
| `book-export` | 导出 HTML/PDF/EPUB 与排错 |
| `book-release` | 发版、Release 与 Pages |
| `template-update` | 升级模板版本；把改进（含 skills 修订）回馈模板 |

## 完成标准

改动经 PR 合入 `main`，CI 通过，Pages 部署成功；涉及发版时 Release 附件齐全。
