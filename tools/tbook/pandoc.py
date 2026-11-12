"""PDF (Pandoc → Typst) and EPUB 3 (Pandoc, for Apple Books) pipeline.

Both outputs share one staging directory, ``build/stage/<slug>/<lang>/pandoc/``::

    book.md          every chapter in SUMMARY order (drafts skipped) + the verification ledger
    _book/…          files the chapters link to (book assets, edition-local images), by their
                     path relative to the book directory
    _theme/…         copies of theme/typst/*, theme/generated/tokens.typ and derived code themes
    meta.json        book/edition metadata read by theme/typst/book.typ
    main.typ         Pandoc's Typst output (PDF)
    cover.png        the EPUB cover (1600×2560, tbook.cover.render_cover)
    epub/…           EPUB-only inputs: stylesheet, metadata, colophon; pandoc.epub before post-processing

Staging (:func:`stage`):

* each chapter goes through :func:`tbook.render.chapter_markdown` with ``target="pandoc"``
  (environment divs, ``[@id]`` references, Lean permalinks, ``_book/`` paths);
* the chapter title (its first level-1 heading, or the SUMMARY title when the file has
  none) gets a stable id (``ch-<file stem>`` unless it has one) and ``.tr-chapter``
  attributes; prefix/suffix chapters are ``.unnumbered``; nested chapters (depth > 0)
  have every heading shifted down by their depth; SUMMARY part titles become
  ``.tr-part`` headings;
* chapters are separate pages in HTML but one document here, so names that are only unique
  per chapter are scoped: footnote labels become ``[^<chapter id>--<label>]``
  (:func:`scope_footnotes`, only where mdBook reads a footnote), and every heading without
  an explicit id gets one (:func:`heading_slugs` — its mdBook id, formulas counted as the
  text KaTeX shows and footnote references as their numbers in the chapter, or
  ``<chapter id>--<slug>`` when another chapter already uses that slug); ``{-}`` is read as
  ``.unnumbered``, and a heading, a ``:::`` div opener or a footnote definition right under
  a line of text gets a blank line before it so Pandoc reads it as one;
* fenced and indented code blocks, HTML comments and inline code are never rewritten
  (:func:`_code_mask`);
* links between chapter files (``other.md``, ``other.md#x``, ``#x``) become internal ``#ids``
  (a fragment resolves within the linked chapter, as in HTML; one that chapter lacks is
  rendered as text with a warning); relative images of
  nested chapters are rebased onto the staging root and files inside the edition are
  copied to ``_book/<lang>/…`` (looked up by the decoded path, so ``<a b.png>`` and
  ``a%20b.png`` both work, and written percent-encoded); plain links to files (not
  images) cannot work inside a PDF or EPUB, so they point to the file's published copy
  on the site (``site.book_url``) or, without a known base URL, are dropped with a
  warning (their text is kept);
* :data:`tbook.mathrender.TEX_MACROS` is written at the top as ``\\newcommand`` definitions
  (expanded by Pandoc's ``latex_macros``; tr-env.lua gets them as ``tr-tex-macros`` for
  environment titles), so macros render as they do in HTML;
* the ledger from :func:`tbook.ledger.ledger_markdown` is appended as the last,
  unnumbered back-matter chapter.

The reader is Pandoc Markdown without ``citations``: ``[@id]`` is resolved by
:mod:`tbook.render` before Pandoc runs, and a bare ``@word`` in prose is text.

Rendering: ``tools/filters/tr-book.lua`` (book structure) and ``tools/filters/tr-env.lua``
(environments) run inside Pandoc. The PDF is compiled by the ``typst`` Python module with
``theme/typst/book.typ`` (``sys.inputs["tr-variant"]`` = ``screen`` | ``print`` | ``academic``); the EPUB
is written by Pandoc with ``theme/epub/book.css`` and post-processed for Apple Books
(``META-INF/com.apple.ibooks.display-options.xml``, deterministic zip) and validated with
epubcheck when Java is available.

Environment variables: ``TBOOK_EPUBCHECK`` (``1`` default: validate and fail on errors;
``warn``: report only; ``0``: skip), ``SOURCE_DATE_EPOCH`` (overrides the date derived
from ``book.date``).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import unicodedata
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

from . import config, lean, ledger, mathrender, mdscan, paths, render
from .model import OPEN, EditionModel, Env, load_edition
from .summary import chapter_prefix

# No `citations`: [@id] references are resolved by tbook.render before Pandoc runs, and a
# bare "@word" (or a leftover "[@x]") must stay text instead of becoming a Typst #cite.
READER = "markdown+gfm_auto_identifiers-citations"
FILTERS = paths.TOOLS / "filters"
TYPST_THEME = paths.THEME / "typst"
EPUB_THEME = paths.THEME / "epub"
FONT_CACHE = paths.CACHE / "fonts"
THEME_FONTS = TYPST_THEME / "fonts"


class PandocError(RuntimeError):
    pass


# --------------------------------------------------------------------------- strings
#
# Strings used only by the PDF/EPUB front matter. A key present in theme/i18n/<lang>.toml
# (or the downstream i18n/<lang>.toml) wins; these tables are the fallback until the keys
# are merged into the shared i18n files. Languages other than zh fall back to en.

LOCAL_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "pdf.colophon": "版权信息",
        "pdf.abstract": "摘要",
        "pdf.date": "日期",
        "pdf.authors": "作者",
        "pdf.license": "许可",
        "pdf.isbn": "ISBN",
        "pdf.publisher": "出版",
        "pdf.edition": "版本说明",
        "pdf.variant_screen": "屏幕版（深色）",
        "pdf.variant_print": "印刷版（浅色）",
        "pdf.variant_academic": "学术预印本",
        "pdf.typeset": "排版",
        "pdf.typeset_value": "Pandoc 与 Typst，由 trureturing 书籍模板构建",
        "pdf.source": "源文件",
        "pdf.online": "在线阅读",
        "pdf.verified_statement": "本书共有 {n} 条形式结论（定理、引理、命题、推论），每一条都引用 trureturing 中已由 Lean 内核验证并冻结的声明；书末“形式化验证账本”逐条列出对应关系与永久链接。",
        "pdf.no_formal": "本书没有形式结论。",
        "pdf.open_statement": "明确标为开放的问题与猜想：{n} 条。书中不把它们当作已证结论使用。",
        "pdf.lean_label": "Lean",
        "cover.series": "TRURETURING · 形式化专著",
        "cover.stamp_caption": "条形式结论 · 内核验证",
        "cover.pinned": "冻结于",
        "epub.colophon": "版权信息",
    },
    "en": {
        "pdf.colophon": "Colophon",
        "pdf.abstract": "Abstract",
        "pdf.date": "Date",
        "pdf.authors": "Authors",
        "pdf.license": "License",
        "pdf.isbn": "ISBN",
        "pdf.publisher": "Published by",
        "pdf.edition": "Edition",
        "pdf.variant_screen": "Screen edition (dark)",
        "pdf.variant_print": "Print edition (light)",
        "pdf.variant_academic": "Research preprint",
        "pdf.typeset": "Typeset with",
        "pdf.typeset_value": "Pandoc and Typst, built with the trureturing books template",
        "pdf.source": "Source",
        "pdf.online": "Read online",
        "pdf.verified_statement": "Formal results in this book (theorems, lemmas, propositions and corollaries): {n}. Each one cites a declaration in trureturing that the Lean kernel has verified and that is frozen; the verification ledger at the end lists them with permanent links.",
        "pdf.no_formal": "This book states no formal results.",
        "pdf.open_statement": "Open problems and conjectures, explicitly marked as such: {n}. The book never uses them as proved.",
        "pdf.lean_label": "Lean",
        "cover.series": "TRURETURING · FORMAL MONOGRAPH",
        "cover.stamp_caption": "formal results · kernel-verified",
        "cover.pinned": "frozen at",
        "epub.colophon": "Colophon",
    },
}


def t(lang: str, key: str, **fmt) -> str:
    """Localized string: shared i18n first, then :data:`LOCAL_STRINGS` (zh/en)."""
    text = config.s(lang, key)
    if not text:
        table = LOCAL_STRINGS.get(lang) or LOCAL_STRINGS.get(lang.split("-")[0]) or LOCAL_STRINGS["en"]
        text = table.get(key) or LOCAL_STRINGS["en"].get(key, key)
    return text.format(**fmt) if fmt else text


# --------------------------------------------------------------------------- tools


def pandoc_path() -> str:
    """The Pandoc executable: $PANDOC, the pypandoc_binary copy, then PATH."""
    env = os.environ.get("PANDOC")
    if env:
        return env
    try:
        import pypandoc  # type: ignore

        return pypandoc.get_pandoc_path()
    except (ImportError, OSError):
        pass
    found = shutil.which("pandoc")
    if not found:
        raise PandocError("pandoc not found: install requirements.txt (pypandoc_binary) or set $PANDOC")
    return found


# Pandoc warnings that are expected for this pipeline and only add noise.
_PANDOC_NOISE = (
    re.compile(r"Could not load translations for"),
    re.compile(r"data file translations/"),
    re.compile(r"has no translation defined"),
)


def run_pandoc(args: list[str], *, cwd: Path, env: dict | None = None) -> str:
    cmd = [pandoc_path(), *args]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    lines = [ln for ln in proc.stderr.splitlines()
             if ln.strip() and not any(p.search(ln) for p in _PANDOC_NOISE) and not ln.startswith("  ")]
    if proc.returncode != 0:
        raise PandocError(f"pandoc failed ({proc.returncode}) in {paths.rel(cwd)}:\n{proc.stderr.strip()}")
    for ln in lines:
        print(f"  pandoc: {ln}", file=sys.stderr)
    return proc.stdout


def source_date_epoch(book: config.Book) -> int:
    env = os.environ.get("SOURCE_DATE_EPOCH")
    if env and env.isdigit():
        return int(env)
    try:
        d = datetime.strptime(book.date[:10], "%Y-%m-%d")
    except ValueError:
        return 0
    return int(d.replace(tzinfo=timezone.utc).timestamp())


# --------------------------------------------------------------------------- fonts


def _woff_to_sfnt(data: bytes) -> bytes:
    """Decode a WOFF 1.0 file into the TrueType/OpenType font it wraps (W3C WOFF §5)."""
    if data[:4] != b"wOFF":
        raise ValueError("not a WOFF 1.0 file")
    (flavor,) = struct.unpack(">I", data[4:8])
    (num,) = struct.unpack(">H", data[12:14])
    entries = []
    for i in range(num):
        tag, off, comp, orig, cks = struct.unpack(">4sIIII", data[44 + 20 * i:64 + 20 * i])
        raw = data[off:off + comp]
        if comp < orig:
            raw = zlib.decompress(raw)
        entries.append((tag, raw, cks))
    entries.sort(key=lambda e: e[0])
    es = 1
    while es * 2 <= num:
        es *= 2
    header = struct.pack(">IHHHH", flavor, num, es * 16, es.bit_length() - 1, num * 16 - es * 16)
    directory, body = bytearray(), bytearray()
    offset = 12 + 16 * num
    for tag, raw, cks in entries:
        directory += struct.pack(">4sIII", tag, cks, offset + len(body), len(raw))
        body += raw + b"\0" * (-len(raw) % 4)
    return bytes(header + directory + body)


# @fontsource packages (installed by npm for the site and slides) ship WOFF only; Typst
# needs TTF/OTF. When neither tools/fetch-fonts.sh, theme/typst/fonts nor the system
# provides a family, its Latin subset is unpacked into .cache/fonts-fontsource/ so the
# cyberpunk display/data faces still reach the PDF offline. CJK families are not
# converted (fontsource splits them into unicode-range shards); install fonts-noto-cjk
# or run tools/fetch-fonts.sh for those.
FONTSOURCE = {
    "Chakra Petch": ("chakra-petch", "ChakraPetch", (400, 500, 600, 700)),
    "JetBrains Mono": ("jetbrains-mono", "JetBrainsMono", (400, 600, 700)),
}
FONTSOURCE_CACHE = paths.CACHE / "fonts-fontsource"


def _font_files(dirs: list[Path]) -> list[Path]:
    out = []
    for d in dirs:
        if d.is_dir():
            out += sorted(p for p in d.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc"))
    return out


_FAMILIES: dict[tuple[str, ...], set[str]] = {}


def _families(dirs: list[Path]) -> set[str]:
    """Font families Typst sees with ``dirs`` plus system fonts (cached per process)."""
    key = tuple(str(d) for d in dirs)
    if key not in _FAMILIES:
        try:
            import typst  # type: ignore

            _FAMILIES[key] = set(typst.Fonts(include_embedded_fonts=False, font_paths=list(key)).families())
        except Exception:  # noqa: BLE001 - informational only
            _FAMILIES[key] = set()
    return _FAMILIES[key]


def font_dirs() -> list[Path]:
    """Font directories handed to Typst: .cache/fonts, theme/typst/fonts, fontsource fallbacks."""
    dirs = [d for d in (FONT_CACHE, THEME_FONTS) if d.is_dir()]
    have = _families(dirs)
    fs_root = paths.ROOT / "node_modules" / "@fontsource"
    use_fallback = False
    for family, (pkg, stem, weights) in FONTSOURCE.items():
        if family in have:
            continue
        for w in weights:
            src = fs_root / pkg / "files" / f"{pkg}-latin-{w}-normal.woff"
            dst = FONTSOURCE_CACHE / f"{stem}-{w}.ttf"
            if dst.exists():
                use_fallback = True
                continue
            if not src.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(_woff_to_sfnt(src.read_bytes()))
                use_fallback = True
            except (OSError, ValueError, zlib.error) as exc:
                print(f"  fonts: cannot convert {src.name}: {exc}", file=sys.stderr)
    return dirs + ([FONTSOURCE_CACHE] if use_fallback else [])


def epub_font_files() -> list[Path]:
    """Font files that may be embedded in the EPUB (fetched fonts first, then fallbacks)."""
    font_dirs()  # make sure the fontsource fallbacks exist when nothing better is installed
    found = _font_files([FONT_CACHE, THEME_FONTS])
    families = {(_font_face(p) or ("",))[0] for p in found}
    return found + [p for p in _font_files([FONTSOURCE_CACHE]) if (_font_face(p) or ("",))[0] not in families]


# --------------------------------------------------------------------------- staging


ATX_RE = re.compile(r"^(?P<indent> {0,3})(?P<hashes>#{1,6})(?P<rest>(?:[ \t].*)?)$")
ATTR_TAIL_RE = re.compile(r"\s*\{(?P<attrs>[^{}]*)\}\s*$")
CLOSING_HASHES_RE = re.compile(r"(?:^|\s+)#+\s*$")
SETEXT_RE = re.compile(r"^ {0,3}(?P<ch>=+|-+)[ \t]*$")
REFDEF_RE = mdscan.REFDEF_RE  # a line that only defines a link reference (CommonMark)
NOT_PARAGRAPH_RE = re.compile(r"^(?: {4,}|\s*$|\s*[#>|<]|\s*:{3,}|\s*[-*+][ \t]|\s*\d+[.)][ \t]|\s*(?:`{3,}|~{3,}))")
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
# Footnote labels as Pandoc reads them: no whitespace, "^", "[" or "]" (mdBook also takes spaces
# and "^", which Pandoc reads as a link: footnote_problems).
_LABEL = r"(?P<label>[^\s^\[\]]+)"
# A footnote definition, also in a block quote or a list item (``> [^a]: …``, ``- [^a]: …``):
# mdBook and Pandoc both read it as a footnote of the document.
FOOTNOTE_DEF_RE = re.compile(r"^(?P<lead>" + mdscan.CONTAINER + r")\[\^" + _LABEL + r"\]:")
# What makes ``[^a]`` the text of a link for mdBook instead of a reference: a destination ``(…)``
# (``[^a](1972)``, ``[^a]()``) or a link label ``[x]`` (``[^a][x]``, also ``[^a]\[x]``; text when x
# is no link reference; a label has a character other than whitespace). ``[^a][^b]``, ``[^a][]``,
# ``[^a][ ]``, ``[^a] (1972)`` and ``[^a]\(1972)`` are references.
_LINK_TAIL = (r"\([ \t]*(?:<[^<>\n]*>|(?:[^\s()\\]|\\.|\((?:[^\s()\\]|\\.)*+\))++)?(?:[ \t]+" + mdscan.LINK_TITLE
              + r")?[ \t]*\)|\\?\[(?!\^)\s*+(?:[^\[\]\\\s]|\\.)(?:[^\[\]\\]|\\.)*+\]")
# A footnote reference that is not escaped (``\[^a]`` is text; ``\\[^a]`` is a backslash and a
# reference), with the escaped backslashes before it, and not the text of a link.
_NOTE_REF_RE = re.compile(r"(?<!\\)(?P<esc>(?:\\\\)*)\[\^" + _LABEL + r"\](?!" + _LINK_TAIL + ")")
_NOTE_LINK_RE = re.compile(r"(?<!\\)(?P<esc>(?:\\\\)*)\[\^" + _LABEL + r"\](?=" + _LINK_TAIL + ")")
# A definition whose label Pandoc does not read as one (spaces or "^" in it).
_ODD_DEF_RE = re.compile(r"^(?P<lead>" + mdscan.CONTAINER + r")\[\^(?P<label>[^\[\]]*[\s^][^\[\]]*)\]:")
# CommonMark HTML blocks, which mdBook passes on as raw HTML (no footnotes, links or emphasis in
# them): start → end (a line holding it; None: a blank line). Types 1-6 may interrupt a
# paragraph; type 7, one complete tag alone on its line, may not.
_HTML_BLOCK_TAGS = ("address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|"
                    "dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|"
                    "header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|"
                    "param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul")
_HTML_BLOCKS = [
    (re.compile(r"<(?:script|pre|style|textarea)(?=[\s>]|$)", re.I),
     re.compile(r"</(?:script|pre|style|textarea)>", re.I)),
    (re.compile(r"<!--"), re.compile(r"-->")),
    (re.compile(r"<\?"), re.compile(r"\?>")),
    (re.compile(r"<![A-Za-z]"), re.compile(r">")),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r"</?(?:" + _HTML_BLOCK_TAGS + r")(?=[\s/>]|$)", re.I), None),
]
# Block-quote and list-item markers before a line's own text (an HTML block may sit in either).
_QUOTE_RE = re.compile(r" {0,3}>")
# A thematic break (after the containers' markers): it ends a paragraph, and is no lazy line.
_BREAK_RE = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*")
_SPACES_RE = re.compile(r" *")
_LIST_ITEM_RE = re.compile(r"(?:[-*+]|\d{1,9}[.)])(?= |$)")
# A complete open or closing HTML tag, with CommonMark's attribute names: raw HTML, in which mdBook
# reads no footnote reference (``<b and [^a] c>`` is no tag: "[^a]" is no attribute name).
_TAG_RE = re.compile(r"""</?[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*"""
                     r"""(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*\s*/?>""")
# Inline link or image (text kept) and raw HTML tags: what heading slugs strip; a trailing
# brace block that Pandoc cannot parse ({weird stuff}) stays text in Pandoc, but mdBook
# reads it as attributes and drops it from the id.
_HEADING_LINK_RE = re.compile(r"!?\[((?:[^\[\]\\]|\\.)*)\]\([^)]*\)")
_HEADING_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_UNPARSED_ATTRS_RE = re.compile(r"\{[^{}]*\}\s*$")
_MARK = 0xE000  # private-use placeholders for a heading's formulas and footnote numbers (_mdbook_plain)
_ATTR_BLOCK_RE = re.compile(r"\{([^{}\n]*)\}")
_ATTR_ID_RE = re.compile(r"(?:^|\s)#([^\s{}#.=\"']+)")
# An id in raw HTML (``<a id="x">``), which tools/filters/tr-book.lua also counts as a link target.
_HTML_ID_RE = re.compile(r'<[A-Za-z][^<>]*?\sid="([^"]+)"')
# Files a Pandoc image can embed (a reference definition to anything else is a plain link).
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
# What a written destination percent-encodes, as tbook.render does: a fragment (whitespace,
# angle brackets, parentheses) and a decoded file path (also "%", "#", "?" and backslashes).
_DEST_UNSAFE_RE = re.compile(r"[\s<>()]")
_PATH_UNSAFE_RE = re.compile(r"[\s<>()%#?\\]")


def _url_quote(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda m: quote(m.group(), safe=""), text)


@dataclass
class Heading:
    index: int  # line index
    level: int
    text: str
    attrs: mdscan.Attrs | None


@dataclass
class StagedChapter:
    path: str  # relative to the edition
    id: str
    section: str
    depth: int
    title: str


@dataclass
class Stage:
    dir: Path
    book_md: Path
    chapters: list[StagedChapter] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # staged support files (relative)
    warnings: list[str] = field(default_factory=list)
    formal_count: int = 0
    open_count: int = 0
    meta: dict = field(default_factory=dict)


def _code_mask(lines: list[str]) -> list[bool]:
    """True for lines that are never rewritten: fenced and indented code blocks (also in block
    quotes, list items, footnote and definition bodies), HTML comment blocks and lines wholly
    inside an inline comment that spans lines — the block model of
    :func:`tbook.mdscan.parse_blocks` and the math scanner (:attr:`tbook.mdscan.BlockScan.hidden`).
    The other lines go through :func:`tbook.mdscan.map_closed` with the scan's ``carry``, so the
    part of a line inside such a comment is left alone too."""
    return mdscan.scan_blocks(lines).hidden


def _in_formula(lines: list[str]) -> list[bool]:
    """True for each line that a formula begun on an earlier line goes on over: like
    :func:`tbook.mdscan.scan_blocks`, which pairs ``$`` as :func:`tbook.mathrender.find_math` does,
    no block (and so no setext underline) starts there."""
    out = [False] * len(lines)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    for span in mathrender.find_math("\n".join(lines))[0]:
        k = span.line  # the line after the formula's first
        while k < len(lines) and starts[k] < span.end:
            out[k] = True
            k += 1
    return out


def normalize_setext(md: str) -> str:
    """Rewrite setext headings (``Title`` + ``===``/``---``) as ATX so later passes see one form.
    A pair inside a formula (``$$`` + ``=``) is no heading."""
    lines = md.split("\n")
    mask = _code_mask(lines)
    formula: list[bool] | None = None  # _in_formula, once a pair needs it
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (not mask[i] and i + 1 < len(lines) and not mask[i + 1] and SETEXT_RE.match(lines[i + 1])
                and not NOT_PARAGRAPH_RE.match(line) and (i == 0 or not lines[i - 1].strip())):
            formula = formula or _in_formula(lines)
            if not formula[i + 1]:
                level = 1 if SETEXT_RE.match(lines[i + 1]).group("ch")[0] == "=" else 2
                out.append("#" * level + " " + line.strip())
                i += 2
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


def heading_attrs(raw: str) -> mdscan.Attrs:
    """A heading's attribute block as Pandoc reads it: ``-`` is ``.unnumbered`` (``{-}``,
    ``{- #id}``) and of several ``#id`` the last wins (as in mdBook). Raises
    :class:`tbook.mdscan.AttrError` for what Pandoc would show as text (``{weird stuff}``)."""
    text, pos, tokens = raw.strip(), 0, []
    while pos < len(text):
        if text[pos] == "-" and (pos + 1 == len(text) or text[pos + 1].isspace()):
            tokens.append(".unnumbered")
            pos += 1
        else:
            m = mdscan.ATTR_TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                return mdscan.parse_attrs(text)  # raises AttrError with the parser's message
            tokens.append(m.group(0).strip())
            pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    last_id = max((k for k, tok in enumerate(tokens) if tok.startswith("#")), default=-1)
    kept = [tok for k, tok in enumerate(tokens) if not tok.startswith("#") or k == last_id]
    return mdscan.parse_attrs(" ".join(kept))


def parse_heading(line: str) -> tuple[int, str, mdscan.Attrs | None] | None:
    m = ATX_RE.match(line)
    if not m:
        return None
    level = len(m.group("hashes"))
    rest = m.group("rest").strip()
    attrs = None
    am = ATTR_TAIL_RE.search(rest)
    if am:
        try:
            attrs = heading_attrs(am.group("attrs"))
            rest = rest[:am.start()].rstrip()
        except mdscan.AttrError:
            attrs = None
    rest = CLOSING_HASHES_RE.sub("", rest).strip() if rest.strip("#").strip() or not rest else ""
    return level, rest, attrs


def format_heading(level: int, text: str, attrs: mdscan.Attrs | None) -> str:
    line = "#" * level + " " + text
    if attrs and (attrs.id or attrs.classes or attrs.kv):
        if "*" in text:
            # An unmatched asterisk can make Pandoc consume trailing attributes
            # as title text. Carry generated metadata before the untouched title.
            marker = attrs.to_pandoc()[:-1] + " .tr-heading-meta}"
            return "#" * level + " []" + marker + " " + text
        line += " " + attrs.to_pandoc()
    return line


def find_headings(md: str) -> list[Heading]:
    lines = md.split("\n")
    mask = _code_mask(lines)
    out = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        h = parse_heading(line)
        if h:
            out.append(Heading(i, h[0], h[1], h[2]))
    return out


def contained_headings(md: str) -> list[Heading]:
    """ATX headings whose line opens a block quote or list item (``> ## 引文标题``, ``- ### 项``),
    which :func:`find_headings` leaves out; :func:`restructure_chapter` writes their ids after the
    markers (:func:`with_heading_id`)."""
    lines = md.split("\n")
    mask = _code_mask(lines)
    out = []
    for i, raw in enumerate(lines):
        first = raw.lstrip(" \t")[:1]
        if mask[i] or not (first in (">", "-", "*", "+") or first.isdigit()):
            continue
        line = raw.expandtabs(4)
        stack, pos = _containers(line)
        h = parse_heading(line[pos:]) if stack else None
        if h:
            out.append(Heading(i, h[0], h[1], h[2]))
    return out


def with_heading_id(line: str, hid: str) -> str:
    """``line``, a heading after block-quote or list markers (:func:`contained_headings`), with
    the id ``hid`` unless it has one."""
    line = line.expandtabs(4)
    stack, pos = _containers(line)
    h = parse_heading(line[pos:]) if stack else None
    if not h or (h[2] and h[2].id):
        return line
    attrs = h[2] or mdscan.Attrs()
    attrs.id = hid
    return line[:pos] + format_heading(h[0], h[1], attrs)


def chapter_slug(path: str) -> str:
    stem = path[:-3] if path.endswith(".md") else path
    return "ch-" + (SAFE_ID_RE.sub("-", stem).strip("-").lower() or "chapter")


def _containers(line: str) -> tuple[list[int], int]:
    """The block quotes and list items that the markers at the start of ``line`` (tabs expanded)
    open, kept as :func:`tbook.mdscan.scan_blocks` keeps containers (-1 for a block quote, else the
    columns of a list item's content), and where the line's own text starts."""
    stack: list[int] = []
    pos = 0
    while True:
        start = _SPACES_RE.match(line, pos).end()
        if start - pos >= 4:
            return stack, pos
        if line.startswith(">", start):
            stack.append(-1)
            pos = start + 1 + line.startswith(" ", start + 1)
            continue
        m = _LIST_ITEM_RE.match(line, start)
        if not m:
            return stack, pos
        after = _SPACES_RE.match(line, m.end()).end()
        gap = after - m.end()
        stack.append(m.end() - pos + (1 if after == len(line) or gap > 4 else gap))
        pos += stack[-1]


def _goes_on(line: str, stack: list[int]) -> int | None:
    """Where the text of ``line`` (tabs expanded) starts inside the containers ``stack``
    (:func:`_containers`), or None if the line is outside one of them: a block quote goes on with
    its ``>``, a list item with a blank line or a line indented to its content."""
    pos = 0
    for col in stack:
        if col < 0:
            m = _QUOTE_RE.match(line, pos)
            if not m:
                return None
            pos = m.end() + line.startswith(" ", m.end())
        else:
            start = _SPACES_RE.match(line, pos).end()
            if start < len(line):  # a blank line goes on with a list item
                if start - pos < col:
                    return None
                pos += col
    return pos


def _raw_html_lines(lines: list[str], scan: mdscan.BlockScan) -> list[bool]:
    """True for each line that mdBook passes on as raw HTML: the lines of CommonMark HTML blocks
    (:data:`_HTML_BLOCKS`, also in block quotes and list items) and the ``:::`` lines of divs,
    which the HTML edition writes as HTML between blank lines (an environment's title too).

    An HTML block also ends with the block quote or list item it is in (it has no lazy lines): at a
    line without that ``>``, or not blank and indented less than that list item's content. The
    containers are those whose markers stand on the block's first line, and the list items opened
    on earlier lines that the first line is indented into (``- 项`` then a blank line and ``  <div>``);
    other indentation of the first line is no container."""
    hidden = scan.hidden
    raw = [False] * len(lines)
    end: re.Pattern | None = None  # what ends the open HTML block (None: a blank line)
    inside: list[int] = []  # the containers of the open HTML block (_containers)
    open_ = para = False  # an HTML block goes on; the line before goes on with a paragraph
    para_quotes = 0  # the block quotes of the paragraph's first line
    items: list[tuple[int, int, str]] = []  # open list items: (block quotes around, content column, marker)
    for i, line in enumerate(lines):
        if hidden[i] or mdscan.DIV_OPEN_RE.match(line) or mdscan.DIV_CLOSE_RE.match(line):
            raw[i] = not hidden[i]
            open_ = para = False
            continue
        line = line.expandtabs(4)
        if open_:
            pos = _goes_on(line, inside)
            if pos is None or (end is None and not line[pos:].strip(" ")):
                open_ = False  # its container ended, or a blank line ended it
            else:
                raw[i] = True
                open_ = end is None or not end.search(line, pos)
                continue
        stack, pos = _containers(line)
        body = line[pos:]
        text = body.lstrip(" ")
        quotes, after = _quote_prefix(line)
        rest = line[after:]
        marks = _list_marks(rest)
        if not text:
            if marks and _BREAK_RE.fullmatch(rest.strip(" ")):  # "- - -", "* * *": no list items
                items = _open_items(items, quotes, rest, [], False)
                para = False
                continue
            if para and marks and quotes <= para_quotes:
                at, kind = marks[0][2], marks[0][1]
                cut = [(c, k) for q, c, k in items if q == quotes and c > at]  # the items it would end
                if not cut and quotes == para_quotes and SETEXT_RE.match(rest):
                    para = False  # "-" under the paragraph: a setext heading's underline
                    continue
                if not cut or min(cut)[1] != kind:
                    continue  # an empty item cannot begin a list in a paragraph: the line goes on with it
            if marks:  # only markers: they end deeper list items and open their own
                items = _open_items(items, quotes, rest, marks, False)
            else:  # blank, maybe after block-quote markers: the block quotes past them end
                items = [it for it in items if it[0] <= quotes]
            para = False
            continue
        if len(body) - len(text) < 4:
            for start, stop in _HTML_BLOCKS:
                m = start.match(text)
                if m:
                    raw[i], end = True, stop
                    open_ = stop is None or not stop.search(text, m.end())
                    break
            else:
                if not para and _TAG_RE.fullmatch(text.rstrip()):  # type 7
                    raw[i], end, open_ = True, None, True
        items = _open_items(items, quotes, rest, marks, para and not raw[i] and not marks)
        if raw[i]:
            inside = stack
            if all(c < 0 for c in stack):  # in the list items it is indented into
                indent = len(rest) - len(rest.lstrip(" "))
                cols = [c for q, c, _ in items if q == quotes and c <= indent]
                inside = stack + [b - a for a, b in zip([0] + cols, cols)]
        # A heading ends the paragraph (an ATX heading, or the underline of a setext heading, which
        # is in the paragraph's block quotes), and so does a thematic break.
        was = para
        para = (not raw[i] and not ATX_RE.match(text) and not _BREAK_RE.fullmatch(text)
                and not (para and quotes == para_quotes and SETEXT_RE.match(text)))
        if para and not was:
            para_quotes = quotes
    return raw


def _open_items(items: list[tuple[int, int, str]], quotes: int, rest: str,
                marks: list[tuple[int, str, int]], lazy: bool) -> list[tuple[int, int, str]]:
    """The list items open after a non-blank line (:func:`_raw_html_lines`): ``items`` as
    (block quotes around, content column after them, marker); the line has ``quotes`` block
    quotes, then ``rest``, whose markers open ``marks`` (:func:`_list_marks`). Unless the line is a
    ``lazy`` continuation of a paragraph, it ends the items in deeper block quotes and those whose
    content it is not indented to; then it opens its own."""
    if lazy:
        items = list(items)
    else:
        indent = len(rest) - len(rest.lstrip(" "))
        items = [it for it in items if it[0] < quotes or (it[0] == quotes and it[1] <= indent)]
    items.extend((quotes, col, kind) for col, kind, _ in marks)
    return items


def _list_marks(rest: str) -> list[tuple[int, str, int]]:
    """(content column, marker, marker column) of each list item whose marker starts ``rest`` (a
    line after its block-quote markers), as :func:`_containers` reads them, up to a block quote.
    The marker is the bullet, or the delimiter of an ordered one (``.`` or ``)``)."""
    out: list[tuple[int, str, int]] = []
    pos = 0
    while True:
        start = _SPACES_RE.match(rest, pos).end()
        m = _LIST_ITEM_RE.match(rest, start) if start - pos < 4 else None
        if not m:
            return out
        after = _SPACES_RE.match(rest, m.end()).end()
        gap = after - m.end()
        pos = m.end() + (1 if after == len(rest) or gap > 4 else gap)
        out.append((pos, m.group()[-1], start))


def _quote_prefix(line: str) -> tuple[int, int]:
    """The block quotes whose markers start ``line`` (tabs expanded), as :func:`_containers` reads
    them, and where the text after them starts."""
    quotes = pos = 0
    while True:
        m = _QUOTE_RE.match(line, pos)
        if not m:
            return quotes, pos
        quotes += 1
        pos = m.end() + line.startswith(" ", m.end())


def _math_spans(lines: list[str]) -> list[list[tuple[int, int]]]:
    """Per line, the parts inside formulas (the HTML edition shows them rendered by KaTeX)."""
    out: list[list[tuple[int, int]]] = [[] for _ in lines]
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    for span in mathrender.find_math("\n".join(lines))[0]:
        k = span.line - 1
        while k < len(lines) and starts[k] < span.end:
            out[k].append((max(span.start - starts[k], 0), min(span.end - starts[k], len(lines[k]))))
            k += 1
    return out


def _not_read(line: str, carry: tuple[bool, bool] = (False, False),
              math: list[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    """The parts of a line where mdBook reads no footnote reference: code spans, HTML comments,
    formulas (``math``), HTML tags, autolinks and link destinations and titles."""
    spans = mdscan.hidden_spans(line, carry) + list(math or [])
    for pattern in (_TAG_RE, mathrender.AUTOLINK_RE, mathrender.LINK_DEST_RE):
        spans += [m.span() for m in pattern.finditer(line)]
    return spans


def _refs(line: str, spans: list[tuple[int, int]], pattern: re.Pattern = _NOTE_REF_RE) -> list[re.Match]:
    """The matches of ``pattern`` (footnote references) whose ``[`` is outside ``spans``."""
    return [m for m in pattern.finditer(line)
            if not any(a <= m.start("label") - 2 < b for a, b in spans)]


def _footnote_def(lines: list[str], i: int) -> re.Match | None:
    """The footnote definition line ``i`` holds (:data:`FOOTNOTE_DEF_RE`). Without a block-quote or
    list marker and indented 4 columns or more, a line right under another one goes on with it."""
    m = FOOTNOTE_DEF_RE.match(lines[i])
    lead = m.group("lead") if m else ""
    if m and not lead.strip() and len(lead.expandtabs(4)) >= 4 and i and lines[i - 1].strip():
        return None
    return m


def _note_lines(md: str) -> list[tuple[int, str, re.Match | None, list[tuple[int, int]]]]:
    """``(index, line, definition, spans)`` for each line of ``md`` where mdBook reads footnotes:
    not in code, an HTML comment or raw HTML (:func:`_raw_html_lines`). ``definition`` is the
    footnote definition the line holds, or None; ``spans`` are the parts where no reference is
    read (:func:`_not_read`, and the definition's own label)."""
    lines = md.split("\n")
    scan = mdscan.scan_blocks(lines)
    hidden = scan.hidden
    raw = _raw_html_lines(lines, scan)
    math = _math_spans(lines)
    out = []
    for i, line in enumerate(lines):
        if hidden[i] or raw[i]:
            continue
        d = _footnote_def(lines, i)
        spans = _not_read(line, scan.carry[i], math[i]) + ([(0, d.end())] if d else [])
        out.append((i, line, d, spans))
    return out


def scope_footnotes(md: str, prefix: str) -> str:
    """Rename the footnotes defined in this chapter: ``[^n]`` → ``[^<prefix>--n]``.

    Each chapter is its own page in HTML, so ``[^1]`` is reused from chapter to chapter;
    book.md holds every chapter and Pandoc would give every ``[^1]`` the text of the last
    definition in the book. The definitions (also in block quotes and list items) and the
    references that mdBook reads (:func:`_note_lines`, :data:`_NOTE_REF_RE`) to a label defined
    in the chapter are renamed. Everything else stays as written: what the HTML edition shows as
    text (escaped, in code, a comment, a formula, raw HTML, an environment title, a link) then
    names no footnote of book.md, and Pandoc shows the same text.
    """
    notes = _note_lines(md)
    labels = {d.group("label") for _, _, d, _ in notes if d}
    if not labels:
        return md
    lines = md.split("\n")
    for i, line, d, spans in notes:
        starts = [m.start("label") for m in _refs(line, spans) if m.group("label") in labels]
        for pos in sorted(starts + ([d.start("label")] if d else []), reverse=True):
            line = f"{line[:pos]}{prefix}--{line[pos:]}"
        lines[i] = line
    return "\n".join(lines)


def footnote_numbers(md: str) -> dict[str, int]:
    """The number mdBook shows for each footnote reference of a chapter: label → number.

    mdBook (0.5) numbers the labels in the order of their first reference, in source order
    (body, headings and footnote definitions alike), keyed by the label as written; a
    reference counts when a definition in the chapter matches its label ignoring case. A
    reference without a definition is text, and so is one mdBook does not read
    (:func:`_note_lines`): escaped (``\\[^a]``), in code, a comment, a formula, raw HTML or an
    environment title, or the text of a link (``[^a](1972)``).
    """
    notes = _note_lines(md)
    defined = {d.group("label").casefold() for _, _, d, _ in notes if d}
    numbers: dict[str, int] = {}
    for _, line, _, spans in notes:
        for m in _refs(line, spans):
            if m.group("label").casefold() in defined:
                numbers.setdefault(m.group("label"), len(numbers) + 1)
    return numbers


def footnote_problems(md: str) -> list[tuple[int, str]]:
    """``(line, message)`` for each footnote that the HTML edition (mdBook) and the PDF/EPUB
    (Pandoc) read differently, for ``./tbook check``: a reference whose label matches a definition
    only ignoring case, ``[^a]`` right before ``(…)`` or ``[x]`` (a link for mdBook), and a label
    with a space or ``^`` (a link for Pandoc)."""
    notes = _note_lines(md)
    defined = {d.group("label") for _, _, d, _ in notes if d}
    folded: dict[str, str] = {}
    for label in sorted(defined):
        folded.setdefault(label.casefold(), label)
    out: list[tuple[int, str]] = []
    for i, line, d, spans in notes:
        found: list[tuple[int, str]] = []
        for m in _refs(line, spans):
            label = m.group("label")
            if label not in defined and label.casefold() in folded:
                found.append((m.start(), f"[^{label}] matches the footnote [^{folded[label.casefold()]}] only ignoring "
                                         f"case: the HTML edition shows a number that leads to no note, the PDF/EPUB "
                                         f"show the text [^{label}]; write the label as defined"))
        for m in _refs(line, spans, _NOTE_LINK_RE):
            label, after = m.group("label"), line[m.end():].lstrip("\\")[:1]
            if label.casefold() in folded:
                fix = "a space or a backslash" if after == "(" else "a space"
                found.append((m.start(), f"[^{label}] right before '{after}' is the text of a link in the HTML edition "
                                         f"(mdBook), not a footnote reference; put {fix} before the '{after}'"))
        odd = None if d else _ODD_DEF_RE.match(line)
        if odd and odd.group("label").strip():
            label = odd.group("label")
            found.append((0, f"footnote label '{label}' has a space or '^': the HTML edition reads [^{label}] as a "
                             f"footnote, the PDF/EPUB (Pandoc) as a link; use a label without them"))
        out += [(i + 1, msg) for _, msg in sorted(found)]
    return out


def _heading_plain(text: str) -> str:
    """Heading Markdown as the plain text its automatic id is made from (approximately).

    Footnote references stay as written: Pandoc's id keeps the label (``注释[^a]`` → ``注释a``),
    and :func:`_mdbook_plain` puts mdBook's numbers in first. HTML comments (outside code spans)
    show nothing, as tags do.
    """
    comments = [(a, b) for a, b in mdscan.code_spans(text, comments=True) if text.startswith("<!--", a)]
    if comments:
        ends = [0] + [b for _, b in comments]
        text = "".join(text[ends[k]:a] for k, (a, _) in enumerate(comments)) + text[ends[-1]:]
    text = _HEADING_LINK_RE.sub(r"\1", text)
    text = _HEADING_TAG_RE.sub("", text)
    text = re.sub(r"(?<!\w)_+|_+(?!\w)", "", text)  # _emphasis_ (intraword "_" stays)
    return re.sub(r"\\(.)", r"\1", text)


def _mdbook_plain(text: str, math: dict[tuple[str, bool], str] | None,
                  notes: dict[str, int] | None = None) -> str:
    """:func:`_heading_plain` of the heading as mdBook shows it: each formula as the text KaTeX
    shows for it (``math``: ``(tex, display)`` → text; without an entry the TeX source stands
    in), each reference to a footnote of the chapter as its number (``notes``:
    :func:`footnote_numbers`), with a space between two references side by side. A reference
    to no footnote of the chapter stays text, as in mdBook."""
    shown: list[str] = []  # what each placeholder stands for, so it is never re-parsed

    def mark(s: str) -> str:
        shown.append(s)
        return chr(_MARK + len(shown) - 1)

    spans = mathrender.find_math(text)[0] if math else []
    parts, cursor = [], 0
    for span in spans:
        katex = math.get((span.tex, span.display))
        if katex is None:
            katex = _heading_plain(text[span.start:span.end])
        parts += [text[cursor:span.start], mark(katex)]
        cursor = span.end
    text = "".join(parts) + text[cursor:]
    if notes:
        last = -1  # where the previous reference ended
        # Formulas left as TeX (without ``math``) hold no references either.
        skip = _not_read(text, math=[(s.start, s.end) for s in mathrender.find_math(text)[0]])

        def number(m: re.Match) -> str:
            nonlocal last
            n = notes.get(m.group("label"))
            if n is None or any(a <= m.start("label") - 2 < b for a, b in skip):
                return m.group(0)
            side_by_side = not m.group("esc") and m.start() == last
            last = m.end()
            return m.group("esc") + (" " if side_by_side else "") + mark(str(n))

        text = _NOTE_REF_RE.sub(number, text)
    plain = _heading_plain(text)
    for k, s in enumerate(shown):
        plain = plain.replace(chr(_MARK + k), s)
    return plain


def _slug_pair(text: str, shown: str, math: dict[tuple[str, bool], str] | None,
               notes: dict[str, int] | None = None) -> tuple[str, str]:
    """(mdBook's id, Pandoc's ``gfm_auto_identifiers`` id) of a heading before de-duplication.

    mdBook makes its id from the text of the rendered heading (``shown``, which lacks a trailing
    ``{…}`` that only mdBook reads as attributes; formulas as KaTeX shows them, footnote
    references as their numbers in the chapter, ``notes``); Pandoc from the text it reads,
    formulas as TeX, footnote references as their labels and a run of spaces as one (the spaces on
    both sides of a comment stay two).
    """
    mdbook = "".join("-" if ch.isspace() else ch for ch in _mdbook_plain(shown, math, notes).strip().lower()
                     if ch.isalnum() or ch in "-_" or ch.isspace())
    gfm = "".join("-" if ch.isspace() else ch for ch in _heading_plain(re.sub(r"[ \t]+", " ", text)).lower()
                  if ch.isspace() or ch.isalnum() or ch in "-_"
                  or unicodedata.category(ch) in ("Mn", "Mc", "Me", "Pc"))
    return mdbook, gfm


def heading_slugs(text: str, math: dict[tuple[str, bool], str] | None = None,
                  notes: dict[str, int] | None = None) -> list[str]:
    """The automatic ids of a heading before de-duplication: mdBook's (the HTML edition,
    which authors link to) first, then Pandoc's ``gfm_auto_identifiers`` when it differs.

    ``math`` maps ``(tex, display)`` to the text KaTeX shows (:func:`tbook.mathrender.formula_texts`):
    mdBook's id of ``关于 $\\beta$ 的估计`` is ``关于-β-的估计``. Without it the TeX stands in.
    ``notes`` numbers the footnotes of the chapter (:func:`footnote_numbers`): with ``a`` the
    first, mdBook's id of ``注释[^a]`` is ``注释1`` and Pandoc's ``注释a``. Without it every
    footnote reference is text, as one without a definition is.
    """
    pair = _slug_pair(text, text, math, notes)
    return [s for i, s in enumerate(pair) if s and s not in pair[:i]]


def _mdbook_text(h: Heading) -> str:
    """The heading text mdBook shows: it reads any trailing ``{…}`` as attributes, also one
    that Pandoc (and :func:`heading_attrs`) cannot parse and keeps as text."""
    return _UNPARSED_ATTRS_RE.sub("", h.text).rstrip() if h.attrs is None else h.text


def _unique(base: str, used: set[str]) -> str:
    """``base``, else ``base-1``, ``base-2``… (mdBook's and Pandoc's de-duplication)."""
    candidate, n = base, 1
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    used.add(candidate)
    return candidate


def _safe_id(slug: str) -> str:
    """A slug as an id Pandoc's attribute syntax accepts (starts with a letter or digit)."""
    return "".join(ch for ch in slug if ch.isalnum() or ch in "-_").lstrip("-_") or "section"


def explicit_ids(md: str) -> set[str]:
    """Ids written as ``{#id …}`` attributes (headings, divs, spans) in a chapter."""
    out: set[str] = set()
    for block in _ATTR_BLOCK_RE.finditer(md):
        out.update(_ATTR_ID_RE.findall(block.group(1)))
    return out


@dataclass
class HeadingIds:
    """Ids given to the headings without one, and the fragments that reach them."""

    by_line: dict[str, dict[int, str]] = field(default_factory=dict)  # chapter → line → id
    # chapter → fragment → id: every fragment the chapter's page has (heading slugs, explicit and HTML ids)
    anchors: dict[str, dict[str, str]] = field(default_factory=dict)


def _heading_math(heads: list[Heading], render_math) -> dict[tuple[str, bool], str]:
    """``(tex, display)`` → shown text for the formulas of ``heads`` (one ``render_math`` call)."""
    if render_math is None:
        return {}
    items = list(dict.fromkeys((s.tex, s.display) for h in heads
                               for s in mathrender.find_math(_mdbook_text(h))[0]))
    shown = render_math(items) if items else None
    return dict(zip(items, shown)) if shown is not None else {}


def assign_heading_ids(chapters: list[tuple[str, str]], chapter_ids: dict[str, str],
                       taken: set[str], *, render_math=None) -> HeadingIds:
    """Give every heading without an explicit id one that is unique in the whole book.

    ``chapters`` is ``(path, rendered Markdown)`` in book order; ``taken`` holds the ids
    already in use (environments, chapters, parts…) and receives the new ones. A heading
    keeps its mdBook slug when no other chapter uses it, otherwise it becomes
    ``<chapter id>--<slug>``. ``anchors`` resolves a fragment within its chapter as the
    chapter's HTML page does (its own explicit ids first, then mdBook's automatic heading
    ids, then Pandoc's, then ids in raw HTML), so ``other.md#summary`` reaches the "Summary"
    of ``other.md``, not the first in the book. Headings in block quotes and list items
    (:func:`contained_headings`) get ids too, in document order with the others.

    ``render_math(items)`` returns the text the HTML edition shows for each ``(tex, display)``
    formula in a heading (:func:`tbook.mathrender.formula_texts`), or None when it cannot;
    mdBook's id of a heading with math is made from that text. Without it the TeX source
    stands in, and fragments copied from the HTML edition do not reach such headings. A
    footnote reference counts as mdBook's number for it in the chapter (:func:`footnote_numbers`).
    """
    parsed = []
    for path, md in chapters:
        flat = normalize_setext(md)
        top = find_headings(flat)
        parsed.append((posixpath.normpath(path), md, top, sorted(top + contained_headings(flat), key=lambda h: h.index)))
    for _, _, _, heads in parsed:
        taken |= {h.attrs.id for h in heads if h.attrs and h.attrs.id}
    math = _heading_math([h for *_, heads in parsed for h in heads if not (h.attrs and h.attrs.id)], render_math)
    out = HeadingIds()
    for path, md, top, heads in parsed:
        cid = chapter_ids[path]
        own = explicit_ids(md)
        notes = footnote_numbers(md)
        lines = out.by_line.setdefault(path, {})
        # Automatic ids of this chapter, each tool de-duplicating its own as it does.
        mdbook_ids: set[str] = set()
        pandoc_ids: set[str] = set()
        reach: list[tuple[str, str]] = []  # (mdBook fragment, id)
        reach_pandoc: list[tuple[str, str]] = []
        title = next((h for h in top if h.level == 1), None)
        for h in heads:
            if h.attrs and h.attrs.id:
                continue
            mdbook, gfm = _slug_pair(h.text, _mdbook_text(h), math, notes)
            mdbook = _unique(mdbook, mdbook_ids) if mdbook else ""
            gfm = _unique(gfm, pandoc_ids) if gfm else ""
            if h is title:
                new = cid  # restructure_chapter gives the chapter title its id
            else:
                base = _safe_id(mdbook or gfm)
                new = _unique(base if base not in taken else f"{cid}--{base}", taken)
                lines[h.index] = new
            reach.append((mdbook, new))
            reach_pandoc.append((gfm, new))
        anchors = out.anchors.setdefault(path, {})
        anchors.update((frag, frag) for frag in sorted(own))
        for frag, new in reach + reach_pandoc:
            if frag and frag not in own:
                anchors.setdefault(frag, new)
        for frag in _HTML_ID_RE.findall(md):
            anchors.setdefault(frag, frag)
    return out


class _Linker:
    """Rewrites a chapter's relative links for the flattened book.md at the staging root.

    ``anchors`` (chapter → fragment → id, :func:`assign_heading_ids`) resolves fragments per
    chapter; ``env_ids`` are the environment ids that ``[@id]`` references point to (never
    re-resolved); ``online`` is the published edition's URL
    (``site.book_url(slug, lang)``, '' when unknown), where plain links to files point.
    """

    def __init__(self, stage_dir: Path, edition: config.Edition, chapter_ids: dict[str, str],
                 warnings: list[str], files: set[str], *, anchors: dict[str, dict[str, str]] | None = None,
                 env_ids: set[str] | None = None, online: str = ""):
        self.stage_dir = stage_dir
        self.edition = edition
        self.chapter_ids = chapter_ids
        self.warnings = warnings
        self.files = files
        self.anchors = anchors or {}
        self.env_ids = env_ids or set()
        self.online = online.rstrip("/")

    def anchor(self, chapter: str, frag: str) -> str:
        """The book-wide id that ``frag`` (as written, maybe percent-encoded) names on the page of
        ``chapter``. A fragment that page lacks (no heading slug, explicit or HTML id there, and no
        environment id) leads nowhere in the HTML edition, so it must not land on another chapter's
        id: it becomes ``<chapter>#<frag>``, which no id of book.md is, and tools/filters/tr-book.lua
        renders the link as text with a warning. Without ``anchors`` for the chapter, ``frag``."""
        ids = self.anchors.get(chapter)
        name = unquote(frag)
        if ids is None or name in self.env_ids:
            return frag
        if name in ids:
            return _url_quote(_DEST_UNSAFE_RE, ids[name])
        return _url_quote(_DEST_UNSAFE_RE, chapter) + "#" + _url_quote(_DEST_UNSAFE_RE, frag)

    def published(self, rel: str, hash_: str, frag: str, chapter_path: str, url: str) -> str | None:
        """Absolute URL of the HTML edition's copy of ``rel`` (a plain link to a file: Pandoc
        embeds images only, so a relative link would be dead in the PDF and break the EPUB)."""
        if self.online:
            return f"{self.online}/{quote(rel)}" + (hash_ + frag if hash_ else "")
        self.warnings.append(f"{self.edition.key}/{chapter_path}: link to the file {url} needs the site's "
                             "base_url (site.toml) in PDF/EPUB; kept as text")
        return None

    def target(self, url: str, chapter_path: str, *, image: bool | None) -> str | None:
        """New URL, or None to drop the link (keeping its text).

        ``url`` is the destination as written: ``<…>`` (may contain spaces) or a plain,
        possibly percent-encoded one (:mod:`tbook.render` writes ``<…>`` that way). Files are
        looked up by the decoded path; a staged path is written percent-encoded. ``image``
        is True for images, False for links and None for reference definitions (decided by
        the file type).
        """
        raw = url
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        if render.EXTERNAL_RE.match(url) and not url.startswith("#"):
            return raw
        path_part, hash_, frag = url.partition("#")
        if not path_part:
            if frag and unquote(frag) not in self.env_ids:
                return "#" + self.anchor(posixpath.normpath(chapter_path), frag)
            return raw
        frag = _url_quote(_DEST_UNSAFE_RE, frag)
        tail = hash_ + frag if hash_ else ""
        path = unquote(path_part)
        chapter_dir = posixpath.dirname(chapter_path)
        joined = posixpath.normpath(posixpath.join(chapter_dir, path))
        embed = image if image is not None else joined.lower().endswith(IMAGE_SUFFIXES)
        if joined == "_book" or joined.startswith("_book/"):
            if not embed:
                return self.published(joined, hash_, frag, chapter_path, url)
            return _url_quote(_PATH_UNSAFE_RE, joined) + tail
        if joined.startswith(("../", "/")) or joined == "..":
            self.warnings.append(f"{self.edition.key}/{chapter_path}: link leaves the edition: {url}")
            return raw
        if joined in self.chapter_ids:
            return "#" + (self.anchor(joined, frag) if frag else self.chapter_ids[joined])
        if joined.endswith(".md") and image is False:
            self.warnings.append(f"{self.edition.key}/{chapter_path}: link to {path}, which is not a "
                                 "chapter of this edition; kept as text")
            return None
        src = self.edition.dir / joined
        if src.is_file():
            if not embed:
                return self.published(joined, hash_, frag, chapter_path, url)
            staged = posixpath.join("_book", self.edition.lang, joined)
            dst = self.stage_dir / staged
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            self.files.add(staged)
            return _url_quote(_PATH_UNSAFE_RE, staged) + tail
        self.warnings.append(f"{self.edition.key}/{chapter_path}: linked file not found: {url}")
        return raw

    def rewrite_line(self, line: str, chapter_path: str) -> str:
        def link(m: re.Match) -> str:
            image = bool(m.group("bang"))
            text = mdscan.sub_outside_code(render.LINK_RE, link, m.group("text"))  # an image inside a link
            new = self.target(m.group("url"), chapter_path, image=image)
            if new is None:
                return text
            title = mdscan.quoted_title(m.group("title")) if m.group("title") else ""
            return f"{m.group('bang')}[{text}]({new}{title})"

        rd = REFDEF_RE.match(line)  # also in a block quote or list item; never a footnote
        if rd:
            raw = rd.group("url")
            new = self.target(raw, chapter_path, image=None)  # keep reference definitions as links
            return f"{rd.group('lead')}{new or raw}{rd.group('rest')}"
        return mdscan.sub_outside_code(render.LINK_RE, link, line)


def restructure_chapter(md: str, *, chapter_path: str, depth: int, chapter_id: str, title: str,
                        classes: list[str], kv: dict[str, str], linker: _Linker | None,
                        heading_ids: dict[int, str] | None = None) -> str:
    """Shift headings by ``depth``, decorate the chapter title heading, rewrite links.

    ``heading_ids`` maps line numbers (of the setext-normalized text) to the ids that
    :func:`assign_heading_ids` gave headings without one. A heading right under a line of
    text gets a blank line before it: mdBook reads it as a heading there, Pandoc
    (``blank_before_header``) would read the line, ``{#id}`` included, as paragraph text.
    So do a ``:::`` div opener (the HTML edition gets HTML that ends the paragraph; Pandoc
    opens a div only after a blank line) and a footnote definition (mdBook reads it there,
    Pandoc only after a blank line; in a block quote the blank line is a ``>`` line); a
    definition right under another one stays as it is, as does one that starts a list item.
    """
    md = normalize_setext(md)
    lines = md.split("\n")
    scan = mdscan.scan_blocks(lines)
    mask = scan.hidden
    title_done = False
    out: list[str] = []
    for i, line in enumerate(lines):
        if mask[i]:
            out.append(line)
            continue
        h = parse_heading(line)
        if h:
            level, text, attrs = h
            if linker:
                text = linker.rewrite_line(text, chapter_path)
            if not title_done and level == 1:
                attrs = attrs or mdscan.Attrs()
                attrs.id = attrs.id or chapter_id
                attrs.classes = [*classes, *[c for c in attrs.classes if c not in classes]]
                attrs.kv = {**kv, **attrs.kv}
                title_done = True
            elif heading_ids and i in heading_ids and not (attrs and attrs.id):
                attrs = attrs or mdscan.Attrs()
                attrs.id = heading_ids[i]
            if out and out[-1].strip():
                out.append("")
            out.append(format_heading(min(6, level + depth), text, attrs))
            continue
        note = _footnote_def(lines, i)
        if out and out[-1].strip() and mdscan.DIV_OPEN_RE.match(line):
            out.append("")
        elif (note and out and out[-1].strip(" \t>") and not FOOTNOTE_DEF_RE.match(out[-1])
              and not re.search(r"[-*+]|\d[.)]", note.group("lead"))):
            out.append(" ".join(">" * note.group("lead").count(">")))
        line = (mdscan.map_closed(lambda s: linker.rewrite_line(s, chapter_path), line, scan.carry[i])
                if linker else line)
        out.append(with_heading_id(line, heading_ids[i]) if heading_ids and i in heading_ids else line)
    if not title_done:
        attrs = mdscan.Attrs(id=chapter_id, classes=list(classes), kv=dict(kv))
        out = [format_heading(min(6, 1 + depth), title, attrs), ""] + out
    return "\n".join(out).strip("\n") + "\n"


def verified_formal_envs(model: EditionModel, lock: lean.Lock | None) -> list[Env]:
    """Formal results shown with the green LEAN ✓: every Lean citation resolves in the lock to
    a frozen theorem (:func:`tbook.render.lean_verified`). Only these are counted in the ledger
    kicker, the colophon and on the cover; the others are UNVERIFIED (``check`` rejects them)."""
    return render.verified_envs(model.formal_envs(), lock)


def _kicker(model: EditionModel, chapter, book: config.Book) -> str:
    if model.summary is None:
        return ""
    prefix = chapter_prefix(model.summary, chapter)
    if chapter.section == "numbered":
        return f"§ {int(prefix):02d}" if prefix.isdigit() else f"§ {prefix}"
    if chapter.section == "suffix":
        return f"§ {prefix}"
    return book.code


def stage_dir_for(book: config.Book, edition: config.Edition) -> Path:
    return paths.BUILD / "stage" / book.slug / edition.lang / "pandoc"


def stage(site: config.Site, book: config.Book, edition: config.Edition, model: EditionModel | None,
          lock: lean.Lock | None, out_dir: Path | None = None) -> Stage:
    """Write book.md, _book/, _theme/ and meta.json into the staging directory."""
    model = model if model is not None else load_edition(edition)
    out_dir = Path(out_dir) if out_dir else stage_dir_for(book, edition)
    # Clear what staging owns; main.typ and cover.png stay for inspection until rebuilt.
    for name in ("_book", "_theme", "epub"):
        if (out_dir / name).exists():
            shutil.rmtree(out_dir / name)
    for name in ("book.md", "meta.json"):
        (out_dir / name).unlink(missing_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = Stage(dir=out_dir, book_md=out_dir / "book.md")
    ctx = render.RenderContext(site=site, book=book, edition=edition, model=model, lock=lock, target="pandoc")
    rendered = [(doc, render.chapter_markdown(doc, ctx)) for doc in model.chapters]
    result.warnings += ctx.issues

    # Pass 1: one stable id per chapter title, then ids for the other headings.
    env_ids = {e.id for e in model.all_envs() + [m for ch in model.chapters for m in ch.media] if e.id}
    taken = set(env_ids)
    taken.add(ledger.LEDGER_ID)
    taken.add("tr-colophon")
    taken.update(f"tr-part-{n}" for n in range(1, len(rendered) + 1))
    chapter_ids: dict[str, str] = {}
    for doc, md in rendered:
        heads = [h for h in find_headings(normalize_setext(md)) if h.level == 1]
        cid = heads[0].attrs.id if heads and heads[0].attrs and heads[0].attrs.id else ""
        if not cid:
            base = cid = chapter_slug(doc.chapter.path)
            n = 2
            while cid in taken:
                cid, n = f"{base}-{n}", n + 1
        taken.add(cid)
        chapter_ids[posixpath.normpath(doc.chapter.path)] = cid

    def heading_math(items: list[tuple[str, bool]]) -> list[str] | None:
        # mdBook's id of a heading with math is made from the text KaTeX shows (Node needed).
        try:
            return mathrender.formula_texts(items)
        except mathrender.MathError as exc:
            result.warnings.append(f"{edition.key}: ids of headings with math follow their TeX, not the HTML "
                                   f"edition, so links to them may not resolve (KaTeX unavailable: {exc})")
            return None

    heading_ids = assign_heading_ids([(doc.chapter.path, md) for doc, md in rendered], chapter_ids, taken,
                                     render_math=heading_math)

    # Pass 2: restructure and concatenate.
    staged_files: set[str] = set()
    linker = _Linker(out_dir, edition, chapter_ids, result.warnings, staged_files, anchors=heading_ids.anchors,
                     env_ids=env_ids, online=site.book_url(book.slug, edition.lang))
    # Macros first: Pandoc's latex_macros expands them in all math that follows.
    pieces: list[str] = [mathrender.newcommands() + "\n"]
    prev_part = ""
    parts = 0
    for doc, md in rendered:
        ch = doc.chapter
        if ch.depth == 0:
            if ch.part and ch.part != prev_part:
                parts += 1
                attrs = mdscan.Attrs(id=f"tr-part-{parts}", classes=["tr-part", "unnumbered"],
                                     kv={"tr-section": "part", "tr-kicker": book.code})
                pieces.append(format_heading(1, ch.part, attrs) + "\n")
            prev_part = ch.part
        cid = chapter_ids[posixpath.normpath(ch.path)]
        classes = ["tr-chapter"] + ([] if ch.section == "numbered" else ["unnumbered"])
        kv = {"tr-section": ch.section, "tr-depth": str(ch.depth), "tr-kicker": _kicker(model, ch, book) if ch.depth == 0 else ""}
        if ch.depth == 0 and ch.section == "prefix":
            kv["epub:type"] = "preface"
        elif ch.depth == 0 and ch.section == "suffix":
            kv["epub:type"] = "appendix"
        path = posixpath.normpath(ch.path)
        pieces.append(restructure_chapter(scope_footnotes(md, cid), chapter_path=ch.path, depth=ch.depth,
                                          chapter_id=cid, title=ch.title_md or ch.title, classes=classes, kv=kv, linker=linker,
                                          heading_ids=heading_ids.by_line.get(path)))
        heads = [h for h in find_headings(pieces[-1]) if h.attrs and h.attrs.id == cid]
        result.chapters.append(StagedChapter(path=ch.path, id=cid, section=ch.section, depth=ch.depth,
                                             title=heads[0].text if heads else ch.title))

    result.formal_count = len(verified_formal_envs(model, lock))
    result.open_count = len([e for e in model.all_envs() if e.kind in OPEN])
    ledger_md = ledger.ledger_markdown(model, lock)
    pieces.append(restructure_chapter(
        ledger_md, chapter_path=ledger.LEDGER_FILE, depth=0, chapter_id=ledger.LEDGER_ID,
        title=config.s(edition.lang, "ledger.title"),
        classes=["tr-chapter", "tr-ledger", "unnumbered"],
        kv={"tr-section": "back", "tr-depth": "0", "tr-kicker": f"LEAN ✓ {result.formal_count}",
            "epub:type": "appendix"},
        linker=None))
    result.chapters.append(StagedChapter(path=ledger.LEDGER_FILE, id=ledger.LEDGER_ID, section="back",
                                         depth=0, title=config.s(edition.lang, "ledger.title")))
    result.book_md.write_text("\n".join(pieces), encoding="utf-8")

    # Files the renderer collected from the book directory (../assets/…).
    book_dir = book.dir.resolve()
    for src in sorted(ctx.book_files):
        src = Path(src)
        try:
            rel = src.resolve().relative_to(book_dir).as_posix()
        except ValueError:
            continue
        if not src.is_file():
            if not src.exists():
                result.warnings.append(f"{edition.key}: linked book file not found: {rel}")
            continue
        dst = out_dir / "_book" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        staged_files.add(f"_book/{rel}")
    # Files the renderer generated for this target (a figure with the palette of each output written in).
    for rel, text in sorted(ctx.book_texts.items()):
        dst = out_dir / "_book" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        staged_files.add(f"_book/{rel}")
    result.files = sorted(staged_files)
    _stage_theme(out_dir)
    result.meta = book_meta(site, book, edition, model, lock, result)
    (out_dir / "meta.json").write_text(json.dumps(result.meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for w in result.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    return result


# --------------------------------------------------------------------------- theme copies


def _stage_theme(out_dir: Path) -> None:
    """Copy the Typst theme so imports resolve inside the Typst root (the staging dir)."""
    dst = out_dir / "_theme" / "typst"
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(TYPST_THEME.iterdir()):
        if p.is_file() and p.suffix in (".typ", ".typst", ".tmTheme", ".svg", ".png"):
            shutil.copy2(p, dst / p.name)
    gen = out_dir / "_theme" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.GENERATED / "tokens.typ", gen / "tokens.typ")
    tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
    for variant in config.PDF_VARIANTS:
        palette = tokens["screen"] if variant == "screen" else tokens["paper"]
        (dst / f"code-{variant}.tmTheme").write_text(code_theme(palette, variant), encoding="utf-8")


def _hex(colour: str) -> str:
    """#rrggbb for a token colour (rgba() is flattened to its rgb part)."""
    colour = colour.strip()
    if colour.startswith("#"):
        return colour
    m = re.match(r"rgba?\(([^)]*)\)", colour)
    if not m:
        raise ValueError(colour)
    r, g, b = (int(float(x)) for x in m.group(1).split(",")[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def code_theme(palette: dict, variant: str) -> str:
    """A TextMate theme for Typst's code highlighting, coloured from theme/tokens.json.

    Green and amber are reserved (Lean-verified / current focus), so code uses cyan,
    magenta, orange, blue and the neutral inks.
    """
    rules = [
        ("Comment", "comment", "dim", "italic"),
        ("Keyword", "keyword, storage, keyword.control, keyword.other", "magenta", ""),
        ("Operator", "keyword.operator, punctuation", "dim", ""),
        ("String", "string, string.quoted", "sigma" if variant == "screen" else "blue", ""),
        ("Number", "constant.numeric, constant.language, constant.character", "orange", ""),
        ("Function", "entity.name.function, support.function, meta.function-call", "cyan", ""),
        ("Type", "entity.name.type, support.type, storage.type, entity.name.class", "blue", ""),
        ("Variable", "variable, variable.parameter", "ink", ""),
        ("Tag", "entity.name.tag, markup.heading", "cyan", "bold"),
        ("Attribute", "entity.other.attribute-name", "orange", ""),
    ]

    def dict_xml(d: dict[str, str]) -> str:
        return "".join(f"<key>{k}</key><string>{v}</string>" for k, v in d.items())

    items = [f"<dict><key>settings</key><dict>{dict_xml({'foreground': _hex(palette['ink']), 'background': _hex(palette['panel-solid'])})}</dict></dict>"]
    for name, scope, colour, style in rules:
        settings = {"foreground": _hex(palette[colour])}
        if style:
            settings["fontStyle"] = style
        items.append(f"<dict><key>name</key><string>{name}</string><key>scope</key><string>{scope}</string>"
                     f"<key>settings</key><dict>{dict_xml(settings)}</dict></dict>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- generated by tools/tbook/pandoc.py from theme/tokens.json — do not edit -->\n'
            '<plist version="1.0"><dict><key>name</key><string>trureturing-' + variant + '</string>'
            '<key>settings</key><array>' + "".join(items) + "</array></dict></plist>\n")


# --------------------------------------------------------------------------- metadata


def _region(bcp47: str) -> str:
    parts = bcp47.split("-")
    for p in parts[1:]:
        if len(p) == 2 and p.isalpha():
            return p.upper()
    return ""


def edition_isbn(book: config.Book, edition: config.Edition) -> str:
    return edition.text(book.isbn).strip() if book.isbn else ""


def edition_identifier(book: config.Book, edition: config.Edition) -> str:
    """ISBN when given, otherwise a deterministic urn:uuid (uuid5 of slug, language and version)."""
    isbn = edition_isbn(book, edition)
    if isbn:
        return "urn:isbn:" + re.sub(r"[^0-9Xx]", "", isbn)
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"trureturing-books:{book.slug}:{edition.lang}:{book.version}"))


def book_meta(site: config.Site, book: config.Book, edition: config.Edition, model: EditionModel,
              lock: lean.Lock | None, staged: Stage | None = None) -> dict:
    """Everything theme/typst/book.typ and cover.typ need, as plain JSON data."""
    lang = edition.lang
    formal = staged.formal_count if staged else len(verified_formal_envs(model, lock))
    opens = staged.open_count if staged else len([e for e in model.all_envs() if e.kind in OPEN])
    try:
        d = datetime.strptime(book.date[:10], "%Y-%m-%d")
        date = {"year": d.year, "month": d.month, "day": d.day, "iso": book.date[:10]}
    except ValueError:
        date = {"year": 1970, "month": 1, "day": 1, "iso": book.date}
    online = site.book_url(book.slug, lang) + "/" if site.base_url else ""
    s = lambda key: config.s(lang, key)  # noqa: E731
    return {
        "schema": "trureturing-books.pdf-meta.v1",
        "slug": book.slug,
        "lang": lang.split("-")[0],
        "bcp47": edition.bcp47,
        "region": _region(edition.bcp47),
        "cjk": lang.split("-")[0] in ("zh", "ja", "ko"),
        "title": edition.title,
        "subtitle": edition.subtitle,
        "description": edition.description,
        "authors": list(book.authors),
        "code": book.code,
        "version": book.version,
        "date": date,
        "license": book.license,
        "isbn": edition_isbn(book, edition),
        "identifier": edition_identifier(book, edition),
        "publisher": site.text(site.title, lang),
        "keywords": _keywords(book, edition),
        "paper": str(book.pdf.get("paper", "a4")),
        "academic_paper": str(book.pdf.get("academic_paper", "a4")),
        "online_url": online,
        "repo_url": f"https://github.com/{site.repo}" if site.repo else "",
        "formal_count": formal,
        "open_count": opens,
        "trureturing": {
            "repo": lock.repo if lock else site.trureturing_repo,
            "commit": lock.commit if lock else "",
            "short": lock.commit[:12] if lock else "",
            "url": lock.tree_url if lock else "",
        },
        "strings": {
            "lang_name": s("meta.name"),
            "lang_short": s("meta.short") or lang.upper(),
            "contents": s("ui.contents"),
            "version": s("ui.version"),
            "language": s("ui.language"),
            "pinned_at": s("ui.pinned_at"),
            "title_open": s("punct.title_open"),
            "title_close": s("punct.title_close"),
            "badge_lean": s("badge.lean"),
            "lean_label": t(lang, "pdf.lean_label"),
            "colophon": t(lang, "pdf.colophon"),
            "abstract": t(lang, "pdf.abstract"),
            "date": t(lang, "pdf.date"),
            "authors": t(lang, "pdf.authors"),
            "license": t(lang, "pdf.license"),
            "isbn": t(lang, "pdf.isbn"),
            "publisher": t(lang, "pdf.publisher"),
            "edition": t(lang, "pdf.edition"),
            "variant_screen": t(lang, "pdf.variant_screen"),
            "variant_print": t(lang, "pdf.variant_print"),
            "variant_academic": t(lang, "pdf.variant_academic"),
            "typeset": t(lang, "pdf.typeset"),
            "typeset_value": t(lang, "pdf.typeset_value"),
            "source": t(lang, "pdf.source"),
            "online": t(lang, "pdf.online"),
            "verified_statement": t(lang, "pdf.verified_statement", n=formal) if formal else t(lang, "pdf.no_formal"),
            "open_statement": t(lang, "pdf.open_statement", n=opens) if opens else "",
            "series": t(lang, "cover.series"),
            "stamp_caption": t(lang, "cover.stamp_caption"),
            "pinned_short": t(lang, "cover.pinned"),
        },
    }


def _keywords(book: config.Book, edition: config.Edition) -> list[str]:
    raw = book.raw.get("book", {}).get("keywords")
    if isinstance(raw, dict):
        raw = raw.get(edition.lang) or next(iter(raw.values()), [])
    words = [str(k) for k in raw] if isinstance(raw, list) else []
    for k in ("trureturing", "Lean 4"):
        if k not in words:
            words.append(k)
    return words


def _filter_meta(lang: str) -> list[str]:
    """Strings the Lua filters need that are not carried by the environment divs."""
    pairs = {
        "tr-punct-open": config.s(lang, "punct.title_open"),
        "tr-punct-close": config.s(lang, "punct.title_close"),
        "tr-lean-label": t(lang, "pdf.lean_label"),
        "tr-badge-lean-title": config.s(lang, "badge.lean_title"),
        "tr-badge-open-title": config.s(lang, "badge.open_title"),
        # Environment titles are read by a separate pandoc.read in tr-env.lua.
        "tr-tex-macros": mathrender.newcommands(),
    }
    out = []
    for k, v in pairs.items():
        out += ["--metadata", f"{k}={v}"]
    return out


def _filters() -> list[str]:
    return ["--lua-filter", str(FILTERS / "tr-book.lua"), "--lua-filter", str(FILTERS / "tr-env.lua")]


# --------------------------------------------------------------------------- PDF


def typst_source(site, book, edition, model, lock, staged: Stage | None = None,
                 stage_dir: Path | None = None) -> Stage:
    """Stage the edition and convert book.md to main.typ (variant-independent)."""
    staged = staged or stage(site, book, edition, model, lock, out_dir=stage_dir)
    run_pandoc([
        "book.md", "--from", READER, "--to", "typst",
        "--template", str((staged.dir / "_theme" / "typst" / "pandoc-template.typst")),
        "--output", "main.typ", "--wrap", "preserve",
        "--metadata", f"lang={edition.bcp47}",
        *_filter_meta(edition.lang), *_filters(),
    ], cwd=staged.dir, env={"SOURCE_DATE_EPOCH": str(source_date_epoch(book))})
    return staged


_TYPST_FONT_WARNING = re.compile(r"unknown font family: (.+)")


def compile_typst(main: Path, out_path: Path, *, root: Path, fmt: str = "pdf", ppi: float | None = None,
                  sys_inputs: dict[str, str] | None = None, timestamp: int | None = None,
                  pdf_tags: bool = True) -> Path:
    """Compile in a fresh process so each document releases its Typst memory on exit."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(output=str(out_path), root=str(root), font_paths=[str(d) for d in font_dirs()],
                  format=fmt, sys_inputs=sys_inputs or {})
    if fmt == "pdf":
        kwargs["pdf_tags"] = pdf_tags
    if ppi:
        kwargs["ppi"] = ppi
    if timestamp:
        kwargs["timestamp"] = timestamp
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("typst_worker.py"))],
            input=json.dumps({"main": str(main), "kwargs": kwargs}),
            capture_output=True, encoding="utf-8",
        )
    except OSError as exc:
        raise PandocError(f"typst failed for {paths.rel(main)}:\n{exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or f"compiler worker exited with status {result.returncode}"
        raise PandocError(f"typst failed for {paths.rel(main)}:\n{detail}")
    try:
        warnings = json.loads(result.stdout)
    except ValueError as exc:
        raise PandocError(f"typst failed for {paths.rel(main)}:\ninvalid compiler worker response") from exc
    missing: set[str] = set()
    for msg in warnings:
        m = _TYPST_FONT_WARNING.search(msg)
        if m:
            missing.add(m.group(1))
        elif "is not a valid typst font" not in msg:
            print(f"  typst: {msg}", file=sys.stderr)
    if missing and os.environ.get("TBOOK_VERBOSE"):
        print(f"  typst: fonts not installed, using fallbacks: {', '.join(sorted(missing))}", file=sys.stderr)
    return out_path


def build_pdf(site, book, edition, model, lock, variant: str, out_path: Path, *,
              stage_dir: Path | None = None) -> Path:
    """Build ``out_path`` (PDF: ``screen`` (dark), ``print`` (light), or ``academic`` (scholarly layout)).

    ``stage_dir`` overrides build/stage/<slug>/<lang>/pandoc/ (tests).
    """
    if variant not in config.PDF_VARIANTS:
        raise PandocError(f"unknown PDF variant {variant!r}; expected one of {config.PDF_VARIANTS}")
    staged = typst_source(site, book, edition, model, lock, stage_dir=stage_dir)
    return compile_typst(staged.dir / "main.typ", Path(out_path), root=staged.dir,
                         sys_inputs={"tr-variant": variant}, timestamp=source_date_epoch(book) or None,
                         pdf_tags=bool(book.pdf.get("academic_tags", False)) if variant == "academic" else True)


# --------------------------------------------------------------------------- EPUB


def epub_palette_css() -> str:
    """CSS custom properties for the EPUB: paper tokens by default, screen tokens in dark themes."""
    tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))

    def block(selector: str, palette: dict, indent: str = "") -> str:
        body = "".join(f"{indent}  --tr-{k}: {v};\n" for k, v in palette.items())
        sem = "".join(f"{indent}  --tr-sem-{k}: var(--tr-{v});\n" for k, v in tokens["semantic"].items())
        return f"{indent}{selector} {{\n{body}{sem}{indent}}}\n"

    dark_sel = (':root[__ibooks_internal_theme*="Night"], :root[__ibooks_internal_theme*="Gray"], '
                ':root[__ibooks_internal_theme*="night"], :root[__ibooks_internal_theme*="gray"]')
    fonts = "".join(f"  --tr-font-{k}: {', '.join(_css_font(f) for f in v)};\n"
                    for k, v in tokens["font"].items() if isinstance(v, list))
    return ("/* generated by tools/tbook/pandoc.py from theme/tokens.json — do not edit */\n"
            + block(":root", tokens["paper"])
            + f":root {{\n{fonts}}}\n"
            + "@media (prefers-color-scheme: dark) {\n" + block(":root", tokens["screen"], "  ") + "}\n"
            + block(dark_sel, tokens["screen"]))


def _css_font(name: str) -> str:
    generic = {"serif", "sans-serif", "monospace", "system-ui", "ui-monospace", "cursive", "fantasy"}
    return name if name in generic else f'"{name}"'


_FONT_FACE_NAMES = {
    "chakrapetch": "Chakra Petch",
    "jetbrainsmono": "JetBrains Mono",
    "notosanssc": "Noto Sans SC",
    "notoserifsc": "Noto Serif SC",
}
_WEIGHTS = {"thin": 100, "extralight": 200, "light": 300, "regular": 400, "medium": 500,
            "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800, "black": 900}


def _font_face(path: Path) -> tuple[str, int, str] | None:
    """(family, weight, style) from a file name such as ChakraPetch-SemiBold.ttf."""
    stem = path.stem.lower().replace("_", "-")
    key = stem.split("-")[0].replace(" ", "")
    family = _FONT_FACE_NAMES.get(key)
    if not family:
        return None
    rest = stem[len(stem.split("-")[0]):].strip("-")
    style = "italic" if "italic" in rest else "normal"
    rest = rest.replace("italic", "")
    weight = 400
    if rest.isdigit():
        weight = int(rest)
    else:
        for name, w in _WEIGHTS.items():
            if rest == name:
                weight = w
    return family, weight, style


def _epub_fonts(book: config.Book) -> list[tuple[Path, str, int, str]]:
    mode = book.epub.get("embed_fonts", False)
    if not mode:
        return []
    cjk = mode == "all"
    out = []
    for p in epub_font_files():
        face = _font_face(p)
        if not face:
            continue
        if face[0].endswith(" SC") and not cjk:
            continue  # CJK faces are large; Apple Books ships PingFang / Songti
        out.append((p, *face))
    return out


def stage_epub(site, book, edition, model, lock, staged: Stage) -> dict:
    """Write epub/ inputs (stylesheet, metadata, colophon, cover) next to book.md."""
    from . import cover

    lang = edition.lang
    edir = staged.dir / "epub"
    edir.mkdir(parents=True, exist_ok=True)
    meta = staged.meta
    fonts = _epub_fonts(book)
    font_css = "".join(
        f'@font-face {{ font-family: "{fam}"; font-weight: {w}; font-style: {st}; src: url("../fonts/{p.name}"); }}\n'
        for p, fam, w, st in fonts)
    css = epub_palette_css() + font_css + (EPUB_THEME / "book.css").read_text(encoding="utf-8")
    (edir / "book.css").write_text(css, encoding="utf-8")

    cover_png = cover.render_cover(site, book, edition, staged.dir / "cover.png", fmt="png", variant="screen",
                                   model=model, lock=lock, meta=meta)

    isbn = meta["isbn"]
    identifier = [{"scheme": "ISBN-13", "text": re.sub(r"[^0-9Xx]", "", isbn)}] if isbn else [{"text": meta["identifier"]}]
    title = [{"type": "main", "text": meta["title"]}]
    if meta["subtitle"]:
        title.append({"type": "subtitle", "text": meta["subtitle"]})
    md_meta = {
        "title": title,
        "creator": [{"role": "author", "text": a} for a in meta["authors"]],
        "identifier": identifier,
        "lang": edition.bcp47,
        "date": meta["date"]["iso"],
        "rights": meta["license"],
        "publisher": meta["publisher"],
        "description": meta["description"],
        "subject": meta["keywords"],
        "toc-title": config.s(lang, "ui.contents"),
        "ibooks": {"version": book.version, "specified-fonts": "true" if fonts else "false"},
    }
    # epubcheck rejects empty dc:* elements: leave out what the book does not define.
    md_meta = {k: v for k, v in md_meta.items() if v not in ("", [], None)}
    (edir / "metadata.json").write_text(json.dumps(md_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (edir / "colophon.md").write_text(epub_colophon(meta), encoding="utf-8")
    return {"cover": cover_png, "fonts": [f[0] for f in fonts]}


def _md_escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#|$])", r"\\\1", text)


def epub_colophon(meta: dict) -> str:
    """Front-matter copyright page (the PDF draws the same data in book.typ)."""
    s = meta["strings"]
    rows = [(s["version"], meta["version"]), (s["date"], meta["date"]["iso"])]
    if meta["authors"]:
        rows.append((s["authors"], config.s(meta["lang"], "punct.list_sep").join(meta["authors"])))
    if meta["license"]:
        rows.append((s["license"], meta["license"]))
    if meta["isbn"]:
        rows.append((s["isbn"], meta["isbn"]))
    if meta["publisher"]:
        rows.append((s["publisher"], meta["publisher"]))
    tru = meta["trureturing"]
    out = [f"# {_md_escape(s['colophon'])} {{#tr-colophon .unnumbered .unlisted .tr-colophon epub:type=\"copyright-page\"}}", ""]
    out += [f"**{_md_escape(meta['title'])}**" + (f"  \n{_md_escape(meta['subtitle'])}" if meta["subtitle"] else ""), ""]
    out.append("::: {.tr-colophon-table}")
    for k, v in rows:
        out.append(f"[{_md_escape(k)}]{{.tr-k}} [{_md_escape(v)}]{{.tr-v}}  ")
    if tru["commit"]:
        out.append(f"[{_md_escape(s['pinned_at'])}]{{.tr-k}} [`{tru['short']}`]({tru['url']}) · `{tru['repo']}`  ")
    if meta["online_url"]:
        out.append(f"[{_md_escape(s['online'])}]{{.tr-k}} <{meta['online_url']}>  ")
    if meta["repo_url"]:
        out.append(f"[{_md_escape(s['source'])}]{{.tr-k}} <{meta['repo_url']}>  ")
    out += [":::", ""]
    out += ["::: {.tr-verified}", _md_escape(s["verified_statement"]), ":::", ""]
    if s["open_statement"]:
        out += [_md_escape(s["open_statement"]), ""]
    return "\n".join(out)


DISPLAY_OPTIONS = "META-INF/com.apple.ibooks.display-options.xml"


def display_options_xml(specified_fonts: bool) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<display_options>\n  <platform name="*">\n'
            f'    <option name="specified-fonts">{"true" if specified_fonts else "false"}</option>\n'
            '  </platform>\n</display_options>\n')


_XHTML_TITLE_RE = re.compile(rb"<title>[^<]*\.xhtml</title>")
_H1_RE = re.compile(rb"<h1[^>]*>(.*?)</h1>", re.S)


def _page_title(xhtml: bytes, fallback: str) -> bytes:
    """Pandoc titles chapter files after their file name; use the chapter heading instead."""
    m = _H1_RE.search(xhtml)
    text = re.sub(rb"<annotation[^>]*>.*?</annotation>", b"", m.group(1), flags=re.S) if m else b""
    text = re.sub(rb"<[^>]+>", b"", text).strip()
    if not text:
        text = fallback.replace("&", "&amp;").replace("<", "&lt;").encode("utf-8")
    return _XHTML_TITLE_RE.sub(lambda _: b"<title>" + re.sub(rb"\s+", b" ", text) + b"</title>", xhtml, count=1)


_ROOTFILE_RE = re.compile(rb'<rootfile\b[^>]*\bfull-path="([^"]+)"')
_ITEM_RE = re.compile(rb"<item\b[^>]*>")
_HREF_RE = re.compile(rb'\bhref="([^"]+)"')
_PROPERTIES_RE = re.compile(rb'\bproperties="([^"]*)"')


def declare_mathml(opf: bytes, opf_name: str, data: dict[str, bytes]) -> bytes:
    """Add the ``mathml`` property to every manifest item whose XHTML contains MathML.

    Pandoc declares it for chapters but not for nav.xhtml, which copies the MathML of
    headings into the table of contents (epubcheck OPF-014).
    """
    base = posixpath.dirname(opf_name)

    def fix(m: re.Match) -> bytes:
        item = m.group(0)
        href = _HREF_RE.search(item)
        if not href:
            return item
        name = posixpath.normpath(posixpath.join(base, unquote(href.group(1).decode("utf-8"))))
        if b"<math" not in data.get(name, b""):
            return item
        props = _PROPERTIES_RE.search(item)
        if props is None:
            end = len(item) - (2 if item.endswith(b"/>") else 1)
            return item[:end].rstrip() + b' properties="mathml"' + item[end:]
        if b"mathml" in props.group(1).split():
            return item
        value = (props.group(1) + b" mathml").strip()
        return item[:props.start(1)] + value + item[props.end(1):]

    return _ITEM_RE.sub(fix, opf)


def finalize_epub(src: Path, dst: Path, *, specified_fonts: bool, epoch: int, title: str = "") -> Path:
    """Rewrite the zip: ``mimetype`` first and stored, Apple display options, chapter titles,
    ``mathml`` declared wherever MathML occurs, fixed timestamps (from ``epoch``) for a
    byte-reproducible file."""
    when = datetime.fromtimestamp(max(epoch, 315532800), tz=timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(src) as zin:
        names = [n for n in zin.namelist() if n != "mimetype" and n != DISPLAY_OPTIONS]
        data = {n: zin.read(n) for n in names}
    for n in names:
        if n.endswith(".xhtml"):
            data[n] = _page_title(data[n], title)
    rootfile = _ROOTFILE_RE.search(data.get("META-INF/container.xml", b""))
    opf_name = rootfile.group(1).decode("utf-8") if rootfile else next((n for n in names if n.endswith(".opf")), "")
    if opf_name in data:
        data[opf_name] = declare_mathml(data[opf_name], opf_name, data)
    order = []
    for n in names:
        order.append(n)
        if n == "META-INF/container.xml":
            order.append(DISPLAY_OPTIONS)
    if DISPLAY_OPTIONS not in order:
        order.insert(0, DISPLAY_OPTIONS)
    data[DISPLAY_OPTIONS] = display_options_xml(specified_fonts).encode("utf-8")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as zout:
        info = zipfile.ZipInfo("mimetype", date_time=when)
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o644 << 16
        zout.writestr(info, b"application/epub+zip")
        for n in order:
            info = zipfile.ZipInfo(n, date_time=when)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zout.writestr(info, data[n], compresslevel=9)
    tmp.replace(dst)
    return dst


@dataclass
class EpubReport:
    valid: bool
    errors: list[str]
    warnings: list[str]
    skipped: str = ""


def check_epub(path: Path) -> EpubReport:
    """Run epubcheck (Python package, needs Java). ``skipped`` explains when it could not run."""
    if not shutil.which("java"):
        return EpubReport(True, [], [], skipped="java not found")
    try:
        from epubcheck import EpubCheck  # type: ignore
    except ImportError:
        return EpubReport(True, [], [], skipped="epubcheck package not installed")
    result = EpubCheck(str(path))
    errors, warnings = [], []
    for msg in result.messages:
        level = str(getattr(msg, "level", "")).upper()
        text = f"{getattr(msg, 'id', '')} {getattr(msg, 'location', '')}: {getattr(msg, 'message', msg)}".strip()
        if level in ("ERROR", "FATAL"):
            errors.append(text)
        elif level in ("WARNING",):
            warnings.append(text)
    return EpubReport(bool(result.valid) and not errors, errors, warnings)


def build_epub(site, book, edition, model, lock, out_path: Path, *, stage_dir: Path | None = None) -> Path:
    """Build an EPUB 3 for Apple Books at ``out_path`` and validate it with epubcheck.

    ``stage_dir`` overrides build/stage/<slug>/<lang>/pandoc/ (tests).
    """
    out_path = Path(out_path)
    staged = stage(site, book, edition, model, lock, out_dir=stage_dir)
    extra = stage_epub(site, book, edition, model, lock, staged)
    epoch = source_date_epoch(book)
    raw = staged.dir / "epub" / "pandoc.epub"
    args = [
        "epub/colophon.md", "book.md", "--from", READER, "--to", "epub3", "--output", str(raw.relative_to(staged.dir)),
        "--mathml", "--toc", "--toc-depth", "2", "--split-level", "1",
        "--epub-cover-image", str(Path(extra["cover"]).relative_to(staged.dir)),
        "--css", "epub/book.css", "--metadata-file", "epub/metadata.json", "--syntax-highlighting", "none",
        "--resource-path", ".", "--wrap", "none",
        *_filter_meta(edition.lang), *_filters(),
    ]
    for font in extra["fonts"]:
        args += ["--epub-embed-font", str(font)]
    run_pandoc(args, cwd=staged.dir, env={"SOURCE_DATE_EPOCH": str(epoch)})
    finalize_epub(raw, out_path, specified_fonts=bool(extra["fonts"]), epoch=epoch, title=staged.meta["title"])
    mode = os.environ.get("TBOOK_EPUBCHECK", "1").lower()
    if mode not in ("0", "false", "no", "off"):
        report = check_epub(out_path)
        if report.skipped:
            print(f"  epubcheck skipped: {report.skipped}", file=sys.stderr)
        else:
            for w in report.warnings:
                print(f"  epubcheck warning: {w}", file=sys.stderr)
            for e in report.errors:
                print(f"  epubcheck error: {e}", file=sys.stderr)
            if report.errors and mode != "warn":
                raise PandocError(f"epubcheck: {len(report.errors)} error(s) in {paths.rel(out_path)}")
    return out_path
