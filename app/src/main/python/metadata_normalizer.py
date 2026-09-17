# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
"""
Pure-Python metadata normalization engine for FanFicFare Android.

Takes an existing metadata dictionary (as produced by ``epub_editor.read_metadata_fields``)
and returns a normalized copy plus an explicit list of normalization changes.

This module:
  * Does NOT read or write EPUB files.
  * Does NOT perform network requests.
  * Does NOT modify FanFicFare itself.
  * Does NOT modify the existing EPUB writer.

Normalization is cleanup, not rewriting — no semantic interpretation,
no invented metadata, no translation.
"""

import re
import html as _html
import copy
import unicodedata


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ISO 639-2/T (3-letter) → ISO 639-1 (2-letter) mapping.
# Used for normalizing 3-letter language codes to their 2-letter BCP 47 equivalents.
# This is a curated subset of commonly used codes.
_LANGUAGE_CODE_MAP = {
    'eng': 'en', 'fra': 'fr', 'fre': 'fr',
    'deu': 'de', 'ger': 'de',
    'spa': 'es', 'ita': 'it', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja',
    'zho': 'zh', 'chi': 'zh', 'kor': 'ko', 'ara': 'ar', 'hin': 'hi',
    'ben': 'bn', 'pan': 'pa', 'jav': 'jv', 'vie': 'vi', 'tur': 'tr',
    'pol': 'pl', 'ukr': 'uk', 'ron': 'ro', 'rum': 'ro', 'nld': 'nl',
    'dut': 'nl', 'ell': 'el', 'gre': 'el', 'ces': 'cs', 'cze': 'cs',
    'hun': 'hu', 'swe': 'sv', 'bul': 'bg', 'dan': 'da', 'fin': 'fi',
    'nor': 'no', 'nob': 'nb', 'nno': 'nn', 'slk': 'sk', 'slo': 'sk',
    'hrv': 'hr', 'srp': 'sr', 'slv': 'sl', 'est': 'et', 'lav': 'lv',
    'lit': 'lt', 'cat': 'ca', 'eus': 'eu', 'baq': 'eu', 'glg': 'gl',
    'cym': 'cy', 'wel': 'cy', 'gle': 'ga', 'isl': 'is', 'ice': 'is',
    'mlt': 'mt', 'afr': 'af', 'sqi': 'sq', 'alb': 'sq', 'bel': 'be',
    'bos': 'bs', 'mkd': 'mk', 'mac': 'mk', 'heb': 'he', 'yid': 'yi',
    'ind': 'id', 'msa': 'ms', 'may': 'ms', 'tha': 'th', 'fil': 'tl',
    'tgl': 'tl', 'fas': 'fa', 'per': 'fa', 'urd': 'ur', 'guj': 'gu',
    'mar': 'mr', 'tam': 'ta', 'tel': 'te', 'kan': 'kn', 'mal': 'ml',
    'mya': 'my', 'bur': 'my', 'khm': 'km', 'lao': 'lo', 'kat': 'ka',
    'geo': 'ka', 'hye': 'hy', 'arm': 'hy', 'aze': 'az', 'kaz': 'kk',
    'uzb': 'uz', 'mon': 'mn', 'nep': 'ne', 'sin': 'si', 'amh': 'am',
    'swa': 'sw', 'hau': 'ha', 'yor': 'yo', 'ibo': 'ig', 'zul': 'zu',
    'xho': 'xh', 'lat': 'la', 'san': 'sa', 'epo': 'eo',
}

# Valid 2-letter BCP 47 primary language subtags (subset for validation).
_VALID_BCP47_CODES = frozenset([
    'aa', 'ab', 'ae', 'af', 'ak', 'am', 'an', 'ar', 'as', 'av', 'ay', 'az',
    'ba', 'be', 'bg', 'bh', 'bi', 'bm', 'bn', 'bo', 'br', 'bs', 'ca', 'ce',
    'ch', 'co', 'cr', 'cs', 'cu', 'cv', 'cy', 'da', 'de', 'dv', 'dz', 'ee',
    'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'ff', 'fi', 'fj', 'fo', 'fr',
    'fy', 'ga', 'gd', 'gl', 'gn', 'gu', 'gv', 'ha', 'he', 'hi', 'ho', 'hr',
    'ht', 'hu', 'hy', 'hz', 'ia', 'id', 'ie', 'ig', 'ii', 'ik', 'io', 'is',
    'it', 'iu', 'ja', 'jv', 'ka', 'kg', 'ki', 'kj', 'kk', 'kl', 'km', 'kn',
    'ko', 'kr', 'ks', 'ku', 'kv', 'kw', 'ky', 'la', 'lb', 'lg', 'li', 'ln',
    'lo', 'lt', 'lu', 'lv', 'mg', 'mh', 'mi', 'mk', 'ml', 'mn', 'mr', 'ms',
    'mt', 'my', 'na', 'nb', 'nd', 'ne', 'ng', 'nl', 'nn', 'no', 'nr', 'nv',
    'ny', 'oc', 'oj', 'om', 'or', 'os', 'pa', 'pi', 'pl', 'ps', 'pt', 'qu',
    'rm', 'rn', 'ro', 'ru', 'rw', 'sa', 'sc', 'sd', 'se', 'sg', 'si', 'sk',
    'sl', 'sm', 'sn', 'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw', 'ta',
    'te', 'tg', 'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw',
    'ty', 'ug', 'uk', 'ur', 'uz', 've', 'vi', 'vo', 'wa', 'wo', 'xh', 'yi',
    'yo', 'za', 'zh', 'zu',
])

# Whitespace control characters (excluding newline \x0A and tab \x09).
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Pattern for collapsing runs of ordinary whitespace (spaces, tabs outside of
# newlines) — used for plain text fields but NOT descriptions (which preserve
# line structure).
_MULTI_SPACE = re.compile(r'[ \t]+')

# HTML stripping pattern for descriptions.
_HTML_TAG = re.compile(r'<[^>]+>')


# ---------------------------------------------------------------------------
# Core normalization
# ---------------------------------------------------------------------------

def normalize_metadata(metadata):
    """Normalize a metadata dictionary (as returned by ``read_metadata_fields``).

    Returns a dict with two keys:

    * ``metadata`` — the normalized metadata (a deep copy of the input with
      all normalization rules applied).
    * ``changes`` — a list of per-field change records, each containing
      ``field``, ``before``, ``after``, and ``reason``.

    The input ``metadata`` object is never mutated.
    """
    normalized = copy.deepcopy(metadata)
    changes = []

    # --- String fields -------------------------------------------------------
    _normalize_string(normalized, 'title', changes)
    _normalize_string(normalized, 'subtitle', changes)
    _normalize_string(normalized, 'publisher', changes)
    _normalize_description(normalized, 'description', changes)
    _normalize_string(normalized, 'rights', changes)
    _normalize_string(normalized, 'series', changes)
    _normalize_string(normalized, 'series_index', changes)
    _normalize_string(normalized, 'rating', changes)
    _normalize_string(normalized, 'isbn', changes)
    _normalize_string(normalized, 'pubdate', changes)

    # --- Authors / Contributors names (lists of strings) -------------------
    _normalize_string_list(normalized, 'authors', changes)
    _normalize_string_list(normalized, 'tags', changes)
    _normalize_string_list(normalized, 'languages', changes)

    # --- Contributors (list of dicts with name/role/file_as) ---------------
    _normalize_contributors(normalized, changes)

    # --- Language (special: BCP 47 normalization + conversion) ------------
    _normalize_language(normalized, 'languages', changes)

    # --- Date normalization (pubdate) ----------------------------------------
    _normalize_date(normalized, changes)

    # --- ISBN normalization -------------------------------------------------
    _normalize_isbn(normalized, changes)

    # --- Strip control characters from all string fields -------------------
    _strip_control_chars(normalized, changes)

    # Sort changes deterministically by field name then order of discovery.
    changes.sort(key=lambda c: (c['field'], c.get('_order', 0)))
    for i, change in enumerate(changes):
        change['_order'] = i
    # Final sort keeps field ordering stable
    changes.sort(key=lambda c: c['field'])

    return {
        'metadata': normalized,
        'changes': changes,
    }


# ---------------------------------------------------------------------------
# Field-type normalization helpers
# ---------------------------------------------------------------------------

def _normalize_description(meta, field, changes):
    """Normalize a description (or similar text) field: strip HTML, decode
    entities, preserve paragraph structure, collapse whitespace.

    Strips HTML tags and decodes HTML entities (e.g. ``&amp;`` → ``&``).
    Paragraph-breaking tags (``<p>``, ``<br>``, ``<div>``, ``<h1>``...``<h6>``)
    become newlines so the text remains readable when rendered as plain text.
    Inline tags are removed without inserting whitespace.

    Whitespace-only results become empty strings.
    """
    if field not in meta:
        return
    original = meta[field]
    if not isinstance(original, str) or not original.strip():
        return

    value = original
    # Decode HTML entities (e.g., &amp; → &, &lt; → <)
    value = _html.unescape(value)
    # Replace block-level tags with newlines to preserve structure
    value = re.sub(r'</(p|div|br|h\d|li|tr|pre)\s*>', '\n', value, flags=re.IGNORECASE)
    value = re.sub(r'<p\s+[^>]*>', '', value, flags=re.IGNORECASE)
    value = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    # Remove remaining HTML tags
    value = _HTML_TAG.sub('', value)
    # Collapse whitespace: normalize spaces/tabs, collapse multiple newlines
    value = _MULTI_SPACE.sub(' ', value)
    value = re.sub(r'\n[ \t]*', '\n', value)
    value = re.sub(r'[ \t]*\n', '\n', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    value = value.strip()

    if value != original:
        _record_change(meta, changes, field, original, value, 'html_to_text')
        meta[field] = value


def _normalize_string(meta, field, changes):
    """Trim and collapse whitespace for a string field.

    Whitespace-only values become empty strings (consistent with the existing
    default of ``""`` in ``read_metadata_fields``).
    """
    if field not in meta:
        return
    original = meta[field]
    if not isinstance(original, str):
        return
    before = original
    value = original.strip()
    value = _MULTI_SPACE.sub(' ', value)
    # Collapse newlines: trim leading/trailing newlines, collapse internal
    # runs of newlines with optional surrounding spaces to a single newline.
    value = re.sub(r'[ \t]*\n[ \t]*', '\n', value)
    value = value.strip('\n')
    value = re.sub(r'\n{3,}', '\n\n', value)

    if value != before:
        _record_change(meta, changes, field, before, value, 'normalize_whitespace')

    # Remove whitespace-only values → empty string
    if value == '':
        if before != '':
            _record_change(meta, changes, field, before, '', 'remove_empty_value')
        meta[field] = ''
        return

    meta[field] = value


def _normalize_string_list(meta, field, changes):
    """Normalize each element of a list-of-strings field.

    Trims whitespace, removes empty values, and preserves ordering.
    Does NOT deduplicate (deduplication is handled separately for subjects).
    """
    if field not in meta:
        return
    original = meta[field]
    if not isinstance(original, list):
        return

    items = []
    seen = set()
    for item in original:
        if not isinstance(item, str):
            items.append(item)
            continue
        cleaned = item.strip()
        cleaned = _MULTI_SPACE.sub(' ', cleaned)
        if cleaned:
            items.append(cleaned)

    if items != original:
        _record_change(meta, changes, field, _list_to_str(original), _list_to_str(items),
                       'normalize_list')

    meta[field] = items


def _normalize_contributors(meta, changes):
    """Normalize contributor name/role/file_as string values within the
    ``contributors`` list-of-dicts field.

    Trims whitespace on each string value. Does not invent roles or file-as
    values. Does not reorder or deduplicate contributors.
    """
    if 'contributors' not in meta:
        return
    original = meta['contributors']
    if not isinstance(original, list):
        return
    normalized = []
    changed = False
    for contrib in original:
        if not isinstance(contrib, dict):
            normalized.append(contrib)
            continue
        new_contrib = {}
        contrib_changed = False
        for key in ('name', 'role', 'file_as'):
            if key in contrib:
                val = contrib[key]
                if isinstance(val, str):
                    cleaned = val.strip()
                    if cleaned != val:
                        contrib_changed = True
                    new_contrib[key] = cleaned
                else:
                    new_contrib[key] = val
            else:
                new_contrib[key] = ''
        if contrib_changed:
            changed = True
        normalized.append(new_contrib)
    if changed:
        _record_change(meta, changes, 'contributors',
                       _list_to_str([str(c) for c in original]),
                       _list_to_str([str(c) for c in normalized]),
                       'normalize_contributors')
    meta['contributors'] = normalized


def _normalize_language(meta, field, changes):
    """Normalize language codes to BCP 47 form.

    Handles:
      * Lowercasing the primary subtag
      * Converting 3-letter codes to 2-letter where a mapping exists
      * Region subtag uppercase (e.g., ``en-US``)
      * ``en_US`` → ``en-US`` (underscore → hyphen)

    Unknown/malformed codes are preserved rather than deleted.
    """
    if field not in meta or not isinstance(meta[field], list):
        return

    languages = meta[field]
    normalized_langs = []
    for lang in languages:
        if not isinstance(lang, str):
            normalized_langs.append(lang)
            continue

        original = lang.strip()
        if not original:
            normalized_langs.append('')
            continue

        normalized = _normalize_bcp47(original)

        if normalized != original:
            _record_change(meta, changes, field, original, normalized,
                           'normalize_language')
        normalized_langs.append(normalized)

    meta[field] = normalized_langs


def _normalize_bcp47(code):
    """Normalize a single BCP 47 language tag.

    Returns the normalized form. Unknown codes are preserved exactly.
    Handles:
      * 2-letter primary subtag (lowercase): ``EN`` → ``en``
      * 3-letter primary subtag with known mapping: ``ENG`` → ``en``
      * Region subtag (uppercase): ``en-us`` → ``en-US``
      * Underscore → hyphen: ``en_US`` → ``en-US``

    Codes that don't match a recognized BCP 47 pattern are returned unchanged.
    """
    # Replace underscores with hyphens and split.
    raw = code.strip()
    parts = raw.replace('_', '-').split('-')
    if not parts or not parts[0]:
        return code

    primary = parts[0]

    # Only normalize if the primary subtag is 2 or 3 letters.
    if len(primary) == 2:
        # 2-letter: lowercase it (valid BCP 47 primary subtag)
        primary_lower = primary.lower()
    elif len(primary) == 3 and primary.lower() in _LANGUAGE_CODE_MAP:
        # Known 3-letter code: convert to 2-letter
        primary_lower = _LANGUAGE_CODE_MAP[primary.lower()]
    else:
        # Unknown primary subtag: preserve the entire original code unchanged.
        return code

    # Build normalized parts.
    result_parts = [primary_lower]
    if len(parts) > 1:
        # Region subtag: uppercase for 2-letter codes.
        region = parts[1]
        if len(region) == 2:
            result_parts.append(region.upper())
        elif len(region) == 3 and region.isalpha():
            # 3-letter region (e.g., "419" is numeric, actual regional codes are 2-letter)
            result_parts.append(region)
        else:
            # Numeric region or unknown — preserve as-is
            result_parts.append(region)
    # Script and other subtags: preserve as-is (don't mangle)
    if len(parts) > 2:
        result_parts.extend(parts[2:])

    normalized = '-'.join(result_parts)
    return normalized


def _normalize_date(meta, changes):
    """Normalize the ``pubdate`` field to a consistent format.

    Supported: ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``, ISO timestamps.
    Never invents month/day for year-only dates.
    Preserves dates that cannot be safely parsed.
    """
    if 'pubdate' not in meta:
        return
    original = meta['pubdate']
    if not isinstance(original, str) or not original.strip():
        return

    value = original.strip()
    normalized = _normalize_date_value(value)

    if normalized != original:
        _record_change(meta, changes, 'pubdate', original, normalized, 'normalize_date')

    meta['pubdate'] = normalized


def _normalize_date_value(date_str):
    """Attempt to normalize a date string to YYYY-MM-DD or YYYY-MM or YYYY."""
    date_str = date_str.strip()

    # Already in a canonical format.
    if re.match(r'^\d{4}$', date_str):
        return date_str
    if re.match(r'^\d{4}-\d{2}$', date_str):
        return date_str
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # Try parsing as an ISO timestamp and extracting the date portion.
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', date_str)
    if m:
        year, month, day = m.group(1), m.group(2), m.group(3)
        # Validate basic ranges
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            return f'{year}-{month}-{day}'
        return f'{year}' if month == '00' else date_str

    # Try year-month format
    m = re.match(r'^(\d{4})-(\d{2})$', date_str)
    if m:
        year, month = m.group(1), m.group(2)
        if 1 <= int(month) <= 12:
            return f'{year}-{month}'

    # Try MM/DD/YYYY or DD/MM/YYYY — ambiguous, just extract year+month+day
    # only if we can validate ranges.
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_str)
    if m:
        n1, n2, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if n1 <= 12 and n2 <= 31:
            return f'{year}-{n1:02d}-{n2:02d}'

    # Try named month formats: "January 15, 2024", "Jan 2024", etc.
    months = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    }
    # "Month YYYY" → YYYY-MM
    m = re.match(r'^([A-Za-z]+)\s+(\d{4})$', date_str)
    if m:
        mon_name = m.group(1).lower()[:3]
        year = m.group(2)
        if mon_name in months:
            return f'{year}-{months[mon_name]}'

    # "Month DD, YYYY" → YYYY-MM-DD
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$', date_str)
    if m:
        mon_name = m.group(1).lower()[:3]
        day = int(m.group(2))
        year = m.group(3)
        if mon_name in months and 1 <= day <= 31:
            return f'{year}-{months[mon_name]}-{day:02d}'

    # Could not safely parse — preserve original.
    return date_str


def _normalize_isbn(meta, changes):
    """Normalize ISBN: remove hyphens and spaces; validate checksum.

    Valid ISBNs are normalized (dashes/spaces removed).
    Invalid ISBNs are preserved (not silently deleted).
    """
    if 'isbn' not in meta:
        return
    original = meta['isbn']
    if not isinstance(original, str) or not original.strip():
        return

    value = original.strip()
    cleaned = re.sub(r'[-\s]', '', value)

    # Check if it's ISBN-10 or ISBN-13 format.
    is_valid_isbn10 = re.match(r'^\d{9}[\dXx]$', cleaned)
    is_valid_isbn13 = re.match(r'^(978|979)\d{10}$', cleaned)

    if is_valid_isbn10 and _validate_isbn10_checksum(cleaned.upper()):
        if cleaned != value:
            _record_change(meta, changes, 'isbn', value, cleaned, 'normalize_isbn')
        meta['isbn'] = cleaned
    elif is_valid_isbn13 and _validate_isbn13_checksum(cleaned):
        if cleaned != value:
            _record_change(meta, changes, 'isbn', value, cleaned, 'normalize_isbn')
        meta['isbn'] = cleaned
    else:
        # Invalid ISBN — remove only hyphens/spaces if the cleaned form
        # at least looks ISBN-like, otherwise preserve entirely.
        if cleaned and re.match(r'^[\dX]+$', cleaned):
            if cleaned != value:
                _record_change(meta, changes, 'isbn', value, cleaned, 'normalize_isbn')
            meta['isbn'] = cleaned
        # If it doesn't look ISBN-like at all, leave it unchanged.


def _validate_isbn10_checksum(isbn):
    """Validate ISBN-10 check digit."""
    total = 0
    for i in range(9):
        total += int(isbn[i]) * (10 - i)
    check = (11 - (total % 11)) % 11
    expected = isbn[9]
    if check == 10:
        return expected.upper() == 'X'
    return expected == str(check)


def _validate_isbn13_checksum(isbn):
    """Validate ISBN-13 check digit."""
    total = 0
    for i in range(12):
        digit = int(isbn[i])
        total += digit if i % 2 == 0 else digit * 3
    check = (10 - (total % 10)) % 10
    return isbn[12] == str(check)


def _strip_control_chars(meta, changes):
    """Remove non-whitespace control characters from all string fields."""
    string_fields = ['title', 'publisher', 'description', 'rights',
                     'series', 'series_index', 'rating', 'isbn', 'pubdate']
    for field in string_fields:
        if field not in meta:
            continue
        original = meta[field]
        if not isinstance(original, str):
            continue
        if not original:
            continue
        cleaned = _CONTROL_CHARS.sub('', original)
        if cleaned != original:
            _record_change(meta, changes, field, original, cleaned, 'strip_control_char')
            meta[field] = cleaned


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _list_to_str(lst):
    """Convert a list to a comparable string representation for change records."""
    return ', '.join(str(x) for x in lst)


def _record_change(meta, changes, field, before, after, reason):
    """Append a change record to the changes list.

    Checks whether the *final* value in ``meta`` differs from ``before``
    (not whether ``before`` differs from ``after``), so multiple normalizations
    on the same field chain correctly.
    """
    change = {
        'field': field,
        'before': before,
        'after': after,
        'reason': reason,
    }
    changes.append(change)


# ---------------------------------------------------------------------------
# Backward-compatible convenience functions
# ---------------------------------------------------------------------------

def get_normalized_metadata(metadata):
    """Return just the normalized metadata dict (without change records)."""
    result = normalize_metadata(metadata)
    return result['metadata']


def get_normalization_changes(metadata):
    """Return just the list of change records."""
    result = normalize_metadata(metadata)
    return result['changes']
