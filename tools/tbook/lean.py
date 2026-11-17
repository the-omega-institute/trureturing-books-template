"""Resolve Lean declarations against trureturing's frozen ledger at a pinned commit.

In trureturing, a module's declarations are kernel-verified and frozen exactly when
``Golden/Frozen/state/<module>.lean.json`` exists (CLAUDE.md §1.3, the freeze rule).
Each state file lists ``{statement_id, declarations: [{declaration_name_key, kind}]}``,
where a name key encodes a Lean ``Name`` with length-prefixed components::

    ns(ns(ns(ns(n0,2:D5),2:S1),7:Deficit),20:deficit_three_valued)  ==  D5.S1.Deficit.deficit_three_valued

Books cite declarations by GID, the same address trureturing's Blueprint uses.  The
downstream evidence lock is sharded by module under ``trureturing-lock/``; its
historical root JSON is only a pointer:
``<module path>.<name>``, e.g. ``D5/S1/Deficit/DeficitThreeValued.deficit_three_valued``.
The name part is a Lean name (identifier components such as ``of_ρ_eq_self`` or ``mk₂?``,
or ``«…»``-escaped ones); its components are matched against the module's frozen
declarations exactly or as a suffix; exactly one match is required (as in trureturing's
LeanReferenceResolver).

State files are read from, in order: a local trureturing checkout (``$TRURETURING_DIR``
or ``../trureturing``) via ``git show <commit>:<path>``; the cache under
``.cache/trureturing/<commit>/``; ``raw.githubusercontent.com`` at the commit. A pull
request's GitHub Actions run never reads the cache (``cache_trusted``): the cache it
restores may have been saved by an earlier run of the same pull request, i.e. by its code.

The freeze rule is enforced by trureturing's CI on its integration branch (``dev``), so a
pinned commit must be reachable from that branch (``Ledger.branch_contains``): raw URLs
also serve commits that were never merged (pull-request heads, other branches). The
branch must be a valid branch name, not a commit SHA, a full ref or a revision expression
such as ``<sha>^0`` (``branch_problem``), and an existing branch of the repository: the
name is looked up as a ref or a branch, never read as a revision, which would take git
describe output such as ``dev-12-g<sha>`` for the commit it abbreviates (``_branch_ref``,
``github_branch_contains``).
"""

from __future__ import annotations

import json
import contextlib
import fcntl
import os
import re
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import paths

# The name part is validated component by component (``name_components``): Lean identifiers
# allow Greek and letter-like symbols, subscripts, ``'``, ``!`` and ``?``, and ``«…»`` escapes.
GID_RE = re.compile(r"^(?P<module>D[0-9]+/S[0-9]+/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>.+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ABBREV_SHA_RE = re.compile(r"^[0-9a-f]{4,39}$")
HEXISH_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")  # a name that git and GitHub can also read as a commit SHA
STATE_DIR = "Golden/Frozen/state"
LOCK_SCHEMA = "trureturing-books.lock.v1"
SHARDED_LOCK_SCHEMA = "trureturing-books.lock.v3"
SHARDED_LOCK_SCHEMA_V2 = "trureturing-books.lock.v2"
LOCK_POINTER_SCHEMA = "trureturing-books.lock-pointer.v2"
MODULE_LOCK_SCHEMA = "trureturing-books.lock-module.v1"
FORMAL_KINDS = {"theorem"}
STD_AXIOMS = ("propext", "Classical.choice", "Quot.sound")


class LeanError(Exception):
    pass


# --------------------------------------------------------------------------- names


def parse_name_key(key: str) -> list[str | int]:
    """Decode a ``declaration_name_key`` into Lean name components."""

    def parse(i: int) -> tuple[list[str | int], int]:
        if key.startswith("n0", i):
            return [], i + 2
        tag = key[i:i + 3]
        if tag not in ("ns(", "nn("):
            raise LeanError(f"bad name key at {i}: {key[i:i + 20]!r}")
        parent, i = parse(i + 3)
        if i >= len(key) or key[i] != ",":
            raise LeanError(f"bad name key at {i}: expected ','")
        i += 1
        if tag == "ns(":
            colon = key.index(":", i)
            length = int(key[i:colon])
            start = colon + 1
            # trureturing writes component lengths in UTF-8 bytes (e.g. ``5:mk₂``).
            raw = key[start:].encode("utf-8")[:length]
            try:
                comp: str | int = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LeanError(f"bad name key at {start}: length splits a UTF-8 sequence") from exc
            i = start + len(comp)
        else:
            close = key.index(")", i)
            comp = int(key[i:close])
            i = close
        if i >= len(key) or key[i] != ")":
            raise LeanError(f"bad name key at {i}: expected ')'")
        return parent + [comp], i + 1

    comps, end = parse(0)
    if end != len(key):
        raise LeanError(f"trailing characters in name key: {key[end:]!r}")
    return comps


def _letter_like(o: int) -> bool:
    """Lean 4 ``isLetterLike``: Greek (but λ, Π, Σ), Coptic, letter-like symbols, math alphanumerics."""
    return ((0x3B1 <= o <= 0x3C9 and o != 0x3BB) or (0x391 <= o <= 0x3A9 and o not in (0x3A0, 0x3A3))
            or 0x3CA <= o <= 0x3FB or 0x1F00 <= o <= 0x1FFE or 0x2100 <= o <= 0x214F or 0x1D49C <= o <= 0x1D59F)


def _subscript(o: int) -> bool:
    """Lean 4 ``isSubScriptAlnum``: ₀–₉, ₐ–ₜ, ᵢ–ᵪ."""
    return 0x2080 <= o <= 0x2089 or 0x2090 <= o <= 0x209C or 0x1D62 <= o <= 0x1D6A


def _id_first(ch: str) -> bool:
    return (ch.isascii() and (ch.isalpha() or ch == "_")) or _letter_like(ord(ch))


def _id_rest(ch: str) -> bool:
    return _id_first(ch) or (ch.isascii() and ch.isdigit()) or ch in "'!?" or _subscript(ord(ch))


def is_identifier(comp: str) -> bool:
    """Whether ``comp`` is a Lean 4 identifier component that needs no ``«…»`` escape."""
    return bool(comp) and _id_first(comp[0]) and all(_id_rest(ch) for ch in comp[1:])


def name_to_str(comps: list[str | int]) -> str:
    out = []
    for c in comps:
        if isinstance(c, int):
            out.append(str(c))
        elif is_identifier(c):
            out.append(c)
        else:
            out.append("«" + c + "»")
    return ".".join(out)


def name_components(text: str) -> list[str]:
    """Components of a written Lean name: ``Foo.«a.b».of_ρ_eq_self`` → ``["Foo", "a.b", "of_ρ_eq_self"]``.

    Plain components must be Lean identifiers; ``«…»`` encloses any other component.
    """
    comps: list[str] = []
    i, n = 0, len(text)
    while True:
        if text.startswith("«", i):
            j = text.find("»", i + 1)
            comp = text[i + 1:j] if j > 0 else ""
            if not comp or "«" in comp:
                raise LeanError(f"bad «…» component in Lean name {text!r}")
            i = j + 1
        else:
            j = text.find(".", i)
            j = n if j < 0 else j
            comp = text[i:j]
            if not is_identifier(comp):
                raise LeanError(f"{comp!r} is not a Lean identifier (in {text!r}); escape it as «…»")
            i = j
        comps.append(comp)
        if i == n:
            return comps
        if text[i] != "." or i + 1 == n:
            raise LeanError(f"malformed Lean name {text!r}")
        i += 1


def is_private(comps: list[str | int]) -> bool:
    return "_private" in comps


@dataclass(frozen=True)
class Gid:
    module: str
    name: str

    @property
    def text(self) -> str:
        return f"{self.module}.{self.name}"

    @property
    def lean_module(self) -> str:
        return self.module.replace("/", ".")

    @property
    def state_path(self) -> str:
        return f"{STATE_DIR}/{self.module}.lean.json"

    @property
    def source_path(self) -> str:
        return f"{self.module}.lean"

    @property
    def blueprint_path(self) -> str:
        return f"Blueprint/{self.module}.md"

    @property
    def parts(self) -> list[str]:
        """Components of the name part (``«…»`` escapes removed)."""
        return name_components(self.name)


def parse_gid(text: str) -> Gid:
    m = GID_RE.match(text.strip())
    if m:
        try:  # no whitespace or commas even inside «…»: they separate the GIDs of lean="…"
            if re.search(r"[\s,]", m.group("name")):
                raise LeanError("separator in name")
            name_components(m.group("name"))
        except LeanError:
            m = None
    if not m:
        raise LeanError(
            f"not a declaration GID: {text!r} (expected <module path>.<name>, "
            "e.g. D5/S1/Deficit/DeficitThreeValued.deficit_three_valued)"
        )
    return Gid(m.group("module"), m.group("name"))


def split_gids(value: str) -> list[str]:
    return [p for p in re.split(r"[\s,]+", value.strip()) if p]


# --------------------------------------------------------------------------- sources


class Source:
    label = "source"

    def read(self, commit: str, path: str) -> bytes | None:  # pragma: no cover - interface
        raise NotImplementedError


class GitSource(Source):
    def __init__(self, repo_dir: Path):
        self.dir = repo_dir
        self.label = f"git checkout {repo_dir}"
        self._has: dict[str, bool] = {}

    def has_commit(self, commit: str) -> bool:
        if commit not in self._has:
            r = subprocess.run(["git", "-C", str(self.dir), "cat-file", "-e", f"{commit}^{{commit}}"],
                               capture_output=True)
            self._has[commit] = r.returncode == 0
        return self._has[commit]

    def read(self, commit: str, path: str) -> bytes | None:
        if not self.has_commit(commit):
            return None
        r = subprocess.run(["git", "-C", str(self.dir), "show", f"{commit}:{path}"], capture_output=True)
        return r.stdout if r.returncode == 0 else b""  # b"" = definitely absent at this commit


class CacheSource(Source):
    def __init__(self, cache_dir: Path, *, readable: bool = True):
        self.dir = cache_dir
        self.readable = readable  # False in a pull request's GitHub Actions run (cache_trusted): written, not read
        self.label = f"cache {cache_dir}" + ("" if readable else " (not read in a pull-request run)")

    def _file(self, commit: str, path: str) -> Path:
        return self.dir / commit / path

    def read(self, commit: str, path: str) -> bytes | None:
        if not self.readable:
            return None
        f = self._file(commit, path)
        if f.exists():
            return f.read_bytes()
        missing = self._file(commit, path + ".missing")
        return b"" if missing.exists() else None

    def store(self, commit: str, path: str, data: bytes) -> None:
        f = self._file(commit, path if data else path + ".missing")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)


class HttpSource(Source):
    def __init__(self, repo: str, timeout: float = 30.0):
        self.repo = repo
        self.timeout = timeout
        self.label = f"https://raw.githubusercontent.com/{repo}"

    def read(self, commit: str, path: str) -> bytes | None:
        url = f"https://raw.githubusercontent.com/{self.repo}/{commit}/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "tbook"})
        token = os.environ.get("TRURETURING_TOKEN")
        if token:
            req.add_header("Authorization", f"token {token}")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return b""
                if attempt == 2:
                    raise LeanError(f"GET {url}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise LeanError(f"GET {url}: {exc}") from exc
        return None


class Ledger:
    """Reads frozen state (and Lean sources) of trureturing at a commit."""

    def __init__(self, repo: str, *, offline: bool = False, checkout: Path | None = None):
        self.repo = repo
        self.offline = offline
        self.cache = CacheSource(paths.CACHE / "trureturing", readable=cache_trusted())
        self.sources: list[Source] = []
        self.checkout: Path | None = None
        for cand in [checkout, os.environ.get("TRURETURING_DIR"), paths.ROOT.parent / "trureturing"]:
            if cand and (Path(cand) / ".git").exists():
                self.checkout = Path(cand)
                self.sources.append(GitSource(self.checkout))
                break
        self.sources.append(self.cache)
        if not offline:
            self.http = HttpSource(repo)
            self.sources.append(self.http)
        self._json: dict[tuple[str, str], dict | None] = {}

    def read(self, commit: str, path: str) -> bytes | None:
        """File bytes at the commit; b"" if absent there; None if no source could tell."""
        for src in self.sources:
            data = src.read(commit, path)
            if data is None:
                continue
            if isinstance(src, HttpSource):
                self.cache.store(commit, path, data)
            return data
        return None

    def state(self, commit: str, module: str) -> dict | None:
        key = (commit, module)
        if key not in self._json:
            data = self.read(commit, f"{STATE_DIR}/{module}.lean.json")
            if data is None:
                cache = "no cache entry" if self.cache.readable else "the cache is not read in a pull-request run"
                raise LeanError(
                    f"cannot read {STATE_DIR}/{module}.lean.json at {commit[:12]}: no trureturing checkout, "
                    f"{cache} and network disabled"
                )
            self._json[key] = json.loads(data) if data else None
        return self._json[key]

    # Branch ancestry ---------------------------------------------------------
    def branch_contains(self, commit: str, branch: str) -> "Ancestry":
        """Whether ``commit`` is reachable from ``branch`` of the repository.

        Asked, in order: a positive answer cached under ``.cache/trureturing/<commit>/`` (not in a
        pull request's run, see ``cache_trusted``); the local checkout (``git merge-base --is-ancestor``
        against the branch's remote-tracking ref, else the local branch; ``git_branch_contains``);
        GitHub's API unless offline (``github_branch_contains``). The last definite answer wins, so
        GitHub overrides a stale checkout, and a checkout's "no" stands when GitHub cannot answer.
        GitHub's "the repository has no branch of that name" is a definite no (``Ancestry.no_branch``);
        a checkout without the branch cannot tell. Positive answers are cached; ``None`` means nobody
        could tell, or that ``branch`` is not a branch name (``branch_problem``).
        """
        problem = branch_problem(branch, commit)
        if problem:
            return Ancestry(None, f"branch {branch!r} {problem}")
        known = self._ancestry_cache(commit).get(f"{self.repo}@{branch}") if self.cache.readable else None
        if isinstance(known, str):
            return Ancestry(True, f"{known} (cached)")
        found: list[Ancestry] = []
        if self.checkout:
            found.append(git_branch_contains(self.checkout, self.repo, branch, commit))
        if not any(a.on_branch for a in found) and not self.offline:
            found.append(github_branch_contains(self.repo, branch, commit))
        result = next((a for a in reversed(found) if a.on_branch is not None), None)
        if result is None:
            reasons = [a.detail for a in found]
            if not self.checkout:
                reasons.insert(0, "no local trureturing checkout ($TRURETURING_DIR or ../trureturing)")
            if self.offline:
                reasons.append("network disabled")
            if not self.cache.readable:
                reasons.append("the cache is not read in a pull-request run")
            result = Ancestry(None, "; ".join(reasons))
        if result.on_branch:
            self.record_on_branch(commit, branch, result.detail)
        return result

    def record_on_branch(self, commit: str, branch: str, detail: str) -> None:
        """Cache a positive ancestry answer (best effort)."""
        data = self._ancestry_cache(commit)
        data[f"{self.repo}@{branch}"] = detail
        f = self.cache.dir / commit / ANCESTRY_FILE
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _ancestry_cache(self, commit: str) -> dict:
        try:
            data = json.loads((self.cache.dir / commit / ANCESTRY_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def expand_sha(self, prefix: str) -> str | None:
        """The full SHA of the commit abbreviated as ``prefix``: local checkout, then GitHub; None if unknown
        or ambiguous."""
        prefix = prefix.lower()
        if not ABBREV_SHA_RE.match(prefix):
            return None
        if self.checkout:
            r = _git(self.checkout, "rev-parse", "--verify", "-q", f"{prefix}^{{commit}}")
            sha = r.stdout.strip()
            if r.returncode == 0 and SHA_RE.match(sha) and sha.startswith(prefix):
                return sha
        if not self.offline:
            code, data, _ = github_api(f"repos/{self.repo}/commits/{prefix}")
            sha = data.get("sha", "") if code == 200 and isinstance(data, dict) else ""
            if isinstance(sha, str) and SHA_RE.match(sha) and sha.startswith(prefix):
                return sha
        return None


# --------------------------------------------------------------------------- branch ancestry

# Positive answers, in .cache/trureturing/<commit>/. Versioned: the answers earlier versions cached (in
# .tbook-on-branch.json) are not read, because those versions took some names that are no branch, such as
# git describe output (dev-12-g<sha>), for one.
ANCESTRY_FILE = ".tbook-on-branch-v2.json"


@dataclass(frozen=True)
class Ancestry:
    """Is a commit reachable from a branch? ``on_branch`` is True, False, or None (cannot tell).

    ``no_branch``: the repository has no branch of that name (``on_branch`` is then False)."""

    on_branch: bool | None
    detail: str
    no_branch: bool = False


def ancestry_required(offline: bool) -> bool:
    """Whether an undetermined ancestry is an error: in GitHub Actions unless offline; a warning elsewhere."""
    return not offline and os.environ.get("GITHUB_ACTIONS") == "true"


# GitHub Actions events whose runs execute a pull request's code in the pull request's cache scope.
PULL_REQUEST_EVENTS = ("pull_request", "pull_request_target", "pull_request_review", "pull_request_review_comment")


def cache_trusted() -> bool:
    """Whether ``.cache/trureturing`` may be read (it is written either way).

    Not in a pull request's GitHub Actions run (``$GITHUB_EVENT_NAME``): the cache such a run restores
    can have been saved by an earlier run of the same pull request, which ran the pull request's own
    code, so frozen state and ancestry come from a checkout or from GitHub instead. The workflows
    restore the cache only on the default branch and on tags; on a developer's machine it is their own.
    """
    return os.environ.get("GITHUB_EVENT_NAME", "") not in PULL_REQUEST_EVENTS


# Characters ``git check-ref-format --branch`` refuses, with what they mean to git and to GitHub's API.
BRANCH_FORBIDDEN = {
    "^": "revision syntax: GitHub reads <sha>^0 as that commit",
    "~": "revision syntax: GitHub reads <sha>~0 as that commit",
    ":": "owner:branch names a branch of another repository",
    "?": "a wildcard", "*": "a wildcard", "[": "a wildcard", "\\": "an escape",
}


def branch_name_problem(name: str) -> tuple[str, bool]:
    """What keeps ``name`` from being a branch name ('' if nothing), and whether git refuses it too.

    The rules of ``git check-ref-format --branch``: no ASCII control character or space, none of
    ``^ ~ : ? * [ \\``, no ``..`` or ``@{``, not ``HEAD``, no leading ``-``, no empty component (a
    leading or trailing ``/``, ``//``), no component that starts with ``.`` or ends with ``.lock``, no
    trailing ``.``. Refused beyond git: a bare ``@`` (git's shorthand for HEAD), and Unicode whitespace
    or invisible characters, with which two different names print alike.
    """
    for ch in name:
        if ord(ch) < 0x20 or ord(ch) == 0x7F or ch == " ":
            return "it contains whitespace or a control character", True
        if ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf", "Zs", "Zl", "Zp"):
            return f"it contains whitespace or an invisible character, U+{ord(ch):04X}", False
    for ch, meaning in BRANCH_FORBIDDEN.items():
        if ch in name:
            return f"it contains {ch!r}, {meaning}", True
    if ".." in name:
        return "it contains '..', a revision range", True
    if "@{" in name:
        return "it contains '@{', reflog and upstream syntax: dev@{1} is an earlier commit of dev", True
    if name == "HEAD":
        return "HEAD names a repository's current commit", True
    if name == "@":
        return "'@' is git's shorthand for HEAD", False
    if name.startswith("-"):
        return "it starts with '-'", True
    parts = name.split("/")
    if "" in parts:
        return "it has an empty component: a leading or trailing '/', or '//'", True
    if any(part.startswith(".") for part in parts):
        return "a component starts with '.'", True
    if any(part.endswith(".lock") for part in parts):
        return "a component ends with '.lock'", True
    if name.endswith("."):
        return "it ends with '.'", True
    return "", False


def branch_problem(branch: str, commit: str = "") -> str:
    """Why ``branch`` (site.toml ``[trureturing].branch``) cannot stand for trureturing's integration
    branch, as a phrase that follows the name ('' if it can).

    Git and GitHub's compare API read more than branch names: with the pinned commit, an abbreviation
    of it, or ``<sha>^0`` in place of the branch, compare answers ``identical``; ``owner:branch`` names
    another repository's branch. Refused here, before anybody is asked: every name
    ``git check-ref-format --branch`` refuses, and a few more (``branch_name_problem``); a full ref
    (``refs/…``); a full SHA, and a hex name that abbreviates ``commit``. A name that passes must
    still be an existing branch: ``_branch_ref`` and ``github_branch_contains`` look it up as one.
    """
    if not branch.strip():
        return "is empty"
    why, by_git = branch_name_problem(branch)
    if why:
        return f"is not a branch name ({why}{'; git check-ref-format --branch refuses it' if by_git else ''})"
    if branch.startswith("refs/"):
        return "is a full ref; write the branch name alone (e.g. dev), without refs/heads/"
    if HEXISH_RE.match(branch) and (len(branch) == 40 or commit.lower().startswith(branch.lower())):
        return "is a commit SHA, not a branch"
    return ""


def _git(repo_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True)


def _same_repo(url: str, repo: str) -> bool:
    u = url.strip().lower().rstrip("/")
    u = u[:-4] if u.endswith(".git") else u
    return re.search(r"github\.com[:/]" + re.escape(repo.lower()) + "$", u) is not None


def _branch_ref(repo_dir: Path, repo: str, branch: str) -> str | None:
    """The ref of ``branch`` in a checkout: the remote-tracking ref of a remote that points at ``repo``,
    else ``origin/<branch>``, else the local branch.

    Only a ref of exactly that name counts (``git show-ref --verify``). ``git rev-parse`` would also
    read the name as a revision: to it ``refs/remotes/origin/dev-12-g<sha>`` is git describe output,
    i.e. the commit ``<sha>`` abbreviates, which such a "branch" would then contain."""
    remotes = []
    for line in _git(repo_dir, "config", "--get-regexp", r"^remote\..*\.url$").stdout.splitlines():
        key, _, url = line.partition(" ")
        if _same_repo(url, repo):
            remotes.append(key[len("remote."):-len(".url")])
    candidates = [f"refs/remotes/{r}/{branch}" for r in remotes]
    candidates += [f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"]
    for ref in dict.fromkeys(candidates):
        if _git(repo_dir, "show-ref", "--verify", "-q", ref).returncode == 0:
            return ref
    return None


def git_branch_contains(repo_dir: Path, repo: str, branch: str, commit: str) -> Ancestry:
    """Ancestry from a local checkout (None when it lacks the commit or the branch: a checkout cannot tell
    whether the repository has a branch that it has not fetched)."""
    if _git(repo_dir, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        return Ancestry(None, f"the checkout {repo_dir} does not have {commit[:12]}")
    ref = _branch_ref(repo_dir, repo, branch)
    if ref is None:
        return Ancestry(None, f"the checkout {repo_dir} has no branch {branch!r}")
    short = ref.removeprefix("refs/remotes/").removeprefix("refs/heads/")
    r = _git(repo_dir, "merge-base", "--is-ancestor", commit, ref)
    if r.returncode == 0:
        return Ancestry(True, f"ancestor of {short} in {repo_dir}")
    if r.returncode == 1:
        return Ancestry(False, f"not an ancestor of {short} in {repo_dir} (if {branch} has moved: "
                               f"git -C {repo_dir} fetch)")
    return Ancestry(None, f"git merge-base failed in {repo_dir}: {r.stderr.strip()[:200]}")


def _api_token() -> str:
    for key in ("TRURETURING_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(key):
            return os.environ[key]
    return ""


def github_api(path: str, timeout: float = 30.0) -> tuple[int, object, str]:
    """GET ``https://api.github.com/<path>``: (HTTP status, or 0 if unreachable; JSON or None; error text).

    Authenticates with ``$TRURETURING_TOKEN``, ``$GITHUB_TOKEN`` or ``$GH_TOKEN`` when set."""
    url = f"https://api.github.com/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "tbook", "Accept": "application/vnd.github+json",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    token = _api_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    code, err = 0, "no answer"
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null"), ""
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                message = json.loads(exc.read() or b"{}").get("message", "")
            except (ValueError, AttributeError, OSError):
                message = ""
            err = f"HTTP {exc.code}" + (f" {message}" if message else "")
            if exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            code, err = 0, str(exc)
    return code, None, err


def github_branch_contains(repo: str, branch: str, commit: str) -> Ancestry:
    """Ancestry from GitHub's API: the branch's head commit, then the compare API.

    The branch is looked up by name (``branches/<branch>``), and the commit is compared with the head
    commit of that answer (``compare/<head>...<commit>``), never with the name: in place of the base,
    the compare API also reads a commit SHA, an abbreviation of one, ``<sha>^0`` or git describe output
    such as ``dev-12-g<sha>``, and answers ``identical`` when that is the commit itself. The branches
    endpoint answers 404 for any name that is not a branch of the repository; when the repository
    itself is readable, that is a definite "no such branch" (``Ancestry.no_branch``), and so is an
    answer for another branch (GitHub redirects a renamed branch to its new name). ``compare``:
    ``behind`` or ``identical`` means the branch contains the commit (and the answer is small: no
    commits, no files); ``ahead`` or ``diverged`` means the commit has history the branch does not.
    """
    what = f"GitHub branch {branch!r}"
    problem = branch_problem(branch, commit)
    if problem:
        return Ancestry(None, f"{what}: {branch!r} {problem}")
    missing = f"GitHub: {repo} has no branch {branch!r}"
    fix = "; [trureturing] branch in site.toml must name an existing branch (default dev)"
    code, data, err = github_api(f"repos/{repo}/branches/{urllib.parse.quote(branch, safe='/')}")
    if code == 404:
        if github_api(f"repos/{repo}")[0] == 200:
            return Ancestry(False, missing + fix, no_branch=True)
        return Ancestry(None, f"{what}: {err} (unknown branch or repository, or a private repository without "
                              "$TRURETURING_TOKEN)")
    head = data.get("commit") if code == 200 and isinstance(data, dict) else None
    head = head.get("sha") if isinstance(head, dict) else None
    if not (isinstance(head, str) and SHA_RE.match(head) and isinstance(data.get("name"), str)):
        return Ancestry(None, f"{what}: {err or 'unexpected answer'}")
    if data["name"] != branch:
        return Ancestry(False, f"{missing} (GitHub answered with branch {data['name']!r}: renamed?){fix}",
                        no_branch=True)
    what = f"GitHub compare {head[:12]} (head of {branch})...{commit[:12]}"
    code, data, err = github_api(f"repos/{repo}/compare/{head}...{commit}")
    if code == 200 and isinstance(data, dict):
        status = data.get("status")
        if status in ("behind", "identical"):
            return Ancestry(True, f"{what}: {status}")
        if status in ("ahead", "diverged"):
            return Ancestry(False, f"{what}: {status}, {data.get('ahead_by', '?')} commit(s) not on {branch}")
        return Ancestry(None, f"{what}: unexpected status {status!r}")
    if code == 404:
        err += " (unknown commit, or a private repository without $TRURETURING_TOKEN)"
    return Ancestry(None, f"{what}: {err}")


# --------------------------------------------------------------------------- resolution


@dataclass
class Resolution:
    gid: str
    module: str
    name: str  # fully qualified Lean name
    kind: str  # theorem | def | inductive | constructor | recursor | opaque
    statement_id: str  # module statement digest from the state file
    line: int = 0  # line of the declaration in the .lean source (0 = unknown)
    signature: str = ""  # declaration header up to ':=' (best effort, informational)
    # The commit that supplied this module's frozen state.  Sharded locks may
    # intentionally contain several commits while dev advances.
    commit: str = ""

    def to_lock(self) -> dict:
        d = asdict(self)
        d.pop("gid")
        return d


def resolve(ledger: Ledger, commit: str, gid_text: str) -> Resolution:
    gid = parse_gid(gid_text)
    state = ledger.state(commit, gid.module)
    if state is None:
        raise LeanError(
            f"{gid.text}: module {gid.module} is not frozen at {commit[:12]} "
            f"(no {gid.state_path}); only kernel-verified, frozen declarations may be cited"
        )
    want = gid.parts
    matches: list[tuple[str, str]] = []
    for decl in state.get("declarations", []):
        comps = parse_name_key(decl["declaration_name_key"])
        if is_private(comps):
            continue
        if len(comps) >= len(want) and [str(c) for c in comps[-len(want):]] == want:
            matches.append((name_to_str(comps), decl.get("kind", "")))
    if not matches:
        raise LeanError(f"{gid.text}: no frozen declaration named {gid.name!r} in {gid.state_path} at {commit[:12]}")
    if len(matches) > 1:
        names = ", ".join(m[0] for m in matches)
        raise LeanError(f"{gid.text}: ambiguous, matches {names}; write a longer name suffix")
    full, kind = matches[0]
    return Resolution(gid=gid.text, module=gid.module, name=full, kind=kind,
                      statement_id=str(state.get("statement_id", "")), commit=commit)


DECL_KEYWORDS = r"(?:theorem|lemma|def|abbrev|instance|structure|inductive|class|opaque|axiom)"
_MODIFIERS = r"(?:(?:private|protected|public|noncomputable|nonrec|partial|unsafe|meta)\s+)*"
_DECL_RE = re.compile(r"^\s*(?P<head>(?:@\[[^\]]*\]\s*)*(?P<mods>" + _MODIFIERS + r")" + DECL_KEYWORDS
                      + r"\s+(?P<name>(?:«[^»]*»|[^\s(){}\[\]⦃⦄:«])+))")
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?P<name>\S+)")
_SECTION_RE = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:public|private|noncomputable|meta)\s+)*section\b"
                         r"(?:[ \t]+(?P<name>\S+))?")
_MUTUAL_RE = re.compile(r"^\s*mutual\b")
_END_RE = re.compile(r"^\s*end\b(?:[ \t]+(?P<name>\S+))?")
_ATTR_LINE_RE = re.compile(r"^\s*@\[[^\]]*\]\s*$")


def _blank_comments(text: str) -> str:
    """``text`` with Lean comments and string literals replaced by spaces (newlines and offsets kept)."""
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        if text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif text.startswith("/-", i):  # block and doc comments nest
            depth, j = 0, i
            while j < n:
                if text.startswith("/-", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("-/", j):
                    depth, j = depth - 1, j + 2
                    if depth == 0:
                        break
                else:
                    j += 1
        elif text[i] == '"' and not (text[i - 1:i] == "'" and text[i + 1:i + 2] == "'"):
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(n, j + 1)
        else:
            i += 1
            continue
        for k in range(i, j):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def _declarations(text: str) -> tuple[list[tuple[int, int, list[str], list[str]]], bool]:
    """Non-private declaration headers of a Lean source as (offset, line, full name, written name), and
    whether its ``namespace`` / ``section`` / ``mutual`` / ``end`` scopes could not be followed."""
    scopes: list[tuple[str, str | None]] = []  # ("ns", component) | ("section", name) | ("mutual", None)
    decls: list[tuple[int, int, list[str], list[str]]] = []
    confused = False
    offset = 0
    attr: tuple[int, int] | None = None  # an attribute alone on the line(s) before a declaration
    for lineno, line in enumerate(_blank_comments(text).split("\n"), 1):
        start, offset = offset, offset + len(line) + 1
        if not line.strip():
            continue
        if _ATTR_LINE_RE.match(line):
            attr = (start + len(line) - len(line.lstrip()), lineno)
            continue
        pending, attr = attr, None
        m = _NAMESPACE_RE.match(line)
        if m:
            try:
                scopes += [("ns", c) for c in name_components(m.group("name"))]
            except LeanError:
                confused = True
            continue
        m = _SECTION_RE.match(line)
        if m:
            scopes.append(("section", m.group("name")))
            continue
        if _MUTUAL_RE.match(line):
            scopes.append(("mutual", None))
            continue
        m = _END_RE.match(line)
        if m:
            name = m.group("name")
            if not scopes:
                confused = True
            elif scopes[-1][0] != "ns":  # a section (closed by `end` or `end <its name>`) or a mutual block
                if name and scopes[-1][1] != name:
                    confused = True
                scopes.pop()
            else:
                try:
                    names = name_components(name) if name else []
                except LeanError:
                    names = []
                k = max(len(names), 1)
                if not names or scopes[-k:] != [("ns", c) for c in names]:
                    confused = True
                del scopes[-k:]
            continue
        m = _DECL_RE.match(line)
        if not m or "private" in m.group("mods").split():
            continue
        try:
            written = name_components(m.group("name").rstrip("."))
        except LeanError:
            continue
        if written[0] == "_root_":
            written = full = written[1:]
        else:
            full = [c for kind, c in scopes if kind == "ns"] + written
        if written:
            at = pending if pending and not m.group("head").startswith("@") else (start + m.start("head"), lineno)
            decls.append((at[0], at[1], full, written))
    return decls, confused


def locate(ledger: Ledger, commit: str, res: Resolution) -> None:
    """Fill ``line`` and ``signature`` from the Lean source (best effort).

    The source's ``namespace`` / ``section`` / ``end`` scopes are followed so that a declaration is
    found by its full name: in ``namespace Lambda``, ``theorem LMonoTys.foo`` is ``Lambda.LMonoTys.foo``
    and ``theorem LMonoTy.foo`` is not. Only when the scopes cannot be followed does the longest written
    name that is a suffix of the full name count. Several candidates, or none, leave ``line`` at 0:
    a wrong line is worse than none (badges and ledger links point at it).
    """
    try:
        data = ledger.read(commit, f"{res.module}.lean")
    except LeanError:
        return
    if not data:
        return
    text = data.decode("utf-8", "replace")
    try:
        target = name_components(res.name)
    except LeanError:
        return
    decls, confused = _declarations(text)
    picks = [d for d in decls if d[2] == target]
    if not picks and confused:
        fits = [d for d in decls if len(d[3]) <= len(target) and target[-len(d[3]):] == d[3]]
        longest = max((len(d[3]) for d in fits), default=0)
        picks = [d for d in fits if len(d[3]) == longest]
    if len(picks) != 1:
        return
    start, res.line = picks[0][0], picks[0][1]
    end = text.find(":=", start)
    if end < 0 or end - start > 2000:
        end = min(len(text), start + 400)
    sig = re.sub(r"\s+", " ", text[start:end]).strip()
    res.signature = sig[:600]


# --------------------------------------------------------------------------- lock file


def _atomic_write(path: Path, text: str) -> None:
    """Write a small evidence file without exposing a partial JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


@contextlib.contextmanager
def _lock_writer():
    """Serialize local pin writers while preserving independent module shards."""
    lock_path = paths.CACHE / "trureturing-lock-write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass
class Lock:
    repo: str
    branch: str
    commit: str
    pinned_at: str = ""
    declarations: dict[str, dict] = field(default_factory=dict)
    schema: str = LOCK_SCHEMA

    @classmethod
    def load(cls, path: Path | None = None) -> "Lock | None":
        # An explicit path is the v1 compatibility API used by migrations and
        # callers that need to inspect an historical lock.  The default loader
        # prefers the sharded lock and falls back to the old aggregate file.
        if path is not None:
            return cls._load_legacy(path)
        # The pointer is part of the canonical lock contract.  Requiring it
        # makes deleting the pointer an unambiguous "no lock" operation while
        # still keeping all declaration evidence in the directory.
        if paths.LOCK_FILE.exists():
            try:
                pointer = json.loads(paths.LOCK_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LeanError(f"{paths.rel(paths.LOCK_FILE)}: unreadable lock pointer: {exc}") from exc
            if pointer.get("schema") == LOCK_POINTER_SCHEMA:
                if pointer.get("path") != paths.lock_dir().name:
                    raise LeanError(f"{paths.rel(paths.LOCK_FILE)}: unsupported lock pointer schema")
                # A pointer without its directory is an absent lock.  This is
                # useful for template/no-book fixtures and produces the normal
                # missing-lock diagnostic only when a citation needs one.
                return cls._load_sharded(paths.lock_index()) if paths.lock_index().exists() else None
            if paths.lock_index().exists():
                raise LeanError(f"{paths.rel(paths.LOCK_FILE)}: unsupported lock pointer schema")
        return cls._load_legacy(paths.LOCK_FILE)

    @classmethod
    def _load_legacy(cls, path: Path) -> "Lock | None":
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != LOCK_SCHEMA:
            raise LeanError(f"{paths.rel(path)}: unsupported schema {data.get('schema')!r}")
        if not SHA_RE.match(data.get("commit", "")):
            raise LeanError(f"{paths.rel(path)}: commit must be a full 40-hex SHA")
        obj = cls(repo=data["repo"], branch=data.get("branch", ""), commit=data["commit"],
                  pinned_at=data.get("pinned_at", ""), declarations=data.get("declarations", {}))
        obj._base_declarations = dict(obj.declarations)
        return obj

    @classmethod
    def _load_sharded(cls, index: Path) -> "Lock | None":
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LeanError(f"{paths.rel(index)}: unreadable sharded lock: {exc}") from exc
        if data.get("schema") not in (SHARDED_LOCK_SCHEMA, SHARDED_LOCK_SCHEMA_V2):
            raise LeanError(f"{paths.rel(index)}: unsupported schema {data.get('schema')!r}")
        if not SHA_RE.match(data.get("commit", "")):
            raise LeanError(f"{paths.rel(index)}: commit must be a full 40-hex SHA")
        root = index.parent
        declarations: dict[str, dict] = {}
        for module_file in sorted(root.rglob("*.lean.json")):
            try:
                fragment = json.loads(module_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LeanError(f"{paths.rel(module_file)}: unreadable lock shard: {exc}") from exc
            if fragment.get("schema") != MODULE_LOCK_SCHEMA:
                raise LeanError(f"{paths.rel(module_file)}: unsupported schema {fragment.get('schema')!r}")
            module = str(fragment.get("module", ""))
            if not module or module_file.is_symlink() or module_file.relative_to(root).as_posix() != f"{module}.lean.json":
                raise LeanError(f"{paths.rel(module_file)}: module path does not match its shard filename")
            shard_commit = fragment.get("commit", data["commit"])
            if not SHA_RE.match(str(shard_commit)):
                raise LeanError(f"{paths.rel(module_file)}: commit must be a full 40-hex SHA")
            entries = fragment.get("declarations", {})
            if not isinstance(entries, dict):
                raise LeanError(f"{paths.rel(module_file)}: declarations must be an object")
            for gid, resolution in entries.items():
                if not isinstance(resolution, dict) or resolution.get("module") != module:
                    raise LeanError(f"{paths.rel(module_file)}: invalid declaration {gid!r}")
                if gid in declarations:
                    raise LeanError(f"{paths.rel(module_file)}: duplicate declaration {gid!r}")
                item = dict(resolution)
                item.setdefault("commit", shard_commit)
                if not SHA_RE.match(str(item["commit"])):
                    raise LeanError(f"{paths.rel(module_file)}: declaration {gid!r} has invalid commit")
                declarations[gid] = item
        obj = cls(repo=data["repo"], branch=data.get("branch", ""), commit=data["commit"],
                  pinned_at=data.get("pinned_at", ""), declarations=declarations,
                  schema=SHARDED_LOCK_SCHEMA)
        obj._base_declarations = dict(declarations)
        return obj

    def save(self, path: Path | None = None) -> None:
        # Explicit paths retain the old single-file writer for compatibility with
        # importers and old lock snapshots.  The normal writer is sharded by module.
        if path is not None:
            self._save_legacy(path)
            return
        self._save_sharded()

    def _save_legacy(self, path: Path) -> None:
        data = {
            "schema": LOCK_SCHEMA,
            "repo": self.repo,
            "branch": self.branch,
            "commit": self.commit,
            "pinned_at": self.pinned_at,
            "declarations": {k: self.declarations[k] for k in sorted(self.declarations)},
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _save_sharded(self) -> None:
        root = paths.lock_dir()
        root.mkdir(parents=True, exist_ok=True)
        by_module: dict[str, dict[str, dict]] = {}
        for gid, resolution in self.declarations.items():
            module = str(resolution.get("module", ""))
            if not module:
                raise LeanError(f"{gid}: lock declaration has no module")
            by_module.setdefault(module, {})[gid] = resolution

        # A short local lock makes the read/merge/write sequence safe when two
        # pin jobs update different modules in the same checkout.  The lock is
        # ignored and lives outside the tracked evidence directory.
        with _lock_writer():
            existing = Lock._load_sharded(paths.lock_index()) if paths.lock_index().exists() else None
            existing_by_module: dict[str, dict[str, dict]] = {}
            if existing:
                for gid, resolution in existing.declarations.items():
                    existing_by_module.setdefault(str(resolution.get("module", "")), {})[gid] = resolution

            # If the lock changed since this writer read it, merge instead of
            # pruning. Otherwise the caller's cited set is authoritative and
            # stale modules can be removed as before. This optimistic check is
            # what lets concurrent pins update different modules safely.
            base = getattr(self, "_base_declarations", None)
            concurrent_change = existing is not None and base is not None and existing.declarations != base
            for module, entries in sorted(by_module.items()):
                if concurrent_change:
                    merged = dict(existing_by_module.get(module, {}))
                    for gid, entry in entries.items():
                        old_entry = (base or {}).get(gid)
                        # A loader adds the shard commit as a compatibility
                        # field; that alone does not mean this stale writer
                        # changed the declaration.
                        comparable = lambda value: {k: v for k, v in value.items() if k != "commit"}
                        if old_entry is None or comparable(entry) != comparable(old_entry):
                            merged[gid] = entry
                else:
                    merged = dict(entries)
                target = root / f"{module}.lean.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "schema": MODULE_LOCK_SCHEMA,
                    "module": module,
                    "declarations": {k: merged[k] for k in sorted(merged)},
                }
                encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
                _atomic_write(target, encoded)

            if not concurrent_change:
                expected = {f"{module}.lean.json" for module in by_module}
                for target in sorted(root.rglob("*.lean.json")):
                    if target.relative_to(root).as_posix() not in expected:
                        target.unlink()
                for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
                    if directory != root and not any(directory.iterdir()):
                        directory.rmdir()

            # The index is intentionally stable.  Its commit is a baseline for
            # old consumers and is written only when the index is first created
            # (or when repo/branch changes); declaration source commits live in
            # their module entries and therefore do not contend on this file.
            index_path = paths.lock_index()
            current_index = None
            if index_path.exists():
                try:
                    current_index = json.loads(index_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    current_index = None
            index = {
                "schema": SHARDED_LOCK_SCHEMA,
                "repo": self.repo,
                "branch": self.branch,
                "commit": (current_index or {}).get("commit") if current_index else self.commit,
                "pinned_at": (current_index or {}).get("pinned_at") if current_index else self.pinned_at,
            }
            if not SHA_RE.match(str(index["commit"])):
                index["commit"] = self.commit
            if not index.get("pinned_at"):
                index["pinned_at"] = self.pinned_at
            _atomic_write(index_path, json.dumps(index, ensure_ascii=False, indent=2) + "\n")

        # Keep a stable, tiny compatibility pointer at the historical path.  It
        # is deliberately independent of declaration content, so it never causes
        # the old large-file merge conflict.
        pointer = {"schema": LOCK_POINTER_SCHEMA, "path": paths.lock_dir().name}
        _atomic_write(paths.LOCK_FILE, json.dumps(pointer, ensure_ascii=False, indent=2) + "\n")

    def get(self, gid: str) -> Resolution | None:
        d = self.declarations.get(gid)
        if not d:
            return None
        return Resolution(gid=gid, module=d["module"], name=d["name"], kind=d["kind"],
                          statement_id=d.get("statement_id", ""), line=int(d.get("line", 0) or 0),
                          signature=d.get("signature", ""), commit=d.get("commit", self.commit))

    def commit_for(self, gid: str) -> str:
        """Commit whose frozen state supplied ``gid`` (with v1 fallback)."""
        return str((self.declarations.get(gid) or {}).get("commit") or self.commit)

    # Links ------------------------------------------------------------------
    def blob(self, path: str, line: int = 0) -> str:
        url = f"https://github.com/{self.repo}/blob/{self.commit}/{path}"
        return url + (f"#L{line}" if line else "")

    def source_url(self, gid: str) -> str:
        res = self.get(gid)
        g = parse_gid(gid)
        return self._blob_at(self.commit_for(gid), g.source_path, res.line if res else 0)

    def state_url(self, gid: str) -> str:
        return self._blob_at(self.commit_for(gid), parse_gid(gid).state_path)

    def blueprint_url(self, gid: str) -> str:
        return self._blob_at(self.commit_for(gid), parse_gid(gid).blueprint_path)

    def _blob_at(self, commit: str, path: str, line: int = 0) -> str:
        url = f"https://github.com/{self.repo}/blob/{commit}/{path}"
        return url + (f"#L{line}" if line else "")

    @property
    def tree_url(self) -> str:
        return f"https://github.com/{self.repo}/tree/{self.commit}"


def ls_remote(repo: str, ref: str) -> str:
    """Resolve a branch or tag of the trureturing repository to a commit SHA.

    Only ``refs/heads/*`` and ``refs/tags/*`` count, matched by exact name: ``git ls-remote`` alone
    matches patterns by suffix, so ``head`` would find a pull-request head ``refs/pull/N/head``.
    Annotated tags are peeled to their commit. A full 40-hex SHA is returned unchanged.
    """
    if SHA_RE.match(ref):
        return ref
    url = f"https://github.com/{repo}.git"
    if ref.startswith("refs/"):
        if not ref.startswith(("refs/heads/", "refs/tags/")):
            raise LeanError(f"cannot pin {ref!r}: only branches (refs/heads/…) and tags (refs/tags/…) of {repo}")
        candidates = [ref]
    else:
        candidates = [f"refs/heads/{ref}", f"refs/tags/{ref}"]
    patterns = candidates + [c + "^{}" for c in candidates if c.startswith("refs/tags/")]
    r = subprocess.run(["git", "ls-remote", url, *patterns], capture_output=True, text=True)
    if r.returncode != 0:
        raise LeanError(f"git ls-remote {url} failed: {r.stderr.strip()[:300]}")
    found: dict[str, str] = {}
    for line in r.stdout.splitlines():
        sha, _, name = line.partition("\t")
        found[name.strip()] = sha.strip()
    for c in candidates:
        sha = found.get(c + "^{}") or found.get(c, "")
        if SHA_RE.match(sha):
            return sha
    hint = "; to pin a commit, pass its full 40-character SHA" if ABBREV_SHA_RE.match(ref) else ""
    raise LeanError(f"cannot resolve {ref!r}: no branch or tag of that name in {url}{hint}")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
