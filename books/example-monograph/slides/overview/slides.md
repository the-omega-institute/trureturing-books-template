---
# 01 封面（cover 版式：无页眉页脚，自带书代号、所钉提交与页码）
theme: ../../../../theme/slides
title: "黄金整数与可观测性 · 概览"
info: "示例专著《黄金整数与可观测性》的概览：模板的保证、第一章与第二章的主要定理、一个开放问题与全部输出。"
htmlAttrs:
  lang: "zh-CN"
deck:
  code: "GOLDEN//OBSERVE"
  book: "黄金整数与可观测性"
  title: "概览"
  version: "0.1.0"
  blurb: "模板的保证、第一章与第二章的主要定理、一个开放问题与全部输出。"
layout: cover
---

<p class="kicker">示例专著 · 演示文稿</p>
<h1 class="display">黄金整数<br>与<em>可观测性</em></h1>
<p class="lead">区分 Lean 验证、书面证明与开放问题的示例专著。已有匹配的冻结 Lean 验证时必须引用；书面证明附 DOI 或源论文仓库与形式化请求。</p>

---
# 02 模板的保证
section: "模板的保证"
---

<div class="body">
  <p class="kicker">What the template guarantees</p>
  <h2 class="t">优先引用<em>冻结的 Lean 声明</em></h2>
  <p class="lead">Lean 结果在所钉提交上逐条核对；只有没有匹配验证时，才允许有 DOI 或源论文仓库、关联证明与请求登记的书面证明。</p>
  <div class="flow mt-l">
    <div class="step"><span class="i">01 · 书</span><b>写明 GID</b><p>Lean 验证结果带 <code>lean="…"</code>，至少一条。</p></div>
    <div class="step"><span class="i">02 · 锁文件</span><b>钉住提交</b><p><code>trureturing.lock.json</code> 记录提交与解析结果。</p></div>
    <div class="step"><span class="i">03 · 冻结</span><b>只引冻结声明</b><p>列在 <code>Golden/Frozen/state</code> 中，种类为 theorem。</p></div>
    <div class="step ok"><span class="i">04 · 内核</span><b><LeanBadge gid="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued" /></b><p>徽章链接到所钉提交上的 Lean 源码。</p></div>
  </div>
  <div class="g3 mt-l">
    <Stat value="33" label="条 Lean 验证结论（全书）" tone="ok" />
    <Stat value="3" label="个开放问题与猜想（全书），标为 OPEN" tone="warn" />
    <Stat value="1" label="条书面证明，附 DOI 或源论文仓库与形式化请求" />
  </div>
</div>
<Source>docs/ARCHITECTURE.md §1、§4；trureturing.lock.json</Source>

---
# 03 第一章（section 版式：大号章节编号）
layout: section
chapter: "01"
section: "第一章"
---

<p class="kicker">Chapter 1</p>
<h2 class="t">黄金整数的<em>进位亏量</em></h2>
<p class="lead">每个自然数都唯一地写成互不相邻的 Fibonacci 数之和。把权重 <Tex t="F_i" /> 换成黄金比的幂 <Tex t="\varphi^i" />，得到实数 <Tex t="\beta(n)" />；<Tex t="\beta" /> 不保持加法，差额就是亏量。</p>
<TheoremCard class="compact mt-l" kind="definition" label="定义1.1" title="归一化亏量" gid="D5/S1/Deficit/DeficitInteger.deficit" cite="def-deficit">

$$c(v_1, v_2) = \beta(v_1) + \beta(v_2) - \beta(v_1 + v_2)$$

</TheoremCard>

---
# 04 定理 1.3：三值
section: "第一章 · 亏量"
---

<div class="body">
  <p class="kicker">Theorem 1.3</p>
  <h2 class="t">无论输入多大，亏量只取 <em>−1、0、1</em></h2>
<TheoremCard class="mt" label="定理1.3" title="亏量只取三个值" gid="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued" cite="thm-deficit-three-valued">

对所有自然数 $v_1, v_2$，

$$c(v_1, v_2) \in \{-1,\ 0,\ 1\}.$$

</TheoremCard>
  <p class="lead mt">例如 <Tex t="\beta(1) = \varphi^2" />、<Tex t="\beta(2) = \varphi^3" />，于是 <Tex t="c(1, 1) = 2\varphi^2 - \varphi^3 = 1" />。这个界对任意大的输入都成立，把逐位进位这一算术算法和一个精确结论联系起来，可以作为后续推理的前提反复使用。</p>
</div>
<Source>D5/S1/Deficit/DeficitThreeValued.lean · 第一章 定理1.3</Source>

---
# 05 定理 1.2：整数与进位；定理 1.3 的证明思路
section: "第一章 · 亏量"
---

<div class="body">
  <p class="kicker">Theorem 1.2</p>
  <h2 class="t">亏量是整数，恰好<em>数出了进位</em></h2>
<TheoremCard class="compact mt-s" label="定理1.2" title="亏量是整数，且等于带符号的进位计数" gid="D5/S1/Deficit/DeficitInteger.deficit_integer" cite="thm-deficit-integer">

对所有自然数 $v_1, v_2$，亏量 $c(v_1, v_2)$ 等于它在收缩面（Galois 共轭）上的读数，是一个整数，并且等于把两个 Zeckendorf 表示逐位相加后、规范化过程中两条最低重复进位规则的带符号计数。

</TheoremCard>
  <p class="kicker mt-s">Proof of theorem 1.3 · 定理1.3 的证明思路</p>
  <div class="flow mt-s">
    <div class="step"><span class="i">01 · 收缩面</span><b>换成共轭</b><p>在 <Tex t="\psi = (1-\sqrt5)/2" /> 的幂上求值：每个 <Tex t="\beta'(v)" /> 落在长度恰为 1 的窗口 <Tex t="[-\psi^2, -\psi]" /> 中。</p></div>
    <div class="step"><span class="i">02 · 夹逼</span><b>严格小于 2</b><p>于是收缩面上的读数满足 <Tex t="-2 \lt c(v_1, v_2) \lt 2" />。</p></div>
    <div class="step ok"><span class="i">03 · 整数</span><b>只剩三个值</b><p>由定理1.2 它是整数，所以 <Tex t="c \in \{-1, 0, 1\}" />；完整证明由 Lean 内核检查。</p></div>
  </div>
</div>
<Source>D5/S1/Deficit/DeficitInteger.lean · 第一章 定理1.2 与定理1.3 的证明</Source>

---
section: "第一章 · 书面证明"
---

<div class="body">
  <p class="kicker">Written proof · 命题 1.12</p>
  <h2 class="t">从相位面积到<em>数对的极限频率</em></h2>
<TheoremCard class="mt-s" label="命题1.12" title="亏量的极限频率" status="written-proof" cite="rem-areas-not-frequencies" doi="10.1007/BF01475864" source="pp.313-352 (equidistribution; derived result)" request="https://github.com/the-omega-institute/trureturing-requests/issues/1">

令 $a_n^+$、$a_n^-$ 为 $0\le v_1,v_2<n$ 中亏量取 $+1$、$-1$ 的比例。

$$\lim_{n\to\infty}a_n^+=\frac{1}{2\varphi^2},\qquad \lim_{n\to\infty}a_n^-=\frac{1}{2\varphi^4}.$$

</TheoremCard>
  <p class="lead mt">Weyl 等分布定理给出一维区间比例；矩形计数的乘积与网格夹逼把它推广到两个相位三角形。该推导尚无匹配的冻结 Lean 验证，已登记形式化请求。</p>
</div>
<Source>书面论证 · pf-deficit-frequencies · trureturing-requests#1</Source>

---
# 06 第二章
layout: section
chapter: "02"
section: "第二章"
---

<p class="kicker">Chapter 2</p>
<h2 class="t">反驳与<em>可观测性</em></h2>
<p class="lead">对正整数 <Tex t="n" />，令 <Tex t="a(n)" /> 为满足 <Tex t="(1 + 1/n)^k \le 2" /> 的最大自然数 <Tex t="k" />。Greathouse 为 OEIS A175406 猜想了一个取整公式：</p>
<div class="card hot mt">
  <h4>猜想 · Greathouse（OEIS A175406）</h4>
  <Tex display t="a(n) = \left\lfloor \left(n + \tfrac{1}{2}\right) \log 2 \right\rfloor \qquad (n \ge 1)" />
</div>

---
# 07 定理 2.1 与开放问题 2.2
section: "第二章 · 反驳"
---

<div class="body">
  <p class="kicker">Theorem 2.1 · Open problem 2.2</p>
  <h2 class="t">一个反例推翻猜想；它是否最小<em class="warn">仍然开放</em></h2>
  <div class="g2 mt-s">
    <div>
      <TheoremCard class="compact" label="定理2.1" title="该取整公式不成立" gid="D5/S0/Certificates/GreathouseLogTwoFloorRefutation.result" cite="thm-greathouse-refuted">
        <p>猜想的公式并非对所有 <Tex t="n \ge 1" /> 成立。</p>
      </TheoremCard>
      <p class="kicker mt-s">证明中的见证 · 不在定理陈述中</p>
      <dl class="readout">
        <dt><Tex t="n_0" /></dt><dd class="cy">1121626023352383</dd>
        <dt>公式</dt><dd>777451915729368</dd>
        <dt><Tex t="a(n_0)" /></dt><dd class="hot">777451915729367<small>小一</small></dd>
      </dl>
    </div>
    <TheoremCard class="compact" label="开放问题2.2" title="最小反例" status="open" cite="prob-greathouse-minimal">
      <p><Tex t="n_0" /> = <span class="mono">1121626023352383</span> 是否是使公式失效的最小 <Tex t="n" />？使公式失效的输入有怎样的刻画？</p>
      <p>trureturing 只证明了公式并非处处成立，不主张 <Tex t="n_0" /> 最小。</p>
    </TheoremCard>
  </div>
</div>
<Source>D5/S0/Certificates/GreathouseLogTwoFloorRefutation.lean（result : ¬ claim）· 第二章</Source>

---
# 08 定理 2.3：目标恢复
section: "第二章 · 可观测性"
---

<div class="body">
  <p class="kicker">Theorem 2.3</p>
  <h2 class="t">观测能恢复什么：<em>读数相同，目标就必须相同</em></h2>
<TheoremCard class="mt-s" label="定理2.3" title="目标恢复判据" gid="D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.target_recovery_criterion" cite="thm-target-recovery">

设状态空间 $X$ 非空，过程读数 $p: X \to P$，目标 $t: X \to T$。存在恢复函数 $r$ 使 $t = r \circ p$，当且仅当任意两个读数相同的状态有相同的目标值；这又等价于目标缺陷关系为空。

$$\exists\, r,\ t = r \circ p \iff \bigl(p(x) = p(y) \Rightarrow t(x) = t(y)\bigr) \iff \operatorname{defect}(p, t) = \varnothing$$

</TheoremCard>
  <p class="lead mt">边界：定理只断言恢复函数<b>存在</b>，不提供算法，也不给出代价界。</p>
</div>
<Source>D5/S3/ConceptDynamics/Restoration/TargetRecoveryCriterion.lean · 第二章 定理2.3</Source>

---
# 09 输出
section: "输出"
---

<div class="body">
  <p class="kicker">One source, every format</p>
  <h2 class="t">一份 Markdown，<em>六种输出</em></h2>
  <p class="lead">编号、证据徽章与来源链接在各端一致；中文为权威版本，英文逐条对齐。</p>
  <div class="g3 mt">
    <div class="tile"><i>MDBOOK</i><b>HTML</b><span>在线阅读：KaTeX 数学、中英文切换，定理链接到 Lean 源码。</span></div>
    <div class="tile"><i>TYPST</i><b>PDF</b><span>屏幕版深色、印刷版白底，同一套编号与徽章。</span></div>
    <div class="tile"><i>EPUB 3</i><b>Apple Books</b><span>MathML 数学，在 iPhone、iPad 与 Mac 上阅读。</span></div>
    <div class="tile"><i>TRURETURING-VISUALIZE</i><b>可视化</b><span>交互页面嵌入章节；PDF 与 EPUB 中给出缩略图与地址。</span></div>
    <div class="tile"><i>TRURETURING-FILM</i><b>视频</b><span>脚本、场景与字幕在仓库中，成片随站点构建。</span></div>
    <div class="tile now"><i>SLIDEV · 当前</i><b>演示文稿</b><span>就是这一份：在线演示，并附可下载的 PDF。</span></div>
  </div>
</div>
<Source>./tbook build all → build/ 与 _site/（GitHub Pages）</Source>

---
# 10 结尾（cover 版式）
layout: cover
---

<p class="kicker">Read · Verify · Extend</p>
<h1 class="display">书负责解释，<br><em>Lean</em> 负责成立</h1>
<p class="lead">在线阅读，下载 PDF 与 EPUB，或者在所钉的 trureturing 提交上逐条核对每一条定理。</p>
<p class="lead mt mono hl-cyan">./tbook check · ./tbook build all</p>
