/* trureturing books · language switch for the library hub and the book landing pages (written by tbook.site).
   Adapted from trureturing-visualize/assets/shell.js (Apache-2.0, the-omega-institute).

   Every user-visible string is in the page once per interface language, on elements with data-l="<lang>";
   the page's inline <style> hides all but the language named by <html data-lang>. The language is chosen by
   the language path, the legacy ?lang=<code>, the remembered choice (localStorage "tr-lang"),
   the browser's languages, then <html data-default-lang> (the first language of site.toml).
   Loaded synchronously in <head>, so the right language is set before the first paint. Without JavaScript the
   language baked into the page shows. Other attributes read here:
     data-page-lang                 language of the localized path, if any
     data-language-paths            relative paths of the localized copies of this page
     data-langs="zh en"            interface languages of the page
     data-lang-meta='{"zh": {"bcp47": "zh-CN"}, …}'
     data-title-<lang>             document title per language
     [data-aria] + data-aria-<lang>   aria-label per language
     [data-lang-set="<lang>"]      language links (aria-current is kept in sync)
     [data-ed="<lang>"]            edition rows: the one in the current language gets class "current" */
(function () {
  "use strict";
  var root = document.documentElement;
  var KEY = "tr-lang";
  var langs = (root.getAttribute("data-langs") || "").split(/\s+/).filter(Boolean);
  var fallback = root.getAttribute("data-default-lang") || langs[0] || "zh";
  var meta = {};
  try { meta = JSON.parse(root.getAttribute("data-lang-meta") || "{}"); } catch (e) { meta = {}; }
  var paths = {};
  try { paths = JSON.parse(root.getAttribute("data-language-paths") || "{}"); } catch (e) { paths = {}; }
  var pageLang = root.getAttribute("data-page-lang");
  var web = location.protocol === "http:" || location.protocol === "https:";

  function known(code) { return code && langs.indexOf(code) >= 0 ? code : null; }
  function remember(lang) {
    try { localStorage.setItem(KEY, lang); } catch (e) { /* storage may be blocked */ }
  }
  function share(lang) {
    try {
      var url = new URL(location.href);
      if (url.searchParams.get("lang") === lang) return;
      url.searchParams.set("lang", lang);
      history.replaceState(history.state, "", url);
    } catch (e) { /* ignore */ }
  }

  function destination(href, lang) {
    var url = new URL(href, location.href);
    url.search = location.search;
    if (paths[lang]) {
      if (url.searchParams.has("lang")) url.searchParams.delete("lang");
    } else {
      url.searchParams.set("lang", lang);
    }
    url.hash = location.hash;
    return url;
  }

  function fromNavigator() {
    var prefs = [];
    try { prefs = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language || ""]; } catch (e) { prefs = []; }
    for (var i = 0; i < prefs.length; i++) {
      var tag = String(prefs[i] || "").toLowerCase();
      if (known(tag)) return tag;
      var primary = tag.split("-")[0];
      if (known(primary)) return primary;
    }
    return null;
  }

  function detect() {
    if (known(pageLang)) {
      remember(pageLang);
      return pageLang;
    }
    var q = null, stored = null;
    try { q = new URLSearchParams(location.search).get("lang"); } catch (e) { q = null; }
    if (known(q)) {
      if (langs.length > 1) remember(q);
      return q;
    }
    try { stored = localStorage.getItem(KEY); } catch (e) { stored = null; }  // storage may be blocked
    if (known(stored)) return stored;
    return fromNavigator() || fallback;
  }

  var lang = detect();
  if (web && paths[lang]) {
    if (lang !== pageLang || new URLSearchParams(location.search).has("lang")) {
      location.replace(destination(paths[lang], lang).href);
    }
  } else if (!pageLang && langs.length > 1) {
    share(lang);
  }

  function apply() {
    root.setAttribute("data-lang", lang);
    root.lang = (meta[lang] && meta[lang].bcp47) || lang;
    var title = root.getAttribute("data-title-" + lang);
    if (title) document.title = title;
    var switches = document.querySelectorAll("[data-lang-set]");
    for (var i = 0; i < switches.length; i++) {
      var link = switches[i], code = link.getAttribute("data-lang-set");
      if (code === lang) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
      var href = link.getAttribute("href");
      if (web && href) link.setAttribute("href", destination(href, code).href);
    }
    var labelled = document.querySelectorAll("[data-aria]");
    for (var j = 0; j < labelled.length; j++) {
      var label = labelled[j].getAttribute("data-aria-" + lang);
      if (label) labelled[j].setAttribute("aria-label", label);
    }
    var eds = document.querySelectorAll("[data-ed]");
    for (var k = 0; k < eds.length; k++) {
      eds[k].classList.toggle("current", eds[k].getAttribute("data-ed") === lang);
    }
  }

  function setLang(next) {
    if (!known(next)) return;
    if (web && paths[next]) {
      location.assign(destination(paths[next], next).href);
      return;
    }
    lang = next;
    remember(next);
    share(next);
    apply();
  }

  apply();
  document.addEventListener("DOMContentLoaded", function () {
    apply();
    var buttons = document.querySelectorAll("[data-lang-set]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function (ev) {
        var link = ev.currentTarget;
        if (web && link.getAttribute("href")) {
          // Update the link at activation so a hash picked since page load also carries over.
          var code = link.getAttribute("data-lang-set");
          link.setAttribute("href", destination(link.getAttribute("href"), code).href);
          return;
        }
        ev.preventDefault();
        setLang(link.getAttribute("data-lang-set"));
      });
    }
  });
  window.TRBooks = { lang: function () { return lang; }, setLang: setLang };
})();
