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
import os
import sys
import traceback
import zipfile
import xml.etree.ElementTree as ET

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODULE_NAMES = ('epub_xml', 'epub_container', 'epub_tools')


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


def run_tests():
    ctx = _load_modules()
    tests = [
        # --- epub_xml ------------------------------------------------------
        ('serialize_default_ns_no_ns0', test_serialize_default_ns_no_ns0_fn),
        ('parent_map_matches_structure', test_parent_map_matches_structure_fn),
        ('entity_expansion_and_tolerant_parse',
         test_entity_expansion_and_tolerant_parse_fn),
        ('split_prolog', test_split_prolog_fn),
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
