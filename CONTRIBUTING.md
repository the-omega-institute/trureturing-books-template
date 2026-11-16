# 贡献与协作规范

上游模板与下游书库使用同一套 Issue、PR 和分支约定。书库自己的补充规则写在 `PROJECT.md` 或 `docs/project/`；共享工具、主题、工作流和本规范在模板仓库修改，发布后通过 `./tbook template update` 同步。

## Issue

先搜索已有问题，再选择缺陷、改进建议或内容校正表单。标题使用 `type(scope): 摘要`，`scope` 可省略；摘要用中文或英文，说明具体对象和问题，例如：

- `fix(epub): 表格超出页面宽度`
- `feat(viz): 增加参数重置操作`
- `docs(ch19): 核对定理的非空条件`

正文应给出影响位置、当前行为或陈述、期望结果，以及复现步骤、来源或验收条件。章节问题注明书名、语言、章节路径和环境 id；工具问题注明命令、版本与必要日志。跨仓库事项附完整 Issue/PR 链接，在各自仓库分别确认完成。

形式化请求仍提交到 [trureturing-requests](https://github.com/the-omega-institute/trureturing-requests/issues)，使用英文及 [形式化请求规范](docs/FORMALIZATION-REQUESTS.md) 规定的标题和登记格式。

## 分支与提交

从最新的 `origin/main` 创建工作分支：

```bash
git fetch origin main
git switch -c fix/ch19-proof-scope origin/main
```

普通分支为 `<type>/<topic>`。`topic` 仅用小写英文字母、数字和单个连字符，可在开头带 Issue 编号，例如 `fix/123-epub-table-width`。一个分支解决一件事；工作区有未提交改动时先保存自己的工作。

| type | 用途 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷或错误修正 |
| `docs` | 正文、翻译、文档与来源说明 |
| `refactor` | 保持行为的内部重构 |
| `perf` | 性能改进 |
| `test` | 测试与测试夹具 |
| `build` | 依赖、构建与打包 |
| `ci` | 持续集成与部署工作流 |
| `chore` | 模板升级、钉版及仓库维护 |
| `revert` | 撤销已合入的改动 |

提交标题沿用 `type(scope): 摘要`，scope 使用小写字母、数字、连字符、点或斜线。破坏性变更可加 `!`，如 `feat(export)!: 调整输出目录`，正文写明迁移方法。PR 检查校验 PR 标题与源分支名；提交标题由作者和评审核对。

两个自动化流程保留固定分支，手动接续同类升级时也可使用：

- `template-update/<version>` 或 `template-update/<layer>/<version>`：模板及模板层升级，版本为 `1.3.0`、`v1.3.0` 或相应预发布版本。
- `trureturing-bump/<sha12>`：冻结声明钉版，后缀为 12 位小写十六进制提交前缀。

其 PR 标题分别使用 `chore(template): …` 与 `chore(trureturing): …`；冲突、失败或陈述变化的提示放在冒号后的摘要里。

## Pull request

向 `main` 提交 PR，标题使用上述格式，最长 100 个字符。填写 PR 模板中的问题与结果、改动范围、关联 Issue/上下游 PR、验证结果和迁移说明。需要自动关闭本仓库问题时使用 `Closes #123`；跨仓库链接使用 `Refs <完整 URL>`，在另一仓库工作完成后再关闭对应问题。小修正可以没有 Issue，在正文说明原因即可。

验证按改动范围执行：先 `./tbook test --list`，再 `./tbook test`；如涉及书籍结构或出版输出，补做受影响书籍的结构检查与对应格式构建。大范围浏览器回归交给 CI 并行矩阵，完整本地测试仅在用户明确要求时运行。PR 写出实际执行的命令、结果及未完成的检查；纯协作模板改动不需要重建书籍。

`PR conventions` 工作流在标题修改和新提交后检查标题及分支名。它使用目标分支上的检查程序，仅读取 PR 元数据，不执行 PR 分支代码。已打开 PR 的命名是否沿用历史，由仓库变量 `PR_CONVENTIONS_SINCE` 决定：值为 UTC 时间（如 `2026-11-16T16:00:00Z`）时，仅此前创建的 PR 保留旧命名；未设置时检查所有 PR。历史 PR 仍须通过原有验证。

合并前等待适用的 CI 通过并处理评审。一般使用 squash，合并提交标题采用 PR 标题；模板升级若包含需要留在 Git 历史中的新增托管文件删除，按 [升级说明](docs/UPGRADING.md) 使用 merge commit。不得直接或强制推送 `main`。

## 仓库初始化与维护

GitHub 的分支保护和仓库变量不会随模板文件复制。维护者为上游与每个下游分别设置：

1. 保护 `main`：必须通过 PR 合并，规则同样约束管理员，PR 绕过名单为空，禁止强制推送和删除。
2. 待本规范的工作流进入 `main` 后，将稳定检查 `Check` 与 `PR conventions` 设为必需；不使用 `lock_branch` 或空推送白名单阻断正常 PR 合并。
3. 如需保留现有 PR 命名，在启用时设置 `PR_CONVENTIONS_SINCE`，此后不要向后移动该时间。新仓库无需设置。

升级本规范会同步表单、PR 模板与检查工作流。下游自有的附加表单请放在 `.github/ISSUE_TEMPLATE/local-*.yml` 或 `local-*.md`，这些文件由书库维护。
