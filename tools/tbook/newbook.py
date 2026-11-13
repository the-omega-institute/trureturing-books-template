"""``./tbook new-book`` and ``./tbook new-chapter``: scaffold books and chapters."""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path

from . import config, paths
from .summary import SummaryError, parse_summary

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


def new_chapter(slug: str, name: str, titles: dict[str, str], *, parent: str | None = None) -> list[Path]:
    """Append ``- [title](name.md)`` to every edition's SUMMARY and create the files.

    All or nothing: every edition is validated (title, SUMMARY.md present and parseable, chapter
    not there yet) before any file is written, so a failure leaves the book as it was.
    """
    if not CHAPTER_RE.fullmatch(name):
        raise config.ConfigError(f"chapter file name {name!r} must be kebab-case")
    book = config.named_book(slug)
    parent_path = parent if parent is None or parent.endswith(".md") else parent + ".md"
    plan = []
    placement = None
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
        try:
            parsed = parse_summary(ed.summary)
            listed = parsed.files()
        except SummaryError as exc:
            raise config.ConfigError(f"{paths.rel(exc.path)}:{exc.line}: {exc.message}") from None
        if f"{name}.md" in listed:
            raise config.ConfigError(f"{paths.rel(ed.summary)} already lists {name}.md")
        lines = ed.summary.read_text(encoding="utf-8").splitlines(keepends=True)
        indent = ""
        insert = len(lines)
        if parent_path is not None:
            matches = [ch for ch in parsed.chapters if ch.path == parent_path]
            if len(matches) != 1 or matches[0].section != "numbered":
                raise config.ConfigError(f"{paths.rel(ed.summary)}: parent {parent_path!r} must name one numbered chapter")
            ancestor = matches[0]
            if not (ed.dir / parent_path).is_file():
                raise config.ConfigError(f"{paths.rel(ed.dir / parent_path)} not found")
            # Place the new child after the whole existing subtree, before any following part.
            start = parsed.chapters.index(ancestor)
            last = ancestor
            for child in parsed.chapters[start + 1:]:
                if child.depth <= ancestor.depth:
                    break
                last = child
            insert = last.line
            source_indent = re.match(r"[ \t]*", lines[ancestor.line - 1]).group().expandtabs(4)
            indent = source_indent + "  "
            shape = [(ch.path, ch.section, ch.number, ch.depth) for ch in parsed.chapters]
            if placement is not None and shape != placement:
                raise config.ConfigError("edition chapter hierarchy differs; align SUMMARY.md before adding a child")
            placement = shape
        else:
            # mdBook forbids a numbered chapter after an unnumbered suffix.
            suffix = next((ch for ch in parsed.chapters if ch.section == "suffix"), None)
            if suffix is not None:
                insert = suffix.line - 1
        entry = f"{indent}- [{title}]({name}.md)\n"
        if insert and not lines[insert - 1].endswith("\n"):
            entry = "\n" + entry
        lines.insert(insert, entry)
        summary = "".join(lines)
        # Validate generated Markdown, including title syntax, before touching any edition.
        try:
            generated = parse_summary(ed.summary, text=summary)
        except SummaryError as exc:
            raise config.ConfigError(f"invalid chapter title: {exc.message}") from None
        added = [ch for ch in generated.chapters if ch.path == f"{name}.md"]
        if len(added) != 1 or len(generated.chapters) != len(parsed.chapters) + 1:
            raise config.ConfigError("chapter title must fit on one SUMMARY link line")
        plan.append((ed, title, md, summary))
    created = []
    for ed, title, md, summary in plan:
        ed.summary.write_text(summary, encoding="utf-8")
        md.write_text(f"# {title}\n\n", encoding="utf-8")
        created.append(md)
    return created
