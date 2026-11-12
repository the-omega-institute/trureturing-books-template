/* trureturing books · solid-core: the modelling core of lit solids (an ES module; published as <slug>/viz/assets/solid-core.js)

   It builds and draws the objects of a solid stage with the pinned three.js next to it (./vendor/, see vendor/README.md)
   and knows nothing of the page: no DOM, no events, no theme switching, no animation loop, no clock, no random numbers.
   Given a state it draws one frame, synchronously, into the renderer it is handed; the same state drawn twice gives the
   same pixels. Two hosts use it:
     · kit.solid (theme/viz/kit.js), the interactive shell of a page: stage, pointer, labels, contexts made on screen
       and given back when idle;
     · the film engine (theme/film/), which draws a frame in renderAt(t) and composites it with drawImage.

     import { createScene, createRenderer } from '<…>/viz/solid-core.js';
     const r = createRenderer(canvas, { pixelRatio: 1 });          // or { canvas } of your own, any size
     const sc = createScene({ palette: { stage, ink, cyan, violet, amber, … } });   // token colours (CSS strings)
     sc.camera({ W: 1280, H: 720, yaw: -0.6, pitch: 0.4, zoom: 1, radius: 0.36 });  // as kit.stage3; or unit, cx, cy
     sc.begin();
     sc.surface('band', (u, v) => [x, y, z], { u: [0, 1], v: [0, 1], nu: 96, nv: 20, color: palette.violet });
     sc.bead([0, 0, 1], { color: palette.amber, key: 'now' });
     sc.end();
     sc.render(r);                                                   // one frame, now
     ctx.drawImage(r.domElement, 0, 0);
     sc.p([0, 0, 1]) → [x, y, depth] in canvas pixels;  sc.occluded([0, 0, 1]) → true when a solid hides the point

   World axes and camera are those of kit.stage3: x right, z up, an orthographic camera orbiting the origin (yaw about z,
   pitch above the horizon); `unit` pixels per world unit (default radius × min(W, H) × zoom). Colours are CSS colour
   strings, normally token colours; one key light fixed in camera coordinates plus ambient light, brighter on paper
   (a light `stage` colour) than on the dark stage. */
import * as T from './vendor/three.module.min.js';

export const THREE = T;
const TAU = Math.PI * 2;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a) => Math.hypot(a[0], a[1], a[2]);
const unit = (a) => { const n = len(a); return n > 1e-12 ? scale(a, 1 / n) : [0, 0, 1]; };
const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
function rot(v, n, a) {
  const c = Math.cos(a), s = Math.sin(a), d = dot(n, v), x = cross(n, v);
  return [v[0] * c + x[0] * s + n[0] * d * (1 - c), v[1] * c + x[1] * s + n[1] * d * (1 - c), v[2] * c + x[2] * s + n[2] * d * (1 - c)];
}

/** Sample f(u, v) → [x, y, z] on a grid of nu × nv cells (or take rows[j][i] = [x, y, z]). */
export function grid(f, o) {
  o = o || {};
  const rows = Array.isArray(f), nu = rows ? f[0].length - 1 : o.nu || 48, nv = rows ? f.length - 1 : o.nv || 24;
  const [u0, u1] = rows ? [0, 1] : o.u || [0, 1], [v0, v1] = rows ? [0, 1] : o.v || [0, 1];
  const us = [], vs = [], pts = [];
  for (let i = 0; i <= nu; i++) us.push(u0 + (u1 - u0) * i / nu);
  for (let j = 0; j <= nv; j++) vs.push(v0 + (v1 - v0) * j / nv);
  for (let j = 0; j <= nv; j++) for (let i = 0; i <= nu; i++) pts.push(rows ? f[j][i] : f(us[i], vs[j]));
  return { nu, nv, us, vs, pts, f: rows ? null : f };
}

/** The camera basis of kit.stage3: right R, up U and D towards the viewer. */
export function basis(yaw, pitch) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  return { R: [cy, -sy, 0], U: [sy * sp, cy * sp, cp], D: [-sy * cp, -cy * cp, sp] };
}

/** A WebGL renderer on `canvas` (transparent, antialiased, the drawing buffer kept so that it can be copied). */
export function createRenderer(canvas, o) {
  o = o || {};
  const r = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: o.powerPreference || 'low-power' });
  r.setClearColor(0x000000, 0);
  r.setPixelRatio(o.pixelRatio || 1);
  return r;
}

/**
 * A scene of lit solids. o.palette: token colours as CSS strings (stage decides dark or paper lighting; cyan, violet,
 * amber and ink are the defaults of the primitives). Returns the scene object described at the top of this file.
 */
export function createScene(o) {
  o = o || {};
  const pal = () => o.palette || {};
  const sc = { faces: 0, W: 300, H: 150, cx: 150, cy: 75, unit: 1, lw: 1 };
  let R = [1, 0, 0], U = [0, 0, 1], D = [0, -1, 0];
  const scene = new T.Scene(), camera = new T.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
  const ambient = new T.AmbientLight(0xffffff, 1), keyLight = new T.DirectionalLight(0xffffff, 2.2);
  keyLight.position.set(-0.42, 0.62, 0.66);                // above, to the left and in front of the viewer
  camera.add(keyLight); camera.add(keyLight.target); keyLight.target.position.set(0, 0, -1);
  scene.add(camera); scene.add(ambient);

  /** Fix the view: W, H (pixels), yaw, pitch, zoom, and either unit (pixels per world unit) or radius (0.36);
      cx, cy (0.5: the centre as a fraction of W, H; or pixels with px: true); lw (line-width factor). */
  sc.camera = (c) => {
    sc.W = c.W; sc.H = c.H; sc.lw = c.lw || 1;
    sc.cx = c.px ? c.cx : c.W * (c.cx == null ? 0.5 : c.cx); sc.cy = c.px ? c.cy : c.H * (c.cy == null ? 0.5 : c.cy);
    sc.unit = c.unit || Math.min(c.W, c.H) * (c.radius || 0.36) * (c.zoom || 1);
    ({ R, U, D } = basis(c.yaw == null ? -0.62 : c.yaw, c.pitch == null ? 0.34 : c.pitch));
    camera.left = -sc.cx / sc.unit; camera.right = (sc.W - sc.cx) / sc.unit; camera.top = sc.cy / sc.unit; camera.bottom = -(sc.H - sc.cy) / sc.unit;
    camera.position.set(D[0] * 50, D[1] * 50, D[2] * 50); camera.up.set(U[0], U[1], U[2]); camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
  };
  /** World point → [x, y, depth] in canvas pixels (depth > 0 faces the viewer). */
  sc.p = (v) => [sc.cx + sc.unit * dot(v, R), sc.cy - sc.unit * dot(v, U), dot(v, D)];
  sc.facing = () => D.slice();

  /* colours */
  const col = (c) => { const k = new T.Color(); k.setStyle(c); return k; };
  function ramp(stops, t) {
    if (stops.length === 1) return stops[0];
    const x = clamp(t, 0, 1) * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(x));
    return stops[k].clone().lerp(stops[k + 1], x - k);
  }
  let dark = true;
  function lighting() {
    const s = col(pal().stage || '#02040a');
    dark = 0.2126 * s.r + 0.7152 * s.g + 0.0722 * s.b < 0.3;
    ambient.intensity = dark ? 0.55 : 1.2;
    keyLight.intensity = dark ? 2.6 : 1.9;
  }

  /* buffers */
  const keyed = new Map();
  let loose = [], pickables = [], occluders = [], marks = [], used = new Set();
  // Picking and hiding are independent: transparent objects do not hide marks; pick:false lets rays pass.
  function register(mesh, s, extra, opaque) {
    const p = { mesh, ...extra };
    if (s.pick !== false) pickables.push(p);
    if (s.occlude == null ? opaque : s.occlude) occluders.push(p);
  }
  function setAttr(g, name, arr, size) {
    const a = g.getAttribute(name);
    if (a && a.array.length === arr.length) { a.array.set(arr); a.needsUpdate = true; } else g.setAttribute(name, new T.BufferAttribute(arr, size));
  }
  function gridIndex(nu, nv) {
    const idx = new Uint32Array(nu * nv * 6);
    let k = 0;
    for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) {
      const a = j * (nu + 1) + i, b = a + 1, c = a + nu + 2, d = a + nu + 1;
      idx[k++] = a; idx[k++] = b; idx[k++] = c; idx[k++] = a; idx[k++] = c; idx[k++] = d;
    }
    return idx;
  }
  /** Lit, both sides, shaded by vertex colour; the back side mixed towards its own colour (default: darker). */
  function surfaceMaterial() {
    const m = new T.MeshStandardMaterial({ vertexColors: true, side: T.DoubleSide, roughness: 0.52, metalness: 0.06, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    m.userData.back = { value: new T.Vector3(0, 0, 0) };
    m.userData.backMix = { value: 0.45 };
    m.onBeforeCompile = (sh) => {
      sh.uniforms.backTint = m.userData.back; sh.uniforms.backMix = m.userData.backMix;
      sh.fragmentShader = 'uniform vec3 backTint;\nuniform float backMix;\n' + sh.fragmentShader.replace('#include <color_fragment>',
        '#include <color_fragment>\n  if (!gl_FrontFacing) diffuseColor.rgb = mix(diffuseColor.rgb, backTint, backMix);');
    };
    return m;
  }

  /** Start a frame: the objects of the last frame without a key are dropped, those with a key wait to be placed. */
  sc.begin = () => {
    used = new Set();
    loose.forEach((x) => { scene.remove(x); if (x.geometry) x.geometry.dispose(); if (x.material) x.material.dispose(); });
    loose = []; pickables = []; occluders = []; marks = []; sc.faces = 0;
    lighting();
  };
  function take(k, kind, make) {
    used.add(k);
    let it = keyed.get(k);
    if (!it || it.kind !== kind) { if (it) drop(k); it = make(); it.kind = kind; keyed.set(k, it); scene.add(it.obj); }
    it.obj.visible = true;
    return it;
  }
  function drop(k) {
    const it = keyed.get(k); if (!it) return;
    scene.remove(it.obj); it.obj.traverse((x) => { if (x.geometry) x.geometry.dispose(); if (x.material) x.material.dispose(); });
    keyed.delete(k);
  }
  /**
   * A lit surface. f(u, v) → [x, y, z] (or rows of points). s: u, v ([lo, hi]), nu, nv, value(u, v) → the scalar of
   * the colour ramp; color, or colors (two or three token colours) with range [lo, hi]; back (the colour of the back
   * side; default the front colour, darker); alpha; grid ({ every: [ku, kv], color, alpha } | true); id (what hitAt
   * returns; default the key); pick (false: not pickable; it still hides what is behind it).
   */
  sc.surface = (k, f, s) => {
    s = s || {};
    const g = grid(f, s), n = g.pts.length;
    const it = take(k, 'surface', () => {
      const mesh = new T.Mesh(new T.BufferGeometry(), surfaceMaterial()), obj = new T.Group();
      const lines = new T.LineSegments(new T.BufferGeometry(), new T.LineBasicMaterial({ transparent: true }));
      obj.add(mesh); obj.add(lines);
      return { obj, mesh, lines, nu: -1, nv: -1 };
    });
    const geo = it.mesh.geometry, pos = new Float32Array(n * 3), uv = new Float32Array(n * 2), cl = new Float32Array(n * 4);
    let opaque = true;
    const stops = (s.colors || [s.color || pal().cyan || '#19f0ff']).map(col);
    const [lo, hi] = s.range || [0, 1];
    for (let j = 0; j <= g.nv; j++) for (let i = 0; i <= g.nu; i++) {
      const q = j * (g.nu + 1) + i, p = g.pts[q];
      pos[3 * q] = p[0]; pos[3 * q + 1] = p[1]; pos[3 * q + 2] = p[2];
      uv[2 * q] = g.us[i]; uv[2 * q + 1] = g.vs[j];
      const c = ramp(stops, s.value && hi > lo ? (s.value(g.us[i], g.vs[j]) - lo) / (hi - lo) : 0);
      const alpha = typeof s.alpha === 'function' ? clamp(s.alpha(g.us[i], g.vs[j]), 0, 1) : 1;
      cl[4 * q] = c.r; cl[4 * q + 1] = c.g; cl[4 * q + 2] = c.b; cl[4 * q + 3] = alpha;
      if (alpha < 1) opaque = false;
    }
    setAttr(geo, 'position', pos, 3); setAttr(geo, 'uv', uv, 2); setAttr(geo, 'color', cl, 4);
    if (it.nu !== g.nu || it.nv !== g.nv) { geo.setIndex(new T.BufferAttribute(gridIndex(g.nu, g.nv), 1)); it.nu = g.nu; it.nv = g.nv; }
    geo.computeVertexNormals(); geo.computeBoundingSphere(); geo.computeBoundingBox();
    const m = it.mesh.material, bc = s.back ? col(s.back) : new T.Color(0, 0, 0);
    m.userData.back.value.set(bc.r, bc.g, bc.b); m.userData.backMix.value = s.back ? 1 : dark ? 0.5 : 0.35;
    m.opacity = typeof s.alpha === 'number' ? s.alpha : 1; opaque = opaque && m.opacity >= 1;
    m.transparent = !opaque; m.depthWrite = opaque;
    const ln = it.lines, gr = s.grid === true ? {} : s.grid;
    ln.visible = !!gr;
    if (gr) {   // every ku-th u-line and kv-th v-line, kept on top of the faces they bound by the faces' polygon offset
      const ev = [].concat(gr.every || 1), ku = ev[0], kv = ev[ev.length - 1], seg = [];
      const addSeg = (a, b) => { const A = g.pts[a], B = g.pts[b]; seg.push(A[0], A[1], A[2], B[0], B[1], B[2]); };
      for (let i = 0; i <= g.nu; i += ku) for (let j = 0; j < g.nv; j++) addSeg(j * (g.nu + 1) + i, (j + 1) * (g.nu + 1) + i);
      for (let j = 0; j <= g.nv; j += kv) for (let i = 0; i < g.nu; i++) addSeg(j * (g.nu + 1) + i, j * (g.nu + 1) + i + 1);
      setAttr(ln.geometry, 'position', new Float32Array(seg), 3); ln.geometry.setDrawRange(0, seg.length / 3); ln.geometry.computeBoundingSphere();
      ln.material.color = gr.color ? col(gr.color) : new T.Color(0, 0, 0);
      ln.material.opacity = gr.alpha == null ? (dark ? 0.34 : 0.22) : gr.alpha;
    }
    sc.faces += g.nu * g.nv * 2;
    register(it.mesh, s, { id: s.id || k, grid: g }, opaque);
    return it.mesh;
  };
  /** A flat-shaded polyhedron: vertices [[x, y, z], …], faces [[i, j, k, …], …] (convex polygons). s: color, colors
      (one per face), alpha, edges (the colour of the edges; false: none), id. hitAt returns the face index. */
  sc.poly = (k, m, s) => {
    s = s || {};
    const it = take(k, 'poly', () => {
      const mesh = new T.Mesh(new T.BufferGeometry(), new T.MeshStandardMaterial({ vertexColors: true, side: T.DoubleSide, roughness: 0.6, metalness: 0.05, flatShading: true, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
      const edges = new T.LineSegments(new T.BufferGeometry(), new T.LineBasicMaterial({ transparent: true }));
      const obj = new T.Group(); obj.add(mesh); obj.add(edges);
      return { obj, mesh, edges };
    });
    const pos = [], cl = [], seg = [], faceOf = [];
    m.faces.forEach((f, fi) => {
      const c = col((s.colors && s.colors[fi]) || s.color || pal().violet || '#9d8cff');
      for (let t = 1; t + 1 < f.length; t++) {
        for (const q of [f[0], f[t], f[t + 1]]) { const p = m.vertices[q]; pos.push(p[0], p[1], p[2]); cl.push(c.r, c.g, c.b); }
        faceOf.push(fi);
      }
      f.forEach((q, t) => { const A = m.vertices[q], B = m.vertices[f[(t + 1) % f.length]]; seg.push(A[0], A[1], A[2], B[0], B[1], B[2]); });
    });
    const geo = it.mesh.geometry;
    setAttr(geo, 'position', new Float32Array(pos), 3); setAttr(geo, 'color', new Float32Array(cl), 3);
    geo.computeVertexNormals(); geo.computeBoundingSphere(); geo.setDrawRange(0, pos.length / 3);
    const mat = it.mesh.material; mat.opacity = s.alpha == null ? 1 : s.alpha; mat.transparent = mat.opacity < 1; mat.depthWrite = mat.opacity >= 1;
    it.edges.visible = s.edges !== false;
    setAttr(it.edges.geometry, 'position', new Float32Array(seg), 3); it.edges.geometry.setDrawRange(0, seg.length / 3); it.edges.geometry.computeBoundingSphere();
    it.edges.material.color = col(s.edges || pal().ink || '#d4efff'); it.edges.material.opacity = 0.35;
    sc.faces += pos.length / 9;
    register(it.mesh, s, { id: s.id || k, faceOf }, mat.opacity >= 1);
    return it.mesh;
  };
  /** A glass shell, centre c and radius r: faint where it faces the viewer and brighter towards the rim, so that what
      is inside stays visible and the ball still reads as a ball. s: color (default cyan), alpha, rim. It hides nothing
      and is not picked. */
  sc.glass = (k, c, r, s) => {
    s = s || {};
    const it = take(k, 'glass', () => {
      const geo = new T.SphereGeometry(1, 72, 36), obj = new T.Group();
      const mk = (side, order) => {
        const m = new T.MeshStandardMaterial({ side, transparent: true, depthWrite: false, roughness: 0.3, metalness: 0 });
        m.userData.rim = { value: 0.5 };
        m.onBeforeCompile = (sh) => {
          sh.uniforms.rimAlpha = m.userData.rim;
          sh.fragmentShader = 'uniform float rimAlpha;\n' + sh.fragmentShader.replace('#include <opaque_fragment>',
            '  diffuseColor.a = mix(diffuseColor.a, rimAlpha, pow(1.0 - abs(normalize(vNormal).z), 3.0));\n#include <opaque_fragment>');
        };
        const mesh = new T.Mesh(geo, m); mesh.renderOrder = order; return mesh;
      };
      const back = mk(T.BackSide, 1), front = mk(T.FrontSide, 3);
      obj.add(back); obj.add(front);
      return { obj, back, front };
    });
    it.obj.position.set(c[0], c[1], c[2]); it.obj.scale.setScalar(r);
    const k0 = col(s.color || pal().cyan || '#19f0ff'), a = s.alpha == null ? 0.07 : s.alpha;
    for (const [m, f] of [[it.back.material, 0.6], [it.front.material, 1]]) { m.color = k0.clone(); m.opacity = a * f; m.userData.rim.value = Math.min(1, (s.rim == null ? 0.5 : s.rim) * f); }
    return it.obj;
  };

  /* tubes and lines: a parallel-transported frame, which does not flip on straight runs */
  function tubeGeo(pts, rad, sides) {
    const n = pts.length, pos = [], nor = [], idx = [], uv = [];
    if (n < 2) return null;
    const tan = pts.map((p, i) => unit(sub(pts[Math.min(n - 1, i + 1)], pts[Math.max(0, i - 1)])));
    let N = unit(cross(tan[0], Math.abs(tan[0][2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]));
    const lengths = [0];
    for (let i = 1; i < n; i++) lengths.push(lengths[i - 1] + len(sub(pts[i], pts[i - 1])));
    for (let i = 0; i < n; i++) {
      if (i > 0) {
        const b = cross(tan[i - 1], tan[i]), sn = len(b);
        if (sn > 1e-9) N = rot(N, scale(b, 1 / sn), Math.atan2(sn, dot(tan[i - 1], tan[i])));
        N = unit(sub(N, scale(tan[i], dot(N, tan[i]))));
      }
      const B = cross(tan[i], N);
      for (let k = 0; k < sides; k++) {
        const a = TAU * k / sides, d = add(scale(N, Math.cos(a)), scale(B, Math.sin(a)));
        pos.push(pts[i][0] + rad * d[0], pts[i][1] + rad * d[1], pts[i][2] + rad * d[2]); nor.push(d[0], d[1], d[2]);
        uv.push(lengths[n - 1] > 0 ? lengths[i] / lengths[n - 1] : 0, k / sides);
      }
    }
    for (let i = 0; i + 1 < n; i++) for (let k = 0; k < sides; k++) {
      const a = i * sides + k, b = i * sides + (k + 1) % sides, c = a + sides, d = b + sides;
      idx.push(a, b, c, b, d, c);   // counter-clockwise seen from outside
    }
    const g = new T.BufferGeometry();
    g.setAttribute('position', new T.Float32BufferAttribute(pos, 3)); g.setAttribute('normal', new T.Float32BufferAttribute(nor, 3));
    g.setAttribute('uv', new T.Float32BufferAttribute(uv, 2)); g.setIndex(idx);
    return g;
  }
  /** A polyline cut into dashes of [on, off] pixels. */
  function dashes(pts, dash) {
    const on = dash[0], off = dash[1] == null ? dash[0] : dash[1], out = [];
    if (!(on > 0 && off > 0)) return [pts];
    let cur = [pts[0]], drawn = true, left = on;
    for (let i = 1; i < pts.length; i++) {
      let a = pts[i - 1], A = sc.p(a), B = sc.p(pts[i]), L = Math.hypot(B[0] - A[0], B[1] - A[1]);
      while (L > left) {
        const m = lerp(a, pts[i], left / L);
        L -= left; a = m;
        if (drawn) { cur.push(m); out.push(cur); } else cur = [m];
        drawn = !drawn; left = drawn ? on : off;
      }
      left -= L; if (drawn) cur.push(pts[i]);
    }
    if (drawn && cur.length > 1) out.push(cur);
    return out;
  }
  function addLoose(obj) { scene.add(obj); loose.push(obj); return obj; }
  const flatMat = (c, a) => new T.MeshBasicMaterial({ color: col(c), transparent: a < 1, opacity: a, depthWrite: a >= 1 });
  const litMat = (c, a, glow) => new T.MeshStandardMaterial({ color: col(c), emissive: col(c), emissiveIntensity: glow == null ? 0.35 : glow, roughness: 0.45, metalness: 0.05, transparent: a < 1, opacity: a });
  /** A line through world points: a thin unlit tube; width and dash ([on, off]) in pixels; alpha; close. */
  sc.line = (pts, s) => {
    s = s || {};
    if (pts.length < 2) return;
    const p = s.close ? pts.concat([pts[0]]) : pts, rad = (s.width || 1.2) * sc.lw * 0.5 / sc.unit, a = s.alpha == null ? 1 : s.alpha;
    for (const run of s.dash && s.dash.length ? dashes(p, s.dash) : [p]) {
      const g = tubeGeo(run, rad, 6);
      if (g) addLoose(new T.Mesh(g, flatMat(s.color || pal().cyan || '#19f0ff', a))).renderOrder = a < 1 ? 2 : 0;
    }
  };
  /** A lit tube along a curve, with a key. s: width (pixels) or r (world units), color, alpha, glow (0.2: how much of
      its own colour it gives off, so that it stands out on a solid of the same colour), sides. */
  sc.tube = (k, pts, s) => {
    s = s || {};
    if (pts.length < 2) return null;
    const c0 = s.color || pal().cyan || '#19f0ff';
    const it = take(k, 'tube', () => ({ obj: new T.Mesh(new T.BufferGeometry(), litMat(c0, 1, 0.2)) }));
    const rad = s.r || (s.width || 3) * sc.lw * 0.5 / sc.unit;
    it.obj.geometry.dispose(); it.obj.geometry = tubeGeo(pts, rad, s.sides || 10);
    const c = col(c0), a = typeof s.alpha === 'number' ? s.alpha : 1;
    const rgba = [], uv = it.obj.geometry.getAttribute('uv');
    let opaque = a >= 1;
    for (let i = 0; i < uv.count; i++) {
      const alpha = typeof s.alpha === 'function' ? clamp(s.alpha(uv.getX(i)), 0, 1) : 1;
      rgba.push(1, 1, 1, alpha); if (alpha < 1) opaque = false;
    }
    it.obj.geometry.setAttribute('color', new T.Float32BufferAttribute(rgba, 4));
    it.obj.material.vertexColors = true;
    it.obj.material.color = c; it.obj.material.emissive = c.clone(); it.obj.material.emissiveIntensity = s.glow == null ? 0.2 : s.glow;
    it.obj.material.opacity = a; it.obj.material.transparent = !opaque; it.obj.material.depthWrite = opaque;
    register(it.obj, s, { id: s.id || k }, opaque);
    return it.obj;
  };
  /** A circle (or latitude) on a sphere. Hidden hemisphere segments are dim, with continuous dash phase.
      s: n (samples, 96), fade (true), back (0.28), and line styles. centre and normal set any spherical circle. */
  sc.circle = (c, normal, r, s) => {
    s = s || {};
    const n = unit(normal), e1 = unit(cross(n, Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0])), e2 = cross(n, e1);
    const pts = [], N = s.n || 96;
    for (let i = 0; i <= N; i++) { const a = TAU * i / N; pts.push(add(c, add(scale(e1, r * Math.cos(a)), scale(e2, r * Math.sin(a))))); }
    if (s.fade === false) return sc.line(pts, s);
    const runs = s.dash && s.dash.length ? dashes(pts, s.dash) : [pts];
    for (const run of runs) for (let i = 1; i < run.length; i++) {
      const back = dot(sub(lerp(run[i - 1], run[i], 0.5), c), D) < 0;
      const g = tubeGeo([run[i - 1], run[i]], (s.width || 1.2) * sc.lw * 0.5 / sc.unit, 6);
      const a = (s.alpha == null ? 1 : s.alpha) * (back ? (s.back == null ? 0.28 : s.back) : 1);
      const mat = flatMat(s.color || pal().cyan || '#19f0ff', a);
      if (back) { mat.depthTest = false; mat.depthWrite = false; }
      addLoose(new T.Mesh(g, mat)).renderOrder = back ? 4 : 0;
    }
  };
  /** An arrow from a to b: a shaft and a lit cone; width and headSize in pixels; dash; alpha. */
  sc.arrow = (a, b, s) => {
    s = s || {};
    const d = sub(b, a), L = len(d);
    if (L < 1e-9) return;
    const u = scale(d, 1 / L), h = Math.min((s.headSize || 10) * sc.lw / sc.unit, L * 0.6), w = (s.width || 2) * sc.lw / sc.unit, c = s.color || pal().cyan || '#19f0ff', al = s.alpha == null ? 1 : s.alpha;
    const base = sub(b, scale(u, s.head === false ? 0 : h));
    sc.line([a, base], { color: c, width: s.width || 2, dash: s.dash, alpha: al });
    if (s.head === false) return;
    const cone = addLoose(new T.Mesh(new T.ConeGeometry(Math.max(w * 1.6, h * 0.42), h, 18), litMat(c, al, 0.5)));
    cone.position.set(base[0] + u[0] * h / 2, base[1] + u[1] * h / 2, base[2] + u[2] * h / 2);
    cone.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), new T.Vector3(u[0], u[1], u[2]));
  };
  /** A small lit ball at p, r in pixels; key names it among the marks. */
  sc.bead = (p, s) => {
    s = s || {};
    const m = addLoose(new T.Mesh(new T.SphereGeometry(1, 20, 12), litMat(s.color || pal().amber || '#ffc83d', s.alpha == null ? 1 : s.alpha, s.glow == null ? 0.55 : s.glow)));
    m.position.set(p[0], p[1], p[2]); m.scale.setScalar((s.r || 5) * sc.lw / sc.unit);
    marks.push({ key: s.key, p, kind: 'bead' });
  };
  /** A ring marker at p lying on a surface of normal s.normal (default: facing the viewer); r in pixels. */
  sc.ring = (p, s) => {
    s = s || {};
    const r = (s.r || 5) * sc.lw / sc.unit, m = addLoose(new T.Mesh(new T.TorusGeometry(r, r * 0.28, 8, 28), litMat(s.color || pal().violet || '#9d8cff', s.alpha == null ? 1 : s.alpha, 0.5)));
    const n = unit(s.normal || D);
    m.position.set(p[0], p[1], p[2]); m.quaternion.setFromUnitVectors(new T.Vector3(0, 0, 1), new T.Vector3(n[0], n[1], n[2]));
    marks.push({ key: s.key, p, kind: 'ring' });
  };
  /** A filled planar polygon (unlit) through world points: fill, alpha; color (with width, dash) for its outline. */
  sc.fan = (pts, s) => {
    s = s || {};
    if (pts.length < 3) return;
    if (s.fill) {
      const pos = [];
      for (let t = 1; t + 1 < pts.length; t++) for (const q of [pts[0], pts[t], pts[t + 1]]) pos.push(q[0], q[1], q[2]);
      const g = new T.BufferGeometry(); g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
      const a = s.alpha == null ? 0.25 : s.alpha;
      addLoose(new T.Mesh(g, new T.MeshBasicMaterial({ color: col(s.fill), transparent: a < 1, opacity: a, side: T.DoubleSide, depthWrite: a >= 1 }))).renderOrder = 2;
    }
    if (s.color) sc.line(pts, { color: s.color, width: s.width || 1, dash: s.dash, alpha: s.strokeAlpha == null ? 0.9 : s.strokeAlpha, close: true });
  };
  /** End the frame: keyed objects this frame did not place are hidden. */
  sc.end = () => { keyed.forEach((it, k) => { if (!used.has(k)) it.obj.visible = false; }); };
  /** Prepare shaders without blocking on compilation when KHR_parallel_shader_compile is available. */
  sc.prepare = (renderer) => renderer.compileAsync(scene, camera);
  /** Draw the frame now into `renderer` (from createRenderer), at W × H. */
  sc.render = (renderer) => {
    const sz = renderer.getSize(new T.Vector2());
    if (sz.x !== sc.W || sz.y !== sc.H) renderer.setSize(sc.W, sc.H, false);
    renderer.render(scene, camera);
  };

  /* picking: a ray from the eye through the canvas point */
  let ray = null;
  function cast(x, y, list) {
    if (!list.length) return null;
    if (!ray) ray = new T.Raycaster();
    ray.setFromCamera(new T.Vector2(x / sc.W * 2 - 1, -(y / sc.H) * 2 + 1), camera);
    scene.updateMatrixWorld(true);
    const hits = ray.intersectObjects(list.map((p) => p.mesh), false);
    for (const h of hits) { const p = list.find((q) => q.mesh === h.object); if (p) return { h, p }; }
    return null;
  }
  /** What lies under the canvas point (x, y): { id, u, v, point, normal, front, depth } (face instead of u, v on a
      polyhedron), or null. On a surface given by a function, (u, v) is refined on the exact surface (Newton on its
      projection), so it agrees with the surface rather than with its flat faces. */
  sc.hitAt = (x, y) => {
    const r = cast(x, y, pickables);
    if (!r) return null;
    const { h, p } = r, pt = [h.point.x, h.point.y, h.point.z];
    const n = h.face ? unit([h.face.normal.x, h.face.normal.y, h.face.normal.z]) : D;
    const out = { id: p.id, point: pt, normal: n, front: dot(n, D) >= 0, depth: dot(pt, D) };
    if (p.faceOf && h.faceIndex != null) out.face = p.faceOf[h.faceIndex];
    if (p.grid && h.uv) {
      const g = p.grid;
      let u = h.uv.x, v = h.uv.y;
      if (g.f) {
        const du = (g.us[g.nu] - g.us[0]) / g.nu, dv = (g.vs[g.nv] - g.vs[0]) / g.nv, u0 = u, v0 = v;
        const scr = (uu, vv) => sc.p(g.f(uu, vv));
        for (let it = 0; it < 8; it++) {
          const q = scr(u, v), ex = q[0] - x, ey = q[1] - y;
          if (Math.hypot(ex, ey) < 1e-7) break;
          const hu = du * 1e-4, hv = dv * 1e-4, qu = scr(u + hu, v), qv = scr(u, v + hv);
          const a11 = (qu[0] - q[0]) / hu, a21 = (qu[1] - q[1]) / hu, a12 = (qv[0] - q[0]) / hv, a22 = (qv[1] - q[1]) / hv, det = a11 * a22 - a12 * a21;
          if (Math.abs(det) < 1e-12) break;
          const nu = u - (a22 * ex - a12 * ey) / det, nv = v - (a11 * ey - a21 * ex) / det;
          if (Math.abs(nu - u0) > 2 * Math.abs(du) || Math.abs(nv - v0) > 2 * Math.abs(dv)) break;
          u = nu; v = nv;
        }
        const q = scr(u, v);
        if (Math.hypot(q[0] - x, q[1] - y) < 0.5) { out.point = g.f(u, v); out.depth = dot(out.point, D); } else { u = h.uv.x; v = h.uv.y; }
      }
      out.u = u; out.v = v;
    }
    return out;
  };
  /** True when a surface or polyhedron of this frame is in front of the world point p (by more than eps). */
  sc.occluded = (p, eps) => {
    const q = sc.p(p), r = cast(q[0], q[1], occluders);
    return !!r && dot([r.h.point.x, r.h.point.y, r.h.point.z], D) > q[2] + (eps == null ? 1e-3 : eps);
  };
  /** The beads and rings of the frame: { key, kind, p, x, y, hidden } (x, y in canvas pixels). */
  sc.marks = () => marks.map((m) => { const q = sc.p(m.p); return { key: m.key, kind: m.kind, p: m.p, x: q[0], y: q[1], hidden: sc.occluded(m.p, 0.02) }; });
  /** Free the GPU-side and scene objects. */
  sc.dispose = () => { [...keyed.keys()].forEach(drop); loose.forEach((x) => { scene.remove(x); if (x.geometry) x.geometry.dispose(); if (x.material) x.material.dispose(); }); loose = []; };
  return sc;
}
