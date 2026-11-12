---
name: book-film
description: 为书做讲解视频时使用：按 trureturing-film 方案新建并编写视频（确定性 Canvas 动画、Kokoro 英文旁白、程序化配乐、中英双语字幕），本地预览单帧与片段，由构建渲染（未改动时从缓存恢复）并随站点发布，再嵌入书中。
---

# 讲解视频

## 适用范围

**用**：为一章或一组定理制作 1–3 分钟的讲解视频；修改已有视频的脚本或画面；排查视频流水线与构建。

**不用**：可交互的探索（`book-viz`）；面向讲台的演示（`book-slides`）。

**权威**：`templates/film/README.md`（`film.json`、`script.json`、`scenes.js` 规范与流水线）、`theme/film/`（共享引擎与步骤脚本）、`tools/tbook/film.py`（构建单元与站点发布）、示例 `books/example-monograph/films/001-golden-deficit/`。

## 原则

1. **视频是讲解，不是证明。** 片中只有 `film.json` 的 `lean` 列出、且在锁文件中种类为 `theorem` 的声明可以标 `LEAN ✓`（`lean` 列出定义会被 `./tbook check` 报错）；屏幕上的计算用 `badge(a, 'computed')`，论证用 `argued`，开放问题用 `open`。
2. **片中的数字必须精确算出或取自所钉提交。**
3. **旁白英文自然，字幕中文准确**，各一行，不逐字硬译。旁白与字幕写在 `script.json`，它是唯一的时间来源。
4. **颜色只来自令牌**（`C.lean` 绿、`C.now` 琥珀、`C.open` 红、`C.argued` 紫，其余 `C.cyan`、`C.mag`、`C.white`、`C.dim`）。
5. **实体镜头只给曲面与体。** 判据同 `book-viz` 的“具象”：正文点名的对象本身是曲面或体（环面、带、多面体、可行域、球里的东西）时，可以用实体镜头 `solid(…)` 把它画成受光的实体；它是多出来的一种能力，不是统一风格，曲线、格点、矩阵、记号串照旧二维。实体只是画法，依据标注不变：`LEAN ✓` 仍只给 `film.json` 的 `lean` 列出的定理。
6. **仓库只存源码**：`film.json`、`script.json`、`scenes.js`、可选 `data/*.json`、`poster.jpg`（≤ 300 KB）。成片是构建产物，与 PDF 一样：构建写到 `build/films/<slug>/<id>/`，站点托管在 `_site/<slug>/films/<id>/`。没有单独的视频 Release，`film-*` tag 也不发布任何东西。

## 流程

```bash
./tbook film new <book> <NNN>-<name> "<中文标题>" "<English title>"
F=books/<book>/films/<NNN>-<name>
theme/film/setup.sh                  # 每台机器一次：视频 venv（.cache/film/venv）、Kokoro 模型（.cache/film/models）、字体
```

`setup.sh` 把 `theme/film/requirements.txt` 中钉死的包装进独立的视频 venv（Python 3.12 或 3.13），不装进 tbook 的 `.venv`；设置 `PYTHON` 时改为装进该解释器。ffmpeg 来自系统（`apt-get install ffmpeg` 或 `FFMPEG`），Chromium 来自 Playwright 或 `PW_CHROMIUM_PATH`。

1. 写 `script.json`：每个场景 `id`、`name`、`lead`/`tail`、`lines: [[英文旁白, 中文字幕], …]`，可选 `music`、`cues`；发音修正写在 `say`。
2. 写 `scenes.js`：每个场景 `SCENES.<id> = S => { … }`，用 `at(S, k, dur)` / `Q(S, k, '短语')` 与旁白对齐，用 `panel`、`chip`、`stamp`、`leanList`、`closingCard` 等绘制（见 README 的 scenes.js 一节）。
   - 实体镜头（见 README 的“实体镜头”）：`film.json` 加 `"solid": true`；场景里 `const sh = solid('key', { x, y, w, h, yaw, pitch, zoom })`，`sh.begin()` … `sh.surface/poly/glass/tube/line/arrow/ring/bead/fan(…)` … `sh.end(a)`，之后用 `sh.anchor(v)` 放二维标签（`hidden` 时变淡）。与可视化页面共用造型时，把造型写成 `viz/<id>/model.js`，页面在 `main.js` 前加载，`film.json` 写 `"scripts": ["viz/<id>/model.js"]`。每帧按 `S.u` 从头描述，不用时钟与随机数。
   - 引用定理按完整 GID：`leanCite(gid)`；不要按 `short` 查（两条引用可能同短名）。`leanList` 与视频页显示的名字是 Lean 全名，命名空间会被读成别的模块时显示 GID。
   - `Q(S, k, '短语')` 的短语必须原样出现在第 k 句旁白里；`./tbook check` 与 `film.sh $F timeline` 会报出对不上的位置。
3. 填 `film.json`：`title`/`title_zh`、`summary`/`summary_zh`、`publication_basis: "pinned"`（当前出版依据从锁文件解析；真实制作历史才另记 `subject_commit`）、`lean`（片中引用的 GID）、`outputs`（构建产出的文件：默认只有 `narrated_720p`——720p 旁白版，播放器播放它——与 `cover`；确实需要时再列出 `narrated`（1080p 旁白版）、`music_only`（1080p 纯配乐）、`music_only_720p`，列出 1080p 视频时 `resolution` 改为 `1920x1080@30`）。新 GID 后运行 `./tbook pin --refresh`（它收集视频引用的 GID）。
4. 本地迭代（不需要 TTS）：

   ```bash
   theme/film/film.sh $F timeline                 # 暂定时间轴
   theme/film/film.sh $F shot 2 8 14 --poster     # 单帧 → out/shots/，逐张查看
   theme/film/film.sh $F serve                    # 浏览器预览
   theme/film/film.sh $F clip 30 3 960x540        # 3 秒低清片段
   theme/film/film.sh $F poster                   # 生成 poster.jpg，提交入库（只有这一步写它）
   ```

   `./tbook doctor` 会列出缺失的 Chromium、ffmpeg 与字体。
5. 构建视频：

   ```bash
   TBOOK_FILMS=require ./tbook build films --book <book> [--film <NNN>-<name> …]
   ```

   `--film`（可重复）只渲染或恢复这几部，本书其他视频只从缓存恢复、不渲染；`build site`、`build all` 不接受它。

   每部视频是一个构建单元（`./tbook cache status` 中目标为 `films`）：输入未变时从本地缓存恢复，设置 `TBOOK_CACHE_REMOTE=1` 时也从已发布的整站 Release 恢复（本机没有视频工具链时用它取得视频）；都没有时运行 `film.sh <dir> all`（`FILM_STRICT=1`：只用 TTS 实测的时间轴与自托管字体），只编码并复制 `outputs` 所列的文件到 `build/films/<slug>/<id>/`（默认不做 1080p 母版，720p 由帧直接缩放编码；50 秒的示例约 80 秒、成片约 6 MB）。构建不写任何入库文件；`poster.jpg` 只由第 4 步手工更新。渲染后若实际时长与 `film.json` 的 `duration` 不同，构建会警告，按提示更新。
   `TBOOK_FILMS`：`auto`（默认）缓存未命中且工具链齐全时渲染，否则警告并在站点上只显示海报与“视频未构建”；`require` 缺工具链时失败；`skip` 从不渲染（命中缓存仍恢复）。`./tbook build site` 与 `./tbook build all` 同样会渲染或恢复视频。
6. 嵌入章节——**所有语言版本都要加**，`src` 相同，只翻译图注：

   ```markdown
   ::: {.film src="<NNN>-<name>"}
   图注（可含数学与 [@thm-…] 引用）。
   :::
   ```

   本书的视频：HTML 中为 `<video>`，播放站内 `films/<id>/` 的 720p 旁白版，海报为提交的 `poster.jpg`，附 `outputs` 所列视频的下载（默认只有 720p）与视频页链接；站点没有该视频（未构建）时改为显示海报与“视频未构建”。PDF/EPUB 中为海报、图注与站点视频页地址（`site.toml` 没有 `base_url` 时只有海报与图注）。

   外部视频（trureturing-film 的 Release）：`::: {.film src="trureturing-film:film-<NNN>-v<k>"}`。HTML 中为 `<video>`，直接播放该 Release 的旁白版附件 `TRURETURING_<NNN>_narrated_EN_subs_ZH-EN.mp4`，海报为其 `TRURETURING_<NNN>_cover.jpg`，附“观看”（视频文件）与“下载”（Release 页）链接；不经站点托管，也不显示“视频未构建”。Release 附件的地址在 iOS Safari 中不能播放，需要所有读者都能看的视频请做成本书的视频。PDF/EPUB 中没有海报，为标题“trureturing-film 的视频 · film-<NNN>-v<k>”、图注与该 Release 页的地址（不依赖 `base_url`）。
7. `./tbook build site --book <book> && ./tbook serve` 查看视频页 `<slug>/films/` 与章节中的播放器（手机宽度、深浅主题）。`./tbook serve` 支持按字节范围请求，Safari 也能在本地播放；用 iPhone 查看时设置 `TBOOK_SERVE_HOST=0.0.0.0`，从同一网络访问。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `check` 警告 `subject_commit` 与所钉提交不同 | 复核片中陈述；若它记录真实制作历史则保留原值。当前出版用 `publication_basis: "pinned"`，构建自动随锁文件重新渲染 |
| `check` 警告 `release_tag` / `published_tag` 不再使用 | 旧的逐片 Release 字段；删除即可，视频随站点构建 |
| `check` 报 `outputs.narrated_720p is required` 或 `outputs.<键> is not an output` | `outputs` 必须列出 `narrated_720p` 与 `cover`，可选键只有 `narrated`、`music_only`、`music_only_720p`；文件名可取 `./tbook film new` 生成的默认名 |
| 需要 1080p 或纯配乐版本 | 在 `outputs` 中列出 `narrated`、`music_only` 或 `music_only_720p`（1080p 时 `resolution` 改为 `1920x1080@30`）；视频重新渲染，站点只托管、链接所列文件。每分钟视频默认约 7 MB，列出全部输出时约 84 MB，注意 Pages 站点 1 GB 的上限 |
| 站点显示“视频未构建” | 缓存未命中且没有渲染：工具链不全（构建日志列出缺项，运行 `theme/film/setup.sh`）或 `TBOOK_FILMS=skip` |
| 改了章节，视频却重新渲染 | 不应发生：键只含 git 列出的视频文件（不含 `out/`、`poster.jpg`、`README.md`）、`theme/film/`（不含 `site/`）、`theme/generated/tokens.mjs`、`tools/tbook/film.py`、引擎绘制的数据（书的代号、版本与标题，所钉提交，引用的声明及其陈述摘要，片内文字）、字体与 Playwright 的 npm 版本、Kokoro 模型版本与 Node 主版本，不含站点地址。改 `book.toml` 的版本或标题、钉新的 trureturing 提交也会让视频重新渲染（它们属于引擎数据）；用 `./tbook cache status` 与条目的 `entry.json` 比对输入 |
| PR 中视频每次推送都重新渲染 | 预期如此：PR 运行不读也不存 Actions 缓存（防投毒），只从已发布的 Release 恢复；合入后 `pages.yml` 渲染并保存，之后分支与 `main` 上的构建都从缓存恢复，PR 要等某个 Release 附上该键 |
| 本机没有视频工具链 | 设置 `TBOOK_CACHE_REMOTE=1` 构建，从已发布的整站 Release 恢复键未变的视频；改动过的视频仍需工具链渲染（或交给 CI） |
| 页面报 “cannot create a WebGL context” | 这部视频有实体镜头而 Chromium 没有 WebGL；`./tbook doctor` 的 “WebGL for solid shots” 一行给出原因。`theme/film/lib.js` 以 `--enable-unsafe-swiftshader` 启动（SwiftShader，不需要 GPU），不要加 `--use-angle=swiftshader`（它把二维画布也换到 ANGLE，所有帧都会变，且帧与之前画过的帧有关）。不做回退 |
| 实体镜头很慢 | SwiftShader 在 CPU 上画：示例结尾镜头（760×680，120×120 网格环面加 64 颗珠）每帧约 0.65 秒，二维帧约 0.2 秒（4 核、与其他任务同时运行）。网格取够看的密度即可，实体只画在需要的镜头里 |
| `check` 警告 `line k of scene … does not contain …` | `Q`/`badgeQ` 的短语不在该句旁白里，时刻退回句首；按旁白改短语或句号。构建（`FILM_STRICT=1`）时这是错误 |
| 数学符号显示为方框 | 用 `F.math` 字体；CI 安装 `fonts-dejavu-core`、`fonts-freefont-ttf` 作后备 |

## 完成标准

单帧与海报逐张看过；`./tbook check` 通过；`TBOOK_FILMS=require ./tbook build films` 成功；各语言章节都已嵌入，站点视频页、章节播放器（用 `./tbook serve` 在桌面浏览器与 iOS Safari 中实际播放）与 PDF/EPUB 中显示正确。
