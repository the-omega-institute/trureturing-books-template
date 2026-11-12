"""Render CI film shards, retaining the normal cache keys and strict failure behavior."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import buildcache, config, film  # noqa: E402


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


def build_one(site: config.Site, item: film.Film) -> str:
    """Use the ordinary film unit and renderer; scheduling must not invalidate rendered videos."""
    unit = film.video_unit(site, item)

    def render():
        missing = film.toolchain_missing()
        if missing:
            raise film.FilmError("the film toolchain is incomplete: " + "; ".join(missing))
        print(f"film {unit.name}: rendering (key {unit.key[:12]})", flush=True)
        film.render_videos(item, unit.outputs[0])

    return buildcache.run(unit, render, repo=site.repo or None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=shard, default=(1, 1))
    args = parser.parse_args()
    site, books = config.load_site(), config.load_books()
    items = {(b.slug, f.id): f for b in books for f in film.films(b)}
    selected = selection(items, args.shard)
    failures = []
    for book in books:
        keys = [key for key in selected if key[0] == book.slug]
        if not keys:
            continue
        errors = [issue.format() for issue in film.check(book) if issue.severity == "error"]
        if errors:
            failures.extend(errors)
            continue
        for key in keys:
            try:
                build_one(site, items[key])
            except Exception as exc:
                failures.append(f"{'/'.join(key)}: {exc}")
    for failure in failures:
        print(f"FAILED {failure}", file=sys.stderr)
    print(f"film shard {args.shard[0]}/{args.shard[1]}: {len(selected)} film(s), {len(failures)} failure(s)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
