"""Parse an mdBook ``SUMMARY.md`` into an ordered chapter list.

Supported, as in mdBook: an optional ``# Summary`` title, prefix chapters
(``[Title](file.md)`` before the first list), numbered chapters (nested ``-``/``*``
list items), part titles (``# Part``) between lists, separators (``---``), suffix
chapters after the numbered list, and draft chapters (``- [Title]()``).

Theorem numbering uses the top-level chapter: numbered chapters give ``2.3``,
prefix chapters give ``0.n`` and suffix chapters (appendices) give ``A.n``, ``B.n``…
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import mdscan

# Titles may contain escapes and balanced brackets, as mdBook accepts: ``[Section [x] y](a.md)``.
LINK_RE = re.compile(r"^\[(?P<title>(?:[^\[\]\\]|\\.|\[(?:[^\[\]\\]|\\.)*\])*)\]\((?P<path>[^)]*)\)\s*$")
ITEM_RE = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<rest>.*)$")
PART_RE = re.compile(r"^#\s+(?P<title>.+?)\s*$")
SEP_RE = re.compile(r"^\s*-{3,}\s*$")


class SummaryError(Exception):
    def __init__(self, path: Path, line: int, message: str):
        super().__init__(f"{path}:{line}: {message}")
        self.path, self.line, self.message = path, line, message


@dataclass
class Chapter:
    title: str  # plain text (:func:`_unescape`): what the sidebar, page titles and the site show
    path: str | None  # relative to the edition directory; None for drafts
    section: str  # "prefix" | "numbered" | "suffix"
    number: tuple[int, ...] = ()  # mdBook section number for numbered chapters
    depth: int = 0  # nesting depth (0 = top level)
    part: str = ""  # most recent part title
    top: int = 0  # index of the top-level chapter this one belongs to
    line: int = 0
    children: list["Chapter"] = field(default_factory=list, repr=False)
    title_md: str = ""  # the link text as written (inline Markdown), for Markdown targets (Pandoc)

    @property
    def draft(self) -> bool:
        return not self.path

    @property
    def number_label(self) -> str:
        return ".".join(str(n) for n in self.number)


@dataclass
class Summary:
    path: Path
    title: str
    chapters: list[Chapter]  # flattened, in reading order

    def top_level(self) -> list[Chapter]:
        return [c for c in self.chapters if c.depth == 0]

    def files(self) -> list[str]:
        return [c.path for c in self.chapters if c.path]


def _letters(n: int) -> str:
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def chapter_prefix(summary: Summary, chapter: Chapter) -> str:
    """Prefix used in theorem numbers for every environment inside ``chapter``."""
    top = summary.top_level()[chapter.top]
    if top.section == "numbered":
        return str(top.number[0])
    if top.section == "prefix":
        return "0"
    suffix_tops = [c for c in summary.top_level() if c.section == "suffix"]
    return _letters(suffix_tops.index(top))


def parse_summary(path: Path, *, text: str | None = None) -> Summary:
    if text is None:
        text = path.read_text(encoding="utf-8")
    title = ""
    chapters: list[Chapter] = []
    section = "prefix"
    part = ""
    stack: list[tuple[int, Chapter]] = []  # (indent, chapter)
    counters: list[int] = []
    in_comment = False
    seen_numbered = False
    top_index = -1

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.strip().startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        if not line.strip():
            continue
        part_m = PART_RE.match(line)
        if part_m:
            if not title and not chapters:
                title = part_m.group("title")
            else:
                part = part_m.group("title")
                if seen_numbered:
                    section = "numbered"
            stack.clear()
            continue
        if SEP_RE.match(line):
            stack.clear()
            continue
        item = ITEM_RE.match(line)
        if item:
            if section == "suffix":
                raise SummaryError(path, lineno, "numbered chapters cannot follow suffix chapters")
            section = "numbered"
            seen_numbered = True
            indent = len(item.group("indent").expandtabs(4))
            link = LINK_RE.match(item.group("rest").strip())
            if not link:
                raise SummaryError(path, lineno, "list items must be links: - [Title](file.md)")
            while stack and stack[-1][0] >= indent:
                stack.pop()
            depth = len(stack)
            del counters[depth + 1 :]
            while len(counters) < depth + 1:
                counters.append(0)
            counters[depth] += 1
            ch = Chapter(
                title=_unescape(link.group("title")),
                title_md=link.group("title"),
                path=link.group("path").strip() or None,
                section="numbered",
                number=tuple(counters[: depth + 1]),
                depth=depth,
                part=part,
                line=lineno,
            )
            if depth == 0:
                top_index += 1
            else:
                stack[-1][1].children.append(ch)
            ch.top = top_index
            chapters.append(ch)
            stack.append((indent, ch))
            continue
        link = LINK_RE.match(line.strip())
        if link:
            if seen_numbered:
                section = "suffix"
            top_index += 1
            ch = Chapter(
                title=_unescape(link.group("title")),
                title_md=link.group("title"),
                path=link.group("path").strip() or None,
                section=section if section != "numbered" else "suffix",
                part=part,
                line=lineno,
                top=top_index,
            )
            chapters.append(ch)
            stack.clear()
            continue
        raise SummaryError(path, lineno, f"unrecognised SUMMARY line: {line.strip()[:60]}")
    for ch in chapters:
        if ch.path and (ch.path.startswith("/") or ".." in Path(ch.path).parts):
            raise SummaryError(path, ch.line, f"chapter path must stay inside the edition: {ch.path}")
        if ch.path and not ch.path.endswith(".md"):
            raise SummaryError(path, ch.line, f"chapter path must be a .md file: {ch.path}")
    return Summary(path=path, title=title, chapters=chapters)


def _unescape(s: str) -> str:
    """The plain text of a SUMMARY link text: Markdown escapes of ASCII punctuation are undone, as
    mdBook does (``C\\*-代数`` → ``C*-代数``, ``\\[x\\]`` → ``[x]``), except inside ``$…$``, so TeX in a
    title survives (``[附录 B：$\\varphi$-边界](b.md)``, ``$\\{x\\}$``). ``tbook.html._escape_title``
    writes it back for mdBook (:func:`tbook.mdscan.unescape_markdown`).
    """
    return mdscan.unescape_markdown(s)
