/* __CODE__ · __TITLE__
   A working stage-first page: a point on the unit circle, its shadow cos θ and its height sin θ, and the sum of
   their squares, which does not move. Replace the subject and keep the shape:
     · the stage shows the object itself, large, and the reader moves it directly;
     · each experiment card is one named situation with one sentence, citable from a chapter (?preset=<id>);
     · the rail is the one quantity that runs; the strip under the stage plots what changes against it;
     · window.STARTER_DEBUG lets the browser suite read the state (rename it for your page).
   Helpers: TRV (theme/viz/shell.js) and TRV.kit (theme/viz/kit.js). Method: skills/book-viz/SKILL.md. */
(() => {
  'use strict';
  const { kit, L } = TRV, { fix, sgn } = kit, P = TRV.palette;
  const $ = (id) => document.getElementById(id);
  const DEG = Math.PI / 180;
  const read = (deg) => { const c = Math.cos(deg * DEG), s = Math.sin(deg * DEG); return { deg, c, s, sum: c * c + s * s }; };

  /* ---------- stage: a 2D scene with equal scales on both axes ---------- */
  let view = null;
  function drawStage() {
    const now = read(clock.t), g = kit.plot($('cv'), { x: [-1.35, 1.35], y: [-1.35, 1.35], pad: [20, 20, 64, 46], equal: true });
    view = g;
    g.line([[g.x0, 0], [g.x1, 0]], P.faint, { width: 1 }); g.line([[0, g.y0], [0, g.y1]], P.faint, { width: 1 });
    const circle = []; for (let i = 0; i <= 120; i++) circle.push([Math.cos(i * 3 * DEG), Math.sin(i * 3 * DEG)]);
    g.line(circle, P.lineHot, { width: 1.4 });
    const arc = []; for (let i = 0; i <= 60; i++) arc.push([0.22 * Math.cos(now.deg * DEG * i / 60), 0.22 * Math.sin(now.deg * DEG * i / 60)]);
    g.line(arc, P.sigma, { width: 1, dash: [2, 3] });
    g.poly([[0, 0], [now.c, 0], [now.c, now.s]], P.magenta, { alpha: 0.12 });
    g.line([[0, 0], [now.c, 0]], P.cyan, { width: 4.5, glow: 10 });                     // the shadow
    g.line([[now.c, 0], [now.c, now.s]], P.magenta, { width: 3 });                      // the height
    g.line([[0, 0], [now.c, now.s]], P.amber, { width: 2.4, glow: 10 });                // the radius, always 1
    g.dot(now.c, now.s, P.amber, 6, { glow: 14 });
    if (!TRV.thumbMode) {   // the cover is wordless; the page and the stills of cited cards carry their labels
      g.text(now.c / 2, 0, fix(now.c, 2), P.cyan, { align: 'center', base: now.s >= 0 ? 'top' : 'bottom', dy: now.s >= 0 ? 8 : -8, size: 12 });
      g.text(now.c, now.s / 2, fix(now.s, 2), P.magenta, { align: now.c >= 0 ? 'left' : 'right', dx: now.c >= 0 ? 9 : -9, size: 12 });
    }
    $('hudBig').textContent = `θ = ${fix(now.deg, 0)}°`;
    $('hudSub').textContent = L(`影子 ${sgn(now.c, 2)} · 高度 ${sgn(now.s, 2)} · 平方和 ${fix(now.sum, 3)}`, `shadow ${sgn(now.c, 2)} · height ${sgn(now.s, 2)} · sum of squares ${fix(now.sum, 3)}`);
  }

  /* ---------- strip: what changes along the rail ---------- */
  function drawPlot() {
    const now = read(clock.t), g = kit.plot($('plot'), { x: [0, 360], y: [0, 1.25], pad: [30, 10, 10, 22] });
    g.axes({ yTicks: [0, 0.5, 1], xTicks: [[0, '0°'], [90, '90°'], [180, '180°'], [270, '270°'], [360, '360°']] });
    const cs = [], sn = []; for (let d = 0; d <= 360; d += 3) { const r = read(d); cs.push([d, r.c * r.c]); sn.push([d, r.s * r.s]); }
    g.hline(1, P.amber, { dash: [4, 3] }); g.line(cs, P.cyan); g.line(sn, P.magenta);
    g.vline(now.deg, P.amber, { alpha: 0.7 }); g.dot(now.deg, now.c * now.c, P.cyan, 4.5); g.dot(now.deg, now.s * now.s, P.magenta, 4.5);
    g.legend([[P.cyan, 'cos²θ'], [P.magenta, 'sin²θ'], [P.amber, L('两者之和', 'their sum'), 'dash']]);
    $('plotMeta').textContent = `${fix(now.c * now.c, 3)} + ${fix(now.s * now.s, 3)}`;
  }

  /* ---------- readouts: few, in plain words, with the one line that matters set large ---------- */
  function drawText() {
    const now = read(clock.t);
    $('roSum').innerHTML = `<span class="c-cy">${fix(now.c * now.c, 3)}</span> + <span class="c-mg">${fix(now.s * now.s, 3)}</span> = ${fix(now.sum, 3)}`;
    $('roSumSub').textContent = L('无论 θ 是多少', 'whatever θ is');
    $('roCos').textContent = sgn(now.c, 4); $('roSin').textContent = sgn(now.s, 4);
    $('roNote').textContent = Math.abs(now.s) < 0.02 ? L('点落在横轴上：只有影子，没有高度。', 'The point is on the horizontal axis: all shadow, no height.')
      : Math.abs(now.c) < 0.02 ? L('点在正上方或正下方：只有高度，没有影子。', 'The point is straight above or below: all height, no shadow.')
        : L(`影子占 ${fix(100 * now.c * now.c, 0)}%，高度占 ${fix(100 * now.s * now.s, 0)}%。`, `${fix(100 * now.c * now.c, 0)}% shadow and ${fix(100 * now.s * now.s, 0)}% height.`);
    $('pillAngle').querySelector('strong').textContent = `${fix(now.deg, 0)}°`;
    $('pillSum').querySelector('strong').textContent = fix(now.sum, 3);
  }

  const paint = kit.painter(() => { drawStage(); drawPlot(); drawText(); }, [$('stage'), $('plot')]);

  /* ---------- controls: the rail is the angle ---------- */
  const clock = kit.clock({
    range: $('now'), play: $('play'), label: $('tau'), speeds: $('speedChips'), max: 360, t: 60, rate: 60, step: 15,
    format: (t) => `θ ${t.toFixed(0)}° <small>/ 360°</small>`,
    onChange: (t) => { fTheta.set(Math.round(t)); paint(); }
  });
  const fTheta = kit.field($('theta'), { fmt: (v) => `${v}°`, onInput: (v) => { cards.mark(null); clock.pause(); clock.set(v); } });
  $('rew').addEventListener('click', () => { clock.pause(); clock.set(0); });
  // direct manipulation: drag the point round the circle
  let dragging = false;
  const toAngle = (ev) => { const b = $('cv').getBoundingClientRect(), x = view.invX(ev.clientX - b.left), y = view.invY(ev.clientY - b.top); return (Math.atan2(y, x) / DEG + 360) % 360; };
  $('cv').addEventListener('pointerdown', (ev) => { dragging = true; try { $('cv').setPointerCapture(ev.pointerId); } catch (e) { /* synthetic events */ } cards.mark(null); clock.pause(); clock.set(toAngle(ev)); });
  $('cv').addEventListener('pointermove', (ev) => { if (dragging) clock.set(toAngle(ev)); });
  for (const type of ['pointerup', 'pointercancel']) $('cv').addEventListener(type, () => { dragging = false; });

  /* ---------- experiment cards: where the story starts, whether it plays, and the frame a still shows ---------- */
  const PRESETS = { shadow: { at: 0 }, even: { at: 45 }, height: { at: 90 }, sweep: { at: 0, play: true, still: 135 } };
  const NOTES = {
    shadow: ['θ = 0°：点躺在横轴上，影子就是整条半径，高度为零。', 'θ = 0°: the point lies on the horizontal axis, the shadow is the whole radius and the height is zero.'],
    even: ['θ = 45°：影子与高度一样长，各占平方和的一半。', 'θ = 45°: shadow and height are equally long, and each holds half of the sum of squares.'],
    height: ['θ = 90°：点在正上方，影子缩成一个点，高度是整条半径。', 'θ = 90°: the point is straight above, the shadow shrinks to a point and the height is the whole radius.'],
    sweep: ['让点转一圈：青色与品红的两条曲线此消彼长，琥珀色的和始终停在 1。', 'Let the point go once around: the cyan and magenta curves trade places while the amber sum stays at 1.']
  };
  let booting = true;
  function applyPreset(id) {
    const p = PRESETS[id];
    clock.pause(); clock.set(p.at);
    // a still (cover, cited figure for PDF/EPUB) and the opening view of the full page show the telling frame;
    // inside a chapter the card plays once the reader has scrolled it into view; a click plays at once
    if (TRV.still || (booting && !TRV.embed)) { if (p.still != null) clock.set(p.still); } else if (p.play) { if (booting) kit.autoplay(clock, $('stage')); else clock.play(); }
  }
  const cards = kit.cards($('presets'), { notes: NOTES, noteEl: $('presetNote'), tour: $('tour'), onPick: applyPreset,
    idle: ['自由探索：拖动圆上的点，或拖动时间轴。随时可以再选一张卡。', 'Free play: drag the point on the circle, or scrub the rail. Pick a card again at any time.'] });

  TRV.drawer({ drawer: $('drawer'), open: $('infoBtn'), close: $('drawerClose') });
  TRV.startGlitch(document.querySelector('.brand'));

  /* ---------- probe for the browser suite, cover, start ---------- */
  window.STARTER_DEBUG = {
    get state() { const now = read(clock.t); return { theta: clock.t, cos: now.c, sin: now.s, sum: now.sum, playing: clock.playing, preset: cards.current }; },
    seek: (t) => { clock.pause(); clock.set(t); },
    /** Viewport coordinates of the point at `deg` degrees (for pointer tests). */
    at: (deg) => { const b = $('cv').getBoundingClientRect(); return [b.left + view.X(Math.cos(deg * DEG)), b.top + view.Y(Math.sin(deg * DEG))]; }
  };
  window.TRV_THUMB = () => { clock.pause(); clock.set(55); paint.now(); };
  cards.pick(cards.initial('even'));   // a chapter may cite another card: ::: {.viz src="__ID__" preset="sweep"}
  booting = false;
  paint();
})();
