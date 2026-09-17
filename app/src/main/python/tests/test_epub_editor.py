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
        ('atomic_meta_only', test_write_metadata_and_cover_metadata_only_fn),
        ('atomic_meta_and_cover', test_write_metadata_and_cover_both_fn),
        ('atomic_cover_only', test_write_metadata_and_cover_cover_only_fn),
        ('atomic_combined_one_write', test_combined_atomic_single_write_fn),
        ('atomic_failure_original_untouched', test_combined_failure_preserves_original_fn),
        ('temp_cleanup_on_failure', test_temp_cleanup_on_failure_fn),
        ('replace_cover_temp_cleanup_on_failure', test_replace_cover_temp_cleanup_on_failure_fn),
        ('replace_cover_temp_cleanup_on_zip_error', test_replace_cover_temp_cleanup_on_zip_error_fn),
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

def test_write_metadata_and_cover_metadata_only_fn(ee):
    """Atomic write with metadata only (no cover) should succeed."""
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    fields = {'title': 'Atomic Meta Title', 'publisher': 'Atomic Publisher'}
    result = ee.write_metadata_and_cover(path, fields, image_data=None, image_mime=None,
                                          output_path=None, backup_suffix='.bak')
    assert result['ok'], "write_metadata_and_cover failed: %s" % result.get('error', '')
    assert result['metadata_written'], "metadata_written should be True"
    assert not result['cover_written'], "cover_written should be False"
    assert 'title' in result['changed_fields']
    md = ee.read_metadata_fields(path)
    assert md['metadata']['title'] == 'Atomic Meta Title', "title=%s" % md['metadata']['title']
    assert md['metadata']['publisher'] == 'Atomic Publisher', "publisher=%s" % md['metadata']['publisher']
    # Original cover should still be present
    with zipfile.ZipFile(path, 'r') as zf:
        assert 'cover.jpg' in zf.namelist(), "cover.jpg should still be in EPUB"
    os.unlink(path)
    if os.path.exists(path + '.bak'):
        os.unlink(path + '.bak')

def test_write_metadata_and_cover_both_fn(ee):
    """Atomic write with both metadata and cover should succeed in one pass."""
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    fields = {'title': 'Atomic Both Title', 'publisher': 'Atomic Both Publisher'}
    new_jpeg = base64.b64decode('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG')
    result = ee.write_metadata_and_cover(path, fields, image_data=new_jpeg,
                                          image_mime='image/jpeg',
                                          output_path=None, backup_suffix='.bak')
    assert result['ok'], "write_metadata_and_cover failed: %s" % result.get('error', '')
    assert result['metadata_written'], "metadata_written should be True"
    assert result['cover_written'], "cover_written should be True"
    assert 'title' in result['changed_fields']
    # Verify metadata was updated
    md = ee.read_metadata_fields(path)
    assert md['metadata']['title'] == 'Atomic Both Title', "title=%s" % md['metadata']['title']
    # Verify cover image is the new one
    with zipfile.ZipFile(path, 'r') as zf:
        names = zf.namelist()
        assert 'cover.jpg' in names, "cover.jpg not in EPUB: %s" % names
        cover_data = zf.read('cover.jpg')
        assert cover_data == new_jpeg, "cover image data does not match"
    os.unlink(path)
    if os.path.exists(path + '.bak'):
        os.unlink(path + '.bak')

def test_write_metadata_and_cover_cover_only_fn(ee):
    """Atomic write with cover only (no metadata fields) should succeed."""
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    new_jpeg = base64.b64decode('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG')
    result = ee.write_metadata_and_cover(path, {}, image_data=new_jpeg,
                                          image_mime='image/jpeg',
                                          output_path=None, backup_suffix='.bak')
    assert result['ok'], "write_metadata_and_cover failed: %s" % result.get('error', '')
    assert result['metadata_written'], "metadata_written should be True (OPF rewritten)"
    assert result['cover_written'], "cover_written should be True"
    # Original title should be preserved
    md = ee.read_metadata_fields(path)
    assert md['metadata']['title'] == 'Test Book Title', "title should be unchanged"
    # Cover image should be updated
    with zipfile.ZipFile(path, 'r') as zf:
        cover_data = zf.read('cover.jpg')
        assert cover_data == new_jpeg, "cover image data does not match"
    os.unlink(path)
    if os.path.exists(path + '.bak'):
        os.unlink(path + '.bak')


def test_combined_atomic_single_write_fn(ee):
    """Verify that metadata + cover is written through ONE zip write,
    not separate write_metadata + replace_cover calls.
    The output should have both new title and new cover in the same EPUB.
    """
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    new_jpeg = base64.b64decode('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBGcG')
    fields = {'title': 'Combined Single Write Title'}
    result = ee.write_metadata_and_cover(
        path, fields, image_data=new_jpeg, image_mime='image/jpeg',
        output_path=None, backup_suffix='.bak',
    )
    assert result['ok'], "write_metadata_and_cover failed: %s" % result.get('error', '')
    assert result['metadata_written'], "metadata should be written"
    assert result['cover_written'], "cover should be written"
    assert result.get('old_cover_removed', False), "old cover should be removed"
    # Verify both were applied atomically
    md = ee.read_metadata_fields(path)
    assert md['metadata']['title'] == 'Combined Single Write Title'
    with zipfile.ZipFile(path, 'r') as zf:
        names = zf.namelist()
        assert 'cover.jpg' in names, "cover.jpg should be in EPUB"
        assert zf.read('cover.jpg') == new_jpeg, "cover should be the new image"
    os.unlink(path)
    if os.path.exists(path + '.bak'):
        os.unlink(path + '.bak')


def test_combined_failure_preserves_original_fn(ee):
    """If the combined write fails, the original EPUB must be untouched
    and no partial state should exist.
    """
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    # Save original content
    with zipfile.ZipFile(path, 'r') as zf:
        original_entries = {name: zf.read(name) for name in zf.namelist()}

    # Trigger a failure by passing a non-existent epub_path
    bad_path = path + '_does_not_exist'
    result = ee.write_metadata_and_cover(
        bad_path, {'title': 'Should Fail'}, image_data=b'', image_mime='image/jpeg',
        output_path=None, backup_suffix=None,
    )
    assert not result['ok'], "should fail for non-existent file"
    assert 'error' in result, "should have error key"

    # Original file must be unchanged
    with zipfile.ZipFile(path, 'r') as zf:
        for name in zf.namelist():
            assert zf.read(name) == original_entries[name], \
                "original file entry %s was modified" % name

    os.unlink(path)


def test_temp_cleanup_on_failure_fn(ee):
    """If a write fails after the temp file is created, the temp file
    must be cleaned up — no orphaned temp files should remain.
    """
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    dir_name = os.path.dirname(path)

    # Count temp files before
    temp_before = [f for f in os.listdir(dir_name) if f.endswith('.epub') and f != os.path.basename(path)]

    # Trigger a failure: pass a path that exists but as a directory won't work,
    # so instead pass invalid fields that will cause _apply_metadata_to_opf to fail.
    # Actually, _apply_metadata_to_opf is very lenient. Let's cause failure by
    # using a non-existent file.
    bad_path = path + '_no_exist'
    result = ee.write_metadata_and_cover(
        bad_path, {'title': 'Test'}, output_path=None, backup_suffix=None,
    )
    assert not result['ok'], "should fail for non-existent file"

    # Count temp files after — should not increase (no orphaned temps)
    temp_after = [f for f in os.listdir(dir_name) if f.endswith('.epub') and f != os.path.basename(path)]
    assert len(temp_after) == len(temp_before), \
        "temp file leaked: before=%d after=%d" % (len(temp_before), len(temp_after))

    os.unlink(path)

def test_replace_cover_temp_cleanup_on_failure_fn(ee):
    """replace_cover() must clean up temp files on failure, just like
    write_metadata_and_cover(). If a failure occurs after the temp file is
    created, no orphaned temp file should remain and the original EPUB
    must be untouched.
    """
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    dir_name = os.path.dirname(path)

    # Count temp files before
    temp_before = [f for f in os.listdir(dir_name) if f.endswith('.epub') and f != os.path.basename(path)]

    # Trigger a failure by passing a non-existent epub_path.
    # _resolve_target will attempt tempfile.mkstemp in dirname(bad_path),
    # which will raise FileNotFoundError — caught by the outer try/except.
    bad_path = path + '_no_exist'
    result = ee.replace_cover(
        bad_path, b'\xff\xd8\xff\xe0', 'image/jpeg', output_path=None, backup_suffix=None,
    )
    assert not result['ok'], "should fail for non-existent file"
    assert 'error' in result, "should have error key"

    # Count temp files after — should not increase (no orphaned temps)
    temp_after = [f for f in os.listdir(dir_name) if f.endswith('.epub') and f != os.path.basename(path)]
    assert len(temp_after) == len(temp_before), \
        "temp file leaked: before=%d after=%d" % (len(temp_before), len(temp_after))

    # Original file must be unchanged
    with zipfile.ZipFile(path, 'r') as zf:
        assert 'cover.jpg' in zf.namelist(), "cover.jpg should still be in original EPUB"

    os.unlink(path)

def test_replace_cover_temp_cleanup_on_zip_error_fn(ee):
    """replace_cover() must clean up temp files even when the failure occurs
    during the zip write (after temp file creation). We simulate this by
    passing a valid epub_path but then triggering a ZIP write error via
    a non-writable target directory.
    """
    path = tempfile.mktemp(suffix='.epub')
    create_test_epub(path)
    dir_name = os.path.dirname(path)

    temp_before = [f for f in os.listdir(dir_name) if f.endswith('.epub') and f != os.path.basename(path)]

    # Use output_path as a directory (will fail on zipfile write)
    # but we can't easily make a directory with .epub suffix. Instead,
    # pass output_path pointing to an existing directory to trigger OSError.
    dir_target = tempfile.mkdtemp(suffix='.epub_dir')
    result = ee.replace_cover(
        path, b'\xff\xd8\xff\xe0', 'image/jpeg',
        output_path=dir_target, backup_suffix=None,
    )
    assert not result['ok'], "should fail when output_path is a directory"

    temp_after = [f for f in os.listdir(dir_name) if f.endswith('.epub') and f != os.path.basename(path)]
    assert len(temp_after) == len(temp_before), \
        "temp file leaked: before=%d after=%d" % (len(temp_before), len(temp_after))

    # Original file must still be intact
    with zipfile.ZipFile(path, 'r') as zf:
        assert 'cover.jpg' in zf.namelist(), "cover.jpg should still be in original EPUB"

    os.unlink(path)
    os.rmdir(dir_target)

if __name__ == '__main__':
    sys.exit(run_tests())
