"""Assemble the GitHub Pages artifact (``_site/``) from the build outputs (docs/ARCHITECTURE.md §6).

:func:`build` copies what the other build steps produced and writes the pages around it::

    build/html/<slug>/<lang>/   →  <out>/<slug>/<lang>/          mdBook editions
    build/dist/<slug>/*         →  <out>/<slug>/downloads/       PDF (screen, print) and EPUB
    tbook.cover.render_cover    →  <out>/<slug>/cover-<lang>.png (CSS-only cover card if it fails)
    tbook.viz.build             →  <out>/<slug>/viz/
    tbook.film.build            →  <out>/<slug>/films/           films page, posters, the videos (rendered or restored)
    tbook.slides.publish        →  <out>/<slug>/slides/
    generated                   →  index.html (library hub), <slug>/index.html (book landing page),
                                   404.html, manifest.json, .nojekyll, assets/

Pages are static HTML written here with every value escaped (:func:`html.escape`; formulas are
KaTeX's HTML, rendered with ``trust: false``); the only script is ``assets/site.js`` (language
switch). Each page carries every interface string once
per site language (elements with ``data-l="<lang>"``); an inline ``<style>`` hides the inactive
ones, so the default language (the first of ``site.toml``) shows even without JavaScript.
Strings come from ``theme/i18n/<lang>.toml`` via :func:`tbook.config.s`, plus :data:`SITE_I18N`
for the keys this component adds (overridable as ``[site]`` in the i18n tables). Links are
relative (the site is served under ``/<repo>/``); only ``404.html`` uses the absolute base path,
since GitHub Pages serves it at any depth.

Media modules (viz, film, slides) are optional: a module that is missing, not implemented yet
(``NotImplementedError``) or has no ``items(book)`` is skipped and its landing-page section
omitted. Any other failure is reported and raised as :class:`SiteError` after the rest of the
site has been written, so CI does not deploy a site with silently missing parts.

``only={"viz"}`` (or ``{"films"}``, ``{"slides"}``) republishes just those parts of the given
books into an existing site and regenerates the pages, which are computed from what is present in
``out_dir``; the hub and the manifest keep every configured book already published there. Any build
removes ``<out>/<slug>/`` of the books site.toml [books].hide hides (a full build empties ``out`` anyway).

Theorem titles on the landing pages are inline Markdown: their formulas are rendered by KaTeX at build
time (:func:`render_title_math`, one Node process for the site; tbook.mathrender finds them as everywhere
else), and the pages that show one load ``assets/katex/katex.min.css`` with its fonts. Without Node or
KaTeX the formulas show as their TeX source.
"""

from __future__ import annotations

import hashlib
import html
import importlib
import json
import os
import subprocess
import posixpath
import re
import shutil
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import config, lean, mathrender, mdscan, paths, render
from .ledger import LEDGER_FILE
from .model import OPEN, EditionModel, Env, load_book_models

SCHEMA = "trureturing-books.site.v1"
SITE_THEME = paths.THEME / "site"
MEDIA_PARTS = ("viz", "films", "slides")
MEDIA_MODULES = {"viz": "viz", "films": "film", "slides": "slides"}
COVER_WIDTH = 640  # px; 640×1024 covers are sharp on 2× screens at card size
COVER_SIZE = (640, 1024)
FORMAL_PREVIEW = 8  # verification list: items shown before "all N"
MARKER_FILES = ("manifest.json", ".nojekyll")
KATEX_CSS = "katex/katex.min.css"  # below assets/, with its fonts in assets/katex/fonts/ (write_assets)

# Interface strings this component adds to theme/i18n/<lang>.toml. Looked up as ``[site] <key>`` in
# the language's i18n table first, so merging them there (or into a downstream i18n/<lang>.toml)
# overrides these defaults. "{…}" fields are filled by :func:`t`.
SITE_I18N: dict[str, dict[str, str]] = {
    "zh": {
        "skip": "跳到正文",
        "lede": "本书库区分 Lean 内核验证、书面证明与开放问题；只有 LEAN ✓ 表示陈述同一结果的冻结声明。",
        "nav_site": "站点信息",
        "lang_group": "界面语言",
        "source": "源码",
        "books_empty": "书库里还没有书。运行 ./tbook new-book 新建一本。",
        "stat_theorems": "定理",
        "stat_open": "开放问题",
        "stat_decls": "Lean 声明",
        "stat_editions": "语言版本",
        "stat_chapters": "章节",
        "not_built": "尚未构建",
        "downloads_none": "尚无可下载的文件。",
        "read_download": "阅读与下载",
        "open_book": "进入本书",
        "authors": "作者",
        "license": "许可",
        "date": "日期",
        "verification": "形式化验证",
        "verification_intro": "以下定理都引用 trureturing 中已冻结的 Lean 声明；链接固定在所钉的提交上，不随上游漂移。",
        "ledger_link": "完整的形式化验证账本",
        "all_theorems": "全部 {n} 条定理",
        "open_none": "本书没有标为开放的条目。",
        "theorems_none": "本书还没有形式化定理。",
        "edition_missing": "本书没有该语言版本，下面显示{name}版。",
        "toc_missing": "目录不可用（SUMMARY.md 缺失或无法解析）。",
        "hub_viz": "全部可视化",
        "hub_films": "全部视频",
        "hub_slides": "全部演示文稿",
        "slides_count": "{n} 页",
        "cover_alt": "《{title}》封面",
        "on_this_page": "本页",
        "template": "由 {name} {version} 生成",
        "lost_title": "SIGNAL LOST · 404",
        "lost_text": "这个地址上没有页面。",
    },
    "en": {
        "skip": "Skip to content",
        "lede": "These books distinguish kernel-verified Lean results, written proofs and open questions. Only LEAN ✓ marks a matching frozen declaration.",
        "nav_site": "Site status",
        "lang_group": "Interface language",
        "source": "Source",
        "books_empty": "The library has no books yet. Create one with ./tbook new-book.",
        "stat_theorems": "Theorems",
        "stat_open": "Open problems",
        "stat_decls": "Lean declarations",
        "stat_editions": "Editions",
        "stat_chapters": "Chapters",
        "not_built": "not built yet",
        "downloads_none": "No downloads yet.",
        "read_download": "Read and download",
        "open_book": "Open the book",
        "authors": "Authors",
        "license": "License",
        "date": "Date",
        "verification": "Formal verification",
        "verification_intro": "Each theorem below cites a frozen Lean declaration in trureturing; the links are fixed "
                              "to the pinned commit and do not drift with upstream changes.",
        "ledger_link": "Full verification ledger",
        "all_theorems": "All {n} theorems",
        "open_none": "This book marks no item as open.",
        "theorems_none": "This book has no formal theorems yet.",
        "edition_missing": "This book has no edition in this language; showing the {name} edition.",
        "toc_missing": "Contents unavailable (SUMMARY.md missing or unreadable).",
        "hub_viz": "All visualizations",
        "hub_films": "All films",
        "hub_slides": "All slide decks",
        "slides_count": "{n} slides",
        "cover_alt": "Cover of {title}",
        "on_this_page": "On this page",
        "template": "Built with {name} {version}",
        "lost_title": "SIGNAL LOST · 404",
        "lost_text": "No page lives at this address.",
    },
}


class SiteError(RuntimeError):
    """The site could not be assembled completely."""


def t(lang: str, key: str, **fmt: Any) -> str:
    """Interface string of this component: ``[site] <key>`` of the i18n table, then :data:`SITE_I18N`."""
    table = config.i18n(lang).get("site", {}) if config.has_i18n(lang) else {}
    text = table.get(key) if isinstance(table, dict) else None
    if not isinstance(text, str):
        local = SITE_I18N.get(lang) or SITE_I18N.get(lang.split("-")[0]) or SITE_I18N["en"]
        text = local.get(key) or SITE_I18N["en"].get(key, key)
    return text.format(**fmt) if fmt else text


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _warn(message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=site::{message.replace(chr(10), '%0A')}", file=sys.stderr, flush=True)
    else:
        print(f"  site: {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- bilingual rendering


class Bi:
    """Renders text once per interface language (``data-l``), collapsing identical variants."""

    def __init__(self, langs: list[str]):
        self.langs = list(langs)

    def bcp(self, lang: str) -> str:
        return config.bcp47(lang)

    def span(self, fn: Callable[[str], str], tag: str = "span", cls: str = "") -> str:
        """``fn(lang)`` returns *escaped HTML* for one language."""
        texts = [(lang, fn(lang)) for lang in self.langs]
        klass = f' class="{cls}"' if cls else ""
        if len({x for _, x in texts}) == 1:
            return f"<{tag}{klass}>{texts[0][1]}</{tag}>" if cls or tag != "span" else texts[0][1]
        return "".join(f'<{tag}{klass} data-l="{esc(lang)}" lang="{esc(self.bcp(lang))}">{x}</{tag}>'
                       for lang, x in texts)

    def text(self, fn: Callable[[str], str], tag: str = "span", cls: str = "") -> str:
        """Like :meth:`span` for plain text (escaped here)."""
        return self.span(lambda lang: esc(fn(lang)), tag, cls)

    def s(self, key: str) -> str:
        return self.text(lambda lang: config.s(lang, key))

    def t(self, key: str, **fmt: Any) -> str:
        return self.text(lambda lang: t(lang, key, **fmt))

    def block(self, fn: Callable[[str], tuple[str, str]], tag: str = "div", cls: str = "") -> str:
        """``fn(lang)`` returns (html, content language) for one interface language."""
        parts = [(lang, *fn(lang)) for lang in self.langs]
        klass = f' class="{cls}"' if cls else ""
        if len({h for _, h, _ in parts}) == 1:
            return f'<{tag}{klass} lang="{esc(self.bcp(parts[0][2]))}">{parts[0][1]}</{tag}>'
        return "".join(f'<{tag}{klass} data-l="{esc(lang)}" lang="{esc(self.bcp(content))}">{h}</{tag}>'
                       for lang, h, content in parts)

    def each(self, fn: Callable[[str, str], str]) -> str:
        """``fn(lang, attrs)`` renders one element, inserting ``attrs`` (`` data-l="…" lang="…"`` or "")
        into its start tag; one copy without attributes when every language renders the same."""
        plain = [fn(lang, "") for lang in self.langs]
        if len(set(plain)) == 1:
            return plain[0]
        return "".join(fn(lang, f' data-l="{esc(lang)}" lang="{esc(self.bcp(lang))}"') for lang in self.langs)

    def aria(self, fn: Callable[[str], str]) -> str:
        """``aria-label`` attributes switched by site.js."""
        first = fn(self.langs[0])
        per = "".join(f' data-aria-{esc(lang)}="{esc(fn(lang))}"' for lang in self.langs)
        return f'aria-label="{esc(first)}" data-aria{per}'


def lang_style(langs: list[str]) -> str:
    """Inline CSS: hide every ``data-l`` element that is not in the current language."""
    hide = ",\n".join(f':root[data-lang="{lang}"] [data-l]:not([data-l="{lang}"])' for lang in langs)
    return f"<style>\n{hide} {{ display: none !important; }}\n</style>"


# --------------------------------------------------------------------------- small helpers


def chapter_html(path: str) -> str:
    """Published page of a chapter: ``x.md`` → ``x.html``; ``README.md`` → ``index.html`` (mdBook's index preprocessor)."""
    stem = posixpath.splitext(path)[0]
    head, base = posixpath.split(stem)
    if base.lower() == "readme":
        base = "index"
    return posixpath.join(head, base + ".html") if head else base + ".html"


def wbr(name: str) -> str:
    """Escaped dotted name with line-break opportunities after each dot (long Lean names on phones)."""
    return "<wbr>".join(esc(part) + "." for part in name.split(".")[:-1]) + "<wbr>" + esc(name.split(".")[-1]) \
        if "." in name else esc(name)


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tokens() -> dict:
    return json.loads(paths.TOKENS.read_text(encoding="utf-8"))


def _google_fonts() -> str:
    try:
        return str(_tokens().get("font", {}).get("google-fonts-css", ""))
    except (OSError, ValueError):
        return ""


def _template_info() -> tuple[str, str]:
    try:
        with paths.TEMPLATE_TOML.open("rb") as fh:
            tpl = tomllib.load(fh).get("template", {})
        return str(tpl.get("name", "")), str(tpl.get("version", ""))
    except (OSError, tomllib.TOMLDecodeError):
        return "", ""


def logo_text(site: config.Site) -> str:
    """``[site] logo`` of site.toml, else the English title as ``FIRST//REST`` (e.g. TRURETURING//BOOKS)."""
    explicit = site.raw.get("site", {}).get("logo")
    if explicit:
        return str(explicit)
    title = config.pick(site.title, "en", site.languages)
    words = title.split()
    if len(words) >= 2:
        return (words[0] + "//" + " ".join(words[1:])).upper()
    return title.upper()


def logo_html(text: str) -> str:
    """``GOLDEN//OBSERVE`` → ``GOLDEN<b>//</b><wbr>OBSERVE`` (the slashes are styled; a narrow box may break there)."""
    head, sep, tail = text.partition("//")
    return esc(head) + ("<b>//</b><wbr>" + esc(tail) if sep else "")


def _exists(base: Path, rel: str) -> bool:
    """Is the relative link ``rel`` (from ``base``) a published file or directory page?"""
    if not rel or re.match(r"^[a-z][a-z0-9+.-]*:", rel, re.I):
        return bool(rel)
    target = base / rel.split("#", 1)[0].split("?", 1)[0]
    if rel.endswith("/") or target.is_dir():
        return (target / "index.html").is_file()
    return target.is_file()


def _loc(value: Any, lang: str, fallback: list[str]) -> str:
    if isinstance(value, dict):
        table = {str(k): str(v) for k, v in value.items() if isinstance(v, (str, int, float)) and str(v)}
        return config.pick(table, lang, fallback) if table else ""
    return "" if value is None else str(value)


# --------------------------------------------------------------------------- data


@dataclass
class Download:
    kind: str  # pdf | epub
    variant: str  # screen | print | ""
    name: str
    size: int


@dataclass
class BookView:
    book: config.Book
    bdir: Path
    models: dict[str, EditionModel]
    lock: lean.Lock | None
    downloads: dict[str, list[Download]] = field(default_factory=dict)
    covers: dict[str, str] = field(default_factory=dict)  # edition lang → "cover-<lang>.png"
    built: dict[str, bool] = field(default_factory=dict)
    media: dict[str, list[dict]] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return self.book.slug

    @property
    def primary(self) -> EditionModel | None:
        return self.models.get(self.book.primary.lang)

    def verified(self) -> list[Env]:
        """Formal results of the primary edition the book shows as LEAN ✓ (every count of LEAN ✓)."""
        return render.verified_envs(self.primary.formal_envs(), self.lock) if self.primary else []

    def open_items(self) -> list[Env]:
        return [e for e in self.primary.all_envs() if e.kind in OPEN] if self.primary else []

    def declarations(self) -> list[str]:
        return sorted({g for e in self.verified() for g in e.lean})

    def chapters(self) -> int:
        model = self.primary
        return sum(1 for c in model.summary.chapters if c.depth == 0) if model and model.summary else 0

    def edition_for(self, ui_lang: str) -> str:
        """The edition shown to readers of interface language ``ui_lang``."""
        return ui_lang if ui_lang in self.book.languages else self.book.primary.lang

    def cover_for(self, ui_lang: str) -> str:
        return self.covers.get(self.edition_for(ui_lang)) or self.covers.get(self.book.primary.lang, "")


def _media_module(part: str):
    try:
        return importlib.import_module(f"tbook.{MEDIA_MODULES[part]}")
    except Exception as exc:  # noqa: BLE001 - a broken optional module must not break the site
        _warn(f"tbook.{MEDIA_MODULES[part]} cannot be imported ({exc}); skipping {part}")
        return None


def _items(part: str, book: config.Book) -> list[dict]:
    mod = _media_module(part)
    fn = getattr(mod, "items", None) if mod else None
    if fn is None:
        return []
    try:
        items = fn(book)
    except NotImplementedError:
        return []
    except Exception as exc:  # noqa: BLE001
        _warn(f"{part} items of {book.slug} unavailable: {exc}")
        return []
    return [i for i in items or [] if isinstance(i, dict)]


def collect(site: config.Site, book: config.Book, bdir: Path, lock: lean.Lock | None,
            models: dict[str, EditionModel] | None = None) -> BookView:
    """What exists for ``book`` under ``bdir`` (``<out>/<slug>``), for the pages and the manifest."""
    view = BookView(book=book, bdir=bdir, models=models if models is not None else load_book_models(book), lock=lock)
    for ed in book.editions:
        view.built[ed.lang] = (bdir / ed.lang / "index.html").is_file()
        cover = f"cover-{ed.lang}.png"
        if (bdir / cover).is_file():
            view.covers[ed.lang] = cover
        found = []
        for kind, variant in [("pdf", v) for v in config.PDF_VARIANTS] + [("epub", "")]:
            name = book.artifact(ed.lang, kind, variant)
            f = bdir / "downloads" / name
            if f.is_file():
                found.append(Download(kind, variant, name, f.stat().st_size))
        view.downloads[ed.lang] = found
    for part in MEDIA_PARTS:
        view.media[part] = [i for i in _items(part, book) if _item_published(bdir, part, i)]
    return view


def _item_published(bdir: Path, part: str, item: dict) -> bool:
    href = item.get("href")
    if isinstance(href, dict):
        return any(_exists(bdir, str(h)) for h in href.values() if h)
    if href:
        return _exists(bdir, str(href))
    return (bdir / part).is_dir()


# --------------------------------------------------------------------------- publishing steps


def _reset(out: Path) -> None:
    """Empty ``out`` — only if it is missing, empty, the default _site/, or a site built by this module."""
    if not out.exists():
        return
    if not out.is_dir():
        raise SiteError(f"{out} exists and is not a directory")
    entries = list(out.iterdir())
    if entries and out.resolve() != paths.SITE_OUT.resolve() and not any((out / m).exists() for m in MARKER_FILES):
        raise SiteError(f"refusing to replace {out}: it is not empty and was not built by ./tbook build site "
                        "(no manifest.json or .nojekyll)")
    for entry in entries:
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _remove_hidden_books(out: Path, keep: set[str]) -> list[str]:
    """Remove ``<out>/<slug>`` of every book site.toml [books].hide hides (except ``keep``); returns the slugs.

    A full build empties ``out`` first, but a media-only rebuild (``only=``) writes into the site as it is, so
    the pages of a book hidden since the last full build would stay published (and served by ./tbook serve).
    Nothing else in ``out`` is touched."""
    try:
        hidden = config.hidden_books()
    except config.ConfigError:
        return []
    removed = []
    for slug in hidden:
        target = out / slug
        if slug in keep or not (target.exists() or target.is_symlink()):
            continue
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(slug)
    return removed


def _ignore_hidden(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n.startswith(".")]


# an <iframe> / <video> / <source> start tag (quote-aware: mdBook re-serializes attributes and may leave a raw
# ">" in them)
_BOOK_PATH_TAG_RE = re.compile(r'<(?:iframe|video|source)\b(?=(?:[^>"]|"[^"]*")*\sdata-tr-(?:src|poster)=")(?:[^>"]|"[^"]*")*>', re.I)
# a film embed that plays a video of the site (tbook.film render_embed: data-tr-video): its start tag (group 1)
# and its content up to </figure> (group 2; figures do not nest)
_FILM_FIGURE_RE = re.compile(r'(<figure\b(?=(?:[^>"]|"[^"]*")*\sdata-tr-video=")(?:[^>"]|"[^"]*")*>)((?:(?!</figure\b).)*)',
                             re.I | re.S)
# the start tag of the embed's player (tbook.film _local_player)
_FILM_PLAYER_RE = re.compile(r'<video\b(?=(?:[^>"]|"[^"]*")*\sclass="[^"]*\btr-film-player\b)(?:[^>"]|"[^"]*")*>', re.I)
FILM_UNBUILT = "tr-film-unbuilt"
# preload of the player when the site hosts its video (as tbook.film writes it) and when it does not: the hidden
# player of an unbuilt film must not request the missing file
FILM_PRELOAD = {True: "metadata", False: "none"}


def fix_print_media(page_html: str, prefix: str = "../") -> str:
    """Repair media URLs in mdBook's ``<lang>/print.html``.

    print.html copies every chapter to ``<lang>/`` and rewrites ``<a href>`` and ``<img src>`` for the new
    depth, but not the ``src`` of iframes and video sources or the ``poster`` of videos, so the embeds of
    chapters in subdirectories would point above the book. Embeds carry those targets relative to the book
    (``<slug>/``) in ``data-tr-src`` / ``data-tr-poster`` (tbook.viz / tbook.film ``render_embed``);
    ``prefix`` is the path from the page to ``<slug>/``.
    """
    def repl(m: re.Match) -> str:
        tag = m.group(0)
        for data, attr in (("data-tr-src", "src"), ("data-tr-poster", "poster")):
            value = re.search(rf'\s{data}="([^"]*)"', tag)
            if value:
                url = prefix + value.group(1)
                tag = re.sub(rf'(\s{attr}=")[^"]*(")', lambda a: a.group(1) + url + a.group(2), tag, count=1)
        return tag

    return _BOOK_PATH_TAG_RE.sub(repl, page_html)


def mark_films(page_html: str, bdir: Path) -> str:
    """Mark the film embeds of a chapter page whose video the site does not host.

    A film embed (tbook.film ``render_embed``) names its video relative to the book in ``data-tr-video``; the
    chapter HTML is built (and cached) before the videos, so it always has the player. Here the figure gets
    the class ``tr-film-unbuilt`` when ``bdir`` (``<out>/<slug>``) has no such file, and loses it when it has
    one: the theme then shows the poster and "video not built" instead of a player that cannot play. The
    hidden player of such a figure gets ``preload="none"``, so the browser does not request the missing file
    either; it gets ``preload="metadata"`` back once the video is there.
    """
    def repl(m: re.Match) -> str:
        tag, content = m.group(1), m.group(2)
        video = re.search(r'\sdata-tr-video="([^"]*)"', tag).group(1)
        built = _exists(bdir, html.unescape(video))
        names = [c for c in _attr(tag, "class").split() if c != FILM_UNBUILT]
        if not built:
            names.append(FILM_UNBUILT)
        if names or _attr(tag, "class", None) is not None:
            tag = _set_attr(tag, "class", " ".join(names))
        content = _FILM_PLAYER_RE.sub(lambda v: _set_attr(v.group(0), "preload", FILM_PRELOAD[built]), content)
        return tag + content

    return _FILM_FIGURE_RE.sub(repl, page_html)


def _attr(tag: str, name: str, default: str | None = "") -> str | None:
    """The value of the double-quoted attribute ``name`` of a start tag as written (``default`` when absent)."""
    m = re.search(rf'\s{name}="([^"]*)"', tag)
    return m.group(1) if m else default


def _set_attr(tag: str, name: str, value: str) -> str:
    """The start tag with the double-quoted attribute ``name`` set to ``value`` (added before ``>`` if absent)."""
    m = re.search(rf'(\s{name}=")([^"]*)(")', tag)
    if m:
        return tag[:m.start(2)] + value + tag[m.end(2):]
    end = len(tag) - (2 if tag.endswith("/>") else 1)
    return f'{tag[:end]} {name}="{value}"{tag[end:]}'


def publish_film_marks(book: config.Book, bdir: Path) -> None:
    """Apply :func:`mark_films` to every page of the book's editions in ``bdir`` that embeds a film."""
    for ed in book.editions:
        edir = bdir / ed.lang
        if not edir.is_dir():
            continue
        for page_file in sorted(edir.rglob("*.html")):
            text = page_file.read_text(encoding="utf-8")
            if "data-tr-video=" not in text:
                continue
            marked = mark_films(text, bdir)
            if marked != text:
                page_file.write_text(marked, encoding="utf-8")


def publish_html(book: config.Book, bdir: Path, build_root: Path) -> None:
    for ed in book.editions:
        src = build_root / "html" / book.slug / ed.lang
        dst = bdir / ed.lang
        if dst.exists():
            shutil.rmtree(dst)
        if (src / "index.html").is_file():
            shutil.copytree(src, dst, ignore=_ignore_hidden)
            printed = dst / "print.html"
            if printed.is_file():
                printed.write_text(fix_print_media(printed.read_text(encoding="utf-8")), encoding="utf-8")


def publish_downloads(book: config.Book, bdir: Path, build_root: Path) -> None:
    src = build_root / "dist" / book.slug
    dst = bdir / "downloads"
    if dst.exists():
        shutil.rmtree(dst)
    if not src.is_dir():
        return
    files = [f for f in sorted(src.iterdir()) if f.is_file() and not f.name.startswith(".")]
    if not files:
        return
    dst.mkdir(parents=True)
    for f in files:
        shutil.copy2(f, dst / f.name)


def publish_covers(site: config.Site, book: config.Book, bdir: Path, models: dict[str, EditionModel],
                   lock: lean.Lock | None) -> None:
    """``cover-<lang>.png`` per edition via tbook.cover; a failure leaves the CSS cover card in place."""
    try:
        from . import cover
    except Exception as exc:  # noqa: BLE001 - optional component
        _warn(f"covers unavailable ({exc}); using CSS cover cards")
        return
    render = getattr(cover, "render_cover", None)
    if render is None:
        return
    for ed in book.editions:
        out = bdir / f"cover-{ed.lang}.png"
        try:
            try:
                render(site, book, ed, out, fmt="png", model=models.get(ed.lang), lock=lock, width_px=COVER_WIDTH)
            except TypeError:  # an implementation with only the contract signature
                render(site, book, ed, out, fmt="png")
        except NotImplementedError:
            return
        except Exception as exc:  # noqa: BLE001
            _warn(f"cover of {ed.key} failed ({exc}); using a CSS cover card")
            out.unlink(missing_ok=True)


def publish_media(site: config.Site, book: config.Book, part: str, dest: Path) -> str | None:
    """Publish one media part; returns an error message (None when fine or nothing to do)."""
    mod = _media_module(part)
    if mod is None:
        return None
    if not _items(part, book):
        if dest.exists():
            shutil.rmtree(dest)
        return None
    fn = getattr(mod, "publish", None) if part == "slides" else None
    fn = fn or getattr(mod, "build", None)
    if fn is None:
        return None
    try:
        fn(site, book, dest)
    except NotImplementedError:
        _warn(f"tbook.{MEDIA_MODULES[part]} is not implemented yet; {book.slug} has no {part} section")
        return None
    except Exception as exc:  # noqa: BLE001 - report, finish the site, then fail
        _warn(f"{part} of {book.slug} failed: {exc}")
        return f"{part} of {book.slug}: {exc}"
    return None


def write_assets(out: Path, *, katex: bool = False) -> dict[str, str]:
    """assets/ (site.css, site.js, tokens.css, favicon.svg; with ``katex``, KaTeX's stylesheet :data:`KATEX_CSS`
    and its fonts, for the formulas of theorem titles); returns cache-busting versions by path below assets/."""
    adir = out / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SITE_THEME / "site.css", adir / "site.css")
    shutil.copy2(SITE_THEME / "site.js", adir / "site.js")
    shutil.copy2(paths.GENERATED / "tokens.css", adir / "tokens.css")
    screen = _tokens().get("screen", {})
    icon = re.sub(r"@@([a-z-]+)@@", lambda m: screen.get(m.group(1), m.group(0)),
                  (SITE_THEME / "favicon.svg").read_text(encoding="utf-8"))
    (adir / "favicon.svg").write_text(icon, encoding="utf-8")
    names = ["site.css", "site.js", "tokens.css", "favicon.svg"]
    kdir = adir / posixpath.dirname(KATEX_CSS)
    if kdir.is_dir():
        shutil.rmtree(kdir)
    if katex:
        try:
            css = mathrender.katex_css()
            (kdir / "fonts").mkdir(parents=True)
            (adir / KATEX_CSS).write_text(css, encoding="utf-8")
            for font in mathrender.katex_fonts():
                shutil.copy2(font, kdir / "fonts" / font.name)
            names.append(KATEX_CSS)
        except (mathrender.MathError, OSError) as exc:
            _warn(f"KaTeX stylesheet unavailable ({exc}); theorem titles show their formulas as TeX")
            shutil.rmtree(kdir, ignore_errors=True)
    return {name: hashlib.sha256((adir / name).read_bytes()).hexdigest()[:10] for name in names}


# --------------------------------------------------------------------------- page frame


@dataclass
class Frame:
    site: config.Site
    bi: Bi
    versions: dict[str, str]
    lock: lean.Lock | None
    math: dict[str, str] = field(default_factory=dict)  # KaTeX HTML of the formulas of theorem titles, by TeX

    def asset(self, prefix: str, name: str) -> str:
        v = self.versions.get(name)
        return f"{prefix}assets/{name}" + (f"?v={v}" if v else "")


def page(frame: Frame, *, prefix: str, titles: Callable[[str], str], description: Callable[[str], str],
         body: str, og_image: str = "", canonical: str = "") -> str:
    langs = frame.bi.langs
    default = langs[0]
    meta = {lang: {"bcp47": config.bcp47(lang)} for lang in langs}
    title_attrs = "".join(f' data-title-{esc(lang)}="{esc(titles(lang))}"' for lang in langs)
    fonts = _google_fonts()
    head = [
        "<!doctype html>",
        f'<html lang="{esc(config.bcp47(default))}" data-lang="{esc(default)}" data-default-lang="{esc(default)}" '
        f'data-langs="{esc(" ".join(langs))}" data-lang-meta="{esc(json.dumps(meta, ensure_ascii=False))}"{title_attrs}>',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f"<title>{esc(titles(default))}</title>",
        f'<meta name="description" content="{esc(description(default))}">',
        '<meta name="color-scheme" content="dark">',
        '<meta name="generator" content="tbook">',
        f'<link rel="icon" href="{esc(frame.asset(prefix, "favicon.svg"))}" type="image/svg+xml">',
    ]
    if canonical:
        head.append(f'<link rel="canonical" href="{esc(canonical)}">')
    head += [
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{esc(titles(default))}">',
        f'<meta property="og:description" content="{esc(description(default))}">',
    ]
    if og_image:
        head.append(f'<meta property="og:image" content="{esc(og_image)}">')
    if fonts:
        head += ['<link rel="preconnect" href="https://fonts.googleapis.com">',
                 '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
                 f'<link rel="stylesheet" href="{esc(fonts)}">']
    head.append(f'<link rel="stylesheet" href="{esc(frame.asset(prefix, "tokens.css"))}">')
    if KATEX_CSS in frame.versions and 'class="katex"' in body:  # a page with rendered formulas
        head.append(f'<link rel="stylesheet" href="{esc(frame.asset(prefix, KATEX_CSS))}">')
    head += [
        f'<link rel="stylesheet" href="{esc(frame.asset(prefix, "site.css"))}">',
        lang_style(langs),
        f'<script src="{esc(frame.asset(prefix, "site.js"))}"></script>',
        "</head>",
        "<body>",
        f'<a class="skip" href="#main">{frame.bi.t("skip")}</a>',
        '<div class="shell">',
        body,
        "</div>",
        "</body>",
        "</html>",
    ]
    return "\n".join(head) + "\n"


def lang_switch(frame: Frame) -> str:
    langs = frame.bi.langs
    if len(langs) < 2:
        return ""
    buttons = "".join(
        f'<button type="button" data-lang-set="{esc(lang)}" aria-pressed="{"true" if i == 0 else "false"}" '
        f'lang="{esc(config.bcp47(lang))}" title="{esc(config.s(lang, "meta.name"))}">'
        f'{esc(config.s(lang, "meta.short") or lang.upper())}</button>'
        for i, lang in enumerate(langs))
    return f'<div class="langs" role="group" {frame.bi.aria(lambda lang: t(lang, "lang_group"))}>{buttons}</div>'


def footer(frame: Frame) -> str:
    bi = frame.bi
    name, version = _template_info()
    parts = [f"<span>{bi.s('ui.generated_note')}</span>"]
    right = []
    if frame.lock:
        right.append(f'<a href="{esc(frame.lock.tree_url)}" rel="noopener">trureturing@<code>{esc(frame.lock.commit[:12])}</code></a>')
    if name:
        right.append(bi.t("template", name=name, version=version))
    if frame.site.repo:
        right.append(f'<a href="https://github.com/{esc(frame.site.repo)}" rel="noopener">{bi.t("source")} ↗</a>')
    parts.append(f"<span>{' · '.join(right)}</span>")
    return f'<footer class="foot">{"".join(parts)}</footer>'


# --------------------------------------------------------------------------- fragments


def stats_html(bi: Bi, view: BookView, *, extended: bool = False) -> str:
    """Stat tiles (number above label); LEAN ✓ in green and OPEN in red only."""
    def chip(cls: str, key: str) -> str:
        return bi.span(lambda lang: esc(config.s(lang, key)), cls=f"k {cls}")

    items = [("ok", chip("ok", "badge.lean") + bi.t("stat_theorems"), len(view.verified()))]
    if extended:
        items.append(("", bi.t("stat_decls"), len(view.declarations())))
    items.append(("warn", chip("warn", "badge.open") + bi.t("stat_open"), len(view.open_items())))
    items.append(("", bi.t("stat_editions"), len(view.book.editions)))
    if extended:
        items.append(("", bi.t("stat_chapters"), view.chapters()))
    tiles = "".join(f'<div class="stat {cls}"><dt>{label}</dt><dd>{n}</dd></div>' for cls, label, n in items)
    return f'<dl class="stats">{tiles}</dl>'


def editions_html(bi: Bi, view: BookView, prefix: str) -> str:
    """One row per edition: read online + downloads (``prefix`` = path from the page to <slug>/)."""
    rows = []
    labels = {("pdf", "screen"): "ui.pdf_screen", ("pdf", "print"): "ui.pdf_print",
              ("pdf", "academic"): "ui.pdf_academic", ("epub", ""): "ui.epub"}
    for ed in view.book.editions:
        lang = ed.lang
        links = []
        if view.built.get(lang):
            links.append(f'<a class="btn solid" href="{esc(prefix + lang + "/")}" hreflang="{esc(ed.bcp47)}">'
                         f'{bi.s("ui.read_online")} <span aria-hidden="true">▸</span></a>')
        for d in view.downloads.get(lang, []):
            mime = "application/pdf" if d.kind == "pdf" else "application/epub+zip"
            dl = ' download' if d.kind == "epub" else ""
            links.append(f'<a class="chip" href="{esc(prefix + "downloads/" + d.name)}" type="{mime}" '
                         f'hreflang="{esc(ed.bcp47)}"{dl}>{bi.s(labels[(d.kind, d.variant)])} '
                         f'<small>{esc(human_size(d.size))}</small></a>')
        if not links:
            links.append(f'<span class="muted">{bi.t("not_built")}</span>')
        name = config.s(lang, "meta.name") or lang
        short = config.s(lang, "meta.short") or lang.upper()
        rows.append(
            f'<li class="ed" data-ed="{esc(lang)}">'
            f'<span class="ed-id" lang="{esc(ed.bcp47)}"><span class="ed-lang">{esc(short)}</span>'
            f'<span class="ed-name">{esc(name)}</span></span>'
            f'<span class="ed-links">{"".join(links)}</span></li>')
    return f'<ul class="eds">{"".join(rows)}</ul>'


def cover_html(bi: Bi, view: BookView, prefix: str, *, alt: bool, eager: bool = False) -> str:
    """Cover image per interface language, or the CSS-only cover card (``alt``: meaningful alt text)."""
    book = view.book
    loading = "eager" if eager else "lazy"

    def title(lang: str) -> str:
        return config.pick(book.title, view.edition_for(lang), book.languages)

    if any(view.cover_for(lang) for lang in bi.langs):
        def img(lang: str, attrs: str) -> str:
            text = t(lang, "cover_alt", title=title(lang)) if alt else ""
            return (f'<img{attrs} src="{esc(prefix + view.cover_for(lang))}" alt="{esc(text)}" '
                    f'width="{COVER_SIZE[0]}" height="{COVER_SIZE[1]}" loading="{loading}" decoding="async">')
        return bi.each(img)

    def card(lang: str, attrs: str) -> str:
        label = f' role="img" aria-label="{esc(t(lang, "cover_alt", title=title(lang)))}"' if alt else ' aria-hidden="true"'
        return (f'<span class="cover-css"{attrs}{label}>'
                f'<span class="c-code">{logo_html(book.code)}</span>'
                f'<span class="c-title" lang="{esc(config.bcp47(view.edition_for(lang)))}">{esc(title(lang))}</span>'
                f'<span class="c-stamp">{esc(config.s(lang, "badge.lean"))} {len(view.verified())}</span></span>')
    return bi.each(card)


def media_line(bi: Bi, view: BookView, prefix: str) -> str:
    """Links to the landing page's media sections, with counts (index cards)."""
    links = [f'<a class="chip" href="{esc(prefix)}#{part}">{bi.s(key)} <small>{len(view.media[part])}</small></a>'
             for part, key in (("viz", "ui.visualizations"), ("films", "ui.films"), ("slides", "ui.slides"))
             if view.media.get(part)]
    return f'<p class="media-links">{"".join(links)}</p>' if links else ""


def book_card(frame: Frame, view: BookView) -> str:
    bi, book = frame.bi, view.book
    slug = view.slug
    title = bi.text(lambda lang: config.pick(book.title, view.edition_for(lang), book.languages))
    sub = bi.text(lambda lang: config.pick(book.subtitle, view.edition_for(lang), book.languages)) if book.subtitle else ""
    desc = bi.text(lambda lang: config.pick(book.description, view.edition_for(lang), book.languages)) if book.description else ""
    hid = f"book-{slug}"
    return (
        f'<article class="book panel" aria-labelledby="{esc(hid)}">'
        f'<a class="cover-link" href="{esc(slug)}/" tabindex="-1" aria-hidden="true">{cover_html(bi, view, slug + "/", alt=False)}</a>'
        f'<div class="body">'
        f'<p class="code">{logo_html(book.code)} <span class="ver">· v{esc(book.version)}</span></p>'
        f'<h3 id="{esc(hid)}"><a href="{esc(slug)}/">{title}</a></h3>'
        + (f'<p class="subtitle">{sub}</p>' if sub else "")
        + (f'<p class="desc">{desc}</p>' if desc else "")
        + stats_html(bi, view)
        + media_line(bi, view, slug + "/")
        + editions_html(bi, view, slug + "/")
        + f'<div class="more"><a class="btn" href="{esc(slug)}/">{bi.t("open_book")} <span aria-hidden="true">▸</span></a></div>'
        + "</div></article>"
    )


# --------------------------------------------------------------------------- library hub


def index_html(frame: Frame, views: list[BookView]) -> str:
    site, bi, lock = frame.site, frame.bi, frame.lock
    logo = logo_text(site)
    total = sum(len(v.verified()) for v in views)
    pills = [f'<span class="pill">{bi.s("ui.books")} <strong>{len(views)}</strong></span>',
             f'<span class="pill ok">LEAN ✓ <strong>{total}</strong></span>']
    if lock:
        pills.append(f'<a class="pill" href="{esc(lock.tree_url)}" rel="noopener">trureturing '
                     f'<strong>@{esc(lock.commit[:12])} ↗</strong></a>')
    if site.repo:
        pills.append(f'<a class="pill" href="https://github.com/{esc(site.repo)}" rel="noopener">'
                     f'{bi.t("source")} <strong>↗</strong></a>')
    header = (
        '<header class="top">'
        f'<div class="brand"><a class="logo" href="./" data-text="{esc(logo)}">{logo_html(logo)}</a></div>'
        f'<nav class="status" {bi.aria(lambda lang: t(lang, "nav_site"))}>{"".join(pills)}{lang_switch(frame)}</nav>'
        "</header>"
    )
    legend = (
        '<ul class="legend">'
        f'<li><span class="k ok">LEAN ✓</span>{bi.s("badge.lean_title")}</li>'
        f'<li><span class="k warn">OPEN</span>{bi.s("badge.open_title")}</li>'
        + (f'<li><span class="k dim">PIN</span>{bi.s("ui.pinned_at")} <code>{esc(lock.commit[:12])}</code></li>' if lock else "")
        + "</ul>"
    )
    hero = (
        '<section class="hero panel" aria-labelledby="hero-title">'
        '<div class="hero-fx" aria-hidden="true"><div class="sun"></div><div class="horizon"></div><div class="floor"></div></div>'
        '<div class="hero-text">'
        f'<h1 id="hero-title">{bi.text(lambda lang: site.text(site.title, lang))}</h1>'
        + (f'<p class="lede">{bi.text(lambda lang: site.text(site.tagline, lang))}</p>' if site.tagline else "")
        + f'<p class="sub">{bi.t("lede")}</p>'
        + legend
        + "</div></section>"
    )
    if views:
        cards = "".join(book_card(frame, v) for v in views)
        grid = f'<div class="books">{cards}</div>'
    else:
        grid = f'<p class="note">{bi.t("books_empty")}</p>'
    library = (
        '<section aria-labelledby="library-title" class="library">'
        f'<div class="sec-head"><h2 id="library-title" class="sec-title">{bi.s("ui.books")}</h2>'
        f'<span class="aside">{len(views)} · LEAN ✓ {total}</span></div>'
        f"{grid}</section>"
    )
    body = f'{header}<main id="main" tabindex="-1">{hero}{library}</main>{footer(frame)}'
    first_cover = ""
    if views and site.base_url and views[0].covers:
        first_cover = site.base_url + views[0].slug + "/" + next(iter(views[0].covers.values()))
    return page(frame, prefix="", titles=lambda lang: site.text(site.title, lang),
                description=lambda lang: site.text(site.tagline, lang) or site.text(site.title, lang),
                body=body, og_image=first_cover, canonical=site.base_url)


# --------------------------------------------------------------------------- book landing page


def _chapter_counts(model: EditionModel, lock: lean.Lock | None) -> tuple[Counter, Counter]:
    """Per chapter: formal results shown as LEAN ✓, and open items."""
    formal, opened = Counter(), Counter()
    for doc in model.chapters:
        for env in doc.envs:
            if render.env_verified(env, lock):
                formal[doc.chapter.path] += 1
            elif env.kind in OPEN:
                opened[doc.chapter.path] += 1
    return formal, opened


def toc_html(view: BookView, ed_lang: str, ui_lang: str, math: dict[str, str] | None = None) -> str:
    model = view.models.get(ed_lang)
    if model is None or model.summary is None:
        return f'<p class="note">{esc(t(ui_lang, "toc_missing"))}</p>'
    built = view.built.get(ed_lang, False)
    root = view.bdir / ed_lang
    formal, opened = _chapter_counts(model, view.lock)

    def item(ch) -> str:
        title = f'<span class="t-title">{title_html(ch.title_md or ch.title, math)}</span>'
        tags = []
        if ch.path and formal.get(ch.path):
            tags.append(f'<span class="k ok">LEAN ✓ {formal[ch.path]}</span>')
        if ch.path and opened.get(ch.path):
            tags.append(f'<span class="k warn">OPEN {opened[ch.path]}</span>')
        tag_html = f'<span class="t-tags">{"".join(tags)}</span>' if tags else ""
        target = chapter_html(ch.path) if ch.path else ""
        if target and built and (root / target).is_file():
            inner = f'<a href="{esc(ed_lang + "/" + target)}">{title}{tag_html}</a>'
        else:
            inner = f'<span class="draft">{title}{tag_html}</span>'
        kids = "".join(item(c) for c in ch.children)
        return f"<li>{inner}" + (f"<ol>{kids}</ol>" if kids else "") + "</li>"

    out, part = [], ""
    for ch in model.summary.chapters:
        if ch.depth:
            continue
        if ch.part and ch.part != part:
            part = ch.part
            out.append(f'<li class="part" aria-hidden="true">{title_html(part, math)}</li>')
        out.append(item(ch))
    ledger_page = chapter_html(LEDGER_FILE)
    if built and (root / ledger_page).is_file():
        out.append(f'<li class="ledger"><a href="{esc(ed_lang + "/" + ledger_page)}">'
                   f'<span class="t-title">{esc(config.s(ed_lang, "ledger.title"))}</span>'
                   f'<span class="t-tags"><span class="k ok">LEAN ✓ {sum(formal.values())}</span></span></a></li>')
    note = ""
    if ed_lang != ui_lang:
        note = f'<p class="note missing">{esc(t(ui_lang, "edition_missing", name=config.s(ed_lang, "meta.name")))}</p>'
    return note + f'<ol class="toc">{"".join(out)}</ol>'


def _env_href(view: BookView, ed_lang: str, env: Env) -> str:
    if not view.built.get(ed_lang) or not env.chapter.path or not env.id:
        return ""
    page_name = chapter_html(env.chapter.path)
    if not (view.bdir / ed_lang / page_name).is_file():
        return ""
    return f"{ed_lang}/{page_name}#{env.id}"


def _listed_envs(model: EditionModel) -> list[Env]:
    """The environments the verification section lists: formal results and open items."""
    return model.formal_envs() + [e for e in model.all_envs() if e.kind in OPEN]


def _title_formulas(markdown: str) -> dict[int, mathrender.MathSpan]:
    """The formulas of a title (inline Markdown), by offset, found as everywhere else (tbook.mathrender)."""
    return {span.start: span for span in mathrender.find_math(markdown)[0]} if "$" in markdown else {}


def render_title_math(views: list[BookView]) -> dict[str, str]:
    """KaTeX HTML (inline) of every formula in the titles the landing pages list, by TeX: one Node process
    for the whole site. Empty, with a warning, when Node or KaTeX is missing; a formula KaTeX cannot render
    is left out (:func:`title_html` then shows its TeX source)."""
    titles = []
    for view in views:
        for model in view.models.values():
            titles.extend(model.title_markdown(env) for env in _listed_envs(model) if env.title)
            if model.summary:
                titles.extend(title for ch in model.summary.chapters for title in (ch.title_md or ch.title, ch.part))
    texs = list(dict.fromkeys(span.tex for title in titles for span in _title_formulas(title).values()))
    if not texs:
        return {}
    try:
        answers = mathrender.render_formulas([(tex, False) for tex in texs])
    except mathrender.MathError as exc:
        _warn(f"landing-page titles show their formulas as TeX: {exc}")
        return {}
    rendered = {tex: a["html"].replace("\n", " ") for tex, a in zip(texs, answers) if isinstance(a.get("html"), str)}
    failed = [tex for tex in texs if tex not in rendered]
    if failed:
        _warn(f"KaTeX cannot render {len(failed)} formula(s) of landing-page titles, shown as TeX: "
              + ", ".join(f"${tex}$" for tex in failed))
    return rendered


def title_html(markdown: str, math: dict[str, str] | None = None) -> str:
    """A title (inline Markdown, references resolved: :meth:`EditionModel.title_markdown`) as site HTML.

    Text reads as everywhere else (Markdown escapes undone: ``C\\*-代数`` shows ``C*-代数``, ``\\$5`` shows
    ``$5``), code spans stay as written, and each formula is its KaTeX HTML from ``math`` (built by
    :func:`render_title_math`), or its TeX source with the dollars where ``math`` has none."""
    formulas = _title_formulas(markdown)
    out, pos = [], 0
    for kind, piece in mdscan.inline_segments(markdown) if formulas or "\\" in markdown else [("text", markdown)]:
        if kind == "math":
            span = formulas.get(pos)
            rendered = (math or {}).get(span.tex) if span else None
            out.append(rendered if rendered is not None else esc(piece))
        else:
            out.append(esc(mdscan.unescape_text(piece) if kind == "text" else piece))
        pos += len(piece)
    return "".join(out)


def verification_html(view: BookView, ed_lang: str, ui_lang: str, math: dict[str, str] | None = None) -> str:
    """The verification section of a landing page; ``math``: rendered formulas of titles (:func:`render_title_math`)."""
    model = view.models.get(ed_lang)
    lock = view.lock
    if model is None:
        return ""

    def ref(env: Env) -> str:
        href = _env_href(view, ed_lang, env)
        text = esc(env.ref_text(ed_lang))
        return f'<a class="ref" href="{esc(href)}">{text}</a>' if href else f'<span class="ref">{text}</span>'

    def title(env: Env, chip: str = "") -> str:
        text = title_html(model.title_markdown(env), math) if env.title else ""  # [@id] shows its reference text
        return f'<span class="ttl">{chip}{" " if chip and text else ""}{text}</span>'

    def row(env: Env, chip: str = "") -> str:
        decls = []
        for gid in env.lean if env.status != "written-proof" else []:
            lv = render.lean_view(gid, lock)  # a link only where the lock resolves the declaration
            code = f"<code>{wbr(lv['name'] or gid)}</code>"
            decls.append(f'<a href="{esc(lv["url"])}" rel="noopener" title="{esc(gid)}">{code}</a>'
                         if lv["url"] else code)
        if env.status == "written-proof":
            decls.append(render.source_html(render.source_view(env)))
        return f"<li>{ref(env)}{title(env, chip)}" + (f'<span class="decls">{"".join(decls)}</span>' if decls else "") + "</li>"

    formal = render.verified_envs(model.formal_envs(), lock)
    out = [f'<p class="note">{esc(t(ui_lang, "verification_intro"))}</p>']
    if formal:
        head, rest = formal[:FORMAL_PREVIEW], formal[FORMAL_PREVIEW:]
        if len(formal) <= FORMAL_PREVIEW + 2:
            head, rest = formal, []
        out.append(f'<ul class="vlist lean">{"".join(row(e) for e in head)}</ul>')
        if rest:
            out.append(f'<details class="more-items"><summary>{esc(t(ui_lang, "all_theorems", n=len(formal)))}</summary>'
                       f'<ul class="vlist lean">{"".join(row(e) for e in rest)}</ul></details>')
    else:
        out.append(f'<p class="note">{esc(t(ui_lang, "theorems_none"))}</p>')
    # Formal results the lock does not back (./tbook check rejects them): red, never in the green list.
    unverified = [e for e in model.formal_envs() if e.status != "written-proof" and not any(e is v for v in formal)]
    if unverified:
        text, tip = render.unverified_badge(ui_lang)
        chip = f'<span class="k warn" title="{esc(tip)}">{esc(text)}</span>'
        out.append(f'<ul class="vlist open">{"".join(row(e, chip) for e in unverified)}</ul>')
    written = [e for e in model.formal_envs() if e.status == "written-proof"]
    if written:
        out.append(f'<h3>{esc(config.s(ui_lang, "ledger.written_title"))}</h3>')
        chip = (f'<span class="k written-proof" title="{esc(config.s(ui_lang, "badge.written_proof_title"))}">'
                f'{esc(config.s(ui_lang, "badge.written_proof"))}</span>')
        out.append(f'<ul class="vlist written-proof">{"".join(row(e, chip) for e in written)}</ul>')
    out.append(f'<h3>{esc(config.s(ui_lang, "ledger.open_title"))}</h3>')
    opened = [e for e in model.all_envs() if e.kind in OPEN]
    if opened:
        out.append('<ul class="vlist open">' + "".join(f"<li>{ref(e)}{title(e)}</li>" for e in opened) + "</ul>")
    else:
        out.append(f'<p class="note">{esc(t(ui_lang, "open_none"))}</p>')
    ledger_page = chapter_html(LEDGER_FILE)
    if view.built.get(ed_lang) and (view.bdir / ed_lang / ledger_page).is_file():
        out.append(f'<p><a class="btn" href="{esc(ed_lang + "/" + ledger_page)}">{esc(t(ui_lang, "ledger_link"))} '
                   f'<span aria-hidden="true">▸</span></a></p>')
    return "".join(out)


def _lean_chips(refs: list) -> str:
    """Lean citations of a media item: green LEAN ✓ only for ``kind == "theorem"``, a plain LEAN link otherwise."""
    chips = []
    for r in refs or []:
        if not isinstance(r, dict):
            continue
        label = str(r.get("label") or r.get("short") or r.get("name") or r.get("gid") or "")
        url = str(r.get("url") or r.get("href") or "")
        if not label:
            continue
        code = f"<code>{esc(label)}</code>"
        chip = '<span class="k ok">LEAN ✓</span>' if r.get("kind") in lean.FORMAL_KINDS else '<span class="k dim">LEAN</span>'
        chips.append(f"<span>{chip} "
                     + (f'<a href="{esc(url)}" rel="noopener">{code}</a>' if url else code) + "</span>")
    return f'<div class="refs">{"".join(chips)}</div>' if chips else ""


def viz_section(bi: Bi, view: BookView) -> str:
    items = view.media.get("viz") or []
    if not items:
        return ""
    langs = view.book.languages
    cards = []
    for it in items:
        href = str(it.get("href") or "")
        thumb = str(it.get("thumb") or "")
        img = (f'<img src="{esc(thumb)}" alt="" loading="lazy" decoding="async" width="1280" height="720">'
               if thumb and _exists(view.bdir, thumb) else "")
        code = esc(it.get("code") or it.get("id") or "")
        title = bi.text(lambda lang: _loc(it.get("title"), lang, langs))
        summary = bi.text(lambda lang: _loc(it.get("summary"), lang, langs))
        cards.append(
            '<article class="mcard panel">'
            f'<a class="thumb{"" if img else " blank"}" href="{esc(href)}" tabindex="-1" aria-hidden="true">{img}<span class="code">{code}</span></a>'
            f'<div class="body"><h3><a href="{esc(href)}">{title}</a></h3>'
            f'<p class="sum">{summary}</p>{_lean_chips(it.get("lean"))}'
            f'<div class="actions"><a class="btn" href="{esc(href)}">{bi.s("ui.open_fullscreen")} <span aria-hidden="true">▸</span></a></div>'
            "</div></article>")
    hub = str(items[0].get("hub") or "viz/")
    more = (f'<a class="aside" href="{esc(hub)}">{bi.t("hub_viz")} ▸</a>' if _exists(view.bdir, hub) else "")
    return (f'<section id="viz" class="sec panel{_wide(items)}" aria-labelledby="viz-title">'
            f'<div class="sec-head"><h2 id="viz-title">{bi.s("ui.visualizations")}</h2>{more}</div>'
            f'<div class="mgrid">{"".join(cards)}</div></section>')


def films_section(bi: Bi, view: BookView) -> str:
    """Film cards: poster, title, duration; the page on the site (``href``) and the video (``watch_url``).

    A video on the site (a relative ``watch_url``) that the build did not publish gets the item's ``note``
    ("video not built") instead of a Watch button, as does an item with ``published`` False."""
    items = view.media.get("films") or []
    if not items:
        return ""
    langs = view.book.languages
    cards = []
    for it in items:
        page_link = _loc(it.get("href"), bi.langs[0], langs)
        page_link = page_link if page_link and _exists(view.bdir, page_link) else ""
        poster = str(it.get("poster") or it.get("thumb") or "")
        img = (f'<img src="{esc(poster)}" alt="" loading="lazy" decoding="async" width="1280" height="720">'
               if poster and _exists(view.bdir, poster) else "")

        # a film with a video of its own never falls back to its page: without the video (not published, or not
        # built into this site) it gets the note instead of a Watch button
        own_video = it.get("published") is False or bool(it.get("watch_url"))

        def watch_link(lang: str) -> str:
            url = _loc(it.get("watch_url") or it.get("url"), lang, langs)
            if url and not _exists(view.bdir, url):
                url = ""
            return url or ("" if own_video else page_link)

        title = bi.text(lambda lang: _loc(it.get("title"), lang, langs) or str(it.get("id", "")))
        heading = f'<a href="{esc(page_link)}">{title}</a>' if page_link else title
        summary = _loc(it.get("summary") or it.get("blurb") or it.get("description"), bi.langs[0], langs)
        summary_html = (f'<p class="sum">{bi.text(lambda lang: _loc(it.get("summary") or it.get("blurb") or it.get("description"), lang, langs))}</p>'
                        if summary else "")
        meta = " · ".join(esc(str(it.get(k))) for k in ("duration", "released") if it.get(k))
        def action(lang: str) -> str:
            if watch_link(lang):
                return (f'<a class="btn" href="{esc(watch_link(lang))}" rel="noopener">'
                        f'{esc(config.s(lang, "ui.watch"))} <span aria-hidden="true">▸</span></a>')
            note = _loc(it.get("note"), lang, langs)  # e.g. "video not built"
            return f'<span class="muted">{esc(note)}</span>' if note else ""

        watch = bi.span(action)
        thumb_target = page_link or watch_link(bi.langs[0])
        cards.append(
            '<article class="mcard panel">'
            + (f'<a class="thumb{"" if img else " blank"}" href="{esc(thumb_target)}" tabindex="-1" aria-hidden="true">{img}'
               f'<span class="code">{esc(it.get("code") or it.get("id") or "")}</span></a>' if thumb_target else "")
            + f'<div class="body"><h3>{heading}</h3>{summary_html}'
            + (f'<span class="meta-line">{meta}</span>' if meta else "")
            + f'{_lean_chips(it.get("lean"))}<div class="actions">{watch}</div></div></article>')
    hub = str(items[0].get("hub") or "films/")
    more = f'<a class="aside" href="{esc(hub)}">{bi.t("hub_films")} ▸</a>' if _exists(view.bdir, hub) else ""
    return (f'<section id="films" class="sec panel{_wide(items)}" aria-labelledby="films-title">'
            f'<div class="sec-head"><h2 id="films-title">{bi.s("ui.films")}</h2>{more}</div>'
            f'<div class="mgrid">{"".join(cards)}</div></section>')


def slides_section(bi: Bi, view: BookView) -> str:
    """Deck cards: title, blurb, slide count; per deck language a row with the deck and its PDF."""
    items = view.media.get("slides") or []
    if not items:
        return ""
    langs = view.book.languages
    cards = []
    for it in items:
        deck_langs = [lang for lang in (it.get("languages") or langs) if isinstance(lang, str)]
        hrefs = it.get("href") if isinstance(it.get("href"), dict) else {}
        pdfs = it.get("pdf") if isinstance(it.get("pdf"), dict) else {}
        title = bi.text(lambda lang: _loc(it.get("title"), lang, deck_langs) or str(it.get("id", "")))
        blurb = bi.text(lambda lang: _loc(it.get("blurb") or it.get("info") or it.get("summary"), lang, deck_langs))
        rows = []
        for lang in deck_langs:
            links = []
            h = str(hrefs.get(lang) or "")
            if h and _exists(view.bdir, h):
                links.append(f'<a class="btn" href="{esc(h)}" hreflang="{esc(config.bcp47(lang))}" lang="{esc(config.bcp47(lang))}">'
                             f'{esc(config.s(lang, "meta.name") or lang)} <span aria-hidden="true">▸</span></a>')
            p = str(pdfs.get(lang) or "")
            if p and _exists(view.bdir, p):
                size = human_size((view.bdir / p).stat().st_size)
                links.append(f'<a class="chip" href="{esc(p)}" type="application/pdf" hreflang="{esc(config.bcp47(lang))}">'
                             f'PDF <small>{esc(size)}</small></a>')
            notes = str(it.get("notes_pdf", {}).get(lang) or "")
            if notes and _exists(view.bdir, notes):
                from . import slides
                links.append(f'<a class="chip" href="{esc(notes)}" type="application/pdf">{esc(slides.t(lang, "notes_pdf"))}</a>')
            if links:
                rows.append(f'<div class="deck-row" data-ed="{esc(lang)}">{"".join(links)}</div>')
        count = it.get("slides")
        meta = f'<span class="meta-line">{bi.t("slides_count", n=count)}</span>' if isinstance(count, int) and count else ""
        first = next((str(hrefs.get(lang)) for lang in deck_langs if hrefs.get(lang)), "")
        heading = f'<a href="{esc(first)}">{title}</a>' if first and _exists(view.bdir, first) else title
        cards.append('<article class="mcard panel"><div class="body">'
                     f'<h3>{heading}</h3><p class="sum">{blurb}</p>{meta}'
                     f'<div class="decks">{"".join(rows)}</div></div></article>')
    hub = str(items[0].get("index") or "slides/")
    more = f'<a class="aside" href="{esc(hub)}">{bi.t("hub_slides")} ▸</a>' if _exists(view.bdir, hub) else ""
    return (f'<section id="slides" class="sec panel{_wide(items)}" aria-labelledby="slides-title">'
            f'<div class="sec-head"><h2 id="slides-title">{bi.s("ui.slides")}</h2>{more}</div>'
            f'<div class="mgrid">{"".join(cards)}</div></section>')


def _wide(items: list) -> str:
    """Media sections share a row; one with many items gets the full width."""
    return " wide" if len(items) >= 3 else ""


def landing_html(frame: Frame, view: BookView) -> str:
    site, bi, lock, book = frame.site, frame.bi, frame.lock, view.book
    langs = book.languages

    def ed_text(value) -> Callable[[str], str]:
        return lambda lang: config.pick(value, view.edition_for(lang), langs)

    pills = [f'<span class="pill">v<strong>{esc(book.version)}</strong></span>',
             f'<span class="pill ok">LEAN ✓ <strong>{len(view.verified())}</strong></span>']
    if view.open_items():
        pills.append(f'<span class="pill warn">OPEN <strong>{len(view.open_items())}</strong></span>')
    header = (
        '<header class="top">'
        f'<div class="brand"><a class="crumb" href="../"><span aria-hidden="true">◂ </span>{bi.s("ui.back_to_library")}</a>'
        f'<p class="logo" data-text="{esc(book.code)}">{logo_html(book.code)}</p></div>'
        f'<nav class="status" {bi.aria(lambda lang: t(lang, "nav_site"))}>{"".join(pills)}{lang_switch(frame)}</nav>'
        "</header>"
    )
    facts = []
    if book.authors:
        facts.append((bi.t("authors"), esc(", ".join(book.authors))))
    facts.append((bi.s("ui.version"), f"<code>{esc(book.version)}</code>"))
    if book.license:
        facts.append((bi.t("license"), esc(book.license)))
    if book.date:
        facts.append((bi.t("date"), f"<code>{esc(book.date)}</code>"))
    facts.append((bi.s("ui.language"), " · ".join(
        f'<span lang="{esc(ed.bcp47)}">{esc(config.s(ed.lang, "meta.name") or ed.lang)}</span>' for ed in book.editions)))
    if lock:
        facts.append(("trureturing", f'<a href="{esc(lock.tree_url)}" rel="noopener"><code>{esc(lock.commit[:12])}</code></a>'))
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    sections = [("contents", bi.s("ui.contents")), ("verification", bi.t("verification"))]
    for part, key in (("viz", "ui.visualizations"), ("films", "ui.films"), ("slides", "ui.slides")):
        if view.media.get(part):
            sections.append((part, bi.s(key)))
    jump = (f'<nav {bi.aria(lambda lang: t(lang, "on_this_page"))}><ul class="jump">'
            + f'<li><a href="#downloads">{bi.t("read_download")}</a></li>'
            + "".join(f'<li><a href="#{sid}">{label}</a></li>' for sid, label in sections)
            + "</ul></nav>")

    hero = (
        '<section class="book-hero panel" aria-labelledby="book-title">'
        f'<figure class="cover">{cover_html(bi, view, "", alt=True, eager=True)}</figure>'
        '<div class="meta">'
        f'<p class="kicker">{logo_html(book.code)} <span class="ver">· v{esc(book.version)}</span></p>'
        f'<h1 id="book-title">{bi.text(ed_text(book.title))}</h1>'
        + (f'<p class="subtitle">{bi.text(ed_text(book.subtitle))}</p>' if book.subtitle else "")
        + (f'<p class="desc">{bi.text(ed_text(book.description))}</p>' if book.description else "")
        + stats_html(bi, view, extended=True)
        + f'<dl class="facts">{facts_html}</dl>'
        + f'<div id="downloads" class="downloads"><h2 class="sr-only">{bi.t("read_download")}</h2>'
        + editions_html(bi, view, "")
        + (f'<p class="note">{bi.t("downloads_none")}</p>'
           if any(view.built.values()) and not any(view.downloads.values()) else "")
        + "</div>"
        + jump
        + "</div></section>"
    )
    contents = (
        '<section id="contents" class="sec panel" aria-labelledby="contents-title">'
        f'<div class="sec-head"><h2 id="contents-title">{bi.s("ui.contents")}</h2>'
        f'<span class="aside">{view.chapters()} · {bi.t("stat_chapters")}</span></div>'
        + bi.block(lambda lang: (toc_html(view, view.edition_for(lang), lang, frame.math), view.edition_for(lang)))
        + "</section>"
    )
    pin = ""
    if lock:
        pin = (f'<p class="pin">{bi.s("ui.pinned_at")} <a href="{esc(lock.tree_url)}" rel="noopener">'
               f'<code>{esc(lock.commit[:12])}</code></a> · <code>{esc(lock.repo)}</code></p>')
    verification = (
        '<section id="verification" class="sec panel" aria-labelledby="verification-title">'
        f'<div class="sec-head"><h2 id="verification-title">{bi.t("verification")}</h2>'
        f'<span class="aside">LEAN ✓ {len(view.verified())} · OPEN {len(view.open_items())}</span></div>'
        + pin
        + bi.block(lambda lang: (verification_html(view, view.edition_for(lang), lang, frame.math), view.edition_for(lang)))
        + "</section>"
    )
    media = viz_section(bi, view) + films_section(bi, view) + slides_section(bi, view)
    media = f'<div class="media">{media}</div>' if media else ""
    body = (f'{header}<main id="main" tabindex="-1">{hero}<div class="cols">{contents}{verification}</div>'
            f'{media}</main>{footer(frame)}')
    og = ""
    if site.base_url and view.covers:
        og = site.book_url(book.slug, view.covers.get(book.primary.lang) or next(iter(view.covers.values())))
    site_title = lambda lang: site.text(site.title, lang)  # noqa: E731
    return page(frame, prefix="../",
                titles=lambda lang: f"{ed_text(book.title)(lang)} · {site_title(lang)}",
                description=lambda lang: ed_text(book.description)(lang) or ed_text(book.subtitle)(lang),
                body=body, og_image=og, canonical=site.book_url(book.slug) + "/" if site.base_url else "")


# --------------------------------------------------------------------------- 404 and manifest


def not_found_html(site: config.Site) -> str:
    """Self-contained 404 (GitHub Pages serves it at any depth, so it loads no relative assets)."""
    from .serve import base_path

    langs = site.languages
    base = base_path(site)
    tokens_css = (paths.GENERATED / "tokens.css").read_text(encoding="utf-8")
    texts = "".join(f'<p lang="{esc(config.bcp47(lang))}">{esc(t(lang, "lost_text"))}</p>' for lang in langs)
    home = " · ".join(esc(config.s(lang, "ui.back_to_library")) for lang in langs)
    guess = "" if base != "/" else (
        "\n  // Base path unknown at build time: a project site lives under /<repo>/ on github.io.\n"
        "  if (/\\.github\\.io$/.test(location.hostname) && !/^[^.]+\\.github\\.io$/.test(location.pathname.split('/')[1] || '')) {\n"
        "    var seg = location.pathname.split('/').filter(Boolean)[0];\n"
        "    document.getElementById('home').href = seg ? '/' + seg + '/' : '/';\n  }")
    return f"""<!doctype html>
<html lang="{esc(config.bcp47(langs[0]))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>{esc(t(langs[0], "lost_title"))}</title>
<style>
/* tokens.css (theme/generated, from theme/tokens.json) inlined: this page loads no relative assets. */
{tokens_css}
html, body {{ height: 100%; margin: 0; }}
body {{
  background-color: var(--tr-void); background-image: var(--tr-fx-scanlines), var(--tr-fx-aurora);
  color: var(--tr-ink); display: grid; place-items: center; padding: 16px; box-sizing: border-box;
  font-family: var(--tr-font-data);
}}
main {{ max-width: 580px; width: 100%; box-sizing: border-box; border: 1px solid var(--tr-panel-edge); padding: 26px 28px;
  background: var(--tr-panel); clip-path: var(--tr-fx-cut-corner); }}
h1 {{ margin: 0 0 10px; font-family: var(--tr-font-display); font-size: clamp(24px, 6vw, 32px); letter-spacing: 0.1em;
  color: var(--tr-cyan); text-shadow: var(--tr-fx-glow-cyan); }}
p {{ margin: 0 0 8px; color: var(--tr-dim); line-height: 1.6; font-family: var(--tr-font-body); }}
code {{ display: block; margin: 10px 0 18px; color: var(--tr-amber); overflow-wrap: anywhere; }}
a {{ color: var(--tr-on-accent); background: var(--tr-cyan); padding: 7px 14px; text-decoration: none; display: inline-block;
  letter-spacing: 0.06em; font-family: var(--tr-font-display); font-weight: 600; }}
a:hover {{ box-shadow: var(--tr-fx-glow-cyan-strong); }}
a:focus-visible {{ outline: 2px solid var(--tr-amber); outline-offset: 3px; }}
</style>
</head>
<body>
<main>
  <h1>{esc(t(langs[0], "lost_title"))}</h1>
  {texts}
  <code id="path"></code>
  <a id="home" href="{esc(base)}">{home}</a>
</main>
<script>
  document.getElementById('path').textContent = location.pathname;{guess}
</script>
</body>
</html>
"""


def _generated_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    when = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch and epoch.isdigit() else datetime.now(timezone.utc)
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def manifest(site: config.Site, views: list[BookView], lock: lean.Lock | None) -> dict:
    """``manifest.json`` (schema ``trureturing-books.site.v1``)."""
    name, version = _template_info()
    books = []
    for v in views:
        book = v.book
        files = []
        for ed in book.editions:
            for d in v.downloads.get(ed.lang, []):
                f = v.bdir / "downloads" / d.name
                files.append({"path": f"{book.slug}/downloads/{d.name}", "size": d.size, "sha256": _sha256(f),
                              "kind": d.kind, "lang": ed.lang, "variant": d.variant or None})
            cover = v.covers.get(ed.lang)
            if cover:
                f = v.bdir / cover
                files.append({"path": f"{book.slug}/{cover}", "size": f.stat().st_size, "sha256": _sha256(f),
                              "kind": "cover", "lang": ed.lang, "variant": "screen"})
        for it in v.media.get("slides", []):
            pdfs = it.get("pdf") if isinstance(it.get("pdf"), dict) else {}
            pdfs = dict(pdfs)
            for lang, rel in sorted(it.get("notes_pdf", {}).items()):
                f = v.bdir / str(rel)
                if f.is_file():
                    files.append({"path": f"{book.slug}/{rel}", "size": f.stat().st_size, "sha256": _sha256(f),
                                  "kind": "slides-notes-pdf", "lang": lang, "variant": str(it.get("id", "")) or None})
            for lang, rel in sorted(pdfs.items()):
                f = v.bdir / str(rel)
                if f.is_file():
                    files.append({"path": f"{book.slug}/{rel}", "size": f.stat().st_size, "sha256": _sha256(f),
                                  "kind": "slides-pdf", "lang": lang, "variant": str(it.get("id", "")) or None})
        books.append({
            "slug": book.slug,
            "version": book.version,
            "code": book.code,
            "title": {ed.lang: ed.title for ed in book.editions},
            "editions": [{"lang": ed.lang, "bcp47": ed.bcp47, "primary": ed.primary,
                          "html": f"{book.slug}/{ed.lang}/" if v.built.get(ed.lang) else None}
                         for ed in book.editions],
            "landing": f"{book.slug}/",
            "verified": len(v.verified()),
            "open": len(v.open_items()),
            "declarations": v.declarations(),
            "media": {part: [str(i.get("id", "")) for i in v.media.get(part, [])] for part in MEDIA_PARTS},
            "files": files,
        })
    from . import requests
    return {
        "schema": SCHEMA,
        "generated_at": _generated_at(),
        "site": {"title": {lang: site.text(site.title, lang) for lang in site.languages},
                 "languages": site.languages, "base_url": site.base_url or None, "repo": site.repo or None},
        "template": {"name": name or None, "version": version or None},
        "trureturing": {"repo": lock.repo, "commit": lock.commit, "branch": lock.branch or None} if lock else None,
        "books": books,
        "formalization_requests": requests.collect(m for view in views for m in view.models.values()),
    }


# --------------------------------------------------------------------------- entry point


def _load_lock() -> lean.Lock | None:
    try:
        return lean.Lock.load()
    except lean.LeanError as exc:
        _warn(f"trureturing.lock.json unreadable ({exc}); pages omit the pinned commit")
        return None


def _site_books(books: list[config.Book], out: Path) -> list[config.Book]:
    """The books of a media-only rebuild's pages: ``books`` plus every other configured book already
    published in ``out`` (``<out>/<slug>/``), in site order, so the hub and manifest keep listing them."""
    try:
        configured = config.load_books()
    except config.ConfigError as exc:
        _warn(f"cannot list the configured books ({exc}); the hub lists only the rebuilt ones")
        configured = []
    selected = {b.slug: b for b in books}
    ordered = []
    for b in configured:
        if b.slug in selected:
            ordered.append(selected.pop(b.slug))
        elif (out / b.slug).is_dir():
            ordered.append(b)
    return ordered + list(selected.values())


def post_build(site: config.Site, out: Path) -> None:
    """Run an explicitly configured repository command after successful assembly."""
    command = site.raw.get("site", {}).get("post_build")
    if command is not None:
        if not isinstance(command, list) or not command or not all(isinstance(a, str) and a for a in command):
            raise SiteError("site.post_build must be a nonempty array of command arguments")
        env = dict(os.environ, TBOOK_SITE_OUT=str(out.resolve()))
        try:
            subprocess.run(command, cwd=site.root, env=env, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SiteError(f"site.post_build failed: {exc}") from exc


def build(site, books, out_dir: Path, only: set[str] | None = None, *, build_root: Path | None = None) -> Path:
    """Assemble the site into ``out_dir`` and return it (see the module docstring).

    ``only`` ⊆ {"viz", "films", "slides"} republishes those parts of ``books`` into an existing site; the
    hub, landing pages and manifest are then regenerated for every configured book present in ``out_dir``,
    not only ``books``. ``build_root`` overrides ``build/`` (tests).
    """
    out = Path(out_dir)
    build_root = Path(build_root) if build_root else paths.BUILD
    parts = set(only) if only else None
    if parts is not None:
        unknown = parts - set(MEDIA_PARTS)
        if unknown:
            raise SiteError(f"only= accepts {', '.join(MEDIA_PARTS)}; got {', '.join(sorted(unknown))}")
    lock = _load_lock()
    if parts is None:
        _reset(out)
    out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    views: list[BookView] = []
    rebuilt = {b.slug for b in books}
    removed = _remove_hidden_books(out, rebuilt)
    if removed:
        _warn(f"removed the pages of {', '.join(removed)} (hidden by site.toml [books].hide)")
    for book in books if parts is None else _site_books(list(books), out):
        bdir = out / book.slug
        bdir.mkdir(parents=True, exist_ok=True)
        models = load_book_models(book)
        if parts is None:
            publish_html(book, bdir, build_root)
            publish_downloads(book, bdir, build_root)
            publish_covers(site, book, bdir, models, lock)
        for part in MEDIA_PARTS:
            if book.slug in rebuilt and (parts is None or part in parts):
                err = publish_media(site, book, part, bdir / part)
                if err:
                    problems.append(err)
        if book.slug in rebuilt and (parts is None or "films" in parts):
            publish_film_marks(book, bdir)
        views.append(collect(site, book, bdir, lock, models))
    langs = list(site.languages) or ["zh", "en"]
    math = render_title_math(views)
    versions = write_assets(out, katex=bool(math))
    frame = Frame(site=site, bi=Bi(langs), versions=versions, lock=lock,
                  math=math if KATEX_CSS in versions else {})  # no stylesheet: the formulas stay TeX
    for v in views:
        (v.bdir / "index.html").write_text(landing_html(frame, v), encoding="utf-8")
    (out / "index.html").write_text(index_html(frame, views), encoding="utf-8")
    (out / "404.html").write_text(not_found_html(site), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest(site, views, lock), ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    if problems:
        raise SiteError(f"site written to {out} with {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    post_build(site, out)
    return out
