/* trureturing books · shared runtime for book-local visualizations (window.TRV), published as <slug>/viz/assets/shell.js
   Adapted from trureturing-visualize/assets/shell.js (Apache-2.0, the-omega-institute); the API is the same, so pages
   written for trureturing-visualize port unchanged:
     TRV.L(zh, en), TRV.lang(), TRV.setLang(l), TRV.onLang(fn)   language (?lang= beats the remembered choice beats the browser;
                                                                  remembered site-wide under localStorage "tr-lang")
     TRV.palette, TRV.rgb, TRV.fonts                              colours read from the design tokens (tokens.css)
     TRV.fitCanvas, TRV.toast, TRV.glitch, TRV.startGlitch, TRV.drawer, TRV.mulberry32, TRV.gauss, TRV.smooth, TRV.reduceMotion
   Additions for books:
     TRV.embed        true with ?embed=1 (the page is inside an <iframe> of the book: header chrome hidden, compact layout)
     TRV.thumbMode    true with ?thumb=1 (tools/node/viz-thumbs.mjs is capturing the wordless cover of [data-thumb])
     TRV.preset       the experiment card a chapter cites: ?preset=<id> (null when absent)
     TRV.figure       true with ?embed=1&preset=<id>: a cited figure (the stage, one sentence, the transport; no scrolling)
     TRV.shot         true with ?shot=1 (viz-thumbs.mjs is capturing the labelled still of a cited card for PDF/EPUB)
     TRV.still        thumbMode || shot: no animation; show a representative state at once
     TRV.css(name)    the computed value of a CSS custom property, e.g. TRV.css('--tr-cyan')
     TRV.esc(text)    HTML-escape a string for innerHTML
   Load it in <head>, after theme.css and before any page script (src="../assets/shell.js" from a viz page).
   It sets <html data-lang> immediately, so the paired .zh / .en fragments never flash both languages. */
(function () {
  'use strict';
  const reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const root = document.documentElement;
  let params;
  try { params = new URLSearchParams(location.search); } catch (e) { params = new URLSearchParams(''); }
  const embed = params.get('embed') === '1';
  const thumbMode = params.get('thumb') === '1';
  const shot = params.get('shot') === '1';
  const preset = /^[A-Za-z0-9][\w-]*$/.test(params.get('preset') || '') ? params.get('preset') : null;
  if (embed) root.dataset.embed = '1';
  if (thumbMode) root.dataset.thumbMode = '1';
  if (shot) root.dataset.shot = '1';
  if (embed && preset) root.dataset.figure = '1';

  /* ---------- language: ?lang= beats the remembered choice, which beats the browser language ----------
     The choice is remembered under "tr-lang", shared with the library, the book landing pages, the films page and
     the slide decks, so a language picked anywhere on the site carries over ("trv-lang" is read for older choices). */
  const LANGS = ['zh', 'en'], KEY = 'tr-lang', OLD_KEYS = ['trv-lang'];
  function detectLang() {
    const q = params.get('lang'); if (LANGS.includes(q)) return q;
    try {
      for (const k of [KEY, ...OLD_KEYS]) { const s = localStorage.getItem(k); if (LANGS.includes(s)) return s; }
    } catch (e) { /* storage may be blocked */ }
    return /^zh/i.test(navigator.language || '') ? 'zh' : 'en';
  }
  let lang = detectLang();
  root.dataset.lang = lang;
  const langListeners = [];
  /** Pick the string for the current language. */
  const L = (zh, en) => (lang === 'en' ? en : zh);
  function applyLang() {
    root.dataset.lang = lang;
    root.lang = lang === 'zh' ? 'zh-CN' : 'en';
    if (!root.dataset.titleZh) root.dataset.titleZh = document.title;
    const title = lang === 'en' ? root.dataset.titleEn : root.dataset.titleZh;
    if (title) document.title = title;
    document.querySelectorAll('[data-lang-set]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.langSet === lang)));
    document.querySelectorAll('[data-aria-en]').forEach((el) => {
      if (!el.dataset.ariaZh) el.dataset.ariaZh = el.getAttribute('aria-label') || '';
      el.setAttribute('aria-label', lang === 'en' ? el.dataset.ariaEn : el.dataset.ariaZh);
    });
  }
  function setLang(next) {
    if (!LANGS.includes(next) || next === lang) return;
    lang = next;
    // inside the book the host page decides the language; do not overwrite the reader's own choice
    if (!embed) { try { localStorage.setItem(KEY, next); } catch (e) { /* ignore */ } }
    try { const u = new URL(location.href); if (u.searchParams.has('lang')) { u.searchParams.set('lang', next); history.replaceState(null, '', u); } } catch (e) { /* ignore */ }
    applyLang();
    // a toast in the old language disappears at once instead of fading out over the new interface
    document.querySelectorAll('.toast').forEach((t) => { t.style.transition = 'none'; t.style.opacity = '0'; void t.offsetWidth; t.style.transition = ''; });
    langListeners.forEach((fn) => fn(lang));
  }
  document.addEventListener('DOMContentLoaded', () => {
    applyLang();
    document.querySelectorAll('[data-lang-set]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.langSet)));
  });

  /* ---------- colours: read from the --tr-* design tokens (tokens.css), never duplicated here ---------- */
  function css(name) {
    try { return getComputedStyle(root).getPropertyValue(name).trim(); } catch (e) { return ''; }
  }
  // Self-contained fallbacks, used only when tokens.css could not be read (values of theme/tokens.json "screen").
  const FALLBACK = { ink: '#d4efff', dim: '#6f8ea5', faint: '#34506a', cyan: '#19f0ff', magenta: '#ff2fd0', amber: '#ffc83d', sigma: '#cfe3ff', ok: '#46ffb2', warn: '#ff5064', violet: '#9d8cff', void: '#03060c', stage: '#02040a', 'panel-edge': '#143049', 'line-hot': '#1f5d7c', blue: '#2a7bff', orange: '#ff8a3c' };
  const PALETTE_KEYS = Object.keys(FALLBACK);
  let paletteCache = null;
  function readPalette() {
    const p = {};
    for (const k of PALETTE_KEYS) p[k] = css('--tr-' + k) || FALLBACK[k];
    p.panelEdge = p['panel-edge']; p.lineHot = p['line-hot'];
    return p;
  }
  const pal = () => (paletteCache || (paletteCache = readPalette()));
  // re-read once the document (and late stylesheets) are in, in case the first read happened too early
  document.addEventListener('DOMContentLoaded', () => { paletteCache = null; });
  window.addEventListener('load', () => { paletteCache = null; });
  /** CSS colours for 2D canvases, from the tokens. */
  const palette = new Proxy({}, {
    get(_, k) { return pal()[k]; },
    has(_, k) { return k in pal(); },
    ownKeys() { return Reflect.ownKeys(pal()); },
    getOwnPropertyDescriptor(_, k) { return k in pal() ? { value: pal()[k], enumerable: true, configurable: true } : undefined; }
  });
  function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex).trim());
    if (!m) return [1, 1, 1];
    const n = parseInt(m[1], 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  /** RGB triples in 0..1 for WebGL shaders (from the same tokens). */
  const rgb = new Proxy({}, {
    get(_, k) {
      if (k === 'pre') return hexToRgb(palette.sigma).map((x) => Math.min(1, x * 1.05));
      if (k === 'gray') return hexToRgb(palette.dim);
      return hexToRgb(palette[k]);
    }
  });
  const fonts = {
    get data() { return css('--tr-font-data') || 'monospace'; },
    get body() { return css('--tr-font-body') || 'sans-serif'; },
    get display() { return css('--tr-font-display') || 'sans-serif'; }
  };
  /** Colour with alpha, e.g. TRV.alpha(TRV.palette.cyan, 0.4) → rgba(…). */
  function alpha(hex, a) { const [r, g, b] = hexToRgb(hex); return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`; }

  /** Match a canvas backing store to its CSS box; returns the device pixel ratio used. */
  function fitCanvas(cv) {
    // Labelled print stills can be captured at 4×; interactive canvases retain the 2× cap.
    const dpr = Math.min(shot ? 4 : 2, window.devicePixelRatio || 1);
    const w = Math.max(10, Math.round(cv.clientWidth * dpr));
    const h = Math.max(10, Math.round(cv.clientHeight * dpr));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    return dpr;
  }

  const toastTimers = new WeakMap();
  /** Show a transient message in a .toast element. */
  function toast(el, html, ms) {
    if (!el) return;
    el.innerHTML = html;
    el.style.opacity = '1';
    clearTimeout(toastTimers.get(el));
    toastTimers.set(el, setTimeout(() => { el.style.opacity = '0'; }, ms || 4200));
  }

  /** One glitch pulse on the .logo inside root. */
  function glitch(el) {
    if (reduceMotion || !el || embed || thumbMode || shot) return;
    el.classList.remove('glitching');
    void el.offsetWidth;
    el.classList.add('glitching');
  }
  function startGlitch(el, every) {
    glitch(el);
    if (!reduceMotion && !embed && !thumbMode && !shot) setInterval(() => glitch(el), every || 9000);
  }

  /** Wire a theory drawer. Escape closes it; returns { isOpen, open, close }. */
  function drawer(opts) {
    const d = opts.drawer, openBtn = opts.open, closeBtn = opts.close;
    const api = {
      isOpen: () => !d.hidden,
      open: () => { d.hidden = false; if (closeBtn) closeBtn.focus(); },
      close: () => { d.hidden = true; if (openBtn) openBtn.focus(); }
    };
    if (openBtn) openBtn.addEventListener('click', api.open);
    if (closeBtn) closeBtn.addEventListener('click', api.close);
    d.addEventListener('click', (ev) => { if (ev.target === d) api.close(); });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && api.isOpen()) { ev.stopImmediatePropagation(); api.close(); }
    }, true);
    return api;
  }

  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function gauss(rng) { let u = 0; while (u === 0) u = rng(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng()); }
  const smooth = (x) => x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  window.TRV = {
    reduceMotion, palette, rgb, fonts, alpha, css, esc, fitCanvas, toast, glitch, startGlitch, drawer, mulberry32, gauss, smooth,
    embed, thumbMode, shot, still: thumbMode || shot, preset, figure: embed && !!preset, L, lang: () => lang, setLang, onLang: (fn) => langListeners.push(fn)
  };
})();
