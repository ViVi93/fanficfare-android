#!/usr/bin/env python3
# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""Merge several EPUB files into a single book.

Used for building one book out of per-chapter EPUBs, and for joining the parts
of an anthology. Built on :mod:`epub_container`.

Design notes
------------

* The **first source is the base**: its OPF, metadata and cover are the template
  for the merged book, and its own files keep their original paths. Everything
  imported from the other sources is namespaced under ``merged/<n>/`` so two
  sources can both contain ``OEBPS/images/pic.png`` without clashing.
* Every source document keeps its **own file** in the merged book, so duplicate
  ``id`` values across documents are legal (only duplicates *within* a document
  are invalid). Book-level merging therefore needs no anchor renaming -- unlike
  merging chapter files into one file, which does.
* Links are rewritten by resolving each URL against the **source** layout and
  re-emitting it relative to the new document. URLs that do not point at
  something we imported (external links, or items deliberately skipped) are left
  untouched.
* Sources are opened read-only and never modified; the merged book is written to
  a new file.
"""

import os

import xml.etree.ElementTree as ET

from epub_container import (NCX_TYPE, OEB_DOCS, ContainerError, EpubContainer)
from epub_xml import DC_NS, localname

__all__ = ['merge_books', 'plan_import', 'import_source', 'ImportPlan',
           'ImportPlanError']


class ImportPlanError(ContainerError):
    """Raised when a source cannot be imported into the merged book."""


class ImportPlan:
    """How one source EPUB's files map into the merged book."""

    def __init__(self, index, prefix, source_title):
        self.index = index
        self.prefix = prefix
        self.source_title = source_title or 'Part %d' % index
        self.name_map = {}       # old zipname -> new zipname
        self.spine = []          # [(old_name, linear)] in reading order
        self.toc = []            # [(label, old_name, fragment)] from the source TOC
        self.skipped = []        # source entries deliberately not imported

    @property
    def content_docs(self):
        return [old for old, _linear in self.spine]

    def new_name(self, old_name):
        return self.name_map.get(old_name)

    def __repr__(self):
        return '<ImportPlan #%d %s files=%d spine=%d toc=%d>' % (
            self.index, self.prefix, len(self.name_map), len(self.spine),
            len(self.toc))


def _title_of(container):
    """dcterms title of a container, or ''."""
    try:
        root = container.parsed(container.opf_name)
    except Exception:
        return ''
    for elem in root.iter():
        if elem.tag == '{%s}title' % DC_NS and elem.text and elem.text.strip():
            return elem.text.strip()
    return ''


def _clean_prefix(base, index, prefix=None):
    """A ``merged/<n>/`` prefix guaranteed not to collide with existing entries."""
    candidate = prefix or 'merged/%d/' % index
    existing = base.entries()
    bump = 0
    while any(name.startswith(candidate) for name in existing):
        bump += 1
        candidate = 'merged/%d-%d/' % (index, bump)
    return candidate


def plan_import(base, src, index, prefix=None):
    """Work out how ``src`` maps into ``base`` (pure: does not mutate either).

    Every manifest item is imported except the source's OPF, its NCX and its
    EPUB3 nav document -- those are replaced by the merged book's own. Cover
    images *are* imported: a source titlepage commonly links to its cover, and
    dropping it would leave a dangling reference.
    """
    plan = ImportPlan(index, _clean_prefix(base, index, prefix), _title_of(src))

    skip = {src.opf_name}
    for name in src.mime_map:
        properties = src.properties_of(name)
        if src.media_type_of(name) == NCX_TYPE or 'nav' in properties.split():
            skip.add(name)

    for name in src.mime_map:
        if name in skip:
            plan.skipped.append(name)
        else:
            plan.name_map[name] = plan.prefix + name

    for _itemref, name, linear in src.spine_iter():
        plan.spine.append((name, linear))
        if name not in plan.name_map:
            # A spine document the manifest does not describe properly: import
            # it anyway rather than dropping it from the reading order.
            plan.name_map[name] = plan.prefix + name

    for label, target, fragment in src.toc_entries():
        if target in plan.name_map:
            plan.toc.append((label, target, fragment))

    return plan


def _make_rewriter(base, src, plan, old_doc, new_doc):
    """A ``url -> url`` callable that re-points one source document's links."""

    def rewrite(url):
        if not url or url.startswith('#'):
            # Pure fragment: stays inside the same document.
            return url
        target = src.href_to_name(url, old_doc)
        new_target = plan.new_name(target)
        if new_target is None:
            # External, or something we deliberately did not import.
            return url
        fragment = url.split('#', 1)[1] if '#' in url else ''
        href = base.name_to_href(new_target, new_doc)
        return href + ('#' + fragment if fragment else '')

    return rewrite


def _last_spine_name(container):
    names = [name for _ref, name, _linear in container.spine_iter()]
    if not names:
        raise ImportPlanError('the base book has an empty spine')
    return names[-1]


def import_source(base, src, plan):
    """Copy ``src`` into ``base`` per ``plan``. Returns the number of files added.

    Adds files, registers manifest items, rewrites links and appends the source's
    documents to the end of the base spine in reading order.
    """
    added = 0
    spine_docs = set(plan.content_docs)
    for old_name in sorted(plan.name_map):
        new_name = plan.name_map[old_name]
        # A spine document with no usable media type in the source manifest
        # still has to end up in the merged manifest.
        media_type = src.media_type_of(old_name)
        if not media_type:
            media_type = ('application/xhtml+xml' if old_name in spine_docs
                          else 'application/octet-stream')
        base.add_file(new_name, src.raw_data(old_name))
        base.generate_item(new_name, media_type)
        added += 1

    for old_doc, _linear in plan.spine:
        new_doc = plan.name_map[old_doc]
        if base.media_type_of(new_doc) not in OEB_DOCS:
            continue
        base.replace_links(new_doc, _make_rewriter(base, src, plan, old_doc, new_doc))

    tail = _last_spine_name(base)
    for old_doc, linear in plan.spine:
        new_doc = plan.name_map[old_doc]
        base.insert_spine_item_after(tail, new_doc, linear=linear)
        tail = new_doc

    return added


def _set_dc_element(root, tag, value):
    """Set (or create) a dc:<tag> element's text in an OPF tree."""
    metadata = None
    for elem in root:
        if localname(elem.tag) == 'metadata':
            metadata = elem
            break
    if metadata is None:
        raise ImportPlanError('the base OPF has no <metadata>')
    qualified = '{%s}%s' % (DC_NS, tag)
    target = None
    for elem in metadata.iter(qualified):
        target = elem
        break
    if target is None:
        target = ET.SubElement(metadata, qualified)
    target.text = value
    return target


def apply_metadata(base, title=None, author=None):
    """Override the merged book's title/author. Base metadata wins otherwise."""
    if not title and not author:
        return False
    root = base.parsed(base.opf_name)
    changed = False
    if title:
        _set_dc_element(root, 'title', title)
        changed = True
    if author:
        _set_dc_element(root, 'creator', author)
        changed = True
    if changed:
        base.dirty(base.opf_name)
    return changed


def default_output_path(base_path):
    """A ``... (merged).epub`` path next to the base book."""
    root, ext = os.path.splitext(base_path)
    return '%s (merged)%s' % (root, ext or '.epub')


def merge_books(epub_paths, output_path=None, title=None, author=None,
                base_index=0):
    """Merge two or more EPUBs into one book.

    ``base_index`` selects which source provides the metadata and cover. The
    result is written to ``output_path``, or to a ``... (merged).epub`` file
    beside the base book -- **never** over a source. Returns a result dict.
    """
    paths = [p for p in (epub_paths or []) if p]
    if len(paths) < 2:
        return {'ok': False,
                'error': 'merging needs at least two EPUBs (got %d)' % len(paths)}
    if not 0 <= base_index < len(paths):
        return {'ok': False, 'error': 'base_index %r is out of range' % (base_index,)}

    opened = []
    try:
        base = EpubContainer(paths[base_index])
        opened.append(base)

        others = []
        for i, path in enumerate(paths):
            if i == base_index:
                continue
            container = EpubContainer(path)
            opened.append(container)
            others.append((i, container))

        spine_before = len(list(base.spine_iter()))
        entries_added = 0
        warnings = []
        imported = 0

        for n, (i, src) in enumerate(others, start=1):
            plan = plan_import(base, src, n)
            if not plan.spine:
                warnings.append('source %d has no spine documents; skipped' % i)
                continue
            entries_added += import_source(base, src, plan)
            imported += 1

        if not imported:
            return {'ok': False, 'error': 'no source had anything to merge'}

        apply_metadata(base, title, author)

        target = output_path or default_output_path(paths[base_index])
        result = base.commit(output_path=target)
        if not result.get('ok'):
            return result

        result.update({
            'sources_merged': imported + 1,
            'entries_added': entries_added,
            'spine_before': spine_before,
            'spine_after': len(list(base.spine_iter())),
            'warnings': warnings,
        })
        return result

    except ContainerError as e:
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
    finally:
        for container in opened:
            container.close()
