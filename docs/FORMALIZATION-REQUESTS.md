# 书面证明与形式化请求

书面证明是尚无匹配 Lean 验证时的过渡状态。写作前先搜索所钉提交的冻结库，并阅读候选声明的假设与结论；已有匹配声明时必须引用 Lean，不得改用书面证明。若上游已冻结而当前锁尚未包含，先升级或刷新钉版，不以旧锁为由降为书面证明。未证问题仍用 `conjecture` 或 `problem`。有纸面论证但没有 DOI 的材料可作为注明出处和边界的注记，不得使用书面证明徽章；不要为通过检查编造 DOI。

## 必填证据

定理类环境使用 `status="written-proof"` 时，还必须填写：

| 属性 | 含义 |
| --- | --- |
| `proof="pf-result"` | 本语言版本中非空的证明块，可跨章节；各版本都须有完整论证 |
| `doi="10.<注册者>/<后缀>"` | 支持该陈述及其证明的文献 DOI，只填一个裸标识符，不填 URL |
| `source="Theorem 2.1"` | 用英文写原文定位：定理/引理编号；没有编号时写章节和页码，如 `§4, p.12` |
| `request="https://github.com/the-omega-institute/trureturing-requests/issues/<编号>"` | 对应数学结果的形式化请求，不能填 PR、评论片段链接或别的仓库 |

这些属性与环境种类、id 一起逐语言对齐。禁止同时带 `lean`（空值也不行）。DOI 是否真实、来源是否证明了同一陈述，以及是否已有匹配冻结声明，由作者与评审核对；格式检查、DOI 链接或 issue 登记不证明数学正确性。

所有输出中的紫色“书面证明 / WRITTEN PROOF”与绿色 `LEAN ✓` 分开。正文、账本与演示稿提供 DOI 和请求链接，书面证明不计入 Lean 数量。

## Issue 标题

统一格式：

```text
[Formalization] <Result name> | DOI:<bare DOI> | <Source location>
```

请求标题、正文和登记评论统一使用英文，结果名称用简明英文；文献原题、数学记号与原文编号保留原写法。不把书名、语言、处理状态或优先级塞进标题。定位用 `Theorem 2.1`、`Lemma 3` 或 `§4, p.12`。一个 issue 追踪一项数学结果；不要把一篇论文的全部结果混成一个请求。标题不超过 GitHub 的 256 字符限制。

## 先搜索，再登记

1. 先在 trureturing 冻结库中按数学对象、结论形状、作者和术语变体搜索，核对声明是否陈述同一结果。只证明特例、变体或等价改写的声明不能冒充该结果。
2. 在 [trureturing-requests](https://github.com/the-omega-institute/trureturing-requests/issues) 搜索 DOI、原文编号及结论关键词，包含已关闭的问题。去重依据数学陈述，不只依据标题或 DOI。
3. 已有对应 issue：引用它，并在正文或新评论补充本书用途。不同文献证明同一结果时复用同一 issue，在评论列出新增 DOI 和定位；标题保留最初的规范来源，不为另一本书、另一语言或另一份证明重复开 issue。
4. 没有对应 issue：按上述标题格式新建。正文包含精确陈述（假设、量词和边界）、DOI 与原文定位、Lean 检索范围及未匹配的原因、已有相关声明及差异、本书的引用位置和用途。不要将“待形式化”写成“数学尚未证明”。
5. 在新 issue 正文或已有 issue 的评论中，为每个书中结果加入以下登记段。替换全部占位符；即使同一 issue 已有其他书登记，也要添加自己的记录：

```markdown
<!-- tbook:<library-owner/repo>:<book-slug>:<environment-id> -->
DOI:<same bare DOI as the environment> | <same source location>

- Book and chapter: <source or reading-page link>, environment `<id>`.
- Use: <why this result is needed and which later arguments depend on it>.
- Exact statement to formalize: <matching the source and the book>.
- Lean search: <pinned commit, search terms, related declarations and gaps>.
```

登记标记中的仓库取 `site.toml [site].repo`，留空时由环境或 git remote 推断。每个 `(仓库, book-slug, 环境 id)` 只登记一次，翻译不重复登记。不要把正式登记写在围栏或引用里；登记中的 DOI 与定位必须同属这一用途。

可以用 `gh issue list --repo the-omega-institute/trureturing-requests --state all --search '<DOI 或关键词>'` 检索；确认复用或新建后，将准确正文写入文件，用 `gh issue create --title '…' --body-file <文件>` 或 `gh issue comment <编号> --body-file <文件>`（都带上述 `--repo`）登记。`./tbook check` 和构建命令只读取请求，不会自动发帖。

## 校验与统计

`./tbook check` 检查必填属性、多语言一致性、非空证明，联网核对 issue 存在、规范标题及正文/评论中的书籍登记；404、PR 链接或未登记会报错。`--offline` 只做本地检查，对未核验的请求给出警告；CI 中无法联网核验也报错。

```bash
./tbook requests                    # 按 issue 汇总本书库的使用情况
./tbook requests --json              # 导出 DOI、定位、书籍、章节、环境 id 与计数
./tbook requests --book <slug> --json # 只查看一本书的需求
```

英文标题建议优先取英文版本的结果名；没有英文版本时使用环境 id 作为提示，提交前由作者写成清晰的英文名称。

站点 `manifest.json` 的 `formalization_requests` 提供同一份数据。每个 issue 包含全部 DOI/定位来源、引用它的结果和书籍数；按书籍数、结果数降序列出，同一结果的翻译只计一次。跨书库可按共享 issue 中的登记标记汇总需求；计数是实际使用量，数学重要性、依赖关系与形式化难度仍需维护者判断。

当结果在 trureturing 合入并冻结后，在书库升级钉版，复核同一陈述，所有语言同步改用 `lean` 并删除 `status`、`proof`、`doi`、`source`、`request` 属性；证明正文和文献出处可以保留。更新原请求，注明冻结 GID、提交与使用它的书籍，不另开 issue。
