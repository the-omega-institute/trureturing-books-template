"""Regression of lock-only changes, publication data and the conservative migration."""
import dataclasses
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tbook import config, film, paths, viz
from test_film import fake_lock, temp_book
from test_viz import fake_book


class PinSources(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is required for the preview server")
    def test_preview_lock_asset_returns_404_until_lock_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_book(root / "books", "x")
            lock = dataclasses.asdict(fake_lock())
            script = """
                import fs from 'node:fs';
                import path from 'node:path';
                import {startServer} from './tools/node/viz-server.mjs';
                const {server, origin} = await startServer();
                const url = `${origin}/site/x/viz/assets/trureturing.json`;
                try {
                    const missing = await fetch(url);
                    const absent = {status: missing.status, ok: missing.ok, body: await missing.text()};
                    fs.writeFileSync(path.join(process.env.TBOOK_ROOT, 'trureturing.lock.json'), process.argv[1]);
                    const restored = await fetch(url);
                    console.log(JSON.stringify({absent, restored: {
                        status: restored.status, ok: restored.ok,
                        type: restored.headers.get('content-type'), data: await restored.json()
                    }}));
                } finally {
                    server.closeAllConnections();
                    await new Promise(resolve => server.close(resolve));
                }
            """
            r = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(lock)],
                               cwd=paths.ROOT, env={**os.environ, "TBOOK_ROOT": str(root)},
                               capture_output=True, text=True, timeout=15)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(data["absent"], {"status": 404, "ok": False,
                                              "body": "404 /site/x/viz/assets/trureturing.json\n"})
            self.assertEqual(data["restored"], {"status": 200, "ok": True,
                                                "type": "application/json; charset=utf-8", "data": lock})

    def test_viz_publication_and_preview_read_changed_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = fake_book(root / "books", "x")
            lock = fake_lock()
            page = book.viz_dir / "fib-walk" / "index.html"
            # fake_book has no page; publish a small fixture through the actual build.
            page.parent.mkdir(parents=True, exist_ok=True)
            gid = next(iter(lock.declarations))
            page.write_text(f'<a href="#" data-lean-gid="{gid}">source</a>')
            source = page.read_bytes()
            for commit, line in (("a" * 40, 7), ("b" * 40, 83)):
                lock.commit = commit
                lock.declarations[gid]["line"] = line
                with mock.patch.object(viz, "_lock", return_value=lock), \
                     mock.patch.object(viz, "check_native", return_value=[]), \
                     mock.patch.object(viz, "live_entries", return_value=[{"id": "fib-walk"}]), \
                     mock.patch.object(viz, "hub_html", return_value="hub"), \
                     mock.patch.object(viz, "published_registry", return_value={}):
                    viz.build(config.load_site(), book, root / "out")
                published = (root / "out/fib-walk/index.html").read_text()
                self.assertIn(f"/blob/{commit}/", published)
                self.assertIn(f"#L{line}", published)
                data = json.loads((root / "out/assets/trureturing.json").read_text())
                self.assertEqual(data["commit"], commit)
                self.assertEqual(data["declarations"][gid]["line"], line)
                if shutil.which("node"):
                    (root / "trureturing.lock.json").write_text(json.dumps(dataclasses.asdict(lock)))
                    script = ("import {route} from './tools/node/viz-server.mjs';"
                              "process.stdout.write(route('/site/x/viz/assets/trureturing.json').body)")
                    r = subprocess.run(["node", "--input-type=module", "-e", script], cwd=paths.ROOT,
                                       env={**os.environ, "TBOOK_ROOT": str(root)}, capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(json.loads(r.stdout), data)
                self.assertEqual(page.read_bytes(), source)

    def test_film_current_basis_does_not_rewrite_historical_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = temp_book(Path(tmp))
            created = film.scaffold(book, "002-current", "当前", "Current")
            meta = json.loads(created[0].read_text())
            self.assertEqual(meta["publication_basis"], "pinned")
            self.assertNotIn("subject_commit", meta)
            source = created[0].read_bytes()
            f = film.get(book, "002-current")
            lock = fake_lock()
            with mock.patch.object(film, "_lock", return_value=lock):
                self.assert_film_updates(f, lock, created, source)

    def assert_film_updates(self, f, lock, created, source):
        for commit in ("a" * 40, "b" * 40):
            lock.commit = commit
            data = film.engine_data(f)
            self.assertEqual(data["film"]["publication_commit"], commit)
            self.assertEqual(data["pin"]["commit"], commit)
            self.assertEqual(created[0].read_bytes(), source)
        f.meta["subject_commit"] = "0123456789abcdef"
        self.assertEqual(film.engine_data(f)["film"]["subject_commit"], "0123456789abcdef")
        self.assertTrue(any("preserve subject_commit" in message
                            for severity, message in film.validate_meta(f.meta, f.dir, f.book, lock)
                            if severity == "warning"))


    def test_migration_is_idempotent_and_preserves_history(self):
        migrate = runpy.run_path(str(paths.TOOLS / "migrations/v0.5.0.py"))["migrate"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "trureturing.lock.json").write_text(json.dumps({"repo": "o/r"}))
            page = root / "books/x/viz/map/index.html"
            page.parent.mkdir(parents=True)
            old = '<a href="https://github.com/o/r/blob/old/X.lean" data-lean-gid="G">now</a>'
            historical = '<a href="https://github.com/o/r/blob/old/X.lean">historical</a>'
            page.write_text(old + historical)
            migrate(root)
            self.assertEqual(page.read_text(), old.replace('href="https://github.com/o/r/blob/old/X.lean"', 'href="#"') + historical)
            once = page.read_bytes()
            migrate(root)
            self.assertEqual(page.read_bytes(), once)
