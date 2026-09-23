#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""Test suite for the EPUB merge/split tooling.

Covers ``epub_xml`` (namespace-safe primitives), ``epub_container`` (manifest,
spine, href math, link rewriting, commit) and ``epub_tools`` (merge/split).

Follows the procedural runner convention of ``test_epub_editor.py``: plain
``test_*_fn(ctx)`` functions registered as ``(name, fn)`` tuples, a summary
line, and ``sys.exit()``.

Each test receives ``ctx``, a dict of the modules under test (``None`` when a
module does not exist yet, so a partially implemented feature fails with a
clear message instead of an ImportError at collection time).

Run::

    cd app/src/main/python
    PYTHONPATH=. python3 tests/test_epub_tools.py
"""

import importlib
import json
import os
import sys
import traceback
import zipfile
import xml.etree.ElementTree as ET

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODULE_NAMES = ('epub_xml', 'epub_container', 'epub_merge', 'epub_tools',
                'fanficfare_bridge')


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _load_modules():
    ctx = {}
    for name in MODULE_NAMES:
        try:
            ctx[name] = importlib.import_module(name)
        except ImportError:
            ctx[name] = None
    return ctx


def require(ctx, name):
    """Fetch a module from ctx, failing clearly when it does not exist yet."""
    mod = ctx.get(name)
    if mod is None:
        raise AssertionError('module %r is not importable' % name)
    return mod


def fixtures():
    """The fixture generator module."""
    import fixtures.make_fixtures as mf
    return mf


def fixture_paths():
    """Build (or reuse) the fixture corpus and return {name: path}."""
    return fixtures().ensure_fixtures()


def assert_sane(path):
    """Structural validation, shared with the merge/split output checks."""
    import epub_assert
    return epub_assert.assert_epub_sane(path)


OPF_FIXTURE_XML = (
    '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
    'unique-identifier="bookid">'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
    '<dc:identifier id="bookid">urn:uuid:ns-test</dc:identifier>'
    '<dc:title>T</dc:title></metadata>'
    '<manifest/><spine/></package>'
)

XHTML_FIXTURE_XML = (
    '<html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops">'
    '<head><title>t</title><link rel="stylesheet" href="../styles/main.css"/></head>'
    '<body><h2 id="c" epub:type="chapter">Hi</h2>'
    '<a href="x.xhtml#y">link</a></body></html>'
)


# ---------------------------------------------------------------------------
# epub_xml
# ---------------------------------------------------------------------------

def test_serialize_default_ns_no_ns0_fn(ctx):
    """OPF and XHTML both keep their default namespace with no ns0: prefixes,
    and serializing XHTML must not corrupt later OPF output.
    """
    x = require(ctx, 'epub_xml')
    opf_root = ET.fromstring(OPF_FIXTURE_XML)
    xhtml_root = ET.fromstring(XHTML_FIXTURE_XML)

    for round_no in range(3):
        opf_out = x.serialize(opf_root, x.OPF, xml_declaration=False)
        assert b'ns0:' not in opf_out, 'round %d: ns0: in OPF output' % round_no
        assert b'xmlns="http://www.idpf.org/2007/opf"' in opf_out, \
            'round %d: OPF lost its default namespace' % round_no
        assert b'<dc:title>T</dc:title>' in opf_out, \
            'round %d: dc: prefix not applied' % round_no

        xhtml_out = x.serialize(xhtml_root, x.XHTML)
        assert b'ns0:' not in xhtml_out, 'round %d: ns0: in XHTML output' % round_no
        assert b'xmlns="http://www.w3.org/1999/xhtml"' in xhtml_out, \
            'round %d: XHTML lost its default namespace' % round_no
        assert b'epub:type="chapter"' in xhtml_out, \
            'round %d: epub: prefix not applied' % round_no
        assert xhtml_out.startswith(b'<?xml'), \
            'round %d: XHTML declaration missing' % round_no

    # Integration guard: the pre-existing OPF writer must still produce default-ns
    # OPF even though XHTML has just claimed the empty prefix.
    ee = importlib.import_module('epub_editor')
    retro = ee._serialize_opf(ET.fromstring(OPF_FIXTURE_XML))
    assert b'ns0:' not in retro, 'epub_editor._serialize_opf emits ns0: prefixes'
    assert b'http://www.idpf.org/2007/opf' in retro, \
        'epub_editor._serialize_opf lost the OPF namespace'

    # And a third kind must not disturb either of them.
    ncx_out = x.serialize(ET.fromstring(
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"/>'), x.NCX)
    assert b'ns0:' not in ncx_out, 'ns0: in NCX output'
    assert b'xmlns="http://www.daisy.org/z3986/2005/ncx/"' in ncx_out


def test_parent_map_matches_structure_fn(ctx):
    """parent_map / ancestors / iter_with_attr replace getparent() and XPath."""
    x = require(ctx, 'epub_xml')
    root = ET.fromstring(
        '<body><div class="part"><h2 id="target">T</h2><p>text</p></div>'
        '<div><p id="second">S</p></div></body>')
    div = root[0]
    h2 = div[0]
    second_div = root[1]
    p2 = second_div[0]

    pm = x.parent_map(root)
    assert pm[h2] is div, 'h2 parent should be the first div'
    assert pm[div] is root, 'div parent should be body'
    assert pm[p2] is second_div, 'second p parent should be the second div'
    assert root not in pm, 'the search root must not appear in the parent map'

    assert list(x.ancestors(h2, pm)) == [div, root], \
        'ancestors must be nearest-first and stop at the root'
    assert list(x.ancestors(root, pm)) == [], 'root has no ancestors'

    assert [e.get('id') for e in x.iter_with_attr(root, 'id')] == \
        ['target', 'second'], 'iter_with_attr must find ids in document order'

    cache = {}
    x.parent_map(root, cache)
    assert cache[h2] is div, 'parent_map must extend a provided cache'
    assert x.localname('{http://www.w3.org/1999/xhtml}p') == 'p'
    assert x.localname('p') == 'p'


def test_entity_expansion_and_tolerant_parse_fn(ctx):
    """Named entities expand; unknown ones and XML built-ins survive; malformed
    markup still parses via the html5lib fallback.
    """
    x = require(ctx, 'epub_xml')

    out = x.expand_named_entities(b'<p>a&nbsp;b&mdash;c&hellip;d&amp;e&unknown;f</p>')
    assert '\xa0'.encode('utf-8') in out, '&nbsp; should become U+00A0'
    assert '\u2014'.encode('utf-8') in out, '&mdash; should become U+2014'
    assert '\u2026'.encode('utf-8') in out, '&hellip; should become U+2026'
    assert b'&amp;' in out, '&amp; must be left escaped'
    assert b'&unknown;' in out, 'unknown entities must be left alone'

    # Well formed except for the entity: the strict ladder handles it.
    root = x.parse_xhtml(b'<html xmlns="http://www.w3.org/1999/xhtml">'
                         b'<body><h2 id="ok">A&nbsp;B</h2></body></html>')
    assert [e.get('id') for e in x.iter_with_attr(root, 'id')] == ['ok'], \
        'entity-only failure should be recovered without html5lib'

    # Genuinely malformed HTML: html5lib fallback must still preserve content.
    malformed = (b'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                 b'<p>one<p>nested<br>unclosed<h2 id="deep">H</h2></body></html>')
    mroot = x.parse_xhtml(malformed)
    assert mroot is not None, 'malformed markup must still parse'
    assert [e.get('id') for e in x.iter_with_attr(mroot, 'id')] == ['deep'], \
        'html5lib fallback must keep the heading id'


def test_split_prolog_fn(ctx):
    """The XML declaration/DOCTYPE is preserved separately so it can be
    re-attached after ElementTree drops it.
    """
    x = require(ctx, 'epub_xml')

    raw = (b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
           b'<html><body><p>x</p></body></html>\n')
    header, footer = x.split_prolog(raw)
    assert header.startswith(b'<?xml'), 'declaration should lead the header'
    assert b'<!DOCTYPE html>' in header, 'doctype should be in the header'
    assert raw[len(header):].startswith(b'<html'), 'header must cover the prolog'
    assert footer == b'\n', 'trailing newline should be the footer'
    assert header + raw[len(header):] == raw, 'split must be lossless'

    internal_subset = b'<!DOCTYPE html [ <!ENTITY nbsp "&#160;"> ]>\n<html/>'
    h3, _ = x.split_prolog(internal_subset)
    assert h3.startswith(b'<!DOCTYPE'), 'internal-subset doctype should be kept'
    assert internal_subset[len(h3):].startswith(b'<html')

    h4, f4 = x.split_prolog(b'<html/>')
    assert h4 == b'' and f4 == b'', 'no prolog means empty header and footer'


def staging_copy(path):
    """Copy a fixture into a scratch dir so a test can mutate it safely."""
    import shutil
    import tempfile
    dest_dir = tempfile.mkdtemp(prefix='ff_stage_')
    dest = os.path.join(dest_dir, os.path.basename(path))
    shutil.copy2(path, dest)
    return dest


def zip_bytes(path):
    """{entry name: raw bytes} for an EPUB, for structural comparison."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            out[info.filename] = z.read(info.filename)
    return out


# ---------------------------------------------------------------------------
# epub_container: indexing and href math (tasks 8-9)
# ---------------------------------------------------------------------------

def test_container_index_fn(ctx):
    """Manifest/spine indexing: opf location, content docs in spine order,
    stylesheets, mime map, and id<->name round tripping.
    """
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()
    with c_mod.EpubContainer(paths['fic_simple']) as c:
        assert c.opf_name == 'OEBPS/content.opf', c.opf_name
        assert c.opf_dir == 'OEBPS', c.opf_dir

        docs = list(c.content_docs())
        spine_docs = [name for _ref, name, _lin in c.spine_iter()]
        assert len(spine_docs) == 5, 'spine should hold 5 chapters: %r' % spine_docs
        assert docs[:5] == spine_docs, \
            'content_docs must lead with spine order: %r vs %r' % (docs[:5], spine_docs)
        assert 'OEBPS/nav.xhtml' in docs, \
            'non-spine content documents (nav) must still be walked'

        sheets = list(c.stylesheets())
        assert sheets == ['OEBPS/styles/main.css'], sheets
        assert c.media_type_of('OEBPS/styles/main.css') == 'text/css'
        assert c.media_type_of('OEBPS/text/chapter1.xhtml') == 'application/xhtml+xml'

        for name in spine_docs:
            item_id = c.item_id_of(name)
            assert item_id, 'no manifest id for %r' % name
            assert c.name_of(item_id) == name, \
                'id->name round trip failed for %r' % name
        assert c.item_id_of('OEBPS/nope.xhtml') is None
        assert c.name_of('no-such-id') is None
        assert c.exists('OEBPS/text/chapter1.xhtml')
        assert not c.exists('OEBPS/missing.xhtml')

        linear = [lin for _ref, _name, lin in c.spine_iter()]
        assert all(linear), 'fixture spine entries should be linear'


def test_container_href_math_fn(ctx):
    """href<->zipname resolution: relative, absolute, %20, fragments, dot paths."""
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()
    with c_mod.EpubContainer(paths['fic_multidir']) as c:
        base = 'OEBPS/text/a.xhtml'
        cases = {
            '../images/pic.png': 'OEBPS/images/pic.png',
            '/OEBPS/images/pic.png': 'OEBPS/images/pic.png',
            '../images/a%20b.png': 'OEBPS/images/a b.png',
            '../Text/b.xhtml#b1': 'OEBPS/Text/b.xhtml',
            '#frag': base,
            '': base,
            './sub/../a.xhtml': base,
            './a.xhtml': base,
            'a.xhtml': base,
        }
        for href, expected in cases.items():
            got = c.href_to_name(href, base)
            assert got == expected, 'href_to_name(%r) = %r, want %r' % (href, got, expected)
        # absolute-from-root, resolved against the OPF
        assert c.href_to_name('text/a.xhtml', 'OEBPS/content.opf') == 'OEBPS/text/a.xhtml'

        reverse = {
            'OEBPS/images/pic.png': '../images/pic.png',
            'OEBPS/images/a b.png': '../images/a%20b.png',
            'OEBPS/text/a.xhtml': 'a.xhtml',
            'OEBPS/nav.xhtml': '../nav.xhtml',
        }
        for name, expected in reverse.items():
            got = c.name_to_href(name, base)
            assert got == expected, 'name_to_href(%r) = %r, want %r' % (name, got, expected)

        # round trip through both directions
        for name in ('OEBPS/images/pic.png', 'OEBPS/Text/b.xhtml', 'OEBPS/nav.xhtml'):
            href = c.name_to_href(name, base)
            assert c.href_to_name(href, base) == name, \
                'round trip failed for %r via %r' % (name, href)


# ---------------------------------------------------------------------------
# epub_container: document cache and commit (tasks 10-11)
# ---------------------------------------------------------------------------

def test_container_document_cache_fn(ctx):
    """parsed() caching, dirty tracking, raw bytes and prolog capture."""
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()
    doc = 'OEBPS/text/chapter1.xhtml'
    with c_mod.EpubContainer(paths['fic_entities']) as c:
        first = c.parsed(doc)
        assert c.parsed(doc) is first, 'parsed() must cache the tree object'
        assert not c.is_dirty(doc), 'reading must not dirty a document'

        with zipfile.ZipFile(paths['fic_entities']) as z:
            original = z.read(doc)
        assert c.raw_data(doc) == original, 'raw_data must be the untouched bytes'

        header, footer = c.prolog(doc)
        assert b'<?xml' in header, 'the XML declaration should be captured'
        assert b'<!DOCTYPE' in header, 'the DOCTYPE should be captured'
        assert c.raw_data(doc).startswith(header), 'prolog must come off the front'

        c.dirty(doc)
        assert c.is_dirty(doc)

        fresh = ET.fromstring('<html xmlns="http://www.w3.org/1999/xhtml">'
                              '<body><p>replaced</p></body></html>')
        c.replace(doc, fresh)
        assert c.parsed(doc) is fresh, 'replace() must install the new tree'
        assert c.is_dirty(doc)


def test_container_commit_roundtrip_fn(ctx):
    """commit() preserves the OCF invariant, leaves an untouched book
    byte-identical, and can write to a copy instead of in place.
    """
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()
    src = paths['fic_simple']
    original = zip_bytes(src)

    # 1. untouched round trip, in place
    staged = staging_copy(src)
    with c_mod.EpubContainer(staged) as c:
        result = c.commit()
    assert result['ok'], result
    assert_sane(staged)
    after = zip_bytes(staged)
    assert set(after) == set(original), 'entry set changed on a no-op commit'
    for name, data in original.items():
        assert after[name] == data, 'entry %r changed on a no-op commit' % name

    with zipfile.ZipFile(staged) as z:
        names = z.namelist()
        assert names[0] == 'mimetype', names[:3]
        assert z.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert z.read('mimetype') == b'application/epub+zip'

    # 2. one document replaced: only that entry changes
    staged2 = staging_copy(src)
    doc = 'OEBPS/text/chapter3.xhtml'
    with c_mod.EpubContainer(staged2) as c:
        root = c.parsed(doc)
        # Edit text only: removing the <h2 id="ch3"> would orphan the NCX/nav
        # fragment pointing at it, which the validator rightly rejects.
        paragraphs = [e for e in root.iter() if c_mod.localname(e.tag) == 'p']
        assert paragraphs, 'fixture chapter should contain a paragraph'
        paragraphs[-1].text = 'rewritten body'
        c.replace(doc, root)
        result = c.commit(backup_suffix='.bak')
    assert result['ok'], result
    assert os.path.exists(staged2 + '.bak'), 'backup_suffix should leave a .bak'
    after2 = zip_bytes(staged2)
    assert set(after2) == set(original), 'entry set changed for a one-doc edit'
    changed = [n for n in original if original[n] != after2[n]]
    assert changed == [doc], 'only %r should change, got %r' % (doc, changed)
    assert b'rewritten body' in after2[doc]
    assert_sane(staged2)

    # 3. output_path writes a copy and leaves the source alone
    staged3 = staging_copy(src)
    out = staged3 + '.out.epub'
    with c_mod.EpubContainer(staged3) as c:
        c.dirty('OEBPS/text/chapter1.xhtml')
        result = c.commit(output_path=out)
    assert result['ok'], result
    assert result['output_path'] == out
    assert zip_bytes(staged3) == original, 'source must be untouched with output_path'
    assert_sane(out)


def test_container_replace_links_fn(ctx):
    """replace_links visits href, src, xlink:href, inline style url() and
    <style> element url(), and only dirties the document when something changed.
    """
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()
    staged = staging_copy(paths['fic_links'])
    xlink = '{http://www.w3.org/1999/xlink}href'

    with c_mod.EpubContainer(staged) as c:
        doc = 'OEBPS/text/links.xhtml'
        assert c.replace_links(doc, lambda url: url) is False, \
            'an identity replacer must report no change'
        assert not c.is_dirty(doc), 'an identity replacer must not dirty the doc'

        seen = []

        def record_and_mark(url):
            seen.append(url)
            return url + '?x=1'

        assert c.replace_links(doc, record_and_mark) is True
        assert c.is_dirty(doc)

        root = c.parsed(doc)
        hrefs = [e.get('href') for e in root.iter() if e.get('href')]
        srcs = [e.get('src') for e in root.iter() if e.get('src')]
        xlinks = [e.get(xlink) for e in root.iter() if e.get(xlink)]
        style_attr = [e.get('style') for e in root.iter() if e.get('style')]
        style_text = [e.text for e in root.iter()
                      if c_mod.localname(e.tag) == 'style' and e.text]

        assert all(h.endswith('?x=1') for h in hrefs), hrefs
        assert hrefs, 'href attributes must have been visited'
        assert all(s.endswith('?x=1') for s in srcs), srcs
        assert srcs, 'img src must have been visited'
        assert xlinks and all(x.endswith('?x=1') for x in xlinks), \
            'the inline SVG xlink:href must have been visited'
        assert all('url(../images/pic.png?x=1)' in s for s in style_attr), style_attr
        assert all('url("../images/pic.png?x=1")' in t for t in style_text), style_text
        assert len(seen) >= 6, 'expected every link form to reach the replacer: %r' % seen


def test_container_spine_mutation_fn(ctx):
    """generate_item / insert_spine_item_after keep manifest, spine and the
    written archive in sync; linearity is inherited from the source itemref.
    """
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()
    staged = staging_copy(paths['fic_simple'])

    with c_mod.EpubContainer(staged) as c:
        before = [name for _ref, name, _lin in c.spine_iter()]
        assert len(before) == 5, before

        doc_a = 'OEBPS/text/inserted_a.xhtml'
        c.add_file(doc_a, b'<html xmlns="http://www.w3.org/1999/xhtml">'
                          b'<body><p>inserted a</p></body></html>')
        item = c.generate_item(doc_a, 'application/xhtml+xml')
        assert item.get('media-type') == 'application/xhtml+xml'
        assert item.get('href') == 'text/inserted_a.xhtml', item.get('href')
        assert c.media_type_of(doc_a) == 'application/xhtml+xml'
        assert c.item_id_of(doc_a) == item.get('id')

        pos = c.insert_spine_item_after(before[1], doc_a)
        assert pos == 2, 'inserted after index 1 should land at index 2'
        after = [name for _ref, name, _lin in c.spine_iter()]
        assert after == before[:2] + [doc_a] + before[2:], after

        try:
            c.generate_item(doc_a, 'application/xhtml+xml')
            raise AssertionError('registering the same entry twice must fail')
        except c_mod.ContainerError:
            pass

        # linear="no" on the source must be inherited by the new itemref
        doc_b = 'OEBPS/text/inserted_b.xhtml'
        c.add_file(doc_b, b'<html xmlns="http://www.w3.org/1999/xhtml">'
                          b'<body><p>inserted b</p></body></html>')
        c.generate_item(doc_b, 'application/xhtml+xml')
        source_ref = [ref for ref, name, _lin in c.spine_iter() if name == before[3]][0]
        source_ref.set('linear', 'no')
        c.dirty(c.opf_name)
        c.insert_spine_item_after(before[3], doc_b)
        new_refs = [ref for ref, name, _lin in c.spine_iter() if name == doc_b]
        assert new_refs, 'doc_b should be in the spine'
        assert new_refs[0].get('linear') == 'no', \
            'linearity must be inherited from the source itemref'
        assert not [lin for _r, n, lin in c.spine_iter() if n == doc_b][0], \
            'spine_iter must report the inherited linearity'

        # doc_b was inserted after before[3], so locate that entry in the
        # already-updated spine rather than recomputing indices by hand.
        expected = list(after)
        expected.insert(after.index(before[3]) + 1, doc_b)

        result = c.commit()
        assert result['ok'], result
    assert_sane(staged)

    with c_mod.EpubContainer(staged) as reopened:
        final = [name for _ref, name, _lin in reopened.spine_iter()]
        assert final == expected, 'final %r != expected %r' % (final, expected)
        assert reopened.exists(doc_a) and reopened.exists(doc_b)
        assert reopened.media_type_of(doc_a) == 'application/xhtml+xml'


def test_container_remove_item_fn(ctx):
    """remove_item drops the manifest item, spine entry, file and TOC links,
    and can repoint TOC entries instead of dropping them.
    """
    c_mod = require(ctx, 'epub_container')
    paths = fixture_paths()

    # 1. plain removal
    staged = staging_copy(paths['fic_simple'])
    victim = 'OEBPS/text/chapter3.xhtml'
    with c_mod.EpubContainer(staged) as c:
        assert any(n == victim for n, _f in c.toc_targets()), \
            'precondition: the TOC should reference the victim'
        c.remove_item(victim)
        assert c.item_id_of(victim) is None
        assert victim not in c.mime_map
        assert not any(n == victim for _r, n, _l in c.spine_iter())
        assert not any(n == victim for n, _f in c.toc_targets()), \
            'TOC must not still reference the removed file'
        result = c.commit()
        assert result['ok'], result

    with zipfile.ZipFile(staged) as z:
        assert victim not in z.namelist(), 'the removed file must not be written'
    assert_sane(staged)

    # 2. repointing instead of dropping (what a merge does)
    staged2 = staging_copy(paths['fic_simple'])
    victim2 = 'OEBPS/text/chapter3.xhtml'
    survivor = 'OEBPS/text/chapter4.xhtml'

    with c_mod.EpubContainer(staged2) as c:
        def rebase(url):
            if 'chapter3.xhtml' not in url:
                return url
            return url.replace('chapter3.xhtml', 'chapter4.xhtml').replace('#ch3', '#ch4')

        c.remove_item(victim2, rebase=rebase)
        targets = c.toc_targets()
        assert not any(n == victim2 for n, _f in targets), \
            'no TOC entry may still point at the removed file'
        survivors = [(n, f) for n, f in targets if n == survivor]
        assert survivors, 'the TOC entry should have been repointed, not dropped'
        assert all(f == 'ch4' for _n, f in survivors), survivors
        result = c.commit()
        assert result['ok'], result
    assert_sane(staged2)


def test_merge_plan_import_fn(ctx):
    """plan_import maps a source into the merged namespace without mutating
    anything: opf/ncx/nav skipped, everything else namespaced and unique.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    # fic_simple ships both a toc.ncx and an EPUB3 nav.xhtml, so the skip
    # rules for each can be exercised.
    base_src = staging_copy(paths['fic_multidir'])
    src_paths = [paths['fic_simple']]

    with c_mod.EpubContainer(base_src) as base, \
            c_mod.EpubContainer(src_paths[0]) as src:
        before_base = set(base.entries())
        before_src_manifest = dict(src.mime_map)

        plan = m_mod.plan_import(base, src, 1)
        assert plan.prefix.startswith('merged/'), plan.prefix
        assert plan.index == 1

        # opf / ncx / nav must not be imported (the OPF is only a manifest item
        # in some producers, so check the map rather than the skip list)
        skipped = set(plan.skipped)
        assert src.opf_name not in plan.name_map, 'the source OPF must not be imported'
        assert any(src.media_type_of(n) == 'application/x-dtbncx+xml' for n in skipped), \
            'the source NCX must be skipped'
        assert any('nav' in src.properties_of(n).split() for n in skipped), \
            'the source nav document must be skipped'

        # every other manifest item must be mapped, under the prefix
        for name in src.mime_map:
            if name in skipped:
                assert name not in plan.name_map, name
            else:
                assert plan.name_map[name] == plan.prefix + name, name

        # cover images are imported: a titlepage often links to its own cover
        assert not any('cover' in n for n in skipped), skipped

        # spine order is preserved, with linearity
        assert [n for n, _l in plan.spine] == \
            [n for _r, n, _l in src.spine_iter()], plan.spine
        assert all(isinstance(l, bool) for _n, l in plan.spine)

        # nothing was mutated
        assert set(base.entries()) == before_base, 'plan_import must not mutate base'
        assert dict(src.mime_map) == before_src_manifest

        # the plan is collision-free against the base
        assert not (set(plan.name_map.values()) & before_base), \
            'planned names must not collide with existing entries'


def test_merge_two_books_fn(ctx):
    """Merging two books produces one valid book: both sources' chapters in the
    spine, source files untouched, links rewritten to the imported copies.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_nested'])
    first_before = zip_bytes(first)
    second_before = zip_bytes(second)

    out = os.path.join(os.path.dirname(first), 'merged.epub')
    result = m_mod.merge_books([first, second], output_path=out)
    assert result['ok'], result
    assert result['sources_merged'] == 2, result
    assert result['spine_before'] == 5, result
    assert result['spine_after'] == 8, result
    assert result['entries_added'] > 0, result
    assert_sane(out)

    # sources must not have been touched
    assert zip_bytes(first) == first_before, 'the base source was modified'
    assert zip_bytes(second) == second_before, 'the second source was modified'

    # both sources' content is present, second source namespaced
    merged = zip_bytes(out)
    imported = sorted(n for n in merged if n.startswith('merged/'))
    assert imported, 'the second source should be namespaced under merged/'
    assert 'merged/1/OEBPS/text/part1.xhtml' in merged, imported
    assert b'First chapter text' in merged['merged/1/OEBPS/text/part1.xhtml']

    # source 2's documents are all after source 1's in the spine
    with c_mod.EpubContainer(out) as c:
        spine = [name for _r, name, _l in c.spine_iter()]
        assert spine[:5] == [n for n in spine if not n.startswith('merged/')][:5]
        assert all(n.startswith('merged/1/') for n in spine[5:]), spine
        # the base's own TOC entries survive
        assert any(n == 'OEBPS/text/chapter1.xhtml' for n, _f in c.toc_targets())
        # imported documents are link-consistent
        assert c.media_type_of('merged/1/OEBPS/text/part1.xhtml') == \
            'application/xhtml+xml'


def test_merge_resource_collision_fn(ctx):
    """Two sources containing the same resource path must both survive, and each
    document must reference its own copy.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    # fic_links and fic_multidir both ship OEBPS/images/pic.png
    first = staging_copy(paths['fic_links'])
    second = staging_copy(paths['fic_multidir'])
    out = os.path.join(os.path.dirname(first), 'collide.epub')

    result = m_mod.merge_books([first, second], output_path=out)
    assert result['ok'], result
    assert_sane(out)

    merged = zip_bytes(out)
    pics = [n for n in merged if n.endswith('images/pic.png')]
    assert len(pics) >= 2, \
        'both sources\' copies of pic.png must survive: %r' % pics
    assert 'OEBPS/images/pic.png' in pics, pics
    assert any(n.startswith('merged/1/') for n in pics), pics

    # each imported document must reference its own namespaced copy
    imported_doc = 'merged/1/OEBPS/text/a.xhtml'
    assert imported_doc in merged, sorted(
        n for n in merged if n.startswith('merged/'))
    with c_mod.EpubContainer(out) as c:
        root = c.parsed(imported_doc)
        resolved = []
        for elem in root.iter():
            for attr in ('href', 'src'):
                url = elem.get(attr)
                if not url or url.startswith('#'):
                    continue
                resolved.append((url, c.href_to_name(url, imported_doc)))
        assert resolved, 'the imported document should carry links'
        for url, target in resolved:
            assert target in merged, '%s -> %s is dangling' % (url, target)
        image_targets = [t for _u, t in resolved if t.endswith('.png')]
        assert image_targets, resolved
        assert all(t.startswith('merged/1/') for t in image_targets), \
            'imported docs must use their own copies, got %r' % image_targets


def test_merge_titlepage_cover_reference_fn(ctx):
    """A source titlepage referencing its own cover must stay resolvable after
    import, and the merged book must still advertise exactly one cover.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_epub3'])       # base, ships its own cover
    second = staging_copy(paths['fic_titlepage'])  # source with a titlepage cover
    out = os.path.join(os.path.dirname(first), 'titlepage.epub')

    result = m_mod.merge_books([first, second], output_path=out)
    assert result['ok'], result
    # would fail if the imported titlepage's <img src> dangled
    assert_sane(out)

    merged = zip_bytes(out)
    titlepage = 'merged/1/OEBPS/titlepage.xhtml'
    assert titlepage in merged, sorted(n for n in merged if n.startswith('merged/'))
    assert 'merged/1/OEBPS/cover.png' in merged, \
        'the source cover must be imported, not skipped'

    with c_mod.EpubContainer(out) as c:
        root = c.parsed(titlepage)
        sources = [e.get('src') for e in root.iter() if e.get('src')]
        assert sources, 'the titlepage should still reference its cover'
        for src in sources:
            target = c.href_to_name(src, titlepage)
            assert target in merged, '%s -> %s is dangling' % (src, target)
            assert target.startswith('merged/1/'), \
                'the titlepage must point at its own imported copy, got %r' % target
        # the imported cover must not also claim cover-image, or readers see two
        covers = [n for n in c.mime_map if 'cover-image' in c.properties_of(n)]
        assert len(covers) == 1, 'expected exactly one cover-image, got %r' % covers
        assert covers[0] == 'OEBPS/images/cover.png', \
            "the base book's cover must win, got %r" % covers


def test_merge_toc_nesting_fn(ctx):
    """Each source becomes its own TOC section: NCX and nav both nest, the
    base's entries survive underneath a base section, and every section target
    resolves.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    # fic_simple has both toc.ncx and nav.xhtml, so both mirrors get exercised
    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_nested'])
    third = staging_copy(paths['fic_multidir'])
    out = os.path.join(os.path.dirname(first), 'toc.epub')

    result = m_mod.merge_books([first, second, third], output_path=out)
    assert result['ok'], result
    assert result['sources_merged'] == 3, result
    assert result['toc_sections'] >= 2, \
        'expected sections in NCX and nav, got %r' % result['toc_sections']
    assert_sane(out)

    with c_mod.EpubContainer(out) as c:
        targets = {n for n, _f in c.toc_targets()}
        # every source's chapters are reachable from the TOC now
        for expect in ('OEBPS/text/chapter3.xhtml',
                       'merged/1/OEBPS/text/part1.xhtml',
                       'merged/2/OEBPS/text/a.xhtml'):
            assert expect in targets, '%s missing from TOC: %r' % (expect, sorted(targets))

        # NCX: the base's entries are nested under a section, not top level
        ncx = [n for n in c.toc_doc_names() if c.media_type_of(n) == 'application/x-dtbncx+xml']
        assert ncx, 'the fixture base should still have an NCX'
        ncx_name = ncx[0]
        root = c.parsed(ncx_name)
        navmap = [e for e in root.iter() if c_mod.localname(e.tag) == 'navMap'][0]
        top = [e for e in navmap if c_mod.localname(e.tag) == 'navPoint']
        assert len(top) == 3, 'expected 3 top-level sections, got %d' % len(top)

        def label(node):
            for text in node.iter():
                if c_mod.localname(text.tag) == 'text' and text.text:
                    return text.text.strip()
            return ''

        labels = [label(node) for node in top]
        assert 'Simple Fic' in labels, labels
        assert 'Nested Fic' in labels, labels
        # the base's own chapters sit under the base section
        base_section = top[labels.index('Simple Fic')]
        base_children = [e for e in base_section if c_mod.localname(e.tag) == 'navPoint']
        assert len(base_children) == 5, 'base section should hold 5 chapters'
        # the second source's section holds its TOC entries (part1 has two
        # chapters, so 4 entries across 3 documents)
        nested_section = top[labels.index('Nested Fic')]
        nested_children = [e for e in nested_section if c_mod.localname(e.tag) == 'navPoint']
        assert len(nested_children) == 4, \
            'nested source should hold 4 TOC entries, got %d' % len(nested_children)

        # playOrder must be a clean 1..N sequence after renumbering
        orders = [int(e.get('playOrder')) for e in root.iter()
                  if c_mod.localname(e.tag) == 'navPoint']
        assert orders == list(range(1, len(orders) + 1)), orders

        # nav.xhtml mirrors the same shape
        nav_names = [n for n in c.toc_doc_names() if n not in ncx]
        assert nav_names, 'the fixture base should still have a nav document'
        nav_root = c.parsed(nav_names[0])
        nav = [e for e in nav_root.iter() if c_mod.localname(e.tag) == 'nav'][0]
        outer_ol = [ch for ch in nav if c_mod.localname(ch.tag) == 'ol'][0]
        outer_items = [ch for ch in outer_ol if c_mod.localname(ch.tag) == 'li']
        assert len(outer_items) == 3, \
            'nav should have 3 top-level sections, got %d' % len(outer_items)


def test_merge_declaration_matches_bytes_fn(ctx):
    """A source document declaring a non-UTF-8 encoding must be written with a
    declaration that describes the bytes actually written.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_encoding'])
    out = os.path.join(os.path.dirname(first), 'encoding.epub')

    result = m_mod.merge_books([first, second], output_path=out)
    assert result['ok'], result
    assert_sane(out)

    with c_mod.EpubContainer(out) as c:
        raw = c.raw_data('merged/1/OEBPS/text/latin1.xhtml')

    declaration = raw.split(b'?>')[0]
    assert b'8859' not in declaration, \
        'the declaration still claims latin-1: %r' % declaration
    assert b'utf-8' in declaration.lower(), declaration

    # A reader honours the declaration, so decoding that way must reproduce the
    # original text rather than mojibake.
    visible = ''.join(ET.fromstring(raw).itertext())
    assert 'Caf\u00e9' in visible, 'reader-visible text was %r' % visible
    assert 'na\u00efve r\u00e9sum\u00e9' in visible, \
        'reader-visible text was %r' % visible
    assert '\u00c3' not in visible, \
        'mojibake: utf-8 bytes were read back as latin-1: %r' % visible


def test_merge_preserves_properties_fn(ctx):
    """Manifest properties and media-overlay survive an import: the overlay is
    remapped to the imported SMIL, semantic properties are kept, and the merged
    book still declares exactly one cover.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_epub3'])      # base ships its own cover
    second = staging_copy(paths['fic_media'])
    out = os.path.join(os.path.dirname(first), 'media.epub')

    result = m_mod.merge_books([first, second], output_path=out)
    assert result['ok'], result
    # assert_epub_sane now also checks media-overlay targets and SMIL references
    assert_sane(out)

    doc = 'merged/1/OEBPS/text/chapter1.xhtml'
    smil = 'merged/1/OEBPS/text/chapter1.smil'
    with c_mod.EpubContainer(out) as c:
        assert smil in c.mime_map, 'the SMIL file must be imported'
        assert c.media_type_of(smil) == 'application/smil+xml'

        overlay = c.item_attr(doc, 'media-overlay')
        assert overlay, 'media-overlay was dropped from the imported document'
        assert overlay == c.item_id_of(smil), \
            'media-overlay must be remapped to the imported SMIL id, got %r' % overlay

        props = c.properties_of('merged/1/OEBPS/text/chapter2.xhtml')
        assert 'svg' in props, 'the svg property was dropped: %r' % props
        assert 'scripted' in props, 'the scripted property was dropped: %r' % props

        # the imported cover must not claim cover-image
        imported_cover = 'merged/1/OEBPS/images/cover.png'
        assert imported_cover in c.mime_map, 'the source cover should be imported'
        assert 'cover-image' not in c.properties_of(imported_cover)
        covers = [n for n in c.mime_map if 'cover-image' in c.properties_of(n)]
        assert len(covers) == 1, 'expected exactly one cover-image, got %r' % covers

    # the imported document is still navigable from the TOC
    with c_mod.EpubContainer(out) as c:
        targets = {n for n, _f in c.toc_targets()}
        assert doc in targets, sorted(targets)


def test_external_urls_untouched_fn(ctx):
    """External, protocol-relative and data: URLs must never be resolved to an
    archive entry nor rewritten by a merge.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    externals = ('http://example.com/story', 'https://example.com/secure#frag',
                 'mailto:someone@example.com',
                 'data:image/gif;base64,R0lGODlhAQABAAAAACw=',
                 '//cdn.example.com/pic.png')
    base = 'OEBPS/text/ext.xhtml'
    with c_mod.EpubContainer(paths['fic_external']) as c:
        for url in externals:
            assert c_mod.is_external_url(url), url
            assert c.href_to_name(url, base) is None, \
                '%s must not resolve to an archive entry' % url
        # a filename that merely contains a colon is not a scheme
        assert not c_mod.is_external_url('ch1:2.xhtml')
        assert c.href_to_name('../images/local.png', base) == 'OEBPS/images/local.png'

    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_external'])
    out = os.path.join(os.path.dirname(first), 'external.epub')
    result = m_mod.merge_books([first, second], output_path=out)
    assert result['ok'], result
    assert_sane(out)

    with c_mod.EpubContainer(out) as c:
        imported = 'merged/1/OEBPS/text/ext.xhtml'
        root = c.parsed(imported)
        urls = [e.get('src') or e.get('href') for e in root.iter()
                if e.get('src') or e.get('href')]
        for url in externals:
            assert url in urls, '%s was rewritten or dropped: %r' % (url, urls)
        # ...while the internal reference is repointed at the imported copy
        local = [u for u in urls if u.endswith('local.png')]
        assert local, urls
        assert c.href_to_name(local[0], imported).startswith('merged/1/'), local


def test_merge_toc_edge_shapes_fn(ctx):
    """nav-only sources contribute a TOC section; TOC-less sources contribute
    none but stay in the spine; a TOC-less base stays TOC-less.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    # nav-only source: entries come from its nav document
    first = staging_copy(paths['fic_simple'])
    navonly = staging_copy(paths['fic_navonly'])
    out = os.path.join(os.path.dirname(first), 'navonly.epub')
    result = m_mod.merge_books([first, navonly], output_path=out)
    assert result['ok'], result
    assert_sane(out)
    with c_mod.EpubContainer(out) as c:
        targets = {n for n, _f in c.toc_targets()}
        for expect in ('merged/1/OEBPS/text/one.xhtml', 'merged/1/OEBPS/text/two.xhtml'):
            assert expect in targets, '%s missing: %r' % (expect, sorted(targets))

    # TOC-less source: no section, but the chapters are still in the spine
    first2 = staging_copy(paths['fic_simple'])
    notoc = staging_copy(paths['fic_notoc'])
    out2 = os.path.join(os.path.dirname(first2), 'notoc.epub')
    result2 = m_mod.merge_books([first2, notoc], output_path=out2)
    assert result2['ok'], result2
    assert_sane(out2)
    with c_mod.EpubContainer(out2) as c:
        spine = [n for _r, n, _l in c.spine_iter()]
        assert spine[5:] == ['merged/1/OEBPS/text/plain1.xhtml',
                             'merged/1/OEBPS/text/plain2.xhtml'], spine
        targets = {n for n, _f in c.toc_targets()}
        assert 'OEBPS/text/chapter1.xhtml' in targets, 'the base TOC should survive'
        # A TOC-less source still gets a section pointing at its first chapter,
        # so it is reachable -- but it cannot contribute per-chapter entries.
        assert 'merged/1/OEBPS/text/plain1.xhtml' in targets, sorted(targets)
        assert 'merged/1/OEBPS/text/plain2.xhtml' not in targets, sorted(targets)

        ncx = [n for n in c.toc_doc_names()
               if c.media_type_of(n) == 'application/x-dtbncx+xml'][0]
        root = c.parsed(ncx)
        navmap = [e for e in root.iter() if c_mod.localname(e.tag) == 'navMap'][0]
        sections = [e for e in navmap if c_mod.localname(e.tag) == 'navPoint']
        assert len(sections) == 2, 'expected base + source sections, got %d' % len(sections)
        empty = [s for s in sections
                 if not [ch for ch in s if c_mod.localname(ch.tag) == 'navPoint']]
        assert len(empty) == 1, 'only the TOC-less source should have no children'

    # TOC-less base: there is nothing to nest into, so the merged book has no TOC
    # and the imported chapters are reachable only through the spine. This is a
    # known limitation, asserted so it cannot regress silently.
    notoc_base = staging_copy(paths['fic_notoc'])
    other = staging_copy(paths['fic_simple'])
    out3 = os.path.join(os.path.dirname(notoc_base), 'notocbase.epub')
    result3 = m_mod.merge_books([notoc_base, other], output_path=out3)
    assert result3['ok'], result3
    assert result3['toc_sections'] == 0, result3
    assert_sane(out3)
    with c_mod.EpubContainer(out3) as c:
        assert not c.toc_doc_names(), 'a TOC-less base should stay TOC-less'
        spine = [n for _r, n, _l in c.spine_iter()]
        assert len(spine) == 7, spine          # 2 base chapters + 5 imported
        assert spine[:2] == ['OEBPS/text/plain1.xhtml', 'OEBPS/text/plain2.xhtml'], spine


def test_merge_nested_toc_and_unicode_fn(ctx):
    """A source with a two-level TOC flattens into its section in order, and
    non-ASCII labels and filenames survive a merge.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_simple'])
    nested = staging_copy(paths['fic_tocnested'])
    out = os.path.join(os.path.dirname(first), 'nestedtoc.epub')
    result = m_mod.merge_books([first, nested], output_path=out)
    assert result['ok'], result
    assert_sane(out)

    with c_mod.EpubContainer(out) as c:
        # the source's section, then its two-level TOC flattened in order
        labels = [label for label, name, _f in c.toc_entries()
                  if name.startswith('merged/1/')]
        assert labels == ['Nested TOC Fic', 'Part One', 'Chapter 1', 'Chapter 2',
                          'Part Two', 'Chapter 3', 'Chapter 4'], labels
        targets = {n for n, _f in c.toc_targets()}
        for i in range(1, 5):
            assert 'merged/1/OEBPS/text/c%d.xhtml' % i in targets, sorted(targets)

    # a source with non-ASCII text, labels and a percent-encoded filename
    first2 = staging_copy(paths['fic_simple'])
    uni = staging_copy(paths['fic_unicode'])
    out2 = os.path.join(os.path.dirname(first2), 'unicode.epub')
    result2 = m_mod.merge_books([first2, uni], output_path=out2)
    assert result2['ok'], result2
    assert_sane(out2)

    with c_mod.EpubContainer(out2) as c:
        imported_docs = [n for n in c.mime_map
                         if n.startswith('merged/1/') and 'caf' in n]
        assert imported_docs, sorted(c.mime_map)
        doc = imported_docs[0]
        assert doc == 'merged/1/OEBPS/text/caf\u00e9.xhtml', doc
        # the percent-encoded href in the manifest must resolve back to that name
        item_id = c.item_id_of(doc)
        assert c.name_of(item_id) == doc, c.name_of(item_id)
        # non-ASCII label survives, and the chapter is reachable from the TOC
        labels = [label for label, _n, _f in c.toc_entries()]
        assert any('\u30c1\u30e3\u30d7\u30bf\u30fc' in label for label in labels), labels
        assert doc in {n for n, _f in c.toc_targets()}, sorted(c.toc_targets())


def test_bridge_merge_preview_fn(ctx):
    """The bridge's preview returns what the confirmation screen needs, and
    reports failures as data rather than raising.
    """
    m_mod = require(ctx, 'epub_merge')
    bridge = require(ctx, 'fanficfare_bridge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_nested'])

    preview = json.loads(bridge.epub_merge_preview(json.dumps([first, second])))
    assert preview['ok'], preview
    assert preview['source_count'] == 2, preview
    assert preview['chapters'] == 8, preview          # 5 + 3
    assert preview['estimated_bytes'] > 0
    assert preview['too_large'] is False
    assert preview['default_title'] == 'Simple Fic', preview['default_title']
    titles = [s['title'] for s in preview['sources']]
    assert titles == ['Simple Fic', 'Nested Fic'], titles
    assert preview['sources'][0]['is_base'] is True
    assert preview['sources'][1]['is_base'] is False
    assert all(s['chapters'] > 0 for s in preview['sources']), preview['sources']

    # base_index moves both the flag and the defaults
    preview2 = json.loads(bridge.epub_merge_preview(
        json.dumps([first, second]), base_index=1))
    assert preview2['default_title'] == 'Nested Fic', preview2['default_title']
    assert preview2['sources'][1]['is_base'] is True

    # failures come back as JSON, never as an exception
    single = json.loads(bridge.epub_merge_preview(json.dumps([first])))
    assert single['ok'] is False and 'two' in single['error'], single
    bad_index = json.loads(bridge.epub_merge_preview(json.dumps([first, second]),
                                                    base_index=9))
    assert bad_index['ok'] is False and 'range' in bad_index['error'], bad_index
    missing = json.loads(bridge.epub_merge_preview(json.dumps([first, first + '.nope'])))
    assert missing['ok'] is False and missing['error'], missing

    # a TOC-less first book is called out, because the merged book inherits that
    notoc = staging_copy(paths['fic_notoc'])
    warn = json.loads(bridge.epub_merge_preview(json.dumps([notoc, second])))
    assert warn['ok'], warn
    assert any('table of contents' in w for w in warn['warnings']), warn['warnings']

    # the size guard refuses rather than trying to write a runaway book
    real_cap = m_mod.MERGE_MAX_BYTES
    try:
        m_mod.MERGE_MAX_BYTES = 1
        refused = json.loads(bridge.epub_merge_books(json.dumps([first, second]),
                                                     output_path=first + '.out.epub'))
        assert refused['ok'] is False, refused
        assert 'limit' in refused['error'], refused
    finally:
        m_mod.MERGE_MAX_BYTES = real_cap


def test_bridge_merge_writes_valid_book_fn(ctx):
    """A merge driven through the bridge produces a structurally valid book and
    leaves the sources untouched.
    """
    bridge = require(ctx, 'fanficfare_bridge')
    paths = fixture_paths()

    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_multidir'])
    before_first, before_second = zip_bytes(first), zip_bytes(second)
    out = os.path.join(os.path.dirname(first), 'bridged.epub')

    result = json.loads(bridge.epub_merge_books(
        json.dumps([first, second]), output_path=out,
        title='Bridged Collection', author='Bridged Author'))
    assert result['ok'], result
    assert result['sources_merged'] == 2, result
    assert result['output_path'] == out, result
    assert_sane(out)

    assert zip_bytes(first) == before_first, 'the base source was modified'
    assert zip_bytes(second) == before_second, 'the second source was modified'

    with zipfile.ZipFile(out) as z:
        assert z.namelist()[0] == 'mimetype'
        assert z.infolist()[0].compress_type == zipfile.ZIP_STORED

    # newline-separated paths are accepted too (easier from Kotlin)
    first3 = staging_copy(paths['fic_simple'])
    second3 = staging_copy(paths['fic_nested'])
    out2 = os.path.join(os.path.dirname(first3), 'bridged2.epub')
    result2 = json.loads(bridge.epub_merge_books(
        '\n'.join([first3, second3]), output_path=out2))
    assert result2['ok'], result2
    assert_sane(out2)


def test_merge_metadata_and_output_fn(ctx):
    """Metadata overrides, the default output path, and input validation."""
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    # too few sources
    bad = m_mod.merge_books([paths['fic_simple']])
    assert not bad['ok'], 'a single source must be rejected'
    assert 'two' in bad['error'], bad['error']
    empty = m_mod.merge_books([])
    assert not empty['ok']

    # a non-EPUB input must be reported, not raised
    junk = os.path.join(os.path.dirname(staging_copy(paths['fic_simple'])), 'junk.epub')
    with open(junk, 'wb') as handle:
        handle.write(b'not a zip at all')
    broken = m_mod.merge_books([paths['fic_simple'], junk])
    assert not broken['ok'], broken
    assert 'error' in broken

    # default output path: beside the base, named after the title, base untouched
    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_nested'])
    before = zip_bytes(first)
    result = m_mod.merge_books([first, second], title='Collected Works',
                               author='Collected Author')
    assert result['ok'], result
    expected_out = os.path.join(os.path.dirname(first), 'Collected Works.epub')
    assert result['output_path'] == expected_out, result['output_path']
    assert zip_bytes(first) == before, 'the base must not be written in place'
    assert_sane(expected_out)

    with c_mod.EpubContainer(expected_out) as c:
        root = c.parsed(c.opf_name)
        titles = [e.text for e in root.iter() if e.tag.endswith('}title')]
        creators = [e.text for e in root.iter() if e.tag.endswith('}creator')]
        assert 'Collected Works' in titles, titles
        assert 'Collected Author' in creators, creators


def test_toc_style_cleanup_fn(ctx):
    """prepare_groups drops imported front matter, repoints a section off its
    title page, and removes an entry that only repeats its section's label --
    the exact shapes reported from a merged book on device.
    """
    m_mod = require(ctx, 'epub_merge')

    reported = [{
        'label': 'Heart of the Mountain Ch. 09',
        'target': ('merged/1/OEBPS/titlepage.xhtml', 'tp'),
        'children': [('Title Page', 'merged/1/OEBPS/titlepage.xhtml', 'tp'),
                     ('Heart of the Mountain Ch. 09',
                      'merged/1/OEBPS/text/ch09.xhtml', 'c1')],
    }]
    sections = m_mod.prepare_groups(reported, 'sections')[0]
    # the duplicate label is gone, but the title page carrying this book's own
    # details stays, and the section still opens there
    assert sections['children'] == [
        ('Title Page', 'merged/1/OEBPS/titlepage.xhtml', 'tp')], sections['children']
    assert sections['target'] == ('merged/1/OEBPS/titlepage.xhtml', 'tp'), \
        sections['target']

    flat = m_mod.prepare_groups(reported, 'flat')[0]
    # no section header exists in flat mode, so the chapter must survive
    assert flat['children'] == [('Heart of the Mountain Ch. 09',
                                'merged/1/OEBPS/text/ch09.xhtml', 'c1')], flat['children']

    # an anthology keeps its first chapter's name, and its title page as well
    anthology = m_mod.prepare_groups([{
        'label': 'Dune',
        'target': ('merged/1/OEBPS/titlepage.xhtml', 'tp'),
        'children': [('Title Page', 'merged/1/OEBPS/titlepage.xhtml', 'tp'),
                     ('Chapter 1', 'merged/1/OEBPS/c1.xhtml', 'c1')],
    }], 'sections')[0]
    assert anthology['children'] == [
        ('Title Page', 'merged/1/OEBPS/titlepage.xhtml', 'tp'),
        ('Chapter 1', 'merged/1/OEBPS/c1.xhtml', 'c1')], anthology['children']
    assert anthology['target'] == ('merged/1/OEBPS/titlepage.xhtml', 'tp'), \
        anthology['target']

    assert m_mod.suggest_toc_style(
        ['Heart of the Mountain', 'Heart of the Mountain Ch. 09',
         'Heart of the Mountain Ch. 10']) == 'flat'
    assert m_mod.suggest_toc_style(['Dune', 'Neuromancer', 'Book of Spells']) == 'sections'
    assert m_mod.suggest_toc_style(['Only One']) == 'sections'


def test_merge_flat_toc_fn(ctx):
    """A flat merge has no section headers, keeps every source's chapters, and
    mirrors the same list into the EPUB3 nav.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    sources = [staging_copy(paths['fic_simple']), staging_copy(paths['fic_nested']),
               staging_copy(paths['fic_multidir'])]
    out = os.path.join(os.path.dirname(sources[0]), 'flat.epub')

    result = m_mod.merge_books(sources, output_path=out, title='Collected',
                               toc_style='flat')
    assert result['ok'], result
    assert result['toc_style'] == 'flat', result
    assert_sane(out)

    with c_mod.EpubContainer(out) as c:
        labels = [label for label, _n, _f in c.toc_entries()]
        # every chapter from every source is present, including the ones that
        # would have been absorbed into a section header in sections mode
        for expect in ('Chapter 1', 'Chapter 5', 'One', 'Four', 'A', 'C'):
            assert expect in labels, '%r missing from flat TOC: %r' % (expect, labels)
        # and no source title became a header
        for source_title in ('Collected', 'Nested Fic', 'Multidir Fic'):
            assert source_title not in labels, \
                'flat TOC should have no section headers: %r' % (labels,)

        # the nav document carries the same labels as the NCX
        nav = [n for n in c.toc_doc_names() if c.media_type_of(n) != 'application/x-dtbncx+xml']
        if nav:
            nav_labels = [e.text for e in c.parsed(nav[0]).iter()
                          if e.tag.endswith('}a')]
            for expect in ('Chapter 1', 'One', 'A'):
                assert expect in nav_labels, '%r missing from nav: %r' % (expect, nav_labels)


def test_merge_sections_no_duplicate_labels_fn(ctx):
    """In sections mode no entry repeats its parent's label: the reader showed
    the same chapter twice for every source that had its own name as its first
    entry.
    """
    c_mod = require(ctx, 'epub_container')
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()

    sources = [staging_copy(paths['fic_simple']), staging_copy(paths['fic_titlepage'])]
    out = os.path.join(os.path.dirname(sources[0]), 'sections.epub')

    result = m_mod.merge_books(sources, output_path=out, title='Collected')
    assert result['ok'], result
    assert result['toc_style'] == 'sections', result
    assert_sane(out)

    with c_mod.EpubContainer(out) as c:
        ncx = [n for n in c.toc_doc_names()
               if c.media_type_of(n) == 'application/x-dtbncx+xml']
        assert ncx, 'base should still have an NCX'
        root = c.parsed(ncx[0])
        navmap = [e for e in root.iter() if c_mod.localname(e.tag) == 'navMap'][0]

        def label_of(node):
            for child in node.iter():
                if c_mod.localname(child.tag) == 'text':
                    return (child.text or '').strip()
            return ''

        for parent in [e for e in navmap if c_mod.localname(e.tag) == 'navPoint']:
            parent_label = label_of(parent)
            for child in parent:
                if c_mod.localname(child.tag) != 'navPoint':
                    continue
                assert label_of(child).lower() != parent_label.lower(), \
                    'entry %r repeats its section label' % parent_label

        # a sectioned merge keeps each source's title page: that page is where
        # the book's own details (author, dates, tags) are shown
        all_labels = [l for l, _n, _f in c.toc_entries()]
        assert 'Titlepage' in all_labels, all_labels


def test_merge_output_naming_fn(ctx):
    """The merged file is named after the title that was given, and a title that
    collides with a source still cannot overwrite that source.
    """
    m_mod = require(ctx, 'epub_merge')
    paths = fixture_paths()
    first = staging_copy(paths['fic_simple'])
    second = staging_copy(paths['fic_nested'])

    # no title -> the base book's name with a " (merged)" suffix
    fallback = m_mod.default_output_path(first)
    assert fallback.endswith(' (merged).epub'), fallback

    # a title -> a file named after the title, beside the base book
    named = m_mod.default_output_path(first, 'Heart of the Mountain merge test')
    assert os.path.basename(named) == 'Heart of the Mountain merge test.epub', named
    assert os.path.dirname(named) == os.path.dirname(first), named

    # characters a file name cannot hold are stripped
    awkward = os.path.basename(m_mod.default_output_path(first, 'A/B: "C"? <D> |E|'))
    for bad in '\\/:*?"<>|':
        assert bad not in awkward, awkward
    assert awkward.endswith('.epub'), awkward
    assert 'A' in awkward and 'E' in awkward, awkward

    # a title that matches a source's own name must not clobber it
    own_name = os.path.splitext(os.path.basename(first))[0]
    colliding = m_mod.default_output_path(first, own_name)
    assert os.path.abspath(colliding) == os.path.abspath(first), colliding
    guarded = m_mod._non_clobbering(colliding, [first, second])
    assert os.path.abspath(guarded) != os.path.abspath(first), guarded
    assert os.path.exists(first), 'the source must still be there'

    # end to end: the written file carries the title's name
    result = m_mod.merge_books([first, second], title='Collected Works Two')
    assert result['ok'], result
    assert os.path.basename(result['output_path']) == 'Collected Works Two.epub', \
        result['output_path']
    assert os.path.exists(result['output_path']), result
    assert_sane(result['output_path'])


def with_source_url(path, url='http://example.com/story/1'):
    """A copy of an EPUB whose OPF carries a story URL, as FanFicFare writes it.

    FanFicFare emits ``<dc:source>storyUrl</dc:source>`` plus a URL-scheme
    ``dc:identifier`` in every book it produces, so these are the elements a
    merged book would otherwise inherit from its base.
    """
    import shutil
    import tempfile

    dest_dir = tempfile.mkdtemp(prefix='ff_url_')
    dest = os.path.join(dest_dir, os.path.basename(path))
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(dest, 'w') as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith('.opf'):
                text = data.decode('utf-8')
                injected = ('<dc:source>%s</dc:source>'
                            '<dc:identifier opf:scheme="URL">%s</dc:identifier>' % (url, url))
                assert '</metadata>' in text, 'fixture OPF has no metadata block'
                text = text.replace('</metadata>', injected + '</metadata>', 1)
                data = text.encode('utf-8')
            out.writestr(info, data)
    return dest


def test_merge_drops_inherited_source_url_fn(ctx):
    """A merged book must not inherit the base's story URL.

    The library matches an existing book by URL before its path, so a merged book
    carrying the base's URL was found to be "already in the library": the base's
    row was updated to point at the merged file and the merged book never appeared
    as an entry of its own.
    """
    m_mod = require(ctx, 'epub_merge')
    bridge = require(ctx, 'fanficfare_bridge')
    paths = fixture_paths()

    base = with_source_url(staging_copy(paths['fic_simple']))
    other = staging_copy(paths['fic_nested'])

    before = json.loads(bridge.epub_metadata_json(base))
    assert before['url'] == 'http://example.com/story/1', before

    result = m_mod.merge_books([base, other], title='Merged Book')
    assert result['ok'], result

    after = json.loads(bridge.epub_metadata_json(result['output_path']))
    assert after['url'] == '', \
        'merged book inherited the base URL %r' % (after['url'],)
    assert after['title'] == 'Merged Book', after
    assert_sane(result['output_path'])

    # the sources must keep their own URLs: only the merged book drops it
    assert json.loads(bridge.epub_metadata_json(base))['url'] == \
        'http://example.com/story/1'


def run_tests():
    ctx = _load_modules()
    tests = [
        # --- epub_xml ------------------------------------------------------
        ('serialize_default_ns_no_ns0', test_serialize_default_ns_no_ns0_fn),
        ('parent_map_matches_structure', test_parent_map_matches_structure_fn),
        ('entity_expansion_and_tolerant_parse',
         test_entity_expansion_and_tolerant_parse_fn),
        ('split_prolog', test_split_prolog_fn),
        # --- epub_container ------------------------------------------------
        ('container_index', test_container_index_fn),
        ('container_href_math', test_container_href_math_fn),
        ('container_document_cache', test_container_document_cache_fn),
        ('container_commit_roundtrip', test_container_commit_roundtrip_fn),
        ('container_replace_links', test_container_replace_links_fn),
        ('container_spine_mutation', test_container_spine_mutation_fn),
        ('container_remove_item', test_container_remove_item_fn),
        # --- epub_merge (library-level merge) ------------------------------
        ('merge_plan_import', test_merge_plan_import_fn),
        ('merge_two_books', test_merge_two_books_fn),
        ('merge_titlepage_cover_reference', test_merge_titlepage_cover_reference_fn),
        ('merge_toc_nesting', test_merge_toc_nesting_fn),
        ('merge_declaration_matches_bytes', test_merge_declaration_matches_bytes_fn),
        ('merge_preserves_properties', test_merge_preserves_properties_fn),
        ('external_urls_untouched', test_external_urls_untouched_fn),
        ('merge_toc_edge_shapes', test_merge_toc_edge_shapes_fn),
        ('merge_nested_toc_and_unicode', test_merge_nested_toc_and_unicode_fn),
        ('bridge_merge_preview', test_bridge_merge_preview_fn),
        ('bridge_merge_writes_valid_book', test_bridge_merge_writes_valid_book_fn),
        ('merge_resource_collision', test_merge_resource_collision_fn),
        ('merge_metadata_and_output', test_merge_metadata_and_output_fn),
        ('toc_style_cleanup', test_toc_style_cleanup_fn),
        ('merge_flat_toc', test_merge_flat_toc_fn),
        ('merge_sections_no_duplicate_labels', test_merge_sections_no_duplicate_labels_fn),
        ('merge_output_naming', test_merge_output_naming_fn),
        ('merge_drops_inherited_source_url', test_merge_drops_inherited_source_url_fn),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn(ctx)
            print('  %s: OK' % name)
            passed += 1
        except Exception as e:
            print('  %s: FAILED - %s' % (name, e))
            traceback.print_exc()
            failed += 1
    print('')
    print('%d passed, %d failed' % (passed, failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(run_tests())
