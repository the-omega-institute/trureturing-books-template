---
name: book-new
description: 在书库中新建一本书、新增章节或新增一个语言版本时使用（./tbook new-book / new-chapter），包括 book.toml 元数据、默认中英双语与 SUMMARY 结构。
---

# 新建书、章节与语言版本

## 适用范围

**用**：开一本新书；给已有书加章节；给书加一种语言（如日文）；从模板仓库新建下游书库后的初始化。

**不用**：写章节内容（`skills/book-write`）。

## 新书库（从模板创建后）

1. 在 GitHub 上用 “Use this template” 创建仓库，克隆到本地。
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && npm ci`；`./tbook doctor` 逐项检查工具链并给出修复命令。
3. 编辑 `site.toml`：站点标题、`languages`（默认 `["zh", "en"]`）、`[books].order`。`repo` 与 `base_url` 一般留空（自动推断）。
4. 隐藏模板附带的示例书（`books/example-*`：`books/example-monograph/` 与 `books/example-primer/`），不要删除：
   1. 在 `site.toml` 的 `[books]` 中设 `hide = ["example-*"]`，并从 `[books].order` 中去掉 `"example-monograph"` 与 `"example-primer"`；
   2. `./tbook check`：0 错误，并有一行 `check: hidden by site.toml [books].hide, not checked: example-…`；`./tbook books` 不再列出示例书；
   3. `./tbook pin --refresh` 把只被示例书引用的声明从锁文件中清掉。

   隐藏的书留在 `books/` 中可供参考（写法、可视化、视频、幻灯片），但检查、钉版、构建、站点、发版与 CI 都当它不存在，`--book example-monograph` 之类的点名会报错。删除也可以（检查、构建与 CI 不依赖示例书），但书库以后用 git 合并模板改动时，模板改过的示例书会与删除冲突（modify/delete），每次都要手动处理；隐藏则没有这个问题（`docs/UPGRADING.md` §6）。想看示例书的效果时，临时从 `hide` 中去掉该模式，再运行 `./tbook pin --refresh`：第 3 步已把只被示例书引用的声明从锁文件中删去，不重新解析，`./tbook check` 会报错，构建出的页面上每条定理都标 `UNVERIFIED`。看完恢复 `hide`，再运行一次 `./tbook pin --refresh`；这期间的锁文件不要提交。
5. 在 GitHub：Settings → Pages → Source 选 “GitHub Actions”。
6. `./tbook check && ./tbook build all`，检查日志与适用的自动校验结果。仅在出现相关错误或警告，或任务明确要求视觉／版式检查与修复时，按 [book-export](../book-export/SKILL.md) 使用 `./tbook serve` 等工具查看受影响页面。

## 新书

```bash
./tbook new-book <slug> --title zh="中文书名" --title en="English Title" \
  [--subtitle zh=… --subtitle en=…] [--langs zh,en] [--author "…"] [--code "CODE//NAME"]
```

- `<slug>`：kebab-case，是目录名、URL 段与下载文件名前缀，发布后不要改。不要用 `example-` 开头（模板的示例书用这个前缀，书库通常隐藏它们）；slug 匹配 `site.toml` 的 `[books] hide` 时书照常创建，但命令会警告它被隐藏。
- `--langs`：逗号分隔的语言代码（小写 ISO 639 代码，可带 `-地区/文字`，如 `pt-BR`），不能重复；第一个是权威版本。每种语言都要有 `--title`。参数有误时不会创建任何文件。
- 生成 `books/<slug>/{book.toml, zh/, en/, assets/}`。补全 `book.toml` 的 `description`、`license`、可选 `isbn`；`code` 是封面与站点卡片上的赛博朋克代号。
- 把 `<slug>` 加入 `site.toml` 的 `[books].order`。

## 新章节

```bash
./tbook new-chapter <slug> ch02-name --title zh="第二章 …" --title en="Chapter 2 …"
```

会在每个语言版本的 `SUMMARY.md` 编号章节末尾追加条目并创建文件；如果末尾有无编号附录，插在附录之前。每个语言版本都要有 `--title`，且都已有 `SUMMARY.md`；先全部校验再写入，出错时不改任何文件，修正参数后直接重试即可。嵌套子章节用 `--parent`，父项可带或不带 `.md`；命令把新条目放在父项已有的全部后代之后、下一个同级章节或部标题之前。父项必须是已存在的编号章节；各语言目录层级不一致时拒绝写入。可以继续指定子章节为父项，创建更深一级。

```bash
./tbook new-chapter <slug> ch02-s01-projections --parent ch02-name \
  --title zh="投影的几何" --title en="Geometry of projections"
./tbook new-chapter <slug> ch02-s01-s01-examples --parent ch02-s01-projections \
  --title zh="手算例子" --title en="Worked examples"
```

文件命名与已有大章的拆分步骤见 `docs/AUTHORING.md` 的“章节命名与长章拆分”。子章节仍使用所属主章的定理编号并接续计数；不会另起一章。

## 新语言版本

1. 在 `book.toml` 的 `editions` 中加入语言代码（如 `"ja"`）；第一个仍是权威版本。
2. 若 `theme/i18n/<lang>.toml` 不存在：复制 `theme/i18n/en.toml` 到仓库根的 `i18n/<lang>.toml` 并翻译。`[meta]` 三项都改成该语言自己的值：`name`（如 `"日本語"`）、`bcp47`（BCP 47 标签，如 `"ja"`）、`short`（版本切换按钮上的标签，如 `"JA"`）；不要沿用 `English` / `en` / `EN`，否则页面的 `lang` 属性与版本切换按钮会把它当成英文。没翻译的键回退到英文。
3. 把它加入 `site.toml` 的 `languages`（站点界面也会提供该语言）。
4. 复制权威版本目录为 `books/<slug>/<lang>/`，保持文件名、顺序、环境序列（种类、`#id`、`lean`）与媒体嵌入不变，逐章翻译（含 `SUMMARY.md` 里的标题）。这一步之前 `./tbook new-chapter` 会拒绝执行，因为新语言还没有 `SUMMARY.md`。
5. 演示文稿：`books/<slug>/slides/` 下的每个 deck 都要加 `slides.<lang>.md`（`./tbook check` 要求每个 deck 覆盖书的全部语言）。复制权威语言的文件（中文是 `slides.md`，其他语言是 `slides.<语言>.md`），逐页翻译：页数与每页的 `layout`、`bare`、`chapter`、`class` 不变，headmatter 的 `htmlAttrs.lang` 设为该语言的 `meta.bcp47`（如 `"ja"`），`deck.code`、`deck.version` 与权威版本相同；`<TheoremCard cite="…">` 的 `label` 改成新语言版本里书的编号（该语言 `[env]` 的名称加编号，如 `定理2.3`；`./tbook check` 会给出应写的值）。写法见 `skills/book-slides`。
6. 可视化（`viz/`）与视频（`films/`）不分语言版本，不需要加文件：可视化页面只有中英两种界面，视频只有中英字幕；新语言的章节照常嵌入它们。
7. `./tbook check` 校验对齐（0 错误）；运行 `./tbook build html --book <slug> --lang <lang>` 并检查日志与适用的自动校验结果。普通导出页面仅在 [book-export](../book-export/SKILL.md) 的视觉排查条件成立时查看。

## 完成标准

`./tbook check` 0 错误；`./tbook build html --book <slug>` 成功；书库首页出现新书卡片。
