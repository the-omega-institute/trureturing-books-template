"""Migration coverage for the module-sharded trureturing lock."""

import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tbook import lean, paths


class LockMigrationTests(unittest.TestCase):
    def test_v1_lock_is_split_and_second_run_is_idempotent(self):
        migration = runpy.run_path(str(paths.ROOT / "tools/migrations/v1.6.0.py"))["migrate"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "trureturing.lock.json"
            gid = "D5/S1/Example/Result.result"
            legacy.write_text(json.dumps({
                "schema": lean.LOCK_SCHEMA,
                "repo": "the-omega-institute/trureturing",
                "branch": "dev",
                "commit": "a" * 40,
                "pinned_at": "2026-01-01T00:00:00Z",
                "declarations": {gid: {"module": "D5/S1/Example/Result", "name": "Result.result",
                                      "kind": "theorem", "statement_id": "sha256:x"}},
            }) + "\n", encoding="utf-8")
            with mock.patch.object(paths, "LOCK_FILE", legacy):
                self.assertIn("split", migration(root)[0])
                pointer = json.loads(legacy.read_text(encoding="utf-8"))
                self.assertEqual(pointer["path"], "trureturing-lock")
                self.assertEqual(json.loads((root / "trureturing-lock/index.json").read_text())["schema"],
                                 lean.SHARDED_LOCK_SCHEMA)
                self.assertIn(gid, lean.Lock.load().declarations)
                self.assertEqual(migration(root), ["trureturing lock: already sharded"])


if __name__ == "__main__":
    unittest.main()
