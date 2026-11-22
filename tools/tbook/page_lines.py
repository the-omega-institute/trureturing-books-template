"""Source-line budgets for book edition Markdown; no network or publishing tools."""
from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

from . import config


def line_count(text: str) -> int:
    """Count LF/CRLF source lines, including an unterminated final line."""
    return text.count("\n") + int(bool(text) and not text.endswith("\n"))


def message(actual: int, limit: int) -> str:
    return (f"{actual} lines exceed book.max_page_lines = {limit}; "
            "split complete sections into child pages or move supplementary material to an appendix")


def check_book(book: config.Book) -> list[tuple[Path, int, int]]:
    """Audit all Markdown in configured editions, including SUMMARY and orphan pages."""
    limit = book.max_page_lines
    if limit is None:
        return []
    return [(p, actual, limit) for edition in book.editions for p in sorted(edition.dir.rglob("*.md"))
            if p.is_file() and (actual := line_count(p.read_text(encoding="utf-8"))) > limit]


def check_tree(tree, changed: list[str] | None = None) -> list[tuple[str, int, int]]:
    """Check complete files in the tested Git tree, independently of reusable CI coverage.

    A book config edit rechecks that book; a site config edit rechecks all visible books
    (editions and visibility may have changed). Deleted paths are absent from tree.files.
    """
    site = tree.toml("site.toml")
    hidden = config.hide_patterns(site.get("books", {}).get("hide"))
    selected = set(changed) if changed is not None else None
    failures = []
    for name in sorted(tree.files):
        parts = PurePosixPath(name).parts
        if len(parts) != 3 or parts[0] != "books" or parts[2] != "book.toml":
            continue
        slug = parts[1]
        if any(fnmatch.fnmatchcase(slug, pat) for pat in hidden):
            continue
        meta = tree.toml(name).get("book", {})
        limit = config.page_line_limit(meta.get("max_page_lines"), name)
        if limit is None:
            continue
        languages = meta.get("editions") or site.get("site", {}).get("languages") or ["zh", "en"]
        if not isinstance(languages, list) or not all(isinstance(lang, str) and config.LANG_RE.fullmatch(lang)
                                                     for lang in languages):
            raise config.ConfigError(f"{name}: book.editions must list language codes")
        prefixes = tuple(f"books/{slug}/{lang}/" for lang in languages)
        whole_book = selected is None or name in selected or "site.toml" in selected
        for page in sorted(tree.files if whole_book else selected & tree.files):
            if page.endswith(".md") and page.startswith(prefixes):
                actual = line_count(tree.read(page))
                if actual > limit:
                    failures.append((page, actual, limit))
    return failures
