"""Book-local interactive visualizations, following the trureturing-visualize scheme.

Source layout of a book (``books/<slug>/``)::

    viz/visualizations.json        the registry (schema below; the only list of visualizations)
    viz/<id>/index.html            the page: plain HTML/CSS/JS, no build step, relative links only
    viz/<id>/style.css, main.js    page layout and logic (shared pieces live in theme/viz/)
    viz/<id>/thumb.jpg             1280×720 cover for the hub and the landing page (tools/node/viz-thumbs.mjs)
    viz/tests/<id>.test.mjs        browser regression suite (tools/node/viz-test.mjs)

Published layout (:func:`build`, into ``_site/<slug>/viz/``)::

    assets/{theme.css,shell.js,hub.css,hub.js,favicon.svg}   the shared runtime (theme/viz/)
    assets/tokens.css                                        theme/generated/tokens.css
    <id>/…                                                   every *live* entry; Lean links pinned to the lock
    index.html                                               the hub: this book's live visualizations, bilingual
    visualizations.json                                      the live entries with every link resolved

Registry schema (``version`` 1, as in trureturing-visualize, except that ``path`` and ``thumbnail`` are
relative to ``viz/`` and Lean references cite GIDs)::

    {"version": 1, "visualizations": [{
        "id": "golden-carry",                    kebab-case, = directory name
        "code": "GOLDEN//CARRY",                 display code (the part after // is highlighted)
        "title": "…", "title_en": "…",           Chinese and English titles
        "summary": "…", "summary_en": "…",       one paragraph each (required for live entries)
        "path": "golden-carry/", "thumbnail": "golden-carry/thumb.jpg",
        "status": "live" | "draft",              drafts are not published and may not be embedded
        "added": "YYYY-MM-DD",
        "tags": […], "tags_en": […],              tags_en translates every tag
        "theory": [{"label", "label_en", "href", "href_en"?}],
                     href: https://…, {trureturing}/<path> (that path at the pinned commit), or a chapter of
                     this book relative to viz/, e.g. ../zh/ch01-golden-deficit.html (href_en for English)
        "lean": [{"gid": "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued", "label"?: "…"}]
                     the theorems the visualization cites (shown as LEAN ✓): every GID must be in
                     trureturing.lock.json with kind "theorem"; links point at the pinned commit
    }]}

Pages cite Lean theorems with ``<a data-lean-gid="GID" href="…">`` (a theorem of the lock: pages mark these
LEAN ✓) and other trureturing files, definitions included, with
``<a data-trureturing-path="Blueprint/…" href="…">``; :func:`pin_links` (and tools/node/viz-server.mjs for local
preview) rewrite those hrefs to the pinned commit, so a re-pin never leaves a page pointing at an old commit.

Embedding in a chapter: ``::: {.viz src="golden-carry" height="560"}`` (a local id) or
``src="trureturing-visualize:<id>"`` (a page of https://the-omega-institute.github.io/trureturing-visualize/).
HTML gets an ``<iframe>`` of ``<id>/index.html?embed=1&lang=<lang>``; PDF/EPUB get the thumbnail, the caption
and the address of the interactive version (:func:`render_embed`).

Citing one experiment card: ``::: {.viz src="<id>" preset="<card>" height="480"}``. The page must carry a button
``data-preset="<card>"`` (:func:`check_preset`). HTML gets the same iframe with ``&preset=<card>``: the page opens
on that card as a figure (the stage, one sentence, the transport; nothing scrolls inside the frame). PDF/EPUB get
the labelled still ``<id>/fig-<card>.<lang>.jpg`` of that card in the language of the edition, captured by
tools/node/viz-thumbs.mjs, instead of the wordless cover. One visualization can so be cited at several places of
a book, each time in the state the surrounding text talks about. The iframe of a local visualization also
carries its target relative to the book in ``data-tr-src``: mdBook's print.html copies chapters of every depth
to ``<lang>/`` without rewriting iframe sources, and :func:`tbook.site.fix_print_media` repairs them from it.

The same registry and page rules are implemented for Node in tools/node/viz-validate.mjs; :func:`check` runs
them natively and calls that script (when ``node`` is available) only for the JavaScript syntax check.
"""

from __future__ import annotations

import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, lean, paths
from .model import Issue

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("live", "draft")
RESERVED = ("tests", "assets")
RUNTIME_FILES = ("theme.css", "shell.js", "kit.js", "hub.css", "hub.js", "favicon.svg")
THUMB_EXT = (".jpg", ".jpeg", ".png", ".webp")
PRESET_RE = re.compile(r"^[A-Za-z0-9][\w-]*$")
_PRESET_ATTR_RE = re.compile(r'\bdata-preset="([^"]+)"')
EXTERNAL_PREFIX = "trureturing-visualize:"
EXTERNAL_BASE = "https://the-omega-institute.github.io/trureturing-visualize/viz/"
TRURETURING_HREF = "{trureturing}/"
DEFAULT_HEIGHT = 560
HEIGHT_RANGE = (160, 2400)
REGISTRY = "visualizations.json"
PAGE_FILES = ("index.html", "style.css", "main.js")
TEST_TEMPLATE = "test.mjs"

THEME_VIZ = paths.THEME / "viz"
TEMPLATES_VIZ = paths.TEMPLATES / "viz"
NODE_VALIDATE = paths.TOOLS / "node" / "viz-validate.mjs"

# Component-local interface strings. config.s(lang, "viz.<key>") wins once these are merged into
# theme/i18n/<lang>.toml (table [viz]); until then the values below are used.
STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "back_to_book": "◂ 返回本书",
        "back_to_hub": "◂ 可视化索引",
        "tagline_em": "动画只改变看法，真值以 Lean 内核验证为准",
        "hero_title": "把书中的关系结构，做成可以操作的对象",
        "hero_lede": "每个可视化对应书中的一节或一组定理。页面写明依据的章节，哪些结论已由 Lean 内核验证并冻结"
                     "（链接固定到所钉的 trureturing 提交），哪些只是页面上的数值计算或示意模型。",
        "legend_lean": "trureturing 中已冻结的定理",
        "legend_theory": "书中章节与理论条目",
        "legend_num": "页面上的数值计算，不是证明",
        "index": "索引",
        "published": "{n} 个已发布 · 按登记顺序",
        "none_live": "本书还没有已发布的可视化。",
        "added": "登记",
        "enter": "进入",
        "foot": "本页由构建依据 books/{slug}/viz/visualizations.json 生成；新增可视化：./tbook viz new。",
        "lean_pin": "Lean 依据",
        "external": "trureturing-visualize 的可视化",
        "interactive": "交互可视化",
    },
    "en": {
        "back_to_book": "◂ Back to the book",
        "back_to_hub": "◂ Visualizations",
        "tagline_em": "animation changes the view; truth rests on the Lean kernel",
        "hero_title": "The relations in the book, as objects you can operate",
        "hero_lede": "Each visualization follows a section of the book or a group of its theorems. Every page names the "
                     "sections it draws on, which results are kernel-verified and frozen in Lean (linked at the pinned "
                     "trureturing commit), and which parts are computations on the page or a schematic model.",
        "legend_lean": "frozen theorem in trureturing",
        "legend_theory": "book section or theory entry",
        "legend_num": "computed on the page, not a proof",
        "index": "Index",
        "published": "{n} published · in registry order",
        "none_live": "This book has no published visualization yet.",
        "added": "ADDED",
        "enter": "ENTER",
        "foot": "Generated by the build from books/{slug}/viz/visualizations.json; add one with ./tbook viz new.",
        "lean_pin": "Lean basis",
        "external": "Visualization from trureturing-visualize",
        "interactive": "Interactive visualization",
    },
}


class VizError(Exception):
    """A registry or page problem that stops a build or a command."""


def t(lang: str, key: str, **fmt: Any) -> str:
    """Interface string ``viz.<key>``: the shared i18n table if it defines it, else the local table."""
    text = config.s(lang, f"viz.{key}") if lang in ("zh", "en") or config.has_i18n(lang) else ""
    if not text:
        text = STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
    return text.format(**fmt) if fmt else text


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def code_html(code: str) -> str:
    """``GOLDEN//CARRY`` → ``GOLDEN<b>//</b>CARRY`` (escaped)."""
    head, sep, tail = code.partition("//")
    return esc(head) + ("<b>//</b>" + esc(tail) if sep else "")


# --------------------------------------------------------------------------- registry


def registry_path(book) -> Path:
    return book.viz_dir / REGISTRY


def load_registry(book) -> dict | None:
    """The parsed registry, None when the book has no ``viz/`` directory; raises VizError when unreadable."""
    if not book.viz_dir.exists():
        return None
    reg_file = registry_path(book)
    if not reg_file.exists():
        raise VizError(f"{paths.rel(book.viz_dir)}/ exists but has no {REGISTRY} (create entries with ./tbook viz new)")
    try:
        reg = json.loads(reg_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VizError(f"{paths.rel(reg_file)}:{exc.lineno}: not valid JSON: {exc.msg}") from exc
    if not isinstance(reg, dict):
        raise VizError(f"{paths.rel(reg_file)}: the registry must be a JSON object")
    return reg


def entries(book) -> list[dict]:
    try:
        reg = load_registry(book)
    except VizError:
        return []
    items = (reg or {}).get("visualizations")
    return [v for v in items if isinstance(v, dict)] if isinstance(items, list) else []


def entry(book, viz_id: str) -> dict | None:
    return next((v for v in entries(book) if v.get("id") == viz_id), None)


def live_entries(book) -> list[dict]:
    return [v for v in entries(book) if v.get("status") == "live" and ID_RE.match(str(v.get("id", "")))]


def _lock() -> lean.Lock | None:
    try:
        return lean.Lock.load()
    except (lean.LeanError, ValueError, KeyError, OSError):
        return None


def _localized(v: dict, key: str, lang: str) -> str:
    """``title``/``title_en`` style field for a language (Chinese for zh, English otherwise, with fallback)."""
    zh, en = v.get(key) or "", v.get(f"{key}_en") or ""
    if lang.startswith("zh"):
        return zh or en
    return en or zh


def _localized_list(v: dict, key: str, lang: str) -> list[str]:
    zh, en = v.get(key) or [], v.get(f"{key}_en") or []
    return list(zh or en) if lang.startswith("zh") else list(en or zh)


# --------------------------------------------------------------------------- links


_A_TAG_RE = re.compile(r"<a\b[^>]*>", re.I)
_HREF_RE = re.compile(r'\shref="[^"]*"')


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\s{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def pinned_refs(page_html: str) -> list[tuple[str, str]]:
    """``("gid", GID)`` / ``("path", repo path)`` for every ``<a data-lean-gid>`` / ``<a data-trureturing-path>``."""
    out = []
    for m in _A_TAG_RE.finditer(page_html):
        gid = _attr(m.group(0), "data-lean-gid")
        if gid is not None:
            out.append(("gid", gid))
        p = _attr(m.group(0), "data-trureturing-path")
        if p is not None:
            out.append(("path", p))
    return out


def trureturing_url(lock: lean.Lock | None, path: str) -> str:
    return lock.blob(path.lstrip("/")) if lock else ""


def lean_url(lock: lean.Lock | None, gid: str) -> str:
    try:
        return lock.source_url(gid) if lock else ""
    except lean.LeanError:
        return ""


def pin_links(page_html: str, lock: lean.Lock | None) -> str:
    """Point ``<a data-lean-gid>`` / ``<a data-trureturing-path>`` hrefs at the pinned commit.

    Mirrors ``pinLinks`` in tools/node/viz-common.mjs (the local preview server applies the same rewrite).
    """
    if lock is None:
        return page_html

    def repl(m: re.Match) -> str:
        tag = m.group(0)
        gid, p = _attr(tag, "data-lean-gid"), _attr(tag, "data-trureturing-path")
        url = lean_url(lock, gid) if gid is not None else trureturing_url(lock, p) if p is not None else ""
        if not url:
            return tag
        safe = url.replace("&", "&amp;").replace('"', "&quot;")
        if _HREF_RE.search(tag):
            return _HREF_RE.sub(f' href="{safe}"', tag, count=1)
        return re.sub(r"^<a\b", f'<a href="{safe}"', tag, count=1, flags=re.I)

    return _A_TAG_RE.sub(repl, page_html)


def resolve_href(href: str, lock: lean.Lock | None) -> str:
    """Registry theory href → URL (``{trureturing}/<path>`` becomes that path at the pinned commit)."""
    if isinstance(href, str) and href.startswith(TRURETURING_HREF):
        return trureturing_url(lock, href[len(TRURETURING_HREF):]) or href
    return href


def lean_refs(v: dict, lock: lean.Lock | None) -> list[dict]:
    """The entry's Lean references with label and pinned URL."""
    out = []
    for ref in v.get("lean") or []:
        if not isinstance(ref, dict) or not ref.get("gid"):
            continue
        gid = ref["gid"]
        res = lock.get(gid) if lock else None
        short = (res.name if res else gid.rsplit(".", 1)[-1]).rsplit(".", 1)[-1]
        out.append({"gid": gid, "label": ref.get("label") or short, "url": lean_url(lock, gid),
                    "kind": res.kind if res else ""})
    return out


def cited_gids(book) -> list[tuple[Path, int, str]]:
    """GIDs a book's visualizations cite (registry ``lean`` entries and page ``data-lean-gid`` links).

    ``./tbook pin --refresh`` and the unused-lock check should count these as cited (see the integration notes).
    """
    out: list[tuple[Path, int, str]] = []
    reg_file = registry_path(book)
    for v in entries(book):
        for ref in v.get("lean") or []:
            if isinstance(ref, dict) and isinstance(ref.get("gid"), str):
                out.append((reg_file, 0, ref["gid"]))
        vid = str(v.get("id", ""))
        page = book.viz_dir / vid / "index.html"
        if ID_RE.match(vid) and page.exists():
            for kind, value in pinned_refs(page.read_text(encoding="utf-8")):
                if kind == "gid":
                    out.append((page, 0, value))
    return out


def _chapter_for(book, published: str) -> Path | None:
    """``zh/ch01.html`` → ``books/<slug>/zh/ch01.md`` (README.md for index.html); None if not a chapter path."""
    m = re.match(r"^([a-z]{2,3}(?:-[A-Za-z0-9]+)*)/(.+)\.html$", published)
    if not m:
        return None
    lang, stem = m.groups()
    cand = book.dir / lang / f"{stem}.md"
    if not cand.exists() and (stem == "index" or stem.endswith("/index")):
        alt = book.dir / lang / (stem[:-5] + "README.md")
        if alt.exists():
            return alt
    return cand


def link_problem(book, base: str, url: str, ids: set[str] | None = None) -> str | None:
    """Why a relative link written in the registry (base ``viz/``) or a page (``viz/<id>/``) would break, or None.

    Paths are resolved in the published book (``_site/<slug>/``). Mirrors ``linkProblem`` in viz-validate.mjs.
    """
    if re.match(r"^(https?:|mailto:|data:|#|\{trureturing\}/)", url):
        return None
    if url.startswith("/"):
        return f'root-absolute link "{url}" breaks under /<repo>/ on GitHub Pages; use a relative link'
    p = re.split(r"[?#]", url, maxsplit=1)[0]
    if not p:
        return None
    target = posixpath.normpath(posixpath.join(base, p)) + ("/" if p.endswith("/") else "")
    if target.startswith("../"):
        return f'link "{url}" leaves the published book'
    if target in ("./", ".", "index.html", "viz/", "viz", "viz/index.html"):
        return None
    if target.startswith("viz/assets/"):
        name = target[len("viz/assets/"):]
        if name == "tokens.css":
            return None
        if (name in RUNTIME_FILES or name.startswith("vendor/")) and (THEME_VIZ / name).exists():
            return None
        return f'link "{url}" names {target}, which is not part of the shared runtime theme/viz/'
    if target.startswith("viz/"):
        vid = target[4:].split("/", 1)[0]
        if ids is not None and vid not in ids:
            return f'link "{url}" points to {vid}, which is not registered'
        f = book.viz_dir / target[4:]
        if target.endswith("/"):
            f = f / "index.html"
        return None if f.exists() else f'link "{url}" does not resolve ({paths.rel(f)})'
    chapter = _chapter_for(book, target)
    if chapter is not None:
        return None if chapter.exists() else f'link "{url}" names a chapter that does not exist ({paths.rel(chapter)})'
    return f'link "{url}" resolves to {target}, which the build does not publish'


# --------------------------------------------------------------------------- check


def check_ref(book, src: str) -> str | None:
    """Error message when ``src`` of a ``::: {.viz src=…}`` block names no usable visualization, else None."""
    src = (src or "").strip()
    if src.startswith(EXTERNAL_PREFIX):
        ext = src[len(EXTERNAL_PREFIX):]
        if not ID_RE.match(ext):
            return (f'viz src "{src}": expected trureturing-visualize:<id> with a kebab-case id, '
                    "e.g. trureturing-visualize:robin-lattice")
        return None
    if not ID_RE.match(src):
        return (f'viz src "{src}": expected the id of a visualization in {paths.rel(book.viz_dir)}/ '
                "or trureturing-visualize:<id>")
    try:
        reg = load_registry(book)
    except VizError as exc:
        return f'viz src "{src}": {exc}'
    if reg is None:
        return f'viz src "{src}": {paths.rel(book.viz_dir)}/ does not exist (scaffold one with ./tbook viz new {book.slug} {src} …)'
    v = entry(book, src)
    if v is None:
        known = ", ".join(str(e.get("id")) for e in entries(book)) or "none"
        return f'viz src "{src}" is not registered in {paths.rel(registry_path(book))} (registered: {known})'
    if v.get("status") != "live":
        return (f'viz "{src}" is a {v.get("status") or "draft"}: drafts are not published, so the embed would break; '
                'finish it (summary, theory, test, thumbnail) and set "status": "live"')
    if not (book.viz_dir / src / "index.html").exists():
        return f'viz "{src}": {paths.rel(book.viz_dir / src)}/index.html does not exist'
    return None


def still_name(preset: str, lang: str) -> str:
    """File name, inside ``viz/<id>/``, of the labelled still of an experiment card for one language."""
    return f"fig-{preset}.{lang}.jpg"


def page_presets(book, viz_id: str) -> list[str]:
    """The experiment cards (``data-preset`` values) of a local page, in document order."""
    page = book.viz_dir / viz_id / "index.html"
    try:
        found = _PRESET_ATTR_RE.findall(page.read_text(encoding="utf-8"))
    except OSError:
        return []
    return list(dict.fromkeys(found))


def check_preset(book, src: str, preset: str, lang: str | None = None) -> str | None:
    """Error message when ``preset`` of ``::: {.viz src=… preset=…}`` cannot be cited, else None.

    A local page must have the card, and (when ``lang`` is given) the still shown by PDF/EPUB must exist. A page
    of trureturing-visualize is not on disk: only the form of the name is checked."""
    src, preset = (src or "").strip(), (preset or "").strip()
    if not PRESET_RE.match(preset):
        return f'viz "{src}": preset "{preset}" is not a card name (letters, digits, "-" and "_")'
    if src.startswith(EXTERNAL_PREFIX):
        return None
    cards = page_presets(book, src)
    if preset not in cards:
        have = ", ".join(cards) or "none: the page has no data-preset buttons"
        return f'viz "{src}": no experiment card data-preset="{preset}" in {paths.rel(book.viz_dir / src / "index.html")} (cards: {have})'
    if lang and not (book.viz_dir / src / still_name(preset, lang)).is_file():
        return (f'viz "{src}": the still of card "{preset}" for {lang} is missing ({paths.rel(book.viz_dir / src / still_name(preset, lang))}); '
                f"run node tools/node/viz-thumbs.mjs {book.slug} {src}")
    return None


def _line_of(text: str, viz_id: str) -> int:
    m = re.search(r'"id"\s*:\s*"' + re.escape(viz_id) + '"', text)
    return text.count("\n", 0, m.start()) + 1 if m else 0


def _ledger_has(ledger: lean.Ledger | None, lock: lean.Lock | None, path: str) -> bool | None:
    """Whether ``path`` exists in trureturing at the pinned commit (None when no offline source can tell)."""
    if ledger is None or lock is None:
        return None
    try:
        data = ledger.read(lock.commit, path)
    except lean.LeanError:
        return None
    return None if data is None else bool(data)


def check_native(book, *, lock: lean.Lock | None = None, ledger: lean.Ledger | None = None) -> list[Issue]:
    """Registry, Lean, page-contract, link, directory, thumbnail and test checks (no Node needed)."""
    issues: list[Issue] = []
    vdir = book.viz_dir
    if not vdir.exists():
        return issues
    reg_file = registry_path(book)

    def err(path: Path, line: int, msg: str) -> None:
        issues.append(Issue("error", path, line, msg))

    def warn(path: Path, line: int, msg: str) -> None:
        issues.append(Issue("warning", path, line, msg))

    try:
        reg = load_registry(book)
    except VizError as exc:
        err(reg_file if reg_file.exists() else vdir, 0, str(exc))
        return issues
    text = reg_file.read_text(encoding="utf-8")
    if reg.get("version") != 1:
        err(reg_file, 0, "version must be 1")
    items = reg.get("visualizations")
    if not isinstance(items, list):
        err(reg_file, 0, "visualizations must be a list")
        items = []
    ids = {str(v.get("id")) for v in items if isinstance(v, dict) and v.get("id")}
    seen: set[str] = set()
    for i, v in enumerate(items):
        if not isinstance(v, dict):
            err(reg_file, 0, f"visualizations[{i}] must be an object")
            continue
        vid = str(v.get("id") or "")
        at = f"visualizations[{i}]" + (f" ({vid})" if vid else "")
        line = _line_of(text, vid) if vid else 0
        live = v.get("status") == "live"
        for key in ("id", "code", "title", "path", "thumbnail", "status", "added"):
            if not isinstance(v.get(key), str) or not v[key].strip():
                err(reg_file, line, f'{at}: missing string field "{key}"')
        if not ID_RE.match(vid) or vid in RESERVED:
            err(reg_file, line, f"{at}: id must be kebab-case and not {' or '.join(RESERVED)}")
        if vid in seen:
            err(reg_file, line, f"{at}: duplicate id")
        if v.get("path") != f"{vid}/":
            err(reg_file, line, f'{at}: path must be "{vid}/"')
        thumb = v.get("thumbnail")
        if isinstance(thumb, str) and thumb.strip() and (not thumb.startswith(f"{vid}/") or not thumb.lower().endswith(THUMB_EXT)):
            err(reg_file, line, f'{at}: thumbnail must be an image in {vid}/ (normally "{vid}/thumb.jpg")')
        if v.get("status") not in STATUSES:
            err(reg_file, line, f"{at}: status must be one of {', '.join(STATUSES)}")
        if not DATE_RE.match(str(v.get("added", ""))):
            err(reg_file, line, f"{at}: added must be YYYY-MM-DD")
        if live:
            for key in ("title_en", "summary", "summary_en"):
                if not isinstance(v.get(key), str) or not v[key].strip():
                    err(reg_file, line, f'{at}: a live entry needs "{key}"')
            if not isinstance(v.get("theory"), list) or not v["theory"]:
                err(reg_file, line, f"{at}: a live entry names at least one theory reference")
        for key in ("tags", "tags_en"):
            if key in v and (not isinstance(v[key], list) or any(not isinstance(x, str) or not x.strip() for x in v[key])):
                err(reg_file, line, f"{at}: {key} must be a list of strings")
        if live and isinstance(v.get("tags"), list) and v["tags"] and (
                not isinstance(v.get("tags_en"), list) or len(v["tags_en"]) != len(v["tags"])):
            err(reg_file, line, f"{at}: tags_en must translate every tag")
        theory = v.get("theory", [])
        if not isinstance(theory, list):
            err(reg_file, line, f"{at}: theory must be a list")
            theory = []
        for k, ref in enumerate(theory):
            if not isinstance(ref, dict) or not str(ref.get("label") or "").strip() or not str(ref.get("href") or "").strip():
                err(reg_file, line, f"{at}: theory[{k}] needs a label and an href")
                continue
            if live and not str(ref.get("label_en") or "").strip():
                err(reg_file, line, f'{at}: theory reference "{ref["label"]}" needs label_en')
            for key in ("href", "href_en"):
                if key not in ref:
                    continue
                href = str(ref[key])
                if re.match(r"^https?:", href) and not re.match(r"^https://\S+$", href):
                    err(reg_file, line, f"{at}: theory[{k}].{key} must use https")
                problem = link_problem(book, "viz/", href, ids)
                if problem:
                    err(reg_file, line, f"{at}: theory[{k}].{key}: {problem}")
                if href.startswith(TRURETURING_HREF) and _ledger_has(ledger, lock, href[len(TRURETURING_HREF):]) is False:
                    err(reg_file, line, f"{at}: theory[{k}].{key}: {href[len(TRURETURING_HREF):]} does not exist in "
                                        f"trureturing at the pinned commit {lock.commit[:12]}")
        refs = v.get("lean", [])
        if not isinstance(refs, list):
            err(reg_file, line, f"{at}: lean must be a list of {{gid, label?}}")
            refs = []
        for k, ref in enumerate(refs):
            gid = ref.get("gid") if isinstance(ref, dict) else None
            if not isinstance(gid, str) or not gid.strip():
                err(reg_file, line, f'{at}: lean[{k}] needs a "gid" (e.g. D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)')
                continue
            if "label" in ref and (not isinstance(ref["label"], str) or not ref["label"].strip()):
                err(reg_file, line, f"{at}: lean[{k}].label must be a non-empty string when given")
            try:
                lean.parse_gid(gid)
            except lean.LeanError:
                err(reg_file, line, f"{at}: lean[{k}]: not a declaration GID: {gid}")
                continue
            res = lock.get(gid) if lock is not None else None
            if lock is None:
                err(reg_file, line, f"{at}: lean[{k}]: {gid} cannot be linked: trureturing.lock.json is missing (run ./tbook pin)")
            elif res is None:
                err(reg_file, line, f"{at}: lean[{k}]: {gid} is not in trureturing.lock.json; cite it in a chapter "
                                    "and run ./tbook pin --refresh" + config.unhide_hint(book.slug))
            elif res.kind not in lean.FORMAL_KINDS:
                err(reg_file, line, f"{at}: lean[{k}]: {gid} is a Lean {res.kind}, not a theorem; lean lists the "
                                    "theorems the visualization cites (shown as LEAN ✓)")
        seen.add(vid)
        if not ID_RE.match(vid):
            continue
        vpath = vdir / vid
        if live and isinstance(thumb, str) and thumb.strip() and not (vdir / thumb).exists():
            err(vdir / thumb, 0, f"{at}: thumbnail does not exist (run node tools/node/viz-thumbs.mjs {book.slug} {vid})")
        if live and not (vdir / "tests" / f"{vid}.test.mjs").exists():
            warn(vdir / "tests", 0, f"{at}: a live visualization should have a browser test tests/{vid}.test.mjs")
        page = vpath / "index.html"
        if not page.exists():
            err(page, 0, f"{at}: page does not exist")
            continue
        issues.extend(check_page(book, vid, page, ids, lock=lock, ledger=ledger))
    for d in sorted(p for p in vdir.iterdir() if p.is_dir()):
        if d.name not in RESERVED and d.name not in seen:
            err(d, 0, f"viz/{d.name}/ is not registered in {REGISTRY}")
    tdir = vdir / "tests"
    if tdir.is_dir():
        for f in sorted(tdir.glob("*.test.mjs")):
            if f.name[: -len(".test.mjs")] not in seen:
                warn(f, 0, f"tests/{f.name} belongs to no registered visualization")
    return issues


PAGE_NEEDLES = (
    ('data-viz-id="{id}"', "body carries data-viz-id"),
    ('href="../assets/theme.css"', "loads the shared theme"),
    ('class="crumb" href="../"', "links back to the visualization index"),
    ("<title>", "has a <title>"),
    ('data-title-en="', "gives an English title on <html>"),
    ('data-lang-set="zh"', "offers the Chinese switch"),
    ('data-lang-set="en"', "offers the English switch"),
)


def _class_count(page_html: str, name: str) -> int:
    return len(re.findall(rf'class="(?:[^"]*\s)?{name}(?:\s[^"]*)?"', page_html))


def check_page(book, vid: str, page: Path, ids: set[str], *, lock=None, ledger=None) -> list[Issue]:
    """The page contract of one visualization (mirrors viz-validate.mjs)."""
    issues: list[Issue] = []
    text = page.read_text(encoding="utf-8")

    def err(line: int, msg: str) -> None:
        issues.append(Issue("error", page, line, msg))

    for needle, why in PAGE_NEEDLES:
        needle = needle.replace("{id}", vid)
        if needle not in text:
            err(0, f"{why} (expected {needle})")
    head = text[: max(0, text.find("</head>"))]
    if 'src="../assets/shell.js"' not in head:
        err(0, 'loads the shared runtime in <head> (expected src="../assets/shell.js" before </head>)')
    zh, en = _class_count(text, "zh"), _class_count(text, "en")
    if zh != en:
        err(0, f"{zh} .zh fragments but {en} .en fragments; every text fragment needs both languages")
    for kind, value in pinned_refs(text):
        line = text.count("\n", 0, text.find(value)) + 1 if value else 0
        if kind == "gid":
            try:
                lean.parse_gid(value)
            except lean.LeanError:
                err(line, f'data-lean-gid="{value}" is not a declaration GID')
                continue
            res = lock.get(value) if lock is not None else None
            if lock is not None and res is None:
                err(line, f'data-lean-gid="{value}" is not in trureturing.lock.json; cite it in a chapter and run ./tbook pin --refresh'
                    + config.unhide_hint(book.slug))
            elif res is not None and res.kind not in lean.FORMAL_KINDS:
                err(line, f'data-lean-gid="{value}" names a Lean {res.kind}, not a theorem; data-lean-gid cites verified '
                          'theorems (LEAN ✓); link a definition with data-trureturing-path="<module>.lean"')
        else:
            if not value or ".." in value or value.startswith("/"):
                err(line, f'data-trureturing-path="{value}" must be a repository-relative path')
            elif _ledger_has(ledger, lock, value) is False:
                err(line, f'data-trureturing-path="{value}" does not exist in trureturing at the pinned commit {lock.commit[:12]}')
    for m in re.finditer(r'\s(?:src|href)="([^"]+)"', text):
        problem = link_problem(book, f"viz/{vid}/", m.group(1), ids)
        if problem:
            err(text.count("\n", 0, m.start()) + 1, problem)
    return issues


def node_executable() -> str | None:
    return os.environ.get("NODE") or shutil.which("node")


def check_scripts(book) -> list[Issue]:
    """JavaScript syntax of the book's visualizations and the shared runtime, via node (skipped without node)."""
    node = node_executable()
    if not node or not NODE_VALIDATE.exists() or os.environ.get("TBOOK_VIZ_NODE") == "0":
        return []
    try:
        r = subprocess.run([node, str(NODE_VALIDATE), "--json", "--only=scripts", str(book.dir)],
                           capture_output=True, text=True, timeout=300, cwd=paths.ROOT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Issue("warning", NODE_VALIDATE, 0, f"could not run viz-validate.mjs: {exc}")]
    try:
        problems = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        msg = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["no output"]
        return [Issue("warning", NODE_VALIDATE, 0, f"viz-validate.mjs failed: {msg[0]}")]
    return [Issue("error" if p.get("severity") == "error" else "warning", paths.ROOT / p.get("path", ""), 0,
                  str(p.get("message", ""))) for p in problems]


def check(book) -> list[Issue]:
    """Validate the book's ``viz/`` directory (``./tbook check``); returns :class:`tbook.model.Issue` objects."""
    if not book.viz_dir.exists():
        return []
    lock = _lock()
    ledger = lean.Ledger(lock.repo, offline=True) if lock else None
    issues = check_native(book, lock=lock, ledger=ledger)
    issues.extend(check_scripts(book))
    return issues


# --------------------------------------------------------------------------- landing page


def _theory_hrefs(ref: dict, lock: lean.Lock | None) -> dict[str, str]:
    href = resolve_href(str(ref.get("href", "")), lock)
    return {"zh": href, "en": resolve_href(str(ref.get("href_en") or ref.get("href", "")), lock)}


def items(book) -> list[dict]:
    """Live visualizations for the book's landing page (``_site/<slug>/index.html``).

    Each item: ``kind`` ("viz"), ``id``, ``code``, ``title`` / ``summary`` ({lang: text}), ``tags`` ({lang: [..]}),
    ``href`` ("viz/<id>/") and ``thumb`` ("viz/<id>/thumb.jpg") relative to the landing page, ``thumb_file``
    (absolute source path), ``hub`` ("viz/"), ``added``, ``lean`` ([{gid, label, url, kind}]) and ``theory``
    ([{label: {lang: text}, href: {lang: url}}], hrefs relative to ``viz/`` or absolute).
    """
    lock = _lock()
    langs = list(dict.fromkeys([*book.languages, "zh", "en"]))
    out = []
    for v in live_entries(book):
        vid = v["id"]
        thumb = str(v.get("thumbnail") or f"{vid}/thumb.jpg")
        out.append({
            "kind": "viz",
            "id": vid,
            "code": v.get("code", ""),
            "title": {lang: _localized(v, "title", lang) for lang in langs},
            "summary": {lang: _localized(v, "summary", lang) for lang in langs},
            "tags": {lang: _localized_list(v, "tags", lang) for lang in langs},
            "href": f"viz/{vid}/",
            "thumb": f"viz/{thumb}",
            "thumb_file": book.viz_dir / thumb,
            "hub": "viz/",
            "added": v.get("added", ""),
            "lean": lean_refs(v, lock),
            "theory": [{"label": {lang: (ref.get("label") if lang.startswith("zh") else ref.get("label_en") or ref.get("label"))
                                  for lang in langs},
                        "href": {lang: (_theory_hrefs(ref, lock)["zh" if lang.startswith("zh") else "en"]) for lang in langs}}
                       for ref in v.get("theory") or [] if isinstance(ref, dict)],
        })
    return out


# --------------------------------------------------------------------------- embeds


def _height(env, ctx) -> int:
    raw = env.attrs.get("height", str(DEFAULT_HEIGHT)).strip().removesuffix("px")
    try:
        h = int(raw)
    except ValueError:
        h = 0
    if not HEIGHT_RANGE[0] <= h <= HEIGHT_RANGE[1]:
        ctx.issues.append(f"viz {env.attrs.get('src')}: height must be a number of pixels between "
                          f"{HEIGHT_RANGE[0]} and {HEIGHT_RANGE[1]}, got {raw!r}; using {DEFAULT_HEIGHT}")
        return DEFAULT_HEIGHT
    return h


def published_url(site, book, viz_id: str) -> str:
    """Absolute URL of a local visualization ('' when the site has no base_url)."""
    url = site.book_url(book.slug, "viz", viz_id)
    return url + "/" if url else ""


def render_embed(env, ctx, inner: str, doc) -> str:
    """Markup replacing a ``::: {.viz src=…}`` block for ``ctx.target`` ("mdbook" or "pandoc")."""
    src = (env.attrs.get("src") or "").strip()
    lang = ctx.lang
    inner = inner.strip("\n")
    external = src.startswith(EXTERNAL_PREFIX)
    vid = src[len(EXTERNAL_PREFIX):] if external else src
    v = None if external else entry(ctx.book, vid)
    title = (_localized(v, "title", lang) if v else "") or (f"trureturing-visualize · {vid}" if external else vid)
    code = (v or {}).get("code", "")
    problem = check_ref(ctx.book, src)
    preset = (env.attrs.get("preset") or "").strip()
    if not problem and preset:
        problem = check_preset(ctx.book, src, preset)
        if problem:
            preset = ""  # an unusable card: show the page in its default state rather than a broken figure
    if problem:
        ctx.issues.append(f"{doc.path}: {problem}")
    cite = f"&preset={preset}" if preset else ""
    if ctx.target == "mdbook":
        book_src = ""  # the iframe target relative to the book (<slug>/), for pages at another depth
        if external:
            page = EXTERNAL_BASE + vid + "/"
        else:
            depth = (doc.chapter.path or "").count("/")
            page = "../" * (depth + 1) + f"viz/{vid}/index.html"
            book_src = f' data-tr-src="{esc(f"viz/{vid}/index.html?embed=1&lang={lang}{cite}")}"'
        frame = f"{page}?embed=1&lang={lang}{cite}"
        full = f"{page}?lang={lang}{cite}"
        h = _height(env, ctx)
        caption = inner or esc(title)
        label = f"{code} · {title}" if code else title
        return "\n".join([
            f'<figure class="tr-media tr-viz" data-viz="{esc(src)}"' + (f' data-preset="{esc(preset)}"' if preset else "") + ">",
            f'<iframe class="tr-viz-frame" src="{esc(frame)}"{book_src} title="{esc(label)}" loading="lazy" height="{h}" '
            f'style="height:{h}px" allow="fullscreen" allowfullscreen></iframe>',
            '<figcaption class="tr-media-caption">',
            "",
            caption,
            "",
            f'<div class="tr-media-links"><a href="{esc(full)}" target="_blank" rel="noopener">'
            f'{esc(config.s(lang, "ui.open_fullscreen"))} ↗</a></div>',
            "</figcaption>",
            "</figure>",
        ])
    # pandoc (PDF / EPUB): a static card. This output does not pass through render's link rewriting, so the
    # thumbnail is registered in ctx.book_files and addressed under ctx.book_prefix (_book/…) like ../assets links.
    note = config.s(lang, "ui.viz_static_note")
    if external:
        url = EXTERNAL_BASE + vid + "/"
        where = f"<{url}>"
    else:
        url = published_url(ctx.site, ctx.book, vid)
        where = f"<{url}>" if url else f"`{ctx.book.slug}/viz/{vid}/`"
    lines = ["::: {.tr-media .tr-viz}"]
    thumb_rel = str((v or {}).get("thumbnail") or f"{vid}/thumb.jpg")
    if preset and not external:
        # a cited card: its own labelled still in this language; the wordless cover only when it has not been captured
        still_rel = f"{vid}/{still_name(preset, lang)}"
        if (ctx.book.viz_dir / still_rel).is_file():
            thumb_rel = still_rel
        else:
            ctx.issues.append(f"{doc.path}: viz {vid}: no still {paths.rel(ctx.book.viz_dir / still_rel)} for card "
                              f'"{preset}"; the PDF/EPUB shows the cover (run node tools/node/viz-thumbs.mjs {ctx.book.slug} {vid})')
    thumb_abs = ctx.book.viz_dir / thumb_rel
    if not external and thumb_abs.is_file():
        ctx.book_files.add(thumb_abs.resolve())
        chapter_dir = posixpath.dirname(doc.chapter.path or "") or "."
        img = posixpath.relpath(posixpath.join(ctx.book_prefix, "viz", thumb_rel), chapter_dir)
        alt = (f"{code} · {title}" if code else title).replace("[", "\\[").replace("]", "\\]")
        lines += [f"![{alt}]({img}){{width=100%}}", ""]
    else:
        if not external:
            ctx.issues.append(f"{doc.path}: viz {vid}: no thumbnail {paths.rel(thumb_abs)}; the PDF/EPUB shows a text card")
        head = f"{code} · {title}" if code else (t(lang, "external") + f" · {vid}" if external else title)
        lines += [f"**{head}**", ""]
    if inner:
        lines += [inner, ""]
    # a hard line break keeps the long address from stretching the justified note line
    lines += [f"{note}\\", where, ":::"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- hub and build


def _pair(key: str, **fmt: Any) -> str:
    return f'<span class="zh">{esc(t("zh", key, **fmt))}</span><span class="en">{esc(t("en", key, **fmt))}</span>'


def _pair_text(zh: str, en: str) -> str:
    if zh == en:
        return esc(zh)
    return f'<span class="zh">{esc(zh)}</span><span class="en">{esc(en)}</span>'


def _ui_pair(key: str) -> str:
    return _pair_text(config.s("zh", key), config.s("en", key))


def _google_fonts() -> str:
    try:
        tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
        return str(tokens.get("font", {}).get("google-fonts-css", ""))
    except (OSError, json.JSONDecodeError):
        return ""


def _card(v: dict, lock: lean.Lock | None, featured: bool) -> str:
    vid = v["id"]
    zh_t, en_t = v.get("title") or "", v.get("title_en") or v.get("title") or ""
    refs = []
    for ref in v.get("theory") or []:
        if not isinstance(ref, dict):
            continue
        hrefs = _theory_hrefs(ref, lock)
        lz, le = str(ref.get("label") or ""), str(ref.get("label_en") or ref.get("label") or "")
        ext = ' target="_blank" rel="noopener"' if re.match(r"^https?:", hrefs["zh"]) else ""
        if hrefs["zh"] == hrefs["en"]:
            link = f'<a href="{esc(hrefs["zh"])}"{ext}>{_pair_text(lz, le)}</a>'
        else:
            ext_en = ' target="_blank" rel="noopener"' if re.match(r"^https?:", hrefs["en"]) else ""
            link = (f'<a class="zh" href="{esc(hrefs["zh"])}"{ext}>{esc(lz)}</a>'
                    f'<a class="en" href="{esc(hrefs["en"])}"{ext_en}>{esc(le)}</a>')
        refs.append(f'<div><span class="k">THEORY</span>{link}</div>')
    for ref in lean_refs(v, lock):
        target = f'<a href="{esc(ref["url"])}" target="_blank" rel="noopener" title="{esc(ref["gid"])}"><code>{esc(ref["label"])}</code></a>' \
            if ref["url"] else f'<code title="{esc(ref["gid"])}">{esc(ref["label"])}</code>'
        # green LEAN ✓ only for a locked theorem; anything else (check refuses it) is a plain Lean link
        chip = '<span class="k ok">LEAN ✓</span>' if ref["kind"] in lean.FORMAL_KINDS else '<span class="k">LEAN</span>'
        refs.append(f"<div>{chip}{target}</div>")
    tags_zh, tags_en = list(v.get("tags") or []), list(v.get("tags_en") or v.get("tags") or [])
    tags = ""
    if tags_zh or tags_en:
        if tags_zh == tags_en:
            tags = '<ul class="tags">' + "".join(f"<li>{esc(x)}</li>" for x in tags_zh) + "</ul>"
        else:
            tags = ('<ul class="tags zh">' + "".join(f"<li>{esc(x)}</li>" for x in tags_zh) + "</ul>"
                    '<ul class="tags en">' + "".join(f"<li>{esc(x)}</li>" for x in tags_en) + "</ul>")
    thumb = str(v.get("thumbnail") or f"{vid}/thumb.jpg")
    # in Chinese mode the English title runs underneath (as in trureturing-visualize); English mode stays English
    alt = f'<p class="alt-title zh">{esc(en_t)}</p>' if zh_t != en_t else ""
    return "\n".join([
        f'<article class="card panel{" featured" if featured else ""}" data-viz="{esc(vid)}">',
        f'  <a class="thumb" href="{esc(vid)}/" tabindex="-1" aria-hidden="true"><img src="{esc(thumb)}" alt="" '
        f'loading="lazy" width="1280" height="720"><span class="code">{esc(v.get("code", ""))}</span></a>',
        '  <div class="body">',
        f'    <h3><a href="{esc(vid)}/">{_pair_text(zh_t, en_t)}</a></h3>',
        f"    {alt}" if alt else "",
        f'    <p class="sum">{_pair_text(str(v.get("summary") or ""), str(v.get("summary_en") or v.get("summary") or ""))}</p>',
        f"    {tags}" if tags else "",
        f'    <div class="refs">{"".join(refs)}</div>',
        f'    <div class="actions"><span class="date">{_pair("added")} {esc(v.get("added", ""))}</span>'
        f'<a class="chip enter" href="{esc(vid)}/">{_pair("enter")} ▸</a></div>',
        "  </div>",
        "</article>",
    ]).replace("\n\n", "\n")


def hub_html(site, book, lock: lean.Lock | None = None) -> str:
    """The bilingual hub page ``_site/<slug>/viz/index.html`` (static HTML; hub.js only decorates)."""
    live = live_entries(book)
    title_zh, title_en = config.pick(book.title, "zh", book.languages), config.pick(book.title, "en", book.languages)
    viz_zh, viz_en = config.s("zh", "ui.visualizations"), config.s("en", "ui.visualizations")
    fonts = _google_fonts()
    cards = "\n".join(_card(v, lock, i == 0) for i, v in enumerate(live)) or f'<p class="note">{_pair("none_live")}</p>'
    pin = ""
    if lock:
        pin = (f'<a class="pill" href="{esc(lock.tree_url)}" target="_blank" rel="noopener">LEAN '
               f'<strong>trureturing@{esc(lock.commit[:7])} ↗</strong></a>')
    head_fonts = ""
    if fonts:
        head_fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
                      f'<link rel="stylesheet" href="{esc(fonts)}">\n')
    desc_zh = f"{title_zh} · {viz_zh}"
    desc_en = f"{title_en} · {viz_en}"
    return f"""<!doctype html>
<html lang="zh-CN" data-title-en="{esc(book.code)} · {esc(viz_en)} · {esc(title_en)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(book.code)} · {esc(viz_zh)} · {esc(title_zh)}</title>
<meta name="description" content="{esc(desc_zh)} · {esc(desc_en)}">
<meta name="generator" content="tbook viz">
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
{head_fonts}<link rel="stylesheet" href="assets/theme.css">
<link rel="stylesheet" href="assets/hub.css">
<script src="assets/shell.js"></script>
</head>
<body data-viz-hub="{esc(book.slug)}">
<div class="hub" id="app">
  <header class="top">
    <div class="brand">
      <a class="crumb" href="../">{_pair("back_to_book")}</a>
      <h1 class="logo" data-text="{esc(book.code)}">{code_html(book.code)}</h1>
      <div class="tagline">{_pair_text(title_zh, title_en)} · <em>{_pair_text(viz_zh, viz_en)}</em></div>
    </div>
    <nav class="status" aria-label="链接" data-aria-en="Links">
      <span class="pill">VIZ <strong>{len(live)}</strong></span>
      {pin}
      <div class="langs" role="group" aria-label="语言 Language"><button data-lang-set="zh" aria-pressed="true">中</button><button data-lang-set="en" aria-pressed="false">EN</button></div>
    </nav>
  </header>

  <section class="hero panel" aria-labelledby="heroTitle">
    <canvas id="field" aria-hidden="true"></canvas>
    <div class="hero-text">
      <h2 id="heroTitle">{_pair("hero_title")}</h2>
      <p>{_pair("hero_lede")}</p>
      <p class="tagline"><em>{_pair("tagline_em")}</em></p>
      <ul class="legend">
        <li><span class="k ok">LEAN ✓</span>{_pair("legend_lean")}</li>
        <li><span class="k">THEORY</span>{_pair("legend_theory")}</li>
        <li><span class="k num">NUM</span>{_pair("legend_num")}</li>
      </ul>
    </div>
  </section>

  <section aria-labelledby="indexTitle">
    <div class="index-head"><h2 id="indexTitle">{_pair("index")}</h2><span>{_pair("published", n=len(live))}</span></div>
    <div class="grid" id="grid">
{cards}
    </div>
  </section>

  <footer class="foot">
    <span>{_pair("foot", slug=book.slug)}</span>
    <span>trureturing books · {esc(book.license or "")}</span>
  </footer>
</div>
<script src="assets/hub.js"></script>
</body>
</html>
"""


def hub_html_for(slug: str) -> str:
    """Hub of a book by slug (used by tools/node/viz-server.mjs for local preview)."""
    return hub_html(config.load_site(), config.named_book(slug), _lock())


def favicon_svg() -> str:
    tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
    text = (THEME_VIZ / "favicon.svg").read_text(encoding="utf-8")
    return re.sub(r"@@([a-z-]+)@@", lambda m: tokens["screen"].get(m.group(1), m.group(0)), text)


def publish_assets(out_dir: Path) -> None:
    """Copy the shared runtime and tokens.css into ``out_dir/assets``."""
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_FILES:
        src = THEME_VIZ / name
        if not src.exists():
            raise VizError(f"shared runtime file missing: {paths.rel(src)}")
        if name == "favicon.svg":
            (assets / name).write_text(favicon_svg(), encoding="utf-8")
        else:
            shutil.copyfile(src, assets / name)
    vendor = THEME_VIZ / "vendor"
    if vendor.is_dir():
        shutil.copytree(vendor, assets / "vendor", dirs_exist_ok=True)
    tokens_css = paths.GENERATED / "tokens.css"
    if not tokens_css.exists():
        raise VizError(f"{paths.rel(tokens_css)} is missing; run ./tbook theme")
    shutil.copyfile(tokens_css, assets / "tokens.css")


def published_registry(book, lock: lean.Lock | None) -> dict:
    out = []
    for v in live_entries(book):
        e = {k: v[k] for k in ("id", "code", "title", "title_en", "summary", "summary_en", "path", "thumbnail",
                               "status", "added", "tags", "tags_en") if k in v}
        e["theory"] = [{**ref, "href": _theory_hrefs(ref, lock)["zh"],
                        **({"href_en": _theory_hrefs(ref, lock)["en"]} if "href_en" in ref else {})}
                       for ref in v.get("theory") or [] if isinstance(ref, dict)]
        e["lean"] = [{"gid": r["gid"], "label": r["label"], "href": r["url"], "kind": r["kind"]} for r in lean_refs(v, lock)]
        out.append(e)
    data: dict[str, Any] = {"version": 1, "book": book.slug}
    if lock:
        data["trureturing"] = {"repo": lock.repo, "commit": lock.commit}
    data["visualizations"] = out
    return data


def _ignore(_dir: str, names: list[str]) -> list[str]:
    # fig-<card>.<lang>.jpg are the stills of cited cards for PDF/EPUB; the site shows the live page instead
    return [n for n in names if n.startswith(".") or n == "node_modules" or (n.startswith("fig-") and n.endswith(".jpg"))]


def build(site, book, out_dir: Path) -> None:
    """Publish the book's live visualizations, the shared runtime and the hub into ``out_dir`` (``_site/<slug>/viz/``).

    Raises :class:`VizError` when the registry or a live page has errors (the same as ``./tbook check`` reports).
    A book without ``viz/`` publishes nothing.
    """
    out_dir = Path(out_dir)
    if not book.viz_dir.exists():
        return
    lock = _lock()
    problems = [i for i in check_native(book, lock=lock) if i.severity == "error"]
    if problems:
        shown = "\n  ".join(i.format() for i in problems[:12])
        more = f"\n  … and {len(problems) - 12} more" if len(problems) > 12 else ""
        raise VizError(f"{book.slug}: {len(problems)} visualization error(s):\n  {shown}{more}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    publish_assets(out_dir)
    # Generated publication input, also served by viz-server for local previews. Pages
    # keep their book-specific topology in source and join it to the current lock here.
    if lock:
        (out_dir / "assets" / "trureturing.json").write_text(
            json.dumps(asdict(lock), ensure_ascii=False) + "\n", encoding="utf-8")
    for v in live_entries(book):
        dst = out_dir / v["id"]
        shutil.copytree(book.viz_dir / v["id"], dst, ignore=_ignore)
        for page in sorted(dst.rglob("*.html")):
            page.write_text(pin_links(page.read_text(encoding="utf-8"), lock), encoding="utf-8")
    (out_dir / "index.html").write_text(hub_html(site, book, lock), encoding="utf-8")
    (out_dir / REGISTRY).write_text(json.dumps(published_registry(book, lock), ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")


# --------------------------------------------------------------------------- scaffolding and CLI


def fill_template(text: str, *, slug: str, viz_id: str, code: str, title: str, title_en: str,
                  html_text: bool = True) -> str:
    """Placeholders of templates/viz/ (same as ``fill`` in tools/node/viz-new.mjs).

    In an HTML template (``html_text``) the code and titles are HTML-escaped, so quotes, ``&`` and ``<`` stay
    text; in a script or stylesheet, where they only appear in comments, a ``*/`` is broken up instead.
    """
    def val(s: str) -> str:
        return html.escape(s, quote=True) if html_text else s.replace("*/", "* /")

    head, sep, tail = code.partition("//")
    code_h = f"{val(head)}<b>//</b>{val(tail)}" if sep else val(code)
    return (text.replace("__BOOK__", slug).replace("__ID__", viz_id).replace("__CODE_HTML__", code_h)
            .replace("__CODE__", val(code)).replace("__TITLE_EN__", val(title_en or title)).replace("__TITLE__", val(title)))


def scaffold(book, viz_id: str, code: str, title: str, title_en: str = "", *, added: str | None = None) -> list[Path]:
    """Create ``viz/<id>/`` and ``viz/tests/<id>.test.mjs`` from templates/viz/ and register a draft."""
    if not ID_RE.match(viz_id) or viz_id in RESERVED:
        raise VizError(f'id "{viz_id}" must be kebab-case (a-z, 0-9, -) and not {" or ".join(RESERVED)}')
    if not code.strip() or not title.strip():
        raise VizError("code and Chinese title are required")
    dest = book.viz_dir / viz_id
    if dest.exists():
        raise VizError(f"{paths.rel(dest)}/ already exists")
    reg = load_registry(book) if book.viz_dir.exists() and registry_path(book).exists() else {"version": 1, "visualizations": []}
    reg.setdefault("version", 1)
    reg.setdefault("visualizations", [])
    if any(isinstance(v, dict) and v.get("id") == viz_id for v in reg["visualizations"]):
        raise VizError(f"{viz_id} is already registered in {paths.rel(registry_path(book))}")
    fill = dict(slug=book.slug, viz_id=viz_id, code=code, title=title, title_en=title_en)
    dest.mkdir(parents=True)
    created = []
    for name in PAGE_FILES:
        out = dest / name
        out.write_text(fill_template((TEMPLATES_VIZ / name).read_text(encoding="utf-8"), **fill,
                                     html_text=name.endswith(".html")), encoding="utf-8")
        created.append(out)
    test = book.viz_dir / "tests" / f"{viz_id}.test.mjs"
    if not test.exists():
        test.parent.mkdir(parents=True, exist_ok=True)
        test.write_text(fill_template((TEMPLATES_VIZ / TEST_TEMPLATE).read_text(encoding="utf-8"), **fill,
                                      html_text=False), encoding="utf-8")
        created.append(test)
    reg["visualizations"].append({
        "id": viz_id, "code": code, "title": title, "title_en": title_en, "summary": "", "summary_en": "",
        "path": f"{viz_id}/", "thumbnail": f"{viz_id}/thumb.jpg", "status": "draft",
        "added": added or datetime.now(timezone.utc).date().isoformat(), "tags": [], "tags_en": [], "theory": [], "lean": [],
    })
    registry_path(book).write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    created.append(registry_path(book))
    return created


USAGE_NEW = './tbook viz new <book> <id> "<CODE//NAME>" "<中文标题>" "<English title>"'


def cli(args) -> int:
    """``./tbook viz new <book> <id> "<CODE//NAME>" "<中文标题>" "<English title>"`` and ``./tbook viz list``."""
    rest = list(getattr(args, "rest", []) or [])
    if args.action == "new":
        if len(rest) < 4 or len(rest) > 5:
            print(f"usage: {USAGE_NEW}", file=sys.stderr)
            return 2
        slug, viz_id, code, title = rest[:4]
        title_en = rest[4] if len(rest) == 5 else ""
        try:
            book = config.named_book(slug)
            created = scaffold(book, viz_id, code, title, title_en)
        except (VizError, config.ConfigError) as exc:
            print(f"tbook viz new: {exc}", file=sys.stderr)
            return 2
        for p in created:
            print(f"wrote {paths.rel(p)}")
        print(f"registered {viz_id} as a draft. Next: write the page (paired .zh/.en text), fill summary, tags, theory "
              f"and lean in the registry; preview with node tools/node/viz-server.mjs; test with node "
              f"tools/node/viz-test.mjs {book.slug}; capture node tools/node/viz-thumbs.mjs {book.slug} {viz_id}; set "
              '"status": "live"; then ./tbook check.')
        return 0
    if args.action == "list":
        if rest:
            print("usage: ./tbook viz list", file=sys.stderr)
            return 2
        rows = []
        for book in config.load_books():
            for v in entries(book):
                vid = str(v.get("id", ""))
                thumb = (book.viz_dir / str(v.get("thumbnail") or f"{vid}/thumb.jpg")).exists()
                test = (book.viz_dir / "tests" / f"{vid}.test.mjs").exists()
                rows.append((f"{book.slug}/{vid}", str(v.get("status", "?")), str(v.get("code", "")),
                             "thumb" if thumb else "no-thumb", "test" if test else "no-test",
                             str(v.get("title", ""))))
        if not rows:
            print("no visualizations (scaffold one with " + USAGE_NEW + ")")
            return 0
        widths = [max(len(r[k]) for r in rows) for k in range(5)]
        for r in rows:
            print("  ".join(r[k].ljust(widths[k]) for k in range(5)) + "  " + r[5])
        return 0
    print(f"tbook viz: unknown action {args.action!r} (new, list)", file=sys.stderr)
    return 2
