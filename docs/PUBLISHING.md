# 构建与发布 · Building and publishing

## 1. 产物

| 产物 | 命令 | 位置 |
| --- | --- | --- |
| 在线 HTML（mdBook） | `./tbook build html` | `build/html/<slug>/<lang>/` |
| PDF 屏幕版（深色霓虹） | `./tbook build pdf --variant screen` | `build/dist/<slug>/<slug>-<version>-<lang>-screen.pdf` |
| PDF 印刷版（白底） | `./tbook build pdf --variant print` | `build/dist/<slug>/<slug>-<version>-<lang>-print.pdf` |
| PDF 学术预印本版（A4 单栏） | `./tbook build pdf --variant academic`（书中须先启用） | `build/dist/<slug>/<slug>-<version>-<lang>-academic.pdf` |
| EPUB 3（Apple Books） | `./tbook build epub` | `build/dist/<slug>/<slug>-<version>-<lang>.epub` |
| 演示文稿 | `./tbook build slides` | `build/slides/<slug>/`（PDF：`<deck>-<lang>.pdf`） |
| 视频 | `./tbook build films`（`--film <NNN>-<name>` 只渲染这几部） | `build/films/<slug>/<film id>/`（`film.json` 的 `outputs` 所列文件），并重新发布到已有站点的 `_site/<slug>/films/` |
| 可视化 | `./tbook build viz` | 重新发布到已有的 `_site/<slug>/viz/`（`viz`、`films` 加 `--book` 只重发选定的书，首页与 manifest 保留其他书） |
| 站点（含可视化、视频） | `./tbook build site` | `_site/` |
| 全部 | `./tbook build all` | 以上全部 |

所有构建命令都接受 `--book <slug>`（可重复）与 `--lang <code>`（可重复）。所选的书都没有 `--lang` 指定的语言版本时，构建报错退出（退出码 2），不会静默跳过。

视频与其他产物一样随站点构建：站点在 `_site/<slug>/films/<film id>/<文件>` 同源托管视频（Content-Type 与按字节范围请求都正确，iOS Safari 需要这两点；Release 附件的地址在那里不能播放），不再为单个视频发 Release；视频计入 GitHub Pages 站点 1 GB 的上限。只构建、托管 `film.json` 的 `outputs` 所列的文件：默认只有 720p 旁白版与封面，50 秒的示例视频共约 6.5 MB（视频 6.1 MB、封面 0.5 MB，另有提交的海报 0.16 MB），约合每分钟 8 MB；同时列出 1080p 旁白版、1080p 与 720p 纯配乐时约 70 MB（每分钟约 84 MB）。渲染视频需要视频工具链（`bash theme/film/setup.sh` 与系统的 ffmpeg）。环境变量 `TBOOK_FILMS` 决定缓存未命中时怎么办：`auto`（默认）有工具链就渲染，没有则警告，站点不含该视频；`require` 无法渲染即构建失败；`skip` 从不渲染。三种情况下缓存命中的视频都照常恢复。

学术预印本的官方技术要求与项目版式选择见 [PDF-TYPOGRAPHY.md](PDF-TYPOGRAPHY.md)。

## 2. 站点

`_site/` 是 GitHub Pages 的产物：书库首页（每本书一张卡片：封面、简介、在线阅读、下载）、每本书的落地页（目录、下载、验证摘要、可视化/视频/幻灯片）、mdBook 页面、下载文件与 `manifest.json`（机器可读清单：版本、文件、sha256、所钉的 trureturing 提交）。所有链接都是相对链接，站点可以挂在 `/<repo>/` 之下。

本地预览：`./tbook serve`（默认端口 8765，自动挂在 Pages 子路径下；支持按字节范围请求，Safari 也能播放视频；`TBOOK_SERVE_HOST=0.0.0.0` 允许其他设备访问，例如用 iPhone 查看）。

## 3. Apple Books

EPUB 按 Apple Books 的要求生成：EPUB 3、MathML 数学、PNG 封面、导航目录与 landmarks、`dc:language` 与 `ibooks:version` 元数据、`META-INF/com.apple.ibooks.display-options.xml`；样式不强制页面背景，在白/米/灰/夜间主题下都可读（夜间主题切换为霓虹强调色）。每次构建后由 epubcheck 校验。

上架 Apple Books 需要通过 Apple Books for Authors / iTunes Producer 提交；若需要 ISBN，在 `book.toml` 的 `[book.isbn]` 中按语言填写，它会成为 EPUB 的标识符。

## 4. 持续集成与发布

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| `ci.yml` | PR、推送到 main、手动、被调用、每周 | 先由仅需标准库的 `tools/ci/plan.py` 生成计划，再启动选中的结构／Lean、theme、unit、manifest、静态媒体、模板兼容检查族，以及按书籍启用格式展开的导出、精确 suite、film 和 slide 集合；空集合不开 runner；同一导出格式合并所选书籍，复用一次安装。viz 最多 8 片、film 最多 4 片，先选择再分片，每项恰一次。稳定必需检查名仍为 **Check**，移到末尾用 `always()` 核对全部计划任务，失败、取消和意外跳过均不通过。调用者须授予 `contents: read`、`actions: read` 与 `pages: read` |
| `pages.yml` | 推送到 `main`、手动 | 共用影响规则，以独立的成功部署覆盖为基准；无站点影响且已有有效部署时跳过安装和构建。需要输出时仍 `./tbook check`、`./tbook build all`，恢复未变单元、补建缺失单元、清理删除内容后完整部署；Pages 未启用时只构建并提示，不记录部署覆盖。唯一保存构建缓存的工作流（§5），同一时间只运行一个 |
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

**选择入口与成功基准。** PR 核对实际 checkout 的 merge parents：head 须与事件相同，base 须等于事件 base 或为其后继；base 前进时按实际被测 merge 重新规划，联合完整累计 `merge-base…head` 差异及可信基准至 merge tree 的差异，base 更新也会纳入。main 不用 push 的 `before` 充当覆盖基准，而是寻找最近可比的成功记录；先前失败或取消的变更不会丢失。手动与 `workflow_call` 的 `selection_mode=auto|full`、`base`（可选的预期成功基准）和 `head`（可选的预期 checkout）含义相同；被调用运行以调用方上下文规划，发布时仍由原发布作业完整组装站点。手动运行按同 ref 查找成功记录，非默认分支的记录只供该分支使用；PR、main、定时与被调用运行读取默认分支的可追溯祖先覆盖，分支记录不能成为默认分支覆盖。显式 `full` 用于诊断和全量验收。

覆盖工件 `tbook-coverage-normal|films|slow|pages` 保留 90 天，记录 SHA、profile、选择器版本、运行时、工具／检查定义摘要、run ID、attempt 与继承的来源 ID。只读取同仓库、对应工作流与所需分支上已完成且成功的 push／手动／定时运行；PR 自产记录与缓存始终不读。只有末尾汇总成功才写记录，读取时还核对整个运行的最终成功结论与 attempt。每个来源工作流搜索限最近 100 个成功运行；工件过期、权限/API/历史缺失、定义或运行时不可比均在摘要显示 **full fallback**，不能当成空集合。Pages 计划作业以 `deployments: read` 核对覆盖所指的 `github-pages` 部署仍为成功状态；CI 成功不能替代部署成功。

影片独立使用 `films` 成功覆盖：CI 实际承担所选影片并通过末尾 Check 时可记录；main／tag push 将影片留给 Pages／Release，不写影片覆盖。Pages 完整严格构建与末尾汇总成功时记录影片覆盖，即使未启用部署也可记录；无构建的 Pages 运行不推进它。影片选择在 CI 与 Pages 的可信成功影片记录中取较新的祖先，以该 SHA 累计比较；已有覆盖且未变的影片跳过。normal 覆盖单独推进不会清除影片责任：Pages 失败、取消或影片证据缺失后，文档 PR／手动 CI 仍选待验证影片，main 仍交给 Pages；全部影片证据缺失时只将影片责任全量回退。影片覆盖不替代独立部署覆盖，也不读取 PR 自产缓存。

纯 `docs/`、`skills/`、项目说明等已知工程文档没有重型消费者；模板仍核对 manifest。未知根路径与共享工具／依赖先保守全量；书内未登记 suite 的额外文件读取先扩大到所属书。现有导出键覆盖整本书，因此书内变动选择该书全部启用格式与语言，不擅自缩窄缓存输入。正文变化覆盖读取 preset／lang／height 的 `stageFirstChecks`；影片的 `film.json scripts` 保留反向依赖；solid 核心与 vendor 变化覆盖实际 viz 与 film 读者。隐藏／删除书不生成假分片，Pages 仍完整组装以删除旧输出。

**额外测试依赖。** 书库可维护自有 `books/<slug>/viz/tests/dependencies.json`，登记每个 suite 在常规对象目录和静态 import 之外读取的文件。路径从仓库根起算，可用 glob；不能用绝对路径或 `..`。声明不存在的 suite、错误 schema 或损坏 JSON 会使计划失败，不能静默跳过。正文仍保守传播到该书全部 suite。以下为通用示例，不要求模板修改书籍内容：

```json
{
  "schema": "tbook-ci-dependencies-v1",
  "suites": {
    "declaration-map.test.mjs": [
      "trureturing.lock.json",
      "books/my-book/zh/SUMMARY.md",
      "books/my-book/zh/*.md"
    ],
    "readout.test.mjs": ["books/my-book/en/*.md", "books/my-book/assets/**"]
  }
}
```

声明须完整列出 suite 的额外读取；没有声明时，任何该书变动都会选择该书未登记的 suite。相对 import 自动跟踪，动态计算的路径、额外页面导航、子进程、文件存在性查询及生成数据的源文件仍须登记。声明是与实际源码对应的完整读取契约；schema 校验、空列表或 glob 未匹配本身不证明没有读取。新增或改变这些读取时须同步复核声明。模板单测用独立 Git fixture 验证传播与回退，不硬编码下游书名。

可比增量模式下，`theme/`、`templates/`、`i18n/` 的执行选择统一沿消费者输入传播，不以共享前缀或资源角色缺失覆盖已知非读者。suite 的输入是自身源码、自身对象目录、registry、支持的相对 import 及完整额外读取声明；声明所列 JS/MJS 模块的相对 import 也会展开，因此同一构造新增 vendor/helper 成员不依赖另一个文件名名单。任一树缺少适用声明（包括新增 suite）时，该 suite 对共享资源仍保守入选，范围跨所有可见书。`kit.solid()` 才加载实体核心及其 vendor 闭包，hub 的 JS/CSS 只由实际打开 hub 的 suite 读取；真实的章节／SUMMARY、CHSH 额外导航、缩略图存在性和 helper 读取仍须完整表达。

影片选择与 `video_unit` 共用 `tools/tbook/film_inputs.py` 的文件输入构造：影片目录及原有排除项、`theme/film/`（排除 `site/`）、`tokens.mjs`、列出的 classic scripts，以及条件 solid 核心／vendor。目录构造覆盖未来成员增删；`engine_data` 和 npm 数据的源路径另外保留，包括书籍元数据、锁文件、包锁和中英主题表／可选本地覆盖。中英语言集合与 `engine_strings` 共用；原本不存在的覆盖文件也有依赖。该提取保留原有文件与生成值的哈希顺序、排除项和输出键范围，源路径不代替生成值进入键。

删除沿旧依赖传播，重命名两端分别分析，已删除消费者不执行。新旧树都必须支持该消费者总结；新增影片或任一端发现不受支持的内联 module import 时，保留该影片的共享读取不确定性，书内变化则保留所属书的这些未知影片。影片脚本在 `out/index.html` 中内联，不能把原源码目录的相对 import 当作实际 URL 的完备证明。现有影片构造的完整性以前提为：脚本自包含，额外资源由已列输入和条件构造提供；任意自定义网络、文件系统、动态生成读取没有通用额外依赖接口，须复核实际源码，无法建立对应时保守扩大影片责任。已有路径、schema、空匹配和当前消费者计数都不证明语义完整；选择器也不宣称能自动发现任意 JavaScript 中未申报的读取。不确定性属于缺少适用总结的消费者，不因一个资源名不存在或缺少角色标签而产生；影片未知不会扩大已有完整总结的浏览器非读者。

浏览器非读者仍可能是发布消费者：`publish_assets` 向每本书复制实体、hub 与 vendor 资源。因此上述执行选择不缩减书籍导出、静态检查、slide 或完整 Pages 组装责任。影片站点资源仍复制发布，但不因而重新渲染非读者影片。工具／检查定义、安装依赖和无法建立整体范围的未知输入，以及显式 full 和不可比成功覆盖，继续遵守既有全量语义。

精确集合通过 JSON 环境变量传给 `viz-test.mjs --selection-env`、`films.py --selection-env`，拒绝不存在、隐藏或重复项。slide 集合按 deck 执行；整书集合沿用原 slides 单元键，部分集合可恢复完整单元，冷构建只运行选中 deck，且不把部分产物写入整书缓存。

**慢帧复查（`viz-slow`）。** `--slow` 令 `VIZ_SLOW_FRAMES=1000`，用于发现固定等待时间造成的偶发失败。每周三的本工作流定时入口只选择 slow profile；手动运行由 `slow_frames` 控制，调用者也可明确传入。slow 使用独立成功基准：相同输入、运行时与检查定义已经覆盖时不开 runner；首次或基准失效则全量 slow fallback。共享运行时、测试工具或 suite 改动后的本地复查仍见 [book-viz](../skills/book-viz/SKILL.md)。

开发分支在 PR 上运行选择后的 CI，不再因分支 push 重复运行；尚未开 PR 时可手动运行。PR 与 main 被新提交取代的 CI 会取消，Pages 仍串行保存缓存并部署。默认分支名称若不是 main，需同步调整两个工作流的 push 分支过滤。分支保护继续要求稳定的 **Check**；媒体分片数量现在动态变化；若曾将单个矩阵检查设为必需检查，维护者须改为 Check。

## 5. 构建缓存

构建单元（每个语言版本的 HTML、每种 PDF、EPUB、每本书的幻灯片、每个视频）的输入没有变化时不再构建，而是恢复存下的产物（`tools/tbook/buildcache.py`；键与本地存储见 `docs/ARCHITECTURE.md`）。视频不是特例，与 PDF、幻灯片走同一条路。查找顺序：

1. 本地存储 `.cache/artifacts/`。在 GitHub Actions 中，组合动作 `.github/actions/build-cache` 在构建前恢复它（Actions 缓存，按前缀 `build-cache-v1-` 先找本次运行所在 ref 的最新一份，再找默认分支的），PR 事件不读 Actions 缓存，改读成功的默认分支 Pages 运行的 `tbook-build-store` 工件；
2. 设置了 `TBOOK_CACHE_REMOTE=1` 时（构建步骤都设置，并传入 `GITHUB_TOKEN`），查最新的 5 个附有 `build-cache.json` 的已发布 Release（手工发的、没有该文件的 Release 不占名额），下载对应的 `cache-*.tar`，核对 SHA-256 后恢复。没有任何 Actions 缓存的构建（新仓库、缓存被清除、PR）由此从整站 Release 恢复；
3. 都没有时构建，并存入本地存储。

只有 `pages.yml` 保存 Actions 缓存：在默认分支上（push 或手动运行）构建后执行 `./tbook cache prune`（只留当前输入的条目），再由 `./tbook cache key` 算出存储内容的摘要 `build-cache-v1-<sha256>`。它与恢复到的键去掉运行后缀 `-r…` 后的部分相同时不再上传；不同时以 `build-cache-v1-<sha256>-r<run id>-<run attempt>` 保存。运行后缀使每次保存都得到一个新键，成为最新的一份：缓存键不能覆盖，存储回到早先的内容（例如回滚）时，若沿用早先的键，保存会因键已存在而落空，恢复就仍取那份更新却已过时的存储。每次保存的是整个存储，仓库的 Actions 缓存超过上限（默认 10 GB）时，GitHub 先淘汰最久未用的条目，恢复总是取最新的一份。构建失败时也保存，已完成的单元（例如先渲染好的视频）不必重做；构建步骤自己的时限（210 分钟）短于作业的时限，超时只让这一步失败，保存照常进行，重新运行或下一次推送从已完成处继续（作业超时会被取消，保存也随之跳过）。`pages` 并发组使它同一时间只运行一个，后一次运行恢复前一次保存的结果。`ci.yml` 只恢复、不保存，`films` 作业在默认分支与 tag 的推送上不构建视频（`pages.yml` 与发版工作流会构建）；`release.yml` 不保存 Actions 缓存，而是把缓存附在 Release 上。

PR 复用 Pages 构建：默认分支成功的 `pages.yml` 在构建后上传 `tbook-build-store`（保留 7 天，含隐藏文件，不压缩已压缩的视频）。PR 用 GitHub API 选择默认分支最近 20 次成功 Pages 运行中仍有工件的一次，核对 workflow ID、源仓库、分支、事件（只允许 push / workflow_dispatch）、完成状态与结果，再按不可混淆的 run ID / artifact ID 下载。需要 `actions: read`；被调用的 CI 的调用者也须授予它。权限不足、工件过期或下载失败时照常构建，仍可从 Release 恢复。PR 自己的 Actions 缓存与工件始终不读；每个构建单元仍按当前输入键与逐文件摘要验证。信任边界见 `docs/VERIFICATION.md` §2。

仍会重复渲染的情形：改动了视频输入且缓存未命中的 PR 仍须渲染。CI 先选择待验证影片，再按完整影片动态分成最多 4 个非空分片，每片通过 `python tools/ci/films.py --selection-env CI_ITEMS` 执行分配的精确集合，所选影片各执行一次；空集合不开影片作业。所选影片缓存未命中时，缺工具链或渲染失败会使作业失败。合入后 Pages 渲染并保存新键，此后 PR 即可复用，无须等待发版。工件超过 7 天、从未成功构建 Pages，或 PR 的输入与默认分支和 Release 都不同，仍会重建。可视化同样先选择 suite，再动态分成最多 8 个非空分片，所选 suite 各执行一次，空集合不开作业。分片减少等待时间，冷构建总计算量不会随之减少；多个分片也会增加工具链安装开销与并发需求。

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

## 7. 学术报告 PDF

`./tbook build slides --book <slug>` 同时构建 Slidev 与学术演示稿。后者用固定 **Tectonic 0.16.9** 与 `default_bundle_v33.tar`，输出 `build/slides/<slug>/<deck>-<lang>.pdf`（听众版，隐藏备注）和 `<deck>-<lang>-notes.pdf`（报告页与演讲备注）。站点在 `<slug>/slides/<deck>/` 下发布两个下载文件与按语言的 PDF 入口页；幻灯片索引、书的落地页与章节卡片包含两种链接，书库 Release 附上两种 PDF。`TBOOK_SLIDES_NO_PDF`/`NO_CHECK` 仍只控制 Slidev 的浏览器导出。

引擎由 `./tbook doctor` 核对精确版本，Linux 安装脚本 `tools/install-tectonic.sh DESTINATION` 校验发布包 SHA-256；容器预装引擎与需要的 TeX 资源，普通托管运行器只在包含学术稿配置的媒体/浏览器作业中安装到本地缓存目录。默认运行器与现有必需检查保持不变。引擎、资源包、固定时间基准、书的章节/图件/可视化、主题与自有主题文件均进入幻灯片缓存键。构建的可复现设置和冷启动联网要求见 [Beamer 说明](../theme/beamer/README.md)。本地可以用 `TECTONIC` 指向已有的同版本引擎。

## 8. 站点构建后命令

书库可在自有的 `site.toml` 中设置 `[site].post_build = ["python3", "docs/project/site.py"]`。
站点成功组装后（包括只更新媒体的情况），构建工具在仓库根目录直接执行这个参数数组，
不经过 shell。环境变量 `TBOOK_SITE_OUT` 指向已组装输出目录的绝对路径。
命令以非零状态退出时构建失败，Pages 不会部署这份产物。
该命令与构建过程一样，属于受信任的仓库代码，可以生成书库特有的清单，
或把书库索引替换为跳转页，同时保留各书的目录与现有 URL。仅在显式配置时执行。
