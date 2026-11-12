"""Template versioning: ``./tbook template status | update | manifest``.

A books repository is created from trureturing-books-template and keeps receiving its
improvements. ``template.toml`` draws the line:

* ``[managed].paths`` — paths the template owns (tools, theme, skills, docs, workflows …).
  Entries ending in ``/`` are directories; other entries are a file or a directory.
* ``[managed].exclude`` — plain string prefixes inside managed paths that belong to the
  repository after all (``skills/local-``, ``docs/project/``).
* ``[managed].owned`` — paths that always belong to the repository (``books/``,
  ``site.toml`` …). Anything that is not under a managed path is owned as well.

``template-manifest.json`` records, for the template version the repository is on, the
sha256 and git mode (``100644`` / ``100755`` / ``120000``) of every managed file; symlinks
are hashed by their target. It is the *base* of a three-way comparison:

=====================  ===========================  =========================================
local vs. base         upstream vs. base            result
=====================  ===========================  =========================================
unchanged              changed / added / removed    take upstream
changed                unchanged                    keep local
changed                changed (differently)        conflict: keep local, write upstream to
                                                    ``<file>.template-new`` (``--force``: take
                                                    upstream)
absent (new file)      added, local file differs    conflict, as above
=====================  ===========================  =========================================

"Deleted locally" means the repository had the file: a file the base lists that is absent
and that the repository's git history never contained (a repository adopting the template,
whose copied manifest describes files it never had) is installed as if the base did not list
it. Without git history to tell (no repository, a shallow clone) the base is trusted.

Without ``--to`` the target is the newest stable release (a plain-directory ``--source`` is the
target as given), and ``update`` never goes back: when that release is older than
``template.toml``'s version, or has the same version but differs from the repository's manifest
(a repository created from the template's main branch between releases), it changes nothing and
says so; ``--to`` re-syncs or downgrades.

Owned and excluded paths are never touched. After the files, ``update`` writes the new
``template.toml`` and ``template-manifest.json``, runs the migrations
``tools/migrations/v<X.Y.Z>.py`` (``migrate(root: Path) -> list[str]``) of every version
in ``(old, new]`` from the new template, each in a fresh Python process that imports
``tbook`` from the fetched template (``TBOOK_ROOT`` = the repository), and writes a Markdown
summary to ``build/template-update.md`` (the body of the template-sync pull request).

Exit codes: 0 success, 1 error, 3 conflicts to merge by hand.

The status report and the update summary use the repository's default language (the first
of ``site.toml`` ``[site].languages`` with a string table here; ``TBOOK_LANG=zh|en``
overrides it). Errors are English, like the rest of the CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from . import paths

MANIFEST_NAME = "template-manifest.json"
TEMPLATE_TOML = "template.toml"
MANIFEST_SCHEMA = "trureturing-books.template-manifest.v1"
CONFLICT_SUFFIX = ".template-new"
SUMMARY_PATH = "build/template-update.md"
MIGRATIONS_DIR = "tools/migrations"
CHANGELOG = "docs/CHANGELOG.md"
SELF_FILES = (TEMPLATE_TOML, MANIFEST_NAME)  # never listed in the manifest itself
LAYER_DIR = "template.d"
LAYER_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
LAYER_PREFIXES = ("docs/layer-", "skills/layer-", ".github/workflows/layer-")

DEFAULT_REPO = "the-omega-institute/trureturing-books-template"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFLICTS = 3

MODE_FILE = "100644"
MODE_EXEC = "100755"
MODE_LINK = "120000"
MODE_OTHER = "040000"  # a directory (or anything that is not a file) where a file is expected

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
MIGRATION_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\.py$")
SHORT_SHA_RE = re.compile(r"^[0-9a-fA-F]{4,39}$")  # what an abbreviated commit SHA looks like
SKIP_NAMES = {"__pycache__", ".git", ".DS_Store", "node_modules"}

# --------------------------------------------------------------------------- strings
# Component-local i18n table (zh + en). Keys are candidates for theme/i18n/<lang>.toml [template].

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "colon": "：",
        "count": "（{n}）",
        "status_title": "模板",
        "status_manifest": "清单",
        "status_no_manifest": "没有 template-manifest.json：无法判断本地改动。从模板复制它，或运行 ./tbook template update。",
        "status_manifest_version_differs": "清单版本 {manifest} 与 template.toml 版本 {version} 不一致",
        "status_files": "{n} 个托管文件",
        "status_clean": "托管文件与清单一致。",
        "status_modified": "本地改过（{n}）",
        "status_missing": "缺失（{n}）",
        "status_extra": "多出（{n}）· 位于托管路径下、不在清单中",
        "status_pending": "待合并（{n}）· 上次升级留下的 .template-new 文件",
        "status_owned": "书库自有（升级永不触碰）",
        "status_excluded": "托管路径中的例外",
        "status_hint": "本地改过的文件在升级时不会被覆盖；上游也改了时会产生冲突。改进请回馈模板（skills/template-update）。",
        "sum_title": "模板升级 {old} → {new}",
        "sum_title_dry": "模板升级预览 {old} → {new}（--dry-run，未写入任何文件）",
        "sum_source": "来源",
        "sum_counts": "新增 {added} · 更新 {updated} · 删除 {removed} · 冲突 {conflicts} · 保留本地改动 {kept}",
        "sum_up_to_date": "托管文件已是最新，无需改动。",
        "sum_title_none": "模板 {old}：无需升级",
        "not_newer_older": "最新发布 {new} 比本书库的模板版本 {old} 旧。不带 `--to` 的升级从不降级，因此没有改动任何文件；确需降级时用 `--to {new}`。",
        "not_newer_same": "本书库已是最新发布的版本号 {new}，但托管文件来自同一版本号下的另一个快照（例如两次发布之间的模板 main 分支），换成发布版会撤销较新的改动，因此没有改动任何文件；下一个版本发布后再升级。确需与发布版同步时用 `--to {new}`。",
        "sec_added": "新增",
        "sec_updated": "更新",
        "sec_removed": "删除",
        "sec_conflicts": "冲突：需要人工合并",
        "sec_kept": "保留的本地改动（上游未改）",
        "sec_released": "不再由模板托管（保留在书库中，归书库所有）",
        "sec_skipped": "书库自有路径（未触碰）",
        "sec_migrations": "迁移",
        "sec_warnings": "警告",
        "sec_changelog": "变更记录",
        "sec_next": "下一步",
        "conflict_both": "本地与上游都改了；上游版本在 `{new}`",
        "conflict_added": "上游新增了此文件，但本地已有不同的同名文件；上游版本在 `{new}`",
        "conflict_deleted_local": "本地删除了此文件，上游改了它；上游版本在 `{new}`",
        "conflict_removed_upstream": "上游删除了此文件，但本地改过它；已保留本地文件",
        "conflict_dir": "此处是一个目录，无法写入上游文件",
        "conflict_forced": "已用 --force 采用上游版本（本地改动已丢弃）",
        "kept_modified": "本地改过",
        "kept_deleted": "本地已删除",
        "migration_none": "无需迁移。",
        "migration_pending": "将运行：{names}",
        "migration_no_notes": "（无输出）",
        "migration_failed": "{name} 失败：{error}",
        "changelog_link": "阅读跨越的各版本说明，处理标为“需要手动操作”的条目：{link}",
        "next_conflicts": "逐个合并冲突：比较每个文件与旁边的 `.template-new`，保留需要的改动后删除 `.template-new`。",
        "next_install": "重新安装依赖：`pip install -r requirements.txt`、`npm ci`。",
        "next_verify": "验证：`./tbook doctor`、`./tbook check`、`./tbook build all`，并运行单元测试。",
        "next_feedback": "本地对托管文件的改动应回馈模板仓库（`skills/template-update` B 节），否则每次升级都会再次冲突。",
        "wrote_summary": "摘要已写入 {path}",
    },
    "en": {
        "colon": ": ",
        "count": " ({n})",
        "status_title": "Template",
        "status_manifest": "Manifest",
        "status_no_manifest": "No template-manifest.json: local changes cannot be detected. Copy it from the template or run ./tbook template update.",
        "status_manifest_version_differs": "manifest version {manifest} differs from template.toml version {version}",
        "status_files": "{n} managed files",
        "status_clean": "Managed files match the manifest.",
        "status_modified": "Modified locally ({n})",
        "status_missing": "Missing ({n})",
        "status_extra": "Extra ({n}) · under managed paths, not in the manifest",
        "status_pending": "Pending merges ({n}) · .template-new files left by an update",
        "status_owned": "Owned by this repository (never touched by updates)",
        "status_excluded": "Exceptions inside managed paths",
        "status_hint": "Locally modified files are never overwritten by an update; if the template changed them too, you get a conflict. Contribute improvements upstream (skills/template-update).",
        "sum_title": "Template update {old} → {new}",
        "sum_title_dry": "Template update preview {old} → {new} (--dry-run, nothing written)",
        "sum_source": "Source",
        "sum_counts": "{added} added · {updated} updated · {removed} removed · {conflicts} conflicts · {kept} local changes kept",
        "sum_up_to_date": "Managed files are up to date; nothing to change.",
        "sum_title_none": "Template {old}: no update",
        "not_newer_older": "The latest release ({new}) is older than this repository's template version {old}. Without `--to` an update never downgrades, so nothing was changed; pass `--to {new}` to downgrade on purpose.",
        "not_newer_same": "This repository already has version {new}, the latest release, but its managed files come from another snapshot with that version number (for example the template's main branch between releases). Taking the release would revert newer changes, so nothing was changed; the next release will update it. Pass `--to {new}` to re-sync with the release anyway.",
        "sec_added": "Added",
        "sec_updated": "Updated",
        "sec_removed": "Removed",
        "sec_conflicts": "Conflicts: merge by hand",
        "sec_kept": "Local changes kept (unchanged upstream)",
        "sec_released": "No longer managed by the template (left in place, now owned by this repository)",
        "sec_skipped": "Owned paths (not touched)",
        "sec_migrations": "Migrations",
        "sec_warnings": "Warnings",
        "sec_changelog": "Changelog",
        "sec_next": "Next steps",
        "conflict_both": "changed locally and upstream; the upstream version is in `{new}`",
        "conflict_added": "added upstream, but a different local file exists; the upstream version is in `{new}`",
        "conflict_deleted_local": "deleted locally but changed upstream; the upstream version is in `{new}`",
        "conflict_removed_upstream": "removed upstream but changed locally; the local file was kept",
        "conflict_dir": "a directory is in the way; the upstream file cannot be written",
        "conflict_forced": "took the upstream version (--force; local changes discarded)",
        "kept_modified": "modified locally",
        "kept_deleted": "deleted locally",
        "migration_none": "No migrations needed.",
        "migration_pending": "Will run: {names}",
        "migration_no_notes": "(no output)",
        "migration_failed": "{name} failed: {error}",
        "changelog_link": "Read the notes of every version crossed and act on items marked as needing manual steps: {link}",
        "next_conflicts": "Resolve each conflict: compare the file with the `.template-new` next to it, keep what you need, then delete the `.template-new`.",
        "next_install": "Reinstall dependencies: `pip install -r requirements.txt`, `npm ci`.",
        "next_verify": "Verify: `./tbook doctor`, `./tbook check`, `./tbook build all`, and run the unit tests.",
        "next_feedback": "Contribute local changes to managed files back to the template (`skills/template-update`, section B), or they will conflict on every update.",
        "wrote_summary": "Summary written to {path}",
    },
}


def _lang(root: Path) -> str:
    """The repository's default language for messages: TBOOK_LANG, else site.toml, else English."""
    env = os.environ.get("TBOOK_LANG", "")
    if env in STRINGS:
        return env
    try:
        with (root / "site.toml").open("rb") as fh:
            langs = tomllib.load(fh).get("site", {}).get("languages") or []
    except (OSError, tomllib.TOMLDecodeError):
        langs = []
    for lang in langs:
        if lang in STRINGS:
            return lang
        base = str(lang).split("-")[0]
        if base in STRINGS:
            return base
    return "en"


def _t(lang: str, key: str, **kw: object) -> str:
    text = STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"][key]
    return text.format(**kw) if kw else text


# --------------------------------------------------------------------------- errors, semver


class TemplateError(Exception):
    """A user-facing failure of a template command (exit code 1)."""


def parse_semver(text: str) -> tuple | None:
    """Sort key for ``X.Y.Z[-pre][+build]``; None when ``text`` is not a semantic version.

    Pre-releases sort before their release; numeric identifiers before alphanumeric ones.
    """
    m = SEMVER_RE.match(text.strip())
    if not m:
        return None
    major, minor, patch, pre = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    if pre is None:
        return (major, minor, patch, 1, ())
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (major, minor, patch, 0, ids)


def is_prerelease(version: str) -> bool:
    key = parse_semver(version)
    return bool(key and key[3] == 0)


# --------------------------------------------------------------------------- template.toml


def _under(path: str, entry: str) -> bool:
    """``tools/`` matches everything below it; ``tbook`` matches the file (or a directory) ``tbook``."""
    entry = entry.strip()
    if not entry:
        return False
    if entry.endswith("/"):
        return path.startswith(entry)
    return path == entry or path.startswith(entry + "/")


@dataclass
class TemplateConfig:
    name: str
    repo: str
    version: str
    tag_prefix: str = "v"
    managed: list[str] = field(default_factory=list)
    owned: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    layer: str | None = None

    @property
    def config_path(self) -> str:
        return f"{LAYER_DIR}/{self.layer}.toml" if self.layer else TEMPLATE_TOML

    @property
    def manifest_path(self) -> str:
        return f"{LAYER_DIR}/{self.layer}.manifest.json" if self.layer else MANIFEST_NAME

    @property
    def migrations_dir(self) -> str:
        return f"docs/layer-{self.layer}/migrations" if self.layer else MIGRATIONS_DIR

    @property
    def changelog_path(self) -> str:
        return f"docs/layer-{self.layer}/CHANGELOG.md" if self.layer else CHANGELOG

    @classmethod
    def from_bytes(cls, data: bytes, where: str = TEMPLATE_TOML) -> "TemplateConfig":
        try:
            raw = tomllib.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise TemplateError(f"{where}: {exc}") from exc
        tpl = raw.get("template", {})
        man = raw.get("managed", {})
        if not tpl.get("version"):
            raise TemplateError(f"{where}: [template].version is required")
        if not man.get("paths"):
            raise TemplateError(f"{where}: [managed].paths is required")
        for key in ("paths", "owned", "exclude"):
            value = man.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise TemplateError(f"{where}: [managed].{key} must be a list of strings")
        return cls(
            name=str(tpl.get("name", "")),
            repo=str(tpl.get("repo", "") or DEFAULT_REPO),
            version=str(tpl["version"]),
            tag_prefix=str(tpl.get("tag_prefix", "v")),
            managed=list(man.get("paths", [])),
            owned=list(man.get("owned", [])),
            exclude=list(man.get("exclude", [])),
        )

    @classmethod
    def load(cls, root: Path, layer: str | None = None) -> "TemplateConfig":
        validate_layer_name(layer)
        path = root / (f"{LAYER_DIR}/{layer}.toml" if layer else TEMPLATE_TOML)
        if not path.is_file():
            if layer:
                raise TemplateError(f"{path}: layer is not installed (use ./tbook template install {layer} --source <source>)")
            raise TemplateError(
                f"{TEMPLATE_TOML} not found in {root}; a repository that was not created from the template "
                "can adopt it: copy tbook, tools/ and template.toml from a template release, then run "
                "./tbook template update, which installs the other managed files (docs/UPGRADING.md §5)"
            )
        return replace(cls.from_bytes(path.read_bytes(), str(path)), layer=layer)

    def under_managed(self, path: str) -> bool:
        return any(_under(path, e) for e in self.managed)

    def is_owned(self, path: str) -> bool:
        return any(_under(path, e) for e in self.owned)

    def is_excluded(self, path: str) -> bool:
        return any(e and path.startswith(e) for e in self.exclude)

    def protects(self, path: str) -> bool:
        """Owned or excluded: an update must never touch it."""
        return self.is_owned(path) or self.is_excluded(path)

    def manages(self, path: str) -> bool:
        """True for files whose content the template owns (and lists in the manifest)."""
        if path in (*SELF_FILES, self.config_path, self.manifest_path) or path.endswith(CONFLICT_SUFFIX):
            return False
        return self.under_managed(path) and not self.protects(path)


def validate_layer_name(name: str | None) -> None:
    if name is not None and (not LAYER_RE.fullmatch(name) or name == "upstream"):
        raise TemplateError(f"invalid layer name {name!r}; use lowercase words, digits and hyphens (upstream is reserved)")


def layer_configs(root: Path) -> list[TemplateConfig]:
    return [TemplateConfig.load(root, p.stem) for p in sorted((root / LAYER_DIR).glob("*.toml"))]


def _overlap(a: str, b: str) -> bool:
    return _under(a.rstrip("/"), b) or _under(b.rstrip("/"), a) or a.rstrip("/") == b.rstrip("/")


def validate_claims(root: Path, candidate: TemplateConfig | None = None) -> None:
    """Reject overlapping namespaces before any writes, even when the files do not exist yet.

    Claims inside upstream directories must fit entirely within an excluded prefix.
    The three reserved namespaces are partitioned by layer name; other unclaimed
    paths may also be managed, but repository-owned paths and template.d are protected.
    """
    if (root / LAYER_DIR).is_symlink():
        raise TemplateError("template.d must be a real downstream-owned directory")
    # A standalone layer source has no upstream config. Its manifest can still be
    # generated; ownership against the consumer's upstream is checked at install.
    upstream = candidate if candidate is not None and not candidate.layer else (
        TemplateConfig.load(root) if (root / TEMPLATE_TOML).is_file() else None)
    upstream_owned = upstream.owned if upstream else []
    upstream_exclude = upstream.exclude if upstream else []
    upstream_managed = upstream.managed if upstream else []
    layers = {c.layer: c for c in layer_configs(root)}
    if candidate is not None and candidate.layer:
        layers[candidate.layer] = candidate
    claimed: list[tuple[str, str]] = []
    for name, cfg in sorted(layers.items()):
        for metadata in (cfg.config_path, cfg.manifest_path):
            if (root / metadata).is_symlink() or not _inside(root, root / metadata):
                raise TemplateError(f"{metadata}: layer metadata must be inside the repository, without symlinks")
        if cfg.name != name or parse_semver(cfg.version) is None:
            raise TemplateError(f"layer {name}: [template].name must match its filename and version must be semver")
        for entry in cfg.managed:
            clean = entry.rstrip("/")
            if not _safe_relpath(clean) or "\\" in clean or "." in clean.split("/") or any(c in clean for c in "*?["):
                raise TemplateError(f"layer {name}: invalid managed path {entry!r}")
            if any(_overlap(entry, p) for p in [*SELF_FILES, LAYER_DIR + "/", *upstream_owned]):
                raise TemplateError(f"layer {name}: cannot claim repository-owned path {entry!r}")
            if any(entry.startswith(p) for p in upstream_exclude if p not in LAYER_PREFIXES):
                raise TemplateError(f"layer {name}: cannot claim repository-owned path {entry!r}")
            for prefix, own in [("docs/layer-", f"docs/layer-{name}/"),
                                ("skills/layer-", f"skills/layer-{name}-"),
                                (".github/workflows/layer-", f".github/workflows/layer-{name}-")]:
                if clean.startswith(prefix) and not (entry.startswith(own) or entry == own):
                    raise TemplateError(f"layer {name}: path {entry!r} belongs to another layer namespace")
            if any(_overlap(entry, p) for p in upstream_managed):
                if not any(entry.startswith(e) for e in upstream_exclude):
                    raise TemplateError(f"layer {name}: upstream manages {entry!r}")
            for other, path in claimed:
                if other != name and _overlap(entry, path):
                    raise TemplateError(f"layer {name}: {entry!r} overlaps layer {other} claim {path!r}")
            claimed.append((name, entry))


def targets(root: Path) -> list[dict[str, str]]:
    validate_claims(root)
    return [{"name": c.layer or "upstream", "repo": c.repo, "version": c.version}
            for c in [TemplateConfig.load(root), *layer_configs(root)]]


# --------------------------------------------------------------------------- files and manifest


@dataclass(frozen=True)
class Entry:
    sha256: str
    mode: str

    def to_json(self) -> dict:
        return {"sha256": self.sha256, "mode": self.mode}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(path: Path) -> Entry | None:
    """Entry of a working-tree path: None if absent; symlinks hashed by their target."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return Entry(hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest(), MODE_LINK)
    if stat.S_ISREG(st.st_mode):
        return Entry(_sha256_file(path), MODE_EXEC if st.st_mode & stat.S_IXUSR else MODE_FILE)
    return Entry("", MODE_OTHER)


@dataclass
class Manifest:
    template: str
    version: str
    files: dict[str, Entry] = field(default_factory=dict)
    schema: str = MANIFEST_SCHEMA

    def to_json(self) -> str:
        data = {
            "schema": self.schema,
            "template": self.template,
            "version": self.version,
            "files": {p: self.files[p].to_json() for p in sorted(self.files)},
        }
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_bytes(cls, data: bytes, where: str = MANIFEST_NAME) -> "Manifest":
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TemplateError(f"{where}: invalid JSON: {exc}") from exc
        if raw.get("schema") != MANIFEST_SCHEMA:
            raise TemplateError(f"{where}: unsupported schema {raw.get('schema')!r} (expected {MANIFEST_SCHEMA})")
        files: dict[str, Entry] = {}
        for p, e in (raw.get("files") or {}).items():
            if not isinstance(e, dict) or "sha256" not in e or "mode" not in e:
                raise TemplateError(f"{where}: bad entry for {p!r}")
            files[p] = Entry(str(e["sha256"]), str(e["mode"]))
        return cls(template=str(raw.get("template", "")), version=str(raw.get("version", "")), files=files)

    @classmethod
    def load(cls, root: Path, name: str = MANIFEST_NAME) -> "Manifest | None":
        path = root / name
        if not path.is_file():
            return None
        return cls.from_bytes(path.read_bytes(), str(path))


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except OSError as exc:  # git not installed
        raise TemplateError(f"cannot run git: {exc}") from exc
    if check and r.returncode != 0:
        msg = r.stderr.decode("utf-8", "replace").strip() or r.stdout.decode("utf-8", "replace").strip()
        raise TemplateError(f"git {' '.join(args)} failed: {msg}")
    return r


def _is_repo_root(root: Path) -> bool:
    r = _git(root, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return False
    top = Path(r.stdout.decode("utf-8", "replace").strip())
    try:
        return top.resolve() == root.resolve()
    except OSError:
        return False


def _walk(root: Path, cfg: TemplateConfig) -> list[str]:
    """Fallback without git: every file below the managed paths (symlinked directories are entries)."""
    out: list[str] = []
    for entry in cfg.managed:
        base = root / entry.rstrip("/")
        if base.is_symlink() or base.is_file():
            out.append(base.relative_to(root).as_posix())
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            d = Path(dirpath)
            keep = []
            for name in dirnames:
                if name in SKIP_NAMES:
                    continue
                if (d / name).is_symlink():
                    filenames.append(name)
                else:
                    keep.append(name)
            dirnames[:] = sorted(keep)
            for name in filenames:
                if name in SKIP_NAMES or name.endswith((".pyc", ".swp")):
                    continue
                out.append((d / name).relative_to(root).as_posix())
    return out


def candidate_files(root: Path, cfg: TemplateConfig) -> list[str]:
    """Tracked plus untracked-but-not-ignored files (``git ls-files``), or a walk without git."""
    if _is_repo_root(root):
        r = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", check=True)
        names = [p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p]
    else:
        names = _walk(root, cfg)
    return sorted({p for p in names if os.path.lexists(root / p)})


def managed_files(root: Path, cfg: TemplateConfig) -> dict[str, Entry]:
    out: dict[str, Entry] = {}
    for p in candidate_files(root, cfg):
        if not cfg.manages(p):
            continue
        entry = file_entry(root / p)
        if entry is None or entry.mode == MODE_OTHER:  # gitlinks / directories are not files
            continue
        out[p] = entry
    return out


def build_manifest(root: Path, cfg: TemplateConfig) -> Manifest:
    return Manifest(template=cfg.name, version=cfg.version, files=managed_files(root, cfg))


def manifest_diff(old: Manifest | None, new: Manifest) -> list[str]:
    """Human-readable differences (empty when equal)."""
    lines: list[str] = []
    if old is None:
        return [f"  {MANIFEST_NAME} does not exist"]
    if old.template != new.template:
        lines.append(f"  template: {old.template!r} → {new.template!r}")
    if old.version != new.version:
        lines.append(f"  version: {old.version} → {new.version}")
    for p in sorted(set(old.files) | set(new.files)):
        a, b = old.files.get(p), new.files.get(p)
        if a == b:
            continue
        if a is None:
            lines.append(f"  + {p}")
        elif b is None:
            lines.append(f"  - {p}")
        elif a.mode != b.mode and a.sha256 == b.sha256:
            lines.append(f"  ~ {p} (mode {a.mode} → {b.mode})")
        else:
            lines.append(f"  ~ {p}")
    if old.schema != new.schema:
        lines.append(f"  schema: {old.schema} → {new.schema}")
    return lines


# --------------------------------------------------------------------------- manifest command


def _origin_repo(root: Path) -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    r = _git(root, "remote", "get-url", "origin")
    if r.returncode != 0:
        return ""
    url = r.stdout.decode("utf-8", "replace").strip()
    m = re.search(r"(?:github\.com[:/]|/git/)([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else ""


def cmd_manifest(root: Path, *, check: bool = False, layer: str | None = None, out: Callable[[str], None] = print) -> int:
    cfg = TemplateConfig.load(root, layer)
    validate_claims(root, cfg)
    new = build_manifest(root, cfg)
    unreadable = ""
    try:
        old = Manifest.load(root, cfg.manifest_path)
    except TemplateError as exc:
        old, unreadable = None, str(exc)
    if check:
        if unreadable:
            diff = [f"  {unreadable}"]
        else:
            diff = manifest_diff(old, new) if old is None or old.to_json() != new.to_json() else []
        if diff:
            out(f"{cfg.manifest_path} is out of date; run ./tbook template manifest and commit it:")
            for line in diff[:200]:
                out(line)
            if len(diff) > 200:
                out(f"  … and {len(diff) - 200} more")
            return EXIT_ERROR
        out(f"{cfg.manifest_path} is up to date ({len(new.files)} files, version {new.version})")
        return EXIT_OK
    origin = _origin_repo(root)
    if origin and cfg.repo and origin.lower() != cfg.repo.lower():
        print(f"warning: this repository ({origin}) is not the template ({cfg.repo}). The manifest is the base "
              "that `./tbook template update` compares local changes against; regenerating it here makes local "
              "edits look like template content. Restore it with `git checkout -- template-manifest.json` "
              "unless that is what you want.", file=sys.stderr)
    text = new.to_json()
    path = root / cfg.manifest_path
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
        out(f"wrote {cfg.manifest_path} ({len(new.files)} files, version {new.version})")
    else:
        out(f"{cfg.manifest_path} is up to date ({len(new.files)} files, version {new.version})")
    return EXIT_OK


# --------------------------------------------------------------------------- status command


@dataclass
class Status:
    version: str
    manifest: Manifest | None
    modified: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def compute_status(root: Path, cfg: TemplateConfig | None = None) -> Status:
    cfg = cfg or TemplateConfig.load(root)
    manifest = Manifest.load(root, cfg.manifest_path)
    st = Status(version=cfg.version, manifest=manifest)
    candidates = candidate_files(root, cfg)
    st.pending = [p for p in candidates if p.endswith(CONFLICT_SUFFIX) and cfg.under_managed(p) and not cfg.protects(p)]
    if manifest is None:
        return st
    for p, base in sorted(manifest.files.items()):
        if cfg.protects(p) or not cfg.under_managed(p):
            continue
        local = file_entry(root / p)
        if local is None:
            st.missing.append(p)
        elif local != base:
            st.modified.append(p)
    for p in candidates:
        if cfg.manages(p) and p not in manifest.files:
            entry = file_entry(root / p)
            if entry is not None and entry.mode != MODE_OTHER:
                st.extra.append(p)
    return st


def cmd_status(root: Path, *, layer: str | None = None, out: Callable[[str], None] = print) -> int:
    cfg = TemplateConfig.load(root, layer)
    validate_claims(root, cfg)
    lang = _lang(root)
    colon = _t(lang, "colon")
    st = compute_status(root, cfg)
    out(f"{_t(lang, 'status_title')}{colon}{cfg.name} {cfg.version} ({cfg.repo})")
    if st.manifest is None:
        out(_t(lang, "status_no_manifest"))
    else:
        out(f"{_t(lang, 'status_manifest')}{colon}{st.manifest.version} · "
            f"{_t(lang, 'status_files', n=len(st.manifest.files))}")
        if st.manifest.version != cfg.version:
            out("warning: " + _t(lang, "status_manifest_version_differs", manifest=st.manifest.version,
                                  version=cfg.version))
    groups = (("status_modified", "M", st.modified), ("status_missing", "D", st.missing),
              ("status_extra", "?", st.extra), ("status_pending", "!", st.pending))
    if st.manifest is not None and not (st.modified or st.missing or st.extra or st.pending):
        out(_t(lang, "status_clean"))
    for key, mark, items in groups:
        if items:
            out("")
            out(_t(lang, key, n=len(items)) + colon.rstrip())
            for p in items:
                out(f"  {mark} {p}")
    out("")
    out(f"{_t(lang, 'status_owned')}{colon}{', '.join(cfg.owned) or '—'}")
    if cfg.exclude:
        shown = ", ".join(e if e.endswith("/") else e + "*" for e in cfg.exclude)
        out(f"{_t(lang, 'status_excluded')}{colon}{shown}")
    if st.modified or st.missing:
        out("")
        out(_t(lang, "status_hint"))
    return EXIT_OK


# --------------------------------------------------------------------------- fetching the template


@dataclass
class Upstream:
    dir: Path
    source: str
    ref: str  # what was fetched (tag name, branch, sha, or "" for a plain directory)
    commit: str  # resolved commit ("" for a plain directory)
    cfg: TemplateConfig
    manifest: Manifest  # computed from the fetched tree
    declared: Manifest | None  # template-manifest.json as shipped
    warnings: list[str] = field(default_factory=list)


def default_source(cfg: TemplateConfig) -> str:
    return f"https://github.com/{cfg.repo}.git"


def _is_local(source: str) -> bool:
    return not re.match(r"^[a-z][a-z0-9+.-]*://", source, re.I) and not re.match(r"^[\w.-]+@[\w.-]+:", source) \
        and Path(source).expanduser().exists()


def _is_git_dir(p: Path) -> bool:
    return (p / ".git").exists() or ((p / "HEAD").is_file() and (p / "objects").is_dir())


def remote_tags(source: str) -> dict[str, str]:
    """``{tag name: commit}`` from ``git ls-remote --tags`` (annotated tags peeled)."""
    try:
        r = subprocess.run(["git", "ls-remote", "--tags", source], capture_output=True)
    except OSError as exc:
        raise TemplateError(f"cannot run git: {exc}") from exc
    if r.returncode != 0:
        raise TemplateError(f"git ls-remote --tags {source} failed: "
                            f"{r.stderr.decode('utf-8', 'replace').strip()}")
    tags: dict[str, str] = {}
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        sha, name = parts[0], parts[1][len("refs/tags/"):]
        if name.endswith("^{}"):
            tags[name[:-3]] = sha  # the peeled commit wins over the tag object
        else:
            tags.setdefault(name, sha)
    return tags


def release_tags(tags: Iterable[str], prefix: str) -> list[tuple[str, str]]:
    """``[(tag, version)]`` of tags ``<prefix>X.Y.Z``, sorted ascending by semver."""
    out = []
    for tag in tags:
        if not tag.startswith(prefix):
            continue
        version = tag[len(prefix):]
        if parse_semver(version) is not None:
            out.append((tag, version))
    return sorted(out, key=lambda tv: parse_semver(tv[1]))


def resolve_target(to: str | None, tags: dict[str, str], prefix: str, source: str) -> tuple[str, str]:
    """``(ref to fetch, label)`` for ``--to`` (a version, a tag, a branch or a commit)."""
    releases = release_tags(tags, prefix)
    if not to:
        stable = [tv for tv in releases if not is_prerelease(tv[1])]
        if not stable:
            raise TemplateError(f"no release tags {prefix}X.Y.Z found in {source}; pass --to <version or ref>")
        tag = stable[-1][0]
        return f"refs/tags/{tag}", tag
    candidates = [to] if to.startswith(prefix) else [prefix + to, to]
    for cand in candidates:
        if cand in tags:
            return f"refs/tags/{cand}", cand
    version = to[len(prefix):] if to.startswith(prefix) else to
    if parse_semver(version) is not None:
        known = ", ".join(t for t, _ in releases[-8:]) or "none"
        raise TemplateError(f"template version {to} not found in {source} (latest tags: {known})")
    return to, to


def fetch_upstream(source: str, ref: str, dest: Path) -> str:
    """Shallow-fetch ``ref`` of ``source`` into ``dest`` and check it out; returns the commit."""
    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q", check=True)
    _git(dest, "config", "core.symlinks", "true")
    r = _git(dest, "fetch", "-q", "--depth", "1", "--no-tags", source, ref)
    if r.returncode != 0:
        raise TemplateError(f"cannot fetch {ref!r} from {source}: {r.stderr.decode('utf-8', 'replace').strip()}")
    _git(dest, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", "FETCH_HEAD", check=True)
    return _git(dest, "rev-parse", "HEAD", check=True).stdout.decode().strip()


def load_upstream(src_dir: Path, *, source: str, ref: str, commit: str,
                  layer: str | None = None) -> Upstream:
    config_path = f"{LAYER_DIR}/{layer}.toml" if layer else TEMPLATE_TOML
    toml_path = src_dir / config_path
    if not toml_path.is_file():
        raise TemplateError(f"{source} at {ref or 'its working tree'} has no {config_path}: not the requested template")
    cfg = replace(TemplateConfig.from_bytes(toml_path.read_bytes(), f"{source}:{config_path}"), layer=layer)
    try:
        declared = Manifest.load(src_dir, cfg.manifest_path)
    except TemplateError as exc:
        declared = None
        warn = [f"upstream {MANIFEST_NAME} is unreadable ({exc}); using the fetched tree"]
    else:
        warn = []
    computed = build_manifest(src_dir, cfg)
    up = Upstream(dir=src_dir, source=source, ref=ref, commit=commit, cfg=cfg, manifest=computed,
                  declared=declared, warnings=warn)
    if declared is None and not warn:
        up.warnings.append(f"upstream has no {MANIFEST_NAME}; the file list was computed from the fetched tree")
    elif declared is not None:
        diff = manifest_diff(declared, computed)
        if diff:
            up.warnings.append(f"upstream {MANIFEST_NAME} does not match its tree ({len(diff)} differences); "
                               "using the tree")
    return up


# --------------------------------------------------------------------------- three-way plan


ADD, UPDATE, REMOVE, CONFLICT, KEEP, SAME, RELEASE, SKIP = (
    "add", "update", "remove", "conflict", "keep", "same", "release", "skip")


@dataclass
class Action:
    path: str
    kind: str
    reason: str = ""  # i18n key for conflicts / kept files
    forced: bool = False  # a conflict resolved by --force
    upstream: Entry | None = None


def _safe_relpath(p: str) -> bool:
    parts = p.split("/")
    return bool(p) and not p.startswith("/") and ".." not in parts and "" not in parts and ".git" not in parts


def never_installed(root: Path, base: Manifest | None) -> set[str]:
    """Files the base manifest lists that are absent here and that the repository never had.

    "Never had" means: not in the index and in no commit of HEAD's history, branches merged with a
    merge commit included (renames counted as deletions). A squash merge leaves no such commit: a file
    added and deleted in a squashed branch was never here. A repository that adopts the template by
    copying tbook, tools/, template.toml and template-manifest.json has none of the other managed
    files; they must be installed, not kept "deleted locally". Empty when this cannot be known: no
    base, not the root of a git repository, or a shallow clone (whose history may not show a deletion).
    """
    if base is None:
        return set()
    missing = sorted(p for p in base.files
                     if p not in SELF_FILES and _safe_relpath(p) and not os.path.lexists(root / p))
    if not missing or not _is_repo_root(root):
        return set()
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0 or shallow.stdout.decode("utf-8", "replace").strip() != "false":
        return set()
    has_head = _git(root, "rev-parse", "-q", "--verify", "HEAD^{commit}").returncode == 0
    seen: set[str] = set()
    for i in range(0, len(missing), 500):  # keep command lines short
        specs = [f":(literal){p}" for p in missing[i:i + 500]]
        queries = [("ls-files", "-z", "--cached", "--", *specs)]
        if has_head:
            # --full-history: every commit that touches a path, also on merged side branches (the default
            # simplification skips a branch whose merge is TREESAME to its first parent, e.g. a file added
            # and deleted there); -m: merge commits too, against each parent (a merge resolution adding or
            # dropping a file).
            queries.append(("log", "--full-history", "-m", "--no-renames", "--format=", "--name-only", "-z",
                            "HEAD", "--", *specs))
        for query in queries:
            r = _git(root, *query)
            if r.returncode != 0:
                return set()
            seen.update(n.strip("\n") for n in r.stdout.decode("utf-8", "surrogateescape").split("\0"))
    return set(missing) - seen


def plan_update(root: Path, local_cfg: TemplateConfig, base: Manifest | None, up: Upstream,
                *, force: bool = False, never_had: set[str] | frozenset[str] = frozenset()) -> list[Action]:
    """The three-way plan. ``never_had``: base files to treat as not in the base (see never_installed)."""
    base_files = base.files if base else {}
    theirs = up.manifest.files
    actions: list[Action] = []
    for p in sorted(set(base_files) | set(theirs)):
        if p in SELF_FILES or not _safe_relpath(p):
            continue
        b, t = (None if p in never_had else base_files.get(p)), theirs.get(p)
        if b is None and t is None:  # listed only in a base that never applied here: nothing to do
            continue
        if t is None and not up.cfg.manages(p):
            actions.append(Action(p, RELEASE))  # the template let go of it: it stays, owned locally
            continue
        if local_cfg.protects(p) or up.cfg.protects(p):
            actions.append(Action(p, SKIP, upstream=t))  # owned or excluded here: never touched
            continue
        local = file_entry(root / p)
        if t == b:
            if local == b:
                actions.append(Action(p, SAME, upstream=t))
            else:
                actions.append(Action(p, KEEP, "kept_deleted" if local is None else "kept_modified", upstream=t))
            continue
        if local == t:
            actions.append(Action(p, SAME, upstream=t))
            continue
        if local == b:
            kind = REMOVE if t is None else ADD if local is None else UPDATE
            actions.append(Action(p, kind, upstream=t))
            continue
        # local changed and upstream changed differently: a conflict
        if local is not None and local.mode == MODE_OTHER:
            actions.append(Action(p, CONFLICT, "conflict_dir", upstream=t))
            continue
        if t is None:
            reason = "conflict_removed_upstream"
        elif local is None:
            reason = "conflict_deleted_local"
        elif b is None:
            reason = "conflict_added"
        else:
            reason = "conflict_both"
        if force:
            kind = REMOVE if t is None else ADD if local is None else UPDATE
            actions.append(Action(p, kind, reason, forced=True, upstream=t))
        else:
            actions.append(Action(p, CONFLICT, reason, upstream=t))
    return actions


# --------------------------------------------------------------------------- applying


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _inside(root: Path, path: Path) -> bool:
    try:
        path.parent.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()


def _copy_entry(src: Path, dst: Path, entry: Entry, mask: int) -> None:
    """Copy a file or symlink from the fetched template, with its mode, replacing ``dst`` atomically."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if entry.mode == MODE_LINK:
        target = os.readlink(src)
        tmp = dst.with_name(dst.name + ".tbook-tmp")
        _remove(tmp)
        os.symlink(target, tmp)
        os.replace(tmp, dst)
        return
    fd, tmp_name = tempfile.mkstemp(prefix=dst.name + ".", suffix=".tbook-tmp", dir=dst.parent)
    try:
        with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
            shutil.copyfileobj(inp, out)
        os.chmod(tmp_name, (0o777 if entry.mode == MODE_EXEC else 0o666) & ~mask)
        if dst.is_dir() and not dst.is_symlink():
            raise TemplateError(f"{dst}: a directory is in the way")
        os.replace(tmp_name, dst)
    except BaseException:
        if os.path.lexists(tmp_name):
            os.unlink(tmp_name)
        raise


def _prune_dirs(root: Path, start: Path) -> None:
    d = start
    root = root.resolve()
    while d.resolve() != root and d.is_dir() and not d.is_symlink():
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            break
        d = d.parent


def apply_plan(root: Path, up: Upstream, actions: list[Action]) -> list[str]:
    """Write the plan to the working tree; returns error messages (empty on success)."""
    mask = _umask()
    errors: list[str] = []
    # Removals first, so that a file replaced by a directory (or the reverse) has room.
    ordered = [a for a in actions if a.kind == REMOVE] + [a for a in actions if a.kind != REMOVE]
    for a in ordered:
        dst = root / a.path
        try:
            if a.kind in (ADD, UPDATE, REMOVE, CONFLICT) and not _inside(root, dst):
                raise TemplateError(f"{a.path}: path leaves the repository through a symlink")
            if a.kind in (ADD, UPDATE):
                _copy_entry(up.dir / a.path, dst, a.upstream, mask)
                if a.forced:
                    _remove(dst.with_name(dst.name + CONFLICT_SUFFIX))
            elif a.kind == REMOVE:
                _remove(dst)
                if a.forced:
                    _remove(dst.with_name(dst.name + CONFLICT_SUFFIX))
                _prune_dirs(root, dst.parent)
            elif a.kind == CONFLICT and a.upstream is not None and a.reason != "conflict_dir":
                _copy_entry(up.dir / a.path, dst.with_name(dst.name + CONFLICT_SUFFIX), a.upstream, mask)
        except (OSError, TemplateError) as exc:
            errors.append(f"{a.path}: {exc}")
    return errors


# --------------------------------------------------------------------------- migrations


@dataclass
class Migration:
    version: str
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


def find_migrations(directory: Path, old: str, new: str) -> list[Migration]:
    """Migrations ``v<X.Y.Z>.py`` with ``old < X.Y.Z <= new``, in semver order."""
    lo, hi = parse_semver(old), parse_semver(new)
    if lo is None or hi is None or not directory.is_dir():
        return []
    found = []
    for f in directory.iterdir():
        m = MIGRATION_RE.match(f.name)
        if not m or not f.is_file():
            continue
        key = parse_semver(m.group(1))
        if key is not None and lo < key <= hi:
            found.append(Migration(m.group(1), f))
    return sorted(found, key=lambda mg: parse_semver(mg.version))


# Runs one migration in a fresh interpreter: argv = migration file, repository root, result file (JSON).
_MIGRATION_RUNNER = r"""
import importlib.util, json, sys, traceback
from pathlib import Path

path, root, result = sys.argv[1:4]

def done(**data):
    with open(result, "w", encoding="utf-8") as fh:
        json.dump(data, fh)

fn = notes = None
try:
    spec = importlib.util.spec_from_file_location("tbook_migration", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, "migrate", None)
    if callable(fn):
        notes = fn(Path(root))
except BaseException as exc:
    traceback.print_exc()
    done(error=f"{type(exc).__name__}: {exc}")
    sys.exit(1)
if not callable(fn):
    done(missing=True)
elif notes is None:
    done(notes=[])
elif isinstance(notes, str):
    done(notes=[notes])
else:
    done(notes=[str(n) for n in notes])
"""


def run_migration(mig: Migration, root: Path, tools: Path | None = None) -> list[str]:
    """Run ``mig`` in a fresh Python process and return its notes.

    ``import tbook`` there loads the template the migration came from (``tools``, by default the
    ``tools/`` directory holding ``tools/migrations/`` when it has ``tbook/``), never the modules this
    process imported before the update; ``TBOOK_ROOT`` points ``tbook.paths`` at ``root``, which is
    also the working directory.
    """
    if tools is None:
        guess = mig.path.resolve().parent.parent
        tools = guess if (guess / "tbook").is_dir() else None
    env = dict(os.environ, TBOOK_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)  # never the modules of the template this process runs
    if tools is not None:
        env["PYTHONPATH"] = str(tools)
    with tempfile.TemporaryDirectory(prefix="tbook-migration-") as tmp:
        result = Path(tmp) / "result.json"
        try:
            r = subprocess.run([sys.executable or "python3", "-P", "-c", _MIGRATION_RUNNER, str(mig.path),
                                str(root), str(result)], cwd=root, env=env, stderr=subprocess.PIPE)
        except OSError as exc:
            raise TemplateError(f"cannot run Python for {mig.name}: {exc}") from exc
        if r.stderr:
            sys.stderr.write(r.stderr.decode("utf-8", "replace"))
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise TemplateError(f"{mig.name} exited with status {r.returncode} without a result") from None
    if data.get("missing"):
        raise TemplateError(f"{mig.name} defines no migrate(root) function")
    if "error" in data:
        raise TemplateError(str(data["error"]))
    return [str(n) for n in data.get("notes", [])]


# --------------------------------------------------------------------------- changelog


def changelog_sections(text: str, old: str, new: str) -> str:
    """The ``## [X.Y.Z]`` sections of a Keep-a-Changelog file for versions in ``(old, new]``."""
    lo, hi = parse_semver(old), parse_semver(new)
    out: list[str] = []
    keep = False
    for line in text.splitlines():
        m = re.match(r"^##\s+\[?v?([^\]\s]+)\]?", line)
        if m:
            key = parse_semver(m.group(1))
            keep = key is not None and hi is not None and key <= hi and (lo is None or key > lo)
        elif re.match(r"^#\s", line):
            keep = False
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def _changelog_link(up: Upstream) -> str:
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$", up.source)
    if m and up.ref:
        ref = up.ref[len("refs/tags/"):] if up.ref.startswith("refs/tags/") else up.ref
        return f"https://github.com/{m.group(1)}/blob/{ref}/{up.cfg.changelog_path}"
    return f"`{up.cfg.changelog_path}`"


# --------------------------------------------------------------------------- update command


@dataclass
class UpdateResult:
    old_version: str
    new_version: str
    actions: list[Action]
    upstream: Upstream | None = None
    migrations: list[tuple[str, list[str]]] = field(default_factory=list)  # (name, notes)
    pending_migrations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False
    changelog: str = ""
    summary: str = ""
    # Set (to the explaining string key) when the latest release is not newer: nothing was planned.
    no_update: str = ""

    def of(self, *kinds: str) -> list[Action]:
        return [a for a in self.actions if a.kind in kinds]

    @property
    def conflicts(self) -> list[Action]:
        return self.of(CONFLICT)

    @property
    def changed(self) -> bool:
        if self.no_update:
            return False
        return bool(self.of(ADD, UPDATE, REMOVE, CONFLICT)) or self.old_version != self.new_version

    @property
    def exit_code(self) -> int:
        if self.errors:
            return EXIT_ERROR
        return EXIT_CONFLICTS if self.conflicts else EXIT_OK


def _md_list(items: list[str], limit: int = 300) -> list[str]:
    lines = [f"- {x}" for x in items[:limit]]
    if len(items) > limit:
        lines.append(f"- … (+{len(items) - limit})")
    return lines


def render_summary(res: UpdateResult, lang: str) -> str:
    up = res.upstream
    t = lambda key, **kw: _t(lang, key, **kw)  # noqa: E731
    if res.no_update:
        title = t("sum_title_none", old=res.old_version)
    else:
        title = t("sum_title_dry" if res.dry_run else "sum_title", old=res.old_version, new=res.new_version)
    lines = [f"## {title}", ""]
    if up is not None:
        src = up.source
        ref = up.ref[len("refs/tags/"):] if up.ref.startswith("refs/tags/") else up.ref
        where = f"`{src}`" + (f" @ `{ref}`" if ref else "") + (f" (`{up.commit[:12]}`)" if up.commit else "")
        lines += [f"{t('sum_source')}{t('colon')}{where}", ""]
    if res.no_update:
        lines += [t(res.no_update, old=res.old_version, new=res.new_version), ""]
        problems = res.errors + res.warnings + (up.warnings if up else [])
        if problems:
            lines += [f"### {t('sec_warnings')}", ""] + _md_list(problems) + [""]
        return "\n".join(lines).rstrip() + "\n"
    added, updated, removed = res.of(ADD), res.of(UPDATE), res.of(REMOVE)
    lines.append(t("sum_counts", added=len(added), updated=len(updated), removed=len(removed),
                   conflicts=len(res.conflicts), kept=len(res.of(KEEP))))
    lines.append("")
    if not (added or updated or removed or res.conflicts):
        lines += [t("sum_up_to_date"), ""]

    def forced(a: Action) -> str:
        return f" — {t('conflict_forced')}" if a.forced else ""

    if res.conflicts:
        lines += [f"### {t('sec_conflicts')}{t('count', n=len(res.conflicts))}", ""]
        lines += _md_list([f"`{a.path}` — {t(a.reason, new=a.path + CONFLICT_SUFFIX)}" for a in res.conflicts])
        lines.append("")
    for key, items in (("sec_added", added), ("sec_updated", updated), ("sec_removed", removed)):
        if items:
            lines += [f"### {t(key)}{t('count', n=len(items))}", ""] + _md_list([f"`{a.path}`{forced(a)}" for a in items]) + [""]
    kept = res.of(KEEP)
    if kept:
        lines += [f"### {t('sec_kept')}{t('count', n=len(kept))}", ""]
        lines += _md_list([f"`{a.path}` — {t(a.reason)}" for a in kept]) + [""]
    released = res.of(RELEASE)
    if released:
        lines += [f"### {t('sec_released')}{t('count', n=len(released))}", ""] + _md_list([f"`{a.path}`" for a in released]) + [""]
    skipped = res.of(SKIP)
    if skipped:
        lines += [f"### {t('sec_skipped')}{t('count', n=len(skipped))}", ""] + _md_list([f"`{a.path}`" for a in skipped]) + [""]
    lines += [f"### {t('sec_migrations')}", ""]
    if res.dry_run and res.pending_migrations:
        lines += [t("migration_pending", names=", ".join(f"`{n}`" for n in res.pending_migrations)), ""]
    elif res.migrations:
        for name, notes in res.migrations:
            lines.append(f"- `{name}`")
            lines += [f"  - {n}" for n in notes] or [f"  - {t('migration_no_notes')}"]
        lines.append("")
    else:
        lines += [t("migration_none"), ""]
    problems = res.errors + res.warnings + (up.warnings if up else [])
    if problems:
        lines += [f"### {t('sec_warnings')}", ""] + _md_list(problems) + [""]
    if up is not None:
        lines += [f"### {t('sec_changelog')}", "", t("changelog_link", link=_changelog_link(up)), ""]
        if res.changelog:
            excerpt = res.changelog if len(res.changelog) < 20000 else res.changelog[:20000] + "\n…"
            lines += ["<details>", f"<summary>{up.cfg.changelog_path}</summary>", "", excerpt, "", "</details>", ""]
    steps = []
    if res.conflicts:
        steps.append(t("next_conflicts"))
    steps += [t("next_install"), t("next_verify")]
    if kept or res.conflicts:
        steps.append(t("next_feedback"))
    lines += [f"### {t('sec_next')}", ""] + [f"{k}. {s}" for k, s in enumerate(steps, 1)]
    return "\n".join(lines).rstrip() + "\n"


def update(root: Path, *, to: str | None = None, source: str | None = None, dry_run: bool = False,
           force: bool = False, layer: str | None = None, install: bool = False) -> UpdateResult:
    """Update the managed files of ``root`` to a template release (see the module docstring)."""
    validate_layer_name(layer)
    validate_claims(root)
    if install:
        if not layer or not source:
            raise TemplateError("install requires a layer name and --source")
        if (root / f"{LAYER_DIR}/{layer}.toml").exists():
            raise TemplateError(f"layer {layer} is already installed; use update --layer {layer}")
        local_cfg = TemplateConfig(name=layer, repo="", version="0.0.0", layer=layer)
    else:
        local_cfg = TemplateConfig.load(root, layer)
    base = Manifest.load(root, local_cfg.manifest_path)
    warnings: list[str] = []
    if base is None:
        warnings.append(f"no local {MANIFEST_NAME}: every managed file that differs from the template is "
                        "treated as a local change (conflict)")
    elif base.version != local_cfg.version:
        warnings.append(f"{MANIFEST_NAME} records version {base.version} but {TEMPLATE_TOML} says "
                        f"{local_cfg.version}; using the manifest as the base")
    src = source or default_source(local_cfg)
    if _is_local(src):
        src = str(Path(src).expanduser().resolve())
    with tempfile.TemporaryDirectory(prefix="tbook-template-") as tmp:
        if _is_local(src) and not _is_git_dir(Path(src)):
            if to:
                raise TemplateError(f"--to needs a git source; {src} is a plain directory")
            up = load_upstream(Path(src), source=src, ref="", commit="", layer=layer)
            latest = False  # the directory given is the target
        else:
            if install and not to:
                # A new consumer has no config yet. Read the source's default branch
                # to discover its release namespace, then install a stable release.
                discovery = Path(tmp) / "discovery"
                fetch_upstream(src, "HEAD", discovery)
                discovered = TemplateConfig.load(discovery, layer)
                local_cfg = replace(local_cfg, tag_prefix=discovered.tag_prefix)
            tags = remote_tags(src)
            ref, label = resolve_target(to, tags, local_cfg.tag_prefix, src)
            latest = not to  # the newest stable release, picked automatically
            short_sha = bool(to) and ref == to and SHORT_SHA_RE.match(ref) is not None
            if short_sha and _is_local(src):
                # git fetch needs a full object name; a local repository expands an abbreviated SHA.
                r = _git(Path(src), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
                if r.returncode == 0:
                    ref = r.stdout.decode("utf-8", "replace").strip()
            try:
                commit = fetch_upstream(src, ref, Path(tmp) / "template")
            except TemplateError as exc:
                if short_sha and not _is_local(src):
                    raise TemplateError(f"{exc}\n(an abbreviated commit SHA is expanded only in a local git "
                                        "source; pass the full 40-character SHA, a tag or a branch)") from None
                raise
            up = load_upstream(Path(tmp) / "template", source=src, ref=label, commit=commit, layer=layer)
            if label.startswith(local_cfg.tag_prefix) and parse_semver(label[len(local_cfg.tag_prefix):]):
                if label[len(local_cfg.tag_prefix):] != up.cfg.version:
                    warnings.append(f"tag {label} carries {TEMPLATE_TOML} version {up.cfg.version}")
        if local_cfg.name and up.cfg.name and local_cfg.name != up.cfg.name and not force:
            raise TemplateError(f"{src} is template {up.cfg.name!r}, but this repository uses {local_cfg.name!r} "
                                "(pass --force to switch templates)")
        validate_claims(root, up.cfg)
        old_v, new_v = local_cfg.version, up.cfg.version
        ko, kn = parse_semver(old_v), parse_semver(new_v)
        # Without --to, never go back: an older release, or the same version from another snapshot (a
        # repository created from the template's main branch between releases), would revert newer files.
        no_update = ""
        if latest and ko is not None and kn is not None:
            if kn < ko:
                no_update = "not_newer_older"
            elif kn == ko and base is not None and base.files != up.manifest.files:
                no_update = "not_newer_same"
        if no_update:
            return UpdateResult(old_version=old_v, new_version=new_v, actions=[], upstream=up,
                                warnings=warnings, dry_run=dry_run, no_update=no_update)
        if ko is not None and kn is not None and kn < ko:
            warnings.append(f"{new_v} is older than {old_v}: this is a downgrade; migrations do not run backwards")
        for entry in local_cfg.owned + local_cfg.exclude:
            if entry not in up.cfg.owned + up.cfg.exclude:
                warnings.append(f"{TEMPLATE_TOML} [managed] entry {entry!r} is not in the new template.toml; "
                                "add it back if you still need it")
        never_had = never_installed(root, base)
        if never_had:
            warnings.append(f"{len(never_had)} file(s) listed in {MANIFEST_NAME} were never in this repository "
                            "(not in its git history): installed as new files, not kept as deleted locally")
        actions = plan_update(root, local_cfg, base, up, force=force, never_had=never_had)
        res = UpdateResult(old_version=old_v, new_version=new_v, actions=actions, upstream=up,
                           warnings=warnings, dry_run=dry_run)
        changelog_file = up.dir / up.cfg.changelog_path
        if changelog_file.is_file():
            res.changelog = changelog_sections(changelog_file.read_text(encoding="utf-8", errors="replace"),
                                               old_v, new_v)
        migrations = find_migrations(up.dir / up.cfg.migrations_dir, old_v, new_v)
        res.pending_migrations = [m.name for m in migrations]
        if not dry_run:
            res.errors += apply_plan(root, up, actions)
            if not res.errors:
                _write_self(root, up)
                for mig in migrations:
                    try:
                        res.migrations.append((mig.name, run_migration(mig, root, (root if layer else up.dir) / "tools")))
                    except Exception as exc:  # noqa: BLE001 - report any migration failure with its name
                        error = str(exc) if isinstance(exc, TemplateError) else f"{type(exc).__name__}: {exc}"
                        res.errors.append(_t(_lang(root), "migration_failed", name=mig.name, error=error))
                        break
    return res


def _write_self(root: Path, up: Upstream) -> None:
    """The new template.toml (verbatim) and the manifest of the fetched tree."""
    for name in (up.cfg.config_path, up.cfg.manifest_path):
        if not _inside(root, root / name) or (root / name).is_symlink():
            raise TemplateError(f"{name}: metadata path leaves the repository or is a symlink")
    (root / up.cfg.config_path).parent.mkdir(parents=True, exist_ok=True)
    (root / up.cfg.config_path).write_bytes((up.dir / up.cfg.config_path).read_bytes())
    (root / up.cfg.manifest_path).write_text(up.manifest.to_json(), encoding="utf-8")


def cmd_update(root: Path, *, to: str | None, source: str | None, dry_run: bool, force: bool,
               out: Callable[[str], None] = print, layer: str | None = None, install: bool = False) -> int:
    lang = _lang(root)
    res = update(root, to=to, source=source, dry_run=dry_run, force=force, layer=layer, install=install)
    res.summary = render_summary(res, lang)
    out(res.summary.rstrip())
    if not dry_run:
        summary_path = f"build/template-update-{layer}.md" if layer else SUMMARY_PATH
        path = root / summary_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(res.summary, encoding="utf-8")
        out("")
        out(_t(lang, "wrote_summary", path=summary_path))
    return res.exit_code


# --------------------------------------------------------------------------- entry point


def main(args) -> int:
    """``./tbook template status|update|manifest`` (arguments parsed by tbook.cli)."""
    root = paths.ROOT
    cmd = getattr(args, "template_cmd", None)
    try:
        selected = getattr(args, "layer", None)
        layer = None if selected == "upstream" else selected
        validate_layer_name(layer)
        if cmd == "list":
            rows = targets(root)
            print(json.dumps(rows) if getattr(args, "json", False) else "\n".join(r["name"] for r in rows))
            return EXIT_OK
        if cmd == "manifest":
            return cmd_manifest(root, check=bool(getattr(args, "check", False)), layer=layer)
        if cmd in ("status", "update", "install"):
            names = [layer] if selected or cmd == "install" else [None, *[c.layer for c in layer_configs(root)]]
            if cmd == "update" and len(names) > 1 and (args.to or args.source):
                raise TemplateError("--to and --source require --layer upstream|<name> when layers are installed")
            codes = []
            for name in names:
                if cmd == "status":
                    codes.append(cmd_status(root, layer=name))
                else:
                    codes.append(cmd_update(root, to=getattr(args, "to", None), source=getattr(args, "source", None),
                                            dry_run=bool(getattr(args, "dry_run", False)),
                                            force=bool(getattr(args, "force", False)), layer=name, install=cmd == "install"))
            return EXIT_ERROR if EXIT_ERROR in codes else EXIT_CONFLICTS if EXIT_CONFLICTS in codes else EXIT_OK
    except TemplateError as exc:
        print(f"template: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"template: unknown command {cmd!r} (status, update, manifest)", file=sys.stderr)
    return EXIT_ERROR
