"""Academic citation policy, TeX token boundaries, edition subsets and publication.

Use the existing synthetic-lock fixtures, never depend on example books or upstream.
"""
import json
import unittest
from unittest import mock

from test_newbook import Repo, write
from test_slides import FAKE_THM, FAKE_DEF, fake_lock
from test_figure import SCRIPT
from tbook import academic, buildcache, config, figure, lean, model, paths, slides


class AcademicTests(unittest.TestCase):
    def prepare(self, repo):
        book = repo.book()
        chapter = (f'# One\n\n::: {{.theorem #thm-one title="A $x$ bound" lean="{FAKE_THM}"}}\nStatement.\n:::\n\n'
                   f'::: {{.definition #def-one title="Definition" lean="{FAKE_DEF}"}}\nDefinition.\n:::\n\n'
                   '::: {.problem #prob-one title="An open question"}\nQuestion.\n:::\n')
        for lang in book.languages:
            write(book.dir / lang / 'ch01.md', chapter)
        deck = book.slides_dir / 'talk'
        write(deck / 'deck.toml', 'kind="academic"\neditions=["en"]\n[title]\nen="Talk"\n')
        self.source = write(deck / 'slides.tex', r'''
            \documentclass{beamer}
            \input{tbook-deck}
            \begin{document}
            \begin{frame}[t]{A title with {nested} groups}
              \begin{bookresult}{thm-one}Statement\end{bookresult}
              \note{Notes are in the same source.}
            \end{frame}
            \appendix
            \FormalVerification
            \end{document}
        ''')
        return book

    def errors(self, book, lock=None):
        return '\n'.join(x.message for x in academic.check_deck(book, 'talk', lock or fake_lock()))

    def test_subset_and_scaffold_file_ownership(self):
        with Repo() as repo:
            book = self.prepare(repo)
            self.assertEqual(self.errors(book), '')
            self.assertEqual(slides.deck_langs(book, 'talk'), ['en'])
            self.assertIsNone(slides.check_ref(book, 'talk'))
            self.assertEqual(slides.read_edition(book, 'talk', 'en').count, 2)
            self.assertEqual(academic.cited_gids(book, 'talk')[0][2], FAKE_THM)
            academic.scaffold(['demo', 'new-talk', 'English', 'Chinese', '--academic', '--editions', 'en,zh', '--aspect', '16:9'])
            directory = book.slides_dir / 'new-talk'
            self.assertTrue((directory / 'slides.tex').is_file())
            self.assertTrue((directory / 'slides.zh.tex').is_file())
            self.assertFalse((directory / 'slides.en.tex').exists())
            self.assertEqual(academic.settings(book, 'new-talk')['aspect'], '16:9')

    def test_descriptor_title_metadata_and_navigation_option(self):
        with Repo() as repo:
            book = self.prepare(repo)
            descriptor = book.slides_dir / 'talk/deck.toml'
            original = descriptor.read_text()
            descriptor.write_text('institution="Example seminar"\ncoauthors="Example contributors"\ndate="Seminar"\nnavigation_symbols=true\n' + original)
            data = academic.settings(book, 'talk')
            self.assertTrue(data['navigation_symbols'])
            self.assertEqual(data['institution'], 'Example seminar')
            descriptor.write_text('navigation_symbols="yes"\n' + original)
            with self.assertRaisesRegex(ValueError, 'navigation_symbols must be a boolean'):
                academic.settings(book, 'talk')

    def test_ledger_paginates_twelve_distinct_results_with_matching_frame_counts(self):
        with Repo() as repo:
            book = self.prepare(repo)
            chapter = book.dir / 'en/ch01.md'
            # Synthetic ids/lock fixtures only; multiple book results can cite the same GID.
            chapter.write_text(chapter.read_text() + ''.join(
                f'\n::: {{.theorem #thm-extra-{i} lean="{FAKE_THM}"}}\nStatement.\n:::\n'
                for i in range(12)))
            out = repo.root / 'generated'
            out.mkdir()
            for size, pages in ((12, 1), (13, 2)):
                ids = ['thm-one'] + [f'thm-extra-{i}' for i in range(size - 1)]
                self.source.write_text(r'\input{tbook-deck}\begin{frame}' + ''.join(
                    rf'\begin{{bookresult}}{{{ident}}}Statement.\end{{bookresult}}' for ident in ids + [ids[0]])
                    + r'\end{frame}\appendix\FormalVerification')
                source = academic.read_source(book, 'talk', 'en')
                self.assertEqual(source.count, 1 + pages)
                academic.generate_package(book, 'en', source, fake_lock(), out)
                generated = (out / 'tbook-lean.sty').read_text()
                self.assertEqual(generated.count('Formal verification}'), pages)
                self.assertEqual(generated.count('Pinned source:'), pages)
                self.assertEqual(generated.count(r'\rule{0pt}{8pt}'), size)
                self.assertEqual(generated.count(r'\begin{tabular}'), pages)
                self.assertIn('Source (Lean / DOI / request)', generated)

    def test_tex_comments_verbatim_escapes_and_optional_arguments(self):
        text = r'''
            % \begin{bookresult}{bad-comment}
            \verb|% \begin{bookresult}{bad-verb}|
            \verb*+\begin{bookresult}{bad-star}+
            \begin{verbatim}
            % comments are literal here
            \begin{bookresult}{bad-environment}
            \end{verbatim}
            \begin{frame}<1->[fragile,environment={foo[bar]}]{Title}
            A literal \% does not hide \begin{bookresult}% line end is removed
            {thm-one}x\end{bookresult}
            \end{frame}
        '''
        calls = academic.commands(text)
        self.assertEqual([c.args[1] for c in calls if c.name == 'begin' and len(c.args) == 2], ['thm-one'])
        self.assertEqual(sum(c.name == 'begin' and c.args == ['frame'] for c in calls), 1)
        with self.assertRaisesRegex(ValueError, 'unclosed'):
            academic.commands(r'\begin{bookresult}{thm-one')

    def test_unknown_result_and_computed_id_fail(self):
        with Repo() as repo:
            book = self.prepare(repo)
            original = self.source.read_text()
            self.source.write_text(original.replace('thm-one', 'thm-unknown'))
            self.assertIn('unknown result id', self.errors(book))
            self.source.write_text(original.replace('thm-one', r'\myresult'))
            self.assertIn('literal book result id', self.errors(book))
            self.source.write_text(original.replace('{thm-one}', '[status=verified]{thm-one}'))
            self.assertIn('takes no options', self.errors(book))

    def test_unresolved_wrong_kind_and_open_gid_fail(self):
        with Repo() as repo:
            book = self.prepare(repo)
            lock = fake_lock()
            lock.declarations = {}
            self.assertIn('UNVERIFIED', self.errors(book, lock))
            lock = fake_lock()
            lock.declarations[FAKE_THM] = dict(lock.declarations[FAKE_THM], kind='def')
            self.assertIn('not a verified theorem', self.errors(book, lock))
            self.source.write_text(self.source.read_text().replace('thm-one', 'prob-one'))
            p = book.dir / 'en/ch01.md'
            p.write_text(p.read_text().replace('#prob-one title=', f'#prob-one lean="{FAKE_THM}" title='))
            self.assertIn('open problem #prob-one must not have a GID', self.errors(book))

    def test_generated_titles_badges_links_and_ledger_use_lock(self):
        with Repo() as repo:
            book = self.prepare(repo)
            self.source.write_text(self.source.read_text().replace(r'\appendix', r'\begin{bookresult}{def-one}D\end{bookresult}\begin{bookresult}{prob-one}Q\end{bookresult}\appendix'))
            source = academic.read_source(book, 'talk', 'en')
            out = repo.root / 'generated'
            out.mkdir()
            academic.generate_package(book, 'en', source, fake_lock(), out)
            text = (out / 'tbook-lean.sty').read_text()
            self.assertIn('Theorem 1.1 (A $x$ bound)', text)
            self.assertIn('Lean $\\checkmark$', text)
            self.assertIn('LEAN DEF', text)
            self.assertIn('OPEN', text)
            self.assertIn('\\#L1', text)
            self.assertIn('blob/' + '0' * 40, text)
            self.assertEqual(text.count('Formal verification}'), 1)
            lock = fake_lock()
            lock.declarations = {}
            academic.generate_package(book, 'en', source, lock, out)
            text = (out / 'tbook-lean.sty').read_text()
            self.assertNotIn('Lean $\\checkmark$', text)
            self.assertNotIn('blob/', text)
            self.assertIn('UNVERIFIED', text)

    def test_definition_without_gid_is_neutral_in_ledger(self):
        with Repo() as repo:
            book = self.prepare(repo)
            p = book.dir / 'en/ch01.md'
            p.write_text(p.read_text().replace(f' lean="{FAKE_DEF}"', ''))
            self.source.write_text(self.source.read_text().replace('thm-one', 'def-one'))
            out = repo.root / 'generated'
            out.mkdir()
            academic.generate_package(book, 'en', academic.read_source(book, 'talk', 'en'), fake_lock(), out)
            text = (out / 'tbook-lean.sty').read_text()
            self.assertIn('No Lean citation', text)
            self.assertNotIn('{OPEN}', text)
            self.assertNotIn('{UNVERIFIED}', text)

    def test_media_failures_and_stale_canonical_figure(self):
        with Repo() as repo:
            book = self.prepare(repo)
            original = self.source.read_text()
            self.source.write_text(original.replace(r'\appendix', r'\BookViz{unknown}{card}\appendix'))
            self.assertIn('viz src "unknown"', self.errors(book))
            self.source.write_text(original.replace(r'\appendix', r'\BookFigure{line}\appendix'))
            write(book.dir / 'figures/line.py', SCRIPT)
            figure.build(book)
            self.assertEqual(self.errors(book), '')
            p = figure.out_path(book, 'line', 'en')
            p.write_text(p.read_text() + '<!-- stale -->')
            self.assertIn('is stale', self.errors(book))
            self.source.write_text(original.replace(r'\appendix', r'\BookViz{known}{card}\appendix'))
            with mock.patch.object(academic.viz, 'check_ref', return_value=None), mock.patch.object(academic.viz, 'check_preset', return_value=None):
                self.assertIn('unknown paper snapshot', self.errors(book))

    def test_parity_is_only_within_deck_and_imports_fail_closed(self):
        with Repo() as repo:
            book = self.prepare(repo)
            write(book.slides_dir / 'talk/deck.toml', 'kind="academic"\neditions=["en","zh"]\n')
            other = write(book.slides_dir / 'talk/slides.zh.tex', self.source.read_text() + '\n' + r'\begin{frame}{More}x\end{frame}')
            self.assertIn('frames, but', self.errors(book))
            other.write_text(self.source.read_text())
            self.assertEqual(self.errors(book), '')
            other.write_text(self.source.read_text() + r'\input{another-file}')
            self.assertIn('imports are not checked', self.errors(book))

    def test_notes_publish_to_index_and_manifest(self):
        with Repo() as repo:
            book = self.prepare(repo)
            out = slides.build_dir(book)
            target = out / 'talk/en'
            target.mkdir(parents=True)
            write(target / 'index.html', '<p>PDF</p>')
            (out / 'talk-en.pdf').write_bytes(b'%PDF')
            (out / 'talk-en-notes.pdf').write_bytes(b'%PDF notes')
            manifest = {'schema': slides.MANIFEST_SCHEMA, 'base': slides.base_path(config.load_site()),
                        'decks': {'talk': {'kind': 'academic', 'langs': {'en': {'dir': 'talk/en', 'site_path': 'talk/en/', 'pdf': 'talk-en.pdf', 'notes_pdf': 'talk-en-notes.pdf'}}}}}
            write(out / 'manifest.json', json.dumps(manifest))
            published = repo.root / '_site/demo/slides'
            with mock.patch.object(lean.Lock, 'load', return_value=fake_lock()):
                result = slides.publish(config.load_site(), book, published, build_missing=False)
            self.assertTrue((published / 'talk/demo-talk-en-notes.pdf').is_file())
            self.assertIn('demo-talk-en-notes.pdf', (published / 'index.html').read_text())
            self.assertIn('notes_pdf', result[0])
            (out / 'talk-en-notes.pdf').unlink()
            self.assertIn('missing its notes_pdf', slides._stale(book, out, manifest, manifest['base']))
