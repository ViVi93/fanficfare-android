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

import threading
import xml.etree.ElementTree as ET

__all__ = [
    'serialize', 'register_namespaces', 'localname',
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
