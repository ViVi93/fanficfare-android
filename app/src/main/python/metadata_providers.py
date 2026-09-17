# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""
Online metadata provider lookup layer for FanFicFare Android.

Provides a reusable abstraction for querying public book-metadata APIs:

* Google Books
* Open Library
* iTunes / Apple Books

Architecture:

    ProviderResult  ── normalized candidate with provider attribution
    MetadataProvider ── abstract interface: search(query) -> list[ProviderResult]
    GoogleBooksProvider / OpenLibraryProvider / ITunesProvider ── concrete
    lookup_metadata(query, ...) ── multi-provider aggregation + ranking

Design principles:

* Standard-library ``urllib.request`` only — no third-party dependencies.
* HTTP fetching is injected via a ``fetch_fn`` callable so tests can
  substitute fixture responses without network access.
* Each provider separates ``_build_request``, ``_parse_response``, and
  ``_normalize_metadata`` for clarity and testability.
* Failures are isolated: one provider's timeout or error does not
  prevent others from returning results.
* Provider results are normalized to the same field schema used by
  ``epub_editor.read_metadata_fields`` and passed through the existing
  :func:`metadata_normalizer.normalize_metadata` for cleanup.
* No API keys, no authentication, no cookies.
* No cover image downloading.

Result schema (ProviderResult):

    {
        "provider": str,          # e.g. "google_books"
        "source_id": str,          # provider-specific identifier
        "source_url": str,         # human-readable URL to the record
        "metadata": {              # normalized metadata dict
            "title": str,
            "subtitle": str,
            "authors": list[str],
            "contributors": list[dict],  # [{'name','role','file_as'}]
            "languages": list[str],
            "publisher": str,
            "description": str,
            "tags": list[str],       # subjects/categories
            "series": str,
            "series_index": str,
            "rating": str,
            "identifiers": dict,     # {id_type: value}
            "isbn": str,
            "isbn13": str,
            "isbn10": str,
            "pubdate": str,
            "rights": str,
        },
        "error": str,             # empty string when successful
    }

Query schema (MetadataQuery):

    {
        "title": str,             # optional
        "author": str,            # optional
        "isbn": str,              # optional — preferred for ISBN-based lookup
    }
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import socket

import metadata_normalizer as normalizer

__all__ = [
    'MetadataQuery',
    'ProviderResult',
    'ProviderError',
    'ProviderFailure',
    'ProviderTimeout',
    'ProviderHTTPError',
    'ProviderParseError',
    'MetadataProvider',
    'GoogleBooksProvider',
    'OpenLibraryProvider',
    'ITunesProvider',
    'DEFAULT_PROVIDERS',
    'lookup_metadata',
    'fetch_url',
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default HTTP timeout in seconds — bounded, never infinite.
DEFAULT_TIMEOUT = 15

# User-Agent string for all provider requests.
USER_AGENT = 'FanFicFare-Android/1.0 (online-metadata; +https://github.com/ViVi93/fanficfare-android)'

# MARC relator code for translator (used when mapping Open Library / iTunes fields).
_ROLE_TRANSLATOR = 'trl'
_ROLE_EDITOR = 'edt'

# Open Library / Google Books language mapping (3-letter → 2-letter BCP 47).
_LANG_MAP = {
    'eng': 'en', 'spa': 'es', 'fra': 'fr', 'fre': 'fr',
    'deu': 'de', 'ita': 'it', 'nld': 'nl', 'por': 'pt',
    'rus': 'ru', 'jpn': 'ja', 'zho': 'zh', 'pol': 'pl',
    'swe': 'sv', 'nor': 'no', 'dan': 'da', 'fin': 'fi',
    'czc': 'cs', 'slo': 'sk', 'hun': 'hu', 'rus': 'ru',
    'ukr': 'uk', 'cat': 'ca', 'gle': 'ga', 'slv': 'sl',
    'srp': 'sr', 'hrv': 'hr', 'bul': 'bg', 'ron': 'ro',
    'hun': 'hu', 'gre': 'el', 'heb': 'he', 'fas': 'fa',
    'tur': 'tr', 'ara': 'ar', 'hin': 'hi', 'tha': 'th',
    'vie': 'vi', 'ind': 'id', 'msa': 'ms', 'fil': 'tl',
    'kor': 'ko', 'vie': 'vi',
}


# ---------------------------------------------------------------------------
# Query / Result types
# ---------------------------------------------------------------------------

class MetadataQuery(dict):
    """A query dict with ``title``, ``author``, and/or ``isbn`` keys.

    All values are optional; at least one should be present for a meaningful
    search.  Values are stripped of surrounding whitespace and lowercased
    for ISBN.
    """

    def __init__(self, title='', author='', isbn=''):
        super().__init__()
        self.title = (title or '').strip()
        self.author = (author or '').strip()
        self.isbn = _normalize_isbn((isbn or '').strip())

    @property
    def title(self):
        return self.get('title', '')

    @title.setter
    def title(self, value):
        self['title'] = (value or '').strip()

    @property
    def author(self):
        return self.get('author', '')

    @author.setter
    def author(self, value):
        self['author'] = (value or '').strip()

    @property
    def isbn(self):
        return self.get('isbn', '')

    @isbn.setter
    def isbn(self, value):
        normalized = (value or '').strip()
        self['isbn'] = _normalize_isbn(normalized)

    def has_isbn(self):
        return bool(self.isbn)

    def has_title(self):
        return bool(self.title)

    def has_author(self):
        return bool(self.author)

    def is_empty(self):
        return not (self.has_isbn() or self.has_title() or self.has_author())


class ProviderResult(dict):
    """A single normalized candidate from a provider.

    Keys: ``provider``, ``source_id``, ``source_url``, ``metadata``, ``error``.
    """

    def __init__(self, provider, metadata=None, source_id='',
                 source_url='', error=''):
        super().__init__()
        self['provider'] = provider
        self['metadata'] = metadata if metadata is not None else {}
        self['source_id'] = source_id
        self['source_url'] = source_url
        self['error'] = error

    @property
    def ok(self):
        """True if this result has no error."""
        return not self.error

    @property
    def title(self):
        return self['metadata'].get('title', '')

    @property
    def authors(self):
        return self['metadata'].get('authors', [])

    @property
    def isbn10(self):
        return self['metadata'].get('isbn10', '')

    @property
    def isbn13(self):
        return self['metadata'].get('isbn13', '')

    @property
    def identifiers(self):
        return self['metadata'].get('identifiers', {})

    @property
    def error(self):
        return self['error']

    @error.setter
    def error(self, value):
        self['error'] = value


# ---------------------------------------------------------------------------
# Provider exceptions — distinguish failure modes for diagnostics
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base exception for provider failures."""

    def __init__(self, message='', provider='', error_type=''):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.error_type = error_type or type(self).__name__

    def __str__(self):
        if self.provider:
            return '%s: [%s] %s' % (self.provider, self.error_type, self.message)
        return '[%s] %s' % (self.error_type, self.message)


class ProviderFailure(ProviderError):
    """Generic provider failure (non-specific)."""
    pass


class ProviderTimeout(ProviderError):
    """Provider request timed out."""

    def __init__(self, message='timeout', provider=''):
        super().__init__(message, provider, 'timeout')


class ProviderHTTPError(ProviderError):
    """Provider returned an HTTP error status."""

    def __init__(self, message='http_error', provider='', status_code=0):
        super().__init__(message, provider, 'http_error')
        self.status_code = status_code


class ProviderParseError(ProviderError):
    """Provider response could not be parsed."""

    def __init__(self, message='parse_error', provider=''):
        super().__init__(message, provider, 'parse_error')


# ---------------------------------------------------------------------------
# HTTP helper — injectable for testing
# ---------------------------------------------------------------------------

def fetch_url(url, timeout=DEFAULT_TIMEOUT, headers=None):
    """Fetch a URL using standard-library urllib.

    Returns the response body bytes on success.
    Raises :class:`ProviderTimeout` on timeout.
    Raises :class:`ProviderHTTPError` on HTTP error status.
    Raises :class:`ProviderFailure` on other network errors.
    """
    if headers is None:
        headers = {}
    req_headers = dict(headers)
    req_headers.setdefault('User-Agent', USER_AGENT)

    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except socket.timeout as e:
        raise ProviderTimeout(str(e))
    except urllib.error.HTTPError as e:
        raise ProviderHTTPError(
            'HTTP %d: %s' % (e.code, e.reason),
            status_code=e.code,
        )
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise ProviderTimeout(str(e.reason))
        raise ProviderFailure(str(e))
    except Exception as e:
        raise ProviderFailure(str(e))


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _normalize_isbn(isbn):
    """Strip non-alphanumeric chars from an ISBN string."""
    if not isbn:
        return ''
    cleaned = ''.join(c for c in isbn if c.isalnum() or c == '-')
    cleaned = cleaned.replace('-', '')
    # Normalize internal spacing.
    cleaned = cleaned.strip()
    return cleaned


def _extract_isbn10(identifiers):
    """Extract ISBN-10 from a identifiers structure.

    *identifiers* may be:
    - a list of dicts like [{'type': 'ISBN', 'identifier': '043955485X'}]
    - a list of strings like ['ISBN:043955485X']
    """
    for item in identifiers or []:
        if isinstance(item, dict):
            t = (item.get('type', '') or '').upper()
            val = (item.get('identifier', '') or '').strip()
            if 'ISBN' in t:
                cleaned = _normalize_isbn(val)
                if len(cleaned) == 10:
                    return cleaned
        elif isinstance(item, str):
            s = item.strip()
            if s.upper().startswith('ISBN'):
                val = s[4:].strip().lstrip(':').strip()
                cleaned = _normalize_isbn(val)
                if len(cleaned) == 10:
                    return cleaned
    return ''


def _extract_isbn13(identifiers):
    """Extract ISBN-13 from a identifiers structure."""
    for item in identifiers or []:
        if isinstance(item, dict):
            t = (item.get('type', '') or '').upper()
            val = (item.get('identifier', '') or '').strip()
            if 'ISBN' in t:
                cleaned = _normalize_isbn(val)
                if len(cleaned) == 13:
                    return cleaned
        elif isinstance(item, str):
            s = item.strip()
            if s.upper().startswith('ISBN'):
                val = s[4:].strip().lstrip(':').strip()
                cleaned = _normalize_isbn(val)
                if len(cleaned) == 13:
                    return cleaned
    return ''


def _to_authors(name_list):
    """Convert a list of name strings to a clean list."""
    result = []
    for n in name_list or []:
        if isinstance(n, str):
            n = n.strip()
            if n and n != 'N/A' and n != 'Unknown':
                result.append(n)
        elif isinstance(n, dict):
            name = (n.get('name') or '').strip()
            if name:
                result.append(name)
    return result


def _to_tags(subject_list):
    """Convert a list of subject/category strings to clean tags."""
    result = []
    for s in subject_list or []:
        if isinstance(s, str):
            s = s.strip()
            if s:
                result.append(s)
        elif isinstance(s, dict):
            name = (s.get('name') or s.get('value') or '').strip()
            if name:
                result.append(name)
    return result


def _to_languages(lang_list):
    """Convert a list of language codes to BCP 47 format."""
    result = []
    for lang in lang_list or []:
        if not isinstance(lang, str):
            continue
        lang = lang.strip().lower()
        if not lang:
            continue
        # Map 3-letter to 2-letter where possible.
        mapped = _LANG_MAP.get(lang, lang)
        # Take first segment if it contains '-' (e.g. 'en-US' -> 'en').
        if '-' in mapped:
            mapped = mapped.split('-')[0]
        if mapped and mapped not in result:
            result.append(mapped)
    return result


def _to_description(text):
    """Clean and trim a description string."""
    if not text or not isinstance(text, str):
        return ''
    return text.strip()


def _empty_metadata():
    """Return an empty normalized metadata dict (all fields present)."""
    return {
        'title': '',
        'subtitle': '',
        'authors': [],
        'contributors': [],
        'languages': [],
        'publisher': '',
        'description': '',
        'tags': [],
        'series': '',
        'series_index': '',
        'rating': '',
        'identifiers': {},
        'isbn': '',
        'isbn10': '',
        'isbn13': '',
        'pubdate': '',
        'rights': '',
    }


def _normalize_provider_metadata(raw, provider_name):
    """Normalize a raw provider-specific metadata dict into the common schema.

    Merges *raw* into an empty base dict, then runs it through the existing
    metadata_normalizer.  Returns the normalized ``metadata`` dict.
    """
    base = _empty_metadata()
    base.update(raw)
    norm_result = normalizer.normalize_metadata(base)
    return norm_result['metadata']


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class MetadataProvider:
    """Abstract base class for online metadata providers.

    Subclasses define:
    - ``name``: provider identifier string
    - ``_build_request(query, fetch_fn) -> str``: build the request URL
    - ``_parse_response(data, query) -> list[ProviderResult]``: parse raw
      response bytes into ProviderResult objects (before normalization)

    The base ``search`` method handles HTTP fetching, JSON parsing, and
    error isolation.  Subclasses should NOT override ``search``.
    """

    name = 'base'

    def search(self, query, fetch_fn=None, timeout=DEFAULT_TIMEOUT):
        """Query this provider for the given MetadataQuery.

        Returns a list of ProviderResult objects.  On failure, returns a
        list containing a single failed ProviderResult (with ``error`` set)
        rather than raising — so one provider's failure never crashes the
        aggregator.

        Args:
            query: A MetadataQuery dict.
            fetch_fn: Optional callable (url, timeout) -> bytes.  Defaults
                      to the module-level ``fetch_url``.
            timeout: Request timeout in seconds.
        """
        if fetch_fn is None:
            fetch_fn = fetch_url

        if query.is_empty():
            return [ProviderResult(
                provider=self.name,
                error='empty query',
            )]

        try:
            request = self._build_request(query)
        except ProviderError as e:
            return [ProviderResult(
                provider=self.name,
                error=str(e),
            )]

        try:
            raw = fetch_fn(request, timeout=timeout)
        except ProviderError as e:
            return [ProviderResult(
                provider=e.provider or self.name,
                error=str(e),
            )]
        except Exception as e:
            return [ProviderResult(
                provider=self.name,
                error='%s: %s' % (type(e).__name__, e),
            )]

        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as e:
            return [ProviderResult(
                provider=self.name,
                error='JSON parse error: %s' % e,
            )]

        try:
            return self._parse_response(data, query)
        except ProviderError as e:
            return [ProviderResult(
                provider=self.name,
                error=str(e),
            )]
        except Exception as e:
            return [ProviderResult(
                provider=self.name,
                error='%s: %s' % (type(e).__name__, e),
            )]

    def _build_request(self, query):
        """Build the full request URL for this provider. Override in subclass."""
        raise NotImplementedError

    def _parse_response(self, data, query):
        """Parse JSON response data into list of ProviderResult. Override in subclass."""
        raise NotImplementedError

    def _make_result(self, metadata, source_id='', source_url=''):
        """Create a ProviderResult with this provider's name and normalized metadata."""
        norm_meta = _normalize_provider_metadata(metadata, self.name)
        return ProviderResult(
            provider=self.name,
            metadata=norm_meta,
            source_id=source_id,
            source_url=source_url,
        )


# ---------------------------------------------------------------------------
# Google Books provider
# ---------------------------------------------------------------------------

class GoogleBooksProvider(MetadataProvider):
    """Google Books public API provider (no API key required for basic queries)."""

    name = 'google_books'

    BASE_URL = 'https://www.googleapis.com/books/v1/volumes'

    def _build_request(self, query):
        params = {}

        if query.has_isbn():
            # ISBN-oriented query: use 'isbn:' prefix for precise matching.
            params['q'] = 'isbn:%s' % query.isbn
        else:
            parts = []
            if query.has_title():
                parts.append('intitle:%s' % query.title)
            if query.has_author():
                parts.append('inauthor:%s' % query.author)
            if parts:
                params['q'] = '+'.join(parts)
            else:
                params['q'] = ' '  # will produce no useful results

        # maxResults: 0-40 (we use 20 for reasonable performance).
        params['maxResults'] = '20'

        query_string = urllib.parse.urlencode(params)
        return '%s?%s' % (self.BASE_URL, query_string)

    def _parse_response(self, data, query):
        results = []

        items = data.get('items', [])
        if not isinstance(items, list):
            return results

        for item in items:
            if not isinstance(item, dict):
                continue
            vol_info = item.get('volumeInfo', {})
            if not isinstance(vol_info, dict):
                continue

            raw = {}

            raw['title'] = vol_info.get('title', '')

            # Subtitle.
            raw['subtitle'] = vol_info.get('subtitle', '') or ''

            # Authors.
            authors = vol_info.get('authors', [])
            raw['authors'] = _to_authors(authors)

            # Description.
            raw['description'] = _to_description(
                vol_info.get('description', '') or '')

            # Publisher.
            raw['publisher'] = vol_info.get('publisher', '') or ''

            # Published date.
            raw['pubdate'] = vol_info.get('publishedDate', '') or ''

            # Language.
            lang = vol_info.get('language', '')
            if lang:
                raw['languages'] = _to_languages([lang])

            # Categories (subjects/tags).
            raw['tags'] = _to_tags(vol_info.get('categories', []))

            # Rating.
            avg_rating = vol_info.get('averageRating')
            if avg_rating is not None:
                raw['rating'] = str(avg_rating)

            # Industry identifiers (ISBN).
            industry_ids = vol_info.get('industryIdentifiers', [])
            isbn10 = _extract_isbn10(industry_ids)
            isbn13 = _extract_isbn13(industry_ids)
            if isbn10:
                raw['isbn10'] = isbn10
                raw['isbn'] = isbn10
            if isbn13:
                raw['isbn13'] = isbn13
                raw['isbn'] = isbn13

            # Identifiers dict.
            raw.setdefault('identifiers', {})
            if isbn10:
                raw['identifiers']['isbn10'] = isbn10
            if isbn13:
                raw['identifiers']['isbn13'] = isbn13

            # Source URL.
            source_url = vol_info.get('canonicalVolumeLink', '') or ''
            source_id = item.get('id', '')

            # Cover image links (Google Books).
            image_links = vol_info.get('imageLinks', {})
            if isinstance(image_links, dict):
                raw['image_links'] = image_links

            results.append(
                self._make_result(raw, source_id=source_id, source_url=source_url)
            )

        return results


# ---------------------------------------------------------------------------
# Open Library provider
# ---------------------------------------------------------------------------

class OpenLibraryProvider(MetadataProvider):
    """Open Library public API provider."""

    name = 'open_library'

    BASE_URL = 'https://openlibrary.org/search.json'

    def _build_request(self, query):
        params = {}

        if query.has_isbn():
            params['isbn'] = query.isbn
        else:
            if query.has_title():
                params['title'] = query.title
            if query.has_author():
                params['author'] = query.author

        params['limit'] = '20'
        params['jscmd'] = 'data'

        query_string = urllib.parse.urlencode(params)
        return '%s?%s' % (self.BASE_URL, query_string)

    def _parse_response(self, data, query):
        results = []

        docs = data.get('docs', [])
        if not isinstance(docs, list):
            return results

        for doc in docs:
            if not isinstance(doc, dict):
                continue

            raw = {}

            raw['title'] = doc.get('title', '') or ''
            raw['subtitle'] = doc.get('subtitle', '') or ''

            # Authors: OL returns author_name list.
            raw['authors'] = _to_authors(doc.get('author_name', []))

            # Description: OL search returns 'description' only for some editions;
            # often it's not in search results.  Keep if present.
            raw['description'] = _to_description(
                doc.get('description', '') or '')

            # Publisher.
            pubs = doc.get('publisher', [])
            if isinstance(pubs, list) and pubs:
                raw['publisher'] = pubs[0].strip()

            # First publish year as pubdate.
            first_year = doc.get('first_publish_year')
            if first_year:
                raw['pubdate'] = str(first_year)

            # Subjects/tags.
            raw['tags'] = _to_tags(doc.get('subject', []))

            # Languages.
            langs = doc.get('language', [])
            if isinstance(langs, list):
                raw['languages'] = _to_languages(langs)

            # ISBN identifiers.
            isbn_list = doc.get('isbn', [])
            if isinstance(isbn_list, list):
                for isbn_val in isbn_list:
                    if isinstance(isbn_val, str):
                        cleaned = _normalize_isbn(isbn_val)
                        if len(cleaned) == 10 and not raw.get('isbn10'):
                            raw['isbn10'] = cleaned
                        elif len(cleaned) == 13 and not raw.get('isbn13'):
                            raw['isbn13'] = cleaned
                if raw.get('isbn13'):
                    raw['isbn'] = raw['isbn13']
                elif raw.get('isbn10'):
                    raw['isbn'] = raw['isbn10']

            # Identifiers dict.
            raw.setdefault('identifiers', {})
            key = doc.get('key', '')
            if key:
                raw['identifiers']['open_library_key'] = key

            # Source URL.
            if key:
                source_url = 'https://openlibrary.org%s' % key
            else:
                source_url = ''
            source_id = doc.get('lccn', doc.get('oclc', '')) or ''

            # Cover image (Open Library).
            cover_i = doc.get('cover_i')
            if cover_i:
                raw['cover_i'] = str(cover_i)

            results.append(
                self._make_result(raw, source_id=source_id, source_url=source_url)
            )

        return results


# ---------------------------------------------------------------------------
# iTunes / Apple Books provider
# ---------------------------------------------------------------------------

class ITunesProvider(MetadataProvider):
    """iTunes Search API provider (restricted to book media type)."""

    name = 'itunes'

    BASE_URL = 'https://itunes.apple.com/search'

    def _build_request(self, query):
        params = {}
        params['media'] = 'book'
        params['limit'] = '20'
        params['entity'] = 'ebook'

        if query.has_isbn():
            params['term'] = query.isbn
        elif query.has_title() and query.has_author():
            params['term'] = '%s %s' % (query.title, query.author)
        elif query.has_title():
            params['term'] = query.title
        elif query.has_author():
            params['term'] = query.author
        else:
            params['term'] = ' '

        query_string = urllib.parse.urlencode(params)
        return '%s?%s' % (self.BASE_URL, query_string)

    def _parse_response(self, data, query):
        results = []

        result_count = data.get('resultCount', 0)
        if not isinstance(result_count, int) or result_count == 0:
            return results

        items = data.get('results', [])
        if not isinstance(items, list):
            return results

        for item in items:
            if not isinstance(item, dict):
                continue

            raw = {}

            raw['title'] = item.get('trackName', item.get('collectionName', '')) or ''
            raw['subtitle'] = item.get('subtitle', '') or ''

            # Authors: iTunes uses 'artistName' for author.
            author = item.get('artistName', '') or ''
            raw['authors'] = _to_authors([author]) if author else []

            raw['description'] = _to_description(
                item.get('description', '') or '')
            raw['publisher'] = item.get('publisher', '') or ''

            # Release date.
            release_date = item.get('releaseDate', '')
            if release_date:
                # Extract just the date part (YYYY-MM-DD).
                raw['pubdate'] = release_date[:10] if len(release_date) >= 10 else release_date

            # Genre / categories.
            genres = item.get('genres', [])
            raw['tags'] = _to_tags(genres)
            primary_genre = item.get('primaryGenreName', '')
            if isinstance(primary_genre, str) and primary_genre.strip():
                if primary_genre.strip() not in raw['tags']:
                    raw['tags'].insert(0, primary_genre.strip())

            # Rating: iTunes provides 'contentAdvisoryRating' (e.g. '4+') —
            # not a book rating.  We do NOT map this to the rating field.
            # No numeric average rating is available from iTunes book API.

            # ISBN.
            isbn_val = item.get('isbn', '') or ''
            if isinstance(isbn_val, str) and isbn_val.strip():
                cleaned = _normalize_isbn(isbn_val)
                if len(cleaned) == 13:
                    raw['isbn13'] = cleaned
                    raw['isbn'] = cleaned
                elif len(cleaned) == 10:
                    raw['isbn10'] = cleaned
                    raw['isbn'] = cleaned

            # Identifiers dict.
            raw.setdefault('identifiers', {})
            track_id = item.get('trackId')
            if track_id is not None:
                raw['identifiers']['itunes_track_id'] = str(track_id)

            # Source URL.
            source_url = item.get('trackViewUrl', '') or item.get('collectionViewUrl', '') or ''
            source_id = str(item.get('trackId', ''))

            # Cover artwork (iTunes).
            artwork_url = item.get('artworkUrl512') or item.get('artworkUrl100') or ''
            if artwork_url:
                raw['cover_url'] = artwork_url

            results.append(
                self._make_result(raw, source_id=source_id, source_url=source_url)
            )

        return results


# ---------------------------------------------------------------------------
# Default providers
# ---------------------------------------------------------------------------

#: Default provider instances for use with :func:`lookup_metadata`.
DEFAULT_PROVIDERS = [
    GoogleBooksProvider(),
    OpenLibraryProvider(),
    ITunesProvider(),
]


# ---------------------------------------------------------------------------
# Aggregation / lookup
# ---------------------------------------------------------------------------

def lookup_metadata(query, providers=None, fetch_fn=None, timeout=DEFAULT_TIMEOUT):
    """Query multiple providers and return aggregated, normalized results.

    Args:
        query: A MetadataQuery dict (or a dict with 'title'/'author'/'isbn').
        providers: List of MetadataProvider instances.  Defaults to
                   :data:`DEFAULT_PROVIDERS`.
        fetch_fn: Optional callable (url, timeout) -> bytes.  Defaults to
                  :func:`fetch_url`.
        timeout: Per-provider request timeout in seconds.

    Returns:
        A list of ProviderResult objects (sorted by ranking), each with
        normalized metadata.  Failed providers appear as results with
        ``error`` set.  Only the first ``_MAX_CANDIDATES`` successful
        results are returned (failures are always included for diagnostics).

    Design:
        - Providers are queried in the order given.
        - Each provider's failure is isolated; its ProviderResult has
          ``error`` set but does not crash the aggregation.
        - Results are deduplicated by ISBN-13 → ISBN-10 → title+author.
        - Results are ranked: ISBN matches first, then exact title+author.
    """
    if providers is None:
        providers = DEFAULT_PROVIDERS

    if isinstance(query, dict) and not isinstance(query, MetadataQuery):
        query = MetadataQuery(
            title=query.get('title', ''),
            author=query.get('author', ''),
            isbn=query.get('isbn', ''),
        )

    all_results = []
    seen_keys = set()

    for provider in providers:
        provider_results = provider.search(query, fetch_fn=fetch_fn, timeout=timeout)
        for result in provider_results:
            if result.ok:
                # Deduplicate successful results.
                dedup_key = _dedup_key(result)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                all_results.append(result)
            else:
                # Always include failures for diagnostics.
                all_results.append(result)

    # Rank and sort.
    ranked = _rank_results(all_results)

    # Limit successful results to _MAX_CANDIDATES, but always include failures.
    successes = [r for r in ranked if r.ok]
    failures = [r for r in ranked if not r.ok]
    return successes[:_MAX_CANDIDATES] + failures


_MAX_CANDIDATES = 50


def _dedup_key(result):
    """Build a deduplication key for a ProviderResult.

    Priority: ISBN-13 → ISBN-10 → identifiers → title+authors.
    """
    meta = result['metadata']
    isbn13 = meta.get('isbn13', '')
    if isbn13:
        return ('isbn13', isbn13.lower())
    isbn10 = meta.get('isbn10', '')
    if isbn10:
        return ('isbn10', isbn10.lower())
    identifiers = meta.get('identifiers', {})
    if identifiers:
        return ('ident', tuple(sorted(identifiers.items())))
    title = (meta.get('title', '') or '').strip().lower()
    authors = tuple(sorted(a.strip().lower() for a in meta.get('authors', []) if a.strip()))
    return ('title_author', title, authors)


def _rank_results(results):
    """Sort ProviderResult objects by relevance.

    Ranking (deterministic):
    1. Results with an ISBN-13 or ISBN-10 are ranked higher.
    2. Results with a title are ranked higher.
    3. Results with authors are ranked higher.
    4. Provider order is a stable tiebreaker (google_books > open_library > itunes).
    """
    return sorted(results, key=_sort_key, reverse=True)


def _sort_key(result):
    """Compute a sort key for a ProviderResult.

    Higher = better.  We use tuples where True/1 sorts after False/0.
    """
    meta = result['metadata'] if result.ok else {}

    has_isbn = bool(meta.get('isbn13') or meta.get('isbn10'))
    has_exact_title = bool(meta.get('title'))
    has_authors = bool(meta.get('authors'))

    # Stable tiebreaker: provider name alphabetical, then source_id.
    provider_order = ['google_books', 'open_library', 'itunes']
    provider_rank = provider_order.index(result['provider']) if result['provider'] in provider_order else len(provider_order)

    return (
        int(has_isbn),
        int(has_exact_title),
        int(has_authors),
        -provider_rank,  # lower provider_order index = higher priority
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_query(title='', author='', isbn=''):
    """Build a MetadataQuery from individual components."""
    return MetadataQuery(title=title, author=author, isbn=isbn)


def search_all(query, providers=None, fetch_fn=None, timeout=DEFAULT_TIMEOUT):
    """Convenience alias for :func:`lookup_metadata`."""
    return lookup_metadata(query, providers=providers, fetch_fn=fetch_fn, timeout=timeout)
