"""Prepare disjoint visualization image shards once for every publication format."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import buildcache, config, derived, theme
from ci import cache_store


def prepare(items, dest):
    books = {b.slug: b for b in config.load_books()}
    known = {f"{b.slug}/{v['id']}" for b in books.values()
             if (b.viz_dir / 'visualizations.json').is_file()
             for v in json.loads((b.viz_dir / 'visualizations.json').read_text())["visualizations"]
             if v.get('status') == 'live'}
    if (not isinstance(items, list) or not items or any(not isinstance(x, str) for x in items)
            or len(items) != len(set(items)) or set(items) - known):
        raise ValueError('invalid, empty, duplicate or unknown visualization image selection')
    theme.write()
    dest = Path(dest)
    if dest.exists():
        raise ValueError('image shard destination already exists')
    dest.mkdir(parents=True)
    for slug, book in books.items():
        ids = [name.split('/', 1)[1] for name in items if name.split('/', 1)[0] == slug]
        if not ids:
            continue
        derived.refresh(book)
        derived.images(book, ids)
        for unit in buildcache.viz_units(book, ids):
            entry = unit.entry_dir()
            if cache_store.valid(entry, buildcache.store_root()) is None:
                raise ValueError(f'incomplete prepared image entry: {unit.name}')
            cache_store._copy(entry, dest / entry.relative_to(buildcache.store_root()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--items-file', type=Path)
    mode.add_argument('--ensure-books', nargs='+', metavar='BOOK')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.items_file:
        if not args.out:
            parser.error('--items-file requires --out')
        prepare(json.loads(args.items_file.read_text()), args.out)
        return

    # A cold export must be buildable even when none of its image sources changed.
    # Restore required inputs first; install Chromium only if something needs capture.
    books = {book.slug: book for book in config.load_books()}
    theme.write()
    installed = False
    for slug in args.ensure_books:
        book = books[slug]
        derived.refresh(book)
        missing = [unit.name.split("/", 1)[1] for unit in buildcache.viz_units(book)
                   if buildcache.run(unit, None) == "missing"]
        if missing:
            if not installed and not os.environ.get("PW_CHROMIUM_PATH"):
                subprocess.run(["npx", "--no-install", "playwright", "install", "--with-deps", "chromium"], check=True)
                installed = True
            derived.images(book, missing)



if __name__ == '__main__':
    main()
