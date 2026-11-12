"""``./tbook check``: structure, bilingual parity and the Lean verification rule.

The rule this enforces: every theorem / lemma / proposition / corollary cites at least
one Lean declaration (``lean="<GID>"``) that is recorded in ``trureturing.lock.json`` and
that, at the pinned commit, is listed in trureturing's ``Golden/Frozen/state`` with kind
``theorem`` — i.e. kernel-verified and frozen. The pinned commit must be on the site.toml
branch, where trureturing's CI enforces the freeze rule. Conjectures and open problems must
not cite Lean. Editions of a book (zh, en, …) must agree item by item, and their SUMMARY.md
must give every chapter the same number.
"""

from __future__ import annotations

import importlib
import re
import subprocess
from pathlib import Path

from . import config, lean, mdscan, paths, render
from .model import (DEFINITION, FORMAL, MEDIA, NUMBERED, OPEN, PROOF, EditionModel, Issue, load_book_models, kind_of,
                    media_cited_gids)
from .summary import Chapter, Summary, chapter_prefix


def _err(issues: list[Issue], path: Path | None, line: int, msg: str) -> None:
    issues.append(Issue("error", path, line, msg))


def _warn(issues: list[Issue], path: Path | None, line: int, msg: str) -> None:
    issues.append(Issue("warning", path, line, msg))


def _check_ref(model: EditionModel, issues: list[Issue], path: Path, line: int, ref: str, where: str = "") -> None:
    """A ``[@ref]`` in prose or (``where``) in an environment title must name a numbered environment."""
    if ref not in model.envs:
        _err(issues, path, line, f"[@{ref}]{where} refers to no environment in this edition")
    elif model.envs[ref].kind in MEDIA:
        _err(issues, path, line,
             f"[@{ref}]{where} points at a {model.envs[ref].kind} embed; references can only target "
             "numbered environments (theorem, definition, example …)")


def check_env_policy(model: EditionModel, issues: list[Issue]) -> None:
    for ch in model.chapters:
        for env in ch.envs + ch.media:
            where = (ch.path, env.line)
            if env.id and not mdscan.ID_RE.match(env.id):
                _err(issues, *where, f"#{env.id}: ids use letters, digits, '-', '_' or ':' and start with a letter")
            if env.kind in FORMAL + DEFINITION + OPEN and not env.id:
                _err(issues, *where, f"{env.kind} needs an id, e.g. {{.{env.kind} #{env.kind[:3]}-name}}")
            if env.kind in FORMAL and not env.lean:
                _err(issues, *where,
                     f"{env.kind} #{env.id or '?'} cites no Lean declaration. Every {env.kind} must be "
                     "kernel-verified in trureturing: add lean=\"<module path>.<name>\". If it is not proved yet, "
                     "write it as a conjecture or problem instead.")
            if env.kind in OPEN and env.lean:
                _err(issues, *where, f"{env.kind} #{env.id}: open items must not cite Lean; if it is proved, make it a theorem")
            for gid in env.lean:
                try:
                    lean.parse_gid(gid)
                except lean.LeanError as exc:
                    _err(issues, *where, str(exc))
            if env.kind in MEDIA:
                if not env.attrs.get("src"):
                    _err(issues, *where, f"{env.kind} embed needs src=\"…\"")
                    continue
                try:
                    mod = importlib.import_module(f"tbook.{env.kind}")
                    problem = mod.check_ref(model.edition.book, env.attrs.get("src"))
                    if not problem and env.kind == "viz" and "preset" in env.attrs.kv:
                        # a cited experiment card: it must exist, and so must its still for this edition
                        problem = mod.check_preset(model.edition.book, env.attrs.get("src"), env.attrs.get("preset"), model.lang)
                except Exception as exc:  # noqa: BLE001 - surface any media checker failure
                    problem = f"cannot check {env.kind} src: {exc}"
                if problem:
                    _err(issues, *where, problem)
            if env.title and "\n" in env.title:
                _err(issues, *where, "title must be one line")
            if env.title and mdscan.strip_lean_links(env.title) != env.title:
                _err(issues, *where, "a title cannot link to Lean (every target shows only the link text): cite the "
                                     "declaration with lean=\"…\" or link to it in the text")
            for m in mdscan.find_outside_code(mdscan.REF_RE, env.title or ""):
                _check_ref(model, issues, ch.path, env.line, m.group("id"),
                           f" in the title of {env.kind} #{env.id}" if env.id else f" in the title of a {env.kind}")
        for line, ref in ch.refs:
            _check_ref(model, issues, ch.path, line, ref)
        for line, gid in ch.lean_links:
            try:
                lean.parse_gid(gid)
            except lean.LeanError as exc:
                _err(issues, ch.path, line, str(exc))


def check_orphans(model: EditionModel, issues: list[Issue]) -> None:
    ed = model.edition
    if not ed.dir.exists() or model.summary is None:
        return
    listed = {(ed.dir / f).resolve() for f in model.summary.files()}
    for md in sorted(ed.dir.rglob("*.md")):
        if md.name == "SUMMARY.md" or md.resolve() in listed:
            continue
        _warn(issues, md, 0, "not listed in SUMMARY.md (it will not be published)")


def check_links(model: EditionModel, site: config.Site, issues: list[Issue]) -> None:
    """Local files that chapters link to or embed must exist, links must stay in the book directory,
    and destinations should not be empty (HTML links to the page itself, PDF/EPUB show the text).

    Runs the builds' own link rewriting (:func:`tbook.render.rewrite_links`), so it reads links and
    images the way the builds do: inline, ``<…>`` and percent-encoded destinations, reference
    definitions (only where one may begin, :func:`tbook.mdscan.definition_roles`), ``../assets/…``,
    and nothing in code or HTML comments (which no target shows). Otherwise a missing file is
    reported only when an edition is built. A definition whose destination is on the line after its
    label is reported: the builds do not read it there. Warnings, like the build's: a broken link
    does not make a result unverified.
    """
    ed = model.edition
    for doc in model.chapters:
        ctx = render.RenderContext(site, ed.book, ed, model, None, target="pandoc")
        prefix = f"{doc.path}: "
        for lineno, line, role in mdscan.iter_text(doc.blocks):
            ctx.book_files.clear()
            ctx.edition_files.clear()
            ctx.issues.clear()
            render.rewrite_links(line, doc, ctx, role)
            # files outside the edition are copied into the build one by one, so they must be files
            missing = sorted(p for p in ctx.book_files if not p.is_file())
            missing += sorted(p for p in ctx.edition_files if not p.exists())
            for p in missing:
                what = "is not a file" if p.exists() else "does not exist"
                _warn(issues, doc.path, lineno, f"links to {paths.rel(p)}, which {what}")
            for msg in ctx.issues:  # "link leaves the book directory: …", "empty link destination in …"
                _warn(issues, doc.path, lineno, msg[len(prefix):] if msg.startswith(prefix) else msg)


_IMAGE_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif")


def check_captions(model: EditionModel, issues: list[Issue]) -> None:
    """A figure says what it shows: ``::: {.figure}`` blocks need a caption, and neither they nor an
    image (``![caption](file)``, whose description is its caption in the PDF and EPUB) may carry
    only a number ("图 13"), which every reader sees as an unfinished page."""
    from . import figure

    for doc in model.chapters:
        for env in doc.media:
            if env.kind != "figure" or env.div is None:
                continue
            inner = mdscan.render_blocks(env.div.children, div_fn=lambda d, i: i, text_fn=lambda t: "\n".join(t.lines))
            problem = figure.caption_problem(inner)
            if problem:
                _err(issues, doc.path, env.line, f"figure {env.attrs.get('src') or '?'} {problem}")
        for lineno, text, url in _images(doc):
            problem = figure.caption_problem(text)
            if problem:
                _err(issues, doc.path, lineno, f"image {url} {problem}")


def _images(doc) -> list[tuple[int, str, str]]:
    """(line, description, destination) of every image a chapter shows (``![…](file)``, not in code)."""
    out = []
    for lineno, line, _role in mdscan.iter_text(doc.blocks):
        for m in mdscan.find_outside_code(render.LINK_RE, line):
            url = mdscan.unangle(m.group("url")).partition("#")[0].partition("?")[0]
            if m.group("bang") and url.lower().endswith(_IMAGE_SUFFIXES):
                out.append((lineno, m.group("text"), url))
    return out


def check_image_parity(book: config.Book, models: dict[str, EditionModel], issues: list[Issue]) -> None:
    """Editions show the same pictures: figure blocks are compared one by one with the other media
    (:func:`check_parity`); plain images may be language-specific files, so only their number per
    chapter is compared (a warning)."""
    if len(models) < 2:
        return
    primary = models[book.languages[0]]
    counts = {doc.chapter.path: len(_images(doc)) for doc in primary.chapters}
    for lang in book.languages[1:]:
        for doc in models[lang].chapters:
            n = len(_images(doc))
            m = counts.get(doc.chapter.path)
            if m is not None and n != m:
                _warn(issues, doc.path, 0, f"the {lang} edition shows {n} image(s) in this chapter, the "
                                           f"{book.languages[0]} edition {m}: editions show the same pictures at the same places")


# A colour written into an SVG: a fill / stroke / stop-color / color attribute or style declaration whose value is
# a hex, rgb()/hsl() or named colour (not none, currentColor, inherit, transparent or a url(#…) paint server).
_SVG_COLOR_RE = re.compile(r"""(?:\b(?:fill|stroke|stop-color|flood-color|lighting-color|color)\s*(?:=\s*["']|:)\s*)"""
                           r"""(?!none\b|freeze\b|remove\b|currentcolor\b|inherit\b|transparent\b|url\(|var\()(?:#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|[a-z]{3,}\b)""",
                           re.I)
_SVG_ROLE_RE = re.compile(r"""class\s*=\s*["'][^"']*\bt[sf]-[a-z]""")


def svg_is_hand_drawn(svg: str) -> bool:
    """True when ``svg`` writes its colours in: it neither paints by role classes (``ts-…``/``tf-…``,
    as the figure scripts do) nor follows the reader's colour scheme (``prefers-color-scheme``)."""
    return bool(_SVG_COLOR_RE.search(svg)) and not _SVG_ROLE_RE.search(svg) and "prefers-color-scheme" not in svg


def _image_file(doc, url: str) -> Path | None:
    """The local file an image destination of chapter ``doc`` names, or None (remote, missing)."""
    if not url or "://" in url or url.startswith(("/", "data:")):
        return None
    from urllib.parse import unquote

    p = (doc.path.parent / unquote(url)).resolve()
    return p if p.is_file() else None


def check_drawn_images(book: config.Book, models: dict[str, EditionModel], issues: list[Issue]) -> None:
    """Images that should have been figures (warnings). An SVG in ``assets/`` shown with image syntax
    that writes its colours in keeps them in the light theme, in print and in the EPUB: draw it with a
    figure script (``figures/<name>.py``, cited with ``::: {.figure}``). Image syntax is for pictures
    no script can draw (photographs, scans); bitmaps are not reported. An SVG with text that two
    editions show as the same file gives every reader the labels of one language."""
    assets = (book.dir / "assets").resolve()
    users: dict[Path, list[tuple[str, Path, int]]] = {}
    for lang, model in models.items():
        for doc in model.chapters:
            for lineno, _text, url in _images(doc):
                p = _image_file(doc, url)
                if p is not None and p.suffix.lower() == ".svg":
                    users.setdefault(p, []).append((lang, doc.path, lineno))
    for p, uses in users.items():
        try:
            svg = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if p.is_relative_to(assets) and svg_is_hand_drawn(svg):
            for _lang, path, lineno in uses:
                _warn(issues, path, lineno,
                      f"{paths.rel(p)} is a hand-drawn SVG with its colours written in (no role classes, no "
                      "prefers-color-scheme): it keeps those colours in both themes, in print and in the EPUB. Draw it "
                      "with a figure script figures/<name>.py and cite it with ::: {.figure src=\"<name>\"} "
                      "(image syntax is for pictures no script can draw, such as photographs)")
        langs = list(dict.fromkeys(lang for lang, _path, _line in uses))
        if len(langs) > 1 and re.search(r"<text\b", svg):
            later = [u for u in uses if u[0] != langs[0]]
            _lang, path, lineno = later[0]
            _warn(issues, path, lineno,
                  f"{paths.rel(p)} has text and is shown by the {', '.join(langs)} editions alike: give every "
                  "language its own labels (a figure script draws one version per language; or one image file "
                  "per edition)")


_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
def _media_label(node: "mdscan.Div") -> str:
    """How a warning names one media block: its kind, ``src`` and (for a card) ``preset``."""
    label = f'{kind_of(node)} "{node.attrs.get("src") or "?"}"'
    if node.attrs.get("preset"):
        label += f' preset "{node.attrs.get("preset")}"'
    elif kind_of(node) == "viz":
        label += " (the full lab)"
    return label


def check_media_runs(model: EditionModel, issues: list[Issue]) -> None:
    """Two media blocks (figure, viz, film, slides) with nothing but blank lines or HTML comments between
    them (a warning, on the second block of every such pair): a reader meets a stack of pictures and cannot
    tell which sentence each one belongs to. Cite each next to the sentence it shows, with prose between."""
    for doc in model.chapters:
        for nodes in [doc.blocks] + [n.children for n in mdscan.walk(doc.blocks) if isinstance(n, mdscan.Div)]:
            prev: "mdscan.Div | None" = None
            for node in nodes:
                if isinstance(node, mdscan.Div) and kind_of(node) in MEDIA:
                    if prev is not None:
                        msg = (f"{_media_label(prev)} (line {prev.start}) and {_media_label(node)} (line {node.start}) "
                               "sit next to each other with no text between them: cite each next to the sentence "
                               "it shows, with prose between the two")
                        if (kind_of(prev) == kind_of(node) == "viz" and prev.attrs.get("preset")
                                and not node.attrs.get("preset") and prev.attrs.get("src") == node.attrs.get("src")):
                            msg += ("; the full lab right after the last card of the same page: move the lab after "
                                    "the last paragraph at the end of the chapter, or put a sentence between the two "
                                    "that says what the lab adds")
                        _warn(issues, doc.path, node.start, msg)
                    prev = node
                elif isinstance(node, mdscan.Comment) or (isinstance(node, mdscan.Text) and not _COMMENT_RE.sub(
                        "", "\n".join(node.lines)).strip()):  # blank lines and HTML comments show nothing
                    continue
                else:
                    prev = None


def check_unused_figures(book: config.Book, models: dict[str, EditionModel], issues: list[Issue]) -> None:
    """Figures that no chapter of any edition cites: drawn and committed, but shown nowhere (a warning)."""
    from . import figure

    cited = {env.attrs.get("src") for model in models.values() for doc in model.chapters
             for env in doc.media if env.kind == "figure"}
    for name in figure.names(book):
        if name not in cited:
            _warn(issues, figure.script_path(book, name), 0,
                  f'no chapter cites this figure; cite it with ::: {{.figure src="{name}"}} or delete it and its SVG files')


def check_unused_assets(book: config.Book, models: dict[str, EditionModel], site: config.Site, issues: list[Issue]) -> None:
    """Files in ``assets/`` that no chapter of any edition and no slide deck or visualization names:
    left-overs that the builds never publish (a warning; delete them or cite them)."""
    assets = book.dir / "assets"
    if not assets.is_dir():
        return
    used: set[Path] = set()
    for model in models.values():
        for doc in model.chapters:
            ctx = render.RenderContext(site, model.edition.book, model.edition, model, None, target="pandoc")
            for _lineno, line, role in mdscan.iter_text(doc.blocks):
                render.rewrite_links(line, doc, ctx, role)
            used.update(p.resolve() for p in ctx.book_files)
    # decks, films and pages name assets in their own sources: a file whose name appears there counts as used
    elsewhere = ""
    for sub in ("slides", "viz", "films"):
        d = book.dir / sub
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".md", ".html", ".js", ".json", ".vue", ".css") and "node_modules" not in p.parts:
                    try:
                        elsewhere += p.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        pass
    for p in sorted(assets.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.resolve() in used or p.name in elsewhere:
            continue
        _warn(issues, p, 0, "no chapter, deck, film or visualization of this book uses this file")


def check_footnotes(model: EditionModel, issues: list[Issue]) -> None:
    """Footnotes that the HTML edition and the PDF/EPUB would show differently (:func:`tbook.pandoc.footnote_problems`)."""
    from . import pandoc

    for doc in model.chapters:
        for line, msg in pandoc.footnote_problems(doc.text):
            _warn(issues, doc.path, line, msg)


def _env_signature(model: EditionModel) -> list[tuple[str, list[tuple[str, str, tuple[str, ...]]]]]:
    sig = []
    for ch in model.chapters:
        items = [(e.kind, e.id, tuple(e.lean)) for e in ch.envs if e.kind in NUMBERED + PROOF]
        # a cited card (viz preset=…) is part of the citation: every edition cites the same card at the same place
        items += [(e.kind, e.attrs.get("src"), (e.attrs.get("preset"),) if e.attrs.get("preset") else ()) for e in ch.media]
        sig.append((ch.chapter.path or "", items))
    return sig


def _placement(summary: Summary, ch: Chapter) -> tuple[str, tuple[int, ...], int, str]:
    """What decides a chapter's theorem numbers: section, mdBook number, nesting depth and the
    numbering prefix (``2``, ``0`` for prefix chapters, ``A`` for the first suffix chapter)."""
    return ch.section, ch.number, ch.depth, chapter_prefix(summary, ch)


def _describe(summary: Summary, ch: Chapter) -> str:
    section, number, depth, prefix = _placement(summary, ch)
    nested = f", nested at depth {depth}" if depth else ""
    if section == "numbered":
        return f"numbered chapter {'.'.join(map(str, number))}{nested} (theorems {prefix}.n)"
    if section == "prefix":
        return "a prefix chapter before the numbered list (theorems 0.n)"
    return f"a suffix chapter after the numbered list (theorems {prefix}.n)"


def check_parity(book: config.Book, models: dict[str, EditionModel], issues: list[Issue]) -> None:
    if len(models) < 2:
        return
    primary = models[book.languages[0]]
    if primary.summary is None:
        return
    p_files = primary.summary.files()
    p_sig = _env_signature(primary)
    p_place = {c.path: c for c in primary.summary.chapters if c.path}
    for lang in book.languages[1:]:
        other = models[lang]
        if other.summary is None:
            continue
        o_files = other.summary.files()
        if p_files != o_files:
            missing = [f for f in p_files if f not in o_files]
            extra = [f for f in o_files if f not in p_files]
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("extra " + ", ".join(extra))
            if not detail:
                detail.append("same files in a different order")
            _err(issues, other.summary.path, 0,
                 f"{lang} edition chapters differ from the {book.languages[0]} edition ({'; '.join(detail)}). "
                 "Editions use the same file names in the same order.")
            continue
        for ch in other.summary.chapters:  # same files, but the same numbers? (sections, nesting, drafts)
            pch = p_place.get(ch.path) if ch.path else None
            if pch and _placement(other.summary, ch) != _placement(primary.summary, pch):
                _err(issues, other.summary.path, ch.line,
                     f"{ch.path} is {_describe(other.summary, ch)} in the {lang} edition but "
                     f"{_describe(primary.summary, pch)} in the {book.languages[0]} edition, so its theorem "
                     "numbers would differ. Give every edition the same SUMMARY.md structure (prefix / "
                     "numbered / suffix chapters, nesting, draft entries).")
                break
        o_sig = dict(_env_signature(other))
        for path, items in p_sig:
            o_items = o_sig.get(path, [])
            if items == o_items:
                continue
            ch_path = other.edition.dir / path
            for k in range(max(len(items), len(o_items))):
                a = items[k] if k < len(items) else None
                b = o_items[k] if k < len(o_items) else None
                if a != b:
                    def fmt(x):
                        if x is None:
                            return "nothing"
                        return f"{x[0]} #{x[1]}" + (f" lean={' '.join(x[2])}" if x[2] else "")
                    _err(issues, ch_path, 0,
                         f"item {k + 1} differs between editions: {book.languages[0]} has {fmt(a)}, {lang} has {fmt(b)}")
                    break


def check_lean(models_by_book: dict[str, dict[str, EditionModel]], lock: lean.Lock | None,
               site: config.Site, issues: list[Issue], *, offline: bool,
               extra_cited: list[tuple[Path, int, str]] | None = None,
               cited_elsewhere: set[str] | None = frozenset()) -> None:
    """Re-verify every cited GID against the lock and the frozen state at the pinned commit, and
    the pinned commit against the site.toml branch, which must be a branch name and the lock's branch.
    (In a pull request's GitHub Actions run the Ledger reads nothing from ``.cache/trureturing``.)

    ``extra_cited`` holds citations outside the chapters (visualizations, films, slides); they are
    verified the same way but do not impose the theorem-kind rule here: tbook.viz, tbook.film and
    tbook.slides each require kind ``theorem`` wherever they show a green LEAN ✓ chip (the viz
    registry's ``lean``, a page's ``data-lean-gid``, film.json's ``lean``, ``<LeanBadge>`` /
    ``<TheoremCard>`` without ``kind="definition"``).
    ``cited_elsewhere`` holds GIDs cited by books outside ``models_by_book`` (``check --book``), so
    their lock entries do not count as unused; ``None`` (unknown) skips the unused-entry warning.
    """
    cited: dict[str, list[tuple[Path, int, bool]]] = {}
    for path, line, gid in extra_cited or []:
        try:
            lean.parse_gid(gid)
        except lean.LeanError:
            continue  # reported by the media module's own check
        cited.setdefault(gid, []).append((path, line, False))
    for models in models_by_book.values():
        for model in models.values():
            for path, line, gid, env in model.cited_gids():
                try:
                    lean.parse_gid(gid)
                except lean.LeanError:
                    continue  # reported by the policy check
                cited.setdefault(gid, []).append((path, line, bool(env and env.kind in FORMAL)))
    if not cited:
        return
    if lock is None:
        _err(issues, paths.LOCK_FILE, 0, "trureturing.lock.json is missing; run ./tbook pin")
        return
    if lock.repo != site.trureturing_repo:
        _err(issues, paths.LOCK_FILE, 0,
             f"lock pins {lock.repo} but site.toml uses {site.trureturing_repo}; run ./tbook pin")
    branch = site.trureturing_branch
    if lock.branch and lock.branch != branch:  # the lock (and the site manifest) would name an unchecked branch
        _err(issues, paths.LOCK_FILE, 0,
             f"lock was pinned against branch {lock.branch!r} but site.toml uses {branch!r}; run ./tbook pin "
             f"(or ./tbook pin --refresh to keep commit {lock.commit[:12]} if it is on {branch!r})")
    ledger = lean.Ledger(lock.repo, offline=offline)
    problem = lean.branch_problem(branch, lock.commit)
    anc = lean.Ancestry(None, "") if problem else ledger.branch_contains(lock.commit, branch)
    where = f"branch {branch!r} of {lock.repo}"
    if problem:
        _err(issues, paths.SITE_TOML, 0,
             f"[trureturing] branch {branch!r} {problem}: trureturing enforces its freeze rule on a branch "
             "(default 'dev'), and only a branch can show that the pinned commit was merged")
    elif anc.no_branch:
        _err(issues, paths.SITE_TOML, 0,
             f"[trureturing] branch {branch!r} does not exist in {lock.repo} ({anc.detail}); set it to an existing "
             f"branch (default 'dev'), then run ./tbook pin --refresh to keep commit {lock.commit[:12]} if it is on "
             "that branch, or ./tbook pin")
    elif anc.on_branch is False:
        _err(issues, paths.LOCK_FILE, 0,
             f"pinned commit {lock.commit[:12]} is not on {where} ({anc.detail}); trureturing enforces the freeze "
             f"rule only on {branch}, so its frozen state at other commits proves nothing. Pin a commit on "
             f"{branch}: ./tbook pin")
    elif anc.on_branch is None:
        (_err if lean.ancestry_required(offline) else _warn)(
            issues, paths.LOCK_FILE, 0,
            f"could not verify that pinned commit {lock.commit[:12]} is on {where}: {anc.detail}")
    for gid, uses in sorted(cited.items()):
        path, line, _ = uses[0]
        res = lock.get(gid)
        if res is None:
            _err(issues, path, line, f"{gid} is not in trureturing.lock.json; run ./tbook pin --refresh")
            continue
        if res.kind not in lean.FORMAL_KINDS:
            for fpath, fline, formal in uses:  # at each theorem-like environment, not at a media citation
                if formal:
                    _err(issues, fpath, fline,
                         f"{gid} is a Lean {res.kind}, but theorem-like environments must cite theorems")
        try:
            live = lean.resolve(ledger, lock.commit, gid)
        except lean.LeanError as exc:
            if offline and "network disabled" in str(exc):
                _warn(issues, path, line, f"{gid}: not re-verified offline ({exc})")
            else:
                _err(issues, path, line, str(exc))
            continue
        for fld in ("name", "kind", "module", "statement_id"):
            if getattr(live, fld) != getattr(res, fld):
                _err(issues, paths.LOCK_FILE, 0,
                     f"{gid}: lock says {fld}={getattr(res, fld)!r} but trureturing@{lock.commit[:12]} says "
                     f"{getattr(live, fld)!r}; run ./tbook pin --refresh")
                break
    if cited_elsewhere is None:
        return
    for gid in sorted(set(lock.declarations) - set(cited) - set(cited_elsewhere)):
        _warn(issues, paths.LOCK_FILE, 0, f"{gid} is locked but no longer cited; ./tbook pin --refresh prunes it")


def _cited_by_other_books(books: list[config.Book]) -> set[str] | None:
    """GIDs cited by the repository's books that ``books`` leaves out (None if they cannot be read)."""
    from .pin import cited_gids

    try:
        slugs = {b.slug for b in books}
        others = [b for b in config.load_books() if b.slug not in slugs]
        return set(cited_gids(others)) if others else set()
    except Exception:  # noqa: BLE001 - another book's problem is reported when that book is checked
        return None


def check_cache(issues: list[Issue]) -> None:
    """``.cache/`` holds downloaded trureturing state and verification results; committed files there
    would let a pull request feed ``./tbook check`` fabricated frozen state.

    git is asked about the literal ``.cache``: a resolved path would follow a committed ``.cache`` symlink
    to its target (say an ignored ``node_modules/<package>``) and find nothing committed there."""
    name = paths.CACHE.relative_to(paths.ROOT).as_posix()
    try:
        r = subprocess.run(["git", "-C", str(paths.ROOT), "ls-files", "--", name], capture_output=True, text=True)
    except OSError:  # no git: not a checkout of the repository
        return
    tracked = r.stdout.splitlines() if r.returncode == 0 else []
    if tracked:
        what = (f"{name} itself is committed (a symlink or a file)" if name in tracked
                else f"{len(tracked)} file(s) under {name}/ are committed (e.g. {tracked[0]})")
        # named, not resolved: a symlink's target would hide what is committed
        _err(issues, None if paths.CACHE.is_symlink() else paths.CACHE, 0,
             f"{what}; it is a local cache and is never trusted from the repository: git rm -r --cached {name}")


def check_theme(issues: list[Issue]) -> None:
    from . import theme

    for path in theme.stale_outputs():
        _err(issues, path, 0, "generated from theme/tokens.json but out of date; run ./tbook theme")


def run(books: list[config.Book], *, offline: bool = False) -> list[Issue]:
    site = config.load_site()
    issues: list[Issue] = []
    for lang in site.languages:
        if not config.has_i18n(lang):
            _err(issues, paths.SITE_TOML, 0, f"no i18n table for {lang!r}: add i18n/{lang}.toml (copy theme/i18n/en.toml)")
    i18n_langs = list(dict.fromkeys([*site.languages, *(lang for book in books for lang in book.languages)]))
    for path, msg in config.i18n_problems(i18n_langs):
        _err(issues, path, 0, msg)
    try:
        lock = lean.Lock.load()
    except (lean.LeanError, ValueError, KeyError) as exc:
        _err(issues, paths.LOCK_FILE, 0, f"unreadable lock: {exc}")
        lock = None
    models_by_book: dict[str, dict[str, EditionModel]] = {}
    for book in books:
        for lang in book.languages:
            if not config.has_i18n(lang):
                _err(issues, book.dir / "book.toml", 0,
                     f"edition {lang!r} has no i18n table: add i18n/{lang}.toml (copy theme/i18n/en.toml)")
            if lang not in site.languages:
                _warn(issues, book.dir / "book.toml", 0, f"edition {lang!r} is not in site.toml languages")
        models = load_book_models(book)
        models_by_book[book.slug] = models
        for model in models.values():
            issues.extend(model.issues)
            check_env_policy(model, issues)
            check_orphans(model, issues)
            check_links(model, site, issues)
            check_footnotes(model, issues)
            check_captions(model, issues)
            check_media_runs(model, issues)
            if model.summary is not None and not model.chapters:
                _warn(issues, model.edition.summary, 0, "edition has no chapters yet")
        check_parity(book, models, issues)
        check_image_parity(book, models, issues)
        check_drawn_images(book, models, issues)
        check_unused_figures(book, models, issues)
        check_unused_assets(book, models, site, issues)
        for kind in MEDIA:
            try:
                mod = importlib.import_module(f"tbook.{kind}")
                issues.extend(mod.check(book))
            except NotImplementedError:
                pass
    extra = [c for book in books for c in media_cited_gids(book)]
    check_cache(issues)
    check_lean(models_by_book, lock, site, issues, offline=offline, extra_cited=extra,
               cited_elsewhere=_cited_by_other_books(books))
    check_theme(issues)
    return issues
