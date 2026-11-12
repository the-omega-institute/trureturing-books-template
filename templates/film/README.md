# 视频模板 · Film template

本目录是 `./tbook film new` 的起始模板；每部视频按 [trureturing-film](https://github.com/the-omega-institute/trureturing-film) 的方案完全由代码生成：确定性的 Canvas 动画、本地合成的英文旁白（Kokoro-82M）、程序化配乐，内嵌中英双语字幕。仓库只存源码；成片与 PDF 一样是构建产物：`./tbook build films|site|all` 渲染（输入未变时从缓存恢复）到 `build/films/<slug>/<id>/`，站点托管在 `<slug>/films/<id>/`，书中以 `<video>` 嵌入。

This directory is the starting point of `./tbook film new`. Every film follows the trureturing-film scheme and is generated entirely by code: a deterministic Canvas animation, English narration synthesized locally with Kokoro-82M, a procedural score, and burned-in Chinese and English subtitles. The repository holds source only; the videos are build outputs like the PDFs: `./tbook build films|site|all` renders them (or restores them from the build cache when nothing they depend on changed) into `build/films/<slug>/<id>/`, the site hosts them at `<slug>/films/<id>/`, and the book embeds them.

## 新建 · Create

```bash
./tbook film new example-monograph 002-carry-rules "进位规则" "The Carry Rules"
./tbook film list
```

`books/<slug>/films/<NNN>-<name>/` 只放这些源文件 · a film directory holds only:

| 文件 File | 作用 Purpose |
| --- | --- |
| `film.json` | 元数据（下表） · metadata (below) |
| `script.json` | 旁白与字幕，唯一的时间来源 · narration and subtitles, the single source of timing |
| `scenes.js` | 每个场景一个 `SCENES.<id> = S => { … }` · one drawing function per scene |
| `data/*.json` | 可选数据，内联为 `DATA.data.<名>` · optional data, inlined as `DATA.data.<name>` |
| `poster.jpg` | 提交入库的小海报（≤ 300 KB，手工运行 `film.sh <dir> poster` 生成；构建从不改写它） · the committed poster, written by hand with the `poster` step, never by the build |
| `README.md` | 可选：场景说明、每条论断的出处 · optional notes, the source of every claim |

流水线的工作文件都在 `<dir>/out/`（已被 `.gitignore` 忽略），构建把成片复制到 `build/films/<slug>/<id>/`。The pipeline works in `<dir>/out/` (git-ignored); the build copies the videos to `build/films/<slug>/<id>/`.

## film.json

```json
{
  "id": "001-golden-deficit",
  "title": "The Golden Deficit",
  "title_zh": "黄金亏量",
  "summary": "Zeckendorf digits, golden carries and the deficit of beta …",
  "summary_zh": "Zeckendorf 数字、黄金进位与 β 的亏量……",
  "subject": "https://github.com/the-omega-institute/trureturing",
  "publication_basis": "pinned",
  "released": "2026-11-08",
  "duration": "0:50",
  "resolution": "1280x720@30",
  "style": "trureturing cyberpunk · …",
  "narration": {"language": "en", "engine": "Kokoro-82M v1.0 (onnx)", "voice": "af_heart"},
  "subtitles": ["zh", "en"],
  "lean": ["D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"],
  "outputs": {
    "narrated_720p": "example-monograph_001_720p_narrated.mp4",
    "cover": "example-monograph_001_cover.jpg"
  }
}
```

| 字段 Field | 规则 Rule |
| --- | --- |
| `id` | 等于目录名 `<NNN>-<name>` · equals the directory name |
| `title`, `title_zh` | 英文、中文标题，各一行 · English and Chinese titles, one line each |
| `summary`, `summary_zh` | 可选，一段简介（落地页与视频页） · optional one-paragraph blurbs |
| `publication_basis` | 新视频填 `"pinned"`：当前出版依据、精确链接与构建数据由锁文件解析；钉版后仍须复核旁白 · current publication follows the lock; review narration after re-pinning |
| `subject_commit` | 可选，真实制作历史的 7–40 位提交；原样保留，不能为消除警告改成当前版本。旧视频仅有此字段仍受支持 · optional literal historical production commit; preserve it when re-pinning; legacy manifests remain supported |
| `released`, `duration` | `YYYY-MM-DD`，`m:ss`：旁白版的实际时长（`tts` 步骤与构建在不一致时提示） · the narrated length; the `tts` step and the build warn when it differs |
| `resolution` | 发布的视频尺寸与帧率：默认 `1280x720@<fps>`，`outputs` 列出 1080p 视频时为 `1920x1080@<fps>`（引擎总按 1920×1080 绘制，720p 由构建缩放） · the size of the published video: `1280x720@<fps>`, or `1920x1080@<fps>` when `outputs` lists a 1080p video (the engine always draws 1920×1080; the build scales to 720p) |
| `narration`, `subtitles` | 旁白语言/引擎/声音；字幕只支持 `zh`、`en` · subtitles are `zh` and/or `en` |
| `lean` | 片中引用的定理 GID，必须都在锁文件中且种类为 `theorem`；片中与视频页都以 LEAN ✓ 链接到所钉提交 · theorems cited by the film; each must be in the lock with kind `theorem` |
| `solid` | 可选，`true`：视频有实体镜头（见“实体镜头”），页面加载造型核心与 three.js · optional: the film has solid shots |
| `scripts` | 可选，书里的经典脚本（相对 `books/<slug>/`，如 `viz/<id>/model.js`），内联在 `scenes.js` 之前，计入构建键 · optional book scripts inlined before `scenes.js` |
| `outputs` | 构建产出的文件，键为输出、值为文件名；列出什么就构建、托管、链接什么。必需：`narrated_720p`（720p 旁白版，播放器播放它）与 `cover`（1920×1080 封面）；可选，列出才构建：`narrated`（1080p 旁白版）、`music_only`（1080p 纯配乐）、`music_only_720p`（720p 纯配乐）。其他键是错误。站点地址为 `<slug>/films/<id>/<文件名>` · what the build makes, by file name: what is listed is built, hosted and linked, nothing else. Required: `narrated_720p` (the 720p narrated video the players play) and `cover` (1920×1080); optional, built only when listed: `narrated` (1080p), `music_only` (1080p), `music_only_720p`; any other key is an error. The site serves `<slug>/films/<id>/<file>` |

旧的 `release_tag`、`published_tag`（逐片 Release）不再使用，`./tbook check` 给出警告，删除即可。The former `release_tag` and `published_tag` (per-film releases) are no longer used: `./tbook check` warns; remove them.

## script.json

```json
{
  "voice": "af_heart", "speed": 0.94,
  "say": {"Lean": "Leen"},
  "music": {"bpm": 84, "progression": "d-minor"},
  "scenes": [
    {"id": "zeck", "name": "ZECKENDORF", "lead": 1.6, "tail": 0.5,
     "music": [1.0, 0.4, 0.3, 0.0, 0.1],
     "cues": [{"line": 1, "at": 2.8, "kind": "stamp"}],
     "lines": [["English narration.", "中文字幕。"]]}
  ]
}
```

- `id`：小写标识符，对应 `SCENES.<id>`；`name`：HUD 上的场景名。
- `lead` / `tail`：场景开头、结尾的静默秒数；同一场景内相邻两句之间固定 0.6 秒。
- `lines`：`[英文旁白, 中文字幕]`，各一行；字幕自动换行。英文自然，中文准确，不逐字硬译。
- `say`：发音修正（只影响合成，不影响字幕）；`music`：节拍与和声；场景 `music`：五层音量 `[pad, bass, arp, kick, hat]`；`cues`：音效点（`stamp`、`chime`、`impact`、`glitch`）。

## scenes.js

场景函数由共享引擎 `theme/film/engine.js` 调用，`S = { u: 场景内秒数, d: 场景时长, p: u/d, t: 全片时间, f: 帧号, L: 本场景各句 }`。

- 时间：`at(S, k, dur, off)` 从第 k 句开始的 0→1 进度；`Q(S, k, '短语')` 从该短语被说出的时刻开始；`badgeQ(S, [[k, 短语|null, kind], …])` 顶部状态条。短语必须原样出现在第 k 句的英文旁白里，否则时刻退回句首：`./tbook check` 与 `film.sh <dir> timeline|build|all` 对 `SCENES.<id> = …` 里字面量形式的调用报出场景、句号与短语（平时是警告，`FILM_STRICT=1`——构建就这样运行——时失败），引擎渲染时也报出写成变量的短语。
- 绘制：`txt`、`panel`（切角面板）、`box`（角括号框）、`chip`、`dot`、`stamp`、`drawHyper`、`leanList`、`closingCard`。
- 颜色（来自 `theme/tokens.json`）：`C.lean` 绿色只给 Lean 已验证；`C.now` 琥珀色只给当前焦点；`C.open` 红色标开放问题；`C.argued` 紫色标论证但未经内核检验；其余用 `C.cyan`、`C.mag`、`C.white`、`C.dim`。
- `badge(a, kind)`：`lean`（绿）、`open`（红）、`argued`（紫）、`computed`（青，屏幕上的计算，不是证明）。
- 字体：`F.orb`（Orbitron 标题）、`F.disp`（Chakra Petch）、`F.zh`（Noto Sans SC）、`F.mono`（JetBrains Mono 数据）、`F.raj`（Rajdhani 英文字幕）、`F.math`（数学符号）。
- 引用：`leanCite(gid)` 按完整 GID 取 `DATA.lean` 中的一条（`{gid, name, label, short, kind, …}`；两条引用可能同短名，不要按 `short` 查）；`leanList` 显示 `label`：Lean 全名，命名空间不在模块路径上（会被误读成别的模块）时改为 GID。
- 实体镜头：`solid(key, rect)`，见下文“实体镜头”。
- 可选：`FILM.init.push(fn)` 预计算；`FILM.poster = () => { … }` 自定义海报；`FILM.speed[id]` 星空速度；`DATA.data.<名>` 读取 `data/*.json`。
- 片中的数字必须在页面上精确算出或取自所钉提交；把 Lean 已验证的结论与屏幕上的计算区分开（`badge`）。

## 实体镜头 · Solid shots

**什么时候用**：判据与 `skills/book-viz` 的“具象”一节相同——正文点名的对象本身是曲面或体（环面、莫比乌斯带、多面体、可行域、球与球里的东西），画成受光的实体确实更能让人看懂时才用。它是多出来的一种能力，不是视频的统一风格：曲线、格点、矩阵、记号串与读数照旧用二维画法，一部视频里通常只有一两个镜头是实体。依据标注不变：实体只是画法，`LEAN ✓` 仍只给 `film.json` 的 `lean` 列出的定理，实体镜头里屏幕上的计算照实写“computed here”或用 `badge(a, 'computed')`。

**When**: the same test as the “concrete” section of `skills/book-viz` — the object the text names is a surface or a solid, and a lit solid makes it easier to see. It is one more ability, not the style of the films: curves, lattices, matrices, strings of symbols and readouts stay 2D. The grounds do not change: a solid is a way of drawing; `LEAN ✓` still goes only to the theorems `film.json` lists in `lean`.

**怎么写**：在 `film.json` 加 `"solid": true`（只有这样的视频才加载 three.js：构建把造型核心 `theme/viz/solid-core.js` 与 `theme/viz/vendor/` 的 three.js 放到 `out/solid/`，页面在启动前导入）。场景里用 `solid(key, { x, y, w, h, yaw, pitch, zoom, radius | unit, cx, cy })` 取一个镜头：`x, y, w, h` 是它在 1920×1080 画面里的矩形，相机参数与页面的 `kit.solid` / `kit.stage3` 相同（x 向右、z 向上、正交轨道相机）。图元与页面同名：`surface`、`poly`、`glass`、`tube`、`line`、`arrow`、`ring`、`bead`、`fan`，写在 `begin()` 与 `end(a)` 之间；每帧按 `S.u`（或 `S.t`）从头描述一遍，带 key 的对象（`surface`、`poly`、`glass`、`tube`）只更新缓冲。`end(a)` 当场同步画出并以不透明度 `a` 合成进画面，之后画的 `txt`、`panel`、`chip`、`stamp` 与字幕都盖在实体上。`sh.anchor(v)` 把三维点投到画面坐标，返回 `{ x, y, depth, hidden }`，`hidden` 表示被本镜头的曲面或多面体挡住，二维标签据此变淡；`sh.p(v)`、`sh.occluded(v)`、`sh.marks()` 同页面。

```js
SCENES.torus = S => {
  const g = 2 * ease(clamp((S.u - 0.3) / 2.8));                         // a pure function of the scene time
  const sh = solid('torus', { x: 110, y: 170, w: 760, h: 680, yaw: -0.5 + 0.3 * S.u, pitch: 0.78, zoom: 1.6 });
  sh.begin();
  sh.surface('torus', (u, v) => shape(u, v, g), { u: [0, 1], v: [0, 1], nu: 96, nv: 48, color: C.vio, grid: { every: [8, 8] } });
  sh.bead(P, { color: C.now, r: 6 });
  sh.end(clamp(S.u / 0.6));                                             // drawn now, composited under the 2D layer
  const a = sh.anchor(P);
  txt('P', a.x + 12, a.y - 12, { size: 24, c: C.now, a: a.hidden ? 0.3 : 1 });
};
```

**页面与视频共用一处造型**：把对象的造型（参数化、颜色分区、标记点，以及用 `surface`/`tube`/`bead` 画它的函数）写成书里的一个经典脚本，例如 `books/<slug>/viz/<id>/model.js`，定义一个全局对象；页面在 `main.js` 之前 `<script src="model.js">` 加载它，视频在 `film.json` 写 `"scripts": ["viz/<id>/model.js"]`（相对书目录），构建把它内联在 `scenes.js` 之前，并把它计入视频构建单元的键。画法函数只调用两边同名的图元、颜色由调用方传入（页面传 `TRV.palette`，视频传 `C.*`），于是改一处两边都变。示例：`books/example-monograph/viz/phase-torus/model.js`，页面 `phase-torus` 与视频 001 的结尾镜头都画它。

**Share the model with the page**: put the object's model (parametrisation, coloured regions, marked points and a function that draws it with `surface`/`tube`/`bead`) in a classic script of the book such as `viz/<id>/model.js`; the page loads it before `main.js`, the film lists it in `film.json` `"scripts"`, which the build inlines before `scenes.js` and adds to the build key. The drawing function uses only the primitives both hosts share and takes its colours from the caller, so one edit changes both.

**确定性与环境**：实体镜头没有动画循环、时钟或随机数，像素比固定 1、抗锯齿固定开启；同一时刻渲染两次逐像素相同，与之前画过哪些帧无关，所以分段并行截帧与整段截帧相同。`theme/film/lib.js` 以 `--enable-unsafe-swiftshader` 启动 Chromium，用 SwiftShader（CPU）画 WebGL，有没有 GPU 都一样；不做能力探测与回退：不能创建 WebGL 上下文时页面启动失败并说明原因（`./tbook doctor` 报告能否画实体镜头）。示例的结尾镜头（760×680、120×120 网格的环面加 64 颗珠）每帧约 0.65 秒，二维场景约 0.2 秒（4 核机器、与其他任务同时运行时的实测）。

## 流水线 · Pipeline

```bash
theme/film/setup.sh                # 每台机器一次：视频 venv 与钉死的包（.cache/film/venv）、Kokoro 模型（.cache/film/models）、字体
F=books/<slug>/films/<NNN>-<name>
theme/film/film.sh $F timeline     # 无 TTS 的暂定时间轴（预览用）
theme/film/film.sh $F shot 2 8 14 --poster   # 单帧截图 → out/shots/
theme/film/film.sh $F serve        # 浏览器预览 index.html?play
theme/film/film.sh $F clip 30 3 960x540      # 3 秒无声低清片段 → out/clip.mp4
theme/film/film.sh $F poster       # out/<cover>.jpg 与提交入库的 poster.jpg（只有这一步写它）
theme/film/film.sh $F all          # tts → music → mix → frames → mux → cover，只做 outputs 所列（构建运行的就是这一步）
theme/film/film.sh $F all narrated narrated_720p cover   # 手工指定要做的输出（也可设 FILM_OUTPUTS）
```

`all` 只做所需的编码：Chromium 每帧按 1920×1080 截取一次，各渲染进程在同一遍中编码——720p 视频由帧直接缩放（lanczos，CRF 19），不先做 1080p 母版；只有 `outputs` 列出 1080p 视频时才另编码 1080p 母版（CRF 17）；只有列出纯配乐视频时才做纯配乐混音。默认（720p 旁白版与封面）渲染 50 秒的示例视频约 80 秒，成片约 6 MB。`all` frames are captured once at 1920×1080 and each worker encodes, in the same pass, only what the outputs need: the 720p videos straight from the frames (lanczos, CRF 19), a 1080p master (CRF 17) only for a 1080p video, the music-only mix only for a music-only video. The default (the 720p narrated video and the cover) renders the 50-second example in about 80 s, about 6 MB.

Python 包钉在 `theme/film/requirements.txt`，`setup.sh` 装进独立的视频 venv（Python 3.12 或 3.13；设置 `PYTHON` 时装进该解释器），tbook 的 `.venv` 不受影响；`film.sh` 与构建在未设置 `PYTHON` 时使用这个 venv。Chromium：设置 `PW_CHROMIUM_PATH` 使用已有浏览器，否则用 Playwright 自带的（`npx playwright install chromium`）。ffmpeg 来自系统：`$FFMPEG` 或 `PATH`（`apt-get install ffmpeg`）。

## 构建与发布 · Build and publish

1. `./tbook check` 无错误；提交 `film.json`、`script.json`、`scenes.js`、`poster.jpg`。
2. `./tbook build films --book <slug>`（`build site`、`build all` 同样；`--film <NNN>-<name>` 可重复，只渲染或恢复这几部，本书其他视频只从缓存恢复、不渲染）：每部视频是一个构建单元。键覆盖视频依赖的全部输入——git 列出的视频目录文件（不含 `out/`、`poster.jpg`、`README.md`）、`theme/film/`（不含 `site/`）、`theme/generated/tokens.mjs`、`tools/tbook/film.py`、引擎绘制的数据（书的代号、版本与标题，所钉提交，引用的声明及其陈述摘要，片内文字）、`package-lock.json` 中 @fontsource 字体与 Playwright 的版本、Kokoro 模型版本与 Node 主版本，`scripts` 所列的脚本，有实体镜头时还有 `theme/viz/solid-core.js` 与 `theme/viz/vendor/`；不含站点地址，也不含探测到的 ffmpeg、Chromium 与视频 Python。键未变时从本地缓存恢复，设置 `TBOOK_CACHE_REMOTE=1` 时也从已发布的整站 Release 恢复（本机没有视频工具链的贡献者可用它取得视频）；都没有时以 `FILM_STRICT=1` 运行 `film.sh <dir> all <outputs 的键…>` 并把这些文件复制到 `build/films/<slug>/<id>/`。改动 `outputs` 会重新渲染（`film.json` 在键中）。
3. `TBOOK_FILMS`：`auto`（默认）缓存未命中且工具链齐全时渲染，否则警告，站点只显示海报与“视频未构建”；`require` 缺工具链时失败；`skip` 从不渲染（命中缓存仍恢复）。
4. 站点把视频放在 `<slug>/films/<id>/<文件名>`（同源，Content-Type 与按字节范围请求正确，iOS Safari 可以播放）；整站 Release 附带构建缓存，没有缓存的构建设置 `TBOOK_CACHE_REMOTE=1` 时可以从中恢复。
5. 在章节中嵌入：`::: {.film src="<NNN>-<name>"}` 或 `::: {.film src="trureturing-film:film-<NNN>-v<k>"}`，块内文字为图注。

1. `./tbook check` passes; commit `film.json`, `script.json`, `scenes.js`, `poster.jpg`.
2. `./tbook build films --book <slug>` (or `build site`, `build all`; `--film <NNN>-<name>`, repeatable, renders or restores only those films and restores the others of the book from the cache without rendering): each film is a build unit. Its key covers everything the videos depend on: the film's files as git lists them (not `out/`, `poster.jpg` or `README.md`), `theme/film/` (not `site/`), `theme/generated/tokens.mjs`, `tools/tbook/film.py`, the data the engine draws (the book's code, version and titles, the pinned commit, the cited declarations and their statement digests, the in-frame strings), the `package-lock.json` versions of the @fontsource fonts and Playwright, the Kokoro model release and Node's major version, the scripts `scripts` lists and, for a film with solid shots, `theme/viz/solid-core.js` and `theme/viz/vendor/`; not the site's address, nor the probed ffmpeg, Chromium or film Python. An unchanged film is restored from the local cache, and with `TBOOK_CACHE_REMOTE=1` also from the published whole-site releases (the way for contributors without the film toolchain to get the videos); otherwise it is rendered with `film.sh <dir> all <the outputs keys…>` (`FILM_STRICT=1`) and those files are copied to `build/films/<slug>/<id>/`. Changing `outputs` renders again (`film.json` is in the key).
3. `TBOOK_FILMS`: `auto` (default) renders a film the cache does not hold when the toolchain is complete, and otherwise warns and the site shows only the poster and "Video not built"; `require` fails without the toolchain; `skip` never renders (a cached film is still restored).
4. The site serves the videos at `<slug>/films/<id>/<file>`, same origin with the right Content-Type and byte-range responses, which iOS Safari needs; whole-site releases carry the build cache, from which a build without a cache can restore them with `TBOOK_CACHE_REMOTE=1`.
5. Embed a film in a chapter with `::: {.film src="<NNN>-<name>"}` or `::: {.film src="trureturing-film:film-<NNN>-v<k>"}`; the text inside the block is the caption.

## 边界 · Scope

视频是讲解，不是证明。片中标 LEAN ✓ 的结论以 trureturing 中已冻结的 Lean 声明为准；其余是屏幕上的计算或论证，必须如实标注。A film explains; it proves nothing. Only results marked LEAN ✓ rest on frozen Lean declarations; everything else is labelled as computed on screen or argued.
