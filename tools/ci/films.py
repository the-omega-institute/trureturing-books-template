"""Render CI film shards, retaining the normal cache keys and strict failure behavior."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import config, film  # noqa: E402


def shard(value: str) -> tuple[int, int]:
    try:
        index, count = map(int, value.split("/"))
        if 1 <= index <= count:
            return index, count
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected i/n with 1 <= i <= n")


def selection(items, part: tuple[int, int]):
    index, count = part
    return sorted(items)[index - 1::count]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=shard, default=(1, 1))
    args = parser.parse_args()
    site, books = config.load_site(), config.load_books()
    selected = set(selection([(b.slug, f.id) for b in books for f in film.films(b)], args.shard))
    failures = []
    for book in books:
        ids = {fid for slug, fid in selected if slug == book.slug}
        if not ids:
            continue
        try:
            film.build_videos(site, book, mode="require", select=ids)
        except Exception as exc:
            failures.append(f"{book.slug}: {exc}")
    for failure in failures:
        print(f"FAILED {failure}", file=sys.stderr)
    print(f"film shard {args.shard[0]}/{args.shard[1]}: {len(selected)} film(s), {len(failures)} failure(s)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
