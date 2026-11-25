"""Render CI film shards, retaining the normal cache keys and strict failure behavior.

With --release, a shard renders the MP4 renditions that a release attaches (the unit of
``tbook.film.release_unit`` on a site with ``film_release_only``; on other sites ``./tbook build all``
renders them itself). ``--matrix N`` prints the GitHub Actions matrix of up to N shards, balanced by the
films' durations, as {"include": [{"shard": "i/n", "items": ["<book>/<film>", …]}, …]}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import buildcache, config, film  # noqa: E402

DEFAULT_SECONDS = 120  # a film whose film.json gives no "m:ss" duration counts as two minutes


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


def seconds(item: film.Film) -> int:
    """The film's length from film.json "duration" ("m:ss" or "h:mm:ss"), else DEFAULT_SECONDS."""
    value = str((item.meta or {}).get("duration") or "")
    try:
        parts = [int(p) for p in value.split(":")]
    except ValueError:
        return DEFAULT_SECONDS
    if len(parts) not in (2, 3) or any(p < 0 for p in parts):
        return DEFAULT_SECONDS
    total = 0
    for p in parts:
        total = total * 60 + p
    return total or DEFAULT_SECONDS


def balanced(weights: dict[str, int], count: int) -> list[list[str]]:
    """Split the names of ``weights`` into ``count`` shards, longest first onto the lightest shard, so
    that the slowest shard is as short as the films allow; each shard lists its names sorted."""
    shards: list[list[str]] = [[] for _ in range(count)]
    load = [0] * count
    for name in sorted(weights, key=lambda n: (-weights[n], n)):
        i = min(range(count), key=lambda j: (load[j], j))
        shards[i].append(name)
        load[i] += weights[name]
    return [sorted(s) for s in shards]


def matrix(items: dict[tuple[str, str], film.Film], limit: int) -> dict:
    weights = {"/".join(key): seconds(item) for key, item in items.items()}
    count = min(limit, len(weights))
    if count < 1:
        return {"include": []}
    return {"include": [{"shard": f"{i + 1}/{count}", "items": names}
                        for i, names in enumerate(balanced(weights, count))]}


def build_one(site: config.Site, item: film.Film, *, release: bool = False) -> str:
    """Use the ordinary film unit and renderer; scheduling must not invalidate rendered videos."""
    unit = film.release_unit(site, item) if release else film.video_unit(site, item)
    canvas = site.film_release_only and not release

    def render():
        missing = film.toolchain_missing(canvas=canvas)
        if missing:
            raise film.FilmError("the film toolchain is incomplete: " + "; ".join(missing))
        print(f"film {unit.name}: rendering (key {unit.key[:12]})", flush=True)
        if canvas:
            film.render_videos(item, unit.outputs[0], canvas=True)
        else:
            film.render_videos(item, unit.outputs[0])

    return buildcache.run(unit, render, repo=site.repo or None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shard", type=shard, default=(1, 1))
    parser.add_argument("--selection-env", help="environment variable containing exact book/film JSON array")
    parser.add_argument("--release", action="store_true",
                        help="render the MP4 renditions a release attaches (sites with film_release_only)")
    parser.add_argument("--matrix", type=int, metavar="N",
                        help="print the matrix of at most N shards balanced by duration, and exit")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    site, books = config.load_site(), config.load_books()
    items = {(b.slug, f.id): f for b in books for f in film.films(b)}
    if args.release:
        # Without film_release_only the build renders the videos a release attaches.
        items = {key: item for key, item in items.items() if site.film_release_only and item.meta is not None}
    if args.matrix is not None:
        if args.matrix < 1:
            parser.error("--matrix takes a positive number of shards")
        print(json.dumps(matrix(items, args.matrix), ensure_ascii=False))
        return 0
    keys = list(items)
    if args.selection_env:
        names = json.loads(os.environ[args.selection_env])
        known = {"/".join(key): key for key in items}
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names) or len(names) != len(set(names)) or set(names) - known.keys():
            raise ValueError("invalid, duplicate, missing or hidden selected film")
        keys = [known[name] for name in names]
    selected = selection(keys, args.shard)
    if args.list:
        print("\n".join("/".join(key) for key in selected))
        return 0
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
                build_one(site, items[key], release=args.release)
            except Exception as exc:
                failures.append(f"{'/'.join(key)}: {exc}")
    for failure in failures:
        print(f"FAILED {failure}", file=sys.stderr)
    print(f"film shard {args.shard[0]}/{args.shard[1]}: {len(selected)} film(s), {len(failures)} failure(s)")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
