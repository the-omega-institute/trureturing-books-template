"""Source-mode resolution against committed Lean files, and its book and media consumers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from tbook import check, config, film, lean, leanverify, ledger, model, paths, pin, render, viz
from test_core import CoreRepo, messages, write


REPO = "the-omega-institute/riemann-hypothesis"
GID = "Main.riemannHypothesis"
NESTED_GID = "Riemann/Divisors₂.NatFacts.divisors₂"
SOURCE_SITE = f'''[site]
languages = ["en"]

[trureturing]
repo = "{REPO}"
branch = "main"
mode = "lean-source"
source_root = "src/"
'''
MAIN = """\
namespace Riemann
section Local

theorem riemannHypothesis : True := by
  -- sorry
  /- admit /- nested sorry -/ -/
  trivial

private theorem hidden : False := by sorry

lemma proved : True := True.intro
def value : Nat := 1
abbrev alias := value
instance namedInstance : Inhabited Nat := ⟨0⟩
structure Record where
  value : Nat
class Witness where
  value : Nat
inductive Choice where
  | first
opaque answer : Nat := 42
axiom premise : True
theorem _root_.Outside.ok : True := True.intro

end Local
end Riemann

namespace Other
lemma proved : True := True.intro
theorem incomplete : True := by sorry
theorem admitted : True := by admit
end Other
"""
NESTED = """\
namespace NatFacts
theorem divisors₂ : True /- := where -/ := True.intro
end NatFacts
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class SourceSettingsTests(unittest.TestCase):
    def test_site_defaults_and_normalization(self):
        with CoreRepo("[site]\n") as repo:
            site = config.load_site()
            self.assertEqual((site.trureturing_mode, site.trureturing_source_root), ("frozen-state", ""))
            write(repo.root / "site.toml", SOURCE_SITE)
            config.load_site.cache_clear()
            site = config.load_site()
            self.assertEqual((site.trureturing_mode, site.trureturing_source_root), ("lean-source", "src"))

    def test_invalid_site_settings(self):
        for setting in ('mode = "source"', "mode = 42", 'source_root = "/src"', 'source_root = "src/../root"',
                        'source_root = ".."', "source_root = 42", r"source_root = 'src\Lean'"):
            with self.subTest(setting=setting), CoreRepo(f"[trureturing]\n{setting}\n"):
                with self.assertRaises(config.ConfigError):
                    config.load_site()

    def test_gids(self):
        for gid, module, name in [(GID, "Main", "riemannHypothesis"),
                                  (NESTED_GID, "Riemann/Divisors₂", "NatFacts.divisors₂"),
                                  ("Outer/Inner.«a.b»", "Outer/Inner", "«a.b»")]:
            with self.subTest(gid=gid):
                self.assertEqual(lean.parse_gid(f" {gid} ", mode="lean-source"), lean.Gid(module, name))
                with self.assertRaisesRegex(lean.LeanError, "D5/S1/Deficit"):
                    lean.parse_gid(gid)
        self.assertEqual(lean.parse_gid("D5/S1/Module.ρ₂"), lean.Gid("D5/S1/Module", "ρ₂"))
        self.assertEqual(lean.parse_gid(GID, mode="lean-source").source_path_for(), "Main.lean")
        for bad in ("Main", "Main.", ".x", "Main .x", "Main.a,b", "Main.«a b»", "Main.1x", "Main.a..b",
                    "Main/a-b.x", "/Main.x", "Outer//Main.x", "Outer/.x", "Outer.Part/Main.x", "«Main».x"):
            with self.subTest(bad=bad), self.assertRaisesRegex(lean.LeanError, "not a declaration GID"):
                lean.parse_gid(bad, mode="lean-source")
        with self.assertRaisesRegex(lean.LeanError, "unknown Lean source mode"):
            lean.parse_gid(GID, mode="unknown")

    def test_lock_round_trips_and_default_json(self):
        with CoreRepo() as repo:
            dest = repo.root / "lock.json"
            for cls, kwargs in [(lean.Lock, {"commit": "a" * 40}), (lean.BranchLock, {})]:
                for mode, root in [("frozen-state", ""), ("lean-source", ""), ("lean-source", "src"),
                                   ("frozen-state", "vendor")]:
                    with self.subTest(cls=cls, mode=mode, root=root):
                        lock = cls(repo=REPO, branch="main", mode=mode, source_root=root, **kwargs)
                        lock.save(dest)
                        data = json.loads(dest.read_text())
                        self.assertEqual(data.get("mode"), None if mode == "frozen-state" else mode)
                        self.assertEqual(data.get("source_root"), root or None)
                        self.assertEqual(lean.Lock.read_spec(dest), lock)
            default = lean.BranchLock(REPO, "main")
            default.save(dest)
            expected = {"schema": lean.LOCK_SCHEMA, "repo": REPO, "branch": "main"}
            self.assertEqual(dest.read_text(), json.dumps(expected, indent=2) + "\n")
            for fields in ({"mode": "other"}, {"source_root": []}, {"source_root": "/abs"},
                           {"source_root": "src/.."}, {"branch": None}, {"extra": True}):
                with self.subTest(fields=fields):
                    dest.write_text(json.dumps(expected | fields))
                    with self.assertRaises(lean.LeanError):
                        lean.Lock.read_spec(dest)


class LeanSourceTests(unittest.TestCase):
    def setUp(self):
        self.books = self.enterContext(CoreRepo(SOURCE_SITE))
        temp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="tbook-lean-source-")))
        self.source_repo = temp / "riemann-hypothesis"
        self.source_repo.mkdir()
        git(self.source_repo, "init", "-b", "main")
        git(self.source_repo, "config", "user.name", "Lean source test")
        git(self.source_repo, "config", "user.email", "test@example.com")
        write(self.source_repo / "src/Main.lean", MAIN)
        write(self.source_repo / "src/Riemann/Divisors₂.lean", NESTED)
        # A scope the lightweight scanner cannot follow, for the written-name fallback.
        write(self.source_repo / "src/Scoped.lean", "namespace\n  Outer\ntheorem inner : True := True.intro\nend Outer")
        self.commit = self.commit_sources()
        os.environ["TRURETURING_DIR"] = str(self.source_repo)
        self.ledger = lean.Ledger(REPO, offline=True, mode="lean-source", source_root="src/")

    def commit_sources(self) -> str:
        git(self.source_repo, "add", "src")
        git(self.source_repo, "commit", "-m", "Update fixture")
        return git(self.source_repo, "rev-parse", "HEAD")

    def resolve(self, gid: str) -> lean.Resolution:
        return lean.resolve(self.ledger, self.commit, gid)

    def test_discover_checkout_by_repository_name(self):
        del os.environ["TRURETURING_DIR"]
        trureturing = self.source_repo.parent / "trureturing"
        (trureturing / ".git").mkdir(parents=True)
        with mock.patch.object(paths, "ROOT", self.source_repo.parent / "books"):
            self.assertEqual(lean.Ledger(REPO, offline=True).checkout, self.source_repo)
            self.assertEqual(lean.Ledger("the-omega-institute/trureturing", offline=True).checkout, trureturing)
            self.assertIsNone(lean.Ledger("the-omega-institute/other", offline=True).checkout)

    def test_kinds_and_scopes(self):
        for name, kind in {
            "riemannHypothesis": "theorem", "Riemann.proved": "theorem", "value": "def",
            "alias": "def", "namedInstance": "def", "Record": "inductive", "Witness": "inductive",
            "Choice": "inductive", "answer": "opaque", "premise": "axiom", "Outside.ok": "theorem",
        }.items():
            with self.subTest(name=name):
                self.assertEqual(self.resolve(f"Main.{name}").kind, kind)
        self.assertEqual(self.resolve(GID).name, "Riemann.riemannHypothesis")
        self.assertEqual(self.resolve("Main.Outside.ok").name, "Outside.ok")
        self.assertEqual(self.resolve(NESTED_GID).name, "NatFacts.divisors₂")
        self.assertEqual(self.resolve("Scoped.Outer.inner").line, 3)
        self.assertEqual(self.resolve("Main.Record").signature, "structure Record")

    def test_errors_and_comment_handling(self):
        for gid, error in [
            ("Main.proved", "ambiguous, matches Riemann.proved, Other.proved"),
            ("Main.missing", "no declaration named"),
            ("Main.hidden", "no declaration named"),
            ("Missing.theorem", "source src/Missing.lean not found"),
            ("Main.incomplete", "declaration uses sorry/admit"),
            ("Main.admitted", "declaration uses sorry/admit"),
        ]:
            with self.subTest(gid=gid), self.assertRaisesRegex(lean.LeanError, error):
                self.resolve(gid)
        self.assertEqual(self.resolve(GID).signature, "theorem riemannHypothesis : True")
        self.assertEqual(self.resolve(NESTED_GID).signature, "theorem divisors₂ : True /- := where -/")

    def test_statement_digest_and_locate(self):
        initial = self.resolve(GID)
        with mock.patch.object(self.ledger, "read", side_effect=AssertionError("already located")):
            lean.locate(self.ledger, self.commit, initial)
        revised = MAIN.replace("riemannHypothesis : True := by", "riemannHypothesis   : True := by")
        write(self.source_repo / "src/Main.lean", revised.replace("  trivial", "  exact True.intro"))
        self.commit = self.commit_sources()
        self.assertEqual(self.resolve(GID).statement_id, initial.statement_id)
        write(self.source_repo / "src/Main.lean", revised.replace("riemannHypothesis   : True", "riemannHypothesis (n : Nat) : True"))
        self.commit = self.commit_sources()
        self.assertNotEqual(self.resolve(GID).statement_id, initial.statement_id)

    def book(self, gid: str = GID):
        book = self.books.book(langs=("en",), summaries={"en": "# Summary\n\n- [Chapter](chapter.md)\n"},
                               files={"en": {"chapter.md":
                                            f'# Chapter\n\n::: {{.theorem #thm-result lean="{gid}"}}\nTrue.\n:::\n'}})
        (book.dir / "assets" / "fig.svg").unlink()  # The fixture's optional image is unused here.
        return book

    def test_fixed_pin_check_ledger_and_viz(self):
        book = self.book()
        report = pin.pin(self.commit, offline=True)
        self.assertTrue(report.written, report.markdown())
        self.assertEqual(report.added, [GID])
        lock = lean.Lock.load()
        self.assertEqual((lock.mode, lock.source_root), ("lean-source", "src"))
        self.assertEqual(messages(check.run([book], offline=True), "error"), [])
        expected = f"https://github.com/{REPO}/blob/{self.commit}/src/Main.lean#L4"
        self.assertEqual(lock.source_url(GID), expected)
        self.assertEqual(lock.state_url(GID), expected)
        self.assertEqual(lock.blueprint_url(GID), "")
        self.assertEqual(render.lean_view(GID, lock)["url"], expected)
        self.assertEqual(render.lean_view(GID, None)["name"], GID)
        self.assertEqual(film.lean_refs([GID], lock)[0]["url"], expected)
        edition = model.load_edition(book.primary)
        markdown = ledger.ledger_markdown(edition, lock)
        self.assertIn(f"[\x60Riemann.riemannHypothesis\x60]({expected})", markdown)
        self.assertIn("Signature digest", markdown)

        page = book.viz_dir / "result" / "index.html"
        write(page, f'''<!DOCTYPE html>
<html data-title-en="Result"><head><title>Result</title>
<link rel="stylesheet" href="../assets/theme.css">
<script src="../assets/shell.js"></script></head>
<body data-viz-id="result"><a class="crumb" href="../">Back</a>
<button data-lang-set="zh">中文</button><button data-lang-set="en">English</button>
<div class="lean"><a data-lean-gid="{GID}">Theorem</a></div>
<a data-trureturing-path="src/Main.lean">Source file</a>
</body></html>
''')
        self.assertEqual(messages(viz.check_page(book, "result", page, {"result"}, lock=lock, ledger=self.ledger), "error"), [])
        pinned = viz.pin_links(page.read_text(), lock)
        self.assertIn(f'href="{expected}"', pinned)
        self.assertIn(f'href="{lock.blob("src/Main.lean")}"', pinned)
        self.assertEqual(leanverify.module_name("Riemann/Divisors₂"), "Riemann.Divisors₂")
        self.assertEqual(tomllib.loads(leanverify.lakefile_toml(lock))["require"][0]["name"], "riemann_hypothesis")

    def test_theorem_boxes_reject_non_theorems(self):
        for gid, kind in [("Main.value", "def"), ("Main.Record", "inductive")]:
            with self.subTest(gid=gid):
                book = self.book(gid)
                self.assertTrue(pin.pin(self.commit, offline=True).written)
                self.assertIn(f"{gid} is a Lean {kind}, but theorem-like environments must cite theorems",
                              messages(check.run([book], offline=True), "error"))

    def test_branch_lock_and_snapshot(self):
        self.book()
        with mock.patch.object(lean, "ls_remote", return_value=self.commit):
            self.assertTrue(pin.pin(follow=True).written)
        spec = lean.Lock.read_spec()
        self.assertEqual(spec, lean.BranchLock(REPO, "main", "lean-source", "src"))
        lock = pin.resolve_branch(spec, commit=self.commit, offline=True)
        self.assertIn(GID, lock.declarations)
        snapshot = self.books.root / "snapshot.json"
        lock.save(snapshot)
        os.environ["TBOOK_LOCK_SNAPSHOT"] = str(snapshot)
        self.assertEqual(lean.Lock.load(offline=True), lock)
        lock.source_root = ""
        lock.save(snapshot)
        with self.assertRaisesRegex(lean.LeanError, "snapshot does not match"):
            lean.Lock.load(offline=True)
        with self.assertRaisesRegex(lean.LeanError, "run ./tbook pin --follow"):
            pin.resolve_branch(lean.BranchLock(REPO, "main"), commit=self.commit, offline=True)

    def test_fixed_lock_settings_must_match_site(self):
        book = self.book()
        self.assertTrue(pin.pin(self.commit, offline=True).written)
        lock = lean.Lock.load()
        lock.source_root = "other"
        lock.save()
        self.assertIn("lock mode and source_root must match site.toml [trureturing]; run ./tbook pin",
                      messages(check.run([book], offline=True), "error"))

    @unittest.skipUnless(shutil.which("node"), "node is required for visualization and slide link tests")
    def test_node_gids_and_source_links(self):
        declaration = self.resolve(NESTED_GID)
        lock = lean.Lock(repo=REPO, branch="main", commit=self.commit, mode="lean-source", source_root="src",
                         declarations={NESTED_GID: declaration.to_lock()})
        script = """
import assert from 'node:assert/strict';
import { parseGid, leanUrl, pinLinks } from './tools/node/viz-common.mjs';
import { leanSourceUrl } from './tools/node/slides-lib.mjs';

const [input, gid, expected] = process.argv.slice(1);
const lock = JSON.parse(input);
lock.source_root += '/';
assert.deepEqual(parseGid(gid, lock), { module: 'Riemann/Divisors₂', name: 'NatFacts.divisors₂' });
assert.deepEqual(parseGid('Main.«a.b»', lock), { module: 'Main', name: '«a.b»' });
assert.equal(parseGid(gid), null);
assert.equal(parseGid('Main.riemannHypothesis'), null);
assert.ok(parseGid('D5/S1/Module.abc'));
for (const bad of ['Main.', 'Main.2bad', 'Main.a b', 'Main.a,b', 'Main//File.a', 'Main.«a b»']) {
  assert.equal(parseGid(bad, lock), null, bad);
}
assert.equal(leanUrl(lock, gid), expected);
assert.equal(leanSourceUrl(lock, gid), expected);
assert.ok(pinLinks('<a data-lean-gid="' + gid + '">Lean</a>', lock).includes(expected));
"""
        subprocess.run(["node", "--input-type=module", "-e", script, lock.document(), NESTED_GID,
                        lock.source_url(NESTED_GID)], cwd=Path(__file__).resolve().parents[2], check=True)


if __name__ == "__main__":
    unittest.main()
