#!/usr/bin/env python3
"""Test suite for epub_editor module."""
import sys, os, json, base64, zipfile, io, tempfile, importlib
sys.path.insert(0, '.')

def create_test_epub(path):
    """Create a minimal test EPUB with metadata and a cover image."""
    opf_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">urn:uuid:test-id-12345</dc:identifier>
    <dc:title>Test Book Title</dc:title>
    <dc:creator id="author1">Test Author One</dc:creator>
    <dc:creator id="author2">Test Author Two</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Test Publisher</dc:publisher>
    <dc:description>Test description.</dc:description>
    <dc:date>2023-01-15</dc:date>
    <dc:rights>Test rights</dc:rights>
    <dc:identifier id="isbn">urn:isbn:978-1234567890</dc:identifier>
    <meta property="dcterms:modified">2023-01-15T00:00:00Z</meta>
    <meta property="rendition:layout">reflowable</meta>
    <meta property="rendition:orientation">portrait</meta>
    <meta property="rendition:spread">none</meta>
    <meta property="series">Test Series</meta>
    <meta property="series_index">2</meta>
    <meta property="rating">4.5</meta>
    <meta property="cover">cover-image</meta>
    <meta name="cover" content="cover-image"/>
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
    jpeg = base64.b64decode(
        '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG'
        'BgYHBwYI/w4JCxgQJCQwMCwsKCs0NDx0fE9c'
        'FBwcHBQgHBgkJCzsYGRgZGBcUGBgZGBgYGBg'
        'ZGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgZGBgYGBgYGBgYGBgYGBgYGB'
        'gYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYG'
        'BgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgKG'
        'BgZGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYG'
        'BgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGB'
        'gYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgY'
        'GBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'YGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBg'
        'BgZGBgYGBgYGBg==')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('mimetype', 'application/epub+zip')
        zf.writestr('META-INF/container.xml', '''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps/package+xml"/>
  </rootfiles>
</container>''')
        zf.writestr('content.opf', opf_xml)
        zf.writestr('page.xhtml', xhtml)
        zf.writestr('cover.jpg', jpeg)

def run_tests():
    epub_editor = importlib.import_module('epub_editor')
    tests = [
        ('export_opf', test_export_opf_fn),
        ('import_opf', test_import_opf_fn),
        ('write_metadata', test_set_metadata_fn),
        ('read_metadata', test_get_metadata_fn),
        ('replace_cover', test_replace_cover_fn),
        ('full_roundtrip', test_full_roundtrip_fn),
    ]
    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn(epub_editor)
            print('  %s: OK' % name)
            passed += 1
        except Exception as e:
            import traceback
            print('  %s: FAILED - %s' % (name, e))
            traceback.print_exc()
            failed += 1
    print('')
    print('=' * 50)
    print('Results: %d passed, %d failed out of %d tests' % (passed, failed, len(tests)))
    return 0 if failed == 0 else 1

def test_export_opf_fn(ee):
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    result = ee.export_opf(path, output_path=None)
    assert result['ok'], "Export failed: %s" % result.get('error', '')
    assert '<dc:title>Test Book Title</dc:title>' in result['opf']
    os.unlink(path)

def test_import_opf_fn(ee):
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    result = ee.export_opf(path, output_path=None)
    opf_xml = result['opf']
    opf_xml = opf_xml.replace('Test Book Title', 'Modified Title')
    opf_xml = opf_xml.replace('Test Author One', 'Modified Author')
    result2 = ee.import_opf(path, opf_xml, output_path=None, backup_suffix='.bak')
    assert result2['ok'], "Import failed: %s" % result2.get('error', '')
    result3 = ee.export_opf(path, output_path=None)
    assert 'Modified Title' in result3['opf']
    os.unlink(path)

def test_set_metadata_fn(ee):
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    fields = {
        'title': 'New Title',
        'authors': ['New Author'],
        'publisher': 'New Publisher',
        'description': 'New description',
        'tags': 'fiction, test',
        'languages': ['fr'],
        'series': 'New Series',
        'series_index': '3',
        'rating': '4.0',
        'isbn': '978-0987654321',
        'pubdate': '2024-06-01',
        'rights': 'New rights'
    }
    result = ee.write_metadata(path, json.dumps(fields), output_path=None, backup_suffix='.bak')
    assert result['ok'], "write_metadata failed: %s" % result.get('error', '')
    changed = result.get('changed_fields', [])
    assert 'title' in changed, "title not in changed: %s" % changed
    os.unlink(path)

def test_get_metadata_fn(ee):
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    result = ee.read_metadata_fields(path)
    assert result['ok'], "read_metadata_fields failed: %s" % result.get('error', '')
    md = result['metadata']
    assert md['title'] == 'Test Book Title', "title=%s" % md['title']
    assert 'Test Author One' in md['authors'], "authors=%s" % md['authors']
    assert 'en' in md['languages'], "languages=%s" % md['languages']
    os.unlink(path)

def test_replace_cover_fn(ee):
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    new_jpeg = base64.b64decode('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG')
    result = ee.replace_cover(path, new_jpeg, 'image/jpeg', output_path=None, backup_suffix='.bak')
    assert result['ok'], "replace_cover failed: %s" % result.get('error', '')
    assert result['cover_path_in_epub'] == 'cover.jpg', "cover_path=%s" % result.get('cover_path_in_epub')
    with zipfile.ZipFile(path, 'r') as zf:
        names = zf.namelist()
        assert 'cover.jpg' in names, "cover.jpg not in EPUB: %s" % names
    os.unlink(path)

def test_full_roundtrip_fn(ee):
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    result = ee.read_metadata_fields(path)
    md = result['metadata']
    fields = {'title': 'Roundtrip Title'}
    result2 = ee.write_metadata(path, fields, output_path=None, backup_suffix='.bak')
    assert result2['ok']
    result3 = ee.read_metadata_fields(path)
    assert result3['metadata']['title'] == 'Roundtrip Title', "title=%s" % result3['metadata']['title']
    os.unlink(path)

if __name__ == '__main__':
    sys.exit(run_tests())
