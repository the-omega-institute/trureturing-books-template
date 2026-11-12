"""One Typst compilation per process; called by tbook.pandoc.compile_typst."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path


def font_options(typst, options: dict, directory: Path) -> dict:
    """Exclude placeholder fonts that claim coverage but draw missing-glyph boxes."""
    catalog = typst.Fonts(include_embedded_fonts=False,
                          include_system_fonts=not options.get("ignore_system_fonts", False),
                          font_paths=options.get("font_paths", [])).fonts()
    blocked = {str(f.path) for f in catalog if f.path and f.family.replace(" ", "").lower() == "lastresort"}
    if not blocked:
        return options
    # font_paths scans directories, not individual files. Keep genuine system
    # and project fonts through a temporary directory of links to allowed files.
    for source in sorted({str(f.path) for f in catalog if f.path} - blocked):
        path = Path(source)
        name = hashlib.sha256(source.encode()).hexdigest()[:16] + "-" + path.name
        (directory / name).symlink_to(path)
    return dict(options, font_paths=[str(directory)], ignore_system_fonts=True)


def main() -> int:
    import typst

    request = json.load(sys.stdin)
    try:
        with tempfile.TemporaryDirectory(prefix="tbook-fonts-") as tmp:
            options = font_options(typst, request["kwargs"], Path(tmp))
            _, warnings = typst.compile_with_warnings(request["main"], **options)
    except (typst.TypstError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    json.dump([getattr(w, "message", str(w)) for w in warnings or []], sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
