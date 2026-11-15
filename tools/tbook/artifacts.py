"""Inventory reproducible book outputs without touching authored assets or evidence locks."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from . import config, figure, paths


def outputs(book) -> set[Path]:
    result = set()
    for name in figure.names(book):
        for lang in book.languages:
            result.add(figure.out_path(book, name, lang))
            result.update(figure.slide_copies(book, name, lang))
    registry = book.viz_dir / "visualizations.json"
    if registry.is_file():
        for entry in json.loads(registry.read_text(encoding="utf-8")).get("visualizations", []):
            vid = entry.get("id", "")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", vid):
                continue
            directory = book.viz_dir / vid
            # Custom thumbnails can be authored images; only the conventional capture is automatic.
            if entry.get("thumbnail", f"{vid}/thumb.jpg") == f"{vid}/thumb.jpg":
                result.add(directory / "thumb.jpg")
            result.add(directory / ".stills.json")
            result.update(directory.glob("fig-*.jpg"))
    for name in book.raw.get("derived", {}).get("outputs", []):
        target = book.dir / name
        if Path(name).is_absolute() or ".." in Path(name).parts or not target.resolve().is_relative_to(book.dir.resolve()):
            raise config.ConfigError(f"{book.slug}: derived.outputs must stay inside the book: {name}")
        result.add(target)
    return result


def books(only: list[str] | None = None):
    # Source hygiene covers hidden books too: their files are still part of Git merges.
    if only:
        return config.load_books(only)
    return [config.load_book(str(p.parent)) for p in sorted(paths.BOOKS.glob("*/book.toml"))]


def tracked(books) -> list[str]:
    theme_outputs = {paths.ROOT / "theme/generated" / f"tokens.{ext}" for ext in ("css", "typ", "mjs")}
    theme_outputs.update(paths.ROOT / "theme/slides/styles" / f"backdrop.{ext}" for ext in ("jpg", "json"))
    candidates = {p.relative_to(paths.ROOT).as_posix() for book in books for p in outputs(book)} | {p.relative_to(paths.ROOT).as_posix() for p in theme_outputs}
    run = subprocess.run(["git", "-C", str(paths.ROOT), "ls-files", "-z"], capture_output=True, check=True)
    return sorted(set(run.stdout.decode().split("\0")) & candidates)


def untrack(books) -> list[str]:
    names = tracked(books)
    if names:
        subprocess.run(["git", "-C", str(paths.ROOT), "rm", "--cached", "--quiet", "--pathspec-from-file=-",
                        "--pathspec-file-nul"], input="\0".join(names).encode() + b"\0", check=True)
    return names


def cli(args) -> int:
    selected = books(args.book)
    names = untrack(selected) if args.action == "untrack" else tracked(selected)
    for name in names:
        print(name)
    if args.action == "check" and names:
        print(f"{len(names)} generated files tracked; run ./tbook artifacts untrack (local files are kept)")
        return 1
    return 0
