// trureturing books · films page: the 中 / EN switch. The language is ?lang=, else the choice remembered under
// localStorage "tr-lang" (shared with the library, the book landing pages, the visualizations and the slide decks,
// so a language picked anywhere on the site carries over; "tr-films-lang" is read for older choices), else the
// browser language. Only toggles html[data-lang], html[lang] and the title; the page is complete without this script.
(function () {
  'use strict';
  var KEY = 'tr-lang', OLD_KEYS = ['tr-films-lang'];
  var root = document.documentElement;
  function known(v) { return v === 'zh' || v === 'en' ? v : null; }
  function stored() {
    var keys = [KEY].concat(OLD_KEYS);
    for (var i = 0; i < keys.length; i++) {
      var v = null;
      try { v = localStorage.getItem(keys[i]); } catch (e) { return null; }
      if (known(v)) return v;
    }
    return null;
  }
  function store(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* private mode: keep the choice for this page only */ } }
  function browser() { return /^zh/i.test(navigator.language || '') ? 'zh' : 'en'; }
  function apply(lang) {
    lang = lang === 'en' ? 'en' : 'zh';
    root.setAttribute('data-lang', lang);
    root.setAttribute('lang', lang === 'en' ? 'en' : 'zh-CN');
    var title = root.getAttribute('data-title-' + lang);
    if (title) document.title = title;
    var buttons = document.querySelectorAll('[data-lang-set]');
    for (var i = 0; i < buttons.length; i++) buttons[i].setAttribute('aria-pressed', String(buttons[i].getAttribute('data-lang-set') === lang));
  }
  var q = null;
  try { q = new URLSearchParams(location.search).get('lang'); } catch (e) { /* very old browsers */ }
  apply(known(q) || stored() || browser());
  document.addEventListener('DOMContentLoaded', function () {
    apply(root.getAttribute('data-lang'));
    document.addEventListener('click', function (ev) {
      var b = ev.target.closest && ev.target.closest('[data-lang-set]');
      if (!b) return;
      var lang = b.getAttribute('data-lang-set');
      store(lang);
      apply(lang);
      try {
        var url = new URL(location.href);
        url.searchParams.set('lang', lang);
        history.replaceState(history.state, '', url);
      } catch (e) { /* ignore */ }
    });
  });
})();
