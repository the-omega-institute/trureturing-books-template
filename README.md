# trureturing-books-template

**出版“每一条定理都经 Lean 内核验证”的专著。** 一个仓库容纳多本书、多种语言（默认中文与英文），一次编写，导出为在线 HTML、PDF（深色屏幕版 / 白底印刷版）与 Apple Books 兼容的 EPUB，配交互可视化、视频与演示文稿，经 GitHub Pages 与 Release 自动发布。

*Publish monographs in which every theorem is kernel-verified in Lean. Multiple books, multiple languages (Chinese and English by default), one source exported to HTML, PDF (screen and print) and EPUB for Apple Books, with interactive visualizations, films and slides, published automatically to GitHub Pages and Releases.*

| 组成 | 方案 |
| --- | --- |
| 形式化验证 | [trureturing](https://github.com/the-omega-institute/trureturing)：Lean 代码写在那里；书按 GID 引用其已冻结的声明，提交钉在 `trureturing.lock.json` |
| 在线阅读 | [trureturing-mdbook](https://github.com/the-omega-institute/trureturing-mdbook) 的 mdBook 方案（KaTeX 构建期渲染、永久链接） |
| 交互可视化 | [trureturing-visualize](https://github.com/the-omega-institute/trureturing-visualize) 方案（纯 HTML/CSS/JS、双语、理论接口抽屉） |
| 视频 | [trureturing-film](https://github.com/the-omega-institute/trureturing-film) 方案（确定性 Canvas、TTS 旁白、双语字幕） |
| 演示文稿 | [chrono-company-slides](https://github.com/ChronoAIProject/chrono-company-slides) 方案（Slidev、中英逐页对应、PDF 导出） |
| PDF / EPUB | Pandoc → Typst；Pandoc EPUB 3 + MathML |
| 视觉 | trureturing 赛博朋克风，配色唯一来源 `theme/tokens.json` |

## 承诺与检查

书中的 `theorem / lemma / proposition / corollary` 必须写成：

```markdown
::: {.theorem #thm-deficit-three-valued title="亏量只取三个值" lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
对所有自然数 $v_1, v_2$，$c(v_1, v_2) \in \{-1, 0, 1\}$。
:::
```

`./tbook check` 在所钉的 trureturing 提交上读取 `Golden/Frozen/state/<module>.lean.json`——trureturing 冻结律下“已被内核验证并冻结”的唯一判据——确认该声明存在且是 `theorem`；缺少 Lean 引用的定理、引用了 Lean 的开放问题、过期或被手改的锁文件、中英版本不一致，都会让 CI 失败。`lean-verify` 工作流再生成一个依赖所钉 trureturing 的 Lake 工程，逐条检查公理闭包。详见 [docs/VERIFICATION.md](docs/VERIFICATION.md)。

渲染后，每个定理框带绿色 `LEAN ✓` 徽章与指向所钉提交上 Lean 源（含行号）的链接，书末自动生成“形式化验证账本”；锁文件不能确认的形式结论显示红色 `UNVERIFIED`，徽章不是链接，锁文件没有的声明也不给链接（`./tbook check` 会报错，不能发布）。

## 快速开始

1. 在 GitHub 上点 **Use this template** 新建书库并克隆。
2. 安装工具链：

   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```

   ```bash
   npm ci
   ```

   ```bash
   cargo install mdbook --version 0.5.4 --locked
   ```

   ```bash
   ./tbook doctor
   ```

3. 修改 `site.toml`（站点标题、语言），并在 `[books]` 中隐藏模板附带的示例书：

   ```toml
   [books]
   order = ["my-book"]
   hide = ["example-*"]
   ```

   示例书留在 `books/example-*/` 供参考，但检查、构建、站点与发版都当它不存在。不要删除它：以后用 git 合并模板改动时，被删除而模板又改过的示例书会冲突（[docs/UPGRADING.md](docs/UPGRADING.md) §6）。然后新建一本书：

   ```bash
   ./tbook new-book my-book --title zh="我的书" --title en="My Book"
   ```

4. 写作（见 [docs/AUTHORING.md](docs/AUTHORING.md)），引用新的 Lean 声明后：

   ```bash
   ./tbook pin --refresh
   ```

   ```bash
   ./tbook check
   ```

5. 构建与预览：

   ```bash
   ./tbook build all && ./tbook serve
   ```

6. 在 GitHub：Settings → Pages → Source 选 **GitHub Actions**。推送到 `main` 即构建（含视频）并部署；打 tag `<slug>-v<version>` 并推送即发布 Release（PDF、EPUB、幻灯片 PDF 与构建缓存；tag 的原理与步骤见 [docs/PUBLISHING.md](docs/PUBLISHING.md) §6）。输入未变的产物不再重建：CI 从 Actions 缓存或最近的已发布 Release 恢复，PR 运行只从 Release 恢复；本地构建设置 `TBOOK_CACHE_REMOTE=1` 时也从 Release 恢复（[docs/PUBLISHING.md](docs/PUBLISHING.md) §5）。

## 目录

```
site.toml  trureturing.lock.json  template.toml
books/<slug>/{book.toml, zh/, en/, assets/, viz/, films/, slides/}
theme/   tools/   templates/   skills/   docs/   .github/workflows/
```

完整说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 命令

| 命令 | 作用 |
| --- | --- |
| `./tbook doctor` | 工具链体检 |
| `./tbook check` | 结构、多语言对齐、Lean 引用 |
| `./tbook pin [<sha>\|<branch>\|<tag>\|--refresh]` | 钉 trureturing 提交（须在 `site.toml` 的分支上），解析引用 |
| `./tbook new-book` / `new-chapter` | 新书、新章节 |
| `./tbook books [--hidden]` | 列出书库中的书（`site.toml` 的 `[books] hide` 隐藏的书不算；`--hidden` 列出它们） |
| `./tbook build [html\|pdf\|epub\|slides\|viz\|films\|site\|all]` | 构建（输入未变的单元从缓存恢复） |
| `./tbook cache status\|key\|prune\|export` | 构建缓存：输入未变的单元不再构建；各单元状态、存储内容摘要（Actions 缓存键的内容部分）、清理旧条目、导出 Release 附件 |
| `./tbook serve` | 本地预览站点 |
| `./tbook viz\|slides\|film new …` | 新建可视化、演示文稿、视频 |
| `./tbook lean-project` | 生成深度验证 Lake 工程 |
| `./tbook template status\|update` | 模板版本与升级 |

## Agent 与 skills

`CLAUDE.md`（`AGENTS.md` 指向它）是 agent 工作守则；`skills/`（`.claude/skills` 指向它）内置写作、形式化往返、钉版、可视化、视频、演示文稿、导出、发版与模板升级等 skills。`skills/template-update` 负责把书库升级到模板新版本，以及把改进（包括 skills 自身的修订）回馈模板。

## 升级模板

```bash
./tbook template update
```

模板托管的文件（工具、主题、工作流、skills、文档）会被同步，书的内容与配置永不被覆盖；本地改过的托管文件会以 `.template-new` 标出冲突。`template-sync` 工作流每周自动开升级 PR。详见 [docs/UPGRADING.md](docs/UPGRADING.md)。

## 示例

模板附带两本示例书：

- `books/example-monograph/`《黄金整数与可观测性》：四章加一个附录，演示全部写法（各种定理环境、多个 Lean 引用、开放问题与猜想、交叉引用、表格、图、脚注、定义列表、引文）以及书内可视化、视频与演示文稿。内容从 Zeckendorf 进位亏量只取三个值出发，经有限证书与反驳、细化与记忆、黄金词，到齐肯多夫表示与进位的附录。
- `books/example-primer/`《斐波那契与卢卡斯：一本可验证的入门小书》：两章的入门小书，没有媒体，演示一本书最少需要什么。

模板附带的示例书都以 `example-` 开头；书库用 `site.toml` 的 `[books] hide = ["example-*"]` 隐藏它们（见快速开始第 3 步）。

## 许可

模板代码以 Apache-2.0 发布（见 `LICENSE`）。每本书的文本许可在其 `book.toml` 中声明（示例书为 CC-BY-4.0）。

传统学术报告也可用 Beamer：`./tbook slides new <book> <deck> "<title>" --academic --editions en`。白底 4:3（可选 16:9）、定理与 Lean 链接由书和锁生成，输出听众 PDF 与演讲备注 PDF，可使用书库自有主题。见 [theme/beamer/README.md](theme/beamer/README.md)。Slidev 继续提供现有的在线演示。
