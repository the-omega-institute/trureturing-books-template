// trureturing books · mdBook enhancements (loaded after mdBook's own scripts).
//
// * Menu bar: a link to the book's landing page (../ = _site/<slug>/), a language switcher
//   that opens the same chapter in the other editions (../<lang>/<same path>), and a
//   "LEAN ✓ n" link to the verification ledger.
// * Localizes mdBook's built-in English chrome (tooltips, search, help, theme names).
// * Hides "suggest an edit" on the generated ledger chapter (it has no source file).
// * CJK-aware search: mdBook indexes whitespace-separated words, which leaves Chinese
//   unsearchable; tbook.html adds character uni-/bigrams to the index at build time and
//   this file tokenizes queries the same way.
//
// Data: window.TR_EDITIONS, written per edition by tbook.html (tr-editions.js).
(function () {
  "use strict";

  const data = window.TR_EDITIONS;
  if (!data) return;
  const S = data.strings || {};
  const doc = document;

  function fmt(template, vars) {
    return String(template || "").replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  }

  function make(tag, attrs, children) {
    const node = doc.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "text") node.textContent = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const child of children || []) node.append(child);
    return node;
  }

  function svg(paths) {
    const ns = "http://www.w3.org/2000/svg";
    const icon = doc.createElementNS(ns, "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    icon.setAttribute("class", "tr-icon");
    for (const d of paths) {
      const p = doc.createElementNS(ns, "path");
      p.setAttribute("d", d);
      icon.append(p);
    }
    return icon;
  }

  // ------------------------------------------------------------------ locations

  // The edition root: mdBook's path_to_root relative to the page (the 404 page has a <base>).
  const root = (function () {
    const rel = typeof path_to_root === "string" && path_to_root ? path_to_root : "./";
    try {
      return new URL(rel, doc.baseURI);
    } catch (e) {
      return null;
    }
  })();

  // Path of this page relative to the edition root ("ch01.html", "" for the root itself).
  function pagePath() {
    if (!root || doc.querySelector("base[href]")) return "";
    const here = new URL(location.href);
    here.hash = "";
    here.search = "";
    return here.href.startsWith(root.href) ? decodeURI(here.href.slice(root.href.length)) : "";
  }

  function editionURL(code) {
    const target = new URL("../" + encodeURIComponent(code) + "/" + encodeURI(pagePath()), root);
    return target.href + location.hash;
  }

  // ------------------------------------------------------------------ menu bar

  function menuBar() {
    const right = doc.querySelector("#mdbook-menu-bar .right-buttons");
    if (!right || !root || right.querySelector(".tr-menu")) return;
    const box = make("div", { class: "tr-menu" });

    if (data.verified > 0 && data.ledger) {
      const label = `${data.verified} ${S.verified_count || ""}`.trim();
      box.append(make("a", {
        class: "tr-menu-verified",
        href: new URL(data.ledger, root).href,
        title: `${label} · ${S.verified_link || ""}`,
        "aria-label": `${label} · ${S.verified_link || ""}`,
      }, [make("span", { class: "tr-menu-verified-badge", text: S.badge_lean || "LEAN ✓" }),
          make("span", { class: "tr-menu-verified-count", text: String(data.verified) })]));
    }

    const langs = data.langs || [];
    if (langs.length > 1) {
      const nav = make("nav", { class: "tr-langs", "aria-label": S.editions || S.language || "Editions" });
      for (const lang of langs) {
        const name = lang.name || lang.code;
        if (lang.code === data.current) {
          nav.append(make("span", {
            class: "tr-lang is-current", lang: lang.bcp47, "aria-current": "true", title: name, text: lang.short,
          }));
        } else {
          nav.append(make("a", {
            class: "tr-lang", href: editionURL(lang.code), hreflang: lang.bcp47, lang: lang.bcp47,
            title: fmt(S.read_in, { name }), "aria-label": fmt(S.read_in, { name }), text: lang.short,
          }));
        }
      }
      box.append(nav);
    }

    if (data.landing) {
      box.append(make("a", {
        class: "tr-menu-home", href: new URL(data.landing, root).href,
        title: S.book_home, "aria-label": S.book_home,
      }, [svg(["M3 5.5h6.5a2.5 2.5 0 0 1 2.5 2.5v11a2 2 0 0 0-2-2H3z",
               "M21 5.5h-6.5A2.5 2.5 0 0 0 12 8v11a2 2 0 0 1 2-2h7z"])]));
    }
    right.prepend(box);
  }

  // The book's code and version above the table of contents, linking to the landing page.
  function sidebarBrand() {
    const box = doc.querySelector("#mdbook-sidebar .sidebar-scrollbox");
    if (!box || !root || box.querySelector(".tr-side-brand") || !(data.code || data.version)) return;
    const brand = make("a", {
      class: "tr-side-brand", href: new URL(data.landing || "../", root).href, title: S.book_home,
    }, [make("span", { class: "tr-side-code", text: data.code || "" }),
        make("span", { class: "tr-side-version", text: data.version ? "v" + data.version : "" })]);
    box.prepend(brand);
  }

  // ------------------------------------------------------------------ localization

  function label(selector, text, attrs) {
    if (!text) return;
    for (const node of doc.querySelectorAll(selector)) {
      for (const a of attrs || ["title", "aria-label"]) {
        if (a === "placeholder" || node.hasAttribute(a)) node.setAttribute(a, text);
      }
    }
  }

  // "[←]" in a string becomes <kbd>←</kbd>.
  function withKeys(node, text) {
    node.textContent = "";
    for (const part of String(text).split(/(\[[^\]]+\])/)) {
      if (!part) continue;
      const key = part.match(/^\[([^\]]+)\]$/);
      node.append(key ? make("kbd", { text: key[1] }) : doc.createTextNode(part));
    }
  }

  function localize() {
    // Stable hooks for the stylesheet before the English labels are replaced.
    for (const a of doc.querySelectorAll('#mdbook-menu-bar a[href$="print.html"]')) a.classList.add("tr-menu-print");
    for (const a of doc.querySelectorAll('#mdbook-menu-bar a[aria-label="Git repository"]')) a.classList.add("tr-menu-git");
    label("#mdbook-sidebar-toggle", S.toggle_toc);
    label("#mdbook-theme-toggle", S.change_theme);
    label("#mdbook-search-toggle", S.search);
    label("#mdbook-searchbar", S.search_placeholder, ["placeholder"]);
    label('#mdbook-menu-bar a[href$="print.html"]', S.print);
    label("#mdbook-menu-bar a[rel~=edit]", S.edit);
    label('#mdbook-menu-bar a[aria-label="Git repository"]', S.repository);
    label("a[rel~=prev]", S.prev);
    label("a[rel~=next]", S.next);
    label("#mdbook-sidebar", S.contents, ["aria-label"]);
    label("#mdbook-theme-list", S.change_theme, ["aria-label"]);
    for (const theme of ["default_theme", "light", "rust", "coal", "navy", "ayu"]) {
      const button = doc.getElementById("mdbook-theme-" + theme);
      const text = S["theme_" + (theme === "default_theme" ? "auto" : theme)];
      if (button && text) button.textContent = text;
    }
    // GitHub-style alerts (> [!NOTE]): mdBook writes the English kind as the title.
    for (const title of doc.querySelectorAll("#mdbook-content .blockquote-tag-title")) {
      const kind = (title.parentElement.className.match(/blockquote-tag-(note|tip|important|warning|caution)/) || [])[1];
      const text = kind && S["alert_" + kind];
      if (!text) continue;
      const last = [...title.childNodes].reverse().find((n) => n.nodeType === 3 && n.textContent.trim());
      if (last) last.textContent = text;
    }
    const help = doc.getElementById("mdbook-help-popup");
    if (help) {
      const title = help.querySelector(".mdbook-help-title");
      if (title && S.help_title) title.textContent = S.help_title;
      const lines = help.querySelectorAll("p");
      const texts = lines.length === 4 ? [S.help_nav, S.help_search, S.help_help, S.help_esc]
        : [S.help_nav, S.help_help, S.help_esc];
      lines.forEach((p, i) => { if (texts[i]) withKeys(p, texts[i]); });
    }
    const header = doc.getElementById("mdbook-searchresults-header");
    if (header && window.MutationObserver) {
      const rewrite = () => {
        const text = header.textContent;
        let m;
        if ((m = text.match(/^(\d+) search results? for '(.*)':$/s))) {
          const t = fmt(m[1] === "1" ? S.search_one : S.search_many, { n: m[1], q: m[2] });
          if (t && t !== text) header.textContent = t;
        } else if ((m = text.match(/^No search results for '(.*)'\.$/s))) {
          const t = fmt(S.search_none, { q: m[1] });
          if (t && t !== text) header.textContent = t;
        }
      };
      new MutationObserver(rewrite).observe(header, { childList: true, characterData: true, subtree: true });
    }
  }

  function ledgerPage() {
    if (pagePath() !== data.ledger) return;
    doc.documentElement.classList.add("tr-page-ledger");
    for (const a of doc.querySelectorAll("#mdbook-menu-bar a[rel~=edit]")) a.hidden = true;
    // Column names on every cell, for the stacked layout on small screens.
    for (const table of doc.querySelectorAll("#mdbook-content main table")) {
      const names = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
      for (const row of table.querySelectorAll("tbody tr")) {
        [...row.children].forEach((cell, i) => { if (names[i]) cell.setAttribute("data-label", names[i]); });
      }
    }
  }

  // ------------------------------------------------------------------ search

  // Han, kana and Hangul; punctuation splits runs. Keep in sync with tbook/html.py CJK_RE.
  const CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯";
  const RUNS = new RegExp(`[${CJK}]+|[^${CJK}]+`, "g");
  const IS_CJK = new RegExp(`^[${CJK}]`);

  function cjkGrams(run) {
    const chars = Array.from(run);
    if (chars.length === 1) return chars;
    const out = [];
    for (let i = 0; i + 1 < chars.length; i++) out.push(chars[i] + chars[i + 1]);
    return out;
  }

  function cjkSearch() {
    const E = window.elasticlunr;
    if (!E || !E.tokenizer || E.tokenizer.trCjk) return;
    const base = E.tokenizer;
    const tokenizer = function (str) {
      const out = [];
      for (const token of base.apply(this, arguments)) {
        for (const part of String(token).match(RUNS) || []) {
          if (IS_CJK.test(part)) out.push(...cjkGrams(part));
          else if (part.trim()) out.push(part);
        }
      }
      return out;
    };
    Object.assign(tokenizer, base, { trCjk: true });
    E.tokenizer = tokenizer;
    // elasticlunr's trimmer strips every non-ASCII character; trim by Unicode class instead.
    const trimmer = (token) => token.replace(/^[^\p{L}\p{N}_]+/u, "").replace(/[^\p{L}\p{N}_]+$/u, "");
    if (E.Pipeline && E.Pipeline.registeredFunctions) {
      trimmer.label = "trimmer";
      E.Pipeline.registeredFunctions.trimmer = trimmer;
    }
    E.trimmer = trimmer;
  }

  // mdBook's 30-word teaser counts a whole unspaced CJK paragraph as one word.
  // Use the stored document to show a bounded excerpt around the actual match.
  function cjkSearchTeasers() {
    const results = doc.getElementById("mdbook-searchresults");
    const input = doc.getElementById("mdbook-searchbar");
    if (!results || !input || !root || !window.MutationObserver) return;
    const update = () => {
      const config = window.search;
      const docs = config && config.index && config.index.documentStore && config.index.documentStore.docs;
      if (!docs || !config.doc_urls) return;
      const sources = new Map(config.doc_urls.map((url, i) => [new URL(url, root).href.replace(/#$/, ""), docs[i]]));
      const terms = [...new Set(input.value.toLowerCase().trim().split(/\s+/).filter(Boolean))];
      for (const item of results.children) {
        const link = item.querySelector("a[href]");
        const teaser = item.querySelector(".teaser");
        if (!link || !teaser) continue;
        const url = new URL(link.href);
        url.search = "";
        const source = sources.get(url.href.replace(/#$/, ""));
        const body = source && source.body;
        if (typeof body !== "string" || !new RegExp(`[${CJK}]`).test(body)) continue;
        const lower = body.toLowerCase();
        const hits = terms.map(t => lower.indexOf(t)).filter(i => i >= 0);
        const hit = hits.length ? Math.min(...hits) : 0;
        const chars = Array.from(body);
        const center = Array.from(body.slice(0, hit)).length;
        const start = Math.max(0, center - 40);
        const end = Math.min(chars.length, start + 160);
        const excerpt = chars.slice(start, end).join("");
        const folded = excerpt.toLowerCase();
        teaser.textContent = start ? "…" : "";
        let pos = 0;
        while (pos < excerpt.length) {
          const matches = terms.map(t => ({ term: t, at: folded.indexOf(t, pos) }))
            .filter(m => m.at >= 0).sort((a, b) => a.at - b.at || b.term.length - a.term.length);
          const match = matches[0];
          if (!match) { teaser.append(doc.createTextNode(excerpt.slice(pos))); break; }
          teaser.append(doc.createTextNode(excerpt.slice(pos, match.at)));
          teaser.append(make("em", { text: excerpt.slice(match.at, match.at + match.term.length) }));
          pos = match.at + match.term.length;
        }
        if (end < chars.length) teaser.append(doc.createTextNode("…"));
      }
    };
    new MutationObserver(update).observe(results, { childList: true });
    update();
  }

  function scrollLongInlineMath() {
    const main = doc.querySelector("#mdbook-content main");
    if (!main) return;
    const nodes = [...main.querySelectorAll(".tr-nobr, .katex")].filter(node =>
      !node.closest(".tr-math, .katex-display") &&
      (node.classList.contains("tr-nobr") || !node.closest(".tr-nobr")));
    const update = () => {
      for (const node of nodes) {
        const block = node.parentElement.closest("p, li, td, th, h1, h2, h3, h4, h5, h6") || main;
        const style = getComputedStyle(block);
        const available = block.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        node.classList.toggle("tr-inline-scroll", Math.max(node.scrollWidth, node.getBoundingClientRect().width) > available + 1);
      }
    };
    update();
    if (window.ResizeObserver) new ResizeObserver(update).observe(main);
    else window.addEventListener("resize", update);
    if (doc.fonts) doc.fonts.ready.then(update);
  }

  function run() {
    cjkSearch();
    cjkSearchTeasers();
    menuBar();
    sidebarBrand();
    localize();
    ledgerPage();
    scrollLongInlineMath();
  }

  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", run);
  else run();
})();
