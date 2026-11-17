"""Well-known locations inside a books repository."""

from __future__ import annotations

import os
from pathlib import Path

# tools/tbook/paths.py -> repository root
ROOT = Path(os.environ.get("TBOOK_ROOT") or Path(__file__).resolve().parents[2])

TOOLS = ROOT / "tools"
THEME = ROOT / "theme"
TEMPLATES = ROOT / "templates"
BOOKS = ROOT / "books"
BUILD = ROOT / "build"
SITE_OUT = ROOT / "_site"
CACHE = ROOT / ".cache"

SITE_TOML = ROOT / "site.toml"
TEMPLATE_TOML = ROOT / "template.toml"
# The pointer is intentionally tiny and stable.  Declaration evidence lives in the
# sharded directory below so independent book changes do not rewrite one large JSON
# document.
LOCK_FILE = ROOT / "trureturing.lock.json"
LOCK_DIR = ROOT / "trureturing-lock"
LOCK_INDEX = LOCK_DIR / "index.json"
TOKENS = THEME / "tokens.json"
GENERATED = THEME / "generated"
I18N_THEME = THEME / "i18n"
I18N_LOCAL = ROOT / "i18n"


def rel(path: Path) -> str:
    """Repository-relative POSIX path for messages."""
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def lock_dir() -> Path:
    """The sharded lock directory, derived from the patchable legacy pointer path."""
    return LOCK_FILE.parent / "trureturing-lock"


def lock_index() -> Path:
    return lock_dir() / "index.json"
