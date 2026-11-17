"""v1.6.0: migrate the aggregate trureturing lock to module shards."""

from __future__ import annotations

from pathlib import Path


def migrate(root: Path) -> list[str]:
    """Convert the old lock once; a pointer or no lock is already migrated."""
    from tbook import lean, paths

    legacy = root / "trureturing.lock.json"
    if not legacy.is_file():
        return ["trureturing lock: nothing to migrate"]
    try:
        pointer = __import__("json").loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pointer = None
    if isinstance(pointer, dict) and pointer.get("schema") == lean.LOCK_POINTER_SCHEMA:
        return ["trureturing lock: already sharded"]
    lock = lean.Lock.load(legacy)
    if lock is None:
        return ["trureturing lock: nothing to migrate"]
    # Lock.save() resolves the directory from paths.LOCK_FILE. The migration
    # runs in a fresh process, so temporarily pointing it at this repository is
    # sufficient and leaves no process-global state for the caller.
    paths.LOCK_FILE = legacy
    lock.save()
    return [f"trureturing lock: split {len(lock.declarations)} declarations into trureturing-lock/"]
