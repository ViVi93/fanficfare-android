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
import zipfile
from urllib.parse import quote, unquote

import epub_xml
from epub_editor import _finalize_write, _find_opf_path, _resolve_target
from epub_xml import localname, parse_xhtml, serialize, split_prolog

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

        Fragments and query strings are dropped; percent-escapes are decoded;
        a leading ``/`` is treated as absolute from the archive root (the OCF
        convention).
        """
        if not href:
            return base_name
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