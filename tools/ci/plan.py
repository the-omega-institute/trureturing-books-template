"""Plan CI before setup, using Git trees and successful, trusted coverage artifacts only.

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
import tomllib
from urllib.parse import urlencode
import zipfile

VERSION = 3
SCHEMA = "tbook-ci-coverage-v1"
DEPENDENCIES = "tbook-ci-dependencies-v1"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
JOBS = ("validate", "build", "viz", "viz-slow", "media", "films")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


class Tree:
    def __init__(self, root, ref):
        self.root = Path(root)
        self.sha = git(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
        self.files = set(git(root, "ls-tree", "-r", "--name-only", "-z", self.sha).decode().rstrip("\0").split("\0")) - {""}
        self.cache = {}

    def read(self, name):
        if name not in self.cache:
            self.cache[name] = git(self.root, "show", f"{self.sha}:{name}").decode()
        return self.cache[name]

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
                if not re.fullmatch(r"[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*", fm[1]):
                    raise ValueError(f"invalid film directory: {fm[1]}")
                meta = tree.json(f)
                scripts = meta.get("scripts", [])
                if not isinstance(scripts, list) or not all(isinstance(x, str) for x in scripts):
                    raise ValueError(f"{f}: invalid scripts")
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
        books[slug] = dict(suites=suites, films=films, slides=sorted(decks), deps=deps,
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


def imports(tree, suite):
    """Static local JS import closure, including model imports shared by suites and film scripts."""
    seen, pending = set(), [suite]
    while pending:
        p = pending.pop()
        if p in seen:
            continue
        seen.add(p)
        if p not in tree.files or not p.endswith((".js", ".mjs")):
            continue
        for spec in re.findall(r'(?:from\s*|import\s*(?:\(\s*)?)[\'"]([^\'"]+)[\'"]', tree.read(p)):
            if spec.startswith("."):
                import posixpath
                q = posixpath.normpath(str(PurePosixPath(p).parent / spec))
                if q not in seen:
                    pending.append(q)
    return seen


def shared_role(current, previous, path):
    """Only runtime roles with established loading/input contracts can narrow execution.

    A new vendor module has no old reader correspondence: even if the new core
    imports it, existing concrete suite declarations need not mention it yet.
    Deleted modules retain their old role; an unclassified rename endpoint falls
    through to full impact. Optional local i18n files are inputs even when absent.
    """
    if path == "theme/viz/solid-core.js":
        return "solid"
    if path in ("theme/viz/hub.js", "theme/viz/hub.css"):
        return "hub"
    if re.fullmatch(r"(?:theme/)?i18n/(?:zh|en)\.toml", path):
        return "localization"
    if (path.startswith("theme/viz/vendor/") and previous and path in previous.files and
            path in imports(previous, "theme/viz/solid-core.js") and
            (path not in current.files or path in imports(current, "theme/viz/solid-core.js"))):
        return "solid"
    return None


def impact(current, previous, paths, *, full=False, template=False):
    now, old = inventory(current), inventory(previous) if previous else {}
    all_suites = {s for b in now.values() for s in b["suites"]}
    all_films = {f for b in now.values() for f in b["films"]}
    all_slides = {s for b in now.values() for s in b["slides"]}
    selected_books, suites, films, slides = set(), set(), set(), set()
    checks = dict(unit=False, theme=False, structure=False, viz_static=False, slides_static=False,
                  compat=False, manifest=template)
    reasons = []
    site = False

    def shared_outputs(reason):
        nonlocal site
        reasons.append(reason)
        site = True
        checks.update({k: True for k in checks if k != "manifest"})
        checks["compat"] = template
        for slug in now:
            # publish_assets copies optional runtimes/vendor even for browser nonreaders.
            # Preserve complete export/static/deck responsibility independently of execution.
            selected_books.add(slug)
            slides.update(now[slug]["slides"])

    def everything(reason):
        shared_outputs(reason)
        suites.update(all_suites)
        films.update(all_films)

    if full:
        everything("full: explicit mode or unavailable comparable successful coverage")
    for p in paths:
        # Declared nonlocal dependencies apply even to otherwise documentary paths.
        for tree, books in ((current, now), (previous, old)):
            if tree is None:
                continue
            for slug, b in books.items():
                for suite in b["suites"]:
                    patterns = b["deps"].get(suite)
                    if ((patterns is not None and any(fnmatch.fnmatchcase(p, pat) for pat in patterns)) or
                            p in imports(tree, suite)):
                        if suite in all_suites:
                            suites.add(suite)
                            reasons.append(f"{p} -> suite {suite}")
                for film, meta in b["films"].items():
                    closure = set().union(*(imports(tree, script) for script in meta["scripts"])) if meta["scripts"] else set()
                    if p in closure or (meta["solid"] and (p == "theme/viz/solid-core.js" or p.startswith("theme/viz/vendor/"))):
                        if film in all_films:
                            films.add(film)
                            reasons.append(f"{p} -> film {film}")
        if p.startswith(("docs/", "skills/", ".claude/")) or ("/" not in p and p.endswith(".md")) or p in ("LICENSE", "template-manifest.json"):
            continue
        if p.startswith("books/"):
            parts = p.split("/")
            slug = parts[1] if len(parts) > 1 else ""
            if slug.startswith("example-"):
                # Tool tests copy example source fixtures even when the books are hidden.
                checks["unit"] = True
                checks["compat"] = template
                reasons.append(f"tool test example fixture: {p}")
            if slug not in now and slug not in old:
                # Hidden books do not participate; unrecognised files outside a book are uncertain.
                hidden = current.toml("site.toml").get("books", {}).get("hide", [])
                if any(fnmatch.fnmatchcase(slug, x) for x in hidden):
                    continue
                everything(f"unknown book path: {p}")
                continue
            site = True
            checks["structure"] = True
            if slug not in now:
                reasons.append(f"removed book: {slug}; Pages rebuild removes obsolete output")
                continue
            selected_books.add(slug)  # existing export keys include the entire book, all languages
            b = now[slug]
            local = "/".join(parts[2:])
            checks["viz_static"] = checks["slides_static"] = True
            # Unregistered suites have unknown file reads: widen to the owning book's suites.
            for suite in b["suites"]:
                if suite not in b["deps"] or (slug in old and suite not in old[slug]["deps"]):
                    suites.add(suite)
                    reasons.append(f"unregistered suite dependency -> {suite}")
            if local.startswith("viz/tests/") and p in all_suites:
                suites.add(p)
            elif local.startswith("viz/"):
                for suite in b["suites"]:
                    ident = PurePosixPath(suite).name.removesuffix(".test.mjs")
                    if local.startswith(f"viz/{ident}/") or local in ("viz/visualizations.json", "viz/tests/dependencies.json") or local.startswith("viz/assets/"):
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
                # Chapter citation frame geometry (stageFirstChecks) and academic slides read prose.
                suites.update(b["suites"])
                slides.update(b["slides"])
                languages = current.toml(f"books/{slug}/book.toml").get("book", {}).get("editions") or current.toml("site.toml").get("site", {}).get("languages", ["zh", "en"])
                if local == "book.toml" or local.split("/")[0] not in languages:
                    films.update(b["films"])
                    reasons.append(f"book metadata/resource or unknown local dependency: {p}")
            # Academic decks read chapters, figures and viz, beyond slides/ itself.
            for deck in b["slides"]:
                if f"books/{deck.split('/')[0]}/slides/{deck.split('/')[1]}/deck.toml" in current.files:
                    slides.add(deck)
            continue
        role = shared_role(current, previous, p)
        if role:
            shared_outputs(f"shared {role} input: {p}")
            for slug, b in now.items():
                for suite in b["suites"]:
                    # Both summaries must apply to the live reader. New or undeclared
                    # suites may read any shared resource, including via computed paths.
                    if suite not in b["deps"] or suite not in old.get(slug, {}).get("deps", {}):
                        suites.add(suite)
                        reasons.append(f"unknown shared reads -> {suite}")
            if role == "localization":
                # engine_data -> engine_strings reads both languages for every film,
                # including existing or newly created local overrides.
                films.update(all_films)
            continue
        if p.startswith(("tools/", "theme/", "templates/", ".github/", "i18n/")) or p in (
                "site.toml", "trureturing.lock.json", "package.json", "package-lock.json", "requirements.txt", "template.toml", "tbook"):
            everything(f"shared input: {p}")
        else:
            everything(f"unknown impact: {p}")
    # Any dependency-selected consumer also needs its book's structural/static checks and site publication.
    for item in suites | films | slides:
        slug = item.split("/")[1] if item.startswith("books/") else item.split("/")[0]
        if slug in now:
            selected_books.add(slug)
        checks["structure"] = True
        site = True
    checks["viz_static"] |= bool(suites)
    checks["slides_static"] |= bool(slides)
    exports = []
    for slug in sorted(selected_books):
        for output in now[slug]["outputs"]:
            target, _, variant = output.partition("-")
            exports.append(dict(name=f"{slug}-{output}", book=slug, target=target, variant=variant))
    return dict(checks=checks, books=sorted(selected_books), suites=sorted(suites), films=sorted(films),
                slides=sorted(slides), exports=exports, site=site, reasons=sorted(set(reasons)))


def signature(tree, runtime):
    digest = hashlib.sha256(json.dumps([VERSION, runtime], sort_keys=True).encode())
    for entry in git(tree.root, "ls-tree", "-r", "-z", tree.sha).split(b"\0"):
        if not entry:
            continue
        name = entry.split(b"\t", 1)[1].decode()
        if name.startswith(("tools/", ".github/actions/")) or name in (
                ".github/workflows/ci.yml", ".github/workflows/pages.yml", "package-lock.json", "requirements.txt", "theme/film/requirements.txt"):
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
                run.get("head_branch") == branch and run.get("event") in {"push", "workflow_dispatch", "schedule"} and
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
            if (record.get("schema") == SCHEMA and record.get("profile") == profile and record.get("signature") == sig and
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


def plan(root, *, event, payload, repo, branch, ref, workflow="ci", own=True, slow=False,
         mode="auto", base="", head="", get_baseline=trusted_baseline, runtime="local"):
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
    template = repo == "the-omega-institute/trureturing-books-template"
    deferred_films = event == "push" and (ref == f"refs/heads/{branch}" or ref.startswith("refs/tags/"))
    for profile in profiles:
        record = None
        if mode != "full":
            # A normal CI success may have deferred films. Only actual film responsibility
            # coverage, from CI or Pages, can discharge them; no deployment proof is needed
            # for a successful strict film build in an otherwise successful Pages run.
            for producer in (("ci", "pages") if profile == "films" else (workflow,)):
                try:
                    candidate = get_baseline(root, repo, coverage_branch, producer, profile, sig, limit)
                    if candidate and (not record or ancestor(root, record["sha"], candidate["sha"])):
                        record = candidate
                except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
                    reasons.append(f"{profile}/{producer}: baseline unavailable ({type(exc).__name__})")
        previous, paths = None, []
        try:
            if base and (not record or Tree(root, base).sha != record["sha"]):
                record = None
                reasons.append(f"{profile}: full fallback: requested base has no comparable successful coverage")
            previous = Tree(root, record["sha"]) if record else None
            paths = changed_paths(root, previous.sha, current.sha) if previous else []
            if pr_base and previous:
                # Union the cumulative PR diff, even if the merged tree cancels a base edit.
                merge_base = git(root, "merge-base", pr_base, payload["pull_request"]["head"]["sha"]).decode().strip()
                paths = sorted(set(paths) | set(changed_paths(root, merge_base, payload["pull_request"]["head"]["sha"])))
        except subprocess.SubprocessError:
            previous, record, paths = None, None, []
            reasons.append(f"{profile}: full fallback: incomplete Git comparison history")
        selected = impact(current, previous, paths, full=previous is None, template=template)
        if not record:
            reasons.append(f"{profile}: full fallback: no comparable successful baseline" if mode != "full" else f"{profile}: explicit full")
        if profile != "films" or not deferred_films:
            coverage[profile] = dict(schema=SCHEMA, selector_version=VERSION, ref=ref, profile=profile, sha=current.sha, signature=sig, runtime=runtime,
                                     repository=repo, run_id=os.environ.get("GITHUB_RUN_ID", "local"),
                                     run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
                                     inherited={k: record[k] for k in ("sha", "source_run", "artifact_id", "deployment_sha") if k in record} if record else None,
                                     paths=paths)
        selections[profile] = selected
    normal = selections.get("normal", {})
    if normal:
        normal["films"] = selections["films"]["films"]
    if workflow == "pages" and selections["pages"]["site"]:
        # Pages builds all consumers, including strict films, even when deployment is disabled.
        # A no-op Pages run must not advance film coverage using deployment coverage alone.
        coverage["films"] = dict(coverage["pages"], profile="films", inherited=None)
    film_items = [] if deferred_films else normal.get("films", [])
    tasks = dict(validate=bool(normal and any(normal["checks"].values())), build=bool(normal.get("exports")),
                 viz=bool(normal.get("suites")), **{"viz-slow": bool(selections.get("slow", {}).get("suites"))},
                 media=bool(normal.get("slides")), films=bool(film_items))
    result = dict(version=VERSION, event=event, entry="own" if own else "call", sha=current.sha, mode=mode,
                  profiles=profiles, coverage=coverage, selections=selections, tasks=tasks,
                  viz=shards(normal.get("suites", []), 8), slow=shards(selections.get("slow", {}).get("suites", []), 8),
                  films=shards(film_items, 4), exports=export_matrix(normal.get("exports", [])), slides=normal.get("slides", []),
                  site=selections.get("pages", {}).get("site", False), deferred_films=normal.get("films", []) if deferred_films else [],
                  publish=own and not event.startswith("pull_request") and (ref == f"refs/heads/{branch}" or
                          (event == "workflow_dispatch" and ref.startswith("refs/heads/"))), baseline_branch=coverage_branch, reasons=reasons)
    return result


def verify_results(plan, results, *, pages=False, pages_enabled=True):
    expected = {"plan": True}
    expected.update({"probe": True, "build": plan["site"], "deploy": plan["site"] and pages_enabled} if pages else plan["tasks"])
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
                      slow_matrix={"include": result["slow"]}, film_matrix={"include": result["films"]})
        with open(output, "a") as f:
            for key, value in fields.items():
                f.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("### CI selection\n\n```json\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("ci", "pages"), default="ci")
    parser.add_argument("--mode", default=os.environ.get("SELECTION_MODE") or "auto")
    parser.add_argument("--base", default=os.environ.get("SELECTION_BASE", ""))
    parser.add_argument("--head", default=os.environ.get("SELECTION_HEAD", ""))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = json.loads(os.environ["PLAN_JSON"])
        verify_results(result, json.loads(os.environ["RESULTS_JSON"]), pages=args.workflow == "pages", pages_enabled=os.environ.get("PAGES_ENABLED") == "true")
        Path("coverage").mkdir(exist_ok=True)
        for profile, record in result["coverage"].items():
            if profile == "pages":
                record["deployed"] = os.environ.get("PAGES_ENABLED") == "true"
                record["deployment_sha"] = result["sha"] if result["site"] else record["inherited"]["deployment_sha"]
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
                  slow=os.environ.get("SLOW_FRAMES") == "true", mode=args.mode, base=args.base, head=args.head, runtime=runtime)
    Path("ci-plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write_outputs(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
