/* Film · @@TITLE_EN@@ · @@TITLE_ZH@@ (book @@SLUG@@).
   Scenes for the shared engine theme/film/engine.js: one SCENES.<id> per scene of script.json.
   S = { u: seconds into the scene, d: scene length, p: u / d, t: film time, f: frame, L: lines }.
   Timing helpers: at(S, k, dur, off) ramps 0→1 from line k's start; Q(S, k, 'phrase') from the moment the phrase
   is spoken. Drawing: txt, panel, box, chip, dot, stamp, badge(a, 'lean' | 'open' | 'argued' | 'computed').
   Colours: C.lean (green) only for Lean-verified results, C.now (amber) for the current focus,
   C.open (red) for open problems, C.argued (violet) for argued-but-unchecked claims. */
'use strict';

SCENES.open = S => {
  const a = clamp(S.u / 0.8) * clamp((S.d - S.u) / 0.6);
  txt('@@BOOK_CODE@@', W / 2, 330, { size: 30, fam: F.mono, w: 700, align: 'center', c: C.cyan, a, ls: 8 });
  txt(DATA.film.title_zh, W / 2, 470, { size: 86, fam: F.zh, w: 900, align: 'center', c: C.white, a, ab: 3 });
  txt(DATA.film.title.toUpperCase(), W / 2, 560, { size: 46, fam: F.orb, w: 900, align: 'center', c: C.white, a, ls: 4 });
  panel(W / 2 - 520, 640, 1040, 120, at(S, 1, 0.6) * a, C.cyan, 'SCENES.JS');
  txt('edit books/@@SLUG@@/films/@@ID@@/scenes.js', W / 2, 715, { size: 26, fam: F.mono, align: 'center', c: C.white, a: at(S, 1, 0.6) * a });
};

SCENES.close = S => {
  if (DATA.lean.length) badgeQ(S, [[0, null, 'lean']]);  // only when film.json cites Lean theorems
  closingCard(S, { from: 0.2 });
};
