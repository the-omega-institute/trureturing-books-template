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
| 视频 | `./tbook build films`（`--film <name>` 只渲染这几部） | `build/films/<slug>/<name>/`（`film.json` 的 `outputs` 所列文件），并重新发布到已有站点的 `_site/<slug>/films/` |
| 可视化 | `./tbook build viz` | 重新发布到已有的 `_site/<slug>/viz/`（`viz`、`films` 加 `--book` 只重发选定的书，首页与 manifest 保留其他书） |
| 站点（含可视化、视频） | `./tbook build site` | `_site/` |
| 全部 | `./tbook build all` | 以上全部 |

所有构建命令都接受 `--book <slug>`（可重复）与 `--lang <code>`（可重复）。所选的书都没有 `--lang` 指定的语言版本时，构建报错退出（退出码 2），不会静默跳过。

EPUB 保留原生 MathML。超宽公式与表格在各自容器内横向滚动，保留完整内容和阅读字号；页面本身应随阅读栏宽度重排。EPUBCheck 验证结构，不能代替已知版面问题处的阅读检查；浏览器原生 MathML 的检查也不等于 Apple Books 实测认证。

默认情况下，视频与其他产物一样随站点构建：站点在 `_site/<slug>/films/<name>/<文件>` 同源托管视频（Content-Type 与按字节范围请求都正确，iOS Safari 需要这两点；Release 附件的地址在那里不能播放），不再为单个视频发 Release；视频计入 GitHub Pages 站点 1 GB 的上限。只构建、托管 `film.json` 的 `outputs` 所列的文件：默认只有 720p 旁白版与封面，50 秒的示例视频共约 6.5 MB（视频 6.1 MB、封面 0.5 MB，另有提交的海报 0.16 MB），约合每分钟 8 MB；同时列出 1080p 旁白版、1080p 与 720p 纯配乐时约 70 MB（每分钟约 84 MB）。渲染视频需要视频工具链（`bash theme/film/setup.sh` 与系统的 ffmpeg）。环境变量 `TBOOK_FILMS` 决定缓存未命中时怎么办：`auto`（默认）有工具链就渲染，没有则警告，站点不含该视频；`require` 无法渲染即构建失败；`skip` 从不渲染。三种情况下缓存命中的视频都照常恢复。

学术预印本的官方技术要求与项目版式选择见 [PDF-TYPOGRAPHY.md](PDF-TYPOGRAPHY.md)。

## 2. 站点

`_site/` 是 GitHub Pages 的产物：书库首页（每本书一张卡片：封面、简介、在线阅读、下载）、每本书的落地页（目录、下载、验证摘要、可视化/视频/幻灯片）、mdBook 页面、下载文件与 `manifest.json`（机器可读清单：版本、文件、sha256、所钉的 trureturing 提交）。站内使用相对链接，站点可以挂在 `/<repo>/` 之下。

在 `site.toml` 的 `[site]` 中设置 `pdf_release_only = true`，常规 CI 和 Pages 构建便会跳过书籍及演示文稿 PDF 导出。Pages 的下载链接直接指向已发布的 GitHub Release 附件（含公开预发布）。书籍按当前 `book.toml` 版本匹配文件名，演示文稿采用最近发布的同名附件。没有对应附件时隐藏该下载链接。Pages 每小时检查已发布附件并刷新主干站点的下载链接。组装站点时需要可访问仓库的 GitHub CLI（`gh`）。本地仍可显式执行 `./tbook build pdf`，或用 `TBOOK_BUILD_RELEASE=1 ./tbook build slides` 导出演示文稿 PDF。

在 `[site]` 中设置 `film_release_only = true` 后，常规 CI 与 Pages 按影片合成旁白和配乐，写入 `build/film-players/<slug>/<name>/`。网页从本站加载 MP3、字体、镜头与所需的三维模型。Media Chrome 提供播放、拖动、音量、倍速和全屏，Canvas 根据音轨时间绘制画面和字幕。日常构建跳过逐帧编码。发书籍或整站 Release（含每日预览）时，工作流把所选书籍的 `film.json` 中列出的每个 MP4 作为独立附件上传。影片页按片名和版本规格链接最近一次已发布的相应附件，首次发布前仍可在线播放。关闭此项可恢复同源 MP4 模式。外部影片引用沿用其来源链接。

本地预览：`./tbook serve`（默认端口 8765，自动挂在 Pages 子路径下；支持按字节范围请求，Safari 也能播放视频；`TBOOK_SERVE_HOST=0.0.0.0` 允许其他设备访问，例如用 iPhone 查看）。

## 3. Apple Books

EPUB 按 Apple Books 的要求生成：EPUB 3、MathML 数学、PNG 封面、导航目录与 landmarks、`dc:language` 与 `ibooks:version` 元数据、`META-INF/com.apple.ibooks.display-options.xml`；样式不强制页面背景，在白/米/灰/夜间主题下都可读（夜间主题切换为霓虹强调色）。每次构建后由 epubcheck 校验。

上架 Apple Books 需要通过 Apple Books for Authors / iTunes Producer 提交；若需要 ISBN，在 `book.toml` 的 `[book.isbn]` 中按语言填写，它会成为 EPUB 的标识符。出版 DOI 写在 `book.toml` 的 `[book].doi`（推荐 Zenodo 概念 DOI）；若省略，构建会从根目录的 `.zenodo.json`、`CITATION.cff` 或 README 中明确的 Zenodo DOI 链接读取。模板不会联网猜测 DOI，也不会把版本 DOI 自动写回源码。

## 4. 持续集成与发布

| 工作流 | 触发 | 作用 |
| --- | --- | --- |
| `ci.yml` | PR、手动、被调用、每周 | 先由仅需标准库的 `tools/ci/plan.py` 生成计划，再启动选中的结构／Lean、theme、unit、manifest、静态媒体、模板兼容检查族，以及按书籍启用格式展开的导出、精确 suite、film 和 slide 集合；空集合不开 runner；同一导出格式合并所选书籍，复用一次安装。viz 最多 8 片。CI 与 Pages 的 film 最多 16 片，所选影片每部恰执行一次，选中 16 部以内时每部独占一片。稳定必需检查名仍为 **Check**，移到末尾用 `always()` 核对全部计划任务，失败、取消和意外跳过均不通过。调用者须授予 `contents: read`、`actions: read` 与 `pages: read` |
| `pages.yml` | `main` 推送、手动、定时刷新 | 每次推送直接进入独占发布队列，当前发布完成后立即处理最新的待发提交。按线上版本到该提交的累计差异选择出版输入，执行 `./tbook check`、组装整站并部署。每个滚动小时最多启动十次出版。缓存见 §5 |
| `release.yml` | tag `<slug>-v<version>`（单本，须等于 `book.toml` 的 version）或 `v*`（全部书，仅下游书库，如 `v2026.11.08`、`v3.0.0`）或启用后的每日预览（§6.6） | 构建整个站点（含视频），创建 GitHub Release，附所选书的 PDF、EPUB 与幻灯片 PDF（`<slug>-<deck>-<lang>.pdf`），以及全站的构建缓存（`cache-*.tar` 与 `build-cache.json`，§5）；Release 先建为草稿，附件全部上传后才发布，已发布的 Release 不再改动附件；tag 发版中，只有语义化版本的预发布（`book.toml` 的 `1.0.0-rc.1`，或 tag `v3.0.0-rc.1`）标为 pre-release；以日期开头的版本（`YYYY.MM.DD`、`YYYY-MM-DD` 或 `YYYYMMDD`，月、日补零）无论后面跟什么都是正式发布，如同一天的第二次发布 `v2026.11.08-2`；以 `film-` 开头、不指向任何书的 tag（旧的逐片视频 tag）只给出提示并跳过，不发布任何东西，可以删除；`site.toml` 的 `[books] hide` 隐藏的书不发布：`v*` 不含它们，指向它们的 `<slug>-v*` 失败并说明原因 |
| `lean-verify.yml` | 每周、手动、可被 Release 调用 | Lake 工程深度验证被引用定理的公理闭包 |
| `trureturing-bump.yml` | 每周、手动 | 把所钉的 trureturing 提交升级到最新并开 PR；标题前缀 `[refused]`（目标提交不在 `site.toml` 的分支上或无法核实）、`[unresolved]`（有引用无法解析）、`[pin failed]`、`[check fails]`、`[review statements]` 提示需要处理的情况；前三种 PR 不改锁文件，与 `[check fails]` 一样以草稿开出 |
| `template-sync.yml` | 每周、手动（仅下游） | 升级到模板新版本并开 PR（标题使用 `chore(template): …`，冲突时在摘要中标注 `[conflicts]`，`.template-new` 文件一并提交） |
| `template-release.yml` | tag `v*`（仅模板仓库） | 核对版本与清单，复用标签提交在默认分支上成功的 CI，无匹配记录时运行 CI，随后发布模板版本，附示例站点的构建缓存（同样先建草稿、上传后发布） |

`ci.yml` 的选择检查从 JSON 文件读取完整计划；CI 与 Pages 的汇总从另一份 JSON 文件读取完整 `needs`，并直接使用其中的 `plan.outputs.plan`，没有第二份计划副本。工作流用带引号的 here-document 接收 `toJSON` 编码的数据，由运行器先写脚本再落盘；计划和汇总载荷不进入进程参数或环境变量，字符串中的换行与 shell 语法不会被执行。矩阵、检查条件、精确浏览器报告核对与覆盖来源保持原有契约；缺少计划、作业结果或执行报告仍使汇总失败。

**仅修改书稿也运行 CI。** `books/<slug>/<lang>/*.md`（含子目录与 `SUMMARY.md`）属于出版输入，选择所属书的结构／多语言检查与启用的导出格式；没有浏览器套件读取该章，也不能省略这些工作。工程文档 `docs/` 与根目录说明的轻量规则不适用于书稿。推送普通工作分支尚未开 PR 时不会自动运行 CI；创建或更新 PR 时触发 CI，合入 `main` 时触发 Pages，编辑 PR 标题／正文只重跑命名检查。排查时先在 Actions 中按工作流和提交 SHA 找运行，再看 **Plan affected work** 的 `coverage.normal.paths` 与 `tasks`：没有运行、任务按计划跳过、排队和旧提交的 Pages 被跳过是不同情况；稳定的 **Check** 必须等所有已选任务成功。

检查与构建作业（`ci.yml`、`pages.yml`、`release.yml` 的构建、`trureturing-bump.yml`）通过组合动作 `.github/actions/setup` 安装工具链（Python 3.12 + requirements、Node 22 + `npm ci`、按需安装 Chromium、mdBook 0.5.4、CJK 字体；`films: 'true'` 且有（未隐藏的）书带视频时另装 ffmpeg 与备用字体，运行 `theme/film/setup.sh` 安装 `theme/film/requirements.txt` 并下载 Kokoro 模型到 `.cache/film/models`）。

`ci.yml` 的验证作业先完成普通单元测试及模板仓库的删除／隐藏示例兼容检查，再用同一安装动作启用 Chromium，执行 `PYTHONPATH=tools python tools/tests/test_export_layout.py` 的必需 EPUB 布局回归。普通测试发现模式按工具链体检的 Chromium 可用性保持可选；独立入口遇到缺依赖、跳过或失败均以非零状态退出，验证作业时限仍为 30 分钟。

CI 中没有 trureturing 的 checkout，`./tbook check` 通过 GitHub compare API 核对所钉提交在 `site.toml` 的分支上；GitHub Actions 中无法判定即为错误。因此 `ci.yml`、`pages.yml`、`release.yml` 的检查步骤把 `github.token` 作为 `GITHUB_TOKEN` 传入（`trureturing-bump.yml` 用作业的 `GH_TOKEN`），这些作业至少需要 `contents: read` 权限。

首次使用：Settings → Pages → Source 选 **GitHub Actions**。`site.toml` 的 `base_url` 留空时，站点地址取自 `configure-pages`。可选仓库设置：

- 变量 `REQUIRE_LEAN_VERIFY=true`：Release 前强制深度验证。
- Secret `BOT_TOKEN`：细粒度令牌，Contents、Pull requests、**Workflows** 读写。没有它时，自动 PR 由 `GITHUB_TOKEN` 创建，不会触发 CI，且不能推送 `.github/workflows/` 的改动。
- Secret `TRURETURING_TOKEN`（可选）：只在 trureturing 是私有仓库时需要，能读取该仓库内容的令牌。`check`、`pin` 用它读取冻结状态并通过 GitHub API 核对所钉提交是否在分支上；公开仓库不需要。
- Settings → Actions → General → 勾选 “Allow GitHub Actions to create and approve pull requests”（使用 `GITHUB_TOKEN` 开 PR 时需要）。
- Settings → General → Releases → 启用 **immutable releases**（建议）：已发布的 Release 的附件与 tag 不能再改，从 Release 恢复的构建缓存因此不会被事后替换（`docs/VERIFICATION.md` §2）。工作流先建草稿、上传全部附件再发布，与之兼容。

容器运行方式见 [容器工具链](CONTAINERS.md)：上游提供预装全部工具、浏览器、字体与语音模型的镜像，避免每次作业依赖 Ubuntu 软件源。

**选择入口与比较基准。** PR 核对实际 checkout 的两个父提交，用第一父提交至合并树的差异规划。主干 push 用事件的 `before` 至 `after`，一次推送中的多个提交共同计算。选择完成后，可信耗时记录可用于已选浏览器任务分片。手动与被调用的工作流可传入 `base` 和预期 `head`，显式 `full` 用于诊断。定时慢帧与未指定基准的手动运行按各自最近可比的成功记录计算累计变化。Pages 单独比较已成功部署的状态，以覆盖相邻发布间积累的变化。

覆盖工件 `tbook-coverage-normal|films|slow|pages` 保留 90 天，记录 SHA、profile、选择器版本、运行时、工具链环境摘要、run ID、attempt 与继承的来源 ID。只读取同仓库、对应工作流与所需分支上已完成且成功的 push／手动／定时运行；PR 自产记录与缓存始终不读。只有末尾汇总成功才写记录，读取时还核对整个运行的最终成功结论与 attempt。每个来源工作流搜索限最近 100 个成功运行；工件过期或工具链环境不可比时，改用最近同来源的成功运行树计算差异；首次运行使用事件的 PR base、push before 或上一提交，显式 `base` 优先。摘要列出实际比较 SHA，并标明没有继承覆盖；历史不足以计算差异时计划失败，要求补充基准，不自动启动全量浏览器。Pages 计划作业以 `deployments: read` 核对覆盖所指的 `github-pages` 部署仍为成功状态；CI 成功不能替代部署成功。

PR 的影片范围来自本次文件差异与影片渲染器的输入。主干 push 将影片留给 Pages。手动运行可依据 CI 或 Pages 成功完成的影片记录核对待验证影片。影片读取的钉版提交、引用声明、经典脚本和 solid 运行时均计入相关依赖。

纯 `docs/`、`skills/`、项目说明等已知工程文档没有重型消费者；模板仍核对 manifest。未知根路径与安装依赖仍保守覆盖全部可能读者；书内未登记 suite 的额外文件读取先扩大到所属书。章节变化选择本书启用的导出。书内浏览器测试源码只调度验证，mdBook 和 EPUB 主题分别选择 HTML 和 EPUB。PDF 与 EPUB 的静帧分片比较页面、截图运行时、锁文件用途和已出版章节引用的卡片与语言。导出任务从可信存储恢复其余所需图片，冷缓存时自行补齐。正文变化仅覆盖引用该页面的章节与显式声明的额外正文读取，保留 preset／lang／height 的 `stageFirstChecks`；影片的 `film.json scripts` 保留反向依赖；solid 核心与 vendor 变化覆盖实际 viz 与 film 读者。隐藏／删除书不生成假分片，Pages 仍完整组装以删除旧输出。

`template.toml` 仅变更 `[template].version` 时，先按现有模板工具配置契约与语义版本解析新旧文件，并严格比较其余全部解析值（包括未知字段与值类型）。确认属于版本元数据后，选择读取模板配置和复制模板夹具的既有单元检查族，模板仓库另保留兼容检查与 manifest 检查；这些检查族只运行选中的测试类，浏览器回归单独选择；兼容工作树复用同一份测试清单。额外 suite 声明与影片输入构造中的真实读取在分类前传播，不因元数据分类消失；书内与共享资源的未知读取回退规则不变。普通 CI 不因此选择无关 suite、影片、幻灯片或导出；Pages 的页脚与站点 `manifest.json` 确实读取模板版本，因此仍完整组装站点，并沿用可信构建缓存。其他字段变化、无效配置／版本或任一配置文件缺失时仍保守覆盖可能读者。工具源码修改按新旧依赖传播，不再使整轮浏览器覆盖失效；环境签名保留安装依赖与工具链，忽略运行器每日镜像修订号。旧记录可用其生产树与已记录环境重新比较，成本建议仍受执行定义指纹约束；条件回放不表示新 CI／部署成功。

**本地与 CI 共用测试选择。** `./tbook test --list` 显示从 `origin/main` 分支点到工作区的改动及选择，包含提交、暂存、未暂存与未跟踪文件；`--base <ref>` 更换基准。选择规则相同，本地是否执行按改动的性质决定：只改章节正文文字（含定理环境属性、交叉引用及随之的钉版锁文件）时，本地只运行受影响书籍的 `./tbook check`，所选浏览器套件、影片、幻灯片与导出检查留给 PR 的 CI；改动触及媒体引用块、媒体源文件、工具、主题或工作流时，本地照常运行所选测试。`./tbook test` 只运行所选单元测试类、浏览器回归与可视化父套件；空集合直接结束。`--slow` 仅作用于所选可视化，`--full` 明确请求全量。Python 测试沿新旧静态导入闭包选择，动态载入与非 Python 资源在 `tools/ci/testing.py` 的 `EXTRA` 中登记；昂贵浏览器类在 `BROWSER` 中声明实际输入，测试夹具变动同样传播。新增自定义读取须同步这些声明，不假定静态导入能发现任意文件读取。CI 用计划中的同一清单执行，只有选中浏览器类才安装 Chromium；被选中的必需浏览器测试发生跳过也算失败。

CI 在计划选中下游作业时解析一次分支锁。分片按计划输出的工件 ID 从同一次运行下载快照并核对提交号。局部重跑使用原计划工件，整轮重跑重新解析。固定提交锁从检出的源码读取。

**额外测试依赖。** 书库可维护自有 `books/<slug>/viz/tests/dependencies.json`，登记每个 suite 在常规对象目录和静态 import 之外读取的文件。路径从仓库根起算，可用 glob；不能用绝对路径或 `..`。声明不存在的 suite、错误 schema 或损坏 JSON 会使计划失败，不能静默跳过。`@citations` 使用正式出版块解析器，将正文依赖缩小到引用该 suite 对应可视化的章节。目录变动按各版本中实际引用该可视化的章节序列选择，直接读取目录的 suite 另列文件或 glob；旧、新两端取并集，移动或删除引用仍会选中原读者。章中文字的直接读取必须另列精确路径；依赖清单本身只影响未来选择，修改它不单独重跑页面。没有适用声明的 suite 仍保守扩大到所属书。以下为通用示例，不要求模板修改书籍内容：

```json
{
  "schema": "tbook-ci-dependencies-v1",
  "suites": {
    "declaration-map.test.mjs": [
      "trureturing.lock.json",
      "books/my-book/zh/SUMMARY.md",
      "books/my-book/zh/*.md"
    ],
    "readout.test.mjs": ["@citations", "books/my-book/assets/**"]
  }
}
```

声明须完整列出 suite 的额外读取；没有声明时，任何该书变动都会选择该书未登记的 suite。相对 import 自动跟踪，动态计算的路径、额外页面导航、子进程、文件存在性查询及生成数据的源文件仍须登记。声明是与实际源码对应的完整读取契约；schema 校验、空列表或 glob 未匹配本身不证明没有读取。新增或改变这些读取时须同步复核声明。模板单测用独立 Git fixture 验证传播与回退，不硬编码下游书名。

可比增量模式下，`theme/`、`templates/`、`i18n/` 的执行选择统一沿消费者输入传播，不以共享前缀或资源角色缺失覆盖已知非读者。suite 的输入是自身源码、自身对象目录、registry、支持的相对 import 及完整额外读取声明；声明所列 JS/MJS 模块的相对 import 也会展开，因此同一构造新增 vendor/helper 成员不依赖另一个文件名名单。任一树缺少适用声明（包括新增 suite）时，该 suite 对共享资源仍保守入选，范围跨所有可见书。`kit.solid()` 才加载实体核心及其 vendor 闭包，hub 的 JS/CSS 只由实际打开 hub 的 suite 读取；真实的章节／SUMMARY、CHSH 额外导航、缩略图存在性和 helper 读取仍须完整表达。

影片选择与 `video_unit` 共用 `tools/tbook/film_inputs.py` 的文件输入构造：影片目录及原有排除项、`theme/film/`（排除 `site/`）、`tokens.mjs`、列出的 classic scripts，以及条件 solid 核心／vendor。目录构造覆盖未来成员增删；`engine_data` 和 npm 数据的源路径另外保留，包括书籍元数据、锁文件、包锁和中英主题表／可选本地覆盖。中英语言集合与 `engine_strings` 共用；原本不存在的覆盖文件也有依赖。该提取保留原有文件与生成值的哈希顺序、排除项和输出键范围，源路径不代替生成值进入键。

删除沿旧依赖传播，重命名两端分别分析，已删除消费者不执行。新旧树都必须支持该消费者总结。新增或修正的完整 suite 声明仅在它描述的全部文件集合与内容（含二进制资源、测试与 import 闭包）在两端完全相同时复用于旧树，避免补声明或收窄过宽的正文 glob 时重跑未变页面；任一实际输入有变化仍保留旧声明。新增影片或任一端发现不受支持的内联 module import 时，保留该影片的共享读取不确定性，书内变化则保留所属书的这些未知影片；已有完整输入构造的影片只沿真实读取选择，书内统计数据等非读者资源不触发重渲染。影片脚本在 `out/index.html` 中内联，不能把原源码目录的相对 import 当作实际 URL 的完备证明。现有影片构造的完整性以前提为：脚本自包含，额外资源由已列输入和条件构造提供；任意自定义网络、文件系统、动态生成读取没有通用额外依赖接口，须复核实际源码，无法建立对应时保守扩大影片责任。已有路径、schema、空匹配和当前消费者计数都不证明语义完整；选择器也不宣称能自动发现任意 JavaScript 中未申报的读取。不确定性属于缺少适用总结的消费者，不因一个资源名不存在或缺少角色标签而产生；影片未知不会扩大已有完整总结的浏览器非读者。

浏览器非读者仍可能是发布消费者：`publish_assets` 向每本书复制实体、hub 与 vendor 资源。因此上述执行选择不缩减书籍导出、静态检查、slide 或完整 Pages 组装责任。影片站点资源仍复制发布，但不因而重新渲染非读者影片。生产工具源码按完整读取声明传播；`tools/ci/`、`tools/tests/` 和 CI 工作流本身只选择相关测试及已声明的实际读者，不触发出版构建。安装依赖、未知输入与显式 full 保留各自的完整影响范围；缺少可比覆盖时按上述 Git 差异选择。

直接运行 `node tools/node/viz-test.mjs [book ...]` 也默认复用上述工作区选择规则；书名仅过滤受影响集合，不会触发整本书。`--base <ref>` 更换比较基准，`--list` 只列所选套件，`--shard` 在所选集合上分片，`--slow` 只降低所选套件的动画帧率。只有显式 `--full` 才运行范围内全部套件；缺少比较历史时报错，不自动回退全量。工具链镜像验收显式使用 `--full`，以保留完整示例覆盖。

精确集合通过 JSON 环境变量传给 `viz-test.mjs --selection-env`、`films.py --selection-env`，拒绝不存在、隐藏或重复项。可视化的显式集合直接执行，不再按本地 Git 差异过滤，也不能与 `--base` 或 `--full` 混用。slide 集合按 deck 执行；整书集合沿用原 slides 单元键，部分集合可恢复完整单元，冷构建只运行选中 deck，且不把部分产物写入整书缓存。

**可选执行分部与时间预算。** 父 suite 的影响选择保持不变。仅对实测过重的 suite，可在书库自有 `books/<slug>/viz/tests/execution-parts.json` 声明有限、非空、不重复的分部：

```json
{
  "schema": "tbook-viz-parts-v1",
  "suites": {"readout.test.mjs": ["checks", "transitions"]}
}
```

分部标识只用小写字母、数字与连接号，每套最多 64 个。父脚本读取 `VIZ_TEST_PART`，对每个声明值运行对应的独立完整检查子集，拒绝未知值；未设置或空值仍运行原有全部检查。作者负责证明子集无漏项、无重复、没有跨分部状态依赖，明确新会话的字体／实体／控件前置条件；不得减少真实重绘、刷新或等待来换取速度。相对 import 的 helper 自动继承父输入，其他真实读取仍按完整 `dependencies.json` 登记。分部元数据变化只选择契约改变的父 suite；缺少读取总结时仍按原规则保守扩大。所有被选父 suite 的全部分部必须成功，才允许推进父覆盖。

CI 精确项为 `books/<slug>/viz/tests/<id>.test.mjs#<part>`，未分部仍为父路径。`--selection-env` 接受这些项并拒绝父与其分部重叠、隐藏／未知／重复项；直接点父路径和原有 `--shard` 仍按完整 suite 运行。`--report <path>` 在每个子进程结束时原子写入单调时钟秒数、退出码、帧配置、运行与尝试标识及 runner 身份。稳定 Check 下载本次运行的工件，按计划核对精确集合及来源，失败、缺失或重复报告使 Check 失败。报告工件按运行尝试隔离，整轮重跑不会下载旧尝试遗留的分片；计划与报告须来自同一次尝试，局部重跑后须重新运行整轮。影片、缓存和完整 Pages 责任不变。

每个 profile 仅在既有可信成功覆盖记录中保留每个存活单元的一份最新建议耗时。执行定义指纹覆盖父测试、其静态 import／helper 与分部声明，另保存父实际输入的工作负载指纹及实测来源运行；记录沿既有运行时／工具链签名与生产者校验继承，PR 工件不提供默认分支覆盖或成本基准。正常帧不能为慢帧定价；改变测试／helper／分部、缺失／损坏建议值或不兼容运行时使受影响的已选单元单独执行，不重测未选父套来采样。页面／数据变化可沿用相同执行定义的建议值，但计划逐项列出 `changed_workloads`，保留原样本的工作负载与实测来源；不能把它当作新工作负载的耗时保证。显式 full 仍全量执行，可复用可信成本但不继承覆盖。冷启动因此可能暂时产生每单元一个作业。选择先于装箱，空选择不开作业或安装。

已知成本采用确定性的最长任务优先装箱，增加作业数直到预计完整作业达到 900 秒目标；执行成本乘 1.25，另预留 120 秒给安装、server、报告和收尾。矩阵最多 256 个作业，超限明确失败；单个不可分单元超目标／预计达到 1200 秒会明确标记预算问题并仍执行。原有失败超时保留，不能把取消当覆盖。裕量依据实际 38–67 秒非测试开销，只是规划假设。采用后必须以实际完整作业开始至结束验收每片 **小于 1200 秒**、争取不超过 900 秒，另报排队与计划等待；超过目标要解释并调整粒度／装箱。运行时增长、额外初始化、安装超过预留或并发不足导致两波排队都会使预测失效。首次采用与 slow 实际预算仍需各自实测，计划等重不表示实测等时。

**慢帧复查（`viz-slow`）。** `--slow` 令 `VIZ_SLOW_FRAMES=1000`，用于发现固定等待时间造成的偶发失败。每周三的本工作流定时入口只选择 slow profile；手动运行由默认关闭的 `slow_frames` 控制，调用者也可明确传入。slow 使用独立成功基准：相同输入、运行时与检查定义已经覆盖时不开 runner；首次或基准失效按实际 Git 差异选择，无法比较时明确失败；不因覆盖工件缺失而全量慢帧复测。共享运行时、测试工具或 suite 改动后的本地复查仍见 [book-viz](../skills/book-viz/SKILL.md)。

开发分支在 PR 上运行选择后的 CI。同一 PR 的新提交取代先前的检查。主干推送直接进入 Pages，整个工作流共用 `pages` 并发组。运行中到达的推送合并为一个待发版本，其中包含自线上版本以来的所有出版改动。默认分支采用其他名称时，请调整 `pages.yml` 的 push 分支过滤。分支保护要求稳定的 **Check** 与 **PR conventions**，见[贡献与协作规范](../CONTRIBUTING.md)。

推送、手动运行和定时刷新共用滚动 60 分钟的十次启动额度。工作流在 `tbook-pages-build` 环境记录启动时间，失败的出版也占一格。额度用尽时，当前工作流等到最早一格到期后继续。每小时检查 Release 下载链接，每日 05:17 UTC 检查上游冻结声明。无出版变化的自动检查直接结束。Pages 未启用时，首次构建仍提供站点工件。

## 5. 构建缓存

视频分片使用 `scope: films`：默认分支优先恢复 `film-cache-v1-`，PR 只读取可信成功 CI／Pages 发布的 `tbook-film-store`，恢复到 `.cache/artifacts/films/`。独立缓存不包含 PDF、EPUB 和静帧；视频工件按名称分页检索，分页范围由首次返回的工件总数限定，再校验其所属运行，不受最近 20 次无关成功运行的窗口限制；只有实际完成视频任务的 CI 汇总或成功完整构建的 Pages 发布它，纯导出 CI 不覆盖它。完整站点／Release 构建与 CI 汇总用 `film-baseline: true` 将最新可信视频库存先独立下载、逐条原子合并，再导入本次分片，保留未选影片的较新缓存；普通导出作业只恢复本格式所需的缓存。升级初期没有独立缓存时仍恢复旧完整缓存，并按旧归档的根目录解包。视频单元的输入键、完整性校验与 PR 信任边界沿用原契约；输入变化仍须重建。

CI 中的 PDF、EPUB 导出只预取可视化静帧库存。默认分支优先查 `image-cache-v1-`，其他恢复走成功的默认分支 CI 或 Pages 运行发布的 `tbook-image-store`。库存缺少当前所需的静帧时，按输入键从 Release 恢复或生成。HTML 和幻灯片直接按单元输入键从 Release 恢复或构建。各格式继续使用相同的 Pages 地址计算链接和缓存键。

构建单元（每个语言版本的 HTML、每种 PDF、EPUB、每本书的幻灯片、每个视频）的输入没有变化时不再构建，而是恢复存下的产物（`tools/tbook/buildcache.py`；键与本地存储见 `docs/ARCHITECTURE.md`）。完整站点、发行和 CI 汇总的查找顺序：

1. 本地存储 `.cache/artifacts/`。在 GitHub Actions 中，组合动作 `.github/actions/build-cache` 在构建前恢复它（Actions 缓存，按前缀 `build-cache-v1-` 先找本次运行所在 ref 的最新一份，再找默认分支的），Actions 缓存未命中时从默认分支成功的 CI 或 Pages 运行恢复对应工件（完整存储为 `tbook-build-store`）；
2. 设置了 `TBOOK_CACHE_REMOTE=1` 时（构建步骤都设置，并传入 `GITHUB_TOKEN`），查最新的 5 个附有 `build-cache.json` 的已发布 Release（手工发的、没有该文件的 Release 不占名额），下载对应的 `cache-*.tar`，核对 SHA-256 后恢复。没有任何 Actions 缓存的构建（新仓库、缓存被清除、PR）由此从整站 Release 恢复；
3. 都没有时构建，并存入本地存储。

`pages.yml` 与默认分支成功的 CI 聚合都保存 Actions 缓存。Pages 构建后执行 `./tbook cache prune`（只留当前输入的条目），再由 `./tbook cache key` 算出存储内容的摘要 `build-cache-v1-<sha256>`。它与恢复到的键去掉运行后缀 `-r…` 后的部分相同时不再上传；不同时以 `build-cache-v1-<sha256>-r<run id>-<run attempt>` 保存。运行后缀使每次保存都得到一个新键，成为最新的一份：缓存键不能覆盖，存储回到早先的内容（例如回滚）时，若沿用早先的键，保存会因键已存在而落空，恢复就仍取那份更新却已过时的存储。每次保存的是整个存储，仓库的 Actions 缓存超过上限（默认 10 GB）时，GitHub 先淘汰最久未用的条目，恢复总是取最新的一份。Pages 在构建失败时也保存，已完成的单元（例如先渲染好的视频）不必重做；构建步骤自己的时限（210 分钟）短于作业的时限，超时只让这一步失败，保存照常进行，重新运行或下一次推送从已完成处继续（作业超时会被取消，保存也随之跳过）。`pages` 并发组使它同一时间只运行一个，后一次运行恢复前一次保存的结果。`films` 作业在默认分支与 tag 的推送上不构建视频（`pages.yml` 与发版工作流会构建）；`release.yml` 不保存 Actions 缓存，而是把缓存附在 Release 上。

视频和静帧缓存各自按所含单元与输入键计算摘要。默认分支发布时先查询最近一份同类缓存，内容变化或缓存被淘汰时才上传。回滚到历史输入时，新保存的缓存带有本次运行编号，后续按前缀恢复时仍能取得当前版本。PR 使用的工件按原有保留期续存。

CI 的构建、幻灯片与影片作业在恢复后记录已验证条目的键，上传构建中新增的完整条目；CI 与 Pages 的影片分片同时交付所选影片的已验证命中条目，避免独立视频基准中的命中项在差量传输时丢失（`tools/ci/cache_store.py snapshot|export`；临时分片保留 1 天）。稳定 Check 先确认全部计划作业成功，再恢复已有存储，按本次运行尝试分别下载分片并逐条校验、原子合并，最后保存 Actions 缓存与 `tbook-build-store`。相同输入键可能因编码器而有不同字节，合并保留一份完整有效条目，绝不逐文件覆盖混合两种编码。Check 没有出版字体或工具，不重新计算 PDF 等当前键；它只保留每个单元两个已验证键，优先保留本次已选分片交付的键，再按创建时间取舍；这也保留回滚后命中的较早视频键；同时清理损坏条目、链接与其他未验证文件（动作 `prune: 'false'` 仅供 `check` 聚合使用）。这条写入链只在默认分支的 push、workflow_dispatch、schedule 中运行；PR、其他分支、失败或取消的计划均不发布聚合存储。除所选影片的命中条目外，仅新增条目跨作业上传；完整存储仍需在聚合时下载和发布；这部分传输成本不会消失。缓存传输失败只导致后续缓存未命中，不改变检查结果。

完整缓存未命中的构建、发布和汇总可复用默认分支产物。成功的 `ci.yml` 聚合与 `pages.yml` 构建以压缩等级 1 上传 `tbook-build-store`（保留 7 天，含隐藏文件）。恢复步骤用 GitHub API 分别检查默认分支最近 100 次成功 CI 与 Pages 运行，从新到旧选择仍有工件的一次，核对 workflow ID、源仓库、分支、事件（push / workflow_dispatch，CI 另允许 schedule）、完成状态与结果，再按不可混淆的 run ID / artifact ID 下载。需要 `actions: read`；被调用的 CI 的调用者也须授予它。权限不足、工件过期或下载失败时照常构建，仍可从 Release 恢复。独立静帧与影片缓存按工件名称查询，并对运行来源做同样的校验。只在默认分支成功的生产者中选取工件，每个构建单元仍按当前输入键与逐文件摘要验证。信任边界见 `docs/VERIFICATION.md` §2。

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

`release.yml` 根据推送的 tag 名字确定发布范围。

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

### 6.6 每日预览

在书库默认分支的 `site.toml` 中启用。

```toml
[release]
preview_branch = "main"
```

GitHub Actions 每天 03:17 UTC 检查指定分支。该分支须包含支持此设置的 Release 工作流。`preview_branch` 优先于旧的 `daily_dev_preview = true` 设置，后者仍选择 `dev`。未配置预览分支和旧开关时默认关闭，显式设为 `preview_branch = ""` 也会关闭。

每个 UTC 日最多发布一次，每个提交最多预览一次。tag 为 `preview-<完整提交 SHA>`，`dev` 分支继续使用 `preview-dev-<完整提交 SHA>`。当日已发布、提交已有预览或分支尚未建立时，工作流会跳过构建。

在 Actions 的 **Release** 页面可从默认分支手动触发同一流程。构建使用启动时预览分支的确切提交，按 §6.3 检查并生成所有可见书籍的 PDF、EPUB、幻灯片 PDF 与构建缓存。附件齐全后发布为 GitHub pre-release。读者在对应的 Releases 页面下载预览。官网的 PDF 下载页从版本发行附件生成链接。

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
