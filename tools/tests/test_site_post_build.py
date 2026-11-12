"""Repository post-build hook contract, no external toolchain or network."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from tbook import site

class PostBuildTests(unittest.TestCase):
    def test_absent_command_does_nothing(self):
        with mock.patch.object(subprocess, "run") as run:
            site.post_build(SimpleNamespace(raw={}), Path("missing"))
        run.assert_not_called()

    def test_argument_array_cwd_and_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            out = root / "output with spaces"
            out.mkdir()
            script = root / "hook with spaces.py"
            script.write_text('import os, pathlib, sys; pathlib.Path(os.environ["TBOOK_SITE_OUT"], "receipt").write_text(str(pathlib.Path.cwd()) + "\\n" + sys.argv[1])')
            cfg = SimpleNamespace(root=root, raw={"site": {"post_build": [sys.executable, str(script), "literal $(false)"]}})
            site.post_build(cfg, out)
            self.assertEqual((out / "receipt").read_text(), str(root.resolve()) + "\n" + "literal $(false)")

    def test_failure_and_invalid_config_fail_build(self):
        with tempfile.TemporaryDirectory() as name:
            for cmd in ("echo no", [], [""], [1], [sys.executable, "-c", "raise SystemExit(9)"]):
                cfg = SimpleNamespace(root=Path(name), raw={"site": {"post_build": cmd}})
                with self.subTest(command=cmd), self.assertRaises(site.SiteError):
                    site.post_build(cfg, Path(name))
