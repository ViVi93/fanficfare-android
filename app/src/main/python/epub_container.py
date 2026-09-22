#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""Structural editing layer for EPUB files.

This is the ElementTree/stdlib equivalent of the ``container`` object that
calibre's ``ebooks/oeb/polish`` modules are written against. The method names
are deliberately calibre-compatible so the merge/split algorithms port across
with minimal translation.

Design constraints (see the merge/split plan):

* ``remove_item`` and ``insert_spine_item_after`` are the only structural
  mutators. Nothing else may touch ``<manifest>`` or ``<spine>``, so manifest,
  spine, TOC and files cannot drift apart.
* ``commit()`` never writes onto the source path in place: it writes a temp file
  and renames, reusing ``epub_editor``'s atomic write helpers, and preserves the
  OCF invariant that ``mimetype`` is the first entry and stored uncompressed.
* Unchanged files are streamed through rather than buffered, so editing one
  chapter of a 100 MB book does not need 100 MB of RAM.
* ``parsed()`` returns the same object for repeated calls; ``replace()`` is what
  changes a document. Every mutation marks the document dirty, and a document
  that was never replaced is written back byte-for-byte.

A container is a read view of the file on disk. Use it as a context manager::

    with EpubContainer(path) as c:
        c.generate_item('OEBPS/text/new.xhtml', 'application/xhtml+xml')
        c.commit()
"""

import os
import posixpath
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote, unquote

import epub_xml
from epub_editor import _finalize_write, _find_opf_path, _resolve_target
from epub_xml import localname, parse_xhtml, prolog_for_utf8, serialize, split_prolog

__all__ = ['EpubContainer', 'ContainerError', 'OEB_DOCS', 'CSS_TYPES']

#: Media types treated as content documents (link rewriting walks these).
OEB_DOCS = frozenset({
    'application/xhtml+xml',
    'text/html',
    'application/x-dtbook+xml',
    'image/svg+xml',
})

CSS_TYPES = frozenset({'text/css'})

NCX_TYPE = 'application/x-dtbncx+xml'
OPF_TYPE = 'application/oebps-package+xml'

XLINK_HREF = '{%s}href' % epub_xml.XLINK_NS

_CSS_URL_RE = re.compile(r'url\(\s*([\'"]?)([^\'")]+)\1\s*\)')


def rewrite_css_urls(text, replacer):
    """Rewrite every ``url(...)`` in a CSS fragment through ``replacer``."""

    def sub(match):
        quote_char, url = match.group(1), match.group(2)
        return 'url(%s%s%s)' % (quote_char, replacer(url), quote_char)

    return _CSS_URL_RE.sub(sub, text)


_HIERARCHICAL_URL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.\-]*://')
_NON_HIERARCHICAL_SCHEMES = frozenset({
    'mailto', 'tel', 'data', 'urn', 'about', 'blob', 'javascript', 'sms',
})


def is_external_url(url):
    """True for references that cannot name an archive entry.

    Covers ``scheme://...`` URLs, the non-hierarchical schemes above (``mailto:``,
    ``data:`` ...) and protocol-relative ``//host/path`` -- none of which may be
    mistaken for an archive-absolute path. A filename that merely contains a
    colon (``ch1:2.xhtml``) is *not* treated as external.
    """
    if not url:
        return False
    if url.startswith('//'):
        return True
    if _HIERARCHICAL_URL_RE.match(url):
        return True
    name = url.split(':', 1)[0]
    return name.lower() in _NON_HIERARCHICAL_SCHEMES


class ContainerError(Exception):
    """Raised for malformed EPUBs and invalid structural operations."""


class EpubContainer:
    """Manifest/spine/TOC index over an EPUB, with dirty tracking."""

    def __init__(self, epub_path):
        self.path = epub_path
        try:
            self._zip = zipfile.ZipFile(epub_path, 'r')
        except (zipfile.BadZipFile, OSError) as e:
            raise ContainerError('cannot open %r as a zip: %s' % (epub_path, e))

        self._zip_names = list(self._zip.namelist())
        self._name_set = set(self._zip_names)

        opf_name = _find_opf_path(self._zip)
        if not opf_name or opf_name not in self._name_set:
            self._zip.close()
            raise ContainerError('no OPF found in %r' % epub_path)
        self.opf_name = opf_name
        self.opf_dir = posixpath.dirname(opf_name)

        raw = self._zip.read(self.opf_name)
        self._prologs = {self.opf_name: split_prolog(raw)}
        self._trees = {self.opf_name: parse_xhtml(raw)}
        self._opf_root = self._trees[self.opf_name]

        manifest_elem = self._first_child(self._opf_root, 'manifest')
        if manifest_elem is None:
            self._zip.close()
            raise ContainerError('%r has no <manifest>' % self.opf_name)
        self._manifest_elem = manifest_elem
        spine_elem = self._first_child(self._opf_root, 'spine')
        if spine_elem is None:
            self._zip.close()
            raise ContainerError('%r has no <spine>' % self.opf_name)
        self._spine_elem = spine_elem

        self._index_manifest()
        self._spine_items = [e for e in self._spine_elem if localname(e.tag) == 'itemref']

        self._dirty = set()
        self._removed = set()
        self._new_files = {}
        self._id_counter = 0

    # -- construction helpers ---------------------------------------------

    @staticmethod
    def _first_child(root, name):
        for elem in root:
            if localname(elem.tag) == name:
                return elem
        return None

    def _index_manifest(self):
        self._items = [e for e in self._manifest_elem if localname(e.tag) == 'item']
        self._items_by_id = {}
        self._items_by_name = {}
        self.mime_map = {}
        self._properties_by_name = {}
        for item in self._items:
            item_id = item.get('id')
            href = item.get('href')
            media_type = item.get('media-type') or ''
            if not item_id or href is None:
                continue
            zipname = self.href_to_name(href, self.opf_name)
            if zipname is None:
                # A manifest href naming no archive entry (external URL in a
                # broken book): key it by the raw href so it stays addressable
                # instead of landing under a None key.
                zipname = href
            self._items_by_id[item_id] = item
            self._items_by_name[zipname] = item
            self.mime_map[zipname] = media_type
            self._properties_by_name[zipname] = item.get('properties') or ''

    # -- lifecycle --------------------------------------------------------

    def close(self):
        try:
            self._zip.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # -- identity ---------------------------------------------------------

    def exists(self, name):
        return name in self._name_set or name in self._new_files

    def media_type_of(self, name):
        return self.mime_map.get(name, '')

    def content_docs(self):
        """Content documents, in spine order, then any loose ones."""
        seen = set()
        for _itemref, name, _linear in self.spine_iter():
            if name in seen:
                continue
            seen.add(name)
            if self.mime_map.get(name) in OEB_DOCS:
                yield name
        for name, media_type in self.mime_map.items():
            if media_type in OEB_DOCS and name not in seen:
                seen.add(name)
                yield name

    def stylesheets(self):
        """CSS documents in manifest order."""
        for name, media_type in self.mime_map.items():
            if media_type in CSS_TYPES:
                yield name

    def entries(self):
        """Every entry name currently known: original plus added."""
        seen = list(self._zip_names)
        known = set(seen)
        for name in self._new_files:
            if name not in known:
                seen.append(name)
                known.add(name)
        return seen

    def properties_of(self, name):
        """The manifest ``properties`` attribute for an entry ('' if none)."""
        return self._properties_by_name.get(name, '')

    def item_attr(self, name, attr):
        """Any attribute of an entry's manifest ``<item>`` (e.g. media-overlay)."""
        item = self._items_by_name.get(name)
        return item.get(attr) if item is not None else None

    def set_item_attr(self, name, attr, value):
        """Set an attribute on an entry's manifest ``<item>``."""
        item = self._items_by_name.get(name)
        if item is None:
            raise ContainerError('%r is not in the manifest' % name)
        if value is None:
            item.attrib.pop(attr, None)
        else:
            item.set(attr, value)
        if attr == 'properties':
            self._properties_by_name[name] = value or ''
        self.dirty(self.opf_name)

    def item_id_of(self, name):
        item = self._items_by_name.get(name)
        return item.get('id') if item is not None else None

    def name_of(self, item_id):
        item = self._items_by_id.get(item_id)
        if item is None:
            return None
        return self.href_to_name(item.get('href'), self.opf_name)

    def spine_iter(self):
        """Yield ``(itemref_element, zipname, linear)`` in reading order."""
        for itemref in self._spine_items:
            idref = itemref.get('idref')
            name = self.name_of(idref)
            if name is None:
                continue
            linear = (itemref.get('linear') or 'yes').lower() != 'no'
            yield itemref, name, linear

    # -- href math --------------------------------------------------------

    def href_to_name(self, href, base_name):
        """Resolve an href found in ``base_name`` to a zip entry name.

        Fragments and query strings are dropped; percent-escapes are decoded; a
        leading ``/`` is treated as absolute from the archive root (the OCF
        convention). Returns ``None`` for external and protocol-relative
        references, so callers cannot mistake a remote URL for a missing local
        file.
        """
        if not href:
            return base_name
        if is_external_url(href):
            return None
        path = href.split('#', 1)[0].split('?', 1)[0]
        path = unquote(path)
        if not path:
            return base_name
        if path.startswith('/'):
            return posixpath.normpath(path.lstrip('/'))
        base_dir = posixpath.dirname(base_name)
        if not base_dir:
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(base_dir, path))

    def name_to_href(self, name, base_name):
        """Emit an href for ``name`` as seen from the document ``base_name``."""
        base_dir = posixpath.dirname(base_name)
        rel = posixpath.relpath(name, base_dir) if base_dir else name
        return quote(rel, safe='/#')

    # -- documents --------------------------------------------------------

    def raw_data(self, name):
        """Original bytes of an entry."""
        if name in self._new_files:
            return self._new_files[name]
        return self._zip.read(name)

    def parsed(self, name):
        """Parsed document root, cached. Repeated calls return the same object."""
        if name == self.opf_name:
            return self._opf_root
        root = self._trees.get(name)
        if root is not None:
            return root
        raw = self.raw_data(name)
        self._prologs[name] = split_prolog(raw)
        root = parse_xhtml(raw)
        self._trees[name] = root
        return root

    def prolog(self, name):
        """``(header, footer)`` bytes stripped from this document when parsed."""
        if name not in self._prologs:
            self.parsed(name)
        return self._prologs.get(name, (b'', b''))

    def replace(self, name, root):
        """Install a new tree for ``name`` and mark it dirty."""
        if name == self.opf_name:
            self._opf_root = root
        self._trees[name] = root
        self._dirty.add(name)

    def add_file(self, name, data):
        """Add a brand new entry (not yet in the archive)."""
        self._new_files[name] = data
        self._name_set.add(name)
        self._dirty.add(name)

    def dirty(self, name):
        self._dirty.add(name)

    def is_dirty(self, name):
        return name in self._dirty

    # -- link rewriting ---------------------------------------------------

    def replace_links(self, name, replacer):
        """Rewrite every URL reference in a document through ``replacer``.

        Covers ``href``/``src``, SVG ``xlink:href``, inline ``style`` url() and
        ``<style>`` element text. The replacer sees *all* URLs including
        external ones, so it decides what to touch (this is calibre's contract
        too). Returns True when something changed; the
        document is marked dirty only in that case, so an identity replacer
        leaves the bytes untouched.
        """
        root = self.parsed(name)
        changed = False
        for elem in root.iter():
            for attr in ('href', 'src'):
                url = elem.get(attr)
                if url:
                    new = replacer(url)
                    if new != url:
                        elem.set(attr, new)
                        changed = True
            xlink = elem.get(XLINK_HREF)
            if xlink:
                new = replacer(xlink)
                if new != xlink:
                    elem.set(XLINK_HREF, new)
                    changed = True
            style = elem.get('style')
            if style and 'url(' in style:
                new = rewrite_css_urls(style, replacer)
                if new != style:
                    elem.set('style', new)
                    changed = True
            if localname(elem.tag) == 'style' and elem.text and 'url(' in elem.text:
                new = rewrite_css_urls(elem.text, replacer)
                if new != elem.text:
                    elem.text = new
                    changed = True
        if changed:
            self.dirty(name)
        return changed

    # -- manifest / spine mutation ----------------------------------------
    #
    # These two, plus remove_item, are the only operations allowed to touch
    # <manifest> and <spine>, so the indexes and the XML cannot drift apart.

    def _next_item_id(self, prefix='item'):
        while True:
            self._id_counter += 1
            candidate = '%s-%d' % (prefix, self._id_counter)
            if candidate not in self._items_by_id:
                return candidate

    def generate_item(self, zipname, media_type, properties=None, item_id=None):
        """Register a manifest item for the zip entry ``zipname``.

        The argument is a zip entry name, not an href (matching how calibre's
        split code calls it); the href is computed relative to the OPF.
        """
        if zipname in self._items_by_name:
            raise ContainerError('%r is already in the manifest' % zipname)
        if item_id is None:
            item_id = self._next_item_id()
        elif item_id in self._items_by_id:
            raise ContainerError('manifest id %r already exists' % item_id)

        item = ET.SubElement(self._manifest_elem, '{%s}item' % epub_xml.OPF_NS)
        item.set('id', item_id)
        item.set('href', self.name_to_href(zipname, self.opf_name))
        item.set('media-type', media_type)
        if properties:
            item.set('properties', properties)

        self._items.append(item)
        self._items_by_id[item_id] = item
        self._items_by_name[zipname] = item
        self.mime_map[zipname] = media_type
        self._properties_by_name[zipname] = properties or ''
        self.dirty(self.opf_name)
        return item

    def insert_spine_item_after(self, name, new_name, linear=None):
        """Insert a spine itemref for ``new_name`` straight after ``name``.

        ``linear=None`` inherits the source itemref's linearity (calibre's
        behaviour when splitting); pass True/False to force it.
        """
        new_id = self.item_id_of(new_name)
        if new_id is None:
            raise ContainerError('%r is not in the manifest' % new_name)
        source_id = self.item_id_of(name)
        index = None
        for i, itemref in enumerate(self._spine_items):
            if itemref.get('idref') == source_id:
                index = i
                break
        if index is None:
            raise ContainerError('%r is not in the spine' % name)

        source = self._spine_items[index]
        if linear is None:
            linear = (source.get('linear') or 'yes').lower() != 'no'

        itemref = ET.Element('{%s}itemref' % epub_xml.OPF_NS)
        itemref.set('idref', new_id)
        if not linear:
            itemref.set('linear', 'no')

        self._spine_items.insert(index + 1, itemref)
        self._spine_elem.insert(list(self._spine_elem).index(source) + 1, itemref)
        self.dirty(self.opf_name)
        return index + 1

    def _toc_doc_names(self):
        """NCX and EPUB3 nav documents."""
        out = []
        for name, media_type in self.mime_map.items():
            properties = self._properties_by_name.get(name) or ''
            if media_type == NCX_TYPE or 'nav' in properties.split():
                out.append(name)
        return out

    def toc_targets(self):
        """``[(zipname, fragment)]`` for every NCX navPoint and nav link."""
        out = []
        for toc_name in self._toc_doc_names():
            root = self.parsed(toc_name)
            for elem in root.iter():
                local = localname(elem.tag)
                if local == 'content':
                    url = elem.get('src')
                elif local == 'a':
                    url = elem.get('href')
                else:
                    continue
                if not url:
                    continue
                fragment = url.split('#', 1)[1] if '#' in url else ''
                target = self.href_to_name(url, toc_name)
                if target is None:
                    continue        # external link in a nav document
                out.append((target, fragment))
        return out

    def toc_doc_names(self):
        """NCX and EPUB3 nav documents, in manifest order."""
        return self._toc_doc_names()

    def toc_entries(self):
        """``[(label, zipname, fragment)]`` flattened from the TOC, in order.

        Prefers the NCX and falls back to the EPUB3 nav document, so the same
        book does not yield every entry twice.
        """
        toc_names = self._toc_doc_names()
        ncx = [n for n in toc_names if self.media_type_of(n) == NCX_TYPE]
        chosen = ncx or toc_names
        out = []
        for toc_name in chosen:
            root = self.parsed(toc_name)
            for elem in root.iter():
                local = localname(elem.tag)
                if local == 'navPoint':
                    label, url = '', None
                    for child in elem.iter():
                        child_local = localname(child.tag)
                        if not label and child_local == 'text' and child.text:
                            label = child.text.strip()
                        if child_local == 'content' and child.get('src'):
                            url = child.get('src')
                            break
                    if not url:
                        continue
                elif local == 'a':
                    url = elem.get('href')
                    if not url:
                        continue
                    label = ''.join(elem.itertext()).strip()
                else:
                    continue
                fragment = url.split('#', 1)[1] if '#' in url else ''
                target = self.href_to_name(url, toc_name)
                if target is None:
                    continue        # external link in a nav document
                out.append((label or url, target, fragment))
        return out

    def _fix_toc_for_removed(self, removed_name, rebase):
        """Repoint (via ``rebase``) or drop TOC entries for a removed file."""
        for toc_name in self._toc_doc_names():
            if rebase:
                self.replace_links(toc_name, rebase)
            root = self.parsed(toc_name)
            pm = epub_xml.parent_map(root)
            changed = False

            # EPUB2: drop navPoints whose content now dangles.
            contents = [e for e in root.iter() if localname(e.tag) == 'content']
            for content in contents:
                src = content.get('src')
                if not src or self.href_to_name(src, toc_name) != removed_name:
                    continue
                navpoint = pm.get(content)
                holder = pm.get(navpoint) if navpoint is not None else None
                if holder is not None and navpoint in holder:
                    holder.remove(navpoint)
                    changed = True

            # EPUB3: drop the list item, or just the link inside it.
            for li in [e for e in root.iter() if localname(e.tag) == 'li']:
                anchors = [a for a in li if localname(a.tag) == 'a']
                dangling = [a for a in anchors
                            if a.get('href')
                            and self.href_to_name(a.get('href'), toc_name) == removed_name]
                if not dangling:
                    continue
                parent = pm.get(li)
                if parent is None or li not in parent:
                    continue
                if len(dangling) == len(anchors):
                    parent.remove(li)
                    changed = True
                else:
                    for a in dangling:
                        li.remove(a)
                    changed = True

            if changed:
                self.dirty(toc_name)

    def remove_item(self, name, remove_from_spine=True, fix_toc=True, rebase=None):
        """Remove a manifest item, its spine entry, its file and TOC links.

        ``rebase`` is an optional ``url -> url`` callable (same shape as for
        :meth:`replace_links`) used to repoint TOC entries that referenced the
        removed file -- after a merge, point them at the surviving master file
        instead of dropping them. Without it they are dropped.
        """
        item = self._items_by_name.get(name)
        if item is None:
            raise ContainerError('%r is not in the manifest' % name)
        item_id = item.get('id')

        if item in self._manifest_elem:
            self._manifest_elem.remove(item)
        self._items = [i for i in self._items if i is not item]
        self._items_by_id.pop(item_id, None)
        self._items_by_name.pop(name, None)
        self.mime_map.pop(name, None)
        self._properties_by_name.pop(name, None)

        if remove_from_spine and item_id is not None:
            for itemref in list(self._spine_items):
                if itemref.get('idref') != item_id:
                    continue
                self._spine_items.remove(itemref)
                if itemref in self._spine_elem:
                    self._spine_elem.remove(itemref)

        if fix_toc:
            self._fix_toc_for_removed(name, rebase)

        self._removed.add(name)
        self._trees.pop(name, None)
        self._new_files.pop(name, None)
        self._dirty.discard(name)
        self._name_set.discard(name)
        self.dirty(self.opf_name)

    # -- serialization / commit -------------------------------------------

    def _kind_for(self, name):
        media_type = self.mime_map.get(name, '')
        if name == self.opf_name or media_type == OPF_TYPE:
            return epub_xml.OPF
        if media_type == NCX_TYPE:
            return epub_xml.NCX
        return epub_xml.XHTML

    def _serialize_dirty(self):
        """{name: bytes} for every dirty document, prolog re-attached."""
        out = {}
        for name in sorted(self._dirty):
            if name in self._removed:
                continue
            if name in self._new_files and name not in self._trees:
                out[name] = self._new_files[name]
                continue
            root = self._trees.get(name)
            if root is None:
                if name in self._new_files:
                    out[name] = self._new_files[name]
                continue
            header, footer = self._prologs.get(name, (b'', b''))
            kind = self._kind_for(name)
            if header:
                # The declaration must describe the bytes we are about to write.
                header = prolog_for_utf8(header)
                body = serialize(root, kind, xml_declaration=False)
                out[name] = header + body + footer
            else:
                body = serialize(root, kind, xml_declaration=True)
                out[name] = body + footer
        return out

    def added_names(self):
        """Names that exist only in memory (created by this session).

        Keyed off ``_zip_names`` (the entries read from disk), not ``_name_set``,
        because ``add_file`` registers new names there immediately.
        """
        originals = set(self._zip_names)
        candidates = set(self._new_files) | set(self._trees) | set(self._dirty)
        return sorted(n for n in candidates
                      if n not in originals and n not in self._removed)

    def commit(self, output_path=None, backup_suffix=None):
        """Write the container back out.

        In place by default (temp file + atomic rename, optional backup); pass
        ``output_path`` to write a modified copy instead. Returns a result dict
        with ``ok`` -- errors are reported, not raised, matching the convention
        of the rest of the EPUB tooling.
        """
        temp_path = None
        try:
            serialized = self._serialize_dirty()
            target, temp_path, backup_path = _resolve_target(
                self.path, output_path, backup_suffix)
            write_path = temp_path if temp_path else target

            written = 0
            with zipfile.ZipFile(write_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                # OCF: mimetype first and stored uncompressed.
                zout.writestr(zipfile.ZipInfo('mimetype'),
                              b'application/epub+zip', zipfile.ZIP_STORED)
                written += 1

                for name in self._zip_names:
                    if name == 'mimetype' or name in self._removed:
                        continue
                    payload = serialized.get(name)
                    if payload is not None:
                        zout.writestr(name, payload)
                    else:
                        self._copy_entry(zout, name)
                    written += 1

                for name in self.added_names():
                    payload = serialized.get(name)
                    if payload is None:
                        payload = self._new_files.get(name)
                    if payload is None:
                        continue
                    zout.writestr(name, payload)
                    written += 1

            final_path = _finalize_write(target, temp_path, backup_path)
            temp_path = None

            # In-place: the file on disk changed, so re-open the read handle.
            if os.path.abspath(final_path) == os.path.abspath(self.path):
                self._zip.close()
                self._zip = zipfile.ZipFile(self.path, 'r')
                self._zip_names = list(self._zip.namelist())
                self._name_set |= set(self._zip_names)
            self._dirty.clear()

            result = {'ok': True, 'output_path': final_path,
                      'entries_written': written}
            if backup_path:
                result['backup_path'] = backup_path
            return result

        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def _copy_entry(self, zout, name):
        """Stream an unchanged entry, preserving its compression method."""
        info = self._zip.getinfo(name)
        zinfo = zipfile.ZipInfo(name, date_time=info.date_time)
        zinfo.compress_type = info.compress_type
        zinfo.external_attr = info.external_attr
        zinfo.internal_attr = info.internal_attr
        if info.compress_type == zipfile.ZIP_STORED:
            with self._zip.open(name) as src:
                zout.writestr(zinfo, src.read())
            return
        with self._zip.open(name) as src:
            with zout.open(zinfo, 'w') as dst:
                shutil.copyfileobj(src, dst, 1024 * 256)