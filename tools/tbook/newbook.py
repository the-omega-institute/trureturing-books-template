"""``./tbook new-book`` and ``./tbook new-chapter``: scaffold books and chapters."""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path

from . import config, paths
from .summary import Chapter, Summary, SummaryError, numbered_depth_message, parse_summary

TEMPLATE = paths.TEMPLATES / "book"


def _toml_str(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _table(values: dict[str, str]) -> str:
    return "\n".join(f"{lang} = {_toml_str(text)}" for lang, text in values.items())


def new_book(slug: str, titles: dict[str, str], *, langs: list[str] | None = None, author: str = "",
             code: str = "", subtitles: dict[str, str] | None = None) -> Path:
    if not config.SLUG_RE.match(slug):
        raise config.ConfigError(f"slug {slug!r} must be kebab-case (a-z, 0-9, -)")
    site = config.load_site()
    langs = [lang.strip() for lang in langs] if langs else list(site.languages)
    target = paths.BOOKS / slug
    if target.exists():
        raise config.ConfigError(f"{paths.rel(target)} already exists")
    # validate everything before writing: a failure must not leave a half-made book behind
    for lang in langs:
        if not config.LANG_RE.match(lang):
            raise config.ConfigError(f"invalid edition language {lang!r}: use a language code such as zh, en, ja "
                                     "or pt-BR (lowercase, '-' before a region or script)")
    if config.duplicates(langs):
        raise config.ConfigError(f"--langs lists {config.duplicates(langs)[0]!r} twice")
    for lang in langs:
        if lang not in titles:
            raise config.ConfigError(f"missing a title for the {lang!r} edition (use --title {lang}=…)")
    target.mkdir(parents=True)
    try:
        _write_book(target, slug, titles, langs, author=author, code=code, subtitles=subtitles)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)  # it did not exist before
        raise
    return target


def _write_book(target: Path, slug: str, titles: dict[str, str], langs: list[str], *, author: str, code: str,
                subtitles: dict[str, str] | None) -> None:
    (target / "assets").mkdir()
    (target / "assets" / ".gitkeep").write_text("")
    for lang in langs:
        src = TEMPLATE / (lang if (TEMPLATE / lang).exists() else "en")
        shutil.copytree(src, target / lang)
        if lang not in ("zh", "en"):
            readme = target / lang / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace(
                "Every theorem", f"<!-- TODO: translate to {lang} -->\nEvery theorem"), encoding="utf-8")
    text = (TEMPLATE / "book.toml").read_text(encoding="utf-8")
    code = code or slug.upper().replace("-", "//", 1)
    text = (text.replace("{{AUTHOR}}", author or "The Omega Institute")
            .replace("{{EDITIONS}}", ", ".join(_toml_str(lang) for lang in langs))
            .replace("{{CODE}}", code)
            .replace("{{TITLES}}", _table({lang: titles[lang] for lang in langs}))
            .replace("{{SUBTITLES}}", _table({lang: (subtitles or {}).get(lang, "") for lang in langs}))
            .replace("{{DESCRIPTIONS}}", _table({lang: "" for lang in langs}))
            .replace("{{DATE}}", datetime.datetime.now(datetime.timezone.utc).date().isoformat()))
    (target / "book.toml").write_text(text, encoding="utf-8")


CHAPTER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _chapter_path(name: str) -> str:
    return name if name.endswith(".md") else name + ".md"


def _last_descendant(chapter: Chapter) -> Chapter:
    while chapter.children:
        chapter = chapter.children[-1]
    return chapter


def _summary_indent(lines: list[str], chapter: Chapter) -> str:
    line = lines[chapter.line - 1]
    return line[:len(line) - len(line.lstrip(" \t"))]


def _default_top_level_position(summary: Summary, lines: list[str]) -> tuple[int, str]:
    # Keep the trailing unnumbered list chapters together with any mdBook suffix.
    suffix = trailing = last_list_entry = None
    for chapter in summary.top_level():
        if chapter.section == "suffix":
            suffix = chapter
            break
        if chapter.section == "numbered":
            last_list_entry = chapter
            trailing = None if chapter.number else trailing or chapter
    anchor = trailing or suffix
    reference = trailing or last_list_entry
    return (anchor.line - 1 if anchor else len(lines),
            _summary_indent(lines, reference) if reference else "")


def _chapter_position(summary: Summary, lines: list[str], parent: str | None,
                      target: str | None, *, before: bool) -> tuple[int, str, int]:
    where = paths.rel(summary.path)
    if parent is not None:
        matches = [ch for ch in summary.chapters if ch.path == parent]
        if len(matches) != 1 or matches[0].section != "numbered":
            raise config.ConfigError(f"{where}: parent {parent!r} must name one numbered chapter")
        ancestor = matches[0]
        parent_file = summary.path.parent / parent
        if not parent_file.is_file():
            raise config.ConfigError(f"{paths.rel(parent_file)} not found")
        siblings = ancestor.children
        depth = ancestor.depth + 1
        if target is None:
            indent = (_summary_indent(lines, siblings[-1]) if siblings else _summary_indent(lines, ancestor) + "  ")
            return _last_descendant(ancestor).line, indent, depth
    else:
        if target is None:
            insert, indent = _default_top_level_position(summary, lines)
            return insert, indent, 0
        siblings = [ch for ch in summary.top_level() if ch.section == "numbered"]
        depth = 0

    matches = [ch for ch in siblings if ch.path == target]
    if len(matches) != 1:
        option = "--before" if before else "--after"
        scope = f"a direct child of {parent!r}" if parent is not None else "a top-level list chapter"
        raise config.ConfigError(f"{where}: {option} target {target!r} must name one chapter that is {scope}")
    anchor = matches[0]
    insert = anchor.line - 1 if before else _last_descendant(anchor).line
    return insert, _summary_indent(lines, anchor), depth


def new_chapter(slug: str, name: str, titles: dict[str, str], *, parent: str | None = None,
                before: str | None = None, after: str | None = None) -> list[Path]:
    """Insert ``- [title](name.md)`` in every edition's SUMMARY and create the files.

    All or nothing: every edition is validated (title, SUMMARY.md present and parseable, chapter
    not there yet) before any file is written, so a failure leaves the book as it was.
    """
    if not CHAPTER_RE.fullmatch(name):
        raise config.ConfigError(f"chapter file name {name!r} must be kebab-case")
    if before is not None and after is not None:
        raise config.ConfigError("--before and --after are mutually exclusive")
    book = config.named_book(slug)
    parent_path = _chapter_path(parent) if parent is not None else None
    target = before if before is not None else after
    target_path = _chapter_path(target) if target is not None else None
    plan = []
    primary_shape = None
    for ed in book.editions:
        title = titles.get(ed.lang) or titles.get("*")
        if not title:
            raise config.ConfigError(f"missing a title for the {ed.lang!r} edition (use --title {ed.lang}=…)")
        if "\n" in title or "\r" in title:
            raise config.ConfigError("chapter title must fit on one SUMMARY link line")
        if not ed.summary.is_file():
            hint = ("every edition directory needs a SUMMARY.md" if ed.primary else
                    f"set up the {ed.lang!r} edition first by copying {paths.rel(book.primary.dir)}/ to "
                    f"{paths.rel(ed.dir)}/ (skills/book-new, new language edition)")
            raise config.ConfigError(f"{paths.rel(ed.summary)} not found: {hint}")
        md = ed.dir / f"{name}.md"
        if md.exists():
            raise config.ConfigError(f"{paths.rel(md)} already exists")
        source = ed.summary.read_text(encoding="utf-8")
        try:
            parsed = parse_summary(ed.summary, text=source, unnumbered=book.unnumbered)
        except SummaryError as exc:
            raise config.ConfigError(f"{paths.rel(exc.path)}:{exc.line}: {exc.message}") from None
        if f"{name}.md" in parsed.files():
            raise config.ConfigError(f"{paths.rel(ed.summary)} already lists {name}.md")
        if parent_path is not None or target_path is not None:
            shape = [(ch.path, ch.section, ch.number, ch.depth) for ch in parsed.chapters]
            if primary_shape is not None and shape != primary_shape:
                raise config.ConfigError(f"{paths.rel(ed.summary)}: edition chapter hierarchy differs. "
                                         "Align SUMMARY.md across editions before adding a chapter.")
            primary_shape = shape
        if parent_path is None and book.max_chapters is not None:
            actual = parsed.numbered_chapter_count()
            if actual >= book.max_chapters:
                raise config.ConfigError(
                    f"{paths.rel(ed.summary)}: adding a top-level chapter would exceed "
                    f"book.max_chapters = {book.max_chapters} ({actual} top-level numbered chapters already). "
                    "Use --parent <chapter> [--before|--after <sibling>] or integrate into an existing section."
                )
        lines = source.splitlines(keepends=True)
        insert, indent, depth = _chapter_position(parsed, lines, parent_path, target_path, before=before is not None)
        entry = f"{indent}- [{title}]({name}.md)\n"
        if insert and not lines[insert - 1].endswith("\n"):
            entry = "\n" + entry
        lines.insert(insert, entry)
        summary = "".join(lines)
        # Validate generated Markdown, including title syntax, before touching any edition.
        try:
            generated = parse_summary(ed.summary, text=summary, unnumbered=book.unnumbered)
        except SummaryError as exc:
            raise config.ConfigError(f"invalid chapter title: {exc.message}") from None
        added = [ch for ch in generated.chapters if ch.path == f"{name}.md"]
        if len(added) != 1 or len(generated.chapters) != len(parsed.chapters) + 1:
            raise config.ConfigError("chapter title must fit on one SUMMARY link line")
        chapter = added[0]
        if chapter.section != "numbered" or chapter.depth != depth:
            raise config.ConfigError(f"{paths.rel(ed.summary)}: generated chapter has unexpected nesting")
        if book.max_chapter_depth is not None and chapter.numbered and chapter.depth > book.max_chapter_depth:
            raise config.ConfigError(f"{paths.rel(ed.summary)}: {numbered_depth_message(chapter, book.max_chapter_depth)}")
        plan.append((ed, title, md, summary))
    created = []
    for ed, title, md, summary in plan:
        ed.summary.write_text(summary, encoding="utf-8")
        md.write_text(f"# {title}\n\n", encoding="utf-8")
        created.append(md)
    return created
