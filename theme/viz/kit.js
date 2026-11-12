/* trureturing books · TRV.kit: optional helpers for stage-first visualization pages (published as <slug>/viz/assets/kit.js)
   Load it in <head> after shell.js:  <script src="../assets/kit.js"></script>
   It draws nothing by itself and imposes no layout: a page decides what its stage shows. The helpers only remove the
   boilerplate that every page otherwise rewrites (and gets subtly wrong):

     kit.v3                       vector algebra on [x, y, z]: add sub scale dot cross len unit lerp rot slerp sph
     kit.painter(draw, [els])     coalesced redraw: paint() asks for one frame; repaints on resize, fonts and language
     kit.flush()                  finish running transitions and draw every painter now (browser suites use it instead of waiting)
     kit.ready()                  a promise: resolves once the work the page waits for (three.js for kit.solid) is in
     kit.tween(ms, step, done)    eased 0 → 1 animation (one jump under prefers-reduced-motion); returns { cancel }
     kit.stage3(el, opts)         a 3D scene on a 2D canvas: orbit camera (drag, wheel, pinch), depth-cued lines, sphere,
                                  arcs, arrows, polygons, DOM labels, picking on the unit sphere
     kit.solid(el, opts)          lit solids, glass shells, polyhedra, tubes and marks with occlusion and picking: the shell
                                  of the modelling core solid-core.js (three.js), both fetched on the first call only
     kit.plot(canvas, opts)       a 2D chart or equal-aspect 2D stage: scales, axes, lines, areas, bars, dots, labels
     kit.clock(opts)              the bottom rail: play / pause / speed / scrub over t in [0, max], with keyboard
     kit.autoplay(clock, el)      start playing when the reader can see it (in a book: when el scrolls into view)
     kit.cards(el, opts)          experiment cards (one click = one named scenario with a one-line explanation),
                                  with an optional tour bar that steps through them next to the stage
     kit.chips(el, key, onPick)   an exclusive group of .chip buttons
     kit.field(input, opts)       a range input bound to its <output>
     kit.keys(map)                keyboard shortcuts that stay out of the way of form controls and the drawer
     kit.fix(x, d) kit.sgn(x, d)  number formatting without "-0.00" (U+2212 minus)

   Colours come from TRV.palette (the design tokens); nothing here hard-codes one. */
(function () {
  'use strict';
  const TRV = window.TRV;
  if (!TRV) return;
  const TAU = Math.PI * 2;
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const P = () => TRV.palette;
  const SRC = document.currentScript && document.currentScript.src;   // kit.solid finds solid-core.js next to this file

  /* ---------- vectors ---------- */
  const v3 = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
    scale: (a, k) => [a[0] * k, a[1] * k, a[2] * k],
    dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
    cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
    len: (a) => Math.hypot(a[0], a[1], a[2]),
    unit(a) { const n = Math.hypot(a[0], a[1], a[2]); return n > 1e-12 ? [a[0] / n, a[1] / n, a[2] / n] : [0, 0, 1]; },
    lerp: (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t],
    /** v rotated about the unit axis n by the angle a (right-handed, Rodrigues). */
    rot(v, n, a) {
      const c = Math.cos(a), s = Math.sin(a), d = v3.dot(n, v), x = v3.cross(n, v);
      return [v[0] * c + x[0] * s + n[0] * d * (1 - c), v[1] * c + x[1] * s + n[1] * d * (1 - c), v[2] * c + x[2] * s + n[2] * d * (1 - c)];
    },
    /** The point at fraction t of the great-circle arc from the unit vector u to the unit vector w. */
    slerp(u, w, t) {
      const c = clamp(v3.dot(u, w), -1, 1), th = Math.acos(c);
      if (th < 1e-9) return u.slice();
      if (Math.PI - th < 1e-9) { // antipodal: go through any perpendicular direction
        const p = v3.unit(v3.cross(u, Math.abs(u[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]));
        return v3.rot(u, p, Math.PI * t);
      }
      const s = Math.sin(th), a = Math.sin((1 - t) * th) / s, b = Math.sin(t * th) / s;
      return [a * u[0] + b * w[0], a * u[1] + b * w[1], a * u[2] + b * w[2]];
    },
    /** Unit vector at polar angle theta (from +z) and azimuth phi (from +x), both in radians. */
    sph: (theta, phi) => [Math.sin(theta) * Math.cos(phi), Math.sin(theta) * Math.sin(phi), Math.cos(theta)]
  };

  /* ---------- redraw and animation ---------- */
  /** paint() requests one frame; paint.now() draws synchronously. Repaints on resize, loaded fonts and language. */
  const painters = [];
  function painter(draw, watch) {
    let queued = false;
    const run = (t) => { if (!queued) return; queued = false; draw(t); };
    const paint = () => { if (!queued) { queued = true; requestAnimationFrame(run); } };
    paint.now = () => { queued = false; draw(performance.now()); };
    painters.push(paint);
    window.addEventListener('resize', paint);
    TRV.onLang(paint);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(paint);
    if (window.ResizeObserver && watch) { const ro = new ResizeObserver(paint); [].concat(watch).forEach((el) => el && ro.observe(el)); }
    return paint;
  }
  /** Bring the page to rest now: finish every transition in progress, then draw every painter. Browser suites call it
      (testkit `settle`) instead of waiting: a transition only advances on animation frames, and a busy machine may
      deliver the frame that ends it long after its nominal duration. */
  const tweens = new Set();
  function flush() { [...tweens].forEach((finish) => finish()); painters.forEach((p) => p.now()); }
  /** Work the page is waiting for before its first true frame (kit.solid registers the loading of three.js):
      kit.ready() resolves once all of it is in; the suites' settle() waits for it before calling flush(). */
  const waits = [];
  const pending = (promise) => { waits.push(promise); return promise; };
  const ready = () => Promise.all(waits.map((w) => w.catch(() => null))).then(() => undefined);
  /** step(e) with e eased from 0 to 1 over ms; done() at the end. Under reduced motion: step(1) at once. */
  function tween(ms, step, done) {
    let live = true;
    if (TRV.reduceMotion || ms <= 0) { step(1); if (done) done(); return { cancel() {} }; }
    const t0 = performance.now();
    const finish = () => { if (!live) return; live = false; tweens.delete(finish); step(1); if (done) done(); };
    const tick = (now) => {
      if (!live) return;
      const u = clamp((now - t0) / ms, 0, 1);
      if (u >= 1) { finish(); return; }
      step(TRV.smooth(u));
      requestAnimationFrame(tick);
    };
    tweens.add(finish);
    requestAnimationFrame(tick);
    return { cancel() { live = false; tweens.delete(finish); } };
  }

  /* ---------- 3D stage on a 2D canvas ----------
     World axes: x right, y into the screen at yaw 0, z up. The camera orbits the origin: yaw about z, pitch above
     the horizon, orthographic, so a unit sphere is always a circle of `radius × min(width, height) × zoom` pixels.
     opts: canvas, yaw, pitch, zoom, radius (0.36), cx, cy (0.5: the centre as a fraction of the box), rotate (true),
           onChange() after any camera move, onPick(ev, st) → true to take over a drag (then onDrag(ev, st), onDrop()),
           lineScale (stroke-width factor; 1.8 in thumbnail mode so that the 1280×720 cover reads at card size). */
  function stage3(el, opts) {
    const o = opts || {};
    const cv = o.canvas || el.querySelector('canvas'), ctx = cv.getContext('2d');
    const cam = { yaw: o.yaw == null ? -0.62 : o.yaw, pitch: o.pitch == null ? 0.34 : o.pitch, zoom: o.zoom || 1 };
    const st = { el, canvas: cv, ctx, cam, W: 0, H: 0, cx: 0, cy: 0, unit: 1, lw: o.lineScale || (TRV.thumbMode ? 1.8 : 1) };
    let R = [1, 0, 0], U = [0, 0, 1], D = [0, -1, 0];
    function axes() {
      const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
      R = [cy, -sy, 0]; U = [sy * sp, cy * sp, cp]; D = [-sy * cp, -cy * cp, sp];
    }
    /** Fit the canvas, clear it and fix the projection for this frame. Returns the 2D context (in CSS pixels). */
    st.begin = () => {
      const dpr = TRV.fitCanvas(cv);
      st.W = cv.clientWidth; st.H = cv.clientHeight;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, st.W, st.H);
      st.cx = st.W * (o.cx == null ? 0.5 : o.cx); st.cy = st.H * (o.cy == null ? 0.5 : o.cy);
      st.unit = Math.min(st.W, st.H) * (o.radius || 0.36) * cam.zoom;
      axes(); tagsUsed.clear();
      return ctx;
    };
    /** World point → [screen x, screen y, depth] (depth > 0 faces the viewer). */
    st.p = (v) => [st.cx + st.unit * v3.dot(v, R), st.cy - st.unit * v3.dot(v, U), v3.dot(v, D)];
    /** The point of the unit sphere under a pointer event (front side), or null outside the disc. */
    st.pick = (ev) => {
      const b = cv.getBoundingClientRect(), x = (ev.clientX - b.left - st.cx) / st.unit, y = (st.cy - (ev.clientY - b.top)) / st.unit;
      const r2 = x * x + y * y;
      if (r2 > 1) { const k = 1 / Math.sqrt(r2); return v3.add(v3.scale(R, x * k), v3.scale(U, y * k)); }
      const d = Math.sqrt(1 - r2);
      return v3.add(v3.add(v3.scale(R, x), v3.scale(U, y)), v3.scale(D, d));
    };
    /** Distance in CSS pixels from a pointer event to the projection of a world point. */
    st.near = (ev, v) => { const b = cv.getBoundingClientRect(), q = st.p(v); return Math.hypot(ev.clientX - b.left - q[0], ev.clientY - b.top - q[1]); };
    st.facing = () => D.slice();

    const style = (s, a) => { ctx.strokeStyle = s.color || P().cyan; ctx.lineWidth = (s.width || 1.2) * st.lw; ctx.globalAlpha = (s.alpha == null ? 1 : s.alpha) * a; ctx.setLineDash(s.dash || []); ctx.lineCap = 'round'; ctx.lineJoin = 'round'; };
    /** A polyline through world points. With fade (default) the part behind the centre plane is drawn dimmer. */
    st.path = (pts, s) => {
      s = s || {};
      const q = pts.map(st.p), back = s.back == null ? 0.28 : s.back;
      if (s.fade === false) {
        style(s, 1); ctx.beginPath(); q.forEach((a, i) => (i ? ctx.lineTo(a[0], a[1]) : ctx.moveTo(a[0], a[1]))); if (s.close) ctx.closePath(); ctx.stroke();
      } else {
        for (const front of [false, true]) {
          style(s, front ? 1 : back); ctx.beginPath();
          const n = q.length + (s.close ? 1 : 0);
          for (let i = 1; i < n; i++) {
            const a = q[i - 1], b = q[i % q.length];
            if (((a[2] + b[2]) / 2 >= 0) === front) { ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
          }
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1; ctx.setLineDash([]);
    };
    st.line = (a, b, s) => st.path([a, b], s);
    /** A circle in space: centre c, unit normal n, radius r. */
    st.circle = (c, n, r, s) => {
      const e1 = v3.unit(v3.cross(n, Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0])), e2 = v3.cross(n, e1), pts = [], N = (s && s.n) || 72;
      for (let i = 0; i < N; i++) { const a = TAU * i / N; pts.push(v3.add(c, v3.add(v3.scale(e1, r * Math.cos(a)), v3.scale(e2, r * Math.sin(a))))); }
      st.path(pts, Object.assign({ close: true }, s));
    };
    /** The great-circle arc from the unit vector u to the unit vector w, at radius r. */
    st.arc = (u, w, s, r) => {
      const pts = [], N = (s && s.n) || 40;
      for (let i = 0; i <= N; i++) pts.push(v3.scale(v3.slerp(u, w, i / N), r || 1));
      st.path(pts, s);
    };
    /** A filled polygon through world points (no depth sorting: draw back to front yourself). */
    st.poly = (pts, s) => {
      s = s || {};
      const q = pts.map(st.p);
      ctx.beginPath(); q.forEach((a, i) => (i ? ctx.lineTo(a[0], a[1]) : ctx.moveTo(a[0], a[1]))); ctx.closePath();
      if (s.fill) { ctx.globalAlpha = s.alpha == null ? 0.25 : s.alpha; ctx.fillStyle = s.fill; ctx.fill(); }
      if (s.color) { ctx.globalAlpha = s.strokeAlpha == null ? 0.9 : s.strokeAlpha; ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 1; ctx.setLineDash(s.dash || []); ctx.stroke(); }
      ctx.globalAlpha = 1; ctx.setLineDash([]);
    };
    /** A dot at a world point; ring: true draws an open marker. */
    st.dot = (v, r, color, s) => {
      const q = st.p(v), a = (s && s.alpha != null ? s.alpha : 1) * (q[2] < 0 && !(s && s.fade === false) ? 0.45 : 1);
      ctx.globalAlpha = a; ctx.beginPath(); ctx.arc(q[0], q[1], (r || 4) * st.lw, 0, TAU);
      if (s && s.ring) { ctx.strokeStyle = color; ctx.lineWidth = s.width || 1.5; ctx.stroke(); } else {
        if (s && s.glow) { ctx.shadowColor = color; ctx.shadowBlur = s.glow; }
        ctx.fillStyle = color; ctx.fill(); ctx.shadowBlur = 0;
      }
      ctx.globalAlpha = 1;
    };
    /** An arrow from a to b with a screen-space head. */
    st.arrow = (a, b, s) => {
      s = s || {};
      const qa = st.p(a), qb = st.p(b), dx = qb[0] - qa[0], dy = qb[1] - qa[1], L = Math.hypot(dx, dy);
      const al = (s.alpha == null ? 1 : s.alpha) * (s.fade !== false && (qa[2] + qb[2]) / 2 < 0 ? 0.5 : 1);
      ctx.globalAlpha = al; ctx.strokeStyle = ctx.fillStyle = s.color || P().cyan; ctx.lineWidth = (s.width || 2) * st.lw; ctx.setLineDash(s.dash || []); ctx.lineCap = 'round';
      if (s.glow) { ctx.shadowColor = s.color || P().cyan; ctx.shadowBlur = s.glow; }
      ctx.beginPath(); ctx.moveTo(qa[0], qa[1]); ctx.lineTo(qb[0], qb[1]); ctx.stroke(); ctx.setLineDash([]);
      if (L > 6 && s.head !== false) {
        const h = Math.min((s.headSize || 10) * st.lw, L * 0.6), ux = dx / L, uy = dy / L;
        ctx.beginPath(); ctx.moveTo(qb[0], qb[1]);
        ctx.lineTo(qb[0] - ux * h - uy * h * 0.42, qb[1] - uy * h + ux * h * 0.42);
        ctx.lineTo(qb[0] - ux * h + uy * h * 0.42, qb[1] - uy * h - ux * h * 0.42);
        ctx.closePath(); ctx.fill();
      }
      ctx.shadowBlur = 0; ctx.globalAlpha = 1;
    };
    /** A wire sphere of radius r: shaded disc, silhouette, parallels and meridians (opts: lat, lon, color, alpha). */
    st.sphere = (r, s) => {
      s = s || {}; r = r || 1;
      const col = s.color || P().lineHot, q = st.p([0, 0, 0]), rad = r * st.unit;
      const g = ctx.createRadialGradient(q[0] - rad * 0.3, q[1] - rad * 0.35, rad * 0.05, q[0], q[1], rad);
      g.addColorStop(0, TRV.alpha(P().cyan, s.shade == null ? 0.1 : s.shade)); g.addColorStop(1, TRV.alpha(P().cyan, 0.015));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(q[0], q[1], rad, 0, TAU); ctx.fill();
      ctx.globalAlpha = 0.9; ctx.strokeStyle = col; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(q[0], q[1], rad, 0, TAU); ctx.stroke(); ctx.globalAlpha = 1;
      const a = s.alpha == null ? 0.55 : s.alpha;
      for (const lat of s.lat || [0]) {
        const z = r * Math.sin(lat), rr = r * Math.cos(lat);
        st.circle([0, 0, z], [0, 0, 1], rr, { color: col, width: lat === 0 ? 1.1 : 0.7, alpha: lat === 0 ? a : a * 0.6, back: 0.4 });
      }
      for (let k = 0; k < (s.lon == null ? 2 : s.lon); k++) {
        const ph = Math.PI * k / (s.lon == null ? 2 : s.lon);
        st.circle([0, 0, 0], [-Math.sin(ph), Math.cos(ph), 0], r, { color: col, width: 0.7, alpha: a * 0.6, back: 0.4 });
      }
    };

    /* DOM labels (.tag): bilingual, crisp at any zoom, hidden by the theme in thumbnail mode */
    const tags = new Map(), tagsUsed = new Set();
    let tagBox = el.querySelector('.tags');
    /** Put the label `key` at a world point (or at [x, y] in CSS pixels with { screen: true }). */
    st.tag = (key, v, html, cls, s) => {
      if (!tagBox) { tagBox = document.createElement('div'); tagBox.className = 'tags'; el.appendChild(tagBox); }
      let t = tags.get(key);
      if (!t) { t = document.createElement('div'); tags.set(key, t); tagBox.appendChild(t); }
      const q = s && s.screen ? [v[0], v[1], 1] : st.p(v), dx = (s && s.dx) || 0, dy = (s && s.dy) || 0;
      t.className = 'tag ' + (cls || '');
      if (t._html !== html) { t.innerHTML = html; t._html = html; }
      t.style.transform = `translate(-50%, -50%) translate(${(q[0] + dx).toFixed(1)}px, ${(q[1] + dy).toFixed(1)}px)`;
      t.style.opacity = q[2] < -0.05 && !(s && s.fade === false) ? '0.45' : '1';
      t.hidden = false; tagsUsed.add(key);
    };
    /** Hide the labels that this frame did not place. Call at the end of a draw. */
    st.end = () => { tags.forEach((t, k) => { if (!tagsUsed.has(k)) t.hidden = true; }); };

    /* camera: named views, drag to orbit, wheel and pinch to zoom */
    const VIEWS = { iso: [-0.62, 0.34], front: [0, 0], top: [0, Math.PI / 2 - 0.001], side: [-Math.PI / 2, 0] };
    let camTween = null;
    st.view = (name, ms) => {
      const v = Array.isArray(name) ? name : VIEWS[name] || VIEWS.iso, y0 = cam.yaw, p0 = cam.pitch, z0 = cam.zoom;
      if (camTween) camTween.cancel();
      camTween = tween(ms == null ? 600 : ms, (e) => { cam.yaw = y0 + (v[0] - y0) * e; cam.pitch = p0 + (v[1] - p0) * e; cam.zoom = z0 + ((v[2] || 1) - z0) * e; if (o.onChange) o.onChange(); });
    };
    const ptrs = new Map();
    let mode = null, pinch = 0;
    const changed = () => { if (camTween) { camTween.cancel(); camTween = null; } if (o.onChange) o.onChange(); };
    el.addEventListener('pointerdown', (ev) => {
      if (ev.target.closest('button, a, input, .chip')) return;
      ptrs.set(ev.pointerId, [ev.clientX, ev.clientY]);
      try { el.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic events have no capture */ }
      if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); mode = 'pinch'; return; }
      mode = o.onPick && o.onPick(ev, st) ? 'drag' : (o.rotate === false ? null : 'orbit');
      if (mode === 'drag' && o.onDrag) o.onDrag(ev, st);
    });
    el.addEventListener('pointermove', (ev) => {
      const last = ptrs.get(ev.pointerId);
      if (!last) return;
      const dx = ev.clientX - last[0], dy = ev.clientY - last[1];
      ptrs.set(ev.pointerId, [ev.clientX, ev.clientY]);
      if (mode === 'pinch' && ptrs.size === 2) {
        const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch > 0) { cam.zoom = clamp(cam.zoom * d / pinch, 0.6, 2.6); changed(); }
        pinch = d;
      } else if (mode === 'drag') { if (o.onDrag) o.onDrag(ev, st); } else if (mode === 'orbit') {
        cam.yaw -= dx * 0.008; cam.pitch = clamp(cam.pitch + dy * 0.008, -1.5, 1.5); changed();
      }
    });
    const up = (ev) => { ptrs.delete(ev.pointerId); if (mode === 'drag' && o.onDrop) o.onDrop(ev, st); if (!ptrs.size) mode = null; };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    if (o.rotate !== false && o.wheel !== false) {
      el.addEventListener('wheel', (ev) => { ev.preventDefault(); cam.zoom = clamp(cam.zoom * Math.exp(-ev.deltaY * 0.0012), 0.6, 2.6); changed(); }, { passive: false });
    }
    axes();
    return st;
  }

  /* ---------- 2D charts and 2D stages ----------
     const g = kit.plot(canvas, { x: [0, 10], y: [0, 1], pad: [left, right, top, bottom], logX, logY, equal });
     g.axes({ xTicks, yTicks, xFmt, yFmt, xLabel, yLabel }); g.line(points, color); g.dot(x, y, color); …
     `equal: true` gives both axes the same scale (a 2D stage: lattices, circles), widening one range to fit. */
  /* ---------- sub- and superscripts in canvas text ---------- */
  const SCRIPT = 0.72;   // a script's size, of its text's
  /** The runs [{ t, sub, sup }] of a label with scripts, or null for plain text (drawn as before). A label is a string
      that may write _{…} and ^{…}, or an array of pieces: a string, or { t, sub: true } / { t, sup: true }. */
  function scripts(str) {
    if (Array.isArray(str)) return str.map((p) => (typeof p === 'string' ? { t: p } : { t: String(p.t), sub: !!p.sub, sup: !!p.sup })).filter((r) => r.t);
    if (typeof str !== 'string' || !/[_^]\{/.test(str)) return null;
    const out = [], re = /([_^])\{([^{}]*)\}/g;
    let at = 0, m;
    while ((m = re.exec(str))) {
      if (m.index > at) out.push({ t: str.slice(at, m.index) });
      if (m[2]) out.push({ t: m[2], sub: m[1] === '_', sup: m[1] === '^' });
      at = re.lastIndex;
    }
    if (at < str.length) out.push({ t: str.slice(at) });
    return out;
  }

  function plot(cv, o) {
    o = o || {};
    const dpr = TRV.fitCanvas(cv), W = cv.clientWidth, H = cv.clientHeight, ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (o.clear !== false) ctx.clearRect(0, 0, W, H);
    const pad = o.pad || [38, 12, 10, 22], pl = pad[0], pr = pad[1], pt = pad[2], pb = pad[3];
    const iw = Math.max(1, W - pl - pr), ih = Math.max(1, H - pt - pb);
    const fx = o.logX ? Math.log10 : (v) => v, fy = o.logY ? Math.log10 : (v) => v;
    let a0 = fx(o.x[0]), a1 = fx(o.x[1]), b0 = fy(o.y[0]), b1 = fy(o.y[1]);
    if (o.equal) {
      const s = Math.min(iw / (a1 - a0), ih / (b1 - b0)), mx = (a0 + a1) / 2, my = (b0 + b1) / 2;
      a0 = mx - iw / (2 * s); a1 = mx + iw / (2 * s); b0 = my - ih / (2 * s); b1 = my + ih / (2 * s);
    }
    const X = (v) => pl + (fx(v) - a0) / (a1 - a0) * iw, Y = (v) => pt + ih - (fy(v) - b0) / (b1 - b0) * ih;
    const inv = (f) => (o[f] ? (u) => Math.pow(10, u) : (u) => u);
    const g = {
      ctx, W, H, X, Y, pl, pr, pt, pb, iw, ih,
      x0: inv('logX')(a0), x1: inv('logX')(a1), y0: inv('logY')(b0), y1: inv('logY')(b1),
      /** Screen pixel → data value (for pointer picking). */
      invX: (px) => inv('logX')(a0 + (px - pl) / iw * (a1 - a0)),
      invY: (py) => inv('logY')(b0 + (pt + ih - py) / ih * (b1 - b0)),
      /** Pixels per data unit (linear axes). */
      scale: iw / (a1 - a0)
    };
    const font = (px, face) => `${px || 10}px ${face === 'body' ? TRV.fonts.body : face === 'display' ? TRV.fonts.display : TRV.fonts.data}`;
    /** Draw runs [{ t, sub, sup }] from x, aligned as `align` ('left' | 'center' | 'right') at baseline-free y. */
    const setRuns = (c, runs, x0, y0, size, face, align) => {
      const sized = runs.map((r) => ({ ...r, px: r.sub || r.sup ? size * SCRIPT : size }));
      let w = 0;
      for (const r of sized) { c.font = font(r.px, face); r.w = c.measureText(r.t).width; w += r.w; }
      let x = align === 'center' ? x0 - w / 2 : align === 'right' || align === 'end' ? x0 - w : x0;
      c.textAlign = 'left';
      for (const r of sized) {
        c.font = font(r.px, face);
        c.fillText(r.t, x, y0 + (r.sub ? size * 0.32 : r.sup ? -size * 0.36 : 0));
        x += r.w;
      }
      c.font = font(size, face);
      return w;
    };
    const set = (color, s) => { s = s || {}; ctx.strokeStyle = ctx.fillStyle = color || P().cyan; ctx.lineWidth = s.width || 1.6; ctx.globalAlpha = s.alpha == null ? 1 : s.alpha; ctx.setLineDash(s.dash || []); ctx.lineJoin = 'round'; ctx.lineCap = 'round'; return s; };
    const done = () => { ctx.globalAlpha = 1; ctx.setLineDash([]); ctx.shadowBlur = 0; };
    const trace = (pts) => { let pen = false; ctx.beginPath(); for (const p of pts) { if (p == null || !isFinite(p[1]) || !isFinite(p[0])) { pen = false; continue; } const x = X(p[0]), y = Y(p[1]); if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; } } };
    /** Frame, grid lines and tick labels. Ticks are arrays of values (or of [value, label]). */
    g.axes = (a) => {
      a = a || {};
      ctx.font = font(10); ctx.lineWidth = 1;
      const tick = (t) => (Array.isArray(t) ? t : [t, null]);
      for (const t of a.yTicks || []) {
        const [v, lab] = tick(t), y = Math.round(Y(v)) + 0.5;
        ctx.strokeStyle = P().panelEdge; ctx.globalAlpha = 0.9; ctx.beginPath(); ctx.moveTo(pl, y); ctx.lineTo(pl + iw, y); ctx.stroke();
        ctx.globalAlpha = 1; ctx.fillStyle = P().dim; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        ctx.fillText(lab != null ? lab : (a.yFmt ? a.yFmt(v) : String(v)), pl - 5, y);
      }
      for (const t of a.xTicks || []) {
        const [v, lab] = tick(t), x = Math.round(X(v)) + 0.5;
        if (a.xGrid) { ctx.strokeStyle = P().panelEdge; ctx.globalAlpha = 0.9; ctx.beginPath(); ctx.moveTo(x, pt); ctx.lineTo(x, pt + ih); ctx.stroke(); }
        ctx.globalAlpha = 1; ctx.fillStyle = P().dim; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        ctx.fillText(lab != null ? lab : (a.xFmt ? a.xFmt(v) : String(v)), x, pt + ih + 5);
      }
      if (a.frame !== false) { ctx.strokeStyle = P().lineHot; ctx.globalAlpha = 0.9; ctx.beginPath(); ctx.moveTo(pl + 0.5, pt); ctx.lineTo(pl + 0.5, pt + ih + 0.5); ctx.lineTo(pl + iw, pt + ih + 0.5); ctx.stroke(); }
      ctx.globalAlpha = 1; ctx.fillStyle = P().dim; ctx.font = font(10.5, 'body');
      if (a.xLabel) { ctx.textAlign = 'right'; ctx.textBaseline = 'bottom'; ctx.fillText(a.xLabel, pl + iw, pt + ih - 4); }
      if (a.yLabel) { ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillText(a.yLabel, pl + 6, pt + 2); }
      done();
    };
    /** A polyline through [x, y] points (null breaks the line). */
    g.line = (pts, color, s) => { s = set(color, s); if (s.glow) { ctx.shadowColor = color; ctx.shadowBlur = s.glow; } trace(pts); ctx.stroke(); done(); };
    /** The area between a polyline and the level `base` (default: the bottom of the plot). */
    g.area = (pts, color, s) => {
      s = set(color, Object.assign({ alpha: 0.18 }, s));
      const ok = pts.filter((p) => p && isFinite(p[1]));
      if (ok.length < 2) return done();
      const yb = s.base == null ? pt + ih : Y(s.base);
      ctx.beginPath(); ctx.moveTo(X(ok[0][0]), yb); for (const p of ok) ctx.lineTo(X(p[0]), Y(p[1])); ctx.lineTo(X(ok[ok.length - 1][0]), yb); ctx.closePath(); ctx.fill(); done();
    };
    /** A filled polygon through [x, y] points. */
    g.poly = (pts, color, s) => { s = set(color, Object.assign({ alpha: 0.2 }, s)); ctx.beginPath(); pts.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])))); ctx.closePath(); ctx.fill(); if (s.stroke) { ctx.globalAlpha = s.strokeAlpha == null ? 0.9 : s.strokeAlpha; ctx.strokeStyle = s.stroke; ctx.lineWidth = s.width || 1; ctx.stroke(); } done(); };
    g.dot = (x, y, color, r, s) => {
      s = set(color, s); ctx.beginPath(); ctx.arc(X(x), Y(y), r || 3.5, 0, TAU);
      if (s.ring) { ctx.lineWidth = s.width || 1.5; ctx.stroke(); } else { if (s.glow) { ctx.shadowColor = color; ctx.shadowBlur = s.glow; } ctx.fill(); }
      done();
    };
    g.vline = (x, color, s) => { set(color, Object.assign({ width: 1 }, s)); const px = Math.round(X(x)) + 0.5; ctx.beginPath(); ctx.moveTo(px, pt); ctx.lineTo(px, pt + ih); ctx.stroke(); done(); };
    g.hline = (y, color, s) => { set(color, Object.assign({ width: 1 }, s)); const py = Math.round(Y(y)) + 0.5; ctx.beginPath(); ctx.moveTo(pl, py); ctx.lineTo(pl + iw, py); ctx.stroke(); done(); };
    /** A rectangle between data corners (x0, y0) and (x1, y1). */
    g.rect = (xa, ya, xb, yb, color, s) => {
      s = set(color, Object.assign({ alpha: 0.2 }, s));
      const x = Math.min(X(xa), X(xb)), y = Math.min(Y(ya), Y(yb)), w = Math.abs(X(xb) - X(xa)), h = Math.abs(Y(yb) - Y(ya));
      if (s.fill !== false) ctx.fillRect(x, y, w, h);
      if (s.stroke) { ctx.globalAlpha = s.strokeAlpha == null ? 1 : s.strokeAlpha; ctx.strokeStyle = s.stroke; ctx.lineWidth = s.width || 1; if (s.glow) { ctx.shadowColor = s.stroke; ctx.shadowBlur = s.glow; } ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1); }
      done();
    };
    /** Text at a data point. s: align, base, size, face ('data' | 'body' | 'display'), dx, dy, alpha. `str` may carry
        sub- and superscripts, set smaller and lowered or raised on the canvas: written in the string as _{…} and ^{…}
        ('E_{n}', 'φ^{−n}', '|ψ_{1}⟩'), or given as pieces [text | { t, sub: true } | { t, sup: true }, …]. */
    g.text = (x, y, str, color, s) => {
      s = s || {};
      const size = s.size || 10.5;
      ctx.font = font(size, s.face); ctx.fillStyle = color || P().dim; ctx.globalAlpha = s.alpha == null ? 1 : s.alpha;
      ctx.textAlign = s.align || 'left'; ctx.textBaseline = s.base || 'middle';
      const runs = scripts(str);
      if (!runs) { ctx.fillText(str, X(x) + (s.dx || 0), Y(y) + (s.dy || 0)); done(); return; }
      setRuns(ctx, runs, X(x) + (s.dx || 0), Y(y) + (s.dy || 0), size, s.face, s.align || 'left'); done();
    };
    /** A key in a corner: entries are [colour, label] or [colour, label, 'dash']; a label may carry scripts as g.text. */
    g.legend = (items, s) => {
      s = s || {};
      ctx.font = font(10.5, 'body'); ctx.textBaseline = 'middle';
      const right = s.right !== false, lh = 14;
      let y = (s.bottom ? pt + ih - 9 - lh * (items.length - 1) : pt + 9) + (s.dy || 0);
      for (const [color, label, kind] of items) {
        const runs = scripts(label);
        let w = ctx.measureText(runs ? '' : label).width;
        if (runs) for (const r of runs) { ctx.font = font(r.sub || r.sup ? 10.5 * SCRIPT : 10.5, 'body'); w += ctx.measureText(r.t).width; }
        ctx.font = font(10.5, 'body');
        const x = right ? pl + iw - w - 26 : pl + 10;
        ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash(kind === 'dash' ? [4, 3] : []);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 14, y); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = P().ink; ctx.textAlign = 'left';
        if (runs) setRuns(ctx, runs, x + 19, y, 10.5, 'body', 'left'); else ctx.fillText(label, x + 19, y);
        y += lh;
      }
    };
    return g;
  }

  /* ---------- the clock rail ----------
     kit.clock({ range, play, label, speeds, max, step, rate, loop, t, format(t, max), onChange(t, clock), keys })
     t runs over [0, max]. rate = units of t per second at 1×. step = the keyboard / reduced-motion increment.
     range: <input type=range>; play: the ▶ button; label: the element showing t; speeds: a container of [data-speed]. */
  function clock(o) {
    const C = { t: o.t || 0, max: o.max == null ? 1 : o.max, playing: false, speed: 1, rate: o.rate || 1, step: o.step || 1 };
    const fmt = o.format || ((t, max) => `${t.toFixed(2)} <small>/ ${max.toFixed(2)}</small>`);
    let last = 0, acc = 0, raf = 0;
    function show() {
      if (o.range) { o.range.max = String(C.max); o.range.value = String(C.t); }
      if (o.label) o.label.innerHTML = fmt(C.t, C.max);
      if (o.play) { o.play.textContent = C.playing ? '❚❚' : '▶'; o.play.setAttribute('aria-pressed', String(C.playing)); }
    }
    function emit() { show(); if (o.onChange) o.onChange(C.t, C); }
    function tick(now) {
      raf = 0;
      if (!C.playing) return;
      const dt = clamp((now - last) / 1000, 0, 0.1); last = now;   // a frame's timestamp can precede the performance.now() of play()
      if (TRV.reduceMotion) { acc += dt; if (acc >= 0.45) { acc = 0; C.t = Math.min(C.max, (Math.floor(C.t / C.step + 1e-9) + 1) * C.step); } else { raf = requestAnimationFrame(tick); return; } }
      else C.t += dt * C.rate * C.speed;
      if (C.t >= C.max) { if (o.loop) C.t = 0; else { C.t = C.max; C.playing = false; } }
      emit();
      if (C.playing) raf = requestAnimationFrame(tick);
    }
    C.set = (t, quiet) => { C.t = clamp(t, 0, C.max); if (quiet) show(); else emit(); };
    C.setMax = (m, quiet) => { C.max = Math.max(m, 1e-9); C.t = clamp(C.t, 0, C.max); if (quiet) show(); else emit(); };
    C.play = () => { if (C.playing) return; if (C.t >= C.max - 1e-9) C.t = 0; C.playing = true; last = performance.now(); acc = 0; emit(); if (!raf) raf = requestAnimationFrame(tick); };
    C.pause = () => { if (!C.playing) return; C.playing = false; emit(); };
    C.toggle = () => (C.playing ? C.pause() : C.play());
    /** Move to the next (k = +1) or previous (k = −1) multiple of step. */
    C.stepBy = (k) => { C.playing = false; const u = C.t / C.step; C.set((k > 0 ? Math.floor(u + 1e-9) + 1 : Math.ceil(u - 1e-9) - 1) * C.step); };
    if (o.range) { o.range.min = '0'; o.range.step = o.rangeStep || 'any'; o.range.addEventListener('input', () => { C.playing = false; C.set(parseFloat(o.range.value)); }); }
    if (o.play) o.play.addEventListener('click', C.toggle);
    if (o.speeds) chips(o.speeds, 'speed', (v) => { C.speed = parseFloat(v) || 1; });
    if (o.keys !== false) keys({ ' ': C.toggle, ArrowRight: () => C.stepBy(1), ArrowLeft: () => C.stepBy(-1), Home: () => { C.playing = false; C.set(0); }, End: () => { C.playing = false; C.set(C.max); } });
    TRV.onLang(show);
    show();
    return C;
  }

  /* ---------- controls ---------- */
  /** After a click with the pointer (mouse, pen, touch: detail > 0) on a card, a chip or a tour button, hand the focus to
      the stage (.stage, focusable by script only: tabindex −1), so that Space plays and pauses the clock at once instead
      of pressing that button again. A press from the keyboard (Enter or Space on a focused button: detail 0) keeps the
      focus where the reader put it, so a reader who tabs through the controls is answered by the button. */
  function release(ev) {
    if (!ev || !(ev.detail > 0)) return;
    const from = document.activeElement;
    if (!from || from === document.body || !from.closest || !from.closest('button')) return;
    const st = document.querySelector('.stage');
    if (st && st !== from) {
      if (!st.hasAttribute('tabindex')) st.setAttribute('tabindex', '-1');
      st.focus({ preventScroll: true });
    }
    if (document.activeElement === from) from.blur();
  }
  /** An exclusive group of buttons carrying data-<key>; onPick(value, button). Returns { value, set(value, quiet) }. */
  function chips(el, key, onPick) {
    const prop = key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const btns = () => [...el.querySelectorAll(`[data-${key}]`)];
    const pressed = btns().find((b) => b.getAttribute('aria-pressed') === 'true');
    const api = {
      value: pressed ? pressed.dataset[prop] : null,
      set(v, quiet) { api.value = v == null ? null : String(v); btns().forEach((b) => b.setAttribute('aria-pressed', String(b.dataset[prop] === api.value))); if (!quiet && onPick) onPick(api.value); }
    };
    el.addEventListener('click', (ev) => { const b = ev.target.closest(`[data-${key}]`); if (b && el.contains(b) && !b.disabled) { ev.stopPropagation(); api.set(b.dataset[prop]); release(ev); } });
    return api;
  }
  /** Experiment cards: buttons carrying data-preset inside el. opts: notes { id: [zh, en] }, noteEl, idle [zh, en],
      onPick(id), tour (a .tour element with [data-tour="prev"], [data-tour="next"] and .what), presets (the page's
      table of cards { id: { …, still } }).
      Still frame: a card that plays by itself declares the frame its still shows (the cover, the labelled figure a
      chapter cites, PDF and EPUB) as `still` in the page's table, a clock time or 'end', and the page puts its clock
      there when TRV.still is set. Passed the table as `presets`, cards() writes each declared value onto the card as
      data-still (a card may also carry data-still in the HTML), where the quality gate (stageFirstChecks) reads it.
      Returns { current, pick(id), step(±1), mark(id | null), initial(fallback), still(id) }: mark(null) when the reader
      leaves the scenario by moving a control; initial() honours the card a chapter cites with ?preset=<id>; still(id)
      is the declared still of a card (the table's value, else its data-still, else null). */
  function cards(el, o) {
    o = o || {};
    const api = { current: null };
    const ids = () => [...el.querySelectorAll('[data-preset]')].map((b) => b.dataset.preset);
    const stillOf = (id) => {
      const p = o.presets && o.presets[id];
      if (p && p.still != null) return p.still;
      const b = el.querySelector(`[data-preset="${id}"]`), v = b ? b.dataset.still : undefined;
      return v == null || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : v);
    };
    if (o.presets) for (const b of el.querySelectorAll('[data-preset]')) { const p = o.presets[b.dataset.preset]; if (p && p.still != null) b.dataset.still = String(p.still); }
    api.still = stillOf;
    const tour = o.tour;
    function note() {
      const n = o.notes && api.current && o.notes[api.current], text = n ? TRV.L(n[0], n[1]) : (o.idle ? TRV.L(o.idle[0], o.idle[1]) : '');
      if (o.noteEl) o.noteEl.innerHTML = text;
      if (tour) {
        const list = ids(), k = list.indexOf(api.current), b = k >= 0 ? el.querySelector(`[data-preset="${api.current}"]`) : null;
        const name = b ? [...b.querySelectorAll('.cn')].map((c) => `<span class="${c.classList.contains('en') ? 'en' : 'zh'}">${c.innerHTML}</span>`).join('') : '';
        tour.querySelector('.what').innerHTML = `<b>${k >= 0 ? `${k + 1} / ${list.length} · ${name}` : TRV.L('自由探索', 'Free play')}</b>${text}`;
      }
    }
    api.mark = (id) => { api.current = id || null; el.querySelectorAll('[data-preset]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.preset === api.current))); note(); };
    api.pick = (id) => { api.mark(id); if (o.onPick) o.onPick(id); };
    /** The next (k = +1) or previous (k = −1) card, wrapping around. */
    api.step = (k) => { const list = ids(), i = list.indexOf(api.current); api.pick(list[((i < 0 ? (k > 0 ? -1 : 0) : i) + k + list.length) % list.length]); };
    /** The card a chapter cites (?preset=<id>) when the page has it, else `fallback`: the card to open with. */
    api.initial = (fallback) => (TRV.preset && ids().includes(TRV.preset) ? TRV.preset : fallback);
    el.addEventListener('click', (ev) => { const b = ev.target.closest('[data-preset]'); if (b && el.contains(b)) { api.pick(b.dataset.preset); release(ev); } });
    if (tour) {
      const p = tour.querySelector('[data-tour="prev"]'), n = tour.querySelector('[data-tour="next"]');
      if (p) p.addEventListener('click', (ev) => { api.step(-1); release(ev); });
      if (n) n.addEventListener('click', (ev) => { api.step(1); release(ev); });
    }
    TRV.onLang(note);
    return api;
  }
  /** Start a clock for the reader, not for an empty room: at once on a full page; inside a book (?embed=1) when `el`
      is at least half in view, pausing again when it scrolls away; never for a still (cover or cited figure shot). */
  function autoplay(clk, el) {
    if (TRV.still) return;
    if (!TRV.embed || !window.IntersectionObserver || !el) { clk.play(); return; }
    let started = false;
    new IntersectionObserver((entries) => {
      const seen = entries[entries.length - 1].intersectionRatio >= 0.5;
      if (seen && !started) { started = true; clk.play(); } else if (!seen && clk.playing) clk.pause();
    }, { threshold: [0, 0.5, 1] }).observe(el);
  }
  /** Bind a range input to its output. opts: out (element), fmt(value) → text, onInput(value). Returns { value, set(v) }. */
  function field(input, o) {
    o = o || {};
    const out = o.out || (input.id && document.querySelector(`output[for="${input.id}"]`));
    const api = {
      get value() { return parseFloat(input.value); },
      show() { if (out) out.textContent = o.fmt ? o.fmt(parseFloat(input.value)) : input.value; },
      set(v) { input.value = String(v); api.show(); }
    };
    input.addEventListener('input', () => { api.show(); if (o.onInput) o.onInput(parseFloat(input.value)); });
    TRV.onLang(api.show);
    api.show();
    return api;
  }
  /** Keyboard shortcuts { key: handler }. Ignored while typing in a control, with a modifier, or under an open drawer;
      Space and Enter on a focused button belong to that button (a pointer click on a card or chip moves the focus to
      the stage first: see release). */
  function keys(map) {
    document.addEventListener('keydown', (ev) => {
      if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const t = ev.target, tag = t && t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
      if (tag === 'BUTTON' && (ev.key === ' ' || ev.key === 'Enter')) return;
      if (document.querySelector('.drawer:not([hidden])')) return;
      const fn = map[ev.key] || map[ev.key.length === 1 ? ev.key.toLowerCase() : ev.key];
      if (fn) { ev.preventDefault(); fn(ev); }
    });
  }

  /* ---------- numbers ---------- */
  /** x with d decimals; never "-0.00"; a true minus sign. */
  function fix(x, d) { const s = (Math.abs(x) < 0.5 * Math.pow(10, -(d == null ? 2 : d)) ? 0 : x).toFixed(d == null ? 2 : d); return s.replace('-', '−'); }
  /** As fix, with an explicit sign. */
  function sgn(x, d) { const s = fix(x, d); return s[0] === '−' || Number(s.replace('−', '-')) === 0 ? s : '+' + s; }

  TRV.kit = { v3, painter, flush, ready, pending, src: SRC, tween, stage3, plot, clock, autoplay, chips, cards, field, keys, fix, sgn, clamp, TAU };
})();

/* ---------- kit.solid: the interactive shell of a solid stage (three.js, fetched on first use) ----------
   const sc = TRV.kit.solid(stageEl, { canvas, onChange: paint, onPick, onDrag, onDrop, yaw, pitch, zoom, radius, cx, cy });
   Every page may call it; the modelling core (theme/viz/solid-core.js, an ES module) and the pinned three.js it imports
   (theme/viz/vendor/, see vendor/README.md) are fetched by the first call only, so a page that draws no solid downloads
   nothing more. The core builds and draws the objects and knows nothing of the page (the film engine uses it too); this
   shell puts it on the stage: camera, pointer handling, labels and projection as in kit.stage3 (x right, z up,
   orthographic orbit), a WebGL context made when the stage is on screen and given back after a rest. Draw in the
   painter as with stage3:
     sc.begin();
     sc.surface('band', (u, v) => [x, y, z], { u: [0, 1], v: [0, 1], nu: 96, nv: 20, value: (u, v) => s,
                                              colors: [P.magenta, P.violet, P.cyan], range: [-1, 1], grid: { every: [4, 2] } });
     sc.glass('ball', [0, 0, 0], 1);                         a glass shell: what is inside stays visible
     sc.poly('ico', { vertices, faces }, { color });         a flat-shaded polyhedron from a vertex and face list
     sc.tube('path', points, { width, color, glow });        a tube along a curve (parallel-transported frame)
     sc.line(points, { color, width, dash, alpha, close })   a line: a thin unlit tube, hidden by what is in front of it
     sc.arrow(a, b, s)  sc.ring(p, s)  sc.bead(p, s)  sc.fan(points, s)    marks on and around the solid
     sc.tag(key, p, html, cls, s)                            a DOM label, dimmed where a solid hides its point
     sc.end();                                               draws the frame (no render loop: frames come from paint())
   sc.hit(ev) → { id, u, v, point, normal, front } | null;  sc.nearest(ev, points, px);  sc.occluded(p);  sc.view(…).
   Surfaces, glass shells, polyhedra and tubes take a key and keep their buffers from frame to frame; lines, arrows,
   beads, rings and fans are made for one frame. Inside a book (TRV.embed) the WebGL context is made only once the stage
   is on screen and is given back after a short rest (the frame stays on the page's 2D canvas as a picture); a touch or
   a new frame takes it back. sc.ready resolves once the core is in; kit.ready() waits for every stage, and the suites'
   settle() waits for kit.ready(). */
(function () {
  'use strict';
  const TRV = window.TRV;
  if (!TRV || !TRV.kit) return;
  const kit = TRV.kit, v3 = kit.v3, clamp = kit.clamp;
  const CORE = new URL('solid-core.js', kit.src || location.href).href;
  let coreP = null;
  /** The modelling core (and with it three.js), fetched once per page, on the first call of kit.solid. */
  const loadCore = () => coreP || (coreP = import(CORE));
  const PRIMS = ['surface', 'poly', 'glass', 'tube', 'line', 'arrow', 'bead', 'ring', 'fan'];

  function solid(el, opts) {
    const o = opts || {};
    const still = o.canvas || el.querySelector('canvas');     // the page's 2D canvas: shows the frame while the context rests
    const cam = { yaw: o.yaw == null ? -0.62 : o.yaw, pitch: o.pitch == null ? 0.34 : o.pitch, zoom: o.zoom || 1 };
    const sc = { el, cam, W: 0, H: 0, cx: 0, cy: 0, unit: 1, lw: o.lineScale || (TRV.thumbMode ? 1.8 : 1), mode: 'loading', faces: 0, frameMs: 0, contexts: 0 };
    let R = [1, 0, 0], U = [0, 0, 1], D = [0, -1, 0];
    function axes() {
      const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
      R = [cy, -sy, 0]; U = [sy * sp, cy * sp, cp]; D = [-sy * cp, -cy * cp, sp];
    }
    function box() {
      sc.W = el.clientWidth || 300; sc.H = el.clientHeight || 150;
      sc.cx = sc.W * (o.cx == null ? 0.5 : o.cx); sc.cy = sc.H * (o.cy == null ? 0.5 : o.cy);
      sc.unit = Math.min(sc.W, sc.H) * (o.radius || 0.36) * cam.zoom;
    }
    axes(); box();
    /** World point → [screen x, screen y, depth] in CSS pixels (depth > 0 faces the viewer), as kit.stage3. */
    sc.p = (v) => [sc.cx + sc.unit * v3.dot(v, R), sc.cy - sc.unit * v3.dot(v, U), v3.dot(v, D)];
    sc.facing = () => D.slice();
    /** Distance in CSS pixels from a pointer event to the projection of a world point. */
    sc.near = (ev, v) => { const b = el.getBoundingClientRect(), q = sc.p(v); return Math.hypot(ev.clientX - b.left - q[0], ev.clientY - b.top - q[1]); };
    /** The point of the unit sphere under a pointer event (front side), as kit.stage3. */
    sc.pick = (ev) => {
      const b = el.getBoundingClientRect(), x = (ev.clientX - b.left - sc.cx) / sc.unit, y = (sc.cy - (ev.clientY - b.top)) / sc.unit, r2 = x * x + y * y;
      if (r2 > 1) { const k = 1 / Math.sqrt(r2); return v3.add(v3.scale(R, x * k), v3.scale(U, y * k)); }
      return v3.add(v3.add(v3.scale(R, x), v3.scale(U, y)), v3.scale(D, Math.sqrt(1 - r2)));
    };

    /* the core: the scene, built anew by the page each frame; until it is in, the primitives draw nothing */
    let core = null, scene = null, renderer = null, glCanvas = null, parked = false;
    const ready = loadCore().then((mod) => {
      core = mod; scene = mod.createScene({ palette: TRV.palette });
      sc.mode = 'webgl';
      if (o.onChange) o.onChange();
    }, (e) => { sc.mode = 'failed'; throw e; });
    sc.ready = ready;
    if (kit.pending) kit.pending(ready);
    for (const name of PRIMS) sc[name] = (...a) => (scene ? scene[name](...a) : null);

    /** The renderer and its canvas, made on demand; inside a book only once the stage is on screen. */
    let onScreen = !TRV.embed || !window.IntersectionObserver;
    function ensureRenderer() {
      if (renderer) return true;
      if (!core || !onScreen) return false;
      glCanvas = document.createElement('canvas');
      glCanvas.className = 'fill solid-gl';
      glCanvas.style.touchAction = 'none';
      el.insertBefore(glCanvas, el.firstChild);
      renderer = core.createRenderer(glCanvas, { pixelRatio: Math.min(2, window.devicePixelRatio || 1) });
      glCanvas.addEventListener('webglcontextlost', (ev) => ev.preventDefault());
      parked = false;
      if (still) still.style.visibility = 'hidden';
      sc.contexts += 1;
      return true;
    }
    /** Keep the last frame as a picture on the 2D canvas and give the WebGL context back. */
    function park() {
      if (!renderer) return;
      if (still) {
        TRV.fitCanvas(still);
        const c = still.getContext('2d');
        c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, still.width, still.height);
        c.drawImage(glCanvas, 0, 0, still.width, still.height);
        still.style.visibility = 'visible';
      }
      renderer.forceContextLoss(); renderer.dispose(); renderer = null;
      glCanvas.remove(); glCanvas = null; parked = true;
    }
    sc.park = park;
    sc.parked = () => !renderer;
    let restTimer = 0;
    const restMs = o.park != null ? o.park : TRV.embed ? 1600 : 0;
    const rest = () => { if (!restMs) return; clearTimeout(restTimer); restTimer = setTimeout(park, restMs); };
    if (TRV.embed && window.IntersectionObserver) {
      new IntersectionObserver((entries) => {
        const seen = entries[entries.length - 1].isIntersecting;
        if (seen && !onScreen) { onScreen = true; if (o.onChange) o.onChange(); } else if (!seen && onScreen) { onScreen = false; park(); }
      }).observe(el);
    }

    /* the frame */
    let t0 = 0;
    sc.begin = () => {
      box(); axes(); tagsUsed.clear(); t0 = performance.now();
      if (!scene) return;
      scene.camera({ W: sc.W, H: sc.H, cx: sc.cx, cy: sc.cy, px: true, unit: sc.unit, yaw: cam.yaw, pitch: cam.pitch, lw: sc.lw });
      scene.begin();
    };
    /** Draw the frame. Objects and labels this frame did not place are hidden; labels behind a solid are dimmed. */
    sc.end = () => {
      tags.forEach((t, k) => { if (!tagsUsed.has(k)) { t.hidden = true; tagPts.delete(k); } });
      if (!scene) return;
      scene.end(); sc.faces = scene.faces;
      if (ensureRenderer()) {
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        if (renderer.getPixelRatio() !== dpr) renderer.setPixelRatio(dpr);
        scene.render(renderer);
        rest();
      }
      tagPts.forEach(([t, v]) => { if (sc.occluded(v, 0.02)) t.style.opacity = '0.28'; });
      sc.frameMs = performance.now() - t0;
    };

    /* picking, through the core (stage pixels) */
    sc.hitAt = (x, y) => (scene ? scene.hitAt(x, y) : null);
    sc.hit = (ev) => { const b = el.getBoundingClientRect(); return sc.hitAt(ev.clientX - b.left, ev.clientY - b.top); };
    /** True when a surface or polyhedron of this frame is in front of the world point p (by more than eps). */
    sc.occluded = (p, eps) => (scene ? scene.occluded(p, eps) : false);
    /** The index of the nearest point of `list` within px CSS pixels of a pointer event that no solid hides, or −1. */
    sc.nearest = (ev, list, px) => {
      let best = -1, bd = px == null ? 16 : px;
      list.forEach((v, k) => { const d = sc.near(ev, v); if (d <= bd && !sc.occluded(v, 0.02)) { bd = d; best = k; } });
      return best;
    };
    /** The beads and rings of the frame: { key, kind, p, x, y, hidden } in viewport pixels (for the suites). */
    sc.marks = () => { if (!scene) return []; const b = el.getBoundingClientRect(); return scene.marks().map((m) => Object.assign(m, { x: b.left + m.x, y: b.top + m.y })); };

    /* labels, as kit.stage3; dimmed where a solid hides their point */
    const tags = new Map(), tagsUsed = new Set(), tagPts = new Map();
    let tagBox = el.querySelector('.tags');
    sc.tag = (k, v, html, cls, s) => {
      if (!tagBox) { tagBox = document.createElement('div'); tagBox.className = 'tags'; el.appendChild(tagBox); }
      let t = tags.get(k);
      if (!t) { t = document.createElement('div'); tags.set(k, t); tagBox.appendChild(t); }
      const q = s && s.screen ? [v[0], v[1], 1] : sc.p(v), dx = (s && s.dx) || 0, dy = (s && s.dy) || 0;
      t.className = 'tag ' + (cls || '');
      if (t._html !== html) { t.innerHTML = html; t._html = html; }
      t.style.transform = `translate(-50%, -50%) translate(${(q[0] + dx).toFixed(1)}px, ${(q[1] + dy).toFixed(1)}px)`;
      t.style.opacity = '1'; t.hidden = false; tagsUsed.add(k);
      if (!(s && s.screen) && !(s && s.occlude === false)) tagPts.set(k, [t, v]); else tagPts.delete(k);
    };

    /* camera: named views, drag to orbit, wheel and pinch to zoom (as kit.stage3) */
    const VIEWS = { iso: [-0.62, 0.34], front: [0, 0], top: [0, Math.PI / 2 - 0.001], side: [-Math.PI / 2, 0] };
    let camTween = null;
    sc.view = (name, ms) => {
      const v = Array.isArray(name) ? name : VIEWS[name] || VIEWS.iso, y0 = cam.yaw, p0 = cam.pitch, z0 = cam.zoom;
      if (camTween) camTween.cancel();
      camTween = kit.tween(ms == null ? 600 : ms, (e) => { cam.yaw = y0 + (v[0] - y0) * e; cam.pitch = p0 + (v[1] - p0) * e; cam.zoom = z0 + ((v[2] || 1) - z0) * e; if (o.onChange) o.onChange(); });
    };
    const ptrs = new Map();
    let mode = null, pinch = 0;
    const changed = () => { if (camTween) { camTween.cancel(); camTween = null; } if (o.onChange) o.onChange(); };
    el.addEventListener('pointerdown', (ev) => {
      if (ev.target.closest('button, a, input, .chip')) return;
      if (parked && o.onChange) o.onChange();                   // a touch takes the context back
      ptrs.set(ev.pointerId, [ev.clientX, ev.clientY]);
      try { el.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic events have no capture */ }
      if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); mode = 'pinch'; return; }
      mode = o.onPick && o.onPick(ev, sc) ? 'drag' : (o.rotate === false ? null : 'orbit');
      if (mode === 'drag' && o.onDrag) o.onDrag(ev, sc);
    });
    el.addEventListener('pointermove', (ev) => {
      const last = ptrs.get(ev.pointerId);
      if (!last) return;
      const dx = ev.clientX - last[0], dy = ev.clientY - last[1];
      ptrs.set(ev.pointerId, [ev.clientX, ev.clientY]);
      if (mode === 'pinch' && ptrs.size === 2) {
        const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch > 0) { cam.zoom = clamp(cam.zoom * d / pinch, 0.6, 2.6); changed(); }
        pinch = d;
      } else if (mode === 'drag') { if (o.onDrag) o.onDrag(ev, sc); } else if (mode === 'orbit') {
        cam.yaw -= dx * 0.008; cam.pitch = clamp(cam.pitch + dy * 0.008, -1.5, 1.5); changed();
      }
    });
    const up = (ev) => { ptrs.delete(ev.pointerId); if (mode === 'drag' && o.onDrop) o.onDrop(ev, sc); if (!ptrs.size) mode = null; };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    if (o.rotate !== false && o.wheel !== false) {
      el.addEventListener('wheel', (ev) => { ev.preventDefault(); cam.zoom = clamp(cam.zoom * Math.exp(-ev.deltaY * 0.0012), 0.6, 2.6); changed(); }, { passive: false });
    }
    (TRV.solids || (TRV.solids = [])).push(sc);
    return sc;
  }
  kit.solid = solid;
})();
