"""HTML edition via mdBook: stage an mdBook project for one edition, pre-render math, build.

:func:`build_edition` (the contract in docs/ARCHITECTURE.md §7) does four things:

1. **Stage** ``build/stage/<slug>/<lang>/mdbook/`` (wiped first)::

       book.toml            [book] + [output.html] (theme, repository, edit links, site-url,
                            print, search, fold, additional CSS/JS)
       theme/head.hbs       Google Fonts link (URL from theme/tokens.json) + colour scheme
       theme/favicon.svg    neon mark, colours from theme/tokens.json
       tr/                  additional CSS/JS (hashed by mdBook): tokens.css, the paper
                            palette re-scoped to mdBook's light themes, tr-book.css,
                            KaTeX CSS, tr-editions.js (generated), tr-book.js
       src/SUMMARY.md       regenerated from the edition's SUMMARY (same structure) with the
                            verification ledger appended as the last suffix chapter
       title-math.md        title fragments rendered with the chapters (not published)
       src/<chapter>.md     tbook.render.chapter_markdown(target="mdbook"), math pre-rendered
       src/verification-ledger.md
       src/404.md           localized "page not found"
       src/<asset>          non-Markdown files of the edition directory, same paths
       src/_book/<path>     files of the book directory that chapters link to (../assets/…)
       src/tr/katex/fonts/  KaTeX fonts (served next to the hashed KaTeX stylesheet)

2. **Math**: every ``$…$`` / ``$$…$$`` of the staged Markdown is rendered by KaTeX in one
   Node process (:mod:`tbook.mathrender`); nothing is rendered in the browser.

3. **Build**: ``mdbook build -d <out_dir>`` with the mdBook binary from ``$MDBOOK`` or
   ``PATH`` (0.5.x). mdBook writes "Suggest an edit" links as ``…/<edition dir>/src/<chapter>.md``;
   :func:`fix_edit_links` drops the staged ``src/`` (and the link of the generated ledger), and
   :func:`restore_title_math` restores pre-rendered title math in the TOCs and menu title;
   :func:`tbook.site.fix_print_media` points the iframes and video posters of ``print.html`` at
   their targets (mdBook rewrites only links and images there for nested chapters).

4. **Search**: mdBook's index splits words on whitespace only, so Chinese text is one
   unsearchable "word" per sentence; :func:`augment_search_index` adds CJK character
   uni-/bigrams and ``tr-book.js`` tokenizes queries the same way.

The published layout is ``_site/<slug>/<lang>/<chapter>.html``; ``tr-book.js`` uses it for the
language switcher (``../<other-lang>/<same path>``) and the link to the book's landing page
(``../``). Warnings (unresolved references, links leaving the book, KaTeX fallbacks) go to
stderr — as GitHub annotations under GitHub Actions — and never stop the build; a missing
tool, an unparseable SUMMARY or a failing mdBook run raise :class:`HtmlError`.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import config, ledger, mathrender, mdscan, paths, render
from .model import EditionModel, load_edition

MDBOOK_THEME = paths.THEME / "mdbook"
KATEX_DIST = mathrender.KATEX_DIST
ASSET_DIR = "tr"  # staged next to src/; published as <edition>/tr/
DEFAULT_BRANCH = "main"
MDBOOK_SERIES = (0, 5)

# Interface strings this component needs that are not (yet) in theme/i18n/<lang>.toml.
# Looked up in the language's own table as ``[html] <key>`` first, so merging them into the
# shared tables (or a downstream i18n/<lang>.toml) overrides these defaults. "[x]" marks a
# key cap (<kbd>) in the help texts; "{name}", "{n}", "{q}" are substituted by tr-book.js.
LOCAL_I18N: dict[str, dict[str, str]] = {
    "zh": {
        "book_home": "本书主页",
        "editions": "语言版本",
        "read_in": "{name} 版",
        "verified_link": "查看形式化验证账本",
        "toggle_toc": "显示/隐藏目录",
        "change_theme": "切换配色",
        "search": "搜索（/）",
        "search_placeholder": "搜索本书……",
        "print": "打印本书",
        "repository": "Git 仓库",
        "edit": "建议修改",
        "prev": "上一章",
        "next": "下一章",
        "help_title": "键盘快捷键",
        "help_nav": "按 [←] 或 [→] 在章节间跳转",
        "help_search": "按 [S] 或 [/] 搜索本书",
        "help_help": "按 [?] 显示本帮助",
        "help_esc": "按 [Esc] 关闭本帮助",
        "search_one": "找到 1 条与“{q}”相关的结果：",
        "search_many": "找到 {n} 条与“{q}”相关的结果：",
        "search_none": "没有与“{q}”相关的结果。",
        "theme_auto": "跟随默认",
        "theme_light": "纸面",
        "theme_rust": "暖纸",
        "theme_coal": "静夜",
        "theme_navy": "霓虹",
        "theme_ayu": "深空",
        "alert_note": "注",
        "alert_tip": "提示",
        "alert_important": "重要",
        "alert_warning": "警告",
        "alert_caution": "当心",
        "not_found_title": "页面不存在（404）",
        "not_found_body": "这个地址没有对应的页面。请用目录或搜索继续阅读，或回到[本书主页](../)。",
    },
    "en": {
        "book_home": "Book home",
        "editions": "Editions",
        "read_in": "Read in {name}",
        "verified_link": "Open the verification ledger",
        "toggle_toc": "Toggle table of contents",
        "change_theme": "Change theme",
        "search": "Search (/)",
        "search_placeholder": "Search this book…",
        "print": "Print this book",
        "repository": "Git repository",
        "edit": "Suggest an edit",
        "prev": "Previous chapter",
        "next": "Next chapter",
        "help_title": "Keyboard shortcuts",
        "help_nav": "Press [←] or [→] to move between chapters",
        "help_search": "Press [S] or [/] to search the book",
        "help_help": "Press [?] to show this help",
        "help_esc": "Press [Esc] to hide this help",
        "search_one": "1 result for “{q}”:",
        "search_many": "{n} results for “{q}”:",
        "search_none": "No results for “{q}”.",
        "theme_auto": "Default",
        "theme_light": "Paper",
        "theme_rust": "Warm paper",
        "theme_coal": "Quiet night",
        "theme_navy": "Neon",
        "theme_ayu": "Deep space",
        "alert_note": "Note",
        "alert_tip": "Tip",
        "alert_important": "Important",
        "alert_warning": "Warning",
        "alert_caution": "Caution",
        "not_found_title": "Page not found (404)",
        "not_found_body": "There is no page at this address. Use the table of contents or search to continue reading, or go back to the [book's home page](../).",
    },
}


class HtmlError(RuntimeError):
    """The HTML edition cannot be built (missing tool, bad input, mdBook failure)."""


def ui(lang: str, key: str) -> str:
    """Interface string: ``[html] <key>`` of the language's i18n table, then :data:`LOCAL_I18N`."""
    shared = config.i18n(lang).get("html", {}) if config.has_i18n(lang) else {}
    if isinstance(shared, dict) and isinstance(shared.get(key), str):
        return shared[key]
    table = LOCAL_I18N.get(lang) or LOCAL_I18N.get(lang.split("-")[0]) or LOCAL_I18N["en"]
    return table.get(key) or LOCAL_I18N["en"].get(key, "")


# --------------------------------------------------------------------------- staging


@dataclass
class Stage:
    root: Path
    src: Path
    warnings: list[str] = field(default_factory=list)
    chapters: list[str] = field(default_factory=list)  # staged Markdown paths (relative to src)
    copied: list[str] = field(default_factory=list)  # staged non-Markdown paths (relative to src)
    math: mathrender.MathReport | None = None
    title_math: dict[str, str] = field(default_factory=dict)  # title Markdown → rendered HTML


def stage_dir(book: config.Book, edition: config.Edition) -> Path:
    return paths.BUILD / "stage" / book.slug / edition.lang / "mdbook"


def _toml_str(value: str) -> str:
    # JSON string escapes are valid TOML basic-string escapes.
    return json.dumps(value, ensure_ascii=False)


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def site_path(site: config.Site, book: config.Book, edition: config.Edition) -> str:
    """URL path of the published edition, e.g. ``/trureturing-books-template/<slug>/zh/``."""
    url = site.book_url(book.slug, edition.lang)
    path = urlparse(url).path if url else f"/{book.slug}/{edition.lang}"
    return "/" + path.strip("/") + "/"


def default_branch(site: config.Site) -> str:
    return str(site.raw.get("site", {}).get("branch") or DEFAULT_BRANCH)


def section_labels(book: config.Book) -> bool:
    """mdBook's "1.2." sidebar numbers; off by default (chapter titles carry their own)."""
    return bool(book.raw.get("html", {}).get("section-labels", False))


def edit_url_prefix(site: config.Site, edition: config.Edition) -> str:
    """``<repo>/edit/<branch>/<edition dir>/`` ('' without a repository or outside it)."""
    if not site.repo:
        return ""
    rel_dir = paths.rel(edition.dir)
    if os.path.isabs(rel_dir):  # an edition outside the repository has no edit link
        return ""
    return f"https://github.com/{site.repo}/edit/{default_branch(site)}/{rel_dir}/"


def book_toml(site: config.Site, book: config.Book, edition: config.Edition,
              css: list[str], js: list[str], *, title: str | None = None) -> str:
    out = [
        "# generated by tbook.html — do not edit (rebuilt by ./tbook build html)",
        "[book]",
        f"title = {_toml_str(edition.title if title is None else title)}",
        f"authors = {_toml_list(book.authors)}",
        f"description = {_toml_str(edition.description)}",
        f"language = {_toml_str(edition.bcp47)}",
        'src = "src"',
        "",
        "[build]",
        "create-missing = false",
        "",
        "[output.html]",
        'default-theme = "navy"',
        'preferred-dark-theme = "navy"',
        f"no-section-label = {'false' if section_labels(book) else 'true'}",
        f"site-url = {_toml_str(site_path(site, book, edition))}",
        f"additional-css = {_toml_list(css)}",
        f"additional-js = {_toml_list(js)}",
    ]
    if site.repo:
        repo_url = f"https://github.com/{site.repo}"
        out.append(f"git-repository-url = {_toml_str(repo_url)}")
        prefix = edit_url_prefix(site, edition)
        if prefix:
            # mdBook writes {path} as "src/<chapter>.md"; fix_edit_links drops the "src/".
            out.append(f"edit-url-template = {_toml_str(prefix + '{path}')}")
    out += [
        "",
        "[output.html.print]",
        "enable = true",
        "",
        "[output.html.search]",
        "enable = true",
        "use-boolean-and = true",
        "",
        "[output.html.fold]",
        "enable = true",
        "level = 1",
        "",
        "[output.html.playground]",
        "runnable = false",
        "",
    ]
    return "\n".join(out)


def _escape_title(title: str) -> str:
    """A plain chapter title (``Chapter.title``) as SUMMARY.md link text that mdBook reads back as
    exactly ``title``: every ASCII punctuation character is backslash-escaped (mdBook knows no math,
    so TeX backslashes are doubled too). Inverse of ``tbook.summary._unescape``."""
    return mdscan.escape_markdown(title)


def _summary_link(title: str, path: str | None) -> str:
    target = path or ""
    if " " in target:
        target = f"<{target}>"
    return f"[{_escape_title(title)}]({target})"


def summary_markdown(model: EditionModel, staged: set[str], ledger_title: str,
                     title_math: dict[str, str] | None = None) -> str:
    """SUMMARY.md with the same structure as the edition's, plus the ledger as last suffix.

    Chapters whose file is not staged (missing files) become drafts so that mdBook still
    builds; ``check`` reports them.
    """
    summary = model.summary
    assert summary is not None
    lines = [f"# {summary.title or 'Summary'}", ""]
    part = ""
    prev = ""

    def plain(markdown: str, fallback: str) -> str:
        markup = (title_math or {}).get(markdown)
        return mathrender.visible_text(markup) if markup is not None else fallback

    for ch in summary.chapters:
        path = ch.path if ch.path in staged else None
        title = plain(ch.title_md, ch.title)
        if ch.section == "numbered":
            if ch.part != part:
                part = ch.part
                lines += ["", f"# {_escape_title(plain(part, mdscan.unescape_markdown(part)))}", ""]
            elif prev != "numbered":
                lines.append("")
            lines.append("  " * ch.depth + "- " + _summary_link(title, path))
        else:
            if path is None:
                continue  # mdBook has no draft prefix/suffix chapters
            if ch.section == "suffix" and prev == "numbered":
                lines += ["", "---", ""]
            lines.append(_summary_link(title, path))
        prev = ch.section
    if prev == "numbered":
        lines += ["", "---", ""]
    elif prev:
        lines.append("")
    lines.append(_summary_link(ledger_title, ledger.LEDGER_FILE))
    lines.append("")
    return "\n".join(lines)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _edition_assets(edition: config.Edition) -> list[Path]:
    """Non-Markdown files of the edition directory (hidden files skipped)."""
    out = []
    for p in sorted(edition.dir.rglob("*")):
        rel = p.relative_to(edition.dir)
        if any(part.startswith(".") for part in rel.parts) or not p.is_file():
            continue
        if p.suffix.lower() in (".md", ".markdown"):
            continue
        out.append(p)
    return out


def _tokens() -> dict:
    return json.loads(paths.TOKENS.read_text(encoding="utf-8"))


def paper_palette_css() -> str:
    """The paper palette of theme/generated/tokens.css re-scoped to mdBook's light themes.

    tokens.css swaps the palette under ``.tr-paper``; mdBook marks the theme on ``<html>``
    with ``light``/``rust`` (and print media has no theme class), so the same declarations
    are emitted for those selectors. No colour is restated here: the block is copied.
    """
    css = (paths.GENERATED / "tokens.css").read_text(encoding="utf-8")
    m = re.search(r"\.tr-paper[^{]*\{(?P<body>[^}]*)\}", css)
    if not m:
        raise HtmlError("theme/generated/tokens.css has no .tr-paper block; run ./tbook theme")
    body = m.group("body").strip("\n")
    return (
        "/* generated by tbook.html from theme/generated/tokens.css — do not edit */\n"
        "html.light, html.rust {\n" + body + "\n}\n"
        "@media print {\n  html, html.navy, html.coal, html.ayu, html.light, html.rust {\n"
        + "\n".join("  " + line for line in body.split("\n")) + "\n  }\n}\n"
    )


def _katex_css() -> str:
    try:
        return mathrender.katex_css()  # only the WOFF2 fonts, which every browser that runs the book reads
    except mathrender.MathError as exc:
        raise HtmlError(str(exc)) from None


def _favicon(tokens: dict) -> str:
    tpl = (MDBOOK_THEME / "favicon.svg").read_text(encoding="utf-8")
    screen = tokens["screen"]
    return re.sub(r"@@([a-z-]+)@@", lambda m: screen.get(m.group(1), m.group(0)), tpl)


def editions_data(site: config.Site, book: config.Book, edition: config.Edition,
                  model: EditionModel, lock) -> dict:
    lang = edition.lang
    keys = list(LOCAL_I18N["en"])
    # "n verified" in the menu counts only what the pages badge LEAN ✓ (render.env_verified)
    verified = render.verified_envs(model.formal_envs(), lock)
    return {
        "slug": book.slug,
        "code": book.code,
        "title": edition.title,
        "version": book.version,
        "current": lang,
        "langs": [{"code": ed.lang, "name": config.s(ed.lang, "meta.name") or ed.lang,
                   "short": config.s(ed.lang, "meta.short") or ed.lang.upper(), "bcp47": ed.bcp47}
                  for ed in book.editions],
        "landing": "../",
        "ledger": posixpath.splitext(ledger.LEDGER_FILE)[0] + ".html",
        "verified": len(verified),
        "commit": lock.commit[:12] if lock else "",
        "strings": {
            **{k: ui(lang, k) for k in keys},
            "badge_lean": config.s(lang, "badge.lean"),
            "verified_count": config.s(lang, "ui.verified_count"),
            "language": config.s(lang, "ui.language"),
            "contents": config.s(lang, "ui.contents"),
        },
    }


def cjk_emphasis(text: str) -> str:
    """Keep Chinese punctuation inside ``**strong**`` as in Pandoc's Markdown reader.

    CommonMark rejects a delimiter between a word and punctuation: in
    ``中文**“术语”**后文`` neither pair can delimit emphasis. Invisible inline HTML
    comments separate those boundaries without adding spaces to Chinese prose.
    Code, formulas, escaped markers, destinations and raw HTML stay literal.
    """
    if "**" not in text:
        return text
    mask, html_lines = mathrender._mask(text)
    for span in mathrender.find_math(text)[0]:
        mask[span.start:span.end] = b"\x01" * (span.end - span.start)
    offset = 0
    for line, raw in zip(text.split("\n"), html_lines):
        if raw:
            mask[offset:offset + len(line)] = b"\x01" * len(line)
        offset += len(line) + 1

    def cjk(char: str) -> bool:
        return bool(re.fullmatch(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af\U00020000-\U0003134f]", char))

    def punct(char: str) -> bool:
        return bool(char) and (unicodedata.category(char).startswith("P") or
                               char.isascii() and not char.isalnum() and not char.isspace())

    out, last = [], 0
    for match in re.finditer(r"(?<!\*)\*\*(?!\*)", text):
        a, b = match.span()
        if mask[a] or mask[a + 1] or mathrender._escaped(text, a):
            continue
        before, after = text[a - 1:a] if a else "", text[b:b + 1]
        prefix = "<!-- -->" if cjk(before) and punct(after) else ""
        suffix = "<!-- -->" if punct(before) and cjk(after) else ""
        if prefix or suffix:
            out.extend((text[last:a], prefix, "**", suffix))
            last = b
    return "".join(out) + text[last:]


def stage_edition(site: config.Site, book: config.Book, edition: config.Edition,
                  model: EditionModel, lock, root: Path | None = None) -> Stage:
    """Write the mdBook project for one edition (math rendered); return what was staged."""
    if model.summary is None:
        errors = "; ".join(i.format() for i in model.issues if i.severity == "error")
        raise HtmlError(f"{edition.key}: SUMMARY.md is missing or cannot be parsed: {errors or 'no summary'}")
    root = root or stage_dir(book, edition)
    if root.exists():
        shutil.rmtree(root)
    src = root / "src"
    src.mkdir(parents=True)
    stage = Stage(root=root, src=src)
    lang = edition.lang

    # Chapters.
    ctx = render.RenderContext(site, book, edition, model, lock, target="mdbook",
                               env_href=render.mdbook_env_href(model))
    staged: set[str] = set()
    for doc in model.chapters:
        path = doc.chapter.path
        assert path is not None
        if path == ledger.LEDGER_FILE:
            raise HtmlError(f"{paths.rel(doc.path)}: the file name {ledger.LEDGER_FILE} is reserved "
                            "for the generated verification ledger; rename the chapter")
        text = cjk_emphasis(render.chapter_markdown(doc, ctx)).rstrip("\n") + "\n"
        out = src / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        staged.add(path)
        stage.chapters.append(path)

    # The verification ledger, linking each item to its chapter (a README.md chapter is index.md).
    def ledger_href(env) -> str:
        doc = model.chapter_of(env.id)
        return f"{render.mdbook_chapter_path(doc.chapter.path)}#{env.id}" if doc else f"#{env.id}"

    (src / ledger.LEDGER_FILE).write_text(ledger.ledger_markdown(model, lock, href=ledger_href), encoding="utf-8")
    stage.chapters.append(ledger.LEDGER_FILE)
    if "404.md" not in staged:
        (src / "404.md").write_text(f"# {ui(lang, 'not_found_title')}\n\n{ui(lang, 'not_found_body')}\n",
                                    encoding="utf-8")
    for ch in model.summary.chapters:
        if ch.path and ch.path not in staged:
            stage.warnings.append(f"{paths.rel(edition.summary)}:{ch.line}: chapter {ch.path} not staged "
                                  "(missing file); listed as a draft")

    # Files next to the chapters, and files of the book directory the chapters link to.
    for p in _edition_assets(edition):
        rel = p.relative_to(edition.dir).as_posix()
        if rel.split("/")[0] in (ASSET_DIR, ctx.book_prefix):
            stage.warnings.append(f"{paths.rel(p)}: top-level directory {rel.split('/')[0]}/ is reserved; skipped")
            continue
        _copy(p, src / rel)
        stage.copied.append(rel)
    book_dir = book.dir.resolve()
    for p in sorted(ctx.book_files):
        if not p.is_file():
            stage.warnings.append(f"{paths.rel(p)}: linked from {edition.key} but not found")
            continue
        rel = posixpath.join(ctx.book_prefix, p.resolve().relative_to(book_dir).as_posix())
        _copy(p, src / rel)
        stage.copied.append(rel)
    stage.warnings += ctx.issues

    # Theme.
    tokens = _tokens()
    theme_dir = root / "theme"
    theme_dir.mkdir()
    head = (MDBOOK_THEME / "head.hbs").read_text(encoding="utf-8")
    (theme_dir / "head.hbs").write_text(head.replace("@@FONTS_CSS@@", tokens["font"]["google-fonts-css"]),
                                        encoding="utf-8")
    (theme_dir / "favicon.svg").write_text(_favicon(tokens), encoding="utf-8")
    assets = root / ASSET_DIR
    (assets / "katex").mkdir(parents=True)
    shutil.copy2(paths.GENERATED / "tokens.css", assets / "tokens.css")
    (assets / "tr-palette.css").write_text(paper_palette_css(), encoding="utf-8")
    shutil.copy2(MDBOOK_THEME / "tr-book.css", assets / "tr-book.css")
    (assets / "katex" / "katex.min.css").write_text(_katex_css(), encoding="utf-8")
    fonts = src / ASSET_DIR / "katex" / "fonts"
    fonts.mkdir(parents=True)
    for font in mathrender.katex_fonts():
        shutil.copy2(font, fonts / font.name)
    data = editions_data(site, book, edition, model, lock)
    (assets / "tr-editions.js").write_text(
        "// generated by tbook.html — do not edit\n"
        f"window.TR_EDITIONS = {json.dumps(data, ensure_ascii=False, indent=2)};\n", encoding="utf-8")
    shutil.copy2(MDBOOK_THEME / "tr-book.js", assets / "tr-book.js")
    css = [f"{ASSET_DIR}/tokens.css", f"{ASSET_DIR}/tr-palette.css", f"{ASSET_DIR}/katex/katex.min.css",
           f"{ASSET_DIR}/tr-book.css"]
    js = [f"{ASSET_DIR}/tr-editions.js", f"{ASSET_DIR}/tr-book.js"]
    # mdBook strips markup while parsing SUMMARY and escapes it again in its TOC helper.
    # Render title fragments with the chapters, give mdBook their visible text (also used
    # by <title> and search), then restore the markup in the two generated TOCs.
    titles = list(dict.fromkeys([edition.title] + [t for ch in model.summary.chapters
                                                for t in (ch.title_md, ch.part)]))
    titles = [t for t in titles if mathrender.find_math(t)[0]]
    title_file = root / "title-math.md"
    if titles:
        title_file.write_text("\n".join(f"<div>{render.title_html(t)}</div>" for t in titles) + "\n", encoding="utf-8")
    md_files = [src / p for p in stage.chapters]
    def math_where(path: Path) -> str:
        return f"{edition.key}/titles" if path == title_file else f"{edition.key}/{path.relative_to(src).as_posix()}"
    stage.math = mathrender.render_files(md_files + ([title_file] if titles else []), where=math_where)
    stage.warnings += stage.math.warnings
    if titles:
        fragments = [line.removeprefix("<div>").removesuffix("</div>")
                     for line in title_file.read_text(encoding="utf-8").splitlines()]
        stage.title_math = dict(zip(titles, fragments, strict=True))
    (src / "SUMMARY.md").write_text(
        summary_markdown(model, staged, config.s(lang, "ledger.title"), stage.title_math), encoding="utf-8")
    book_title = mathrender.visible_text(stage.title_math[edition.title]) if edition.title in stage.title_math else None
    (root / "book.toml").write_text(book_toml(site, book, edition, css, js, title=book_title), encoding="utf-8")
    return stage


# --------------------------------------------------------------------------- mdBook


_TOC_TITLE_RE = re.compile(
    r'(?P<open><li class="part-title">|<span class="chapter-link-wrapper">'
    r'(?:<a\b[^>]*>|<span>)(?:<strong\b[^>]*>.*?</strong> )?)(?P<title>[^<]*)')


def restore_title_math(out_dir: Path, stage: Stage, model: EditionModel, edition: config.Edition) -> None:
    """Restore pre-rendered math in mdBook 0.5's JS and no-JS TOCs and book menu title.

    Match entries in SUMMARY order, including drafts: identical visible titles can have
    different formulas, or one may contain escaped literal dollars. Rehash the modified
    TOC script and update its references so browsers do not reuse the old contents.
    """
    if not stage.title_math:
        return
    assert model.summary is not None
    entries: list[str] = []
    part = ""
    for ch in model.summary.chapters:
        if ch.section == "numbered":
            if ch.part != part:
                part = ch.part
                entries.append(part)
        elif ch.path not in stage.chapters:
            continue
        entries.append(ch.title_md)
    entries.append("")  # generated verification ledger

    def toc(text: str, *, javascript: bool = False) -> str:
        index = 0

        def replace(m: re.Match) -> str:
            nonlocal index
            if index >= len(entries):
                raise HtmlError("mdBook TOC structure changed: unexpected title entry")
            markup = stage.title_math.get(entries[index])
            index += 1
            if markup is None:
                return m.group(0)
            if javascript:
                markup = markup.replace("\\", "\\\\").replace("'", "\\'")
            return m["open"] + markup

        result = _TOC_TITLE_RE.sub(replace, text)
        if index != len(entries):
            raise HtmlError("mdBook TOC structure changed: missing title entries")
        return result

    renamed: dict[str, str] = {}
    for script in out_dir.glob("toc*.js"):
        old = script.read_text(encoding="utf-8")
        new = toc(old, javascript=True)
        if new == old:
            continue
        name = f"toc-{hashlib.sha256(new.encode('utf-8')).hexdigest()[:8]}.js" if script.name != "toc.js" else "toc.js"
        script.write_text(new, encoding="utf-8")
        if name != script.name:
            renamed[script.name] = name
            script.rename(script.with_name(name))
    for page in out_dir.rglob("*.html"):
        old = page.read_text(encoding="utf-8")
        new = toc(old) if page.name == "toc.html" else old
        if edition.title in stage.title_math:
            new = re.sub(r'(<h1 class="menu-title">)[^<]*(</h1>)',
                         lambda m: m[1] + stage.title_math[edition.title] + m[2], new)
        for before, after in renamed.items():
            new = new.replace(before, after)
        if new != old:
            page.write_text(new, encoding="utf-8")


def mdbook_binary() -> str:
    exe = os.environ.get("MDBOOK") or shutil.which("mdbook")
    if not exe:
        raise HtmlError("mdbook not found: set MDBOOK=/path/to/mdbook or put mdBook 0.5.4 on PATH "
                        "(cargo install mdbook --version 0.5.4 --locked)")
    if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
        raise HtmlError(f"mdbook at {exe} is not an executable file")
    return exe


def mdbook_version(exe: str) -> tuple[int, ...]:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HtmlError(f"cannot run {exe} --version: {exc}") from exc
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else ()


def run_mdbook(project: Path, out_dir: Path) -> list[str]:
    """``mdbook build``; returns mdBook's warnings, raises :class:`HtmlError` on failure."""
    exe = mdbook_binary()
    warnings = []
    version = mdbook_version(exe)
    if version[:2] != MDBOOK_SERIES:
        warnings.append(f"mdbook {'.'.join(map(str, version)) or '?'} found; the theme targets mdBook 0.5.4")
    out_dir = out_dir.resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("RUST_LOG", "warn")
    env["NO_COLOR"] = "1"
    proc = subprocess.run([exe, "build", "-d", str(out_dir), str(project)], capture_output=True, text=True, env=env)
    log = (proc.stderr + proc.stdout).strip()
    if proc.returncode != 0:
        raise HtmlError(f"mdbook build failed for {paths.rel(project)}:\n{log[-4000:]}")
    for line in log.splitlines():
        if re.search(r"\b(WARN|ERROR)\b", line):
            warnings.append("mdbook: " + line.strip())
    if not (out_dir / "index.html").exists():
        raise HtmlError(f"mdbook build produced no index.html in {paths.rel(out_dir)}")
    return warnings


# --------------------------------------------------------------------------- search


# Han, kana and Hangul; keep in sync with CJK in theme/mdbook/tr-book.js.
CJK_RE = re.compile("[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]+")
SEARCH_FIELDS = ("title", "body", "breadcrumbs")
_SEARCHINDEX_RE = re.compile(r"^(?P<head>window\.search = Object\.assign\(window\.search, JSON\.parse\(')"
                             r"(?P<json>.*)(?P<tail>'\)\);)\s*$", re.S)


def cjk_grams(text: str) -> list[str]:
    """Character unigrams and bigrams of every CJK run of ``text`` (lower-cased words)."""
    out: list[str] = []
    for word in re.split(r"[\s\-]+", text.lower()):
        for run in CJK_RE.findall(word):
            out.extend(run)
            out.extend(run[k:k + 2] for k in range(len(run) - 1))
    return out


def _add_token(root: dict, token: str, ref: str, tf: float) -> None:
    node = root
    for ch in token:
        node = node.setdefault(ch, {"docs": {}, "df": 0})
    docs = node.setdefault("docs", {})
    node.setdefault("df", 0)
    if ref not in docs:
        node["df"] += 1
        docs[ref] = {"tf": tf}
    else:
        docs[ref]["tf"] = max(docs[ref].get("tf", 0.0), tf)


def augment_search_index(path: Path) -> int:
    """Add CJK uni-/bigrams to mdBook's elasticlunr index in place; return tokens added.

    mdBook splits words on whitespace, so a Chinese sentence is one "word" and cannot be
    found by any of its parts. Each document's stored text is re-tokenized here into
    character unigrams and bigrams (elasticlunr's ``tf = sqrt(count)``), and
    ``tr-book.js`` tokenizes queries the same way, so "亏量" finds "归一化亏量".
    """
    raw = path.read_text(encoding="utf-8")
    m = _SEARCHINDEX_RE.match(raw)
    if not m:
        raise HtmlError(f"{paths.rel(path)}: unexpected search index format (mdBook 0.5.x expected)")
    payload = json.loads(re.sub(r"\\([\\'])", r"\1", m.group("json")))
    index = payload["index"]
    store = index.get("documentStore", {})
    docs, info = store.get("docs") or {}, store.setdefault("docInfo", {})
    added = 0
    for ref, fields in docs.items():
        for field_name in SEARCH_FIELDS:
            grams = cjk_grams(str(fields.get(field_name) or ""))
            if not grams or field_name not in index["index"]:
                continue
            counts: dict[str, int] = {}
            for g in grams:
                counts[g] = counts.get(g, 0) + 1
            root = index["index"][field_name]["root"]
            for token in sorted(counts):
                _add_token(root, token, ref, counts[token] ** 0.5)
            doc_info = info.setdefault(ref, {})
            doc_info[field_name] = int(doc_info.get(field_name, 0)) + len(grams)
            added += len(counts)
    if added:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        path.write_text(m.group("head") + text.replace("\\", "\\\\").replace("'", "\\'") + m.group("tail"),
                        encoding="utf-8")
    return added


def augment_search(out_dir: Path) -> int:
    total = 0
    for p in sorted(out_dir.glob("searchindex*.js")):
        total += augment_search_index(p)
    return total


def fix_edit_links(out_dir: Path, prefix: str, generated: set[str]) -> int:
    """Point every "Suggest an edit" link at the chapter's file in the repository.

    mdBook fills ``{path}`` of ``edit-url-template`` with ``<src>/<chapter>.md``
    (``src/ch01.md``), but the staged ``src/`` mirrors the edition directory itself, whose
    chapters live at ``books/<slug>/<lang>/ch01.md``: the ``src/`` is dropped. Pages of
    ``generated`` chapters (the verification ledger) have no source file, so their link is
    removed. Returns the number of pages changed.
    """
    if not prefix:
        return 0
    staged = prefix + "src/"
    drop = re.compile(r'<a href="' + re.escape(staged) + r'(?:' + "|".join(re.escape(g) for g in sorted(generated))
                      + r')"[^>]*>.*?</a>\s*', re.S) if generated else None
    changed = 0
    for page in sorted(out_dir.rglob("*.html")):
        text = page.read_text(encoding="utf-8")
        if f'href="{staged}' not in text:
            continue
        if drop:
            text = drop.sub("", text)
        page.write_text(text.replace(f'href="{staged}', f'href="{prefix}'), encoding="utf-8")
        changed += 1
    return changed


def _warn(label: str, messages: list[str]) -> None:
    gh = os.environ.get("GITHUB_ACTIONS") == "true"
    for msg in messages:
        if gh:
            print(f"::warning title=html {label}::{msg.replace('%', '%25').replace(chr(10), '%0A')}", file=sys.stderr)
        else:
            print(f"warning: html {label}: {msg}", file=sys.stderr)


def build_edition(site, book, edition, model, lock, out_dir: Path) -> Path:
    """Build the HTML edition of ``book`` in ``edition.lang`` into ``out_dir``; return it."""
    mdbook_binary()  # fail before staging when the tool is missing
    if model is None:
        model = load_edition(edition)
    stage = stage_edition(site, book, edition, model, lock)
    errors = [i for i in model.issues if i.severity == "error"]
    if errors:
        _warn(edition.key, [f"{len(errors)} model error(s) in {edition.key}; run ./tbook check"])
    _warn(edition.key, stage.warnings)
    _warn(edition.key, run_mdbook(stage.root, out_dir))
    restore_title_math(out_dir, stage, model, edition)
    generated = {ledger.LEDGER_FILE} | ({"404.md"} if "404.md" not in stage.chapters else set())
    fix_edit_links(out_dir, edit_url_prefix(site, edition), generated)
    augment_search(out_dir)
    # mdBook's print.html does not rewrite iframe src / video poster of nested chapters; the same
    # (idempotent) repair site.publish_html applies, so build/html is right on its own too.
    from . import site as site_mod

    printed = out_dir / "print.html"
    if printed.is_file():
        printed.write_text(site_mod.fix_print_media(printed.read_text(encoding="utf-8")), encoding="utf-8")
    return out_dir

