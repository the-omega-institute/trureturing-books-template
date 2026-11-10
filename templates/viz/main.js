/* __CODE__ · __TITLE__
   Starter: 3-column layout matching books/example-monograph/viz/golden-carry/ (inputs & readouts | step ledger & rail | 2D phase map & evidence).
   Replace the model and drawing; keep the drawer text honest about book sections, Lean theorems and model limits.
   Text written from script goes through TRV.L(中文, English); re-render it in TRV.onLang(...).
   Colours come from the tokens: TRV.palette.cyan, TRV.rgb.magenta, … (never hard-coded hex). */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const N = 16;
  const state = { a: 6, b: 5, pass: 4, trace: null, timer: null };

  TRV.startGlitch($('app'));
  TRV.drawer({ drawer: $('drawer'), open: $('infoBtn'), close: $('drawerClose') });

  function buildTrace(a, b) {
    const bits = (n) => [0, 1, 2, 3].map((k) => (n >> k) & 1);
    const da = bits(a), db = bits(b);
    const passes = [];
    let carry = 0;
    const cur = da.map((x, i) => x + db[i]);
    for (let k = 0; k < 4; k++) {
      const v = da[k] + db[k] + carry;
      const nextCarry = v >= 2 ? 1 : 0;
      const delta = nextCarry - carry;
      cur[k] = v & 1;
      passes.push({ step: k + 1, cells: cur.slice(), touch: [k], delta, rule: nextCarry ? 'R₀' : 'R₁', code: `bit ${k}: ${v} → ${cur[k]} (c=${nextCarry})` });
      carry = nextCarry;
    }
    const deltaSum = ((a + b) % 3) - 1;
    return { a, b, da, db, passes, final: cur.slice(), delta: deltaSum };
  }

  function renderReadouts() {
    const t = state.trace;
    $('roA').textContent = String(t.a);
    $('roB').textContent = String(t.b);
    $('roSum').textContent = String(t.a + t.b);
    $('roSteps').textContent = String(t.passes.length);
    const dEl = $('roDeficit');
    dEl.textContent = t.delta > 0 ? '+1' : t.delta < 0 ? '−1' : '0';
    dEl.className = t.delta > 0 ? 'vpos' : t.delta < 0 ? 'vneg' : 'vzero';
    $('roDeficitSub').textContent = TRV.L(`(${t.a} + ${t.b}) mod 3 − 1`, `(${t.a} + ${t.b}) mod 3 − 1`);
  }

  function cellStrip(cells, touch) {
    const tset = new Set(touch || []);
    return `<div class="cells">${cells.slice().reverse().map((d, idx) => {
      const pos = cells.length - 1 - idx;
      const cls = [d === 1 ? 'd1' : d >= 2 ? 'd2' : 'd0', tset.has(pos) ? 'touch' : ''].filter(Boolean).join(' ');
      return `<span class="${cls}">${d}</span>`;
    }).join('')}</div>`;
  }

  function renderLedger() {
    const t = state.trace, P = t.passes.length, p = Math.min(state.pass, P);
    $('ledgerSub').textContent = TRV.L(`共 ${P} 轮 · 点击任意一行跳到该轮`, `${P} passes · click any row to jump`);
    const rows = [];
    rows.push(`<div class="drow hdr"><span class="lab">${TRV.L('位权', 'bit')}</span><div class="cells">${[3, 2, 1, 0].map((k) => `<span>2<sup>${k}</sup><small>${1 << k}</small></span>`).join('')}</div><span class="what">${TRV.L('操作 · 贡献', 'action · delta')}</span></div>`);
    rows.push(`<div class="drow input"><span class="lab">a = ${t.a}</span>${cellStrip(t.da)}<span class="what"><code>${TRV.L('输入 a', 'input a')}</code></span></div>`);
    rows.push(`<div class="drow input"><span class="lab">b = ${t.b}</span>${cellStrip(t.db)}<span class="what"><code>${TRV.L('输入 b', 'input b')}</code></span></div>`);
    t.passes.forEach((st, idx) => {
      const k = idx + 1;
      const cls = ['drow', 'pass', k === p ? 'now' : '', k > p ? 'future' : ''].filter(Boolean).join(' ');
      const sgnCls = st.delta > 0 ? 'pos' : st.delta < 0 ? 'neg' : 'zero';
      const sgnTxt = st.delta > 0 ? '+1' : st.delta < 0 ? '−1' : '0';
      rows.push(`<div class="${cls}" data-pass="${k}"><span class="lab">#${k} · ${st.rule}</span>${cellStrip(st.cells, st.touch)}<span class="what"><span class="sgn ${sgnCls}">${sgnTxt}</span><code>${st.code}</code></span></div>`);
    });
    rows.push(`<div class="drow final ${p === P ? 'now' : 'future'}" data-pass="${P}"><span class="lab">a+b = ${t.a + t.b}</span>${cellStrip(t.final)}<span class="what"><span class="sgn zero">✓</span><code>Δ = ${t.delta > 0 ? '+1' : t.delta < 0 ? '−1' : '0'}</code></span></div>`);
    $('ledger').innerHTML = rows.join('');
    $('ledger').querySelectorAll('[data-pass]').forEach((el) => {
      el.addEventListener('click', () => { stopPlay(); setPass(Number(el.dataset.pass)); });
    });
    $('tape').innerHTML = t.passes.map((st, idx) => {
      const k = idx + 1;
      const cls = [st.delta > 0 ? 'pos' : st.delta < 0 ? 'neg' : 'zero', k > p ? 'future' : '', k === p ? 'now' : ''].filter(Boolean).join(' ');
      return `<i class="${cls}" data-pass="${k}"></i>`;
    }).join('');
    $('tape').querySelectorAll('i').forEach((el) => {
      el.addEventListener('click', () => { stopPlay(); setPass(Number(el.dataset.pass)); });
    });
    $('tapeSum').textContent = `Δ = ${t.delta > 0 ? '+1' : t.delta < 0 ? '−1' : '0'}`;
    $('pass').max = String(P);
    $('pass').value = String(p);
    $('passLabel').textContent = TRV.L(`第 ${p} / ${P} 轮`, `Pass ${p} / ${P}`);
  }

  function drawHeat() {
    if (TRV.thumbMode) { drawCover(); return; }
    const cv = $('heat');
    const { width: W, height: H } = TRV.fitCanvas(cv);
    const ctx = cv.getContext('2d');
    const pal = TRV.palette();
    ctx.fillStyle = pal.stage;
    ctx.fillRect(0, 0, W, H);
    const pad = 20, side = Math.min(W, H) - pad * 2;
    const cell = side / N;
    let pos = 0, zero = 0, neg = 0;
    for (let b = 1; b <= N; b++) {
      for (let a = 1; a <= N; a++) {
        const d = ((a + b) % 3) - 1;
        if (d > 0) { pos++; ctx.fillStyle = pal.cyan; }
        else if (d < 0) { neg++; ctx.fillStyle = pal.magenta; }
        else { zero++; ctx.fillStyle = pal.panelEdge; }
        ctx.fillRect(pad + (a - 1) * cell + 0.5, pad + (N - b) * cell + 0.5, Math.max(1, cell - 1), Math.max(1, cell - 1));
      }
    }
    const cx = pad + (state.a - 1) * cell, cy = pad + (N - state.b) * cell;
    ctx.strokeStyle = pal.amber;
    ctx.lineWidth = 2;
    ctx.strokeRect(cx, cy, cell, cell);
    $('heatCounts').textContent = `+1: ${pos} · 0: ${zero} · −1: ${neg}`;
  }

  function drawCover() {
    const cv = $('heat');
    const { width: W, height: H, dpr } = TRV.fitCanvas(cv);
    const ctx = cv.getContext('2d');
    const pal = TRV.palette();
    ctx.fillStyle = pal.void;
    ctx.fillRect(0, 0, W, H);
    const u = Math.min(W / 1280, H / 720);
    const ox = 64 * u, side = 580 * u, oy = (H - side) / 2, cell = side / N;
    for (let b = 1; b <= N; b++) {
      for (let a = 1; a <= N; a++) {
        const d = ((a + b) % 3) - 1;
        ctx.fillStyle = d > 0 ? pal.cyan : d < 0 ? pal.magenta : pal.panelEdge;
        ctx.fillRect(ox + (a - 1) * cell + 1, oy + (N - b) * cell + 1, cell - 2, cell - 2);
      }
    }
    ctx.strokeStyle = pal.amber;
    ctx.lineWidth = 3 * dpr;
    ctx.strokeRect(ox + (state.a - 1) * cell, oy + (N - state.b) * cell, cell, cell);
  }
  window.TRV_THUMB = drawCover;

  function setPass(p) {
    state.pass = Math.max(0, Math.min(state.trace.passes.length, p));
    renderLedger();
  }

  function stopPlay() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    $('play').setAttribute('aria-pressed', 'false');
    $('play').textContent = '▶';
  }

  function setInputs(a, b) {
    state.a = Math.max(1, Math.min(N, Math.round(a) || 1));
    state.b = Math.max(1, Math.min(N, Math.round(b) || 1));
    $('aNum').value = $('aRange').value = String(state.a);
    $('bNum').value = $('bRange').value = String(state.b);
    state.trace = buildTrace(state.a, state.b);
    state.pass = state.trace.passes.length;
    renderReadouts();
    renderLedger();
    drawHeat();
  }

  $('aNum').addEventListener('change', (e) => setInputs(e.target.value, state.b));
  $('aRange').addEventListener('input', (e) => setInputs(e.target.value, state.b));
  $('aDec').addEventListener('click', () => setInputs(state.a - 1, state.b));
  $('aInc').addEventListener('click', () => setInputs(state.a + 1, state.b));
  $('bNum').addEventListener('change', (e) => setInputs(state.a, e.target.value));
  $('bRange').addEventListener('input', (e) => setInputs(state.a, e.target.value));
  $('bDec').addEventListener('click', () => setInputs(state.a, state.b - 1));
  $('bInc').addEventListener('click', () => setInputs(state.a, state.b + 1));
  $('swapBtn').addEventListener('click', () => setInputs(state.b, state.a));
  $('randBtn').addEventListener('click', () => setInputs(1 + Math.floor(Math.random() * N), 1 + Math.floor(Math.random() * N)));
  $('first').addEventListener('click', () => { stopPlay(); setPass(0); });
  $('prev').addEventListener('click', () => { stopPlay(); setPass(state.pass - 1); });
  $('next').addEventListener('click', () => { stopPlay(); setPass(state.pass + 1); });
  $('last').addEventListener('click', () => { stopPlay(); setPass(state.trace.passes.length); });
  $('pass').addEventListener('input', (e) => { stopPlay(); setPass(Number(e.target.value)); });
  $('play').addEventListener('click', () => {
    if (state.timer) { stopPlay(); return; }
    if (state.pass >= state.trace.passes.length) setPass(0);
    $('play').setAttribute('aria-pressed', 'true');
    $('play').textContent = '⏸';
    state.timer = setInterval(() => {
      if (state.pass >= state.trace.passes.length) { stopPlay(); return; }
      setPass(state.pass + 1);
    }, 500);
  });

  TRV.onLang(() => { renderReadouts(); renderLedger(); drawHeat(); });
  window.addEventListener('resize', drawHeat);
  setInputs(6, 5);
})();
