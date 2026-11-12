"""The structured view of one edition: chapters, numbered environments, references.

Environment kinds and their verification policy:

=============  ==================================================================
formal         theorem, lemma, proposition, corollary — by default cite >=1 Lean GID
               (``lean="…"``); every cited declaration must be frozen and of kind
               ``theorem``. Rendered with the green LEAN ✓ badge. Explicit
               status="written-proof" instead requires a proof block and forbids lean; violet badge.
definition     definition — ``lean`` optional; when given it must resolve (any kind).
open           conjecture, problem — MUST NOT cite Lean; rendered with the OPEN badge.
informal       example, remark — ``lean`` optional; when given it must resolve.
proof          proof — unnumbered; ``lean`` optional.
media          viz, film, slides, figure — embeds, not numbered.
=============  ==================================================================

Numbered kinds share one counter per top-level chapter: ``定理2.1``, ``定义2.2``…
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, lean, mdscan
from .summary import Chapter, Summary, SummaryError, chapter_prefix, parse_summary

FORMAL = ("theorem", "lemma", "proposition", "corollary")
# Public capability used by template layers; this status never asserts kernel verification.
WRITTEN_PROOF = "written-proof"
DEFINITION = ("definition",)
OPEN = ("conjecture", "problem")
INFORMAL = ("example", "remark")
PROOF = ("proof",)
MEDIA = ("viz", "film", "slides", "figure")
NUMBERED = FORMAL + DEFINITION + OPEN + INFORMAL
ENV_KINDS = NUMBERED + PROOF
ALL_KINDS = ENV_KINDS + MEDIA
# mdscan.stray_lean_links: a Lean link whose declaration nothing checks.
STRAY_LEAN = ("this lean: link is not read by the book tools (it is written across lines, or sits in raw HTML), "
              "so its declaration is not checked and the builds drop its destination: write it on one line, "
              "[text](lean:GID) or [label]: lean:GID")


def kind_of(div: mdscan.Div) -> str | None:
    for cls in div.classes:
        if cls in ALL_KINDS:
            return cls
    return None


def status_of(kind: str) -> str:
    if kind in FORMAL:
        return "lean"
    if kind in OPEN:
        return "open"
    if kind in DEFINITION:
        return "definition"
    if kind in PROOF:
        return "proof"
    if kind in MEDIA:
        return "media"
    return "informal"


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    path: Path | None
    line: int
    message: str

    def format(self) -> str:
        from .paths import rel

        loc = rel(self.path) if self.path else "-"
        if self.line:
            loc += f":{self.line}"
        return f"{self.severity.upper():7} {loc}: {self.message}"

    def github(self) -> str:
        from .paths import rel

        kind = "error" if self.severity == "error" else "warning"
        file = f" file={rel(self.path)}" if self.path else ""
        line = f",line={self.line}" if self.line else ""
        msg = self.message.replace("%", "%25").replace("\n", "%0A")
        return f"::{kind}{file}{line}::{msg}"


@dataclass
class Env:
    kind: str
    id: str
    title: str
    lean: list[str]
    attrs: mdscan.Attrs
    chapter: Chapter
    line: int
    number: str = ""  # "2.1" for numbered kinds
    div: mdscan.Div | None = field(default=None, repr=False)

    @property
    def status(self) -> str:
        if self.kind in FORMAL and self.attrs.get("status") == WRITTEN_PROOF:
            return WRITTEN_PROOF
        return status_of(self.kind)

    def label(self, lang: str) -> str:
        return config.s(lang, f"env.{self.kind}")

    def ref_text(self, lang: str) -> str:
        """``定理2.1`` / ``Theorem 2.1``."""
        sep = "" if lang.startswith(("zh", "ja")) else " "
        return f"{self.label(lang)}{sep}{self.number}" if self.number else self.label(lang)

    def heading(self, lang: str, title: str | None = None) -> str:
        """``定理2.1（亏量三值）`` / ``Theorem 2.1 (Deficit is three-valued)``; ``title`` replaces the
        title as written (e.g. with its references resolved, :meth:`EditionModel.title_text`)."""
        head = self.ref_text(lang)
        title = self.title if title is None else title
        if title:
            head += config.s(lang, "punct.title_open") + title + config.s(lang, "punct.title_close")
        return head


@dataclass
class ChapterDoc:
    chapter: Chapter
    path: Path
    text: str
    blocks: list[mdscan.Node]
    envs: list[Env] = field(default_factory=list)
    media: list[Env] = field(default_factory=list)
    refs: list[tuple[int, str]] = field(default_factory=list)  # (line, id)
    lean_links: list[tuple[int, str]] = field(default_factory=list)  # (line, gid)


@dataclass
class EditionModel:
    edition: config.Edition
    summary: Summary | None
    chapters: list[ChapterDoc]
    issues: list[Issue]
    envs: dict[str, Env] = field(default_factory=dict)

    @property
    def lang(self) -> str:
        return self.edition.lang

    def all_envs(self) -> list[Env]:
        return [e for ch in self.chapters for e in ch.envs]

    def formal_envs(self) -> list[Env]:
        return [e for e in self.all_envs() if e.kind in FORMAL]

    def cited_gids(self) -> list[tuple[Path, int, str, Env | None]]:
        out = []
        for ch in self.chapters:
            for env in ch.envs + ch.media:
                for g in env.lean:
                    out.append((ch.path, env.line, g, env))
            for line, g in ch.lean_links:
                out.append((ch.path, line, g, None))
        return out

    def chapter_of(self, env_id: str) -> ChapterDoc | None:
        for ch in self.chapters:
            if any(e.id == env_id for e in ch.envs):
                return ch
        return None

    def title_text(self, env: Env) -> str:
        """``env.title`` as plain text: :meth:`title_markdown` with the backslash escapes outside math
        undone (``C\\*-代数`` → ``C*-代数``; TeX in ``$…$`` stays). What every target shows; for HTML
        contexts escape it (the site, mdBook's header via :func:`tbook.render.title_html`)."""
        return mdscan.unescape_markdown(self.title_markdown(env))

    def title_markdown(self, env: Env, ref: Callable[[Env, str], str] | None = None) -> str:
        """``env.title`` (inline Markdown) with each ``[@id]`` outside code spans replaced by the
        referenced environment's reference text (``定理2.1``), formatted by ``ref(target, text)``
        (default: the text itself).

        The result is still Markdown (escapes as written): for tools/filters/tr-env.lua and the
        ledger's table cells. An unknown id stays as written (``./tbook check`` reports it). A
        ``lean:`` link becomes its text: titles never link to Lean (``./tbook check`` reports it).
        """
        title = mdscan.strip_lean_links(env.title) if env.title and "lean:" in env.title else env.title
        if not title or "[@" not in title:
            return title

        def repl(m) -> str:
            target = self.envs.get(m.group("id"))
            if target is None:
                return m.group(0)
            text = target.ref_text(self.lang)
            return ref(target, text) if ref else text

        return mdscan.sub_outside_code(mdscan.REF_RE, repl, title)


def load_edition(edition: config.Edition) -> EditionModel:
    issues: list[Issue] = []
    model = EditionModel(edition=edition, summary=None, chapters=[], issues=issues)
    if not edition.summary.exists():
        issues.append(Issue("error", edition.summary, 0, "SUMMARY.md is missing"))
        return model
    try:
        summary = parse_summary(edition.summary)
    except SummaryError as exc:
        issues.append(Issue("error", exc.path, exc.line, exc.message))
        return model
    model.summary = summary
    # One counter per numbered/suffix chapter; all prefix chapters share number 0.
    counters: dict[int | str, int] = {}
    for chapter in summary.chapters:
        if chapter.draft:
            continue
        path = edition.dir / chapter.path
        if not path.exists():
            issues.append(Issue("error", edition.summary, chapter.line, f"chapter file not found: {chapter.path}"))
            continue
        text = path.read_text(encoding="utf-8")
        scan_issues: list[mdscan.ScanIssue] = []
        blocks = mdscan.parse_blocks(text, scan_issues)
        for si in scan_issues:
            issues.append(Issue(si.severity, path, si.line, si.message))
        doc = ChapterDoc(chapter=chapter, path=path, text=text, blocks=blocks)
        prefix = chapter_prefix(summary, chapter)
        for node in mdscan.walk(blocks):
            if not isinstance(node, mdscan.Div):
                continue
            kind = kind_of(node)
            if kind is None:
                continue
            env = Env(
                kind=kind,
                id=node.attrs.id,
                title=node.attrs.get("title"),
                lean=lean.split_gids(node.attrs.get("lean")),
                attrs=node.attrs,
                chapter=chapter,
                line=node.start,
                div=node,
            )
            if kind in NUMBERED:
                ckey: int | str = "prefix" if prefix == "0" else chapter.top
                counters[ckey] = counters.get(ckey, 0) + 1
                env.number = f"{prefix}.{counters[ckey]}"
            if kind in MEDIA:
                doc.media.append(env)
            else:
                doc.envs.append(env)
        # As the builds read them: not in code, not in HTML comments; Lean links inline
        # (``(lean:…)``, ``(<lean:…>)``, ``<lean:…>``) or in reference definitions (``[x]: lean:…``),
        # which cannot interrupt a paragraph (mdscan.definition_roles).
        for lineno, line, role in mdscan.iter_text(blocks):
            for m in mdscan.find_outside_code(mdscan.REF_RE, line):
                doc.refs.append((lineno, m.group("id")))
            for gid in mdscan.lean_link_gids(line, role):
                doc.lean_links.append((lineno, gid))
        # A Lean link the line scanner cannot read cites a declaration nothing checks; the builds drop it.
        for node in mdscan.walk(blocks):
            if isinstance(node, mdscan.Text):
                for stray in mdscan.stray_lean_links(node.lines, node.cont):
                    issues.append(Issue("error", path, node.start + stray.line, STRAY_LEAN))
        model.chapters.append(doc)
    for ch in model.chapters:
        for env in ch.envs + ch.media:
            if not env.id:
                continue
            if env.id in model.envs:
                prev = model.envs[env.id]
                issues.append(Issue("error", ch.path, env.line,
                                    f"duplicate id #{env.id} (first used in {prev.chapter.path}:{prev.line})"))
            else:
                model.envs[env.id] = env
    return model


def load_book_models(book: config.Book) -> dict[str, EditionModel]:
    return {ed.lang: load_edition(ed) for ed in book.editions}


def media_cited_gids(book: config.Book) -> list[tuple[Path, int, str]]:
    """(file, line, GID) cited by a book's visualizations, films and slide decks.

    These count as citations for ``./tbook pin --refresh`` and the lock check, exactly like
    chapter citations. Each media module enforces its own rules about declaration kinds.
    """
    import importlib

    out: list[tuple[Path, int, str]] = []
    for kind in MEDIA:
        try:
            mod = importlib.import_module(f"tbook.{kind}")
        except ImportError:
            continue
        fn = getattr(mod, "cited_gids", None)
        if fn is None:
            continue
        try:
            out.extend(fn(book))
        except NotImplementedError:
            continue
    return out
