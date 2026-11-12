"""Load ``site.toml``, ``books/<slug>/book.toml`` and the i18n string tables."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import paths

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]+)*$")
PDF_VARIANTS = ("screen", "print", "academic")
DEFAULT_PDF_VARIANTS = ("screen", "print")


class ConfigError(Exception):
    pass


Localized = dict[str, str]


def localized(value: Any, where: str) -> Localized:
    """Accept either a plain string (same in all languages) or a {lang: text} table."""
    if value is None:
        return {}
    if isinstance(value, str):
        return {"*": value}
    if isinstance(value, dict) and all(isinstance(v, str) for v in value.values()):
        return dict(value)
    raise ConfigError(f"{where}: expected a string or a table of language = \"text\"")


def pick(text: Localized, lang: str, fallback: list[str] | None = None) -> str:
    """Return the text for ``lang``, falling back to '*' and then to the fallback languages."""
    if lang in text:
        return text[lang]
    if "*" in text:
        return text["*"]
    for other in fallback or []:
        if other in text:
            return text[other]
    return next(iter(text.values()), "")


def duplicates(items: list[str]) -> list[str]:
    """Items that occur more than once, in order of their second occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen and item not in out:
            out.append(item)
        seen.add(item)
    return out


# --------------------------------------------------------------------------- i18n


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


I18N_META = ("name", "bcp47", "short")


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{paths.rel(path)}: {exc}") from None


@lru_cache(maxsize=None)
def i18n(lang: str) -> dict[str, Any]:
    """Strings for ``lang``: theme/i18n/<lang>.toml overridden by i18n/<lang>.toml.

    An unknown language falls back to English so a new edition still builds; ``check``
    reports the missing table. It borrows the English strings but not English's ``[meta]``:
    until i18n/<lang>.toml names the language, it is labelled by its code (``lang="ja"``,
    ``JA``), never as English.
    """
    base = paths.I18N_THEME / f"{lang}.toml"
    known = base.exists()
    table = _load_toml(base if known else paths.I18N_THEME / "en.toml")
    if not known:
        table["meta"] = {"name": lang, "bcp47": lang, "short": lang.upper()}
    local = paths.I18N_LOCAL / f"{lang}.toml"
    if local.exists():
        table = _deep_merge(table, _load_toml(local))
    return table


def has_i18n(lang: str) -> bool:
    return (paths.I18N_THEME / f"{lang}.toml").exists() or (paths.I18N_LOCAL / f"{lang}.toml").exists()


def i18n_problems(languages: list[str]) -> list[tuple[Path, str]]:
    """``(file, message)`` for each defect of the i18n tables of ``languages``, for ``check``.

    A language without theme/i18n/<lang>.toml is named by i18n/<lang>.toml alone, so its
    ``[meta]`` must set name, bcp47 and short. No two languages may share a BCP 47 tag or a
    short label: ``lang="…"`` attributes and the edition switcher tell them apart by these.
    Languages with no table at all are skipped (``has_i18n`` reports them).
    """
    langs = [lang for lang in dict.fromkeys(languages) if has_i18n(lang)]
    problems: list[tuple[Path, str]] = []

    def where(lang: str) -> Path:
        local = paths.I18N_LOCAL / f"{lang}.toml"
        return local if local.exists() else paths.I18N_THEME / f"{lang}.toml"

    def built_in(lang: str) -> bool:
        return (paths.I18N_THEME / f"{lang}.toml").exists()

    for lang in langs:
        if built_in(lang):
            continue
        meta = _load_toml(where(lang)).get("meta")
        meta = meta if isinstance(meta, dict) else {}
        missing = [key for key in I18N_META if not isinstance(meta.get(key), str) or not meta[key].strip()]
        if missing:
            problems.append((where(lang), (
                f"[meta] must set {', '.join(missing)} for the {lang!r} edition: there is no "
                f"theme/i18n/{lang}.toml, so this file names the language, e.g. name = \"<its own name>\", "
                f"bcp47 = \"{lang}\", short = \"{lang.upper()}\"")))
    for key in ("bcp47", "short"):
        groups: dict[str, list[str]] = {}
        for lang in langs:
            value = s(lang, f"meta.{key}").strip()
            if value:
                groups.setdefault(value.casefold(), []).append(lang)
        for group in groups.values():
            if len(group) < 2:
                continue
            # built-in tables are distinct by construction: blame the languages named locally
            for lang in [lang for lang in group if not built_in(lang)] or group[1:]:
                others = ", ".join(repr(o) for o in group if o != lang)
                problems.append((where(lang), (
                    f"meta.{key} = {s(lang, f'meta.{key}')!r} for {lang!r} is also the {key} of {others}; "
                    "every language needs its own")))
    return problems


def s(lang: str, dotted: str) -> str:
    """Look up an i18n string such as ``s('zh', 'env.theorem')``."""
    node: Any = i18n(lang)
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            node = None
            break
        node = node[part]
    if node is None and lang != "en":
        return s("en", dotted)
    return "" if node is None else str(node)


def bcp47(lang: str) -> str:
    return s(lang, "meta.bcp47") or lang


# --------------------------------------------------------------------------- site


@dataclass
class Site:
    root: Path
    repo: str
    base_url: str
    languages: list[str]
    title: Localized
    tagline: Localized
    trureturing_repo: str
    trureturing_branch: str
    book_order: list[str]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    book_hide: list[str] = field(default_factory=list)

    @property
    def default_language(self) -> str:
        return self.languages[0]

    def hidden_by(self, slug: str) -> str:
        """The first ``[books].hide`` pattern that hides the book ``slug``, or '' when it is visible."""
        return next((p for p in self.book_hide if fnmatch.fnmatchcase(slug, p)), "")

    def text(self, value: Localized, lang: str) -> str:
        return pick(value, lang, self.languages)

    def book_url(self, slug: str, *parts: str) -> str:
        """Absolute public URL of a path under the published site (may be '' if unknown)."""
        if not self.base_url:
            return ""
        tail = "/".join(p.strip("/") for p in (slug, *parts) if p)
        return self.base_url.rstrip("/") + "/" + tail


def _git_remote_repo(root: Path) -> str:
    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1)
    m = re.search(r"/git/([^/]+/[^/]+?)(?:\.git)?/?$", url)  # local proxies such as http://host/git/owner/name
    return m.group(1) if m else ""


def pages_base_url(repo: str) -> str:
    if not repo or "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{name}/"


@lru_cache(maxsize=1)
def load_site() -> Site:
    if not paths.SITE_TOML.exists():
        raise ConfigError("site.toml not found at the repository root")
    with paths.SITE_TOML.open("rb") as fh:
        raw = tomllib.load(fh)
    site = raw.get("site", {})
    tru = raw.get("trureturing", {})
    repo = os.environ.get("TBOOK_REPO") or site.get("repo") or os.environ.get("GITHUB_REPOSITORY") or _git_remote_repo(paths.ROOT)
    base_url = os.environ.get("TBOOK_BASE_URL") or site.get("base_url") or pages_base_url(repo)
    if base_url and not base_url.endswith("/"):
        base_url += "/"
    languages = list(site.get("languages") or ["zh", "en"])
    for lang in languages:
        if not LANG_RE.match(lang):
            raise ConfigError(f"site.toml: invalid language code {lang!r}")
    if duplicates(languages):
        raise ConfigError(f"site.toml: languages lists {duplicates(languages)[0]!r} twice")
    books = raw.get("books", {})
    if not isinstance(books, dict):
        raise ConfigError("site.toml: books must be a table ([books])")
    return Site(
        root=paths.ROOT,
        repo=repo,
        base_url=base_url,
        languages=languages,
        title=localized(site.get("title"), "site.title") or {"*": "Books"},
        tagline=localized(site.get("tagline"), "site.tagline"),
        trureturing_repo=tru.get("repo", "the-omega-institute/trureturing"),
        trureturing_branch=tru.get("branch", "dev"),
        book_order=list(books.get("order", [])),
        raw=raw,
        book_hide=hide_patterns(books.get("hide")),
    )


def hide_patterns(value: Any) -> list[str]:
    """``[books].hide`` of site.toml: glob patterns (:func:`fnmatch.fnmatchcase`, matched against the book
    slug, case-sensitive) of books that every command and output treats as absent; [] when unset.

    tools/node/slides-lib.mjs (``hidePatterns``) reads it the same way, with the same messages.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"site.toml: [books].hide must be a list of glob patterns, e.g. hide = [\"example-*\"]; "
                          f"got {json.dumps(value, ensure_ascii=False, default=str)}")
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(f"site.toml: [books].hide entries must be non-empty strings (glob patterns such as "
                              f"\"example-*\"); got {json.dumps(item, ensure_ascii=False, default=str)}")
    return list(value)


# --------------------------------------------------------------------------- books


@dataclass
class Edition:
    book: "Book"
    lang: str

    @property
    def dir(self) -> Path:
        return self.book.dir / self.lang

    @property
    def summary(self) -> Path:
        return self.dir / "SUMMARY.md"

    @property
    def primary(self) -> bool:
        return self.lang == self.book.languages[0]

    @property
    def bcp47(self) -> str:
        return bcp47(self.lang)

    @property
    def key(self) -> str:
        return f"{self.book.slug}/{self.lang}"

    def text(self, value: Localized) -> str:
        return pick(value, self.lang, self.book.languages)

    @property
    def title(self) -> str:
        return self.text(self.book.title)

    @property
    def subtitle(self) -> str:
        return self.text(self.book.subtitle)

    @property
    def description(self) -> str:
        return self.text(self.book.description)


@dataclass
class Book:
    slug: str
    dir: Path
    version: str
    title: Localized
    subtitle: Localized
    description: Localized
    authors: list[str]
    license: str
    languages: list[str]
    code: str
    date: str
    isbn: Localized
    outputs_html: bool
    outputs_pdf: list[str]
    outputs_epub: bool
    pdf: dict[str, Any]
    epub: dict[str, Any]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    editions: list[Edition] = field(default_factory=list)

    def edition(self, lang: str) -> Edition:
        for ed in self.editions:
            if ed.lang == lang:
                return ed
        raise ConfigError(f"book {self.slug} has no {lang!r} edition")

    @property
    def primary(self) -> Edition:
        return self.editions[0]

    def artifact(self, lang: str, kind: str, variant: str = "") -> str:
        """Canonical download file name, e.g. example-monograph-0.1.0-zh-screen.pdf."""
        stem = f"{self.slug}-{self.version}-{lang}"
        if kind == "pdf":
            return f"{stem}-{variant or 'screen'}.pdf"
        if kind == "epub":
            return f"{stem}.epub"
        raise ValueError(kind)

    # Media directories owned by the book.
    @property
    def viz_dir(self) -> Path:
        return self.dir / "viz"

    @property
    def slides_dir(self) -> Path:
        return self.dir / "slides"

    @property
    def films_dir(self) -> Path:
        return self.dir / "films"

    @property
    def assets_dir(self) -> Path:
        return self.dir / "assets"


def load_book(slug_or_dir: str | Path) -> Book:
    bdir = Path(slug_or_dir)
    if not bdir.is_absolute():
        bdir = paths.BOOKS / str(slug_or_dir)
    slug = bdir.name
    toml_path = bdir / "book.toml"
    if not toml_path.exists():
        raise ConfigError(f"{paths.rel(toml_path)} not found")
    if not SLUG_RE.match(slug):
        raise ConfigError(f"book directory name {slug!r} must be kebab-case (a-z, 0-9, -)")
    with toml_path.open("rb") as fh:
        raw = tomllib.load(fh)
    meta = raw.get("book", {})
    outputs = raw.get("outputs", {})
    where = paths.rel(toml_path)
    languages = list(meta.get("editions") or load_site().languages)
    if not languages:
        raise ConfigError(f"{where}: book.editions must list at least one language")
    for lang in languages:
        if not LANG_RE.match(lang):
            raise ConfigError(f"{where}: invalid edition language {lang!r}")
    if duplicates(languages):
        raise ConfigError(f"{where}: book.editions lists {duplicates(languages)[0]!r} twice")
    pdf_variants = outputs.get("pdf", list(DEFAULT_PDF_VARIANTS))
    if pdf_variants is True:
        pdf_variants = list(DEFAULT_PDF_VARIANTS)
    elif pdf_variants is False:
        pdf_variants = []
    for v in pdf_variants:
        if v not in PDF_VARIANTS:
            raise ConfigError(f"{where}: outputs.pdf entries must be among {PDF_VARIANTS}, got {v!r}")
    title = localized(meta.get("title"), f"{where} book.title")
    if not title:
        raise ConfigError(f"{where}: book.title is required")
    book = Book(
        slug=slug,
        dir=bdir,
        version=str(meta.get("version", "0.1.0")),
        title=title,
        subtitle=localized(meta.get("subtitle"), f"{where} book.subtitle"),
        description=localized(meta.get("description"), f"{where} book.description"),
        authors=list(meta.get("authors", [])),
        license=str(meta.get("license", "")),
        languages=languages,
        code=str(meta.get("code", slug.upper().replace("-", "//", 1))),
        date=str(meta.get("date") or datetime.now(timezone.utc).date().isoformat()),
        isbn=localized(meta.get("isbn"), f"{where} book.isbn"),
        outputs_html=bool(outputs.get("html", True)),
        outputs_pdf=list(pdf_variants),
        outputs_epub=bool(outputs.get("epub", True)),
        pdf=dict(raw.get("pdf", {})),
        epub=dict(raw.get("epub", {})),
        raw=raw,
    )
    book.editions = [Edition(book, lang) for lang in languages]
    return book


def _book_dirs() -> list[str]:
    """Slugs of every directory of books/ with a book.toml, hidden ones included, sorted."""
    if not paths.BOOKS.exists():
        return []
    return sorted(p.name for p in paths.BOOKS.iterdir() if (p / "book.toml").exists())


def book_slugs() -> list[str]:
    """The books of the repository in site order ([books] order first, then by slug), without the books
    that site.toml [books].hide hides: the one list every command and output starts from."""
    site = load_site()
    found = [s for s in _book_dirs() if not site.hidden_by(s)]
    order = [s for s in site.book_order if s in found]
    return order + [s for s in found if s not in order]


def unhide_hint(slug: str) -> str:
    """For a "not in trureturing.lock.json" message about a book read by path: when site.toml [books].hide hides
    ``slug``, why ./tbook pin --refresh cannot help yet (it collects visible books only); '' otherwise."""
    try:
        pattern = load_site().hidden_by(slug)
    except ConfigError:
        return ""
    if not pattern:
        return ""
    return (f" (book {slug} is hidden by site.toml [books].hide {json.dumps(pattern)}: remove that pattern "
            "from hide first, since ./tbook pin --refresh collects the citations of visible books only)")


def hidden_books() -> list[str]:
    """Slugs of the books that site.toml [books].hide hides (they exist but no command sees them), sorted."""
    site = load_site()
    return [s for s in _book_dirs() if site.hidden_by(s)]


def hidden_error(slugs: list[str]) -> ConfigError:
    """The error for naming hidden books explicitly (``--book``, ``new-chapter <slug>`` …).

    Unhiding alone is not enough once ``./tbook pin --refresh`` has run while the book was hidden: the lock file
    keeps only the declarations visible books cite, so the message names the refresh too. The Node scripts give
    the same text (tools/node/slides-lib.mjs hiddenError; tools/tests/test_hide.py compares them)."""
    site = load_site()
    patterns = list(dict.fromkeys(site.hidden_by(s) for s in slugs))
    one = len(slugs) == 1
    return ConfigError(
        f"book{'' if one else 's'} {', '.join(slugs)} {'is' if one else 'are'} hidden by site.toml [books].hide "
        f"({', '.join(json.dumps(p, ensure_ascii=False) for p in patterns)}); to use {'it' if one else 'them'}, remove "
        f"{'that pattern' if len(patterns) == 1 else 'those patterns'} from hide, then run ./tbook pin --refresh "
        f"(the lock file keeps only the declarations that visible books cite)")


def named_book(name: str | Path) -> Book:
    """The book a command was given (``new-chapter <slug>``, ``viz new <slug>`` …): :func:`load_book`, except
    that a slug of a book site.toml [books].hide hides is an error, since the book is absent for every command.

    :func:`load_book` itself loads any book directory, hidden or not (a path is not a name: the film pipeline,
    for one, works on the directory it is given)."""
    slug = str(name)
    if "/" not in slug and os.sep not in slug and slug in hidden_books():
        raise hidden_error([slug])
    return load_book(name)


def load_books(only: list[str] | None = None) -> list[Book]:
    """The books of :func:`book_slugs`, or those named in ``only`` (unknown or hidden names are errors)."""
    slugs = book_slugs()
    if only:
        hidden = [s for s in only if s not in slugs and s in hidden_books()]
        if hidden:
            raise hidden_error(list(dict.fromkeys(hidden)))
        missing = [s for s in only if s not in slugs]
        if missing:
            raise ConfigError(f"unknown book(s): {', '.join(missing)}; known: {', '.join(slugs) or 'none'}")
        slugs = [s for s in slugs if s in only]
    return [load_book(s) for s in slugs]
