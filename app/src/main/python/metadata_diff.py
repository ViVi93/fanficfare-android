# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
"""Metadata diff engine for FanFicFare Android.

Compares two metadata dictionaries (as produced by ``epub_editor.read_metadata_fields``)
and produces a deterministic, structured description of what changed.

This module:
  * Does NOT read or write EPUB files.
  * Does NOT perform network requests.
  * Does NOT normalize values — comparison is exact (see ``metadata_normalizer``
    for normalization, which is a separate responsibility).
  * Does NOT modify its input objects.

Intended for the future BookPrep-style before/after metadata diff view.
"""

import copy


# ---------------------------------------------------------------------------
# Deterministic field ordering
# ---------------------------------------------------------------------------
# Fields are ordered to match the natural reading order of the metadata model
# (as returned by ``read_metadata_fields``) plus identifiers (which is a dict).
# This ensures the diff output is always in the same order regardless of
# dict insertion order in the inputs.

_SCALAR_FIELDS = [
    'title',
    'subtitle',
    'publisher',
    'description',
    'series',
    'series_index',
    'rating',
    'isbn',
    'pubdate',
    'rights',
]

# Lists of strings (compared with add/remove detection).
_LIST_FIELDS = [
    'authors',
    'languages',
    'tags',
]

# List of dicts (contributors: [{'name': str, 'role': str, 'file_as': str}]).
# Compared as an ordered list with per-item change detection.
_DICT_LIST_FIELDS = [
    'contributors',
]

_DICT_FIELDS = [
    'identifiers',
]

# A field that is empty (missing key, None, or empty string/container) is
# considered "absent" for diff purposes.
def _is_empty(value):
    """Return True if *value* should be treated as absent/empty."""
    if value is None:
        return True
    if isinstance(value, str) and value == '':
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def diff_metadata(before, after):
    """Compare two metadata dictionaries and return a structured diff.

    Parameters
    ----------
    before : dict
        The original / "before" metadata state.  Not modified.
    after : dict
        The edited / "after" metadata state.  Not modified.

    Returns
    -------
    dict
        A dictionary with the following structure::

            {
                'changed': bool,          # True if any difference was found
                'changes': [
                    {
                        'field': str,
                        'change_type': 'added' | 'removed' | 'changed' | 'unchanged',
                        'before': <value or None>,
                        'after': <value or None>,
                    },
                    ...
                ],
                'summary': {
                    'added': int,
                    'removed': int,
                    'changed': int,
                },
            }

        Only fields that have actually changed are included in ``changes``
        (i.e. unchanged fields are omitted by default).

    The ``before`` and ``after`` values in each change record are **deep copies**
    of the corresponding input values, so the caller can safely hold references
    to them without worrying about aliasing the inputs.
    """
    # Work on deep copies so the inputs are never mutated.
    b = copy.deepcopy(before) if not isinstance(before, dict) else copy.deepcopy(before)
    a = copy.deepcopy(after) if not isinstance(after, dict) else copy.deepcopy(after)

    changes = []

    # --- Scalar fields -------------------------------------------------------
    for field in _SCALAR_FIELDS:
        b_val = b.get(field)
        a_val = a.get(field)

        b_empty = _is_empty(b_val)
        a_empty = _is_empty(a_val)

        if b_empty and a_empty:
            # Both absent — no change (field not even reported).
            continue

        if b_empty and not a_empty:
            changes.append({
                'field': field,
                'change_type': 'added',
                'before': None,
                'after': copy.deepcopy(a_val),
            })
            continue

        if not b_empty and a_empty:
            changes.append({
                'field': field,
                'change_type': 'removed',
                'before': copy.deepcopy(b_val),
                'after': None,
            })
            continue

        # Both non-empty.
        if b_val != a_val:
            changes.append({
                'field': field,
                'change_type': 'changed',
                'before': copy.deepcopy(b_val),
                'after': copy.deepcopy(a_val),
            })

    # --- List fields ---------------------------------------------------------
    for field in _LIST_FIELDS:
        b_list = b.get(field) or []
        a_list = a.get(field) or []

        if b_list == a_list:
            continue

        # Determine added/removed items (exact, order-aware comparison).
        added_items = _list_added(b_list, a_list)
        removed_items = _list_removed(b_list, a_list)

        # If both added and removed are non-empty and total deltas equal,
        # it might be a pure reorder — report as 'changed' with the lists.
        is_reorder = (
            len(added_items) > 0
            and len(removed_items) > 0
            and len(added_items) == len(removed_items)
            and _is_reorder(b_list, a_list)
        )

        if is_reorder:
            changes.append({
                'field': field,
                'change_type': 'changed',
                'before': copy.deepcopy(b_list),
                'after': copy.deepcopy(a_list),
            })
        else:
            changes.append({
                'field': field,
                'change_type': 'changed',
                'before': copy.deepcopy(b_list),
                'after': copy.deepcopy(a_list),
                'added': [copy.deepcopy(x) for x in added_items],
                'removed': [copy.deepcopy(x) for x in removed_items],
            })

    # --- Dict-list fields (e.g. contributors) -------------------------------
    for field in _DICT_LIST_FIELDS:
        b_list = b.get(field) or []
        a_list = a.get(field) or []

        if b_list == a_list:
            continue

        # Per-item comparison: detect added/removed items and changed fields
        # within items that exist in both lists (matched by position).
        added_items = []
        removed_items = []
        item_changes = []
        max_len = max(len(b_list), len(a_list))
        for i in range(max_len):
            b_item = b_list[i] if i < len(b_list) else None
            a_item = a_list[i] if i < len(a_list) else None
            if b_item is None:
                added_items.append(copy.deepcopy(a_item))
            elif a_item is None:
                removed_items.append(copy.deepcopy(b_item))
            elif b_item != a_item:
                # Item at this position changed — record field-level diffs.
                if isinstance(b_item, dict) and isinstance(a_item, dict):
                    all_keys = set(b_item.keys()) | set(a_item.keys())
                    field_diffs = []
                    for k in sorted(all_keys):
                        bv = b_item.get(k)
                        av = a_item.get(k)
                        if bv != av:
                            field_diffs.append({
                                'key': k,
                                'before': copy.deepcopy(bv),
                                'after': copy.deepcopy(av),
                            })
                    if field_diffs:
                        item_changes.append({
                            'index': i,
                            'before': copy.deepcopy(b_item),
                            'after': copy.deepcopy(a_item),
                            'field_diffs': field_diffs,
                        })
                else:
                    item_changes.append({
                        'index': i,
                        'before': copy.deepcopy(b_item),
                        'after': copy.deepcopy(a_item),
                    })

        change_record = {
            'field': field,
            'change_type': 'changed',
            'before': copy.deepcopy(b_list),
            'after': copy.deepcopy(a_list),
        }
        if added_items:
            change_record['added'] = added_items
        if removed_items:
            change_record['removed'] = removed_items
        if item_changes:
            change_record['item_changes'] = item_changes
        changes.append(change_record)

    # --- Dict fields (e.g. identifiers) -------------------------------------
    for field in _DICT_FIELDS:
        b_dict = b.get(field) or {}
        a_dict = a.get(field) or {}

        if b_dict == a_dict:
            continue

        added_keys = [(k, copy.deepcopy(v)) for k, v in a_dict.items() if k not in b_dict]
        removed_keys = [(k, copy.deepcopy(v)) for k, v in b_dict.items() if k not in a_dict]
        changed_keys = [
            (k, copy.deepcopy(b_dict[k]), copy.deepcopy(a_dict[k]))
            for k in b_dict
            if k in a_dict and b_dict[k] != a_dict[k]
        ]

        changes.append({
            'field': field,
            'change_type': 'changed',
            'before': copy.deepcopy(b_dict),
            'after': copy.deepcopy(a_dict),
            'added_keys': added_keys,
            'removed_keys': removed_keys,
            'changed_keys': changed_keys,
        })

    # --- Any extra fields not covered by the canonical lists ----------------
    all_keys = set(b.keys()) | set(a.keys())
    known_keys = set(_SCALAR_FIELDS) | set(_LIST_FIELDS) | set(_DICT_FIELDS) | set(_DICT_LIST_FIELDS)
    extra_keys = sorted(all_keys - known_keys)
    for field in extra_keys:
        b_val = b.get(field)
        a_val = a.get(field)
        if b_val != a_val:
            changes.append({
                'field': field,
                'change_type': 'changed',
                'before': copy.deepcopy(b_val),
                'after': copy.deepcopy(a_val),
            })

    # Build summary.
    summary = {
        'added': sum(1 for c in changes if c['change_type'] == 'added'),
        'removed': sum(1 for c in changes if c['change_type'] == 'removed'),
        'changed': sum(1 for c in changes if c['change_type'] == 'changed'),
    }

    return {
        'changed': len(changes) > 0,
        'changes': changes,
        'summary': summary,
    }


# ---------------------------------------------------------------------------
# List comparison helpers
# ---------------------------------------------------------------------------

def _list_added(before, after):
    """Return items present in *after* but not in *before*, preserving
    the order they appear in *after*."""
    before_set = []
    for item in before:
        if isinstance(item, (dict, list)):
            # Use repr for hashability of complex types.
            before_set.append(repr(item))
        else:
            before_set.append(item)
    added = []
    for item in after:
        key = repr(item) if isinstance(item, (dict, list)) else item
        if key not in before_set and item not in added:
            # For unhashable types, compare by equality.
            if not any(_list_equals(item, x) for x in added):
                added.append(item)
    return added


def _list_removed(before, after):
    """Return items present in *before* but not in *after*, preserving
    the order they appear in *before*."""
    after_set = []
    for item in after:
        if isinstance(item, (dict, list)):
            after_set.append(repr(item))
        else:
            after_set.append(item)
    removed = []
    for item in before:
        key = repr(item) if isinstance(item, (dict, list)) else item
        if key not in after_set and not any(_list_equals(item, x) for x in removed):
            removed.append(item)
    return removed


def _list_equals(a, b):
    """Safe equality for any value type (including dicts/lists)."""
    try:
        return a == b
    except Exception:
        return repr(a) == repr(b)


def _is_reorder(before, after):
    """Return True if *before* and *after* contain the same items (by value)
    but in a different order.

    This uses exact equality, not normalization.  Duplicates are handled by
    checking that the multiset of items is identical.
    """
    if len(before) != len(after):
        return False
    # Check same multisets.
    from collections import Counter
    b_repr = [_safe_repr(x) for x in before]
    a_repr = [_safe_repr(x) for x in after]
    return Counter(b_repr) == Counter(a_repr)


def _safe_repr(value):
    """Return a deterministic string representation for any value."""
    if isinstance(value, (dict, list)):
        return repr(value)
    return value


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def get_changes(diff_result):
    """Return just the list of change records from a ``diff_metadata`` result."""
    return diff_result.get('changes', [])


def has_changed(diff_result):
    """Return True if the diff result contains any changes."""
    return diff_result.get('changed', False)
