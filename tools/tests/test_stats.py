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

    def test_cli_artifacts_are_opt_in_scoped_and_refreshed_without_source_changes(self):
        with Repo() as repo:
            one = repo.book('one')
            repo.book('two')
            sources = snapshot(repo.root)
            code, _, err = repo.run_cli('stats', '--book', 'one')
            self.assertEqual(code, 0, err)
            self.assertEqual(snapshot(repo.root), sources)
            code, out, err = repo.run_cli('stats', '--book', 'one', '--write', '--json')
            self.assertEqual(code, 0, err)
            target = repo.root / 'build/statistics/one.json'
            self.assertEqual(json.loads(target.read_text()), json.loads(out)[0])
            self.assertFalse((repo.root / 'build/statistics/two.json').exists())
            exported = target.read_bytes()
            stamp = target.stat().st_mtime_ns
            code, _, err = repo.run_cli('stats', '--book', 'one', '--write')
            self.assertEqual(code, 0, err)
            self.assertEqual(target.read_bytes(), exported)
            self.assertEqual(target.stat().st_mtime_ns, stamp)
            write(one.primary.dir / 'ch01.md', '# One\n\n::: {.problem #open}\nOpen.\n:::\n')
            edited = snapshot(repo.root / 'books')
            code, _, err = repo.run_cli('stats', '--book', 'one', '--write')
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(target.read_text())['environments']['problem'], 1)
            self.assertEqual(snapshot(repo.root / 'books'), edited)

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


class StatisticsViewsTests(unittest.TestCase):
    def populate(self, repo):
        book = repo.book(summaries={lang: '# Summary\n\n- [One](ch01.md)\n  - [Child](ch01-child.md)\n'
                                    for lang in ('zh', 'en')})
        for edition in book.editions:
            write(edition.dir / 'ch01.md', f'''# One

::: {{.theorem #one lean="{A}"}}
A.
:::

::: {{.lemma #reuse lean="{A}"}}
A again.
:::

::: {{.stats src="summary"}}
:::

::: {{.stats src="declarations" display="link" format="csv" group="theorems"}}
Declaration data
:::

[Carrier](lean:{D})
''')
            write(edition.dir / 'ch01-child.md', f'# Child\n\n[Reuse](lean:{A})\n')
        return book

    def test_views_distinguish_occurrences_unique_declarations_and_chapter_reuse(self):
        with Repo() as repo:
            book = self.populate(repo)
            data = stats.collect(book, lock=lock())
            _, summary = stats.table(data, 'summary', 'en')
            self.assertEqual(summary[0][1], 2)
            self.assertEqual(summary[1][1], 2)
            _, chapters = stats.table(data, 'chapters', 'en')
            self.assertEqual(chapters, [['ch01.md', 2, 2, 1, 2]])
            _, pages = stats.table(data, 'pages', 'en')
            self.assertEqual(len(pages), 2)
            _, declarations = stats.table(data, 'declarations', 'en', 'theorems')
            self.assertEqual(declarations, [[A, 'theorem', 3]])
            _, reuse = stats.table(data, 'reuse', 'en')
            self.assertEqual(reuse[0], [A, 2, 3])
            for view in stats.VIEWS:
                for fmt in stats.FORMATS:
                    self.assertTrue(stats.artifact_content(data, view, 'zh', fmt))

    def test_cli_selects_multiple_artifact_views_formats_and_languages_without_writing_sources(self):
        from tbook import lean
        with Repo() as repo:
            book = self.populate(repo)
            before = snapshot(book.dir)
            with mock.patch.object(lean.Lock, 'load', return_value=lock()):
                code, out, err = repo.run_cli('stats', '--write', '--view', 'summary', '--view', 'kinds',
                                              '--format', 'markdown', '--format', 'csv', '--lang', 'zh', '--lang', 'en')
            self.assertEqual(code, 0, err)
            generated = sorted((repo.root / 'build/statistics/demo').glob('*'))
            self.assertEqual(len(generated), 8)
            self.assertTrue((repo.root / 'build/statistics/demo.json').is_file())
            self.assertEqual(snapshot(book.dir), before)
            times = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in generated}
            with mock.patch.object(lean.Lock, 'load', return_value=lock()):
                code, _, err = repo.run_cli('stats', '--write', '--view', 'summary', '--view', 'kinds',
                                            '--format', 'markdown', '--format', 'csv', '--lang', 'zh', '--lang', 'en')
            self.assertEqual(code, 0, err)
            self.assertEqual(times, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in generated})

    def test_embeds_and_download_links_share_generated_data_for_both_targets(self):
        from tbook import model, render
        with Repo() as repo:
            book = self.populate(repo)
            site = config.load_site()
            edition = book.editions[1]
            parsed = model.load_edition(edition)
            before = snapshot(book.dir)
            for target in ('mdbook', 'pandoc'):
                ctx = render.RenderContext(site, book, edition, parsed, lock(), target=target)
                text = render.chapter_markdown(parsed.chapters[0], ctx)
                self.assertIn('| Lean-verified formal environments | 2 |', text)
                self.assertIn('[Declaration data](_book/statistics/declarations.theorems.en.csv)', text)
                self.assertIn('summary.en.md', ' '.join(ctx.book_texts))
                data = ctx.book_texts['statistics/declarations.theorems.en.csv']
                self.assertIn(A, data)
                self.assertNotIn(D, data)
                self.assertEqual(ctx.statistics_data['environments']['lean_verified'], 2)
            self.assertEqual(snapshot(book.dir), before)

    def test_invalid_options_and_multilingual_selection_are_checked_before_building(self):
        from tbook import check, model
        from tbook.mdscan import Attrs
        for values in ({'src': '../escape'}, {'src': 'summary', 'group': 'theorems'},
                       {'src': 'summary', 'display': 'frame'}, {'src': 'summary', 'format': 'html'},
                       {'src': 'summary', 'lean': A}, {'src': 'summary', 'limit': '5'}):
            self.assertIsNotNone(stats.check_options(Attrs(kv=values)))
        with self.assertRaises(config.ConfigError):
            stats.artifact_name('summary', '../outside', 'html')
        with Repo() as repo:
            book = self.populate(repo)
            models = model.load_book_models(book)
            self.assertEqual(check._env_signature(models['zh']), check._env_signature(models['en']))
            path = book.editions[1].dir / 'ch01.md'
            path.write_text(path.read_text().replace('group="theorems"', 'group="inline"'))
            models = model.load_book_models(book)
            self.assertNotEqual(check._env_signature(models['zh']), check._env_signature(models['en']))
            self.assertFalse((repo.root / 'build').exists())

    def test_html_and_publication_stages_publish_the_requested_artifact_links(self):
        from tbook import html, model, pandoc
        with Repo() as repo:
            book = self.populate(repo)
            edition = book.editions[1]
            path = edition.dir / 'ch01.md'
            path.write_text(path.read_text() + '\n::: {.stats src="evidence" display="link" format="markdown"}\n::: \n')
            parsed = model.load_edition(edition)
            site = config.load_site()
            before = snapshot(book.dir)
            html_stage = html.stage_edition(site, book, edition, parsed, lock(), root=repo.root / 'html-stage')
            csv = 'statistics/declarations.theorems.en.csv'
            self.assertTrue((html_stage.src / '_book' / csv).is_file())
            self.assertTrue((html_stage.src / '_book/statistics/evidence.en.md.txt').is_file())
            publication = pandoc.stage(site, book, edition, parsed, lock(), out_dir=repo.root / 'publication')
            self.assertTrue((publication.dir / '_book' / csv).is_file())
            self.assertIn(site.book_url('demo', 'en') + '/_book/' + csv, publication.book_md.read_text())
            self.assertEqual(snapshot(book.dir), before)
