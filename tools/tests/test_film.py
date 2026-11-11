"""Tests for tbook.film (book-local films) and the stdlib parts of the pipeline in theme/film/.

Run: PYTHONPATH=tools .venv/bin/python -m unittest discover -s tools/tests -p 'test_film.py'
Node-dependent tests are skipped when ``node`` is not on PATH. Rendering (Chromium, ffmpeg) and the
audio steps (Kokoro, numpy) are not run here; see theme/film/film.sh.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from example_support import example_shown

from tbook import config, film, lean, mdscan, paths, render

NODE = film.node_executable()
EXAMPLE = paths.BOOKS / "example-monograph"
EXAMPLE_FILM = EXAMPLE / "films" / "001-golden-deficit"
GID3 = "D5/S1/Deficit/DeficitThreeValued.deficit_three_valued"
GIDI = "D5/S1/Deficit/DeficitInteger.deficit_integer"
GIDDEF = "D5/S1/Deficit/DeficitInteger.deficit"  # a Lean def
THEME_FILM = paths.THEME / "film"
# Downstream repositories may delete the example book (skills/book-new); tests built on it skip then.
needs_example = unittest.skipUnless(EXAMPLE.is_dir(), "books/example-monograph is absent")
needs_listed_example = unittest.skipUnless(example_shown(), "books/example-monograph is absent or hidden")


def fake_lock() -> lean.Lock:
    """A lock with two theorems and one definition (independent of the repository's lock)."""
    def decl(gid: str, kind: str) -> dict:
        module, name = gid.rsplit(".", 1)
        return {"module": module, "name": "D5.S1.Deficit." + name, "kind": kind, "statement_id": "sha256:x", "line": 7}

    return lean.Lock(repo="the-omega-institute/trureturing", branch="dev", commit="a" * 40,
                     declarations={GID3: decl(GID3, "theorem"), GIDI: decl(GIDI, "theorem"), GIDDEF: decl(GIDDEF, "def")})


def example_book() -> config.Book:
    return config.load_book("example-monograph")


def temp_book(root: Path, slug: str = "film-fixture") -> config.Book:
    """A real (loadable) book in a temporary directory, with an empty films/ directory."""
    bdir = root / slug
    (bdir / "films").mkdir(parents=True)
    (bdir / "book.toml").write_text('[book]\ncode = "FIX//FILM"\neditions = ["zh", "en"]\n'
                                    '[book.title]\nzh = "测试书"\nen = "Test Book"\n', encoding="utf-8")
    return config.load_book(bdir)


def copy_example(book: config.Book, name: str = "001-golden-deficit", outputs: tuple[str, ...] | None = None) -> Path:
    """Copy the example film's sources into ``book`` with the book's video file names: the outputs the example
    lists (the default: narrated_720p and cover), or ``outputs`` (``resolution`` then follows them)."""
    dst = book.films_dir / name
    shutil.copytree(EXAMPLE_FILM, dst, ignore=shutil.ignore_patterns("out"))
    meta = json.loads((dst / "film.json").read_text(encoding="utf-8"))
    num = name[:3]
    meta["id"] = name
    outs = film.default_outputs(book.slug, num)
    meta["outputs"] = {k: outs[k] for k in (outputs or meta["outputs"])}
    meta["resolution"] = film.published_size(meta["outputs"]) + "@30"
    (dst / "film.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


ALL_OUTPUTS = film.VIDEO_OUTPUTS  # every output a film.json may list


def errors(issues) -> list[str]:
    return [i.message for i in issues if i.severity == "error"]


def ctx_for(book: config.Book, lang: str, target: str) -> render.RenderContext:
    site = config.load_site()
    return render.RenderContext(site=site, book=book, edition=book.edition(lang), model=None,
                                lock=lean.Lock.load(), target=target)


def env_for(src: str):
    return SimpleNamespace(attrs=mdscan.Attrs(classes=["film"], kv={"src": src}), kind="film")


def doc_for(book: config.Book, lang: str, chapter: str = "ch01-golden-deficit.md"):
    return SimpleNamespace(path=book.dir / lang / chapter, chapter=SimpleNamespace(path=chapter))


@needs_example
class ExampleFilmTest(unittest.TestCase):
    @needs_listed_example
    def test_example_film_is_valid(self):
        book = example_book()
        issues = film.check(book)
        self.assertEqual(errors(issues), [], [i.format() for i in issues])

    @needs_listed_example
    def test_example_cites_locked_theorems(self):
        f = film.get(example_book(), "001-golden-deficit")
        self.assertIsNotNone(f)
        self.assertEqual(sorted(f.lean), sorted([GID3, GIDI]))
        lock = lean.Lock.load()
        self.assertEqual(f.meta["publication_basis"], "pinned")
        for gid in f.lean:
            self.assertEqual(lock.get(gid).kind, "theorem")

    def test_example_poster_is_small(self):
        poster = EXAMPLE_FILM / "poster.jpg"
        self.assertTrue(poster.is_file())
        self.assertLess(poster.stat().st_size, film.POSTER_MAX_BYTES)
        self.assertEqual(poster.read_bytes()[:3], b"\xff\xd8\xff")

    def test_example_duration_is_close_to_provisional_timing(self):
        # film.json gives the narrated cut (tts.py measures it; the build warns when it differs); the provisional
        # timeline only estimates it at a fixed speaking rate
        f = film.get(example_book(), "001-golden-deficit")
        tl = film.provisional_timeline(f.script)
        declared = film.parse_duration(f.meta["duration"])
        self.assertIsNotNone(declared)
        self.assertLess(abs(declared - tl["duration"]), 0.25 * tl["duration"])

    @needs_listed_example
    def test_example_has_no_release_keys(self):
        f = film.get(example_book(), "001-golden-deficit")
        self.assertFalse(set(f.meta) & set(film.LEGACY_KEYS))
        self.assertFalse(any(i.severity == "warning" and "no longer used" in i.message for i in film.check(example_book())))

    def test_cited_gids(self):
        gids = [g for _, _, g in film.cited_gids(example_book())]
        self.assertIn(GID3, gids)


@needs_example
class CheckRefTest(unittest.TestCase):
    def setUp(self):
        self.book = example_book()

    def test_local(self):
        self.assertIsNone(film.check_ref(self.book, "001-golden-deficit"))

    def test_missing_local(self):
        msg = film.check_ref(self.book, "009-nothing-here")
        self.assertIn("not found", msg)
        self.assertIn("001-golden-deficit", msg)

    def test_bad_names(self):
        for src in ("golden-deficit", "1-golden", "001_golden", "../001-golden-deficit"):
            self.assertIsNotNone(film.check_ref(self.book, src), src)
        self.assertIn("needs src", film.check_ref(self.book, ""))

    def test_external(self):
        self.assertIsNone(film.check_ref(self.book, "trureturing-film:film-001-v1"))
        self.assertIsNone(film.check_ref(self.book, "trureturing-film:film-129-v12"))
        for src in ("trureturing-film:001", "trureturing-film:film-1-v1", "trureturing-film:film-001-v0",
                    "trureturing-film:film-001"):
            self.assertIn("trureturing-film:film-<NNN>-v<k>", film.check_ref(self.book, src), src)


class ValidationTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(film, "_lock", return_value=fake_lock())
        patch.start()
        self.addCleanup(patch.stop)
        self.tmp = Path(tempfile.mkdtemp())
        self.book = temp_book(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    @needs_example
    def test_copied_example_is_valid(self):
        copy_example(self.book)
        self.assertEqual(errors(film.check(self.book)), [])

    @needs_example
    def test_meta_errors(self):
        d = copy_example(self.book)
        meta = json.loads((d / "film.json").read_text(encoding="utf-8"))
        meta.update(id="002-other", duration="57s", resolution="1920x1080@30", subtitles=["fr"],
                    lean=["D5/S1/Deficit/DeficitInteger.not_a_locked_name", "not a gid"], subject_commit="XYZ")
        meta["outputs"]["cover"] = "cover.png"
        meta["outputs"]["music_only_720p"] = "poster.jpg"
        del meta["title_zh"]
        (d / "film.json").write_text(json.dumps(meta), encoding="utf-8")
        msgs = "\n".join(errors(film.check(self.book)))
        for needle in ("id must equal the directory name", "duration must look like m:ss",
                       "resolution is the size of the published video: 1280x720@<fps> (outputs lists no 1080p video",
                       "subtitles", "not in trureturing.lock.json", "not a declaration GID",
                       "subject_commit", "outputs.cover", "outputs.music_only_720p", "title_zh"):
            self.assertIn(needle, msgs)

    @needs_example
    def test_release_keys_are_no_longer_used(self):
        """film.json of the per-film release era (release_tag, published_tag) still checks, with warnings."""
        d = copy_example(self.book)
        meta = json.loads((d / "film.json").read_text(encoding="utf-8"))
        meta.update(release_tag="film-film-fixture-001-v2", published_tag="film-film-fixture-001-v1")
        (d / "film.json").write_text(json.dumps(meta), encoding="utf-8")
        issues = film.check(self.book)
        self.assertEqual(errors(issues), [])
        warned = [i.message for i in issues if i.severity == "warning" and "no longer used" in i.message]
        self.assertEqual(len(warned), 2, warned)
        self.assertTrue(warned[0].startswith("film.json: release_tag is no longer used"))
        self.assertTrue(warned[1].startswith("film.json: published_tag is no longer used"))
        self.assertIsNone(film.check_ref(self.book, d.name))
        # null counts too: the key itself is obsolete
        meta.update(release_tag=None, published_tag=None)
        self.assertEqual(sum("no longer used" in m for sev, m in film.validate_meta(meta, d, self.book, fake_lock())
                             if sev == "warning"), 2)

    @needs_example
    def test_the_default_outputs(self):
        """By default a film makes the 720p narrated video the players play and the cover, nothing else."""
        self.assertEqual(film.REQUIRED_OUTPUTS, ("narrated_720p", "cover"))
        self.assertEqual(set(film.REQUIRED_OUTPUTS) | set(film.OPTIONAL_OUTPUTS), set(film.VIDEO_OUTPUTS))
        d = copy_example(self.book)
        self.assertEqual(errors(film.check(self.book)), [])
        f = film.get(self.book, d.name)
        self.assertEqual(f.videos(), {"narrated_720p": "film-fixture_001_720p_narrated.mp4",
                                      "cover": "film-fixture_001_cover.jpg"})
        self.assertEqual(f.meta["resolution"], "1280x720@30")
        self.assertEqual([f.listed(k) for k in film.VIDEO_OUTPUTS], [False, False, True, False, True])
        self.assertEqual(f.download(), "narrated_720p")
        # default_outputs still names every output
        self.assertEqual(f.output("narrated"), "film-fixture_001_narrated_EN_subs_ZH-EN.mp4")
        self.assertEqual(f.output("music_only_720p"), "film-fixture_001_720p_music_only.mp4")

    @needs_example
    def test_optional_outputs_are_made_when_listed(self):
        d = copy_example(self.book, outputs=("cover", "music_only_720p", "narrated_720p", "narrated"))
        self.assertEqual(errors(film.check(self.book)), [])
        f = film.get(self.book, d.name)
        # in the order of VIDEO_OUTPUTS, whatever the order in film.json
        self.assertEqual(list(f.videos()), ["narrated", "narrated_720p", "music_only_720p", "cover"])
        self.assertEqual(f.download(), "narrated")
        d2 = copy_example(self.book, "002-every-output", outputs=ALL_OUTPUTS)
        self.assertEqual(errors(film.check(self.book)), [])
        self.assertEqual(list(film.get(self.book, d2.name).videos()), list(film.VIDEO_OUTPUTS))

    @needs_example
    def test_outputs_validation(self):
        d = copy_example(self.book)
        base = json.loads((d / "film.json").read_text(encoding="utf-8"))

        def problems(**outputs) -> list[str]:
            meta = json.loads(json.dumps(base))
            for key, value in outputs.items():
                if value is ...:
                    del meta["outputs"][key]
                else:
                    meta["outputs"][key] = value
            meta["resolution"] = film.published_size(meta["outputs"]) + "@30"
            return [m for sev, m in film.validate_meta(meta, d, self.book, fake_lock()) if sev == "error"
                    and "outputs" in m]

        self.assertEqual(problems(), [])
        self.assertEqual(problems(narrated_720p=...), [
            "film.json: outputs.narrated_720p is required (the file name of the 720p narrated video the players "
            "play), e.g. 'film-fixture_001_720p_narrated.mp4'"])
        self.assertIn("outputs.cover is required", problems(cover=...)[0])
        self.assertEqual(problems(narrated_4k="x.mp4"), [
            "film.json: outputs.narrated_4k is not an output; outputs lists narrated_720p, cover and may add "
            "narrated, music_only, music_only_720p"])
        self.assertIn("leave the key out to not build this video", problems(music_only=None)[0])
        self.assertIn("wrong extension", problems(narrated="a.jpg")[0])
        self.assertIn("two outputs share a file name", problems(narrated=base["outputs"]["narrated_720p"])[0])
        self.assertIn("outputs.cover must be a file name", problems(cover="poster.jpg")[0])

    @needs_example
    def test_resolution_follows_the_outputs(self):
        d = copy_example(self.book)
        meta = json.loads((d / "film.json").read_text(encoding="utf-8"))

        def res_errors(resolution: str, *extra: str) -> list[str]:
            m = json.loads(json.dumps(meta))
            m["resolution"] = resolution
            for key in extra:
                m["outputs"][key] = film.default_outputs(self.book.slug, "001")[key]
            return [x for sev, x in film.validate_meta(m, d, self.book, fake_lock()) if sev == "error"]

        self.assertEqual(res_errors("1280x720@30"), [])
        self.assertEqual(res_errors("1280x720@24", "music_only_720p"), [])
        self.assertEqual(res_errors("1920x1080@30", "narrated"), [])
        self.assertEqual(res_errors("1920x1080@30", "music_only"), [])
        self.assertEqual(res_errors("1280x720@30", "narrated"), [
            "film.json: resolution is the size of the published video: 1920x1080@<fps> (outputs lists a 1080p video)"])
        self.assertIn("the build scales them to 1280x720", res_errors("1920x1080@30")[0])
        self.assertIn("resolution must look like 1280x720@30", res_errors("720p")[0])
        # without the field: the size the outputs give
        del meta["resolution"]
        self.assertEqual([x for sev, x in film.validate_meta(meta, d, self.book, fake_lock()) if sev == "error"], [])
        meta["outputs"]["narrated"] = "n.mp4"
        self.assertEqual([x for sev, x in film.validate_meta(meta, d, self.book, fake_lock()) if sev == "error"], [])

    @needs_example
    def test_stale_subject_commit_is_a_warning(self):
        d = copy_example(self.book)
        meta = json.loads((d / "film.json").read_text(encoding="utf-8"))
        meta["subject_commit"] = "0123456789abcdef"
        (d / "film.json").write_text(json.dumps(meta), encoding="utf-8")
        issues = film.check(self.book)
        self.assertEqual(errors(issues), [])
        self.assertTrue(any("not the pinned commit" in i.message for i in issues if i.severity == "warning"))

    @needs_example
    def test_script_errors(self):
        d = copy_example(self.book)
        script = {"voice": "", "speed": 5, "scenes": [
            {"id": "Bad-Id", "lead": 1, "tail": 1, "lines": [["only english"]]},
            {"id": "ok", "lead": -1, "tail": 1, "lines": [["a", "甲"]], "music": [1, 2],
             "cues": [{"line": 4, "at": 1, "kind": "boom"}]},
            {"id": "ok", "lead": 0, "tail": 0, "lines": []},
        ]}
        (d / "script.json").write_text(json.dumps(script), encoding="utf-8")
        msgs = "\n".join(errors(film.check(self.book)))
        for needle in ("voice is required", "speed must be", "lowercase identifier", "two non-empty strings",
                       "lead must be", "music must list 5 levels", "cue", "duplicate scene id", "non-empty list"):
            self.assertIn(needle, msgs)

    @needs_example
    def test_invalid_json_and_layout(self):
        d = copy_example(self.book)
        (d / "script.json").write_text("{not json", encoding="utf-8")
        (d / "notes.txt").write_text("x", encoding="utf-8")
        (self.book.films_dir / "stray.md").write_text("x", encoding="utf-8")
        (self.book.films_dir / "001-twin").mkdir()
        issues = film.check(self.book)
        msgs = "\n".join(i.message for i in issues)
        self.assertIn("invalid JSON", msgs)
        self.assertIn("not a film source file", msgs)
        self.assertIn("films/ holds film directories", msgs)
        self.assertIn("film number 001 is used twice", msgs)

    @needs_example
    def test_missing_scene_definition_warns(self):
        d = copy_example(self.book)
        script = json.loads((d / "script.json").read_text(encoding="utf-8"))
        script["scenes"].append({"id": "extra", "lead": 0.5, "tail": 0.5, "lines": [["More.", "更多。"]]})
        (d / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
        issues = film.check(self.book)
        self.assertTrue(any("SCENES.extra" in i.message for i in issues if i.severity == "warning"))

    @needs_example
    @unittest.skipUnless(NODE, "node not available")
    def test_scene_syntax_error(self):
        d = copy_example(self.book)
        (d / "scenes.js").write_text("SCENES.zeck = S => { txt('x', 1, 2 ;\n", encoding="utf-8")
        self.assertTrue(any("JavaScript syntax error" in m for m in errors(film.check(self.book))))

    def test_lean_must_cite_theorems(self):
        created = film.scaffold(self.book, "002-carry-rules", "进位规则", "The Carry Rules", released="2026-11-08")
        meta = json.loads(created[0].read_text(encoding="utf-8"))
        meta["lean"] = [GID3, GIDDEF]
        problems = film.validate_meta(meta, created[0].parent, self.book, fake_lock())
        self.assertEqual([m for sev, m in problems if sev == "error"], [
            f"film.json: {GIDDEF} is a Lean def, not a theorem; lean lists the theorems the film cites (shown as LEAN ✓)"])
        # the films page and the engine data never present the definition as verified
        created[0].write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        f = film.get(self.book, "002-carry-rules")
        card = film._film_card(config.load_site(), f, fake_lock())
        self.assertEqual(card.count('<span class="k ok">LEAN ✓</span>'), 1)
        self.assertIn('<li><span class="k">LEAN</span><a href="https://github.com/the-omega-institute/trureturing/blob/'
                      + "a" * 40 + '/D5/S1/Deficit/DeficitInteger.lean#L7"', card)
        self.assertEqual([r["kind"] for r in film.lean_refs(f.lean, fake_lock())], ["theorem", "def"])
        self.assertIn("DATA.lean.filter(z => z.kind === 'theorem')", (THEME_FILM / "engine.js").read_text(encoding="utf-8"))
        meta["lean"] = [GID3, GIDI]
        self.assertEqual([m for sev, m in film.validate_meta(meta, created[0].parent, self.book, fake_lock())
                          if sev == "error"], [])

    def test_scene_ids_defined(self):
        js = "SCENES.a = S => {};\nSCENES['b-c'] = S => {};\nif (SCENES.d === 1) {}\nSCENES . e=x"
        self.assertEqual(film.scene_ids_defined(js), {"a", "b-c", "e"})


class TimelineTest(unittest.TestCase):
    SCRIPT = {"voice": "af_heart", "speed": 1.0, "scenes": [
        {"id": "one", "lead": 1.5, "tail": 0.5, "lines": [["One two three four five six.", "一"], ["Hi.", "二"]]},
        {"id": "two", "lead": 0.25, "tail": 2.0, "lines": [["Seven eight nine ten eleven twelve thirteen.", "三"]]},
    ]}

    def test_accounting(self):
        tl = film.provisional_timeline(self.SCRIPT, wps=2.0)
        self.assertTrue(tl["provisional"])
        l0, l1, l2 = tl["lines"]
        self.assertEqual(l0["start"], 1.5)
        self.assertAlmostEqual(l0["end"] - l0["start"], 6 / 2.0 + film.LINE_PAD_SECONDS, places=3)
        self.assertAlmostEqual(l1["start"], l0["end"] + film.LINE_GAP_SECONDS, places=3)
        self.assertAlmostEqual(l1["end"] - l1["start"], film.MIN_LINE_SECONDS, places=3)  # short lines get a floor
        s0, s1 = tl["scenes"]
        self.assertEqual(s0["start"], 0.0)
        self.assertAlmostEqual(s0["end"], l1["end"] + 0.5, places=3)
        self.assertAlmostEqual(l2["start"], s1["start"] + 0.25, places=3)
        self.assertAlmostEqual(tl["duration"], s1["end"], places=3)
        self.assertAlmostEqual(s1["end"], l2["end"] + 2.0, places=3)
        self.assertEqual([ln["i"] for ln in tl["lines"]], [0, 1, 2])
        self.assertEqual([ln["scene"] for ln in tl["lines"]], ["one", "one", "two"])

    def test_rate_and_matches(self):
        slow, fast = film.provisional_timeline(self.SCRIPT, 1.0), film.provisional_timeline(self.SCRIPT, 4.0)
        self.assertGreater(slow["duration"], fast["duration"])
        self.assertIsNone(film.timeline_matches(slow, self.SCRIPT))
        changed = json.loads(json.dumps(self.SCRIPT))
        changed["scenes"][1]["lines"][0][0] = "Different words now."
        self.assertIn("line 2 differs", film.timeline_matches(slow, changed))
        changed["scenes"][1]["id"] = "renamed"
        self.assertIn("scene ids", film.timeline_matches(slow, changed))
        with self.assertRaises(ValueError):
            film.provisional_timeline(self.SCRIPT, 0)

    def test_durations(self):
        self.assertEqual(film.format_duration(56.992), "0:57")
        self.assertEqual(film.format_duration(414.4), "6:54")
        self.assertEqual(film.parse_duration("6:54"), 414)
        self.assertIsNone(film.parse_duration("6:61"))


class NamesTest(unittest.TestCase):
    def test_video_names_and_places(self):
        outs = film.default_outputs("example-monograph", "001")
        self.assertEqual(outs["narrated"], "example-monograph_001_narrated_EN_subs_ZH-EN.mp4")
        self.assertEqual(outs["cover"], "example-monograph_001_cover.jpg")
        self.assertEqual(film.video_dir("bk", "001-x"), paths.BUILD / "films" / "bk" / "001-x")
        for name in ("release_asset_url", "release_page_url", "release_notes", "parse_tag", "default_tag", "urls"):
            self.assertFalse(hasattr(film, name), name)
        self.assertFalse((THEME_FILM / "release.py").exists())

    def test_external(self):
        ext = film.external_ref("trureturing-film:film-010-v1")
        self.assertEqual(ext["narrated"], "https://github.com/the-omega-institute/trureturing-film/releases/download/"
                                          "film-010-v1/TRURETURING_010_narrated_EN_subs_ZH-EN.mp4")
        self.assertEqual(ext["cover"], "https://github.com/the-omega-institute/trureturing-film/releases/download/"
                                       "film-010-v1/TRURETURING_010_cover.jpg")
        self.assertIsNone(film.external_ref("001-golden-deficit"))


@needs_example
@needs_listed_example
class EmbedTest(unittest.TestCase):
    def setUp(self):
        self.book = example_book()
        self.site = config.load_site()

    def test_mdbook_local(self):
        ctx = ctx_for(self.book, "zh", "mdbook")
        out = film.render_embed(env_for("001-golden-deficit"), ctx, "\n图注 **加粗**。\n", doc_for(self.book, "zh"))
        d = "films/001-golden-deficit/"
        f = film.get(self.book, "001-golden-deficit")
        v720, v1080 = f.output("narrated_720p"), f.output("narrated")
        head = f"视频 001 · 黄金亏量 · {f.meta['duration']}"
        # the same markup whether or not the video is built: the site marks figures it does not host
        self.assertIn(f'<figure class="tr-media tr-film" data-film="001-golden-deficit" data-tr-video="{d}{v720}">', out)
        self.assertIn(f'<video class="tr-film-player" controls preload="metadata" playsinline poster="../{d}poster.jpg" '
                      f'data-tr-poster="{d}poster.jpg" title="{head}">\n'
                      f'<source src="../{d}{v720}" data-tr-src="{d}{v720}" type="video/mp4">\n</video>', out)
        self.assertIn(f'<img class="tr-film-poster tr-film-fallback" src="../{d}poster.jpg" alt="{head}" loading="lazy">', out)
        # download links only for the videos film.json lists: by default the 720p narrated one
        self.assertIn(f'<span class="tr-film-files"><a href="../{d}{v720}" download>⬇ 720p</a></span>', out)
        self.assertNotIn(v1080, out)
        self.assertNotIn(f.output("music_only"), out)
        self.assertIn(f'<span class="tr-film-note tr-film-fallback">{film.t("zh", "unbuilt")}</span>', out)
        self.assertNotIn("/releases/", out)
        self.assertNotIn("github.com", out)
        self.assertIn('<figcaption class="tr-media-caption">\n\n图注 **加粗**。\n\n<div class="tr-media-links">', out)
        self.assertIn('href="../films/index.html?lang=zh#001-golden-deficit">视频页</a>', out)
        self.assertEqual(ctx.issues, [])

    def test_mdbook_nested_chapter_and_default_caption(self):
        ctx = ctx_for(self.book, "en", "mdbook")
        out = film.render_embed(env_for("001-golden-deficit"), ctx, "", doc_for(self.book, "en", "part/ch.md"))
        duration = film.get(self.book, "001-golden-deficit").meta["duration"]
        self.assertIn('poster="../../films/001-golden-deficit/poster.jpg"', out)
        self.assertIn('<source src="../../films/001-golden-deficit/example-monograph_001_720p_narrated.mp4"', out)
        self.assertIn(f"Film 001 · The Golden Deficit · {duration}", out)
        self.assertIn(">Film page</a>", out)
        self.assertIn(">⬇ 720p</a>", out)
        self.assertNotIn("Music only", out)

    def test_mdbook_links_every_listed_video(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        book = temp_book(tmp)
        copy_example(book, outputs=ALL_OUTPUTS)
        ctx = ctx_for(book, "en", "mdbook")
        out = film.render_embed(env_for("001-golden-deficit"), ctx, "", doc_for(book, "en"))
        d = "../films/001-golden-deficit/film-fixture_001_"
        self.assertIn(f'<span class="tr-film-files"><a href="{d}narrated_EN_subs_ZH-EN.mp4" download>⬇ 1080p</a>'
                      f'<a href="{d}720p_narrated.mp4" download>⬇ 720p</a>'
                      f'<a href="{d}music_only_subs_ZH-EN.mp4" download>⬇ Music only 1080p</a>'
                      f'<a href="{d}720p_music_only.mp4" download>⬇ Music only 720p</a></span>', out)
        # the player plays the 720p narrated video whatever else is listed
        self.assertIn(f'<source src="{d}720p_narrated.mp4"', out)

    def test_mdbook_external(self):
        ctx = ctx_for(self.book, "en", "mdbook")
        out = film.render_embed(env_for("trureturing-film:film-001-v1"), ctx, "", doc_for(self.book, "en"))
        base = "https://github.com/the-omega-institute/trureturing-film/releases/download/film-001-v1/"
        self.assertIn(f'poster="{base}TRURETURING_001_cover.jpg"', out)
        self.assertIn(f'<source src="{base}TRURETURING_001_narrated_EN_subs_ZH-EN.mp4"', out)
        self.assertIn("Film from trureturing-film · film-001-v1", out)

    def test_mdbook_bad_src_is_reported(self):
        ctx = ctx_for(self.book, "zh", "mdbook")
        out = film.render_embed(env_for("404-missing"), ctx, "", doc_for(self.book, "zh"))
        self.assertIn("tr-film", out)
        self.assertTrue(any("not found" in m for m in ctx.issues))

    def test_pandoc_local(self):
        ctx = ctx_for(self.book, "zh", "pandoc")
        out = film.render_embed(env_for("001-golden-deficit"), ctx, "图注。", doc_for(self.book, "zh"))
        duration = film.get(self.book, "001-golden-deficit").meta["duration"]
        lines = out.splitlines()
        self.assertEqual(lines[0], "::: {.tr-media .tr-film}")
        self.assertEqual(lines[-1], ":::")
        self.assertNotEqual(lines[-2], "")
        self.assertIn(f"![视频 001 · 黄金亏量 · {duration}](_book/films/001-golden-deficit/poster.jpg){{width=100%}}", out)
        self.assertIn((EXAMPLE_FILM / "poster.jpg").resolve(), ctx.book_files)
        self.assertIn("图注。", out)
        self.assertNotIn(".mp4", out)
        if self.site.base_url:  # the film on the site's films page
            self.assertIn("视频见\\", out)
            self.assertIn(f"<{self.site.base_url}example-monograph/films/#001-golden-deficit>", out)

    def test_pandoc_without_a_site_shows_the_poster_alone(self):
        site = SimpleNamespace(**{**config.load_site().__dict__, "base_url": ""})
        ctx = render.RenderContext(site=site, book=self.book, edition=self.book.edition("en"), model=None,
                                   lock=lean.Lock.load(), target="pandoc")
        out = film.render_embed(env_for("001-golden-deficit"), ctx, "Caption.", doc_for(self.book, "en"))
        self.assertIn("](_book/films/001-golden-deficit/poster.jpg)", out)
        self.assertIn("Caption.", out)
        self.assertNotIn("Film:", out)
        self.assertNotIn("<http", out)
        self.assertNotIn(film.t("en", "unbuilt"), out)
        self.assertEqual(out.splitlines()[-2:], ["Caption.", ":::"])

    def test_pandoc_nested_and_external(self):
        ctx = ctx_for(self.book, "en", "pandoc")
        out = film.render_embed(env_for("001-golden-deficit"), ctx, "", doc_for(self.book, "en", "part/ch.md"))
        duration = film.get(self.book, "001-golden-deficit").meta["duration"]
        self.assertIn("](../_book/films/001-golden-deficit/poster.jpg)", out)
        self.assertIn(f"**Film 001 · The Golden Deficit · {duration}**", out)
        if self.site.base_url:
            self.assertIn("Film:\\", out)
        ctx = ctx_for(self.book, "en", "pandoc")
        out = film.render_embed(env_for("trureturing-film:film-003-v1"), ctx, "Caption.", doc_for(self.book, "en"))
        self.assertNotIn("![", out)
        self.assertIn("**Film from trureturing-film · film-003-v1**", out)
        self.assertIn("<https://github.com/the-omega-institute/trureturing-film/releases/tag/film-003-v1>", out)
        self.assertEqual(ctx.book_files, set())


class Sandbox:
    """A repository root in a temporary directory (paths.ROOT, BUILD, CACHE patched) with a book holding a
    copy of the example film and a chapter, so build units, the cache store and the build directory are
    real but isolated. TBOOK_* variables are cleared: no remote cache, default film mode."""

    def __init__(self, case: unittest.TestCase):
        self.root = Path(tempfile.mkdtemp())
        case.addCleanup(shutil.rmtree, self.root)
        shutil.copy2(paths.ROOT / "package-lock.json", self.root / "package-lock.json")  # npm versions in the key
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TBOOK_CACHE", "TBOOK_FILMS"))}
        for patch in (mock.patch.dict(os.environ, env, clear=True),
                      mock.patch.object(paths, "ROOT", self.root), mock.patch.object(paths, "BUILD", self.root / "build"),
                      mock.patch.object(paths, "CACHE", self.root / ".cache"),
                      mock.patch.object(film, "_lock", return_value=fake_lock())):
            patch.start()
            case.addCleanup(patch.stop)
        self.book = temp_book(self.root / "books", "bk")
        (self.book.dir / "zh").mkdir()
        (self.book.dir / "zh" / "ch01.md").write_text("# 第一章\n", encoding="utf-8")
        self.dir = copy_example(self.book)
        self.site = dataclasses.replace(config.load_site(), repo="acme/books", base_url="")

    def film(self) -> film.Film:
        return film.get(self.book, self.dir.name)

    def key(self, site=None) -> str:
        return film.video_unit(site or self.site, self.film()).key


@needs_example
class VideoUnitTest(unittest.TestCase):
    """The films build unit: one per film, keyed by what the videos depend on and nothing else."""

    def setUp(self):
        self.sb = Sandbox(self)

    def test_unit(self):
        unit = film.video_unit(self.sb.site, self.sb.film())
        self.assertEqual((unit.target, unit.name), ("films", "bk/001-golden-deficit"))
        self.assertEqual(unit.outputs, [self.sb.root / "build" / "films" / "bk" / "001-golden-deficit"])
        self.assertEqual([u.name for u in film.units(self.sb.site, self.sb.book)], ["bk/001-golden-deficit"])
        labels = [label for label, _ in unit.inputs.parts]
        for want in ("books/bk/films/001-golden-deficit/scenes.js", "books/bk/films/001-golden-deficit/script.json",
                     "books/bk/films/001-golden-deficit/film.json", "<engine>", "<npm>", "<kokoro>", "<node>"):
            self.assertIn(want, labels)
        for probed in ("<ffmpeg>", "<chromium>", "<python>"):
            self.assertNotIn(probed, labels)
        # theme/film/ lies outside the sandbox's root here, so its labels are <outside>/film/…
        self.assertTrue(any(label.endswith("film/engine.js") for label in labels))
        self.assertTrue(any(label.endswith("film/requirements.txt") for label in labels))
        self.assertTrue(any(label.endswith("/tokens.mjs") for label in labels))
        self.assertTrue(any(label.endswith("/film.py") for label in labels))
        self.assertFalse(any("/theme/film/site/" in label or "__pycache__" in label for label in labels))
        self.assertFalse(any(label.endswith("/poster.jpg") or "/out/" in label for label in labels))
        npm = dict(unit.inputs.parts)["<npm>"]
        self.assertNotEqual(npm, film.buildcache.Inputs().text("npm", {}).parts[0][1])  # package-lock.json was read

    def test_unrelated_changes_keep_the_key(self):
        key = self.sb.key()
        (self.sb.book.dir / "zh" / "ch01.md").write_text("# 第一章\n\n新的一段。\n", encoding="utf-8")
        (self.sb.dir / "poster.jpg").write_bytes(b"\xff\xd8\xff another poster")
        (self.sb.dir / "README.md").write_text("notes\n", encoding="utf-8")
        (self.sb.dir / "out").mkdir(exist_ok=True)
        (self.sb.dir / "out" / "timeline.json").write_text("{}", encoding="utf-8")
        toml = self.sb.book.dir / "book.toml"
        toml.write_text(toml.read_text(encoding="utf-8") + 'description = "x"\n', encoding="utf-8")
        self.sb.book = config.load_book(self.sb.book.dir)
        self.assertEqual(self.sb.key(), key)
        # the site's address is not an input: the videos are the same wherever the site is served
        other = dataclasses.replace(self.sb.site, base_url="https://acme.github.io/books/", repo="x/y")
        self.assertEqual(self.sb.key(other), key)

    def test_inputs_change_the_key(self):
        key = self.sb.key()
        scenes = self.sb.dir / "scenes.js"
        scenes.write_text(scenes.read_text(encoding="utf-8") + "\n// a change\n", encoding="utf-8")
        key2 = self.sb.key()
        self.assertNotEqual(key2, key)
        (self.sb.dir / "data").mkdir()
        (self.sb.dir / "data" / "extra.json").write_text("[1]", encoding="utf-8")
        key3 = self.sb.key()
        self.assertNotEqual(key3, key2)
        # the lock: the HUD draws the pinned commit and the cited declarations' statement digests
        moved = fake_lock()
        moved.commit = "c" * 40
        with mock.patch.object(film, "_lock", return_value=moved):
            key4 = self.sb.key()
            moved.commit = "b" * 40
            self.assertNotEqual(self.sb.key(), key4)
        self.assertNotEqual(key4, key3)
        # the book's title is drawn on the end card
        toml = self.sb.book.dir / "book.toml"
        toml.write_text(toml.read_text(encoding="utf-8").replace("Test Book", "Other Book"), encoding="utf-8")
        self.sb.book = config.load_book(self.sb.book.dir)
        self.assertNotEqual(self.sb.key(), key3)

    def test_the_toolchain_present_or_not_keeps_the_key(self):
        # a build without the film toolchain (TBOOK_FILMS=auto|skip) restores the videos a full one stored
        key = self.sb.key()
        with mock.patch.object(film, "ffmpeg_path", return_value=""), \
                mock.patch.object(film, "film_python", return_value="/nonexistent/python"), \
                mock.patch.dict(os.environ, {"PW_CHROMIUM_PATH": "/nonexistent/chromium"}):
            self.assertEqual(self.sb.key(), key)

    def test_node_major_version_changes_the_key(self):
        key = self.sb.key()
        with mock.patch.object(film.buildcache, "node_version", return_value="999"):
            self.assertNotEqual(self.sb.key(), key)

    def test_buildcache_lists_film_units(self):
        names = [(u.target, u.name) for u in film.buildcache.units(self.sb.site, [self.sb.book])]
        self.assertIn(("films", "bk/001-golden-deficit"), names)


@needs_example
class BuildVideosTest(unittest.TestCase):
    """build_videos with the renderer replaced by a fake that writes the video files."""

    def setUp(self):
        self.sb = Sandbox(self)
        self.renders = []
        self.missing: list[str] = []

        def fake_render(f: film.Film, dest: Path) -> None:
            self.renders.append(f.id)
            dest.mkdir(parents=True, exist_ok=True)
            for key, name in f.videos().items():
                (dest / name).write_bytes(f"{key} #{len(self.renders)}".encode())

        for patch in (mock.patch.object(film, "render_videos", side_effect=fake_render),
                      mock.patch.object(film, "toolchain_missing", side_effect=lambda: list(self.missing))):
            patch.start()
            self.addCleanup(patch.stop)
        self.out_dir = self.sb.film().build_dir

    def run_build(self, mode: str | None = None) -> tuple[dict, str]:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            status = film.build_videos(self.sb.site, self.sb.book, mode=mode)
        return status, err.getvalue()

    def files(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.out_dir.iterdir())} if self.out_dir.is_dir() else {}

    def test_renders_stores_then_restores(self):
        status, _ = self.run_build()
        self.assertEqual(status, {"001-golden-deficit": "built"})
        self.assertEqual(self.renders, ["001-golden-deficit"])
        first = self.files()
        self.assertEqual(sorted(first), sorted(self.sb.film().videos().values()))
        unit = film.video_unit(self.sb.site, self.sb.film())
        self.assertTrue(unit.entry_dir().is_dir())
        shutil.rmtree(self.out_dir)
        status, _ = self.run_build()
        self.assertEqual(status, {"001-golden-deficit": "cached"})
        self.assertEqual(len(self.renders), 1)  # not rendered again
        self.assertEqual(self.files(), first)  # restored from the store
        # a changed input renders again
        scenes = self.sb.dir / "scenes.js"
        scenes.write_text(scenes.read_text(encoding="utf-8") + "\n// edit\n", encoding="utf-8")
        status, _ = self.run_build()
        self.assertEqual((status["001-golden-deficit"], len(self.renders)), ("built", 2))
        self.assertIn(b"#2", self.files()[self.sb.film().output("narrated_720p")])

    def test_the_default_builds_the_720p_narrated_video_and_the_cover(self):
        self.run_build()
        f = self.sb.film()
        self.assertEqual(sorted(self.files()), sorted([f.output("narrated_720p"), f.output("cover")]))

    def test_listing_an_output_renders_again_and_builds_it(self):
        self.run_build()
        key = self.sb.key()
        original = (self.sb.dir / "film.json").read_text(encoding="utf-8")
        meta = json.loads(original)
        meta["outputs"]["music_only"] = "bk_001_music.mp4"
        meta["resolution"] = "1920x1080@30"
        (self.sb.dir / "film.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        self.assertNotEqual(self.sb.key(), key)  # film.json is an input: the outputs are part of the key
        status, _ = self.run_build()
        self.assertEqual((status["001-golden-deficit"], len(self.renders)), ("built", 2))
        self.assertIn("bk_001_music.mp4", self.files())
        # and unlisting it again restores the earlier build without the file
        (self.sb.dir / "film.json").write_text(original, encoding="utf-8")
        status, _ = self.run_build()
        self.assertEqual((status["001-golden-deficit"], len(self.renders)), ("cached", 2))
        self.assertNotIn("bk_001_music.mp4", self.files())

    def test_a_render_without_a_listed_output_fails_and_is_not_stored(self):
        def short_render(f: film.Film, dest: Path) -> None:  # a renderer that forgets the cover
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f.output("narrated_720p")).write_bytes(b"mp4")

        with mock.patch.object(film, "render_videos", side_effect=short_render):
            with self.assertRaisesRegex(film.buildcache.MissingOutput, "did not write bk_001_cover.jpg"):
                self.run_build()
        self.assertFalse(film.video_unit(self.sb.site, self.sb.film()).entry_dir().exists())
        # nor does the site host a film whose listed outputs are not all there
        out = self.sb.root / "_site" / "bk" / "films"
        with mock.patch.object(film, "build_videos", return_value={}), redirect_stderr(io.StringIO()):
            film.build(self.sb.site, self.sb.book, out)
        self.assertFalse(json.loads((out / "films.json").read_text(encoding="utf-8"))["films"][0]["built"])
        self.assertEqual(sorted(p.name for p in (out / "001-golden-deficit").iterdir()), ["poster.jpg"])

    def test_cache_off_always_renders(self):
        with mock.patch.dict(os.environ, {"TBOOK_CACHE": "0"}):
            self.run_build()
            self.run_build()
        self.assertEqual(len(self.renders), 2)
        self.assertFalse((self.sb.root / ".cache" / "artifacts").exists())

    def test_auto_without_the_toolchain_leaves_the_film_out(self):
        self.out_dir.mkdir(parents=True)
        (self.out_dir / "stale.mp4").write_bytes(b"older inputs")
        self.missing = ["ffmpeg (install it)"]
        status, err = self.run_build()
        self.assertEqual(status, {"001-golden-deficit": "skipped"})
        self.assertEqual(self.renders, [])
        self.assertIn("film bk/001-golden-deficit was not built", err)
        self.assertIn("ffmpeg (install it)", err)
        self.assertFalse(self.out_dir.exists())  # no video of older inputs stays behind

    def test_require_fails_without_the_toolchain(self):
        self.missing = ["the Kokoro model"]
        with mock.patch.dict(os.environ, {"TBOOK_FILMS": "require"}):
            with self.assertRaisesRegex(film.FilmError, "the film toolchain is incomplete: the Kokoro model"):
                self.run_build()
        self.assertEqual(self.renders, [])

    def test_skip_never_renders_but_restores(self):
        status, err = self.run_build("skip")
        self.assertEqual((status["001-golden-deficit"], self.renders), ("skipped", []))
        self.assertIn("TBOOK_FILMS=skip", err)
        self.run_build("require")  # renders and stores
        shutil.rmtree(self.out_dir)
        with mock.patch.dict(os.environ, {"TBOOK_FILMS": "skip"}):
            status, _ = self.run_build()
        self.assertEqual(status, {"001-golden-deficit": "cached"})
        self.assertEqual(len(self.renders), 1)
        self.assertTrue(self.files())

    def test_mode_is_checked(self):
        with mock.patch.dict(os.environ, {"TBOOK_FILMS": "always"}):
            with self.assertRaisesRegex(film.FilmError, "TBOOK_FILMS='always'"):
                self.run_build()

    def test_films_with_errors_are_not_rendered(self):
        (self.sb.dir / "film.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(film.FilmError):
            self.run_build()
        self.assertEqual(self.renders, [])

    def test_publish_hosts_the_built_videos(self):
        out = self.sb.root / "_site" / "bk" / "films"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = film.build(self.sb.site, self.sb.book, out)
        self.assertEqual(status, {"001-golden-deficit": "built"})
        f = self.sb.film()
        d = out / f.id
        for name in f.videos().values():
            self.assertEqual((d / name).read_bytes(), (self.out_dir / name).read_bytes())
        # by default only the 720p narrated video and the cover (and the committed poster)
        self.assertEqual(sorted(p.name for p in d.iterdir()),
                         sorted([f.output("narrated_720p"), f.output("cover"), "poster.jpg"]))
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn(f'<video controls preload="metadata" playsinline poster="{f.id}/poster.jpg"', page)
        self.assertIn(f'<source src="{f.id}/{f.output("narrated_720p")}" type="video/mp4">', page)
        links = page.split('<div class="links">', 1)[1].split("</div>", 1)[0]
        self.assertEqual(links, f'<a class="btn primary" href="{f.id}/{f.output("narrated_720p")}" download>⬇ '
                                f'{film._pair("small")}</a><a class="btn" href="{f.id}/{f.output("cover")}" '
                                f'download>{film._pair("cover")}</a>')
        for key in film.OPTIONAL_OUTPUTS:
            self.assertNotIn(f.output(key), page)
        self.assertNotIn("github.com/acme/books/releases", page)
        self.assertNotIn(film.t("en", "unbuilt"), page)
        reg = json.loads((out / "films.json").read_text(encoding="utf-8"))["films"][0]
        self.assertTrue(reg["built"])
        self.assertEqual(reg["videos"], {"narrated_720p": f"{f.id}/{f.output('narrated_720p')}",
                                         "cover": f"{f.id}/{f.output('cover')}"})
        self.assertFalse({"release_tag", "published_tag"} & set(reg))

    def test_publish_hosts_and_links_the_listed_optional_videos(self):
        shutil.rmtree(self.sb.dir)
        copy_example(self.sb.book, outputs=("narrated", "narrated_720p", "music_only_720p", "cover"))
        out = self.sb.root / "_site" / "bk" / "films"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            film.build(self.sb.site, self.sb.book, out)
        f = self.sb.film()
        d = out / f.id
        listed = [f.output(k) for k in ("narrated", "narrated_720p", "music_only_720p", "cover")]
        self.assertEqual(sorted(p.name for p in d.iterdir()), sorted(listed + ["poster.jpg"]))
        page = (out / "index.html").read_text(encoding="utf-8")
        links = page.split('<div class="links">', 1)[1].split("</div>", 1)[0]
        hrefs = [h.split('"', 1)[0] for h in links.split('href="')[1:]]
        self.assertEqual(hrefs, [f"{f.id}/{n}" for n in listed])  # 1080p first (primary), then 720p, music, cover
        self.assertIn(f'<a class="btn primary" href="{f.id}/{f.output("narrated")}" download>⬇ {film._pair("hd")}</a>', links)
        self.assertIn(film._pair("music_only_small"), links)
        self.assertNotIn(f.output("music_only"), page)
        reg = json.loads((out / "films.json").read_text(encoding="utf-8"))["films"][0]
        self.assertEqual(sorted(reg["videos"]), sorted(["narrated", "narrated_720p", "music_only_720p", "cover"]))
        items = film.items(self.sb.book)
        self.assertEqual(items[0]["download_url"], f"films/{f.id}/{f.output('narrated')}")
        self.assertEqual(items[0]["watch_url"], f"films/{f.id}/{f.output('narrated_720p')}")

    def test_publish_without_videos_shows_the_poster_and_a_note(self):
        self.missing = ["node"]
        out = self.sb.root / "_site" / "bk" / "films"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = film.build(self.sb.site, self.sb.book, out)
        self.assertEqual(status, {"001-golden-deficit": "skipped"})
        f = self.sb.film()
        self.assertEqual(sorted(p.name for p in (out / f.id).iterdir()), ["poster.jpg"])
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<video", page)
        self.assertIn(f'<img src="{f.id}/poster.jpg"', page)
        self.assertIn(film.t("en", "unbuilt"), page)
        self.assertFalse(json.loads((out / "films.json").read_text(encoding="utf-8"))["films"][0]["built"])


class ToolchainTest(unittest.TestCase):
    def test_reports_what_is_missing(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        env = {"KOKORO_MODEL_DIR": str(tmp / "models"), "FILM_CACHE": str(tmp / "cache"), "PYTHON": str(tmp / "nope"),
               "FFMPEG": "", "PW_CHROMIUM_PATH": str(tmp / "no-chrome")}
        with mock.patch.dict(os.environ, env), mock.patch.object(film.shutil, "which", return_value=None):
            missing = "\n".join(film.toolchain_missing())
        for needle in ("ffmpeg", "node", "Chromium", f"the film Python packages for {tmp / 'nope'}",
                       "kokoro-v1.0.onnx, voices-v1.0.bin", "theme/film/setup.sh"):
            self.assertIn(needle, missing)

    def test_film_python(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        env = {k: v for k, v in os.environ.items() if k != "PYTHON"}
        env["FILM_CACHE"] = str(tmp)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertNotEqual(film.film_python(), str(tmp / "venv" / "bin" / "python"))
            venv = tmp / "venv" / "bin" / "python"
            venv.parent.mkdir(parents=True)
            venv.write_text("#!/bin/sh\n")
            venv.chmod(0o755)
            self.assertEqual(film.film_python(), str(venv))  # the venv setup.sh creates
            self.assertEqual(film.model_dir(), tmp / "models")
            with mock.patch.dict(os.environ, {"PYTHON": "/opt/py"}):
                self.assertEqual(film.film_python(), "/opt/py")
        # film.sh picks the same interpreter
        self.assertIn('VENV_PY="${FILM_CACHE:-$ROOT/.cache/film}/venv/bin/python"',
                      (THEME_FILM / "film.sh").read_text(encoding="utf-8"))

    def test_setup_and_requirements(self):
        setup = (THEME_FILM / "setup.sh").read_text(encoding="utf-8")
        self.assertIn(f'KOKORO_RELEASE="{film.KOKORO_RELEASE}"', setup)
        for f in film.KOKORO_FILES:
            self.assertIn(f, setup)
        self.assertIn('"$PYTHON" -m pip install', setup)
        self.assertIn('-r "$HERE/requirements.txt"', setup)
        reqs = [ln.strip() for ln in (THEME_FILM / "requirements.txt").read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
        self.assertTrue(reqs)
        for req in reqs:
            self.assertRegex(req, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*$")
        names = {r.split("==")[0].lower().replace("_", "-") for r in reqs}
        self.assertLessEqual({"kokoro-onnx", "numpy", "scipy", "soundfile", "onnxruntime"}, names)

    def test_the_build_writes_no_committed_file(self):
        # the committed poster is only written by the `poster` step, which the build never runs
        self.assertNotIn("poster", (THEME_FILM / "render_all.sh").read_text(encoding="utf-8").split("set -euo")[1])
        sh = (THEME_FILM / "film.sh").read_text(encoding="utf-8")
        self.assertEqual(sh.count('"$FILM/poster.jpg"'), 1)
        self.assertIn('poster)   py build.py "$FILM" && node "$HERE/poster.js" "$OUT" "$(meta cover)" "$FILM/poster.jpg"', sh)
        all_step = sh.split("  all)", 1)[1].split(";;", 1)[0]
        self.assertNotIn("poster", all_step)
        self.assertNotIn("notes)", sh)


class SiteHostingTest(unittest.TestCase):
    """tbook.site: chapter embeds of films the site does not host are marked; print.html sources repaired."""

    # as mdBook writes the embed of tbook.film _local_player (attributes re-serialized), with its fallback poster
    FIGURE = ('<figure class="tr-media tr-film" data-film="001-x" data-tr-video="films/001-x/v720.mp4">\n'
              '<video class="tr-film-player" controls="" preload="metadata" playsinline="" poster="../films/001-x/poster.jpg" '
              'data-tr-poster="films/001-x/poster.jpg"><source src="../films/001-x/v720.mp4" '
              'data-tr-src="films/001-x/v720.mp4" type="video/mp4"></video>\n'
              '<img class="tr-film-poster tr-film-fallback" src="../films/001-x/poster.jpg" alt="A > B"></figure>')

    def test_mark_films(self):
        from tbook import site

        bdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bdir)
        after = '\n<p>Text.</p>\n<video class="tr-film-player" preload="metadata"></video>'  # not in a film figure
        marked = site.mark_films(self.FIGURE + after, bdir)
        self.assertIn('<figure class="tr-media tr-film tr-film-unbuilt" data-film="001-x"', marked)
        # the hidden player does not request the missing video (a 404 in the console on every such page)
        self.assertIn('<video class="tr-film-player" controls="" preload="none" playsinline=""', marked)
        self.assertNotIn('preload="metadata" playsinline', marked)
        self.assertTrue(marked.endswith(after), "only the film's figure is changed")
        self.assertEqual(site.mark_films(marked, bdir), marked)  # idempotent
        (bdir / "films" / "001-x").mkdir(parents=True)
        (bdir / "films" / "001-x" / "v720.mp4").write_bytes(b"mp4")
        self.assertEqual(site.mark_films(marked, bdir), self.FIGURE + after)  # reversible once the video is there
        external = ('<figure class="tr-media tr-film" data-film="trureturing-film:film-001-v1">'
                    '<video class="tr-film-player" preload="none"></video></figure>')
        self.assertEqual(site.mark_films(external, bdir), external)

    def test_mark_films_adds_missing_attributes(self):
        from tbook import site

        bdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bdir)
        bare = '<figure data-tr-video="films/a.mp4"><video class="tr-film-player" controls/></figure>'
        marked = site.mark_films(bare, bdir)
        self.assertEqual(marked, '<figure data-tr-video="films/a.mp4" class="tr-film-unbuilt">'
                                 '<video class="tr-film-player" controls preload="none"/></figure>')
        (bdir / "films").mkdir()
        (bdir / "films" / "a.mp4").write_bytes(b"mp4")
        self.assertEqual(site.mark_films(marked, bdir), '<figure data-tr-video="films/a.mp4" class="">'
                                                        '<video class="tr-film-player" controls preload="metadata"/></figure>')
        unclosed = '<figure data-tr-video="films/b.mp4"><video class="tr-film-player" preload="metadata">'
        self.assertIn('preload="none"', site.mark_films(unclosed, bdir), "a figure cut short is still marked")

    def test_print_page_sources(self):
        from tbook import site

        # a chapter one level down, copied into print.html: mdBook rewrites the <img> but not the <video>
        nested = self.FIGURE.replace('"../films', '"../../films').replace('src="../../films/001-x/poster', 'src="../films/001-x/poster')
        printed = site.fix_print_media(nested)
        self.assertIn('<source src="../films/001-x/v720.mp4" data-tr-src=', printed)
        self.assertIn('poster="../films/001-x/poster.jpg" data-tr-poster=', printed)
        self.assertNotIn("../../", printed)

    @needs_example
    def test_site_build_marks_the_chapter_pages(self):
        from tbook import site

        sb = Sandbox(self)
        build_root = sb.root / "build"
        page = f"<html><body>{self.FIGURE.replace('001-x', '001-golden-deficit')}</body></html>"
        for rel in ("index.html", "print.html"):
            p = build_root / "html" / "bk" / "zh" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(page, encoding="utf-8")
        out = sb.root / "_site"
        with mock.patch.object(film, "toolchain_missing", return_value=["node"]), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            site.build(sb.site, [sb.book], out, build_root=build_root)
        chapter = (out / "bk" / "zh" / "index.html").read_text(encoding="utf-8")
        self.assertIn("tr-film tr-film-unbuilt", chapter)
        self.assertIn('preload="none"', chapter)
        printed = (out / "bk" / "zh" / "print.html").read_text(encoding="utf-8")
        self.assertIn("tr-film-unbuilt", printed)
        self.assertIn('preload="none"', printed)
        landing = (out / "bk" / "index.html").read_text(encoding="utf-8")
        films_html = landing.split('id="films"', 1)[1].split("</section>", 1)[0]
        self.assertIn(film.t("zh", "unbuilt"), films_html)
        self.assertNotIn(".mp4", films_html)
        # the videos are built: `./tbook build films` (only films) hosts them and unmarks the chapters

        def fake_render(f: film.Film, dest: Path) -> None:
            dest.mkdir(parents=True, exist_ok=True)
            for name in f.videos().values():
                (dest / name).write_bytes(b"mp4")

        # the figure in this page names the 720p file of film.json
        v720 = sb.film().output("narrated_720p")
        for p in (out / "bk" / "zh").glob("*.html"):
            p.write_text(p.read_text(encoding="utf-8").replace("v720.mp4", v720), encoding="utf-8")
        with mock.patch.object(film, "toolchain_missing", return_value=[]), \
                mock.patch.object(film, "render_videos", side_effect=fake_render), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            site.build(sb.site, [sb.book], out, only={"films"}, build_root=build_root)
        chapter = (out / "bk" / "zh" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("tr-film-unbuilt", chapter)
        self.assertIn('class="tr-film-player" controls="" preload="metadata"', chapter)
        self.assertNotIn('preload="none"', chapter)
        self.assertTrue((out / "bk" / "films" / "001-golden-deficit" / v720).is_file())
        landing = (out / "bk" / "index.html").read_text(encoding="utf-8")
        films_html = landing.split('id="films"', 1)[1].split("</section>", 1)[0]
        self.assertIn(f'href="films/001-golden-deficit/{v720}"', films_html)
        self.assertNotIn(film.t("zh", "unbuilt"), films_html)


@needs_example
@needs_listed_example
class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_items(self):
        items = film.items(example_book())
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual((it["kind"], it["id"], it["number"]), ("film", "001-golden-deficit", "001"))
        self.assertEqual(it["title"]["zh"], "黄金亏量")
        self.assertEqual(it["title"]["en"], "The Golden Deficit")
        self.assertEqual(it["poster"], "films/001-golden-deficit/poster.jpg")
        self.assertEqual(it["href"], "films/index.html#001-golden-deficit")
        self.assertEqual(it["watch_url"], "films/001-golden-deficit/example-monograph_001_720p_narrated.mp4")
        # the example lists no 1080p video: the narrated video to download is the 720p one
        self.assertEqual(it["download_url"], it["watch_url"])
        self.assertEqual(it["cover_url"], "films/001-golden-deficit/example-monograph_001_cover.jpg")
        self.assertEqual(it["note"]["en"], film.t("en", "unbuilt"))
        self.assertFalse({"release_tag", "published", "release_url"} & set(it))
        self.assertEqual({r["gid"] for r in it["lean"]}, {GID3, GIDI})
        self.assertTrue(all(r["url"].startswith("https://github.com/the-omega-institute/trureturing/blob/") for r in it["lean"]))

    def test_build_page(self):
        out = self.tmp / "films"
        film.build(config.load_site(), example_book(), out, videos=False)
        page = (out / "index.html").read_text(encoding="utf-8")
        for needle in ("黄金亏量", "The Golden Deficit", 'id="001-golden-deficit"', "LEAN ✓",
                       "D5.S1.Deficit.deficit_three_valued", 'href="assets/films.css"', "data-lang-set"):
            self.assertIn(needle, page)
        self.assertTrue((out / "001-golden-deficit" / "poster.jpg").is_file())
        for name in ("tokens.css", "films.css", "films.js"):
            self.assertTrue((out / "assets" / name).is_file())
        data = json.loads((out / "films.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["trureturing"]["commit"], lean.Lock.load().commit)

    def test_build_refuses_errors(self):
        book = temp_book(self.tmp / "books")
        d = copy_example(book)
        (d / "film.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(film.FilmError):
            film.build(config.load_site(), book, self.tmp / "out", videos=False)


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = temp_book(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_default_release_date_uses_utc(self):
        with mock.patch.object(film, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
            created = film.scaffold(self.book, "002-carry-rules", "进位规则", "Carry Rules")
            clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(json.loads(created[0].read_text(encoding="utf-8"))["released"], "2026-12-31")

    def test_new_film_is_valid(self):
        created = film.scaffold(self.book, "002-carry-rules", "进位规则", "The Carry Rules", released="2026-11-08")
        self.assertEqual([p.name for p in created], ["film.json", "script.json", "scenes.js"])
        meta = json.loads(created[0].read_text(encoding="utf-8"))
        self.assertFalse(set(meta) & set(film.LEGACY_KEYS))
        self.assertEqual(meta["title_zh"], "进位规则")
        self.assertEqual(meta["publication_basis"], "pinned")
        self.assertNotIn("subject_commit", meta)
        # the default: the 720p narrated video and the cover
        self.assertEqual(meta["outputs"], {"narrated_720p": "film-fixture_002_720p_narrated.mp4",
                                           "cover": "film-fixture_002_cover.jpg"})
        self.assertEqual(meta["resolution"], "1280x720@30")
        issues = film.check(self.book)
        self.assertEqual(errors(issues), [], [i.format() for i in issues])
        self.assertNotIn("@@", "".join(p.read_text(encoding="utf-8") for p in created))

    def test_scaffold_rejects(self):
        film.scaffold(self.book, "002-carry-rules", "进位", "Carry")
        for args in (("002-other", "甲", "A"), ("002-carry-rules", "甲", "A"), ("carry", "甲", "A"),
                     ("003-x", "", "A"), ("003-y", '引"号', "A")):
            with self.assertRaises(film.FilmError, msg=str(args)):
                film.scaffold(self.book, *args)

    def test_cli(self):
        args = SimpleNamespace(action="new", rest=[str(self.book.dir), "004-cli-made", "命令行", "From the CLI"])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(film.cli(args), 0)
        self.assertTrue((self.book.films_dir / "004-cli-made" / "scenes.js").is_file())
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(film.cli(SimpleNamespace(action="new", rest=["only-one"])), 2)
            self.assertEqual(film.cli(SimpleNamespace(action="list", rest=[])), 0)
            self.assertEqual(film.cli(SimpleNamespace(action="list", rest=["no-such-book"])), 1)


class PipelineTest(unittest.TestCase):
    """The stdlib parts of theme/film: tokens, page assembly (without fonts), JavaScript syntax."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        # theme/film/build.py imports its sibling common.py; load it under a private name.
        sys.path.insert(0, str(THEME_FILM))
        try:
            spec = importlib.util.spec_from_file_location("tbook_test_film_build", THEME_FILM / "build.py")
            cls.build = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.build)
        finally:
            sys.path.remove(str(THEME_FILM))

    def test_tokens_from_generated_mjs(self):
        tok = self.build.film_tokens()
        tokens = json.loads(paths.TOKENS.read_text(encoding="utf-8"))
        self.assertEqual(tok["film"], tokens["film"])
        self.assertEqual(tok["sem"]["lean"], tokens["film"]["green"])
        self.assertEqual(tok["sem"]["open"], tokens["film"]["red"])
        self.assertEqual(tok["sem"]["argued"], tokens["film"]["vio"])
        self.assertEqual(tok["sem"]["now"], tokens["film"]["gold"])
        self.assertEqual(tok["font"]["film-display"][0], "Orbitron")

    def test_unicode_ranges(self):
        self.assertEqual(self.build._ranges("U+0000-00FF, U+0131,U+4??"), [(0, 255), (0x131, 0x131), (0x400, 0x4FF)])

    @needs_example
    def test_assemble_page(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            book = temp_book(tmp)
            d = copy_example(book)
            with mock.patch.object(film, "_lock", return_value=fake_lock()), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                page = self.build.build(d)
            html = page.read_text(encoding="utf-8")
            self.assertIn("window.FILM_TOKENS=", html)
            self.assertIn('"provisional":true', html)
            self.assertIn("SCENES.zeck", html)
            self.assertIn("window.ready = boot()", html)
            self.assertNotIn("</script>\n<script>\n</script>", html)
            self.assertTrue((d / "out" / "timeline.provisional.json").is_file())
            data = json.loads(html.split("window.DATA=", 1)[1].split(";</script>", 1)[0].replace("<\\/", "</"))
            self.assertEqual(data["book"]["title"]["en"], "Test Book")
            self.assertEqual({r["short"] for r in data["lean"]}, {"deficit_three_valued", "deficit_integer"})
            self.assertIn("黄", data["fontText"])
            if (paths.ROOT / "node_modules" / "@fontsource" / "noto-sans-sc").is_dir():
                self.assertIn(["Noto Sans SC", 700], data["fonts"])
                self.assertTrue(any((d / "out" / "fonts" / "noto-sans-sc").iterdir()))
            with self.assertRaises(SystemExit):  # --strict refuses provisional timing
                with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    self.build.build(d, strict=True)
        finally:
            shutil.rmtree(tmp)

    @unittest.skipUnless(NODE, "node not available")
    def test_javascript_syntax(self):
        files = [THEME_FILM / "engine.js", paths.TEMPLATES / "film" / "scenes.js"]
        if EXAMPLE_FILM.is_dir():  # the example book may have been deleted downstream
            files.append(EXAMPLE_FILM / "scenes.js")
        self.assertEqual(film.js_syntax_errors(files), {})
        import subprocess

        for name in ("lib.js", "render.js", "poster.js", "shot.js", "site/films.js"):
            r = subprocess.run([NODE, "--check", str(THEME_FILM / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_scripts_are_executable(self):
        import os

        for name in ("film.sh", "render_all.sh", "mux.sh", "setup.sh"):
            self.assertTrue(os.access(THEME_FILM / name, os.X_OK), name)
        # the 720p videos are encoded from the frames, never again from a 1080p master
        self.assertFalse((THEME_FILM / "small.sh").exists())

    def test_render_plan(self):
        plan = film.render_plan
        self.assertEqual(plan(["narrated_720p", "cover"]),
                         {"outputs": ["narrated_720p", "cover"], "renditions": ["720p"], "music": False})
        self.assertEqual(plan(["cover", "music_only_720p", "narrated_720p"]),
                         {"outputs": ["narrated_720p", "music_only_720p", "cover"], "renditions": ["720p"], "music": True})
        self.assertEqual(plan(["narrated", "narrated_720p", "cover"])["renditions"], ["master", "720p"])
        self.assertEqual(plan(["music_only"]), {"outputs": ["music_only"], "renditions": ["master"], "music": True})
        self.assertEqual(plan(["cover"])["renditions"], [])
        with self.assertRaisesRegex(film.FilmError, "unknown output narrated_4k"):
            plan(["narrated_4k"])
        with self.assertRaisesRegex(film.FilmError, "no outputs"):
            plan([])

    @needs_example
    def test_plan_script(self):
        """theme/film/plan.py: the shell assignments film.sh, render_all.sh and mux.sh evaluate."""
        import subprocess

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        book = temp_book(tmp)
        d = copy_example(book)

        def run(outputs: str | None) -> subprocess.CompletedProcess:
            env = {k: v for k, v in os.environ.items() if k != "FILM_OUTPUTS"}
            if outputs is not None:
                env["FILM_OUTPUTS"] = outputs
            return subprocess.run([sys.executable, str(THEME_FILM / "plan.py"), str(d)], capture_output=True,
                                  text=True, env=env)

        r = run(None)  # what film.json lists
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "OUTPUTS='narrated_720p cover'", "RENDITIONS=720p", "MUSIC_MIX=0", "NARRATED=''", "MUSIC_ONLY=''",
            "NARRATED_720P=film-fixture_001_720p_narrated.mp4", "MUSIC_ONLY_720P=''", "COVER=film-fixture_001_cover.jpg"])
        r = run("narrated, music_only_720p")  # by hand, also unlisted outputs (default file names)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RENDITIONS=master,720p", r.stdout)
        self.assertIn("MUSIC_MIX=1", r.stdout)
        self.assertIn("NARRATED=film-fixture_001_narrated_EN_subs_ZH-EN.mp4", r.stdout)
        self.assertIn("COVER=''", r.stdout)
        r = run("narrated_4k")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown output narrated_4k", r.stderr)

    def test_pipeline_scripts_follow_the_plan(self):
        sh = (THEME_FILM / "film.sh").read_text(encoding="utf-8")
        all_step = sh.split("  all)", 1)[1].split(";;", 1)[0]
        self.assertIn('export FILM_OUTPUTS="$*"', all_step)
        self.assertIn('if [ -n "$COVER" ]; then FILM_STRICT=1 cover; fi', all_step)
        self.assertNotIn("small", sh)
        render_all = (THEME_FILM / "render_all.sh").read_text(encoding="utf-8")
        self.assertIn('--renditions "$RENDITIONS"', render_all)
        mux = (THEME_FILM / "mux.sh").read_text(encoding="utf-8")
        for needle in ("-movflags +faststart", "-ar 48000", 'mux video_720p.mp4 mix_voice.wav 128k "$NARRATED_720P"',
                       'mux video_only.mp4 mix_voice.wav 192k "$NARRATED"', "-c:v copy"):
            self.assertIn(needle, mux)
        self.assertNotIn("libx264", mux)  # nothing is encoded twice
        render = (THEME_FILM / "render.js").read_text(encoding="utf-8")
        self.assertIn("'hqdn3d=3:2:6:5,scale=1280:720:flags=lanczos,format=yuv420p'", render)
        self.assertIn("viewport: { width: 1920, height: 1080 }", (THEME_FILM / "lib.js").read_text(encoding="utf-8"))

    @needs_example
    def test_render_videos_passes_the_listed_outputs(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        book = temp_book(tmp)
        d = copy_example(book, outputs=("narrated_720p", "music_only", "cover"))
        f = film.get(book, d.name)
        calls = []

        def fake_run(args, **kw):
            calls.append((args, kw["env"]))
            (d / "out").mkdir(exist_ok=True)
            for key in film.VIDEO_OUTPUTS:  # a pipeline that also leaves other files in out/
                (d / "out" / f.output(key)).write_bytes(key.encode())
            return SimpleNamespace(returncode=0)

        with mock.patch.object(film.subprocess, "run", side_effect=fake_run), \
                mock.patch.dict(os.environ, {"FILM_OUTPUTS": "narrated"}):
            film.render_videos(f, tmp / "dest")
        (args, env), = calls
        self.assertEqual(args[1:], [str(d), "all", "music_only", "narrated_720p", "cover"])
        self.assertNotIn("FILM_OUTPUTS", env)
        self.assertEqual(env["FILM_STRICT"], "1")
        # only the listed outputs are copied
        self.assertEqual(sorted(p.name for p in (tmp / "dest").iterdir()), sorted(f.videos().values()))
        (d / "out" / f.output("music_only")).unlink()

        def no_write(args, **kw):
            return SimpleNamespace(returncode=0)

        with mock.patch.object(film.subprocess, "run", side_effect=no_write):
            with self.assertRaisesRegex(film.FilmError, "did not write out/film-fixture_001_music_only"):
                film.render_videos(f, tmp / "dest2")


class DoctorFfmpegTest(unittest.TestCase):
    def test_doctor_honours_ffmpeg_env(self):
        """./tbook doctor looks for ffmpeg where the film build does: $FFMPEG, else PATH."""
        from tbook import doctor

        with mock.patch.dict(os.environ, {"FFMPEG": "/opt/ff/bin/ffmpeg"}):
            report = mock.Mock()
            doctor.check_ffmpeg(report)
        check = report.add.call_args[0][0]
        self.assertTrue(check.ok)
        self.assertIn("/opt/ff/bin/ffmpeg", check.detail)
        with mock.patch.dict(os.environ, {"FFMPEG": "", "PATH": ""}):
            report = mock.Mock()
            doctor.check_ffmpeg(report)
        self.assertFalse(report.add.call_args[0][0].ok)


if __name__ == "__main__":
    unittest.main()
