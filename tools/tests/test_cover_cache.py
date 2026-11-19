"""Cover compilation is shared across output directories and checks its real inputs."""

import json
import os
import subprocess
import shutil
from types import SimpleNamespace
from unittest import TestCase, mock, skipUnless

from test_buildcache import Scratch, write
from test_pandoc import fixture_site, have_typst, make_book
from tbook import buildcache, cover, pandoc, paths


def compile_with_fixture_fonts(args, *, input, **kwargs):
    # The image installs the same family system-wide. Use the fixture's actual
    # font files in the real compiler worker so their replacement is observable.
    request = json.loads(input)
    request["kwargs"]["ignore_system_fonts"] = True
    return subprocess.run(args, input=json.dumps(request), **kwargs)


class FontsourceConversionTests(TestCase):
    def setUp(self):
        self.real_root = paths.ROOT
        self.real_generated = paths.GENERATED
        self.site = fixture_site()
        self.root = self.enterContext(Scratch()).root
        for name, value in dict(FONT_CACHE=paths.CACHE / "fonts",
                                THEME_FONTS=paths.THEME / "typst/fonts",
                                FONTSOURCE_CACHE=paths.CACHE / "fonts-fontsource").items():
            self.enterContext(mock.patch.object(pandoc, name, value))
        self.enterContext(mock.patch.object(pandoc, "_families", return_value=set()))
        self.enterContext(mock.patch.object(paths, "GENERATED", paths.THEME / "generated"))

    def mapped_fonts(self):
        return [(self.root / "node_modules/@fontsource" / pkg / "files" / f"{pkg}-latin-{w}-normal.woff",
                 pandoc.FONTSOURCE_CACHE / f"{stem}-{w}.ttf")
                for pkg, stem, weights in pandoc.FONTSOURCE.values() for w in weights]

    def test_every_mapping_refreshes_legacy_and_changed_sources_but_reuses_unchanged(self):
        fonts = self.mapped_fonts()
        for src, dst in fonts:
            write(src, src.name.encode())
            write(dst, b"legacy conversion without provenance")
        with mock.patch.object(pandoc, "_woff_to_sfnt", side_effect=lambda data: b"sfnt:" + data) as convert:
            self.assertEqual(pandoc.font_dirs(), [pandoc.FONTSOURCE_CACHE])
            self.assertEqual(convert.call_count, len(fonts))
            for src, dst in fonts:
                self.assertEqual(dst.read_bytes(), b"sfnt:" + src.read_bytes())
            pandoc.font_dirs()
            self.assertEqual(convert.call_count, len(fonts))
            for i, (src, dst) in enumerate(fonts, 1):
                with self.subTest(font=src.name):
                    stat = src.stat()
                    write(src, src.read_bytes().replace(b"normal", b"update"))
                    os.utime(src, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                    pandoc.font_dirs()
                    self.assertEqual(convert.call_count, len(fonts) + i)
                    self.assertEqual(dst.read_bytes(), b"sfnt:" + src.read_bytes())
                    pandoc.font_dirs()
                    self.assertEqual(convert.call_count, len(fonts) + i)

    def test_damaged_conversion_is_rebuilt_and_failed_update_cannot_supply_stale_font(self):
        src, dst = self.mapped_fonts()[0]
        write(src, b"current source")
        with mock.patch.object(pandoc, "_woff_to_sfnt", return_value=b"current font") as convert:
            pandoc.font_dirs()
            write(dst, b"damaged font")
            pandoc.font_dirs()
            self.assertEqual(convert.call_count, 2)
            self.assertEqual(dst.read_bytes(), b"current font")
        write(src, b"invalid update")
        with mock.patch.object(pandoc, "_woff_to_sfnt", side_effect=ValueError("bad WOFF")), \
                mock.patch("sys.stderr"):
            self.assertEqual(pandoc.font_dirs(), [])
            self.assertFalse(dst.exists())
            self.assertEqual(pandoc.epub_font_files(), [])

    def test_missing_source_preserves_offline_fallback(self):
        _src, dst = self.mapped_fonts()[0]
        write(dst, b"offline font")
        with mock.patch.object(pandoc, "_woff_to_sfnt", side_effect=AssertionError("source unavailable")):
            self.assertEqual(pandoc.font_dirs(), [pandoc.FONTSOURCE_CACHE])
            self.assertEqual(dst.read_bytes(), b"offline font")

    @skipUnless(have_typst(), "typst not available")
    def test_fontsource_update_with_retained_caches_matches_fresh_typst_cover(self):
        self.enterContext(mock.patch.object(pandoc, "subprocess", SimpleNamespace(run=compile_with_fixture_fonts)))
        fonts = self.mapped_fonts()
        for src, _dst in fonts:
            original = self.real_root / src.relative_to(self.root)
            if not original.is_file():
                self.skipTest(f"{original.name} not installed")
            write(src, original.read_bytes())
        write(paths.THEME / "typst/cover.typ", (self.real_root / "theme/typst/cover.typ").read_bytes())
        write(paths.GENERATED / "tokens.typ", (self.real_generated / "tokens.typ").read_bytes())
        lock = write(self.root / "package-lock.json", '{"lockfileVersion": 3, "version": "1"}')
        site = self.site
        book = make_book(self.root)
        edition = book.edition("en")
        kwargs = dict(meta=cover.cover_meta(site, book, edition), width_px=320)
        bold_src, bold_dst = next((src, dst) for src, dst in fonts if src.name == "chakra-petch-latin-700-normal.woff")
        regular_src = bold_src.with_name("chakra-petch-latin-400-normal.woff")
        with mock.patch.object(pandoc, "_woff_to_sfnt", wraps=pandoc._woff_to_sfnt) as convert, \
                mock.patch.object(cover, "_render", wraps=cover._render) as compiler:
            first = cover.render_cover(site, book, edition, self.root / "first.png", **kwargs)
            first_key = cover.cache_unit(site, book, edition, **kwargs).key
            pandoc.font_dirs()
            self.assertEqual(convert.call_count, len(fonts))
            restored = cover.render_cover(site, book, edition, self.root / "restored.png", **kwargs)
            self.assertEqual(compiler.call_count, 1)
            self.assertEqual(restored.read_bytes(), first.read_bytes())

            write(bold_src, regular_src.read_bytes())
            write(lock, '{"lockfileVersion": 3, "version": "2"}')
            self.assertNotEqual(cover.cache_unit(site, book, edition, **kwargs).key, first_key)
            hot = cover.render_cover(site, book, edition, self.root / "hot.png", **kwargs)
            self.assertEqual(convert.call_count, len(fonts) + 1)
            self.assertEqual(compiler.call_count, 2)
            hot_font = bold_dst.read_bytes()
            pandoc.font_dirs()
            self.assertEqual(convert.call_count, len(fonts) + 1)
            restored = cover.render_cover(site, book, edition, self.root / "hot-restored.png", **kwargs)
            self.assertEqual(compiler.call_count, 2)
            self.assertEqual(restored.read_bytes(), hot.read_bytes())

            shutil.rmtree(pandoc.FONTSOURCE_CACHE)
            with mock.patch.dict("os.environ", {"TBOOK_CACHE": "0"}):
                cold = cover.render_cover(site, book, edition, self.root / "cold.png", **kwargs)
            self.assertEqual(convert.call_count, 2 * len(fonts) + 1)
            self.assertEqual(compiler.call_count, 3)
            self.assertEqual(bold_dst.read_bytes(), hot_font)
            self.assertNotEqual(hot.read_bytes(), first.read_bytes())
            self.assertEqual(hot.read_bytes(), cold.read_bytes())


class CoverCacheTests(TestCase):
    def test_restore_elsewhere_and_invalidate_metadata_settings_fonts_and_template(self):
        with Scratch() as scratch, mock.patch.object(buildcache, "_fonts", return_value=buildcache.Inputs()):
            book = make_book(scratch.root)
            edition = book.edition("en")
            site = SimpleNamespace(repo="")
            meta = {"title": "First title"}
            write(paths.THEME / "typst" / "cover.typ", "cover template")

            def render(_book, dest, **kwargs):
                write(dest, str(kwargs).encode())
                return dest

            first = scratch.root / "epub/cover.png"
            moved = scratch.root / "site/cover.png"
            with mock.patch.object(cover, "_render", side_effect=render) as compiler:
                cover.render_cover(site, book, edition, first, meta=meta)
                first_bytes = first.read_bytes()
                first.unlink()
                cover.render_cover(site, book, edition, moved, meta=meta)
                self.assertEqual(compiler.call_count, 1)
                self.assertEqual(moved.read_bytes(), first_bytes)
                cover.render_cover(site, book, edition, moved, meta={"title": "Second title"})
                self.assertEqual(compiler.call_count, 2)
                cover.render_cover(site, book, edition, moved, meta=meta, width_px=640)
                self.assertEqual(compiler.call_count, 3)
                write(paths.THEME / "typst" / "cover.typ", "changed template")
                cover.render_cover(site, book, edition, moved, meta=meta)
                self.assertEqual(compiler.call_count, 4)
                with mock.patch.object(buildcache, "_fonts", return_value=buildcache.Inputs().text("fonts", "changed")):
                    cover.render_cover(site, book, edition, moved, meta=meta)
                self.assertEqual(compiler.call_count, 5)

    def test_fontsource_package_lock_changes_invalidate_cover(self):
        with Scratch() as scratch, mock.patch.object(buildcache, "_fonts", return_value=buildcache.Inputs()):
            book = make_book(scratch.root)
            edition = book.edition("en")
            site = SimpleNamespace(repo="")
            meta = {"title": "Cover"}
            lock = write(scratch.root / "package-lock.json", '{"lockfileVersion": 3, "version": "1"}')
            dest = scratch.root / "out.png"

            def render(_book, output, **_kwargs):
                return write(output, lock.read_bytes())

            with mock.patch.object(cover, "_render", side_effect=render) as compiler:
                cover.render_cover(site, book, edition, dest, meta=meta)
                first_key = cover.cache_unit(site, book, edition, meta=meta).key
                first_bytes = dest.read_bytes()
                write(lock, '{"lockfileVersion": 3, "version": "2"}')
                self.assertNotEqual(cover.cache_unit(site, book, edition, meta=meta).key, first_key)
                cover.render_cover(site, book, edition, dest, meta=meta)
                self.assertEqual(compiler.call_count, 2)
                self.assertNotEqual(dest.read_bytes(), first_bytes)

    @skipUnless(have_typst(), "typst not available")
    def test_same_family_theme_font_replacement_matches_cold_render(self):
        import typst

        source = paths.ROOT / "node_modules/@fontsource/chakra-petch/files"
        sources = [source / f"chakra-petch-latin-{weight}-normal.woff" for weight in (700, 400)]
        if not all(path.is_file() for path in sources):
            self.skipTest("@fontsource/chakra-petch not installed")
        bold, regular = [pandoc._woff_to_sfnt(path.read_bytes()) for path in sources]
        template = (paths.THEME / "typst/cover.typ").read_bytes()
        tokens = (paths.GENERATED / "tokens.typ").read_bytes()
        site = fixture_site()

        with Scratch() as scratch, \
                mock.patch.object(pandoc, "subprocess", SimpleNamespace(run=compile_with_fixture_fonts)), \
                mock.patch.object(pandoc, "FONT_CACHE", paths.CACHE / "fonts"), \
                mock.patch.object(pandoc, "THEME_FONTS", paths.THEME / "typst/fonts"), \
                mock.patch.object(pandoc, "FONTSOURCE_CACHE", paths.CACHE / "fonts-fontsource"), \
                mock.patch.object(pandoc, "_FAMILIES", {}), \
                mock.patch.object(paths, "GENERATED", paths.THEME / "generated"):
            write(paths.THEME / "typst/cover.typ", template)
            write(paths.GENERATED / "tokens.typ", tokens)
            font = write(pandoc.THEME_FONTS / "ChakraPetch-700.ttf", bold)
            book = make_book(scratch.root)
            edition = book.edition("en")
            meta = cover.cover_meta(site, book, edition)
            kwargs = dict(meta=meta, width_px=320)

            def families():
                return typst.Fonts(include_embedded_fonts=False, include_system_fonts=False,
                                   font_paths=[str(pandoc.THEME_FONTS)]).families()

            first_families = families()
            self.assertIn("Chakra Petch", first_families)
            with mock.patch.object(cover, "_render", wraps=cover._render) as compiler:
                first = cover.render_cover(site, book, edition, scratch.root / "first.png", **kwargs)
                first_key = cover.cache_unit(site, book, edition, **kwargs).key
                restored = cover.render_cover(site, book, edition, scratch.root / "restored.png", **kwargs)
                self.assertEqual(compiler.call_count, 1)
                self.assertEqual(restored.read_bytes(), first.read_bytes())

                write(font, regular)
                self.assertEqual(families(), first_families)
                self.assertNotEqual(cover.cache_unit(site, book, edition, **kwargs).key, first_key)
                hot = cover.render_cover(site, book, edition, scratch.root / "hot.png", **kwargs)
                self.assertEqual(compiler.call_count, 2)
                with mock.patch.dict("os.environ", {"TBOOK_CACHE": "0"}):
                    cold = cover.render_cover(site, book, edition, scratch.root / "cold.png", **kwargs)
                self.assertEqual(compiler.call_count, 3)
                self.assertNotEqual(hot.read_bytes(), first.read_bytes())
                self.assertEqual(hot.read_bytes(), cold.read_bytes())
                data = hot.read_bytes()
                self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")),
                                 (320, 512))

    def test_damage_is_recompiled_and_cache_disabled_has_no_store(self):
        with Scratch() as scratch, mock.patch.object(buildcache, "_fonts", return_value=buildcache.Inputs()):
            book = make_book(scratch.root)
            edition = book.edition("en")
            site = SimpleNamespace(repo="")
            meta = {"title": "Cover"}
            dest = scratch.root / "out.png"

            def render(_book, output, **_kwargs):
                return write(output, b"compiled cover")

            with mock.patch.object(cover, "_render", side_effect=render) as compiler:
                cover.render_cover(site, book, edition, dest, meta=meta)
                unit = cover.cache_unit(site, book, edition, meta=meta)
                write(unit.entry_dir() / "files/0", b"corrupt")
                cover.render_cover(site, book, edition, dest, meta=meta)
                self.assertEqual(compiler.call_count, 2)
                self.assertEqual(dest.read_bytes(), b"compiled cover")
                with mock.patch.dict("os.environ", {"TBOOK_CACHE": "0"}), \
                        mock.patch.object(cover, "cache_unit", side_effect=AssertionError("cache disabled")):
                    cover.render_cover(site, book, edition, dest, meta=meta)
                self.assertEqual(compiler.call_count, 3)
