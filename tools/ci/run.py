"""Execute selected structural/static checks and decks; retain ordinary whole-book cache units."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import academic, build, buildcache, config, paths, slides  # noqa: E402
from ci import testing  # noqa: E402


def run(command):
    subprocess.run(command, check=True)


def selected_slides(items):
    site = config.load_site()
    books = {b.slug: b for b in config.load_books()}
    known = {f"{b.slug}/{d}" for b in books.values() for d in slides.deck_names(b)}
    if len(items) != len(set(items)) or set(items) - known:
        raise ValueError("invalid, duplicate or missing selected deck")
    for slug, book in books.items():
        names = [x.split("/")[1] for x in items if x.split("/")[0] == slug]
        if not names:
            continue
        out = build.slides_dir(slug)
        unit = buildcache.slides_unit(site, book, out)
        if set(names) == set(slides.deck_names(book)):
            slides.build(site, book, out)
        elif buildcache.run(unit, None, repo=site.repo or None) == "missing":
            # Partial output must never be saved under the complete book's unit key.
            slidev = [d for d in names if not academic.is_academic(book.slides_dir / d)]
            if slidev:
                run([slides._node(), str(paths.TOOLS / "node" / "slides-build.mjs"), "--book", slug,
                     "--out", str(out.resolve()), "--base", slides.base_path(site),
                     *[v for d in slidev for v in ("--deck", d)]])
            for name in names:
                if name not in slidev:
                    academic.build_deck(site, book, name, out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("structure", "viz-static", "slides-static", "slides", "unit", "browser"))
    parser.add_argument("--plan-file", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
    selected = plan["selections"]["normal"]
    books = selected["books"]
    kind = args.kind
    if kind in ("unit", "browser"):
        testing.run_tests(selected["unit_tests" if kind == "unit" else "browser_tests"], required=kind == "browser")
    elif kind == "structure":
        # Deleted/hidden final book still needs global structural validation.
        run([str(paths.ROOT / "tbook"), "check", *[v for b in books for v in ("--book", b)]])
    elif kind == "viz-static":
        run(["node", "tools/node/viz-validate.mjs", *books])
    elif kind == "slides-static":
        run(["node", "tools/node/slides-check.mjs", *[v for b in books for v in ("--book", b)]])
    elif kind == "slides":
        selected_slides(plan["slides"])
    else:
        raise ValueError(f"unknown check: {kind}")


if __name__ == "__main__":
    main()
