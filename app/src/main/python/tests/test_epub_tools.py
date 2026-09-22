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


def run_tests():
    ctx = _load_modules()
    tests = []

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
