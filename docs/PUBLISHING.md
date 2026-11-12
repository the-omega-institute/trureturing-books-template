# 构建与发布 · Building and publishing

## 1. 产物

| 产物 | 命令 | 位置 |
| --- | --- | --- |
| 在线 HTML（mdBook） | `./tbook build html` | `build/html/<slug>/<lang>/` |
| PDF 屏幕版（深色霓虹） | `./tbook build pdf --variant screen` | `build/dist/<slug>/<slug>-<version>-<lang>-screen.pdf` |
| PDF 印刷版（白底） | `./tbook build pdf --variant print` | `build/dist/<slug>/<slug>-<version>-<lang>-print.pdf` |
| EPUB 3（Apple Books） | `./tbook build epub` | `build/dist/<slug>/<slug>-<version>-<lang>.epub` |
| 演示文稿 | `./tbook build slides` | `build/slides/<slug>/`（PDF：`<deck>-<lang>.pdf`） |
| 视频 | `./tbook build films` | `build/films/<slug>/<film id>/`（`film.json` 的 `outputs` 所列文件），并重新发布到已有站点的 `_site/<slug>/films/` |
| 可视化 | `./tbook build viz` | 重新发布到已有的 `_site/<slug>/viz/`（`viz`、`films` 加 `--book` 只重发选定的书，首页与 manifest 保留其他书） |
| 站点（含可视化、视频） | `./tbook build site` | `_site/` |
| 全部 | `./tbook build all` | 以上全部 |

所有构建命令都接受 `--book <slug>`（可重复）与 `--lang <code>`（可重复）。所选的书都没有 `--lang` 指定的语言版本时，构建报错退出（退出码 2），不会静默跳过。

视频与其他产物一样随站点构建：站点在 `_site/<slug>/films/<film id>/<文件>` 同源托管视频（Content-Type 与按字节范围请求都正确，iOS Safari 需要这两点；Release 附件的地址在那里不能播放），不再为单个视频发 Release；视频计入 GitHub Pages 站点 1 GB 的上限。只构建、托管 `film.json` 的 `outputs` 所列的文件：默认只有 720p 旁白版与封面，50 秒的示例视频共约 6.5 MB（视频 6.1 MB、封面 0.5 MB，另有提交的海报 0.16 MB），约合每分钟 8 MB；同时列出 1080p 旁白版、1080p 与 720p 纯配乐时约 70 MB（每分钟约 84 MB）。渲染视频需要视频工具链（`bash theme/film/setup.sh` 与系统的 ffmpeg）。环境变量 `TBOOK_FILMS` 决定缓存未命中时怎么办：`auto`（默认）有工具链就渲染，没有则警告，站点不含该视频；`require` 无法渲染即构建失败；`skip` 从不渲染。三种情况下缓存命中的视频都照常恢复。

## 2. 站点

`_site/` 是 GitHub Pages 的产物：书库首页（每本书一张卡片：封面、简介、在线阅读、下载）、每本书的落地页（目录、下载、验证摘要、可视化/视频/幻灯片）、mdBook 页面、下载文件与 `manifest.json`（机器可读清单：版本、文件、sha256、所钉的 trureturing 提交）。所有链接都是相对链接，站点可以挂在 `/<repo>/` 之下。

本地预览：`./tbook serve`（默认端口 8765，自动挂在 Pages 子路径下；支持按字节范围请求，Safari 也能播放视频；`TBOOK_SERVE_HOST=0.0.0.0` 允许其他设备访问，例如用 iPhone 查看）。

## 3. Apple Books

EPUB 按 Apple Books 的要求生成：EPUB 3、MathML 数学、PNG 封面、导航目录与 landmarks、`dc:language` 与 `ibooks:version` 元数据、`META-INF/com.apple.ibooks.display-options.xml`；样式不强制页面背景，在白/米/灰/夜间主题下都可读（夜间主题切换为霓虹强调色）。每次构建后由 epubcheck 校验。

上架 Apple Books 需要通过 Apple Books for Authors / iTunes Producer 提交；若需要 ISBN，在 `book.toml` 的 `[book.isbn]` 中按语言填写，它会成为 EPUB 的标识符。

## 4. 持续集成与发布

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| `ci.yml` | PR、推送到 main、手动、被调用、每周（只跑 `viz-slow`） | `check` 作业：`./tbook check`、`./tbook theme --check`、全部单元测试、可视化登记校验与幻灯片检查（模板仓库另跑 `./tbook template manifest --check`，并在删去示例书的工作树中、以及用 `site.toml` 的 `[books] hide = ["example-*"]` 隐藏示例书的工作树中重跑检查与单元测试：下游书库可以隐藏或删除示例书，甚至暂时没有书，CI 照样通过）；`build` 作业：HTML、屏幕 PDF、印刷 PDF、EPUB 分 4 个作业并行，产物按 `books-html-html`、`books-dist-pdf-screen`、`books-dist-pdf-print`、`books-dist-epub` 分别上传；`viz` 作业：可视化浏览器回归测试，分 8 片并行（`node tools/node/viz-test.mjs --shard i/8`；每个页面的测试约一分钟，页面多了串行跑会让后面的每次运行排上大半个小时）；`viz-slow` 作业：同样的测试以慢帧（`--slow`，即 `VIZ_SLOW_FRAMES=1000`）分 8 片再跑一遍，只在手动运行（输入 `slow_frames`，默认勾选）与每周三的定时运行中出现，定时运行只跑它，PR 与推送不跑；`media` 作业：幻灯片构建与 PDF；`films` 作业：视频分 4 片严格构建（`TBOOK_FILMS=require`；默认分支推送与 tag 的被调用运行由 Pages / 发版工作流构建视频）。`build`、`media`、`films` 经构建缓存（§5）恢复未变的单元，从不保存；调用者须授予 `contents: read`、`actions: read` 与 `pages: read` |
| `pages.yml` | 推送到 `main`、手动 | `./tbook check` 后构建全部（含视频，`TBOOK_FILMS=require`）并部署 GitHub Pages；Pages 尚未启用时只构建、不部署，并在作业摘要中提示。唯一保存构建缓存的工作流（§5），同一时间只运行一个 |
| `release.yml` | tag `<slug>-v<version>`（单本，须等于 `book.toml` 的 version）或 `v*`（全部书，仅下游书库，如 `v2026.11.08`、`v3.0.0`） | 构建整个站点（含视频），创建 GitHub Release，附所选书的 PDF、EPUB 与幻灯片 PDF（`<slug>-<deck>-<lang>.pdf`），以及全站的构建缓存（`cache-*.tar` 与 `build-cache.json`，§5）；Release 先建为草稿，附件全部上传后才发布，已发布的 Release 不再改动附件；只有语义化版本的预发布（`book.toml` 的 `1.0.0-rc.1`，或 tag `v3.0.0-rc.1`）标为 pre-release；以日期开头的版本（`YYYY.MM.DD`、`YYYY-MM-DD` 或 `YYYYMMDD`，月、日补零）无论后面跟什么都是正式发布，如同一天的第二次发布 `v2026.11.08-2`；以 `film-` 开头、不指向任何书的 tag（旧的逐片视频 tag）只给出提示并跳过，不发布任何东西，可以删除；`site.toml` 的 `[books] hide` 隐藏的书不发布：`v*` 不含它们，指向它们的 `<slug>-v*` 失败并说明原因 |
| `lean-verify.yml` | 每周、手动、可被 Release 调用 | Lake 工程深度验证被引用定理的公理闭包 |
| `trureturing-bump.yml` | 每周、手动 | 把所钉的 trureturing 提交升级到最新并开 PR；标题前缀 `[refused]`（目标提交不在 `site.toml` 的分支上或无法核实）、`[unresolved]`（有引用无法解析）、`[pin failed]`、`[check fails]`、`[review statements]` 提示需要处理的情况；前三种 PR 不改锁文件，与 `[check fails]` 一样以草稿开出 |
| `template-sync.yml` | 每周、手动（仅下游） | 升级到模板新版本并开 PR（有冲突时标题以 `[conflicts]` 开头，`.template-new` 文件一并提交） |
| `template-release.yml` | tag `v*`（仅模板仓库） | 核对版本与清单、跑 CI 后发布模板版本，附示例站点的构建缓存（同样先建草稿、上传后发布） |

检查与构建作业（`ci.yml`、`pages.yml`、`release.yml` 的构建、`trureturing-bump.yml`）通过组合动作 `.github/actions/setup` 安装工具链（Python 3.12 + requirements、Node 22 + `npm ci`、按需安装 Chromium、mdBook 0.5.4、CJK 字体；`films: 'true'` 且有（未隐藏的）书带视频时另装 ffmpeg 与备用字体，运行 `theme/film/setup.sh` 安装 `theme/film/requirements.txt` 并下载 Kokoro 模型到 `.cache/film/models`）。

CI 中没有 trureturing 的 checkout，`./tbook check` 通过 GitHub compare API 核对所钉提交在 `site.toml` 的分支上；GitHub Actions 中无法判定即为错误。因此 `ci.yml`、`pages.yml`、`release.yml` 的检查步骤把 `github.token` 作为 `GITHUB_TOKEN` 传入（`trureturing-bump.yml` 用作业的 `GH_TOKEN`），这些作业至少需要 `contents: read` 权限。

首次使用：Settings → Pages → Source 选 **GitHub Actions**。`site.toml` 的 `base_url` 留空时，站点地址取自 `configure-pages`。可选仓库设置：

- 变量 `REQUIRE_LEAN_VERIFY=true`：Release 前强制深度验证。
- Secret `BOT_TOKEN`：细粒度令牌，Contents、Pull requests、**Workflows** 读写。没有它时，自动 PR 由 `GITHUB_TOKEN` 创建，不会触发 CI，且不能推送 `.github/workflows/` 的改动。
- Secret `TRURETURING_TOKEN`（可选）：只在 trureturing 是私有仓库时需要，能读取该仓库内容的令牌。`check`、`pin` 用它读取冻结状态并通过 GitHub API 核对所钉提交是否在分支上；公开仓库不需要。
- Settings → Actions → General → 勾选 “Allow GitHub Actions to create and approve pull requests”（使用 `GITHUB_TOKEN` 开 PR 时需要）。
- Settings → General → Releases → 启用 **immutable releases**（建议）：已发布的 Release 的附件与 tag 不能再改，从 Release 恢复的构建缓存因此不会被事后替换（`docs/VERIFICATION.md` §2）。工作流先建草稿、上传全部附件再发布，与之兼容。

容器运行方式见 [容器工具链](CONTAINERS.md)：上游提供预装全部工具、浏览器、字体与语音模型的镜像，避免每次作业依赖 Ubuntu 软件源。

**慢帧复查（`viz-slow`）。** 无头浏览器在忙碌的 runner 上可能一秒才给一帧；测试若为过渡或播放等了固定时间，在快机器上通过、在那里偶发失败。`node tools/node/viz-test.mjs [<book>] --slow` 把动画帧拉开到一秒一帧再跑全部（或一本书的）测试，下游 36 个页面分 4 片约需 20 分钟，故不放进 PR 的 CI。何时跑：新写或改了某个页面的测试，交付前在本地对那个测试跑一次（`VIZ_SLOW_FRAMES=1000 node books/<book>/viz/tests/<id>.test.mjs`）；改了共享运行时（`theme/viz/kit.js`、`shell.js`）或测试工具（`tools/node/viz-testkit.mjs`）、升级模板之后，以及 CI 上出现时过时不过的可视化失败时，在 Actions 中手动运行 CI（`slow_frames` 勾选）；其余由每周的定时运行兜底，失败时看作业日志里的 `FAIL` 行，按 `skills/book-viz` 改成 `settle(page)` / `until(page, …)`。`viz-validate` 对测试里的 `waitForTimeout(…)` 报警告，提前指出这类写法。

开发分支在 PR 上运行完整 CI，不再同时因分支 push 重复跑一轮；尚未开 PR 时可手动运行。PR 与 main 上被新提交取代的 CI 会取消，Pages 仍串行保存缓存并部署。默认分支名称若不是 main，需同步调整 `ci.yml` / `pages.yml` 的 push 分支过滤。

## 5. 构建缓存

构建单元（每个语言版本的 HTML、每种 PDF、EPUB、每本书的幻灯片、每个视频）的输入没有变化时不再构建，而是恢复存下的产物（`tools/tbook/buildcache.py`；键与本地存储见 `docs/ARCHITECTURE.md`）。视频不是特例，与 PDF、幻灯片走同一条路。查找顺序：

1. 本地存储 `.cache/artifacts/`。在 GitHub Actions 中，组合动作 `.github/actions/build-cache` 在构建前恢复它（Actions 缓存，按前缀 `build-cache-v1-` 先找本次运行所在 ref 的最新一份，再找默认分支的），PR 事件不读 Actions 缓存，改读成功的默认分支 Pages 运行的 `tbook-build-store` 工件；
2. 设置了 `TBOOK_CACHE_REMOTE=1` 时（构建步骤都设置，并传入 `GITHUB_TOKEN`），查最新的 5 个附有 `build-cache.json` 的已发布 Release（手工发的、没有该文件的 Release 不占名额），下载对应的 `cache-*.tar`，核对 SHA-256 后恢复。没有任何 Actions 缓存的构建（新仓库、缓存被清除、PR）由此从整站 Release 恢复；
3. 都没有时构建，并存入本地存储。

只有 `pages.yml` 保存 Actions 缓存：在默认分支上（push 或手动运行）构建后执行 `./tbook cache prune`（只留当前输入的条目），再由 `./tbook cache key` 算出存储内容的摘要 `build-cache-v1-<sha256>`。它与恢复到的键去掉运行后缀 `-r…` 后的部分相同时不再上传；不同时以 `build-cache-v1-<sha256>-r<run id>-<run attempt>` 保存。运行后缀使每次保存都得到一个新键，成为最新的一份：缓存键不能覆盖，存储回到早先的内容（例如回滚）时，若沿用早先的键，保存会因键已存在而落空，恢复就仍取那份更新却已过时的存储。每次保存的是整个存储，仓库的 Actions 缓存超过上限（默认 10 GB）时，GitHub 先淘汰最久未用的条目，恢复总是取最新的一份。构建失败时也保存，已完成的单元（例如先渲染好的视频）不必重做；构建步骤自己的时限（210 分钟）短于作业的时限，超时只让这一步失败，保存照常进行，重新运行或下一次推送从已完成处继续（作业超时会被取消，保存也随之跳过）。`pages` 并发组使它同一时间只运行一个，后一次运行恢复前一次保存的结果。`ci.yml` 只恢复、不保存，`films` 作业在默认分支与 tag 的推送上不构建视频（`pages.yml` 与发版工作流会构建）；`release.yml` 不保存 Actions 缓存，而是把缓存附在 Release 上。

PR 复用 Pages 构建：默认分支成功的 `pages.yml` 在构建后上传 `tbook-build-store`（保留 7 天，含隐藏文件，不压缩已压缩的视频）。PR 用 GitHub API 选择默认分支最近 20 次成功 Pages 运行中仍有工件的一次，核对 workflow ID、源仓库、分支、事件（只允许 push / workflow_dispatch）、完成状态与结果，再按不可混淆的 run ID / artifact ID 下载。需要 `actions: read`；被调用的 CI 的调用者也须授予它。权限不足、工件过期或下载失败时照常构建，仍可从 Release 恢复。PR 自己的 Actions 缓存与工件始终不读；每个构建单元仍按当前输入键与逐文件摘要验证。信任边界见 `docs/VERIFICATION.md` §2。

仍会重复渲染的情形：改动了视频输入的 PR 仍须渲染，视频按完整的影片分成 4 片（`python tools/ci/films.py --shard i/4`），所有未隐藏的书共用有序列表，空分片通过，缺工具链或渲染失败会失败。合入后 Pages 渲染并保存新键，此后 PR 即可复用，无须等待发版。工件超过 7 天、从未成功构建 Pages，或 PR 的输入与默认分支和 Release 都不同，仍会重建。分片减少等待时间，冷构建总计算量不会随之减少；8 片可视化与 4 片影片也会增加工具链安装开销与并发需求。

键中的工具版本：Node 取主版本（Chromium 由 `package-lock.json` 中的 Playwright 决定，不单独计入），Pandoc、Typst 取“主.次”（精确版本钉在 `requirements.txt`），mdBook 取精确版本（CI 安装的正是 0.5.4）；其余精确版本由 `package-lock.json`、`theme/film/requirements.txt` 与 `.github/actions/setup` 钉住。所以运行器镜像更新 Node 补丁版本或 ffmpeg 包修订，不会让缓存与已发布的 Release 失效。视频的键覆盖 git 列出的视频文件（不含 `out/`、`poster.jpg`、`README.md`）、`theme/film/`（不含 `site/`）、`theme/generated/tokens.mjs`、`tools/tbook/film.py`、引擎绘制的数据（书的代号、版本与标题，所钉提交，引用的声明及其陈述摘要，片内文字）、`package-lock.json` 中 @fontsource 字体与 Playwright 的版本、Kokoro 模型版本与 Node 主版本；不含站点地址，也不含探测到的 ffmpeg、Chromium 与视频 Python，所以没有视频工具链的构建（`TBOOK_FILMS=auto|skip`）也能恢复视频。

每个 Release 都是一个恢复点：`release.yml` 无论 tag 是单本还是全部书，都构建整个站点，`./tbook cache export release/cache` 为每个单元写一个 tar 和清单 `build-cache.json`，与读者下载一并附上（缺少任何单元则失败）；模板仓库的 `template-release.yml` 为示例站点做同样的事。HTML、PDF、EPUB 与幻灯片的键包含站点地址（视频的键不含），所以 `ci.yml`、`release.yml` 与 `pages.yml` 一样用 `actions/configure-pages` 取得的 Pages 地址构建（`site.toml` 设了 `base_url` 时以它为准），各处的键才一致。

本地：`./tbook cache status` 列出每个单元、键与是否已存；`TBOOK_CACHE=0` 关闭缓存（全部重建、不存储）。本地构建默认只查本地存储；设置 `TBOOK_CACHE_REMOTE=1` 时也从已发布的整站 Release 恢复，本机没有视频工具链时可以这样取得视频（视频的键不含站点地址；其他单元的键含站点地址，只有与 Release 构建时的地址相同才能命中）。谁可以写入缓存、为何可以信任 Release，见 `docs/VERIFICATION.md` §2。

## 6. 发版：tag 的原理与步骤

操作清单见 `skills/book-release/SKILL.md`；这里说明发版靠什么触发、触发后发生什么。

### 6.1 tag 是什么

tag（标签）是给某一个提交起的固定名字。分支（如 `main`）会随新提交前进，tag 不会：`example-monograph-v0.1.0` 打在哪个提交上，就永远指向那个提交。所以用它标记“这个版本就是这一刻的内容”：Release 中的 PDF、EPUB 与构建缓存都由这个提交构建。

`git tag` 只在本地创建 tag，GitHub 上什么也不会发生；`git push origin <tag>` 把它推到 GitHub 后，发版才开始。带说明的 tag（`git tag -a … -m …`）与轻量 tag（`git tag …`）都可以。

### 6.2 推送哪种 tag 会发版

`release.yml` 只在推送名字符合下列形式的 tag 时运行，名字决定发布什么：

| tag | 发布什么 |
| --- | --- |
| `<slug>-v<version>`，如 `example-monograph-v0.1.0` | 只发这一本书。`<version>` 必须等于 `books/<slug>/book.toml` 的 `version`，否则工作流失败并说明原因；被 `site.toml` 的 `[books] hide` 隐藏的书不能发 |
| `v<日期或版本>`，如 `v2026.11.08`、`v3.0.0` | 书库：一次发布全部（未隐藏的）书。模板仓库：这类 tag 是模板自身的版本，由 `template-release.yml` 处理，`release.yml` 跳过 |
| `film-…`（旧的单个视频 tag） | 只给出提示并跳过；视频随站点构建，不单独发布 |

名字不是这两种形式的 tag 不触发发版；形如 `<x>-v<y>` 而 `<x>` 不是任何书的 tag 会触发工作流，并以“tag 不指向任何书”失败。

### 6.3 推送之后发生什么

1. GitHub 看到新 tag，在它指向的提交上运行 `release.yml`。
2. 解析 tag，确定发布哪些书，核对版本号；设了仓库变量 `REQUIRE_LEAN_VERIFY=true` 时先跑深度 Lean 验证。
3. 运行 `./tbook check`，再构建整个站点（不只所选的书）。`pages.yml` 通常已经构建过这个提交，没有变化的单元直接从缓存恢复（§5），视频也不必重新渲染。
4. `./tbook cache export` 把每个构建单元写成一个 `cache-*.tar`，并写出清单 `build-cache.json`；有单元缺失时失败。
5. 先建草稿 Release，上传所选书的 PDF（屏幕版、印刷版）、EPUB、幻灯片 PDF 与全部缓存文件，全部上传成功后才发布。说明中列出所钉的 trureturing 提交与定理数。

### 6.4 与“从 Release 恢复”的关系

已发布的 Release 是整站的恢复点。以后没有 Actions 缓存的构建（新仓库、缓存过期被清除、PR 运行，或本地设置 `TBOOK_CACHE_REMOTE=1` 的构建）查最新 5 个附有 `build-cache.json` 的 Release，下载并核对对应的 `cache-*.tar`，恢复后就不必重新编译（§5）。

### 6.5 步骤

1. `./tbook check` 0 错误，`./tbook build all` 成功；改好 `book.toml` 的 `version`，提交并合入 `main`。
2. 在本地取得最新的 `main`，在要发布的提交上打 tag，再推送这个 tag：

   ```bash
   git fetch origin
   git tag -a <slug>-v<version> origin/main -m "<slug> <version>"
   git push origin <slug>-v<version>
   ```

3. 在仓库的 Actions 页看 `Release` 工作流；完成后在 Releases 页核对附件（读者下载与 `build-cache.json` 都在）。

注意：

- 不要在 GitHub 网页上用 “Draft a new release” 建发布。那样会先发布一个没有附件的 Release，随后运行的工作流遇到已发布的 Release 只更新标题与说明，PDF 与缓存文件就附不上去。
- tag 打错了（名字或提交不对）而 Release 还没发布时，删掉重打：`git push origin :refs/tags/<tag>` 删除远端 tag，`git tag -d <tag>` 删除本地 tag，并在 Releases 页删除留下的草稿。已发布的版本不要复用 tag，发一个新的补丁版本。
- 推送 tag 需要对仓库有写权限；只能推送分支的环境（例如受限的自动化会话）推不了 tag，由有权限的人推送。
