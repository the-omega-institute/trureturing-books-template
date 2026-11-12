# 验证模型 · Verification model

本书库区分三种状态：**Lean 内核验证、源文书面证明、开放问题。** 只有 `LEAN ✓` 结果承诺对应 trureturing 中已被 Lean 内核验证并冻结的声明，且固定在一个确切的提交上。`status="written-proof"` 表示有书面证明但没有陈述同一结果的冻结声明，不声称内核验证。 本文说明这条承诺如何被检查、检查到什么程度，以及什么仍需人工负责。

## 1. 一条定理的身份链

```
书中环境  ::: {.theorem #thm-x lean="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"}
   │  GID = <模块路径>.<声明名>
   ▼
trureturing.lock.json   commit = 8a24ea4e…（40 位 SHA）
   │  name = D5.S1.Deficit.deficit_three_valued, kind = theorem,
   │  statement_id = sha256:…（模块陈述摘要）, line = 264
   ▼
trureturing @ commit:  Golden/Frozen/state/D5/S1/Deficit/DeficitThreeValued.lean.json
   │  {statement_id, declarations: [{declaration_name_key: "ns(…,20:deficit_three_valued)", kind: "theorem"}]}
   ▼
trureturing @ commit:  D5/S1/Deficit/DeficitThreeValued.lean   （Lean 源；由 trureturing 的 CI 以 lake build 与公理检查保证）
```

trureturing 的冻结律（其 `CLAUDE.md` §1.3）规定：**模块的状态片 `Golden/Frozen/state/<module>.lean.json` 存在，当且仅当该模块已冻结**；状态片只在声明经内核验证（无 `sorry`、无私有公理）后由 trureturing 的流程写入。因此“在所钉提交上，状态片列有该声明且种类为 theorem”就是本书库对“已经 Lean 验证”的判据。

这条判据只在 trureturing 的集成分支上成立：冻结律由 trureturing 的 CI 在 `site.toml` 的 `[trureturing].branch`（默认 `dev`）上执行。GitHub 也会按 SHA 提供从未合入的提交（任何人发起的 PR 的 head、其他分支），那些提交上的状态片可以是任意内容。所以**所钉提交必须能从该分支到达**：`./tbook pin` 拒绝不在分支上的提交，`./tbook check` 每次复核（§2）。锁文件的 `branch` 字段记录的就是被核对的分支，`./tbook check` 要求它与 `site.toml` 的分支相同（改了 `site.toml` 的分支就要重新 `./tbook pin`，或在提交也在新分支上时 `./tbook pin --refresh`），站点清单发布的分支因此就是被核对的分支。`[trureturing].branch` 必须是 trureturing 中一个**现有分支**的名字，因为 git 与 GitHub compare API 读的不只是分支名：`compare/<sha>...<sha>` 与 `compare/<sha>^0...<sha>` 的结果都是 `identical`；`dev-12-g7bbf30f` 这类形如 `git describe` 输出的名字，git 与 compare API 都读作 `-g` 后面那段缩写所指的提交；`owner:branch` 指向另一个仓库（例如 fork）的分支；`pull/123/head` 在 git 里是 `refs/pull/123/head`，即某个 PR 的 head。核对分两步。

第一步只看名字，不问任何人。下列写法都是错误：`git check-ref-format --branch` 不接受的名字（含 `^`、`~`、`:`、`?`、`*`、`[`、`\`、`..`、`@{`、空白或控制字符；以 `-` 开头或以 `.` 结尾；有空的分量，即以 `/` 开头或结尾或含 `//`；有以 `.` 开头或以 `.lock` 结尾的分量；`HEAD`）；单独的 `@`（在修订表达式里 git 把它当作 `HEAD`）与含 Unicode 空白或不可见字符的名字（git 接受，但不同的名字会显示得一模一样）；完整 SHA、所钉提交的缩写 SHA 与 `refs/…`。

第二步核对这个分支确实存在，并且只把它当分支查，不当修订表达式解析（§2）：本地 checkout 只认恰好同名的 ref（`git show-ref --verify` 核对 `refs/remotes/<远程>/<分支>` 或 `refs/heads/<分支>`）；GitHub 上先问 `repos/<repo>/branches/<分支>`，再用它回答的分支头提交的完整 SHA（而不是名字）去比较。GitHub 回答仓库里没有这个分支，或回答的是另一个分支（改过名的分支会被重定向到新名字），`./tbook check` 把错误报在 `site.toml` 上：说明该分支不存在，提示把它改成现有分支（默认 `dev`），再运行 `./tbook pin --refresh`（所钉提交也在那个分支上时保留它）或 `./tbook pin`；`./tbook pin` 拒绝（**Refused**）。形如 describe 输出的名字、`pull/123/head` 与拼错的名字在语法上都是合法的分支名，就在这一步被拒绝；真有一个这样命名的分支时，按那个分支本身核对。本地 checkout 里没有同名 ref 时，它说不清 GitHub 上有没有这个分支，只能算“无法判定”（规则见 §2 的表）。

## 2. 每个 PR 都运行的检查（`./tbook check`）

| 检查 | 失败时 |
| --- | --- |
| 形式结论默认必须有 `lean`；显式 `status="written-proof"` 必须无 `lean`，并用 `proof="id"` 指向每版非空证明，填写 DOI、原文定位与已登记的形式化请求；开放条目不能用该状态或 `lean` | 错误 |
| 所钉提交可从 `site.toml` 的 trureturing 分支到达，且该分支存在（§1） | 错误，报在锁文件上，提示 `./tbook pin`；GitHub 回答没有这个分支时报在 `site.toml` 上，提示改成现有分支（§1）；无法判定时：GitHub Actions 中为错误，本地或 `--offline` 下为警告 |
| 锁文件的 `branch` 与 `site.toml` 的 trureturing 分支相同；该分支是合法的分支名（`git check-ref-format --branch` 接受，且不是 `@`、SHA、`refs/…`，见 §1） | 错误，提示 `./tbook pin`；分支名不合法时指出原因 |
| GID 语法（与 trureturing Blueprint 相同的地址格式；声明名是 Lean 名，分量可含希腊字母等类字母符号、下标与 `'` `!` `?`，其他分量写成 `«…»`；不得含空白或逗号） | 错误 |
| 每个被引用的 GID 都在锁文件中 | 错误，提示 `./tbook pin --refresh` |
| 形式结论引用的声明种类为 `theorem` | 错误 |
| 在锁定提交上重新读取状态片：名称、种类、模块、`statement_id` 与锁文件一致 | 错误（锁文件过期或被手改） |
| 声明解析：在模块状态片中按完整名或名称分量后缀恰好匹配一个非私有声明 | 错误（不存在 / 有歧义 / 模块未冻结） |
| 多语言版本的环境序列（种类、id、Lean 引用）逐条一致；SUMMARY 结构（前言/编号/附录章节、嵌套、草稿条目）一致，使同一定理在各语言中编号相同 | 错误 |
| 锁文件中有未被任何书引用的条目（`--book` 时也计入其他书的引用） | 警告 |
| `.cache/` 下有提交入库的文件，或 `.cache` 本身（例如一个符号链接）被提交（缓存只在本地可信） | 错误 |

状态片的来源依次为：本地 trureturing checkout（`$TRURETURING_DIR` 或 `../trureturing`，用 `git show <commit>:<path>`）、缓存 `.cache/trureturing/<commit>/`、`raw.githubusercontent.com/<repo>/<commit>/<path>`。因为路径中带着完整 SHA，读到的内容不可变。

分支可达性的判定依次为：

1. 缓存 `.cache/trureturing/<commit>/.tbook-on-branch-v2.json` 中的肯定结果。旧版工具写的 `.tbook-on-branch.json` 不再读取：旧版会把形如 describe 输出的名字当作分支。
2. 本地 checkout 的 `git merge-base --is-ancestor <commit> <ref>`，`<ref>` 依次取指向该仓库的远程的跟踪分支、`origin/<branch>`、本地 `<branch>`，且只取确实存在的同名 ref（`git show-ref --verify`）。一个都没有时，本地无法判定。
3. 联网时问 GitHub：先 `repos/<repo>/branches/<branch>`，取回答中的分支头提交 `<head>`，再问 `repos/<repo>/compare/<head>...<commit>`，状态为 `behind` 或 `identical` 才算在分支上。比较的基准是分支头的完整 SHA 而不是名字，GitHub 对名字的其他读法因此不起作用。分支端点回答 404 时再问 `repos/<repo>`：仓库可读，就确定没有这个分支；仓库也读不到（例如私有仓库而没有令牌）则无法判定。

本地 checkout 已确认在分支上时不再问 GitHub；否则 GitHub 的确定回答优先于可能过期的 checkout，GitHub 答不出时 checkout 的“不在分支上”仍然有效。只有肯定结果会被缓存。访问 API 时依次使用 `$TRURETURING_TOKEN`、`$GITHUB_TOKEN`、`$GH_TOKEN`（未设置时匿名，每小时 60 次）。CI 中没有 trureturing checkout，各工作流的检查步骤因此把 `github.token` 作为 `GITHUB_TOKEN` 传入（`trureturing-bump.yml` 用作业的 `GH_TOKEN`）。

**缓存在 CI 中的信任边界。** GitHub Actions 的缓存按 ref 隔离，但一个 PR 的运行会恢复同一 PR 之前的运行保存的缓存，而那些运行执行的是 PR 自己的代码：第一次推送改动工具、把伪造的状态片和“在分支上”的结论写进 `.cache/trureturing`，第二次推送撤回改动，最终 diff 看起来干净，检查却读到伪造的缓存。因此：

- 工作流只在可信的 ref 上恢复和保存 `.cache/trureturing`：`ci.yml` 在默认分支的 push（及手动运行）与 tag 上（包括 tag 工作流通过 `workflow_call` 调用时），`pages.yml` 与 `trureturing-bump.yml` 在默认分支上（定时运行总在默认分支上），`release.yml` 在 tag 上。PR 与其他分支的运行不使用这份缓存。
- `tbook` 自身也做纵深防御：`$GITHUB_EVENT_NAME` 为 `pull_request`、`pull_request_target`、`pull_request_review` 或 `pull_request_review_comment` 时，不从 `.cache/trureturing` 读取状态片和分支结论（仍会写入），状态片从 `raw.githubusercontent.com` 读取，分支可达性每次都问 GitHub 的分支端点与 compare API（用 `GITHUB_TOKEN`）。所以 PR 的检查需要网络；`--offline` 下这些项目只是警告。
- 本地运行时，缓存是开发者自己的，照常读取。
- 工具链缓存（`.github/actions/setup` 中的 pip 缓存、Playwright 的 Chromium、`.cache/fonts`、视频用的 Kokoro 模型 `.cache/film/models`）在 PR 事件（`github.event_name` 以 `pull_request` 开头）中既不恢复也不保存，PR 的运行每次从 PyPI、Playwright 的下载站和 GitHub 重新下载。只是不保存还不够：PR 的运行执行的是 PR 自己的工作流和 action 文件，第一次推送可以去掉保存条件（或另加一个 `actions/cache/save` 步骤），把篡改过的包或 Chromium 存进该 PR 的缓存作用域；第二次推送恢复原样，最终 diff 干净，恢复步骤却会先在 PR 自己的作用域里找到那份缓存，找不到才去目标分支和默认分支。跳过恢复的条件写在最终版本的文件里，早先推送的改动左右不了它。其他事件照常恢复和保存（`actions/cache/restore` + `actions/cache/save`；不用会在 PR 中保存的 `actions/cache` 与 setup-python 自带缓存），作用域是所在分支，找不到时回落到默认分支。
- `lean-verify.yml` 的 pip 缓存与 Lake 工作区缓存（`build/lean-verify/.lake`，公理检查读的正是其中已构建的 `.olean`）按同样的规则处理：PR 事件中既不恢复也不保存，其他事件用 `actions/cache/restore` + `actions/cache/save`，恢复未精确命中时才保存，Lake 工作区还要等构建成功。本仓库只在定时、手动运行与 `release.yml`（tag）中运行它，但它可以经 `workflow_call` 被调用，书库若从自己的 PR 工作流调用它，这条规则同样生效。
- 构建缓存（`.cache/artifacts`，组合动作 `.github/actions/build-cache`；`docs/PUBLISHING.md` §5）的条目直接替代构建，其中的 HTML、PDF、EPUB、幻灯片与视频原样进入站点和 Release，所以只有默认分支自己的代码能写入：只在默认分支上的 `push`、`workflow_dispatch` 与 `schedule` 事件中保存（目前只有 `pages.yml` 保存）。条件按事件名而不只按 ref 写：`pull_request_target` 的 ref 是目标分支，它的运行若保存，就会写进默认分支的作用域。恢复在 PR 事件之外照常进行，先找本次运行所在 ref 的作用域（只有该 ref 自己的代码写得进去），再找默认分支的；PR 事件中既不恢复也不保存 Actions 缓存，理由与上面相同。
- PR 可读取成功的默认分支 Pages 运行上传的 `tbook-build-store` 工件。`tools/ci/trusted_cache.py` 从 `pages.yml` 的 workflow 端点枚举成功运行，再核对 workflow ID、`head_repository.full_name`、默认分支、事件（仅 `push` / `workflow_dispatch`）、`status=completed` 与 `conclusion=success`；按该运行中未过期工件的 ID 下载，绝不按跨运行的同名工件或 PR 的 run ID 恢复。即使以前的 PR 曾上传同名工件也不会入选。`pages.yml` 只在默认分支上传。此处的信任级别是已合入默认分支并成功运行的 Pages 代码，与现有默认分支 Actions 缓存相同。下载需要 `actions: read`；不可用时为缓存未命中。恢复后仍按当前单元输入键与文件摘要检查，Lean 冻结状态缓存不在工件内。
- 从 Release 恢复（`TBOOK_CACHE_REMOTE=1`）在 PR 中也允许。Release 只能由有 `contents: write` 的令牌或有写权限的人创建：本仓库只有 tag 触发的 `release.yml` 与 `template-release.yml` 的发布作业这样做（构建作业只有读权限）；fork 发起的 PR 拿到的是只读令牌，PR 存进自己缓存作用域的东西也到不了 Release。工具只读已发布（非草稿）的 Release，每个 tar 都核对 `build-cache.json` 记录的 SHA-256 和 GitHub 报告的摘要，解包时拒绝绝对路径、`..` 与链接，再逐个文件核对条目自带的摘要。因此 Release 的信任级别就是仓库写权限：能发布 Release 的人本来也能推送 tag、运行 `release.yml`。若默认分支要求评审而写权限者不受此限，应当用 tag 规则集限制谁能创建 tag，并留意新发布的 Release。
- 建议启用不可变 Release（immutable releases）：发布之后附件不能再替换或删除，tag 也不能移动，已发布的缓存条目不会被事后掉包（包括被泄露的令牌）。工作流先把 Release 建为草稿、传完全部附件再发布，与之兼容；工具不读草稿。
- npm 缓存（setup-node 的 `cache: npm`）在 PR 中照常恢复和保存，这是安全的：`npm ci` 只按 `package-lock.json` 为每个包记录的 sha512 完整性值从缓存取 tarball，字节对不上就丢弃并重新下载，植入的条目只会被忽略，不会被安装。单元测试检查锁文件中每个包都带有这个值，且安装用的是 `npm ci`；也检查可能在 PR 事件中运行的工作流（由 PR 事件触发的、被它们调用的，以及所有可经 `workflow_call` 调用的；目前是 `ci.yml` 与 `lean-verify.yml`）和它们用到的组合动作（`setup`、`build-cache`，输入取任何值）没有别的步骤在 PR 中恢复或保存缓存：`actions/cache`、`actions/cache/restore` 与 `actions/cache/save` 步骤在 PR 事件中都被跳过，`setup-*` 动作除 npm 外不启用缓存；构建缓存只在默认分支的 `push`、`workflow_dispatch` 与 `schedule` 中保存。

## 3. 深度验证（`lean-verify` 工作流）

状态片是 trureturing 自己的账本。为了不只依赖账本，`./tbook lean-project` 生成一个 Lake 工程：

- `lean-toolchain` 取自所钉提交；`lakefile.toml` 以 `rev = <commit>` 依赖 trureturing；
- 导入每个被引用的模块，对每条声明检查：存在；位于预期模块；种类与锁文件一致；`collectAxioms` 的结果只含 `propext`、`Classical.choice`、`Quot.sound`（因而没有 `sorryAx`）。

它需要构建被引用模块及其依赖（Mathlib 用 `lake exe cache get`），耗时较长，所以每周和发版前运行（`.github/workflows/lean-verify.yml`；设置仓库变量 `REQUIRE_LEAN_VERIFY=true` 可让 Release 依赖它）。

## 4. 升级所钉提交时

`./tbook pin` 先核对目标提交在 `site.toml` 的分支上（不在，或 GitHub 回答没有这个分支，则 **Refused**，锁文件不写；无法判定时 GitHub Actions 中拒绝、其他情况列为 **Warnings**；不带参数时用 `git ls-remote` 取 `refs/heads/<分支>` 的头，分支不存在则直接报错退出），再列出：新增与删除的 GID（仍被引用但无法解析的只列在 Unresolved）、名称或种类变化、**模块陈述摘要变化**、源码行号变化。`statement_id` 是模块级摘要：它变了，说明该模块中至少一条声明的陈述变了，不一定是你引用的那条。合并前必须对照新旧提交的 Lean 源复核被引用定理的陈述，并同步书中文字（`skills/trureturing-pin`）。

## 5. 不由机器保证、需要人工负责的部分

- **书面陈述与 Lean 陈述一致。** 工具能保证“引用的声明存在且已验证”，不能保证“书中的话说的就是那条声明”。写作与评审时必须对照 Lean 源（链接带行号）和 trureturing 的 Blueprint 说明。
- **书面证明的责任。** `status="written-proof"` 检查 DOI、原文定位、请求 URL、issue 标题与书籍登记，以及每版关联的非空 proof 块；不自动判定冻结库中是否已有同一陈述，不能保证论证正确或完整。作者与评审必须检查源文证明、假设、量词、边界情况与出处；不因缺少 Lean 形式化把已证明结果称作开放问题，也不把变体当成同一结果。该状态的紫色徽章不带链接，不计入 Lean 数量，账本单列并链接书内证明、DOI 与形式化请求。已有匹配 Lean 验证时不得继续用书面证明状态。请求规范与统计见 [FORMALIZATION-REQUESTS.md](FORMALIZATION-REQUESTS.md)。
- **解释与图示。** Lean 结果的 `proof` 块用于解释；书面证明结果的 `proof` 是作者承担责任的论证。可视化与视频只是解释或示意，必须声明哪些是示意模型。
- **trureturing 自身的正确性**由它的 CI、Lean 内核与评审流程负责；本书库信任其冻结账本，并通过深度验证独立复核公理闭包。

## 6. 读者如何自行核对

Lean 验证定理框的 `LEAN ✓` 徽章与页脚链接指向所钉提交上的 Lean 源文件（含行号；行号按 `namespace`/`section` 解析出的完整名定位，无法唯一确定时不带行号，而不是猜一个）；书末“形式化验证账本”列出全部对应关系与状态片链接。构建只在锁文件把一条形式结论所引的每个 GID 都解析为 Lean `theorem` 时才显示 `LEAN ✓`；否则显示红色 `UNVERIFIED`（徽章在各端都不是链接），也不计入“LEAN ✓ n”等统计（这样的书通不过 `./tbook check`，不会发布）；页脚与账本只给锁文件解析了的声明链接，锁文件没有的 GID 显示为不带链接的文字。读者可以克隆 trureturing，检出该提交，运行 `lake build` 并对声明执行 `#print axioms`。
