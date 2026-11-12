# 前言

本书从一个具体的算术现象出发。每个自然数都唯一地写成互不相邻的 Fibonacci 数之和，即它的 Zeckendorf 表示；把其中的 Fibonacci 权重换成黄金比 $\varphi = (1+\sqrt5)/2$ 的幂，加法就不再精确，留下的差额称为亏量。[第一章](ch01-golden-deficit.md)证明亏量是整数，而且无论输入多大，都只取 $-1$、$0$、$1$ 三个值（[@thm-deficit-three-valued]）。

由这个例子引出两个更一般的问题：怎样确定地否定一个断言，以及一个读数能告诉我们什么、不能告诉我们什么。对前者，本书的回答是有限的、可以机械检查的证书；对后者，是读数之间的一个序，它把恢复、记忆与熵联系在一起。

全书优先引用 [trureturing](https://github.com/the-omega-institute/trureturing) 中已被 Lean 内核验证并冻结的声明[^frozen]，书中陈述不超出所引声明。只有没有匹配的冻结 Lean 验证时，才允许显式标为“书面证明”：必须给出关联证明、DOI 与原文定位，并在 [trureturing-requests](https://github.com/the-omega-institute/trureturing-requests) 登记形式化需求。本书的例子是 [@rem-areas-not-frequencies]。真正尚未解决的结论写成猜想或开放问题。Lean 代码在 trureturing 中，本书只按 GID（模块路径加声明名）引用。

本书同时是 trureturing 书籍模板的示例专著：定理环境与交叉引用、脚注、表格、图、定义列表，以及可视化、视频与演示文稿，这些写法在书中都有实例。

[^frozen]: 冻结是 trureturing 的一道流程：模块经 Lean 内核验证（不含 `sorry`，不依赖仓库自设的公理）之后，流程才在 `Golden/Frozen/state/` 下为它写入状态片，记录模块陈述的摘要和其中每条声明的名称与种类。本书标为 `LEAN ✓` 的定理、引理、命题与推论只引用在所钉提交上列于状态片、种类为 theorem 的声明。

## 各章内容 {#sec-preface-map}

[第一章 黄金整数的进位亏量](ch01-golden-deficit.md)
: 定义亏量 $c(v_1, v_2)$，证明它是整数并等于带符号的进位计数（[@thm-deficit-integer]），只取三个值（[@thm-deficit-three-valued]）。随后把同一组数位放在展开面与收缩面两张面孔上读，解释其中的道理，用两个黄金相位之和判定亏量取哪个值（[@thm-beatty-deficit]、[@thm-golden-phase]），并计算相位正方形中亏量取 $+1$ 与取 $-1$ 的两块区域的面积（[@prop-phase-areas]）。

[第二章 反驳与可观测性](ch02-refutation-observation.md)
: 两种否定。一种是反驳：Greathouse 为 OEIS A175406 猜想的取整公式不成立（[@thm-greathouse-refuted]），证明中所用的反例是否最小仍然开放（[@prob-greathouse-minimal]）；有限的反例与 Farkas 权重都是可以机械检查的证书。另一种是不可观测：在非空的状态空间上，目标能从读数恢复，当且仅当读数相同的状态目标也相同（[@thm-target-recovery]）；对每个模数 $m \ge 2$，模 $m$ 的余数都不能决定亏量（[@thm-modulus-blind]）。

[第三章 细化、记忆与信息](ch03-refinement-memory.md)
: 把“能否恢复”看作读数之间的序，从三个方向考察：细化不增加风险、不减少代价（[@thm-refinement-tradeoff]）；遗忘定义中的“后来不再知道”可以换成一个见证，即后来的读数把事件取值不同的两个世界读成相同（[@thm-forgot-iff]）；在有限的状态空间上，确定性映射保持熵，当且仅当它不合并正概率的状态（[@thm-entropy-injective]）。

[第四章 黄金词与回归](ch04-golden-word.md)
: 把每个自然数最低的 Zeckendorf 数位依次排开，得到黄金词；它长度为 $n$ 的因子恰有 $n+1$ 个（[@thm-factor-complexity]）。随后讨论黄金旋转在 Fibonacci 时刻的回归（[@thm-revival-score]），以及亏量在素因子分解上的一个用处（[@thm-almost-additive]）。本章还记下一个开放问题（[@prob-revival-spectrum]）与一个猜想（[@conj-independence]）。

[附录 A 齐肯多夫表示与进位](appendix-a-zeckendorf.md)
: 第一章所用的背景：齐肯多夫表示的存在、唯一与保序，以及把两个表示的逐位和化回规范形的进位规则。从同一个数字串出发的两条进位路径总能汇合（[@thm-carry-confluent]）；化到规范形时，终点与带符号的进位电荷都与路径无关（[@thm-charge-unique]）。

第一章是全书的起点。附录 A 可以先读，也可以在需要时查阅。第二章的反驳部分不依赖第一章，后半部分用到第一章的黄金相位；第三章接着第二章的[@thm-target-recovery]展开；第四章用到第一章的亏量与附录 A 的齐肯多夫表示。

同一章内的各种编号条目共用一个计数器，编号形如“定理1.3”：点前是章号，点后是该条目在本章编号条目中的序号；附录中的条目编号为 A.1、A.2……。Lean 验证结果的证明块解释思路；书面证明块给出所引用的纸面论证，由作者和评审核对。书中的数值表都是用程序算出的，正文注明它们是计算，不是证明。

## 徽章与颜色 {#sec-preface-badges}

颜色在本书中有固定的含义。

| 标记 | 颜色 | 含义 |
| --- | --- | --- |
| `LEAN ✓` | 绿 | 定理、引理、命题与推论：所引的每条声明在所钉提交上都已被 Lean 内核验证并冻结。徽章链接到第一条声明的源码 |
| `书面证明` | 紫 | 没有匹配的冻结 Lean 验证；关联证明、DOI、原文定位与形式化请求齐全，由作者和评审核对 |
| `OPEN` | 红 | 猜想与开放问题：没有 Lean 证明，书中不把它们当作已证结论，并注明问题记载在 trureturing 的哪个文件中 |
| 当前位置 | 琥珀 | 只表示“当前”：侧栏中正在阅读的一章、语言切换中的当前语言、键盘焦点 |

绿色只留给 Lean 已验证的结论，琥珀色只表示当前位置，红色标出开放问题，紫色标出书面证明。徽章由构建根据锁文件生成，不是手写的：锁文件不能确认所引声明是已冻结的 Lean 定理时，构建显示红色的 `UNVERIFIED`，`./tbook check` 报错，书就不能发布。

带 Lean 引用的条目末尾列出所引声明的名称，链接到所钉提交上的源文件；定义也引用 Lean 中的 `def`，但没有徽章，因为定义没有需要验证的结论。正文中也可以直接链接一条声明，例如 [@thm-deficit-three-valued] 就是 [`deficit_three_valued`](lean:D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)。

## 可视化、视频与演示文稿 {#sec-preface-media}

[第一章](ch01-golden-deficit.md)末尾有一个交互可视化：选择 $v_1$ 与 $v_2$，逐步观察两个 Zeckendorf 表示相加后的进位，并在亏量图上看 $c(v_1, v_2)$ 的分布。同一处还有一段约五十秒的讲解视频，用动画演示进位与亏量的三个值，配英文旁白与中英双语字幕。

[第二章](ch02-refutation-observation.md)末尾链接一份演示文稿，概览第一、二章的主要结果与一个开放问题，可以在线演示，也可以下载 PDF。

可视化与视频由本书仓库构建，随网站发布。画面上的数值是页面上的计算，帮助理解，不是证明；绿色结果以 Lean 验证为依据，紫色结果以所引书面证明为依据。PDF 与 EPUB 中不能交互或播放：可视化与视频改为显示缩略图或海报，三处都附在线地址。

## 姊妹篇 {#sec-preface-primer}

本书库还有一本入门小书《斐波那契与卢卡斯：一本可验证的入门小书》，从 Fibonacci 递推讲到黄金比与 Lucas 数，每条定理同样经 Lean 内核验证。不熟悉 Fibonacci 数与黄金比的读者可以先读它。两本书彼此独立，本书不引用它的条目。

## 验证账本 {#sec-preface-ledger}

书末的“形式化验证账本”由构建自动生成。它开头写明所钉的 trureturing 提交，然后逐条列出 Lean 验证的定理、引理、命题与推论：每条的 Lean 声明链接到该提交上的源码，状态一列链接到冻结状态片；书面证明单列 DOI、原文定位、关联证明与请求链接；最后列出全部开放问题与猜想。每次检查时，`./tbook check` 都在所钉提交上重新读取状态片，逐条核对声明的名称、种类与陈述摘要。
