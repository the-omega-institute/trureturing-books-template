"""Build orchestration: ``./tbook build [html|pdf|epub|viz|slides|films|site|all]``.

Directory contract (all under ``build/``, git-ignored)::

    build/stage/<slug>/<lang>/mdbook/   staged mdBook project (book.toml, src/)
    build/stage/<slug>/<lang>/pandoc/   staged Pandoc input (book.md, _book/, cover)
    build/html/<slug>/<lang>/           mdBook output
    build/dist/<slug>/                  PDF and EPUB downloads, named by Book.artifact()
    build/slides/<slug>/                Slidev output (one dir per deck and language) + PDFs

``site`` assembles ``_site/`` (the GitHub Pages artifact) from those directories and
publishes visualizations, films and slides with the book they belong to.

Every unit (an edition's HTML, a PDF variant, an EPUB, a book's slides, a film) goes through
:mod:`tbook.buildcache`: when its inputs did not change, the stored outputs are restored instead of
building it again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import buildcache, config, lean, paths
from .model import load_book_models

TARGETS = ("html", "pdf", "epub", "viz", "slides", "films", "site")


def html_dir(slug: str, lang: str) -> Path:
    return paths.BUILD / "html" / slug / lang


def dist_dir(slug: str) -> Path:
    return paths.BUILD / "dist" / slug


def stage_dir(slug: str, lang: str, target: str) -> Path:
    return paths.BUILD / "stage" / slug / lang / target


def slides_dir(slug: str) -> Path:
    return paths.BUILD / "slides" / slug


@dataclass
class BuildResult:
    outputs: list[Path] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _timed(label: str, fn, result: BuildResult) -> None:
    t0 = time.time()
    print(f"→ {label}", flush=True)
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001 - report and continue with other targets
        result.failures.append(f"{label}: {exc}")
        print(f"✗ {label}: {exc}", flush=True)
        return
    if isinstance(out, Path):
        result.outputs.append(out)
    print(f"✓ {label} ({time.time() - t0:.1f}s)" + (f" → {paths.rel(out)}" if isinstance(out, Path) else ""), flush=True)


def _cached(make_unit, build_fn, out: Path) -> Path:
    """``build_fn()`` unless the unit ``make_unit()`` describes is cached (:func:`tbook.buildcache.run`);
    ``out`` either way. The unit is made here, inside :func:`_timed`, so an error while reading its inputs
    is reported as a failure of this step."""
    buildcache.run(make_unit(), build_fn)
    return out


def _figures(book: config.Book) -> None:
    """Draw the book's figures (``./tbook fig build``): the editions show the committed files, which
    must be what the scripts draw now."""
    from . import figure

    changed, errors = figure.build(book)
    for p in changed:
        print(f"  figure redrawn: {paths.rel(p)} (commit it)", flush=True)
    if errors:
        raise RuntimeError("; ".join(errors))


def check_films(targets: list[str], books: list[config.Book], film_ids: list[str] | None) -> None:
    """``--film`` names films of the selected books and goes with ``build films`` only."""
    if not film_ids:
        return
    if set(targets) != {"films"}:
        raise config.ConfigError("--film limits `./tbook build films`; build site and build all publish every film")
    from . import film

    have = {f.id for book in books for f in film.films(book)}
    missing = [f for f in film_ids if f not in have]
    if missing:
        raise config.ConfigError(f"--film {', '.join(missing)}: no such film in "
                                 f"{', '.join(b.slug for b in books) or 'the selected books'} "
                                 f"(films: {', '.join(sorted(have)) or 'none'})")


def build(targets: list[str], books: list[config.Book], langs: list[str] | None = None,
          *, pdf_variants: list[str] | None = None, films: list[str] | None = None) -> BuildResult:
    """Build ``targets`` of ``books``. ``films`` (``--film``, with the target ``films`` only): render or restore
    these films; the other films of the books are only restored from the build cache (:func:`tbook.film.only`)."""
    check_films(targets, books, films)
    unknown = [lang for lang in langs or [] if not any(lang in book.languages for book in books)]
    if unknown:
        have = "; ".join(f"{book.slug} ({', '.join(book.languages)})" for book in books) or "no books"
        raise config.ConfigError(f"no {' or '.join(repr(lang) for lang in unknown)} edition in the selected "
                                 f"books: {have}")
    site = config.load_site()
    lock = lean.Lock.load()
    result = BuildResult()
    want = set(targets)
    if "all" in want:
        want = set(TARGETS)
    for book in books:
        if want & {"html", "pdf", "epub"}:
            from . import figure

            if figure.names(book):
                _timed(f"figures {book.slug}", lambda b=book: _figures(b), result)
        models = load_book_models(book) if want & {"html", "pdf", "epub"} else {}
        for ed in book.editions:
            if langs and ed.lang not in langs:
                continue
            model = models.get(ed.lang)
            if "html" in want and book.outputs_html:
                from . import html

                out = html_dir(book.slug, ed.lang)
                _timed(f"html {ed.key}", lambda o=out: _cached(
                    lambda: buildcache.html_unit(site, book, ed.lang, o),
                    lambda: html.build_edition(site, book, ed, model, lock, o), o), result)
            if "pdf" in want:
                from . import pandoc

                for variant in book.outputs_pdf:
                    if pdf_variants and variant not in pdf_variants:
                        continue
                    out = dist_dir(book.slug) / book.artifact(ed.lang, "pdf", variant)
                    _timed(f"pdf {ed.key} {variant}", lambda v=variant, o=out: _cached(
                        lambda: buildcache.pdf_unit(site, book, ed.lang, v, o),
                        lambda: pandoc.build_pdf(site, book, ed, model, lock, v, o), o), result)
            if "epub" in want and book.outputs_epub:
                from . import pandoc

                out = dist_dir(book.slug) / book.artifact(ed.lang, "epub")
                _timed(f"epub {ed.key}", lambda o=out: _cached(
                    lambda: buildcache.epub_unit(site, book, ed.lang, o),
                    lambda: pandoc.build_epub(site, book, ed, model, lock, o), o), result)
        if "slides" in want:
            from . import slides

            _timed(f"slides {book.slug}", lambda: slides.build(site, book, slides_dir(book.slug)), result)
    if "site" in want or "viz" in want or "films" in want:
        from . import site as site_mod

        from . import film as film_mod

        with film_mod.only(films):
            _timed("site", lambda: site_mod.build(site, books, paths.SITE_OUT,
                                                  only={"viz", "films"} & want if "site" not in want else None), result)
    return result
