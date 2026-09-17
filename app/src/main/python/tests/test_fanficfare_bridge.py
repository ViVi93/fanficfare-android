# -*- coding: utf-8 -*-
"""Tests for the fanficfare_bridge module.

Run with:
    cd /home/ubuntu/workspace/fanficfare-android/app/src/main/python
    /tmp/ff_venv/bin/python3 -m unittest tests.test_fanficfare_bridge -v

All tests use mocked data — NO live network access is required.
"""
import sys, os, json, base64, zipfile
sys.path.insert(0, '.')

import unittest
import fanficfare_bridge as bridge
import importlib


class TestBridgeExtractCoverCandidates(unittest.TestCase):
    """Tests for the bridge extract_cover_candidates function."""

    def test_json_roundtrip(self):
        """extract_cover_candidates must accept JSON-serialized
        ProviderResult dicts (as sent from the Android Kotlin side)
        and correctly reconstruct ProviderResult objects so that
        result.ok works inside cover_manager.
        """
        mp = importlib.import_module('metadata_providers')

        pr = mp.ProviderResult(
            provider='google_books',
            source_id='test-id',
            metadata={
                'title': 'Test Book',
                'authors': ['Test Author'],
                'isbn13': '9781234567890',
                'image_links': {'large': 'https://books.google.com/cover.jpg'},
            },
        )
        results_json = json.dumps([dict(pr)])

        result = json.loads(bridge.extract_cover_candidates(results_json))
        self.assertTrue(result['ok'],
                        "extract_cover_candidates returned error: %s" % result.get('error', ''))
        candidates = result['candidates']
        self.assertGreaterEqual(len(candidates), 1,
                                "expected at least 1 candidate, got %d" % len(candidates))
        self.assertEqual(candidates[0]['url'], 'https://books.google.com/cover.jpg')
        self.assertEqual(candidates[0]['source'], 'google_books')

    def test_empty_results(self):
        """An empty results list should produce zero candidates, not an error."""
        result = json.loads(bridge.extract_cover_candidates(json.dumps([])))
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['candidates']), 0)

    def test_failed_result_skipped(self):
        """A failed ProviderResult (with error) should produce no candidates."""
        mp = importlib.import_module('metadata_providers')

        failed_pr = mp.ProviderResult(
            provider='google_books',
            source_id='test-id',
            metadata={},  # empty — failed result
            error='HTTP 500: Internal Server Error',
        )
        results_json = json.dumps([dict(failed_pr)])
        result = json.loads(bridge.extract_cover_candidates(results_json))
        self.assertTrue(result['ok'],
                        "extract_cover_candidates returned error: %s" % result.get('error', ''))
        self.assertEqual(len(result['candidates']), 0,
                         "failed result should produce no candidates")


class TestBridgeApplyMetadataAndCover(unittest.TestCase):
    """Tests for the bridge apply_metadata_and_cover function."""

    def _create_test_epub(self, path):
        """Create a minimal test EPUB at the given path."""
        opf_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
            '<dc:identifier id="bookid">urn:uuid:test-id</dc:identifier>'
            '<dc:title>Original Title</dc:title>'
            '<dc:creator id="author1">Test Author</dc:creator>'
            '<dc:language>en</dc:language>'
            '<meta name="cover" content="cover-image"/>'
            '</metadata>'
            '<manifest>'
            '<item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>'
            '<item id="opf" href="content.opf" media-type="application/oebps/package+xml"/>'
            '</manifest>'
            '<spine><itemref idref="opf"/></spine>'
            '</package>'
        )
        jpeg = base64.b64decode(
            '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG'
            'BgYHBwYI/w4JCxgQJCQwMCwsKCs0NDx0fE9c'
            'FBwcHBQgHBgkJCzsYGRgZGBcUGBgZGBgYGBg'
            'ZGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
            'ZGBgYGBgZGBgYGBgYGBgYGBgYGBgYGBgYGBg',
        )
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
            zf.writestr('content.opf', opf_xml.encode('utf-8'))
            zf.writestr('cover.jpg', jpeg)

    def test_atomic_metadata_only(self):
        """apply_metadata_and_cover should write metadata atomically
        without a cover, returning metadata_written=True.
        """
        path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'test_atomic_meta.epub')
        self._create_test_epub(path)

        fields = {'title': 'Atomic Title'}
        result = json.loads(bridge.apply_metadata_and_cover(
            path, json.dumps(fields), None, None, None, '.bak'
        ))
        self.assertTrue(result['ok'],
                        "apply_metadata_and_cover failed: %s" % result.get('error', ''))
        self.assertTrue(result['metadata_written'], "metadata_written should be True")
        self.assertFalse(result['cover_written'], "cover_written should be False for metadata-only")

        # Verify the metadata was actually written
        ee = importlib.import_module('epub_editor')
        md = ee.read_metadata_fields(path)
        self.assertTrue(md['ok'], "read_metadata_fields failed")
        self.assertEqual(md['metadata']['title'], 'Atomic Title', "title mismatch")

        os.unlink(path)
        if os.path.exists(path + '.bak'):
            os.unlink(path + '.bak')


class TestBridgeApplyDefensive(unittest.TestCase):
    """Tests for Phase 8 defensive validation in apply_metadata_and_cover."""

    TEST_OPF = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
        '<dc:identifier id="bookid">urn:uuid:test-def-id</dc:identifier>'
        '<dc:title>Defensive Test</dc:title>'
        '<dc:creator id="author1">Author</dc:creator>'
        '<dc:language>en</dc:language>'
        '</metadata>'
        '<manifest>'
        '<item id="opf" href="content.opf" media-type="application/oebps/package+xml"/>'
        '</manifest>'
        '<spine><itemref idref="opf"/></spine>'
        '</package>'
    )

    def _create_minimal_epub(self, path):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
            zf.writestr('content.opf', self.TEST_OPF.encode('utf-8'))

    def test_empty_fields_no_cover_rejected(self):
        """Applying with empty fields and no cover must be rejected —
        this is the defensive guard against applying a failed provider result.
        """
        path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'test_def_empty.epub')
        self._create_minimal_epub(path)

        result = json.loads(bridge.apply_metadata_and_cover(
            path, json.dumps({}), None, None, None, None
        ))
        self.assertFalse(result['ok'], "should reject empty fields with no cover")
        self.assertFalse(result['metadata_written'])
        self.assertFalse(result['cover_written'])
        # Original EPUB must remain untouched
        with zipfile.ZipFile(path, 'r') as zf:
            opf = zf.read('content.opf').decode('utf-8')
            self.assertIn('Defensive Test', opf, "original title must be preserved")
        os.unlink(path)

    def test_empty_fields_with_cover_still_works(self):
        """Applying a cover with empty fields is a cover-only write and
        should be allowed (e.g. the 'Apply Cover' button passes {}).
        """
        path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'test_def_cover_only.epub')
        self._create_minimal_epub(path)

        jpeg = base64.b64decode(
            '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG'
            'BgYHBwYI/w4JCxgQJCQwMCwsKCs0NDx0fE9c'
            'FBwcHBQgHBgkJCzsYGRgZGBcUGBgZGBgYGBg'
            'ZGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg',
        )
        b64 = base64.b64encode(jpeg).decode('ascii')

        result = json.loads(bridge.apply_metadata_and_cover(
            path, json.dumps({}), b64, 'image/jpeg', None, None
        ))
        self.assertTrue(result['ok'],
                        "cover-only apply failed: %s" % result.get('error', ''))
        self.assertTrue(result['metadata_written'], "OPF is rewritten even for cover-only")
        self.assertTrue(result['cover_written'], "cover should be written")
        os.unlink(path)


class TestBridgeApplyMetadataOnly(unittest.TestCase):
    """Tests for Phase 8: metadata-only apply through the combined bridge path."""

    TEST_OPF = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
        '<dc:identifier id="bookid">urn:uuid:test-mo-id</dc:identifier>'
        '<dc:title>Metadata Only Test</dc:title>'
        '<dc:creator id="author1">Author</dc:creator>'
        '<dc:language>en</dc:language>'
        '</metadata>'
        '<manifest>'
        '<item id="opf" href="content.opf" media-type="application/oebps/package+xml"/>'
        '</manifest>'
        '<spine><itemref idref="opf"/></spine>'
        '</package>'
    )

    def _create_minimal_epub(self, path):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
            zf.writestr('content.opf', self.TEST_OPF.encode('utf-8'))

    def test_metadata_only_apply_via_combined_bridge(self):
        """Metadata-only apply through apply_metadata_and_cover should
        succeed, write the metadata, and NOT write a cover.
        """
        path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'test_meta_only.epub')
        self._create_minimal_epub(path)

        fields = {'title': 'New Meta Only Title', 'publisher': 'Phase 8 Publisher'}
        result = json.loads(bridge.apply_metadata_and_cover(
            path, json.dumps(fields), None, None, None, '.bak'
        ))
        self.assertTrue(result['ok'],
                        "metadata-only apply failed: %s" % result.get('error', ''))
        self.assertTrue(result['metadata_written'])
        self.assertFalse(result['cover_written'])
        self.assertIn('title', result['changed_fields'])
        self.assertIn('publisher', result['changed_fields'])

        ee = importlib.import_module('epub_editor')
        md = ee.read_metadata_fields(path)
        self.assertEqual(md['metadata']['title'], 'New Meta Only Title')
        self.assertEqual(md['metadata']['publisher'], 'Phase 8 Publisher')
        os.unlink(path)
        if os.path.exists(path + '.bak'):
            os.unlink(path + '.bak')


class TestBridgeCombinedAtomic(unittest.TestCase):
    """Tests for Phase 8: combined metadata + cover atomic write."""

    TEST_OPF = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
        '<dc:identifier id="bookid">urn:uuid:test-cb-id</dc:identifier>'
        '<dc:title>Combined Atomic Test</dc:title>'
        '<dc:creator id="author1">Author</dc:creator>'
        '<dc:language>en</dc:language>'
        '<meta name="cover" content="cover-image"/>'
        '</metadata>'
        '<manifest>'
        '<item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>'
        '<item id="opf" href="content.opf" media-type="application/oebps/package+xml"/>'
        '</manifest>'
        '<spine><itemref idref="opf"/></spine>'
        '</package>'
    )

    def _create_epub_with_cover(self, path):
        jpeg = base64.b64decode(
            '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG'
            'BgYHBwYI/w4JCxgQJCQwMCwsKCs0NDx0fE9c'
            'FBwcHBQgHBgkJCzsYGRgZGBcUGBgZGBgYGBg'
            'ZGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg',
        )
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
            zf.writestr('content.opf', self.TEST_OPF.encode('utf-8'))
            zf.writestr('cover.jpg', jpeg)

    def test_combined_atomic_write(self):
        """Both metadata and cover applied in one call should produce
        a single atomic write with both metadata_written and cover_written=True.
        """
        path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'test_combined_atomic.epub')
        self._create_epub_with_cover(path)

        # Read original cover for comparison
        with zipfile.ZipFile(path, 'r') as zf:
            original_cover = zf.read('cover.jpg')

        # New cover data (different bytes)
        new_jpeg = base64.b64decode(
            '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG'
            'BgYHBwYI/w4JCxgQJCQwMCwsKCs0NDx0fE9c'
            'FBwcHBQgHBgkJCzsYGRgZGBcUGBgZGBgYGBg'
            'aGVsbG93b3JsZGRtZGFtbXlvdWxkZGRk',
        )
        b64 = base64.b64encode(new_jpeg).decode('ascii')

        fields = {'title': 'New Combined Title'}
        result = json.loads(bridge.apply_metadata_and_cover(
            path, json.dumps(fields), b64, 'image/jpeg', None, '.bak'
        ))
        self.assertTrue(result['ok'],
                        "combined apply failed: %s" % result.get('error', ''))
        self.assertTrue(result['metadata_written'], "metadata should be written")
        self.assertTrue(result['cover_written'], "cover should be written")
        self.assertIn('title', result['changed_fields'])
        self.assertEqual(result.get('output_path', path), path)

        # Verify both metadata and cover were updated
        ee = importlib.import_module('epub_editor')
        md = ee.read_metadata_fields(path)
        self.assertEqual(md['metadata']['title'], 'New Combined Title')

        with zipfile.ZipFile(path, 'r') as zf:
            new_cover = zf.read('cover.jpg')
            self.assertNotEqual(original_cover, new_cover,
                                "cover should have been replaced")
            self.assertEqual(new_cover, new_jpeg,
                             "cover should match the new image data")

        os.unlink(path)
        if os.path.exists(path + '.bak'):
            os.unlink(path + '.bak')


if __name__ == '__main__':
    unittest.main()