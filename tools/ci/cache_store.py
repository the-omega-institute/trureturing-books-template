"""Transfer complete, verified build-cache entries between CI jobs.

Build jobs snapshot the restored store and upload only added entries. The successful
aggregate merges each shard separately: copying files from two encodings of the same
input-addressed key would corrupt both entries. No command calculates current build
keys or needs the publishing toolchain (in particular, the runner's font families).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import buildcache  # noqa: E402

SNAPSHOT = "tbook-build-store-snapshot-v1"
KEY = re.compile(r"[0-9a-f]{64}\Z")


def candidates(root: Path):
    """Key directories without following links or entering an entry's outputs."""
    root = Path(root)
    if root.is_symlink():
        raise ValueError(f"cache store is a symbolic link: {root}")
    if not root.is_dir():
        return
    for directory, dirs, _ in os.walk(root):
        here = Path(directory)
        if KEY.fullmatch(here.name) and here != root:
            dirs[:] = []
            yield here
        else:
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (here / d).is_symlink())


def valid(entry: Path, root: Path):
    """Metadata of a complete entry, or None; its relative location is its identity."""
    try:
        parts = entry.relative_to(root).parts
        if len(parts) < 3 or not KEY.fullmatch(parts[-1]):
            return None
        if any(p in ("", ".", "..") or "\\" in p for p in parts):
            return None
        # verify() checks files/; also reject links or extra data outside that tree.
        if entry.is_symlink() or {p.name for p in entry.iterdir()} != {buildcache.ENTRY, "files"}:
            return None
        for directory, dirs, files in os.walk(entry):
            for name in [*dirs, *files]:
                mode = (Path(directory) / name).lstat().st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    return None
        data = buildcache.read_entry(entry)
        if not data or (data["target"], data["unit"], data["key"]) != (
                parts[0], "/".join(parts[1:-1]), parts[-1]):
            return None
        if buildcache.verify(entry):
            return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def verified(root: Path):
    for entry in candidates(root):
        data = valid(entry, root)
        if data is not None:
            yield entry, data
        else:
            print(f"cache store: ignoring incomplete or damaged entry {entry}", file=sys.stderr)


def snapshot(root: Path, dest: Path) -> int:
    entries = sorted([d["target"], d["unit"], d["key"]] for _, d in verified(root))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"schema": SNAPSHOT, "entries": entries}) + "\n", encoding="utf-8")
    return len(entries)


def _separate(source: Path, dest: Path) -> None:
    a, b = source.resolve(), dest.resolve()
    if a == b or a in b.parents or b in a.parents:
        raise ValueError("cache transfer source and destination must be separate directories")


def _copy(entry: Path, final: Path) -> None:
    """Publish one whole entry atomically; the first valid encoding of a key wins."""
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
    try:
        shutil.copytree(entry, tmp, dirs_exist_ok=True)
        if buildcache.verify(tmp):
            raise ValueError(f"entry changed during transfer: {entry}")
        buildcache._publish(tmp, final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def export(root: Path, baseline: Path, dest: Path) -> int:
    """Write added entries only, preserving each complete entry's relative path."""
    _separate(root, dest)
    data = json.loads(baseline.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT or not isinstance(data.get("entries"), list):
        raise ValueError("invalid build-cache snapshot")
    before = {tuple(item) for item in data["entries"]}
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    count = 0
    for entry, meta in verified(root):
        if (meta["target"], meta["unit"], meta["key"]) not in before:
            _copy(entry, dest / entry.relative_to(root))
            count += 1
    return count


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def maintain(root: Path) -> int:
    """Keep only verified entries and the newest KEEP keys of each unit, without rebuilding keys."""
    groups = {}
    for entry, data in verified(root):
        groups.setdefault((data["target"], data["unit"]), []).append((entry, data))
    keep = set()
    for entries in groups.values():
        def order(item):
            created = item[1].get("created", 0)
            return (created if isinstance(created, int) else 0, item[1]["key"])
        keep.update(entry for entry, _ in sorted(entries, key=order, reverse=True)[:buildcache.KEEP])
    parents = {p for entry in keep for p in entry.parents if p != root and root in p.parents}

    def clean(directory):
        for item in directory.iterdir():
            if item in keep:
                continue
            if item in parents:
                clean(item)
            else:
                _remove(item)
    if root.is_dir():
        clean(root)
    return len(keep)


def merge(root: Path, sources: list[Path]) -> int:
    """Validate and import shards separately; never overlay the files of the same key."""
    maintain(root)
    for source in sources:
        _separate(source, root)
        for entry, _ in verified(source):
            final = root / entry.relative_to(source)
            if valid(final, root) is None:
                if final.exists() or final.is_symlink():
                    _remove(final)
                _copy(entry, final)
    return maintain(root)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=buildcache.store_root())
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("snapshot")
    p.add_argument("file", type=Path)
    p = sub.add_parser("export")
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("merge")
    p.add_argument("sources", nargs="*", type=Path)
    sub.add_parser("maintain")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            count = snapshot(args.store, args.file)
        elif args.command == "export":
            count = export(args.store, args.baseline, args.out)
        elif args.command == "merge":
            count = merge(args.store, args.sources)
        else:
            count = maintain(args.store)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"cache store: {exc}\n")
    print(f"cache store {args.command}: {count} verified entry(s)")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"entries={count}\n")


if __name__ == "__main__":
    main()
