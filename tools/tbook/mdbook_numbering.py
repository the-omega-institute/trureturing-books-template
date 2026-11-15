"""Stage and run the mdBook preprocessor for explicitly unnumbered chapter trees."""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path


def stage(root, summary) -> str:
    """Return a command that applies the model's numbers without changing the TOC tree."""
    shutil.copy2(__file__, root / "chapter-numbering.py")
    numbers = {ch.path: list(ch.number) if ch.number else None
               for ch in summary.chapters if ch.path}
    (root / "chapter-numbers.json").write_text(json.dumps(numbers), encoding="utf-8")
    return shlex.join([sys.executable, str(root / "chapter-numbering.py")])


def apply(book: dict, numbers: dict) -> None:
    def walk(items):
        for item in items:
            if not isinstance(item, dict):  # separators are serialized as strings
                continue
            chapter = item.get("Chapter")
            if chapter is None:
                continue
            path = chapter.get("source_path")
            if path in numbers:
                chapter["number"] = numbers[path]
            walk(chapter.get("sub_items", []))

    walk(book["items"])


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "supports":
        raise SystemExit(0 if sys.argv[2:] == ["html"] else 1)
    _, book = json.load(sys.stdin)
    numbers = json.loads(Path(__file__).with_name("chapter-numbers.json").read_text(encoding="utf-8"))
    apply(book, numbers)
    json.dump(book, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
