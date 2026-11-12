"""Layer integration tests with local git releases; no network or build tools."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tbook import template as t
from test_template import GitEnv, git, write, tree_snapshot


class LayersTests(unittest.TestCase):
    def setUp(self):
        self.env = GitEnv().__enter__()
        self.tmp = tempfile.TemporaryDirectory(prefix="tbook-layers-")
        self.root = Path(self.tmp.name)
        self.up = self.root / "upstream"
        self.down = self.root / "downstream"
        self.up.mkdir()
        write(self.up / "template.toml", '''[template]
name = "base"
repo = "example/base"
version = "1.0.0"
[managed]
paths = ["tools/", "docs/", "skills/", ".github/workflows/", "template.toml"]
owned = ["books/", "site.toml", "PROJECT.md", "template.d/"]
exclude = ["docs/project/", "skills/local-", "docs/layer-", "skills/layer-", ".github/workflows/layer-"]
''')
        write(self.up / "docs/base.md", "base one\n")
        t.cmd_manifest(self.up, out=lambda _: None)
        shutil.copytree(self.up, self.down)
        git(self.down, "init", "-q")
        git(self.down, "add", ".")
        git(self.down, "commit", "-qm", "Created from template")
        write(self.down / "books/paper.txt", "paper owned\n")
        self.layer = self.make_layer("alpha")

    def tearDown(self):
        self.tmp.cleanup()
        self.env.__exit__()

    def make_layer(self, name, claims=None):
        src = self.root / name
        shutil.copytree(self.up, src)
        write(src / f"template.d/{name}.toml", f'''[template]
name = "{name}"
repo = "example/{name}"
version = "1.0.0"
[managed]
paths = {claims or [f"docs/layer-{name}/", f"skills/layer-{name}-task/", f".github/workflows/layer-{name}-check.yml"]!r}
'''.replace("'", '"'))
        write(src / f"docs/layer-{name}/guide.md", "layer one\n")
        write(src / f"skills/layer-{name}-task/SKILL.md", "task\n")
        write(src / f".github/workflows/layer-{name}-check.yml", "name: Check\n")
        return src

    def install(self, name="alpha", source=None, **kwargs):
        return t.update(self.down, source=str(source or self.layer), layer=name, install=True, **kwargs)

    def bump(self, src=None, name="alpha", version="1.1.0"):
        src = src or self.layer
        p = src / f"template.d/{name}.toml"
        p.write_text(p.read_text().replace('version = "1.0.0"', f'version = "{version}"'))
        write(src / f"docs/layer-{name}/guide.md", "layer two\n")

    def test_install_and_manifest_status(self):
        before = tree_snapshot(self.down)
        res = self.install(dry_run=True)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(before, tree_snapshot(self.down))
        self.assertEqual(self.install().exit_code, 0)
        self.assertTrue((self.down / "template.d/alpha.manifest.json").is_file())
        st = t.compute_status(self.down, t.TemplateConfig.load(self.down, "alpha"))
        self.assertFalse(st.modified or st.missing or st.extra)
        self.assertEqual(t.cmd_manifest(self.layer, layer="alpha", out=lambda _: None), 0)
        self.assertEqual(t.cmd_manifest(self.layer, layer="alpha", check=True, out=lambda _: None), 0)

    def test_update_preserves_upstream_and_owned(self):
        self.install()
        before = tree_snapshot(self.down)
        self.bump()
        res = t.update(self.down, source=str(self.layer), layer="alpha")
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.new_version, "1.1.0")
        self.assertEqual((self.down / "docs/layer-alpha/guide.md").read_text(), "layer two\n")
        after = tree_snapshot(self.down)
        changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
        self.assertEqual(changed, {"docs/layer-alpha/guide.md", "template.d/alpha.toml", "template.d/alpha.manifest.json"})

    def test_standalone_layer_source_manifest_and_install(self):
        source = self.root / "standalone"
        source.mkdir()
        cfg = t.TemplateConfig.load(self.layer, "alpha")
        for name in [cfg.config_path, *t.build_manifest(self.layer, cfg).files]:
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.layer / name, dest)
        self.assertFalse((source / "template.toml").exists())
        self.assertEqual(t.cmd_manifest(source, layer="alpha", out=lambda _: None), 0)
        self.assertEqual(t.cmd_manifest(source, layer="alpha", check=True, out=lambda _: None), 0)
        self.assertEqual(self.install(source=source).exit_code, 0)
        self.assertEqual((self.down / "docs/layer-alpha/guide.md").read_text(), "layer one\n")

    def test_conflict_dry_run_and_force(self):
        self.install()
        target = self.down / "docs/layer-alpha/guide.md"
        target.write_text("local\n")
        self.bump()
        before = tree_snapshot(self.down)
        res = t.update(self.down, source=str(self.layer), layer="alpha", dry_run=True)
        self.assertEqual(res.exit_code, 3)
        self.assertEqual(before, tree_snapshot(self.down))
        self.assertEqual(t.update(self.down, source=str(self.layer), layer="alpha").exit_code, 3)
        self.assertEqual(target.read_text(), "local\n")
        self.assertEqual(Path(str(target) + ".template-new").read_text(), "layer two\n")

    def test_upstream_keeps_layer_and_unlisted_extras(self):
        self.install()
        write(self.down / "docs/extra.md", "unlisted\n")
        st = t.compute_status(self.down)
        self.assertIn("docs/extra.md", st.extra)
        self.assertNotIn("docs/layer-alpha/guide.md", st.extra)
        before = tree_snapshot(self.down)
        write(self.up / "docs/base.md", "base two\n")
        self.assertEqual(t.update(self.down, source=str(self.up)).exit_code, 0)
        after = tree_snapshot(self.down)
        changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
        self.assertEqual(changed, {"docs/base.md", "template-manifest.json"})

    def test_path_claims_refused_before_writes(self):
        for path in ["tools/", "docs/", "docs/base.md", "books/", "template.d/", "../escape", "docs/layer-beta/",
                     "docs/project/", "docs/project/owned.md", "skills/local-task/"]:
            with self.subTest(path=path):
                p = self.layer / "template.d/alpha.toml"
                p.write_text('[template]\nname="alpha"\nversion="1.0.0"\n[managed]\npaths=["' + path + '"]\n')
                before = tree_snapshot(self.down)
                for force in (False, True):
                    with self.subTest(force=force), self.assertRaises(t.TemplateError):
                        self.install(force=force)
                self.assertEqual(before, tree_snapshot(self.down))

    def test_two_layers_and_overlap(self):
        self.install()
        beta = self.make_layer("beta")
        self.assertEqual(self.install("beta", beta).exit_code, 0)
        self.assertEqual([r["name"] for r in t.targets(self.down)], ["upstream", "alpha", "beta"])
        # Disjoint files need disjoint namespace claims, even if no file exists yet.
        for name in ("alpha", "beta"):
            p = self.down / f"template.d/{name}.toml"
            p.write_text(p.read_text().replace('[managed]', '[managed]').replace('paths = [', 'paths = ["shared/", '))
        with self.assertRaisesRegex(t.TemplateError, "overlaps"):
            t.validate_claims(self.down)

    def test_migrations_are_per_layer(self):
        self.install()
        self.bump()
        write(self.layer / "docs/layer-alpha/migrations/v1.1.0.py",
              'def migrate(root):\n    (root / "MIGRATED").write_text("alpha")\n    return ["alpha migration"]\n')
        write(self.layer / "tools/migrations/v1.1.0.py", 'raise RuntimeError("wrong namespace")\n')
        preview = t.update(self.down, source=str(self.layer), layer="alpha", dry_run=True)
        self.assertEqual(preview.pending_migrations, ["v1.1.0.py"])
        self.assertFalse((self.down / "MIGRATED").exists())
        res = t.update(self.down, source=str(self.layer), layer="alpha")
        self.assertEqual(res.exit_code, 0)
        self.assertEqual((self.down / "MIGRATED").read_text(), "alpha")

    def test_git_history_deletion_and_never_installed(self):
        self.install()
        git(self.down, "add", ".")
        git(self.down, "commit", "-qm", "Install layer")
        target = self.down / "docs/layer-alpha/guide.md"
        target.unlink()
        git(self.down, "add", "-A")
        git(self.down, "commit", "-qm", "Delete layer guide")
        self.assertEqual(t.update(self.down, source=str(self.layer), layer="alpha").exit_code, 0)
        self.assertFalse(target.exists())
        # A copied manifest for files absent from every reachable commit installs them.
        write(self.layer / "docs/layer-alpha/new.md", "new\n")
        cfg = t.TemplateConfig.load(self.layer, "alpha")
        (self.down / cfg.manifest_path).write_text(t.build_manifest(self.layer, cfg).to_json())
        self.assertEqual(t.update(self.down, source=str(self.layer), layer="alpha").exit_code, 0)
        self.assertTrue((self.down / "docs/layer-alpha/new.md").exists())

    def test_release_selection_never_backwards(self):
        git(self.layer, "init", "-q")
        t.cmd_manifest(self.layer, layer="alpha", out=lambda _: None)
        git(self.layer, "add", ".")
        git(self.layer, "commit", "-qm", "Layer release")
        git(self.layer, "tag", "v1.0.0")
        self.assertEqual(self.install().exit_code, 0)
        p = self.down / "template.d/alpha.toml"
        p.write_text(p.read_text().replace('version = "1.0.0"', 'version = "1.1.0"'))
        before = tree_snapshot(self.down)
        res = t.update(self.down, source=str(self.layer), layer="alpha")
        self.assertEqual(res.no_update, "not_newer_older")
        self.assertEqual(before, tree_snapshot(self.down))
        # Same version with a different manifest also leaves a newer snapshot alone.
        p.write_text(p.read_text().replace('version = "1.1.0"', 'version = "1.0.0"'))
        m = self.down / "template.d/alpha.manifest.json"
        m.write_text(m.read_text().replace('"files": {', '"files": {"extra": {"sha256": "x", "mode": "100644"},'))
        self.assertEqual(t.update(self.down, source=str(self.layer), layer="alpha").no_update, "not_newer_same")
        self.assertFalse(t.update(self.down, source=str(self.layer), layer="alpha", to="v1.0.0").no_update)

    def test_custom_layer_tag_prefix(self):
        path = self.layer / "template.d/alpha.toml"
        path.write_text(path.read_text().replace('[managed]', 'tag_prefix = "alpha-"\n[managed]'))
        git(self.layer, "init", "-q")
        git(self.layer, "add", ".")
        git(self.layer, "commit", "-qm", "Layer with its own release namespace")
        git(self.layer, "tag", "alpha-1.0.0")
        self.assertEqual(self.install().exit_code, 0)
        self.assertEqual(t.TemplateConfig.load(self.down, "alpha").tag_prefix, "alpha-")

    def test_linked_layer_metadata_refused_before_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.down / "template.d").symlink_to(outside, target_is_directory=True)
        before = tree_snapshot(self.down)
        with self.assertRaisesRegex(t.TemplateError, "real downstream-owned directory"):
            self.install()
        self.assertEqual(before, tree_snapshot(self.down))
        self.assertFalse(list(outside.iterdir()))
