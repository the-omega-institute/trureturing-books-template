"""Book covers rendered with Typst from ``theme/typst/cover.typ``.

:func:`render_cover` draws the cyberpunk cover of one edition — book code with a glitch
treatment, title, subtitle, authors, language tag, neon perspective grid and scanlines, a
``LEAN ✓ <N>`` stamp (N = formal environments of the edition) and the short pinned
trureturing commit — in one of three formats:

* ``png`` — 1600×2560 px (5×8 in at 320 ppi): the EPUB cover image and the site's book cards;
* ``pdf`` — one page at the book's paper size (``[pdf] paper``), the same page the PDF opens with;
* ``svg`` — 5×8 in, for the web.

``variant="screen"`` is the dark neon cover; ``variant="print"`` the light-adapted one.
Inputs are compiled in a temporary directory, so concurrent calls do not interfere.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from . import config, lean, paths
from .model import load_edition

COVER_PX = (1600, 2560)
COVER_IN = (5, 8)
FORMATS = ("png", "pdf", "svg")


def cover_meta(site: config.Site, book: config.Book, edition: config.Edition, *, model=None, lock=None) -> dict:
    """The metadata dictionary shared with the PDF (see tbook.pandoc.book_meta)."""
    from . import pandoc

    if model is None:
        model = load_edition(edition)
    if lock is None:
        try:
            lock = lean.Lock.load()
        except lean.LeanError:
            lock = None
    return pandoc.book_meta(site, book, edition, model, lock)


def render_cover(site, book, edition, out_path: Path, *, fmt: str = "png", variant: str = "screen",
                 model=None, lock=None, meta: dict | None = None, width_px: int = COVER_PX[0]) -> Path:
    """Render the cover of ``edition`` to ``out_path`` and return it.

    ``model``/``lock``/``meta`` may be passed to avoid reloading them; ``width_px`` scales
    the PNG (default 1600 → 1600×2560; e.g. 480 for a 480×768 web card).
    """
    from . import pandoc

    if fmt not in FORMATS:
        raise ValueError(f"cover format must be one of {FORMATS}, got {fmt!r}")
    if variant not in config.PDF_VARIANTS:
        raise ValueError(f"cover variant must be one of {config.PDF_VARIANTS}, got {variant!r}")
    meta = meta or cover_meta(site, book, edition, model=model, lock=lock)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        paper = meta.get("academic_paper", "a4") if variant == "academic" else meta["paper"]
        page = f'paper: "{paper}"'
    else:
        page = f"width: {COVER_IN[0]}in, height: {COVER_IN[1]}in"
    with tempfile.TemporaryDirectory(prefix="tbook-cover-") as tmp:
        root = Path(tmp)
        (root / "_theme" / "typst").mkdir(parents=True)
        (root / "_theme" / "generated").mkdir(parents=True)
        shutil.copy2(paths.THEME / "typst" / "cover.typ", root / "_theme" / "typst" / "cover.typ")
        shutil.copy2(paths.GENERATED / "tokens.typ", root / "_theme" / "generated" / "tokens.typ")
        (root / "cover.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        (root / "main.typ").write_text(
            '#import "_theme/typst/cover.typ": tr-cover\n'
            '#let meta = json("cover.json")\n'
            "#set document(title: meta.title, author: meta.authors)\n"
            f"#set page({page}, margin: 0pt)\n"
            "#set text(lang: meta.lang)\n"
            f'#tr-cover(meta, variant: "{variant}")\n',
            encoding="utf-8",
        )
        ppi = width_px / COVER_IN[0] if fmt == "png" else None
        pandoc.compile_typst(root / "main.typ", out_path, root=root, fmt=fmt, ppi=ppi,
                             timestamp=pandoc.source_date_epoch(book) or None)
    return out_path
