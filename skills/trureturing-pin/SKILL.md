---
name: trureturing-pin
description: 升级或刷新本书库所钉的 trureturing 提交时使用（./tbook pin），包括处理自动 bump PR：解析全部 Lean 引用、复核陈述摘要发生变化的定理文字、确保 ./tbook check 通过。
---

# 升级所钉的 trureturing 提交

## 适用范围

**用**：想引用 trureturing 新冻结的声明；`trureturing-bump` 工作流开了 PR；`./tbook check` 报告锁文件与上游不一致，或锁文件的分支与 `site.toml` 不同；新增引用后锁文件缺条目。

**权威**：`tools/tbook/pin.py` 的行为与 `./tbook check` 的输出。

## 三种用法

```bash
./tbook pin              # 跟随 site.toml [trureturing].branch（默认 dev）到最新提交
./tbook pin <sha|ref>    # 钉到指定提交（完整或缩写 SHA）、分支或 tag
./tbook pin --refresh    # 不动提交；解析新增引用、清理不再使用的条目
```

加 `--dry-run` 只看报告不写锁文件；加 `--report build/pin.md` 把报告写成文件（PR 正文用，目录不存在时自动创建）。

无论哪种写法，目标提交都必须能从 `site.toml` 的分支（默认 `dev`）到达：trureturing 只在该分支上执行冻结律，GitHub 却也按 SHA 提供未合入的提交（PR head、其他分支）。不在分支上的提交会被拒绝（报告中的 **Refused**，锁文件不写）；无法判定时（没有同时含该提交与该分支的本地 checkout，且 GitHub API 不可用或加了 `--offline`），在 GitHub Actions 中（未加 `--offline`）拒绝，其他情况写入锁文件并在 **Warnings** 中提示，之后由 `./tbook check` 再次核对。本地 checkout 的 `origin/dev` 过期时先 `git -C ../trureturing fetch`。浅克隆（`--depth 1`）的 checkout 即使同时含有所钉提交与分支头，两者之间的祖先链也是断的，`./tbook pin --refresh` 会把本来在分支上的提交报为不在分支上：先 `git -C ../trureturing fetch --depth=<足够深> origin dev`（或 `--unshallow`；嫌大可加 `--filter=blob:none`），直到 `git -C ../trureturing merge-base --is-ancestor <所钉提交> origin/dev` 成功再重试。只支持分支（`refs/heads/*`）与 tag（`refs/tags/*`），不支持 `refs/pull/*`。

`site.toml` 的 `[trureturing].branch` 必须是 trureturing 中现有分支的名字。写成 SHA（完整的，或所钉提交的缩写）、`refs/…`、`<sha>^0` 这类修订表达式、`owner:branch`、`HEAD`、`@`，或任何 `git check-ref-format --branch` 不接受的名字时，pin 直接报错，`./tbook check` 也报错并指出原因（GitHub compare API 会把 SHA 与 `<sha>^0` 当作比较基准，`compare/<sha>...<sha>` 恒为 `identical`，什么也证明不了；`owner:branch` 比较的是另一个仓库的分支）。名字合法但不是现有分支时（例如 `dev-12-g7bbf30f` 这类形如 `git describe` 输出、会被 git 与 compare API 读作缩写 SHA 的名字，`pull/123/head`，或拼错的名字），GitHub 的分支端点回答没有这个分支，`./tbook pin <sha>` 与 `./tbook pin --refresh` 拒绝（**Refused**），不带参数的 `./tbook pin` 用 `git ls-remote` 找不到该分支而直接报错，`./tbook check` 报错；只有本地 checkout、没有网络时，checkout 里没有同名 ref 只算无法判定（完整规则见 `docs/VERIFICATION.md` §1、§2）。锁文件的 `branch` 记录钉版时核对的分支；`./tbook check` 要求它与 `site.toml` 相同。确有理由更换分支时（例如 trureturing 改了集成分支），改 `site.toml` 后运行 `./tbook pin`（钉到新分支的最新提交），或在当前提交也在新分支上时运行 `./tbook pin --refresh`；报告首行下方会写出 `Branch: <旧> → <新>`。

在 PR 的 GitHub Actions 运行里，`./tbook check` 与 `./tbook pin` 不读 `.cache/trureturing`（同一 PR 先前的运行可能写入伪造的缓存），状态片从 `raw.githubusercontent.com` 读取，分支可达性每次问 GitHub（先问分支端点取分支头，再用 compare API 比较），所以那里离不开网络与 `GITHUB_TOKEN`（`docs/VERIFICATION.md` §2）。

## 步骤

1. 运行 `./tbook pin --dry-run`，读报告：
   - **Refused**：目标提交不在所跟随的分支上（或在 CI 中无法核对）。改钉已合入该分支的提交；不要为此修改 `site.toml` 的分支。若原因是 `site.toml` 的分支在 trureturing 中不存在（“is not a branch of …”），把它改回 trureturing 的集成分支（默认 `dev`）。
   - **Unresolved**：某个 GID 在新提交上不存在或未冻结（模块被移动、改名、删除冻结状态片）。到 trureturing 查明原因（`git log -- Golden/Frozen/state/<module>.lean.json`），改用新的 GID，或把条目降级为 `conjecture` 并说明。锁文件在全部解析前不会写入。
   - **Changed — module statement digest changed**：该模块中某些声明的陈述变了（`statement_id` 是模块级摘要，不一定是你引用的那条）。逐条打开新旧两个提交上的 Lean 源，比较被引用声明的陈述；若变了，更新所有语言版本中的书面陈述。
   - **name/kind changed**：后缀匹配到了别的声明，或声明种类变化。改用更长的名字后缀。
   - **Source line changed**：只是源码行号变化（链接随之更新），无须改书；若同一 GID 也列在 **Changed** 中，按 Changed 的要求复核。
2. 确认无误后去掉 `--dry-run` 正式运行。
3. `./tbook check` 必须 0 错误。
4. 构建并抽查受影响的章节（`./tbook build html --book <slug>`）。
5. 提交 `trureturing.lock.json` 与书的改动，说明：新旧提交、新增/删除的 GID、复核过的定理。

## 自动 bump PR

`.github/workflows/trureturing-bump.yml` 每周运行 `./tbook pin` 并开 PR，正文是 pin 报告与 `./tbook check` 输出。合并前必须由人或 agent 完成上面第 1 步的复核；有 “statement digest changed” 时，在 PR 中逐条写下复核结论。

标题前缀说明 PR 的状态：`[refused]`（目标提交不在所跟随的分支上，或在 CI 中无法核对）、`[unresolved]`（有引用无法解析）、`[pin failed]`（pin 在写出报告前就失败了，见工作流日志）——这三种是草稿 PR，只有一个空提交，不改锁文件，按第 1 步的对应条目处理后重新运行工作流；`[check fails]`（锁文件已更新但 `./tbook check` 失败，同样是草稿）；`[review statements]`（有陈述摘要变化，须逐条复核）。

## 禁止

- 手改 `trureturing.lock.json`。
- 钉未合入所跟随分支的提交（例如自己尚未合并的形式化 PR 的 head）。
- 提交 `.cache/` 下的文件，或把 `.cache` 作为符号链接提交（`./tbook check` 报错）。
- 为让 PR 通过而修改 `site.toml` 的 `[trureturing].branch`，或把它写成 SHA、修订表达式、形如 `git describe` 输出的名字、别的仓库的分支或任何不存在的分支。
- 为让检查通过而删除 `lean` 属性或把定理改成注释。
- 在未复核陈述变化的情况下合并 bump PR。

当前版本来自 `trureturing.lock.json`，不复制 SHA 到源码。正文与审计表用 `docs/AUTHORING.md` 的保留链接标签；幻灯片用 `<PinnedCommit />`（复用主题的 `pinned`）；可视化锚点用 `data-lean-gid` / `data-trureturing-path` 和 `href="#"`，由构建与本地预览解析。动态声明数据可从 `../assets/trureturing.json` 取得（构建生成、本地预览从锁读取；不提交该文件）。真实历史版本仍按历史事实保留。钉版后复核摘要变化与媒体陈述，再重建；纯提交或行号变化不要求改正文或媒体源码。
