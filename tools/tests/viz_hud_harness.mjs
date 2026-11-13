// Browser regressions for complete HUD text and the space it shares with the tour.
import { session, settle } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';
const book = listBooks()[0];
const T = await session();
const url = `${T.origin}/site/${book.slug}/viz/__hud__/`;
const note = 'The window selects the cyan points and projects them to the line below. Neighbouring points have different gaps, shown by the coloured intervals. Moving the window changes which points are selected. The green rings show the expansions of the natural numbers. Each mark and every label remains part of the same experiment when its card changes.';
const title = 'The window is shifted by u · six points selected in view · gaps between neighbours: 1, φ, φ²';
const legend = 'Dashed arcs: the states turning; dashed ink: the pulled-back observer';
const fixture = `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Chakra+Petch"><link rel="stylesheet" href="../assets/theme.css"><script src="../assets/shell.js"></script><script src="../assets/kit.js"></script><style>
/* A page may place its title below its original single row of scene buttons. */
#stage.local .hud-tl { top:46px }
</style></head><body><div class="app lab"><header class="top">A stage with a long note</header><aside class="deck"><div id="cards">${['a','b','c','d'].map(id=>`<button data-preset="${id}"><span class="cn zh">完整图例与窗口</span><span class="cn en">The window and its complete legend</span></button>`).join('')}</div></aside><main class="center"><div id="stage" class="stage" data-thumb><canvas class="fill"></canvas><div class="hud-tl"><b class="big">Window · u = 0</b><span class="sub"></span></div><div class="hud-tr">${['Window','Cassini','Returns','Gaps','Orbit'].map(t=>`<button class="chip">${t}</button>`).join('')}</div><div class="hud-bl"><span><i class="sw"></i><span id="longLegend"></span> · ρ<sub>A</sub> = φ<sup>2</sup></span><span><i class="sw"></i>ObserverProjectionWithoutAnOrdinaryWordBreak012345678901234567890</span><span><i class="sw"></i>the selected points</span></div></div><div class="tour"><button class="tbtn" data-tour="prev">◀</button><div class="what"></div><button class="tbtn" data-tour="next">▶</button></div></main><aside class="side">Readouts</aside><footer class="rail"><button class="tbtn">▶</button><input type="range" aria-label="Time"></footer></div><script>
window.longNote=${JSON.stringify(note)}; window.longTitle=${JSON.stringify(title)}; window.longLegend=${JSON.stringify(legend)};
window.cards=TRV.kit.cards(document.getElementById('cards'),{notes:Object.fromEntries(['a','b','c','d'].map(id=>[id,['窗口选择青色的点，并投影到下方的直线；移动窗口会改变哪些点被选中。每一个标记和完整的图例都属于当前实验。',longNote]])),tour:document.querySelector('.tour')});cards.pick('a');
window.text='short';window.paint=TRV.kit.painter(()=>{document.querySelector('.sub').textContent=text==='short'?'The selected points':TRV.L('窗口平移，六个点被选中；相邻点的间距为 1、φ 或 φ²。',longTitle);document.getElementById('longLegend').textContent=TRV.L('虚线：转动中的态；墨色虚线：拉回的观察者',longLegend);});paint.now();
</script></body></html>`;
await T.context.route(`${url}**`,r=>r.fulfill({contentType:'text/html',body:fixture}));
// Text rectangles, entry boxes, hit targets and normal-flow regions are measured independently of hudFit.
async function inspect() {
  return T.page.evaluate(() => {
    const st=document.getElementById('stage'), box=e=>e.getBoundingClientRect(), sr=box(st);
    const shown=e=>{for(let a=e;a;a=a.parentElement){const s=getComputedStyle(a);if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;}return true;};
    const inside=r=>r.left>=sr.left-.5&&r.right<=sr.right+.5&&r.top>=sr.top-.5&&r.bottom<=sr.bottom+.5;
    const meet=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>.5&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>.5;
    const textRects=e=>{const out=[],w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);for(let n=w.nextNode();n;n=w.nextNode())if(n.textContent.trim()&&shown(n.parentElement)){const r=document.createRange();r.selectNodeContents(n);out.push(...r.getClientRects());}return out;};
    const titles=textRects(st.querySelector('.hud-tl')), buttons=[...st.querySelectorAll('.hud-tr button')].filter(shown), br=buttons.map(box);
    const legends=[...st.querySelectorAll('.hud-bl>span')].filter(shown), lr=legends.flatMap(e=>[box(e),...textRects(e)]);
    const regions=['.stage','.tour','footer.rail'].map(q=>box(document.querySelector(q)));
    const note=document.querySelector('.tour-note');
    return {complete:[...titles,...br,...lr].every(inside),clear:titles.every(t=>br.every(b=>!meet(t,b)))&&[...titles,...br].every(t=>lr.every(l=>!meet(t,l))),
      hit:buttons.every(b=>{const r=box(b);return b.contains(document.elementFromPoint((r.left+r.right)/2,(r.top+r.bottom)/2));}),
      regions:TRV.still||regions.every((r,i)=>regions.every((s,j)=>i===j||!meet(r,s))),
      frame:!TRV.figure||document.documentElement.scrollHeight<=innerHeight,
      note:TRV.lang()!=='en'||note?.innerText===longNote,
      noteWidth:!note||box(note).width>=box(document.querySelector('.tour')).width-20,
      height:sr.height};
  });
}
for(const [query,width,height] of [['',1440,500],['',1081,320],['',390,844],['?embed=1',334,620],['?embed=1&preset=a',334,500],['?embed=1&preset=a',740,500],['?embed=1&preset=a&shot=1',334,500]]) {
  await T.page.setViewportSize({width,height});await T.page.goto(url+query);await T.page.evaluate(()=>document.fonts.ready);await settle(T.page,100);
  for(const lang of ['en','zh'])for(const local of [false,true]) {
    await T.page.evaluate(({lang,local})=>{TRV.setLang(lang);document.getElementById('stage').classList.toggle('local',local);}, {lang,local});
    // The first read after synchronous rendering must already have the final HUD layout, with no extra frame.
    for(const text of ['short','long','short','long']) {
      await T.page.evaluate(text=>{window.text=text;TRV.kit.flush();},text);
      const r=await inspect();T.check(`${query||'lab'} ${width}×${height} ${lang} local=${local} ${text}`,Object.entries(r).every(([k,v])=>k==='height'||v===true),JSON.stringify(r));
    }
  }
}
T.check('no page or request errors',T.errors.length===0,JSON.stringify(T.errors));
await T.finish();
