"""Prepared images are transferred whole; publication cannot silently recapture them."""
import json
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from tbook import buildcache, derived
from test_buildcache import Scratch, write
from test_ci_performance import ci_module

stills = ci_module('stills')


class PreparedImagesTest(unittest.TestCase):
    def test_missing_pages_share_one_capture_process_and_restored_pages_never_capture(self):
        with Scratch() as s:
            book = SimpleNamespace(slug='demo', viz_dir=s.root / 'books/demo/viz')
            write(book.viz_dir / 'visualizations.json', '{}')
            units = [buildcache.Unit('viz-stills', f'demo/{vid}', buildcache.Inputs().text('source', vid),
                                     [book.viz_dir / vid / 'thumb.jpg']) for vid in ['one', 'two']]

            def render(args, **kwargs):
                self.assertEqual(args[-3:], ['demo', 'one', 'two'])
                for unit in units:
                    write(unit.outputs[0], unit.name)

            with mock.patch.object(buildcache, 'viz_units', return_value=units), \
                    mock.patch.object(derived.subprocess, 'run', side_effect=render) as capture:
                derived.images(book)
                self.assertEqual(capture.call_count, 1)
                for unit in units:
                    unit.outputs[0].unlink()
                with mock.patch.dict(os.environ, TBOOK_STILLS_REQUIRE_CACHE='1'):
                    derived.images(book)
                self.assertEqual(capture.call_count, 1)
                for unit in units:
                    self.assertEqual(unit.outputs[0].read_text(), unit.name)
                # A corrupt prepared entry must fail before an export starts a new browser.
                (units[0].entry_dir() / 'files/0').write_text('corrupt')
                with mock.patch.dict(os.environ, TBOOK_STILLS_REQUIRE_CACHE='1'), \
                        self.assertRaisesRegex(Exception, 'missing prepared'):
                    derived.images(book)
                self.assertEqual(capture.call_count, 1)

    def test_worker_exports_only_selected_complete_image_entries(self):
        with Scratch() as s:
            book = SimpleNamespace(slug='demo', viz_dir=s.root / 'books/demo/viz')
            write(book.viz_dir / 'visualizations.json', json.dumps({'visualizations': [
                {'id': 'one', 'status': 'live'}, {'id': 'two', 'status': 'live'}]}))
            unit = buildcache.Unit('viz-stills', 'demo/one', buildcache.Inputs().text('source', 'one'),
                                   [book.viz_dir / 'one/thumb.jpg'])
            write(unit.outputs[0], 'image')
            buildcache.store(unit)
            with mock.patch.object(stills.config, 'load_books', return_value=[book]), \
                    mock.patch.object(stills.theme, 'write'), mock.patch.object(stills.derived, 'refresh'), \
                    mock.patch.object(stills.derived, 'images'), \
                    mock.patch.object(stills.buildcache, 'viz_units', return_value=[unit]):
                dest = s.root / 'export'
                stills.prepare(['demo/one'], dest)
                entries = list(stills.cache_store.verified(dest))
                self.assertEqual([meta['unit'] for _, meta in entries], ['demo/one'])
                for invalid in [[], ['demo/one', 'demo/one'], ['demo/missing'], ['../one']]:
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        stills.prepare(invalid, s.root / 'invalid')
