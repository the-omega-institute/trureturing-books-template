"""Clean-checkout regeneration and Git policy for reproducible publication assets."""
import json
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest import mock
from types import SimpleNamespace

from test_newbook import Repo, write
from test_figure import SCRIPT
from test_buildcache import Scratch
from tbook import artifacts, buildcache, config, figure, model, paths, stats

MIGRATION = paths.ROOT / "tools/migrations/v1.0.0.py"


class SourceOnlyTests(unittest.TestCase):
    def test_export_keys_follow_figure_sources_after_rendered_copies_are_ignored(self):
        from tbook import slides
        with Scratch(git_repo=True) as repo, \
                mock.patch.object(paths, "TOKENS", repo.root / "theme/tokens.json"), \
                mock.patch.object(slides, "deck_names", return_value=[]), \
                mock.patch.object(slides, "base_path", return_value="/books/"), \
                mock.patch.object(buildcache, "node_version", return_value="22"):
            book = SimpleNamespace(slug="demo", dir=repo.root / "books/demo")
            site = SimpleNamespace(repo="owner/books", base_url="")
            write(repo.root / ".gitignore", "*.svg\n")
            script = write(book.dir / "figures/demo.py", "source v1")
            helper = write(paths.TOOLS / "figkit/draw.py", "renderer v1")
            palette = write(paths.TOKENS, "palette v1")
            rendered = write(book.dir / "slides/deck/img/demo.en.svg", "rendered v1")

            def keys():
                buildcache._clear_memos()
                return (buildcache.site_inputs(site).files(book.dir).key(),
                        buildcache.slides_unit(site, book, repo.root / "build/slides/demo").key)

            before = keys()
            rendered.write_text("rebuilt output")
            self.assertEqual(keys(), before)
            for source in (script, helper, palette):
                before = keys()
                source.write_text(source.read_text() + " changed")
                after = keys()
                self.assertTrue(all(a != b for a, b in zip(before, after)), source)

    def test_migration_preserves_sources_and_working_outputs_and_is_idempotent(self):
        with Repo() as repo:
            book = repo.book()
            write(book.dir / "figures/demo.py", SCRIPT)
            figure.build(book)
            write(book.dir / "slides/deck/slides.md", '<img src="img/demo.en.svg">')
            figure.build(book)
            write(book.dir / "assets/photo.jpg", "original")
            write(book.dir / "viz/demo/index.html", "authored page")
            write(book.dir / "viz/demo/thumb.jpg", "generated cover")
            write(book.dir / "viz/demo/fig-first.en.jpg", "generated still")
            write(book.dir / "viz/visualizations.json", json.dumps({"visualizations": [{"id": "demo"}]}))
            write(book.dir / "derived.json", "generated data")
            config_file = book.dir / "book.toml"
            config_file.write_text(config_file.read_text() + '\n[derived]\noutputs = ["derived.json"]\n')
            subprocess.run(["git", "init", "-q", str(repo.root)], check=True)
            subprocess.run(["git", "-C", str(repo.root), "add", "."], check=True)
            migrate = runpy.run_path(str(MIGRATION))["migrate"]
            migrate(repo.root)
            self.assertEqual(artifacts.tracked(config.load_books()), [])
            for name in ("figures/demo.en.svg", "viz/demo/thumb.jpg", "derived.json"):
                self.assertTrue((book.dir / name).is_file())
            tracked = subprocess.check_output(["git", "-C", str(repo.root), "ls-files"]).decode()
            self.assertIn("assets/photo.jpg", tracked)
            self.assertIn("figures/demo.py", tracked)
            ignore = (book.dir / ".gitignore").read_text()
            migrate(repo.root)
            self.assertEqual((book.dir / ".gitignore").read_text(), ignore)
            self.assertIn("/slides/deck/img/demo.en.svg", ignore)
            self.assertIn("/derived.json", ignore)
            # A clean checkout has no copy to discover: source references still recreate it.
            copy = book.dir / "slides/deck/img/demo.en.svg"
            copy.unlink()
            figure.build(book)
            self.assertTrue(copy.is_file())

    def test_statistics_reads_authored_template_without_generated_chapter(self):
        with Repo() as repo:
            book = repo.book(summaries={"zh": "# Summary\n\n- [Appendix](appendix-c.md)\n"})
            write(book.dir / "data/appendix-c.zh.md.in", "# Appendix\n\n::: {.remark #authored}\n{{total}} declarations.\n:::\n")
            book.raw["statistics"] = {"exclude": ["appendix-c.md"], "templates": {"appendix-c.md": "data/appendix-c.{lang}.md.in"}}
            data = stats.collect(book, lock=mock.Mock())
            self.assertEqual(data["environments"]["remark"], 1)
            self.assertEqual(data["declarations"], {})
            self.assertFalse((book.dir / "zh/appendix-c.md").exists())
            self.assertFalse(model.load_edition(book.editions[0]).issues)

    def test_outputs_cannot_escape_book(self):
        with Repo() as repo:
            book = repo.book()
            book.raw["derived"] = {"outputs": ["../../trureturing.lock.json"]}
            with self.assertRaises(config.ConfigError):
                artifacts.outputs(book)

    def test_cached_capture_units_are_restored_without_launching_browser(self):
        with Repo() as repo:
            book = repo.book()
            write(book.viz_dir / "visualizations.json", '{"visualizations":[{"id":"demo","status":"live"}]}')
            payload = [{"id": "demo", "key": "capture-key", "outputs": ["books/demo/viz/demo/thumb.jpg"]}]
            with mock.patch.object(buildcache.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(payload))):
                unit = buildcache.viz_units(book)[0]
            output = unit.outputs[0]
            write(output, "rendered once")
            buildcache.store(unit)
            output.unlink()
            render = mock.Mock(side_effect=AssertionError("browser must not launch"))
            self.assertEqual(buildcache.run(unit, render), "cached")
            self.assertEqual(output.read_text(), "rendered once")
            render.assert_not_called()
