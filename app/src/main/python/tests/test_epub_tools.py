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


def run_tests():
    ctx = _load_modules()
    tests = [
        # --- epub_xml ------------------------------------------------------
        ('serialize_default_ns_no_ns0', test_serialize_default_ns_no_ns0_fn),
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
