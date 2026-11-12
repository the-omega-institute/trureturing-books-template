// Shared runtime regressions, independent of example-book content.
import fs from 'node:fs';
import path from 'node:path';
import { session, settle, until, caseChanges, solidChecks, stageFirstChecks } from '../node/viz-testkit.mjs';
import { listBooks } from '../node/viz-common.mjs';
const book = listBooks().find((b) => fs.existsSync(path.join(b.dir, 'viz')));
if (!book) { console.log(JSON.stringify({ skip: 'no visible book with viz/' })); process.exit(0); }
const T = await session({ viewport: { width: 800, height: 600 } });
const page = T.page, rows = [];
const check = (name, ok, detail = '') => { rows.push({ name, ok: !!ok, detail }); console.log(JSON.stringify(rows.at(-1))); };
const url = `${T.origin}/site/${book.slug}/viz/__runtime__/`;
await T.context.route(`${url}**`, (r) => r.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="../assets/theme.css"><script src="../assets/shell.js"></script><script src="../assets/kit.js"></script><style>#st{width:calc(100vw - 2px);height:590px}#st>canvas{position:absolute;inset:0;width:100%;height:100%}</style></head><body><div class="stage" id="st"><canvas class="fill" id="cv"></canvas><div class="hud-tl"><b class="big">δ u φ</b><span class="sub">A long description with mathematical variables δ and φ</span></div><div class="hud-tr">${Array.from({length:8},(_,i)=>`<button class="chip">Scene ${i}</button>`).join('')}</div></div></body></html>` }));
await page.goto(url);
await settle(page);
const dashed = await page.evaluate(() => {
  document.getElementById('st').style.setProperty('--hud-flow','0');
  const st = TRV.kit.stage3(document.getElementById('st'), { canvas: document.getElementById('cv'), yaw: 0, pitch: 0 });
  const frame = (n, fade) => {
    st.begin(); st.path(Array.from({length:n+1},(_,i)=>[-1+2*i/n,-0.1,0]), { dash:[12,8], width:2, fade }); st.end();
    const c=st.ctx, d=c.getImageData(0,Math.round(st.H/2),st.W,1).data;
    return Array.from({length:st.W},(_,i)=>d[4*i+3]);
  };
  const sparse=frame(1,true), dense=frame(2000,true), plain=frame(1,false);
  const delta=(a,b)=>a.reduce((s,x,i)=>s+Math.abs(x-b[i]),0)/a.length;
  return { sparseDense:delta(sparse,dense), defaultUnfaded:delta(sparse,plain), gaps:dense.filter((x)=>x===0).length, ink:dense.filter((x)=>x>200).length };
});
check('dense dashed stage3 paths retain the gaps and the sparse-path phase', dashed.sparseDense < 2 && dashed.defaultUnfaded < 6 && dashed.gaps > 150 && dashed.ink > 100, dashed);
const arrow = await page.evaluate(() => {
  const cv=document.getElementById('cv'), g=TRV.kit.plot(cv,{x:[0,10],y:[0,10],pad:[0,0,0,0]});
  g.arrow([2,5],[8,5],{color:TRV.palette.cyan,headSize:20,width:2});
  const at=(x,y)=>g.ctx.getImageData(Math.round(x),Math.round(y),1,1).data[3];
  const head=at(g.X(8)-12,g.Y(5)+3), shaft=at(g.X(5),g.Y(5));
  TRV.kit.plot(cv,{x:[0,10],y:[0,10],pad:[0,0,0,0]}).arrow([2,5],[8,5],{head:false});
  return {head,shaft,noHead:at(g.X(8)-12,g.Y(5)+3)};
});
check('plot arrows draw a screen-sized head and honour head:false', arrow.head > 200 && arrow.shaft > 200 && arrow.noHead === 0, arrow);
await page.evaluate(()=>{const t=document.createElement('div');t.className='tag num c-cy backed';t.textContent='δ u φ';document.getElementById('st').appendChild(t);const sw=document.createElement('i');sw.className='sw ik';document.body.appendChild(sw);});
const css=await page.evaluate(()=>({tag:getComputedStyle(document.querySelector('.tag')).color,ink:getComputedStyle(document.querySelector('.sw')).backgroundColor,cyan:(()=>{const e=document.createElement('i');e.style.color=TRV.palette.cyan;document.body.appendChild(e);const c=getComputedStyle(e).color;e.remove();return c})(),inkToken:(()=>{const e=document.createElement('i');e.style.color=TRV.palette.ink;document.body.appendChild(e);const c=getComputedStyle(e).color;e.remove();return c})(),transform:getComputedStyle(document.querySelector('.tag')).textTransform,back:getComputedStyle(document.querySelector('.tag')).backgroundColor}));
check('numeric label colours and optional backings preserve mathematical case', css.tag===css.cyan && css.transform==='none' && css.back!=='rgba(0, 0, 0, 0)',css);
check('the ink legend swatch uses the ink token',css.ink===css.inkToken,css);
check('the Greek-case gate accepts unchanged notation',(await caseChanges(page)).length===0);
await page.addStyleTag({content:'.tag { text-transform:uppercase!important }'});
check('the Greek-case gate catches a page override',(await caseChanges(page)).some(t=>t.includes('δ')));
await page.evaluate(()=>document.getElementById('st').style.removeProperty('--hud-flow'));
for(const width of [334,390,740]){
  await page.setViewportSize({width,height:700});
  await until(page,()=>document.getElementById('st').hasAttribute('data-hud-flow'));
  const b=await page.evaluate(()=>{const r=s=>document.querySelector(s).getBoundingClientRect();return {tl:r('.hud-tl').bottom,tr:r('.hud-tr').top,end:r('.hud-tr').bottom,cv:r('#cv').top,h:r('#cv').height}});
  check(`HUD blocks and drawing have separate space at ${width}px`,b.tl<=b.tr && b.end<=b.cv && b.h>150,b);
}
// Independent geometry and pixels for the new solid options.
await page.setViewportSize({width:800,height:600});
await page.evaluate(async()=>{
  const mod=await import('../assets/solid-core.js');
  window.CORE=mod; window.C=mod.createScene({palette:TRV.palette});
  C.camera({W:800,H:600,yaw:0,pitch:0,unit:180});
});
const geometry=await page.evaluate(()=>{
  const square=(u,v)=>[u,-0.4,v], settings={u:[-1,1],v:[-1,1],nu:2,nv:2};
  const plane={vertices:[[-1,-0.6,-1],[1,-0.6,-1],[1,-0.6,1],[-1,-0.6,1]],faces:[[0,1,2,3]]};
  const query=()=>({hidden:C.occluded([0,0,0]),hit:C.hitAt(400,300)?.id||null});
  C.begin();C.surface('back',square,{...settings});C.poly('front',plane,{pick:false});C.end();const pass=query();
  C.begin();C.poly('glass',plane,{alpha:0.3});C.end();const glass=query();
  C.begin();C.surface('glass',square,{...settings,alpha:0.3});C.end();const surface=query();
  C.begin();C.tube('pipe',[[-1,-0.5,0],[1,-0.5,0]],{r:0.2});C.end();const tube=query();
  C.begin();C.tube('pipe',[[-1,-0.5,0],[1,-0.5,0]],{r:0.2,alpha:0.2});C.end();const clearTube=query();
  C.begin();const mesh=C.surface('fade',square,{...settings,alpha:(u,v)=>(u+1)/2});C.end();const a=Array.from(mesh.geometry.getAttribute('color').array).filter((_,i)=>i%4===3);
  C.begin();const pipe=C.tube('fade',[[-1,0,0],[0,0,0],[1,0,0]],{r:0.1,alpha:t=>4*t*(1-t)});C.end();const t=Array.from(pipe.geometry.getAttribute('color').array).filter((_,i)=>i%4===3);
  return {pass,glass,surface,tube,clearTube,a,t};
});
check('pick:false passes rays through a polyhedron while it still hides marks',geometry.pass.hidden&&geometry.pass.hit==='back',geometry);
check('transparent lit surfaces and polyhedra leave marks visible',!geometry.glass.hidden&&!geometry.surface.hidden,geometry);
check('opaque tubes hide and pick; transparent tubes leave marks visible',geometry.tube.hidden&&geometry.tube.hit==='pipe'&&!geometry.clearTube.hidden,geometry);
check('surface and tube vertex opacity reaches zero at the ends',Math.min(...geometry.a)===0&&Math.max(...geometry.a)===1&&Math.min(...geometry.t)===0&&Math.max(...geometry.t)===1,geometry);
const pixels=await page.evaluate(()=>{
  const cv=document.createElement('canvas'),r=CORE.createRenderer(cv,{pixelRatio:1});
  const grab=()=>{C.end();C.render(r);const copy=document.createElement('canvas');copy.width=800;copy.height=600;const g=copy.getContext('2d');g.drawImage(cv,0,0);return g.getImageData(0,0,800,600).data;};
  const dash=n=>{C.begin();C.line(Array.from({length:n+1},(_,i)=>[-1+2*i/n, -0.8+1.6*i/n, 0]),{dash:[12,8],width:2});return grab();};
  const a=dash(1),b=dash(2000);let delta=0;for(let i=0;i<a.length;i++)delta+=Math.abs(a[i]-b[i]);
  C.begin();C.surface('plane',(u,v)=>[u,-0.4,v],{u:[-1,1],v:[-1,1],nu:12,nv:4,alpha:(u,v)=>(u+1)/2});const faded=grab();
  const alpha=x=>faded[4*(300*800+x)+3];
  C.begin();C.circle([0,0,0],[0,0,1],1,{width:3});const ring=grab();
  const at=y=>ring[4*(y*800+400)+3];
  const result={delta:delta/a.length,left:alpha(250),right:alpha(550),circlePixels:Array.from(ring).filter((x,i)=>i%4===3&&x>0).length};
  r.dispose();C.dispose();return result;
});
check('solid dash spacing follows projected arc length independent of samples',pixels.delta<0.3,pixels);
check('vertex opacity produces a visible alpha gradient',pixels.right>pixels.left+100,pixels);
check('spherical circles draw visible front and back portions',pixels.circlePixels>500,pixels);
// Mixed stages keep canvas ownership, labels and screen coordinates coherent.
await page.evaluate(()=>{
  const st=document.getElementById('st'),cv=document.getElementById('cv');
  window.SC=TRV.kit.solid(st,{canvas:cv,yaw:0,pitch:0,onChange:()=>PAINT()});
  window.PAINT=TRV.kit.painter(()=>{SC.begin();SC.surface('sphere',(u,v)=>[Math.sin(v)*Math.cos(u),Math.sin(v)*Math.sin(u),Math.cos(v)],{u:[0,2*Math.PI],v:[0,Math.PI],nu:32,nv:16});SC.tag('x',[0,0,1],'x');SC.end();});
});
await settle(page);
const coords=await page.evaluate(()=>{const r=document.getElementById('cv').getBoundingClientRect(),q=SC.p([0,0,0]),ev={clientX:r.left+q[0],clientY:r.top+q[1]};return {near:SC.near(ev,[0,0,0]),hit:SC.hit(ev)?.id}});
check('solid hit and near agree with the bordered canvas origin',coords.near<1e-9&&coords.hit==='sphere',coords);
await page.evaluate(()=>{SC.active(false);TRV.kit.plot(document.getElementById('cv'),{x:[0,1],y:[0,1]}).line([[0,0],[1,1]],TRV.palette.cyan);});
check('switching to 2D returns the original canvas and hides solid labels',await page.evaluate(()=>SC.parked()&&document.getElementById('cv').style.visibility==='visible'&&[...document.querySelectorAll('.tags .tag')].every(t=>t.hidden)));
await page.evaluate(()=>{const cv=SC.overlay();TRV.kit.plot(cv,{x:[0,1],y:[0,1]}).dot(.5,.5,TRV.palette.amber);SC.active(true);});
await settle(page);
check('a 2D overlay survives restoration of the solid context',await page.evaluate(()=>!SC.parked()&&SC.overlay().getContext('2d')!==null&&SC.overlay().width>1));
// Updating a card while its stage is outside the iframe viewport updates the parked picture too.
const em = await T.newPage();
await em.goto(url + '?embed=1');
await em.evaluate(() => {
  const el=document.getElementById('st'); window.SIZE=0.9;
  window.SC=TRV.kit.solid(el,{canvas:document.getElementById('cv'),onChange:()=>PAINT()});
  window.PAINT=TRV.kit.painter(()=>{SC.begin();SC.surface('s',(u,v)=>[SIZE*Math.sin(v)*Math.cos(u),SIZE*Math.sin(v)*Math.sin(u),SIZE*Math.cos(v)],{u:[0,2*Math.PI],v:[0,Math.PI],nu:24,nv:12});SC.end();});
});
await until(em,()=>TRV.solids?.[0]?.contexts>0);
await settle(em);
await em.evaluate(()=>{document.getElementById('st').style.marginTop='1200px';scrollTo(0,0);});
await until(em,()=>SC.parked());
const offscreen=await em.evaluate(()=>{const n=SC.contexts;SIZE=0.4;SC.refresh();return n;});
await settle(em);
check('an offscreen card change draws and parks a fresh solid frame',await em.evaluate(n=>SC.contexts>n&&SC.parked()&&document.getElementById('cv').style.visibility==='visible',offscreen));
await em.close();
check('no page, console or request errors',T.errors.length===0,T.errors);
await T.browser.close();
process.exit(rows.every(r=>r.ok)?0:1);
