"""Slide decks of a book (Slidev 53, the chrono-company-slides scheme, trureturing theme).

Layout::

    books/<slug>/slides/<deck>/slides.md          the book's first language (book.toml editions[0], zh by default)
    books/<slug>/slides/<deck>/slides.<lang>.md   every other edition language of the book (e.g. slides.en.md)

Every deck has one file per language of the book, page for page; ``slides.<first language>.md`` is an
error (``slides.md`` would shadow it). The shared Slidev theme is ``theme/slides``
(``theme: ../../../../theme/slides`` in the headmatter); its components ``<LeanBadge gid>`` and
``<TheoremCard gid>`` (also written ``<lean-badge>``, ``<theorem-card>``) show the green LEAN ✓ only
for GIDs that ``trureturing.lock.json`` resolves to a Lean theorem.

This module is the Python side of the scheme (``tbook.check``, ``tbook.render`` and ``tbook.build``
call it); the Node side lives in ``tools/node/slides-*.mjs``:

* :func:`check` — both languages present, headmatter, page-for-page parity (slides are split
  exactly like ``@slidev/parser``), cited GIDs locked and consistent with the book (``cite=``),
  no root-relative links;
* :func:`render_embed` — ``::: {.slides src="<deck>"}`` in a chapter: a link card (mdBook) or a
  short block with the public URL (PDF / EPUB);
* :func:`build` — ``slides-build.mjs``: ``slidev build`` per deck and language into
  ``build/slides/<slug>/<deck>/<lang>/``, browser checks, ``slidev export`` to
  ``build/slides/<slug>/<deck>-<lang>.pdf`` with a page-count check;
* :func:`publish` — copy the built decks into ``_site/<slug>/slides/`` (the first language at
  ``<deck>/``, other languages at ``<deck>/<lang>/``, PDFs at ``<deck>/<slug>-<deck>-<lang>.pdf``)
  plus an index page;
* :func:`cli` — ``./tbook slides new <book> <deck> "<中文标题>" "<English title>"`` and ``list``.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import academic, config, evidence, lean, paths
from .model import OPEN, Issue

PRIMARY_FILE = "slides.md"  # the edition of the book's first language
DECK_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FILE_RE = re.compile(r"^slides\.([a-z]{2,3}(?:-[A-Za-z0-9]+)*)\.md$")
MANIFEST = "manifest.json"
MANIFEST_SCHEMA = "trureturing-books.slides.v1"

# Interface strings this component needs that theme/i18n/*.toml does not have yet. config.s() wins
# once the keys are merged there as [slides] (the Slidev theme keeps the same table in i18n.ts).
LOCAL_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "present": "在线演示",
        "pdf": "下载 PDF",
        "notes_pdf": "讲者笔记 PDF",
        "pages": "{n} 页",
        "static_note": "在线演示见",
        "keys": "在线演示：方向键或空格翻页，O 总览，F 全屏。",
        "back_to_book": "返回本书",
        "none": "本书还没有演示文稿。",
        "not_built": "尚未构建",
    },
    "en": {
        "present": "Present online",
        "pdf": "Download PDF",
        "notes_pdf": "Speaker notes PDF",
        "pages": "{n} slides",
        "static_note": "Slides online:",
        "keys": "Online: arrow keys or space to advance, O for the overview, F for full screen.",
        "back_to_book": "Back to the book",
        "none": "This book has no slides yet.",
        "not_built": "not built yet",
    },
}


def t(lang: str, key: str, **fmt: Any) -> str:
    """``slides.<key>`` from the shared i18n tables, else from :data:`LOCAL_STRINGS`."""
    text = config.s(lang, f"slides.{key}") or LOCAL_STRINGS.get(lang, LOCAL_STRINGS["en"]).get(key) \
        or LOCAL_STRINGS["en"].get(key, key)
    return text.format(**fmt) if fmt else text


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


# --------------------------------------------------------------------------- file conventions


def edition_file(book: config.Book, lang: str) -> str:
    """``slides.md`` for the book's first language, ``slides.<lang>.md`` for every other language."""
    return PRIMARY_FILE if lang == book.languages[0] else f"slides.{lang}.md"


def lang_of_file(book: config.Book, name: str) -> str | None:
    """The edition language of a deck file, or None when the file is not an edition. ``slides.<first
    language>.md`` is not one: that language's edition is ``slides.md`` (:func:`check` reports it)."""
    if name == PRIMARY_FILE:
        return book.languages[0]
    m = FILE_RE.match(name)
    return m.group(1) if m and m.group(1) != book.languages[0] else None


def site_path(book: config.Book, deck: str, lang: str) -> str:
    """Path of an edition under ``_site/<slug>/slides/``: ``<deck>/`` for the book's first language,
    ``<deck>/<lang>/`` for the others."""
    return f"{deck}/" if lang == book.languages[0] else f"{deck}/{lang}/"


def pdf_name(book: config.Book, deck: str, lang: str) -> str:
    """Published PDF name, e.g. ``example-monograph-overview-zh.pdf`` (kept in sync with slides-lib.mjs)."""
    return f"{book.slug}-{deck}-{lang}.pdf"


def build_pdf_name(deck: str, lang: str) -> str:
    """PDF name under ``build/slides/<slug>/`` (docs/ARCHITECTURE.md §5)."""
    return f"{deck}-{lang}.pdf"


def theme_ref(deck_dir: Path) -> str:
    """The ``theme:`` value a deck must use: the relative path to ``theme/slides``."""
    return Path(os.path.relpath(paths.THEME / "slides", deck_dir)).as_posix()


def base_path(site: config.Site) -> str:
    """URL path of the site root (``/books/`` for https://owner.github.io/books/); ``/`` when unknown."""
    path = urlparse(site.base_url).path if site.base_url else ""
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path if path.endswith("/") else path + "/"


def public_url(site: config.Site, book: config.Book, deck: str, lang: str) -> str:
    """Absolute URL of an edition on the published site ('' when the site has no base_url)."""
    url = site.book_url(book.slug, "slides", site_path(book, deck, lang))
    return url + "/" if url and not url.endswith("/") else url


def build_dir(book: config.Book) -> Path:
    return paths.BUILD / "slides" / book.slug


def deck_names(book: config.Book) -> list[str]:
    root = book.slides_dir
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def deck_langs(book: config.Book, deck: str) -> list[str]:
    """Languages with an edition file in the deck directory, the book's order first."""
    d = book.slides_dir / deck
    if academic.is_academic(d):
        return academic.settings(book, deck)["editions"]
    if not d.is_dir():
        return []
    found = {lang for lang in (lang_of_file(book, p.name) for p in d.iterdir() if p.is_file()) if lang}
    order = {lang: i for i, lang in enumerate(book.languages)}
    return sorted(found, key=lambda lang: (order.get(lang, len(order)), lang))


# --------------------------------------------------------------------------- YAML (frontmatter subset)


class YamlError(ValueError):
    pass


_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
            "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0"}


def _double_quoted(s: str, i: int) -> tuple[str, int]:
    out = []
    i += 1
    while i < len(s):
        c = s[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\" and i + 1 < len(s):
            d = s[i + 1]
            if d in "xuU":
                n = {"x": 2, "u": 4, "U": 8}[d]
                out.append(chr(int(s[i + 2:i + 2 + n], 16)))
                i += 2 + n
                continue
            out.append(_ESCAPES.get(d, d))
            i += 2
            continue
        out.append(c)
        i += 1
    raise YamlError("unterminated double-quoted string")


def _single_quoted(s: str, i: int) -> tuple[str, int]:
    out = []
    i += 1
    while i < len(s):
        if s[i] == "'":
            if s[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(s[i])
        i += 1
    raise YamlError("unterminated single-quoted string")


def _plain(text: str) -> Any:
    v = text.strip()
    if v in ("", "~", "null", "Null", "NULL"):
        return None
    if v in ("true", "True", "TRUE"):
        return True
    if v in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?(?:0|[1-9][0-9]*)", v):
        return int(v)
    if re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", v):
        return float(v)
    return v


def _split_flow(body: str) -> list[str]:
    parts, depth, quote, cur = [], 0, "", []
    for c in body:
        if quote:
            cur.append(c)
            if c == quote:
                quote = ""
            continue
        if c in "\"'":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(c)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _scalar(text: str) -> Any:
    """A YAML value written on one line: quoted, flow collection or plain (trailing comment removed)."""
    s = text.strip()
    if not s:
        return None
    if s[0] in "\"'":
        value, end = (_double_quoted if s[0] == '"' else _single_quoted)(s, 0)
        rest = s[end:].strip()
        if rest and not rest.startswith("#"):
            raise YamlError(f"unexpected text after a quoted string: {rest!r}")
        return value
    if s[0] in "[{":
        close = "]" if s[0] == "[" else "}"
        body = s[1:s.rindex(close)] if close in s else s[1:]
        items = [p.strip() for p in _split_flow(body)]
        if s[0] == "[":
            return [_scalar(p) for p in items if p]
        out: dict[str, Any] = {}
        for p in items:
            k, _, v = p.partition(":")
            out[str(_scalar(k))] = _scalar(v)
        return out
    s = re.split(r"\s#", s, maxsplit=1)[0]
    return _plain(s)


@dataclass
class _Line:
    indent: int
    text: str
    no: int  # index into the raw lines


def parse_yaml(text: str) -> dict[str, Any]:
    """Parse the YAML subset used by Slidev frontmatter: nested block mappings, block and flow
    sequences, quoted and plain scalars, block scalars (``|``/``>``) and comments."""
    raw = text.split("\n")
    items = []
    for no, line in enumerate(raw):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise YamlError(f"line {no + 1}: tabs are not allowed for indentation")
        items.append(_Line(len(line) - len(line.lstrip(" ")), stripped, no))

    def block_scalar(header: str, start_no: int, parent_indent: int) -> tuple[str, int]:
        body, no, ind = [], start_no + 1, None
        while no < len(raw):
            line = raw[no]
            if line.strip():
                cur = len(line) - len(line.lstrip(" "))
                if cur <= parent_indent:
                    break
                ind = cur if ind is None else ind
                body.append(line[ind:])
            else:
                body.append("")
            no += 1
        while body and not body[-1]:
            body.pop()
        value = "\n".join(body) if header.startswith("|") else " ".join(b for b in body if b)
        if not header.endswith("-"):
            value += "\n"
        return value, no

    def skip_to(no: int, i: int) -> int:
        while i < len(items) and items[i].no < no:
            i += 1
        return i

    def node(i: int, indent: int) -> tuple[Any, int]:
        if items[i].text.startswith("- ") or items[i].text == "-":
            return seq(i, indent)
        return mapping(i, indent)

    def value_after(rest: str, i: int, line: _Line) -> tuple[Any, int]:
        rest = rest.strip()
        if rest.startswith(("|", ">")):
            value, no = block_scalar(rest.split("#")[0].strip(), line.no, line.indent)
            return value, skip_to(no, i)
        if rest and not rest.startswith("#"):
            return _scalar(rest), i
        if i < len(items) and (items[i].indent > line.indent or
                               (items[i].indent == line.indent and items[i].text.startswith("- "))):
            return node(i, items[i].indent)
        return None, i

    def mapping(i: int, indent: int) -> tuple[dict, int]:
        out: dict[str, Any] = {}
        while i < len(items) and items[i].indent == indent and not items[i].text.startswith("- "):
            line = items[i]
            text = line.text
            if text[0] in "\"'":
                key, end = (_double_quoted if text[0] == '"' else _single_quoted)(text, 0)
                if not text[end:].lstrip().startswith(":"):
                    raise YamlError(f"line {line.no + 1}: expected ':' after the key")
                rest = text[end:].lstrip()[1:]
            else:
                m = re.match(r"([^:#]+?)\s*:(?:\s|$)", text + " ")
                if not m:
                    raise YamlError(f"line {line.no + 1}: expected 'key: value', got {text!r}")
                key, rest = m.group(1), text[m.end():]
            out[str(key)], i = value_after(rest, i + 1, line)
        if i < len(items) and items[i].indent > indent:
            raise YamlError(f"line {items[i].no + 1}: unexpected indentation")
        return out, i

    def seq(i: int, indent: int) -> tuple[list, int]:
        out: list[Any] = []
        while i < len(items) and items[i].indent == indent and (items[i].text.startswith("- ") or items[i].text == "-"):
            line = items[i]
            rest = line.text[1:].strip()
            if re.match(r"[^\"'\[{][^:#]*:\s", rest + " ") and not rest.startswith(("|", ">")):
                # "- key: value" starts an inline mapping
                sub_indent = indent + (len(line.text) - len(line.text[1:].lstrip()))
                items[i] = _Line(sub_indent, rest, line.no)
                value, i = mapping(i, sub_indent)
                out.append(value)
                continue
            value, i = value_after(rest, i + 1, line)
            out.append(value)
        return out, i

    if not items:
        return {}
    value, i = node(0, items[0].indent)
    if i < len(items):
        raise YamlError(f"line {items[i].no + 1}: unexpected content")
    if not isinstance(value, dict):
        raise YamlError("frontmatter must be a mapping")
    return value


# --------------------------------------------------------------------------- splitting (as @slidev/parser)


@dataclass
class Slide:
    index: int  # 1-based position among all slides of the file
    line: int  # 1-based line where the slide (its frontmatter) starts
    frontmatter: dict[str, Any]
    content: str
    error: str = ""

    @property
    def hidden(self) -> bool:
        return bool(self.frontmatter.get("hide") or self.frontmatter.get("disabled"))


# JavaScript's whitespace (\s, trim()): @slidev/parser and Slidev's Markdown trim and match with it, so the code
# here that reads a deck as they do uses it too (Python's differs: U+FEFF, U+0085, U+001C-U+001F).
_JS_SPACE = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_JS_SPACE_CHARS = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
                   "\u2028\u2029\u202f\u205f\u3000\ufeff")
_FRONTMATTER_RE = re.compile(r"^---[^\n\r\u2028\u2029]*\r?\n([\s\S]*?)---")
_YAML_BLOCK_RE = re.compile(rf"^[{_JS_SPACE}]*```ya?ml([\s\S]*?)```")


def _js_trim(s: str) -> str:
    return s.strip(_JS_SPACE_CHARS)


def _advance_comment(line: str, inside: bool) -> bool:
    cursor = 0
    while cursor < len(line):
        if inside:
            end = line.find("-->", cursor)
            if end < 0:
                return True
            inside = False
            cursor = end + 3
        else:
            start = line.find("<!--", cursor)
            if start < 0:
                return False
            end = line.find("-->", start + 4)
            if end < 0:
                return True
            cursor = end + 3
    return inside


def _parse_slide(raw: str, index: int, line: int) -> Slide:
    data, error = "", ""
    m = _FRONTMATTER_RE.match(raw)
    content = raw
    if m:
        data, content = m.group(1), raw[m.end():]
    else:
        m = _YAML_BLOCK_RE.match(raw)
        if m:
            data, content = m.group(1), raw[m.end():]
    try:
        fm = parse_yaml(data) if data else {}
    except YamlError as exc:
        fm, error = {}, str(exc)
    content = _js_trim(content)
    comments = list(re.finditer(r"<!--([\s\S]*?)-->", content))
    if comments and comments[-1].end() >= len(content):  # trailing comment = speaker notes
        content = _js_trim(content[:comments[-1].start()])
    return Slide(index=index, line=line, frontmatter=fm, content=content, error=error)


def split_slides(text: str) -> list[Slide]:
    """Split a Slidev file into slides exactly as ``@slidev/parser`` ``parseSync`` does.

    A line starting with ``---`` ends the current slide; when it is not ``----`` and the next line is
    not blank, it opens a frontmatter block closed by the next ``---`` line. Fenced code and HTML
    comments are skipped.
    """
    lines = re.split(r"\r?\n", text)
    slides: list[Slide] = []
    start = 0
    in_comment = False

    def cut(end: int) -> None:
        nonlocal start
        if start == end:
            return
        slides.append(_parse_slide("\n".join(lines[start:end]), len(slides) + 1, start + 1))
        start = end + 1

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.rstrip(_JS_SPACE_CHARS)
        if in_comment:
            in_comment = _advance_comment(raw_line, True)
        elif line.startswith("---"):
            cut(i)
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if (len(line) < 4 or line[3] != "-") and nxt is not None and _js_trim(nxt):
                start = i
                i += 1
                while i < len(lines) and lines[i].rstrip(_JS_SPACE_CHARS) != "---":
                    i += 1
        elif line.lstrip(_JS_SPACE_CHARS).startswith("```"):
            level = re.match(rf"[{_JS_SPACE}]*`+", line).group(0)
            j = i + 1
            while j < len(lines) and not lines[j].startswith(level):
                j += 1
            if j != len(lines):
                i = j
        else:
            in_comment = _advance_comment(raw_line, False)
        i += 1
    if start <= len(lines) - 1:
        cut(len(lines))
    return slides


def count_slides(text: str) -> int:
    """Slides Slidev presents (and exports): all slides except those marked hide/disabled."""
    return sum(1 for s in split_slides(text) if not s.hidden)


# --------------------------------------------------------------------------- code in a slide (as Slidev's Markdown)
# Slidev 53 renders a slide with markdown-exit (markdown-it 14) as unplugin-vue-markdown sets it up: HTML on,
# the HTML block rule of @mdit-vue/plugin-component (a Vue component tag such as <v-click> or <LeanBadge>
# starts an HTML block that may interrupt a paragraph, a self-closing one fills just its line), GFM tables,
# footnotes (markdown-it-footnote) and Slidev's own block rules: `<<< file` snippet imports, `::name::` slot
# markers and `$$` math (on in every deck that has a `$$`). A tag inside a code block (fenced, indented or
# imported) is shown as text; every other tag is rendered. code_lines() runs those block rules as markdown-it
# does (same rule order, same lists of rules that may interrupt a paragraph, block quote, list or table, same
# container offsets) and records the lines of the code blocks; slides-lib.mjs codeLines() is the same port
# (keep them in step: test_slides compares both with the parser Slidev builds). Patterns use JavaScript's \s
# (Unicode spaces), trim and case folding (ASCII only). Not modelled: what a deck adds itself (mdc/comark
# syntax, setup/transformers.ts, Markdown options in vite.config).

_NEWLINE_RE = re.compile(r"\r\n?|\n")  # line ends as markdown-it reads them
_S = f"[{_JS_SPACE}]"  # JavaScript's \s
_BLOCK_TAGS = ("address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|"
               "dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|"
               "html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|"
               "summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul")
# HTML's inline elements, less Vue's own (template, component, slot, …): any other tag is a component
_INLINE_TAGS = ("a|abbr|acronym|audio|b|bdi|bdo|big|br|button|canvas|cite|code|data|datalist|del|dfn|em|embed|i|"
                "iframe|img|input|ins|kbd|label|map|mark|meter|noscript|object|output|picture|progress|q|ruby|s|"
                "samp|script|select|small|span|strong|sub|sup|svg|textarea|time|u|tt|var|video|wbr")
_ATTR = (rf"(?:{_S}+[a-zA-Z_:@][a-zA-Z0-9:._-]*(?:{_S}*={_S}*(?:[^\"'=<>`\x00-\x20]+|'[^']*'|\"[^\"]*\"))?)")
_OPEN_TAG = rf"<[A-Za-z][A-Za-z0-9\-]*{_ATTR}*{_S}*/?>"
_CLOSE_TAG = rf"</[A-Za-z][A-Za-z0-9\-]*{_S}*>"
# HTML blocks: (start, end (None: a blank line), may interrupt a paragraph). ``` inside one is HTML, not code.
_HTML_BLOCKS = (
    (re.compile(rf"<(?:script|pre|style)(?={_S}|>|\Z)", re.I | re.A),
     re.compile(r"</(?:script|pre|style)>", re.I | re.A), True),
    (re.compile(r"<!--"), re.compile(r"-->"), True),
    (re.compile(r"<\?"), re.compile(r"\?>"), True),
    (re.compile(r"<![A-Z]"), re.compile(r">"), True),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>"), True),
    (re.compile(rf"</?(?:{_BLOCK_TAGS})(?={_S}|/?>|\Z)", re.I | re.A), None, True),
    (re.compile(rf"</?(?!(?:{_INLINE_TAGS})(?![\w-]))[A-Za-z][A-Za-z0-9\-]*(?={_S}|/?>|\Z)", re.A), None, True),
    (re.compile(rf"(?:{_OPEN_TAG}|{_CLOSE_TAG}){_S}*\Z"), None, False),
)
_COMPONENT = 6  # its tag alone on a line, self-closing or closed on the line, is just that line
_ONE_LINE_TAG = re.compile(rf"<[A-Za-z][A-Za-z0-9\-]*{_ATTR}*{_S}*/>|<([A-Za-z][A-Za-z0-9\-]*){_ATTR}*{_S}*>"
                           rf"[^\n\r\u2028\u2029]*</\1{_S}*>")
_SLOT_RE = re.compile(rf"::{_S}*[\w.\-:]+{_S}*::{_S}*\Z", re.A)  # Slidev's ::slot:: line
_DOT = r"[^\n\r\u2028\u2029]"  # JavaScript's .
_SNIPPET_RE = re.compile(  # Slidev's <<< file import: path, #region, language, {meta}
    rf"<<<[ \t]*([^{_JS_SPACE}]{_DOT}*?)(#[\w-]+)?[ \t]*(?:[ \t]([^{_JS_SPACE}]+?))?[ \t]*(\{{{_DOT}*)?\Z", re.A)
_DELIMITER_CELL_RE = re.compile(r":?-+:?\Z")
_BAD_PROTO_RE = re.compile(r"(?:vbscript|javascript|file|data):")
_GOOD_DATA_RE = re.compile(r"data:image/(?:gif|png|jpeg|webp);")
# the named character references that can make a link destination start with one of those schemes
_NAMED_REFS = {"Tab": "\t", "NewLine": "\n", "nbsp": "\u00a0", "NonBreakingSpace": "\u00a0", "ensp": "\u2002",
               "emsp": "\u2003", "emsp13": "\u2004", "emsp14": "\u2005", "numsp": "\u2007", "puncsp": "\u2008",
               "thinsp": "\u2009", "ThinSpace": "\u2009", "hairsp": "\u200a", "VeryThinSpace": "\u200a",
               "MediumSpace": "\u205f", "ThickSpace": "\u205f\u200a", "colon": ":", "semi": ";", "sol": "/",
               "fjlig": "fj"}
_UNESCAPE_RE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])|&#([0-9A-Za-z]{1,31});"
                          rf"|&({'|'.join(sorted(_NAMED_REFS, key=len, reverse=True))});")
_NUMERIC_RE = re.compile(r"[xX]([0-9a-fA-F]{1,8})|([0-9]{1,8})")
_NUMERIC_PREFIX_RE = re.compile(r"[xX]([0-9a-fA-F]+)|([0-9]+)")


def _space(c: str) -> bool:
    return c == " " or c == "\t"


def _valid_entity(c: int) -> bool:
    return not (0xD800 <= c <= 0xDFFF or 0xFDD0 <= c <= 0xFDEF or (c & 0xFFFF) in (0xFFFF, 0xFFFE) or c <= 0x08
                or c == 0x0B or 0x0E <= c <= 0x1F or 0x7F <= c <= 0x9F or c > 0x10FFFF)


def _unescape(s: str) -> str:
    """A link destination as markdown-it unescapes it, as far as it can decide whether the link is allowed:
    backslash escapes, numeric character references (``&#58;``; ``&#58x;`` as the entities decoder reads it,
    any character that cannot matter as U+FFFD) and the named references in ``_NAMED_REFS``."""
    def one(m: re.Match) -> str:
        if m.group(1):
            return m.group(1)
        if m.group(3):
            return _NAMED_REFS[m.group(3)]
        name = m.group(2)
        exact = _NUMERIC_RE.fullmatch(name)
        if exact:
            c = int(exact.group(1), 16) if exact.group(1) else int(exact.group(2))
            return chr(c) if _valid_entity(c) else m.group(0)
        lead = _NUMERIC_PREFIX_RE.match(name)
        if not lead:
            return m.group(0)
        c = int(lead.group(1), 16) if lead.group(1) else int(lead.group(2))
        rest = name[lead.end():]
        bad = c == 0 or 0x80 <= c <= 0x9F or 0xD800 <= c <= 0xDFFF or c > 0x10FFFF
        return ("\ufffd" if bad else chr(c)) + (rest + ";" if rest else "")
    return _UNESCAPE_RE.sub(one, s)


def _escaped_split(s: str) -> list[str]:
    """A table row's cells: split at | unless escaped (markdown-it's escapedSplit)."""
    out, cur, last, escaped = [], "", 0, False
    for pos, c in enumerate(s):
        if c == "|":
            if not escaped:
                out.append(cur + s[last:pos])
                cur, last = "", pos + 1
            else:
                cur += s[last:pos - 1]
                last = pos
        escaped = c == "\\"
    out.append(cur + s[last:])
    if out and out[0] == "":
        out.pop(0)
    if out and out[-1] == "":
        out.pop()
    return out


class _Blocks:
    """markdown-it's block state (StateBlock): per line its start (bm), end (em), first non-space (ts), indent
    in columns (sc) and tab offset (bs), as the containers met so far have shifted them."""

    def __init__(self, src: str) -> None:
        self.src = src
        self.bm: list[int] = []
        self.em: list[int] = []
        self.ts: list[int] = []
        self.sc: list[int] = []
        self.bs: list[int] = []
        start, n = 0, len(src)
        while start < n:
            end = src.find("\n", start)
            end = n if end < 0 else end
            pos, offset = start, 0
            while pos < end and _space(src[pos]):
                offset += 4 - offset % 4 if src[pos] == "\t" else 1
                pos += 1
            self.bm.append(start), self.em.append(end), self.ts.append(pos - start), self.sc.append(offset)
            self.bs.append(0)
            start = end + 1
        self.bm.append(n), self.em.append(n), self.ts.append(0), self.sc.append(0), self.bs.append(0)
        self.line_max = len(self.bm) - 1
        self.line = 0
        self.blk = 0  # blkIndent
        self.list_indent = -1
        self.parent = "root"
        self.level = 0
        self.code = [False] * self.line_max

    def at(self, pos: int) -> str:
        return self.src[pos:pos + 1]

    def empty(self, line: int) -> bool:
        return line < len(self.bm) and self.bm[line] + self.ts[line] >= self.em[line]

    def skip_empty(self, line: int) -> int:
        while line < self.line_max and self.bm[line] + self.ts[line] >= self.em[line]:
            line += 1
        return line

    def skip_spaces(self, pos: int) -> int:
        while pos < len(self.src) and _space(self.src[pos]):
            pos += 1
        return pos

    def skip_chars(self, pos: int, c: str) -> int:
        while pos < len(self.src) and self.src[pos] == c:
            pos += 1
        return pos

    def text(self, line: int) -> str:
        return self.src[self.bm[line] + self.ts[line]:self.em[line]]

    def mark(self, start: int, end: int) -> None:
        for i in range(start, min(end, self.line_max)):
            self.code[i] = True

    def interrupts(self, chain: tuple, line: int, end: int) -> bool:
        return any(rule(self, line, end, True) for rule in chain)

    def tokenize(self, start: int, end: int) -> None:
        line = start
        while line < end:
            self.line = line = self.skip_empty(line)
            if line >= end or self.sc[line] < self.blk:
                break
            if self.level >= 100:  # markdown-it's maxNesting
                self.line = end
                break
            for rule in _RULES:
                if rule(self, line, end, False):
                    break
            line = self.line
            if line < end and self.empty(line):
                line += 1
                self.line = line


def _table(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    if start + 2 > end:
        return False
    nxt = start + 1
    if s.sc[nxt] < s.blk or s.sc[nxt] - s.blk >= 4:
        return False
    pos, mx = s.bm[nxt] + s.ts[nxt], s.em[nxt]
    if pos >= mx:
        return False
    first = s.src[pos]
    if first not in "|-:" or pos + 1 >= mx:
        return False
    second = s.src[pos + 1]
    if (second not in "|-:" and not _space(second)) or (first == "-" and _space(second)):
        return False
    if any(c not in "|-:" and not _space(c) for c in s.src[pos + 2:mx]):
        return False
    cells = s.text(nxt).split("|")
    aligns = 0
    for i, cell in enumerate(cells):
        t = _js_trim(cell)
        if not t:
            if i == 0 or i == len(cells) - 1:
                continue
            return False
        if not _DELIMITER_CELL_RE.match(t):
            return False
        aligns += 1
    head = _js_trim(s.text(start))
    if "|" not in head or s.sc[start] - s.blk >= 4:
        return False
    columns = len(_escaped_split(head))
    if columns == 0 or columns != aligns:
        return False
    if silent:
        return True
    old_parent, s.parent = s.parent, "table"
    autocompleted = 0
    nxt = start + 2
    while nxt < end:
        if s.sc[nxt] < s.blk or s.interrupts(_QUOTE_BREAKS, nxt, end):
            break
        row = _js_trim(s.text(nxt))
        if not row or s.sc[nxt] - s.blk >= 4:
            break
        autocompleted += columns - len(_escaped_split(row))
        if autocompleted > 65536:
            break
        nxt += 1
    s.parent = old_parent
    s.line = nxt
    return True


def _code(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    if s.sc[start] - s.blk < 4:
        return False
    nxt = last = start + 1
    while nxt < end:
        if s.empty(nxt):
            nxt += 1
        elif s.sc[nxt] - s.blk >= 4:
            nxt += 1
            last = nxt
        else:
            break
    s.line = last
    s.mark(start, last)
    return True


def _snippet(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    m = _SNIPPET_RE.match(s.text(start))
    if not m:
        return False
    if not silent:
        s.line = start + 1
        if "{monaco-write}" not in (m.group(4) or ""):  # that one is an editor
            s.mark(start, start + 1)
    return True


def _slot(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    if s.sc[start] - s.blk > 0 or not _SLOT_RE.match(s.text(start)):
        return False
    if not silent:
        s.line = start + 1
    return True


def _fence(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos, mx = s.bm[start] + s.ts[start], s.em[start]
    if s.sc[start] - s.blk >= 4 or pos + 3 > mx:
        return False
    marker = s.src[pos]
    if marker not in "~`":
        return False
    mem, pos = pos, s.skip_chars(pos, marker)
    size = pos - mem
    if size < 3 or (marker == "`" and "`" in s.src[pos:mx]):
        return False
    if silent:
        return True
    nxt, closed = start, False
    while True:
        nxt += 1
        if nxt >= end:
            break
        pos = mem = s.bm[nxt] + s.ts[nxt]
        mx = s.em[nxt]
        if pos < mx and s.sc[nxt] < s.blk:
            break
        if s.at(pos) != marker or s.sc[nxt] - s.blk >= 4:
            continue
        pos = s.skip_chars(pos, marker)
        if pos - mem < size or s.skip_spaces(pos) < mx:
            continue
        closed = True
        break
    s.line = nxt + (1 if closed else 0)
    s.mark(start, s.line)
    return True


def _blockquote(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos = s.bm[start] + s.ts[start]
    if s.sc[start] - s.blk >= 4 or s.at(pos) != ">":
        return False
    if silent:
        return True
    old_line_max, old_parent, s.parent = s.line_max, s.parent, "blockquote"
    saved: list[tuple[int, int, int, int]] = []  # (bm, bs, sc, ts) of the lines from `start` on
    last_empty = False
    nxt = start
    while nxt < end:
        outdented = s.sc[nxt] < s.blk
        pos, mx = s.bm[nxt] + s.ts[nxt], s.em[nxt]
        if pos >= mx:
            break
        if s.src[pos] == ">" and not outdented:
            pos += 1
            initial = s.sc[nxt] + 1
            adjust = space_after = False
            if s.at(pos) == " ":
                pos, initial, space_after = pos + 1, initial + 1, True
            elif s.at(pos) == "\t":
                space_after = True
                if (s.bs[nxt] + initial) % 4 == 3:
                    pos, initial = pos + 1, initial + 1
                else:
                    adjust = True
            offset = initial
            saved.append((s.bm[nxt], s.bs[nxt], s.sc[nxt], s.ts[nxt]))
            s.bm[nxt] = pos
            while pos < mx and _space(s.src[pos]):
                offset += 4 - (offset + s.bs[nxt] + (1 if adjust else 0)) % 4 if s.src[pos] == "\t" else 1
                pos += 1
            last_empty = pos >= mx
            s.bs[nxt] = s.sc[nxt] + 1 + (1 if space_after else 0)
            s.sc[nxt] = offset - initial
            s.ts[nxt] = pos - s.bm[nxt]
            nxt += 1
            continue
        if last_empty:
            break
        if s.interrupts(_QUOTE_BREAKS, nxt, end):
            s.line_max = nxt
            if s.blk != 0:
                saved.append((s.bm[nxt], s.bs[nxt], s.sc[nxt], s.ts[nxt]))
                s.sc[nxt] -= s.blk
            break
        saved.append((s.bm[nxt], s.bs[nxt], s.sc[nxt], s.ts[nxt]))
        s.sc[nxt] = -1  # a lazy line: text going on with a paragraph
        nxt += 1
    old_indent, s.blk = s.blk, 0
    s.level += 1
    s.tokenize(start, nxt)
    s.level -= 1
    s.line_max, s.parent = old_line_max, old_parent
    for i, (bm, bs, sc, ts) in enumerate(saved):
        s.bm[start + i], s.bs[start + i], s.sc[start + i], s.ts[start + i] = bm, bs, sc, ts
    s.blk = old_indent
    return True


def _math(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos, mx = s.bm[start] + s.ts[start], s.em[start]
    if pos + 2 > mx or s.src[pos:pos + 2] != "$$":
        return False
    if silent:
        return True
    found = _js_trim(s.src[pos + 2:mx])[-2:] == "$$"
    nxt = start
    while not found:
        nxt += 1
        if nxt >= end:
            break
        pos, mx = s.bm[nxt] + s.ts[nxt], s.em[nxt]
        if pos < mx and s.ts[nxt] < s.blk:
            break
        found = _js_trim(s.src[pos:mx])[-2:] == "$$"
    s.line = nxt + 1  # sic: the line that ended the block goes with it
    return True


def _hr(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos, mx = s.bm[start] + s.ts[start], s.em[start]
    marker = s.at(pos)
    if s.sc[start] - s.blk >= 4 or marker not in ("*", "-", "_"):
        return False
    count = 1
    for c in s.src[pos + 1:mx]:
        if c != marker and not _space(c):
            return False
        count += c == marker
    if count < 3:
        return False
    if not silent:
        s.line = start + 1
    return True


def _bullet(s: _Blocks, line: int) -> int:
    pos, mx = s.bm[line] + s.ts[line], s.em[line]
    if s.at(pos) not in ("*", "-", "+") or (pos + 1 < mx and not _space(s.src[pos + 1])):
        return -1
    return pos + 1


def _ordered(s: _Blocks, line: int) -> int:
    start = pos = s.bm[line] + s.ts[line]
    mx = s.em[line]
    if pos + 1 >= mx or not "0" <= s.src[pos] <= "9":
        return -1
    pos += 1
    while True:
        if pos >= mx:
            return -1
        c = s.src[pos]
        pos += 1
        if "0" <= c <= "9":
            if pos - start >= 10:
                return -1
            continue
        if c in ").":
            break
        return -1
    if pos < mx and not _space(s.src[pos]):
        return -1
    return pos


def _list(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    nxt = start
    if s.sc[nxt] - s.blk >= 4:
        return False
    if s.list_indent >= 0 and s.sc[nxt] - s.list_indent >= 4 and s.sc[nxt] < s.blk:
        return False  # a list marker indented 4 columns past its list is text
    interrupting = silent and s.parent == "paragraph" and s.sc[nxt] >= s.blk
    after = _ordered(s, nxt)
    if after >= 0:
        ordered = True
        if interrupting and int(s.src[s.bm[nxt] + s.ts[nxt]:after - 1]) != 1:
            return False
    else:
        after = _bullet(s, nxt)
        if after < 0:
            return False
        ordered = False
    if interrupting and s.skip_spaces(after) >= s.em[nxt]:
        return False
    if silent:
        return True
    marker = s.src[after - 1]
    old_parent, s.parent = s.parent, "list"
    s.level += 1
    while nxt < end:
        pos, mx = after, s.em[nxt]
        initial = offset = s.sc[nxt] + after - (s.bm[nxt] + s.ts[nxt])
        while pos < mx and _space(s.src[pos]):
            offset += 4 - (offset + s.bs[nxt]) % 4 if s.src[pos] == "\t" else 1
            pos += 1
        content = pos
        gap = 1 if content >= mx else offset - initial
        indent = initial + (1 if gap > 4 else gap)
        old_ts, old_sc, old_list_indent = s.ts[nxt], s.sc[nxt], s.list_indent
        s.list_indent, s.blk = s.blk, indent
        s.ts[nxt], s.sc[nxt] = content - s.bm[nxt], offset
        s.level += 1
        if content >= mx and s.empty(nxt + 1):
            s.line = min(s.line + 2, end)
        else:
            s.tokenize(nxt, end)
        s.level -= 1
        s.blk, s.list_indent = s.list_indent, old_list_indent
        s.ts[nxt], s.sc[nxt] = old_ts, old_sc
        nxt = s.line
        if nxt >= end or s.sc[nxt] < s.blk or s.sc[nxt] - s.blk >= 4 or s.interrupts(_LIST_BREAKS, nxt, end):
            break
        after = _ordered(s, nxt) if ordered else _bullet(s, nxt)
        if after < 0 or s.src[after - 1] != marker:
            break
    s.level -= 1
    s.line, s.parent = nxt, old_parent
    return True


def _footnote(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    first, mx = s.bm[start] + s.ts[start], s.em[start]
    if first + 4 > mx or s.src[first:first + 2] != "[^":
        return False
    pos = first + 2
    while pos < mx and s.src[pos] != "]":
        if s.src[pos] == " ":
            return False
        pos += 1
    if pos == first + 2 or pos + 1 >= mx or s.src[pos + 1] != ":":
        return False
    if silent:
        return True
    pos += 2
    old = (s.bm[start], s.ts[start], s.sc[start], s.parent)
    after_colon = pos
    initial = offset = s.sc[start] + pos - first
    while pos < mx and _space(s.src[pos]):
        offset += 4 - offset % 4 if s.src[pos] == "\t" else 1
        pos += 1
    s.ts[start], s.sc[start], s.bm[start] = pos - after_colon, offset - initial, after_colon
    s.blk += 4
    s.parent = "footnote"
    if s.sc[start] < s.blk:
        s.sc[start] += s.blk
    s.level += 1
    s.tokenize(start, end)
    s.level -= 1
    s.blk -= 4
    s.bm[start], s.ts[start], s.sc[start], s.parent = old
    return True


def _link_destination(st: str, start: int, mx: int) -> tuple[int, str] | None:
    pos = start
    if st[pos:pos + 1] == "<":
        pos += 1
        while pos < mx:
            c = st[pos]
            if c in "\n<":
                return None
            if c == ">":
                return pos + 1, _unescape(st[start + 1:pos])
            pos += 2 if c == "\\" and pos + 1 < mx else 1
        return None
    level = 0
    while pos < mx:
        c = st[pos]
        if c == " " or ord(c) < 0x20 or c == "\x7f":
            break
        if c == "\\" and pos + 1 < mx:
            if st[pos + 1] == " ":
                break
            pos += 2
            continue
        if c == "(":
            level += 1
            if level > 32:
                return None
        if c == ")":
            if level == 0:
                break
            level -= 1
        pos += 1
    if start == pos or level != 0:
        return None
    return pos, _unescape(st[start:pos])


def _link_title(st: str, start: int, mx: int, prev: dict | None) -> dict:
    """markdown-it's parseLinkTitle; ``text`` is kept raw (only whether it is empty matters here)."""
    pos = start
    res = {"ok": False, "more": False, "pos": 0, "text": "", "marker": ""}
    if prev:
        res["text"], res["marker"] = prev["text"], prev["marker"]
    else:
        if pos >= mx or st[pos] not in "\"'(":
            return res
        res["marker"] = ")" if st[pos] == "(" else st[pos]
        start, pos = start + 1, pos + 1
    while pos < mx:
        c = st[pos]
        if c == res["marker"]:
            res.update(pos=pos + 1, ok=True, text=res["text"] + st[start:pos])
            return res
        if c == "(" and res["marker"] == ")":
            return res
        if c == "\\" and pos + 1 < mx:
            pos += 1
        pos += 1
    res.update(more=True, text=res["text"] + st[start:pos])
    return res


def _reference(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos, mx = s.bm[start] + s.ts[start], s.em[start]
    if s.sc[start] - s.blk >= 4 or s.at(pos) != "[":
        return False
    nxt = start + 1

    def next_line(line: int) -> str | None:  # the next line, when the definition may go on there
        if line >= s.line_max or s.empty(line):
            return None
        if not (s.sc[line] - s.blk > 3 or s.sc[line] < 0):
            old, s.parent = s.parent, "reference"
            stop = s.interrupts(_PARAGRAPH_BREAKS, line, s.line_max)
            s.parent = old
            if stop:
                return None
        return s.src[s.bm[line] + s.ts[line]:s.em[line] + 1]

    st = s.src[pos:mx + 1]
    mx = len(st)

    def more() -> None:
        nonlocal st, mx, nxt
        tail = next_line(nxt)
        if tail is not None:
            st, nxt = st + tail, nxt + 1
            mx = len(st)

    label_end, pos = -1, 1
    while pos < mx:
        c = st[pos]
        if c == "[":
            return False
        if c == "]":
            label_end = pos
            break
        if c == "\n":
            more()
        elif c == "\\":
            pos += 1
            if pos < mx and st[pos] == "\n":
                more()
        pos += 1
    if label_end < 0 or st[label_end + 1:label_end + 2] != ":":
        return False
    pos = label_end + 2
    while pos < mx and (st[pos] == "\n" or _space(st[pos])):
        if st[pos] == "\n":
            more()
        pos += 1
    dest = _link_destination(st, pos, mx)
    if dest is None:
        return False
    url = _js_trim(dest[1]).lower()
    if _BAD_PROTO_RE.match(url) and not _GOOD_DATA_RE.match(url):
        return False
    pos = dest_end = dest[0]
    dest_line = nxt
    begin = pos
    while pos < mx and (st[pos] == "\n" or _space(st[pos])):
        if st[pos] == "\n":
            more()
        pos += 1
    title = _link_title(st, pos, mx, None)
    while title["more"]:
        tail = next_line(nxt)
        if tail is None:
            break
        st, pos, nxt = st + tail, mx, nxt + 1
        mx = len(st)
        title = _link_title(st, pos, mx, title)
    if pos < mx and begin != pos and title["ok"]:
        has_title, pos = bool(title["text"]), title["pos"]
    else:
        has_title, pos, nxt = False, dest_end, dest_line
    while pos < mx and _space(st[pos]):
        pos += 1
    if pos < mx and st[pos] != "\n" and has_title:  # text after the title: the definition ends before it
        pos, nxt = dest_end, dest_line
        while pos < mx and _space(st[pos]):
            pos += 1
    if (pos < mx and st[pos] != "\n") or not _js_trim(st[1:label_end]):
        return False
    if not silent:
        s.line = nxt
    return True


def _html(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos = s.bm[start] + s.ts[start]
    if s.sc[start] - s.blk >= 4 or s.at(pos) != "<":
        return False
    text = s.text(start)
    kind = next((i for i, h in enumerate(_HTML_BLOCKS) if h[0].match(text)), None)
    if kind is None:
        return False
    _, close, interrupts = _HTML_BLOCKS[kind]
    if silent:
        return interrupts
    nxt = start + 1
    if kind == _COMPONENT and _ONE_LINE_TAG.match(text):
        s.line = nxt
        return True
    if not (close and close.search(text)):
        while nxt < end and s.sc[nxt] >= s.blk:
            line = s.text(nxt)
            if close.search(line) if close else not line:
                nxt += 1 if line else 0
                break
            nxt += 1
    s.line = nxt
    return True


def _heading(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    pos, mx = s.bm[start] + s.ts[start], s.em[start]
    if s.sc[start] - s.blk >= 4 or s.at(pos) != "#" or pos >= mx:
        return False
    level = 1
    pos += 1
    while s.at(pos) == "#" and pos < mx and level <= 6:
        level += 1
        pos += 1
    if level > 6 or (pos < mx and not _space(s.at(pos))):
        return False
    if not silent:
        s.line = start + 1
    return True


def _setext(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    if s.sc[start] - s.blk >= 4:
        return False
    old_parent, s.parent = s.parent, "paragraph"
    level = 0
    nxt = start + 1
    while nxt < end and not s.empty(nxt):
        if s.sc[nxt] - s.blk <= 3:
            if s.sc[nxt] >= s.blk:
                pos, mx = s.bm[nxt] + s.ts[nxt], s.em[nxt]
                if pos < mx and s.src[pos] in "-=":
                    if s.skip_spaces(s.skip_chars(pos, s.src[pos])) >= mx:
                        level = 1 if s.src[pos] == "=" else 2
                        break
            if s.sc[nxt] >= 0 and s.interrupts(_PARAGRAPH_BREAKS, nxt, end):
                break
        nxt += 1
    s.parent = old_parent
    if not level:
        return False
    s.line = nxt + 1
    return True


def _paragraph(s: _Blocks, start: int, end: int, silent: bool) -> bool:
    old_parent, s.parent = s.parent, "paragraph"
    nxt = start + 1
    while nxt < end and not s.empty(nxt):
        if s.sc[nxt] - s.blk <= 3 and s.sc[nxt] >= 0 and s.interrupts(_PARAGRAPH_BREAKS, nxt, end):
            break
        nxt += 1
    s.line = nxt
    s.parent = old_parent
    return True


# markdown-it's block rules in Slidev's order, and the rules that may end a paragraph (or a link reference
# definition), a block quote's lazy text or a table, and a list
_RULES = (_table, _code, _snippet, _slot, _fence, _blockquote, _math, _hr, _list, _footnote, _reference, _html,
          _heading, _setext, _paragraph)
_PARAGRAPH_BREAKS = (_table, _snippet, _slot, _fence, _blockquote, _math, _hr, _list, _footnote, _html, _heading)
_QUOTE_BREAKS = (_snippet, _slot, _fence, _blockquote, _math, _hr, _list, _html, _heading)
_LIST_BREAKS = (_snippet, _slot, _fence, _blockquote, _math, _hr)


def code_lines(text: str) -> list[bool]:
    """For each line of a slide's Markdown, whether Slidev shows it as code: a line of a fenced code block
    (fences included), of an indented code block or a ``<<< file`` import, as markdown-exit set up as Slidev
    sets it up parses the slide (see the comment above). ``` in an HTML block (``<div>``, a component tag such
    as ``<v-click>`` up to the next blank line, …), a math block or a table is not a fence."""
    src = _NEWLINE_RE.sub("\n", text).replace("\0", "\ufffd")
    blocks = _Blocks(src)
    if src:
        blocks.tokenize(0, blocks.line_max)
    return blocks.code + [False] * (src.count("\n") + 1 - blocks.line_max)


def strip_code(text: str) -> str:
    """``text`` with the lines Slidev shows as code emptied (:func:`code_lines`)."""
    return "\n".join("" if code else line for line, code in zip(_NEWLINE_RE.split(text), code_lines(text)))


# --------------------------------------------------------------------------- decks


# Component tags as Slidev reads them. Its Markdown (@mdit-vue/plugin-component) hands a tag to Vue only where a
# complete open tag starts at the '<' (_OPEN_TAG: a name, attributes — name, or name=value with the value in quotes
# or free of ASCII spaces, control characters and "'=<>` —, an optional '/', then '>'); any other '<' is text, so
# `$a <b + 1$` starts no tag and does not run on to the next '>'. citations() tries a complete tag at every '<', also
# inside the quoted values of a complete tag: a '<' in a code span, in $…$ or after a backslash is text, and a tag
# inside quotes that open there is rendered. A '<' and a citing component's name that start no complete tag are
# reported: in a paragraph they are text, but in an HTML block Vue may render the tag (e.g. with a #slot attribute)
# unchecked. Vue ends a tag name at a space, \t, \n, \f, \r, '/' or '>' (_NAME_RE); component() resolves the name.
_TAG_RE = re.compile(rf"<([A-Za-z][A-Za-z0-9\-]*)({_ATTR}*){_S}*/?>")
_NAME_RE = re.compile(r"<([A-Za-z][A-Za-z0-9\-]*)(?=[\t\n\f\r />]|\Z)")
COMPONENTS = ("LeanBadge", "TheoremCard")
_ATTR_RE = re.compile(rf"{_S}+([a-zA-Z_:@][a-zA-Z0-9:._-]*)"  # one attribute of _ATTR: name, unquoted, '…', "…"
                      rf"(?:{_S}*={_S}*(?:([^\"'=<>`\x00-\x20]+)|'([^']*)'|\"([^\"]*)\"))?")
# The gid prop as Vue's compiler passes it: of the attributes that may set gid (gid, :gid and v-bind:gid with or
# without modifiers, v-model:gid) the first in the tag wins; citations() reads gid and a string literal in :gid or
# v-bind:gid and reports the others (also .prop and .attr, which set no prop) when they come first. A v-bind without
# an argument (v-bind="{…}", :="…", v-bind.prop=…) merges an object whose gid wins over the attributes before it:
# always reported. A v-on without one (v-on="{…}", @="…", v-on.x=…) starts a new group of props that Vue merges
# over the earlier ones (mergeProps), so the first gid source after it wins instead.
_GID_ATTR_RE = re.compile(r"gid|(?::|v-bind:|v-model:)gid(?:\..*)?")
_SPREAD_RE = re.compile(r"(?::|v-bind:?)(?:\..*)?")
_ON_SPREAD_RE = re.compile(r"(?:@|v-on:?)(?:\..*)?")
_ABS_LINK_RES = (
    re.compile(r"\b(?:href|src|poster|data)\s*=\s*[\"'](/(?!/)[^\"']*|file:[^\"']*)[\"']", re.I),
    re.compile(r"\]\((/(?!/)[^)\s]*|file:[^)\s]*)\)"),
    re.compile(r"url\(\s*[\"']?(/(?!/)[^\"')]*)", re.I),
)


@dataclass
class Citation:
    tag: str  # LeanBadge | TheoremCard
    gid: str
    attrs: dict[str, Any]


def component(tag: str) -> str:
    """The component name a template tag resolves to, as Vue resolves it (``capitalize(camelize(tag))``):
    ``lean-badge`` and ``leanBadge`` are ``LeanBadge``."""
    name = re.sub(r"-(\w)", lambda m: m.group(1).upper(), tag)
    return name[:1].upper() + name[1:]


def citations(content: str) -> tuple[list[Citation], list[str]]:
    """``<LeanBadge>`` / ``<TheoremCard>`` tags of a slide (in any spelling Vue accepts, e.g.
    ``<lean-badge>``) outside code blocks (:func:`code_lines`), in order, and problems found (see the
    comment above ``_TAG_RE``). ``Citation.tag`` is the PascalCase name, ``Citation.gid`` the gid as Vue passes it
    (``_GID_ATTR_RE``), "" where it cannot be read."""
    out: list[Citation] = []
    problems: list[str] = []
    text = strip_code(content)
    for lt in (i.start() for i in re.finditer("<", text)):
        m = _TAG_RE.match(text, lt)
        if not m:
            name = _NAME_RE.match(text, lt)
            if name and component(name.group(1)) in COMPONENTS:
                problems.append(f"<{name.group(1)} …> is not a complete tag (attributes are name or name=value, the "
                                "value in quotes or free of spaces and \"'=<>`), so it is not checked, yet Vue may "
                                "render it in an HTML block; write it as a complete tag")
            continue
        tag = component(m.group(1))
        if tag not in COMPONENTS:
            continue
        attrs: dict[str, Any] = {}
        first = None  # the attribute Vue takes gid from (_GID_ATTR_RE): name, value
        group = False  # a v-on object began a new group of props since: its first gid source wins
        for a in _ATTR_RE.finditer(m.group(2)):
            name = a.group(1)
            policy_prop = re.fullmatch(r"(?:(?::|v-bind:|v-model:))?(status|kind|cite|doi|source|request)(?:\..*)?", name)
            if policy_prop and (name != policy_prop[1] or name in attrs):
                problems.append(f'<{m.group(1)} {name}=…>: verification metadata must use one literal attribute per prop')
            attrs[name] = next((v for v in a.group(2, 3, 4) if v is not None), True)
            if _SPREAD_RE.fullmatch(name):
                problems.append(f"<{m.group(1)} {name}=…>: an object bound with v-bind can set gid, which cannot be "
                                "checked; bind each prop on its own")
            elif _ON_SPREAD_RE.fullmatch(name):
                group = True
            elif (first is None or group) and _GID_ATTR_RE.fullmatch(name):
                first, group = (name, attrs[name]), False
        gid = first[1] if first and first[0] == "gid" else ""
        if first and first[0] != "gid":
            name, expr = first[0], "true" if first[1] is True else first[1]  # as JavaScript's String() writes it
            lit = re.fullmatch(rf"{_S}*(['\"`])({_DOT}*)\1{_S}*", expr) if name in (":gid", "v-bind:gid") else None
            if lit:
                gid = lit.group(2)
            elif name in (":gid", "v-bind:gid"):
                problems.append(f"<{m.group(1)} {name}=\"{expr}\">: write gid as a literal string so it can be checked")
            else:
                problems.append(f"<{m.group(1)} {name}=\"{expr}\">: write gid=\"<GID>\" (or :gid with a literal "
                                "string, without modifiers) so it can be checked")
        out.append(Citation(tag, _js_trim(gid) if isinstance(gid, str) else "", attrs))
    return out, problems


@dataclass
class DeckEdition:
    lang: str
    path: Path
    slides: list[Slide]  # visible slides only
    head: dict[str, Any]
    issues: list[str] = field(default_factory=list)

    @property
    def meta(self) -> dict[str, Any]:
        deck = self.head.get("deck")
        return deck if isinstance(deck, dict) else {}

    @property
    def title(self) -> str:
        return str(self.head.get("title") or "")

    @property
    def deck_title(self) -> str:
        return str(self.meta.get("title") or self.title)

    @property
    def count(self) -> int:
        return len(self.slides)


def read_edition(book: config.Book, deck: str, lang: str) -> DeckEdition:
    if academic.is_academic(book.slides_dir / deck):
        data = academic.settings(book, deck)
        source = academic.read_source(book, deck, lang, data)
        title = data.get("title", {}).get(lang, deck)
        return DeckEdition(lang, source.path, [Slide(i + 1, 1, {}, "") for i in range(source.count)],
                           {"title": title, "deck": {"title": title, "version": book.version}})
    path = book.slides_dir / deck / edition_file(book, lang)
    all_slides = split_slides(path.read_text(encoding="utf-8"))
    head = all_slides[0].frontmatter if all_slides else {}
    ed = DeckEdition(lang=lang, path=path, slides=[s for s in all_slides if not s.hidden], head=head)
    for s in all_slides:
        if s.error:
            ed.issues.append(f"slide {s.index} (line {s.line}): frontmatter: {s.error}")
        if "src" in s.frontmatter:
            ed.issues.append(f"slide {s.index} (line {s.line}): src: imports slides from another file, which the "
                             "checks (Lean citations, page-for-page parity) do not read; write the slides in this file")
    return ed


def cited_gids(book: config.Book) -> list[tuple[Path, int, str]]:
    """(file, line, GID) for every GID the book's decks cite — for ``./tbook pin`` and the lock check."""
    out = []
    for deck in deck_names(book):
        if academic.is_academic(book.slides_dir / deck):
            try:
                out += academic.cited_gids(book, deck)
            except ValueError:
                pass  # check reports a malformed descriptor
            continue
        for lang in deck_langs(book, deck):
            ed = read_edition(book, deck, lang)
            for s in ed.slides:
                for c in citations(s.content)[0]:
                    if c.gid:
                        out.append((ed.path, s.line, c.gid))
    return out


# --------------------------------------------------------------------------- contract: check


def check_ref(book: config.Book, src: str) -> str | None:
    """Error message if ``::: {.slides src=…}`` does not name a deck of the book, else None."""
    src = (src or "").strip()
    if not src:
        return 'slides embed needs src="<deck>"'
    if not DECK_RE.match(src):
        return (f"slides src={src!r} must name a deck directory of this book (kebab-case), "
                f"i.e. books/{book.slug}/slides/<deck>/")
    d = book.slides_dir / src
    if not d.is_dir():
        return f"slides src={src!r}: books/{book.slug}/slides/{src}/ not found (create it: ./tbook slides new {book.slug} {src} \"<中文标题>\" \"<English title>\")"
    if academic.is_academic(d):
        try:
            data = academic.settings(book, src)
            for lang in data["editions"]:
                if not (d / academic.edition_file(data, lang)).is_file():
                    return f"academic deck {src}: missing {academic.edition_file(data, lang)}"
        except ValueError as exc:
            return str(exc)
        return None
    primary = book.languages[0]
    if not (d / edition_file(book, primary)).is_file():
        return f"slides src={src!r}: books/{book.slug}/slides/{src}/{edition_file(book, primary)} not found"
    return None


def check(book: config.Book) -> list[Issue]:
    """Validate ``books/<slug>/slides/``; returns ``tbook.model.Issue`` items."""
    issues: list[Issue] = []
    names = deck_names(book)
    if not names:
        return issues
    try:
        lock = lean.Lock.load()
    except lean.LeanError as exc:
        issues.append(Issue("error", paths.LOCK_FILE, 0, str(exc)))
        lock = None
    models: dict[str, Any] = {}

    def model_for(lang: str):
        if lang not in models:
            from .model import load_edition

            try:
                models[lang] = load_edition(book.edition(lang))
            except config.ConfigError:
                models[lang] = None
        return models[lang]

    for deck in names:
        d = book.slides_dir / deck
        if academic.is_academic(d):
            issues += academic.check_deck(book, deck, lock)
            continue
        err = lambda path, line, msg: issues.append(Issue("error", path, line, msg))  # noqa: E731
        if not DECK_RE.match(deck):
            err(d, 0, f"deck name {deck!r} must be kebab-case (a-z, 0-9, -)")
        if (d / "index.html").exists():
            err(d / "index.html", 0, "Slidev merges a deck's index.html into every page; delete it")
        langs = deck_langs(book, deck)
        primary = book.languages[0]
        for p in sorted(d.glob("slides.*.md")):
            if p.name == f"slides.{primary}.md":
                err(p, 0, f"{primary} is the book's first language, whose edition is {PRIMARY_FILE}; this file is "
                          f"never read (move its slides into {PRIMARY_FILE} and delete it)")
            elif not lang_of_file(book, p.name):
                err(p, 0, f"not an edition file: use {PRIMARY_FILE} ({primary}, the book's first language) "
                          "or slides.<lang>.md")
        for lang in langs:
            if lang not in book.languages:
                err(d / edition_file(book, lang), 0,
                    f"{lang!r} is not an edition of this book (book.toml editions: {', '.join(book.languages)})")
        for lang in book.languages:
            if lang not in langs:
                err(d, 0, f"deck {deck!r} has no {edition_file(book, lang)}: every deck has an edition for each "
                          f"language of the book ({', '.join(book.languages)}; {PRIMARY_FILE} is {primary}), page for page")
        eds = [read_edition(book, deck, lang) for lang in book.languages if lang in langs]
        if not eds:
            continue
        want_theme = theme_ref(d)
        cites: dict[str, list[list[Citation]]] = {}
        for ed in eds:
            for msg in ed.issues:
                err(ed.path, 0, msg)
            head_line = ed.slides[0].line if ed.slides else 1
            if ed.head.get("theme") != want_theme:
                err(ed.path, head_line, f"headmatter must say theme: {want_theme} (the shared slide theme)")
            if not ed.title:
                err(ed.path, head_line, "headmatter title is missing")
            elif re.search(r"[<>]|\{\{", ed.title):
                err(ed.path, head_line, "title must not contain <, > or {{ (Slidev renders it as a Vue template)")
            attrs = ed.head.get("htmlAttrs") if isinstance(ed.head.get("htmlAttrs"), dict) else {}
            if attrs.get("lang") != config.bcp47(ed.lang):
                err(ed.path, head_line, f'headmatter must set htmlAttrs.lang: "{config.bcp47(ed.lang)}" (the language of the file)')
            for key in ("code", "title", "version"):
                if not ed.meta.get(key):
                    err(ed.path, head_line, f"deck.{key} is missing (the slide header and footer show it)")
            if not ed.count:
                err(ed.path, 0, "the deck has no slides")
            cites[ed.lang] = []
            model = None
            for s in ed.slides:
                found, problems = citations(s.content)
                cites[ed.lang].append(found)
                for msg in problems:
                    err(ed.path, s.line, msg)
                text = strip_code(s.content)
                for rx in _ABS_LINK_RES:
                    for m in rx.finditer(text):
                        err(ed.path, s.line, f"link {m.group(1)} is absolute; the site is served under /<repo>/, "
                                             "use a relative or https:// link")
                for c in found:
                    _check_citation(c, ed, s, lock, err)
                    if c.tag == "TheoremCard" and c.attrs.get("cite"):
                        model = model or model_for(ed.lang)
                        _check_cite(c, ed, s, model, err)
        # page-for-page parity with the primary language
        main = eds[0]
        for ed in eds[1:]:
            if ed.count != main.count:
                err(ed.path, 0, f"{ed.count} slides, but {paths.rel(main.path)} has {main.count}; "
                                "editions correspond page for page")
            for key in ("code", "version"):
                if str(ed.meta.get(key, "")) != str(main.meta.get(key, "")):
                    err(ed.path, 0, f"deck.{key} is {ed.meta.get(key)!r}, {paths.rel(main.path)} has {main.meta.get(key)!r}")
            for i, (a, b) in enumerate(zip(main.slides, ed.slides), start=1):
                for key in ("layout", "bare", "chapter", "class"):
                    if str(a.frontmatter.get(key, "")) != str(b.frontmatter.get(key, "")):
                        err(ed.path, b.line, f"slide {i}: {key} is {b.frontmatter.get(key)!r}, "
                                             f"{paths.rel(main.path)} has {a.frontmatter.get(key)!r}")
                if bool(a.frontmatter.get("section")) != bool(b.frontmatter.get("section")):
                    err(ed.path, b.line, f"slide {i}: section is {'present' if b.frontmatter.get('section') else 'missing'}, "
                                         f"unlike {paths.rel(main.path)}")
                def citation_key(c):
                    base = c.gid or f"({c.attrs.get('status')})"
                    return base + (json.dumps([c.attrs.get(k) for k in ("cite", "doi", "source", "request")], ensure_ascii=False)
                                   if c.attrs.get("status") == "written-proof" else "")
                ga = [citation_key(c) for c in cites[main.lang][i - 1]]
                gb = [citation_key(c) for c in cites[ed.lang][i - 1]]
                if ga != gb:
                    err(ed.path, b.line, f"slide {i}: cites [{' '.join(gb)}], {paths.rel(main.path)} cites [{' '.join(ga)}]")
    return issues


def _check_citation(c: Citation, ed: DeckEdition, s: Slide, lock: lean.Lock | None, err) -> None:
    status = c.attrs.get("status")
    if status == "open" and c.gid:
        err(ed.path, s.line, f'<{c.tag} status="open"> must not cite Lean: open problems have no proof; drop gid')
    if status == "written-proof" and c.attrs.get("kind") not in (None, "theorem", "lemma", "proposition", "corollary"):
        err(ed.path, s.line, 'written-proof is only for formal results, not open items or definitions')
    if status == "written-proof" and "gid" in c.attrs:
        err(ed.path, s.line, f'<{c.tag} status="written-proof"> must not have gid; a written proof is not kernel verification')
    if status == "written-proof":
        if c.tag != "TheoremCard" or not c.attrs.get("cite"):
            err(ed.path, s.line, 'written-proof needs a TheoremCard with cite="<book-result-id>" and its associated book proof')
        if not evidence.doi_url(c.attrs.get("doi")):
            err(ed.path, s.line, 'written-proof requires a bare doi="10.<registrant>/<suffix>"')
        if not evidence.source_location(c.attrs.get("source")) or evidence.request_number(c.attrs.get("request")) is None:
            err(ed.path, s.line, 'written-proof requires source and a trureturing-requests issue URL')
    if status not in (None, "open", "argued", "written-proof"):
        err(ed.path, s.line, f'<{c.tag} status="{status}">: status is "open", "argued" or "written-proof"')
    if not c.gid:
        if not status:
            err(ed.path, s.line, f'<{c.tag}> needs gid="<GID>" (a frozen Lean declaration) or status="open|argued|written-proof"')
        return
    try:
        lean.parse_gid(c.gid)
    except lean.LeanError as exc:
        err(ed.path, s.line, str(exc))
        return
    res = lock.get(c.gid) if lock else None
    if res is None:
        err(ed.path, s.line, f"{c.gid} is not in trureturing.lock.json; slides may only cite declarations the lock "
                             "resolves (cite it in the book, then ./tbook pin --refresh)")
    elif c.attrs.get("kind") != "definition" and res.kind not in lean.FORMAL_KINDS:
        # LEAN ✓ means a kernel-checked theorem; a definition gets the neutral badge only with kind="definition"
        err(ed.path, s.line, f'{c.gid} is a Lean {res.kind}; a {c.tag} must cite a theorem (or say kind="definition")')


def _check_cite(c: Citation, ed: DeckEdition, s: Slide, model, err) -> None:
    """A TheoremCard with cite="<id>" must agree with that environment of the book."""
    cite = str(c.attrs["cite"]).lstrip("#")
    env = model.envs.get(cite) if model else None
    if env is None:
        err(ed.path, s.line, f'<TheoremCard cite="{cite}">: no environment #{cite} in the {ed.lang} edition of the book')
        return
    want = env.ref_text(ed.lang)
    label = str(c.attrs.get("label") or "")
    if label != want:
        err(ed.path, s.line, f'<TheoremCard cite="{cite}">: label is {label!r} but the book numbers it {want!r}')
    if c.gid and env.lean and c.gid not in env.lean:
        err(ed.path, s.line, f'<TheoremCard cite="{cite}">: cites {c.gid}, the book cites {" ".join(env.lean)}')
    if not c.gid and env.lean and c.attrs.get("status") != "argued":
        err(ed.path, s.line, f'<TheoremCard cite="{cite}">: the book cites {" ".join(env.lean)}; add gid')
    if (c.attrs.get("status") == "written-proof") != (env.status == "written-proof"):
        err(ed.path, s.line, f'<TheoremCard cite="{cite}">: written-proof status must agree with the book')
    if env.status == "written-proof":
        for key in ("doi", "source", "request"):
            if c.attrs.get(key) != env.attrs.get(key):
                err(ed.path, s.line, f'<TheoremCard cite="{cite}">: {key} must agree with the book')
    is_open = c.attrs.get("status") == "open"
    if is_open != (env.kind in OPEN):
        err(ed.path, s.line, f'<TheoremCard cite="{cite}">: #{cite} is a {env.kind}; '
                             + ('use status="open"' if env.kind in OPEN else 'only open problems take status="open"'))


# --------------------------------------------------------------------------- contract: items, embed


def items(book: config.Book) -> list[dict[str, Any]]:
    """Decks of the book for its landing page. Paths are relative to ``_site/<slug>/``."""
    site = config.load_site()
    out = []
    for deck in deck_names(book):
        langs = [lang for lang in deck_langs(book, deck) if lang in book.languages]
        if not langs:
            continue
        eds = {lang: read_edition(book, deck, lang) for lang in langs}
        primary = eds[langs[0]]
        out.append({
            "kind": "slides",
            "deck_kind": "academic" if academic.is_academic(book.slides_dir / deck) else "slidev",
            "id": deck,
            "languages": langs,
            "title": {lang: ed.deck_title for lang, ed in eds.items()},
            "full_title": {lang: ed.title for lang, ed in eds.items()},
            "info": {lang: str(ed.head.get("info") or "") for lang, ed in eds.items()},
            "blurb": {lang: str(ed.meta.get("blurb") or "") for lang, ed in eds.items()},
            "version": str(primary.meta.get("version") or ""),
            "slides": primary.count,
            "href": {lang: f"slides/{site_path(book, deck, lang)}" for lang in langs},
            "pdf": {lang: f"slides/{deck}/{pdf_name(book, deck, lang)}" for lang in langs},
            "pdf_name": {lang: pdf_name(book, deck, lang) for lang in langs},
            "notes_pdf": {lang: f"slides/{deck}/{pdf_name(book, deck, lang)[:-4]}-notes.pdf" for lang in langs}
                         if academic.is_academic(book.slides_dir / deck) else {},
            "url": {lang: public_url(site, book, deck, lang) for lang in langs},
            "index": "slides/index.html",
        })
    return out


def _deck_for_lang(book: config.Book, deck: str, lang: str) -> str | None:
    langs = deck_langs(book, deck)
    if lang in langs:
        return lang
    for other in book.languages:
        if other in langs:
            return other
    return None


def render_embed(env, ctx, inner: str, doc) -> str:
    """Replace ``::: {.slides src="<deck>"}``: a link card for mdBook, a short block for Pandoc.

    The card always links the deck's PDF; :func:`publish` removes that link from the published page
    when the PDF was not built (whether it is depends on the slides build, which may run later)."""
    src = (env.attrs.get("src") or "").strip()
    lang = ctx.lang
    inner = inner.strip("\n")
    book = ctx.book
    problem = check_ref(book, src)
    if problem:
        ctx.issues.append(f"{doc.path}: {problem}")
    deck_lang = _deck_for_lang(book, src, lang) if not problem else None
    ed = read_edition(book, src, deck_lang) if deck_lang else None
    title = (ed.title if ed else "") or src
    count = ed.count if ed else 0
    kind = config.s(lang, "ui.slides") or "Slides"
    if ctx.target == "mdbook":
        # the chapter page is _site/<slug>/<lang>/<chapter>.html; climb to _site/<slug>/
        depth = len(posixpath.dirname(doc.chapter.path or "").split("/")) if posixpath.dirname(doc.chapter.path or "") else 0
        up = "../" * (depth + 1)
        if not ed:
            return "\n".join([f'<aside class="tr-media tr-slides" data-slides="{esc(src)}">',
                              f'<p class="tr-media-kind">{esc(kind)}</p>',
                              f'<p><strong class="tr-media-title">{esc(src)}</strong> · {esc(t(lang, "not_built"))}</p>',
                              "", inner, "", "</aside>"])
        href = f"{up}slides/{site_path(book, src, deck_lang)}"
        pdf = f"{up}slides/{src}/{pdf_name(book, src, deck_lang)}"
        meta = f"{esc(kind)} · {esc(t(lang, 'pages', n=count))}"
        if deck_lang != lang:
            meta += f" · {esc(config.s(deck_lang, 'meta.name') or deck_lang)}"
        parts = [
            f'<aside class="tr-media tr-slides" data-slides="{esc(src)}" lang="{esc(config.bcp47(deck_lang))}">',
            f'<p class="tr-media-kind tr-media-caption">{meta}</p>',
            f'<p><a href="{esc(href)}"><strong class="tr-media-title">{esc(title)}</strong></a></p>',
        ]
        if inner:
            parts += ["", inner, ""]
        parts += [
            f'<div class="tr-media-links"><a href="{esc(href)}">{esc(t(lang, "present"))} ↗</a>'
            f'<a href="{esc(pdf)}" download>{esc(t(lang, "pdf"))}</a></div>',
            "</aside>",
        ]
        if academic.is_academic(book.slides_dir / src):
            notes = pdf[:-4] + "-notes.pdf"
            parts.insert(-1, f'<p><a href="{esc(notes)}" download>{esc(t(lang, "notes_pdf"))}</a></p>')
        return "\n".join(parts)
    # pandoc (PDF / EPUB): the title, the caption and the public URL (absolute; empty base_url → site path)
    url = public_url(ctx.site, book, src, deck_lang or lang)
    where = f"<{url}>" if url else f"`{book.slug}/slides/{site_path(book, src, deck_lang or lang)}`"
    sep = "" if lang.startswith(("zh", "ja")) else " "
    head = f"**{kind} · {title}**"
    if count:
        pages = t(lang, "pages", n=count)
        head += f"（{pages}）" if lang.startswith(("zh", "ja")) else f" ({pages})"
    lines = ["::: {.tr-media .tr-slides}", head, ""]
    if inner:
        lines += [inner, ""]
    lines += [f"{t(lang, 'static_note')}{sep}{where}", ":::"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- contract: build, publish


def _node() -> str:
    node = os.environ.get("NODE") or shutil.which("node")
    if not node:
        raise RuntimeError("node not found: install Node >= 22.12 and run `npm ci` (slides need Slidev and Playwright)")
    return node


def build(site: config.Site, book: config.Book, out_dir: Path) -> Path | None:
    """Build every deck of the book into ``out_dir`` (``build/slides/<slug>``): HTML per language,
    browser checks, PDFs; nothing when the decks' inputs did not change (:mod:`tbook.buildcache`).
    Environment: ``PW_CHROMIUM_PATH`` (Chromium binary), ``TBOOK_SLIDES_NO_PDF=1`` (skip PDF export),
    ``TBOOK_SLIDES_NO_CHECK=1`` (skip browser checks), ``NODE`` (node binary)."""
    from . import buildcache

    if not deck_names(book):
        print(f"  {book.slug}: no slides", flush=True)
        return None
    unit = buildcache.slides_unit(site, book, out_dir)
    done = (unit.key, str(Path(out_dir).resolve()))
    if done in _BUILT and Path(out_dir).is_dir():  # built or restored earlier in this process (build, then publish)
        return Path(out_dir)
    buildcache.run(unit, lambda: _build(site, book, out_dir))
    _BUILT.add(done)
    return Path(out_dir)


# (key, output directory) of the decks build() produced in this process: `./tbook build all` builds them,
# then the site step publishes them through build() again, which must not build them a second time when
# the cache is off (TBOOK_CACHE=0) or could not store them.
_BUILT: set[tuple[str, str]] = set()


def _build(site: config.Site, book: config.Book, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    if out_dir.exists():  # a fresh build: no deck or PDF of an earlier one stays behind
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slidev = [d for d in deck_names(book) if not academic.is_academic(book.slides_dir / d)]
    if slidev:
        _build_slidev(site, book, out_dir)
    manifest = read_manifest(out_dir) or {"schema": MANIFEST_SCHEMA, "book": book.slug,
                                       "base": base_path(site), "decks": {}}
    for deck in deck_names(book):
        if academic.is_academic(book.slides_dir / deck):
            manifest["decks"][deck] = academic.build_deck(site, book, deck, out_dir)
    (out_dir / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_slidev(site, book, out_dir):
    cmd = [_node(), str(paths.TOOLS / "node" / "slides-build.mjs"), "--book", book.slug,
           "--out", str(Path(out_dir).resolve()), "--base", base_path(site)]
    if os.environ.get("TBOOK_SLIDES_NO_PDF") == "1":
        cmd.append("--no-pdf")
    if os.environ.get("TBOOK_SLIDES_NO_CHECK") == "1":
        cmd.append("--no-check")
    env = dict(os.environ, TBOOK_ROOT=str(paths.ROOT))
    if site.base_url:
        env.setdefault("TBOOK_BASE_URL", site.base_url)
    r = subprocess.run(cmd, cwd=paths.ROOT, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"slides of {book.slug}: tools/node/slides-build.mjs exited with {r.returncode} (see above)")


def read_manifest(out_dir: Path) -> dict[str, Any] | None:
    f = Path(out_dir) / MANIFEST
    if not f.is_file():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    return data if data.get("schema") == MANIFEST_SCHEMA else None


def _stale(book: config.Book, out_dir: Path, manifest: dict[str, Any] | None, base: str) -> str:
    """Why the build in ``out_dir`` cannot be published as it is ('' when it can). Each edition is built for
    its path on the site (its links and language switcher say so): the site's base path, ``<deck>/`` for the
    book's first language and ``<deck>/<lang>/`` for the others, and the deck's languages."""
    if manifest is None:
        return f"{paths.rel(out_dir)} has no build"
    if manifest.get("base") != base:
        return f"{paths.rel(out_dir)} was built for base {manifest.get('base')!r}, the site uses {base!r}"
    for deck in deck_names(book):
        built = manifest.get("decks", {}).get(deck, {}).get("langs", {})
        langs = [lang for lang in deck_langs(book, deck) if lang in book.languages]
        for lang in langs:
            info = built.get(lang)
            if not info or not (out_dir / info["dir"] / "index.html").is_file():
                return f"{deck} ({lang}) is not built"
            want = site_path(book, deck, lang)
            if info.get("site_path") != want:
                return (f"{deck} ({lang}) was built for {info.get('site_path')!r}, the site uses {want!r} "
                        f"({book.languages[0]} is the book's first language)")
            if academic.is_academic(book.slides_dir / deck):
                for key in ("pdf", "notes_pdf"):
                    if not info.get(key) or not (out_dir / info[key]).is_file():
                        return f"academic deck {deck} ({lang}) is missing its {key}"
        gone = sorted(set(built) - set(langs))
        if gone:
            return f"{deck} was built with {', '.join(gone)} as well, which is no longer an edition of it"
    return ""


def publish(site: config.Site, book: config.Book, site_dir: Path, *, build_missing: bool = True) -> list[dict[str, Any]]:
    """Copy the built decks into ``site_dir`` (``_site/<slug>/slides/``) and write its ``index.html``.

    The book's first language goes to ``<deck>/``, other languages to ``<deck>/<lang>/``, PDFs to
    ``<deck>/<slug>-<deck>-<lang>.pdf``; chapter pages already in ``site_dir.parent/<lang>/`` lose their
    links to PDFs that were not built.
    The decks are built first (:func:`build`, which only restores the stored build when their inputs did
    not change), unless ``build_missing`` is False: then a build that does not fit the site (another base
    path or first language, other languages: :func:`_stale`) is a RuntimeError. Returns :func:`items` for
    the published decks.
    """
    names = deck_names(book)
    if not names:
        return []
    out = build_dir(book)
    base = base_path(site)
    if build_missing:
        build(site, book, out)
    manifest = read_manifest(out)
    why = _stale(book, out, manifest, base)
    if why:
        if not build_missing:
            raise RuntimeError(f"slides of {book.slug}: {why}; run ./tbook build slides --book {book.slug}")
        raise RuntimeError(f"slides of {book.slug}: {why} after building")
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    for deck in names:
        target = site_dir / deck
        if target.exists():
            shutil.rmtree(target)
        built = manifest["decks"][deck]["langs"]
        # primary language first: the other languages are published inside its directory
        for lang in [lang for lang in book.languages if lang in deck_langs(book, deck)]:
            info = built[lang]
            shutil.copytree(out / info["dir"], site_dir / info["site_path"], dirs_exist_ok=True)
            if info.get("pdf") and (out / info["pdf"]).is_file():
                shutil.copy2(out / info["pdf"], site_dir / deck / pdf_name(book, deck, lang))
            if info.get("notes_pdf") and (out / info["notes_pdf"]).is_file():
                shutil.copy2(out / info["notes_pdf"], site_dir / deck / (pdf_name(book, deck, lang)[:-4] + "-notes.pdf"))
    published = items(book)
    for it in published:
        it["built_pdf"] = {lang: (site_dir / it["id"] / it["pdf_name"][lang]).is_file() for lang in it["languages"]}
    (site_dir / "index.html").write_text(index_html(site, book, published), encoding="utf-8")
    _drop_unpublished_pdf_links(book, site_dir.parent, published)
    return published


def _drop_unpublished_pdf_links(book: config.Book, book_site: Path, decks: list[dict[str, Any]]) -> None:
    """Remove chapter-card links (:func:`render_embed`) to deck PDFs that were not published, e.g. after a
    ``TBOOK_SLIDES_NO_PDF=1`` slides build. The site assembler copies the book's HTML to
    ``_site/<slug>/<lang>/`` before it publishes the slides, so the pages are already there."""
    missing = [f"slides/{it['id']}/{it['pdf_name'][lang]}" for it in decks for lang in it["languages"]
               if not it["built_pdf"].get(lang)]
    if not missing:
        return
    link = re.compile(r'<a\b[^>]*\bhref="(?:\.\./)*(?:' + "|".join(re.escape(m) for m in missing) + r')"[^>]*>[^<]*</a>')
    for lang in book.languages:
        root = book_site / lang
        for page in sorted(root.rglob("*.html")) if root.is_dir() else []:
            text = page.read_text(encoding="utf-8")
            new = link.sub("", text)
            if new != text:
                page.write_text(new, encoding="utf-8")


def index_html(site: config.Site, book: config.Book, decks: list[dict[str, Any]]) -> str:
    """The bilingual slides index of a book (``_site/<slug>/slides/index.html``); Chinese by default."""
    langs = list(book.languages)
    primary = langs[0]

    def pair(fn) -> str:
        texts = [(lang, fn(lang)) for lang in langs]
        if len({text for _, text in texts}) == 1:
            return esc(texts[0][1])
        return "".join(f'<span class="l-{esc(lang)}" lang="{esc(config.bcp47(lang))}">{esc(text)}</span>'
                       for lang, text in texts)

    tokens = (paths.GENERATED / "tokens.css").read_text(encoding="utf-8") if (paths.GENERATED / "tokens.css").is_file() else ""
    lock = None
    try:
        lock = lean.Lock.load()
    except lean.LeanError:
        pass
    cards = []
    for d in decks:
        rows = []
        for lang in d["languages"]:
            links = [f'<a href="{esc(site_path(book, d["id"], lang))}">{esc(t(lang, "present"))} ↗</a>']
            if d.get("built_pdf", {}).get(lang, True):
                links.append(f'<a href="{esc(d["id"])}/{esc(d["pdf_name"][lang])}" download>{esc(t(lang, "pdf"))}</a>')
            if lang in d.get("notes_pdf", {}):
                links.append(f'<a href="{esc(d["id"])}/{esc(d["pdf_name"][lang][:-4])}-notes.pdf" download>{esc(t(lang, "notes_pdf"))}</a>')
            rows.append(f'<p class="links" lang="{esc(config.bcp47(lang))}"><span class="ln">'
                        f'{esc(config.s(lang, "meta.name") or lang)}</span><span class="lk">{"".join(links)}</span></p>')
        blurb = pair(lambda lang, d=d: d["blurb"].get(lang) or d["info"].get(lang) or "")
        cards.append(
            f'<article class="deck">\n'
            f'  <p class="kind">{pair(lambda lang: config.s(lang, "ui.slides") or "Slides")} · '
            f'{pair(lambda lang, d=d: t(lang, "pages", n=d["slides"]))}'
            f'{" · <span class=ver>v" + esc(d["version"]) + "</span>" if d["version"] else ""}</p>\n'
            f'  <h2>{pair(lambda lang, d=d: d["title"].get(lang, d["id"]))}</h2>\n'
            f'  <p class="blurb">{blurb}</p>\n  ' + "\n  ".join(rows) + "\n</article>"
        )
    body = "\n".join(cards) or f"<p>{pair(lambda lang: t(lang, 'none'))}</p>"
    toggle = "".join(f'<button type="button" data-set-lang="{esc(lang)}">{esc(config.s(lang, "meta.short") or lang.upper())}</button>'
                     for lang in langs) if len(langs) > 1 else ""
    hide = "\n".join(f':root[data-lang="{lang}"] [class^="l-"]:not(.l-{lang}) {{ display: none; }}' for lang in langs)
    hide_default = f':root:not([data-lang]) [class^="l-"]:not(.l-{primary}) {{ display: none; }}'
    commit = (f'<p class="pin">{pair(lambda lang: config.s(lang, "ui.pinned_at"))} '
              f'<a href="{esc(lock.tree_url)}"><code>{esc(lock.commit[:12])}</code></a></p>') if lock else ""
    from .site import _google_fonts  # theme/tokens.json font.google-fonts-css, as the other pages use

    fonts_css = _google_fonts()
    fonts_head = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                  '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
                  f'<link rel="stylesheet" href="{esc(fonts_css)}">\n') if fonts_css else ""
    title_text = " · ".join(dict.fromkeys(f"{book.edition(lang).title} · {config.s(lang, 'ui.slides') or 'Slides'}" for lang in langs))
    return f"""<!doctype html>
<html lang="{esc(config.bcp47(primary))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title_text)}</title>
{fonts_head}<style>
/* colours: theme/generated/tokens.css (generated from theme/tokens.json) */
{tokens}
/* English (any language but Chinese, Japanese, Korean): a Latin face first, as on the site (theme/site/site.css) */
:not(:lang(zh), :lang(ja), :lang(ko)) {{ --tr-font-body: var(--tr-font-body-latin); }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; background: var(--tr-void); background-image: var(--tr-fx-aurora); color: var(--tr-ink);
  font: 16px/1.65 var(--tr-font-body); }}
body::before {{ content: ""; position: fixed; inset: 0; pointer-events: none; background: var(--tr-fx-scanlines); }}
main {{ position: relative; max-width: 880px; margin: 0 auto; padding: 40px 16px 64px; }}
a {{ color: var(--tr-sem-link); text-underline-offset: 3px; }}
a:focus-visible, button:focus-visible {{ outline: 2px solid var(--tr-sem-now); outline-offset: 2px; }}
nav.top {{ display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; justify-content: space-between; font: 13px/1.6 var(--tr-font-data); }}
nav.top .crumbs a {{ color: var(--tr-dim); text-decoration: none; margin-right: 16px; }}
nav.top .crumbs a:hover {{ color: var(--tr-cyan); }}
.langs {{ display: inline-flex; border: 1px solid var(--tr-line-hot); }}
.langs button {{ background: transparent; border: 0; color: var(--tr-dim); cursor: pointer; font: 600 12px/1 var(--tr-font-data); letter-spacing: .08em; padding: 6px 10px; }}
.langs button + button {{ border-left: 1px solid var(--tr-line-hot); }}
.langs button[aria-pressed="true"] {{ background: var(--tr-cyan); color: var(--tr-on-accent); }}
header {{ margin: 36px 0 28px; }}
.code {{ display: inline-block; font: 700 13px/1 var(--tr-font-display); letter-spacing: .22em; color: var(--tr-cyan);
  border: 1px solid var(--tr-line-hot); padding: 7px 12px; text-shadow: var(--tr-fx-glow-cyan); }}
h1 {{ font: 700 clamp(28px, 6vw, 40px)/1.2 var(--tr-font-display); margin: 18px 0 6px; }}
h1 .k {{ color: var(--tr-cyan); }}
.sub {{ color: var(--tr-dim); margin: 0; }}
.deck {{ position: relative; margin: 18px 0; padding: 20px 22px 16px; background: var(--tr-panel); border: 1px solid var(--tr-panel-edge);
  border-inline-start: 3px solid var(--tr-magenta); clip-path: var(--tr-fx-cut-corner); }}
.kind {{ margin: 0; font: 500 12px/1.6 var(--tr-font-data); letter-spacing: .14em; text-transform: uppercase; color: var(--tr-dim); }}
.kind .ver {{ text-transform: none; }}
h2 {{ font: 600 22px/1.35 var(--tr-font-display); margin: 6px 0 4px; }}
.blurb {{ margin: 0 0 10px; color: var(--tr-ink); opacity: .86; }}
.links {{ display: flex; align-items: baseline; gap: 16px; margin: 6px 0 0; }}
.links .ln {{ flex: none; width: 64px; font: 12px/1.6 var(--tr-font-data); color: var(--tr-dim); letter-spacing: .06em; }}
.links .lk {{ display: flex; flex-wrap: wrap; gap: 4px 16px; min-width: 0; }}
.links a {{ font: 600 14px/1.5 var(--tr-font-display); letter-spacing: .04em; text-decoration: none; border-bottom: 1px solid var(--tr-line-hot); }}
.links a:hover {{ color: var(--tr-ink); border-bottom-color: var(--tr-cyan); }}
footer {{ margin-top: 36px; color: var(--tr-dim); font-size: 14px; }}
footer p {{ margin: 4px 0; }}
.pin code {{ font-family: var(--tr-font-data); color: var(--tr-sigma); }}
{hide_default}
{hide}
</style>
</head>
<body>
<main>
<nav class="top">
  <span class="crumbs"><a href="../">← {pair(lambda lang: t(lang, "back_to_book"))}</a><a href="../../">{pair(lambda lang: config.s(lang, "ui.back_to_library"))}</a></span>
  {f'<span class="langs" role="group">{toggle}</span>' if toggle else ""}
</nav>
<header>
  <span class="code">{esc(book.code)}</span>
  <h1>{pair(lambda lang: book.edition(lang).title)} <span class="k">· {pair(lambda lang: config.s(lang, "ui.slides") or "Slides")}</span></h1>
  <p class="sub">{pair(lambda lang: book.edition(lang).subtitle)}</p>
</header>
{body}
<footer>
  <p>{pair(lambda lang: t(lang, "keys"))}</p>
  {commit}
  <p>{pair(lambda lang: config.s(lang, "ui.generated_note"))}</p>
</footer>
</main>
<script>
(function () {{
  var langs = {json.dumps(langs)}, root = document.documentElement, key = "tr-lang";
  function set(lang, save) {{
    if (langs.indexOf(lang) < 0) return;
    root.setAttribute("data-lang", lang);
    root.lang = {json.dumps({lang: config.bcp47(lang) for lang in langs}, ensure_ascii=False)}[lang];
    document.querySelectorAll("[data-set-lang]").forEach(function (b) {{ b.setAttribute("aria-pressed", String(b.getAttribute("data-set-lang") === lang)); }});
    if (save) {{ try {{ localStorage.setItem(key, lang); }} catch (e) {{}} }}
  }}
  var q = new URLSearchParams(location.search).get("lang"), stored = null;
  try {{ stored = localStorage.getItem(key); }} catch (e) {{}}
  set(q || stored || langs[0], !!q);
  document.querySelectorAll("[data-set-lang]").forEach(function (b) {{
    b.addEventListener("click", function () {{ set(b.getAttribute("data-set-lang"), true); }});
  }});
}})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- contract: cli


def _list(books: list[config.Book]) -> int:
    found = False
    for book in books:
        for it in items(book):
            found = True
            langs = ", ".join(f"{lang}: {it['full_title'][lang]}" for lang in it["languages"])
            print(f"{book.slug}/{it['id']}  {it['slides']} slides  [{langs}]")
    if not found:
        print("no slide decks")
    return 0


def cli(args) -> int:
    """``./tbook slides new <book> <deck> "<中文标题>" "<English title>"`` and ``./tbook slides list [<book>]``."""
    rest = [a for a in (getattr(args, "rest", None) or []) if a != "--"]
    if args.action == "snapshots":
        return academic.snapshots(config.load_books(rest or None))
    if args.action == "list":
        return _list(config.load_books(rest or None))
    if args.action == "new":
        if "--academic" in rest:
            return academic.scaffold(rest)
        if len(rest) not in (3, 4):
            print('usage: ./tbook slides new <book> <deck> "<中文标题>" "<English title>"', file=sys.stderr)
            return 2
        config.named_book(rest[0])  # clear error for an unknown or hidden book
        cmd = [_node(), str(paths.TOOLS / "node" / "slides-new.mjs"), *rest]
        return subprocess.run(cmd, cwd=paths.ROOT, env=dict(os.environ, TBOOK_ROOT=str(paths.ROOT))).returncode
    print(f"tbook slides: unknown action {args.action!r} (new, list)", file=sys.stderr)
    return 2
