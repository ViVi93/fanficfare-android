#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""Namespace-safe ElementTree serialization, shared by the EPUB modules.

ElementTree keeps a single **process-global** namespace registry, and both the
OPF and XHTML formats want the *empty* prefix as their default namespace. If the
two are registered from different modules without coordination, whichever lost
the race gets written out with synthesized ``ns0:`` prefixes -- noisy at best,
and rejected by strict readers at worst.

Everything that writes a namespaced document must therefore go through
:func:`serialize`, which re-registers the registry for the document kind it is
about to write. ``ET.tostring`` must not be called anywhere else in the
codebase; ``epub_editor._serialize_opf`` is routed through here for exactly
that reason.

The registration is guarded by a lock because Chaquopy can service Python calls
from more than one Kotlin thread.
"""

import html.entities
import re
import threading
import xml.etree.ElementTree as ET

__all__ = [
    'serialize', 'register_namespaces', 'localname', 'parent_map', 'ancestors',
    'iter_with_attr', 'parse_xhtml', 'expand_named_entities', 'split_prolog',
    'OPF', 'XHTML', 'NCX',
    'OPF_NS', 'DC_NS', 'XHTML_NS', 'OPS_NS', 'XLINK_NS', 'SVG_NS', 'NCX_NS',
]

OPF_NS = 'http://www.idpf.org/2007/opf'
DC_NS = 'http://purl.org/dc/elements/1.1/'
XHTML_NS = 'http://www.w3.org/1999/xhtml'
OPS_NS = 'http://www.idpf.org/2007/ops'
XLINK_NS = 'http://www.w3.org/1999/xlink'
SVG_NS = 'http://www.w3.org/2000/svg'
NCX_NS = 'http://www.daisy.org/z3986/2005/ncx/'

# Document kinds: each one claims the empty (default) prefix.
OPF = 'opf'
XHTML = 'xhtml'
NCX = 'ncx'

_DEFAULT_NS = {
    OPF: OPF_NS,
    XHTML: XHTML_NS,
    NCX: NCX_NS,
}

# Non-default prefixes. SVG gets an explicit prefix rather than the default
# namespace: only one namespace can own the empty prefix at a time, and inline
# SVG inside XHTML is serialized as <svg:svg>/<svg:image>, which is equivalent
# XML and widely supported.
_PREFIXES = (
    ('opf', OPF_NS),
    ('dc', DC_NS),
    ('epub', OPS_NS),
    ('xlink', XLINK_NS),
    ('svg', SVG_NS),
    ('ncx', NCX_NS),
)

_LOCK = threading.RLock()


def register_namespaces(kind=OPF):
    """Point the global registry at ``kind``'s default namespace.

    ``ET``'s registry maps *namespace URI -> prefix*, so a prefix entry for the
    namespace that is currently the default would overwrite the empty prefix and
    push the document into ``<opf:package>``-style output. Any prefix whose URI
    is this kind's default is therefore skipped.
    """
    if kind not in _DEFAULT_NS:
        raise ValueError('unknown document kind: %r' % (kind,))
    default_ns = _DEFAULT_NS[kind]
    with _LOCK:
        ET.register_namespace('', default_ns)
        for prefix, ns in _PREFIXES:
            if ns == default_ns:
                continue
            ET.register_namespace(prefix, ns)


def serialize(root, kind=OPF, xml_declaration=True):
    """Serialize ``root`` to UTF-8 bytes with ``kind`` as the default namespace.

    ``kind`` is one of :data:`OPF`, :data:`XHTML`, :data:`NCX`. Because the
    registration happens immediately before the write, alternating between
    kinds is safe.
    """
    register_namespaces(kind)
    with _LOCK:
        return ET.tostring(root, encoding='utf-8', xml_declaration=xml_declaration)


def localname(tag):
    """``'{ns}p'`` -> ``'p'``; leaves unqualified names alone."""
    if isinstance(tag, str) and '}' in tag:
        return tag.rsplit('}', 1)[-1]
    return tag


# ---------------------------------------------------------------------------
# Tree navigation
#
# ElementTree has no getparent(), no ancestor axis and no XPath attribute
# selectors. These three primitives cover every navigation need the EPUB
# algorithms have, without an XPath engine.
# ---------------------------------------------------------------------------

def parent_map(root, cache=None):
    """Map every descendant to its parent in one pass.

    ``cache`` may be an existing dict to extend, so one map can serve several
    lookups in the same function. ``root`` itself is not a key (it has no
    parent), which matches the previous recursive ``_find_parent`` semantics of
    returning ``None`` for the search root.
    """
    pm = {} if cache is None else cache
    for parent in root.iter():
        for child in parent:
            pm[child] = parent
    return pm


def ancestors(elem, pm):
    """Yield the ancestors of ``elem``, nearest first, using a ``parent_map``."""
    while elem in pm:
        elem = pm[elem]
        yield elem


def iter_with_attr(root, attr):
    """Yield every element carrying ``attr`` (replaces ``xpath('//*/@id')``)."""
    for elem in root.iter():
        if attr in elem.attrib:
            yield elem


# ---------------------------------------------------------------------------
# Tolerant parsing
#
# Content documents inside real EPUBs routinely contain named entities such as
# &nbsp; (undefined in XML without a DTD) and HTML that is not well formed.
# ElementTree raises on both, so parsing is a three-step ladder.
# ---------------------------------------------------------------------------

_ENTITY_RE = re.compile(r'&([A-Za-z][A-Za-z0-9]*);')

# The five XML built-ins must never be expanded: they are part of XML itself,
# and html.entities.html5 also lists them, so expanding &amp; would emit a bare
# & and corrupt the document.
_XML_BUILTIN_ENTITIES = frozenset({'amp;', 'lt;', 'gt;', 'quot;', 'apos;'})

_XML_DECL_RE = re.compile(rb'\s*<\?xml[^>]*\?>', re.IGNORECASE)

_WS_BYTES = b' \t\r\n\f\v'


def _skip_ws(raw, pos):
    while pos < len(raw) and raw[pos:pos + 1] in _WS_BYTES:
        pos += 1
    return pos


def _scan_doctype(raw, start):
    """End index (exclusive) of a DOCTYPE starting at ``start``, or None.

    Handles an internal subset and quoted strings, which a naive ``[^>]*``
    match gets wrong: ``<!ENTITY nbsp "&#160;">`` inside ``[ ]`` contains a
    ``>`` that must not terminate the declaration.
    """
    i = start + len(b'<!DOCTYPE')
    depth = 0
    quote = None
    while i < len(raw):
        char = raw[i:i + 1]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in (b'"', b"'"):
            quote = char
        elif char == b'[':
            depth += 1
        elif char == b']':
            if depth:
                depth -= 1
        elif char == b'>' and depth == 0:
            return i + 1
        i += 1
    return None


def expand_named_entities(raw):
    """Bytes -> bytes with HTML named entities replaced by their characters.

    Unknown names and the XML built-ins (``&amp;`` ``&lt;`` ``&gt;`` ``&quot;``
    ``&apos;``) are left untouched so escaping stays intact and re-parsing an
    already-valid document is a no-op.
    """
    if isinstance(raw, bytes):
        text = raw.decode('utf-8', 'replace')
    else:
        text = raw

    def sub(match):
        name = match.group(1) + ';'
        if name in _XML_BUILTIN_ENTITIES:
            return match.group(0)
        replacement = html.entities.html5.get(name)
        if replacement is None:
            return match.group(0)
        return replacement

    return _ENTITY_RE.sub(sub, text).encode('utf-8')


def parse_xhtml(raw):
    """Parse an XHTML/HTML document as leniently as is reasonable.

    Tries strict XML first, then XML with named entities expanded, then html5lib
    (an existing Chaquopy dependency). Returns an Element root; the ElementTree
    document prolog/doctype is dropped -- use :func:`split_prolog` to keep it.
    """
    for candidate in (raw, expand_named_entities(raw)):
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            pass
    import html5lib
    result = html5lib.parse(expand_named_entities(raw).decode('utf-8'),
                            namespaceHTMLElements=True, treebuilder='etree')
    getroot = getattr(result, 'getroot', None)
    return getroot() if getroot else result


def split_prolog(raw):
    """Split the leading XML declaration/DOCTYPE from trailing whitespace.

    Returns ``(header, footer)`` bytes. ElementTree discards both when parsing
    and re-serializing, so a document written back out must have them re-attached
    to stay a valid XHTML file. Comments and processing instructions after the
    root element are not preserved (ElementTree drops those too).
    """
    if isinstance(raw, str):
        raw = raw.encode('utf-8')

    decl = _XML_DECL_RE.match(raw)
    pos = decl.end() if decl else 0
    body_start = _skip_ws(raw, pos)
    # With a declaration, the whitespace after it belongs to the header.
    header_end = body_start if decl else 0

    if raw[body_start:body_start + len(b'<!DOCTYPE')].upper() == b'<!DOCTYPE':
        stop = _scan_doctype(raw, body_start)
        if stop is None:
            header_end = body_start      # malformed: leave the doctype in place
        else:
            header_end = _skip_ws(raw, stop)

    header = raw[:header_end]
    tail = raw[header_end:]
    end = re.search(rb'\s*$', tail)
    footer = end.group(0) if end else b''
    return header, footer
