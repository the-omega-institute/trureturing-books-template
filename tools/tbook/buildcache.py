"""Build cache: a build unit whose inputs did not change is not built again.

A *unit* is what one build step produces: an edition's HTML, one PDF variant or the EPUB of an
edition, a book's slides, a film's videos. Its *key* is the SHA-256 of everything its outputs depend
on (:class:`Inputs`: the source files, theme and tool code, the lock file, site settings, the versions
of the tools that run), its target and its name. :func:`run` looks the key up before building:

1. the local store ``.cache/artifacts/<target>/<unit>/<key>/``. On GitHub Actions the store itself is
   saved and restored with the Actions cache, from pushes to the default branch only;
2. with ``TBOOK_CACHE_REMOTE=1``, the newest published releases of the repository: ``./tbook cache
   export`` writes one tar per unit and ``build-cache.json`` (unit, key, asset name, SHA-256, size),
   which the release of the whole site attaches;
3. on a miss it builds the unit and stores its outputs under the key.

A hit copies the stored outputs to where the build writes them (same paths, same file or directory
shape), so the rest of the build cannot tell the difference. Every stored file's SHA-256 is recorded in
``entry.json`` and checked whenever the entry is restored; a release asset is checked against
``build-cache.json`` and the digest GitHub reports, and only regular files and directories are unpacked
from it. Keys are input-addressed: two builds from the same inputs share a key even when their bytes
differ (video encoders, PDF exporters), and a changed input always gives a new key. Each unit keeps its
newest :data:`KEEP` entries; ``./tbook cache prune`` keeps only those of the current inputs.

Nothing here fails a build that would succeed without the cache: an unreadable release, a damaged
entry or a full disk is reported in one line and the unit is built (or not stored).

``TBOOK_CACHE=0`` turns the cache off (every unit is built, nothing is stored or restored).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from . import config, paths

SCHEMA = "trureturing-books.build-cache.v1"
MANIFEST = "build-cache.json"  # the release asset that lists the release's cache entries
ENTRY = "entry.json"
VERSION = "2"  # part of every key: bump it to rebuild everything once
KEEP = 2  # entries kept per unit in the local store
REMOTE_RELEASES = 5  # newest published releases with a build-cache.json searched for an entry
TARGETS = ("html", "pdf", "epub", "slides", "films")
TIMEOUT = 300  # seconds per HTTP request
MAX_JSON = 32 << 20  # bytes: a release list or build-cache.json larger than this is refused
MAX_ASSET = 8 << 30  # bytes: upper bound for an asset whose size is not declared
STALE_TMP = 3600  # seconds: prune removes temporary directories of interrupted runs older than this
OUTSIDE = "<outside>"  # label prefix of input files outside the repository root
# Directories never part of a unit's inputs when git cannot list the files (no work tree, or a directory
# git ignores as a whole, such as .cache/fonts).
SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".slidev", ".vite", "out", "frames", "tts", ".cache",
                       "build", "_site"})
_KEY_RE = re.compile(r"[0-9a-f]{64}")
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class MissingOutput(FileNotFoundError):
    """A build step finished without writing one of its unit's outputs."""


def store_root() -> Path:
    return paths.CACHE / "artifacts"


def enabled() -> bool:
    return os.environ.get("TBOOK_CACHE", "1") != "0"


def remote_enabled() -> bool:
    return enabled() and os.environ.get("TBOOK_CACHE_REMOTE") == "1"


def _say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _clear_memos() -> None:
    """Forget what this process memoized (git listings, digests, tool versions, release indexes)."""
    _DIGESTS.clear()
    _git_files.cache_clear()
    _git_ignored.cache_clear()
    tool_version.cache_clear()
    _remote_index.cache_clear()


# --------------------------------------------------------------------------- inputs and keys

_DIGESTS: dict[tuple[str, int, int, int, int], str] = {}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_digest(path: Path, *, memo: bool = True) -> str:
    """SHA-256 of a file's content. With ``memo``, remembered within the process by path, size, inode,
    mtime and ctime; verification of stored entries reads the bytes every time (``memo=False``)."""
    if not memo:
        return _sha256_file(path)
    st = Path(path).stat()
    key = (str(path), st.st_size, st.st_ino, st.st_mtime_ns, st.st_ctime_ns)
    if key not in _DIGESTS:
        _DIGESTS[key] = _sha256_file(path)
    return _DIGESTS[key]


@lru_cache(maxsize=None)
def _git_files(root: str) -> frozenset[str] | None:
    """Files git would commit under ``root`` (tracked, or untracked and not ignored), relative to ``root``
    (git prints them so, also when ``root`` is a subdirectory of the work tree); None when ``root`` is not
    in a git work tree or git cannot run."""
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return frozenset(n for n in r.stdout.decode("utf-8", "surrogateescape").split("\0") if n)


@lru_cache(maxsize=None)
def _git_ignored(root: str, rel: str) -> bool:
    """Whether git ignores ``rel`` (relative to ``root``), itself or through a parent directory."""
    try:
        r = subprocess.run(["git", "-C", root, "check-ignore", "-q", "--", rel], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _root_rel(path: Path) -> str | None:
    """``path`` relative to the repository root, as a POSIX path ('.' for the root itself): lexically
    first (a symbolic link keeps its own name), then with links resolved; None when it is outside."""
    try:
        rel = Path(os.path.abspath(path)).relative_to(os.path.abspath(paths.ROOT))
    except ValueError:
        try:
            rel = Path(path).resolve().relative_to(paths.ROOT.resolve())
        except (ValueError, OSError):
            return None
    return rel.as_posix()


def _item_label(item: Path) -> str:
    rel = _root_rel(item)
    return rel if rel is not None else f"{OUTSIDE}/{Path(item).name}"


def _walk(item: Path, label: str) -> list[tuple[Path, str]]:
    """Every file under the directory ``item`` outside :data:`SKIP_DIRS`, labelled ``label/<relative path>``."""
    out = []
    for dirpath, dirnames, filenames in os.walk(item):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            f = Path(dirpath) / name
            if name.endswith(".pyc") or name == ".DS_Store" or not f.is_file():
                continue
            sub = f.relative_to(item).as_posix()
            out.append((f, sub if label == "." else f"{label}/{sub}"))
    return out


def _files_under(item: Path) -> list[tuple[Path, str]]:
    """The input files of ``item`` (a file or a directory) with their labels, sorted.

    A file counts as itself. In a directory of the repository's git work tree, the files git would commit
    (so build outputs and ignored files never count); a directory git ignores as a whole (``.cache/fonts``)
    or one outside the repository counts with every file in it. Labels are repository-relative paths; a
    file outside the repository is labelled ``<outside>/<item name>/<path in item>``, so the key does not
    depend on where that directory lives."""
    item = Path(item)
    rel = _root_rel(item)
    label = rel if rel is not None else f"{OUTSIDE}/{item.name}"
    if item.is_file():
        return [(item, label)]
    if not item.is_dir():
        return []
    if rel is not None:
        root = str(paths.ROOT)
        listed = _git_files(root)
        try:
            real = item.resolve().relative_to(paths.ROOT.resolve()).as_posix()
        except (ValueError, OSError):
            real = None  # a link out of the work tree: walk it
        if listed is not None and real is not None:
            head = "" if real == "." else real + "/"
            names = sorted(n for n in listed if n.startswith(head))
            if names or not _git_ignored(root, real):
                return [(paths.ROOT / n, n) for n in names if (paths.ROOT / n).is_file()]
    return sorted(_walk(item, label), key=lambda fl: fl[1])


@dataclass
class Inputs:
    """What a unit's outputs depend on, as (label, digest) pairs; :meth:`key` hashes them in order."""

    parts: list[tuple[str, str]] = field(default_factory=list)

    def files(self, *items: Path, exclude: Iterable[str] = ()) -> "Inputs":
        """Every file of each of ``items`` (files or directories; see :func:`_files_under`), by label and
        content; an item without files counts as missing. ``exclude``: label fragments (``/out/``) to
        leave out, matched against ``/`` + the label."""
        skip = tuple(exclude)
        for item in items:
            found = [(f, label) for f, label in _files_under(Path(item))
                     if not any(s in "/" + label for s in skip)]
            if not found:
                self.parts.append((_item_label(Path(item)), "missing"))
            for f, label in found:
                self.parts.append((label, file_digest(f)))
        return self

    def text(self, label: str, value: Any) -> "Inputs":
        data = json.dumps(value, sort_keys=True, ensure_ascii=False)  # typed: 1 and "1" differ
        self.parts.append((f"<{label}>", hashlib.sha256(data.encode("utf-8", "surrogateescape")).hexdigest()))
        return self

    def add(self, other: "Inputs") -> "Inputs":
        """Append ``other``'s parts."""
        self.parts += other.parts
        return self

    def key(self) -> str:
        h = hashlib.sha256(f"{SCHEMA}\n{VERSION}\n".encode())
        for label, digest in self.parts:
            h.update(json.dumps([label, digest]).encode() + b"\n")  # unambiguous for any file name
        return h.hexdigest()


@lru_cache(maxsize=None)
def tool_version(*cmd: str) -> str:
    """First line of ``cmd --version`` (or of ``cmd`` when it already has arguments); 'missing' if it
    cannot run."""
    if not cmd or not cmd[0]:
        return "missing"
    args = list(cmd) if len(cmd) > 1 else [cmd[0], "--version"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "missing"
    text = (r.stdout or r.stderr).strip()
    return text.splitlines()[0] if text else f"exit {r.returncode}"


def package_version(name: str) -> str:
    """Installed version of the Python package ``name``; 'missing' when it is not installed."""
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "missing"


def series(version: str, parts: int = 2) -> str:
    """The release series of a version line: its first version number cut to ``parts`` components
    ("v22.23.4" → "22" with parts=1, "pandoc 3.1.11" → "3.1"); the text itself when it has no number.

    Keys hold a tool's series, not its exact build. The versions that decide an output are pinned in files
    every key already covers (requirements.txt: Pandoc and Typst; package-lock.json: Playwright and its
    Chromium, the fonts; theme/film/requirements.txt), so the series only tells apart a machine whose tool
    behaves differently. (mdBook, installed at one exact version everywhere, counts by its exact version.) The exact build would key the runner image: a new
    Node patch or an Ubuntu ffmpeg revision would make every entry, and every published release, useless.
    """
    m = re.search(r"\d+(?:\.\d+)*", version)
    return ".".join(m.group(0).split(".")[:parts]) if m else version


def node_version() -> str:
    """Node's major version (``series``)."""
    return series(tool_version(os.environ.get("NODE") or shutil.which("node") or ""), 1)


def _python() -> str:
    return ".".join(platform.python_version_tuple()[:2])


def site_inputs(site: config.Site) -> Inputs:
    """What every HTML, PDF and EPUB unit depends on: the tool and theme code (not the film pipeline in
    theme/film/, which only films use), site settings, the lock file, the pinned packages, the site's
    address (links and paths are built from it)."""
    return (Inputs()
            .files(paths.TOOLS / "tbook", paths.TOOLS / "filters", paths.TOOLS / "node", paths.THEME,
                   paths.I18N_LOCAL, paths.SITE_TOML, paths.LOCK_FILE, paths.ROOT / "requirements.txt",
                   paths.ROOT / "package-lock.json", exclude=("/theme/film/",))
            .text("base_url", site.base_url or "")
            .text("repo", site.repo or "")
            .text("python", _python()))


# --------------------------------------------------------------------------- units


@dataclass
class Unit:
    target: str  # one of TARGETS
    name: str  # "<slug>/<lang>", "<slug>/<lang>/<variant>", "<slug>", "<slug>/<film id>"
    inputs: Inputs
    outputs: list[Path]  # the files and directories the build writes, under the repository root

    @property
    def key(self) -> str:
        """The inputs' key, specific to this unit (its target and name: language, PDF variant, film)."""
        return hashlib.sha256(f"{self.inputs.key()}\n{self.target}\n{self.name}".encode()).hexdigest()

    @property
    def label(self) -> str:
        return f"{self.target} {self.name}"

    def entry_dir(self, key: str | None = None) -> Path:
        parts = [self.target, *self.name.split("/")]
        if any(p in ("", ".", "..") or "\\" in p for p in parts):
            raise ValueError(f"build cache: unsafe unit name {self.label!r}")
        return store_root().joinpath(*parts, key or self.key)


def html_unit(site: config.Site, book: config.Book, lang: str, out_dir: Path) -> Unit:
    from . import doctor

    inputs = site_inputs(site).files(book.dir).text("mdbook", tool_version(doctor.mdbook_path() or ""))
    return Unit("html", f"{book.slug}/{lang}", inputs.text("node", node_version()), [Path(out_dir)])


def _fonts() -> Inputs:
    """The fonts Typst (PDF, covers) and the EPUB use: .cache/fonts (tools/fetch-fonts.sh) and the families
    Typst finds there, in theme/typst/fonts and on the system. .cache/fonts-fontsource is not an input: the
    build derives it from node_modules/@fontsource (package-lock.json) when a family is missing."""
    from . import pandoc

    dirs = [d for d in (pandoc.FONT_CACHE, pandoc.THEME_FONTS) if d.is_dir()]
    try:
        families = sorted(pandoc._families(dirs))
    except Exception:  # noqa: BLE001 - no typst: the build fails on its own
        families = []
    return Inputs().files(pandoc.FONT_CACHE).text("font families", families)


def _pandoc_version() -> str:
    from . import pandoc

    try:
        return series(tool_version(pandoc.pandoc_path()))
    except Exception:  # noqa: BLE001 - no pandoc: the build fails on its own
        return "missing"


def _dated(inputs: Inputs) -> Inputs:
    """PDF and EPUB metadata dates come from $SOURCE_DATE_EPOCH when it is set."""
    return inputs.text("SOURCE_DATE_EPOCH", os.environ.get("SOURCE_DATE_EPOCH", ""))


def pdf_unit(site: config.Site, book: config.Book, lang: str, variant: str, out_file: Path) -> Unit:
    inputs = site_inputs(site).files(book.dir).add(_fonts())
    inputs.text("pandoc", _pandoc_version()).text("typst", series(package_version("typst"))).text("node", node_version())
    return Unit("pdf", f"{book.slug}/{lang}/{variant}", _dated(inputs), [Path(out_file)])


def _epubcheck_mode() -> str:
    """$TBOOK_EPUBCHECK as the build reads it: an EPUB stored without the check is not restored into a
    build that checks."""
    mode = os.environ.get("TBOOK_EPUBCHECK", "1").lower()
    if mode in ("0", "false", "no", "off"):
        return "off"
    # the check cannot run here (pandoc.check_epub skips it): the EPUB is stored as unchecked
    if not shutil.which("java"):
        return "skipped (no java)"
    try:
        import importlib.util

        if importlib.util.find_spec("epubcheck") is None:
            return "skipped (no epubcheck)"
    except (ImportError, ValueError):
        return "skipped (no epubcheck)"
    return mode


def epub_unit(site: config.Site, book: config.Book, lang: str, out_file: Path) -> Unit:
    inputs = site_inputs(site).files(book.dir).add(_fonts())
    inputs.text("pandoc", _pandoc_version()).text("typst", series(package_version("typst"))).text("node", node_version())
    inputs.text("epubcheck", _epubcheck_mode())
    return Unit("epub", f"{book.slug}/{lang}", _dated(inputs), [Path(out_file)])


def slides_unit(site: config.Site, book: config.Book, out_dir: Path) -> Unit:
    """A book's decks (HTML of every language and the PDFs, build/slides/<slug>/): the decks and the book's
    metadata, the slide theme and tools, the lock (cited GIDs), package-lock.json (Slidev, Playwright and its
    Chromium), the site's base path, Node's major version, and whether PDFs are exported and the decks
    checked in a browser (decks stored unchecked are not restored into a build that checks)."""
    from . import academic, slides

    inputs = (Inputs()
              .files(book.dir / "book.toml", book.slides_dir, book.dir / "assets", paths.THEME / "slides",
                     paths.GENERATED, paths.I18N_THEME, paths.I18N_LOCAL, paths.TOOLS / "node",
                     paths.TOOLS / "tbook" / "slides.py", paths.LOCK_FILE, paths.SITE_TOML,
                     paths.ROOT / "package-lock.json")
              .text("base", slides.base_path(site))
              .text("base_url", site.base_url or "")
              .text("no_pdf", os.environ.get("TBOOK_SLIDES_NO_PDF") == "1")
              .text("no_check", os.environ.get("TBOOK_SLIDES_NO_CHECK") == "1")
              .text("node", node_version()))
    academic_decks = [d for d in slides.deck_names(book) if academic.is_academic(book.slides_dir / d)]
    if academic_decks:
        inputs.files(book.dir, paths.THEME / "beamer", paths.TOOLS / "tbook",
                     paths.TOKENS, paths.ROOT / "requirements.txt", paths.TOOLS / "install-tectonic.sh",
                     paths.THEME / "typst" / "fonts").add(_fonts())
        inputs.text("tectonic", academic.ENGINE_VERSION).text("bundle", academic.BUNDLE)
        inputs.text("epoch", os.environ.get("SOURCE_DATE_EPOCH", academic.EPOCH))
        inputs.text("typst", package_version("typst"))
        for deck in academic_decks:
            data = academic.settings(book, deck)
            for key in ("theme_dir", "institution_graphic"):
                if data.get(key):
                    inputs.files((book.slides_dir / deck / data[key]).resolve())
    return Unit("slides", book.slug, inputs, [Path(out_dir)])


def units(site: config.Site, books: Iterable[config.Book]) -> list[Unit]:
    """Every unit of ``books`` that ``./tbook build all`` builds, with its current key."""
    from . import build, film, slides

    out: list[Unit] = []
    for book in books:
        for ed in book.editions:
            if book.outputs_html:
                out.append(html_unit(site, book, ed.lang, build.html_dir(book.slug, ed.lang)))
            for variant in book.outputs_pdf:
                out.append(pdf_unit(site, book, ed.lang, variant,
                                    build.dist_dir(book.slug) / book.artifact(ed.lang, "pdf", variant)))
            if book.outputs_epub:
                out.append(epub_unit(site, book, ed.lang, build.dist_dir(book.slug) / book.artifact(ed.lang, "epub")))
        if slides.deck_names(book):
            out.append(slides_unit(site, book, build.slides_dir(book.slug)))
        out += getattr(film, "units", lambda s, b: [])(site, book)
    return out


# --------------------------------------------------------------------------- local store


def _out_path(path: Path) -> str:
    """How an output path is recorded: repository-relative, or absolute when it is outside."""
    rel = _root_rel(path)
    return rel if rel is not None else Path(os.path.abspath(path)).as_posix()


def _remove(path: Path) -> None:
    """Remove a file, link or directory tree; nothing when it does not exist."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _scan(root: Path) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    """Everything under ``root``, read now: ({relative path: {sha256, size}} of the regular files, the
    relative paths of the directories, the relative paths of anything else: links, devices)."""
    files: dict[str, dict[str, Any]] = {}
    dirs: list[str] = []
    odd: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for name in sorted(dirnames):
            rel = (d / name).relative_to(root).as_posix()
            if (d / name).is_symlink():
                odd.append(rel)
                dirnames.remove(name)
            else:
                dirs.append(rel)
        dirnames.sort()
        for name in sorted(filenames):
            f = d / name
            rel = f.relative_to(root).as_posix()
            st = f.lstat()
            if not stat.S_ISREG(st.st_mode):
                odd.append(rel)
                continue
            files[rel] = {"sha256": file_digest(f, memo=False), "size": st.st_size}
    return files, sorted(dirs), odd


def read_entry(entry: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((entry / ENTRY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    if (not isinstance(data.get("outputs"), list) or not isinstance(data.get("files"), dict)
            or not isinstance(data.get("dirs"), list)):
        return None
    if not all(isinstance(data.get(k), str) for k in ("target", "unit", "key")):
        return None
    return data


def verify(entry: Path) -> str:
    """'' when ``entry`` holds exactly the outputs, directories and files its entry.json lists (each output
    a file or a directory as recorded, each file with its digest, nothing else, no links); else why not."""
    data = read_entry(entry)
    if data is None:
        return "no valid entry.json"
    files = entry / "files"
    for i, out in enumerate(data["outputs"]):
        p = files / str(i)
        kind = out.get("kind") if isinstance(out, dict) else None
        if kind not in ("file", "dir") or p.is_symlink() or not (p.is_dir() if kind == "dir" else p.is_file()):
            return f"output {i} is not the stored {kind or 'output'}"
    have, dirs, odd = _scan(files) if files.is_dir() else ({}, [], [])
    if odd:
        return f"{odd[0]} is not a regular file"
    want = data["files"]
    tops = {p.split("/")[0] for p in [*have, *dirs]}
    if (set(have) != set(want) or dirs != sorted(map(str, data["dirs"]))
            or tops != {str(i) for i in range(len(data["outputs"]))}):
        return "the stored files are not the listed ones"
    for name, info in want.items():
        if not isinstance(info, dict) or have[name]["sha256"] != info.get("sha256"):
            return f"{name} does not match its digest"
    return ""


def _touch(entry: Path) -> None:
    try:
        os.utime(entry)
    except OSError:
        pass


def _publish(tmp: Path, final: Path) -> None:
    """Move the complete entry ``tmp`` to ``final`` with a rename (never a half-written entry). An entry
    already at ``final`` that verifies is kept (another process stored the same key: the same inputs); a
    damaged one is replaced."""
    if final.exists():
        if not verify(final):
            return
        aside = final.parent / f".old-{uuid.uuid4().hex}"
        try:
            final.rename(aside)
        except FileNotFoundError:
            pass
        else:
            shutil.rmtree(aside, ignore_errors=True)
    try:
        tmp.rename(final)
    except OSError:
        if final.is_dir() and not verify(final):
            return  # a concurrent process stored the same entry first
        raise


def store(unit: Unit, key: str | None = None) -> Path:
    """Copy ``unit``'s outputs into the store under ``key`` (default: its current key) and drop all but its
    newest :data:`KEEP` entries. Returns the entry directory. A missing output is a :class:`MissingOutput`."""
    key = key or unit.key
    final = unit.entry_dir(key)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
    try:
        outputs = []
        for i, out in enumerate(unit.outputs):
            out = Path(out)
            if not out.exists():
                raise MissingOutput(f"{unit.label}: the build did not write {paths.rel(out)}")
            dst = tmp / "files" / str(i)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if out.is_dir():  # links are followed: the store holds plain files
                shutil.copytree(out, dst)
            else:
                shutil.copy2(out, dst)
            outputs.append({"path": _out_path(out), "kind": "dir" if out.is_dir() else "file"})
        (tmp / "files").mkdir(exist_ok=True)
        listed, dirs, _ = _scan(tmp / "files")
        (tmp / ENTRY).write_text(json.dumps({
            "schema": SCHEMA, "target": unit.target, "unit": unit.name, "key": key, "created": int(time.time()),
            "outputs": outputs, "files": listed, "dirs": dirs, "inputs": [list(p) for p in unit.inputs.parts],
        }, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")  # a non-UTF-8 file name is escaped
        _publish(tmp, final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _touch(final)
    _keep_newest(final.parent, KEEP)
    return final


def _key_dirs(unit_dir: Path) -> list[Path]:
    try:
        return [d for d in unit_dir.iterdir() if d.is_dir() and _KEY_RE.fullmatch(d.name)]
    except OSError:
        return []


def _keep_newest(unit_dir: Path, keep: int) -> None:
    """Remove all but the ``keep`` most recently stored or restored entries of one unit."""
    def mtime(d: Path) -> float:
        try:
            return d.stat().st_mtime
        except OSError:
            return 0.0

    for old in sorted(_key_dirs(unit_dir), key=mtime, reverse=True)[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def _place(src: Path, dst: Path) -> None:
    """Copy ``src`` (file or directory) to ``dst``, replacing whatever is there (a file, a directory, a
    link): copied next to it first, then renamed, so an interrupted restore leaves no half-copied output."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.restore-{uuid.uuid4().hex[:12]}"
    try:
        if src.is_dir():
            shutil.copytree(src, tmp)
        else:
            shutil.copy2(src, tmp)
        _remove(dst)
        os.rename(tmp, dst)
    finally:
        if tmp.exists() or tmp.is_symlink():
            _remove(tmp)


def restore_local(unit: Unit, key: str | None = None) -> bool:
    """Copy the stored outputs of ``unit`` (``key``: default its current key) to their places; False when
    the store has no valid entry (a damaged one is removed) or the copy fails."""
    key = key or unit.key
    entry = unit.entry_dir(key)
    try:
        if not entry.is_dir():
            return False
        data = read_entry(entry)
        if data is None:
            why = "no valid entry.json"
        elif (data["target"], data["unit"], data["key"]) != (unit.target, unit.name, key):
            why = "it belongs to another unit"
        elif [o.get("path") if isinstance(o, dict) else None for o in data["outputs"]] != [
                _out_path(Path(o)) for o in unit.outputs]:
            why = "it was stored for other output paths"
        else:
            why = verify(entry)
    except OSError as exc:  # unreadable, or removed meanwhile: a miss, but nothing proves it damaged
        _say(f"cache: cannot read the stored {unit.label} ({exc}); building it")
        return False
    if why:
        _say(f"cache: dropping the stored {unit.label} ({why})")
        shutil.rmtree(entry, ignore_errors=True)
        return False
    try:
        for i, out in enumerate(unit.outputs):
            _place(entry / "files" / str(i), Path(out))
    except OSError as exc:
        _say(f"cache: cannot restore {unit.label} ({exc}); building it")
        return False
    _touch(entry)
    return True


# --------------------------------------------------------------------------- releases (remote)


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _api() -> str:
    """The GitHub API (``$GITHUB_API_URL`` on Actions, also for GitHub Enterprise Server)."""
    return (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Drop the token when a redirect leaves the host: GitHub sends asset downloads to signed storage URLs,
    which refuse a second credential (and must not see the token)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


def _open(url: str, *, accept: str, api: bool):
    headers = {"Accept": accept, "User-Agent": "tbook-build-cache"}
    if api and _token():
        headers["Authorization"] = f"Bearer {_token()}"
    opener = urllib.request.build_opener(_NoAuthOnRedirect())
    return opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT)


def _http(url: str, *, accept: str = "application/vnd.github+json", api: bool = True) -> bytes:
    """The body of a small response (a release list, build-cache.json)."""
    with _open(url, accept=accept, api=api) as resp:
        data = resp.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise ValueError(f"the answer is larger than {MAX_JSON} bytes")
    return data


def _asset_url(asset: dict[str, Any]) -> tuple[str, bool]:
    """(URL, whether it takes the token): the API URL with a token (private repositories), else the public
    download URL."""
    if _token() and asset.get("url"):
        return str(asset["url"]), True
    return str(asset.get("browser_download_url") or ""), False


def _asset_bytes(repo: str, asset: dict[str, Any]) -> bytes:
    """A small asset's bytes (build-cache.json)."""
    url, api = _asset_url(asset)
    return _http(url, accept="application/octet-stream", api=api)


def _download(repo: str, asset: dict[str, Any], dest: Path, limit: int) -> str:
    """Write an asset to ``dest`` (at most ``limit`` bytes); returns its SHA-256."""
    url, api = _asset_url(asset)
    h = hashlib.sha256()
    size = 0
    with _open(url, accept="application/octet-stream", api=api) as resp, dest.open("wb") as fh:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            size += len(chunk)
            if size > limit:
                raise ValueError(f"it is larger than the {limit} bytes declared")
            h.update(chunk)
            fh.write(chunk)
    return h.hexdigest()


def _why(exc: BaseException) -> str:
    """One line for a failed request."""
    if isinstance(exc, urllib.error.HTTPError):
        hint = "" if _token() else "; set GITHUB_TOKEN"
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            return f"HTTP {exc.code}: API rate limit reached{hint}"
        if exc.code == 404:
            return f"HTTP 404: not found, or no access{hint}"
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return str(exc.reason)
    return str(exc) or type(exc).__name__


Found = tuple[str, dict[str, Any], dict[str, Any]]  # (release tag, manifest entry, asset)


@lru_cache(maxsize=8)
def _remote_index(repo: str) -> dict[tuple[str, str, str], Found]:
    """(target, unit, key) → (release tag, manifest entry, asset) over the newest ``REMOTE_RELEASES``
    published releases that carry a ``build-cache.json`` (drafts and releases without one, such as a
    release made by hand, are skipped and do not count). Read once per process; a failure is reported once
    and gives an empty index."""
    index: dict[tuple[str, str, str], Found] = {}
    if not _REPO_RE.fullmatch(repo or ""):
        return index
    try:
        releases = json.loads(_http(f"{_api()}/repos/{repo}/releases?per_page=100"))
        if not isinstance(releases, list):
            raise ValueError("unexpected answer")
    except Exception as exc:  # noqa: BLE001 - the build goes on without the releases
        _say(f"cache: cannot list the releases of {repo} ({_why(exc)}); building what is not stored")
        return index
    with_cache = []
    for rel in releases:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        listed = rel.get("assets")
        assets = {a["name"]: a for a in (listed if isinstance(listed, list) else [])
                  if isinstance(a, dict) and isinstance(a.get("name"), str)}
        if isinstance(assets.get(MANIFEST), dict):
            with_cache.append((rel, assets))
    if not with_cache:
        _say(f"cache: no published release of {repo} carries {MANIFEST}; building what is not stored")
    for rel, assets in with_cache[:REMOTE_RELEASES]:
        tag = str(rel.get("tag_name") or "")
        manifest_asset = assets[MANIFEST]
        try:
            manifest = json.loads(_asset_bytes(repo, manifest_asset))
        except Exception as exc:  # noqa: BLE001
            _say(f"cache: cannot read {MANIFEST} of release {tag} ({_why(exc)})")
            continue
        if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
            continue
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            _say(f"cache: {MANIFEST} of release {tag} has no list of entries; skipping it")
            continue
        for e in entries:  # a malformed entry is skipped; the others, and other releases, still count
            if not isinstance(e, dict) or not isinstance(e.get("asset"), str):
                continue
            k = (e.get("target"), e.get("unit"), e.get("key"))
            asset = assets.get(e["asset"])
            if asset and all(isinstance(x, str) for x in k) and k not in index:
                index[k] = (tag, e, asset)  # type: ignore[index]
    return index


def _safe_extract(tar_path: Path, dest: Path) -> None:
    """Unpack an entry tar into the new directory ``dest``: only ``entry.json`` and regular files and
    directories under ``files/``, no links, devices, sparse or duplicate members, no more bytes than the
    tar holds. Written member by member (no tarfile extraction filter: the same on every Python >= 3.11)."""
    dest.mkdir()
    limit = tar_path.stat().st_size
    with tarfile.open(tar_path, mode="r:") as tar:
        members = tar.getmembers()
        seen: set[str] = set()
        total = 0
        for m in members:
            parts = m.name.split("/")
            if (not m.name or "\\" in m.name or any(p in ("", ".", "..") for p in parts) or m.name in seen
                    or not (m.isdir() or (m.isreg() and not m.issparse()))
                    or not (m.name == ENTRY and m.isreg() or parts[0] == "files")):
                raise ValueError(f"unsafe member {m.name!r}")
            seen.add(m.name)
            total += m.size if m.isreg() else 0
            if total > limit:
                raise ValueError("members larger than the archive")
        for m in members:
            target = dest.joinpath(*m.name.split("/"))
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                raise ValueError(f"unreadable member {m.name!r}")
            with src, target.open("xb") as fh:
                shutil.copyfileobj(src, fh)


def restore_remote(unit: Unit, repo: str) -> bool:
    """Fetch ``unit``'s entry for its current key from a release into the store and restore it. False (with
    one line saying why, when there was something to fetch) on any failure."""
    key = unit.key
    found = _remote_index(repo).get((unit.target, unit.name, key)) if repo else None
    if not found:
        return False
    tag, info, asset = found
    name = asset.get("name")
    declared = [n for n in (info.get("size"), asset.get("size")) if isinstance(n, int) and n >= 0]
    limit = min(declared) if declared else MAX_ASSET
    final = unit.entry_dir(key)
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
    except OSError as exc:
        _say(f"cache: cannot restore {unit.label} from release {tag} ({exc}); building it")
        return False
    try:
        tar_path = work / "entry.tar"
        digest = _download(repo, asset, tar_path, limit)
        reported = str(asset.get("digest") or "")
        if digest != info.get("sha256") or (reported.startswith("sha256:") and reported[7:] != digest):
            _say(f"cache: {name} of release {tag} does not match its digest; building {unit.label}")
            return False
        tmp = work / "entry"
        _safe_extract(tar_path, tmp)
        meta = read_entry(tmp) or {}
        why = verify(tmp)
        if not why and (meta.get("target"), meta.get("unit"), meta.get("key")) != (unit.target, unit.name, key):
            why = "another unit"
        if why:
            _say(f"cache: {name} of release {tag} is not the entry it claims ({why}); building {unit.label}")
            return False
        _publish(tmp, final)
    except Exception as exc:  # noqa: BLE001 - never fail a build because a release is unreachable
        _say(f"cache: cannot restore {unit.label} from release {tag} ({_why(exc)}); building it")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not restore_local(unit, key):
        return False
    _say(f"cache: {unit.label} restored from release {tag} ({key[:12]})")
    return True


# --------------------------------------------------------------------------- the build step


def run(unit: Unit, build: Callable[[], Any] | None, *, repo: str | None = None) -> str:
    """Build ``unit`` with ``build()`` unless its key is cached. Returns 'cached' (local store), 'release'
    (restored from a release) or 'built'. With ``build`` None the unit is only restored: 'missing' when it
    is not cached. Errors of ``build()`` propagate (nothing is stored); a store that fails for lack of
    space or permissions is reported and the build counts as done."""
    if not enabled():
        if build is None:
            return "missing"
        build()
        return "built"
    key = unit.key
    if restore_local(unit, key):
        _say(f"cache: {unit.label} is up to date ({key[:12]})")
        return "cached"
    if remote_enabled():
        if repo is None:
            try:
                repo = config.load_site().repo
            except Exception:  # noqa: BLE001
                repo = None
        try:
            if repo and restore_remote(unit, repo):
                return "release"
        except Exception as exc:  # noqa: BLE001 - never fail a build because a release is unreachable
            _say(f"cache: cannot restore {unit.label} from a release ({_why(exc)}); building it")
    if build is None:
        return "missing"
    build()
    try:
        store(unit, key)
    except MissingOutput:
        raise
    except (OSError, ValueError) as exc:  # ValueError: a name or value the entry cannot record
        _say(f"cache: cannot store {unit.label} ({exc}); it was built but is not cached")
    return "built"


# --------------------------------------------------------------------------- whole store


def _walk_store() -> Iterator[tuple[str, Path]]:
    """('entry', key directory) for every key directory in the store, ('tmp', directory) for temporary
    directories (``.tmp-*``, ``.old-*``) and ('dir', directory) for the directories that hold them, deepest
    first; nothing below an entry is searched (its files are a unit's outputs)."""
    root = store_root()
    if not root.is_dir():
        return
    holders: list[Path] = []
    for dirpath, dirnames, _ in os.walk(root):
        d = Path(dirpath)
        if d != root and _KEY_RE.fullmatch(d.name):
            dirnames[:] = []
            yield "entry", d
            continue
        for name in sorted(dirnames):
            if name.startswith("."):
                dirnames.remove(name)
                if name.startswith((".tmp-", ".old-")):
                    yield "tmp", d / name
        dirnames.sort()
        if d != root:
            holders.append(d)
    for d in sorted(holders, key=lambda p: len(p.parts), reverse=True):
        yield "dir", d


def _entries() -> Iterator[tuple[Path, dict[str, Any] | None]]:
    """(entry directory, its entry.json or None when damaged or not where its unit and key put it)."""
    root = store_root()
    for kind, d in _walk_store():
        if kind != "entry":
            continue
        data = read_entry(d)
        parts = d.relative_to(root).parts
        if data and (data["target"], data["unit"], data["key"]) != (parts[0], "/".join(parts[1:-1]), parts[-1]):
            data = None
        yield d, data


def stored() -> list[tuple[str, str, str, Path]]:
    """(target, unit, key, entry dir) of every entry in the local store."""
    return sorted((data["target"], data["unit"], data["key"], entry) for entry, data in _entries() if data)


def prune(current: Iterable[Unit]) -> list[Path]:
    """Remove every stored entry that is not the current key of one of ``current``, damaged entries,
    temporary directories of interrupted runs (older than :data:`STALE_TMP`) and directories left empty.
    Returns the entries it removed."""
    keep = {(u.target, u.name, u.key) for u in current}
    removed = []
    for entry, data in list(_entries()):
        if not data or (data["target"], data["unit"], data["key"]) not in keep:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
    now = time.time()
    for kind, d in list(_walk_store()):
        try:
            if kind == "tmp" and now - d.stat().st_mtime > STALE_TMP:
                shutil.rmtree(d, ignore_errors=True)
            elif kind == "dir":
                d.rmdir()  # only when empty
        except OSError:
            pass
    return removed


def actions_key(prefix: str = "build-cache-v1") -> str:
    """The Actions cache key of the store's content: the same entries give the same key, so an unchanged
    store is not saved again."""
    h = hashlib.sha256()
    for target, name, key, _ in stored():
        h.update(f"{target}\t{name}\t{key}\n".encode())
    return f"{prefix}-{h.hexdigest()}"


def asset_name(target: str, unit: str, key: str) -> str:
    return f"cache-{target}-{re.sub(r'[^A-Za-z0-9._-]+', '-', unit)}-{key[:16]}.tar"


def _write_tar(entry: Path, out: Path) -> None:
    """``entry`` as an uncompressed tar: sorted, directories before their contents, regular files only,
    no owners, times or permissions beyond 0644/0755, so the same entry gives the same bytes."""
    with tarfile.open(out, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for dirpath, dirnames, filenames in os.walk(entry):
            dirnames.sort()
            d = Path(dirpath)
            rel = d.relative_to(entry).as_posix()
            if rel != ".":
                info = tarfile.TarInfo(rel)
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            for name in sorted(filenames):
                f = d / name
                info = tarfile.TarInfo(f.relative_to(entry).as_posix())
                info.size, info.mode = f.stat().st_size, 0o644
                with f.open("rb") as fh:
                    tar.addfile(info, fh)


def export(dest: Path, current: Iterable[Unit], *, repo: str = "") -> Path:
    """Write one tar per current unit found in the store, and :data:`MANIFEST` listing them, into ``dest``
    (for the release of the whole site to attach). Units not in the store are left out (and named on
    stdout)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    entries = []
    for unit in current:
        key = unit.key
        entry = unit.entry_dir(key)
        why = verify(entry) if entry.is_dir() else "not stored"
        if why:
            print(f"cache export: {unit.label} is not in the store ({why}); build it first", flush=True)
            continue
        name = asset_name(unit.target, unit.name, key)
        tmp = dest / f".{name}.tmp"
        _write_tar(entry, tmp)
        os.replace(tmp, dest / name)
        entries.append({"target": unit.target, "unit": unit.name, "key": key, "asset": name,
                        "sha256": _sha256_file(dest / name), "size": (dest / name).stat().st_size})
    manifest = dest / MANIFEST
    manifest.write_text(json.dumps({"schema": SCHEMA, "repo": repo, "generated": int(time.time()),
                                    "entries": entries}, indent=1) + "\n", encoding="utf-8")
    return manifest
