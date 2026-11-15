"""Shared local/CI test selection. Python imports and explicit resource reads are inputs."""
from __future__ import annotations

import ast
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

# Non-Python reads and dynamically loaded modules cannot be recovered from imports.
# Keep these alongside the selector; new test constructors must declare such reads.
EXTRA = {
    "test_ci*": ["tools/ci/**", ".github/**"],
    "test_template*": ["template.toml", "tools/migrations/**", "templates/**", "books/example-*/**"],
    "test_migration*": ["tools/migrations/**"],
    "test_container": ["tools/container/**", ".github/**"],
    "test_verification": [".github/**"],
    "test_*pandoc": ["tools/filters/**", "theme/typst/**", "theme/epub/**"],
    "test_export_layout": ["tools/filters/**", "theme/epub/**", "tools/tests/epub-layout.mjs"],
    "test_pdf*": ["tools/filters/**", "theme/typst/**"],
    "test_*viz*": ["tools/node/viz*", "theme/viz/**", "templates/viz/**", "tools/tests/*harness.mjs"],
    "test_*film*": ["theme/film/**", "tools/tests/*harness.mjs"],
    "test_slides": ["theme/slides/**", "templates/slides/**", "tools/node/slides*"],
    "test_*fig*": ["tools/figkit/**", "templates/figure/**", "tools/node/figure*"],
    "test_html": ["theme/mdbook/**", "tools/node/**"],
}
BROWSER = {
    "test_site.BrowserLayoutTest": ["tools/tbook/site.py", "tools/tbook/html.py", "tools/tbook/mathrender.py",
                                    "theme/mdbook/**", "theme/site/**", "theme/tokens.json", "theme/generated/**"],
    "test_export_layout.EpubLayoutTest": ["tools/tbook/pandoc.py", "tools/tbook/mathrender.py",
        "tools/filters/**", "theme/epub/**", "tools/tests/epub-layout.mjs"],
    **{f"test_viz.{name}": ["tools/tbook/viz.py", "tools/node/viz*", "theme/viz/**", "templates/viz/**"]
       for name in ("RailGate", "StageViewGate", "CitedNoteBar", "KeysGate")},
    "test_viz_runtime.RuntimeRegressions": ["tools/node/viz*", "theme/viz/**", "tools/tests/*harness.mjs"],
    "test_slides.OwnBackgroundBuildTest": ["tools/node/slides*", "theme/slides/**", "templates/slides/**"],
    **{f"test_viz_solid.{name}": ["theme/viz/solid*", "theme/viz/vendor/**", "tools/tests/*solid*harness.mjs"]
       for name in ("SolidInTheBrowser", "SolidProgramsInTheBrowser")},
    **{f"test_viz_kit.{name}": ["theme/viz/**", "tools/node/viz*", "tools/tests/kit_harness.mjs"]
       for name in ("KitInTheBrowser", "FrozenAndCapitalsGate")},
    "test_film_solid.SolidShotInTheBrowser": ["theme/film/**", "theme/viz/solid*", "theme/viz/vendor/**",
                                            "tools/tests/film_solid_harness.mjs"],
    "test_figure_shots.ShotGeometryTests": ["tools/tbook/figure.py", "tools/figkit/**",
                                          "tools/tests/figure-shots.mjs"],
}
GLOBAL = ("requirements.txt", "package.json", "package-lock.json")
RESOURCE_INPUTS = {
    "tools/tbook/pandoc.py": ["tools/filters/**", "theme/typst/**", "theme/epub/**"],
    "tools/tbook/html.py": ["theme/mdbook/**"],
    "tools/tbook/figure.py": ["tools/figkit/**"],
    "tools/tbook/theme.py": ["theme/tokens.json", "theme/generated/**"],
}


def python_inputs(tree, source):
    """Follow repository imports in both production code and reusable test fixtures."""
    if not hasattr(tree, "_python_edges"):
        tree._python_edges = {}
    seen, pending = set(), [source]
    while pending:
        p = pending.pop()
        if p in seen or p not in tree.files or not p.endswith(".py"):
            continue
        seen.add(p)
        if p in tree._python_edges:
            pending.extend(tree._python_edges[p] - seen)
            continue
        edges = set()
        parsed = ast.parse(tree.read(p), filename=p)
        package = p.removesuffix(".py").split("/")[:-1]
        for node in ast.walk(parsed):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name.replace(".", "/") for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = "/".join(package[:len(package) - node.level + 1]) if node.level else ""
                base = "/".join(x for x in (prefix, (node.module or "").replace(".", "/")) if x)
                modules = [base, *(base + "/" + a.name for a in node.names)]
            for module in modules:
                for stem in (module, "tools/" + module, "tools/tests/" + module):
                    for candidate in (stem + ".py", stem + "/__init__.py"):
                        if candidate in tree.files:
                            edges.add(candidate)
        tree._python_edges[p] = edges
        pending.extend(edges - seen)
    return seen


def select(tree, previous, changed, *, full=False):
    tests = sorted(p for p in tree.files if p.startswith("tools/tests/test_") and p.endswith(".py"))
    ordinary, browser = [], []
    for test in tests:
        module = PurePosixPath(test).stem
        sources = set()
        patterns = [*GLOBAL]
        for view in (tree, previous):
            if view and test in view.files:
                sources.update(python_inputs(view, test))
        for glob, extra in EXTRA.items():
            if fnmatch.fnmatchcase(module, glob):
                patterns.extend(extra)
        for source, extra in RESOURCE_INPUTS.items():
            if source in sources:
                patterns.extend(extra)
        # Tests copying the canonical book consume it even when it is hidden.
        text = "\n".join(view.read(p) for view in (tree, previous) if view
                         for p in sources if p in view.files)
        if "example-monograph" in text:
            patterns.append("books/example-monograph/**")
        affected = full or bool(set(changed) & sources) or any(
            fnmatch.fnmatchcase(p, pat) for p in changed for pat in patterns)
        classes = [n for n in ast.parse(tree.read(test)).body if isinstance(n, ast.ClassDef)]
        for cls in classes:
            # Loading a fixture-only class is harmless, but do not include arbitrary helper objects.
            if not cls.bases:
                continue
            ident = module + "." + cls.name
            if ident in BROWSER:
                helpers = {p for p in sources if p.startswith("tools/tests/")}
                if full or bool(set(changed) & helpers) or any(fnmatch.fnmatchcase(p, pat)
                        for p in changed for pat in (*GLOBAL, "tools/tbook/doctor.py", "tools/tbook/paths.py",
                                                   *BROWSER[ident])):
                    browser.append(ident)
            elif affected and (any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
                                  for n in cls.body) or any(isinstance(b, ast.Name) for b in cls.bases)):
                ordinary.append(ident)
    return dict(unit_tests=sorted(ordinary), browser_tests=sorted(browser))


def run_tests(names, *, required=False):
    if not names:
        print("No affected tests.")
        return
    import unittest
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or (required and (result.skipped or not result.testsRun)):
        raise SystemExit(1)


class WorkingTree:
    def __init__(self, root):
        self.root, self.cache = Path(root), {}
        raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "--others",
                                       "--exclude-standard", "-z"])
        self.files = {p for p in raw.decode().split("\0") if p and (self.root / p).is_file()}

    def read(self, name):
        if name not in self.cache:
            self.cache[name] = (self.root / name).read_text(encoding="utf-8")
        return self.cache[name]

    def toml(self, name):
        import tomllib
        return tomllib.loads(self.read(name)) if name in self.files else {}

    def json(self, name):
        return json.loads(self.read(name))


def working_changes(root, ref):
    from ci import plan
    # Compare the working tree with the branch point; include staged, unstaged and new files.
    base = subprocess.check_output(["git", "-C", str(root), "merge-base", ref, "HEAD"]).decode().strip()
    old, current = plan.Tree(root, base), WorkingTree(root)
    diff = subprocess.check_output(["git", "-C", str(root), "diff", "--no-renames", "--name-only", "-z", base, "--"])
    changed = sorted(set(diff.decode().split("\0")) - {""} | (current.files - old.files))
    return old, current, changed


def local(args):
    from ci import plan
    root = Path(__file__).resolve().parents[2]
    old, current, changed = working_changes(root, args.base)
    selected = plan.impact(current, old, changed, full=args.full)
    print(json.dumps(dict(paths=changed, **selected), ensure_ascii=False, indent=2), flush=True)
    if args.list:
        return 0
    run_tests(selected["unit_tests"])
    run_tests(selected["browser_tests"], required=True)
    if selected["suites"]:
        subprocess.run(["node", "tools/node/viz-test.mjs", "--selection-env", "TBOOK_TEST_ITEMS",
                        *(["--slow"] if args.slow else [])], cwd=root, check=True,
                       env={**os.environ, "TBOOK_TEST_ITEMS": json.dumps(selected["suites"])})
    return 0
