"""Run a book-owned deterministic generator, including its read-only freshness check."""

from __future__ import annotations

import os
import subprocess
import sys

from . import config, paths


def refresh(book: config.Book, *, check: bool = False) -> None:
    command = book.raw.get("derived", {}).get("command")
    if command is None:
        return
    if not isinstance(command, list) or not command or not all(isinstance(a, str) and a for a in command):
        raise config.ConfigError(f"{book.slug}: derived.command must be a nonempty array of arguments")
    command = list(command)
    if command[0] == "python3":
        command[0] = sys.executable
    if check:
        command.append("--check")
    env = dict(os.environ, TBOOK_ROOT=str(paths.ROOT),
               PYTHONPATH=os.pathsep.join(filter(None, [str(paths.TOOLS), os.environ.get("PYTHONPATH")])))
    try:
        subprocess.run(command, cwd=paths.ROOT, env=env, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise config.ConfigError(f"{book.slug}: derived data {'check' if check else 'refresh'} failed: {exc}; "
                                 f"run ./tbook sync --book {book.slug}") from exc


def images(book: config.Book, ids: list[str] | None = None) -> None:
    """Materialize local visualization outputs before PDF/EPUB or site publication."""
    if not (book.viz_dir / "visualizations.json").is_file():
        return
    from . import buildcache
    units = buildcache.viz_units(book, ids)
    missing = [unit for unit in units if buildcache.run(unit, None) == "missing"]
    if not missing:
        return
    if os.environ.get("TBOOK_STILLS_REQUIRE_CACHE") == "1":
        raise config.ConfigError("missing prepared visualization images: " + ", ".join(u.name for u in missing))
    # A single parser/server/browser per batch, rather than restarting all three for every page.
    subprocess.run(["node", str(paths.TOOLS / "node/viz-thumbs.mjs"), book.slug,
                    *(u.name.split("/", 1)[1] for u in missing)], cwd=paths.ROOT,
                   env=dict(os.environ, TBOOK_ROOT=str(paths.ROOT)), check=True)
    for unit in missing:
        if buildcache.enabled():
            buildcache.store(unit)
