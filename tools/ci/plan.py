"""Plan CI before setup, using Git diffs and trusted successful producer records.

No third party Python/Node dependency is needed. Unknown paths widen coverage; malformed
inventories and selector failures fail the plan job rather than becoming an empty selection.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib
from urllib.parse import urlencode
import zipfile

# This constructor is dependency-free and shared with the actual video unit.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tbook import film_inputs, template as template_metadata
from ci import viz_budget, testing, trusted_cache

VERSION = 6
SCHEMA = "tbook-ci-coverage-v1"
DEPENDENCIES = "tbook-ci-dependencies-v1"
MAX_FILM_SHARDS = 16
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
JOBS = ("validate", "browser", "stills", "build", "viz", "viz-slow", "media", "films")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


class Tree:
    def __init__(self, root, ref):
        self.root = Path(root)
        self.sha = git(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
        self.objects = {}
        for entry in git(root, 'ls-tree', '-r', '-z', self.sha).split(b'\0'):
            if entry:
                meta, name = entry.split(b'\t', 1)
                self.objects[name.decode()] = meta.split()[-1].decode()
        self.files = set(self.objects)
        self.cache = {}
        self.reader = None

    def read(self, name):
        if name not in self.cache:
            if self.reader is None:
                self.reader = subprocess.Popen(['git', '-C', str(self.root), 'cat-file', '--batch'],
                                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            # Object IDs, never filenames, enter the line-based protocol; unusual paths stay inert.
            self.reader.stdin.write((self.objects[name] + '\n').encode())
            self.reader.stdin.flush()
            header = self.reader.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise ValueError(f'cannot read Git blob: {name}')
            self.cache[name] = self.reader.stdout.read(int(header[2])).decode()
            if self.reader.stdout.read(1) != b'\n':
                raise ValueError('invalid Git object stream')
        return self.cache[name]

    def __del__(self):
        reader = getattr(self, 'reader', None)
        if reader is not None:
            reader.stdin.close()
            reader.stdout.close()
            reader.wait()

    def json(self, name):
        return json.loads(self.read(name))

    def toml(self, name):
        return tomllib.loads(self.read(name)) if name in self.files else {}


def inventory(tree):
    site = tree.toml("site.toml")
    hide = site.get("books", {}).get("hide", [])
    if not isinstance(hide, list) or not all(isinstance(x, str) and x for x in hide):
        raise ValueError("site.toml: invalid books.hide")
    books = {}
    for p in sorted(tree.files):
        m = re.fullmatch(r"books/([^/]+)/book.toml", p)
        if not m or any(fnmatch.fnmatchcase(m[1], pat) for pat in hide):
            continue
        slug = m[1]
        if not SLUG.fullmatch(slug):
            raise ValueError(f"unsafe book slug: {slug}")
        raw = tree.toml(p)
        outputs = raw.get("outputs", {})
        pdf = outputs.get("pdf", ["screen", "print"])
        pdf = ["screen", "print"] if pdf is True else [] if pdf is False else pdf
        if not isinstance(pdf, list) or any(v not in ("screen", "print", "academic") for v in pdf):
            raise ValueError(f"{p}: invalid outputs.pdf")
        prefix = f"books/{slug}/"
        suites = sorted(f for f in tree.files if re.fullmatch(re.escape(prefix) + r"viz/tests/[^/]+\.test\.mjs", f))
        films = {}
        decks = set()
        for f in sorted(tree.files):
            fm = re.fullmatch(re.escape(prefix) + r"films/([^/]+)/film.json", f)
            sm = re.fullmatch(re.escape(prefix) + r"slides/([^/]+)/.+", f)
            if fm:
                if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fm[1]):
                    raise ValueError(f"invalid film directory: {fm[1]}")
                meta = tree.json(f)
                scripts = meta.get("scripts", [])
                if not isinstance(scripts, list) or not all(isinstance(x, str) for x in scripts):
                    raise ValueError(f"{f}: invalid scripts")
                if not isinstance(meta.get("solid", False), bool):
                    raise ValueError(f"{f}: invalid solid")
                if any(not x.endswith(".js") or x.startswith("/") or ".." in PurePosixPath(x).parts or "\\" in x for x in scripts):
                    raise ValueError(f"{f}: invalid script path")
                films[f"{slug}/{fm[1]}"] = {"scripts": [prefix + x for x in scripts], "solid": meta.get("solid", False)}
            if sm and not sm[1].startswith(("_", ".")):
                if not SLUG.fullmatch(sm[1]):
                    raise ValueError(f"unsafe slide id: {sm[1]}")
                decks.add(f"{slug}/{sm[1]}")
        deps_path = prefix + "viz/tests/dependencies.json"
        deps = {}
        if deps_path in tree.files:
            data = tree.json(deps_path)
            if data.get("schema") != DEPENDENCIES or not isinstance(data.get("suites"), dict):
                raise ValueError(f"{deps_path}: invalid schema or suites")
            for name, patterns in data["suites"].items():
                suite = prefix + "viz/tests/" + name
                if "/" in name or not name.endswith(".test.mjs") or suite not in suites:
                    raise ValueError(f"{deps_path}: unknown suite {name}")
                if not isinstance(patterns, list) or not all(isinstance(x, str) and x and not x.startswith("/") and
                        ".." not in PurePosixPath(x).parts and "\\" not in x for x in patterns):
                    raise ValueError(f"{deps_path}: unsafe dependency patterns for {name}")
                deps[suite] = patterns
        parts_path = prefix + "viz/tests/execution-parts.json"
        declared = viz_budget.parts(tree.json(parts_path), [PurePosixPath(s).name for s in suites]) if parts_path in tree.files else {}
        books[slug] = dict(suites=suites, parts=declared, films=films, slides=sorted(decks), deps=deps,
                           outputs=[*( ["html"] if outputs.get("html", True) else []),
                                    *("pdf-" + v for v in pdf), *( ["epub"] if outputs.get("epub", True) else [])])
    return books


def changed_paths(root, base, head):
    # --no-renames deliberately represents both endpoints as D+A; NUL preserves unusual filenames.
    return sorted(set(git(root, "diff", "--no-renames", "--name-only", "-z", base, head, "--").decode().rstrip("\0").split("\0")) - {""})


def shards(items, maximum):
    items = sorted(set(items))
    count = min(maximum, len(items))
    return [{"shard": f"{i + 1}/{count}", "items": items[i::count]} for i in range(count)]


def export_matrix(exports):
    """One installation per enabled format, with an exact list of affected books."""
    groups = {}
    for item in exports:
        key = (item["target"], item["variant"])
        if key not in groups:
            groups[key] = dict(name="-".join(x for x in key if x), target=key[0], variant=key[1], books=[])
        groups[key]["books"].append(item["book"])
    for group in groups.values():
        group["books"] = sorted(set(group["books"]))
    return list(groups.values())


def imports(tree, *sources):
    """Literal relative JS import closure; computed/extra reads need a complete summary."""
    # Trees are immutable. Many suite summaries share the same runtime roots;
    # parse each module once rather than once per consumer/profile.
    if not hasattr(tree, "_import_edges"):
        tree._import_edges = {}
    seen, pending = set(), list(sources)
    while pending:
        p = pending.pop()
        if p in seen:
            continue
        seen.add(p)
        if p not in tree.files or not p.endswith((".js", ".mjs")):
            continue
        if p not in tree._import_edges:
            import posixpath
            tree._import_edges[p] = [posixpath.normpath(str(PurePosixPath(p).parent / spec))
                for spec in re.findall(r'(?:from\s*|import\s*(?:\(\s*)?)[\'"]([^\'"]+)[\'"]', tree.read(p))
                if spec.startswith(".")]
        pending.extend(q for q in tree._import_edges[p] if q not in seen)
    return seen


def suite_inputs(tree, slug, book, suite):
    """Implicit own inputs plus the existing complete extra-read contract.

    Imports of declared runtime modules count too, so a new module reached by
    the same constructor does not require a second concrete filename registry.
    Semantic completeness is a source/author premise, not inferred from JSON.
    """
    base = f"books/{slug}/viz/"
    ident = PurePosixPath(suite).name.removesuffix(".test.mjs")
    patterns = [base + ident + "/**", base + "visualizations.json", *book["deps"].get(suite, [])]
    # The author declares these lock reads are solely the shared evidence-link gate.
    # Structural/static validation still checks them on every lock change.
    if "@lean-links" in patterns:
        patterns.remove("@lean-links")
    if '@registry-entry' in patterns:
        patterns.remove('@registry-entry')
        patterns.remove(base + 'visualizations.json')
    if "@citations" in patterns:
        patterns.remove("@citations")
        patterns.extend(citation_inputs(tree, slug, ident))
    roots = [suite, *(p for p in tree.files if p.endswith((".js", ".mjs")) and
                      any(fnmatch.fnmatchcase(p, pat) for pat in patterns))]
    return patterns, imports(tree, *roots)


def registry_entry(tree, slug, ident):
    if tree is None:
        return None
    name = f'books/{slug}/viz/visualizations.json'
    if name not in tree.files:
        return None
    if not hasattr(tree, '_registry_entries'):
        tree._registry_entries = {}
    if name not in tree._registry_entries:
        data = tree.json(name)
        entries = data['visualizations']
        if not isinstance(entries, list) or any(not isinstance(v, dict) or not SLUG.fullmatch(v.get('id', '')) for v in entries):
            raise ValueError(f'invalid visualization registry: {name}')
        values = {v['id']: v for v in entries}
        if len(values) != len(entries):
            raise ValueError(f'duplicate visualization registry ID: {name}')
        tree._registry_entries[name] = values
    return tree._registry_entries[name].get(ident)


def citation_inputs(tree, slug, ident):
    """Use the publication block parser, including comments and fences, for chapter readers."""
    from tbook import mdscan, model
    if not hasattr(tree, "_citation_inputs"):
        tree._citation_inputs = {}
    if slug not in tree._citation_inputs:
        data = {}
        meta = tree.toml(f"books/{slug}/book.toml")
        langs = meta.get("book", {}).get("editions") or tree.toml("site.toml").get("site", {}).get("languages", ["zh", "en"])
        for p in sorted(tree.files):
            if not any(p.startswith(f"books/{slug}/{lang}/") for lang in langs) or not p.endswith(".md"):
                continue
            if PurePosixPath(p).name == "SUMMARY.md":
                continue
            for node in mdscan.walk(mdscan.parse_blocks(tree.read(p))):
                if isinstance(node, mdscan.Div) and model.kind_of(node) == "viz":
                    data.setdefault((node.attrs.get("src") or "").strip(), set()).add(p)
        tree._citation_inputs[slug] = data
    # A changed reading order may add/remove the chapter from publication.
    summaries = [p for p in tree.files if p.startswith(f"books/{slug}/") and p.endswith("/SUMMARY.md")]
    return sorted(tree._citation_inputs[slug].get(ident, set())) + summaries


def execution_inventory(tree, *, with_workloads=False):
    """Every part inherits the parent's full real input relation and source identity."""
    blobs = {}
    for entry in git(tree.root, "ls-tree", "-r", "-z", tree.sha).split(b"\0"):
        if entry:
            meta, name = entry.split(b"\t", 1)
            blobs[name.decode()] = meta.decode()
    result, workloads = {}, {}
    for slug, book in inventory(tree).items():
        for suite in book["suites"]:
            declared = book["parts"].get(PurePosixPath(suite).name, [])
            patterns, closure = suite_inputs(tree, slug, book, suite)
            files = closure | {p for p in tree.files if any(fnmatch.fnmatchcase(p, pat) for pat in patterns)}
            # Cost eligibility follows the executable test/import/part definition.
            # Page/data changes remain visible as workload provenance; estimates
            # are advisory and do not discharge the newly selected work.
            definition = viz_budget.fingerprint([(p, blobs.get(p)) for p in imports(tree, suite)], declared)
            workload = viz_budget.fingerprint([(p, blobs.get(p)) for p in files], patterns)
            result[suite] = {u: definition for u in viz_budget.units(suite, declared)}
            workloads.update({u: workload for u in result[suite]})
    return (result, workloads) if with_workloads else result


def scope_contains(path, source):
    return path == source.rstrip("/") or (source.endswith("/") and path.startswith(source))


def film_reads(tree, slug, film, meta):
    """Project the supported video constructor, retaining provenance and exclusions.

    Classic scripts are inlined in out/index.html. Their module URLs would have
    a different base; do not treat source-relative imports as complete film reads.
    Arbitrary custom I/O is outside this constructor's completeness premise.
    """
    where = f"books/{slug}/films/{film.split('/')[1]}"
    scopes = (*film_inputs.video_files(where), *film_inputs.extra_files(meta["scripts"], meta["solid"]))
    sources = set(film_inputs.engine_sources(slug))
    scripts = [*meta["scripts"], where + "/scenes.js"]
    closure = imports(tree, *scripts)
    uncertain = any(re.search(r"\bimport\s*(?:\(|['\"{*]|[\w$]+\s*(?:,|from\b))|\bexport\s+.*\bfrom\s*['\"]", tree.read(p))
                    for p in scripts if p in tree.files)
    return scopes, sources | closure, uncertain


def film_lock_inputs(tree, film):
    """Only the pin and this film's resolved declarations enter its engine data."""
    if tree is None or "trureturing.lock.json" not in tree.files:
        return None
    if not hasattr(tree, "_film_lock"):
        tree._film_lock = tree.json("trureturing.lock.json")
    lock = tree._film_lock
    slug, ident = film.split("/")
    path = f"books/{slug}/films/{ident}/film.json"
    if (path not in tree.files or not isinstance(lock.get("declarations"), dict) or
            not lock.get("repo") or not lock.get("commit")):
        return None
    gids = tree.json(path).get("lean") or []
    return lock["repo"], lock["commit"], {gid: lock["declarations"].get(gid) for gid in gids}


def _template_version_only(current, previous):
    """Prove release metadata or collaboration ownership changes without output readers.

    Keep every other parsed field (including unknown fields) in the comparison.
    Missing/invalid inputs cannot establish this narrower responsibility class.
    """
    name = template_metadata.TEMPLATE_TOML
    if previous is None or any(name not in tree.files for tree in (current, previous)):
        return False
    versions, remaining, ownership = [], [], []
    try:
        for tree in (current, previous):
            text = tree.read(name)
            cfg = template_metadata.TemplateConfig.from_bytes(text.encode())
            if template_metadata.parse_semver(cfg.version) is None:
                return False
            data = tomllib.loads(text)
            versions.append(data["template"].pop("version"))
            # These paths describe collaboration metadata, never publication inputs.
            # Keep every other ownership change conservative, and still propagate
            # explicitly declared consumers before this classification.
            metadata_paths = {"CONTRIBUTING.md", ".github/ISSUE_TEMPLATE/", ".github/pull_request_template.md"}
            metadata_excludes = {".github/ISSUE_TEMPLATE/local-"}
            managed = data.get("managed", {})
            ownership.append((managed.get("paths", []), managed.get("exclude", [])))
            for key, metadata in (("paths", metadata_paths), ("exclude", metadata_excludes)):
                if key in managed:
                    managed[key] = [p for p in managed[key] if p not in metadata]
                    if not managed[key]:
                        managed.pop(key)
            # Preserve TOML value types (e.g. true != 1); unsupported values widen.
            remaining.append(json.dumps(data, sort_keys=True))
    except (template_metadata.TemplateError, ValueError, TypeError, AttributeError, KeyError,
            subprocess.SubprocessError):
        return False
    return (versions[0] != versions[1] or ownership[0] != ownership[1]) and remaining[0] == remaining[1]


def blob_id(tree, name):
    if name not in tree.files:
        return None
    if hasattr(tree, "sha"):
        if not hasattr(tree, "_blob_ids"):
            tree._blob_ids = {}
            for entry in git(tree.root, "ls-tree", "-r", "-z", tree.sha).split(b"\0"):
                if entry:
                    meta, path = entry.split(b"\t", 1)
                    tree._blob_ids[path.decode()] = meta.split()[2].decode()
        return tree._blob_ids[name]
    # The local adapter includes uncommitted binary assets too.
    data = (tree.root / name).read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def adopt_unchanged_summaries(current, previous, now, old):
    """A corrected complete summary describes both trees when ALL its inputs are equal."""
    if previous is None:
        return
    for slug, book in now.items():
        prior = old.get(slug)
        if not prior:
            continue
        for suite, deps in book["deps"].items():
            if prior["deps"].get(suite) == deps or suite not in prior["suites"]:
                continue
            view = dict(prior, deps={**prior["deps"], suite: deps})
            relations = []
            for tree, metadata in ((current, book), (previous, view)):
                patterns, closure = suite_inputs(tree, slug, metadata, suite)
                relations.append(closure | {p for p in tree.files
                                             if any(fnmatch.fnmatchcase(p, pat) for pat in patterns)})
            if relations[0] == relations[1] and all(blob_id(current, p) == blob_id(previous, p) for p in relations[0]):
                prior["deps"][suite] = deps


def impact(current, previous, paths, *, full=False, template=False):
    now, old = inventory(current), inventory(previous) if previous else {}
    adopt_unchanged_summaries(current, previous, now, old)
    all_suites = {s for b in now.values() for s in b["suites"]}
    all_films = {f for b in now.values() for f in b["films"]}
    all_slides = {s for b in now.values() for s in b["slides"]}
    selected_books, suites, films, slides = set(), set(), set(), set()
    export_outputs = set()
    checks = dict(unit=False, theme=False, structure=False, viz_static=False, slides_static=False,
                  compat=False, manifest=template)
    reasons, path_reasons = set(), {}
    site = False
    all_tests = full

    def path_reason(prefix, path, suffix=""):
        key = (prefix, suffix)
        first, count = path_reasons.get(key, (path, 0))
        path_reasons[key] = (first, count + 1)

    def shared_outputs(reason, path=None):
        nonlocal site
        if path is None:
            reasons.add(reason)
        else:
            path_reason(reason, path)
        site = True
        checks.update({k: True for k in checks if k != "manifest"})
        checks["compat"] = template
        for slug in now:
            # publish_assets copies optional runtimes/vendor even for browser nonreaders.
            # Preserve complete export/static/deck responsibility independently of execution.
            selected_books.add(slug)
            export_outputs.update((slug, output) for output in now[slug]["outputs"])
            slides.update(now[slug]["slides"])

    def everything(reason, path=None):
        nonlocal all_tests
        all_tests = True
        shared_outputs(reason, path)
        suites.update(all_suites)
        films.update(all_films)

    if full:
        everything("full: explicit mode or unavailable comparable successful coverage")
    readers = []
    for tree, books in ((current, now), (previous, old)):
        if tree is not None and paths:
            readers.append((tree, books,
                {s: suite_inputs(tree, slug, b, s) for slug, b in books.items() for s in b["suites"]},
                {f: film_reads(tree, slug, f, m) for slug, b in books.items() for f, m in b["films"].items()}))
    uncertain_films = set()
    for film in all_films:
        summaries = [video_reads.get(film) for _, _, _, video_reads in readers]
        if len(summaries) != 2 or any(s is None or s[2] for s in summaries):
            uncertain_films.add(film)
    for p in sorted(set(paths)):
        # Declared nonlocal dependencies apply even to otherwise documentary paths.
        matched_suites, matched_films = set(), set()
        for tree, books, suite_reads, video_reads in readers:
            for suite, (patterns, closure) in suite_reads.items():
                if suite in all_suites and (p in closure or any(fnmatch.fnmatchcase(p, pat) for pat in patterns)):
                    matched_suites.add(suite)
            for slug, book in books.items():
                if p == f'books/{slug}/viz/visualizations.json':
                    for suite in book['suites']:
                        ident = PurePosixPath(suite).name.removesuffix('.test.mjs')
                        if (suite in all_suites and '@registry-entry' in book['deps'].get(suite, []) and
                                registry_entry(current, slug, ident) != registry_entry(previous, slug, ident)):
                            matched_suites.add(suite)
            for film, (scopes, sources, uncertain) in video_reads.items():
                if film in all_films and (p in sources or any(scope_contains(p, src) and
                        not any(skip in "/" + p for skip in exclude) for src, exclude in scopes)):
                    matched_films.add(film)
        if p == "trureturing.lock.json":
            for film in matched_films.copy() - uncertain_films:
                inputs = film_lock_inputs(current, film)
                if inputs is not None and inputs == film_lock_inputs(previous, film):
                    matched_films.remove(film)
        if p == "theme/tokens.json":
            # The video constructor reads tokens.mjs generated from this source.
            matched_films.update(all_films)
        suites.update(matched_suites)
        films.update(matched_films)
        # Each path counts once per live consumer, even when both trees read it.
        # Keep only a representative and count, not the path/consumer cross product.
        for suite in matched_suites:
            path_reason("", p, f" -> suite {suite}")
        for film in matched_films:
            path_reason("", p, f" -> film {film}")
        if p.startswith(("docs/", "skills/", ".claude/")) or ("/" not in p and p.endswith(".md")) or p in ("LICENSE", "template-manifest.json"):
            continue
        if p.startswith(("tools/ci/", "tools/tests/")) or p in (
                ".github/workflows/ci.yml", ".github/workflows/toolchain-image.yml"):
            # Planning/test infrastructure has no publication output. Declared
            # runtime readers were already propagated above, before classification.
            continue
        if p == ".github/workflows/pages.yml":
            # Validate publication orchestration and exercise assembly/deployment;
            # unchanged book inputs retain their browser and export evidence.
            site = True
            reasons.add(f"publication workflow: {p}")
            continue
        if p.startswith(".github/ISSUE_TEMPLATE/") or p in (
                ".github/pull_request_template.md", ".github/workflows/pr-conventions.yml",
                ".github/workflows/template-sync.yml", ".github/workflows/trureturing-bump.yml"):
            # Collaboration and PR producers have no publication output. Any
            # declared runtime readers and test-file reads remain selected.
            continue
        if p == "template.toml" and _template_version_only(current, previous):
            # Template fixtures/tooling consume this metadata. Site assembly reads
            # it for footer/manifest attribution; export units do not key on it.
            # As for engineering documents, extra consumer reads above still apply.
            checks["unit"] = True
            checks["compat"] = template
            site = True
            reasons.add(f"template version metadata: {p}")
            continue
        if p.startswith("books/"):
            parts = p.split("/")
            slug = parts[1] if len(parts) > 1 else ""
            if slug.startswith("example-"):
                # Tool tests copy example source fixtures even when the books are hidden.
                checks["unit"] = True
                checks["compat"] = template
                path_reason("tool test example fixture: ", p)
            if slug not in now and slug not in old:
                # Hidden books do not participate; unrecognised files outside a book are uncertain.
                hidden = current.toml("site.toml").get("books", {}).get("hide", [])
                if any(fnmatch.fnmatchcase(slug, x) for x in hidden):
                    continue
                everything("unknown book path: ", p)
                continue
            local = "/".join(parts[2:])
            test_input = local.startswith("viz/tests/")
            site |= not test_input
            checks["structure"] = True
            if slug not in now:
                reasons.add(f"removed book: {slug}; Pages rebuild removes obsolete output")
                continue
            selected_books.add(slug)
            if not test_input:
                export_outputs.update((slug, output) for output in now[slug]["outputs"])
            b = now[slug]
            checks["viz_static"] = checks["slides_static"] = True
            # Unregistered suites have unknown file reads: widen to the owning book's suites.
            for suite in b["suites"]:
                if local != "viz/tests/dependencies.json" and (suite not in b["deps"] or (slug in old and suite not in old[slug]["deps"])):
                    suites.add(suite)
                    reasons.add(f"unregistered suite dependency -> {suite}")
            for film in set(b["films"]) & uncertain_films:
                films.add(film)
                reasons.add(f"unknown book-local film reads -> {film}")
            if local == "viz/tests/dependencies.json":
                suites.update(suite for suite in b["suites"]
                              if b["deps"].get(suite) != old.get(slug, {}).get("deps", {}).get(suite))
            elif local == "viz/tests/execution-parts.json":
                # Changes to a parent's finite execution contract select that parent
                # in either tree, without widening already-declared nonreaders.
                before = old.get(slug, {}).get("parts", {})
                for suite in b["suites"]:
                    name = PurePosixPath(suite).name
                    if b["parts"].get(name) != before.get(name):
                        suites.add(suite)
            elif local.startswith("viz/tests/") and p in all_suites:
                suites.add(p)
            elif local.startswith("viz/"):
                for suite in b["suites"]:
                    ident = PurePosixPath(suite).name.removesuffix(".test.mjs")
                    if (local.startswith(f"viz/{ident}/") or
                            (local == "viz/visualizations.json" and '@registry-entry' not in b['deps'].get(suite, [])) or
                            local.startswith("viz/assets/")):
                        suites.add(suite)
            elif local.startswith("films/"):
                film = f"{slug}/{parts[3]}" if len(parts) > 3 else ""
                if film in all_films:
                    films.add(film)
            elif local.startswith("slides/"):
                deck = f"{slug}/{parts[3]}" if len(parts) > 3 else ""
                if deck in all_slides:
                    slides.add(deck)
            else:
                # Declared chapter readers above select only their own cited visualization.
                languages = current.toml(f"books/{slug}/book.toml").get("book", {}).get("editions") or current.toml("site.toml").get("site", {}).get("languages", ["zh", "en"])
                if local == "book.toml" or local.split("/")[0] not in languages:
                    slides.update(b["slides"])
                    # Supported film constructors already describe their full reads;
                    # unknown readers above keep their own conservative responsibility.
                    path_reason("book metadata/resource or unknown local dependency: ", p)
            # Academic decks read chapters, figures and viz, beyond slides/ itself.
            for deck in b["slides"]:
                if not test_input and f"books/{deck.split('/')[0]}/slides/{deck.split('/')[1]}/deck.toml" in current.files:
                    slides.add(deck)
            continue
        if p.startswith(("tools/", "theme/", "templates/", "i18n/")) or p == ".github/workflows/ci.yml":
            # These theme resources have distinct publication consumers. Test and
            # film read edges are independent and are still propagated below.
            if p.startswith(("theme/mdbook/", "theme/epub/", "theme/site/", "theme/film/", "theme/beamer/", "theme/slides/")):
                site = True
                area = p.split("/")[1]
                for slug, book in now.items():
                    for output in book["outputs"]:
                        if (area, output) in (("mdbook", "html"), ("epub", "epub")):
                            selected_books.add(slug)
                            export_outputs.add((slug, output))
                    if area in ("slides", "beamer"):
                        slides.update(deck for deck in book["slides"] if area == "slides" or
                                      f"books/{slug}/slides/{deck.split('/')[1]}/deck.toml" in current.files)
                path_reason("publication theme: ", p)
            else:
                shared_outputs("shared consumer input: ", p)
            for slug, b in now.items():
                for suite in b["suites"]:
                    # Both summaries must apply to the live reader. New or undeclared
                    # suites may read any shared resource, including via computed paths.
                    if suite not in b["deps"] or suite not in old.get(slug, {}).get("deps", {}):
                        suites.add(suite)
                        reasons.add(f"unknown shared reads -> {suite}")
            # Uncertainty belongs to an inapplicable consumer summary, not to a
            # resource filename/role. A complete supported constructor describes
            # optional and future paths too; file existence is no completeness proof.
            films.update(uncertain_films)
            reasons.update(f"unknown shared film reads -> {film}" for film in uncertain_films)
            continue
        if p == "trureturing.lock.json":
            shared_outputs("evidence lock: ", p)
            # Ordinary declared lock readers above still run. Only explicit link-only
            # readers delegate the unchanged browser behavior to static evidence checks.
            for b in now.values():
                suites.update(s for s in b['suites'] if s not in b['deps'])
            films.update(uncertain_films)
            continue
        if p.startswith(("tools/", "theme/", "templates/", ".github/", "i18n/")) or p in (
                "site.toml", "trureturing.lock.json", "package.json", "package-lock.json", "requirements.txt", "template.toml", "tbook"):
            everything("shared input: ", p)
        else:
            everything("unknown impact: ", p)
    # Any dependency-selected consumer also needs its book's structural/static checks and site publication.
    for item in suites | films | slides:
        slug = item.split("/")[1] if item.startswith("books/") else item.split("/")[0]
        if slug in now:
            selected_books.add(slug)
        checks["structure"] = True
        site |= item in films or item in slides
    checks["viz_static"] |= bool(suites)
    checks["slides_static"] |= bool(slides)
    exports = []
    for slug in sorted(selected_books):
        for output in now[slug]["outputs"]:
            if (slug, output) in export_outputs:
                target, _, variant = output.partition("-")
                exports.append(dict(name=f"{slug}-{output}", book=slug, target=target, variant=variant))
    for (prefix, suffix), (first, count) in path_reasons.items():
        more = f" (+{count - 1} more)" if count > 1 else ""
        reasons.add(f"{prefix}{first}{more}{suffix}")
    test_selection = testing.select(current, previous, paths, full=all_tests)
    checks["unit"] = bool(test_selection["unit_tests"])
    checks["browser"] = bool(test_selection["browser_tests"])
    return dict(**test_selection, checks=checks, books=sorted(selected_books), suites=sorted(suites), films=sorted(films),
                slides=sorted(slides), exports=exports, site=site, reasons=sorted(reasons))


def published_still_cards(tree, slug):
    """Project the publication parser onto the (preset, language) images it requests."""
    from tbook import mdscan, model, summary, viz
    cards = {}
    root = f"books/{slug}/"
    langs = tree.toml(root + "book.toml").get("book", {}).get("editions") or tree.toml("site.toml").get("site", {}).get("languages") or ["zh", "en"]
    for lang in langs:
        prefix = root + lang + "/"
        name = prefix + "SUMMARY.md"
        if name not in tree.files:
            continue
        for chapter in summary.parse_summary(Path(name), text=tree.read(name)).chapters:
            if not chapter.path:
                continue
            for node in mdscan.walk(mdscan.parse_blocks(tree.read(str(PurePosixPath(prefix, chapter.path))))):
                if isinstance(node, mdscan.Div) and model.kind_of(node) == "viz":
                    preset = (node.attrs.get("preset") or "").strip()
                    if viz.PRESET_RE.fullmatch(preset):
                        ident = (node.attrs.get("src") or "").strip()
                        cards.setdefault(ident, set()).add((lang, preset))
    return cards


def image_shards(tree, exports, *, previous=None, paths=(), full=False):
    """Schedule capture workers for changed capture inputs or changed published card sets."""
    slugs = {item['book'] for item in exports if item['target'] in ('pdf', 'epub')}
    shared = {"theme/tokens.json", "theme/generated/tokens.css", "package-lock.json",
              *("tools/node/" + name for name in (
                  "viz-thumbs.mjs", "viz-still-cache.mjs", "viz-common.mjs", "viz-server.mjs", "viz-testkit.mjs"))}
    # These Python inputs implement the published citation and generated token contracts.
    shared.update("tools/tbook/" + name + ".py" for name in
                  ("config", "mdscan", "model", "summary", "theme", "viz"))
    shared_change = bool(shared.intersection(paths)) or any(p.startswith("theme/viz/") for p in paths)
    items = []
    for slug in sorted(slugs):
        prefix = f"books/{slug}/"
        name = prefix + "viz/visualizations.json"
        if name not in tree.files:
            continue
        all_images = full or not previous or shared_change or any(p.startswith(prefix + "assets/") for p in paths)
        compare_cards = previous and not all_images and any(p in ("site.toml", prefix + "book.toml") or
                (p.startswith(prefix) and p.endswith(".md")) for p in paths)
        before = published_still_cards(previous, slug) if compare_cards else {}
        after = published_still_cards(tree, slug) if compare_cards else {}
        for entry in tree.json(name)["visualizations"]:
            if entry.get("status") != "live":
                continue
            ident = entry["id"]
            old = registry_entry(previous, slug, ident) or {}
            if (all_images or old.get("status") != "live" or
                    any(old.get(k) != entry.get(k) for k in ("thumbnail", "capture_lock")) or
                    before.get(ident) != after.get(ident) or
                    ("trureturing.lock.json" in paths and entry.get("capture_lock") != "links") or
                    any(p.startswith(f"{prefix}viz/{ident}/") for p in paths)):
                items.append(f"{slug}/{ident}")
    return shards(items, 12)


def signature(tree, runtime):
    runtime = viz_budget.runtime_identity(runtime)
    digest = hashlib.sha256(json.dumps([VERSION, runtime], sort_keys=True).encode())
    for entry in git(tree.root, "ls-tree", "-r", "-z", tree.sha).split(b"\0"):
        if not entry:
            continue
        name = entry.split(b"\t", 1)[1].decode()
        if name.startswith(".github/actions/") or name in (
                "package-lock.json", "requirements.txt", "theme/film/requirements.txt"):
            digest.update(entry + b"\0")
    return digest.hexdigest()


def api(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", endpoint], timeout=45))


def ancestor(root, base, head):
    return subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", base, head],
                          capture_output=True).returncode == 0


def deployed(repo, sha, get=api):
    """Require an active successful Pages deployment; CI coverage cannot substitute for it."""
    deployments = get(f"repos/{repo}/deployments?environment=github-pages&per_page=20")
    for deployment in deployments:
        if deployment.get("sha") != sha:
            continue
        statuses = get(f"repos/{repo}/deployments/{int(deployment['id'])}/statuses?per_page=1")
        if statuses and statuses[0].get("state") == "success":
            return True
    return False


def active_deployment(root, repo, limit, get=api):
    """Use the live deployment as the publication baseline even after artifact expiry."""
    for item in get(f"repos/{repo}/deployments?environment=github-pages&per_page=100"):
        sha = item.get("sha")
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) and ancestor(root, sha, limit):
            statuses = get(f"repos/{repo}/deployments/{int(item['id'])}/statuses?per_page=1")
            if statuses and statuses[0].get("state") == "success":
                return sha
    return None


def trusted_baseline(root, repo, branch, workflow, profile, sig, limit, *, get=api, download=None):
    """Only successful own-repository producers of the requested branch. Never PR artifacts/caches.

    PR/main/schedule consumers request the default branch. A manual branch's records
    stay scoped to that branch and can never supply default-branch coverage.

    Retention or API/history misses cause full fallback. A record in a failed/cancelled run
    cannot advance coverage, even when that run managed to upload an artifact before failing.
    """
    wf = get(f"repos/{repo}/actions/workflows/{workflow}.yml")
    if wf.get("path") != f".github/workflows/{workflow}.yml":
        return None
    query = urlencode(dict(branch=branch, status="success", per_page=100))
    runs = get(f"repos/{repo}/actions/workflows/{workflow}.yml/runs?{query}")["workflow_runs"]
    for run in runs:
        if not (run.get("workflow_id") == wf["id"] and run.get("head_repository", {}).get("full_name") == repo and
                run.get("head_branch") == branch and
                (trusted_cache.pages_producer(run) if workflow == "pages" else run.get("event") in ("push", "workflow_dispatch", "schedule")) and
                run.get("status") == "completed" and run.get("conclusion") == "success" and
                str(run.get("id")) != os.environ.get("GITHUB_RUN_ID")):
            continue
        if not ancestor(root, run["head_sha"], limit):
            continue
        artifacts = get(f"repos/{repo}/actions/runs/{int(run['id'])}/artifacts?per_page=100")["artifacts"]
        for a in artifacts:
            if a.get("name") != f"tbook-coverage-{profile}" or a.get("expired", True):
                continue
            if download:
                record = download(a["id"], profile)
            else:
                archive = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/artifacts/{int(a['id'])}/zip"], timeout=45)
                with zipfile.ZipFile(io.BytesIO(archive)) as z:
                    record = json.loads(z.read(f"{profile}.json"))
            comparable = record.get("signature") == sig
            if not comparable and "runtime" in record:
                # Older records hashed every tool source. Compare the producer tree's
                # environment instead; changed source responsibilities come from its diff.
                comparable = signature(Tree(root, run["head_sha"]), record["runtime"]) == sig
            if (record.get("schema") == SCHEMA and record.get("profile") == profile and comparable and
                    record.get("sha") == run["head_sha"] and record.get("run_id") == str(run["id"]) and
                    record.get("repository") == repo and record.get("ref") == f"refs/heads/{branch}" and
                    record.get("selector_version") == VERSION and record.get("run_attempt") == str(run.get("run_attempt", 1)) and
                    (profile != "pages" or (record.get("deployed") is True and
                                            deployed(repo, record.get("deployment_sha", ""), get)))):
                return dict(record, source_run=run["id"], artifact_id=a["id"])
    return None


def event_profiles(event, own, slow=False, workflow="ci"):
    if workflow == "pages":
        return ["pages"]
    if event == "schedule" and own:
        return ["slow"]
    return ["normal", "films", *(["slow"] if slow else [])]


def trusted_revision(root, repo, branch, workflow, limit):
    """A successful producer tree remains a diff baseline after artifacts expire."""
    wf = api(f"repos/{repo}/actions/workflows/{workflow}.yml")
    if wf.get("path") != f".github/workflows/{workflow}.yml":
        return None
    query = urlencode(dict(branch=branch, status="success", per_page=100))
    for run in api(f"repos/{repo}/actions/workflows/{workflow}.yml/runs?{query}")["workflow_runs"]:
        if (run.get("workflow_id") == wf["id"] and run.get("head_repository", {}).get("full_name") == repo and
                run.get("head_branch") == branch and
                (trusted_cache.pages_producer(run) if workflow == "pages" else run.get("event") in ("push", "workflow_dispatch", "schedule")) and
                run.get("status") == "completed" and run.get("conclusion") == "success" and
                str(run.get("id")) != os.environ.get("GITHUB_RUN_ID") and ancestor(root, run["head_sha"], limit)):
            return run["head_sha"]
    return None


def plan(root, *, event, payload, repo, branch, ref, workflow="ci", own=True, slow=False,
         mode="auto", base="", head="", get_baseline=trusted_baseline, get_revision=None, get_deployment=None, runtime="local"):
    if mode not in ("auto", "full"):
        raise ValueError("mode must be auto or full")
    current = Tree(root, "HEAD")
    if head and Tree(root, head).sha != current.sha:
        raise ValueError("requested head does not match checkout")
    profiles = event_profiles(event, own, slow, workflow)
    sig = signature(current, runtime)
    coverage_branch = ref.removeprefix("refs/heads/") if own and event == "workflow_dispatch" and ref.startswith("refs/heads/") else branch
    limit = current.sha
    pr_base = None
    reasons = []
    if event.startswith("pull_request"):
        pr = payload["pull_request"]
        pr_base, pr_head = Tree(root, pr["base"]["sha"]).sha, Tree(root, pr["head"]["sha"]).sha
        parents = git(root, "rev-list", "--parents", "-n", "1", current.sha).decode().split()[1:]
        if len(parents) != 2 or parents[1] != pr_head or not ancestor(root, pr_base, parents[0]):
            raise ValueError("PR checkout is not the event's base/head merge; refusing mismatched tested tree")
        if parents[0] != pr_base:
            reasons.append(f"PR tested base advanced from {pr_base} to {parents[0]}; replan actual merge")
        pr_base = parents[0]
        limit = pr_base
    selections, coverage = {}, {}
    execution, matrices, workloads = {}, {}, {}
    live_execution, live_workloads = {}, {}
    template = repo == "the-omega-institute/trureturing-books-template"
    deferred_films = workflow == "ci" and event == "push" and (ref == f"refs/heads/{branch}" or ref.startswith("refs/tags/"))
    # The tested merge parent and push "before" are independent of caches and coverage.
    before = payload.get("before") if workflow == "ci" and event == "push" else None
    created = before == "0" * 40
    first_branch_push = created and ref.startswith("refs/heads/") and not base
    comparison = base or pr_base or (before if not created else None)

    def lookup(producer, profile):
        try:
            return get_baseline(root, repo, coverage_branch, producer, profile, sig, limit)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
            reasons.append(f"{profile}/{producer}: baseline unavailable ({type(exc).__name__})")
            return None

    stills = []
    for profile in profiles:
        record = None
        if not comparison and not first_branch_push and mode != "full":
            for producer in (("ci", "pages") if profile == "films" else (workflow,)):
                candidate = lookup(producer, profile)
                if candidate and (not record or ancestor(root, record["sha"], candidate["sha"])):
                    record = candidate
        cost_record = record
        deployed_sha = None
        previous, paths = None, []
        try:
            previous = Tree(root, record["sha"]) if record else None
            paths = changed_paths(root, previous.sha, current.sha) if previous else []
        except subprocess.SubprocessError:
            previous, record, paths = None, None, []
            reasons.append(f"{profile}: incomplete Git coverage history; determine changed scope")
        if first_branch_push:
            paths = sorted(current.files)
        elif previous is None and mode != "full":
            revision = comparison
            if profile == "pages" and not revision and get_deployment:
                try:
                    deployed_sha = get_deployment(root, repo, limit)
                except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                    reasons.append(f"deployment lookup unavailable ({type(exc).__name__}); assemble the site")
                revision = deployed_sha
            if not revision and profile != "pages" and get_revision:
                try:
                    revision = get_revision(root, repo, coverage_branch, "pages" if profile == "films" else workflow, limit)
                except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                    reasons.append(f"{profile}: revision lookup unavailable ({type(exc).__name__}); use Git event")
            revision = revision or "HEAD^"
            try:
                previous = Tree(root, revision)
                if not ancestor(root, previous.sha, current.sha):
                    raise ValueError("comparison base is not an ancestor of the tested tree")
                paths = changed_paths(root, previous.sha, current.sha)
            except subprocess.SubprocessError as exc:
                raise ValueError("cannot determine changed scope; provide --base or explicitly request --mode full") from exc
            reasons.append(f"{profile}: Git diff from {previous.sha}; no inherited coverage")
        selected = impact(current, previous, paths, full=mode == "full", template=template)
        if profile == "normal":
            stills = image_shards(current, selected["exports"], previous=previous, paths=paths, full=mode == "full")
        if profile == "pages" and (event == "push" or not (record or deployed_sha)):
            # Advance the live commit even when all publication units can be reused.
            selected["site"] = True
        if not record:
            reasons.append(f"{profile}: explicit full" if mode == "full" else f"{profile}: changes only, without coverage artifact")
        if profile != "films" or not deferred_films:
            coverage[profile] = dict(schema=SCHEMA, selector_version=VERSION, ref=ref, profile=profile, sha=current.sha, signature=sig, runtime=runtime,
                                     repository=repo, run_id=os.environ.get("GITHUB_RUN_ID", "local"),
                                     run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
                                     inherited={k: record[k] for k in ("sha", "source_run", "artifact_id", "deployment_sha") if k in record} if record else None,
                                     paths=paths, comparison=previous.sha if previous else None)
        if profile == "pages" and deployed_sha:
            coverage[profile]["deployment_sha"] = deployed_sha
        if profile in ("normal", "slow"):
            if (comparison or mode == "full") and selected["suites"]:
                cost_record = lookup(workflow, profile)  # timings can only pack the selected work
            if not live_execution and (selected["suites"] or cost_record):
                live_execution, live_workloads = execution_inventory(current, with_workloads=True)
            live = {u: src for part in live_execution.values() for u, src in part.items()}
            raw_hints = cost_record.get("timings", {}) if cost_record and cost_record.get("runtime", runtime) == runtime else {}
            raw_hints = raw_hints if isinstance(raw_hints, dict) else {}
            hints = {u: raw_hints[u] for u, src in live.items() if viz_budget.valid_hint(raw_hints.get(u), src) and
                     isinstance(raw_hints[u].get("workload"), str)}
            coverage[profile]["timings"] = hints
            execution[profile] = {u: src for suite in selected["suites"] for u, src in live_execution[suite].items()}
            workloads[profile] = {u: live_workloads[u] for u in execution[profile]}
            matrices[profile] = viz_budget.pack(execution[profile], hints, workloads[profile])
        selections[profile] = selected
    normal = selections.get("normal", {})
    if normal:
        normal["films"] = selections["films"]["films"]
    if workflow == "pages" and selections["pages"]["site"]:
        # Pages builds all consumers, including strict films, even when deployment is disabled.
        # A no-op Pages run must not advance film coverage using deployment coverage alone.
        coverage["films"] = dict(coverage["pages"], profile="films", inherited=None)
    film_items = (selections['pages']['films'] if workflow == 'pages' and selections['pages']['site']
                  else [] if deferred_films else normal.get("films", []))
    tasks = dict(validate=bool(normal and any(normal["checks"].values())), build=bool(normal.get("exports")),
                 browser=bool(normal.get('browser_tests')),
                 stills=bool(stills),
                 viz=bool(normal.get("suites")), **{"viz-slow": bool(selections.get("slow", {}).get("suites"))},
                 media=bool(normal.get("slides")), films=bool(film_items))
    result = dict(version=VERSION, event=event, entry="own" if own else "call", sha=current.sha, mode=mode,
                  profiles=profiles, coverage=coverage, selections=selections, tasks=tasks,
                  viz=matrices.get("normal", []), slow=matrices.get("slow", []), execution=execution, workloads=workloads,
                  browser_budget=dict(target=viz_budget.TARGET, ceiling=viz_budget.CEILING, reserve=viz_budget.RESERVE, margin=viz_budget.MARGIN),
                  films=shards(film_items, MAX_FILM_SHARDS), browser=shards(normal.get('browser_tests', []), 8),
                  stills=stills,
                  exports=export_matrix(normal.get("exports", [])), slides=normal.get("slides", []),
                  site=selections.get("pages", {}).get("site", False), deferred_films=normal.get("films", []) if deferred_films else [],
                  publish=own and not event.startswith("pull_request") and (ref == f"refs/heads/{branch}" or
                          (event == "workflow_dispatch" and ref.startswith("refs/heads/"))), baseline_branch=coverage_branch, reasons=reasons)
    return result


def verify_results(plan, results, *, pages=False, pages_enabled=True):
    expected = {"plan": True}
    expected.update({"probe": plan["site"], "films": bool(plan.get('films')), "build": plan["site"],
                     "deploy": plan["site"] and pages_enabled} if pages else plan["tasks"])
    failures = [f"{job}: expected success, got {results.get(job, {}).get('result', 'missing')}"
                for job, selected in expected.items() if selected and results.get(job, {}).get("result") != "success"]
    if failures:
        raise ValueError("; ".join(failures))


def write_outputs(result):
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        fields = dict(plan=result, site=result["site"], publish=result["publish"],
                      **{k.replace("-", "_"): v for k, v in result["tasks"].items()},
                      build_matrix={"include": result["exports"]}, viz_matrix={"include": result["viz"]},
                      slow_matrix={"include": result["slow"]}, film_matrix={"include": result["films"]},
                      still_matrix={"include": result["stills"]}, browser_matrix={"include": result["browser"]})
        with open(output, "a", encoding="utf-8") as f:
            for key, value in fields.items():
                f.write(f"{key}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        body = json.dumps(result, ensure_ascii=False, indent=2)
        if len(body.encode("utf-8")) > 512 * 1024:
            body = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        if len(body.encode("utf-8")) <= 512 * 1024:
            body = "```json\n" + body + "\n```\n"
        else:
            body = "Plan exceeds the summary display budget; see ci-plan.json for the complete plan.\n"
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### CI selection\n\n" + body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("ci", "pages"), default="ci")
    parser.add_argument("--mode", default=os.environ.get("SELECTION_MODE") or "auto")
    parser.add_argument("--base", default=os.environ.get("SELECTION_BASE", ""))
    parser.add_argument("--head", default=os.environ.get("SELECTION_HEAD", ""))
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--needs-file", type=Path, default=Path("ci-needs.json"))
    args = parser.parse_args()
    if args.verify:
        results = json.loads(args.needs_file.read_text(encoding="utf-8"))
        # Use the plan from this exact needs fanout; do not maintain a second copy.
        result = json.loads(results["plan"]["outputs"]["plan"])
        verify_results(result, results, pages=args.workflow == "pages", pages_enabled=os.environ.get("PAGES_ENABLED") == "true")
        reports = [json.loads(p.read_text()) for p in Path("viz-reports").rglob("*.json")]
        viz_budget.merge_reports(result, reports)
        Path("coverage").mkdir(exist_ok=True)
        for profile, record in result["coverage"].items():
            if profile == "pages":
                record["deployed"] = not result["site"] or os.environ.get("PAGES_ENABLED") == "true"
                record["deployment_sha"] = result["sha"] if result["site"] else record.get("deployment_sha") or record["inherited"]["deployment_sha"]
            # Keep ancestry metadata bounded; retain authoritative run/artifact IDs, not recursively nested records.
            if record["inherited"]:
                record["inherited"] = {k: record["inherited"][k] for k in ("sha", "source_run", "artifact_id")}
            Path(f"coverage/{profile}.json").write_text(json.dumps(record, indent=2) + "\n")
        return
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()) if os.environ.get("GITHUB_EVENT_PATH") else {}
    branch = payload.get("repository", {}).get("default_branch", "main")
    workflow_ref = os.environ.get("CI_WORKFLOW_REF", "")
    own = not workflow_ref or f"/.github/workflows/{args.workflow}.yml@" in workflow_ref
    runtime = {k: os.environ.get(k, "") for k in ("ImageOS", "ImageVersion", "TBOOK_TOOLCHAIN")}
    result = plan(Path.cwd(), event=event, payload=payload, repo=os.environ.get("GITHUB_REPOSITORY", "local/repo"),
                  branch=branch, ref=os.environ.get("GITHUB_REF", "local"), workflow=args.workflow, own=own,
                  slow=os.environ.get("SLOW_FRAMES") == "true", mode=args.mode, base=args.base, head=args.head, runtime=runtime,
                  get_revision=trusted_revision, get_deployment=active_deployment)
    Path("ci-plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write_outputs(result)
    jobs = [name for name, selected in result["tasks"].items() if selected]
    print("Selected CI jobs:", ", ".join(jobs) or "none", "(details in ci-plan.json)")


if __name__ == "__main__":
    main()
