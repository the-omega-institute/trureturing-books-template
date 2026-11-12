# 模板升级 · Upgrading the template

本书库基于 [trureturing-books-template](https://github.com/the-omega-institute/trureturing-books-template)。模板以语义化版本发布（tag `vX.Y.Z`），下游书库通过 `./tbook template update` 升级。

## 1. 托管与自有

`template.toml` 定义了边界：

- **托管**（`[managed].paths`）：`tools/`、`theme/`、`templates/`、`skills/`、`docs/`、`.github/workflows/`、`.github/actions/`、`.claude/`、`CLAUDE.md`、`AGENTS.md`、`tbook`、`template.toml`、`template-manifest.json`、`requirements.txt`、`package.json`、`package-lock.json`、`.gitignore`、`.editorconfig`。升级时同步（新增、修改、删除）。
- **例外**（`[managed].exclude`）：`skills/local-*`（书库自己的 skill）、`docs/project/`（书库自己的文档）。
- **自有**：`books/`、`site.toml`、`trureturing.lock.json`、`i18n/`、`PROJECT.md`、`README.md`、`LICENSE`，以及任何不在托管路径下的文件。升级永不触碰。

`template-manifest.json` 记录当前版本每个托管文件的 sha256 与权限位，用来判断“本地是否改过”。

## 2. 升级

```bash
./tbook template status              # 当前版本；本地改过、缺失、多出的托管文件
./tbook template update --dry-run    # 预览到最新版本的变化
./tbook template update              # 执行；--to vX.Y.Z 指定版本；--source <路径或 git URL> 指定来源
```

不带 `--to` 时目标是最新的正式发布（`vX.Y.Z`，不含预发布），而且**从不倒退**：最新发布比 `template.toml` 的版本旧（例如书库用 `--to` 升到了预发布），或版本号相同但托管文件来自另一个快照（例如在两次发布之间从模板 `main` 分支创建的书库），命令什么也不改，只在摘要中说明原因。确需降级或与该发布重新同步时，用 `--to` 明确指定版本。`--source` 是普通目录时，目标就是该目录：它是明确指定的，即使版本更旧也照常执行，只在摘要中警告这是降级。

每个托管文件按三方比较处理（基准是本地清单记录的旧版本）：

| 本地 | 上游 | 结果 |
| --- | --- | --- |
| 未改 | 改了 / 新增 / 删除 | 采用上游 |
| 改了 | 未改 | 保留本地 |
| 改了 | 改了 | **冲突**：保留本地，上游版本写入 `<file>.template-new` |

“本地删除”指书库曾经有过这个文件：清单列出、但本地不存在且 git 历史中从未出现过的文件（例如接入模板时复制来的清单所列的文件，见第 5 节）按“上游新增”安装。浅克隆或不是 git 仓库时无法判断，按清单处理。

git 历史指 `HEAD` 可达的全部提交，包括以合并提交（merge commit）并入的分支：在升级 PR 的分支上删掉不需要的新托管文件，再以合并提交合入，这个文件此后保持删除。Squash 合并不保留分支上的提交，这样删掉的文件从未进入 `main` 的历史，下次升级会重新安装它（`template-sync` 也会为此再开 PR）。要让它保持删除，用合并提交合入升级 PR，或者先原样合入，再在 `main` 上单独提交删除。

有冲突时命令以退出码 3 结束（`--dry-run` 预览时，若真正执行会冲突，同样返回 3）。逐个合并后删除 `.template-new` 文件。`--force` 直接采用上游（会丢弃本地改动，慎用）。`--source` 接受 git URL、本地 git 仓库或普通目录（此时不能用 `--to`）。`--to` 接受版本号、tag、分支或提交 SHA；来源是 URL 时 SHA 须写完整的 40 位，本地 git 仓库也接受缩写。摘要语言默认是 `site.toml` 中 `languages` 的第一个，`TBOOK_LANG=zh|en` 可指定。

升级完成后会运行 `tools/migrations/` 中跨越版本的迁移脚本（取自新版本模板，各在一个新的 Python 进程中运行，见 `tools/migrations/README.md`），并把摘要写到 `build/template-update.md`。然后：

```bash
.venv/bin/pip install -r requirements.txt && npm ci
./tbook doctor && ./tbook check && ./tbook build all
```

## 3. 自动升级 PR

`.github/workflows/template-sync.yml` 每周检查模板的新版本，执行升级并开 PR（分支 `template-update/<version>`）；有冲突时 PR 标题以 `[conflicts]` 开头，`.template-new` 文件一并提交供合并。没有更新的发布时（见第 2 节，不会倒退）什么也不改，不开 PR。在 PR 分支上删掉了不需要的新托管文件时，用合并提交合入，不要 squash（见第 2 节），否则下一次运行会重新安装它并再开 PR。模板仓库至少发布过一个版本（tag `vX.Y.Z`）后它才会工作。

令牌：

- 只用 `GITHUB_TOKEN` 时，需在 Settings → Actions → General 勾选 “Allow GitHub Actions to create and approve pull requests”；这样开的 PR 不会自动触发 CI，且升级若改动 `.github/workflows/`，推送会被 GitHub 拒绝（工作流会给出说明后失败）。
- 推荐在仓库 Secrets 中设置 `BOT_TOKEN`：细粒度令牌，Contents、Pull requests 与 **Workflows** 均为读写。

## 4. 改进托管文件

不要在书库中长期修改托管文件：把改进提交到模板仓库（流程见 `skills/template-update/SKILL.md` 的 B 节），发布新版本后再升级回来。

## 5. 不是从模板创建的仓库

已有仓库也可以接入：

1. 从模板的一个发布（通常是最新版 `vX.Y.Z`）复制 `tbook`、`tools/` 与 `template.toml` 到仓库根目录，并提交。不需要复制 `template-manifest.json`：升级会写入它。
2. 运行：

   ```bash
   ./tbook template update --source https://github.com/the-omega-institute/trureturing-books-template.git --to vX.Y.Z
   ```

   `--to` 取第 1 步复制的版本（复制的是最新版时可以省略）。结果：
   - 其余托管文件（`theme/`、`skills/`、`docs/`、`.github/workflows/` 等）全部新增；复制来的文件与该发布相同，保持不变。
   - 仓库已有、内容不同的同名托管文件（例如自己的 `.gitignore`）是冲突：保留你的文件，模板版本写在旁边的 `<file>.template-new`，命令以退出码 3 结束。逐个合并后删除 `.template-new`。
   - 若第 1 步也复制了同一发布的 `template-manifest.json`，同样可行：仓库历史中从未有过的托管文件照样新增；已有的同名文件则记为“保留的本地改动”，不写 `.template-new`。
3. 按 `skills/book-new` 补齐 `site.toml` 与 `books/`，运行 `./tbook template status` 与 `./tbook check`，提交。

## 6. 用 git 合并模板与示例书

有的书库不（只）用 `./tbook template update`，而是把模板仓库加为 git 远端，直接合并它的发布 tag 或分支：

```bash
git remote add --no-tags template https://github.com/the-omega-institute/trureturing-books-template.git
git fetch template main "+refs/tags/v*:refs/template-tags/v*"
git merge refs/template-tags/vX.Y.Z   # 从 “Use this template” 创建的书库与模板没有共同历史，第一次合并要加 --allow-unrelated-histories
```

模板的发布 tag 只取到 `refs/template-tags/` 下，不进书库自己的 `refs/tags`（`--no-tags` 让以后的 `git fetch template` 也不自动带回 tag）：书库的 `release.yml` 把推送的 `v*` tag 当作全部书的发版，`git push --tags` 会把模板的版本 tag 当成书库的发版推上去；与书库自己的 tag 同名时（两边都有 `v1.0.0`），`git fetch template --tags` 还会以 “would clobber existing tag” 失败，`git merge v1.0.0` 合到的则是书库自己的提交。以后每次升级重复后两行（不再需要 `--allow-unrelated-histories`）；要合并模板尚未发布的改动，用 `git merge template/main`。

这样合并会带来模板的全部改动，包括 `books/example-*` 下的示例书。示例书被删掉的书库，每当模板改动示例书，合并就在这些文件上冲突（modify/delete），每次都要手动处理。所以**隐藏示例书，不要删除**：在 `site.toml` 的 `[books]` 中设

```toml
hide = ["example-*"]
```

隐藏的书留在 `books/` 中，随合并照常更新，但检查、钉版、构建、站点与发版都当它不存在（`docs/ARCHITECTURE.md` §2.1）；模板以后新增的 `example-*` 示例书也自动隐藏。设好后运行 `./tbook check`（输出一行列出隐藏的书）与 `./tbook pin --refresh`（从锁文件中删去只被示例书引用的声明）。已经删掉示例书的书库，可以先 `git checkout template/main -- books/example-monograph`（或合并时按模板版本解决冲突）把它取回，再隐藏它。

书库自有的文件（`site.toml`、`trureturing.lock.json`、`README.md` 等，§1）在模板里也有自己的版本，git 合并时可能冲突：保留书库的版本（必要时参考模板的改动，例如 `site.toml` 新增的配置项）。锁文件只由工具写：解决冲突后运行 `./tbook pin --refresh`。

## 当前 pin 的单一来源（0.5.0）

0.5.0 向后兼容旧链接和视频清单。迁移仅把可视化里已带 `data-lean-gid` / `data-trureturing-path` 的 trureturing `href` 换成 `#`；构建和 `tools/node/viz-server.mjs` 仍给出精确永久链接。迁移幂等，不改无标记链接或历史档案。

可选的内容迁移：按 `docs/AUTHORING.md` 把当前版本与审计表的行号、摘要改为保留链接标签；幻灯片用 `<PinnedCommit />`。视频若此前每次 pin 都复制 `subject_commit`，核对历史后改用 `publication_basis: "pinned"`；真正记录制作历史的 `subject_commit` 保留。可视化生成器只提交书的拓扑与引用关系，当前 repo/commit/line/kind 由生成的 `assets/trureturing.json` 解析。所有格式的精确提交仍进入构建输出，历史比较不迁移。


## 模板层

第二个模板不必分叉上游。下游自有的 `template.d/<name>.toml` 使用与
`template.toml` 相同的 `[template]`（`name`、`repo`、`version`、可选 `tag_prefix`）
与 `[managed]` 配置；`name` 必须与文件名相同（小写字母、数字、连字符；`upstream` 保留）。
`template.d/<name>.manifest.json` 由同一工具生成，格式与上游清单相同。
层的源仓库可以是从上游模板创建的仓库，也可以仅包含该层的文件与配置。

```toml
# template.d/example.toml：位于模板层的源仓库
[template]
name = "example"
repo = "owner/example-layer"
version = "1.0.0"
[managed]
paths = ["docs/layer-example/", "skills/layer-example-write/",
         ".github/workflows/layer-example-check.yml"]
```

上游为层预留 `docs/layer-<name>/`、`skills/layer-<name>-*`、
`.github/workflows/layer-<name>-*`；它们不进入上游清单，也不由上游升级写入或删除。
层还可以认领未被上游或其他层使用的路径，但不能认领上游托管路径、书库自有路径
（包括 `books/`、`site.toml`、`PROJECT.md`、`template.d/`，以及排除路径 `docs/project/` 与 `skills/local-*`），或另一层的命名空间。
路径认领按整个目录检查，即使尚无文件也会拒绝重叠；`--force` 不绕过此边界。
层配置及清单是命令单独管理的元数据，不列进层的 `[managed].paths`。

```bash
# 源仓库维护者：在含 tbook 的仓库中生成并检查清单
./tbook template manifest --layer example
./tbook template manifest --layer example --check
# 若层的源仓库不含 tbook，可指定该目录并调用已有工具
TBOOK_ROOT=/path/to/layer-source /path/to/tbook template manifest --layer example
# 下游使用者：也支持本地 git 仓库与普通目录作为来源
./tbook template install example --source https://github.com/owner/example-layer.git
./tbook template status                         # 上游与所有已安装层
./tbook template update --dry-run               # 各来源最新稳定版的升级预览
./tbook template update                         # 先升级上游，再升级各层
./tbook template update --layer example --to v1.1.0
./tbook template update --layer upstream --source ../upstream
./tbook template list --json                    # 供工作流发现各来源
```

有多层时，`--source`、`--to` 必须同时用 `--layer upstream|<name>`，以免把一个来源用到所有层。
安装也支持 `--dry-run`，不会写入配置、清单、摘要或迁移。每层独立做三方比较、
`.template-new` 冲突（退出码 3）、git 历史判断与“从不倒退”的发布选择，规则与第 2 节相同。
摘要为 `build/template-update-<name>.md`；上游摘要路径不变。
层的版本迁移放 `docs/layer-<name>/migrations/vX.Y.Z.py`，变更记录放
`docs/layer-<name>/CHANGELOG.md`。迁移以新的 Python 进程运行，导入消费仓库的
`tbook`；与上游迁移一样，只从信任的源运行，迁移负责保持自己的所有权边界。

`template-sync` 每周发现已安装层，对上游及每层从同一基线分别开一个 PR；层分支为
`template-update/<name>/<version>`，上游仍为 `template-update/<version>`。
源仓库不为自己开升级 PR。层需按自己的 `tag_prefix` 发布版本 tag（默认 `vX.Y.Z`）；从上游模板创建的层源仓库宜用独立前缀，以免触发书籍发版工作流。没有正式发布时只提示、不开 PR。
手动 workflow 的 `layer` 输入可选一个来源；多层时填写 `to` 必须也选 `layer`。默认都留空，逐来源取最新正式发布。

此前未列在旧/新清单中的托管目录文件只会在 `status` 显示为“多出”，升级保留它们：
`plan_update` 只遍历两份清单文件名的并集。若上游以后新增同名文件，会按新增冲突处理。
层预留前缀使所有权明确，避免这种未来碰撞；上游升级也不复制源仓库的 `template.d/`。
