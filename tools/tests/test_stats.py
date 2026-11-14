"""Publication statistics and deterministic book-owned derived data."""
import json
import subprocess
import unittest
from unittest import mock

from test_newbook import Repo, write, snapshot
from tbook import config, derived, lean, stats

A = 'D5/S3/Test.one'
B = 'D5/S3/Test.two'
D = 'D5/S3/Test.carrier'


def lock():
    return lean.Lock('owner/lean', 'dev', 'a' * 40, declarations={
        g: {'module': 'D5/S3/Test', 'name': g.rsplit('.', 1)[1], 'kind': k}
        for g, k in [(A, 'theorem'), (B, 'theorem'), (D, 'def')]})


class StatisticsTests(unittest.TestCase):
    def test_publication_parser_scope_reuse_and_evidence(self):
        with Repo() as repo:
            book = repo.book(summaries={x: '# Summary\n\n- [One](ch01.md)\n  - [Child](ch01-child.md)\n- [Index](index.md)\n' for x in ('zh', 'en')})
            write(book.editions[0].dir / 'ch01.md', f'''# One

::: {{.theorem #one lean="{A}"}}
A.
:::

::: {{.theorem #written status="written-proof"}}
Written.
:::

::: {{.example #carrier lean="{D}"}}
D.
:::

::: {{.problem #open}}
Open.
:::

```markdown
::: {{.theorem #fake lean="{B}"}}
```
''')
            write(book.editions[0].dir / 'ch01-child.md', f'# Child\n\n[Reuse](lean:{A})\n')
            write(book.editions[0].dir / 'index.md', f'# Index\n\n[Other book](lean:{B})\n\n::: {{.remark #index-note}}\n文献结果，未在本书形式化。\n:::\n')
            write(book.editions[0].dir / 'orphan.md', f'# Unpublished\n\n[Other](lean:{B})\n')
            with mock.patch.object(stats.model, 'media_cited_gids', return_value=[]):
                data = stats.collect(book, exclude=('index.md',), lock=lock())
            self.assertEqual(data['total'], 2)
            self.assertEqual(data['environments']['lean_verified'], 1)
            self.assertEqual(data['environments']['written_proof'], 1)
            self.assertEqual(data['environments']['problem'], 1)
            self.assertEqual(data['environments']['literature'], 1)
            self.assertEqual(data['groups']['theorems'], [A])
            self.assertEqual(data['groups']['definitions'], [D])
            self.assertNotIn(B, data['declarations'])
            self.assertEqual(data['chapters'][0]['top'], data['chapters'][1]['top'])
            self.assertEqual([c['via'] for c in data['declarations'][A]['citations']], ['environment', 'inline'])

    def test_unresolved_citation_fails_instead_of_inflating_verified_totals(self):
        with Repo() as repo:
            book = repo.book()
            write(book.editions[0].dir / 'ch01.md', '# One\n\n[Missing](lean:D5/S3/Test.missing)\n')
            with self.assertRaisesRegex(config.ConfigError, 'missing from'):
                stats.collect(book, lock=lock())

    def test_media_only_declaration_has_separate_provenance(self):
        with Repo() as repo:
            book = repo.book()
            with mock.patch.object(stats.model, 'media_cited_gids', return_value=[(book.dir / 'viz/x/index.html', 3, A)]):
                data = stats.collect(book, lock=lock())
            self.assertEqual(data['groups']['inline'], [A])
            self.assertEqual(data['declarations'][A]['citations'][0]['via'], 'media')
            self.assertEqual(data['environments']['lean_verified'], 0)

    def test_generator_check_is_read_only_and_failure_propagates(self):
        with Repo() as repo:
            book = repo.book()
            write(repo.root / 'generate.py', 'import sys\nfrom pathlib import Path\np=Path("generated.txt")\nif "--check" in sys.argv:\n    raise SystemExit(0 if p.exists() and p.read_text()=="fresh" else 1)\np.write_text("fresh")\n')
            book.raw['derived'] = {'command': ['python3', 'generate.py']}
            before = snapshot(repo.root)
            with self.assertRaises(config.ConfigError):
                derived.refresh(book, check=True)
            self.assertEqual(snapshot(repo.root), before)
            derived.refresh(book)
            before = snapshot(repo.root)
            derived.refresh(book, check=True)
            self.assertEqual(snapshot(repo.root), before)
            write(repo.root / 'generated.txt', 'corrupt')
            with self.assertRaises(config.ConfigError):
                derived.refresh(book, check=True)

    def test_cli_defaults_to_a_compact_summary(self):
        with Repo() as repo:
            repo.book()
            code, out, err = repo.run_cli('stats')
            self.assertEqual(code, 0, err)
            self.assertIn('0 distinct declarations', out)
            self.assertLess(len(out), 250)
            code, out, err = repo.run_cli('stats', '--json')
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)[0]['total'], 0)

    def test_invalid_hook_and_empty_books(self):
        with Repo() as repo:
            book = repo.book()
            derived.refresh(book, check=True)
            book.raw['derived'] = {'command': 'echo wrong'}
            with self.assertRaises(config.ConfigError):
                derived.refresh(book)
            book.raw.pop('derived')
            data = stats.collect(book, lock=lock())
            self.assertEqual(data['total'], 0)
