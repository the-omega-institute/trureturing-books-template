---
name: template-update
description: 升级或完善书库模板本身时使用：把下游书库更新到 trureturing-books-template 的新版本（./tbook template update，含冲突与迁移）；把下游对工具、主题、工作流或 skills 的改进回馈到模板仓库并发布新版本；以及根据实际使用经验修订这些 skills。
---

# 模板更新与 skills 完善

一个书库由两部分组成：**模板托管的部分**（`template.toml` 的 `[managed].paths`：`tools/`、`theme/`、`templates/`、`skills/`、`docs/`、`.github/workflows/`、`CLAUDE.md`、`package.json` 等）和**书库自己的部分**（`books/`、`site.toml`、`trureturing.lock.json`、`i18n/`、`PROJECT.md`、`README.md`、`skills/local-*/`、`docs/project/`）。托管部分只在模板仓库修改，再同步到各书库；书库自己的部分永远不被模板覆盖。

## 适用范围

**用**：
- A. 把本书库升级到模板的新版本（手动，或处理 `template-sync` 工作流开的 PR）。
- B. 你在书库里发现托管文件（工具、主题、工作流、skill）有 bug 或可以改进 → 回馈到模板仓库。
- C. 一次工作中某个 skill 的指引不对、缺步骤或过时 → 修订该 skill（同 B 的流程）。
- D. 在模板仓库中发布新版本（维护者）。

**权威**：`tools/tbook/template.py` 的行为、`template.toml`、`template-manifest.json`、`docs/UPGRADING.md`。

## A. 升级本书库

1. 工作区干净（`git status` 无改动），新建分支 `template-update/<version>`。
2. `./tbook template status` —— 查看当前模板版本，以及本地被改过的托管文件。被改过的文件在升级时不会被覆盖，会产生冲突。
3. `./tbook template update --dry-run`（默认目标是最新的 `v*` 正式发布，且从不倒退：它不比当前版本新时什么也不改，摘要说明原因；`--to v0.3.0` 指定版本，也用于有意降级或与发布重新同步）。读摘要。
4. `./tbook template update`。结果：
   - 本地未改的托管文件 → 直接替换/新增/删除；
   - 本地改过而上游也改了 → **冲突**：保留本地文件，上游版本写在旁边的 `<file>.template-new`。逐个比较合并，然后删除 `.template-new`。若本地改动本该回馈上游，按 B 处理；若只是临时补丁，通常直接采用上游版本。
   - 版本间的迁移脚本 `tools/migrations/v<X.Y.Z>.py` 会自动运行（取自新版本模板，各在新的 Python 进程中运行）；按其输出检查书的内容（例如语法变更）。
5. 读 `docs/CHANGELOG.md` 中跨越的各版本说明，处理“需要手动操作”的条目。
6. 重新安装依赖（`pip install -r requirements.txt`、`npm ci`），运行 `./tbook doctor`、`./tbook check`、`./tbook build all`。
7. 提交（摘要见 `build/template-update.md`，可直接作 PR 正文），开 PR，CI 通过后合并。若在 PR 中删掉了不需要的新托管文件，用合并提交（merge commit）合并，不要 squash：squash 后这个文件从未进入 `main` 的历史，下次升级会重新安装它（`docs/UPGRADING.md` 第 2 节）。

`template-sync` 工作流每周自动执行 1–4 步并开 PR；合并前仍需完成 4–6 步中的人工部分（冲突、迁移检查、构建核对）。

## 模板层

`template.d/<name>.toml` 与 `<name>.manifest.json` 定义独立来源、版本及托管范围。
先读 `docs/UPGRADING.md` 的“模板层”节。无 `--layer` 的 status/update 检查/升级上游及所有层；
使用 `--source` 或 `--to` 时明确 `--layer upstream|<name>`。
新层用 `./tbook template install <name> --source <路径或 git URL> --dry-run` 预览，再去掉
`--dry-run`。层源码改完运行 `./tbook template manifest --layer <name>`，不要在消费者重置基准。
每层沿用 A 的冲突、历史删除与发布选择规则；看自己的 `build/template-update-<name>.md`，
变更记录和迁移在 `docs/layer-<name>/`。周更工作流分来源开 PR，不应将层变更回馈给上游。
层只能认领自己的保留前缀或其他未认领路径，不能接管上游、其他层或书库自有文件；
`--force` 也不能越界。层不应覆盖 CLI、共享运行时或输出契约。

## B/C. 回馈改进到模板仓库

不要在书库里长期保留对托管文件的修改——下次升级会产生冲突，其他书库也得不到改进。

1. 在书库中确认改动有效（`./tbook check`、相关构建、单元测试 `PYTHONPATH=tools python3 -m unittest discover -s tools/tests`）。
2. 克隆模板仓库：`git clone https://github.com/the-omega-institute/trureturing-books-template ../trureturing-books-template`，新建分支。
3. 把改动移植过去（只移植托管文件；不要带入书库自己的书、配置或锁文件）。修订 skill 时：
   - 写清触发场景（`description`）与“用/不用”；
   - 步骤可执行、命令真实存在（在模板仓库里跑一遍）；
   - 记录导致这次修订的具体情况（在 CHANGELOG 中一句话）。
4. 在模板仓库中：
   - 更新 `docs/CHANGELOG.md`（`## [Unreleased]` 下记录；破坏性变更写明迁移方式）；
   - 需要改书的内容或配置格式时，新增 `tools/migrations/v<下一版本>.py`（`migrate(root) -> list[str]`，幂等）；
   - `./tbook template manifest` 重新生成清单；`./tbook check`、单元测试、`./tbook build all` 全部通过。
5. 向模板仓库开 PR，说明来源书库与动机。
6. 合并并发布后（见 D），回到书库按 A 升级，删除书库里的临时改动。

只属于本书库、不适合所有下游的 skill，放在 `skills/local-<name>/SKILL.md`，不必回馈。

## D. 发布模板版本（模板仓库维护者）

1. 把 `docs/CHANGELOG.md` 的 `[Unreleased]` 改为 `## [X.Y.Z] - YYYY-MM-DD`。
2. `template.toml` 的 `version` 改为 `X.Y.Z`；`./tbook template manifest`。
3. 提交、合入 `main`，打 tag `vX.Y.Z` 并推送；`template-release.yml` 校验版本与清单并创建 Release。
4. 各书库的 `template-sync` 工作流会在下一次运行时开升级 PR。

版本号：修复 → PATCH；向后兼容的新功能 → MINOR；需要下游改内容或配置 → MAJOR（并提供迁移脚本）。

## 禁止

- 用 `--force` 覆盖本地改动而不先检查 `.template-new` 差异。
- 在书库中修改托管文件后不回馈、不记录。
- 把书库自己的内容（`books/`、`site.toml`、锁文件）提交到模板仓库。
- 发布未更新 `template-manifest.json` 的模板版本。
