"""Remove moving href fallbacks only from explicitly lock-bound visualization anchors.

Historical unmarked links, prose and film provenance need editorial review and are left alone.
"""
from pathlib import Path
import json
from tbook import viz


def migrate(root: Path) -> list[str]:
    lock_file = root / "trureturing.lock.json"
    if not lock_file.is_file():
        return ["no lock; nothing to migrate"]
    repo = json.loads(lock_file.read_text(encoding="utf-8"))["repo"]
    notes = []
    for page in sorted((root / "books").glob("*/viz/**/*.html")):
        text = page.read_text(encoding="utf-8")
        def anchor(match):
            tag = match.group(0)
            if viz._attr(tag, "data-lean-gid") is None and viz._attr(tag, "data-trureturing-path") is None:
                return tag
            href = viz._attr(tag, "href") or ""
            if href.startswith(f"https://github.com/{repo}/blob/"):
                return viz._HREF_RE.sub(' href="#"', tag, count=1)
            return tag
        new = viz._A_TAG_RE.sub(anchor, text)
        if new != text:
            page.write_text(new, encoding="utf-8")
            notes.append(f"{page.relative_to(root)}: lock-bound hrefs now resolved at build/preview")
    return notes or ["already migrated"]
