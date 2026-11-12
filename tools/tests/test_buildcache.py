"""The build cache (tools/tbook/buildcache.py): keys, the local store, restores from releases, ./tbook cache,
and a second ``./tbook build html pdf epub`` of the example book that restores every unit."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import socket
import tempfile
import textwrap
import threading
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tbook import buildcache, config, paths

REAL_ROOT = paths.ROOT
MDBOOK = os.environ.get("MDBOOK") or shutil.which("mdbook")
NODE = shutil.which("node")
CACHE_ENV = ("TBOOK_CACHE", "TBOOK_CACHE_REMOTE", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_API_URL", "TBOOK_ROOT",
             "TBOOK_REPO", "TBOOK_BASE_URL", "GITHUB_REPOSITORY", "SOURCE_DATE_EPOCH", "GITHUB_EVENT_NAME")


def write(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "init.defaultBranch=main",
                    *args], cwd=root, check=True, capture_output=True)


def tree(path: Path) -> dict[str, str]:
    """{relative path: 'dir' or SHA-256} of everything under ``path`` (a file: {'': SHA-256})."""
    path = Path(path)
    if path.is_file():
        return {"": hashlib.sha256(path.read_bytes()).hexdigest()}
    out = {}
    for p in sorted(path.rglob("*")):
        out[p.relative_to(path).as_posix()] = "dir" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class Scratch:
    """A throwaway repository root: ``tbook.paths`` points into it and the cache's environment is clean."""

    def __init__(self, *, git_repo: bool = False, sub: str = ""):
        self._tmp = tempfile.TemporaryDirectory(prefix="tbook-cache-")
        self.top = Path(self._tmp.name)
        self.root = self.top / sub if sub else self.top
        self.root.mkdir(parents=True, exist_ok=True)
        if git_repo:
            git(self.top, "init", "-q")

    def __enter__(self) -> "Scratch":
        self.stack = ExitStack()
        r = self.root
        for name, value in dict(ROOT=r, BOOKS=r / "books", BUILD=r / "build", SITE_OUT=r / "_site", CACHE=r / ".cache",
                                TOOLS=r / "tools", THEME=r / "theme", SITE_TOML=r / "site.toml",
                                LOCK_FILE=r / "trureturing.lock.json", I18N_LOCAL=r / "i18n").items():
            self.stack.enter_context(mock.patch.object(paths, name, value))
        self.stack.enter_context(mock.patch.dict(os.environ))
        for key in CACHE_ENV:
            os.environ.pop(key, None)
        buildcache._clear_memos()
        self.stack.callback(buildcache._clear_memos)
        return self

    def __exit__(self, *exc) -> None:
        self.stack.close()
        self._tmp.cleanup()

    def unit(self, name: str = "demo/zh", *, target: str = "html", sources: str = "src",
             outputs: tuple[str, ...] = ("build/out/site", "build/out/book.pdf")) -> buildcache.Unit:
        inputs = buildcache.Inputs().files(self.root / sources).text("setting", "a")
        return buildcache.Unit(target, name, inputs, [self.root / o for o in outputs])


class Builder:
    """A build function that writes a directory output (with an empty directory) and a file output."""

    def __init__(self, unit: buildcache.Unit, tag: str = "v1"):
        self.unit, self.tag, self.calls = unit, tag, 0

    def __call__(self) -> None:
        self.calls += 1
        site, pdf = self.unit.outputs
        if site.exists():
            shutil.rmtree(site)
        write(site / "index.html", f"<p>{self.tag}</p>")
        write(site / "css" / "a.css", "body{}")
        (site / "empty").mkdir()
        write(pdf, f"%PDF {self.tag}".encode())


def quiet(fn, *args, **kwargs):
    """(result, stdout) of ``fn``."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


# --------------------------------------------------------------------------- keys


class KeyTests(unittest.TestCase):
    def test_key_follows_the_files_git_would_commit(self):
        with Scratch(git_repo=True) as s:
            write(s.root / ".gitignore", "/src/ignored/\n*.log\n")
            write(s.root / "src" / "a.md", "one")
            write(s.root / "src" / "ignored" / "x.md", "x")
            write(s.root / "src" / "b.log", "log")
            git(s.root, "add", "-A")
            git(s.root, "commit", "-qm", "init")
            k1 = s.unit().key
            self.assertEqual(s.unit().key, k1, "the key is stable")
            write(s.root / "src" / "ignored" / "x.md", "changed, ignored")
            write(s.root / "src" / "b.log", "more log")
            buildcache._clear_memos()
            self.assertEqual(s.unit().key, k1, "ignored files are not inputs")
            write(s.root / "src" / "a.md", "two!!")
            k2 = s.unit().key
            self.assertNotEqual(k2, k1, "a changed source changes the key")
            write(s.root / "src" / "new.md", "untracked but not ignored")
            buildcache._clear_memos()
            k3 = s.unit().key
            self.assertNotEqual(k3, k2, "a new file git would commit is an input")
            (s.root / "src" / "new.md").unlink()
            buildcache._clear_memos()
            self.assertEqual(s.unit().key, k2, "the same files give the same key again")

    def test_root_in_a_subdirectory_of_the_work_tree(self):
        """git ls-files prints paths relative to the directory it runs in: ROOT may be below the top."""
        with Scratch(git_repo=True, sub="books-repo") as s:
            write(s.root / "src" / "a.md", "one")
            files = buildcache._files_under(s.root / "src")
            self.assertEqual([label for _, label in files], ["src/a.md"])
            k1 = s.unit().key
            write(s.root / "src" / "a.md", "two!")
            self.assertNotEqual(s.unit().key, k1)

    def test_without_git_build_outputs_do_not_count(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "one")
            k1 = s.unit().key
            for skipped in ("build/x.html", "node_modules/m.js", "__pycache__/a.pyc", "out/v.mp4", ".cache/c"):
                write(s.root / "src" / skipped, "generated")
            self.assertEqual(s.unit().key, k1)
            write(s.root / "src" / "sub" / "b.md", "b")
            self.assertNotEqual(s.unit().key, k1)

    def test_a_directory_git_ignores_counts_in_full(self):
        """.cache/fonts (tools/fetch-fonts.sh) is ignored by git but its fonts shape the PDF."""
        with Scratch(git_repo=True) as s:
            write(s.root / ".gitignore", "/.cache/\n")
            write(s.root / ".cache" / "fonts" / "A.ttf", b"font-a")
            labels = [label for _, label in buildcache._files_under(s.root / ".cache" / "fonts")]
            self.assertEqual(labels, [".cache/fonts/A.ttf"])
            k1 = buildcache.Inputs().files(s.root / ".cache" / "fonts").key()
            write(s.root / ".cache" / "fonts" / "A.ttf", b"font-a2")
            self.assertNotEqual(buildcache.Inputs().files(s.root / ".cache" / "fonts").key(), k1)
            self.assertEqual(buildcache.Inputs().files(s.root / ".cache" / "none").parts, [(".cache/none", "missing")])

    def test_files_outside_the_root_do_not_depend_on_their_location(self):
        with Scratch() as s, tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for d in (a, b):
                write(Path(d) / "models" / "voice.bin", b"weights")
                write(Path(d) / "models" / "sub" / "cfg.json", "{}")
            ka = buildcache.Inputs().files(Path(a) / "models").key()
            kb = buildcache.Inputs().files(Path(b) / "models").key()
            self.assertEqual(ka, kb)
            labels = [p[0] for p in buildcache.Inputs().files(Path(a) / "models").parts]
            self.assertEqual(labels, ["<outside>/models/sub/cfg.json", "<outside>/models/voice.bin"])
            self.assertFalse(any(a in label for label in labels))
            write(Path(b) / "models" / "voice.bin", b"other weights")
            self.assertNotEqual(buildcache.Inputs().files(Path(b) / "models").key(), ka)
            write(Path(a) / "one.bin", b"1")
            self.assertEqual(buildcache.Inputs().files(Path(a) / "one.bin").parts[0][0], "<outside>/one.bin")
            self.assertTrue(s.root.is_dir())

    def test_file_and_directory_items_exclude_and_text(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            write(s.root / "src" / "out" / "v.txt", "v")
            write(s.root / "src" / "keep" / "out.md", "k")
            inputs = buildcache.Inputs().files(s.root / "src" / "a.md", s.root / "src", s.root / "gone",
                                               exclude=("/keep/",))
            labels = [p[0] for p in inputs.parts]
            self.assertEqual(labels, ["src/a.md", "src/a.md", "gone"])
            self.assertEqual(inputs.parts[-1][1], "missing")
            self.assertNotEqual(buildcache.Inputs().text("x", 1).key(), buildcache.Inputs().text("x", "1").key())
            self.assertEqual(buildcache.Inputs().text("x", {"b": 1, "a": 2}).key(),
                             buildcache.Inputs().text("x", {"a": 2, "b": 1}).key())

    def test_labels_are_unambiguous(self):
        a = buildcache.Inputs([("a\tb", "c")]).key()
        b = buildcache.Inputs([("a", "b\tc")]).key()
        self.assertNotEqual(a, b)

    def test_tools_count_by_release_series(self):
        self.assertEqual(buildcache.series("v22.23.4", 1), "22")
        self.assertEqual(buildcache.series("pandoc 3.1.11.1"), "3.1")
        self.assertEqual(buildcache.series("mdbook v0.5.4"), "0.5")
        self.assertEqual(buildcache.series("0.15.2"), "0.15")
        self.assertEqual(buildcache.series("missing"), "missing")
        # a new Node patch release keeps every key; a new major version changes them
        buildcache.tool_version.cache_clear()
        self.addCleanup(buildcache.tool_version.cache_clear)
        with mock.patch.object(buildcache, "tool_version", side_effect=["v22.1.0", "v22.9.9", "v24.0.0"]):
            self.assertEqual(buildcache.node_version(), "22")
            self.assertEqual(buildcache.node_version(), "22")
            self.assertEqual(buildcache.node_version(), "24")

    def test_unit_key_depends_on_target_and_name(self):
        inputs = buildcache.Inputs().text("x", "same")
        keys = {buildcache.Unit(t, n, inputs, []).key for t, n in (("pdf", "b/zh/screen"), ("pdf", "b/zh/print"),
                                                                    ("epub", "b/zh/screen"))}
        self.assertEqual(len(keys), 3)

    def test_unsafe_unit_names_are_refused(self):
        for name in ("../x", "a//b", "", "a/./b"):
            with self.assertRaises(ValueError, msg=name):
                buildcache.Unit("html", name, buildcache.Inputs(), []).entry_dir()

    def test_an_epub_check_that_cannot_run_keys_apart(self):
        """An EPUB whose epubcheck was skipped (no Java, no epubcheck package) is not restored into a build
        that checks."""
        with Scratch():
            with mock.patch.object(buildcache.shutil, "which", return_value="/usr/bin/java"), \
                    mock.patch("importlib.util.find_spec", return_value=object()):
                checked = buildcache._epubcheck_mode()
            with mock.patch.object(buildcache.shutil, "which", return_value=None):
                no_java = buildcache._epubcheck_mode()
            with mock.patch.object(buildcache.shutil, "which", return_value="/usr/bin/java"), \
                    mock.patch("importlib.util.find_spec", return_value=None):
                no_package = buildcache._epubcheck_mode()
            os.environ["TBOOK_EPUBCHECK"] = "0"
            with mock.patch.object(buildcache.shutil, "which", return_value=None):
                off = buildcache._epubcheck_mode()
        self.assertEqual(checked, "1")
        self.assertEqual(len({checked, no_java, no_package, off}), 4)
        self.assertEqual(off, "off")

    def test_book_units_do_not_depend_on_the_film_pipeline(self):
        with Scratch() as s:
            write(s.root / "theme" / "mdbook" / "book.css", "a")
            write(s.root / "theme" / "film" / "render.js", "1")
            site = SimpleNamespace(repo="o/r", base_url="https://o.github.io/r/")
            k1 = buildcache.site_inputs(site).key()
            write(s.root / "theme" / "film" / "render.js", "2")
            self.assertEqual(buildcache.site_inputs(site).key(), k1)
            write(s.root / "theme" / "mdbook" / "book.css", "b")
            self.assertNotEqual(buildcache.site_inputs(site).key(), k1)


# --------------------------------------------------------------------------- the local store


class StoreTests(unittest.TestCase):
    def test_an_unreadable_entry_is_a_miss_and_is_kept(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            unit = s.unit()
            quiet(buildcache.run, unit, Builder(unit))
            entry = unit.entry_dir()
            with mock.patch.object(buildcache, "verify", side_effect=PermissionError(13, "Permission denied")):
                builder = Builder(unit)
                result, out = quiet(buildcache.run, unit, builder)
            self.assertEqual((result, builder.calls), ("built", 1))
            self.assertIn(f"cannot read the stored {unit.label}", out)
            self.assertTrue(entry.is_dir(), "an entry that could not be read is not deleted")

    def test_a_name_the_entry_cannot_record_does_not_fail_the_build(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            unit = s.unit()
            builder = Builder(unit)
            with mock.patch.object(buildcache, "store", side_effect=UnicodeEncodeError("utf-8", "x", 0, 1, "bad")):
                result, out = quiet(buildcache.run, unit, builder)
            self.assertEqual((result, builder.calls), ("built", 1))
            self.assertIn(f"cannot store {unit.label}", out)

    @unittest.skipIf(sys.platform == "darwin", "macOS file systems refuse names that are not UTF-8")
    def test_non_utf8_file_names_are_stored_and_restored(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            unit = s.unit(outputs=("build/out/site",))

            def build():
                site = unit.outputs[0]
                site.mkdir(parents=True, exist_ok=True)
                with open(os.fsencode(site) + b"/caf\xe9.txt", "wb") as f:
                    f.write(b"x")

            try:
                result, out = quiet(buildcache.run, unit, build)
            except OSError as exc:  # a file system that refuses the name altogether
                self.skipTest(str(exc))
            self.assertEqual(result, "built", out)
            self.assertNotIn("cannot store", out)
            shutil.rmtree(s.root / "build")
            self.assertEqual(quiet(buildcache.run, unit, build)[0], "cached")
            self.assertTrue(os.path.exists(os.fsencode(unit.outputs[0]) + b"/caf\xe9.txt"))

    def test_built_once_then_restored_with_the_same_shape(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            unit = s.unit()
            build = Builder(unit)
            self.assertEqual(quiet(buildcache.run, unit, build)[0], "built")
            fresh = [tree(o) for o in unit.outputs]
            self.assertIn("empty", fresh[0])
            entry = unit.entry_dir()
            data = json.loads((entry / "entry.json").read_text(encoding="utf-8"))
            self.assertEqual([o["path"] for o in data["outputs"]], ["build/out/site", "build/out/book.pdf"])
            self.assertEqual([o["kind"] for o in data["outputs"]], ["dir", "file"])
            # outputs changed shape since: the PDF path is a directory, the site a file, stale files around
            shutil.rmtree(unit.outputs[0])
            write(unit.outputs[0], "not a directory")
            unit.outputs[1].unlink()
            write(unit.outputs[1] / "junk", "x")
            result, out = quiet(buildcache.run, s.unit(), build)
            self.assertEqual(result, "cached")
            self.assertIn("is up to date", out)
            self.assertEqual(build.calls, 1)
            self.assertEqual([tree(o) for o in unit.outputs], fresh)
            self.assertEqual(sorted(p.name for p in unit.outputs[0].parent.iterdir()), ["book.pdf", "site"],
                             "no temporary files are left next to the outputs")

    def test_a_changed_input_builds_again(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            build = Builder(s.unit())
            quiet(buildcache.run, s.unit(), build)
            write(s.root / "src" / "a.md", "changed")
            build.tag = "v2"
            self.assertEqual(quiet(buildcache.run, s.unit(), build)[0], "built")
            self.assertEqual(build.calls, 2)
            self.assertEqual(s.unit().outputs[1].read_bytes(), b"%PDF v2")

    def test_damaged_entries_are_dropped_and_built(self):
        damage = {
            "changed byte": lambda e: write(e / "files" / "1", b"%PDF v9"),
            "extra file": lambda e: write(e / "files" / "0" / "extra.html", "x"),
            "missing file": lambda e: (e / "files" / "0" / "index.html").unlink(),
            "missing empty dir": lambda e: (e / "files" / "0" / "empty").rmdir(),
            "link": lambda e: (e / "files" / "0" / "css" / "a.css").unlink() or os.symlink(
                "/etc/hostname", e / "files" / "0" / "css" / "a.css"),
            "entry.json": lambda e: write(e / "entry.json", "{"),
            "kind": lambda e: (e / "files" / "1").unlink() or (e / "files" / "1").mkdir(),
        }
        for what, spoil in damage.items():
            with self.subTest(what), Scratch() as s:
                write(s.root / "src" / "a.md", "a")
                build = Builder(s.unit())
                quiet(buildcache.run, s.unit(), build)
                spoil(s.unit().entry_dir())
                result, out = quiet(buildcache.run, s.unit(), build)
                self.assertEqual((result, build.calls), ("built", 2), out)
                self.assertIn("dropping the stored html demo/zh", out)
                self.assertEqual(buildcache.verify(s.unit().entry_dir()), "", "stored again")

    def test_entry_for_other_output_paths_is_not_restored(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            build = Builder(s.unit())
            quiet(buildcache.run, s.unit(), build)
            moved = s.unit(outputs=("build/elsewhere/site", "build/elsewhere/book.pdf"))
            result, out = quiet(buildcache.run, moved, Builder(moved))
            self.assertEqual(result, "built")
            self.assertIn("other output paths", out)

    def test_keeps_the_newest_entries(self):
        with Scratch() as s:
            keys = []
            for i in range(4):
                write(s.root / "src" / "a.md", "v" + "x" * i)  # sizes differ: no memoized digest is reused
                unit = s.unit()
                keys.append(unit.key)
                quiet(buildcache.run, unit, Builder(unit))
                time.sleep(0.03)
            stored = {k for _, _, k, _ in buildcache.stored()}
            self.assertEqual(stored, set(keys[-buildcache.KEEP:]))
            # a restore makes an entry the newest again
            write(s.root / "src" / "a.md", "vxx")
            self.assertEqual(quiet(buildcache.run, s.unit(), Builder(s.unit()))[0], "cached")
            time.sleep(0.03)
            write(s.root / "src" / "a.md", "v" + "x" * 9)
            quiet(buildcache.run, s.unit(), Builder(s.unit()))
            self.assertEqual({k for _, _, k, _ in buildcache.stored()}, {keys[2], s.unit().key})

    def test_prune_keeps_only_current_keys(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "o")
            old = s.unit()
            quiet(buildcache.run, old, Builder(old))
            gone = s.unit("other/zh")
            quiet(buildcache.run, gone, Builder(gone))
            write(s.root / "src" / "a.md", "new")
            current = s.unit()
            quiet(buildcache.run, current, Builder(current))
            stale_tmp = current.entry_dir().parent / ".tmp-interrupted"
            fresh_tmp = current.entry_dir().parent / ".tmp-running"
            stale_tmp.mkdir()
            fresh_tmp.mkdir()
            long_ago = time.time() - 2 * buildcache.STALE_TMP
            os.utime(stale_tmp, (long_ago, long_ago))
            broken = current.entry_dir("f" * 64)
            write(broken / "entry.json", "not json")
            removed = buildcache.prune([current])
            self.assertEqual(sorted(removed), sorted([old.entry_dir(), gone.entry_dir(), broken]))
            self.assertEqual([(t, n, k) for t, n, k, _ in buildcache.stored()], [("html", "demo/zh", current.key)])
            self.assertFalse(stale_tmp.exists())
            self.assertTrue(fresh_tmp.exists(), "a temporary directory of a running build stays")
            self.assertFalse((buildcache.store_root() / "html" / "other").exists(), "empty directories go")
            self.assertEqual(tree(current.entry_dir() / "files" / "0"), tree(current.outputs[0]))

    def test_actions_key(self):
        with Scratch() as s:
            empty = buildcache.actions_key()
            write(s.root / "src" / "a.md", "a")
            quiet(buildcache.run, s.unit(), Builder(s.unit()))
            k1 = buildcache.actions_key()
            self.assertNotEqual(k1, empty)
            self.assertTrue(k1.startswith("build-cache-v1-"))
            quiet(buildcache.run, s.unit(), Builder(s.unit()))  # a restore
            self.assertEqual(buildcache.actions_key(), k1)
            write(s.root / "src" / "a.md", "b")
            quiet(buildcache.run, s.unit(), Builder(s.unit()))
            self.assertNotEqual(buildcache.actions_key(), k1)

    def test_disabled(self):
        with Scratch() as s:
            os.environ["TBOOK_CACHE"] = "0"
            write(s.root / "src" / "a.md", "a")
            build = Builder(s.unit())
            self.assertEqual([quiet(buildcache.run, s.unit(), build)[0] for _ in range(2)], ["built", "built"])
            self.assertEqual(build.calls, 2)
            self.assertFalse(buildcache.store_root().exists())
            self.assertEqual(buildcache.run(s.unit(), None), "missing")

    def test_restore_only(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            self.assertEqual(buildcache.run(s.unit(), None), "missing")
            self.assertFalse(s.unit().outputs[1].exists())
            quiet(buildcache.run, s.unit(), Builder(s.unit()))
            shutil.rmtree(s.root / "build")
            self.assertEqual(quiet(buildcache.run, s.unit(), None)[0], "cached")
            self.assertTrue(s.unit().outputs[1].is_file())

    def test_failed_or_incomplete_builds_store_nothing(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")

            def fail():
                raise RuntimeError("compiler error")

            with self.assertRaises(RuntimeError):
                buildcache.run(s.unit(), fail)
            with self.assertRaisesRegex(buildcache.MissingOutput, "did not write build/out/site"):
                buildcache.run(s.unit(), lambda: None)
            self.assertEqual(buildcache.stored(), [])
            self.assertEqual(list(s.unit().entry_dir().parent.iterdir()), [], "no temporary directory is left")

    def test_a_store_that_fails_does_not_fail_the_build(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            with mock.patch.object(buildcache.shutil, "copy2", side_effect=OSError(28, "No space left on device")):
                result, out = quiet(buildcache.run, s.unit(), Builder(s.unit()))
            self.assertEqual(result, "built")
            self.assertIn("cannot store html demo/zh", out)
            self.assertEqual(buildcache.stored(), [])

    def test_storing_an_existing_key_keeps_a_valid_entry_and_replaces_a_damaged_one(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            unit = s.unit()
            Builder(unit)()
            entry = buildcache.store(unit)
            created = json.loads((entry / "entry.json").read_text(encoding="utf-8"))["created"]
            Builder(unit, "other bytes, same inputs")()
            buildcache.store(unit)  # a concurrent build of the same inputs: the first entry stays
            self.assertEqual(json.loads((entry / "entry.json").read_text(encoding="utf-8"))["created"], created)
            self.assertEqual((entry / "files" / "1").read_bytes(), b"%PDF v1")
            write(entry / "files" / "1", b"damaged")
            buildcache.store(unit)
            self.assertEqual((entry / "files" / "1").read_bytes(), b"%PDF other bytes, same inputs")
            self.assertEqual(buildcache.verify(entry), "")
            self.assertEqual([p.name for p in entry.parent.iterdir()], [entry.name])

    def test_restore_that_cannot_copy_builds(self):
        with Scratch() as s:
            write(s.root / "src" / "a.md", "a")
            build = Builder(s.unit())
            quiet(buildcache.run, s.unit(), build)
            with mock.patch.object(buildcache, "_place", side_effect=OSError(13, "Permission denied")):
                result, out = quiet(buildcache.run, s.unit(), build)
            self.assertEqual((result, build.calls), ("built", 2))
            self.assertIn("cannot restore html demo/zh", out)


# --------------------------------------------------------------------------- releases


class FakeGitHub:
    """Two local HTTP servers: the API (releases, asset API URLs that redirect) and the download host."""

    def __init__(self):
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.api = self._serve("api")
        self.dl = self._serve("dl")

    def _serve(self, name: str):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                fake.requests.append((name, self.path, dict(self.headers)))
                status, headers, body = fake.routes.get(f"{name}{self.path}", (404, {}, b"{}"))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return server

    def url(self, server) -> str:
        return f"http://127.0.0.1:{server.server_address[1]}"

    def close(self) -> None:
        for server in (self.api, self.dl):
            server.shutdown()
            server.server_close()

    def release(self, repo: str, releases: list[tuple[str, bool, dict[str, bytes]]], *, digests: dict | None = None):
        """Serve ``releases`` [(tag, draft, {asset name: bytes})], newest first, for ``repo``."""
        listing, n = [], 0
        for tag, draft, assets in releases:
            entries = []
            for name, data in assets.items():
                n += 1
                api_path = f"/repos/{repo}/releases/assets/{n}"
                dl_path = f"/download/{tag}/{name}"
                self.routes[f"api{api_path}"] = (302, {"Location": self.url(self.dl) + dl_path}, b"")
                self.routes[f"dl{dl_path}"] = (200, {"Content-Type": "application/octet-stream"}, data)
                digest = (digests or {}).get(name, "sha256:" + hashlib.sha256(data).hexdigest())
                entries.append({"name": name, "url": self.url(self.api) + api_path, "size": len(data),
                                "browser_download_url": self.url(self.dl) + dl_path, "digest": digest})
            listing.append({"tag_name": tag, "draft": draft, "assets": entries})
        self.routes[f"api/repos/{repo}/releases?per_page=100"] = (200, {}, json.dumps(listing).encode())


def tar_bytes(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return buf.getvalue()


def member(name: str, kind: bytes = tarfile.REGTYPE, data: bytes | None = b"x", **attrs) -> tuple:
    info = tarfile.TarInfo(name)
    info.type = kind
    for k, v in attrs.items():
        setattr(info, k, v)
    return info, (data if kind == tarfile.REGTYPE else None)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.addCleanup(self.gh.close)
        self.scratch = Scratch()
        self.s = self.scratch.__enter__()
        self.addCleanup(self.scratch.__exit__, None, None, None)
        os.environ.update(GITHUB_API_URL=self.gh.url(self.gh.api), TBOOK_CACHE_REMOTE="1",
                          NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        write(self.s.root / "src" / "a.md", "a")
        self.units = [self.s.unit("demo/zh"), self.s.unit("demo/en", outputs=("build/en/site", "build/en/book.pdf"))]
        for unit in self.units:
            quiet(buildcache.run, unit, Builder(unit))
        self.fresh = {u.name: [tree(o) for o in u.outputs] for u in self.units}
        self.exported = Path(tempfile.mkdtemp(prefix="tbook-export-"))
        self.addCleanup(shutil.rmtree, self.exported, True)
        manifest = buildcache.export(self.exported, self.units, repo="o/r")
        self.assets = {p.name: p.read_bytes() for p in self.exported.iterdir()}
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        self.forget()

    def forget(self):
        """A new checkout: no store, no outputs, nothing memoized."""
        shutil.rmtree(self.s.root / ".cache", ignore_errors=True)
        shutil.rmtree(self.s.root / "build", ignore_errors=True)
        buildcache._clear_memos()

    def build_all(self, **kwargs) -> tuple[list[str], list[Builder], str]:
        builders = [Builder(u) for u in self.units]
        results, out = [], ""
        for unit, builder in zip(self.units, builders):
            r, o = quiet(buildcache.run, unit, builder, **kwargs)
            results.append(r)
            out += o
        return results, builders, out

    def test_export(self):
        names = sorted(e["asset"] for e in self.manifest["entries"])
        self.assertEqual(sorted(self.assets), sorted(names + ["build-cache.json"]))
        self.assertEqual(self.manifest["repo"], "o/r")
        for e in self.manifest["entries"]:
            self.assertEqual(e["sha256"], hashlib.sha256(self.assets[e["asset"]]).hexdigest())
            self.assertEqual(e["size"], len(self.assets[e["asset"]]))
            self.assertEqual(e["asset"], buildcache.asset_name(e["target"], e["unit"], e["key"]))
            with tarfile.open(fileobj=io.BytesIO(self.assets[e["asset"]])) as tar:
                kinds = {m.name: (m.isdir(), m.mtime, m.uid, m.uname) for m in tar.getmembers()}
            self.assertIn("files/0/empty", kinds)
            self.assertEqual({(m, u, n) for _, m, u, n in kinds.values()}, {(0, 0, "")})
        # the same store exports to the same bytes
        self.build_all()
        first, again = (Path(tempfile.mkdtemp(prefix="tbook-export-")) for _ in range(2))
        for d in (first, again):
            self.addCleanup(shutil.rmtree, d, True)
            buildcache.export(d, self.units)
        names = sorted(p.name for p in first.iterdir() if p.suffix == ".tar")
        self.assertEqual(len(names), 2)
        self.assertEqual(names, sorted(p.name for p in again.iterdir() if p.suffix == ".tar"))
        for name in names:
            self.assertEqual((first / name).read_bytes(), (again / name).read_bytes(), "exports are reproducible")
        # a unit that is not stored is left out and named
        shutil.rmtree(self.units[1].entry_dir())
        manifest, out = quiet(buildcache.export, again, self.units)
        self.assertIn("html demo/en is not in the store (not stored)", out)
        self.assertEqual([e["unit"] for e in json.loads(manifest.read_text())["entries"]], ["demo/zh"])

    def test_restore_from_a_release_with_a_token(self):
        os.environ["GITHUB_TOKEN"] = "secret-token"
        self.gh.release("o/r", [("v-draft", True, {}), ("v1", False, self.assets)])
        results, builders, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["release", "release"], out)
        self.assertEqual([b.calls for b in builders], [0, 0])
        self.assertIn("cache: html demo/zh restored from release v1", out)
        self.assertEqual({u.name: [tree(o) for o in u.outputs] for u in self.units}, self.fresh)
        api_assets = [h for srv, path, h in self.gh.requests if srv == "api" and "/assets/" in path]
        downloads = [h for srv, path, h in self.gh.requests if srv == "dl"]
        self.assertTrue(api_assets and downloads)
        self.assertTrue(all(h.get("Authorization") == "Bearer secret-token" for h in api_assets))
        self.assertFalse(any("Authorization" in h for h in downloads), "the token does not follow the redirect")
        listings = [p for srv, p, _ in self.gh.requests if "per_page" in p]
        self.assertEqual(len(listings), 1, "the releases are listed once per process")
        # the entries are in the local store now
        self.forget_outputs_only()
        self.assertEqual(self.build_all(repo="o/r")[0], ["cached", "cached"])

    def forget_outputs_only(self):
        shutil.rmtree(self.s.root / "build")

    def test_restore_without_a_token_uses_the_public_url(self):
        self.gh.release("o/r", [("v1", False, self.assets)])
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["release", "release"], out)
        self.assertFalse(any(srv == "api" and "/assets/" in path for srv, path, _ in self.gh.requests))
        self.assertFalse(any("Authorization" in h for _, _, h in self.gh.requests))

    def test_repository_from_the_site(self):
        os.environ["TBOOK_REPO"] = "o/r"
        write(self.s.root / "site.toml", "[site]\nlanguages = ['zh']\n")
        config.load_site.cache_clear()
        self.addCleanup(config.load_site.cache_clear)
        self.gh.release("o/r", [("v1", False, self.assets)])
        self.assertEqual(self.build_all()[0], ["release", "release"])

    def test_drafts_are_ignored(self):
        self.gh.release("o/r", [("v-draft", True, self.assets)])
        results, builders, _ = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertFalse(any("/download/" in p for _, p, _ in self.gh.requests))

    def test_newest_release_first_and_older_ones_searched(self):
        zh = next(e for e in self.manifest["entries"] if e["unit"] == "demo/zh")
        only_zh = {"build-cache.json": json.dumps({**self.manifest, "entries": [zh]}).encode(),
                   zh["asset"]: self.assets[zh["asset"]]}
        self.gh.release("o/r", [("v2", False, only_zh), ("v1", False, self.assets)])
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["release", "release"])
        self.assertIn("demo/zh restored from release v2", out)
        self.assertIn("demo/en restored from release v1", out)

    def test_releases_without_a_manifest_do_not_count(self):
        # releases made by hand (no build-cache.json) do not push the site's release out of the window
        manual = [(f"manual-{i}", False, {"video.mp4": b"mp4"}) for i in range(buildcache.REMOTE_RELEASES + 2)]
        self.gh.release("o/r", manual + [("v1", False, self.assets)])
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["release", "release"], out)
        self.assertIn("restored from release v1", out)

    def test_says_once_when_no_release_has_a_manifest(self):
        self.gh.release("o/r", [("manual", False, {"video.mp4": b"mp4"})])
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertEqual(out.count("no published release of o/r carries build-cache.json"), 1, out)

    def test_digest_mismatches_are_refused(self):
        zh = next(e for e in self.manifest["entries"] if e["unit"] == "demo/zh")
        en = next(e for e in self.manifest["entries"] if e["unit"] == "demo/en")
        tampered = dict(self.assets)
        tampered[zh["asset"]] = self.assets[zh["asset"]][:-1] + b"!"  # does not match build-cache.json
        self.gh.release("o/r", [("v1", False, tampered)],
                        digests={en["asset"]: "sha256:" + "0" * 64})  # GitHub reports another digest
        results, builders, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertEqual(out.count("does not match its digest"), 2, out)
        self.assertEqual(buildcache.verify(self.units[0].entry_dir()), "", "built and stored")

    def test_assets_larger_than_declared_are_refused(self):
        zh = next(e for e in self.manifest["entries"] if e["unit"] == "demo/zh")
        small = {**self.manifest, "entries": [{**zh, "size": 10}]}
        self.gh.release("o/r", [("v1", False, {**self.assets, "build-cache.json": json.dumps(small).encode()})])
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertIn("larger than the 10 bytes declared", out)

    def test_unsafe_tars_are_refused(self):
        zh = next(e for e in self.manifest["entries"] if e["unit"] == "demo/zh")
        with tarfile.open(fileobj=io.BytesIO(self.assets[zh["asset"]])) as tar:
            good = [(m, tar.extractfile(m).read() if m.isreg() else None) for m in tar.getmembers()]
        outside = self.s.root / "pwned"
        bad_members = {
            "symlink": member("files/0/link", tarfile.SYMTYPE, linkname="/etc/passwd"),
            "hard link": member("files/0/hard", tarfile.LNKTYPE, linkname="entry.json"),
            "parent": member("files/../../pwned", data=b"x"),
            "absolute": member(str(outside), data=b"x"),
            "device": member("files/0/dev", tarfile.CHRTYPE),
            "fifo": member("files/0/fifo", tarfile.FIFOTYPE),
            "outside files/": member("other.txt", data=b"x"),
            "duplicate": member("entry.json", data=b"{}"),
        }
        for what, bad in bad_members.items():
            with self.subTest(what):
                self.forget()
                data = tar_bytes(good + [bad])
                manifest = {**self.manifest, "entries": [{**zh, "sha256": hashlib.sha256(data).hexdigest(),
                                                          "size": len(data)}]}
                self.gh.routes.clear()
                self.gh.release("o/r", [("v1", False, {"build-cache.json": json.dumps(manifest).encode(),
                                                      zh["asset"]: data})])
                result, out = quiet(buildcache.run, self.units[0], Builder(self.units[0]), repo="o/r")
                self.assertEqual(result, "built", out)
                self.assertIn("unsafe member", out)
                self.assertFalse(outside.exists())
                self.assertEqual(buildcache.verify(self.units[0].entry_dir()), "")

    def test_an_entry_of_another_unit_is_refused(self):
        zh = next(e for e in self.manifest["entries"] if e["unit"] == "demo/zh")
        en = next(e for e in self.manifest["entries"] if e["unit"] == "demo/en")
        swapped = {**self.manifest, "entries": [{**zh, "asset": en["asset"], "sha256": en["sha256"],
                                                 "size": en["size"]}]}
        self.gh.release("o/r", [("v1", False, {**self.assets, "build-cache.json": json.dumps(swapped).encode()})])
        result, out = quiet(buildcache.run, self.units[0], Builder(self.units[0]), repo="o/r")
        self.assertEqual(result, "built")
        self.assertIn("not the entry it claims", out)

    def test_http_errors_and_rate_limits_fall_back_to_building(self):
        self.gh.routes["api/repos/o/r/releases?per_page=100"] = (
            403, {"X-RateLimit-Remaining": "0"}, b'{"message": "API rate limit exceeded"}')
        results, builders, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertEqual(out.count("cannot list the releases of o/r (HTTP 403: API rate limit reached; "
                                   "set GITHUB_TOKEN)"), 1, out)
        self.assertEqual(len(out.strip().splitlines()), 1, "one line, once per process")

    def test_missing_asset_and_broken_manifest(self):
        zh = next(e for e in self.manifest["entries"] if e["unit"] == "demo/zh")
        self.gh.release("o/r", [("v2", False, {"build-cache.json": b"not json"}), ("v1", False, self.assets)])
        del self.gh.routes[f"dl/download/v1/{zh['asset']}"]
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "release"], out)
        self.assertIn("cannot read build-cache.json of release v2", out)
        self.assertIn("cannot restore html demo/zh from release v1 (HTTP 404", out)

    def test_mistyped_manifests_are_skipped(self):
        """A manifest of the right schema with mistyped entries does not stop the index: valid entries, in
        it and in other releases, are still used, and the releases are listed once."""
        zh, en = (next(e for e in self.manifest["entries"] if e["unit"] == u) for u in ("demo/zh", "demo/en"))
        bad = {"build-cache.json": json.dumps({**self.manifest, "entries": [
            {"target": "html", "unit": "demo/en", "key": en["key"], "asset": ["not", "a", "name"]}, 7, zh,
        ]}).encode(), zh["asset"]: self.assets[zh["asset"]]}
        worse = {"build-cache.json": json.dumps({**self.manifest, "entries": {"not": "a list"}}).encode()}
        self.gh.release("o/r", [("v3", False, worse), ("v2", False, bad), ("v1", False, self.assets)])
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["release", "release"], out)
        self.assertIn("demo/zh restored from release v2", out)
        self.assertIn("demo/en restored from release v1", out)
        self.assertIn("build-cache.json of release v3 has no list of entries", out)
        self.assertEqual(len([p for _, p, _ in self.gh.requests if "per_page" in p]), 1)

    def test_unreachable_api(self):
        with socket.socket() as sock:  # a port nothing listens on
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        os.environ["GITHUB_API_URL"] = f"http://127.0.0.1:{port}"
        results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertIn("cannot list the releases of o/r", out)

    def test_unexpected_errors_never_fail_the_build(self):
        with mock.patch.object(buildcache, "restore_remote", side_effect=RuntimeError("boom")):
            results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"])
        self.assertIn("boom", out)

    def test_no_network_without_remote(self):
        del os.environ["TBOOK_CACHE_REMOTE"]
        with mock.patch.object(buildcache, "_open") as opened, mock.patch.object(buildcache, "_remote_index") as index:
            results, _, out = self.build_all(repo="o/r")
        self.assertEqual(results, ["built", "built"], out)
        opened.assert_not_called()
        index.assert_not_called()
        self.assertEqual(self.gh.requests, [])
        os.environ["TBOOK_CACHE_REMOTE"] = "1"
        os.environ["TBOOK_CACHE"] = "0"
        self.forget()
        self.build_all(repo="o/r")
        self.assertEqual(self.gh.requests, [], "TBOOK_CACHE=0 turns the releases off too")


class SafeExtractTests(unittest.TestCase):
    def extract(self, members) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="tbook-tar-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        write(tmp / "entry.tar", tar_bytes(members))
        buildcache._safe_extract(tmp / "entry.tar", tmp / "out")
        return tmp / "out"

    def test_regular_entries(self):
        out = self.extract([member("entry.json", data=b"{}"), member("files", tarfile.DIRTYPE),
                            member("files/0", tarfile.DIRTYPE), member("files/0/a.html", data=b"<p>")])
        self.assertEqual(tree(out), {"entry.json": hashlib.sha256(b"{}").hexdigest(), "files": "dir",
                                     "files/0": "dir", "files/0/a.html": hashlib.sha256(b"<p>").hexdigest()})

    def test_refused(self):
        cases = {
            "symlink": [member("files/0", tarfile.SYMTYPE, linkname="/")],
            "dot": [member("files/./0", data=b"x")],
            "entry.json directory": [member("entry.json", tarfile.DIRTYPE)],
            "backslash": [member("files\\..\\x", data=b"x")],
            "file then directory": [member("files/0", data=b"x"), member("files/0/a", data=b"y")],
        }
        for what, members in cases.items():
            with self.subTest(what), self.assertRaises((ValueError, OSError)):
                self.extract(members)

    def test_works_without_the_extraction_filter(self):
        """Python 3.11 before 3.11.4 has no extraction filters: the cache does not use them."""
        with mock.patch.object(tarfile.TarFile, "extractall", side_effect=AssertionError("not used")), \
                mock.patch.object(tarfile.TarFile, "extract", side_effect=AssertionError("not used")):
            out = self.extract([member("entry.json", data=b"{}"), member("files/0", data=b"x")])
        self.assertTrue((out / "files" / "0").is_file())


# --------------------------------------------------------------------------- ./tbook cache and builds


def scratch_repository(dest: Path) -> Path:
    """A copy of this repository's tools, theme and example book (what git would commit) in ``dest``, a git
    repository of its own, with node_modules linked."""
    listed = buildcache._git_files(str(REAL_ROOT))
    prefixes = ("tools/", "theme/", "books/example-monograph/", "i18n/")
    tops = ("tbook", "site.toml", "trureturing.lock.json", "requirements.txt", "package.json", "package-lock.json",
            ".gitignore")
    names = sorted(n for n in listed or () if n.startswith(prefixes) or n in tops)
    for name in names:
        src = REAL_ROOT / name
        if src.is_file():
            write(dest / name, src.read_bytes())
            shutil.copymode(src, dest / name)
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "scratch")
    if (REAL_ROOT / "node_modules").exists():
        os.symlink((REAL_ROOT / "node_modules").resolve(), dest / "node_modules")
    return dest


def cli_env(root: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CACHE_ENV}
    env.update(TBOOK_ROOT=str(root), TBOOK_PYTHON=sys.executable, PYTHONPATH=str(REAL_ROOT / "tools"), **extra)
    return env


def example_shown() -> bool:
    """books/example-monograph is in this repository and its site.toml does not hide it ([books].hide): the
    scratch copy keeps that site.toml, and the commands there must see the example book."""
    if not (REAL_ROOT / "books" / "example-monograph").is_dir():
        return False
    try:
        return not config.load_site().hidden_by("example-monograph")
    except config.ConfigError:
        return False
    finally:
        config.load_site.cache_clear()  # read while the module is imported: cache nothing for the tests


@unittest.skipUnless(REAL_ROOT.joinpath(".git").exists() and shutil.which("git"), "needs this repository's git")
@unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden by site.toml [books].hide")
class CliTests(unittest.TestCase):
    """./tbook cache status|key|prune|export on the example book, with stand-in outputs (the commands
    without any book: test_template's test_ci_and_pages_commands)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-cache-cli-"))
        cls.root = scratch_repository(cls.tmp / "repo")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tbook(self, *args: str, code: int = 0) -> str:
        r = subprocess.run([sys.executable, "-m", "tbook", *args], cwd=self.root, env=cli_env(self.root),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def stand_in(self, which: str) -> None:
        """Store stand-in outputs for the units whose target is in ``which``."""
        script = textwrap.dedent(f"""\
            from tbook import buildcache, config
            for u in buildcache.units(config.load_site(), config.load_books()):
                if u.target not in {which!r}:
                    continue
                for o in u.outputs:
                    if u.target in ("html", "slides"):
                        o.mkdir(parents=True, exist_ok=True)
                        (o / "index.html").write_text(u.name)
                    else:
                        o.parent.mkdir(parents=True, exist_ok=True)
                        o.write_bytes(b"stand-in " + u.name.encode())
                buildcache.store(u)
            """)
        r = subprocess.run([sys.executable, "-c", script], cwd=self.root, env=cli_env(self.root), capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_cache_commands(self):
        status = self.tbook("cache", "status")
        lines = [ln for ln in status.splitlines() if ln.split()[0] in buildcache.TARGETS]
        self.assertTrue(any(ln.startswith("html") and "example-monograph/zh" in ln for ln in lines), status)
        self.assertTrue(all(ln.endswith("not stored") for ln in lines), status)
        empty_key = self.tbook("cache", "key").strip()
        self.assertRegex(empty_key, r"^build-cache-v1-[0-9a-f]{64}$")

        self.stand_in(("html", "epub"))
        status = self.tbook("cache", "status")
        stored = [ln for ln in status.splitlines() if ln.endswith("  stored")]
        self.assertEqual(len(stored), 4, status)  # html and epub of zh and en
        key = self.tbook("cache", "key").strip()
        self.assertNotEqual(key, empty_key)
        self.assertEqual(self.tbook("cache", "key").strip(), key, "the key is stable")

        out_dir = self.tmp / "export"
        out = self.tbook("cache", "export", str(out_dir), code=1)  # PDFs and slides are not stored
        self.assertIn("pdf example-monograph/zh/screen is not in the store", out)
        manifest = json.loads((out_dir / "build-cache.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(e["target"] for e in manifest["entries"]), ["epub", "epub", "html", "html"])
        self.assertTrue(all((out_dir / e["asset"]).is_file() for e in manifest["entries"]))
        out = self.tbook("cache", "export", str(self.tmp / "export-html"), "--book", "example-monograph", code=1)
        self.assertIn("wrote 4 of", out)

        chapter = next((self.root / "books" / "example-monograph" / "zh").glob("*.md"))
        original = chapter.read_text(encoding="utf-8")
        chapter.write_text(original + "\n<!-- edited -->\n", encoding="utf-8")
        try:
            status = self.tbook("cache", "status")
            self.assertEqual([ln for ln in status.splitlines() if ln.endswith("  stored")], [],
                             "an edited chapter changes every unit of the book (all editions read book.dir)")
            self.assertIn("removed 4 entries; 0 left", self.tbook("cache", "prune"))
            self.tbook("cache", "prune", "--book", "example-monograph", code=2)
        finally:
            chapter.write_text(original, encoding="utf-8")


def _toolchain_missing() -> str:
    try:
        from tbook import pandoc

        pandoc.pandoc_path()
    except Exception as exc:  # noqa: BLE001
        return f"pandoc: {exc}"
    if buildcache.package_version("typst") == "missing":
        return "the typst Python module is not installed"
    if not MDBOOK:
        return "mdBook is not installed (set MDBOOK)"
    if not NODE or not (REAL_ROOT / "node_modules" / "katex").is_dir():
        return "node and node_modules are needed"
    if not (REAL_ROOT / ".git").exists():
        return "needs this repository's git"
    return ""


@unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden by site.toml [books].hide")
@unittest.skipIf(_toolchain_missing(), _toolchain_missing())
class BuildIntegrationTests(unittest.TestCase):
    """./tbook build html pdf epub twice on a scratch copy of the example book: the second run restores
    every unit, byte for byte; a new checkout restores them from a release made by ./tbook cache export."""

    def test_second_build_and_release_restore(self):
        tmp = Path(tempfile.mkdtemp(prefix="tbook-cache-build-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        root = scratch_repository(tmp / "repo")
        env = cli_env(root, MDBOOK=MDBOOK, TBOOK_EPUBCHECK="0", TBOOK_REPO="o/r",
                      TBOOK_BASE_URL="https://o.github.io/r/")

        def build(**extra: str) -> tuple[str, float]:
            t0 = time.time()
            r = subprocess.run([str(root / "tbook"), "build", "html", "pdf", "epub"], cwd=root,
                               env={**env, **extra}, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return r.stdout, time.time() - t0

        def outputs() -> dict[str, str]:
            return {**{f"html/{k}": v for k, v in tree(root / "build" / "html").items()},
                    **{f"dist/{k}": v for k, v in tree(root / "build" / "dist").items()}}

        first, t_first = build()
        self.assertNotIn("up to date", first)
        built = outputs()
        units = 10  # zh and en: HTML, screen/print/academic PDF, EPUB
        self.assertEqual(len([k for k in built if k.startswith("dist/") and k.count("/") == 2]), 8, built.keys())

        for lang in ("zh", "en"):
            self.assertTrue(any(k.endswith(f"-{lang}-academic.pdf") for k in built))

        second, t_second = build()
        self.assertEqual(second.count("is up to date"), units, second)
        self.assertEqual(outputs(), built)
        self.assertLess(t_second, t_first / 3, (t_first, t_second))

        shutil.rmtree(root / "build")
        third, _ = build()
        self.assertEqual(third.count("is up to date"), units, third)
        self.assertEqual(outputs(), built, "restored into an empty build directory")

        exported = tmp / "release"
        r = subprocess.run([sys.executable, "-m", "tbook", "cache", "export", str(exported)], cwd=root, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, "the slides were not built: " + r.stdout + r.stderr)
        assets = {p.name: p.read_bytes() for p in exported.iterdir()}
        self.assertEqual(len(json.loads(assets["build-cache.json"])["entries"]), units)

        gh = FakeGitHub()
        self.addCleanup(gh.close)
        gh.release("o/r", [("v1", False, assets)])
        shutil.rmtree(root / "build")
        shutil.rmtree(root / ".cache" / "artifacts")
        fourth, _ = build(TBOOK_CACHE_REMOTE="1", GITHUB_API_URL=gh.url(gh.api), NO_PROXY="127.0.0.1",
                          no_proxy="127.0.0.1")
        self.assertEqual(fourth.count("restored from release v1"), units, fourth)
        self.assertEqual(outputs(), built, "restored from the release")


if __name__ == "__main__":
    unittest.main()
