"""Regression tests for the core follow-ups of the review: references in environment titles, the
ledger link to a README chapter, i18n [meta] problems in ``check``, missing local files, the
LEAN ✓ counts, print.html media in build/html and the doctor's branch check.

Run: PYTHONPATH=tools python -m unittest discover -s tools/tests -p 'test_followups_core.py'

Like ``test_core`` (whose fixtures are reused), every test runs in a throwaway books repository with
an in-memory lock; trureturing is ``FakeLedger``, mdBook and KaTeX are replaced where a test would
need them, and nothing touches the network. The one test that reads ``books/example-monograph`` is
skipped when the example is gone.
"""

from __future__ import annotations

import unittest
from unittest import mock

from example_support import example_shown

from tbook import check, config, doctor, html, lean, mathrender, mdscan, model, paths, render, site
from test_core import (GID_3V, GID_DEF, GID_INT, CoreRepo, FakeLedger, lock_decls, make_lock, media_stub, messages,
                       write)

EXAMPLE = paths.BOOKS / "example-monograph"
ONE_CHAPTER = {"zh": "- [第一章](ch01.md)\n", "en": "- [Chapter 1](ch01.md)\n"}


def title_book(repo: CoreRepo, extra: str = ""):
    """ch01: a theorem, then a lemma whose title cites it, a code span and (``extra``) more."""
    files = {}
    for lang, cite in (("zh", "的推论"), ("en", "corollary")):
        files[lang] = {"ch01.md": f"""\
# {'第一章' if lang == 'zh' else 'Chapter 1'}

::: {{.theorem #thm-a title="Base" lean="{GID_3V}"}}
X
:::

::: {{.lemma #lem-b title="[@thm-a] {cite} `[@thm-a]`" lean="{GID_INT}"}}
Y
:::
{extra}"""}
    return repo.book(summaries=ONE_CHAPTER, files=files)


# --------------------------------------------------------------------------- [@id] in titles


class TitleReferenceTests(unittest.TestCase):
    """Finding 12: ``[@id]`` in an environment title is resolved by every target and checked."""

    def ctx(self, book, lang: str, target: str) -> render.RenderContext:
        m = model.load_edition(book.edition(lang))
        return render.RenderContext(config.load_site(), book, book.edition(lang), m, make_lock(), target=target,
                                    env_href=render.mdbook_env_href(m) if target == "mdbook" else None)

    def test_model_title_text(self):
        with CoreRepo() as repo:
            m = model.load_edition(title_book(repo).edition("zh"))
            lem = m.envs["lem-b"]
            self.assertEqual(m.title_text(lem), "定理1.1 的推论 `[@thm-a]`", "code spans stay as written")
            self.assertEqual(m.title_text(m.envs["thm-a"]), "Base")
            self.assertEqual(m.title_markdown(lem, ref=lambda t, text: f"<{t.id}:{text}>"),
                             "<thm-a:定理1.1> 的推论 `[@thm-a]`")
            self.assertEqual(lem.heading("zh", m.title_text(lem)), "引理1.2（定理1.1 的推论 `[@thm-a]`）")

    def test_mdbook_title_is_plain_text(self):
        with CoreRepo() as repo:
            ctx = self.ctx(title_book(repo), "zh", "mdbook")
            out = render.chapter_markdown(ctx.model.chapters[0], ctx)
            self.assertIn('<span class="tr-env-title">（定理1.1 的推论 `[@thm-a]`）</span>', out)
            self.assertNotIn("[@thm-a] 的推论", out)
            view = render.env_view(ctx.model.envs["lem-b"], ctx)
            self.assertEqual(view["title"], view["title_text"])
            self.assertEqual(view["heading"], "引理1.2（定理1.1 的推论 `[@thm-a]`）")
            self.assertEqual(ctx.issues, [])

    def test_pandoc_title_links_the_reference(self):
        with CoreRepo() as repo:
            ctx = self.ctx(title_book(repo), "en", "pandoc")
            out = render.chapter_markdown(ctx.model.chapters[0], ctx)
            first = next(line for line in out.splitlines() if line.startswith(":::::: {#lem-b"))
            attrs = mdscan.parse_attrs(first[len(":::::: {"):-1])
            self.assertEqual(attrs.get("tr-title"), "[Theorem 1.1](#thm-a) corollary `[@thm-a]`")
            view = render.env_view(ctx.model.envs["lem-b"], ctx)
            self.assertEqual(view["title_text"], "Theorem 1.1 corollary `[@thm-a]`")

    def test_ledger_resolves_title_references(self):
        from tbook import ledger
        with CoreRepo() as repo:
            book = title_book(repo, '\n::: {.problem #prob-c title="beyond [@lem-b]"}\nZ\n:::\n')
            m = model.load_edition(book.edition("en"))
            md = ledger.ledger_markdown(m, make_lock())
            self.assertIn("| [Theorem 1.1](#thm-a) corollary `[@thm-a]` |", md)
            self.assertIn(" — beyond [Lemma 1.2](#lem-b)", md)
            self.assertNotIn("[@lem-b]", md)
            md = ledger.ledger_markdown(m, make_lock(), href=lambda env: f"ch01.md#{env.id}")
            self.assertIn("[Theorem 1.1](ch01.md#thm-a) corollary", md)

    def test_unknown_reference_in_a_title(self):
        with CoreRepo() as repo:
            book = title_book(repo, '\n::: {.remark #rem-x title="see [@nope]"}\nZ\n:::\n')
            ctx = self.ctx(book, "zh", "mdbook")
            out = render.chapter_markdown(ctx.model.chapters[0], ctx)
            self.assertIn('<span class="tr-env-title">（see [@nope]）</span>', out, "left as written")
            self.assertEqual(len(ctx.issues), 1)
            self.assertIn("unknown reference [@nope] in a title", ctx.issues[0])

    def test_check_reports_unknown_and_media_targets(self):
        with CoreRepo() as repo:
            extra = ('\n::: {.remark #rem-x title="see [@nope]"}\nZ\n:::\n\n'
                     '::: {.viz #viz-a src="golden"}\nV\n:::\n\n'
                     '::: {.remark title="about [@viz-a] and `[@nope]`"}\nW\n:::\n')
            book = title_book(repo, extra)
            m = model.load_edition(book.edition("zh"))
            issues: list[model.Issue] = []
            with mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
                check.check_env_policy(m, issues)
            msgs = messages(issues, "error")
            self.assertEqual(len(msgs), 2, msgs)
            self.assertIn("[@nope] in the title of remark #rem-x refers to no environment in this edition", msgs)
            self.assertTrue(any(x.startswith("[@viz-a] in the title of a remark points at a viz embed") for x in msgs),
                            msgs)
            lines = sorted(i.line for i in issues)
            self.assertEqual(lines, [m.envs["rem-x"].line, m.envs["rem-x"].line + 8])

    def test_check_accepts_valid_title_references(self):
        with CoreRepo() as repo:
            m = model.load_edition(title_book(repo).edition("en"))
            issues: list[model.Issue] = []
            check.check_env_policy(m, issues)
            self.assertEqual(issues, [])


# --------------------------------------------------------------------------- ledger link into README.md


@unittest.skipUnless((html.KATEX_DIST / "katex.min.css").exists(), "node_modules/katex is required (npm ci)")
class LedgerReadmeLinkTests(unittest.TestCase):
    """Finding 13: the ledger links a result in a README.md preface to index.html (index.md when staged)."""

    def test_ledger_links_readme_chapter_as_index(self):
        with CoreRepo() as repo:
            files = {"zh": {
                "README.md": f'# 前言\n\n::: {{.theorem #thm-pre lean="{GID_3V}"}}\nX\n:::\n',
                "ch01.md": f'# 第一章\n\n::: {{.lemma #lem-b lean="{GID_INT}"}}\nY\n:::\n',
            }}
            book = repo.book(langs=("zh",), summaries={"zh": "[前言](README.md)\n\n- [第一章](ch01.md)\n"},
                             files=files)
            ed = book.primary
            m = model.load_edition(ed)
            with mock.patch.object(html.mathrender, "render_files", return_value=mathrender.MathReport()):
                stage = html.stage_edition(config.load_site(), book, ed, m, make_lock(), root=repo.root / "stage")
            led = (stage.src / "verification-ledger.md").read_text(encoding="utf-8")
            self.assertIn("(index.md#thm-pre)", led)
            self.assertIn("(ch01.md#lem-b)", led)
            self.assertNotIn("README.md#", led)


# --------------------------------------------------------------------------- i18n [meta] in check


class I18nMetaCheckTests(unittest.TestCase):
    """Finding 45: check reports the i18n [meta] problems of every site and book language."""

    SITE_JA = 'languages = ["zh", "en", "ja"]'

    def run_check(self, repo: CoreRepo, ja_toml: str) -> list[model.Issue]:
        from test_core import SITE

        book = repo.book()
        make_lock().save()
        write(repo.root / "site.toml", SITE.replace('languages = ["zh", "en"]', self.SITE_JA))
        write(repo.root / "i18n" / "ja.toml", ja_toml)
        config.load_site.cache_clear()
        config.i18n.cache_clear()
        with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
            return check.run([book], offline=True)

    def test_missing_meta(self):
        with CoreRepo() as repo:
            issues = self.run_check(repo, '[env]\ntheorem = "定理"\n')
            found = [i for i in issues if "[meta] must set name, bcp47, short for the 'ja' edition" in i.message]
            self.assertEqual(len(found), 1, [i.format() for i in issues])
            self.assertEqual((found[0].severity, found[0].path), ("error", repo.root / "i18n" / "ja.toml"))

    def test_duplicate_bcp47(self):
        with CoreRepo() as repo:
            issues = self.run_check(repo, (paths.I18N_THEME / "en.toml").read_text(encoding="utf-8"))
            msgs = messages(issues, "error")
            self.assertTrue(any("meta.bcp47 = 'en' for 'ja' is also the bcp47 of 'en'" in x for x in msgs), msgs)
            self.assertTrue(any("meta.short = 'EN' for 'ja' is also the short of 'en'" in x for x in msgs), msgs)

    def test_book_language_is_checked_too(self):
        """A language only a book lists (not site.toml) is checked as well."""
        with CoreRepo() as repo:
            book = repo.book(langs=("zh", "ja"), summaries={"zh": "- [A](a.md)\n", "ja": "- [A](a.md)\n"},
                             files={"zh": {"a.md": "# A\n"}, "ja": {"a.md": "# A\n"}})
            write(repo.root / "i18n" / "ja.toml", '[meta]\nname = "日本語"\n')
            config.i18n.cache_clear()
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()), \
                    mock.patch.object(check.importlib, "import_module", side_effect=media_stub):
                msgs = messages(check.run([book], offline=True), "error")
            self.assertTrue(any("[meta] must set bcp47, short for the 'ja' edition" in x for x in msgs), msgs)


# --------------------------------------------------------------------------- local files


class LinkCheckTests(unittest.TestCase):
    """Finding 18 (check part): missing local files and links leaving the book are warnings."""

    TEXT = """\
# A

![missing](../assets/missing.svg) ![ok](../assets/fig.svg)
[data](data/missing.csv) [here](data/here.csv) [dir](data/)
[up](../../../outside.png) [@nope] [lean](lean:not/a.gid) [ext](https://example.org/x.png)
`[code](../assets/code-span.svg)`

```text
![fence](../assets/in-fence.svg)
```

[fig]: ../assets/gone.svg "Gone"
[^1]: ../assets/footnote-not-a-link.svg
![spaced](<../assets/with space.svg>) ![pct](../assets/with%20space.svg)
[shared folder](../assets/)
"""

    def test_missing_files_and_escaping_links(self):
        with CoreRepo() as repo:
            book = repo.book(langs=("zh",), summaries={"zh": "- [A](a.md)\n"}, files={"zh": {"a.md": self.TEXT}})
            write(book.dir / "zh" / "data" / "here.csv", "x\n")
            m = model.load_edition(book.primary)
            issues: list[model.Issue] = []
            check.check_links(m, config.load_site(), issues)
            self.assertEqual({i.severity for i in issues}, {"warning"})
            got = sorted((i.line, i.message) for i in issues)
            self.assertEqual(got, [
                (3, "links to books/demo/assets/missing.svg, which does not exist"),
                (4, "links to books/demo/zh/data/missing.csv, which does not exist"),
                (5, "link leaves the book directory: ../../../outside.png"),
                (12, "links to books/demo/assets/gone.svg, which does not exist"),
                (14, "links to books/demo/assets/with space.svg, which does not exist"),
                (15, "links to books/demo/assets, which is not a file"),
            ])
            self.assertTrue(all(i.path == book.dir / "zh" / "a.md" for i in issues))

    def test_clean_fixture_has_no_warnings(self):
        with CoreRepo() as repo:
            book = repo.book()
            for lang in book.languages:
                issues: list[model.Issue] = []
                check.check_links(model.load_edition(book.edition(lang)), config.load_site(), issues)
                self.assertEqual(issues, [], lang)

    @unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden")
    def test_example_book_has_no_warnings(self):
        book = config.load_book("example-monograph")
        for ed in book.editions:
            issues: list[model.Issue] = []
            check.check_links(model.load_edition(ed), config.load_site(), issues)
            self.assertEqual([i.format() for i in issues], [], ed.key)


# --------------------------------------------------------------------------- LEAN ✓ counts


class VerifiedCountTests(unittest.TestCase):
    """Finding 33: counts of LEAN ✓ include only results whose citations the lock backs."""

    def lock_without_int(self) -> lean.Lock:
        return make_lock(lock_decls(**{GID_INT: None}))

    def test_render_helpers(self):
        with CoreRepo() as repo:
            m = model.load_edition(repo.book().edition("zh"))
            formal = m.formal_envs()
            self.assertEqual([e.id for e in formal], ["thm-a", "lem-b", "cor-c"])
            self.assertEqual([e.id for e in render.verified_envs(formal, make_lock())], ["thm-a", "lem-b", "cor-c"])
            self.assertEqual([e.id for e in render.verified_envs(formal, self.lock_without_int())], ["thm-a"])
            self.assertEqual(render.verified_envs(formal, None), [])
            self.assertFalse(render.env_verified(m.envs["def-d"], make_lock()), "definitions are not counted")

    def test_html_menu_count(self):
        with CoreRepo() as repo:
            book = repo.book()
            ed = book.edition("zh")
            m = model.load_edition(ed)
            site_cfg = config.load_site()
            self.assertEqual(html.editions_data(site_cfg, book, ed, m, make_lock())["verified"], 3)
            self.assertEqual(html.editions_data(site_cfg, book, ed, m, self.lock_without_int())["verified"], 1)

    def test_site_counts_and_verification_list(self):
        with CoreRepo() as repo:
            book = repo.book()
            lock = self.lock_without_int()
            bdir = repo.root / "_site" / book.slug
            for lang in book.languages:
                for page in ("index.html", "ch01.html", "ch02.html", "part/ch02-1.html", "verification-ledger.html"):
                    write(bdir / lang / page, "<!doctype html>")
            with mock.patch.object(site, "_media_module", lambda part: None):
                view = site.collect(config.load_site(), book, bdir, lock)
            self.assertEqual([e.id for e in view.verified()], ["thm-a"])
            self.assertEqual(view.declarations(), [GID_3V])
            bi = site.Bi(["zh", "en"])
            self.assertIn('<dd>1</dd>', site.stats_html(bi, view).split("</div>")[0])
            self.assertEqual(site.manifest(config.load_site(), [view], lock)["books"][0]["verified"], 1)

            toc = site.toc_html(view, "zh", "zh")
            self.assertIn("LEAN ✓ 1</span>", toc, "chapter 1 and the ledger entry")
            self.assertEqual(toc.count("LEAN ✓"), 2, toc)

            ver = site.verification_html(view, "zh", "zh")
            green, rest = ver.split('<ul class="vlist lean">', 1)[1].split("</ul>", 1)
            self.assertIn("#thm-a", green)
            self.assertNotIn("#lem-b", green)
            red = rest.split('<ul class="vlist open">', 1)[1].split("</ul>", 1)[0]
            self.assertIn("#lem-b", red)
            self.assertIn("#cor-c", red)
            self.assertIn('<span class="k warn" title=', red)
            self.assertIn("UNVERIFIED", red)
            self.assertNotIn("DeficitInteger.lean", red, "no link to an unresolved declaration")

    def test_site_titles_resolve_references(self):
        with CoreRepo() as repo:
            book = title_book(repo)
            bdir = repo.root / "_site" / book.slug
            with mock.patch.object(site, "_media_module", lambda part: None):
                view = site.collect(config.load_site(), book, bdir, make_lock())
            ver = site.verification_html(view, "zh", "zh")
            self.assertIn('<span class="ttl">定理1.1 的推论 `[@thm-a]`</span>', ver)


# --------------------------------------------------------------------------- print.html in build/html


class PrintMediaBuildTests(unittest.TestCase):
    """Finding 23: build_edition repairs the media URLs of print.html itself (idempotently)."""

    NESTED = ('<iframe class="tr-viz-frame" src="../../viz/carry/index.html?embed=1" '
              'data-tr-src="viz/carry/index.html?embed=1"></iframe>\n'
              '<video controls="" poster="../../films/001-x/poster.jpg" data-tr-poster="films/001-x/poster.jpg"></video>')

    def test_build_edition_fixes_print_html(self):
        with CoreRepo() as repo:
            book = repo.book(langs=("zh",), summaries={"zh": ONE_CHAPTER["zh"]}, files={"zh": {"ch01.md": "# A\n"}})
            ed = book.primary
            out_dir = repo.root / "build" / "html" / book.slug / ed.lang

            def fake_mdbook(project, out):
                write(out / "index.html", "<!doctype html>")
                write(out / "print.html", self.NESTED)
                return []

            stage = html.Stage(root=repo.root / "stage", src=repo.root / "stage" / "src")
            with mock.patch.object(html, "mdbook_binary", return_value="mdbook"), \
                    mock.patch.object(html, "stage_edition", return_value=stage), \
                    mock.patch.object(html, "run_mdbook", side_effect=fake_mdbook), \
                    mock.patch.object(html, "_warn"):
                html.build_edition(config.load_site(), book, ed, model.load_edition(ed), make_lock(), out_dir)
            printed = (out_dir / "print.html").read_text(encoding="utf-8")
            self.assertIn('src="../viz/carry/index.html?embed=1" data-tr-src=', printed)
            self.assertIn('poster="../films/001-x/poster.jpg" data-tr-poster=', printed)
            self.assertNotIn("../../", printed)
            self.assertEqual(site.fix_print_media(printed), printed, "publishing applies it again: idempotent")


# --------------------------------------------------------------------------- doctor


class DoctorBranchTests(unittest.TestCase):
    """The doctor reports whether the pinned commit is on the site.toml branch, as check asks it."""

    def run_branch(self, on_branch):
        with CoreRepo():
            ledger_obj = FakeLedger(on_branch=on_branch)
            with mock.patch.object(lean, "Ledger", lambda repo, **kw: ledger_obj):
                report = doctor.Report()
                doctor.check_branch(report, f"the-omega-institute/trureturing@{'a' * 40}")
            self.assertEqual(ledger_obj.ancestry_calls, [("a" * 40, "dev")])
            self.assertEqual(len(report.checks), 1)
            return report.checks[0]

    def test_on_branch(self):
        c = self.run_branch(True)
        self.assertTrue(c.ok)
        self.assertIn("on the-omega-institute/trureturing@dev", c.label)
        self.assertEqual(c.detail, "fake: on branch")

    def test_not_on_branch_is_required(self):
        c = self.run_branch(False)
        self.assertFalse(c.ok)
        self.assertTrue(c.is_required)
        self.assertIn("not on dev", c.detail)
        self.assertIn("./tbook pin", c.hint)

    def test_cannot_tell_is_not_fatal(self):
        c = self.run_branch(None)
        self.assertFalse(c.ok)
        self.assertFalse(c.is_required)
        self.assertEqual(c.mark, "!")
        self.assertIn("cannot tell: fake: cannot tell", c.detail)

    def test_no_lock_no_check(self):
        report = doctor.Report()
        doctor.check_branch(report, None)
        self.assertEqual(report.checks, [])

    def test_check_trureturing_includes_the_branch(self):
        with mock.patch.object(doctor, "_check_access") as access, mock.patch.object(doctor, "check_branch") as branch:
            doctor.check_trureturing(doctor.Report(), "r@c")
        access.assert_called_once()
        branch.assert_called_once()


# --------------------------------------------------------------------------- re-review (markdown-render)


class LeanLinkCitationTests(unittest.TestCase):
    """Re-review 6: a GID cited only in a reference definition ``[x]: lean:GID`` or an angle
    destination ``(<lean:GID>)`` is checked against the lock and pinned like an inline link."""

    TEXT = f"""\
# A

见 [该定理][lt] 与 [另一个](<lean:{GID_INT}>)。

[lt]: lean:{GID_DEF}
[bad]: <lean:no-gid-here>
"""

    def book(self, repo: CoreRepo):
        return repo.book(langs=("zh",), summaries={"zh": "- [A](a.md)\n"}, files={"zh": {"a.md": self.TEXT}})

    def test_check_and_pin_cover_every_form(self):
        from tbook import pin

        with CoreRepo() as repo:
            book = self.book(repo)
            self.assertEqual(pin.cited_gids([book]), sorted([GID_DEF, GID_INT]))
            m = model.load_edition(book.primary)
            issues: list[model.Issue] = []
            check.check_env_policy(m, issues)
            self.assertEqual([(i.line, i.message.split(" (")[0]) for i in issues],
                             [(6, "not a declaration GID: 'no-gid-here'")])
            lock = make_lock(lock_decls(**{GID_DEF: None, GID_INT: None}))
            issues = []
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()):
                check.check_lean({"demo": {"zh": m}}, lock, config.load_site(), issues, offline=True)
            self.assertEqual(sorted((i.line, i.message) for i in issues if i.severity == "error"), [
                (3, f"{GID_INT} is not in trureturing.lock.json; run ./tbook pin --refresh"),
                (5, f"{GID_DEF} is not in trureturing.lock.json; run ./tbook pin --refresh"),
            ])
            issues = []
            with mock.patch.object(lean, "Ledger", lambda r, **kw: FakeLedger()):
                check.check_lean({"demo": {"zh": m}}, make_lock(), config.load_site(), issues, offline=True)
            self.assertEqual(messages(issues, "error"), [], "a def cited by a link is fine")


class CommentCheckTests(unittest.TestCase):
    """Re-review 9: ``./tbook check`` ignores what HTML comments hold, as every target does."""

    def test_commented_placeholders_are_not_reported(self):
        text = ("# A\n\n<!--\n![图 3](../assets/fig3.svg) [@todo] [x](lean:not-a-gid)\n-->\n\n"
                "<!-- ![图 4](fig4.svg) [@todo2] --> ![图](../assets/fig.svg)\n")
        with CoreRepo() as repo:
            book = repo.book(langs=("zh",), summaries={"zh": "- [A](a.md)\n"}, files={"zh": {"a.md": text}})
            m = model.load_edition(book.primary)
            issues: list[model.Issue] = list(m.issues)
            check.check_env_policy(m, issues)
            check.check_links(m, config.load_site(), issues)
            self.assertEqual([i.format() for i in issues], [])


class TitleEscapeSiteTests(unittest.TestCase):
    """Re-review 4/5: the site shows titles with Markdown escapes undone outside math; formulas are rendered at
    build time (tbook.site.render_title_math), or shown as their TeX source without a rendering."""

    def test_site_titles_unescape(self):
        summaries = {"zh": "- [C\\*-代数 与 snake\\_case](ch01.md)\n", "en": "- [C\\*-algebras](ch01.md)\n"}
        with CoreRepo() as repo:
            book = title_book(repo)
            for lang, text in summaries.items():
                write(book.edition(lang).summary, text)
            ch01 = book.edition("zh").dir / "ch01.md"
            ch01.write_text(ch01.read_text(encoding="utf-8").replace('title="Base"', 'title="C\\*-代数 与 \\$5 与 $\\{x\\}$"'),
                            encoding="utf-8")
            bdir = repo.root / "_site" / book.slug
            with mock.patch.object(site, "_media_module", lambda part: None):
                view = site.collect(config.load_site(), book, bdir, make_lock())
            ver = site.verification_html(view, "zh", "zh")  # no renderings: the formula is its TeX source
            self.assertIn('<span class="ttl">C*-代数 与 $5 与 $\\{x\\}$</span>', ver)
            toc = site.toc_html(view, "zh", "zh")
            self.assertIn('<span class="t-title">C*-代数 与 snake_case</span>', toc)
            # "\$5" is a literal dollar, not the start of a formula; the code span stays as written
            self.assertEqual(site.title_html("C\\*-代数 与 \\$5 与 $\\{x\\}$", {"\\{x\\}": "<KATEX>"}),
                             "C*-代数 与 $5 与 <KATEX>")
            self.assertEqual(site.title_html("`$x$` 与 $x$ \\& <b>", {"x": "<K>"}), "`$x$` 与 <K> &amp; &lt;b&gt;")
            if not (html.KATEX_DIST / "katex.min.css").exists():
                self.skipTest("node_modules/katex is required (npm ci)")
            math = site.render_title_math([view])
            self.assertEqual(list(math), ["\\{x\\}"])
            ver = site.verification_html(view, "zh", "zh", math)
            self.assertIn('<span class="ttl">C*-代数 与 $5 与 <span class="katex" role="math" aria-label="\\{x\\}">', ver)
            self.assertNotIn("$\\{x\\}$", ver)


if __name__ == "__main__":
    unittest.main()
