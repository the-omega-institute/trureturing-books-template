"""Written proofs stay distinct from both kernel verification and open problems."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile
from types import SimpleNamespace

from tbook import academic, check, config, evidence, ledger, model, render, requests, slides, site, pandoc as tp
from test_pandoc import have_pandoc, have_typst, run_filters
from test_core import CoreRepo, GID_3V, make_lock, write


DOI = '10.1000/fixture.proof'
SOURCE = 'Theorem 2.1'
REQUEST = evidence.REQUEST_PREFIX + '1'
SOURCE_ATTRS = f'doi="{DOI}" source="{SOURCE}" request="{REQUEST}"'
ATTRS = 'status="written-proof" proof="pf-a" ' + SOURCE_ATTRS


class WrittenProofTests(unittest.TestCase):
    def book(self, repo, attrs=ATTRS, proof='A written argument.'):
        book = repo.book()
        for lang in book.languages:
            write(book.edition(lang).dir / 'ch01.md', f'''# Statement

::: {{.theorem #thm-a {attrs}}}
The statement from the source.
:::
''')
            # A proof may be in another chapter; adjacency is not evidence of association.
            write(book.edition(lang).dir / 'ch02.md', f'''# Argument

::: {{.proof #pf-a}}
{proof}
:::
''')
        return book

    def test_proof_in_each_edition_and_parity(self):
        with CoreRepo() as repo:
            book = self.book(repo)
            models = model.load_book_models(book)
            issues = []
            for edition in models.values():
                check.check_env_policy(edition, issues)
            check.check_parity(book, models, issues)
            self.assertEqual(issues, [])
            path = book.edition('en').dir / 'ch02.md'
            path.write_text('# No argument\n')
            issues = []
            check.check_env_policy(model.load_edition(book.edition('en')), issues)
            self.assertTrue(any('naming a proof block' in i.message for i in issues))

    def test_invalid_status_proof_and_lean_combinations(self):
        cases = [
            ('status="written-proof"', 'argument', 'needs proof='),
            ('status="written-proof" proof="thm-a"', 'argument', 'naming a proof block'),
            ('status="written-proof" proof="pf-a"', '<!-- hidden -->', 'is empty'),
            ('status="written-proof" proof="pf-a" lean=""', 'argument', 'must not also have lean'),
            (f'status="written-proof" proof="pf-a" lean="{GID_3V}"', 'argument', 'must not also have lean'),
            ('status="written-proff"', 'argument', 'unknown result status'),
        ]
        for attrs, proof, message in cases:
            with self.subTest(attrs=attrs, proof=proof), CoreRepo() as repo:
                book = self.book(repo, attrs, proof)
                issues = []
                check.check_env_policy(model.load_edition(book.edition('en')), issues)
                self.assertTrue(any(message in i.message for i in issues), issues)

    def test_open_and_non_result_cannot_claim_written_proof(self):
        for kind in (*model.OPEN, 'definition', 'remark', 'proof'):
            with self.subTest(kind=kind), CoreRepo() as repo:
                book = self.book(repo)
                path = book.edition('en').dir / 'ch01.md'
                path.write_text(path.read_text().replace('.theorem', '.' + kind))
                issues = []
                check.check_env_policy(model.load_edition(book.edition('en')), issues)
                self.assertTrue(any('only for theorem/' in i.message for i in issues))

    def test_language_status_and_proof_target_must_match(self):
        for replacement in ('status="written-proof"', 'proof="pf-other"', 'doi="10.1000/other"', 'source="Lemma 3"', 'request="' + evidence.REQUEST_PREFIX + '2"'):
            with self.subTest(replacement=replacement), CoreRepo() as repo:
                book = self.book(repo)
                path = book.edition('en').dir / 'ch01.md'
                text = path.read_text()
                key = replacement.split('=', 1)[0]
                old = {'status':'status="written-proof"', 'proof':'proof="pf-a"', 'doi':f'doi="{DOI}"', 'source':f'source="{SOURCE}"', 'request':f'request="{REQUEST}"'}[key]
                text = text.replace(old, '' if key == 'status' else replacement)
                path.write_text(text)
                issues = []
                check.check_parity(book, model.load_book_models(book), issues)
                self.assertTrue(any('differs between editions' in i.message for i in issues))

    def test_render_and_ledger_never_imply_lean_even_with_invalid_gid(self):
        for invalid_gid in ('', f' lean="{GID_3V}"'):
            with CoreRepo() as repo:
                book = self.book(repo, ATTRS + invalid_gid)
                for lang, label in [('en', 'WRITTEN PROOF'), ('zh', '书面证明')]:
                    ed = book.edition(lang)
                    m = model.load_edition(ed)
                    env = m.envs['thm-a']
                    ctx = render.RenderContext(config.load_site(), book, ed, m, make_lock(), target='mdbook')
                    v = render.env_view(env, ctx)
                    self.assertEqual(v['badge'], label)
                    self.assertEqual(v['status'], 'written-proof')
                    self.assertEqual(v['badge_url'], '')
                    self.assertEqual(v['lean'], [])
                    self.assertFalse(render.env_verified(env, make_lock()))
                    self.assertNotIn(env, render.verified_envs(m.all_envs(), make_lock()))
                    html = render.mdbook_env(env, v, 'statement')
                    self.assertIn('tr-badge-written-proof', html)
                    self.assertIn(evidence.doi_url(DOI), html)
                    self.assertIn(REQUEST, html)
                    self.assertNotIn('tr-badge-written-proof\" href=', html)
                    pandoc = render.pandoc_env(env, v, 'statement')
                    self.assertIn('tr-status="written-proof"', pandoc)
                    self.assertNotIn('tr-badge-url=', pandoc)
                    self.assertNotIn('tr-lean=', pandoc)
                    text = ledger.ledger_markdown(m, make_lock())
                    written = text.split(config.s(lang, 'ledger.written_title'), 1)[1].split(config.s(lang, 'ledger.open_title'), 1)[0]
                    self.assertIn('#thm-a', written)
                    self.assertIn('#pf-a', written)
                    self.assertNotIn(GID_3V, written)
                    self.assertIn(evidence.doi_url(DOI), written)
                    self.assertIn(REQUEST, written)

    def test_site_summary_keeps_written_proof_out_of_unverified_group(self):
        with CoreRepo() as repo:
            book = self.book(repo)
            m = model.load_edition(book.edition('en'))
            view = SimpleNamespace(models={'en': m}, lock=make_lock(), built={}, bdir=repo.root)
            html = site.verification_html(view, 'en', 'en')
            self.assertIn('WRITTEN PROOF', html)
            self.assertNotIn('UNVERIFIED', html)
            self.assertIn('vlist written-proof', html)

    def test_slide_status_and_book_citation(self):
        with CoreRepo() as repo:
            book = self.book(repo)
            m = model.load_edition(book.edition('en'))
            ed, slide = SimpleNamespace(path=book.edition('en').dir / 'slides.md', lang='en'), SimpleNamespace(line=1)
            errors = []
            err = lambda *args: errors.append(args[-1])
            citation = SimpleNamespace(tag='TheoremCard', gid='', attrs={'status':'written-proof', 'cite':'thm-a', 'label':m.envs['thm-a'].ref_text('en'), 'doi':DOI, 'source':SOURCE, 'request':REQUEST})
            slides._check_citation(citation, ed, slide, make_lock(), err)
            slides._check_cite(citation, ed, slide, m, err)
            self.assertEqual(errors, [])
            citation.attrs['gid'] = ''
            slides._check_citation(citation, ed, slide, make_lock(), err)
            self.assertTrue(any('must not have gid' in e for e in errors))
            errors.clear()
            citation.attrs.pop('gid')
            citation.attrs['status'] = 'argued'
            slides._check_cite(citation, ed, slide, m, err)
            self.assertTrue(any('written-proof status must agree' in e for e in errors))


# Real Pandoc/Lua/Typst conversions catch divergence hidden by intermediate Markdown.


@unittest.skipUnless(have_pandoc(), 'Pandoc is required')
class WrittenProofOutputTests(unittest.TestCase):
    def test_lua_html_and_typst_preserve_written_status(self):
        with CoreRepo() as repo:
            book = WrittenProofTests().book(repo)
            ed = book.edition('en')
            m = model.load_edition(ed)
            ctx = render.RenderContext(config.load_site(), book, ed, m, make_lock(), target='pandoc')
            md = render.chapter_markdown(m.chapters[1], ctx)
            html = run_filters(md, 'html5')
            self.assertIn('tr-status-written-proof', html)
            self.assertIn('tr-badge-written-proof', html)
            self.assertIn('WRITTEN PROOF', html)
            self.assertIn(evidence.doi_url(DOI), html)
            self.assertIn(REQUEST, html)
            typ = run_filters(md, 'typst')
            self.assertIn('status: "written-proof"', typ)
            self.assertIn('badge: "WRITTEN PROOF"', typ)
            self.assertIn('badge-url: ""', typ)
            self.assertIn(evidence.doi_url(DOI), typ)
            self.assertIn(REQUEST, typ)

    @unittest.skipUnless(have_typst(), 'Typst is required')
    def test_all_pdf_variants_and_epub_build_with_written_proof(self):
        with CoreRepo() as repo, tempfile.TemporaryDirectory(prefix='tbook-written-outputs-') as tmp:
            book = WrittenProofTests().book(repo)
            ed = book.edition('en')
            m = model.load_edition(ed)
            out = Path(tmp)
            for variant in config.PDF_VARIANTS:
                pdf = tp.build_pdf(config.load_site(), book, ed, m, make_lock(), variant,
                                   out / (variant + '.pdf'), stage_dir=out / variant)
                self.assertTrue(pdf.read_bytes().startswith(b'%PDF-'))
                src = (out / variant / 'main.typ').read_text()
                self.assertIn('status: "written-proof"', src)
                self.assertIn('badge: "WRITTEN PROOF"', src)
            with mock.patch.dict('os.environ', {'TBOOK_EPUBCHECK': '0'}):
                epub = tp.build_epub(config.load_site(), book, ed, m, make_lock(), out / 'book.epub',
                                     stage_dir=out / 'epub')
            with zipfile.ZipFile(epub) as z:
                xhtml = '\n'.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xhtml'))
                self.assertIn('tr-badge-written-proof', xhtml)
                self.assertIn('WRITTEN PROOF', xhtml)
                self.assertIn(evidence.doi_url(DOI), xhtml)
                self.assertIn(REQUEST, xhtml)
                self.assertRegex(xhtml, r'<span[^>]*tr-badge-written-proof[^>]*>WRITTEN PROOF</span>')


class WrittenProofEvidenceTests(unittest.TestCase):
    def edition(self, repo, **changes):
        attrs = ATTRS
        for key, value in changes.items():
            import re
            attrs = re.sub(r'\b' + key + r'="[^"]*"', '' if value is None else f'{key}="{value}"', attrs)
        book = WrittenProofTests().book(repo, attrs)
        return model.load_edition(book.edition('en'))

    def test_missing_or_invalid_provenance_is_rejected(self):
        cases = [('doi', None), ('doi', ''), ('doi', 'https://doi.org/' + DOI), ('doi', '10.1000/'),
                 ('doi', '10.1000/a b'), ('source', None), ('source', ''), ('source', 'Theorem 1 | other'),
                 ('request', None), ('request', REQUEST + '#issuecomment-1'),
                 ('request', REQUEST.replace('/issues/', '/pull/')),
                 ('request', REQUEST.replace('trureturing-requests', 'trureturing'))]
        for key, value in cases:
            with self.subTest(key=key, value=value), CoreRepo() as repo:
                edition = self.edition(repo, **{key:value})
                issues = []
                check.check_env_policy(edition, issues)
                self.assertTrue(any(key in i.message for i in issues), issues)

    def test_doi_suffix_punctuation_is_encoded_without_changing_identifier(self):
        doi = '10.1002/(SICI)1097-4571(199701)48:1<1::AID-ASI1>3.0.CO;2-0'
        self.assertIn('%3C1%3A%3AAID-ASI1%3E', evidence.doi_url(doi))
        doi = '10.1002/(SICI)1097-4571;2-0?x#y%z'
        self.assertEqual(evidence.doi_url(doi), 'https://doi.org/10.1002/%28SICI%291097-4571%3B2-0%3Fx%23y%25z')
        for value in (None, True, '10.1000/a\u200bb', '10.1000/a\nb'):
            self.assertEqual(evidence.doi_url(value), '')
        self.assertIsNotNone(evidence.parse_request_title(evidence.request_title('A result', DOI, SOURCE)))
        for title in ('A result', '[形式化] X | DOI:10.1000/a | Theorem 1', f'[Formalization]  | DOI:{DOI} | {SOURCE}', '[Formalization] X | DOI:not-a-doi | Theorem 1'):
            self.assertIsNone(evidence.parse_request_title(title))

    def test_existing_issue_requires_registration_of_this_book_and_source(self):
        with CoreRepo() as repo:
            edition = self.edition(repo)
            site_config = config.load_site()
            use = requests.marker(site_config.repo, edition.edition.book.slug, 'thm-a')
            source = requests.registration(DOI, SOURCE)
            issue = {'title':evidence.request_title('A result', DOI, SOURCE), 'body':use + '\n' + source, 'comments':0}
            with mock.patch.object(requests, '_api', return_value=issue):
                self.assertEqual(requests.check([edition], site_config), [])
            issue['body'] = 'Another book uses this result.'
            with mock.patch.object(requests, '_api', return_value=issue):
                self.assertTrue(any('register every book/result' in i.message for i in requests.check([edition], site_config)))
            # Reuse the same mathematical request even when another DOI proves the result.
            issue['title'] = evidence.request_title('The same result', '10.1000/another.source', 'Lemma 3')
            issue['comments'] = 1
            with mock.patch.object(requests, '_api', side_effect=[issue, [{'body':use + '\n' + source}]]):
                self.assertEqual(requests.check([edition], site_config), [])
            with mock.patch.object(requests, '_api', side_effect=[issue, [{'body':use + '\nDOI:10.1000/wrong | ' + SOURCE}]]):
                self.assertTrue(requests.check([edition], site_config))

    def test_title_pr_missing_issue_and_offline_policy(self):
        from urllib.error import HTTPError, URLError
        with CoreRepo() as repo:
            edition = self.edition(repo)
            cfg = config.load_site()
            marker = requests.marker(cfg.repo, edition.edition.book.slug, 'thm-a')
            issue = {'title':'wrong title', 'body':marker + '\n' + requests.registration(DOI, SOURCE)}
            with mock.patch.object(requests, '_api', return_value=issue):
                self.assertTrue(any('title must be' in i.message for i in requests.check([edition], cfg)))
            with mock.patch.object(requests, '_api', return_value={'pull_request':{}}):
                self.assertTrue(any('pull request' in i.message for i in requests.check([edition], cfg)))
            with mock.patch.object(requests, '_api', side_effect=HTTPError('url',404,'missing',{},None)):
                self.assertEqual(requests.check([edition], cfg)[0].severity, 'error')
            with mock.patch.object(requests, '_api') as api:
                self.assertEqual(requests.check([edition], cfg, offline=True)[0].severity, 'warning')
                api.assert_not_called()
            with mock.patch.object(requests, '_api', side_effect=URLError('network')), mock.patch.dict('os.environ', {'GITHUB_ACTIONS':'true'}):
                self.assertEqual(requests.check([edition], cfg)[0].severity, 'error')

    def test_pagination_and_translations_do_not_inflate_usage_counts(self):
        with CoreRepo() as repo:
            book = WrittenProofTests().book(repo)
            editions = list(model.load_book_models(book).values())
            groups = requests.collect(editions + editions)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]['result_count'], 1)
            self.assertEqual(groups[0]['book_count'], 1)
            self.assertEqual(groups[0]['sources'], [{'doi':DOI, 'source':SOURCE}])
            with mock.patch.object(requests, '_api', side_effect=[[{'body':'other'}] * 100, [{'body':'marker\nsource'}]]) as api:
                self.assertTrue(requests.registered({'body':'', 'comments':101}, 1, {'marker':'source'}))
                self.assertEqual(api.call_count, 2)

    def test_request_title_uses_english_edition_name(self):
        with CoreRepo() as repo:
            book = WrittenProofTests().book(repo)
            for lang, title in [('zh', '中文结果'), ('en', 'A result in English')]:
                p = book.edition(lang).dir / 'ch01.md'
                p.write_text(p.read_text().replace('#thm-a ', f'#thm-a title="{title}" '))
            editions = list(model.load_book_models(book).values())
            group, = requests.collect(iter(editions))
            self.assertEqual(group['suggested_title'], evidence.request_title('A result in English', DOI, SOURCE))
            group, = requests.collect(ed for ed in editions if ed.lang == 'zh')
            self.assertTrue(group['suggested_title'].startswith('[Formalization] thm-a |'))

    def test_shared_request_counts_books_and_results_once(self):
        with CoreRepo() as repo:
            first = WrittenProofTests().book(repo)
            second = repo.book('another')
            for lang in second.languages:
                for name in ('ch01.md', 'ch02.md'):
                    target = second.edition(lang).dir / name
                    target.write_text((first.edition(lang).dir / name).read_text())
            editions = [m for b in (first, second) for m in model.load_book_models(b).values()]
            group, = requests.collect(editions + editions)
            self.assertEqual(group['book_count'], 2)
            self.assertEqual(group['result_count'], 2)
            self.assertEqual({u['book'] for u in group['uses']}, {'demo', 'another'})

    def test_academic_deck_preserves_written_status_and_provenance(self):
        with CoreRepo() as repo:
            book = WrittenProofTests().book(repo)
            out = repo.root / 'generated'
            out.mkdir()
            academic.generate_package(book, 'en', SimpleNamespace(results=['thm-a']), make_lock(), out)
            text = (out / 'tbook-lean.sty').read_text()
            self.assertIn('WRITTEN PROOF', text)
            self.assertIn(evidence.doi_url(DOI), text)
            self.assertIn(REQUEST, text)
            self.assertIn('TBookWritten', text)
            self.assertNotIn('Lean $\\checkmark$', text)
            self.assertNotIn('UNVERIFIED', text)

    def test_dynamic_or_duplicate_slide_metadata_is_rejected(self):
        for attr in ('v-bind:kind="\'theorem\'"', ':status="\'written-proof\'"', 'status="open" status="argued"', ':doi="\'10.1000/a\'"', 'request="a" request="b"'):
            with self.subTest(attr=attr):
                _, issues = slides.citations('<TheoremCard ' + attr + '/>')
                self.assertTrue(any('one literal attribute' in msg for msg in issues))
