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


CHAPTER_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def new_chapter(slug: str, name: str, titles: dict[str, str]) -> list[Path]:
    """Append ``- [title](name.md)`` to every edition's SUMMARY and create the files.

    All or nothing: every edition is validated (title, SUMMARY.md present and parseable, chapter
    not there yet) before any file is written, so a failure leaves the book as it was.
    """
    if not CHAPTER_RE.match(name):
        raise config.ConfigError(f"chapter file name {name!r} must be kebab-case")
    book = config.named_book(slug)
    plan = []
    for ed in book.editions:
        title = titles.get(ed.lang) or titles.get("*")
        if not title:
            raise config.ConfigError(f"missing a title for the {ed.lang!r} edition (use --title {ed.lang}=…)")
        if not ed.summary.is_file():
            hint = ("every edition directory needs a SUMMARY.md" if ed.primary else
                    f"set up the {ed.lang!r} edition first by copying {paths.rel(book.primary.dir)}/ to "
                    f"{paths.rel(ed.dir)}/ (skills/book-new, new language edition)")
            raise config.ConfigError(f"{paths.rel(ed.summary)} not found: {hint}")
        md = ed.dir / f"{name}.md"
        if md.exists():
            raise config.ConfigError(f"{paths.rel(md)} already exists")
        try:
            listed = parse_summary(ed.summary).files()
        except SummaryError as exc:
            raise config.ConfigError(f"{paths.rel(exc.path)}:{exc.line}: {exc.message}") from None
        if f"{name}.md" in listed:
            raise config.ConfigError(f"{paths.rel(ed.summary)} already lists {name}.md")
        plan.append((ed, title, md))
    created = []
    for ed, title, md in plan:
        summary = ed.summary.read_text(encoding="utf-8").rstrip("\n")
        summary += f"\n- [{title}]({name}.md)\n"
        ed.summary.write_text(summary, encoding="utf-8")
        md.write_text(f"# {title}\n\n", encoding="utf-8")
        created.append(md)
    return created
