"""Tests for template versioning: ``./tbook template status | update | manifest``.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_template.py'

The fixture is a fake template repository built from this repository's managed files
(tagged v0.1.0, then modified and tagged v0.2.0, plus a v0.3.0-rc.1 pre-release) and, per
test, a downstream repository created from v0.1.0 (like GitHub's "Use this template":
a fresh history) with owned changes and local edits to managed files. Updates run against
the template with ``--source <path>``; no network. Git runs with an empty global config.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from tbook import paths, template
from tbook.template import (
    ADD, CONFLICT, KEEP, RELEASE, REMOVE, SAME, SKIP, UPDATE, Manifest, TemplateConfig, TemplateError,
)

REAL_ROOT = paths.ROOT


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {r.stderr}")
    return r.stdout


def write(path: Path, text: str, mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(path, mode)
    return path


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_snapshot(root: Path) -> dict[str, tuple[str, str]]:
    """{path: (mode, sha)} of every file and symlink outside .git (for 'nothing changed' checks)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git" and not (Path(dirpath) / d).is_symlink()]
        for name in filenames + [d for d in os.listdir(dirpath) if (Path(dirpath) / d).is_symlink()]:
            p = Path(dirpath) / name
            entry = template.file_entry(p)
            out[p.relative_to(root).as_posix()] = (entry.mode, entry.sha256)
    return out


class GitEnv:
    """Isolate git from the user's global configuration (signing, hooks …)."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="tbook-gitcfg-")
        cfg = Path(self.tmp) / "gitconfig"
        cfg.write_text("[user]\n\tname = Test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n"
                       "[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n", encoding="utf-8")
        self.patch = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1",
                                                  "TBOOK_LANG": "en"})
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# --------------------------------------------------------------------------- fixture


MIGRATION_020 = '''\
"""Test migration: records that it ran (idempotent)."""
from pathlib import Path


def migrate(root: Path) -> list[str]:
    marker = root / "books" / "MIGRATED-0.2.0.txt"
    if marker.exists():
        return ["already migrated"]
    marker.parent.mkdir(parents=True, exist_ok=True)  # a books repository may have no book yet
    marker.write_text("0.2.0\\n", encoding="utf-8")
    return ["wrote books/MIGRATED-0.2.0.txt"]
'''

MIGRATION_OTHER = '''\
from pathlib import Path


def migrate(root: Path) -> list[str]:
    (root / "WRONG-{v}.txt").write_text("must not run", encoding="utf-8")
    return ["ran {v}"]
'''


def copy_real_managed(dest: Path, *, example: bool = True) -> None:
    """This repository's managed files (and the owned files a template repository has).

    The example book is optional (books repositories may delete it): two of its files are copied when
    it exists and ``example`` is true.
    """
    cfg = TemplateConfig.load(REAL_ROOT)
    files = [p for p in template.candidate_files(REAL_ROOT, cfg) if cfg.manages(p)]
    files += ["template.toml", "site.toml", "README.md", "LICENSE", "trureturing.lock.json"]
    for rel in sorted(set(files)):
        src = REAL_ROOT / rel
        if not os.path.lexists(src):
            continue
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
        elif src.is_file():
            shutil.copy2(src, dst)
    for rel in ("books/example-monograph/book.toml", "books/example-monograph/zh/SUMMARY.md"):
        if example and (REAL_ROOT / rel).exists():
            dst = dest / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REAL_ROOT / rel, dst)


def set_version(root: Path, version: str) -> None:
    p = root / "template.toml"
    text = p.read_text(encoding="utf-8")
    text, n = re.subn(r'(?m)^version = "[^"]*"', f'version = "{version}"', text, count=1)
    assert n == 1
    p.write_text(text, encoding="utf-8")


def commit_all(root: Path, message: str, tag: str | None = None) -> None:
    template.cmd_manifest(root, out=lambda s: None)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    if tag:
        git(root, "tag", "-a", tag, "-m", tag)


def build_template(base: Path) -> Path:
    tpl = base / "template"
    tpl.mkdir()
    copy_real_managed(tpl)
    set_version(tpl, "0.1.0")
    # Fixture-only files exercising symlinks, modes, removals, conflicts and releases.
    write(tpl / "tools" / "fixture" / "replace.txt", "v1\n")
    write(tpl / "tools" / "fixture" / "remove-me.txt", "bye\n")
    write(tpl / "tools" / "fixture" / "both.txt", "base\n")
    write(tpl / "tools" / "fixture" / "kept.txt", "base\n")
    write(tpl / "tools" / "fixture" / "deleted-locally.txt", "base\n")
    write(tpl / "tools" / "fixture" / "removed-upstream-modified-locally.txt", "base\n")
    write(tpl / "tools" / "fixture" / "deleted-locally-changed-upstream.txt", "base\n")
    write(tpl / "tools" / "fixture" / "to-exec.sh", "#!/bin/sh\necho hi\n", 0o644)
    write(tpl / "tools" / "fixture" / "released.txt", "managed in 0.1.0 only\n")
    os.symlink("replace.txt", tpl / "tools" / "fixture" / "link")
    write(tpl / "docs" / "CHANGELOG.md", textwrap.dedent("""\
        # Changelog

        ## [Unreleased]

        ## [0.1.0] - 2026-11-08

        - First release.
        """))
    git(tpl, "init", "-q", "-b", "main")
    commit_all(tpl, "template 0.1.0", "v0.1.0")
    # A book release tag of the template repository itself: not a template release.
    git(tpl, "tag", "example-monograph-v0.1.0")
    git(tpl, "tag", "vnot-a-version")

    # ---- 0.2.0
    set_version(tpl, "0.2.0")
    fx = tpl / "tools" / "fixture"
    write(fx / "replace.txt", "v2\n")
    (fx / "remove-me.txt").unlink()
    write(fx / "both.txt", "upstream\n")
    (fx / "removed-upstream-modified-locally.txt").unlink()
    write(fx / "deleted-locally-changed-upstream.txt", "upstream\n")
    os.chmod(fx / "to-exec.sh", 0o755)
    write(fx / "new.txt", "new upstream\n")
    write(fx / "new-script.sh", "#!/bin/sh\necho new\n", 0o755)
    write(fx / "new-same.txt", "identical\n")
    write(fx / "new-different.txt", "upstream version\n")
    write(fx / "deep" / "nested" / "file.txt", "deep\n")
    (fx / "link").unlink()
    os.symlink("new.txt", fx / "link")
    os.symlink("deep/nested/file.txt", fx / "new-link")
    # 0.2.0 stops managing tools/fixture/released.txt: it moves under an excluded prefix.
    (fx / "released.txt").unlink()
    text = (tpl / "template.toml").read_text(encoding="utf-8")
    text = text.replace('  "docs/project/",\n]', '  "docs/project/",\n  "tools/fixture/released",\n]')
    (tpl / "template.toml").write_text(text, encoding="utf-8")
    # Owned and excluded paths changed upstream must never reach the downstream.
    write(tpl / "site.toml", (tpl / "site.toml").read_text(encoding="utf-8") + "\n# upstream site change\n")
    write(tpl / "README.md", "# upstream readme\n")
    write(tpl / "skills" / "local-mine" / "SKILL.md", "upstream copy of a local skill\n")
    write(tpl / "docs" / "project" / "notes.md", "upstream project notes\n")
    # Migrations: only v0.2.0 is in (0.1.0, 0.2.0].
    write(tpl / "tools" / "migrations" / "v0.1.0.py", MIGRATION_OTHER.format(v="0.1.0"))
    write(tpl / "tools" / "migrations" / "v0.2.0.py", MIGRATION_020)
    write(tpl / "tools" / "migrations" / "v0.3.0.py", MIGRATION_OTHER.format(v="0.3.0"))
    write(tpl / "docs" / "CHANGELOG.md", textwrap.dedent("""\
        # Changelog

        ## [Unreleased]

        ## [0.2.0] - 2026-11-09

        ### Changed

        - Fixture changes for the update test.

        ## [0.1.0] - 2026-11-08

        - First release.
        """))
    commit_all(tpl, "template 0.2.0", "v0.2.0")

    # ---- 0.3.0-rc.1 (a pre-release: never the default target)
    set_version(tpl, "0.3.0-rc.1")
    write(fx / "replace.txt", "v3-rc\n")
    commit_all(tpl, "template 0.3.0-rc.1", "v0.3.0-rc.1")
    git(tpl, "checkout", "-q", "-b", "next")
    git(tpl, "checkout", "-q", "main")
    return tpl


def make_downstream(base: Path, tpl: Path, name: str = "downstream", tag: str = "v0.1.0",
                    local_work: bool = True) -> Path:
    """A repository created from the template at ``tag`` (fresh history), with typical local work."""
    ds = base / name
    ds.mkdir()
    archive = subprocess.run(["git", "-C", str(tpl), "archive", "--format=tar", tag], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(ds)], input=archive.stdout, check=True)
    git(ds, "init", "-q", "-b", "main")
    git(ds, "add", "-A")
    git(ds, "commit", "-q", "-m", "Initial commit from template")
    if not local_work:
        return ds
    # Owned changes.
    write(ds / "site.toml", "[site]\nlanguages = [\"en\", \"zh\"]\nrepo = \"someone/books\"\n")
    write(ds / "books" / "my-book" / "book.toml", "[book]\nversion = \"1.0.0\"\ntitle = \"Mine\"\n")
    write(ds / "README.md", "# my books\n")
    write(ds / "skills" / "local-mine" / "SKILL.md", "my own skill\n")
    write(ds / "docs" / "project" / "notes.md", "my notes\n")
    # Local edits to managed files.
    fx = ds / "tools" / "fixture"
    write(fx / "both.txt", "local\n")
    write(fx / "kept.txt", "local edit\n")
    (fx / "deleted-locally.txt").unlink()
    write(fx / "removed-upstream-modified-locally.txt", "local\n")
    (fx / "deleted-locally-changed-upstream.txt").unlink()
    write(fx / "new-same.txt", "identical\n")
    write(fx / "new-different.txt", "my version\n")
    write(fx / "released.txt", "managed in 0.1.0 only\n")
    git(ds, "add", "-A")
    git(ds, "commit", "-q", "-m", "Local work")
    return ds


class TemplateFixture(unittest.TestCase):
    """Builds the template repository once per class."""

    @classmethod
    def setUpClass(cls):
        cls.genv = GitEnv().__enter__()
        cls.base = Path(tempfile.mkdtemp(prefix="tbook-template-test-"))
        cls.tpl = build_template(cls.base)
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)
        cls.genv.__exit__(None, None, None)

    def downstream(self, tag: str = "v0.1.0") -> Path:
        type(self).counter += 1
        return make_downstream(self.base, self.tpl, f"downstream-{self.counter}", tag)

    def run_update(self, ds: Path, **kw) -> template.UpdateResult:
        kw.setdefault("source", str(self.tpl))
        return template.update(ds, **kw)

    @staticmethod
    def kinds(res: template.UpdateResult) -> dict[str, str]:
        return {a.path: a.kind for a in res.actions if a.path.startswith("tools/fixture/")}

    def tpl_at(self, tag: str) -> Path:
        out = self.base / f"tpl-{tag}"
        if not out.exists():
            out.mkdir()
            archive = subprocess.run(["git", "-C", str(self.tpl), "archive", tag], capture_output=True, check=True)
            subprocess.run(["tar", "-x", "-C", str(out)], input=archive.stdout, check=True)
        return out

    def template_clone(self, name: str, start: str) -> Path:
        """A clone of the fixture template (with its tags) on a new branch at ``start``."""
        type(self).counter += 1
        clone = self.base / f"{name}-{self.counter}"
        subprocess.run(["git", "clone", "-q", str(self.tpl), str(clone)], check=True)
        git(clone, "checkout", "-q", "-b", f"{name}-branch", start)
        return clone


# --------------------------------------------------------------------------- tests: update


class UpdateTests(TemplateFixture):
    def test_three_way_update(self):
        ds = self.downstream()
        before_owned = {p: (ds / p).read_bytes() for p in ("site.toml", "README.md", "books/my-book/book.toml",
                                                          "skills/local-mine/SKILL.md", "docs/project/notes.md")}
        res = self.run_update(ds)
        self.assertEqual(res.errors, [])
        self.assertEqual((res.old_version, res.new_version), ("0.1.0", "0.2.0"))
        self.assertEqual(res.upstream.ref, "v0.2.0", "the default target is the highest stable release")
        k = self.kinds(res)
        fx = "tools/fixture/"
        expected = {
            "replace.txt": UPDATE,                       # (a) unchanged locally → take upstream
            "remove-me.txt": REMOVE,                     # (a) removed upstream
            "new.txt": ADD,                              # (d) new upstream
            "new-script.sh": ADD,
            "deep/nested/file.txt": ADD,
            "link": UPDATE,                              # retargeted symlink
            "new-link": ADD,
            "to-exec.sh": UPDATE,                        # mode-only change
            "kept.txt": KEEP,                            # (b) modified locally, unchanged upstream
            "deleted-locally.txt": KEEP,
            "both.txt": CONFLICT,                        # (c)
            "removed-upstream-modified-locally.txt": CONFLICT,
            "deleted-locally-changed-upstream.txt": CONFLICT,
            "new-different.txt": CONFLICT,               # (e)
            "new-same.txt": SAME,
            "released.txt": RELEASE,
        }
        for name, kind in expected.items():
            self.assertEqual(k.get(fx + name), kind, name)
        self.assertEqual(res.exit_code, template.EXIT_CONFLICTS)

        f = ds / "tools" / "fixture"
        self.assertEqual((f / "replace.txt").read_text(), "v2\n")
        self.assertFalse((f / "remove-me.txt").exists())
        self.assertEqual((f / "new.txt").read_text(), "new upstream\n")
        self.assertEqual((f / "deep" / "nested" / "file.txt").read_text(), "deep\n")
        # Modes and symlinks.
        self.assertTrue(os.stat(f / "new-script.sh").st_mode & stat.S_IXUSR)
        self.assertTrue(os.stat(f / "to-exec.sh").st_mode & stat.S_IXUSR)
        self.assertFalse(os.stat(f / "new.txt").st_mode & stat.S_IXUSR)
        self.assertTrue((f / "link").is_symlink())
        self.assertEqual(os.readlink(f / "link"), "new.txt")
        self.assertEqual(os.readlink(f / "new-link"), "deep/nested/file.txt")
        self.assertEqual((f / "new-link").read_text(), "deep\n")
        self.assertTrue((ds / "AGENTS.md").is_symlink(), "unchanged symlinks stay symlinks")
        # Kept local changes.
        self.assertEqual((f / "kept.txt").read_text(), "local edit\n")
        self.assertFalse((f / "deleted-locally.txt").exists())
        # Conflicts: local kept, upstream next to it.
        self.assertEqual((f / "both.txt").read_text(), "local\n")
        self.assertEqual((f / "both.txt.template-new").read_text(), "upstream\n")
        self.assertEqual((f / "new-different.txt").read_text(), "my version\n")
        self.assertEqual((f / "new-different.txt.template-new").read_text(), "upstream version\n")
        self.assertEqual((f / "removed-upstream-modified-locally.txt").read_text(), "local\n")
        self.assertFalse((f / "removed-upstream-modified-locally.txt.template-new").exists())
        self.assertFalse((f / "deleted-locally-changed-upstream.txt").exists())
        self.assertEqual((f / "deleted-locally-changed-upstream.txt.template-new").read_text(), "upstream\n")
        # Released and identical files stay.
        self.assertEqual((f / "released.txt").read_text(), "managed in 0.1.0 only\n")
        self.assertEqual((f / "new-same.txt").read_text(), "identical\n")
        # Owned and excluded paths untouched, even though upstream changed them.
        for p, data in before_owned.items():
            self.assertEqual((ds / p).read_bytes(), data, p)
        self.assertTrue((ds / "books" / "my-book" / "book.toml").exists())
        skipped = {a.path for a in res.actions if a.kind == SKIP}
        self.assertNotIn("site.toml", {a.path for a in res.actions if a.kind != SKIP})
        self.assertFalse(any(p.startswith(("skills/local-", "docs/project/")) for p in
                             {a.path for a in res.actions if a.kind != SKIP}))
        self.assertTrue(all(not p.startswith("books/") for p in {a.path for a in res.actions} - skipped))
        # New template.toml and manifest.
        cfg = TemplateConfig.load(ds)
        self.assertEqual(cfg.version, "0.2.0")
        self.assertIn("tools/fixture/released", cfg.exclude)
        manifest = Manifest.load(ds)
        self.assertEqual(manifest.version, "0.2.0")
        self.assertEqual(manifest.files, Manifest.load(self.tpl_at("v0.2.0")).files)
        # Migrations: exactly v0.2.0 ran, from the new template.
        self.assertEqual([m[0] for m in res.migrations], ["v0.2.0.py"])
        self.assertEqual(res.migrations[0][1], ["wrote books/MIGRATED-0.2.0.txt"])
        self.assertTrue((ds / "books" / "MIGRATED-0.2.0.txt").exists())
        self.assertFalse((ds / "WRONG-0.1.0.txt").exists())
        self.assertFalse((ds / "WRONG-0.3.0.txt").exists())

    def test_summary_and_exit_code_via_cmd(self):
        ds = self.downstream()
        lines: list[str] = []
        rc = template.cmd_update(ds, to=None, source=str(self.tpl), dry_run=False, force=False, out=lines.append)
        self.assertEqual(rc, 3)
        summary = (ds / "build" / "template-update.md").read_text(encoding="utf-8")
        self.assertIn("## Template update 0.1.0 → 0.2.0", summary)
        self.assertIn("### Conflicts: merge by hand (4)", summary)
        self.assertIn("`tools/fixture/both.txt` — changed locally and upstream; the upstream version is in "
                      "`tools/fixture/both.txt.template-new`", summary)
        self.assertIn("### Added", summary)
        self.assertIn("### Removed", summary)
        self.assertIn("`v0.2.0.py`", summary)
        self.assertIn("wrote books/MIGRATED-0.2.0.txt", summary)
        self.assertIn("## [0.2.0] - 2026-11-09", summary, "the changelog of crossed versions is included")
        self.assertNotIn("## [0.1.0]", summary)
        self.assertIn("docs/CHANGELOG.md", summary)
        self.assertIn("\n".join(lines[:1]), summary)

    def test_summary_in_chinese(self):
        ds = self.downstream()
        write(ds / "site.toml", "[site]\nlanguages = [\"zh\", \"en\"]\n")
        with mock.patch.dict(os.environ, {"TBOOK_LANG": ""}):
            rc = template.cmd_update(ds, to=None, source=str(self.tpl), dry_run=True, force=False,
                                     out=lambda s: None)
            self.assertEqual(rc, 3)
            res = template.update(ds, source=str(self.tpl), dry_run=True)
            text = template.render_summary(res, template._lang(ds))
        self.assertIn("## 模板升级预览 0.1.0 → 0.2.0", text)
        self.assertIn("冲突：需要人工合并", text)
        self.assertIn("将运行：`v0.2.0.py`", text)

    def test_dry_run_writes_nothing(self):
        ds = self.downstream()
        before = tree_snapshot(ds)
        rc = template.cmd_update(ds, to=None, source=str(self.tpl), dry_run=True, force=False, out=lambda s: None)
        self.assertEqual(rc, template.EXIT_CONFLICTS, "a dry run reports the exit code the update would have")
        self.assertEqual(tree_snapshot(ds), before)
        self.assertFalse((ds / "build").exists())
        res = self.run_update(ds, dry_run=True)
        self.assertEqual(res.pending_migrations, ["v0.2.0.py"])
        self.assertEqual(res.migrations, [])
        self.assertIn("Will run: `v0.2.0.py`", template.render_summary(res, "en"))

    def test_force_takes_upstream(self):
        ds = self.downstream()
        write(ds / "tools" / "fixture" / "both.txt.template-new", "stale from an earlier run\n")
        res = self.run_update(ds, force=True)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.conflicts, [])
        f = ds / "tools" / "fixture"
        self.assertEqual((f / "both.txt").read_text(), "upstream\n")
        self.assertFalse((f / "both.txt.template-new").exists())
        self.assertEqual((f / "new-different.txt").read_text(), "upstream version\n")
        self.assertFalse((f / "removed-upstream-modified-locally.txt").exists())
        self.assertEqual((f / "deleted-locally-changed-upstream.txt").read_text(), "upstream\n")
        # --force does not touch files that only changed locally, nor owned paths.
        self.assertEqual((f / "kept.txt").read_text(), "local edit\n")
        self.assertEqual((ds / "README.md").read_text(), "# my books\n")
        forced = [a.path for a in res.actions if a.forced]
        self.assertEqual(len(forced), 4)
        self.assertIn("took the upstream version (--force", template.render_summary(res, "en"))

    def test_second_update_is_a_no_op(self):
        ds = self.downstream()
        self.run_update(ds)
        before = tree_snapshot(ds)
        res = self.run_update(ds)
        self.assertEqual(res.exit_code, 0, "conflicts already written are local changes now")
        self.assertEqual(res.of(ADD, UPDATE, REMOVE, CONFLICT), [])
        self.assertEqual(res.migrations, [], "same version: no migrations")
        before.pop("build/template-update.md", None)
        after = tree_snapshot(ds)
        after.pop("build/template-update.md", None)
        self.assertEqual(after, before)

    def test_to_version_tag_branch_and_commit(self):
        ds = self.downstream()
        res = self.run_update(ds, to="0.1.0", dry_run=True)
        self.assertEqual(res.upstream.ref, "v0.1.0")
        self.assertEqual(res.of(ADD, UPDATE, REMOVE, CONFLICT), [])
        res = self.run_update(ds, to="v0.3.0-rc.1", dry_run=True)
        self.assertEqual(res.new_version, "0.3.0-rc.1")
        self.assertEqual(res.pending_migrations, ["v0.2.0.py"], "0.3.0 > 0.3.0-rc.1: not included")
        res = self.run_update(ds, to="next", dry_run=True)
        self.assertEqual(res.upstream.ref, "next")
        commit = git(self.tpl, "rev-parse", "v0.2.0^{commit}").strip()
        res = self.run_update(ds, to=commit, dry_run=True)
        self.assertEqual(res.upstream.commit, commit)
        self.assertEqual(res.new_version, "0.2.0")
        with self.assertRaisesRegex(TemplateError, "9.9.9 not found"):
            self.run_update(ds, to="9.9.9", dry_run=True)
        with self.assertRaisesRegex(TemplateError, "cannot fetch"):
            self.run_update(ds, to="no-such-branch", dry_run=True)

    def test_to_abbreviated_commit(self):
        """git fetch needs full object names: a local source expands a short SHA, a URL says what to pass."""
        ds = self.downstream()
        commit = git(self.tpl, "rev-parse", "v0.2.0^{commit}").strip()
        res = self.run_update(ds, to=commit[:12], dry_run=True)
        self.assertEqual(res.upstream.commit, commit)
        self.assertEqual(res.upstream.ref, commit[:12])
        self.assertEqual(res.new_version, "0.2.0")
        url = Path(self.tpl).resolve().as_uri()  # file://… is fetched like a remote
        with self.assertRaisesRegex(TemplateError, "(?s)cannot fetch .*full 40-character SHA"):
            self.run_update(ds, source=url, to=commit[:12], dry_run=True)
        self.assertEqual(self.run_update(ds, source=url, to=commit, dry_run=True).upstream.commit, commit)
        with self.assertRaisesRegex(TemplateError, "cannot fetch 'abcdef0123'"):
            self.run_update(ds, to="abcdef0123", dry_run=True)

    def test_upgrade_in_two_steps_runs_each_migration_once(self):
        ds = self.downstream()
        res = self.run_update(ds, to="0.1.0")
        self.assertEqual(res.migrations, [])
        res = self.run_update(ds, to="0.2.0")
        self.assertEqual([m[0] for m in res.migrations], ["v0.2.0.py"])

    def test_no_local_manifest(self):
        ds = self.downstream()
        (ds / "template-manifest.json").unlink()
        res = self.run_update(ds, dry_run=True)
        k = self.kinds(res)
        self.assertEqual(k["tools/fixture/replace.txt"], CONFLICT, "without a base every difference conflicts")
        self.assertEqual(k["tools/fixture/new-same.txt"], SAME)
        self.assertEqual(k["tools/fixture/new.txt"], ADD)
        self.assertTrue(any("no local template-manifest.json" in w for w in res.warnings))

    def test_template_name_mismatch(self):
        ds = self.downstream()
        p = ds / "template.toml"
        p.write_text(p.read_text(encoding="utf-8").replace('name = "trureturing-books-template"',
                                                            'name = "another-template"'), encoding="utf-8")
        with self.assertRaisesRegex(TemplateError, "another-template"):
            self.run_update(ds, dry_run=True)
        res = self.run_update(ds, dry_run=True, force=True)
        self.assertEqual(res.new_version, "0.2.0")

    def test_plain_directory_source(self):
        ds = self.downstream()
        src = self.tpl_at("v0.2.0")
        res = self.run_update(ds, source=str(src), dry_run=True)
        self.assertEqual(res.new_version, "0.2.0")
        self.assertEqual(self.kinds(res)["tools/fixture/both.txt"], CONFLICT)
        with self.assertRaisesRegex(TemplateError, "--to needs a git source"):
            self.run_update(ds, source=str(src), to="0.2.0", dry_run=True)

    def test_not_a_template_source(self):
        ds = self.downstream()
        empty = self.base / "not-a-template"
        empty.mkdir(exist_ok=True)
        with self.assertRaisesRegex(TemplateError, "has no template.toml"):
            self.run_update(ds, source=str(empty))

    def test_no_release_tags(self):
        ds = self.downstream()
        bare = self.base / "untagged"
        if not bare.exists():
            subprocess.run(["git", "clone", "-q", "--no-tags", str(self.tpl), str(bare)], check=True)
            for tag in git(bare, "tag").split():
                git(bare, "tag", "-d", tag)
        with self.assertRaisesRegex(TemplateError, "no release tags vX.Y.Z"):
            self.run_update(ds, source=str(bare))
        res = self.run_update(ds, source=str(bare), to="HEAD", dry_run=True)
        self.assertEqual(res.new_version, "0.3.0-rc.1")

    def test_cli_end_to_end(self):
        """The downstream's own ./tbook (its copy of tools/) performs the update."""
        ds = self.downstream()
        env = dict(os.environ, TBOOK_PYTHON=sys.executable, TBOOK_LANG="en")
        env.pop("TBOOK_ROOT", None)
        r = subprocess.run([str(ds / "tbook"), "template", "update", "--source", str(self.tpl)],
                           cwd=ds, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("Template update 0.1.0 → 0.2.0", r.stdout)
        self.assertTrue((ds / "build" / "template-update.md").exists())
        r = subprocess.run([str(ds / "tbook"), "template", "status"], cwd=ds, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("trureturing-books-template 0.2.0", r.stdout)
        self.assertIn("! tools/fixture/both.txt.template-new", r.stdout)
        r = subprocess.run([str(ds / "tbook"), "template", "update", "--source", str(self.base / "nope")],
                           cwd=ds, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("template: ", r.stderr)


# --------------------------------------------------------------------------- tests: adoption


def adopting_repo(base: Path, tpl: Path, name: str, tag: str, files: tuple[str, ...]) -> Path:
    """A repository that was not created from the template: its own files, plus ``files`` from ``tag``."""
    ds = base / name
    ds.mkdir()
    write(ds / ".gitignore", "my own ignore rules\n")  # a managed path the repository already has
    write(ds / "notes" / "mine.md", "my own notes\n")
    archive = subprocess.run(["git", "-C", str(tpl), "archive", "--format=tar", tag, *files], capture_output=True,
                             check=True)
    subprocess.run(["tar", "-x", "-C", str(ds)], input=archive.stdout, check=True)
    git(ds, "init", "-q", "-b", "main")
    git(ds, "add", "-A")
    git(ds, "commit", "-q", "-m", "Adopt the template")
    return ds


class AdoptionTests(TemplateFixture):
    """docs/UPGRADING.md §5: copy tbook, tools/ and template.toml (perhaps template-manifest.json too) from a
    release, then ./tbook template update installs every other managed file."""

    def adopt(self, *files: str) -> Path:
        type(self).counter += 1
        return adopting_repo(self.base, self.tpl, f"adopt-{self.counter}", "v0.2.0", files)

    def assert_installed(self, ds: Path) -> None:
        release = Manifest.load(self.tpl_at("v0.2.0"))
        for p, entry in release.files.items():
            if p != ".gitignore":
                self.assertEqual(template.file_entry(ds / p), entry, p)
        self.assertTrue((ds / "theme" / "tokens.json").is_file())
        self.assertTrue((ds / ".github" / "workflows" / "ci.yml").is_file())
        self.assertEqual((ds / ".gitignore").read_text(encoding="utf-8"), "my own ignore rules\n")
        self.assertEqual((ds / "notes" / "mine.md").read_text(encoding="utf-8"), "my own notes\n")
        self.assertEqual(Manifest.load(ds).files, release.files)
        self.assertEqual(TemplateConfig.load(ds).version, "0.2.0")

    def test_adopt_without_the_manifest(self):
        """The documented flow: the latest release has the copied version, and there is no base."""
        ds = self.adopt("tbook", "tools", "template.toml")
        res = self.run_update(ds)  # no --to: the latest release, 0.2.0, the version copied
        self.assertEqual(res.errors, [])
        self.assertEqual(res.no_update, "", "same version, no base: an installation, not a no-op")
        added = {a.path for a in res.of(ADD)}
        self.assertIn("theme/tokens.json", added)
        self.assertFalse(any(p.startswith(("tools/", "tbook")) for p in added), "the copied files are the release")
        self.assertEqual([(a.path, a.reason) for a in res.conflicts], [(".gitignore", "conflict_added")])
        self.assertEqual(res.exit_code, template.EXIT_CONFLICTS)
        self.assert_installed(ds)
        self.assertEqual((ds / ".gitignore.template-new").read_bytes(),
                         (self.tpl_at("v0.2.0") / ".gitignore").read_bytes(),
                         "a managed file the repository already had: the template's version is next to it")
        self.assertIn("`.gitignore` — added upstream, but a different local file exists",
                      template.render_summary(res, "en"))
        res = self.run_update(ds, dry_run=True)
        self.assertEqual(res.of(ADD, UPDATE, REMOVE, CONFLICT), [], "installed: a second update changes nothing")

    def test_adopt_with_the_copied_manifest(self):
        """The flow docs/UPGRADING.md §5 used to give: the copied manifest lists files this repository never had."""
        ds = self.adopt("tbook", "tools", "template.toml", "template-manifest.json")
        res = self.run_update(ds)
        self.assertEqual(res.errors, [])
        self.assertEqual([a.path for a in res.actions if a.reason == "kept_deleted"], [])
        added = {a.path for a in res.of(ADD)}
        self.assertIn("theme/tokens.json", added)
        self.assertIn("skills/book-new/SKILL.md", added)
        self.assertFalse(any(p.startswith(("tools/", "tbook")) for p in added), "the copied files are the base")
        self.assertTrue(any("never in this repository" in w for w in res.warnings))
        self.assert_installed(ds)
        git(ds, "add", "-A")
        git(ds, "commit", "-q", "-m", "Install the template")
        res = self.run_update(ds)
        self.assertEqual(res.of(ADD, UPDATE, REMOVE, CONFLICT), [], "installed: a second update changes nothing")

    def test_deleted_files_stay_deleted(self):
        """Only files absent from the whole history are installed; a deletion (committed or not) is kept."""
        ds = self.downstream()  # tools/fixture/deleted-locally*.txt deleted in a commit
        (ds / "tools" / "fixture" / "replace.txt").unlink()  # deleted, not committed
        self.assertEqual(template.never_installed(ds, Manifest.load(ds)), set())
        k = self.kinds(self.run_update(ds, dry_run=True))
        self.assertEqual(k["tools/fixture/deleted-locally.txt"], KEEP)
        self.assertEqual(k["tools/fixture/deleted-locally-changed-upstream.txt"], CONFLICT)
        self.assertEqual(k["tools/fixture/replace.txt"], CONFLICT, "deleted locally, changed upstream")

    def merged_update_branch(self, merge: str) -> Path:
        """An update PR to 0.2.0 that also deletes a file 0.2.0 added, merged into main with ``merge``."""
        type(self).counter += 1
        ds = make_downstream(self.base, self.tpl, f"merged-{self.counter}", "v0.1.0", local_work=False)
        git(ds, "checkout", "-q", "-b", "template-update/0.2.0")
        res = self.run_update(ds)
        self.assertEqual((res.errors, res.conflicts, res.new_version), ([], [], "0.2.0"))
        self.assertIn("tools/fixture/new-script.sh", {a.path for a in res.of(ADD)})
        git(ds, "add", "-A")
        git(ds, "commit", "-q", "-m", "Update template to 0.2.0")
        git(ds, "rm", "-q", "tools/fixture/new-script.sh")
        git(ds, "commit", "-q", "-m", "Not this script")
        git(ds, "checkout", "-q", "main")
        write(ds / "books" / "meanwhile.md", "work on main\n")
        git(ds, "add", "-A")
        git(ds, "commit", "-q", "-m", "Meanwhile on main")
        if merge == "squash":
            git(ds, "merge", "-q", "--squash", "template-update/0.2.0")
            git(ds, "commit", "-q", "-m", "Template update 0.1.0 → 0.2.0 (#1)")
        else:
            git(ds, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "template-update/0.2.0")
        self.assertFalse((ds / "tools" / "fixture" / "new-script.sh").exists())
        self.assertEqual(TemplateConfig.load(ds).version, "0.2.0")
        return ds

    def test_deletion_on_a_merged_branch_stays_deleted(self):
        """A file deleted on a branch merged with a merge commit was in HEAD's history: it stays deleted.

        git log simplifies history by default and skips the side branch (the merge is TREESAME to its first
        parent for that path), which made the file "never installed" and every later update re-add it.
        """
        ds = self.merged_update_branch("merge")
        self.assertEqual(template.never_installed(ds, Manifest.load(ds)), set())
        res = self.run_update(ds, to="v0.2.0", dry_run=True)
        self.assertEqual(res.of(ADD, UPDATE, REMOVE, CONFLICT), [], "nothing to re-add")
        self.assertEqual([(a.path, a.kind, a.reason) for a in res.actions if a.path == "tools/fixture/new-script.sh"],
                         [("tools/fixture/new-script.sh", KEEP, "kept_deleted")])
        self.assertFalse(any("never in this repository" in w for w in res.warnings), res.warnings)
        res = self.run_update(ds)  # what template-sync runs: the latest release is the current version
        self.assertEqual(res.of(ADD, UPDATE, REMOVE, CONFLICT), [])
        self.assertEqual(git(ds, "status", "--porcelain", "--", "tools", ".github"), "",
                         "a clean tree: template-sync opens no pull request")

    def test_never_installed_reads_the_full_history(self):
        """Every commit reachable from HEAD counts, merged side branches and merge resolutions included."""
        type(self).counter += 1
        repo = self.base / f"history-{self.counter}"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "commit", "-q", "--allow-empty", "-m", "root")
        git(repo, "checkout", "-q", "-b", "side")
        write(repo / "x" / "side.txt", "added and deleted on a merged branch\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add on side")
        git(repo, "rm", "-q", "x/side.txt")
        git(repo, "commit", "-q", "-m", "delete on side")
        git(repo, "checkout", "-q", "main")
        write(repo / "x" / "main.txt", "main\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "work on main")
        git(repo, "branch", "other")
        # A merge whose resolution adds x/merge.txt (in neither parent) …
        git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
        write(repo / "x" / "merge.txt", "only in a merge resolution\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "merge side")
        # … and a later merge whose resolution drops it again.
        git(repo, "checkout", "-q", "other")
        write(repo / "x" / "other.txt", "other\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "work on other")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "--no-commit", "other")
        git(repo, "rm", "-q", "x/merge.txt")
        git(repo, "commit", "-q", "-m", "merge other")
        entry = template.Entry("0" * 64, "100644")
        base = Manifest(template="t", version="0.1.0",
                        files={p: entry for p in ("x/side.txt", "x/merge.txt", "x/never.txt", "x/main.txt")})
        self.assertEqual(template.never_installed(repo, base), {"x/never.txt"})

    def test_deletion_in_a_squashed_branch_is_reinstalled(self):
        """docs/UPGRADING.md §2: after a squash merge the file was never in main's history, so it is new."""
        ds = self.merged_update_branch("squash")
        self.assertEqual(template.never_installed(ds, Manifest.load(ds)), {"tools/fixture/new-script.sh"})
        res = self.run_update(ds, to="v0.2.0", dry_run=True)
        self.assertEqual([a.path for a in res.of(ADD)], ["tools/fixture/new-script.sh"])

    def test_shallow_clone_trusts_the_base(self):
        """A shallow clone cannot show old deletions, so the base manifest decides as before."""
        ds = self.downstream()
        write(ds / "books" / "later.md", "a later commit\n")
        git(ds, "add", "-A")
        git(ds, "commit", "-q", "-m", "Later")
        clone = self.base / f"shallow-{self.counter}"
        subprocess.run(["git", "clone", "-q", "--depth", "1", ds.resolve().as_uri(), str(clone)], check=True,
                       capture_output=True)
        self.assertFalse((clone / "tools" / "fixture" / "deleted-locally.txt").exists())
        self.assertEqual(template.never_installed(clone, Manifest.load(clone)), set())
        self.assertEqual(self.kinds(self.run_update(clone, dry_run=True))["tools/fixture/deleted-locally.txt"], KEEP)

    def test_adoption_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(TemplateError, r"copy tbook, tools/ and template\.toml .*UPGRADING\.md §5"):
                TemplateConfig.load(Path(tmp))


# --------------------------------------------------------------------------- tests: never downgrade


class NoDowngradeTests(TemplateFixture):
    """Without --to, an update never goes back (an older release, or the same version from another snapshot)."""

    def test_latest_release_older_than_a_prerelease(self):
        type(self).counter += 1
        ds = make_downstream(self.base, self.tpl, f"rc-{self.counter}", "v0.3.0-rc.1", local_work=False)
        before = tree_snapshot(ds)
        lines: list[str] = []
        rc = template.cmd_update(ds, to=None, source=str(self.tpl), dry_run=False, force=False, out=lines.append)
        self.assertEqual(rc, template.EXIT_OK)
        after = tree_snapshot(ds)
        after.pop("build/template-update.md")
        self.assertEqual(after, before, "nothing changed")
        self.assertEqual(git(ds, "status", "--porcelain"), "", "template-sync finds nothing to propose")
        summary = (ds / "build" / "template-update.md").read_text(encoding="utf-8")
        self.assertIn("## Template 0.3.0-rc.1: no update", summary)
        self.assertIn("The latest release (0.2.0) is older than this repository's template version 0.3.0-rc.1",
                      summary)
        self.assertIn("`--to 0.2.0`", summary)
        res = self.run_update(ds, dry_run=True)
        self.assertEqual((res.no_update, res.actions, res.exit_code, res.changed), ("not_newer_older", [], 0, False))
        # An explicit --to still downgrades, with a warning.
        res = self.run_update(ds, to="0.2.0", dry_run=True)
        self.assertEqual(res.no_update, "")
        self.assertTrue(any("downgrade" in w for w in res.warnings))
        self.assertEqual(self.kinds(res)["tools/fixture/replace.txt"], UPDATE)

    def test_same_version_from_another_snapshot(self):
        """A repository created from the template's main branch between releases (same version number)."""
        main = self.template_clone("tpl-main", "v0.2.0")
        write(main / "tools" / "fixture" / "replace.txt", "v2 plus a fix on main\n")
        write(main / "docs" / "NEXT.md", "on main only\n")
        commit_all(main, "main after 0.2.0 (version unchanged)")
        type(self).counter += 1
        ds = make_downstream(self.base, main, f"from-main-{self.counter}", "HEAD", local_work=False)
        before = tree_snapshot(ds)
        res = self.run_update(ds, source=str(main))
        self.assertEqual((res.no_update, res.actions, res.exit_code), ("not_newer_same", [], 0))
        self.assertEqual(tree_snapshot(ds), before)
        text = template.render_summary(res, "en")
        self.assertIn("another snapshot", text)
        self.assertIn("模板 0.2.0：无需升级", template.render_summary(res, "zh"))
        # --to re-syncs with the release on purpose.
        res = self.run_update(ds, source=str(main), to="0.2.0", dry_run=True)
        self.assertEqual(self.kinds(res)["tools/fixture/replace.txt"], UPDATE)
        self.assertIn(("docs/NEXT.md", REMOVE), {(a.path, a.kind) for a in res.actions})

    def test_newer_release_still_updates(self):
        ds = self.downstream()
        res = self.run_update(ds, dry_run=True)
        self.assertEqual((res.no_update, res.old_version, res.new_version), ("", "0.1.0", "0.2.0"))


# --------------------------------------------------------------------------- tests: migrations


MIGRATION_NEW_CODE = '''\
import os

from tbook import newmod, paths


def migrate(root):
    return [f"const={newmod.NEW_CONST}", f"root={paths.ROOT}", f"cwd={os.getcwd()}", f"file={paths.__file__}"]
'''


class MigrationProcessTests(TemplateFixture):
    """Migrations import tbook from the new template (tools/migrations/README.md), in a fresh process."""

    def template_040(self, migration: str) -> Path:
        """v0.4.0 on top of v0.2.0: tbook.paths gains NEW_CONST, a new module uses it, one migration."""
        tpl = self.template_clone("tpl-040", "v0.2.0")
        set_version(tpl, "0.4.0")
        with (tpl / "tools" / "tbook" / "paths.py").open("a", encoding="utf-8") as fh:
            fh.write('\nNEW_CONST = "new"\n')
        write(tpl / "tools" / "tbook" / "newmod.py", "from .paths import NEW_CONST\n")
        (tpl / "tools" / "migrations" / "v0.3.0.py").unlink()
        write(tpl / "tools" / "migrations" / "v0.4.0.py", migration)
        commit_all(tpl, "template 0.4.0", "v0.4.0")
        return tpl

    def test_migration_imports_the_new_modules(self):
        tpl = self.template_040(MIGRATION_NEW_CODE)
        type(self).counter += 1
        ds = make_downstream(self.base, self.tpl, f"mig-{self.counter}", "v0.2.0", local_work=False)
        res = self.run_update(ds, source=str(tpl))
        self.assertEqual(res.errors, [])
        self.assertEqual([m[0] for m in res.migrations], ["v0.4.0.py"])
        notes = dict(n.split("=", 1) for n in res.migrations[0][1])
        self.assertEqual(notes["const"], "new", "tbook.paths and the new module are the new template's")
        self.assertEqual(Path(notes["root"]).resolve(), ds.resolve(), "tbook.paths.ROOT is the repository")
        self.assertEqual(Path(notes["cwd"]).resolve(), ds.resolve())
        imported = Path(notes["file"]).resolve()
        self.assertEqual(imported.parts[-4:], ("template", "tools", "tbook", "paths.py"), "the fetched template")
        self.assertFalse(imported.is_relative_to(ds.resolve()))
        self.assertFalse(imported.is_relative_to(REAL_ROOT.resolve()))
        self.assertFalse(hasattr(paths, "NEW_CONST"), "this process keeps the modules it imported")

    def test_failing_migration(self):
        tpl = self.template_040('def migrate(root):\n    raise RuntimeError("boom")\n')
        type(self).counter += 1
        ds = make_downstream(self.base, self.tpl, f"mig-{self.counter}", "v0.2.0", local_work=False)
        with redirect_stderr(io.StringIO()) as err:
            res = self.run_update(ds, source=str(tpl))
        self.assertEqual(res.errors, ["v0.4.0.py failed: RuntimeError: boom"])
        self.assertEqual(res.exit_code, template.EXIT_ERROR)
        self.assertIn("Traceback", err.getvalue())
        self.assertIn("RuntimeError: boom", err.getvalue())


# --------------------------------------------------------------------------- tests: status, manifest


class StatusTests(TemplateFixture):
    def test_status_lists_modified_missing_extra(self):
        ds = self.downstream()
        write(ds / "tools" / "fixture" / "untracked-extra.txt", "x\n")
        write(ds / "skills" / "local-other" / "SKILL.md", "excluded: not extra\n")
        st = template.compute_status(ds)
        self.assertEqual(st.version, "0.1.0")
        self.assertIn("tools/fixture/both.txt", st.modified)
        self.assertIn("tools/fixture/kept.txt", st.modified)
        self.assertIn("tools/fixture/deleted-locally.txt", st.missing)
        self.assertIn("tools/fixture/new-different.txt", st.extra)
        self.assertIn("tools/fixture/untracked-extra.txt", st.extra)
        self.assertFalse(any(p.startswith(("skills/local-", "books/", "docs/project/")) for p in st.extra))
        self.assertNotIn("site.toml", st.modified)
        lines: list[str] = []
        self.assertEqual(template.cmd_status(ds, out=lines.append), 0)
        out = "\n".join(lines)
        self.assertIn("Template: trureturing-books-template 0.1.0", out)
        self.assertIn("  M tools/fixture/both.txt", out)
        self.assertIn("  D tools/fixture/deleted-locally.txt", out)
        self.assertIn("  ? tools/fixture/untracked-extra.txt", out)

    def test_status_clean_and_ignored_files(self):
        ds = make_downstream(self.base, self.tpl, "pristine", local_work=False)
        write(ds / "tools" / "tbook" / "__pycache__" / "x.cpython-313.pyc", "ignored\n")
        st = template.compute_status(ds)
        self.assertEqual((st.modified, st.missing, st.extra, st.pending), ([], [], [], []))
        lines: list[str] = []
        template.cmd_status(ds, out=lines.append)
        self.assertIn("Managed files match the manifest.", lines)

    def test_status_without_manifest(self):
        ds = self.downstream()
        (ds / "template-manifest.json").unlink()
        lines: list[str] = []
        self.assertEqual(template.cmd_status(ds, out=lines.append), 0)
        self.assertIn("No template-manifest.json", "\n".join(lines))


class ManifestTests(TemplateFixture):
    def test_manifest_contents(self):
        m = Manifest.load(self.tpl_dir())
        self.assertEqual(m.schema, template.MANIFEST_SCHEMA)
        self.assertEqual(m.template, "trureturing-books-template")
        self.assertNotIn("template.toml", m.files)
        self.assertNotIn("template-manifest.json", m.files)
        self.assertNotIn("site.toml", m.files)
        self.assertFalse(any(p.startswith(("books/", "skills/local-", "docs/project/")) for p in m.files))
        self.assertEqual(m.files["tbook"].mode, "100755")
        self.assertEqual(m.files["AGENTS.md"].mode, "120000")
        self.assertEqual(m.files["AGENTS.md"].sha256, sha("CLAUDE.md"), "symlinks are hashed by their target")
        self.assertEqual(m.files[".claude/skills"].mode, "120000")
        self.assertEqual(m.files["CLAUDE.md"].mode, "100644")
        self.assertEqual(m.files["CLAUDE.md"].sha256,
                         hashlib.sha256((self.tpl_dir() / "CLAUDE.md").read_bytes()).hexdigest())
        raw = (self.tpl_dir() / "template-manifest.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        self.assertEqual(list(data), ["schema", "template", "version", "files"])
        self.assertEqual(list(data["files"]), sorted(data["files"]), "paths are sorted")
        self.assertTrue(raw.endswith("}\n"))

    def tpl_dir(self) -> Path:
        out = self.base / "manifest-check"
        if not out.exists():
            subprocess.run(["git", "clone", "-q", str(self.tpl), str(out)], check=True)
            git(out, "checkout", "-q", "v0.1.0")
        return out

    def test_check_detects_stale_manifest(self):
        root = self.base / "manifest-stale"
        subprocess.run(["git", "clone", "-q", str(self.tpl), str(root)], check=True)
        lines: list[str] = []
        self.assertEqual(template.cmd_manifest(root, check=True, out=lines.append), 0, lines)
        write(root / "docs" / "CHANGELOG.md", "changed\n")
        write(root / "tools" / "brand-new.py", "x = 1\n")  # untracked, not ignored: counts
        write(root / "tools" / "tbook" / "__pycache__" / "y.pyc", "ignored\n")
        (root / "docs" / "AUTHORING.md").unlink()
        os.chmod(root / "docs" / "PUBLISHING.md", 0o755)
        set_version(root, "0.4.0")
        lines = []
        self.assertEqual(template.cmd_manifest(root, check=True, out=lines.append), 1)
        out = "\n".join(lines)
        self.assertIn("out of date", out)
        self.assertIn("  ~ docs/CHANGELOG.md", out)
        self.assertIn("  + tools/brand-new.py", out)
        self.assertIn("  - docs/AUTHORING.md", out)
        self.assertIn("  ~ docs/PUBLISHING.md (mode 100644 → 100755)", out)
        self.assertIn("  version: 0.3.0-rc.1 → 0.4.0", out)
        self.assertNotIn("pyc", out)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(template.cmd_manifest(root, out=lambda s: None), 0)
        self.assertEqual(template.cmd_manifest(root, check=True, out=lambda s: None), 0)
        self.assertEqual(Manifest.load(root).version, "0.4.0")

    def test_manifest_without_git_walks_the_tree(self):
        root = self.base / "manifest-nogit"
        if not root.exists():
            shutil.copytree(self.tpl_at_plain(), root, symlinks=True)
        write(root / "tools" / "tbook" / "__pycache__" / "z.pyc", "skipped\n")
        cfg = TemplateConfig.load(root)
        walked = template.build_manifest(root, cfg)
        self.assertEqual(walked.files, Manifest.load(root).files)

    def tpl_at_plain(self) -> Path:
        out = self.base / "plain-v0.1.0"
        if not out.exists():
            out.mkdir()
            archive = subprocess.run(["git", "-C", str(self.tpl), "archive", "v0.1.0"], capture_output=True,
                                     check=True)
            subprocess.run(["tar", "-x", "-C", str(out)], input=archive.stdout, check=True)
        return out

    def test_unreadable_manifest(self):
        root = self.base / "manifest-bad"
        subprocess.run(["git", "clone", "-q", str(self.tpl), str(root)], check=True)
        write(root / "template-manifest.json", '{"schema": "something-else"}')
        lines: list[str] = []
        self.assertEqual(template.cmd_manifest(root, check=True, out=lines.append), 1)
        self.assertIn("unsupported schema", "\n".join(lines))


# --------------------------------------------------------------------------- unit tests (no repositories)


class UnitTests(unittest.TestCase):
    def test_semver_order(self):
        versions = ["0.10.0", "0.2.0", "1.0.0", "1.0.0-rc.1", "1.0.0-alpha", "1.0.0-alpha.2", "1.0.0-alpha.10",
                    "0.2.1", "1.0.0-beta"]
        ordered = sorted(versions, key=template.parse_semver)
        self.assertEqual(ordered, ["0.2.0", "0.2.1", "0.10.0", "1.0.0-alpha", "1.0.0-alpha.2", "1.0.0-alpha.10",
                                   "1.0.0-beta", "1.0.0-rc.1", "1.0.0"])
        self.assertIsNone(template.parse_semver("1.0"))
        self.assertIsNone(template.parse_semver("v1.0.0"))
        self.assertEqual(template.parse_semver("1.2.3+build.5"), template.parse_semver("1.2.3"))
        self.assertTrue(template.is_prerelease("1.0.0-rc.1"))
        self.assertFalse(template.is_prerelease("1.0.0"))

    def test_release_tags_and_targets(self):
        tags = {"v0.1.0": "a", "v0.10.0": "b", "v0.9.0": "c", "v1.0.0-rc.1": "d", "book-v2.0.0": "e", "vX": "f"}
        self.assertEqual([t for t, _ in template.release_tags(tags, "v")],
                         ["v0.1.0", "v0.9.0", "v0.10.0", "v1.0.0-rc.1"])
        self.assertEqual(template.resolve_target(None, tags, "v", "src"), ("refs/tags/v0.10.0", "v0.10.0"))
        self.assertEqual(template.resolve_target("0.9.0", tags, "v", "src"), ("refs/tags/v0.9.0", "v0.9.0"))
        self.assertEqual(template.resolve_target("v1.0.0-rc.1", tags, "v", "src")[1], "v1.0.0-rc.1")
        self.assertEqual(template.resolve_target("main", tags, "v", "src"), ("main", "main"))
        with self.assertRaises(TemplateError):
            template.resolve_target("2.0.0", tags, "v", "src")
        with self.assertRaises(TemplateError):
            template.resolve_target(None, {"v1.0.0-rc.1": "d"}, "v", "src")
        self.assertEqual(template.resolve_target(None, {"release-1.2.3": "x"}, "release-", "src")[1], "release-1.2.3")

    def test_path_rules(self):
        cfg = TemplateConfig(name="t", repo="o/r", version="1.0.0",
                             managed=["tools/", "tbook", "docs/", ".github/workflows/"],
                             owned=["books/", "site.toml"], exclude=["skills/local-", "docs/project/"])
        self.assertTrue(cfg.manages("tools/tbook/cli.py"))
        self.assertTrue(cfg.manages("tbook"))
        self.assertFalse(cfg.manages("tbook-extra"))
        self.assertFalse(cfg.manages("toolsx/a"))
        self.assertTrue(cfg.manages("docs/AUTHORING.md"))
        self.assertFalse(cfg.manages("docs/project/notes.md"))
        self.assertTrue(cfg.is_excluded("skills/local-mine/SKILL.md"))
        self.assertFalse(cfg.manages("books/x/book.toml"))
        self.assertFalse(cfg.manages("template.toml"))
        self.assertFalse(cfg.manages("tools/a.py.template-new"))
        self.assertTrue(cfg.protects("site.toml"))
        self.assertTrue(cfg.protects("docs/project/a.md"))
        self.assertFalse(cfg.protects("docs/a.md"))

    def test_config_errors(self):
        with self.assertRaisesRegex(TemplateError, "version is required"):
            TemplateConfig.from_bytes(b"[template]\nname='x'\n[managed]\npaths=['a/']\n")
        with self.assertRaisesRegex(TemplateError, "paths is required"):
            TemplateConfig.from_bytes(b"[template]\nversion='1.0.0'\n")
        with self.assertRaisesRegex(TemplateError, "list of strings"):
            TemplateConfig.from_bytes(b"[template]\nversion='1.0.0'\n[managed]\npaths=['a/']\nowned='x'\n")
        with self.assertRaisesRegex(TemplateError, "template.toml"):
            TemplateConfig.from_bytes(b"[template\n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(TemplateError, "docs/UPGRADING.md"):
                TemplateConfig.load(Path(tmp))

    def test_changelog_sections(self):
        text = textwrap.dedent("""\
            # Changelog

            intro

            ## [Unreleased]

            - pending

            ## [0.3.0] - 2026-12-01

            - three

            ## [0.2.0] - 2026-11-20

            - two

            ## [0.1.0] - 2026-11-08

            - one
            """)
        out = template.changelog_sections(text, "0.1.0", "0.3.0")
        self.assertIn("## [0.3.0]", out)
        self.assertIn("- two", out)
        self.assertNotIn("one", out)
        self.assertNotIn("pending", out)
        self.assertNotIn("intro", out)
        self.assertEqual(template.changelog_sections(text, "0.3.0", "0.3.0"), "")

    def test_find_migrations(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ("v0.1.0.py", "v0.2.0.py", "v0.10.0.py", "v1.0.0-rc.1.py", "v1.0.0.py", "README.md",
                         "helper.py", "v2.py"):
                write(d / name, "def migrate(root):\n    return []\n")
            names = [m.name for m in template.find_migrations(d, "0.1.0", "1.0.0")]
            self.assertEqual(names, ["v0.2.0.py", "v0.10.0.py", "v1.0.0-rc.1.py", "v1.0.0.py"])
            self.assertEqual(template.find_migrations(d, "1.0.0", "0.2.0"), [], "no migrations on a downgrade")
            self.assertEqual(template.find_migrations(d, "dev", "1.0.0"), [])
            write(d / "v3.0.0.py", "x = 1\n")
            mig = template.find_migrations(d, "2.0.0", "3.0.0")[0]
            with self.assertRaisesRegex(TemplateError, "no migrate"):
                template.run_migration(mig, d)
            write(d / "v3.0.0.py", "def migrate(root):\n    return 'one note'\n")
            self.assertEqual(template.run_migration(mig, d), ["one note"])

    def test_file_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write(d / "a.txt", "hello", 0o644)
            write(d / "b.sh", "#!/bin/sh\n", 0o755)
            os.symlink("a.txt", d / "link")
            os.symlink("missing-target", d / "dangling")
            (d / "dir").mkdir()
            self.assertEqual(template.file_entry(d / "a.txt"), template.Entry(sha("hello"), "100644"))
            self.assertEqual(template.file_entry(d / "b.sh").mode, "100755")
            self.assertEqual(template.file_entry(d / "link"), template.Entry(sha("a.txt"), "120000"))
            self.assertEqual(template.file_entry(d / "dangling"), template.Entry(sha("missing-target"), "120000"))
            self.assertEqual(template.file_entry(d / "dir").mode, template.MODE_OTHER)
            self.assertIsNone(template.file_entry(d / "nope"))

    def test_main_dispatch_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = mock.Mock(template_cmd="status", layer=None)
            with mock.patch.object(paths, "ROOT", Path(tmp)), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(template.main(args), 1)
            self.assertIn("template.toml not found", err.getvalue())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(template.main(mock.Mock(template_cmd="bogus", layer=None)), 1)

    def test_language_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"TBOOK_LANG": ""}):
                self.assertEqual(template._lang(root), "en")
                write(root / "site.toml", '[site]\nlanguages = ["zh-Hant", "en"]\n')
                self.assertEqual(template._lang(root), "zh")
                write(root / "site.toml", '[site]\nlanguages = ["fr", "en"]\n')
                self.assertEqual(template._lang(root), "en")
            with mock.patch.dict(os.environ, {"TBOOK_LANG": "zh"}):
                self.assertEqual(template._lang(root), "zh")
        for lang in template.STRINGS:
            self.assertEqual(set(template.STRINGS[lang]), set(template.STRINGS["en"]), lang)


class RealRepositoryTests(unittest.TestCase):
    """Properties of this repository's own template.toml / manifest."""

    def test_real_template_toml(self):
        cfg = TemplateConfig.load(REAL_ROOT)
        self.assertEqual(cfg.tag_prefix, "v")
        self.assertIsNotNone(template.parse_semver(cfg.version))
        for owned in ("books/", "site.toml", "trureturing.lock.json"):
            self.assertIn(owned, cfg.owned)
            self.assertFalse(cfg.manages(owned))
        self.assertTrue(cfg.manages("tools/tbook/template.py"))
        self.assertTrue(cfg.manages(".github/workflows/ci.yml"))

    # CONFIG GAP (template.toml): the workflows use the composite action .github/actions/setup, which is
    # not under [managed].paths, so template updates would never deliver changes to it.
    # Patch: add ".github/actions/" after ".github/workflows/" in template.toml [managed].paths
    # (and in docs/UPGRADING.md §1).
    def test_setup_action_is_managed(self):
        self.assertTrue(TemplateConfig.load(REAL_ROOT).manages(".github/actions/setup/action.yml"))

    def test_real_manifest_is_well_formed(self):
        m = Manifest.load(REAL_ROOT)
        if m is None:
            self.skipTest("template-manifest.json not generated yet")
        cfg = TemplateConfig.load(REAL_ROOT)
        self.assertEqual(m.template, cfg.name)
        for p, e in m.files.items():
            self.assertTrue(cfg.manages(p), p)
            self.assertIn(e.mode, ("100644", "100755", "120000"), p)
            self.assertRegex(e.sha256, r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- tests: workflows


WORKFLOWS = REAL_ROOT / ".github" / "workflows"


def _mapping(lines: list[str], i: int, indent: int) -> dict[str, str]:
    """The flat ``key: value`` block below ``lines[i]`` (indented deeper than ``indent``)."""
    head = lines[i].split(":", 1)[1].split("#")[0].strip()
    if head:  # permissions: read-all | write-all | {}
        return {"*": head}
    out: dict[str, str] = {}
    for line in lines[i + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        key, _, value = line.strip().partition(":")
        out[key.strip()] = value.split("#")[0].strip().strip("'\"")
    return out


def read_workflow(path: Path) -> tuple[dict[str, str] | None, dict[str, dict]]:
    """``(top-level permissions, {job: {"permissions": dict | None, "uses": [action refs]}})``.

    A reader for the layout of these workflows (two-space indentation, block mappings), not general YAML.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    top: dict[str, str] | None = None
    jobs: dict[str, dict] = {}
    job: dict | None = None
    in_jobs = False
    for i, line in enumerate(lines):
        if re.match(r"^\S", line) and not line.startswith("#"):
            in_jobs = line.startswith("jobs:")
            job = None
            if line.startswith("permissions:"):
                top = _mapping(lines, i, 0)
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            job = jobs.setdefault(m.group(1), {"permissions": None, "uses": []})
        elif job is not None:
            if re.match(r"^    permissions:", line):
                job["permissions"] = _mapping(lines, i, 4)
            m = re.match(r"^\s+(?:- )?uses:\s*['\"]?([^'\"\s#]+)", line)
            if m:
                job["uses"].append(m.group(1))
    return top, jobs


def granted(perms: dict[str, str], scope: str) -> str:
    """The access level ``perms`` (a permissions block) gives ``scope``: none, read or write."""
    if "*" in perms:
        return {"read-all": "read", "write-all": "write"}.get(perms["*"], "none")
    return perms.get(scope, "none")


def release_plan_script() -> str:
    """The Python script of release.yml's "Resolve the tag" step (id: plan)."""
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    m = re.search(r"\n\s+id: plan\n.*?python3 - <<'PY'\n(.*?)\n\s*PY\n", text, re.S)
    assert m, "release.yml: the plan step's script was not found"
    return textwrap.dedent(m.group(1))


def run_release_plan(root: Path, tag: str, *, template_repo: bool = False) -> tuple[int, dict[str, str], str]:
    """Run the plan step for ``tag`` in the repository ``root``: (exit code, step outputs, log)."""
    out = root / "build" / "github-output.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    env = dict(os.environ, TAG=tag, TEMPLATE_REPO="true" if template_repo else "false", GITHUB_OUTPUT=str(out),
               PYTHONPATH=str(root / "tools"), TBOOK_ROOT=str(root))
    r = subprocess.run([sys.executable, "-"], input=release_plan_script(), cwd=root, env=env, capture_output=True,
                       text=True)
    outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines() if "=" in line)
    return r.returncode, outputs, r.stdout + r.stderr


class WorkflowTests(unittest.TestCase):
    def test_jobs_have_the_permissions_their_actions_need(self):
        """A job-level permissions block replaces the top-level one: it must grant what its actions use."""
        needs = {
            "actions/checkout": [("contents", ("read", "write"))],
            # GET /repos/{owner}/{repo}/pages: refused without Pages access in private repositories.
            "actions/configure-pages": [("pages", ("read", "write"))],
            "actions/deploy-pages": [("pages", ("write",)), ("id-token", ("write",))],
        }
        seen = set()
        for wf in sorted(WORKFLOWS.glob("*.yml")):
            top, jobs = read_workflow(wf)
            self.assertIsNotNone(top, f"{wf.name}: set top-level permissions")
            for name, job in jobs.items():
                perms = job["permissions"] if job["permissions"] is not None else top
                for uses in job["uses"]:
                    action = uses.split("@")[0]
                    for scope, levels in needs.get(action, []):
                        seen.add(action)
                        self.assertIn(granted(perms, scope), levels,
                                      f"{wf.name}, job {name}: {action} needs {scope}: {' or '.join(levels)}")
        self.assertEqual(seen, set(needs), "the reader found every action it checks")

    def test_called_workflows_get_the_permissions_they_ask_for(self):
        """A reusable workflow's token has at most what its caller's job grants; a job of the called workflow
        that asks for more makes the whole run fail (template-release.yml calls ci.yml, whose build and media
        jobs read the Pages configuration)."""
        rank = {"none": 0, "read": 1, "write": 2}
        calls = 0
        for wf in sorted(WORKFLOWS.glob("*.yml")):
            top, jobs = read_workflow(wf)
            for name, job in jobs.items():
                for uses in job["uses"]:
                    m = re.fullmatch(r"\./\.github/workflows/([\w.-]+)", uses)
                    if not m:
                        continue
                    calls += 1
                    given = job["permissions"] if job["permissions"] is not None else top
                    called_top, called_jobs = read_workflow(WORKFLOWS / m.group(1))
                    for called_name, called in called_jobs.items():
                        asked = called["permissions"] if called["permissions"] is not None else called_top
                        scopes = {"contents", "pages", "id-token", "pull-requests", "actions"} if "*" in asked else asked
                        for scope in scopes:
                            self.assertLessEqual(rank[granted(asked, scope)], rank[granted(given, scope)],
                                                 f"{wf.name}, job {name} calls {m.group(1)}: its job {called_name} "
                                                 f"asks for {scope}: {granted(asked, scope)}")
        self.assertGreaterEqual(calls, 2, "release.yml calls lean-verify.yml, template-release.yml calls ci.yml")

    def test_films_are_built_with_the_site(self):
        """Films are build units like the others (pages.yml, release.yml): there is no film workflow and no
        film-* release tag (release.yml's plan only recognises a legacy one to skip it: test_release_plan)."""
        self.assertFalse((WORKFLOWS / "film.yml").exists())
        for path in sorted((WORKFLOWS.parent).rglob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if path.name == "release.yml":  # the plan's skip of legacy per-film tags
                text = re.sub(r'(?ms)^ *elif tag\.startswith\("film-"\):\n.*?sys\.exit\(0\)\n', "", text)
            self.assertNotRegex(text, r"film\.yml|['\"!]film-|\bfilm-(\*|<|\$\{\{)", path.name)
        text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        tags = re.search(r"(?m)^on:\n  push:\n    tags:\n((?:      - .*\n)+)", text).group(1)
        self.assertEqual(re.findall(r"- '([^']*)'", tags), ["*-v*", "v*"])

    def test_reader(self):
        _, jobs = read_workflow(WORKFLOWS / "pages.yml")
        self.assertEqual(set(jobs), {"probe", "build", "deploy"})
        self.assertEqual(jobs["deploy"]["permissions"], {"pages": "write", "id-token": "write"})
        self.assertTrue(any(u.startswith("actions/configure-pages@") for u in jobs["build"]["uses"]), jobs["build"]["uses"])


class NoBooksTests(unittest.TestCase):
    """Books repositories may delete books/example-monograph (skills/book-new) and may have no book yet.

    What ci.yml and pages.yml run must then pass: there is nothing to build, which is not an error.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tbook-nobooks-"))
        cls.env = dict(os.environ, TBOOK_PYTHON=sys.executable)
        cls.env.pop("TBOOK_ROOT", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def repository(self, name: str) -> Path:
        root = self.tmp / name
        root.mkdir()
        copy_real_managed(root, example=False)
        site = root / "site.toml"
        site.write_text(re.sub(r"(?ms)^order\s*=\s*\[.*?\]", "order = []", site.read_text(encoding="utf-8")),
                        encoding="utf-8")
        return root

    def run_ok(self, root: Path, *cmd: str) -> str:
        r = subprocess.run(list(cmd), cwd=root, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"{' '.join(cmd)}:\n{r.stdout}{r.stderr}")
        return r.stdout + r.stderr

    def test_ci_and_pages_commands(self):
        root = self.repository("zero")
        tbook = str(root / "tbook")
        self.assertIn("0 book(s), 0 error(s)", self.run_ok(root, tbook, "check"))
        self.run_ok(root, tbook, "theme", "--check")
        self.run_ok(root, tbook, "build", "html", "pdf", "epub")  # ci.yml build job
        self.run_ok(root, tbook, "build", "films")  # ci.yml media job
        self.run_ok(root, tbook, "build", "all")  # pages.yml, release.yml
        self.assertTrue((root / "_site" / "index.html").is_file())
        # the build cache: .github/actions/build-cache (save) and release.yml (export)
        self.run_ok(root, tbook, "cache", "prune")
        self.assertRegex(self.run_ok(root, tbook, "cache", "key").strip(), r"^build-cache-v1-[0-9a-f]{64}$")
        self.run_ok(root, tbook, "cache", "export", str(root / "release" / "cache"))
        manifest = json.loads((root / "release" / "cache" / "build-cache.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"], [])
        if shutil.which("node"):
            for script in ("viz-validate.mjs", "slides-check.mjs", "viz-test.mjs"):  # ci.yml check and media jobs
                self.run_ok(root, "node", str(root / "tools" / "node" / script))
        # ci.yml's media job builds slides only when a deck exists.
        self.assertEqual(list(root.glob("books/*/slides/*/slides.md")), [])

    def test_release_plan(self):
        root = self.repository("release")
        rc, outputs, log = run_release_plan(root, "v2026.11.08")
        self.assertEqual(rc, 1, "a release needs a book")
        self.assertIn("there are no books", log)
        self.assertEqual(run_release_plan(root, "v1.0.0", template_repo=True)[1].get("skip"), "true")
        self.run_ok(root, str(root / "tbook"), "new-book", "my-book", "--title", "zh=我的书", "--title", "en=My Book")
        # a per-film tag of template 0.1.0 (film-<slug>-<NNN>-v<k>) publishes nothing now: skipped, not failed
        rc, outputs, log = run_release_plan(root, "film-my-book-001-v1")
        self.assertEqual((rc, outputs.get("skip")), (0, "true"), log)
        self.assertIn("per-film tag", log)
        # Only a semantic-version pre-release is a GitHub pre-release; date tags are ordinary releases, a
        # same-day suffix included (2026.11.10-2 parses as a semantic version, but it is a date).
        for tag, pre in (("v2026.11.08", "false"), ("v2026-11-08", "false"), ("v20261108", "false"),
                         ("v2026.11.08-2", "false"), ("v2026.11.10-2", "false"), ("v2026.12.31-rc.1", "false"),
                         ("v2026-11-08-2", "false"), ("v2026.11.08.2", "false"), ("v20261108-2", "false"),
                         ("v3.0.0", "false"), ("v3.0.0+build.5", "false"), ("v3.0.0-rc.1", "true"),
                         ("v1.2.0-rc.1", "true"), ("v3.0.0-rc.1+b.5", "true"), ("v0.2.0-beta", "true"),
                         ("v1.02.0-rc.1", "false"), ("v2026.1.5-2", "true"),  # not zero-padded: no date
                         ("my-book-v0.1.0", "false")):
            rc, outputs, log = run_release_plan(root, tag)
            self.assertEqual(rc, 0, log)
            self.assertEqual((outputs["books"], outputs["prerelease"]), ("my-book", pre), tag)
        book_toml = root / "books" / "my-book" / "book.toml"
        for version, pre in (("0.2.0-beta.1", "true"), ("2026.11.10-2", "false")):  # one book: its book.toml version
            book_toml.write_text(re.sub(r'(?m)^version = "[^"]*"', f'version = "{version}"',
                                        book_toml.read_text(encoding="utf-8"), count=1), encoding="utf-8")
            rc, outputs, log = run_release_plan(root, f"my-book-v{version}")
            self.assertEqual((rc, outputs.get("prerelease")), (0, pre), log)


if __name__ == "__main__":
    unittest.main()
