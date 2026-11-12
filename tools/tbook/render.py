"""Target-independent chapter transformation shared by the mdBook and Pandoc pipelines.

Given an :class:`~tbook.model.EditionModel`, :func:`chapter_markdown` rewrites a
chapter's Markdown for one target:

* ``[@id]`` → ``[定理2.1](href)`` (``href`` from :attr:`RenderContext.env_href`); in an
  environment title → ``定理2.1`` (a ``[定理2.1](#id)`` link for Pandoc, :func:`env_title`);
* ``[text](lean:GID)`` (also ``(<lean:GID>)``, any title, a reference definition ``[x]: lean:GID``
  in or out of a block quote or list item, and the autolink ``<lean:GID>``, whose text is the GID)
  → a permalink to the declaration's Lean source at the pinned commit (just the text when the lock
  does not resolve the GID; a reference definition gets ``#``). A ``lean:`` link the line scanner
  cannot read (written across lines, also with a ``<lean:GID>`` destination, raw HTML) loses its
  destination the same way (:func:`without_stray_lean`): no target ever writes a ``lean:`` URL;
* an empty destination (``[x]()``, ``[x]: <>``) is kept as written and reported in ``ctx.issues``
  (``tools/filters/tr-book.lua`` shows such a link as text in PDF/EPUB); for Pandoc, ``[label]:``
  with no destination is escaped so it stays text, as in CommonMark (:func:`label_only_as_text`);
* links/images (inline, ``<…>`` destinations, reference definitions) that point into the
  book directory outside the edition (``../assets/x.svg``) → percent-encoded paths into the
  staged copy ``_book/…`` (files collected in ``ctx.book_files``); ``<…>`` destinations are
  written as plain percent-encoded ones, which every target reads the same way;
* for mdBook, links to a ``README.md`` chapter → ``index.md`` (mdBook publishes it as
  ``index.html``);
* environment divs → target markup (HTML ``<section>`` for mdBook; an enriched fenced div
  for Pandoc, which ``tools/filters/tr-env.lua`` renders to Typst or EPUB XHTML);
* media divs (``viz``/``film``/``slides``) → whatever ``tbook.<kind>.render_embed`` returns.

Every renderer uses :func:`env_view`, so numbering, labels, badges and Lean links agree
across HTML, PDF and EPUB. Code spans and HTML comments are left alone (tbook.mdscan).
"""

from __future__ import annotations

import html
import importlib
import posixpath
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, evidence, lean, mdscan
from .model import FORMAL, MEDIA, ChapterDoc, EditionModel, Env

# Inline links/images and link reference definitions, as every reader of links sees them (tbook.mdscan).
LINK_RE = mdscan.LINK_RE
REFDEF_RE = mdscan.REFDEF_RE
# ``[label]:`` followed by text on the same line, at the left margin or after block-quote markers, list
# markers or a list item's indentation, on a line where a definition may begin (mdscan.DEF_START: Pandoc,
# like CommonMark, reads a line that goes on with a paragraph as text). Unless REFDEF_RE accepts it,
# CommonMark (mdBook) reads it as a paragraph, but Pandoc's Markdown takes a URL of several words
# (``[1]: Knuth, TAOCP.`` or ``- [注]: 见 ![图](a.svg)``) and drops the line; for Pandoc its "[" is
# escaped so every target shows it.
_CONTAINER_RE = re.compile(mdscan.CONTAINER)
_REFDEF_LIKE_RE = re.compile(r"^(?P<indent>" + mdscan.CONTAINER + r")\[(?!\^)" + mdscan.LINK_TEXT + r"\]:[ \t]*\S")
# ``[label]:`` with nothing after the colon. CommonMark reads a definition only when the next line of the
# paragraph holds its destination (and optional title, mdscan.DEF_DEST); otherwise the line is text, while
# Pandoc's Markdown reads a definition with an empty destination (or the next line as one) and drops the lines.
_LABEL_ONLY_RE = re.compile(r"^(?P<indent>" + mdscan.CONTAINER + r")\[(?!\^)" + mdscan.LINK_TEXT + r"\]:[ \t]*$")
# A destination on the line after its label (mdscan.DEF_DEST), after the block-quote markers.
_DEST_LINE_RE = re.compile(r"[ \t>]*" + mdscan.REFDEF_DEST)
_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]*:", re.I)
EXTERNAL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|/)", re.I)
# Characters a plain (non ``<…>``) destination cannot hold, and those a decoded file path
# must also escape to stay one path.
_DEST_UNSAFE_RE = re.compile(r"[\s<>()]")
_PATH_UNSAFE_RE = re.compile(r"[\s<>()%#?\\]")


def _quote(pattern: re.Pattern, text: str) -> str:
    return pattern.sub(lambda m: urllib.parse.quote(m.group(), safe=""), text)


@dataclass
class RenderContext:
    site: config.Site
    book: config.Book
    edition: config.Edition
    model: EditionModel
    lock: lean.Lock | None
    target: str  # "mdbook" | "pandoc"
    # href to an environment from a chapter (mdBook needs relative chapter paths).
    env_href: Callable[[Env, ChapterDoc], str] | None = None
    # where the staged edition puts files from the book directory (relative to the edition root)
    book_prefix: str = "_book"
    book_files: set[Path] = field(default_factory=set)
    # generated text files staged next to them: path under the book directory → content (tbook.figure
    # stages a figure once per palette for the PDF and EPUB)
    book_texts: dict[str, str] = field(default_factory=dict)
    # files inside the edition directory that links point at (staged with the edition; ``check`` reads it)
    edition_files: set[Path] = field(default_factory=set)
    issues: list[str] = field(default_factory=list)

    @property
    def lang(self) -> str:
        return self.edition.lang

    def href(self, env: Env, frm: ChapterDoc) -> str:
        if self.env_href:
            return self.env_href(env, frm)
        return "#" + env.id


def is_readme(path: str) -> bool:
    """mdBook's index preprocessor publishes a chapter ``README.md`` (any case) as ``index.md``."""
    stem, ext = posixpath.splitext(posixpath.basename(path))
    return stem.lower() == "readme" and ext.lower() == ".md"


def mdbook_chapter_path(path: str) -> str:
    """The path mdBook publishes chapter ``path`` under: ``a/README.md`` → ``a/index.md``.

    mdBook does not rewrite links to a README chapter, so every link into one (``[@id]``,
    plain links, the ledger) must use this path or it points at a missing ``README.html``.
    """
    return posixpath.join(posixpath.dirname(path), "index.md") if is_readme(path) else path


def mdbook_env_href(model: EditionModel) -> Callable[[Env, ChapterDoc], str]:
    def href(env: Env, frm: ChapterDoc) -> str:
        target = model.chapter_of(env.id)
        if target is None or target is frm:
            return "#" + env.id
        rel = posixpath.relpath(mdbook_chapter_path(target.chapter.path), posixpath.dirname(frm.chapter.path) or ".")
        return f"{rel}#{env.id}"

    return href


# --------------------------------------------------------------------------- data views


def lean_view(gid: str, lock: lean.Lock | None) -> dict:
    """What the book shows for ``gid``. Links only when the lock resolves it (``resolved``):
    an unresolved GID is shown as text, never as a link that suggests the declaration exists."""
    view = {"gid": gid, "name": "", "kind": "", "url": "", "state_url": "", "blueprint_url": "",
            "line": 0, "signature": "", "statement_id": "", "resolved": False}
    try:
        g = lean.parse_gid(gid)
    except lean.LeanError:
        return view
    view["name"] = g.lean_module + "." + g.name if not g.name.startswith(g.lean_module) else g.name
    res = lock.get(gid) if lock else None
    if res:
        view.update(name=res.name, kind=res.kind, line=res.line, signature=res.signature,
                    statement_id=res.statement_id, resolved=True,
                    url=lock.source_url(gid), state_url=lock.state_url(gid),
                    blueprint_url=lock.blueprint_url(gid))
    return view


def lean_verified(views: list[dict]) -> bool:
    """True when every cited declaration resolves in the lock to a Lean theorem (the green badge)."""
    return bool(views) and all(v["resolved"] and v["kind"] in lean.FORMAL_KINDS for v in views)


def env_verified(env: Env, lock: lean.Lock | None) -> bool:
    """A formal environment the build shows as LEAN ✓: its citations pass :func:`lean_verified`."""
    return env.kind in FORMAL and env.status == "lean" and lean_verified([lean_view(g, lock) for g in env.lean])


def verified_envs(envs: list[Env], lock: lean.Lock | None) -> list[Env]:
    """The formal environments of ``envs`` that every count of "LEAN ✓" may include."""
    return [e for e in envs if env_verified(e, lock)]


def _s(lang: str, key: str, fallback: str, default: str = "") -> str:
    return config.s(lang, key) or config.s(lang, fallback) or default


def unverified_badge(lang: str) -> tuple[str, str]:
    """Badge text and tooltip for a formal result the lock does not back (``check`` rejects it)."""
    return (_s(lang, "badge.unverified", "slides.badge_unverified", "UNVERIFIED"),
            _s(lang, "badge.unverified_title", "slides.badge_unverified_title"))


def _env_doc_path(env: Env, ctx: RenderContext) -> Path | str:
    doc = next((d for d in ctx.model.chapters if d.chapter is env.chapter), None)
    return doc.path if doc else (env.chapter.path or "?")


def env_title(env: Env, ctx: RenderContext) -> tuple[str, str]:
    """The title of ``env`` as (plain text, target Markdown), with each ``[@id]`` resolved.

    A title is inline Markdown (docs/AUTHORING.md §2). Plain text (:meth:`EditionModel.title_text`)
    replaces a reference by its reference text (``定理2.1``) and undoes backslash escapes outside
    math: headings and the site show it as text. The target Markdown keeps the escapes; for mdBook
    the reference is its text and :func:`title_html` writes the header, for Pandoc it is a link
    (``[定理2.1](#id)``): tools/filters/tr-env.lua parses the title as Markdown, so the link works
    in PDF and EPUB like a reference in prose. Unknown ids stay as written and are reported in
    ``ctx.issues`` (``./tbook check`` rejects them).
    """
    if not env.title:
        return "", ""
    for m in mdscan.find_outside_code(mdscan.REF_RE, env.title):
        if m.group("id") not in ctx.model.envs:
            ctx.issues.append(f"{_env_doc_path(env, ctx)}: unknown reference [@{m.group('id')}] in a title")
    plain = ctx.model.title_text(env)
    if ctx.target != "pandoc":
        return plain, ctx.model.title_markdown(env)
    return plain, ctx.model.title_markdown(env, ref=lambda target, text: f"[{text}](#{target.id})")


# What a title's text may not carry into the mdBook header as such: tbook.mathrender reads "$" as a
# formula delimiter, "\" as its escape and "`" as a code span in that HTML line too.
_HEADER_LITERAL = {"$": "&#36;", "\\": "&#92;", "`": "&#96;"}


def title_html(markdown: str) -> str:
    """A title (inline Markdown, references already resolved) as the HTML of the mdBook header.

    Text reads as everywhere else (:func:`tbook.mdscan.unescape_markdown`: ``C\\*-代数`` shows
    ``C*-代数``); a literal ``$``, ``\\`` or backtick is written as a character reference so the
    header has exactly the formulas Pandoc sees (``\\$x\\$`` is no formula). Formulas stay TeX for
    tbook.mathrender, code spans stay as written.
    """
    out = []
    for kind, piece in mdscan.inline_segments(markdown):
        if kind == "text":
            plain = esc(mdscan.unescape_text(piece))
            out.append("".join(_HEADER_LITERAL.get(ch, ch) for ch in plain))
        else:
            out.append(esc(piece))
    return "".join(out)


def env_view(env: Env, ctx: RenderContext) -> dict:
    lang = ctx.lang
    title, target_title = env_title(env, ctx)
    badge = ""
    badge_title = ""
    status = env.status
    leans = [lean_view(g, ctx.lock) for g in env.lean] if status != "written-proof" else []
    unverified = False
    if status == "written-proof":
        badge, badge_title = config.s(lang, "badge.written_proof"), config.s(lang, "badge.written_proof_title")
    elif env.kind in FORMAL:
        if lean_verified(leans):
            badge, badge_title = config.s(lang, "badge.lean"), config.s(lang, "badge.lean_title")
        else:
            # The build never claims what the lock cannot back: red UNVERIFIED, as the slides do.
            unverified = True
            status = "open"
            badge, badge_title = unverified_badge(lang)
    elif env.status == "open":
        badge, badge_title = config.s(lang, "badge.open"), config.s(lang, "badge.open_title")
    # Only a LEAN ✓ badge links (to the first declaration); an UNVERIFIED badge never does, in any
    # target, even when the lock resolves a cited declaration (a def): the footer links that.
    badge_url = leans[0]["url"] if status == "lean" and badge and leans and not unverified else ""
    return {
        "kind": env.kind,
        "id": env.id,
        "number": env.number,
        "label": env.label(lang),
        "ref_text": env.ref_text(lang),
        "heading": env.heading(lang, title),
        "title": target_title,  # inline Markdown for the target (references as text, or links for Pandoc)
        "title_text": title,  # plain text
        "status": status,
        "unverified": unverified,
        "badge": badge,
        "badge_title": badge_title,
        "badge_url": badge_url,
        "lean": leans,
        **source_view(env),
        "attrs": dict(env.attrs.kv),
    }


# --------------------------------------------------------------------------- inline


def rewrite_links(line: str, doc: ChapterDoc, ctx: RenderContext, role: str = mdscan.DEF_START) -> str:
    """Rewrite the local links and images of ``line`` (see the module docstring); records the files
    they point at in ``ctx.book_files`` / ``ctx.edition_files`` and links that leave the book in
    ``ctx.issues``. ``role`` (:func:`tbook.mdscan.definition_roles`) says whether a reference
    definition may begin on the line; a destination on the line after its label is not read, only
    reported (unless it has a scheme: ``lean:`` is :func:`without_stray_lean`'s)."""
    book_dir = ctx.book.dir.resolve()
    edition_dir = ctx.edition.dir.resolve()
    chapter_dir = doc.path.parent.resolve()

    def new_url(raw: str) -> str | None:
        """The destination to write for ``raw`` (as written); None drops the link, keeping its text."""
        angle = raw.startswith("<") and raw.endswith(">")
        url = raw[1:-1] if angle else raw
        if not url:  # kept as written: a definition's "<>" may not become an empty (no) destination
            return raw
        if url == "trureturing:":
            return ctx.lock.tree_url if ctx.lock else None
        if url.startswith("lean:"):
            return lean_view(url[5:], ctx.lock)["url"] or None
        plain = _quote(_DEST_UNSAFE_RE, url) if angle else raw
        path_part, _, frag = url.partition("#")
        if EXTERNAL_RE.match(url) or not path_part:
            return plain
        frag = "#" + (_quote(_DEST_UNSAFE_RE, frag) if angle else frag) if frag else ""
        path = urllib.parse.unquote(path_part)
        target = (chapter_dir / path).resolve()
        try:
            inside = target.relative_to(edition_dir).as_posix()
        except ValueError:
            inside = None
        if inside is not None:  # inside the edition: staged as is
            ctx.edition_files.add(target)
            if (ctx.target == "mdbook" and is_readme(inside)
                    and any(posixpath.normpath(d.chapter.path) == inside for d in ctx.model.chapters)):
                return _quote(_PATH_UNSAFE_RE, mdbook_chapter_path(path)) + frag
            return plain
        try:
            inside_book = target.relative_to(book_dir)
        except ValueError:
            ctx.issues.append(f"{doc.path}: link leaves the book directory: {url}")
            return plain
        ctx.book_files.add(target)
        staged_chapter_dir = posixpath.dirname(doc.chapter.path) or "."
        new = posixpath.relpath(posixpath.join(ctx.book_prefix, inside_book.as_posix()), staged_chapter_dir)
        return _quote(_PATH_UNSAFE_RE, new) + frag

    def empty(raw: str, snippet: str) -> None:
        if not mdscan.unangle(raw):
            ctx.issues.append(f"{doc.path}: empty link destination in {snippet}: HTML links to the page itself (an "
                              "image is broken), PDF/EPUB show its text (an image its description)")

    def repl(m: re.Match) -> str:
        text = inline(m.group("text"))  # an image inside a link
        raw = mdscan.unangle(m.group("url"))
        # Reserved labels reuse the same locked declaration as the destination. They are
        # inline links, so GID collection, frozen-ledger checks and all export targets agree.
        if not m.group("bang") and ctx.lock:
            if raw == "trureturing:" and text == "{commit}":
                text = f"`{ctx.lock.commit}`"
            elif raw.startswith("lean:") and text in ("{source}", "{statement_id}"):
                res = ctx.lock.get(raw[5:])
                if res:
                    value = (f"{res.module}.lean:{res.line}" if text == "{source}"
                             else res.statement_id[:15])
                    text = f"`{value}`"
        empty(m.group("url"), m.group(0))
        new = new_url(m.group("url"))
        if new is None:
            return text
        title = m.group("title") or ""
        if new == m.group("url") and text == m.group("text") and not title.lstrip().startswith("("):
            return m.group(0)
        # "(…)" titles are written "…": Pandoc's Markdown would read them as part of the destination.
        return f"{m.group('bang')}[{text}]({new}{mdscan.quoted_title(title) if title else ''})"

    def autolink(m: re.Match) -> str:
        # ``<lean:GID>`` shows the GID; never the ``lean:`` scheme, which only mdBook would link.
        new = new_url("lean:" + m.group("gid"))
        text = mdscan.escape_markdown(m.group("gid"))
        return f"[{text}]({new})" if new else text

    def inline(text: str) -> str:
        return mdscan.sub_outside_code(mdscan.LEAN_AUTOLINK_RE, autolink, mdscan.sub_outside_code(LINK_RE, repl, text))

    if role == mdscan.DEF_DEST:
        dest = _DEST_LINE_RE.match(line.replace(mdscan._HIDDEN_LT, "<"))  # a hidden <lean:…> is a stray
        url = mdscan.unangle(dest.group("url")) if dest else ""
        if url and not _SCHEME_RE.match(url):
            ctx.issues.append(f"{doc.path}: '{url}' is the destination of the reference definition whose label "
                              "ends the line before (mdBook and Pandoc read it so and show neither line), but the "
                              "builds do not read a destination there: it is not checked or copied, and PDF/EPUB "
                              "do not resolve it; write it on the label's line, or the label's '[' as '\\[' if "
                              "both lines are text")
        return line
    refdef = mdscan.refdef(line) if role == mdscan.DEF_START else None
    if refdef:
        # An unresolved ``lean:`` destination becomes "#": never a raw ``lean:`` URL (a dead link,
        # and epubcheck rejects the scheme); PDF/EPUB show such a link as text (tr-book.lua).
        empty(refdef.group("url"), line.strip())
        new = new_url(refdef.group("url"))
        return f"{refdef.group('lead')}{'#' if new is None else new}{refdef.group('rest')}"
    like = _REFDEF_LIKE_RE.match(line) if ctx.target == "pandoc" and role == mdscan.DEF_START else None
    if like and not mdscan.REF_RE.match(line, like.end("indent")):  # ``[@id]:`` becomes a link anyway
        line = f"{like.group('indent')}\\{line[like.end('indent'):]}"
    out = inline(line)
    if out != line and role == mdscan.DEF_START and mdscan.refdef(out):
        # ``[3]: <lean:GID>，文字`` is text with an autolink; written ``[3]: [GID](url)，文字`` it would be a
        # definition (a plain destination may start with "[", not with "<"): the label stays text.
        at = _CONTAINER_RE.match(out).end()  # where the label's "[" is, as in mdscan.REFDEF_RE
        out = f"{out[:at]}\\{out[at:]}"
    return out


def label_only_as_text(lines: list[str], roles: list[str] | None = None) -> list[str]:
    """``lines`` (consecutive text lines, for Pandoc; ``roles`` their
    :func:`tbook.mdscan.definition_roles`) with the ``[`` of each ``[label]:`` that has no destination
    escaped where a definition may begin, so that Pandoc shows it as text like CommonMark (mdBook)
    does: the next line is blank, missing, or not a destination with an optional title (``# 标题``,
    words). When the next line holds the destination, both read a definition; on a line that goes on
    with a paragraph (in a formula over lines too) both read text."""
    roles = mdscan.definition_roles(lines) if roles is None else roles
    out = list(lines)
    for k, line in enumerate(lines):
        m = _LABEL_ONLY_RE.match(line) if roles[k] == mdscan.DEF_START else None
        if not m or mdscan.REF_RE.match(line, m.end("indent")):  # ``[@id]:`` becomes a link anyway
            continue
        if k + 1 < len(lines) and roles[k + 1] == mdscan.DEF_DEST:
            continue
        out[k] = f"{m.group('indent')}\\{line[m.end('indent'):]}"
    return out


def without_stray_lean(lines: list[str], start: int, doc: ChapterDoc, ctx: RenderContext,
                       cont: list[bool] | None = None) -> list[str]:
    """``lines`` (consecutive text lines from line ``start``, already rewritten; ``cont`` their
    :attr:`tbook.mdscan.Text.cont`) with every ``lean:`` destination that the line scanner cannot read
    (a link written across lines, raw HTML) neutralised by :func:`tbook.mdscan.without_stray_lean`: no
    target ever writes a ``lean:`` URL. ``./tbook check`` reports each one (:mod:`tbook.model`); the
    build warns."""
    out, strays = mdscan.without_stray_lean(lines, cont)
    for s in strays:
        ctx.issues.append(f"{doc.path}:{start + s.line}: a lean: link the tools cannot read (written across "
                          f"lines, or in raw HTML) loses its lean: destination: {lines[s.line].strip()}")
    return out


def _rewrite_refs(line: str, doc: ChapterDoc, ctx: RenderContext) -> str:
    def repl(m: re.Match) -> str:
        env = ctx.model.envs.get(m.group("id"))
        if env is None:
            ctx.issues.append(f"{doc.path}: unknown reference [@{m.group('id')}]")
            return f"**[@{m.group('id')}?]**"
        return f"[{env.ref_text(ctx.lang)}]({ctx.href(env, doc)})"

    return mdscan.sub_outside_code(mdscan.REF_RE, repl, line)


def transform_line(line: str, doc: ChapterDoc, ctx: RenderContext, role: str = mdscan.DEF_START) -> str:
    return _rewrite_refs(rewrite_links(line, doc, ctx, role), doc, ctx)


# --------------------------------------------------------------------------- environments


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def mdbook_env(env: Env, view: dict, inner: str) -> str:
    """HTML wrapper understood by theme/mdbook/tr-book.css (blank lines keep Markdown inside)."""
    classes = f"tr-env tr-{env.kind} tr-status-{view['status']}" + (" tr-unverified" if view.get("unverified") else "")
    head = [f'<span class="tr-env-label">{esc(view["ref_text"])}</span>']
    if env.kind == "proof":
        head = [f'<span class="tr-env-label">{esc(view["label"])}</span>']
    if view["title"]:
        open_p = config.s(env_lang(view), "punct.title_open")
        head.append(f'<span class="tr-env-title">{esc(open_p)}{title_html(view["title"])}'
                    f'{esc(config.s(env_lang(view), "punct.title_close"))}</span>')
    if view["badge"]:
        first = view.get("badge_url", "")
        cls = "tr-badge-" + view["status"]
        if view.get("unverified"):
            cls += " tr-badge-unverified"
        if first:
            head.append(f'<a class="tr-badge {cls}" href="{esc(first)}" title="{esc(view["badge_title"])}">{esc(view["badge"])}</a>')
        else:
            head.append(f'<span class="tr-badge {cls}" title="{esc(view["badge_title"])}">{esc(view["badge"])}</span>')
    parts = [f'<section class="{classes}" id="{esc(env.id)}" data-kind="{env.kind}">' if env.id
             else f'<section class="{classes}" data-kind="{env.kind}">',
             f'<header class="tr-env-head">{"".join(head)}</header>', "", inner.strip("\n"), ""]
    if view.get("doi_url"):
        parts.append('<footer class="tr-env-lean">' + source_html(view) + '</footer>')
    if view["lean"]:
        links = []
        for lv in view["lean"]:
            name = esc(lv["name"] or lv["gid"])
            if lv["url"]:
                links.append(f'<a class="tr-lean-decl" href="{esc(lv["url"])}" title="{esc(lv["gid"])}"><code>{name}</code></a>')
            else:  # not resolved by the lock: no link (``check`` reports it)
                links.append(f'<code class="tr-lean-decl tr-lean-unresolved" title="{esc(lv["gid"])}">{name}</code>')
        parts.append(f'<footer class="tr-env-lean">{" ".join(links)}</footer>')
    if env.kind == "proof":
        parts.append('<span class="tr-qed" aria-hidden="true">∎</span>')
    parts.append("</section>")
    return "\n".join(parts)


def env_lang(view: dict) -> str:
    return view.get("_lang", "en")


def source_view(env: Env) -> dict:
    written = env.status == "written-proof"
    return {
        "doi": env.attrs.get("doi") if written else "",
        "doi_url": evidence.doi_url(env.attrs.get("doi")) if written else "",
        "source": env.attrs.get("source") if written else "",
        "request": env.attrs.get("request") if written and evidence.request_number(env.attrs.get("request")) else "",
    }


def source_html(view: dict) -> str:
    """Written-proof provenance, kept separate from the non-link verification badge."""
    if not view.get("doi_url"):
        return ""
    out = f'DOI: <a href="{esc(view["doi_url"])}">{esc(view["doi"])}</a>'
    if view.get("source"):
        out += " · " + esc(view["source"])
    if view.get("request"):
        out += f' · <a href="{esc(view["request"])}">trureturing-requests#{evidence.request_number(view["request"])}</a>'
    return out


def source_markdown(env: Env) -> str:
    url = evidence.doi_url(env.attrs.get("doi")) if env.status == "written-proof" else ""
    if not url:
        return ""
    text = f'DOI: [{mdscan.escape_markdown(env.attrs.get("doi"))}]({url})'
    if env.attrs.get("source"):
        text += " · " + mdscan.escape_markdown(env.attrs.get("source"))
    number = evidence.request_number(env.attrs.get("request"))
    if number:
        text += f' · [trureturing-requests#{number}]({env.attrs.get("request")})'
    return text


def pandoc_env(env: Env, view: dict, inner: str) -> str:
    """Fenced div with ``tr-*`` attributes; tools/filters/tr-env.lua renders it per format."""
    attrs = mdscan.Attrs(id=env.id, classes=["tr-env", env.kind])
    kv = attrs.kv
    kv["tr-kind"] = env.kind
    kv["tr-status"] = view["status"]
    kv["tr-label"] = view["label"]
    kv["tr-number"] = view["number"]
    kv["tr-ref"] = view["ref_text"]
    if view["title"]:
        kv["tr-title"] = view["title"]
    if view["badge"]:
        kv["tr-badge"] = view["badge"]
        kv["tr-badge-title"] = view["badge_title"]
        if view.get("badge_url"):
            kv["tr-badge-url"] = view["badge_url"]
    if view.get("unverified"):
        kv["tr-unverified"] = "1"
    if view["lean"]:
        kv["tr-lean"] = " ".join(lv["gid"] for lv in view["lean"])
        kv["tr-lean-name"] = " ".join(lv["name"] or lv["gid"] for lv in view["lean"])
        kv["tr-lean-url"] = " ".join(lv["url"] or "-" for lv in view["lean"])
    fence = ":" * 6
    if source := source_markdown(env):
        inner = inner.rstrip("\n") + "\n\n" + source + "\n"
    return f"{fence} {attrs.to_pandoc()}\n{inner.strip(chr(10))}\n{fence}"


def render_media(env: Env, ctx: RenderContext, inner: str, doc: ChapterDoc) -> str:
    """Delegate to ``tbook.viz`` / ``tbook.film`` / ``tbook.slides`` ``render_embed``."""
    mod = importlib.import_module(f"tbook.{env.kind}")
    return mod.render_embed(env, ctx, inner, doc)


def chapter_markdown(doc: ChapterDoc, ctx: RenderContext) -> str:
    """The chapter's Markdown, transformed for ``ctx.target``."""
    envs_by_div = {id(e.div): e for e in doc.envs + doc.media if e.div is not None}

    def text_fn(node: mdscan.Text) -> str:
        roles = mdscan.text_roles(node)
        if ctx.target == "pandoc":
            node = mdscan.Text(label_only_as_text(node.lines, roles), node.start, node.carry, node.cont)
        lines = mdscan.map_text(node, lambda line, role: transform_line(line, doc, ctx, role), roles)
        return "\n".join(without_stray_lean(lines, node.start, doc, ctx, node.cont))

    def div_fn(div: mdscan.Div, inner: str) -> str:
        out = div_markup(div, inner)
        # For mdBook a div is an HTML block, which goes on to the next blank line: one follows it,
        # so text right after the closing ":::" stays Markdown (Pandoc reads it so too).
        return out + "\n" if ctx.target == "mdbook" else out

    def div_markup(div: mdscan.Div, inner: str) -> str:
        env = envs_by_div.get(id(div))
        if env is None:
            if ctx.target == "mdbook":
                cls = " ".join(div.classes)
                ident = f' id="{esc(div.attrs.id)}"' if div.attrs.id else ""
                return f'<div class="{esc(cls)}"{ident}>\n\n{inner}\n\n</div>'
            return f"{div.fence} {div.attrs.to_pandoc()}\n{inner}\n{div.fence}"
        if env.kind in MEDIA:
            return render_media(env, ctx, inner, doc)
        view = env_view(env, ctx)
        view["_lang"] = ctx.lang
        if ctx.target == "mdbook":
            return mdbook_env(env, view, inner)
        return pandoc_env(env, view, inner)

    return mdscan.render_blocks(doc.blocks, div_fn=div_fn, text_fn=text_fn)
