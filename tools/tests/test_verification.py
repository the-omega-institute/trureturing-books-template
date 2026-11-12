"""Regression tests of the verification chain: branch ancestry of the pinned commit, GID syntax,
declaration lines, pin reports and the checks that compare editions and lock entries.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_verification.py'

Like ``test_core`` (whose fixtures are reused), every test runs in a throwaway books repository
and replaces trureturing with ``FakeLedger`` or with small git repositories made on the fly.
Nothing touches the network: GitHub's API is replaced by a fake ``urlopen``. Tests against the
real trureturing checkout are skipped when it (or the pinned commit) is absent.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tbook import check, config, lean, model, paths, pin
from test_core import (COMMIT, EN_SUMMARY, GID_3V, GID_DEF, GID_INT, MOD_3V, OLD_COMMIT, SITE, TRU,
                       ZH_SUMMARY, CoreRepo, FakeLedger, lock_decls, make_lock, media_stub, messages, name_key,
                       states, write)

GIT_ENV = dict(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
UPSTREAM = f"https://github.com/{TRU}.git"
# The trureturing commit the real-ledger examples below were taken from (independent of this repository's lock).
REAL_COMMIT = "8a24ea4e79de962725aab9d9b49cc605fcc211d8"


def real_checkout() -> Path | None:
    """A local trureturing checkout that has ``REAL_COMMIT`` (``$TRURETURING_DIR`` or ``../trureturing``)."""
    for cand in (os.environ.get("TRURETURING_DIR"), paths.ROOT.parent / "trureturing"):
        if not cand or not (Path(cand) / ".git").exists():
            continue
        r = subprocess.run(["git", "-C", str(cand), "cat-file", "-e", f"{REAL_COMMIT}^{{commit}}"], capture_output=True)
        if r.returncode == 0:
            return Path(cand)
    return None


REAL = real_checkout()


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], env=dict(os.environ, **GIT_ENV), capture_output=True,
                       text=True)
    if r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


class History:
    """A trureturing stand-in: ``dev`` = A ← B, and an unmerged commit C on top of A (a PR head)."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tbook-tru-")
        self.dir = d = Path(self._tmp.name)
        git(d, "init", "-q")
        git(d, "symbolic-ref", "HEAD", "refs/heads/dev")
        write(d / f"Golden/Frozen/state/{MOD_3V}.lean.json", json.dumps(states()[MOD_3V]))
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "A")
        self.a = git(d, "rev-parse", "HEAD")
        git(d, "commit", "-q", "--allow-empty", "-m", "B")
        self.b = git(d, "rev-parse", "HEAD")
        git(d, "checkout", "-q", "-b", "pr", self.a)
        git(d, "commit", "-q", "--allow-empty", "-m", "C")
        self.c = git(d, "rev-parse", "HEAD")
        git(d, "checkout", "-q", "dev")

    def track(self, remote: str, url: str, branch: str = "dev", at: str | None = None) -> None:
        git(self.dir, "remote", "add", remote, url)
        git(self.dir, "update-ref", f"refs/remotes/{remote}/{branch}", at or self.b)

    def cleanup(self):
        self._tmp.cleanup()


class FakeResponse:
    def __init__(self, data: dict, status: int = 200):
        self.status, self._body = status, json.dumps(data).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGitHub:
    """``urllib.request.urlopen`` stand-in answering api.github.com paths from a dict."""

    def __init__(self, answers: dict[str, dict | int]):
        self.answers = answers
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        path = req.full_url.removeprefix("https://api.github.com/")
        answer = self.answers.get(path, 404)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(req.full_url, answer, "error", {},
                                         io.BytesIO(json.dumps({"message": f"status {answer}"}).encode()))
        return FakeResponse(answer)


def compare_path(branch: str, commit: str) -> str:
    return f"repos/{TRU}/compare/{branch}...{commit}"


DEV_HEAD = "d" * 40  # the head of dev in the FakeGitHub answers below


def branch_path(branch: str) -> str:
    return f"repos/{TRU}/branches/{urllib.parse.quote(branch, safe='/')}"


def branch_answers(branch: str = "dev", head: str = DEV_HEAD) -> dict[str, dict]:
    """FakeGitHub answers for an existing branch of trureturing at ``head`` (and for the repository itself)."""
    return {branch_path(branch): {"name": branch, "commit": {"sha": head}}, f"repos/{TRU}": {"full_name": TRU}}


def api(path: str) -> str:
    return f"https://api.github.com/{path}"


# --------------------------------------------------------------------------- finding 0: branch ancestry


class GitAncestryTests(unittest.TestCase):
    def setUp(self):
        self.h = History()
        self.addCleanup(self.h.cleanup)

    def test_remote_tracking_ref_of_the_configured_repository(self):
        h = self.h
        h.track("upstream", UPSTREAM)
        self.assertEqual(lean._branch_ref(h.dir, TRU, "dev"), "refs/remotes/upstream/dev")
        yes = lean.git_branch_contains(h.dir, TRU, "dev", h.a)
        self.assertEqual(yes.on_branch, True)
        self.assertIn("upstream/dev", yes.detail)
        self.assertTrue(lean.git_branch_contains(h.dir, TRU, "dev", h.b).on_branch, "the head itself")
        no = lean.git_branch_contains(h.dir, TRU, "dev", h.c)
        self.assertIs(no.on_branch, False, "an unmerged commit (e.g. a pull-request head) is not on dev")
        self.assertIn("fetch", no.detail)
        unknown = lean.git_branch_contains(h.dir, TRU, "dev", "f" * 40)
        self.assertIsNone(unknown.on_branch)
        self.assertIsNone(lean.git_branch_contains(h.dir, TRU, "main", h.a).on_branch, "no such branch")

    def test_origin_and_local_branch_fallbacks(self):
        h = self.h
        self.assertEqual(lean._branch_ref(h.dir, TRU, "dev"), "refs/heads/dev", "no remotes: the local branch")
        h.track("origin", "https://example.org/mirror/trureturing.git", at=h.a)
        self.assertEqual(lean._branch_ref(h.dir, TRU, "dev"), "refs/remotes/origin/dev")
        self.assertIs(lean.git_branch_contains(h.dir, TRU, "dev", h.b).on_branch, False,
                      "origin/dev (at A) wins over the local dev (at B)")
        h.track("gh", f"git@github.com:{TRU}")
        self.assertEqual(lean._branch_ref(h.dir, TRU, "dev"), "refs/remotes/gh/dev", "the remote of the repository")

    def test_describe_like_names_are_not_branches(self):
        """git reads a name ending in '-g<hex>' (git describe output) as that abbreviated commit, also after
        refs/remotes/origin/: such a "branch" would contain any commit it abbreviates. Only a ref of exactly that
        name counts, and a checkout without one cannot tell (verification re-review 4, item 0)."""
        h = self.h
        h.track("origin", UPSTREAM)
        for name in (f"dev-12-g{h.c[:7]}", f"x-0-g{h.c[:12]}", f"release/2026-1-g{h.c[:8]}"):
            with self.subTest(name=name):
                self.assertEqual(lean.branch_problem(name, h.c), "", "a valid branch name")
                self.assertEqual(git(h.dir, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}^{{commit}}"),
                                 h.c, "what git makes of it: the unmerged commit C itself")
                self.assertIsNone(lean._branch_ref(h.dir, TRU, name))
                anc = lean.git_branch_contains(h.dir, TRU, name, h.c)
                self.assertIsNone(anc.on_branch)
                self.assertIn(f"has no branch {name!r}", anc.detail)
        with CoreRepo():
            name = f"x-0-g{h.c[:12]}"
            offline = lean.Ledger(TRU, offline=True, checkout=h.dir).branch_contains(h.c, name)
            self.assertIsNone(offline.on_branch, "the checkout cannot tell whether GitHub has such a branch")
            self.assertIn("has no branch", offline.detail)
            self.assertFalse((paths.CACHE / "trureturing" / h.c / lean.ANCESTRY_FILE).exists())
            gh = FakeGitHub({f"repos/{TRU}": {"full_name": TRU}, compare_path(name, h.c): {"status": "identical"}})
            with mock.patch.object(lean.urllib.request, "urlopen", gh):
                online = lean.Ledger(TRU, checkout=h.dir).branch_contains(h.c, name)
            self.assertEqual((online.on_branch, online.no_branch), (False, True), "GitHub has no such branch")
            self.assertEqual([r.full_url for r in gh.requests], [api(branch_path(name)), api(f"repos/{TRU}")])
        # a real branch counts whatever its name looks like, and is compared as the branch, not as a commit
        name = f"dev-12-g{h.c[:7]}"
        git(h.dir, "update-ref", f"refs/remotes/origin/{name}", h.b)
        self.assertEqual(lean._branch_ref(h.dir, TRU, name), f"refs/remotes/origin/{name}")
        self.assertIs(lean.git_branch_contains(h.dir, TRU, name, h.c).on_branch, False)
        self.assertTrue(lean.git_branch_contains(h.dir, TRU, name, h.a).on_branch)

    def test_same_repo_urls(self):
        for url in (UPSTREAM, f"https://github.com/{TRU}", f"git@github.com:{TRU}.git", f"HTTPS://GitHub.com/{TRU}/"):
            self.assertTrue(lean._same_repo(url, TRU), url)
        for url in (f"https://github.com/{TRU}-fork.git", "https://github.com/someone/trureturing.git", "/srv/tru"):
            self.assertFalse(lean._same_repo(url, TRU), url)


class LedgerAncestryTests(unittest.TestCase):
    def setUp(self):
        self.repo = CoreRepo().__enter__()
        self.addCleanup(self.repo.__exit__, None, None, None)
        self.h = History()
        self.addCleanup(self.h.cleanup)
        self.h.track("origin", UPSTREAM)

    def github(self, answers):
        fake = FakeGitHub(answers)
        patcher = mock.patch.object(lean.urllib.request, "urlopen", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_checkout_answers_and_positive_answers_are_cached(self):
        h = self.h
        gh = self.github({})
        led = lean.Ledger(TRU, offline=True, checkout=h.dir)
        self.assertTrue(led.branch_contains(h.a, "dev").on_branch)
        marker = paths.CACHE / "trureturing" / h.a / lean.ANCESTRY_FILE
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8")),
                         {f"{TRU}@dev": f"ancestor of origin/dev in {h.dir}"})
        self.assertIs(led.branch_contains(h.c, "dev").on_branch, False)
        self.assertFalse((paths.CACHE / "trureturing" / h.c / lean.ANCESTRY_FILE).exists(), "no negative cache")
        cached = lean.Ledger(TRU, offline=True).branch_contains(h.a, "dev")  # no checkout, no network
        self.assertEqual((cached.on_branch, cached.detail.endswith("(cached)")), (True, True))
        self.assertIsNone(lean.Ledger(TRU, offline=True).branch_contains(h.a, "main").on_branch,
                          "the cache is per branch")
        self.assertEqual(gh.requests, [], "offline: no API request")

    def test_offline_without_checkout_cannot_tell(self):
        res = lean.Ledger(TRU, offline=True).branch_contains(COMMIT, "dev")
        self.assertIsNone(res.on_branch)
        self.assertIn("no local trureturing checkout", res.detail)
        self.assertIn("network disabled", res.detail)

    def test_github_compare(self):
        """The branch's head from the branches endpoint, then compare/<head>...<commit>."""
        gh = self.github({**branch_answers("dev", DEV_HEAD), **branch_answers("release/1", "1" * 40),
                          compare_path(DEV_HEAD, COMMIT): {"status": "behind", "ahead_by": 0, "behind_by": 3},
                          compare_path(DEV_HEAD, OLD_COMMIT): {"status": "diverged", "ahead_by": 2, "behind_by": 9},
                          compare_path(DEV_HEAD, "c" * 40): {"status": "ahead", "ahead_by": 1, "behind_by": 0},
                          compare_path(DEV_HEAD, DEV_HEAD): {"status": "identical", "ahead_by": 0, "behind_by": 0},
                          compare_path(DEV_HEAD, "e" * 40): 403,
                          compare_path("1" * 40, COMMIT): {"status": "behind"}})
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GH_TOKEN", None)
        os.environ["TRURETURING_TOKEN"] = "tok"
        led = lean.Ledger(TRU)
        yes = led.branch_contains(COMMIT, "dev")
        self.assertEqual(yes, lean.Ancestry(True, f"GitHub compare {DEV_HEAD[:12]} (head of dev)...{COMMIT[:12]}: behind"))
        self.assertEqual([r.full_url for r in gh.requests], [api(branch_path("dev")), api(compare_path(DEV_HEAD, COMMIT))])
        for req in gh.requests:
            self.assertEqual(req.get_header("Authorization"), "Bearer tok")
        no = led.branch_contains(OLD_COMMIT, "dev")
        self.assertIs(no.on_branch, False)
        self.assertIn("diverged, 2 commit(s) not on dev", no.detail)
        self.assertIs(led.branch_contains("c" * 40, "dev").on_branch, False, "ahead of dev: not merged yet")
        self.assertFalse(no.no_branch)
        self.assertTrue(led.branch_contains(DEV_HEAD, "dev").on_branch, "the head of dev")
        limited = led.branch_contains("e" * 40, "dev")
        self.assertIsNone(limited.on_branch)
        self.assertIn("HTTP 403 status 403", limited.detail)
        missing = led.branch_contains("f" * 40, "dev")
        self.assertIsNone(missing.on_branch)
        self.assertIn("unknown commit", missing.detail)
        self.assertTrue(led.branch_contains(COMMIT, "release/1").on_branch, "slashes in branch names")
        # GitHub redirects a renamed branch to its new name: the old name is no branch any more
        gh.answers[branch_path("master")] = {"name": "main", "commit": {"sha": DEV_HEAD}}
        renamed = led.branch_contains(COMMIT, "master")
        self.assertEqual((renamed.on_branch, renamed.no_branch), (False, True))
        self.assertIn("answered with branch 'main'", renamed.detail)
        gh.answers[branch_path("busy")] = 403  # e.g. the rate limit: nobody can tell
        busy = led.branch_contains(COMMIT, "busy")
        self.assertEqual((busy.on_branch, busy.no_branch), (None, False))
        self.assertIn("HTTP 403", busy.detail)
        gh.answers[branch_path("odd")] = {"name": "odd"}
        self.assertIsNone(led.branch_contains(COMMIT, "odd").on_branch, "no head commit in the answer")
        os.environ.pop("TRURETURING_TOKEN")
        os.environ["GITHUB_TOKEN"] = "gh"
        gh.requests.clear()
        lean.Ledger(TRU).branch_contains(OLD_COMMIT, "dev")
        self.assertEqual(gh.requests[0].get_header("Authorization"), "Bearer gh")
        os.environ.pop("GITHUB_TOKEN")
        gh.requests.clear()
        lean.Ledger(TRU).branch_contains(OLD_COMMIT, "dev")
        self.assertIsNone(gh.requests[0].get_header("Authorization"))

    def test_github_overrides_a_stale_checkout_and_a_checkout_no_stands_alone(self):
        h = self.h
        git(h.dir, "update-ref", "refs/remotes/origin/dev", h.a)  # stale: dev has moved to B since the last fetch
        gh = self.github({**branch_answers("dev", h.b), compare_path(h.b, h.b): {"status": "identical"}})
        led = lean.Ledger(TRU, checkout=h.dir)
        self.assertTrue(led.branch_contains(h.b, "dev").on_branch)
        self.assertEqual(len(gh.requests), 2, "the head of dev, then compare")
        no = led.branch_contains(h.c, "dev")  # GitHub does not know C (404): the checkout's answer stands
        self.assertIs(no.on_branch, False)
        self.assertIn("not an ancestor of origin/dev", no.detail)
        gh.requests.clear()
        self.assertTrue(led.branch_contains(h.a, "dev").on_branch)
        self.assertEqual(gh.requests, [], "a checkout's yes needs no API request")

    def test_ancestry_required(self):
        os.environ.pop("GITHUB_ACTIONS", None)
        self.assertFalse(lean.ancestry_required(False))
        os.environ["GITHUB_ACTIONS"] = "true"
        self.assertTrue(lean.ancestry_required(False))
        self.assertFalse(lean.ancestry_required(True), "--offline makes it a warning")


class LsRemoteTests(unittest.TestCase):
    OUT = (f"{'1' * 40}\trefs/heads/dev\n{'2' * 40}\trefs/tags/v1\n{'3' * 40}\trefs/tags/v1^{{}}\n"
           f"{'4' * 40}\trefs/pull/7/head\n{'5' * 40}\trefs/tags/light\n")

    def run_ls_remote(self, ref, out=None):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            pats = cmd[3:]
            lines = [ln for ln in (self.OUT if out is None else out).splitlines()
                     if any(ln.split("\t")[1] == p or ln.split("\t")[1].endswith("/" + p) for p in pats)]
            return subprocess.CompletedProcess(cmd, 0, "".join(ln + "\n" for ln in lines), "")

        with mock.patch.object(lean.subprocess, "run", fake_run):
            return lean.ls_remote(TRU, ref), calls

    def test_branches_and_tags_only(self):
        sha, calls = self.run_ls_remote("dev")
        self.assertEqual(sha, "1" * 40)
        self.assertEqual(calls[0][:3], ["git", "ls-remote", UPSTREAM])
        self.assertEqual(calls[0][3:], ["refs/heads/dev", "refs/tags/dev", "refs/tags/dev^{}"])
        self.assertEqual(self.run_ls_remote("v1")[0], "3" * 40, "annotated tags are peeled to their commit")
        self.assertEqual(self.run_ls_remote("light")[0], "5" * 40)
        self.assertEqual(self.run_ls_remote("refs/heads/dev")[0], "1" * 40)
        with self.assertRaisesRegex(lean.LeanError, "no branch or tag of that name"):
            self.run_ls_remote("head")  # git ls-remote alone would match refs/pull/7/head by suffix
        with self.assertRaisesRegex(lean.LeanError, "no branch or tag of that name"):
            self.run_ls_remote("7/head")
        with self.assertRaisesRegex(lean.LeanError, "only branches"):
            self.run_ls_remote("refs/pull/7/head")
        with self.assertRaisesRegex(lean.LeanError, "full 40-character SHA"):
            self.run_ls_remote("8a24ea4e79de")
        self.assertEqual(self.run_ls_remote(COMMIT), (COMMIT, []), "a full SHA needs no network")


class PinBranchTests(unittest.TestCase):
    def setUp(self):
        self.repo = CoreRepo().__enter__()
        self.addCleanup(self.repo.__exit__, None, None, None)
        self.repo.book()
        make_lock().save()
        self.before = paths.LOCK_FILE.read_text(encoding="utf-8")
        os.environ.pop("GITHUB_ACTIONS", None)

    def use(self, ledger):
        patcher = mock.patch.object(lean, "Ledger", lambda r, **kw: ledger)
        patcher.start()
        self.addCleanup(patcher.stop)
        return ledger

    def test_off_branch_commit_is_refused(self):
        led = self.use(FakeLedger(on_branch=False))
        report = pin.pin(OLD_COMMIT, offline=True)
        self.assertFalse(report.written)
        self.assertIn(f"{OLD_COMMIT} is not on branch 'dev' of {TRU} (fake: not on branch)", report.refused)
        self.assertEqual(led.ancestry_calls, [(OLD_COMMIT, "dev")])
        self.assertEqual(led.calls, [], "nothing is resolved at a refused commit")
        self.assertEqual(paths.LOCK_FILE.read_text(encoding="utf-8"), self.before)
        self.assertIn("**Refused (lock not written):**", report.markdown())
        report = pin.pin(refresh=True, offline=True)
        self.assertTrue(report.refused, "--refresh re-verifies the locked commit too")
        from tbook import cli

        out = self.repo.root / "build" / "pin.md"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["pin", OLD_COMMIT, "--offline", "--report", str(out)]), 1)
        self.assertIn("Refused", out.read_text(encoding="utf-8"))
        self.assertEqual(paths.LOCK_FILE.read_text(encoding="utf-8"), self.before)

    def test_undetermined_ancestry(self):
        self.use(FakeLedger(on_branch=None))
        report = pin.pin(COMMIT, offline=False, dry_run=True)
        self.assertEqual(report.refused, "")
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("could not verify", report.warnings[0])
        self.assertIn("**Warnings:**", report.markdown())
        os.environ["GITHUB_ACTIONS"] = "true"
        report = pin.pin(COMMIT, offline=False, dry_run=True)
        self.assertIn("could not verify", report.refused, "in CI an unverifiable commit is refused")
        report = pin.pin(COMMIT, offline=True, dry_run=True)
        self.assertEqual((report.refused, len(report.warnings)), ("", 1), "--offline makes it a warning")

    def test_branch_head_and_other_refs(self):
        led = self.use(FakeLedger(on_branch=False))
        seen = []
        with mock.patch.object(lean, "ls_remote", lambda repo, ref: seen.append(ref) or COMMIT):
            report = pin.pin()
            self.assertEqual(seen, ["refs/heads/dev"])
            self.assertTrue(report.written, report.markdown())
            self.assertEqual(led.ancestry_calls, [], "the head of dev is on dev by construction")
            self.assertEqual(led.recorded, [(COMMIT, "dev")])
            self.assertEqual(lean.Lock.load().branch, "dev")
            pin.pin("dev", dry_run=True)
            self.assertEqual(seen[-1], "refs/heads/dev")
            report = pin.pin("feature-x")
            self.assertEqual(seen[-1], "feature-x")
            self.assertTrue(report.refused, "another branch's head must be on dev too")

    def test_abbreviated_sha(self):
        led = self.use(FakeLedger(shas={"aaaaaaaaaaaa": COMMIT}))
        report = pin.pin("aaaaaaaaaaaa", offline=True, dry_run=True)
        self.assertEqual(report.commit, COMMIT)
        self.assertEqual(led.ancestry_calls, [(COMMIT, "dev")])
        with self.assertRaisesRegex(lean.LeanError, "commit prefix the local trureturing checkout knows"):
            pin.pin("abcdef12", offline=True)
        unknown = lean.LeanError("no branch or tag; pass its full 40-character SHA")
        with mock.patch.object(lean, "ls_remote", side_effect=unknown):
            with self.assertRaisesRegex(lean.LeanError, "full 40-character SHA"):
                pin.pin("abcdef12")


class LedgerExpandShaTests(unittest.TestCase):
    def test_checkout_then_github(self):
        with CoreRepo():
            h = History()
            self.addCleanup(h.cleanup)
            gh = FakeGitHub({f"repos/{TRU}/commits/{COMMIT[:10]}": {"sha": COMMIT},
                             f"repos/{TRU}/commits/1234567": {"sha": "f" * 40}})
            with mock.patch.object(lean.urllib.request, "urlopen", gh):
                local = lean.Ledger(TRU, offline=True, checkout=h.dir)
                self.assertEqual(local.expand_sha(h.c[:12]), h.c)
                self.assertEqual(local.expand_sha(h.c[:12].upper()), h.c)
                self.assertIsNone(local.expand_sha("dev"), "only hex prefixes")
                self.assertIsNone(local.expand_sha(COMMIT[:10]), "offline: the checkout only")
                online = lean.Ledger(TRU)
                self.assertEqual(online.expand_sha(COMMIT[:10]), COMMIT)
                self.assertIsNone(online.expand_sha("1234567"), "an answer that does not extend the prefix")
                self.assertIsNone(online.expand_sha("7654321"), "unknown (404)")


class CheckBranchTests(unittest.TestCase):
    def run_lean(self, ledger, offline=False):
        with mock.patch.object(lean, "Ledger", lambda repo, **kw: ledger):
            issues: list[model.Issue] = []
            check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, make_lock(),
                             config.load_site(), issues, offline=offline)
            return issues

    def test_pinned_commit_must_be_on_the_branch(self):
        with CoreRepo() as repo:
            repo.book()
            os.environ.pop("GITHUB_ACTIONS", None)
            led = FakeLedger(on_branch=False)
            issues = self.run_lean(led)
            self.assertEqual([(i.severity, i.path) for i in issues], [("error", paths.LOCK_FILE)])
            self.assertIn(f"pinned commit {COMMIT[:12]} is not on branch 'dev' of {TRU} (fake: not on branch)",
                          issues[0].message)
            self.assertEqual(led.ancestry_calls, [(COMMIT, "dev")])
            self.assertEqual(self.run_lean(FakeLedger(on_branch=True)), [])
            issues = self.run_lean(FakeLedger(on_branch=None))
            self.assertEqual([i.severity for i in issues], ["warning"])
            self.assertIn("could not verify that pinned commit", issues[0].message)
            os.environ["GITHUB_ACTIONS"] = "true"
            self.assertEqual([i.severity for i in self.run_lean(FakeLedger(on_branch=None))], ["error"])
            self.assertEqual([i.severity for i in self.run_lean(FakeLedger(on_branch=None), offline=True)],
                             ["warning"], "--offline makes it a warning, even in CI")

    def test_committed_cache_is_an_error(self):
        with CoreRepo() as repo:
            check.check_cache(issues := [])
            self.assertEqual(issues, [], "not a git checkout")
            git(repo.root, "init", "-q")
            write(repo.root / ".cache/trureturing" / COMMIT / lean.ANCESTRY_FILE, "{}")
            check.check_cache(issues := [])
            self.assertEqual(issues, [], "untracked cache files are fine")
            git(repo.root, "add", "-f", ".cache")
            check.check_cache(issues := [])
            self.assertEqual([i.severity for i in issues], ["error"])
            self.assertIn("are committed", issues[0].message)


# --------------------------------------------------------------------------- finding 10: declaration lines


def located(source: str, name: str, module: str = "D5/S0/M") -> tuple[int, str]:
    res = lean.Resolution(gid="", module=module, name=name, kind="theorem", statement_id="")
    lean.locate(FakeLedger(sources={f"{module}.lean": textwrap.dedent(source)}), COMMIT, res)
    return res.line, res.signature


class LocateTests(unittest.TestCase):
    def test_qualified_names_inside_namespaces(self):
        src = """\
            namespace Lambda

            theorem LMonoTy.freeVars_of_subst_subset (S : Subst) : True := trivial

            theorem LMonoTys.freeVars_of_subst_subset (S : Subst) : True := trivial

            end Lambda
            """
        self.assertEqual(located(src, "Lambda.LMonoTys.freeVars_of_subst_subset"),
                         (5, "theorem LMonoTys.freeVars_of_subst_subset (S : Subst) : True"))
        self.assertEqual(located(src, "Lambda.LMonoTy.freeVars_of_subst_subset")[0], 3)

    def test_same_short_name_in_two_namespaces(self):
        src = """\
            /- namespace Decoy
            theorem foo : True := trivial -/
            namespace A
            -- theorem foo is below
            theorem foo : True := trivial
            end A

            noncomputable section
            namespace B
            @[simp]
            protected theorem foo : True := trivial
            theorem _root_.Top.foo : True := trivial
            end B
            end
            """
        self.assertEqual(located(src, "A.foo")[0], 5)
        self.assertEqual(located(src, "B.foo"), (10, "@[simp] protected theorem foo : True"))
        self.assertEqual(located(src, "Top.foo")[0], 12)
        self.assertEqual(located(src, "Decoy.foo")[0], 0, "comments are not declarations")
        self.assertEqual(located(src, "C.foo")[0], 0, "not written in this file: no guess")

    def test_unfollowable_scopes_fall_back_to_the_longest_unique_suffix(self):
        src = """\
            namespace X
            end Y
            theorem P.bar : True := trivial
            theorem Q.bar : True := trivial
            theorem baz : True := trivial
            private theorem qux : True := trivial
            """
        self.assertEqual(located(src, "Z.P.bar")[0], 3)
        self.assertEqual(located(src, "Z.R.bar")[0], 0, "two equally good candidates: line 0")
        self.assertEqual(located(src, "Z.baz")[0], 5)
        self.assertEqual(located(src, "Z.qux")[0], 0, "private declarations are never cited")

    def test_unicode_names_and_mutual_blocks(self):
        src = """\
            namespace FDRep
            mutual
            theorem even₂ : True := trivial
            theorem odd₂ : True := trivial
            end
            @[simp] theorem of_ρ_eq_self : True := trivial
            theorem «weird name» : True := trivial
            end FDRep
            """
        self.assertEqual(located(src, "FDRep.odd₂")[0], 4)
        self.assertEqual(located(src, "FDRep.of_ρ_eq_self")[0], 6)
        self.assertEqual(located(src, "FDRep.«weird name»")[0], 7)

    def test_pin_reports_moved_lines(self):
        with CoreRepo() as repo:
            repo.book()
            lean.Lock(repo=TRU, branch="dev", commit=COMMIT, pinned_at="2025-01-01T00:00:00Z",
                      declarations=lock_decls()).save()  # GID_3V at line 12
            src = "namespace D5.S1.Deficit\ntheorem deficit_three_valued : True := trivial\n"
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger(sources={f"{MOD_3V}.lean": src})):
                report = pin.pin(refresh=True, offline=True)
            self.assertIn((GID_3V, 12, 2), report.moved)
            self.assertIn(f"- `{GID_3V}`: L12 → L2", report.markdown())

    @unittest.skipUnless(REAL, f"needs a trureturing checkout ($TRURETURING_DIR) with {REAL_COMMIT[:12]}")
    def test_real_same_short_name(self):
        checkout, commit = REAL, REAL_COMMIT
        led = lean.Ledger(TRU, offline=True, checkout=checkout)
        res = lean.resolve(led, commit, "D5/S0/Rewriting/NativeSubstitution.LMonoTys.freeVars_of_subst_subset")
        lean.locate(led, commit, res)
        self.assertEqual(res.name, "Lambda.LMonoTys.freeVars_of_subst_subset")
        self.assertTrue(res.signature.startswith("theorem LMonoTys.freeVars_of_subst_subset"), res.signature)


# --------------------------------------------------------------------------- finding 11: GID syntax


class GidSyntaxTests(unittest.TestCase):
    def test_lean_identifiers(self):
        for name in ("of_ρ_eq_self", "FDRep.of_ρ_eq_self", "mk₂", "isSome?", "get!", "x'", "«a.b»",
                     "Foo.«with-dash».bar", "Gammaℝ", "αβ_γ", "xᵢ"):
            g = lean.parse_gid(f"D5/S3/M.{name}")
            self.assertEqual(g.name, name)
        self.assertEqual(lean.parse_gid("D5/S3/M.Foo.«a.b».c").parts, ["Foo", "a.b", "c"])
        for bad in ("D5/S3/M.«a b»", "D5/S3/M.«»", "D5/S3/M.a..b", "D5/S3/M.λx", "D5/S3/M.1b", "D5/S3/M.a-b",
                    "D5/S3/M.«a", "D5/S3/M.a.", "D5/S3/M.«a,b»"):
            with self.assertRaises(lean.LeanError, msg=bad):
                lean.parse_gid(bad)

    def test_name_to_str_escapes_only_non_identifiers(self):
        self.assertEqual(lean.name_to_str(["FDRep", "of_ρ_eq_self", "mk₂"]), "FDRep.of_ρ_eq_self.mk₂")
        self.assertEqual(lean.name_to_str(["a-b", "λx", "Π"]), "«a-b».«λx».«Π»")
        self.assertTrue(lean.is_identifier("Sᵥₙ_nonneg"))
        self.assertFalse(lean.is_identifier("₂x"))

    def test_resolve_matches_components(self):
        st = {"statement_id": "s", "declarations": [
            {"declaration_name_key": name_key("D5", "S3", "FDRep", "of_ρ_eq_self"), "kind": "theorem"},
            {"declaration_name_key": name_key("X", "a.b"), "kind": "theorem"},
            {"declaration_name_key": name_key("X", "b"), "kind": "def"}]}
        led = FakeLedger({"D5/S3/M": st})
        for gid in ("D5/S3/M.of_ρ_eq_self", "D5/S3/M.FDRep.«of_ρ_eq_self»", "D5/S3/M.D5.S3.FDRep.of_ρ_eq_self"):
            self.assertEqual(lean.resolve(led, COMMIT, gid).name, "D5.S3.FDRep.of_ρ_eq_self", gid)
        self.assertEqual(lean.resolve(led, COMMIT, "D5/S3/M.«a.b»").name, "X.«a.b»")
        self.assertEqual(lean.resolve(led, COMMIT, "D5/S3/M.b").kind, "def", "b is not a suffix of «a.b»")

    @unittest.skipUnless(REAL, f"needs a trureturing checkout ($TRURETURING_DIR) with {REAL_COMMIT[:12]}")
    def test_real_blueprint_gid(self):
        checkout, commit = REAL, REAL_COMMIT
        led = lean.Ledger(TRU, offline=True, checkout=checkout)
        res = lean.resolve(led, commit, "D5/S3/FiniteGroups/FiniteCharacterAlgebra.of_ρ_eq_self")
        self.assertEqual((res.kind, res.name),
                         ("theorem", "D5.S3.FiniteGroups.FiniteCharacterAlgebra.FDRep.of_ρ_eq_self"))


# --------------------------------------------------------------------------- findings 27, 35: pin report


class PinReportTests(unittest.TestCase):
    def setUp(self):
        self.repo = CoreRepo().__enter__()
        self.addCleanup(self.repo.__exit__, None, None, None)
        self.repo.book()
        patcher = mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_directory_is_created(self):
        from tbook import cli

        make_lock().save()
        out = self.repo.root / "build" / "deeper" / "pin.md"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["pin", "--refresh", "--offline", "--report", str(out)]), 0)
        self.assertIn("trureturing pin:", out.read_text(encoding="utf-8"))

    def test_unwritable_report_leaves_the_lock_alone(self):
        from tbook import cli

        lean.Lock(repo=TRU, branch="dev", commit=COMMIT, pinned_at="2025-01-01T00:00:00Z", declarations={}).save()
        before = paths.LOCK_FILE.read_text(encoding="utf-8")
        write(self.repo.root / "build", "a file, not a directory")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            report = str(self.repo.root / "build" / "x" / "pin.md")
            self.assertEqual(cli.main(["pin", "--refresh", "--offline", "--report", report]), 1)
        self.assertIn("cannot write --report", err.getvalue())
        self.assertEqual(paths.LOCK_FILE.read_text(encoding="utf-8"), before)

    def test_unresolved_cited_gid_is_not_removed(self):
        stale = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued_old"
        for lang in ("zh", "en"):
            p = config.load_book("demo").edition(lang).dir / "ch02.md"
            p.write_text(p.read_text(encoding="utf-8") + f'\n::: {{.lemma #lem-old lean="{stale}"}}\nx\n:::\n',
                         encoding="utf-8")
        gone = {"module": "D5/S1/Old/Gone", "name": "x", "kind": "theorem"}
        make_lock(lock_decls(**{stale: dict(lock_decls()[GID_3V], name="D5.S1.Deficit.deficit_three_valued_old"),
                                "D5/S1/Old/Gone.x": gone})).save()
        report = pin.pin(refresh=True, offline=True, dry_run=True)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("deficit_three_valued_old", report.errors[0])
        self.assertEqual(report.removed, ["D5/S1/Old/Gone.x"], "still cited, so not removed")
        text = report.markdown()
        self.assertEqual(text.count("deficit_three_valued_old"), 2, text)  # the error line names it twice


# --------------------------------------------------------------------------- finding 29: SUMMARY parity


class SummaryParityTests(unittest.TestCase):
    def parity(self, en_summary: str) -> list[model.Issue]:
        with CoreRepo() as repo:
            book = repo.book(summaries={"zh": ZH_SUMMARY, "en": en_summary})
            issues: list[model.Issue] = []
            check.check_parity(book, model.load_book_models(book), issues)
            return issues

    def test_same_structure_passes(self):
        self.assertEqual(self.parity(EN_SUMMARY), [])

    def test_nesting_numbering_and_sections_must_agree(self):
        nested = EN_SUMMARY.replace("- [Chapter 2](ch02.md)", "  - [Chapter 2](ch02.md)").replace(
            "  - [Section 2.1]", "    - [Section 2.1]")
        msgs = messages(self.parity(nested))
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("ch02.md is numbered chapter 1.1, nested at depth 1 (theorems 1.n) in the en edition but "
                      "numbered chapter 2 (theorems 2.n) in the zh edition", msgs[0])
        draft = EN_SUMMARY.replace("- [Chapter 1](ch01.md)", "- [Chapter 1](ch01.md)\n- [Draft]()")
        self.assertIn("ch02.md is numbered chapter 3", messages(self.parity(draft))[0])
        prefix = EN_SUMMARY.replace("[Preface](README.md)\n", "").replace(
            "- [Chapter 1](ch01.md)", "- [Preface](README.md)\n- [Chapter 1](ch01.md)")
        msgs = messages(self.parity(prefix))
        self.assertIn("README.md is numbered chapter 1 (theorems 1.n) in the en edition but a prefix chapter", msgs[0])
        suffix = EN_SUMMARY.replace("[Appendix A](appendix-a.md)\n", "").replace(
            "- [Draft]()", "- [Draft]()\n- [Appendix A](appendix-a.md)")
        self.assertIn("appendix-a.md is numbered chapter 4", messages(self.parity(suffix))[0])


# --------------------------------------------------------------------------- findings 32, 34: lock checks


class LockCheckTests(unittest.TestCase):
    def test_book_filter_counts_other_books_citations(self):
        with CoreRepo() as repo:
            demo = repo.book()
            second = repo.book("second", langs=("zh",), summaries={"zh": "- [A](a.md)\n"}, files={"zh": {
                "a.md": f'::: {{.theorem #thm-only lean="{GID_INT}"}}\nx\n:::\n'}})
            extra = {"D5/S1/Old/Gone.x": {"module": "D5/S1/Old/Gone", "name": "x", "kind": "theorem"}}
            make_lock(dict(lock_decls(), **extra)).save()
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                    mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
                unused = [m for m in messages(check.run([second], offline=True)) if "no longer cited" in m]
                self.assertEqual(unused, ["D5/S1/Old/Gone.x is locked but no longer cited; ./tbook pin --refresh "
                                          "prunes it"], "demo's citations are still cited")
                unused = [m for m in messages(check.run([demo, second], offline=True)) if "no longer cited" in m]
                self.assertEqual(len(unused), 1)
                write(repo.root / "books" / "broken" / "book.toml", "not toml [")
                unused = [m for m in messages(check.run([second], offline=True)) if "no longer cited" in m]
                self.assertEqual(unused, [], "other books unreadable: the warning is skipped, not guessed")

    def test_kind_error_at_each_theorem_like_environment(self):
        with CoreRepo() as repo:
            book = repo.book()
            for lang in ("zh", "en"):
                p = book.edition(lang).dir / "ch02.md"
                p.write_text(p.read_text(encoding="utf-8") + f'\n::: {{.theorem #thm-def lean="{GID_DEF}"}}\nx\n:::\n',
                             encoding="utf-8")
            slide = repo.root / "books" / "demo" / "slides" / "deck" / "slides.md"
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()):
                issues: list[model.Issue] = []
                check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, make_lock(),
                                 config.load_site(), issues, offline=True, extra_cited=[(slide, 44, GID_DEF)])
            kind = [(i.path.relative_to(repo.root).as_posix(), i.line)
                    for i in issues if "must cite theorems" in i.message]
            self.assertEqual(kind, [("books/demo/zh/ch02.md", 9), ("books/demo/en/ch02.md", 9)])


# --------------------------------------------------------------------------- re-review 0: pull requests and .cache

RAW = f"https://raw.githubusercontent.com/{TRU}"
API_TOKENS = ("TRURETURING_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
GID_RH = "D5/S1/Deficit/DeficitThreeValued.riemann_hypothesis"


def state_url(commit: str, module: str) -> str:
    return f"{RAW}/{commit}/{lean.STATE_DIR}/{module}.lean.json"


def raw_states(commit: str) -> dict[str, dict]:
    """FakeGitHub answers: the real frozen state of every module at ``commit``."""
    return {state_url(commit, module): data for module, data in states().items()}


def plant_cache(commit: str, branch: str = "dev") -> None:
    """What an earlier run of a pull request (its own code) can save into .cache/trureturing for the next run:
    frozen state with a fabricated theorem under the module's unchanged statement_id, and a positive answer
    to "is the commit on the branch?"."""
    st = states()
    st[MOD_3V]["declarations"].append(
        {"declaration_name_key": name_key("D5", "S1", "Deficit", "riemann_hypothesis"), "kind": "theorem"})
    for module, data in st.items():
        write(paths.CACHE / "trureturing" / commit / lean.STATE_DIR / f"{module}.lean.json", json.dumps(data))
    write(paths.CACHE / "trureturing" / commit / lean.ANCESTRY_FILE, json.dumps({f"{TRU}@{branch}": "planted"}))


def gha_if(expr: str, *, event: str, ref: str, default_branch: str | None = "main",
           context: dict[str, str] | None = None, cancelled: bool = False, **outputs: str) -> bool:
    """Evaluate a workflow step's ``if:`` written with the subset of GitHub's expression syntax used by the
    cache steps and job conditions: ``==``, ``!=``, ``!``, ``&&``, ``||``, parentheses, ``format``, ``startsWith``,
    ``contains`` (of a string), ``true`` / ``false`` / ``null``, ``cancelled()``. ``context`` gives further names
    (``inputs.browsers``, ``steps.<id>.outputs.cache-hit``, ``github.workflow_ref``…; a name it does not give is
    an error, so pass ``None`` for an input a run does not have)."""
    py = expr.strip().removeprefix("${{").removesuffix("}}")
    py = py.replace("cancelled()", repr(cancelled))
    py = re.sub(r"format\(('[^']*'),\s*([\w.]+)\)", r"\1.format(\2)", py)
    py = re.sub(r"startsWith\(([\w.]+),\s*('[^']*')\)", r"\1.startswith(\2)", py)
    py = re.sub(r"contains\(([\w.]+),\s*('[^']*')\)", r"(\2 in \1)", py)
    literals = {"true": "True", "false": "False", "null": "None"}
    py = "".join(part if part.startswith("'") else re.sub(r"\b(true|false|null)\b", lambda m: literals[m.group(1)], part)
                 for part in re.split(r"('[^']*')", py))
    py = re.sub(r"!(?!=)", " not ", py.replace("&&", " and ").replace("||", " or "))
    values = {"github.event.repository.default_branch": default_branch or "", "github.event_name": event,
              "github.ref": ref, **{f"steps.target.outputs.{k}": v for k, v in outputs.items()}, **(context or {})}
    for name in sorted(values, key=len, reverse=True):
        py = py.replace(name, repr(values[name]))
    bare = re.sub(r"'[^']*'", "''", py).replace(".format(", "(").replace(".startswith(", "(")
    if re.search(r"[A-Za-z_]\w*\.\w", bare):
        raise AssertionError(f"unsupported expression: {expr!r} -> {py!r}")
    return bool(eval(py, {"__builtins__": {}}))  # noqa: S307 - a test reading its own workflows


def trureturing_cache_steps(workflow: Path) -> list[str]:
    """The ``if:`` conditions ('' when absent) of the steps that restore or save ``.cache/trureturing``."""
    steps = re.split(r"\n(?=\s+- name:)", workflow.read_text(encoding="utf-8"))
    out = []
    for step in steps:
        if not re.search(r"^\s+path:\s*\.cache/trureturing\s*$", step, re.M):
            continue
        m = re.search(r"^(\s+)if:\s*(>-?)?\s*(.*?)$((?:\n\1\s+.*)*)", step, re.M)
        out.append(" ".join([m.group(3), *m.group(4).split()]).strip() if m else "")
    return out


GITHUB_DIR = Path(__file__).resolve().parents[2] / ".github"
PR_EVENTS = ("pull_request", "pull_request_target", "pull_request_review", "pull_request_review_comment")


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else value


def read_steps(text: str) -> list[dict]:
    """The steps listed in ``text`` (a job's ``steps:`` or a composite action's ``runs.steps``), in order: each
    a dict of its scalar keys (``name``, ``uses``, ``id``, ``if``, ``run``, ``continue-on-error``…; a folded
    ``>-`` value joined into one line, a ``|`` block dedented) and of ``with`` and ``env`` as flat dicts.

    A reader for the layout of these files (two-space indentation, block mappings), not general YAML."""
    first = re.search(r"^( *)- name:", text, re.M)
    if not first:
        return []
    indent = len(first.group(1))
    steps = []
    for part in re.split(rf"\n(?={' ' * indent}- )", text[first.start():]):
        lines = part.splitlines()
        lines[0] = lines[0].replace("- ", "  ", 1)
        step: dict = {"with": {}, "env": {}}
        i = 0
        while i < len(lines):
            m = re.match(rf"^ {{{indent + 2}}}([\w-]+):\s?(.*)$", lines[i])
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent + 2):
                j += 1
            if m:
                key, value, block = m.group(1), m.group(2).split(" #")[0].strip(), lines[i + 1:j]
                if key in ("with", "env"):
                    for line in block:
                        if (b := re.match(r"^\s+([\w-]+):\s*(.*)$", line)) and not line.lstrip().startswith("#"):
                            step[key][b.group(1)] = _unquote(b.group(2).strip())
                elif value in (">-", ">", "|", "|-"):
                    body = textwrap.dedent("\n".join(block)).strip("\n")
                    step[key] = " ".join(body.split()) if value.startswith(">") else body
                else:
                    step[key] = _unquote(value)
            i = j
        steps.append(step)
    return steps


def action_steps(name: str) -> list[dict]:
    """The steps of the composite action ``.github/actions/<name>``."""
    text = (GITHUB_DIR / "actions" / name / "action.yml").read_text(encoding="utf-8")
    return read_steps(text.split("\n  steps:\n", 1)[1])


def workflow_jobs(path: Path) -> dict[str, list[dict]]:
    """``{job: steps}`` of a workflow (a job that calls a reusable workflow has no steps)."""
    text = path.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    jobs = {}
    for m in re.finditer(r"^  ([\w-]+):\n((?:(?:    .*)?\n)*)", body, re.M):
        steps = m.group(2).split("\n    steps:\n", 1)
        jobs[m.group(1)] = read_steps(steps[1]) if len(steps) == 2 else []
    return jobs


def condition_values(cond: str) -> list[dict[str, str]]:
    """Every assignment of the inputs and step outputs that ``cond`` reads to values they can take, as
    ``gha_if`` contexts: what a step runs with in whatever way its action is used."""
    names = sorted(set(re.findall(r"\b(?:inputs\.[\w-]+|steps\.[\w-]+\.outputs\.[\w-]+)", cond)))
    choices = [("true", "false", "restore", "save", "") if n.startswith("inputs.") else ("", "true", "false")
               for n in names]
    out = [{}]
    for name, values in zip(names, choices):
        out = [{**ctx, name: v} for ctx in out for v in values]
    return out


class PullRequestCacheTests(unittest.TestCase):
    """A pull request's runs restore caches that its earlier runs saved, and those ran the pull request's own
    code: no pull-request run may trust .cache/trureturing (re-review finding 0)."""

    WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

    def setUp(self):
        self.repo = CoreRepo().__enter__()
        self.addCleanup(self.repo.__exit__, None, None, None)
        for key in (*API_TOKENS, "GITHUB_EVENT_NAME"):
            os.environ.pop(key, None)
        os.environ["GITHUB_ACTIONS"] = "true"

    def net(self, answers):
        fake = FakeGitHub(answers)
        patcher = mock.patch.object(lean.urllib.request, "urlopen", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_cache_is_read_outside_pull_requests(self):
        plant_cache(COMMIT)
        for event in (None, "push", "schedule", "workflow_dispatch"):
            if event:
                os.environ["GITHUB_EVENT_NAME"] = event
            self.assertTrue(lean.cache_trusted(), event)
            led = lean.Ledger(TRU, offline=True)
            self.assertEqual(lean.resolve(led, COMMIT, GID_RH).kind, "theorem", "whatever the cache says")
            self.assertEqual(led.branch_contains(COMMIT, "dev"), lean.Ancestry(True, "planted (cached)"))

    def test_pull_request_runs_ask_github(self):
        gh = self.net({**raw_states(COMMIT), **branch_answers(),
                       compare_path(DEV_HEAD, COMMIT): {"status": "behind", "behind_by": 3}})
        os.environ["GITHUB_TOKEN"] = "gh"
        for event in ("pull_request", "pull_request_target"):
            plant_cache(COMMIT)
            gh.requests.clear()
            os.environ["GITHUB_EVENT_NAME"] = event
            self.assertFalse(lean.cache_trusted(), event)
            led = lean.Ledger(TRU)
            with self.assertRaisesRegex(lean.LeanError, "no frozen declaration named 'riemann_hypothesis'"):
                lean.resolve(led, COMMIT, GID_RH)
            self.assertEqual(lean.resolve(led, COMMIT, GID_3V).statement_id, "sha256:3v")
            anc = led.branch_contains(COMMIT, "dev")
            self.assertEqual(anc, lean.Ancestry(True, f"GitHub compare {DEV_HEAD[:12]} (head of dev)...{COMMIT[:12]}: "
                                                      "behind"))
            self.assertEqual([r.full_url for r in gh.requests],
                             [state_url(COMMIT, MOD_3V), api(branch_path("dev")), api(compare_path(DEV_HEAD, COMMIT))])
            for req in gh.requests[1:]:
                self.assertEqual(req.get_header("Authorization"), "Bearer gh", "github.token in CI")
            offline = lean.Ledger(TRU, offline=True)
            self.assertEqual([(type(s).__name__, s.readable) for s in offline.sources], [("CacheSource", False)],
                             "kept, to be written, but not read")
            with self.assertRaisesRegex(lean.LeanError, "the cache is not read in a pull-request run and network disabled"):
                offline.state(COMMIT, MOD_3V)
            self.assertIsNone(offline.branch_contains(COMMIT, "dev").on_branch)
            # still written (by a later run on a trusted ref it is read again): the fetched state replaced
            # the planted one
            stored = paths.CACHE / "trureturing" / COMMIT / lean.STATE_DIR / f"{MOD_3V}.lean.json"
            self.assertEqual(json.loads(stored.read_text(encoding="utf-8")), states()[MOD_3V])

    def check_lean(self, lock: lean.Lock) -> list[model.Issue]:
        issues: list[model.Issue] = []
        check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, lock, config.load_site(),
                         issues, offline=False)
        return issues

    def test_check_job_on_a_pull_request(self):
        self.repo.book()
        os.environ["GITHUB_TOKEN"] = "gh"
        os.environ["GITHUB_EVENT_NAME"] = "pull_request"
        # passes: frozen state from raw.githubusercontent.com, ancestry from the compare API
        gh = self.net({**raw_states(COMMIT), **branch_answers(), compare_path(DEV_HEAD, COMMIT): {"status": "behind"}})
        self.assertEqual(self.check_lean(make_lock()), [])
        self.assertEqual(sorted(r.full_url for r in gh.requests),
                         sorted([api(branch_path("dev")), api(compare_path(DEV_HEAD, COMMIT)), *raw_states(COMMIT)]))
        # an off-branch commit whose state and ancestry an earlier run of the pull request planted
        plant_cache(OLD_COMMIT)
        lock = make_lock()
        lock.commit = OLD_COMMIT
        self.net({**raw_states(OLD_COMMIT), **branch_answers(),
                  compare_path(DEV_HEAD, OLD_COMMIT): {"status": "diverged", "ahead_by": 1, "behind_by": 4}})
        errors = messages(self.check_lean(lock), "error")
        self.assertEqual(len(errors), 1, errors)
        self.assertIn(f"pinned commit {OLD_COMMIT[:12]} is not on branch 'dev'", errors[0])
        # nothing is read back: with GitHub unreachable a pull-request run cannot verify, cache or not
        with mock.patch.object(lean.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")):
            errors = messages(self.check_lean(make_lock()), "error")
        self.assertIn(f"could not verify that pinned commit {COMMIT[:12]} is on branch 'dev'", errors[0])
        self.assertEqual(len(errors), 1 + 3, "and every citation is unverified")
        # the same planted cache outside a pull request (a developer's machine, a run on main): read
        os.environ.pop("GITHUB_EVENT_NAME")
        with mock.patch.object(lean.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")):
            self.assertEqual(self.check_lean(lock), [])

    def test_workflows_cache_only_on_trusted_refs(self):
        trusted = [dict(event="push", ref="refs/heads/main"), dict(event="workflow_dispatch", ref="refs/heads/main"),
                   dict(event="push", ref="refs/tags/v1.2.0"), dict(event="push", ref="refs/tags/demo-v1.0.0"),
                   dict(event="schedule", ref="refs/heads/main", default_branch=None)]
        untrusted = [dict(event="pull_request", ref="refs/pull/7/merge"),
                     dict(event="pull_request_target", ref="refs/heads/main"),
                     dict(event="push", ref="refs/heads/feature"),
                     dict(event="workflow_dispatch", ref="refs/heads/feature")]
        runs = {"ci.yml": trusted[:4], "pages.yml": trusted[:2], "release.yml": trusted[2:4],
                "trureturing-bump.yml": [trusted[1], trusted[4]]}
        for name, ok in runs.items():
            text = (self.WORKFLOWS / name).read_text(encoding="utf-8")
            on = re.search(r"^on:\n((?:  .*\n|\n)*)", text, re.M).group(1)
            events = set(re.findall(r"^  ([a-z_]+):", on, re.M))
            if "workflow_call" in events:  # runs with its caller's event, whatever that is
                events |= {ctx["event"] for ctx in untrusted}
            conditions = trureturing_cache_steps(self.WORKFLOWS / name)
            self.assertEqual(len(conditions), 1, name)
            cond = conditions[0]
            self.assertTrue(cond, f"{name}: the .cache/trureturing step needs an if:")
            out = {"same": "false"} if "steps.target" in cond else {}
            for ctx in ok:
                self.assertIn(ctx["event"], events, name)
                self.assertTrue(gha_if(cond, **ctx, **out), f"{name}: {ctx}")
            for ctx in untrusted:
                if ctx["event"] in events:
                    self.assertFalse(gha_if(cond, **ctx, **out), f"{name}: {ctx}")
        self.assertEqual(trureturing_cache_steps(self.WORKFLOWS.parent / "actions" / "setup" / "action.yml"), [])

    def setup_steps(self) -> list[dict]:
        """The steps of the setup action: ``uses``, ``id``, ``if``, ``run``, ``with``…"""
        return action_steps("setup")

    def test_toolchain_caches_are_not_used_by_pull_requests(self):
        """The same holds for the toolchain caches of the setup action (pip, Playwright's Chromium, fonts, the
        film models): a pull request's runs neither restore nor save them. Its runs execute its own workflow files, so an earlier
        push of the pull request could save an entry in its cache scope (and drop the gate) for the next push to
        restore; skipping the restore, its runs download from the network (re-review 3, finding 0)."""
        steps = self.setup_steps()
        uses = [step.get("uses", "") for step in steps]
        self.assertFalse([u for u in uses if re.fullmatch(r"actions/cache@v\d+", u)],
                         "actions/cache saves in its post step, also in pull requests: use restore + save")
        python = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
        self.assertNotIn("cache", python.get("with", {}), "setup-python's own cache saves in pull requests too")
        restores = {step["with"]["path"]: step for step in steps if step.get("uses", "").startswith("actions/cache/restore@")}
        saves = {step["with"]["path"]: step for step in steps if step.get("uses", "").startswith("actions/cache/save@")}
        self.assertEqual(set(restores), {"~/.cache/pip", "~/.cache/ms-playwright", ".cache/fonts", ".cache/film/models"})
        self.assertEqual(set(saves), set(restores))
        trusted = ("push", "schedule", "workflow_dispatch")
        pull_requests = ("pull_request", "pull_request_target", "pull_request_review", "pull_request_review_comment")
        for path, save in saves.items():
            restore = restores[path]
            self.assertEqual(save["with"]["key"], f"${{{{ steps.{restore['id']}.outputs.cache-primary-key }}}}", path)
            inputs = {"inputs.browsers": "true", "inputs.fonts": "true", "steps.films.outputs.install": "true",
                      "steps.toolchain.outputs.preinstalled": "false"}
            conds = {name: re.sub(r"hashFiles\([^)]*\)", "'h'", step.get("if", ""))
                     for step, name in ((restore, "restore"), (save, "save"))}
            for name, cond in conds.items():
                self.assertIn("github.event_name", cond, f"{path}: {name}")
                # in a pull request the restore step is skipped, and with it its cache-hit output
                context = {**inputs, f"steps.{restore['id']}.outputs.cache-hit": ""}
                for event in trusted:
                    self.assertTrue(gha_if(cond, event=event, ref="refs/heads/main", context=context),
                                    f"{path}: {name} on {event}")
                for event in pull_requests:
                    self.assertFalse(gha_if(cond, event=event, ref="refs/pull/7/merge", context=context),
                                     f"{path}: {name} on {event}")
            for key in ("inputs.browsers", "inputs.fonts", "steps.films.outputs.install"):
                if key in conds["restore"]:
                    off = {**inputs, key: "false"}
                    self.assertFalse(gha_if(conds["restore"], event="push", ref="refs/heads/main", context=off), path)
            hit = {**inputs, f"steps.{restore['id']}.outputs.cache-hit": "true"}
            self.assertFalse(gha_if(conds["save"], event="push", ref="refs/heads/main", context=hit),
                             f"{path}: already cached")

    def test_npm_cache_is_checked_against_the_lockfile(self):
        """setup-node's npm cache is restored (and saved) in pull requests too. That is safe because npm ci reads
        a tarball from the cache only under the sha512 that package-lock.json records for it, and refetches one
        whose bytes do not match: every locked package must therefore carry its integrity."""
        steps = self.setup_steps()
        node = next(step for step in steps if step.get("uses", "").startswith("actions/setup-node@"))
        self.assertEqual(node["with"].get("cache"), "npm")
        self.assertEqual(node["with"].get("cache-dependency-path"), "package-lock.json")
        runs = [step.get("run", "") for step in steps]
        self.assertTrue([r for r in runs if r.startswith("npm ci ")], "installs exactly what the lockfile says")
        self.assertFalse([r for r in runs if re.search(r"\bnpm (install|i)\b", r)])
        lock = json.loads((self.WORKFLOWS.parents[1] / "package-lock.json").read_text(encoding="utf-8"))
        packages = {k: v for k, v in lock["packages"].items() if k}
        self.assertTrue(packages)
        for name, meta in packages.items():
            self.assertFalse(meta.get("link"), name)
            self.assertRegex(meta.get("integrity", ""), r"^sha512-[A-Za-z0-9+/]+=*$", name)

    def test_pull_request_workflows_restore_no_other_cache(self):
        """No other step of a workflow that can run in pull-request events restores or saves a cache there:
        actions/cache steps are skipped, and no setup-* action caches anything but npm. A workflow runs in them
        when one triggers it, or when a workflow that one triggers calls it; and every workflow that can be called
        (workflow_call) is checked too, since a books repository may call it from its own pull-request workflow
        (lean-verify.yml's Lake and pip caches, re-review 4, item 1). So are the composite actions these workflows
        use (.github/actions/setup, .github/actions/build-cache), for every value of their inputs."""
        pr_events = set(PR_EVENTS)
        texts = {wf.name: wf.read_text(encoding="utf-8") for wf in self.WORKFLOWS.glob("*.yml")}
        todo = []
        for name, text in texts.items():
            m = re.search(r"^on:(.*)\n((?:  .*\n|\n)*)", text, re.M)
            events = set(re.findall(r"[a-z_]+", m.group(1))) | set(re.findall(r"^  ([a-z_]+):", m.group(2), re.M))
            if events & (pr_events | {"workflow_call"}):
                todo.append(name)
        self.assertIn("ci.yml", todo)
        self.assertIn("lean-verify.yml", todo, "callable (workflow_call)")
        seen, caches, actions = set(), 0, set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            todo += re.findall(r"uses:\s*\./\.github/workflows/([\w.-]+)", texts[name])
            actions |= set(re.findall(r"uses:\s*\./\.github/actions/([\w.-]+)", texts[name]))
            for step in re.split(r"\n(?=\s+- )", texts[name]):
                uses = re.search(r"^\s+-?\s*uses:\s*(\S+)", step, re.M)
                uses = uses.group(1) if uses else ""
                if re.match(r"actions/cache(/restore|/save)?@", uses):
                    caches += 1
                    m = re.search(r"^(\s+)if:\s*(>-?)?\s*(.*?)$((?:\n\1\s+.*)*)", step, re.M)
                    self.assertTrue(m, f"{name}: {uses} needs an if:")
                    cond = " ".join([m.group(3), *m.group(4).split()])
                    # a skipped restore step leaves its outputs empty
                    context = {k: "" for k in re.findall(r"steps\.[\w-]+\.outputs\.[\w-]+", cond)}
                    for event in pr_events:
                        self.assertFalse(gha_if(cond, event=event, ref="refs/pull/7/merge", context=context),
                                         f"{name}: {uses} on {event}")
                elif re.match(r"actions/setup-\w+@", uses) and re.search(r"^\s+cache:", step, re.M):
                    self.assertTrue(uses.startswith("actions/setup-node@"), f"{name}: {uses} caches")
                    self.assertRegex(step, r"(?m)^\s+cache:\s*npm\s*$", name)
        self.assertIn("lean-verify.yml", seen)
        self.assertGreater(caches, 0, "ci.yml's .cache/trureturing step was examined")
        self.assertEqual(actions, {"setup", "build-cache"})
        action_caches = 0
        for action in sorted(actions):
            for step in action_steps(action):
                uses = step.get("uses", "")
                if re.match(r"actions/cache(/restore|/save)?@", uses):
                    action_caches += 1
                    self.assertNotRegex(uses, r"^actions/cache@", f"{action}: saves in its post step")
                    cond = re.sub(r"hashFiles\([^)]*\)", "'h'", step.get("if", ""))
                    self.assertTrue(cond, f"{action}: {step['name']} needs an if:")
                    for ctx in condition_values(cond):
                        for event in pr_events:
                            self.assertFalse(gha_if(cond, event=event, ref="refs/pull/7/merge", context=ctx),
                                             f"{action}: {step['name']} on {event} with {ctx}")
                elif re.match(r"actions/setup-\w+@", uses) and "cache" in step["with"]:
                    self.assertTrue(uses.startswith("actions/setup-node@"), f"{action}: {uses} caches")
                    self.assertEqual(step["with"]["cache"], "npm", action)
        self.assertEqual(action_caches, 2 * 4 + 2, "pip, Chromium, fonts, film models; the build cache")

    def test_lean_verify_caches_outside_pull_requests(self):
        """lean-verify.yml restores and saves its pip and Lake caches (built .olean files, which the axiom check
        reads) in its other events, schedule, workflow_dispatch and a release's workflow_call, as the setup
        action does: actions/cache/restore + actions/cache/save, saved only when the restore missed."""
        text = (self.WORKFLOWS / "lean-verify.yml").read_text(encoding="utf-8")
        steps = re.split(r"\n(?=      - name:)", text.split("\n    steps:\n", 1)[1])
        fields = []
        for chunk in steps:
            step = {k: m.group(1).strip() for k in ("uses", "id", "if")
                    if (m := re.search(rf"^        {k}:\s*(.*)$", chunk, re.M))}
            step["with"] = {k: m.group(1).strip() for k in ("path", "key", "cache")
                            if (m := re.search(rf"^          {k}:\s*(.*)$", chunk, re.M))}
            fields.append(step)
        self.assertFalse([s for s in fields if re.fullmatch(r"actions/cache@v\d+", s.get("uses", ""))])
        python = next(s for s in fields if s.get("uses", "").startswith("actions/setup-python@"))
        self.assertNotIn("cache", python["with"])
        restores = {s["with"]["path"]: s for s in fields if s.get("uses", "").startswith("actions/cache/restore@")}
        saves = {s["with"]["path"]: s for s in fields if s.get("uses", "").startswith("actions/cache/save@")}
        self.assertEqual(set(restores), {"~/.cache/pip", "build/lean-verify/.lake"})
        self.assertEqual(set(saves), set(restores))
        for path, save in saves.items():
            restore = restores[path]
            hit = f"steps.{restore['id']}.outputs.cache-hit"
            self.assertEqual(save["with"]["key"], f"${{{{ steps.{restore['id']}.outputs.cache-primary-key }}}}", path)
            for event in ("schedule", "workflow_dispatch", "push"):
                self.assertTrue(gha_if(restore["if"], event=event, ref="refs/heads/main"), path)
                self.assertTrue(gha_if(save["if"], event=event, ref="refs/heads/main", context={hit: ""}), path)
                self.assertFalse(gha_if(save["if"], event=event, ref="refs/heads/main", context={hit: "true"}), path)
            for event in ("pull_request", "pull_request_target", "pull_request_review"):
                self.assertFalse(gha_if(restore["if"], event=event, ref="refs/pull/7/merge"), path)
                self.assertFalse(gha_if(save["if"], event=event, ref="refs/pull/7/merge", context={hit: ""}), path)
        order = [s.get("id") or s.get("uses", "") for s in fields]
        lake = restores["build/lean-verify/.lake"]
        self.assertLess(order.index("project"), order.index(lake["id"]), "the key needs the pinned commit")
        build = next(i for i, s in enumerate(steps) if "lake build BookVerify" in s)
        self.assertLess(build, fields.index(saves["build/lean-verify/.lake"]), "saved after the build succeeded")
        self.assertNotIn("always()", saves["build/lean-verify/.lake"]["if"])


# --------------------------------------------------------------------------- the build cache in the workflows


def run_bash(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run a workflow step's ``run:`` script the way GitHub's bash shell does."""
    path = cwd / ".step.sh"
    path.write_text(script + "\n", encoding="utf-8")
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(path)], cwd=cwd,
                          env={**os.environ, **env}, capture_output=True, text=True)


FAKE_GH = """#!/usr/bin/env bash
# gh stand-in: logs its arguments; `gh release view` answers as a release in state $FAKE_STATE would.
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "release view" ]; then
  case "$FAKE_STATE" in
    none) echo "release not found" >&2; exit 1 ;;
    draft) echo true ;;
    published) echo false ;;
  esac
fi
"""


class BuildCacheWorkflowTests(unittest.TestCase):
    """The build cache store (.cache/artifacts) in GitHub Actions: who restores and who saves it, the builds
    that use it, and the releases that carry it (docs/PUBLISHING.md §5, docs/VERIFICATION.md §2)."""

    WORKFLOWS = GITHUB_DIR / "workflows"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tbook-build-cache-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_store_is_restored_outside_pull_requests_and_saved_by_the_default_branch(self):
        steps = action_steps("build-cache")
        restore, = [s for s in steps if s.get("uses", "").startswith("actions/cache/restore@")]
        save, = [s for s in steps if s.get("uses", "").startswith("actions/cache/save@")]
        prune = next(s for s in steps if s.get("id") == "prune")
        self.assertFalse([s for s in steps if re.match(r"actions/cache@", s.get("uses", ""))])
        self.assertEqual(restore["with"], {"path": ".cache/artifacts", "key": "build-cache-v1-${{ github.run_id }}",
                                           "restore-keys": "build-cache-v1-"})
        self.assertEqual(save["with"], {"path": ".cache/artifacts", "key": "${{ steps.prune.outputs.key }}"})
        self.assertLess(steps.index(prune), steps.index(save))
        default = [dict(event="push", ref="refs/heads/main"), dict(event="workflow_dispatch", ref="refs/heads/main"),
                   dict(event="schedule", ref="refs/heads/main", default_branch=None)]
        other = [dict(event="push", ref="refs/heads/feature"), dict(event="push", ref="refs/tags/v1.0.0"),
                 dict(event="workflow_dispatch", ref="refs/heads/feature"),
                 dict(event="repository_dispatch", ref="refs/heads/main"), dict(event="release", ref="refs/tags/v1.0.0")]
        pull_requests = [dict(event=e, ref="refs/pull/7/merge") for e in PR_EVENTS] + [
            dict(event="pull_request_target", ref="refs/heads/main")]
        for mode in ("restore", "save"):
            ctx = {"inputs.mode": mode, "steps.prune.outputs.changed": "true"}
            for run in default + other:
                self.assertEqual(gha_if(restore["if"], **run, context=ctx), mode == "restore", (mode, run))
            for run in default:
                for step in (prune, save):
                    self.assertEqual(gha_if(step["if"], **run, context=ctx), mode == "save", (step["name"], run))
            for run in other + pull_requests:
                for step in (prune, save):
                    self.assertFalse(gha_if(step["if"], **run, context=ctx), (step["name"], mode, run))
            for run in pull_requests:
                self.assertFalse(gha_if(restore["if"], **run, context=ctx), (mode, run))
        main = dict(event="push", ref="refs/heads/main",
                    context={"inputs.mode": "save", "steps.prune.outputs.changed": "true"})
        self.assertTrue(gha_if(save["if"], **main))
        self.assertFalse(gha_if(save["if"], **main, cancelled=True))
        for changed in ("false", ""):
            self.assertFalse(gha_if(save["if"], event="push", ref="refs/heads/main",
                                    context={"inputs.mode": "save", "steps.prune.outputs.changed": changed}))

    def test_an_unchanged_store_is_not_saved_again(self):
        """save compares the content digest of the pruned store with the one in the key restore matched (kept in
        the environment), and saves under a key of its own run: cache keys are immutable, so a store that
        returns to an earlier content (a revert) must still become the newest entry."""
        steps = action_steps("build-cache")
        remember = next(s for s in steps if "TBOOK_BUILD_CACHE_RESTORED" in s.get("run", "") and s.get("id") != "prune")
        self.assertEqual(remember["env"], {"MATCHED": "${{ steps.restore.outputs.cache-matched-key }}"})
        prune = next(s for s in steps if s.get("id") == "prune")
        (self.tmp / "tbook").write_text("#!/usr/bin/env bash\n"
                                        "printf '%s\\n' \"$*\" >> calls.txt\n"
                                        "if [ \"$*\" = 'cache key' ]; then echo build-cache-v1-abc; fi\n",
                                        encoding="utf-8")
        (self.tmp / "tbook").chmod(0o755)
        for restored, changed in (("build-cache-v1-abc-r41-1", "false"), ("build-cache-v1-abc", "false"),
                                  ("build-cache-v1-old-r40-2", "true"), ("build-cache-v1-abcd-r41-1", "true"),
                                  ("", "true")):
            out = self.tmp / "output.txt"
            out.write_text("", encoding="utf-8")
            r = run_bash(prune["run"], self.tmp, {"GITHUB_OUTPUT": str(out), "TBOOK_BUILD_CACHE_RESTORED": restored,
                                                  "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "2"})
            self.assertEqual(r.returncode, 0, r.stderr)
            outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
            self.assertEqual(outputs, {"key": "build-cache-v1-abc-r77-2", "changed": changed}, restored)
            self.assertTrue(outputs["key"].startswith("build-cache-v1-"), "restore finds it by the prefix")
        calls = (self.tmp / "calls.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls[:2], ["cache prune", "cache key"], "pruned before the key is taken")

    def building_jobs(self) -> dict[tuple[str, str], list[dict]]:
        return {(wf.name, job): steps for wf in sorted(self.WORKFLOWS.glob("*.yml"))
                for job, steps in workflow_jobs(wf).items()
                if any(re.search(r"^(?:\./tbook build\b|python tools/ci/films.py\b)", s.get("run", ""), re.M) for s in steps)}

    def test_builds_go_through_the_cache(self):
        """Every job that builds restores the store first (outside pull requests: the action decides), looks
        missing units up in releases, and builds for the Pages URL as pages.yml does, so that all of them share
        keys; jobs that build films install the film toolchain and fail when a film cannot be rendered; only
        pages.yml saves the store, after its build ran."""
        jobs = self.building_jobs()
        self.assertEqual(set(jobs), {("ci.yml", "build"), ("ci.yml", "media"), ("ci.yml", "films"), ("pages.yml", "build"),
                                     ("release.yml", "build"), ("template-release.yml", "site")})
        for (wf, job), steps in jobs.items():
            where = f"{wf}, job {job}"
            builds = [i for i, s in enumerate(steps) if re.search(r"^(?:\./tbook build\b|python tools/ci/films.py\b)", s.get("run", ""), re.M)]
            cache = [(i, s["with"].get("mode")) for i, s in enumerate(steps) if s.get("uses") == "./.github/actions/build-cache"]
            restores = [i for i, mode in cache if mode == "restore"]
            saves = [i for i, mode in cache if mode == "save"]
            self.assertEqual(len(restores), 1, where)
            self.assertLess(restores[0], builds[0], where)
            pages = [i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/configure-pages@")]
            self.assertEqual(len(pages), 1, where)
            self.assertEqual(steps[pages[0]].get("id"), "pages", where)
            self.assertLess(pages[0], restores[0], where)
            self.assertEqual(steps[restores[0]]["with"].get("pages-url"), "${{ steps.pages.outputs.base_url }}", where)
            if wf != "pages.yml":  # pages.yml asks only when its probe found Pages enabled
                self.assertEqual(steps[pages[0]].get("continue-on-error"), "true", where)
            films, film_if = False, ""
            for i in builds:
                env, run = steps[i]["env"], steps[i]["run"]
                self.assertEqual(env.get("TBOOK_CACHE_REMOTE"), "1", f"{where}: {run}")
                self.assertEqual(env.get("GITHUB_TOKEN"), "${{ github.token }}", f"{where}: {run}")
                self.assertNotIn("TBOOK_CACHE", env, where)
                if "python tools/ci/films.py" in run or re.search(r"^\./tbook build\b.*\b(all|films)\b", run, re.M):
                    films = True
                    film_if = steps[i].get("if", "")
                    self.assertEqual(env.get("TBOOK_FILMS"), "require", f"{where}: {run}")
            setup = next(s for s in steps if s.get("uses") == "./.github/actions/setup")
            wanted = setup["with"].get("films", "false")
            if films:
                self.assertEqual(setup["with"].get("browsers"), "true", where)
            if film_if:
                # the toolchain is installed exactly when the film step runs; pull requests always render
                for event, ref in (("push", "refs/heads/main"), ("push", "refs/tags/v1"), ("push", "refs/heads/x"),
                                   ("pull_request", "refs/pull/1/merge"), ("workflow_dispatch", "refs/heads/main")):
                    runs = gha_if(film_if, event=event, ref=ref)
                    self.assertEqual(gha_if(wanted, event=event, ref=ref), runs, f"{where}: {event} {ref}")
                    if event == "pull_request":
                        self.assertTrue(runs, where)
            else:
                self.assertEqual(wanted, "true" if films else "false", where)
            if wf == "pages.yml":
                self.assertEqual(len(saves), 1, where)
                self.assertGreater(saves[0], max(builds), where)
                self.assertEqual(steps[builds[0]].get("id"), "build", where)
                cond = steps[saves[0]]["if"]
                for outcome, want in (("success", True), ("failure", True), ("skipped", False)):
                    self.assertEqual(gha_if(cond, event="push", ref="refs/heads/main",
                                            context={"steps.build.outcome": outcome}), want, outcome)
                self.assertFalse(gha_if(cond, event="push", ref="refs/heads/main", cancelled=True,
                                        context={"steps.build.outcome": "failure"}))
            else:
                self.assertEqual(saves, [], f"{where}: only pages.yml saves the store")

    def test_pdf_and_epub_jobs_see_the_same_system_fonts(self):
        """PDF and EPUB keys include the font families Typst finds on the system, so every job that builds them
        installs one font set: fonts 'true', which also covers the fonts Playwright's --with-deps adds in the
        jobs that install browsers (otherwise ci.yml's build job could never restore what pages.yml saved)."""
        checked = []
        for (wf, job), steps in self.building_jobs().items():
            if (wf, job) != ("ci.yml", "build") and not any(re.search(r"^\./tbook build(?: [\w ]*)?\b(?:all|pdf|epub)\b", s.get("run", ""), re.M)
                       for s in steps):
                continue
            setup = next(s for s in steps if s.get("uses") == "./.github/actions/setup")
            self.assertEqual(setup["with"].get("fonts"), "true", f"{wf}, job {job}")
            checked.append((wf, job))
        self.assertEqual(sorted(checked), [("ci.yml", "build"), ("pages.yml", "build"), ("release.yml", "build"),
                                           ("template-release.yml", "site")])
        text = (GITHUB_DIR / "actions" / "setup" / "action.yml").read_text(encoding="utf-8")
        block = re.search(r'if \[ "\$FONTS" = "true" \]; then\n(.*?)\n\s*fi\n', text, re.S).group(1)
        listed = set(re.findall(r"\b(x?fonts-[\w.-]+)", block))
        deps = GITHUB_DIR.parent / "node_modules" / "playwright-core" / "lib" / "server" / "registry" / "nativeDeps.js"
        if not deps.is_file():
            self.skipTest("node_modules/playwright-core is not installed")
        r = subprocess.run(["node", "-e", "const d=require(process.argv[1]).deps['ubuntu24.04-x64'];"
                            "console.log([...d.tools,...d.chromium].filter(p=>/^x?fonts-/.test(p)).join(' '))",
                            str(deps)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        playwright = set(r.stdout.split())
        self.assertTrue(playwright)
        self.assertLessEqual(playwright, listed, "fonts 'true' installs every font Playwright's --with-deps adds")

    def test_films_render_once_per_change(self):
        """ci.yml leaves the films to pages.yml on the default branch and to the release workflows on tags,
        which build them (pages.yml also stores them); a film is not rendered by two runs of one push."""
        text = (self.WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        match = re.search(r"(?ms)^  films:\n.*?^    if: >-\n(.*?)^    runs-on:", text)
        self.assertTrue(match)
        condition = " ".join(match.group(1).split())
        self.assertFalse(gha_if(condition, event="push", ref="refs/heads/main"))
        self.assertFalse(gha_if(condition, event="push", ref="refs/tags/v1.0.0"))
        self.assertTrue(gha_if(condition, event="workflow_dispatch", ref="refs/heads/feature"))
        self.assertTrue(gha_if(condition, event="pull_request", ref="refs/pull/7/merge"))

    def test_pages_build_step_times_out_before_the_job(self):
        """A step that runs out of time fails and the save still runs; a job that does is cancelled and
        loses every unit it built."""
        steps = workflow_jobs(self.WORKFLOWS / "pages.yml")["build"]
        build = next(s for s in steps if s.get("id") == "build")
        job = re.search(r"(?m)^  build:\n(?:    .*\n)*?    timeout-minutes: (\d+)$",
                        (self.WORKFLOWS / "pages.yml").read_text(encoding="utf-8"))
        self.assertTrue(job)
        self.assertLess(int(build["timeout-minutes"]) + 15, int(job.group(1)))

    def test_pages_runs_one_at_a_time(self):
        """The workflow that saves the store and renders films for it runs one run at a time; a later run
        restores what the earlier one saved instead of rendering the same film again."""
        text = (self.WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^concurrency:\n  group: pages\n  cancel-in-progress: false$")

    def publish_step(self, workflow: str) -> dict:
        steps = workflow_jobs(self.WORKFLOWS / workflow)["publish"]
        return next(s for s in steps if "gh release create" in s.get("run", ""))

    def run_publish(self, workflow: str, state: str, env: dict[str, str]) -> tuple[subprocess.CompletedProcess, list[str]]:
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "gh").write_text(FAKE_GH, encoding="utf-8")
        (bin_dir / "gh").chmod(0o755)
        log = self.tmp / f"gh-{state}.log"
        log.write_text("", encoding="utf-8")
        summary = self.tmp / "summary.md"
        r = run_bash(self.publish_step(workflow)["run"], self.tmp, {
            **env, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(log), "FAKE_STATE": state,
            "GH_TOKEN": "t", "GH_REPO": "o/r", "GITHUB_REPOSITORY": "o/r", "GITHUB_STEP_SUMMARY": str(summary),
            "RUNNER_TEMP": str(self.tmp / "runner")})
        return r, log.read_text(encoding="utf-8").splitlines()

    def check_publish(self, workflow: str, env: dict[str, str], files: list[str], publish_flags: str) -> None:
        """Created as a draft with every file, published after; an earlier attempt's draft gets its files
        replaced, then published; a published release keeps its files."""
        r, calls = self.run_publish(workflow, "none", env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        create = next(c for c in calls if c.startswith("release create "))
        self.assertIn(" --draft ", create)
        self.assertTrue(create.endswith(" ".join(files)), create)
        self.assertEqual(calls[-1], f"release edit {env['TAG']} --draft=false{publish_flags}")
        self.assertLess(calls.index(create), len(calls) - 1)
        self.assertFalse([c for c in calls if c.startswith("release upload")])

        r, calls = self.run_publish(workflow, "draft", env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        upload = next(c for c in calls if c.startswith("release upload "))
        self.assertEqual(upload, f"release upload {env['TAG']} {' '.join(files)} --clobber")
        self.assertEqual(calls[-1], f"release edit {env['TAG']} --draft=false{publish_flags}")
        self.assertFalse([c for c in calls if c.startswith("release create")])

        r, calls = self.run_publish(workflow, "published", env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already published", r.stdout)
        self.assertFalse([c for c in calls if re.match(r"release (create|upload)|.*--draft=false", c)], calls)

    def test_release_attaches_the_build_cache_and_publishes_a_complete_draft(self):
        jobs = workflow_jobs(self.WORKFLOWS / "release.yml")
        runs = [s.get("run", "") for s in jobs["build"]]
        build = runs.index("./tbook build all")
        export = runs.index("./tbook cache export release/cache")
        self.assertLess(build, export)
        upload = next(s for s in jobs["build"] if s.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertLess(export, jobs["build"].index(upload))
        self.assertEqual((upload["with"]["name"], upload["with"]["path"]), ("release", "release"))
        download = next(s for s in jobs["publish"] if s.get("uses", "").startswith("actions/download-artifact@"))
        self.assertEqual((download["with"]["name"], download["with"]["path"]), ("release", "release"))
        for d in ("release/assets", "release/cache"):
            (self.tmp / d).mkdir(parents=True)
        files = ["release/assets/demo-1.0.0-zh-screen.pdf", "release/cache/build-cache.json",
                 "release/cache/cache-films-demo-001-x-0123456789abcdef.tar"]
        for f in files:
            (self.tmp / f).write_text("x", encoding="utf-8")
        (self.tmp / "release" / "notes.md").write_text("notes\n", encoding="utf-8")
        env = {"TAG": "demo-v1.0.0", "TITLE": "Demo 1.0.0", "PRERELEASE": "false"}
        self.check_publish("release.yml", env, files, "")
        self.check_publish("release.yml", {**env, "PRERELEASE": "true"}, files, " --prerelease")
        (self.tmp / "release" / "cache" / "build-cache.json").unlink()
        r, calls = self.run_publish("release.yml", "none", env)
        self.assertNotEqual(r.returncode, 0, "a release without its build cache is not created")
        self.assertEqual(calls, [])

    def test_template_release_attaches_the_example_site_cache(self):
        jobs = workflow_jobs(self.WORKFLOWS / "template-release.yml")
        runs = [s.get("run", "") for s in jobs["site"]]
        self.assertLess(runs.index("./tbook build all"), runs.index('./tbook cache export "$RUNNER_TEMP/build-cache"'))
        upload = next(s for s in jobs["site"] if s.get("uses", "").startswith("actions/upload-artifact@"))
        download = next(s for s in jobs["publish"] if s.get("uses", "").startswith("actions/download-artifact@"))
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/build-cache")
        self.assertEqual((download["with"]["name"], download["with"]["path"]),
                         (upload["with"]["name"], "${{ runner.temp }}/build-cache"))
        text = (self.WORKFLOWS / "template-release.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  publish:\n(?:    .*\n)*?    needs: \[verify, ci, site\]$")
        cache = self.tmp / "runner" / "build-cache"
        cache.mkdir(parents=True)
        files = [str(cache / "build-cache.json"), str(cache / "cache-html-example-zh-0123456789abcdef.tar")]
        for f in files:
            Path(f).write_text("x", encoding="utf-8")
        (self.tmp / "runner" / "notes.md").write_text("notes\n", encoding="utf-8")
        env = {"TAG": "v0.2.0", "VERSION": "0.2.0", "PRERELEASE": "false"}
        self.check_publish("template-release.yml", env, files, " --latest")
        self.check_publish("template-release.yml", {**env, "PRERELEASE": "true"}, files, " --prerelease")


# --------------------------------------------------------------------------- re-review 1: a committed .cache symlink


class CommittedCacheSymlinkTests(unittest.TestCase):
    def test_symlink_is_reported_by_its_own_name(self):
        with CoreRepo() as repo:
            git(repo.root, "init", "-q")
            write(repo.root / ".gitignore", "/.cache/\n/node_modules/\n")
            pkg = repo.root / "node_modules" / "evil-pkg"
            write(pkg / "trureturing" / COMMIT / lean.ANCESTRY_FILE, json.dumps({f"{TRU}@dev": "planted"}))
            os.symlink("node_modules/evil-pkg", repo.root / ".cache")
            check.check_cache(issues := [])
            self.assertEqual(issues, [], "an untracked symlink is a local choice")
            git(repo.root, "add", ".gitignore", ".cache")
            self.assertEqual(git(repo.root, "ls-files", "-s", "--", ".cache").split()[0], "120000")
            check.check_cache(issues := [])
            self.assertEqual([i.severity for i in issues], ["error"], "a committed .cache symlink")
            self.assertIn(".cache", issues[0].format())
            self.assertNotIn("evil-pkg", issues[0].format(), "named as committed, not by its target")
            self.assertIn("git rm -r --cached .cache", issues[0].message)
            git(repo.root, "rm", "-q", "--cached", ".cache")
            os.unlink(repo.root / ".cache")
            outside = Path(tempfile.mkdtemp(prefix="tbook-cache-"))
            self.addCleanup(__import__("shutil").rmtree, outside, True)
            os.symlink(outside, repo.root / ".cache")
            check.check_cache(issues := [])
            self.assertEqual(issues, [], "an untracked symlink outside the repository")


# --------------------------------------------------------------------------- re-review 2: lock.branch and site.toml


class LockBranchTests(unittest.TestCase):
    def run_lean(self, ledger, lock=None):
        with mock.patch.object(lean, "Ledger", lambda repo, **kw: ledger):
            issues: list[model.Issue] = []
            check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, lock or make_lock(),
                             config.load_site(), issues, offline=True)
            return issues

    def test_lock_branch_must_match_site_toml(self):
        with CoreRepo(site=SITE_FAKE_BRANCH) as repo:
            repo.book()
            os.environ.pop("GITHUB_ACTIONS", None)
            led = FakeLedger(on_branch=True)
            issues = self.run_lean(led)
            self.assertEqual([(i.severity, i.path) for i in issues], [("error", paths.LOCK_FILE)])
            self.assertIn("lock was pinned against branch 'dev' but site.toml uses 'fake'; run ./tbook pin",
                          issues[0].message)
            self.assertEqual(led.ancestry_calls, [(COMMIT, "fake")], "verified against site.toml's branch")
            legacy = make_lock()
            legacy.branch = ""
            self.assertEqual(self.run_lean(FakeLedger(on_branch=True), legacy), [], "no branch recorded")
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger(on_branch=True)):
                make_lock().save()
                report = pin.pin(refresh=True, offline=True)
            self.assertTrue(report.written, report.markdown())
            self.assertIn("Branch: `dev` → `fake`", report.markdown())
            self.assertEqual(lean.Lock.load().branch, "fake", "--refresh re-verifies on the new branch")
            self.assertEqual(self.run_lean(FakeLedger(on_branch=True), lean.Lock.load()), [])

    def test_commit_sha_is_not_a_branch(self):
        for branch in (COMMIT, COMMIT[:7], COMMIT[:12].upper(), "refs/heads/dev"):
            with self.subTest(branch=branch), CoreRepo(site=SITE.replace('branch = "dev"', f'branch = "{branch}"')) as repo:
                repo.book()
                os.environ.pop("GITHUB_ACTIONS", None)
                lock = make_lock()
                lock.branch = branch
                led = FakeLedger(on_branch=True)
                errors = messages(self.run_lean(led, lock), "error")
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(f"[trureturing] branch {branch!r}", errors[0])
                self.assertEqual(led.ancestry_calls, [], "no ancestry question against a non-branch")
                self.assertTrue(lean.branch_problem(branch, COMMIT))
                with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger(on_branch=True)):
                    with self.assertRaisesRegex(lean.LeanError, "branch"):
                        pin.pin(COMMIT, offline=True, dry_run=True)
        self.assertEqual(lean.branch_problem("dev", COMMIT), "")
        self.assertEqual(lean.branch_problem("facade", COMMIT), "", "hex letters, but not the pinned commit")
        self.assertEqual(lean.branch_problem("release/1", COMMIT), "")

    def test_ledger_refuses_a_sha_as_branch(self):
        with CoreRepo():
            for key in API_TOKENS:
                os.environ.pop(key, None)
            h = History()
            self.addCleanup(h.cleanup)
            h.track("origin", UPSTREAM)
            desc = "9" * 40  # an unmerged descendant of the pinned commit, written as the "branch"
            # what GitHub's compare API answers for these names (it reads them as commits); never asked now
            gh = FakeGitHub({compare_path(COMMIT, COMMIT): {"status": "identical", "base_commit": {"sha": COMMIT}},
                             compare_path(COMMIT[:7], COMMIT): {"status": "identical", "base_commit": {"sha": COMMIT}},
                             compare_path(desc[:10], COMMIT): {"status": "behind", "base_commit": {"sha": desc}},
                             compare_path(h.b[:10], h.a): {"status": "behind", "base_commit": {"sha": h.b}},
                             **branch_answers("facade", "1" * 40), compare_path("1" * 40, COMMIT): {"status": "behind"}})
            with mock.patch.object(lean.urllib.request, "urlopen", gh):
                led = lean.Ledger(TRU)
                for branch in (COMMIT, COMMIT[:7]):
                    anc = led.branch_contains(COMMIT, branch)
                    self.assertIsNone(anc.on_branch, branch)
                    self.assertIn("is a commit SHA, not a branch", anc.detail)
                self.assertEqual(gh.requests, [], "refused before asking GitHub")
                anc = lean.github_branch_contains(TRU, COMMIT, COMMIT)
                self.assertIsNone(anc.on_branch, "compare/<sha>...<sha> is 'identical'")
                anc = led.branch_contains(COMMIT, desc[:10])
                self.assertEqual((anc.on_branch, anc.no_branch), (False, True), "no branch has that name")
                self.assertIn(f"has no branch {desc[:10]!r}", anc.detail)
                self.assertTrue(led.branch_contains(COMMIT, "facade").on_branch, "a branch named in hex letters")
                anc = lean.Ledger(TRU, checkout=h.dir).branch_contains(h.a, h.b[:10])
                self.assertEqual((anc.on_branch, anc.no_branch), (False, True), "neither the checkout nor GitHub")
                self.assertFalse([r for r in gh.requests if "/compare/" in r.full_url and "1111" not in r.full_url])
            cached = json.loads((paths.CACHE / "trureturing" / COMMIT / lean.ANCESTRY_FILE).read_text(encoding="utf-8"))
            self.assertEqual(list(cached), [f"{TRU}@facade"], "only the real branch's answer is cached")
            self.assertFalse((paths.CACHE / "trureturing" / h.a / lean.ANCESTRY_FILE).exists())


SITE_FAKE_BRANCH = SITE.replace('branch = "dev"', 'branch = "fake"')


# --------------------------------------------------------------------------- re-review 3: names that are not branches

# (name, refused by lean.branch_problem, refused by `git check-ref-format --branch`; None: git cannot be asked).
# branch_problem refuses everything git refuses, and also full refs, commit SHAs, a bare '@' (git's HEAD) and
# Unicode whitespace or invisible characters.
BRANCH_NAMES = [
    ("dev", False, False), ("main", False, False), ("release/1", False, False), ("feature/x-y_z.1", False, False),
    ("facade", False, False), ("a.b", False, False), ("a./b", False, False), ("a/-b", False, False),
    ("dev@", False, False), ("@dev", False, False), ("a@b", False, False), ("x/@", False, False),
    ("a{b", False, False), ("a]b", False, False), ("HEAD/x", False, False), ("x/HEAD", False, False),
    ("head", False, False), ("a.lock.x", False, False), ("héllo", False, False), ("v1.2", False, False),
    # revision syntax GitHub's compare API resolves to a commit, and another repository's branch
    (COMMIT + "^0", True, True), (COMMIT + "~0", True, True), (COMMIT[:12] + "^0", True, True),
    (COMMIT + "^{commit}", True, True), ("dev^0", True, True), ("dev~1", True, True), ("dev^", True, True),
    ("mallory:dev", True, True), ("dev@{0}", True, True), ("dev@{1.day.ago}", True, True), ("@{-1}", True, True),
    ("@{u}", True, True), ("HEAD", True, True), ("dev..main", True, True), ("dev...main", True, True),
    # the rest of git's rules
    ("a?b", True, True), ("a*b", True, True), ("a[b", True, True), ("a\\b", True, True), ("a b", True, True),
    (" dev", True, True), ("dev ", True, True), ("a\tb", True, True), ("a\nb", True, True), ("a\x01b", True, True),
    ("a\x7fb", True, True), ("-dev", True, True), ("-", True, True), (".dev", True, True), ("a/.b", True, True),
    ("a/./b", True, True), ("a/..", True, True), ("dev.", True, True), ("a/b.", True, True), ("dev/", True, True),
    ("/dev", True, True), ("a//b", True, True), ("dev.lock", True, True), ("a/b.lock", True, True),
    ("a.lock/b", True, True), (".lock", True, True), ("HEAD.lock", True, True), ("", True, True),
    ("a\x00b", True, None),
    # refused here although git would take them as branch names
    ("@", True, False), ("refs/heads/dev", True, False), ("refs/x", True, False), (COMMIT, True, False),
    (COMMIT[:7], True, False), (COMMIT[:12].upper(), True, False), ("a\u00a0b", True, False),
    ("dev\u3000", True, False), ("de\u200bv", True, False), ("a\u2028b", True, False),
]


class BranchNameTests(unittest.TestCase):
    def test_branch_names_follow_git(self):
        """branch_problem refuses every name `git check-ref-format --branch` refuses (and a few more)."""
        for name, refused, git_refuses in BRANCH_NAMES:
            with self.subTest(name=name):
                self.assertEqual(bool(lean.branch_problem(name, COMMIT)), refused, lean.branch_problem(name, COMMIT))
                self.assertTrue(refused or not git_refuses, "the table: what git refuses is refused")
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        with tempfile.TemporaryDirectory(prefix="tbook-refname-") as tmp:
            # outside any repository: git then takes '@{-1}' and the like literally
            env = dict(os.environ, **GIT_ENV, GIT_CEILING_DIRECTORIES=str(Path(tmp).parent))
            for name, _, git_refuses in BRANCH_NAMES:
                if git_refuses is None:
                    continue
                with self.subTest(git=name):
                    r = subprocess.run(["git", "check-ref-format", "--branch", name], cwd=tmp, env=env,
                                       capture_output=True, text=True)
                    self.assertEqual(r.returncode != 0, git_refuses, r.stderr)

    def test_reasons_are_specific(self):
        problem = lean.branch_problem(COMMIT + "^0", COMMIT)
        self.assertIn("is not a branch name", problem)
        self.assertIn("'^'", problem)
        self.assertIn("git check-ref-format", problem)
        self.assertIn("another repository", lean.branch_problem("mallory:dev", COMMIT))
        self.assertIn("'@{'", lean.branch_problem("dev@{0}", COMMIT))
        self.assertIn("HEAD", lean.branch_problem("HEAD", COMMIT))
        self.assertIn("HEAD", lean.branch_problem("@", COMMIT))
        self.assertIn("whitespace", lean.branch_problem(" dev", COMMIT))
        self.assertIn("'.lock'", lean.branch_problem("dev.lock", COMMIT))
        self.assertEqual(lean.branch_problem("", COMMIT), "is empty")
        self.assertIn("full ref", lean.branch_problem("refs/heads/dev", COMMIT))
        self.assertEqual(lean.branch_problem(COMMIT, COMMIT), "is a commit SHA, not a branch")

    def test_revision_expressions_do_not_pass_check_or_pin(self):
        """GitHub's compare API reads '<sha>^0' and '<sha>~0' as the commit itself (status 'identical'): a
        pull-request run that let such a "branch" through would accept an unmerged commit (finding 1)."""
        for branch in (COMMIT + "^0", COMMIT + "~0", COMMIT[:12] + "^0", "mallory:dev", "dev@{0}", "HEAD", "@"):
            with self.subTest(branch=branch), CoreRepo(site=SITE.replace('"dev"', json.dumps(branch))) as repo:
                repo.book()
                for key in API_TOKENS:
                    os.environ.pop(key, None)
                os.environ.update(GITHUB_ACTIONS="true", GITHUB_EVENT_NAME="pull_request", GITHUB_TOKEN="gh")
                quoted = urllib.parse.quote(branch, safe="/")
                gh = FakeGitHub({**raw_states(COMMIT),
                                 compare_path(quoted, COMMIT): {"status": "identical", "base_commit": {"sha": COMMIT}}})
                lock = make_lock()
                lock.branch = branch
                with mock.patch.object(lean.urllib.request, "urlopen", gh):
                    issues: list[model.Issue] = []
                    check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, lock,
                                     config.load_site(), issues, offline=False)
                    errors = [i for i in issues if i.severity == "error"]
                    self.assertEqual([i.path for i in errors], [paths.SITE_TOML], messages(issues))
                    self.assertIn(f"[trureturing] branch {branch!r} is not a branch name", errors[0].message)
                    led = lean.Ledger(TRU)
                    self.assertIsNone(led.branch_contains(COMMIT, branch).on_branch)
                    self.assertIsNone(lean.github_branch_contains(TRU, branch, COMMIT).on_branch)
                    self.assertFalse([r for r in gh.requests if "/compare/" in r.full_url], "GitHub is not asked")
                    with self.assertRaisesRegex(lean.LeanError, r"\[trureturing\] branch .* is not a branch name"):
                        pin.pin(COMMIT, dry_run=True)
                self.assertFalse(paths.LOCK_FILE.exists(), "nothing written")
        # Valid branch names that are no branch of trureturing. GitHub's compare API reads git describe output
        # ('dev-12-g<sha7>': the abbreviated commit after '-g') as that commit, also 'pull/<n>/head' (a pull
        # request's head), and answers 'identical'; its branches endpoint answers 404 (re-review 4, item 0).
        for branch in (f"dev-12-g{COMMIT[:7]}", f"x-0-g{COMMIT[:12]}", f"release/2026-1-g{COMMIT[:8]}",
                       "pull/123/head", "no-such-branch"):
            with self.subTest(branch=branch), CoreRepo(site=SITE.replace('"dev"', json.dumps(branch))) as repo:
                repo.book()
                for key in API_TOKENS:
                    os.environ.pop(key, None)
                os.environ.update(GITHUB_ACTIONS="true", GITHUB_EVENT_NAME="pull_request", GITHUB_TOKEN="gh")
                self.assertEqual(lean.branch_problem(branch, COMMIT), "", "syntactically a branch name")
                answers = {**raw_states(COMMIT), f"repos/{TRU}": {"full_name": TRU},
                           compare_path(branch, COMMIT): {"status": "identical", "base_commit": {"sha": COMMIT}}}
                gh = FakeGitHub(answers)  # branches/<branch>: 404, as GitHub answers
                lock = make_lock()
                lock.branch = branch
                with mock.patch.object(lean.urllib.request, "urlopen", gh):
                    issues: list[model.Issue] = []
                    check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, lock,
                                     config.load_site(), issues, offline=False)
                    errors = messages(issues, "error")
                    self.assertEqual(len(errors), 1, messages(issues))
                    self.assertIn(f"{TRU} has no branch {branch!r}", errors[0])
                    self.assertIn("[trureturing] branch in site.toml must name an existing branch", errors[0])
                    for anc in (lean.Ledger(TRU).branch_contains(COMMIT, branch),
                                lean.github_branch_contains(TRU, branch, COMMIT)):
                        self.assertEqual((anc.on_branch, anc.no_branch), (False, True), anc.detail)
                    self.assertFalse([r for r in gh.requests if "/compare/" in r.full_url], "compare is not asked")
                    report = pin.pin(COMMIT, dry_run=True)
                    self.assertIn(f"[trureturing] branch {branch!r} is not a branch of {TRU}", report.refused)
                    self.assertIn("**Refused (lock not written):**", report.markdown())
                    self.assertFalse(report.written)
                    os.environ.pop("GITHUB_ACTIONS")
                    self.assertTrue(pin.pin(COMMIT, dry_run=True).refused, "refused outside GitHub Actions too")
                    os.environ["GITHUB_ACTIONS"] = "true"
                # a repository GitHub does not show (private, no token): nobody can tell, an error in CI
                del answers[f"repos/{TRU}"]
                with mock.patch.object(lean.urllib.request, "urlopen", FakeGitHub(answers)):
                    anc = lean.github_branch_contains(TRU, branch, COMMIT)
                    self.assertEqual((anc.on_branch, anc.no_branch), (None, False), anc.detail)
                    issues = []
                    check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, lock,
                                     config.load_site(), issues, offline=False)
                    self.assertIn("could not verify that pinned commit", messages(issues, "error")[0])
                    self.assertIn("could not verify", pin.pin(COMMIT, dry_run=True).refused)
                self.assertFalse(paths.LOCK_FILE.exists(), "nothing written")


class NoSuchBranchTests(unittest.TestCase):
    """What else follows from "the branch must exist" (re-review 4, item 0)."""

    def test_answers_cached_by_earlier_versions_are_not_read(self):
        """Earlier versions cached positive answers for names that are no branch (git describe output)."""
        with CoreRepo():
            old = paths.CACHE / "trureturing" / COMMIT / ".tbook-on-branch.json"
            write(old, json.dumps({f"{TRU}@dev-12-g{COMMIT[:7]}": "ancestor of origin/dev-12-gaaaaaaa"}))
            self.assertNotEqual(lean.ANCESTRY_FILE, old.name)
            anc = lean.Ledger(TRU, offline=True).branch_contains(COMMIT, f"dev-12-g{COMMIT[:7]}")
            self.assertIsNone(anc.on_branch)

    def test_check_reports_a_missing_branch_under_site_toml(self):
        """A branch the repository does not have is a mistake in site.toml: check says so there and names the
        fix, instead of asking for a pin on that branch (re-review 5, item 18)."""
        branch = "no-such-branch"
        with CoreRepo(site=SITE.replace('"dev"', json.dumps(branch))) as repo:
            repo.book()
            for key in API_TOKENS:
                os.environ.pop(key, None)
            os.environ.pop("GITHUB_ACTIONS", None)
            lock = make_lock()
            lock.branch = branch

            def run(**kw) -> list[model.Issue]:
                issues: list[model.Issue] = []
                check.check_lean({"demo": model.load_book_models(config.load_book("demo"))}, lock,
                                 config.load_site(), issues, **kw)
                return issues

            gh = FakeGitHub({**raw_states(COMMIT), f"repos/{TRU}": {"full_name": TRU}})  # branches/<branch>: 404
            with mock.patch.object(lean.urllib.request, "urlopen", gh):
                issues = run(offline=False)
            self.assertEqual([(i.severity, i.path) for i in issues], [("error", paths.SITE_TOML)], messages(issues))
            message = issues[0].message
            self.assertIn(f"[trureturing] branch {branch!r} does not exist in {TRU} "
                          f"(GitHub: {TRU} has no branch {branch!r}", message)
            self.assertIn(f"set it to an existing branch (default 'dev'), then run ./tbook pin --refresh to keep "
                          f"commit {COMMIT[:12]} if it is on that branch, or ./tbook pin", message)
            self.assertNotIn("Pin a commit on", message)
            # a branch that exists but does not contain the commit: unchanged, under the lock file
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger(on_branch=False)):
                issues = run(offline=True)
            self.assertEqual([(i.severity, i.path) for i in issues], [("error", paths.LOCK_FILE)], messages(issues))
            self.assertIn(f"is not on branch {branch!r} of {TRU} (fake: not on branch)", issues[0].message)
            self.assertIn(f"Pin a commit on {branch}: ./tbook pin", issues[0].message)

    def test_doctor_reports_a_missing_branch(self):
        from tbook import doctor

        with CoreRepo():
            led = FakeLedger()
            led.ancestry = lean.Ancestry(False, f"GitHub: {TRU} has no branch 'dev'", no_branch=True)
            with mock.patch.object(lean, "Ledger", lambda repo, **kw: led):
                report = doctor.Report()
                doctor.check_branch(report, f"{TRU}@{COMMIT}")
        c = report.checks[0]
        self.assertFalse(c.ok)
        self.assertTrue(c.is_required)
        self.assertIn("no branch dev", c.detail)
        self.assertIn("[trureturing] branch in site.toml", c.hint)


if __name__ == "__main__":
    unittest.main()
