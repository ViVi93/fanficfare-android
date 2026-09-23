#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""Generate the EPUB fixture corpus used by the EPUB merge/split test suites.

Fixtures are generated at run time instead of being committed, because the
Chaquopy source set (``app/src/main/python``) is packaged into the APK and
binary ``.epub`` files placed there would ship to users.

Usage::

    import make_fixtures
    paths = make_fixtures.ensure_fixtures()     # {name: path}, temp dir
    paths = make_fixtures.ensure_fixtures('/tmp/my_fixtures')

Set ``FF_FIXTURES_DIR`` to keep generated fixtures somewhere specific. Running
this file directly regenerates the whole corpus and reports the location.
"""

import os
import posixpath
import tempfile
import zipfile
from urllib.parse import quote

# 1x1 transparent PNG
PNG_1PX = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
    '890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082'
)

CONTAINER_TMPL = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="%s" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''

XHTML_TMPL = (
    '{prolog}'
    '<html xmlns="http://www.w3.org/1999/xhtml"{ns_extra}>\n'
    '<head><title>{title}</title>{head_extra}</head>\n'
    '<body>\n{body}\n</body>\n</html>\n'
)

EPUB_NS_ATTR = ' xmlns:epub="http://www.idpf.org/2007/ops"'
XLINK_NS_ATTR = ' xmlns:xlink="http://www.w3.org/1999/xlink"'


class EpubBuilder:
    """Minimal EPUB writer, scoped to producing test fixtures.

    Not a general purpose EPUB tool: it builds one OPF layout, writes the
    mimetype entry first and uncompressed, and lets the caller supply
    deliberately malformed content documents.
    """

    def __init__(self, opf_dir='OEBPS', version='2.0', title='Fixture Book',
                 author='Fixture Author', language='en',
                 identifier='urn:uuid:fixture-0000-0000-0000-000000000001'):
        self.opf_dir = opf_dir
        self.version = version
        self.title = title
        self.author = author
        self.language = language
        self.identifier = identifier
        self.opf_name = (opf_dir + '/content.opf') if opf_dir else 'content.opf'
        self._files = {}          # zipname -> (bytes, stored_bool)
        self._items = []          # manifest item dicts
        self._docs = []           # xhtml zipnames in add order
        self._spine = None        # explicit spine order; None -> self._docs
        self._ncx = False
        self._cover_id = None
        self._counters = {}

    # -- helpers ----------------------------------------------------------

    def _next_id(self, prefix):
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return '%s-%d' % (prefix, n)

    def _add_item(self, zipname, media_type, properties=None, attrs=None):
        item_id = self._next_id('item')
        self._items.append({
            'id': item_id, 'name': zipname, 'type': media_type,
            'properties': properties, 'attrs': dict(attrs or {}),
        })
        return item_id

    def _item_by_name(self, zipname):
        for it in self._items:
            if it['name'] == zipname:
                return it
        raise KeyError('not in manifest: %s' % zipname)

    def manifest_item(self, zipname):
        """Public accessor used by tests that need an item id."""
        return self._item_by_name(zipname)

    # -- content ----------------------------------------------------------

    def add_doc(self, zipname, body, title='Chapter', head_extra='',
                raw=None, epub3=False, properties=None, attrs=None, extra_ns=''):
        """Add an XHTML document. Pass ``raw`` to write the document verbatim
        (used for malformed markup and undefined entities). ``extra_ns`` adds
        namespace declarations to the root element (e.g. xmlns:xlink) so the
        document parses as strict XML instead of needing the html5lib fallback.
        """
        if raw is None:
            ns_extra = (EPUB_NS_ATTR if epub3 else '') + extra_ns
            data = XHTML_TMPL.format(
                prolog='<?xml version="1.0" encoding="utf-8"?>\n',
                ns_extra=ns_extra,
                title=title, head_extra=head_extra, body=body,
            )
        else:
            data = raw
        self._files[zipname] = (data.encode('utf-8') if isinstance(data, str) else data, False)
        self._add_item(zipname, 'application/xhtml+xml', properties=properties, attrs=attrs)
        self._docs.append(zipname)
        return zipname

    def add_style(self, zipname, text):
        self._files[zipname] = (text.encode('utf-8'), False)
        self._add_item(zipname, 'text/css')
        return zipname

    def add_image(self, zipname, data=PNG_1PX, mime='image/png', cover=False,
                  properties=None):
        self._files[zipname] = (data, True)
        if cover:
            properties = 'cover-image'
        item_id = self._add_item(zipname, mime, properties=properties)
        if cover:
            self._cover_id = item_id
        return item_id

    def add_raw(self, zipname, data, media_type=None, stored=False):
        """Add any file. When ``media_type`` is given it is also registered in
        the manifest and its item id is returned."""
        self._files[zipname] = (data.encode('utf-8') if isinstance(data, str) else data, stored)
        if media_type:
            return self._add_item(zipname, media_type)
        return None

    # -- structure --------------------------------------------------------

    def set_spine(self, zipnames):
        self._spine = list(zipnames)

    def set_ncx(self, navpoints, zipname='OEBPS/toc.ncx'):
        """Add an EPUB2 NCX.

        ``navpoints`` is a list of ``(label, href)`` pairs; an entry may instead
        be ``(label, href, [children])`` to nest navPoints under a parent.
        """
        self._add_item(zipname, 'application/x-dtbncx+xml')
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
            '  <head><meta name="dtb:uid" content="%s"/></head>' % self.identifier,
            '  <docTitle><text>%s</text></docTitle>' % self.title,
            '  <navMap>',
        ]
        counter = [0]

        def emit(entries, depth):
            for entry in entries:
                label, href = entry[0], entry[1]
                children = entry[2] if len(entry) > 2 else []
                counter[0] += 1
                pad = '    ' * (depth + 1)
                parts.append('%s<navPoint id="np%d" playOrder="%d">'
                             % (pad, counter[0], counter[0]))
                parts.append('%s  <navLabel><text>%s</text></navLabel>' % (pad, label))
                if href:
                    parts.append('%s  <content src="%s"/>' % (pad, href))
                if children:
                    emit(children, depth + 1)
                parts.append('%s</navPoint>' % pad)

        emit(navpoints, 0)
        parts += ['  </navMap>', '</ncx>', '']
        self._files[zipname] = ('\n'.join(parts).encode('utf-8'), False)
        self._ncx = True

    def set_nav(self, navpoints, zipname='OEBPS/nav.xhtml'):
        """Add an EPUB3 navigation document (not part of the spine)."""
        self._add_item(zipname, 'application/xhtml+xml', properties='nav')
        body = ['<nav epub:type="toc" id="toc">', '  <ol>']
        for label, href in navpoints:
            body.append('    <li><a href="%s">%s</a></li>' % (href, label))
        body += ['  </ol>', '</nav>']
        data = XHTML_TMPL.format(
            prolog='<?xml version="1.0" encoding="utf-8"?>\n',
            ns_extra=EPUB_NS_ATTR, title='Contents',
            head_extra='', body='\n'.join(body),
        )
        self._files[zipname] = (data.encode('utf-8'), False)

    # -- output -----------------------------------------------------------

    def _href(self, zipname):
        if not self.opf_dir:
            rel = zipname
        else:
            rel = posixpath.relpath(zipname, self.opf_dir)
        return quote(rel, safe='/#')

    def _build_opf(self):
        out = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<package xmlns="http://www.idpf.org/2007/opf" version="%s" '
            'unique-identifier="bookid">' % self.version,
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:opf="http://www.idpf.org/2007/opf">',
            '    <dc:identifier id="bookid">%s</dc:identifier>' % self.identifier,
            '    <dc:title>%s</dc:title>' % self.title,
            '    <dc:creator>%s</dc:creator>' % self.author,
            '    <dc:language>%s</dc:language>' % self.language,
        ]
        if self.version.startswith('3'):
            out.append('    <meta property="dcterms:modified">2020-01-01T00:00:00Z</meta>')
        if self._cover_id:
            out.append('    <meta name="cover" content="%s"/>' % self._cover_id)
        out.append('  </metadata>')
        out.append('  <manifest>')
        for it in self._items:
            props = ' properties="%s"' % it['properties'] if it['properties'] else ''
            attrs = ''.join(' %s="%s"' % (k, v) for k, v in sorted(it['attrs'].items()))
            out.append('    <item id="%s" href="%s" media-type="%s"%s%s/>'
                       % (it['id'], self._href(it['name']), it['type'], props, attrs))
        out.append('  </manifest>')
        out.append('  <spine%s>' % (' toc="ncx"' if self._ncx else ''))
        for name in (self._spine if self._spine is not None else self._docs):
            out.append('    <itemref idref="%s"/>' % self._item_by_name(name)['id'])
        out.append('  </spine>')
        out.append('</package>')
        out.append('')
        return '\n'.join(out)

    def write(self, path):
        self._files[self.opf_name] = (self._build_opf().encode('utf-8'), False)
        container = CONTAINER_TMPL % self.opf_name
        order = [self.opf_name]
        for name in self._files:
            if name not in order:
                order.append(name)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo('mimetype'), b'application/epub+zip',
                       zipfile.ZIP_STORED)
            z.writestr('META-INF/container.xml', container.encode('utf-8'))
            for name in order:
                data, stored = self._files[name]
                if stored:
                    z.writestr(zipfile.ZipInfo(name), data, zipfile.ZIP_STORED)
                else:
                    z.writestr(name, data)
        return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _para(index):
    return 'Paragraph %d of the fixture. ' % index


def build_fic_simple(path):
    """5 chapters, unique ids, EPUB2 NCX **and** EPUB3 nav, CSS in another dir."""
    b = EpubBuilder(version='3.0', title='Simple Fic',
                    identifier='urn:uuid:fixture-simple')
    b.add_style('OEBPS/styles/main.css',
                'body { font-family: serif; }\np { margin: 0; text-indent: 1em; }\n')
    for i in range(1, 6):
        b.add_doc(
            'OEBPS/text/chapter%d.xhtml' % i,
            '<h2 id="ch%d">Chapter %d</h2>\n<p>%s</p>' % (i, i, _para(i)),
            title='Chapter %d' % i,
            head_extra='<link rel="stylesheet" type="text/css" href="../styles/main.css"/>',
            epub3=True,
        )
    navpoints = [('Chapter %d' % i, 'text/chapter%d.xhtml#ch%d' % (i, i)) for i in range(1, 6)]
    b.set_ncx(navpoints)
    b.set_nav(navpoints)
    return b.write(path)


def build_fic_dupids(path):
    """Every chapter reuses calibre_pb_0 / toc / top, plus legacy name= anchors."""
    b = EpubBuilder(version='2.0', title='Duplicate Ids Fic',
                    identifier='urn:uuid:fixture-dupids')
    for i in range(1, 6):
        body = (
            '<div id="calibre_pb_0"></div>\n'
            '<a id="top" name="top"></a>\n'
            '<h2 id="toc">Chapter %d</h2>\n'
            '<p id="p1">%s</p>\n'
            '<a name="legacy-anchor"></a>\n'
            '<p><a href="#top">Back to top</a></p>' % (i, _para(i))
        )
        b.add_doc('OEBPS/text/chapter%d.xhtml' % i, body, title='Chapter %d' % i)
    b.set_ncx([('Chapter %d' % i, 'text/chapter%d.xhtml#toc' % i) for i in range(1, 6)])
    return b.write(path)


def build_fic_entities(path):
    """Undefined named entities, unclosed <br>, DOCTYPE and XML declaration."""
    b = EpubBuilder(version='2.0', title='Entities Fic',
                    identifier='urn:uuid:fixture-entities')
    raw_bad = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Entities</title></head>\n'
        '<body>\n'
        '<h2 id="ch1">Chapter&nbsp;1&mdash;Entities</h2>\n'
        '<p>Ellipsis&hellip; and a nonbreaking&nbsp;space.</p>\n'
        '<br>\n'
        '<p>Ampersand &amp; quote &quot; stay intact.</p>\n'
        '</body>\n</html>\n'
    )
    b.add_doc('OEBPS/text/chapter1.xhtml', None, raw=raw_bad)
    b.add_doc('OEBPS/text/chapter2.xhtml',
              '<h2 id="ch2">Chapter 2</h2>\n<p>Numeric&#160;entity is valid XML.</p>',
              title='Chapter 2')
    b.set_ncx([('Chapter 1', 'text/chapter1.xhtml#ch1'),
               ('Chapter 2', 'text/chapter2.xhtml#ch2')])
    return b.write(path)


def build_fic_nested(path):
    """3-deep nesting with two h2 split points inside one wrapper."""
    b = EpubBuilder(version='2.0', title='Nested Fic',
                    identifier='urn:uuid:fixture-nested')
    b.add_doc('OEBPS/text/part1.xhtml', (
        '<div class="part">\n'
        '  <div class="chapter">\n'
        '    <h2 id="ch1">Chapter One</h2>\n'
        '    <p>First chapter text.</p>\n'
        '    <h2 id="ch2">Chapter Two</h2>\n'
        '    <p>Second chapter text.</p>\n'
        '  </div>\n'
        '</div>'), title='Part One')
    b.add_doc('OEBPS/text/part2.xhtml',
              '<h2 id="ch3">Chapter Three</h2>\n<p>Third chapter text.</p>',
              title='Part Two')
    b.add_doc('OEBPS/text/part3.xhtml',
              '<h2 id="ch4">Chapter Four</h2>\n<p>Fourth chapter text.</p>',
              title='Part Three')
    navpoints = [('One', 'text/part1.xhtml#ch1'), ('Two', 'text/part1.xhtml#ch2'),
                 ('Three', 'text/part2.xhtml#ch3'), ('Four', 'text/part3.xhtml#ch4')]
    b.set_ncx(navpoints)
    return b.write(path)


def build_fic_multidir(path):
    """Docs in text/ and Text/ (case differs), ../ and absolute hrefs, %20 name."""
    b = EpubBuilder(version='2.0', title='Multidir Fic',
                    identifier='urn:uuid:fixture-multidir')
    b.add_image('OEBPS/images/pic.png')
    b.add_image('OEBPS/images/a b.png')
    b.add_style('OEBPS/text/local.css', 'p { color: #333; }\n')
    b.add_doc('OEBPS/text/a.xhtml', (
        '<h2 id="a1">A One</h2>\n'
        '<p><img src="../images/pic.png" alt="relative up"/></p>\n'
        '<p><img src="/OEBPS/images/pic.png" alt="absolute"/></p>\n'
        '<p><img src="../images/a%20b.png" alt="quoted"/></p>\n'
        '<p><a href="../Text/b.xhtml#b1">cross directory link</a></p>'),
        title='A', head_extra='<link rel="stylesheet" href="local.css"/>')
    b.add_doc('OEBPS/Text/b.xhtml', (
        '<h2 id="b1">B One</h2>\n'
        '<p><img src="../images/pic.png" alt="relative up"/></p>\n'
        '<p><a href="/OEBPS/text/a.xhtml#a1">absolute link</a></p>'),
        title='B')
    b.add_doc('OEBPS/c.xhtml',
              '<h2 id="c1">C One</h2>\n<p>Root level doc.</p>', title='C')
    b.set_ncx([('A', 'text/a.xhtml#a1'), ('B', 'Text/b.xhtml#b1'), ('C', 'c.xhtml#c1')])
    return b.write(path)


def build_fic_epub3(path):
    """epub:type, xlink:href inside inline SVG, cover-image, media-overlay."""
    b = EpubBuilder(version='3.0', title='EPUB3 Fic',
                    identifier='urn:uuid:fixture-epub3')
    b.add_image('OEBPS/images/cover.png', cover=True)
    b.add_image('OEBPS/images/fig.png')
    smil_id = b.add_raw('OEBPS/text/chapter1.smil', (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0">\n'
        '  <body><seq><par><text src="chapter1.xhtml#ch1"/></par></seq></body>\n'
        '</smil>\n'), media_type='application/smil+xml')
    b.add_doc('OEBPS/text/chapter1.xhtml', (
        '<h2 id="ch1" epub:type="chapter">Chapter One</h2>\n'
        '<p>Text with an inline figure.</p>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">\n'
        '  <image xlink:href="../images/fig.png" width="10" height="10"/>\n'
        '</svg>'),
        title='Chapter One', epub3=True, extra_ns=XLINK_NS_ATTR,
        attrs={'media-overlay': smil_id} if smil_id else None)
    b.add_doc('OEBPS/text/chapter2.xhtml',
              '<h2 id="ch2" epub:type="chapter">Chapter Two</h2>\n<p>Second.</p>',
              title='Chapter Two', epub3=True)
    b.set_ncx([('One', 'text/chapter1.xhtml#ch1'), ('Two', 'text/chapter2.xhtml#ch2')])
    b.set_nav([('One', 'text/chapter1.xhtml#ch1'), ('Two', 'text/chapter2.xhtml#ch2')])
    return b.write(path)


def build_fic_big(path, chapters=60, filler=40):
    """60 chapters of roughly 40KB each, for size caps and performance."""
    b = EpubBuilder(version='2.0', title='Big Fic',
                    identifier='urn:uuid:fixture-big')
    block = '<p>%s</p>\n' % ('Lorem ipsum dolor sit amet, consectetur adipiscing elit. ' * 20)
    for i in range(1, chapters + 1):
        b.add_doc('OEBPS/text/chapter%d.xhtml' % i,
                  ('<h2 id="ch%d">Chapter %d</h2>\n' % (i, i)) + (block * filler),
                  title='Chapter %d' % i)
    b.set_ncx([('Chapter %d' % i, 'text/chapter%d.xhtml#ch%d' % (i, i))
               for i in range(1, chapters + 1)])
    return b.write(path)


def build_fic_table(path):
    """An h2 inside a <table>, which must make splitting abort."""
    b = EpubBuilder(version='2.0', title='Table Fic',
                    identifier='urn:uuid:fixture-table')
    b.add_doc('OEBPS/text/chapter1.xhtml', (
        '<h2 id="ch1">Chapter One</h2>\n<p>Normal heading.</p>\n'
        '<table>\n<tr><td><h2 id="inside">Inside a table</h2></td></tr>\n</table>'),
        title='Chapter One')
    b.add_doc('OEBPS/text/chapter2.xhtml',
              '<h2 id="ch2">Chapter Two</h2>\n<p>Second.</p>', title='Chapter Two')
    b.set_ncx([('One', 'text/chapter1.xhtml#ch1'), ('Two', 'text/chapter2.xhtml#ch2')])
    return b.write(path)


def build_fic_links(path):
    """Every link form the rewriter must handle: href, src, xlink:href and
    url() in both an inline style attribute and a <style> element."""
    b = EpubBuilder(version='3.0', title='Links Fic',
                    identifier='urn:uuid:fixture-links')
    b.add_image('OEBPS/images/pic.png')
    b.add_image('OEBPS/images/bg.png')
    b.add_style('OEBPS/styles/main.css',
                'body { background: url(../images/bg.png); }\n')
    b.add_doc('OEBPS/text/target.xhtml',
              '<h2 id="t1">Target</h2>\n<p>target body</p>',
              title='Target', epub3=True, extra_ns=XLINK_NS_ATTR)
    b.add_doc('OEBPS/text/links.xhtml', (
        '<h2 id="l1">Links</h2>\n'
        '<p><a href="target.xhtml#t1">anchor</a></p>\n'
        '<p><img src="../images/pic.png" alt="img"/></p>\n'
        '<p style="background-image: url(../images/pic.png)">styled</p>\n'
        '<style>div { background: url("../images/pic.png"); }</style>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">\n'
        '  <image xlink:href="../images/pic.png" width="10" height="10"/>\n'
        '</svg>'),
        title='Links', epub3=True, extra_ns=XLINK_NS_ATTR,
        head_extra='<link rel="stylesheet" type="text/css" href="../styles/main.css"/>')
    b.set_ncx([('Target', 'text/target.xhtml#t1'), ('Links', 'text/links.xhtml#l1')])
    b.set_nav([('Target', 'text/target.xhtml#t1'), ('Links', 'text/links.xhtml#l1')])
    return b.write(path)


def build_fic_titlepage(path):
    """FanFicFare-shaped: a titlepage that references the book's own cover.

    Exercises the rule that cover images are *imported* rather than skipped --
    dropping one would leave this titlepage with a dangling <img src>.
    """
    b = EpubBuilder(version='2.0', title='Titlepage Fic',
                    identifier='urn:uuid:fixture-titlepage')
    b.add_image('OEBPS/cover.png', cover=True)
    b.add_style('OEBPS/styles/main.css', 'body { margin: 0; }\n')
    b.add_doc('OEBPS/titlepage.xhtml', (
        '<div class="titlepage">\n'
        '  <h1 id="tp">Titlepage Fic</h1>\n'
        '  <img src="cover.png" alt="cover"/>\n'
        '</div>'),
        title='Titlepage',
        head_extra='<link rel="stylesheet" type="text/css" href="styles/main.css"/>')
    b.add_doc('OEBPS/text/chapter1.xhtml',
              '<h2 id="p1">Chapter 1</h2>\n<p>Titlepage body one.</p>', title='Chapter 1')
    b.add_doc('OEBPS/text/chapter2.xhtml',
              '<h2 id="p2">Chapter 2</h2>\n<p>Titlepage body two.</p>', title='Chapter 2')
    b.set_ncx([('Titlepage', 'titlepage.xhtml#tp'),
               ('Chapter 1', 'text/chapter1.xhtml#p1'),
               ('Chapter 2', 'text/chapter2.xhtml#p2')])
    return b.write(path)


def build_fic_prefixed(path):
    """A book whose chapter labels repeat its own title.

    Labels read "Heart of the Mountain Ch. 00" and up, so a flat merge of several
    such books repeats the same long prefix on every line -- the shape label
    shortening exists for. The first entry is front matter, which must never be
    renumbered.
    """
    b = EpubBuilder(version='2.0', title='Heart of the Mountain',
                    identifier='urn:uuid:fixture-prefixed')
    b.add_image('OEBPS/cover.png', cover=True)
    b.add_doc('OEBPS/titlepage.xhtml', (
        '<div class="titlepage">\n'
        '  <h1 id="tp">Heart of the Mountain</h1>\n'
        '  <p>by WittyUserName</p>\n'
        '</div>'), title='Title Page')
    for index in range(0, 3):
        label = 'Heart of the Mountain Ch. %02d' % index
        b.add_doc('OEBPS/text/ch%02d.xhtml' % index,
                  '<h2 id="c%d">%s</h2>\n<p>Chapter body %d.</p>' % (index, label, index),
                  title=label)
    b.set_ncx([('Title Page', 'titlepage.xhtml#tp'),
               ('Heart of the Mountain Ch. 00', 'text/ch00.xhtml#c0'),
               ('Heart of the Mountain Ch. 01', 'text/ch01.xhtml#c1'),
               ('Heart of the Mountain Ch. 02', 'text/ch02.xhtml#c2')])
    return b.write(path)


def build_fic_encoding(path):
    """A chapter that declares iso-8859-1 and contains latin-1 bytes.

    Re-serializing such a document without correcting its declaration leaves a
    reader decoding UTF-8 bytes as latin-1, which is mojibake.
    """
    b = EpubBuilder(version='2.0', title='Encoding Fic',
                    identifier='urn:uuid:fixture-encoding')
    latin1 = ('<?xml version="1.0" encoding="iso-8859-1"?>\n'
              '<html xmlns="http://www.w3.org/1999/xhtml">\n'
              '<head><title>Caf\xe9</title></head>\n'
              '<body><h2 id="e1">Caf\xe9</h2>\n'
              '<p>na\xefve r\xe9sum\xe9</p></body>\n</html>\n'
              ).encode('iso-8859-1')
    b.add_doc('OEBPS/text/latin1.xhtml', None, raw=latin1)
    b.add_doc('OEBPS/text/utf8.xhtml',
              '<h2 id="u1">UTF-8 chapter</h2>\n<p>na\u00efve r\u00e9sum\u00e9</p>',
              title='UTF-8')
    b.set_ncx([('Latin-1', 'text/latin1.xhtml#e1'),
               ('UTF-8', 'text/utf8.xhtml#u1')])
    return b.write(path)


def build_fic_media(path):
    """EPUB3 with a media overlay and semantic properties worth preserving."""
    b = EpubBuilder(version='3.0', title='Media Fic',
                    identifier='urn:uuid:fixture-media')
    b.add_image('OEBPS/images/cover.png', cover=True)
    smil_id = b.add_raw('OEBPS/text/chapter1.smil', (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0">\n'
        '  <body><seq><par><text src="chapter1.xhtml#m1"/></par></seq></body>\n'
        '</smil>\n'), media_type='application/smil+xml')
    b.add_doc('OEBPS/text/chapter1.xhtml',
              '<h2 id="m1" epub:type="chapter">Media One</h2>\n'
              '<p>With an overlay.</p>',
              title='Media One', epub3=True, extra_ns=XLINK_NS_ATTR,
              attrs={'media-overlay': smil_id})
    b.add_doc('OEBPS/text/chapter2.xhtml',
              '<h2 id="m2">Media Two</h2>\n'
              '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
              '<rect width="4" height="4"/></svg>',
              title='Media Two', epub3=True, properties='svg scripted')
    navpoints = [('Media One', 'text/chapter1.xhtml#m1'),
                 ('Media Two', 'text/chapter2.xhtml#m2')]
    b.set_ncx(navpoints)
    b.set_nav(navpoints)
    return b.write(path)


def build_fic_navonly(path):
    """EPUB3 with a nav document but **no NCX** -- exercises the nav fallback."""
    b = EpubBuilder(version='3.0', title='Nav Only Fic',
                    identifier='urn:uuid:fixture-navonly')
    b.add_doc('OEBPS/text/one.xhtml', '<h2 id="n1">Nav One</h2>\n<p>one</p>',
              title='Nav One', epub3=True)
    b.add_doc('OEBPS/text/two.xhtml', '<h2 id="n2">Nav Two</h2>\n<p>two</p>',
              title='Nav Two', epub3=True)
    b.set_nav([('Nav One', 'text/one.xhtml#n1'), ('Nav Two', 'text/two.xhtml#n2')])
    return b.write(path)


def build_fic_notoc(path):
    """No NCX and no nav document at all -- a book with no table of contents."""
    b = EpubBuilder(version='2.0', title='No TOC Fic',
                    identifier='urn:uuid:fixture-notoc')
    for i in (1, 2):
        b.add_doc('OEBPS/text/plain%d.xhtml' % i,
                  '<h2 id="t%d">Plain %d</h2>\n<p>plain body %d</p>' % (i, i, i),
                  title='Plain %d' % i)
    return b.write(path)


def build_fic_external(path):
    """External, protocol-relative and data: references that must not be rewritten."""
    b = EpubBuilder(version='2.0', title='External Fic',
                    identifier='urn:uuid:fixture-external')
    b.add_image('OEBPS/images/local.png')
    b.add_doc('OEBPS/text/ext.xhtml', (
        '<h2 id="x1">External</h2>\n'
        '<p><a href="http://example.com/story">http link</a></p>\n'
        '<p><a href="https://example.com/secure#frag">https link</a></p>\n'
        '<p><a href="mailto:someone@example.com">mail</a></p>\n'
        '<p><img src="//cdn.example.com/pic.png" alt="protocol relative"/></p>\n'
        '<p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="inline"/></p>\n'
        '<p><img src="../images/local.png" alt="local"/></p>'),
        title='External')
    b.set_ncx([('External', 'text/ext.xhtml#x1')])
    return b.write(path)


def build_fic_tocnested(path):
    """A source whose TOC has parent navPoints with children (two levels)."""
    b = EpubBuilder(version='2.0', title='Nested TOC Fic',
                    identifier='urn:uuid:fixture-tocnested')
    for i in range(1, 5):
        b.add_doc('OEBPS/text/c%d.xhtml' % i,
                  '<h2 id="d%d">Chapter %d</h2>\n<p>nested toc body %d</p>'
                  % (i, i, i), title='Chapter %d' % i)
    b.set_ncx([
        ('Part One', 'text/c1.xhtml#d1', [
            ('Chapter 1', 'text/c1.xhtml#d1'),
            ('Chapter 2', 'text/c2.xhtml#d2'),
        ]),
        ('Part Two', 'text/c3.xhtml#d3', [
            ('Chapter 3', 'text/c3.xhtml#d3'),
            ('Chapter 4', 'text/c4.xhtml#d4'),
        ]),
    ])
    return b.write(path)


def build_fic_unicode(path):
    """Non-ASCII in the title, TOC labels, text and a filename."""
    b = EpubBuilder(version='2.0', title='Caf\u00e9 \u2014 na\u00efve r\u00e9sum\u00e9',
                    identifier='urn:uuid:fixture-unicode',
                    author='\u5c71\u7530 \u592a\u90ce')
    b.add_doc('OEBPS/text/caf\u00e9.xhtml',
              '<h2 id="u2">\u30c1\u30e3\u30d7\u30bf\u30fc\uff11</h2>\n'
              '<p>na\u00efve r\u00e9sum\u00e9 \u2014 \u201cquoted\u201d</p>',
              title='\u30c1\u30e3\u30d7\u30bf\u30fc\uff11')
    b.add_doc('OEBPS/text/plain.xhtml',
              '<h2 id="u1">Plain</h2>\n<p>plain</p>', title='Plain')
    b.set_ncx([('\u30c1\u30e3\u30d7\u30bf\u30fc\uff11', 'text/caf%C3%A9.xhtml#u2'),
               ('Plain', 'text/plain.xhtml#u1')])
    return b.write(path)


FIXTURES = {
    'fic_unicode': build_fic_unicode,
    'fic_tocnested': build_fic_tocnested,
    'fic_external': build_fic_external,
    'fic_notoc': build_fic_notoc,
    'fic_navonly': build_fic_navonly,
    'fic_media': build_fic_media,
    'fic_encoding': build_fic_encoding,
    'fic_titlepage': build_fic_titlepage,
    'fic_prefixed': build_fic_prefixed,
    'fic_links': build_fic_links,
    'fic_simple': build_fic_simple,
    'fic_dupids': build_fic_dupids,
    'fic_entities': build_fic_entities,
    'fic_nested': build_fic_nested,
    'fic_multidir': build_fic_multidir,
    'fic_epub3': build_fic_epub3,
    'fic_big': build_fic_big,
    'fic_table': build_fic_table,
}

FIXTURE_NAMES = sorted(FIXTURES)

_cached_dir = None


def ensure_fixtures(dest=None):
    """Build every fixture and return {name: path}.

    Uses ``dest``, else ``$FF_FIXTURES_DIR``, else a per-process temp directory
    so nothing binary lands in the repository or the APK source set.
    """
    global _cached_dir
    if dest is None:
        dest = os.environ.get('FF_FIXTURES_DIR')
    if dest is None:
        if _cached_dir is None:
            _cached_dir = tempfile.mkdtemp(prefix='ff_epub_fixtures_')
        dest = _cached_dir
    else:
        os.makedirs(dest, exist_ok=True)
    paths = {}
    for name in FIXTURE_NAMES:
        path = os.path.join(dest, name + '.epub')
        paths[name] = FIXTURES[name](path)
    return paths


def main():
    paths = ensure_fixtures()
    for name in FIXTURE_NAMES:
        print('%-14s %8d bytes  %s' % (
            name, os.path.getsize(paths[name]), paths[name]))
    print('')
    print('%d fixtures written' % len(paths))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
