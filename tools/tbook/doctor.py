"""``./tbook doctor``: check the local toolchain, say what each build target can do, and how to fix gaps.

Every check prints one line — ``✓`` found, ``✗`` missing and required, ``!`` missing but
optional — with a fix hint. Each check lists the targets that need it; a check is *required*
when one of the core targets needs it:

=============  ===========================================================================
check          Python ≥ 3.11, trureturing.lock.json, trureturing access (checkout or network),
               the pinned commit on the site.toml trureturing branch
html           mdBook 0.5.x, Node ≥ 22.12, KaTeX in node_modules
pdf            pypandoc (Pandoc 3.9), typst; fonts are optional (Typst falls back)
epub           pypandoc; epubcheck + Java are optional (validation is skipped without them)
site           whatever html/pdf/epub need (it assembles their outputs)
=============  ===========================================================================

Optional targets — ``slides`` (Slidev + Chromium), ``viz`` (Chromium for tests/thumbnails),
``films`` (Chromium + ffmpeg), ``lean-verify`` (elan/lake) — are reported but never fail the
command. Exit status: 1 if a required check fails, else 0.

Nothing here installs anything. Network access is one HEAD request with a short timeout, made
only when no local trureturing checkout is available, and, when neither the cache nor a checkout
can tell, two GitHub API requests asking whether the pinned commit is on the site.toml branch: the
branch's head, then a comparison with it (when the branch is not found, one asking whether the
repository is readable instead). The only file written is the one ``./tbook check`` writes for that
question: a positive answer cached under ``.cache/trureturing/<commit>/``.
"""

from __future__ import annotations

import glob
import importlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

CORE_TARGETS = ("check", "html", "pdf", "epub", "site")
OPTIONAL_TARGETS = ("slides", "viz", "films", "lean-verify")
MDBOOK_EXPECTED = (0, 5, 4)
NODE_MIN = (22, 12)
PY_MIN = (3, 11)
NODE_PACKAGES = (
    ("katex", ("html",)),
    ("@slidev/cli", ("slides",)),
    ("playwright-chromium", ("slides", "viz", "films")),
)
FONTS = (
    # (family names accepted, label, fix hint)
    (("Noto Sans CJK SC", "Noto Sans SC", "Noto Serif CJK SC", "Noto Serif SC"), "Noto CJK SC",
     "sudo apt-get install fonts-noto-cjk  (or ./tools/fetch-fonts.sh)"),
    (("Chakra Petch",), "Chakra Petch", "./tools/fetch-fonts.sh"),
    (("JetBrains Mono",), "JetBrains Mono", "sudo apt-get install fonts-jetbrains-mono  (or ./tools/fetch-fonts.sh)"),
)
NET_TIMEOUT = 4.0


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""
    hint: str = ""
    targets: tuple[str, ...] = ()
    required: bool | None = None  # None: derived from targets

    @property
    def is_required(self) -> bool:
        if self.required is not None:
            return self.required
        return any(t in CORE_TARGETS for t in self.targets)

    @property
    def mark(self) -> str:
        return "✓" if self.ok else ("✗" if self.is_required else "!")


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    def blocking(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.is_required]

    def target_gaps(self) -> dict[str, list[str]]:
        """target → labels of the failed checks that target needs (required or optional)."""
        gaps: dict[str, list[str]] = {t: [] for t in CORE_TARGETS + OPTIONAL_TARGETS}
        for c in self.checks:
            if c.ok:
                continue
            for t in c.targets:
                gaps.setdefault(t, []).append(c.label)
        for t in ("html", "pdf", "epub"):  # the site assembles these outputs
            for label in gaps[t]:
                if label not in gaps["site"]:
                    gaps["site"].append(label)
        return gaps


# --------------------------------------------------------------------------- helpers


def _run(cmd: list[str], timeout: float = 20.0) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return r.returncode, (r.stdout + r.stderr).strip()


def _version_tuple(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(g) for g in m.groups() if g is not None) if m else ()


def _fmt(v: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


def _dist_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _pip_hint() -> str:
    venv = paths.ROOT / ".venv"
    pip = venv / "bin" / "pip" if (venv / "bin").exists() else None
    return f"{paths.rel(pip) if pip else 'pip'} install -r requirements.txt"


# --------------------------------------------------------------------------- checks


def check_python(report: Report) -> None:
    v = sys.version_info[:3]
    ok = v[:2] >= PY_MIN
    report.add(Check(f"Python {_fmt(v)}", ok, "" if ok else f"need ≥ {_fmt(PY_MIN)}",
                     "install Python ≥ 3.11 (python.org, pyenv or your package manager)",
                     targets=CORE_TARGETS))


def check_venv(report: Report) -> None:
    venv = paths.ROOT / ".venv"
    exe = venv / "bin" / "python"
    active = Path(sys.prefix).resolve() == venv.resolve() if venv.exists() else False
    ok = exe.exists()
    detail = "in use by ./tbook" if active else ("present" if ok else "absent: ./tbook uses python3 from PATH")
    report.add(Check("virtualenv .venv", ok, detail,
                     "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",
                     targets=("pdf", "epub"), required=False))


def check_pandoc(report: Report) -> None:
    try:
        pypandoc = importlib.import_module("pypandoc")
    except ImportError:
        report.add(Check("pypandoc (Pandoc)", False, "Python package pypandoc_binary not installed", _pip_hint(),
                         targets=("pdf", "epub")))
        return
    try:
        version = str(pypandoc.get_pandoc_version())
        path = pypandoc.get_pandoc_path()
    except (OSError, RuntimeError) as exc:
        report.add(Check("Pandoc", False, f"pypandoc cannot find pandoc: {exc}", _pip_hint(), targets=("pdf", "epub")))
        return
    ok = _version_tuple(version)[:2] >= (3, 9)
    report.add(Check(f"Pandoc {version}", ok, f"{path}" if ok else f"need 3.9 (pypandoc_binary==1.17), found {version}",
                     _pip_hint(), targets=("pdf", "epub")))


def check_typst(report: Report) -> None:
    try:
        importlib.import_module("typst")
    except ImportError:
        report.add(Check("typst (Python module)", False, "not installed", _pip_hint(), targets=("pdf",)))
        return
    version = _dist_version("typst") or "?"
    report.add(Check(f"typst {version} (Python module)", True, "", _pip_hint(), targets=("pdf",)))


def check_epubcheck(report: Report) -> None:
    try:
        importlib.import_module("epubcheck")
        version = _dist_version("epubcheck") or "?"
        report.add(Check(f"epubcheck {version}", True, "", _pip_hint(), targets=("epub",), required=False))
    except ImportError:
        report.add(Check("epubcheck", False, "not installed: EPUBs are built but not validated", _pip_hint(),
                         targets=("epub",), required=False))
    java = shutil.which("java")
    if not java:
        report.add(Check("Java", False, "not found: epubcheck cannot run, EPUBs are not validated",
                         "sudo apt-get install default-jre-headless  (or any Java ≥ 11)", targets=("epub",), required=False))
        return
    code, out = _run([java, "-version"])
    # The JVM may print "Picked up JAVA_TOOL_OPTIONS: …" first; show the version line.
    lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("Picked up")]
    first = next((ln for ln in lines if "version" in ln), lines[0] if lines else "")
    report.add(Check(f"Java ({first.strip() or java})", code == 0, "" if code == 0 else out[-200:],
                     "sudo apt-get install default-jre-headless", targets=("epub",), required=False))


def mdbook_path() -> str | None:
    env = os.environ.get("MDBOOK")
    if env:
        return env if Path(env).exists() or shutil.which(env) else None
    return shutil.which("mdbook")


def check_mdbook(report: Report) -> None:
    hint = "cargo install mdbook --version 0.5.4 --locked  (or set MDBOOK=/path/to/mdbook)"
    exe = mdbook_path()
    if not exe:
        where = f"MDBOOK={os.environ['MDBOOK']} does not exist" if os.environ.get("MDBOOK") else "not on PATH, MDBOOK unset"
        report.add(Check("mdBook", False, where, hint, targets=("html",)))
        return
    code, out = _run([exe, "--version"])
    v = _version_tuple(out)
    if code != 0 or not v:
        report.add(Check("mdBook", False, f"{exe} --version failed: {out[:120]}", hint, targets=("html",)))
        return
    ok = v[:2] == MDBOOK_EXPECTED[:2]
    detail = exe if v == MDBOOK_EXPECTED else f"{exe}; expected {_fmt(MDBOOK_EXPECTED)}"
    report.add(Check(f"mdBook {_fmt(v)}", ok, detail if ok else f"{exe}: need 0.5.x (0.5.4)", hint, targets=("html",)))


def check_node(report: Report) -> None:
    node = shutil.which("node")
    hint = "install Node ≥ 22.12 (https://nodejs.org or nvm install 22)"
    targets = ("html", "slides", "viz", "films")
    if not node:
        report.add(Check("Node.js", False, "node not on PATH", hint, targets=targets))
        return
    code, out = _run([node, "--version"])
    v = _version_tuple(out)
    ok = code == 0 and v[:2] >= NODE_MIN
    report.add(Check(f"Node.js {_fmt(v) or '?'}", ok, "" if ok else f"need ≥ {_fmt(NODE_MIN)}", hint, targets=targets))


def check_node_modules(report: Report) -> None:
    nm = paths.ROOT / "node_modules"
    for pkg, targets in NODE_PACKAGES:
        manifest = nm / pkg / "package.json"
        if manifest.is_file():
            try:
                version = json.loads(manifest.read_text(encoding="utf-8")).get("version", "?")
            except (OSError, ValueError):
                version = "?"
            report.add(Check(f"node_modules/{pkg} {version}", True, "", "npm ci", targets=targets))
        else:
            report.add(Check(f"node_modules/{pkg}", False, "not installed", "npm ci", targets=targets))


def chromium_path() -> str | None:
    """PW_CHROMIUM_PATH, else a Chromium in Playwright's browser cache."""
    env = os.environ.get("PW_CHROMIUM_PATH")
    if env:
        return env if os.access(env, os.X_OK) else None
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), str(Path.home() / ".cache" / "ms-playwright"),
             str(Path.home() / "Library" / "Caches" / "ms-playwright")]
    patterns = ("chromium-*/chrome-linux*/chrome", "chromium_headless_shell-*/chrome-*/headless_shell",
                "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                "chromium-*/chrome-win*/chrome.exe")
    for root in roots:
        if not root or root == "0":
            continue
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(root, pat)))
            if hits:
                return hits[-1]
    return None


def check_chromium(report: Report) -> None:
    exe = chromium_path()
    hint = "npx playwright install chromium  (or set PW_CHROMIUM_PATH=/path/to/chrome)"
    if os.environ.get("PW_CHROMIUM_PATH") and not exe:
        report.add(Check("Chromium", False, f"PW_CHROMIUM_PATH={os.environ['PW_CHROMIUM_PATH']} is not executable",
                         hint, targets=("slides", "viz", "films")))
        return
    report.add(Check("Chromium (Playwright)", bool(exe), exe or "no PW_CHROMIUM_PATH and no Playwright browser cache",
                     hint, targets=("slides", "viz", "films")))


def check_ffmpeg(report: Report) -> None:
    from . import film

    exe = film.ffmpeg_path()  # $FFMPEG, else ffmpeg on PATH: what the film build uses
    report.add(Check("ffmpeg", bool(exe), exe or "not on PATH and FFMPEG not set",
                     "sudo apt-get install ffmpeg (or set FFMPEG)", targets=("films",)))


# Whether theme/film/lib.js's Chromium can create a WebGL context (solid shots): prints the renderer, or nothing.
_WEBGL_PROBE = """
const { launch } = await import(process.argv[1]);
const b = await launch();
try {
  const p = await b.newPage();
  const r = await p.evaluate(() => { const c = document.createElement('canvas');
    const g = c.getContext('webgl2', { antialias: true, alpha: true, preserveDrawingBuffer: true });
    if (!g) return ''; const d = g.getExtension('WEBGL_debug_renderer_info');
    return String(g.getParameter(g.VERSION)) + (d ? ' · ' + g.getParameter(d.UNMASKED_RENDERER_WEBGL) : ''); });
  console.log(r);
} finally { await b.close(); }
"""


def film_webgl() -> tuple[bool | None, str]:
    """(ok, detail) of a WebGL context in the Chromium the film pipeline launches (theme/film/lib.js); ok is None
    when node, Playwright or a Chromium is missing (reported by their own checks)."""
    node = shutil.which("node")
    if not node or not chromium_path() or not any((paths.ROOT / "node_modules" / p).is_dir()
                                                  for p in ("playwright-chromium", "playwright")):
        return None, "needs node, Playwright and a Chromium"
    lib = (paths.THEME / "film" / "lib.js").resolve().as_uri()
    try:
        r = subprocess.run([node, "--input-type=module", "-e", _WEBGL_PROBE, lib], capture_output=True, text=True,
                           timeout=90, cwd=paths.ROOT)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the probe did not run: {exc}"
    out = r.stdout.strip()
    if r.returncode != 0:
        return False, (r.stderr.strip().splitlines() or ["the probe failed"])[-1][:200]
    return (True, out) if out else (False, "Chromium starts but creates no WebGL context")


def check_film_webgl(report: Report) -> None:
    ok, detail = film_webgl()
    if ok is None:
        return
    report.add(Check("WebGL for solid shots (films)", ok, detail,
                     "films with \"solid\": true need WebGL; theme/film/lib.js starts Chromium with "
                     "--enable-unsafe-swiftshader (SwiftShader, no GPU needed)", targets=("films",)))


def _fc_families() -> set[str] | None:
    exe = shutil.which("fc-list")
    if not exe:
        return None
    code, out = _run([exe, ":", "family"])
    if code != 0:
        return None
    fams: set[str] = set()
    for line in out.splitlines():
        for name in line.split(","):
            fams.add(name.strip())
    return fams


def _cached_font_files() -> list[tuple[str, str]]:
    """(lower-case file name, repository-relative directory) of the fonts the PDF pipeline adds."""
    found: list[tuple[str, str]] = []
    for d in (paths.CACHE / "fonts", paths.CACHE / "fonts-fontsource", paths.THEME / "typst" / "fonts"):
        if d.is_dir():
            found += [(p.name.lower(), paths.rel(d)) for p in sorted(d.iterdir())
                      if p.suffix.lower() in (".ttf", ".otf", ".ttc")]
    return found


def check_fonts(report: Report) -> None:
    fams = _fc_families()
    cached = _cached_font_files()
    for accepted, label, hint in FONTS:
        key = label.lower().replace(" ", "").replace("cjk", "")
        cache_dir = next((d for name, d in cached if key in name.replace("-", "").replace("_", "")), "")
        in_cache = bool(cache_dir)
        found = bool(fams and any(a in fams for a in accepted))
        where = "system (fc-list)" if found else cache_dir
        detail = where or ("fc-list unavailable" if fams is None else "not installed: PDF/EPUB fall back to other fonts")
        report.add(Check(f"font {label}", found or in_cache, detail, hint, targets=("pdf", "epub", "slides", "films"),
                         required=False))


def check_lock(report: Report) -> str | None:
    """Returns the pinned (repo, commit) as 'repo@commit' when the lock is readable."""
    from . import lean

    hint = "./tbook pin  (pins the trureturing commit and resolves cited declarations)"
    if not paths.LOCK_FILE.exists():
        report.add(Check("trureturing.lock.json", False, "missing", hint, targets=("check",)))
        return None
    try:
        lock = lean.Lock.load()
    except (lean.LeanError, ValueError, KeyError) as exc:
        report.add(Check("trureturing.lock.json", False, f"unreadable: {exc}", hint, targets=("check",)))
        return None
    report.add(Check(f"trureturing.lock.json ({lock.commit[:12]}, {len(lock.declarations)} declarations)", True,
                     lock.repo, hint, targets=("check",)))
    return f"{lock.repo}@{lock.commit}"


def _checkouts() -> list[Path]:
    out = []
    env = os.environ.get("TRURETURING_DIR")
    if env:
        out.append(Path(env))
    out.append(paths.ROOT.parent / "trureturing")
    return out


def check_trureturing(report: Report, pinned: str | None) -> None:
    """Access to trureturing at the pinned commit, and whether that commit is on the configured branch."""
    _check_access(report, pinned)
    check_branch(report, pinned)


def check_branch(report: Report, pinned: str | None) -> None:
    """``./tbook check`` requires the pinned commit on site.toml's trureturing branch (default ``dev``).

    Asked as check asks it (cache, local checkout, GitHub's branches and compare API), so a stale
    checkout or a missing API token shows up here first. "Cannot tell" is only a warning: check makes
    it an error in GitHub Actions alone. A branch that GitHub says does not exist is an error.
    """
    from . import config, lean

    _, _, commit = (pinned or "").partition("@")
    if not commit:
        return  # check_lock reported the lock
    try:
        site = config.load_site()
        repo, branch = site.trureturing_repo, site.trureturing_branch
        anc = lean.Ledger(repo).branch_contains(commit, branch)
    except Exception as exc:  # noqa: BLE001 - doctor reports, it never crashes
        report.add(Check("pinned commit on the trureturing branch", False, f"cannot tell: {exc}",
                         "fix site.toml, then ./tbook check", targets=("check",), required=False))
        return
    label = f"pinned commit {commit[:12]} on {repo}@{branch}"
    if anc.on_branch:
        report.add(Check(label, True, anc.detail, targets=("check",)))
    elif anc.no_branch:
        report.add(Check(label, False, f"no branch {branch}: {anc.detail}",
                         f"set [trureturing] branch in site.toml to an existing branch of {repo} (default dev)",
                         targets=("check",)))
    elif anc.on_branch is False:
        report.add(Check(label, False, f"not on {branch}: {anc.detail}",
                         f"pin a commit on {branch}: ./tbook pin", targets=("check",)))
    else:
        report.add(Check(label, False, f"cannot tell: {anc.detail}",
                         f"set TRURETURING_DIR to a trureturing checkout that has fetched {branch} "
                         "(git fetch origin), or allow api.github.com (set GITHUB_TOKEN to avoid its rate limit)",
                         targets=("check",), required=False))


def _check_access(report: Report, pinned: str | None) -> None:
    repo, _, commit = (pinned or "").partition("@")
    for cand in _checkouts():
        if not (cand / ".git").exists():
            continue
        if commit:
            code, _ = _run(["git", "-C", str(cand), "cat-file", "-e", f"{commit}^{{commit}}"])
            if code != 0:
                report.add(Check(f"trureturing checkout {cand}", False, f"lacks the pinned commit {commit[:12]}",
                                 f"git -C {cand} fetch origin", targets=("check",), required=False))
                continue
        report.add(Check("trureturing access", True, f"git checkout {cand}", "", targets=("check",)))
        return
    cache = paths.CACHE / "trureturing" / commit if commit else None
    url = f"https://raw.githubusercontent.com/{repo or 'the-omega-institute/trureturing'}/{commit or 'HEAD'}/lean-toolchain"
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "tbook-doctor"})
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as resp:
            ok, detail = resp.status < 400, f"raw.githubusercontent.com reachable (HTTP {resp.status})"
    except urllib.error.HTTPError as exc:
        ok, detail = False, f"raw.githubusercontent.com answered HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        ok, detail = False, f"raw.githubusercontent.com unreachable ({reason})"
    if not ok and cache is not None and cache.is_dir():
        ok, detail = True, f"offline; using cache {paths.rel(cache)} (./tbook check --offline)"
    report.add(Check("trureturing access", ok, detail,
                     "set TRURETURING_DIR to a trureturing git checkout, or allow access to raw.githubusercontent.com",
                     targets=("check",)))


def check_lean(report: Report) -> None:
    lake = shutil.which("lake") or (str(Path.home() / ".elan" / "bin" / "lake")
                                     if (Path.home() / ".elan" / "bin" / "lake").exists() else None)
    report.add(Check("elan / lake", bool(lake), lake or "not installed (only ./tbook lean-project's verify.sh needs it)",
                     "curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y "
                     "--default-toolchain none", targets=("lean-verify",)))


def collect() -> Report:
    report = Report()
    check_python(report)
    check_venv(report)
    pinned = check_lock(report)
    check_trureturing(report, pinned)
    check_pandoc(report)
    check_typst(report)
    check_epubcheck(report)
    check_mdbook(report)
    check_node(report)
    check_node_modules(report)
    check_chromium(report)
    check_ffmpeg(report)
    check_film_webgl(report)
    check_fonts(report)
    check_lean(report)
    return report


# --------------------------------------------------------------------------- output


def _colour(enabled: bool):
    codes = {"✓": "32", "✗": "31", "!": "33", "dim": "2"}

    def paint(text: str, key: str) -> str:
        return f"\033[{codes[key]}m{text}\033[0m" if enabled else text

    return paint


def books_line() -> str:
    """The books the commands work on and, when site.toml [books].hide hides some, those (informational)."""
    from . import config

    try:
        shown, hidden = config.book_slugs(), config.hidden_books()
    except Exception as exc:  # noqa: BLE001 - doctor reports, it never crashes
        return f"books: cannot list them ({exc})"
    line = f"books: {', '.join(shown) or 'none'}"
    return line + (f"; hidden by site.toml [books].hide: {', '.join(hidden)}" if hidden else "")


def run() -> int:
    """Print the report; return 1 when a required check fails."""
    tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    paint = _colour(tty)
    report = collect()
    print("tbook doctor · toolchain")
    for c in report.checks:
        line = f"  {paint(c.mark, c.mark)} {c.label}"
        if c.detail:
            line += paint(f"  — {c.detail}", "dim")
        print(line)
        if not c.ok and c.hint:
            print(f"      fix: {c.hint}")
    print("targets")
    gaps = report.target_gaps()
    for t in CORE_TARGETS + OPTIONAL_TARGETS:
        missing = gaps.get(t, [])
        kind = "" if t in CORE_TARGETS else " (optional)"
        if not missing:
            print(f"  {paint('✓', '✓')} {t}{kind}")
        else:
            blocking = [c.label for c in report.blocking() if t in c.targets or (t == "site" and set(c.targets) & {"html", "pdf", "epub"})]
            mark = "✗" if blocking else "!"
            print(f"  {paint(mark, mark)} {t}{kind}: {', '.join(missing)}")
    print(books_line())
    blocking = report.blocking()
    optional = [c for c in report.checks if not c.ok and not c.is_required]
    print(f"result: {len(blocking)} required item(s) missing, {len(optional)} optional")
    return 1 if blocking else 0
