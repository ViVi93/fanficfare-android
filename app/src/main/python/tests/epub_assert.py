#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""Independent structural validator for EPUB fixtures and merge/split output.

Deliberately does **not** import ``epub_editor`` / ``epub_xml`` /
``epub_container``: the checker must not share parsing or linking bugs with the
code it validates. It carries its own tolerant parser and its own namespace
handling.

Checks performed by :func:`assert_epub_sane`:

1. ``mimetype`` is the first zip entry and stored uncompressed.
2. ``META-INF/container.xml`` exists and its rootfile resolves.
3. Every manifest ``item`` href resolves to an existing zip entry.
4. Every spine ``itemref`` idref exists in the manifest.
5. No duplicate ``id`` / ``name`` anchors **within** any content document.
6. Every internal ``href`` / ``src`` / ``xlink:href`` resolves to an existing
   entry, and its fragment exists in the target document.
7. NCX ``content/@src`` and nav-document links resolve the same way.

Run directly to regenerate the fixture corpus and self-test::

    PYTHONPATH=. python3 tests/epub_assert.py
"""

import os
import posixpath
import re
import sys
import zipfile
from urllib.parse import unquote, urlparse

import xml.etree.ElementTree as ET

DOC_TYPES = frozenset({'application/xhtml+xml', 'text/html'})
EXTERNAL_SCHEMES = ('http', 'https', 'mailto', 'tel', 'data', 'ftp', 'irc', 'urn')

_ENTITY_RE = re.compile(r'&([A-Za-z][A-Za-z0-9]*);')


def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) and '}' in tag else tag


def _iter_local(root, name):
    for elem in root.iter():
        if _local(elem.tag) == name:
            yield elem


def _xlink_href(elem):
    return elem.get('{http://www.w3.org/1999/xlink}href')


def _expand_named_entities(raw):
    import html.entities
    text = raw.decode('utf-8', 'replace')

    def sub(match):
        name = match.group(1) + ';'
        if name in html.entities.html5:
            return html.entities.html5[name]
        return match.group(0)

    return _ENTITY_RE.sub(sub, text).encode('utf-8')


def parse_tolerant(raw):
    """Parse XHTML leniently. Returns an Element root, or None if hopeless."""
    for candidate in (raw, _expand_named_entities(raw)):
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            pass
    try:
        import html5lib
        result = html5lib.parse(_expand_named_entities(raw).decode('utf-8'),
                                namespaceHTMLElements=True, treebuilder='etree')
        getroot = getattr(result, 'getroot', None)
        return getroot() if getroot else result
    except Exception:
        return None


def resolve(base_name, href):
    """(target_zipname, fragment) for an href relative to base_name."""
    path, _, frag = href.partition('#')
    path = unquote(path.split('?', 1)[0])
    if not path:
        return base_name, frag
    if path.startswith('/'):
        return posixpath.normpath(path.lstrip('/')), frag
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_name), path)), frag


def anchors_of(root):
    """All id/name anchor values in a document."""
    out = set()
    for elem in root.iter():
        val = elem.get('id')
        if val:
            out.add(val)
        val = elem.get('name')
        if val:
            out.add(val)
    return out


def _is_external(url):
    if url.startswith('//'):
        # Protocol-relative: //host/path is external, not an archive-absolute path.
        return True
    parsed = urlparse(url)
    return bool(parsed.scheme) and parsed.scheme.lower() in EXTERNAL_SCHEMES


def audit(path):
    """Inspect an EPUB. Returns {'problems': [...], 'warnings': [...], 'stats': {...}}."""
    problems = []
    warnings = []
    stats = {'docs': 0, 'manifest_items': 0, 'links': 0, 'spine': 0, 'anchors': 0}

    def problem(msg):
        problems.append('%s: %s' % (os.path.basename(path), msg))

    if not zipfile.is_zipfile(path):
        problem('not a zip archive')
        return {'problems': problems, 'warnings': warnings, 'stats': stats}

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        infos = z.infolist()

        # 1. mimetype first + stored
        if not names or names[0] != 'mimetype':
            problem('mimetype is not the first entry (first=%r)' % (names[:1] or None))
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            problem('mimetype is compressed (compress_type=%d)' % infos[0].compress_type)
        if 'mimetype' in names and z.read('mimetype') != b'application/epub+zip':
            problem('mimetype content is not application/epub+zip')

        # 2. container.xml
        if 'META-INF/container.xml' not in names:
            problem('META-INF/container.xml missing')
            return {'problems': problems, 'warnings': warnings, 'stats': stats}
        try:
            croot = ET.fromstring(z.read('META-INF/container.xml'))
        except ET.ParseError as e:
            problem('container.xml is not XML: %s' % e)
            return {'problems': problems, 'warnings': warnings, 'stats': stats}
        opf_names = [rf.get('full-path') for rf in _iter_local(croot, 'rootfile')]
        opf_name = opf_names[0] if opf_names else None
        if not opf_name:
            problem('container.xml declares no rootfile')
            return {'problems': problems, 'warnings': warnings, 'stats': stats}
        if opf_name not in names:
            problem('rootfile %r is not in the archive' % opf_name)
            return {'problems': problems, 'warnings': warnings, 'stats': stats}
        extra_opf = [n for n in names if n.endswith('.opf') and n != opf_name]
        if extra_opf:
            warnings.append('extra .opf entries present: %s' % extra_opf)

        # OPF itself
        try:
            oroot = ET.fromstring(z.read(opf_name))
        except ET.ParseError as e:
            problem('OPF %r is not XML: %s' % (opf_name, e))
            return {'problems': problems, 'warnings': warnings, 'stats': stats}

        manifest = {}
        for item in _iter_local(oroot, 'item'):
            iid = item.get('id')
            href = item.get('href')
            mtype = item.get('media-type') or ''
            stats['manifest_items'] += 1
            if iid is None or href is None:
                problem('manifest item missing id/href: %r' % (item.attrib,))
                continue
            manifest[iid] = {'href': href, 'type': mtype, 'name': None,
                             'overlay': item.get('media-overlay')}
            target, frag = resolve(opf_name, href)
            manifest[iid]['name'] = target
            if frag:
                problem('manifest href %r must not contain a fragment' % href)
            if target not in names:
                problem('manifest item %s href %r -> %r not in archive'
                        % (iid, href, target))

        # 4. spine
        for itemref in _iter_local(oroot, 'itemref'):
            idref = itemref.get('idref')
            stats['spine'] += 1
            if idref not in manifest:
                problem('spine idref %r not in manifest' % idref)

        # 5/6. content documents
        doc_names = [it['name'] for it in manifest.values()
                     if it['type'] in DOC_TYPES and it['name'] in names]
        anchor_cache = {}
        for name in doc_names:
            root = parse_tolerant(z.read(name))
            if root is None:
                problem('document %r could not be parsed even leniently' % name)
                continue
            stats['docs'] += 1
            seen = set()
            for elem in root.iter():
                # An element legitimately carrying both id="x" and name="x" is one
                # anchor, so de-duplicate the values per element first.
                for val in {v for v in (elem.get('id'), elem.get('name')) if v}:
                    if val in seen:
                        problem('duplicate anchor %r in %r' % (val, name))
                    else:
                        seen.add(val)
            anchors = anchors_of(root)
            anchor_cache[name] = anchors
            stats['anchors'] += len(anchors)

            for elem in root.iter():
                urls = []
                for attr in ('href', 'src'):
                    val = elem.get(attr)
                    if val:
                        urls.append(val)
                xl = _xlink_href(elem)
                if xl:
                    urls.append(xl)
                for url in urls:
                    if _is_external(url) or url.startswith('data:'):
                        continue
                    stats['links'] += 1
                    target, frag = resolve(name, url)
                    if target not in names:
                        problem('link %r in %r -> %r not in archive'
                                % (url, name, target))
                        continue
                    if frag:
                        t_anchors = anchor_cache.get(target)
                        if t_anchors is None:
                            troot = parse_tolerant(z.read(target))
                            t_anchors = anchors_of(troot) if troot is not None else set()
                            anchor_cache[target] = t_anchors
                        if frag not in t_anchors:
                            problem('link %r in %r -> fragment %r not found in %r'
                                    % (url, name, frag, target))

        # 6b. media overlays: the manifest attribute must resolve to a SMIL
        # document, and that SMIL's own references must survive relocation.
        for iid, info in manifest.items():
            overlay = info.get('overlay')
            if not overlay:
                continue
            if overlay not in manifest:
                problem('manifest item %s media-overlay %r is not a manifest id'
                        % (iid, overlay))
                continue
            if manifest[overlay]['type'] != 'application/smil+xml':
                warnings.append('media-overlay %r is not a SMIL document' % overlay)
            smil_name = manifest[overlay]['name']
            if smil_name not in names:
                problem('media-overlay %r target %r is not in the archive'
                        % (overlay, smil_name))
                continue
            sroot = parse_tolerant(z.read(smil_name))
            if sroot is None:
                problem('SMIL %r could not be parsed' % smil_name)
                continue
            for elem in sroot.iter():
                url = elem.get('src')
                if not url or _is_external(url):
                    continue
                target, frag = resolve(smil_name, url)
                if target not in names:
                    problem('SMIL %r src %r -> %r not in archive'
                            % (smil_name, url, target))
                    continue
                if frag:
                    t_anchors = anchor_cache.get(target)
                    if t_anchors is None:
                        troot = parse_tolerant(z.read(target))
                        t_anchors = anchors_of(troot) if troot is not None else set()
                        anchor_cache[target] = t_anchors
                    if frag not in t_anchors:
                        problem('SMIL %r src %r -> fragment %r missing in %r'
                                % (smil_name, url, frag, target))

        # 7. NCX + nav
        for iid, it in manifest.items():
            if it['type'] == 'application/x-dtbncx+xml' and it['name'] in names:
                nroot = parse_tolerant(z.read(it['name']))
                if nroot is None:
                    problem('NCX %r unparseable' % it['name'])
                    continue
                for content in _iter_local(nroot, 'content'):
                    src = content.get('src')
                    if not src:
                        problem('NCX navPoint without content src')
                        continue
                    target, frag = resolve(it['name'], src)
                    if target not in names:
                        problem('NCX src %r -> %r not in archive' % (src, target))
                    elif frag:
                        t_anchors = anchor_cache.get(target)
                        if t_anchors is None:
                            troot = parse_tolerant(z.read(target))
                            t_anchors = anchors_of(troot) if troot is not None else set()
                            anchor_cache[target] = t_anchors
                        if frag not in t_anchors:
                            problem('NCX src %r -> fragment %r missing in %r'
                                    % (src, frag, target))

        for item in _iter_local(oroot, 'item'):
            props = item.get('properties') or ''
            if 'nav' in props.split():
                name = manifest.get(item.get('id'), {}).get('name')
                if not name or name not in names:
                    continue
                nroot = parse_tolerant(z.read(name))
                if nroot is None:
                    problem('nav document %r unparseable' % name)
                    continue
                for a in _iter_local(nroot, 'a'):
                    href = a.get('href')
                    if not href or _is_external(href):
                        continue
                    target, frag = resolve(name, href)
                    if target not in names:
                        problem('nav link %r -> %r not in archive' % (href, target))

    return {'problems': problems, 'warnings': warnings, 'stats': stats}


def assert_epub_sane(path):
    """Raise AssertionError listing every structural problem. Returns stats."""
    result = audit(path)
    if result['problems']:
        raise AssertionError('%d problem(s):\n  %s'
                             % (len(result['problems']), '\n  '.join(result['problems'])))
    return result['stats']


# ---------------------------------------------------------------------------
# Self-test (also verifies the checker actually detects breakage)
# ---------------------------------------------------------------------------

def _make_broken_dupid(path):
    """Two elements sharing an id in one document."""
    from fixtures.make_fixtures import EpubBuilder
    b = EpubBuilder(version='2.0', title='Broken DupId',
                    identifier='urn:uuid:broken-dupid')
    b.add_doc('text/chapter1.xhtml',
              '<h2 id="dup">One</h2>\n<p id="dup">Two</p>', title='One')
    return b.write(path)


def _make_broken_dangling(path):
    """A link and an NCX entry pointing at a missing document."""
    from fixtures.make_fixtures import EpubBuilder
    b = EpubBuilder(version='2.0', title='Broken Dangling',
                    identifier='urn:uuid:broken-dangling')
    b.add_doc('text/chapter1.xhtml',
              '<h2 id="ch1">One</h2>\n<p><a href="nope.xhtml">missing</a></p>',
              title='One')
    b.set_ncx([('One', 'text/nope.xhtml#ch1')])
    return b.write(path)


def main():
    import tempfile
    import fixtures.make_fixtures as mf

    failures = []
    paths = mf.ensure_fixtures()

    print('Checking %d fixtures' % len(paths))
    total_links = 0
    for name in mf.FIXTURE_NAMES:
        result = audit(paths[name])
        if result['problems']:
            failures.append(name)
            print('  %-14s BROKEN' % name)
            for p in result['problems']:
                print('      %s' % p)
        else:
            s = result['stats']
            total_links += s['links']
            print('  %-14s OK   docs=%d spine=%d items=%d links=%d anchors=%d'
                  % (name, s['docs'], s['spine'], s['manifest_items'],
                     s['links'], s['anchors']))
    print('')

    tmp = tempfile.mkdtemp(prefix='ff_broken_')
    negatives = [
        ('duplicate id', _make_broken_dupid(os.path.join(tmp, 'dupid.epub')), 'duplicate'),
        ('dangling href', _make_broken_dangling(os.path.join(tmp, 'dangling.epub')),
         'not in archive'),
    ]
    print('Negative controls (must be detected)')
    for label, path, needle in negatives:
        result = audit(path)
        hit = any(needle in p for p in result['problems'])
        print('  %-16s %s' % (label, 'detected' if hit else 'MISSED'))
        if not hit:
            failures.append('negative control: ' + label)
            for p in result['problems']:
                print('      %s' % p)
    print('')

    if failures:
        print('FAILED: %s' % ', '.join(failures))
        return 1
    print('%d fixtures sane, %d links verified, negative controls detected'
          % (len(paths), total_links))
    return 0


if __name__ == '__main__':
    if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
