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
import re

import xml.etree.ElementTree as ET

from epub_container import (NCX_TYPE, OEB_DOCS, ContainerError, EpubContainer)
from epub_xml import DC_NS, NCX_NS, OPF_NS, XHTML_NS, localname, parent_map

__all__ = ['merge_books', 'plan_import', 'import_source', 'ImportPlan',
           'nest_toc', 'ImportPlanError']


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


def _import_properties(src, old_name):
    """Manifest ``properties`` to carry over into the merged book.

    ``cover-image`` is dropped so the base book's cover stays the only declared
    one, and ``nav`` never appears because nav documents are skipped entirely.
    """
    props = [p for p in (src.properties_of(old_name) or '').split()
             if p not in ('cover-image', 'nav')]
    return ' '.join(props) or None


def import_source(base, src, plan):
    """Copy ``src`` into ``base`` per ``plan``. Returns the number of files added.

    Adds files, registers manifest items, rewrites links and appends the source's
    documents to the end of the base spine in reading order.
    """
    added = 0
    spine_docs = set(plan.content_docs)
    item_ids = {}       # source manifest id -> merged manifest id
    for old_name in sorted(plan.name_map):
        new_name = plan.name_map[old_name]
        # A spine document with no usable media type in the source manifest
        # still has to end up in the merged manifest.
        media_type = src.media_type_of(old_name)
        if not media_type:
            media_type = ('application/xhtml+xml' if old_name in spine_docs
                          else 'application/octet-stream')
        base.add_file(new_name, src.raw_data(old_name))
        item = base.generate_item(new_name, media_type,
                                  properties=_import_properties(src, old_name))
        old_id = src.item_id_of(old_name)
        if old_id:
            item_ids[old_id] = item.get('id')
        added += 1

    # second pass: media-overlay is an attribute naming the SMIL item's id, and
    # ids are reassigned on import, so it must be remapped -- or dropped when its
    # target was not imported, rather than left dangling.
    for old_name in list(plan.name_map):
        overlay = src.item_attr(old_name, 'media-overlay')
        if not overlay:
            continue
        base.set_item_attr(plan.name_map[old_name], 'media-overlay',
                           item_ids.get(overlay))

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


def _clear_source_url(root):
    """Drop the story URL the base contributed to the merged metadata.

    A merged book is a new local work, not the base's story. FanFicFare writes the
    story URL as ``<dc:source>`` and a URL-scheme ``<dc:identifier>``, and leaving
    them in made the merged book indistinguishable from its base: the library
    matches a book by URL before its path, so registering the merge found the
    base's existing row, updated it to point at the merged file, and the merged
    book never appeared as an entry of its own.
    """
    parents = parent_map(root)
    removed = 0
    for elem in list(root.iter()):
        if not isinstance(elem.tag, str):
            continue
        tag = localname(elem.tag)
        text = (elem.text or '').strip()
        drop = tag == 'source'
        if tag == 'identifier':
            scheme = ''
            for key, value in elem.attrib.items():
                if localname(key) == 'scheme':
                    scheme = value
            drop = (scheme.upper() == 'URL'
                    or text.startswith('URL:')
                    or text.startswith('http'))
        if drop:
            parent = parents.get(elem)
            if parent is not None:
                parent.remove(elem)
                removed += 1
    return removed > 0


def apply_metadata(base, title=None, author=None):
    """Make the merged book its own: new title/author, and no inherited URL."""
    root = base.parsed(base.opf_name)
    changed = _clear_source_url(root)
    if title:
        _set_dc_element(root, 'title', title)
        changed = True
    if author:
        _set_dc_element(root, 'creator', author)
        changed = True
    if changed:
        base.dirty(base.opf_name)
    return changed


def _unique_id(existing, prefix='section'):
    """An id not already used in the document."""
    n = 0
    while True:
        n += 1
        candidate = '%s-%d' % (prefix, n)
        if candidate not in existing:
            existing.add(candidate)
            return candidate


def _ncx_navpoint(label, src, point_id):
    """A fresh ``<navPoint><navLabel><text/><content src=/></navPoint>``."""
    node = ET.Element('{%s}navPoint' % NCX_NS)
    node.set('id', point_id)
    node.set('playOrder', '0')      # renumbered once the tree is complete
    nav_label = ET.SubElement(node, '{%s}navLabel' % NCX_NS)
    text = ET.SubElement(nav_label, '{%s}text' % NCX_NS)
    text.text = label
    content = ET.SubElement(node, '{%s}content' % NCX_NS)
    content.set('src', src)
    return node


def _nav_list_item(label, href, inner_ol=None):
    """A fresh ``<li><a href="">label</a><ol>…</ol></li>`` for a nav document."""
    item = ET.Element('{%s}li' % XHTML_NS)
    anchor = ET.SubElement(item, '{%s}a' % XHTML_NS)
    anchor.set('href', href)
    anchor.text = label
    if inner_ol is not None:
        item.append(inner_ol)
    return item


def _toc_href(base, toc_name, target):
    """href for a ``(zipname, fragment)`` target as seen from the TOC document."""
    zipname, fragment = target
    href = base.name_to_href(zipname, toc_name)
    return href + ('#' + fragment if fragment else '')


def _first_target(entries, fallback_zipname):
    """``(zipname, fragment)`` of the first TOC entry, else a bare fallback."""
    for _label, zipname, fragment in entries:
        return zipname, fragment
    return fallback_zipname, ''


#: A merged book keeps one title page, from the base. Without this the other
#: sources' front matter lands as stray "Title Page" entries mid-book.
FRONT_MATTER_STEMS = ('titlepage', 'title_page', 'title-page', 'cover')
FRONT_MATTER_LABELS = ('title page', 'titlepage', 'title-page', 'cover')


def _is_front_matter(zipname, label):
    """True for a title page / cover, judged by file name or label."""
    stem = os.path.basename(zipname or '').rsplit('.', 1)[0].lower()
    if any(token in stem for token in FRONT_MATTER_STEMS):
        return True
    return (label or '').strip().lower() in FRONT_MATTER_LABELS


def _same_label(a, b):
    """True when two TOC labels are the same line, ignoring case and spacing."""
    return (a or '').strip().lower() == (b or '').strip().lower()


def _navpoint_label(elem):
    """The ``navLabel/text`` of a navPoint, or an empty string."""
    for child in elem.iter():
        if localname(child.tag) == 'text':
            return child.text or ''
    return ''


def _nav_item_label(elem):
    """The anchor text of a nav ``li``, or an empty string."""
    for child in elem.iter():
        if localname(child.tag) == 'a':
            return child.text or ''
    return ''


def prepare_groups(groups, style='sections'):
    """Clean imported sources' TOC entries before they are nested.

    'flat' mode has no section headers, so a book's name would vanish from the
    contents. Rather than dropping that source's front matter, its title page is
    kept and labelled with the book's name: that page is where the book shows its
    own details, and one annotated page per book is fewer entries than a section
    header plus a separate title page.

    'sections' mode keeps the front matter as it is, under a section named after
    the book. A chapter whose label merely repeats its section's is dropped there,
    since the reader would print the same line twice -- but never when it is the
    section's only entry, or a one-chapter book named after that chapter (as
    FanFicFare writes them) would lose its chapter entirely.
    """
    prepared = []
    for group in groups:
        source = (group.get('label') or '').strip()
        children = list(group.get('children') or [])
        front = [c for c in children if _is_front_matter(c[1], c[0])]

        if style == 'flat':
            # Annotate the title page rather than dropping it: flat mode has no
            # heading, so otherwise the book's name leaves the contents entirely.
            if source:
                children = [tuple([front_matter_label(source, c[0])] + list(c[1:]))
                            if _is_front_matter(c[1], c[0]) else c for c in children]
        else:
            # Promote the book's title page to be the section itself: the section
            # keeps the book's name and its opening page, and the contents lose the
            # separate heading line. The section already points at that page.
            #
            # Front matter is not content, so it must not stop us noticing that the
            # section has no chapters left. A chapter repeating its section's name
            # is dropped only while other content remains -- never the last one, or
            # a one-chapter book named after its chapter would lose it.
            content = [c for c in children if not _is_front_matter(c[1], c[0])]
            repeats = [c for c in content if _same_label(c[0], source)]
            if repeats and len(content) > len(repeats):
                content = [c for c in content if c not in repeats]
            children = content
            if front:
                group = dict(group)
                group['label'] = front_matter_label(source, front[0][0])
                group['target'] = (front[0][1], front[0][2])

        item = dict(group)
        item['children'] = children
        prepared.append(item)
    return prepared


def suggest_toc_style(labels):
    """'flat' when sources look like parts of one work, else 'sections'.

    A set of one-chapter-per-file books (or a book plus its later chapters)
    shares a title prefix, and per-source section headers would just repeat it.
    Unrelated novels in an anthology share nothing, so they want sections.
    """
    titles = [t.strip() for t in (labels or []) if t and t.strip()]
    if len(titles) < 2:
        return 'sections'
    prefix = os.path.commonprefix([t.lower() for t in titles]).strip(' -–—:.,')
    shortest = min(len(t.lower()) for t in titles)
    if shortest and len(prefix) >= 0.6 * shortest:
        return 'flat'
    return 'sections'


#: Leading chapter numbering a label may carry: "Ch. 3", "Chapter 3:", "3.", "IV -".
#: A bare number followed only by a space is deliberately NOT numbering, so a
#: title like "12 Angry Men" survives untouched.
_NUMBERING_RE = re.compile(
    r"""^\s*(?:
        (?:(?:chapter|ch|part|pt|book|vol|volume|episode|ep)\.?)\s*
            (?:\d+|[ivxlcdm]+)\s*[.):\-–—]?\s*
      |
        (?:\d+|[ivxlcdm]+)\s*[.):\-–—]\s*
    )""", re.IGNORECASE | re.VERBOSE)

#: A bare numbering word at the end of a shared prefix ("... Ch").
_NUMBERING_WORD_RE = re.compile(
    r'^(?:chapter|ch|part|pt|book|vol|volume|episode|ep)\.?$', re.IGNORECASE)


def strip_chapter_numbering(label):
    """Remove a leading chapter number, leaving the title itself."""
    return _NUMBERING_RE.sub('', label or '', count=1).strip()


def common_label_prefix(labels, min_chars=4):
    """Longest shared prefix of some TOC labels, cut back to a whole word.

    Returns '' when the labels share nothing worth stripping, so callers can remove
    the result blindly. A trailing numbering word is dropped, so that "... Ch. 00"
    shortens to "Ch. 00" and keeps its number where renumbering can see it.
    """
    texts = [t.strip() for t in (labels or []) if t and t.strip()]
    if len(texts) < 2:
        return ''
    prefix = os.path.commonprefix([t.lower() for t in texts]).strip()
    while prefix and not prefix[-1].isalnum():
        prefix = prefix[:-1]
    if ' ' in prefix:
        prefix = prefix[:prefix.rfind(' ')]
    words = prefix.split()
    if words and _NUMBERING_WORD_RE.match(words[-1]):
        words = words[:-1]
    prefix = ' '.join(words).strip(' .,:;-–—')
    return prefix if len(prefix) >= min_chars else ''


def _navpoint_src(elem):
    """The ``content/@src`` of a navPoint, or an empty string."""
    for child in elem:
        if localname(child.tag) == 'content':
            return child.get('src') or ''
    return ''


def _nav_item_href(elem):
    """The first anchor href inside a nav ``li``, or an empty string."""
    for child in elem.iter():
        if localname(child.tag) == 'a':
            return child.get('href') or ''
    return ''


def front_matter_label(source, label):
    """The label for a book's front matter, carrying the book's name.

    A title page is where the book's own details live, so the book's name is
    attached to it: "The Pilot -- Title Page". Names that are already part of the
    label (or the other way round) are not repeated.
    """
    source = (source or '').strip()
    label = (label or '').strip()
    if not source:
        return label
    if not label or label.lower() in source.lower():
        return source
    if source.lower() in label.lower():
        return label
    return '%s — %s' % (source, label)


def _leaf_entries_ncx(base, toc_name):
    """``(label, href)`` for the NCX's chapter entries, front matter excluded."""
    entries = []
    root = base.parsed(toc_name)
    navmap = next((e for e in root.iter() if localname(e.tag) == 'navMap'), None)
    if navmap is None:
        return entries
    for node in navmap.iter():
        if localname(node.tag) != 'navPoint':
            continue
        if [c for c in node if localname(c.tag) == 'navPoint']:
            continue                        # a section header is not a chapter
        label = _navpoint_label(node)
        href = _navpoint_src(node)
        if _is_front_matter(base.href_to_name(href, toc_name) if href else None, label):
            continue
        entries.append((label, href))
    return entries


def _leaf_entries_nav(base, toc_name):
    """``(label, href)`` for an EPUB3 nav's chapter entries, front matter excluded."""
    entries = []
    root = base.parsed(toc_name)
    nav = next((e for e in root.iter() if localname(e.tag) == 'nav'), None)
    if nav is None:
        return entries
    for item in nav.iter():
        if localname(item.tag) != 'li':
            continue
        if [c for c in item if localname(c.tag) == 'ol']:
            continue
        anchor = next((c for c in item.iter() if localname(c.tag) == 'a'), None)
        if anchor is None:
            continue
        label = anchor.text or ''
        href = anchor.get('href')
        if _is_front_matter(base.href_to_name(href, toc_name) if href else None, label):
            continue
        entries.append((label, href))
    return entries


def _leaf_entries(base):
    """``(label, href)`` for TOC leaves, front matter excluded.

    The NCX mirror is preferred, with an EPUB3 nav as the fallback, so a book that
    has only one of the two is still read correctly. A section header is not a leaf
    and a title page is not a chapter, so neither is counted.
    """
    names = list(base.toc_doc_names())
    for name in names:
        if base.media_type_of(name) == NCX_TYPE:
            entries = _leaf_entries_ncx(base, name)
            if entries:
                return entries
    for name in names:
        if base.media_type_of(name) != NCX_TYPE:
            entries = _leaf_entries_nav(base, name)
            if entries:
                return entries
    return []


def set_chapter_count(base, count=None):
    """Record the merged book's chapter count in its OPF.

    FanFicFare stores this for the books it writes and the app trusts it, but a
    merged book either inherits the base book's number or has none, and with none
    the app falls back to counting TOC entries -- which counts section headers and
    title pages as chapters. So write the real number: TOC leaves, front matter
    excluded.
    """
    root = base.parsed(base.opf_name)
    if count is None:
        count = len(_leaf_entries(base))
    metadata = None
    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        if localname(elem.tag) == 'metadata':
            metadata = elem
        elif localname(elem.tag) == 'meta':
            name = elem.get('name') or ''
            if 'chaptercount' in name.lower():
                elem.set('content', str(count))
                base.dirty(base.opf_name)
                return count
    if metadata is not None:
        meta = ET.SubElement(metadata, '{%s}meta' % OPF_NS)
        meta.set('name', 'chaptercount')
        meta.set('content', str(count))
        base.dirty(base.opf_name)
    return count


def label_prefix_for(base):
    """The prefix this book's chapter labels share, ready to be stripped."""
    return common_label_prefix([label for label, _href in _leaf_entries(base)])


def _relabel(base, toc_name, label, href, has_children, prefix, renumber, counter):
    """The new label for one TOC entry, or None to leave it alone."""
    if has_children:
        return None                     # a section header keeps its own name
    zipname = base.href_to_name(href, toc_name) if href else None
    if _is_front_matter(zipname, label):
        return None                     # front matter is never numbered
    result = label or ''
    if prefix and result.lower().startswith(prefix.lower()):
        remainder = result[len(prefix):].lstrip(' -–—:.,')
        if len(remainder) >= 3:         # never shorten down to "2" or ""
            result = remainder
    if renumber:
        counter[0] += 1
        title = strip_chapter_numbering(result)
        result = '%d. %s' % (counter[0], title) if title else 'Chapter %d' % counter[0]
    return result if result and result != label else None


def _polish_ncx(base, toc_name, prefix, renumber):
    root = base.parsed(toc_name)
    navmap = next((e for e in root.iter() if localname(e.tag) == 'navMap'), None)
    if navmap is None:
        return False
    counter = [0]
    changed = False
    for node in navmap.iter():
        if localname(node.tag) != 'navPoint':
            continue
        children = [c for c in node if localname(c.tag) == 'navPoint']
        new = _relabel(base, toc_name, _navpoint_label(node), _navpoint_src(node),
                       bool(children), prefix, renumber, counter)
        if new is None:
            continue
        for child in node.iter():
            if localname(child.tag) == 'text':
                child.text = new
                changed = True
                break
    if changed:
        base.dirty(toc_name)
    return changed


def _polish_nav(base, toc_name, prefix, renumber):
    root = base.parsed(toc_name)
    nav = next((e for e in root.iter() if localname(e.tag) == 'nav'), None)
    if nav is None:
        return False
    counter = [0]
    changed = False
    for item in nav.iter():
        if localname(item.tag) != 'li':
            continue
        anchor = next((c for c in item.iter() if localname(c.tag) == 'a'), None)
        if anchor is None:
            continue
        children = [c for c in item if localname(c.tag) == 'ol']
        new = _relabel(base, toc_name, anchor.text, anchor.get('href'),
                       bool(children), prefix, renumber, counter)
        if new is None:
            continue
        anchor.text = new
        changed = True
    if changed:
        base.dirty(toc_name)
    return changed


def polish_labels(base, prefix='', renumber=False):
    """Rewrite leaf TOC labels: shorten a shared prefix, then number the chapters.

    Leaves only, so a sectioned merge keeps each source's name while the chapters
    underneath are tidied, and front matter is left alone. Every mirror is walked
    in the same order, so an NCX and an EPUB3 nav end up matching.

    ``prefix`` is stripped from every label that starts with it; pass '' to skip
    shortening. Use ``label_prefix_for`` to work it out from the book itself.
    ``renumber`` writes "N. Title", or "Chapter N" for a label that was only a
    number.
    """
    if not prefix and not renumber:
        return False
    changed = False
    for name in base.toc_doc_names():
        if base.media_type_of(name) == NCX_TYPE:
            changed = _polish_ncx(base, name, prefix, renumber) or changed
        else:
            changed = _polish_nav(base, name, prefix, renumber) or changed
    return changed


def _nest_ncx(base, toc_name, base_label, base_target, groups, style='sections'):
    """Nest source TOC entries in an NCX: one section each, or one flat list."""
    root = base.parsed(toc_name)
    navmap = None
    for elem in root.iter():
        if localname(elem.tag) == 'navMap':
            navmap = elem
            break
    if navmap is None:
        return 0

    existing_ids = {e.get('id') for e in root.iter() if e.get('id')}
    existing_children = [c for c in list(navmap) if localname(c.tag) == 'navPoint']
    added = 0

    if style == 'flat':
        # No section headers: the sources' entries join one flat chapter list.
        for group in groups:
            for label, zipname, fragment in group['children']:
                navmap.append(_ncx_navpoint(
                    label, _toc_href(base, toc_name, (zipname, fragment)),
                    _unique_id(existing_ids, 'point')))
                added += 1
    else:
        # Promote the base book's own title page to be the section, as imported
        # sources are: it carries the book's name, and the contents lose the
        # separate heading line. The section already points at that page.
        if existing_children and _is_front_matter(
                base.href_to_name(_navpoint_src(existing_children[0]), toc_name),
                _navpoint_label(existing_children[0])):
            first = existing_children.pop(0)
            navmap.remove(first)
            base_label = front_matter_label(base_label, _navpoint_label(first))

        # A child repeating the section's label and target would print the same
        # line twice.
        if existing_children and _same_label(_navpoint_label(existing_children[0]),
                                             base_label):
            navmap.remove(existing_children.pop(0))

        section = _ncx_navpoint(base_label, _toc_href(base, toc_name, base_target),
                                _unique_id(existing_ids))
        for child in existing_children:
            navmap.remove(child)
            section.append(child)
        navmap.append(section)
        added = 1

        for group in groups:
            parent = _ncx_navpoint(group['label'],
                                   _toc_href(base, toc_name, group['target']),
                                   _unique_id(existing_ids))
            for label, zipname, fragment in group['children']:
                parent.append(_ncx_navpoint(label,
                                            _toc_href(base, toc_name, (zipname, fragment)),
                                            _unique_id(existing_ids, 'point')))
            navmap.append(parent)
            added += 1

    play_order = 0
    for elem in root.iter():
        if localname(elem.tag) == 'navPoint':
            play_order += 1
            elem.set('playOrder', str(play_order))

    base.dirty(toc_name)
    return added


def _nest_nav(base, toc_name, base_label, base_target, groups, style='sections'):
    """Mirror the NCX nesting into an EPUB3 nav document."""
    root = base.parsed(toc_name)
    nav = ol = None
    for elem in root.iter():
        if localname(elem.tag) == 'nav':
            nav = elem
            break
    if nav is None:
        return 0
    for child in nav:
        if localname(child.tag) == 'ol':
            ol = child
            break
    if ol is None:
        return 0

    existing_items = [c for c in list(ol) if localname(c.tag) == 'li']
    added = 0

    if style == 'flat':
        for group in groups:
            for label, zipname, fragment in group['children']:
                ol.append(_nav_list_item(label,
                                         _toc_href(base, toc_name, (zipname, fragment))))
                added += 1
    else:
        # Same reasoning as the NCX: the base book's title page becomes the
        # section, and a child repeating the section is dropped.
        if existing_items and _is_front_matter(
                base.href_to_name(_nav_item_href(existing_items[0]), toc_name),
                _nav_item_label(existing_items[0])):
            first = existing_items.pop(0)
            ol.remove(first)
            base_label = front_matter_label(base_label, _nav_item_label(first))

        if existing_items and _same_label(_nav_item_label(existing_items[0]), base_label):
            ol.remove(existing_items.pop(0))

        inner = ET.Element('{%s}ol' % XHTML_NS)
        for item in existing_items:
            ol.remove(item)
            inner.append(item)
        ol.append(_nav_list_item(base_label,
                                 _toc_href(base, toc_name, base_target),
                                 inner if len(inner) else None))
        added = 1

        for group in groups:
            inner = ET.Element('{%s}ol' % XHTML_NS)
            for label, zipname, fragment in group['children']:
                inner.append(_nav_list_item(label,
                                            _toc_href(base, toc_name, (zipname, fragment))))
            ol.append(_nav_list_item(group['label'],
                                     _toc_href(base, toc_name, group['target']),
                                     inner if len(inner) else None))
            added += 1

    base.dirty(toc_name)
    return added


def nest_toc(base, groups, base_label=None, base_target=None, style='sections'):
    """Rewrite the merged book's TOC, mirroring NCX and nav.

    ``groups`` is one dict per imported source, in spine order:
    ``{'label': str, 'target': (zipname, fragment), 'children': [(label, zipname,
    fragment), ...]}``.

    ``style='sections'`` wraps each source in a section of its own (the
    ``anthology_merge_keepsingletocs`` shape). ``style='flat'`` omits the section
    headers so every chapter joins one list, which is what a set of
    one-chapter-per-file books wants. Returns the number of entries added to each
    TOC document (sections, in sections mode).
    """
    base_label = base_label or _title_of(base) or 'Part 1'
    if base_target is None:
        entries = base.toc_entries()
        fallback = next((name for _r, name, _l in base.spine_iter()), base.opf_name)
        base_target = _first_target(entries, fallback)

    groups = prepare_groups(groups, style)
    toc_names = base.toc_doc_names()
    ncx_names = [n for n in toc_names if base.media_type_of(n) == NCX_TYPE]
    nav_names = [n for n in toc_names if n not in ncx_names]

    added = 0
    for name in ncx_names:
        added += _nest_ncx(base, name, base_label, base_target, groups, style)
    for name in nav_names:
        added += _nest_nav(base, name, base_label, base_target, groups, style)
    return added


#: Characters that cannot appear in a file name on any supported filesystem.
_FILENAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _title_filename(title):
    """A filesystem-safe file stem for a book title, or '' if there is none."""
    cleaned = _FILENAME_BAD.sub('', (title or '').replace('\n', ' ')).strip(' .')
    return cleaned[:120]


def default_output_path(base_path, title=None):
    """Where a merge writes: beside the base book, named after the merged title.

    Naming the file after the title keeps it identifiable in a library or reader
    that lists files by name; when there is no title the base book's own name is
    used with a `` (merged)`` suffix.
    """
    directory = os.path.dirname(base_path)
    stem = _title_filename(title)
    if stem:
        return os.path.join(directory, stem + '.epub')
    root, ext = os.path.splitext(base_path)
    return '%s (merged)%s' % (root, ext or '.epub')


def _non_clobbering(path, sources):
    """A path that is not one of ``sources``: a merge never overwrites a source.

    A title can collide with a source's file name (merging a book into its own
    title, say), so fall back to a numbered name rather than trusting it.
    """
    taken = {os.path.abspath(p) for p in (sources or []) if p}
    candidate = path
    counter = 1
    while os.path.abspath(candidate) in taken:
        root, ext = os.path.splitext(path)
        counter += 1
        candidate = '%s (%d)%s' % (root, counter, ext)
    return candidate


def _author_of(container):
    """dcterms creator of a container, or ''."""
    try:
        root = container.parsed(container.opf_name)
    except Exception:
        return ''
    for elem in root.iter():
        if elem.tag == '{%s}creator' % DC_NS and elem.text and elem.text.strip():
            return elem.text.strip()
    return ''


#: Warn above this combined source size, refuse above the hard cap: the merged
#: book is written entirely on the device and a runaway merge would fill storage.
MERGE_WARN_BYTES = 100 * 1024 * 1024
MERGE_MAX_BYTES = 1024 * 1024 * 1024


def preview_merge(epub_paths, base_index=0):
    """Summarise a proposed merge without writing anything.

    Used by the confirmation screen so the user can see what will be combined
    (and reorder it) before anything is written.
    """
    paths = [p for p in (epub_paths or []) if p]
    if len(paths) < 2:
        return {'ok': False,
                'error': 'merging needs at least two EPUBs (got %d)' % len(paths)}
    if not 0 <= base_index < len(paths):
        return {'ok': False, 'error': 'base_index %r is out of range' % (base_index,)}

    warnings = []
    sources = []
    opened = []
    try:
        for index, path in enumerate(paths):
            try:
                container = EpubContainer(path)
            except ContainerError as e:
                return {'ok': False, 'error': 'source %d: %s' % (index + 1, e)}
            opened.append(container)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            sources.append({
                'index': index,
                'path': path,
                'title': _title_of(container) or os.path.basename(path),
                'author': _author_of(container),
                'chapters': len([n for _r, n, _l in container.spine_iter()]),
                'toc_entries': len(container.toc_entries()),
                'labels': [label for label, name, _f in container.toc_entries()
                           if not _is_front_matter(name, label)],
                'has_toc': bool(container.toc_doc_names()),
                'size_bytes': size,
                'is_base': index == base_index,
            })

        # The labels the sources already carry: if they share a long prefix, a
        # merged chapter list would repeat it on every line.
        chapter_labels = [label for s in sources for label in s['labels']]
        total = sum(s['size_bytes'] for s in sources)
        if not any(s['has_toc'] for s in sources):
            warnings.append('No source has a table of contents, so the merged '
                            'book will have none either.')
        elif not sources[base_index]['has_toc']:
            warnings.append('The first book has no table of contents, so the '
                            'merged book will not get one.')
        if total >= MERGE_WARN_BYTES:
            warnings.append('Combined sources are %d MB; merging will take a '
                            'while and produce a large book.' % (total // (1024 * 1024)))
        if total >= MERGE_MAX_BYTES:
            warnings.append('Combined sources exceed the %d MB limit.'
                            % (MERGE_MAX_BYTES // (1024 * 1024)))

        return {
            'ok': True,
            'sources': sources,
            'source_count': len(sources),
            'chapters': sum(s['chapters'] for s in sources),
            'toc_entries': sum(s['toc_entries'] for s in sources),
            'estimated_bytes': total,
            'too_large': total >= MERGE_MAX_BYTES,
            'warnings': warnings,
            'default_title': sources[base_index]['title'],
            'default_author': sources[base_index]['author'],
            'suggested_toc_style': suggest_toc_style([s['title'] for s in sources]),
            'suggested_shorten_labels': bool(common_label_prefix(chapter_labels)),
        }
    finally:
        for container in opened:
            container.close()


def merge_books(epub_paths, output_path=None, title=None, author=None,
                base_index=0, toc_style='sections', shorten_labels=False,
                renumber_chapters=False):
    """Merge two or more EPUBs into one book.

    ``base_index`` selects which source provides the metadata and cover. The
    result is written to ``output_path``, or to a ``... (merged).epub`` file
    beside the base book -- **never** over a source. ``toc_style`` is 'sections'
 (a section per source) or 'flat' (one chapter list, no section headers).
 ``shorten_labels`` strips the prefix the chapter labels share, and
 ``renumber_chapters`` numbers them in reading order. Returns a result dict.
    """
    paths = [p for p in (epub_paths or []) if p]
    if len(paths) < 2:
        return {'ok': False,
                'error': 'merging needs at least two EPUBs (got %d)' % len(paths)}
    if not 0 <= base_index < len(paths):
        return {'ok': False, 'error': 'base_index %r is out of range' % (base_index,)}

    total_bytes = 0
    for path in paths:
        try:
            total_bytes += os.path.getsize(path)
        except OSError:
            pass
    if total_bytes >= MERGE_MAX_BYTES:
        return {'ok': False,
                'error': 'sources total %d MB, above the %d MB merge limit'
                         % (total_bytes // (1024 * 1024),
                            MERGE_MAX_BYTES // (1024 * 1024))}

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

        spine_names = [name for _r, name, _l in base.spine_iter()]
        spine_before = len(spine_names)
        base_target = _first_target(base.toc_entries(),
                                    spine_names[0] if spine_names else base.opf_name)
        entries_added = 0
        warnings = []
        imported = 0
        groups = []

        for n, (i, src) in enumerate(others, start=1):
            plan = plan_import(base, src, n)
            if not plan.spine:
                warnings.append('source %d has no spine documents; skipped' % i)
                continue
            entries_added += import_source(base, src, plan)
            imported += 1
            children = [(label, plan.name_map[target], fragment)
                        for label, target, fragment in plan.toc]
            first_doc = plan.name_map[plan.spine[0][0]]
            groups.append({
                'label': plan.source_title,
                'target': _first_target(children, first_doc),
                'children': children,
            })

        if not imported:
            return {'ok': False, 'error': 'no source had anything to merge'}

        # The base book's section is its own title page, so it is named with the
        # base book's own title -- the same way every imported book is named with
        # its own. Read it before apply_metadata overwrites the OPF with the title
        # the user typed, which names the merged book rather than this section.
        base_book_title = _title_of(base)
        apply_metadata(base, title, author)
        toc_sections = nest_toc(base, groups, base_label=base_book_title or None,
                                base_target=base_target, style=toc_style)
        # Labels last, so every chapter is numbered in final reading order.
        polish_labels(base, label_prefix_for(base) if shorten_labels else '',
                      renumber_chapters)
        # Count what the contents actually holds, so the library shows the real
        # number instead of the base book's or a count including title pages.
        chapter_count = set_chapter_count(base)

        target = output_path or _non_clobbering(
            default_output_path(paths[base_index], title), paths)
        result = base.commit(output_path=target)
        if not result.get('ok'):
            return result

        result.update({
            'sources_merged': imported + 1,
            'entries_added': entries_added,
            'spine_before': spine_before,
            'spine_after': len(list(base.spine_iter())),
            'toc_sections': toc_sections,
            'toc_style': toc_style,
            'chapters': chapter_count,
            'shorten_labels': bool(shorten_labels),
            'renumber_chapters': bool(renumber_chapters),
            'warnings': warnings,
        })
        return result

    except ContainerError as e:
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
    finally:
        for container in opened:
            container.close()
