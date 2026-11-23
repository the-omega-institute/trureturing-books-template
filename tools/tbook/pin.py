"""``./tbook pin``: pin a trureturing commit and resolve every cited declaration.

``./tbook pin``            follow the branch in site.toml (default ``dev``) to its head
``./tbook pin <sha|ref>``  pin an explicit commit (full or abbreviated SHA), branch or tag
``./tbook pin --refresh``  keep the current commit; add newly cited and prune unused GIDs

Whatever the ref, the commit must be on the site.toml branch: trureturing's CI enforces the
freeze rule (frozen ⇒ kernel-verified, no ``sorry``) only there, while GitHub also serves
pull-request heads and other unmerged commits. A commit that is not on the branch is
refused; one whose ancestry cannot be determined is refused in GitHub Actions and pinned
with a warning elsewhere (``./tbook check`` verifies it again). The branch must be a valid
branch name, not a commit SHA, a full ref or a revision expression such as ``<sha>^0``
(``lean.branch_problem``), and an existing branch: when GitHub says the repository has no
branch of that name (``dev-12-g<sha>``, ``pull/<n>/head``…), the commit is refused; the lock
records the branch, and ``./tbook check`` requires the lock's branch to be site.toml's.

The lock records, per GID, the fully qualified Lean name, its kind, its module's frozen
``statement_id`` and (best effort) the source line and header. When the commit moves,
the report lists modules whose statement digest changed: re-read those theorems'
statements in trureturing and adjust the book text before merging.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config, lean
from .model import load_book_models, media_cited_gids


@dataclass
class PinReport:
    commit: str
    previous: str
    branch: str = ""  # site.toml's trureturing branch, which the lock records
    previous_branch: str = ""  # the branch the previous lock recorded
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[tuple[str, str]] = field(default_factory=list)  # (gid, what)
    moved: list[tuple[str, int, int]] = field(default_factory=list)  # (gid, old line, new line)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    refused: str = ""  # why the commit cannot be pinned (not on the branch …); nothing was resolved
    written: bool = False

    def markdown(self) -> str:
        lines = [f"trureturing pin: `{self.previous[:12] or '—'}` → `{self.commit[:12]}`", ""]
        if self.previous_branch and self.branch and self.previous_branch != self.branch:
            lines += [f"Branch: `{self.previous_branch}` → `{self.branch}` (site.toml)", ""]
        if self.refused:
            return "\n".join(lines + ["**Refused (lock not written):**", "", f"- {self.refused}"])
        if self.warnings:
            lines += ["**Warnings:**", ""] + [f"- {w}" for w in self.warnings] + [""]
        if self.errors:
            lines += ["**Unresolved (lock not written):**", ""] + [f"- {e}" for e in self.errors] + [""]
        for title, items in (("Added", self.added), ("Removed", self.removed)):
            if items:
                lines += [f"**{title}:**", ""] + [f"- `{g}`" for g in items] + [""]
        if self.changed:
            lines += ["**Changed — review the book text for these:**", ""]
            lines += [f"- `{g}`: {what}" for g, what in self.changed] + [""]
        if self.moved:
            lines += ["**Source line changed:**", ""]
            lines += [f"- `{g}`: L{a or '?'} → L{b or '?'}" for g, a, b in self.moved] + [""]
        if not (self.errors or self.added or self.removed or self.changed):
            lines.append("No declaration changes.")
        return "\n".join(lines)


def cited_gids(books: list[config.Book], *, mode: str | None = None) -> list[str]:
    mode = config.site_mode() if mode is None else mode
    gids: set[str] = set()
    for book in books:
        found = [gid for model in load_book_models(book).values() for _, _, gid, _ in model.cited_gids()]
        found += [gid for _, _, gid in media_cited_gids(book)]
        for gid in found:
            try:
                lean.parse_gid(gid, mode=mode)
            except lean.LeanError:
                continue
            gids.add(gid)
    return sorted(gids)


def _check_branch(branch: str, commit: str = "") -> None:
    """site.toml's trureturing branch must name a branch (not a commit SHA, a full ref or a revision)."""
    problem = lean.branch_problem(branch, commit)
    if problem:
        raise lean.LeanError(f"site.toml [trureturing] branch {branch!r} {problem}: trureturing enforces its freeze "
                             "rule on a branch (default 'dev'), and only a branch can show that a commit was merged")


def _check_branch_lock(spec: lean.BranchLock, site: config.Site) -> None:
    if (spec.repo, spec.branch) != (site.trureturing_repo, site.trureturing_branch):
        raise lean.LeanError("branch lock repository and branch must match site.toml [trureturing]; run ./tbook pin --follow")
    if (spec.mode, spec.source_root) != (site.trureturing_mode, site.trureturing_source_root):
        raise lean.LeanError("branch lock mode and source_root must match site.toml [trureturing]; run ./tbook pin --follow")


def branch_head(spec: lean.BranchLock) -> str:
    site = config.load_site()
    _check_branch_lock(spec, site)
    _check_branch(spec.branch)
    return lean.ls_remote(spec.repo, f"refs/heads/{spec.branch}")


def _declarations(ledger: lean.Ledger, commit: str, cited: list[str], errors: list[str]) -> dict[str, dict]:
    resolved = {}
    for gid in cited:
        try:
            res = lean.resolve(ledger, commit, gid)
        except lean.LeanError as exc:
            errors.append(str(exc))
            continue
        lean.locate(ledger, commit, res)
        resolved[gid] = res.to_lock()
    return resolved


def resolve_branch(spec: lean.BranchLock, *, commit: str = "", offline: bool = False) -> lean.Lock:
    site = config.load_site()
    _check_branch_lock(spec, site)
    _check_branch(spec.branch)
    ledger = lean.Ledger(spec.repo, offline=offline, mode=spec.mode, source_root=spec.source_root)
    if commit:
        _check_branch(spec.branch, commit)
        if not lean.SHA_RE.fullmatch(commit) or ledger.branch_contains(commit, spec.branch).on_branch is not True:
            raise lean.LeanError(f"cannot verify {commit!r} on {spec.repo}/{spec.branch}")
    elif offline:
        raise lean.LeanError("--offline needs a resolved branch snapshot or a fixed SHA lock")
    else:
        commit = branch_head(spec)
        ledger.record_on_branch(commit, spec.branch, f"head of {spec.branch}")
    errors: list[str] = []
    cited = cited_gids(config.load_books(), mode=spec.mode)
    resolved = _declarations(ledger, commit, cited, errors)
    if errors:
        raise lean.LeanError(f"cannot resolve {spec.repo}/{spec.branch} at {commit}:\n" + "\n".join(errors))
    return lean.Lock(repo=spec.repo, branch=spec.branch, commit=commit, declarations=resolved,
                     mode=spec.mode, source_root=spec.source_root)


def _target(ref: str | None, old: lean.Lock | None, *, refresh: bool, offline: bool, branch: str, repo: str,
            ledger) -> tuple[str, bool]:
    """(commit to pin, whether it is the head of ``branch`` by construction)."""
    if refresh:
        if old is None:
            raise lean.LeanError("nothing to refresh: trureturing.lock.json does not exist; run ./tbook pin")
        return old.commit, False
    if ref and lean.SHA_RE.match(ref):
        return ref, False
    if ref and lean.ABBREV_SHA_RE.match(ref):
        full = ledger.expand_sha(ref)
        if full:
            return full, False
    if offline:
        raise lean.LeanError("--offline needs a full 40-hex commit, a commit prefix the local trureturing checkout "
                             "knows, or --refresh")
    if not ref or ref == branch:
        return lean.ls_remote(repo, f"refs/heads/{branch}"), True
    return lean.ls_remote(repo, ref), False


def pin(ref: str | None = None, *, refresh: bool = False, offline: bool = False,
        dry_run: bool = False, follow: bool = False) -> PinReport:
    site = config.load_site()
    branch = site.trureturing_branch
    mode, source_root = site.trureturing_mode, site.trureturing_source_root
    _check_branch(branch)
    spec = lean.Lock.read_spec()
    if follow or (isinstance(spec, lean.BranchLock) and not ref):
        target = lean.BranchLock(site.trureturing_repo, branch, mode=mode, source_root=source_root)
        resolved = resolve_branch(target, offline=offline)
        if not dry_run:
            target.save()
        return PinReport(commit=resolved.commit, previous=spec.commit if isinstance(spec, lean.Lock) else "",
                         branch=branch, previous_branch=spec.branch if spec else "", written=not dry_run)
    old = spec if isinstance(spec, lean.Lock) else None
    ledger = lean.Ledger(site.trureturing_repo, offline=offline, mode=mode, source_root=source_root)
    commit, head = _target(ref, old, refresh=refresh, offline=offline, branch=branch,
                           repo=site.trureturing_repo, ledger=ledger)
    _check_branch(branch, commit)
    report = PinReport(commit=commit, previous=old.commit if old else "", branch=branch,
                       previous_branch=old.branch if old else "")
    if head:
        ledger.record_on_branch(commit, branch, f"head of {branch}")
    else:
        anc = ledger.branch_contains(commit, branch)
        where = f"branch {branch!r} of {site.trureturing_repo}"
        if anc.no_branch:
            report.refused = (f"site.toml [trureturing] branch {branch!r} is not a branch of {site.trureturing_repo} "
                              f"({anc.detail}): trureturing enforces its freeze rule on a branch, and only a branch "
                              "can show that a commit was merged")
            return report
        if anc.on_branch is False:
            report.refused = (f"{commit} is not on {where} ({anc.detail}). trureturing enforces the freeze rule "
                              f"only on {branch}: merge the formalization into {branch} first "
                              "(skills/theorem-formalize), then pin a commit on it")
            return report
        if anc.on_branch is None:
            msg = f"could not verify that {commit[:12]} is on {where}: {anc.detail}"
            if lean.ancestry_required(offline):
                report.refused = msg
                return report
            report.warnings.append(msg + "; ./tbook check verifies it again")
    cited = cited_gids(config.load_books(), mode=mode)
    resolved = _declarations(ledger, commit, cited, report.errors)
    before = old.declarations if old else {}
    report.added = sorted(set(resolved) - set(before))
    report.removed = sorted(set(before) - set(cited))  # a cited GID that fails to resolve is Unresolved only
    for gid in sorted(set(resolved) & set(before)):
        a, b = before[gid], resolved[gid]
        diffs = []
        if a.get("name") != b.get("name"):
            diffs.append(f"name {a.get('name')} → {b.get('name')}")
        if a.get("kind") != b.get("kind"):
            diffs.append(f"kind {a.get('kind')} → {b.get('kind')}")
        if a.get("statement_id") != b.get("statement_id"):
            diffs.append("declaration signature digest changed" if mode == "lean-source" else "module statement digest changed")
        if a.get("axioms") != b.get("axioms"):
            diffs.append(f"frozen axioms {a.get('axioms', 'unknown')} → {b.get('axioms', 'unknown')}")
        if diffs:
            report.changed.append((gid, "; ".join(diffs)))
        if int(a.get("line", 0) or 0) != int(b.get("line", 0) or 0):
            report.moved.append((gid, int(a.get("line", 0) or 0), int(b.get("line", 0) or 0)))
    if report.errors or dry_run:
        return report
    lock = lean.Lock(repo=site.trureturing_repo, branch=branch, commit=commit,
                     pinned_at=(old.pinned_at if old and refresh and old.commit == commit else lean.now_utc()),
                     declarations=resolved, mode=mode, source_root=source_root)
    lock.save()
    report.written = True
    return report
