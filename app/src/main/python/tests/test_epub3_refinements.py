#!/usr/bin/env python3
"""Test suite for EPUB 3 subtitle and contributor metadata in epub_editor.

Tests cover:
- Subtitle read/write/round-trip/repeated-save safety
- Contributor read/write/round-trip with roles and file-as
- Preservation of existing metadata through all operations
- Duplicate refinement protection
- Malformed/ambiguous metadata handling

Run with:
    cd /home/ubuntu/workspace/fanficfare-android/app/src/main/python
    /tmp/ff_venv/bin/python3 -m unittest tests.test_epub3_refinements -v
"""
import sys
import os
import json
import zipfile
import tempfile
import unittest

sys.path.insert(0, '.')

import epub_editor as ee


# ---------------------------------------------------------------------------
# Test EPUB fixture helpers
# ---------------------------------------------------------------------------

def create_basic_epub(path):
    """Create a minimal EPUB 3 with standard metadata fields."""
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title id="title">Test Book Title</dc:title>
    <dc:creator id="author1">Test Author One</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Test Publisher</dc:publisher>
    <dc:description>Test description.</dc:description>
    <dc:date>2023-01-15</dc:date>
    <dc:rights>Test rights</dc:rights>
    <dc:identifier id="isbn">urn:isbn:978-1234567890</dc:identifier>
    <meta property="dcterms:modified">2023-01-15T00:00:00Z</meta>
    <meta name="calibre:series" content="Test Series"/>
    <meta name="calibre:series_index" content="2"/>
    <meta name="calibre:rating" content="4.5"/>
  </metadata>
  <manifest>
    <item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>
    <item id="opf" href="content.opf" media-type="application/oebps/package+xml"/>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>'''
    xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>'
    jpeg = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9'
    _write_epub(path, opf_xml, xhtml, jpeg)


def create_epub_with_subtitle(path, subtitle='A Secondary Title'):
    """Create an EPUB with a subtitle refinement on the title."""
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title id="title">Main Title</dc:title>
    <dc:title id="subtitle-id">%s</dc:title>
    <meta refines="#subtitle-id" property="title-type">subtitle</meta>
    <dc:creator id="author1">Test Author</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>''' % subtitle
    _write_epub(path, opf_xml, '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>',
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')


def create_epub_with_contributor(path, role='', file_as=''):
    """Create an EPUB with a dc:contributor element."""
    role_meta = ''
    if role:
        role_meta = '<meta refines="#contrib1" property="role" scheme="marc:relators">%s</meta>' % role
    fa_meta = ''
    if file_as:
        fa_meta = '<meta refines="#contrib1" property="file-as">%s</meta>' % file_as
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title id="title">Test Book</dc:title>
    <dc:creator id="author1">Test Author</dc:creator>
    <dc:contributor id="contrib1">Jane Editor</dc:contributor>
    %s
    %s
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>''' % (role_meta, fa_meta)
    _write_epub(path, opf_xml, '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>',
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')


def create_epub_with_multiple_contributors(path):
    """Create an EPUB with multiple contributors."""
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title id="title">Test Book</dc:title>
    <dc:creator id="author1">Test Author</dc:creator>
    <dc:contributor id="contrib1">Jane Editor</dc:contributor>
    <meta refines="#contrib1" property="role" scheme="marc:relators">edt</meta>
    <dc:contributor id="contrib2">John Translator</dc:contributor>
    <meta refines="#contrib2" property="file-as">Translator, John</meta>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>'''
    _write_epub(path, opf_xml, '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>',
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')


def create_epub_with_malformed_subtitle(path):
    """Create an EPUB with an ambiguous/malformed title-type refinement."""
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title>Ambiguous Title</dc:title>
    <dc:title>Subtitle Text</dc:title>
    <meta property="title-type">subtitle</meta>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>'''
    _write_epub(path, opf_xml, '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>',
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')


def create_epub_with_all_fields(path):
    """Create an EPUB with subtitle, contributors, and Calibre metadata."""
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title id="title">Full Test Book</dc:title>
    <dc:title id="subtitle-id">A Complete Subtitle</dc:title>
    <meta refines="#subtitle-id" property="title-type">subtitle</meta>
    <dc:creator id="author1">Main Author</dc:creator>
    <dc:contributor id="contrib1">Editor Name</dc:contributor>
    <meta refines="#contrib1" property="role" scheme="marc:relators">edt</meta>
    <meta refines="#contrib1" property="file-as">Name, Editor</meta>
    <dc:language>en</dc:language>
    <dc:publisher>Test Publisher</dc:publisher>
    <dc:description>Full description.</dc:description>
    <dc:date>2024-06-01</dc:date>
    <dc:rights>All rights reserved.</dc:rights>
    <dc:identifier id="isbn">urn:isbn:978-1234567890</dc:identifier>
    <meta name="calibre:series" content="Test Series"/>
    <meta name="calibre:series_index" content="1"/>
    <meta name="calibre:rating" content="5"/>
  </metadata>
  <manifest>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>'''
    _write_epub(path, opf_xml, '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>',
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')


def _write_epub(path, opf_xml, xhtml, jpeg):
    """Helper: write a minimal EPUB with the given OPF XML."""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('mimetype', 'application/epub+zip')
        zf.writestr('META-INF/container.xml',
                    '<?xml version="1.0"?>\n'
                    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                    '  <rootfiles>\n'
                    '    <rootfile full-path="content.opf" media-type="application/oebps/package+xml"/>\n'
                    '  </rootfiles>\n'
                    '</container>')
        zf.writestr('content.opf', opf_xml)
        zf.writestr('page.xhtml', xhtml)
        zf.writestr('cover.jpg', jpeg)


# ---------------------------------------------------------------------------
# Subtitle tests
# ---------------------------------------------------------------------------

class TestSubtitleReading(unittest.TestCase):
    def test_read_subtitle(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_subtitle(path, 'A Secondary Title')
        result = ee.read_metadata_fields(path)
        assert result['ok'], result.get('error')
        md = result['metadata']
        self.assertEqual(md['title'], 'Main Title')
        self.assertEqual(md['subtitle'], 'A Secondary Title')
        os.unlink(path)

    def test_missing_subtitle(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.read_metadata_fields(path)
        assert result['ok'], result.get('error')
        md = result['metadata']
        self.assertEqual(md['subtitle'], '')
        os.unlink(path)

    def test_ambiguous_subtitle_no_id(self):
        """Subtitle refinement without a matching id should not be detected
        as a subtitle (the refines must point to a title element with that id)."""
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_malformed_subtitle(path)
        result = ee.read_metadata_fields(path)
        assert result['ok'], result.get('error')
        md = result['metadata']
        # The malformed refinement has no id on the title, so it should not
        # be picked up as a subtitle. But the title text is the first title.
        self.assertEqual(md['title'], 'Ambiguous Title')
        self.assertEqual(md['subtitle'], '')
        os.unlink(path)


class TestSubtitleWriting(unittest.TestCase):
    def test_add_subtitle(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.write_metadata(path, {'subtitle': 'New Subtitle'},
                                   output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['subtitle'], 'New Subtitle')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_edit_subtitle(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_subtitle(path, 'Original Subtitle')
        result = ee.write_metadata(path, {'subtitle': 'Updated Subtitle'},
                                   output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['subtitle'], 'Updated Subtitle')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_remove_subtitle(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_subtitle(path, 'A Secondary Title')
        result = ee.write_metadata(path, {'subtitle': ''},
                                   output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['subtitle'], '')
        # Primary title must remain unaffected.
        self.assertEqual(md['title'], 'Main Title')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_subtitle_round_trip(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_subtitle(path, 'Round Trip Subtitle')
        # Read, write back the same subtitle, read again.
        result1 = ee.read_metadata_fields(path)
        md1 = result1['metadata']
        result2 = ee.write_metadata(path, {'subtitle': md1['subtitle']},
                                    output_path=None, backup_suffix='.bak')
        assert result2['ok'], result2.get('error')
        result3 = ee.read_metadata_fields(path)
        md3 = result3['metadata']
        self.assertEqual(md3['subtitle'], 'Round Trip Subtitle')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_repeated_save_no_duplicate_subtitle(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_subtitle(path, 'Original')
        # Save subtitle twice.
        ee.write_metadata(path, {'subtitle': 'Updated'}, backup_suffix='.bak')
        ee.write_metadata(path, {'subtitle': 'Updated Again'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['subtitle'], 'Updated Again')
        # Verify only one subtitle title element exists in OPF.
        opf_result = ee.export_opf(path)
        opf_xml = opf_result['opf']
        # Count dc:title elements — should be exactly 2 (main + subtitle).
        title_count = opf_xml.count('<dc:title')
        self.assertEqual(title_count, 2, "Expected exactly 2 dc:title elements, found %d" % title_count)
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_primary_title_remains_unchanged(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        ee.write_metadata(path, {'subtitle': 'New Subtitle'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['title'], 'Test Book Title')
        self.assertEqual(md['subtitle'], 'New Subtitle')
        os.unlink(path)
        os.unlink(path + '.bak')


# ---------------------------------------------------------------------------
# Contributor tests
# ---------------------------------------------------------------------------

class TestContributorReading(unittest.TestCase):
    def test_read_contributor(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path)
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(len(md['contributors']), 1)
        self.assertEqual(md['contributors'][0]['name'], 'Jane Editor')
        self.assertEqual(md['contributors'][0]['role'], '')
        self.assertEqual(md['contributors'][0]['file_as'], '')
        os.unlink(path)

    def test_read_contributor_with_role(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path, role='edt')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(len(md['contributors']), 1)
        self.assertEqual(md['contributors'][0]['name'], 'Jane Editor')
        self.assertEqual(md['contributors'][0]['role'], 'edt')
        self.assertEqual(md['contributors'][0]['file_as'], '')
        os.unlink(path)

    def test_read_contributor_with_file_as(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path, file_as='Editor, Jane')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(len(md['contributors']), 1)
        self.assertEqual(md['contributors'][0]['name'], 'Jane Editor')
        self.assertEqual(md['contributors'][0]['role'], '')
        self.assertEqual(md['contributors'][0]['file_as'], 'Editor, Jane')
        os.unlink(path)

    def test_read_contributor_without_role(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path)
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(len(md['contributors']), 1)
        self.assertEqual(md['contributors'][0]['role'], '')
        self.assertEqual(md['contributors'][0]['file_as'], '')
        os.unlink(path)

    def test_read_contributor_with_role_and_file_as(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path, role='edt', file_as='Editor, Jane')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['contributors'][0]['role'], 'edt')
        self.assertEqual(md['contributors'][0]['file_as'], 'Editor, Jane')
        os.unlink(path)

    def test_read_multiple_contributors(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_multiple_contributors(path)
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(len(md['contributors']), 2)
        self.assertEqual(md['contributors'][0]['name'], 'Jane Editor')
        self.assertEqual(md['contributors'][0]['role'], 'edt')
        self.assertEqual(md['contributors'][0]['file_as'], '')
        self.assertEqual(md['contributors'][1]['name'], 'John Translator')
        self.assertEqual(md['contributors'][1]['role'], '')
        self.assertEqual(md['contributors'][1]['file_as'], 'Translator, John')
        os.unlink(path)

    def test_contributor_ordering_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_multiple_contributors(path)
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        names = [c['name'] for c in md['contributors']]
        self.assertEqual(names, ['Jane Editor', 'John Translator'])
        os.unlink(path)

    def test_missing_contributors(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['contributors'], [])
        os.unlink(path)


class TestContributorWriting(unittest.TestCase):
    def test_add_contributor(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.write_metadata(path, {
            'contributors': [{'name': 'New Contributor', 'role': '', 'file_as': ''}]
        }, output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(len(md['contributors']), 1)
        self.assertEqual(md['contributors'][0]['name'], 'New Contributor')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_add_contributor_with_role(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.write_metadata(path, {
            'contributors': [{'name': 'Editor', 'role': 'edt', 'file_as': ''}]
        }, output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['contributors'][0]['role'], 'edt')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_add_contributor_with_file_as(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.write_metadata(path, {
            'contributors': [{'name': 'Editor', 'role': '', 'file_as': 'Editor, Jane'}]
        }, output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['contributors'][0]['file_as'], 'Editor, Jane')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_add_contributor_with_role_and_file_as(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        result = ee.write_metadata(path, {
            'contributors': [{'name': 'Translator', 'role': 'trl', 'file_as': 'Smith, John'}]
        }, output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['contributors'][0]['name'], 'Translator')
        self.assertEqual(md['contributors'][0]['role'], 'trl')
        self.assertEqual(md['contributors'][0]['file_as'], 'Smith, John')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_edit_contributor(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path, role='edt')
        result = ee.write_metadata(path, {
            'contributors': [{'name': 'Updated Editor', 'role': 'edt', 'file_as': ''}]
        }, output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(md['contributors'][0]['name'], 'Updated Editor')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_remove_contributor(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_multiple_contributors(path)
        result = ee.write_metadata(path, {'contributors': []},
                                   output_path=None, backup_suffix='.bak')
        assert result['ok'], result.get('error')
        result2 = ee.read_metadata_fields(path)
        md = result2['metadata']
        self.assertEqual(len(md['contributors']), 0)
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_contributor_round_trip(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path, role='edt', file_as='Editor, Jane')
        result1 = ee.read_metadata_fields(path)
        md1 = result1['metadata']
        result2 = ee.write_metadata(path, {'contributors': md1['contributors']},
                                    output_path=None, backup_suffix='.bak')
        assert result2['ok'], result2.get('error')
        result3 = ee.read_metadata_fields(path)
        md3 = result3['metadata']
        self.assertEqual(len(md3['contributors']), 1)
        self.assertEqual(md3['contributors'][0]['name'], 'Jane Editor')
        self.assertEqual(md3['contributors'][0]['role'], 'edt')
        self.assertEqual(md3['contributors'][0]['file_as'], 'Editor, Jane')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_repeated_save_no_duplicate_contributor(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_contributor(path, role='edt')
        ee.write_metadata(path, {
            'contributors': [{'name': 'Editor', 'role': 'edt', 'file_as': 'Editor, J'}]
        }, backup_suffix='.bak')
        ee.write_metadata(path, {
            'contributors': [{'name': 'Editor', 'role': 'edt', 'file_as': 'Editor, J'}]
        }, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(len(md['contributors']), 1)
        # Verify only one dc:contributor element in OPF.
        opf_result = ee.export_opf(path)
        opf_xml = opf_result['opf']
        contrib_count = opf_xml.count('<dc:contributor')
        self.assertEqual(contrib_count, 1, "Expected exactly 1 dc:contributor, found %d" % contrib_count)
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_no_empty_refinements_written(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        ee.write_metadata(path, {
            'contributors': [{'name': 'Editor', 'role': '', 'file_as': ''}]
        }, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['contributors'][0]['role'], '')
        self.assertEqual(md['contributors'][0]['file_as'], '')
        # Verify no role/file-as meta elements in OPF.
        opf_result = ee.export_opf(path)
        opf_xml = opf_result['opf']
        # Should have no property="role" or property="file-as" metas.
        self.assertNotIn('property="role"', opf_xml)
        self.assertNotIn('property="file-as"', opf_xml)
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_role_meta_has_marc_relators_scheme(self):
        """Contributor role refinement must carry scheme="marc:relators".

        Verifies the actual serialized OPF metadata (not just the Python dict)
        contains the MARC relator scheme on the role <meta> element.
        """
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        ee.write_metadata(path, {
            'contributors': [{'name': 'Jane Editor', 'role': 'edt', 'file_as': 'Editor, Jane'}]
        }, backup_suffix='.bak')
        # Inspect the serialized OPF.
        opf_result = ee.export_opf(path)
        opf_xml = opf_result['opf']
        # Parse the serialized XML and find the role meta.
        import xml.etree.ElementTree as ET
        root = ET.fromstring(opf_xml)
        DC_NS = "http://purl.org/dc/elements/1.1/"
        OPF_NS = "http://www.idpf.org/2007/opf"
        role_metas = root.findall(
            ".//{%s}meta[@property='role']" % OPF_NS)
        self.assertEqual(len(role_metas), 1,
                         "Expected exactly 1 role meta, found %d" % len(role_metas))
        role_meta = role_metas[0]
        # Verify the four required attributes.
        self.assertEqual(role_meta.get('property'), 'role')
        self.assertTrue(role_meta.get('refines', '').startswith('#'))
        self.assertEqual(role_meta.get('scheme'), 'marc:relators')
        self.assertEqual((role_meta.text or '').strip(), 'edt')
        # Verify file-as is unchanged (no scheme attribute).
        fa_metas = root.findall(
            ".//{%s}meta[@property='file-as']" % OPF_NS)
        self.assertEqual(len(fa_metas), 1)
        self.assertNotIn('scheme', fa_metas[0].attrib)
        self.assertEqual((fa_metas[0].text or '').strip(), 'Editor, Jane')
        os.unlink(path)
        os.unlink(path + '.bak')


# ---------------------------------------------------------------------------
# Preservation tests
# ---------------------------------------------------------------------------

class TestPreservation(unittest.TestCase):
    def test_existing_authors_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_all_fields(path)
        ee.write_metadata(path, {'subtitle': 'New Sub'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertIn('Main Author', md['authors'])
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_identifiers_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_all_fields(path)
        ee.write_metadata(path, {'contributors': []}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertIn('isbn', md['identifiers'])
        self.assertEqual(md['identifiers']['isbn'], 'urn:isbn:978-1234567890')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_calibre_metadata_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_all_fields(path)
        ee.write_metadata(path, {'subtitle': 'New'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['series'], 'Test Series')
        self.assertEqual(md['series_index'], '1')
        self.assertEqual(md['rating'], '5')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_series_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        ee.write_metadata(path, {'subtitle': 'Sub'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['series'], 'Test Series')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_rating_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        ee.write_metadata(path, {'subtitle': 'Sub'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['rating'], '4.5')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_description_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        ee.write_metadata(path, {'subtitle': 'Sub'}, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['description'], 'Test description.')
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_existing_cover_behavior_preserved(self):
        path = tempfile.mktemp(suffix='.epub')
        create_basic_epub(path)
        # Verify cover exists before write.
        with zipfile.ZipFile(path, 'r') as z:
            names_before = z.namelist()
            self.assertIn('cover.jpg', names_before)
        ee.write_metadata(path, {'subtitle': 'Sub'}, backup_suffix='.bak')
        # Verify cover still exists after write.
        with zipfile.ZipFile(path, 'r') as z:
            names_after = z.namelist()
            self.assertIn('cover.jpg', names_after)
        os.unlink(path)
        os.unlink(path + '.bak')


# ---------------------------------------------------------------------------
# Duplicate refinement protection
# ---------------------------------------------------------------------------

class TestDuplicateProtection(unittest.TestCase):
    def test_read_write_read_write_stable(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_all_fields(path)
        # Read, write, read, write, read.
        r1 = ee.read_metadata_fields(path)
        md1 = r1['metadata']
        # Add an extra subtitle and contributor to ensure they're preserved.
        md1['subtitle'] = 'Test Subtitle'
        md1['contributors'] = [{'name': 'New Editor', 'role': 'edt', 'file_as': 'Editor, New'}]
        ee.write_metadata(path, {'subtitle': md1['subtitle'], 'contributors': md1['contributors']},
                          backup_suffix='.bak1')
        r2 = ee.read_metadata_fields(path)
        md2 = r2['metadata']
        ee.write_metadata(path, {'subtitle': md2['subtitle'], 'contributors': md2['contributors']},
                          backup_suffix='.bak2')
        r3 = ee.read_metadata_fields(path)
        md3 = r3['metadata']

        self.assertEqual(md3['subtitle'], 'Test Subtitle')
        self.assertEqual(len(md3['contributors']), 1)
        self.assertEqual(md3['contributors'][0]['name'], 'New Editor')
        self.assertEqual(md3['contributors'][0]['role'], 'edt')

        # Verify no duplicates in OPF.
        opf_result = ee.export_opf(path)
        opf_xml = opf_result['opf']
        title_count = opf_xml.count('<dc:title')
        contrib_count = opf_xml.count('<dc:contributor')
        self.assertLessEqual(title_count, 2)
        self.assertLessEqual(contrib_count, 1)

        os.unlink(path)
        os.unlink(path + '.bak1')
        os.unlink(path + '.bak2')


# ---------------------------------------------------------------------------
# Malformed / edge cases
# ---------------------------------------------------------------------------

class TestMalformedMetadata(unittest.TestCase):
    def test_malformed_subtitle_does_not_crash(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_malformed_subtitle(path)
        result = ee.read_metadata_fields(path)
        self.assertTrue(result['ok'])
        os.unlink(path)

    def test_unknown_opf_metadata_preserved(self):
        """Unknown <meta> properties should not be deleted by write_metadata."""
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_all_fields(path)
        # Add an unknown meta property.
        opf_result = ee.export_opf(path)
        opf_xml = opf_result['opf']
        opf_xml_modified = opf_xml.replace(
            '</metadata>',
            '<meta property="custom:unknown">preserved_value</meta>\n  </metadata>'
        )
        ee.import_opf(path, opf_xml_modified, output_path=None, backup_suffix='.bak')
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        self.assertEqual(md['title'], 'Full Test Book')
        self.assertEqual(md['subtitle'], 'A Complete Subtitle')
        self.assertEqual(len(md['contributors']), 1)
        os.unlink(path)
        os.unlink(path + '.bak')

    def test_contributor_not_turned_into_author(self):
        path = tempfile.mktemp(suffix='.epub')
        create_epub_with_multiple_contributors(path)
        result = ee.read_metadata_fields(path)
        md = result['metadata']
        # Contributors should NOT appear in the authors list.
        self.assertNotIn('Jane Editor', md['authors'])
        self.assertNotIn('John Translator', md['authors'])
        # Contributors should be in contributors list.
        self.assertEqual(len(md['contributors']), 2)
        os.unlink(path)

    def test_epub2_no_subtitle_or_contributor(self):
        """EPUB 2 (version 2.0) without refinements should still work."""
        opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:epub2-test</dc:identifier>
    <dc:title>EPub Two Title</dc:title>
    <dc:creator>EPub Two Author</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="xhtml" href="page.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="xhtml"/>
  </spine>
</package>'''
        path = tempfile.mktemp(suffix='.epub')
        _write_epub(path, opf_xml, '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Test</p></body></html>',
                    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')
        result = ee.read_metadata_fields(path)
        self.assertTrue(result['ok'])
        md = result['metadata']
        self.assertEqual(md['title'], 'EPub Two Title')
        self.assertEqual(md['subtitle'], '')
        self.assertEqual(md['contributors'], [])
        # Write back with subtitle and contributors.
        ee.write_metadata(path, {'subtitle': 'New Sub', 'contributors': [{'name': 'Editor', 'role': 'edt', 'file_as': ''}]},
                          backup_suffix='.bak')
        result2 = ee.read_metadata_fields(path)
        md2 = result2['metadata']
        self.assertEqual(md2['subtitle'], 'New Sub')
        self.assertEqual(len(md2['contributors']), 1)
        os.unlink(path)


# ---------------------------------------------------------------------------
# Integration: normalization and diff
# ---------------------------------------------------------------------------

class TestNormalizationIntegration(unittest.TestCase):
    def test_normalization_accepts_subtitle(self):
        try:
            from metadata_normalizer import normalize_metadata
        except ImportError:
            self.skipTest("metadata_normalizer not available")
        md = {
            'title': 'Test',
            'subtitle': '  Sub  ',
            'contributors': [{'name': '  Editor  ', 'role': '', 'file_as': ''}],
        }
        result = normalize_metadata(md)
        norm = result['metadata']
        self.assertEqual(norm['subtitle'], 'Sub')
        self.assertEqual(norm['contributors'][0]['name'], 'Editor')

    def test_normalization_accepts_contributors(self):
        try:
            from metadata_normalizer import normalize_metadata
        except ImportError:
            self.skipTest("metadata_normalizer not available")
        md = {
            'contributors': [
                {'name': '  Editor  ', 'role': '', 'file_as': '  Editor, J  '},
                {'name': 'Translator', 'role': 'trl', 'file_as': ''},
            ],
        }
        result = normalize_metadata(md)
        norm = result['metadata']
        self.assertEqual(norm['contributors'][0]['name'], 'Editor')
        self.assertEqual(norm['contributors'][0]['file_as'], 'Editor, J')
        self.assertEqual(norm['contributors'][1]['name'], 'Translator')
        self.assertEqual(norm['contributors'][1]['role'], 'trl')


class TestDiffIntegration(unittest.TestCase):
    def test_diff_detects_subtitle_change(self):
        try:
            from metadata_diff import diff_metadata
        except ImportError:
            self.skipTest("metadata_diff not available")
        before = {'subtitle': 'Old Sub', 'title': 'Title'}
        after = {'subtitle': 'New Sub', 'title': 'Title'}
        result = diff_metadata(before, after)
        fields = [c['field'] for c in result['changes']]
        self.assertIn('subtitle', fields)

    def test_diff_handles_contributor_change(self):
        try:
            from metadata_diff import diff_metadata
        except ImportError:
            self.skipTest("metadata_diff not available")
        before = {'contributors': [{'name': 'Editor A', 'role': 'edt', 'file_as': ''}]}
        after = {'contributors': [{'name': 'Editor B', 'role': 'edt', 'file_as': ''}]}
        result = diff_metadata(before, after)
        self.assertTrue(result['changed'])
        fields = [c['field'] for c in result['changes']]
        self.assertIn('contributors', fields)

    def test_diff_output_json_serializable(self):
        try:
            from metadata_diff import diff_metadata
        except ImportError:
            self.skipTest("metadata_diff not available")
        before = {
            'title': 'Old', 'subtitle': 'Old Sub',
            'contributors': [{'name': 'Editor', 'role': 'edt', 'file_as': 'Editor, E'}],
        }
        after = {
            'title': 'New', 'subtitle': 'New Sub',
            'contributors': [{'name': 'Editor', 'role': 'edt', 'file_as': 'Editor, Jane'}],
        }
        result = diff_metadata(before, after)
        # Must be JSON-serializable.
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        self.assertTrue(parsed['changed'])


if __name__ == '__main__':
    unittest.main()
