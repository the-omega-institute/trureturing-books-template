"""v1.0.0: stop tracking reproducible figures and visualization captures."""
from pathlib import Path
import subprocess
import sys


def migrate(root: Path) -> list[str]:
    # Use the newly installed tools, including when invoked by the template migration runner.
    from tbook import artifacts, config, paths
    books = artifacts.books()
    for book in books:
        copies = {p.relative_to(book.dir).as_posix() for p in artifacts.outputs(book)
                  if "/slides/" in p.as_posix() or p in {book.dir / n for n in book.raw.get("derived", {}).get("outputs", [])}}
        if copies:
            ignore = book.dir / ".gitignore"
            old = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
            lines = ["/" + name for name in sorted(copies) if "/" + name not in old.splitlines()]
            if lines:
                ignore.write_text(old + ("\n" if old and not old.endswith("\n") else "") + "\n# Reproducible publication outputs\n" + "\n".join(lines) + "\n", encoding="utf-8")
    names = artifacts.untrack(books)
    return [f"Untracked {len(names)} generated files; working copies retained. Commit the staged deletions and book .gitignore files.",
            "Update custom derived generators to list outputs in [derived].outputs; rebuild missing outputs from their sources."]
