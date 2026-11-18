"""A stale container must fail before it can supply dependencies to a checkout."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_verification import action_steps, condition_values, gha_if

SCRIPT = Path(__file__).resolve().parents[1] / "container/prepare.py"
SPEC = importlib.util.spec_from_file_location("container_prepare", SCRIPT)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class ContainerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "checkout"
        self.image = Path(tmp.name) / "image"
        for root in (self.root, self.image):
            for name in prepare.INPUTS:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(name)
        for name in ("node_modules", ".cache/fonts"):
            (self.image / name).mkdir(parents=True)
        (self.image / "inputs.json").write_text(json.dumps(prepare.fingerprints(self.image)))

    def test_input_key_and_producer_follow_changed_files(self):
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=self.root).decode().strip()

        def commit():
            git("add", ".")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
            return git("rev-parse", "HEAD")

        git("init", "-q")
        source = commit()
        key = prepare.image_key(self.root)
        (self.root / "README.md").write_text("updated")
        commit()
        self.assertEqual(prepare.image_key(self.root), key)
        self.assertEqual(prepare.image_source(self.root), source)
        (self.root / "tools/install-tectonic.sh").write_text("new engine")
        new_source = commit()
        self.assertNotEqual(prepare.image_key(self.root), key)
        self.assertEqual(prepare.image_source(self.root), new_source)
        workflow = (SCRIPT.parents[2] / ".github/workflows/toolchain-image.yml").read_text()
        for path in prepare.IMAGE_INPUTS:
            pattern = path + "/**" if path == "tools/container" else path
            self.assertEqual(workflow.count("      - " + pattern + "\n"), 2, pattern)

    def test_matching_checkout_uses_image_dependencies_idempotently(self):
        prepare.prepare(self.root, self.image)
        prepare.prepare(self.root, self.image)
        self.assertEqual((self.root / "node_modules").resolve(), (self.image / "node_modules").resolve())
        self.assertEqual((self.root / ".cache/fonts").resolve(), (self.image / ".cache/fonts").resolve())

    def test_stale_dependency_or_model_setup_fails_before_linking(self):
        for name in prepare.INPUTS:
            with self.subTest(name=name):
                (self.root / name).write_text("changed")
                with self.assertRaisesRegex(ValueError, "Rebuild the image"):
                    prepare.prepare(self.root, self.image)
                self.assertFalse((self.root / "node_modules").exists())
                (self.root / name).write_text(name)

    def test_existing_directory_is_preserved_without_partial_links(self):
        target = self.root / ".cache/fonts"
        target.mkdir(parents=True)
        (target / "host-font").write_text("keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare.prepare(self.root, self.image)
        self.assertFalse((self.root / "node_modules").exists())
        self.assertEqual((target / "host-font").read_text(), "keep")

    def test_preinstalled_setup_skips_every_installer_and_toolchain_cache(self):
        steps = action_steps("setup")
        first = next(i for i, s in enumerate(steps) if s.get("id") == "toolchain")
        installers = [s for s in steps[first + 1:-1] if s["name"] != "Generate theme tokens"]
        self.assertGreater(len(installers), 10)
        for step in installers:
            cond = step.get("if", "")
            self.assertIn("steps.toolchain.outputs.preinstalled", cond, step["name"])
            cond = re.sub(r"hashFiles\([^)]*\)", "'h'", cond)
            for ctx in condition_values(cond):
                ctx["steps.toolchain.outputs.preinstalled"] = "true"
                self.assertFalse(gha_if(cond, event="push", ref="refs/heads/main", context=ctx), step["name"])
