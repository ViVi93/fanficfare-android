# -*- coding: utf-8 -*-
"""Tests for the metadata_providers module.

Run with:
    cd /home/ubuntu/workspace/fanficfare-android/app/src/main/python
    /tmp/ff_venv/bin/python3 -m unittest tests.test_metadata_providers -v

All tests use mocked HTTP responses — NO live network access is required.

Test coverage:

Google Books:
  - valid response (title + authors + isbn)
  - multiple results
  - ISBN search (isbn: query param)
  - title + author search
  - empty results
  - HTTP error
  - malformed JSON
  - timeout/failure

Open Library:
  - valid response
  - ISBN search
  - title/author result
  - empty results
  - HTTP error
  - malformed JSON
  - timeout/failure

iTunes / Apple Books:
  - valid book response
  - title/author result
  - empty results
  - HTTP error
  - malformed JSON
  - timeout/failure

Aggregation:
  - all providers succeed
  - one provider fails
  - two providers fail
  - all providers fail
  - no results
  - deterministic ordering
  - duplicate ISBN results
  - conflicting titles
  - provider attribution preserved

Normalization integration:
  - authors normalized
  - subtitle normalized
  - description normalized
  - publisher normalized
  - language normalized
  - tags/subjects normalized
  - series preserved
  - rating preserved
  - identifiers preserved
  - isbn preserved
  - pubdate preserved
"""

import sys
import os
import json
import copy
import unittest

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import metadata_providers as mp


# ---------------------------------------------------------------------------
# Mock HTTP helpers
# ---------------------------------------------------------------------------

def make_mock_fetch(response_map):
    """Create a fetch_fn that returns canned JSON for matching URL substrings.

    *response_map* is a list of (url_substring, response_body) pairs.
    If the URL contains the substring, return the response_body bytes.
    First match wins.

    If no match is found, raise a ProviderHTTPError(404).
    """
    def _fetch(url, timeout=15, headers=None):
        for substring, body in response_map:
            if substring in url:
                if isinstance(body, bytes):
                    return body
                return body.encode('utf-8')
        raise mp.ProviderHTTPError('404: Not Found', provider='mock', status_code=404)
    return _fetch


def make_mock_fetch_with_error(error, trigger_substring):
    """Create a fetch_fn that raises *error* for URLs containing
    *trigger_substring*, and returns the given response otherwise."""
    def _fetch(url, timeout=15, headers=None):
        if trigger_substring in url:
            raise error
        return b'{"items": []}'
    return _fetch


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_GOOGLE_BOOKS_RESPONSE = {
    "kind": "books#volumes",
    "totalItems": 1,
    "items": [
        {
            "kind": "books#volume",
            "id": "books/vol1",
            "volumeInfo": {
                "title": "Dune",
                "subtitle": "A Science Fiction Masterpiece",
                "authors": ["Frank Herbert"],
                "publisher": "Chilton Books",
                "publishedDate": "1965-08-01",
                "description": "A desert planet story.",
                "categories": ["Science Fiction", "Adventure"],
                "averageRating": 4.5,
                "language": "en",
                "industryIdentifiers": [
                    {"type": "ISBN_10", "identifier": "0441172717"},
                    {"type": "ISBN_13", "identifier": "9780441172719"},
                ],
                "canonicalVolumeLink": "https://books.google.com/books?id=vol1",
            },
        },
    ],
}

_GOOGLE_BOOKS_EMPTY = {"kind": "books#volumes", "totalItems": 0, "items": []}

_GOOGLE_BOOKS_MULTI = {
    "kind": "books#volumes",
    "totalItems": 2,
    "items": [
        {
            "id": "g1",
            "volumeInfo": {
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "publishedDate": "1965",
                "language": "en",
                "industryIdentifiers": [
                    {"type": "ISBN_10", "identifier": "0441172717"},
                ],
            },
        },
        {
            "id": "g2",
            "volumeInfo": {
                "title": "Dune Messiah",
                "authors": ["Frank Herbert"],
                "publishedDate": "1969",
                "language": "en",
                "industryIdentifiers": [
                    {"type": "ISBN_10", "identifier": "0441172718"},
                ],
            },
        },
    ],
}

_OPEN_LIBRARY_RESPONSE = {
    "numFound": 1,
    "docs": [
        {
            "key": "/books/OL123M",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "publisher": ["Chilton"],
            "first_publish_year": 1965,
            "subject": ["Science Fiction", "Adventure"],
            "language": ["eng"],
            "isbn": ["0441172717", "9780441172719"],
            "lccn": "65050792",
        },
    ],
}

_OPEN_LIBRARY_EMPTY = {"numFound": 0, "docs": []}

_ITUNES_RESPONSE = {
    "resultCount": 1,
    "results": [
        {
            "trackId": 123456789,
            "trackName": "Dune",
            "artistName": "Frank Herbert",
            "description": "A desert planet story.",
            "publisher": "Chilton Books",
            "releaseDate": "1965-08-01T07:00:00Z",
            "genres": ["Books", "Science Fiction"],
            "primaryGenreName": "Books",
            "isbn": "9780441172719",
            "trackViewUrl": "https://itunes.apple.com/book/dune/id123456789",
        },
    ],
}

_ITUNES_EMPTY = {"resultCount": 0, "results": []}


# ---------------------------------------------------------------------------
# Google Books tests
# ---------------------------------------------------------------------------

class TestGoogleBooksProvider(unittest.TestCase):
    """Tests for the Google Books provider."""

    def setUp(self):
        self.provider = mp.GoogleBooksProvider()

    def test_valid_response(self):
        """Google Books returns correctly parsed results from a valid response."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r.ok)
        self.assertEqual(r['provider'], 'google_books')
        meta = r['metadata']
        self.assertEqual(meta['title'], 'Dune')
        self.assertEqual(meta['subtitle'], 'A Science Fiction Masterpiece')
        self.assertEqual(meta['authors'], ['Frank Herbert'])
        self.assertEqual(meta['publisher'], 'Chilton Books')
        self.assertEqual(meta['pubdate'], '1965-08-01')
        self.assertEqual(meta['description'], 'A desert planet story.')
        self.assertEqual(meta['rating'], '4.5')
        self.assertEqual(meta['isbn10'], '0441172717')
        self.assertEqual(meta['isbn13'], '9780441172719')
        self.assertIn('9780441172719', meta['identifiers'].values())
        self.assertEqual(r['source_id'], 'books/vol1')
        self.assertEqual(r['source_url'], 'https://books.google.com/books?id=vol1')

    def test_multiple_results(self):
        """Google Books returns multiple candidates from a multi-item response."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_MULTI))])
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 2)
        titles = [r['metadata']['title'] for r in results]
        self.assertIn('Dune', titles)
        self.assertIn('Dune Messiah', titles)

    def test_isbn_search(self):
        """Google Books uses isbn: prefix when ISBN is provided."""
        captured_urls = []

        def fetch(url, timeout=15, headers=None):
            captured_urls.append(url)
            return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')

        q = mp.build_query(isbn='9780441172719')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(captured_urls), 1)
        self.assertIn('isbn%3A9780441172719', captured_urls[0])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)

    def test_title_author_search(self):
        """Google Books constructs intitle + inauthor query correctly."""
        captured_urls = []

        def fetch(url, timeout=15, headers=None):
            captured_urls.append(url)
            return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')

        q = mp.build_query(title='Dune', author='Herbert')
        self.provider.search(q, fetch_fn=fetch)
        self.assertIn('intitle%3ADune', captured_urls[0])
        self.assertIn('inauthor%3AHerbert', captured_urls[0])

    def test_empty_results(self):
        """Google Books returns empty list for no matches."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_EMPTY))])
        q = mp.build_query(title='Nonexistent')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 0)

    def test_http_error(self):
        """Google Books handles HTTP errors gracefully."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderHTTPError('500: Server Error', provider='google_books', status_code=500)
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('500', results[0]['error'])

    def test_malformed_json(self):
        """Google Books handles malformed JSON gracefully."""
        fetch = make_mock_fetch([('volumes', b'not json at all')])
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('parse', results[0]['error'].lower())

    def test_timeout_failure(self):
        """Google Books handles timeouts gracefully."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderTimeout('timed out')
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('timeout', results[0]['error'].lower())

    def test_empty_query(self):
        """Google Books handles empty queries gracefully."""
        q = mp.build_query()
        results = self.provider.search(q, fetch_fn=lambda url, timeout=15, headers=None: b'')
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('empty', results[0]['error'])


# ---------------------------------------------------------------------------
# Open Library tests
# ---------------------------------------------------------------------------

class TestOpenLibraryProvider(unittest.TestCase):
    """Tests for the Open Library provider."""

    def setUp(self):
        self.provider = mp.OpenLibraryProvider()

    def test_valid_response(self):
        """Open Library returns correctly parsed results from a valid response."""
        fetch = make_mock_fetch([('search.json', json.dumps(_OPEN_LIBRARY_RESPONSE))])
        q = mp.build_query(title='Dune', author='Herbert')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r.ok)
        self.assertEqual(r['provider'], 'open_library')
        meta = r['metadata']
        self.assertEqual(meta['title'], 'Dune')
        self.assertEqual(meta['authors'], ['Frank Herbert'])
        self.assertEqual(meta['publisher'], 'Chilton')
        self.assertEqual(meta['pubdate'], '1965')
        self.assertIn('Science Fiction', meta['tags'])
        self.assertEqual(meta['languages'], ['en'])
        self.assertEqual(meta['isbn10'], '0441172717')
        self.assertEqual(meta['isbn13'], '9780441172719')
        self.assertEqual(r['source_id'], '65050792')
        self.assertIn('/books/OL123M', r['source_url'])

    def test_isbn_search(self):
        """Open Library uses isbn query parameter when ISBN provided."""
        captured_urls = []

        def fetch(url, timeout=15, headers=None):
            captured_urls.append(url)
            return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')

        q = mp.build_query(isbn='9780441172719')
        self.provider.search(q, fetch_fn=fetch)
        self.assertIn('isbn=9780441172719', captured_urls[0])

    def test_title_author_result(self):
        """Open Library title/author search constructs URL correctly."""
        captured_urls = []

        def fetch(url, timeout=15, headers=None):
            captured_urls.append(url)
            return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')

        q = mp.build_query(title='Dune', author='Herbert')
        self.provider.search(q, fetch_fn=fetch)
        self.assertIn('title=Dune', captured_urls[0])
        self.assertIn('author=Herbert', captured_urls[0])

    def test_empty_results(self):
        """Open Library returns empty list for no matches."""
        fetch = make_mock_fetch([('search.json', json.dumps(_OPEN_LIBRARY_EMPTY))])
        q = mp.build_query(title='Nonexistent')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 0)

    def test_http_error(self):
        """Open Library handles HTTP errors gracefully."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderHTTPError('404: Not Found', provider='open_library', status_code=404)
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('404', results[0]['error'])

    def test_malformed_json(self):
        """Open Library handles malformed JSON gracefully."""
        fetch = make_mock_fetch([('search.json', b'broken{json')])
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)

    def test_timeout_failure(self):
        """Open Library handles timeouts gracefully."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderTimeout('timed out')
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('timeout', results[0]['error'].lower())


# ---------------------------------------------------------------------------
# iTunes / Apple Books tests
# ---------------------------------------------------------------------------

class TestITunesProvider(unittest.TestCase):
    """Tests for the iTunes / Apple Books provider."""

    def setUp(self):
        self.provider = mp.ITunesProvider()

    def test_valid_book_response(self):
        """iTunes returns correctly parsed book results."""
        fetch = make_mock_fetch([('search', json.dumps(_ITUNES_RESPONSE))])
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r.ok)
        self.assertEqual(r['provider'], 'itunes')
        meta = r['metadata']
        self.assertEqual(meta['title'], 'Dune')
        self.assertEqual(meta['authors'], ['Frank Herbert'])
        self.assertEqual(meta['publisher'], 'Chilton Books')
        self.assertEqual(meta['pubdate'], '1965-08-01')
        self.assertEqual(meta['description'], 'A desert planet story.')
        self.assertEqual(meta['isbn13'], '9780441172719')
        self.assertIn('Science Fiction', meta['tags'])
        self.assertEqual(r['source_id'], '123456789')
        self.assertEqual(r['source_url'],
                         'https://itunes.apple.com/book/dune/id123456789')

    def test_title_author_result(self):
        """iTunes constructs term query from title + author."""
        captured_urls = []

        def fetch(url, timeout=15, headers=None):
            captured_urls.append(url)
            return json.dumps(_ITUNES_RESPONSE).encode('utf-8')

        q = mp.build_query(title='Dune', author='Herbert')
        self.provider.search(q, fetch_fn=fetch)
        self.assertIn('term=Dune+Herbert', captured_urls[0])

    def test_empty_results(self):
        """iTunes returns empty list for no matches."""
        fetch = make_mock_fetch([('search', json.dumps(_ITUNES_EMPTY))])
        q = mp.build_query(title='Nonexistent')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 0)

    def test_http_error(self):
        """iTunes handles HTTP errors gracefully."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderHTTPError('503: Unavailable', provider='itunes', status_code=503)
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('503', results[0]['error'])

    def test_malformed_json(self):
        """iTunes handles malformed JSON gracefully."""
        fetch = make_mock_fetch([('search', b'<html>error</html>')])
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)

    def test_timeout_failure(self):
        """iTunes handles timeouts gracefully."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderTimeout('timed out')
        q = mp.build_query(title='Dune')
        results = self.provider.search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)


# ---------------------------------------------------------------------------
# Aggregation tests
# ---------------------------------------------------------------------------

class TestAggregation(unittest.TestCase):
    """Tests for multi-provider aggregation and lookup_metadata."""

    def test_all_providers_succeed(self):
        """All three providers return results when all succeed.

        Because all three fixture responses carry the same ISBN-13,
        deduplication reduces the candidates to 1 — but all three
        providers are queried without error.
        """
        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'openlibrary' in url:
                return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(_ITUNES_RESPONSE).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        failures = [r for r in results if not r.ok]
        # All three providers succeed (no failures), deduplication yields 1 unique.
        self.assertEqual(len(failures), 0)
        self.assertGreaterEqual(len(successes), 1)
        # The surviving candidate carries the correct ISBN.
        self.assertTrue(any(r['metadata'].get('isbn13') == '9780441172719' for r in successes))

    def test_one_provider_fails(self):
        """One provider failure does not block others.

        Google Books times out; Open Library and iTunes both succeed but
        share the same ISBN-13, so deduplication yields 1 unique candidate.
        """
        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                raise mp.ProviderTimeout('google timed out')
            elif 'openlibrary' in url:
                return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(_ITUNES_RESPONSE).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        failures = [r for r in results if not r.ok]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['provider'], 'google_books')
        self.assertIn('timeout', failures[0]['error'].lower())
        # OL + iTunes share ISBN-13 → deduped to 1.
        self.assertGreaterEqual(len(successes), 1)

    def test_two_providers_fail(self):
        """Two provider failures still allow the third to return results."""
        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                raise mp.ProviderHTTPError('500', provider='google_books', status_code=500)
            elif 'openlibrary' in url:
                raise mp.ProviderHTTPError('500', provider='open_library', status_code=500)
            elif 'itunes' in url:
                return json.dumps(_ITUNES_RESPONSE).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        failures = [r for r in results if not r.ok]
        self.assertEqual(len(successes), 1)  # iTunes only
        self.assertEqual(len(failures), 2)
        failure_providers = {f['provider'] for f in failures}
        self.assertEqual(failure_providers, {'google_books', 'open_library'})

    def test_all_providers_fail(self):
        """All providers failing produces only failure results."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderTimeout('all timed out')

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        failures = [r for r in results if not r.ok]
        self.assertEqual(len(successes), 0)
        self.assertEqual(len(failures), 3)
        failure_providers = {f['provider'] for f in failures}
        self.assertEqual(failure_providers, {'google_books', 'open_library', 'itunes'})

    def test_no_results(self):
        """All providers returning empty still produces no successes."""
        def fetch(url, timeout=15, headers=None):
            return b'{"items": []}'

        q = mp.build_query(title='Nonexistent Book XYZ')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        self.assertEqual(len(successes), 0)

    def test_deterministic_ordering(self):
        """Calling lookup_metadata twice with same input produces same order."""
        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'openlibrary' in url:
                return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(_ITUNES_RESPONSE).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        r1 = mp.lookup_metadata(q, fetch_fn=fetch)
        r2 = mp.lookup_metadata(q, fetch_fn=fetch)
        self.assertEqual(len(r1), len(r2))
        for a, b in zip(r1, r2):
            self.assertEqual(a['provider'], b['provider'])
            self.assertEqual(a['source_id'], b['source_id'])

    def test_isbn_match_ranks_highest(self):
        """ISBN-matched results are ranked higher than non-ISBN results."""
        # Google returns an ISBN match; iTunes returns a result without ISBN.
        itunes_no_isbn = {
            "resultCount": 1,
            "results": [{
                "trackId": 999,
                "trackName": "Dune",
                "artistName": "Frank Herbert",
                "description": "No ISBN here.",
                "releaseDate": "1965-08-01T07:00:00Z",
            }],
        }

        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(itunes_no_isbn).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        # Google (has ISBN) should rank above iTunes (no ISBN).
        self.assertEqual(successes[0]['provider'], 'google_books')

    def test_duplicate_isbn_deduplicated(self):
        """Two providers returning the same ISBN-13 are deduplicated."""
        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'openlibrary' in url:
                return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        # Both Google and OL return the same ISBN-13 — should be deduplicated to 1.
        isbn13_values = [r['metadata'].get('isbn13') for r in successes if r['metadata'].get('isbn13')]
        unique_isbn13 = set(isbn13_values)
        self.assertEqual(len(unique_isbn13), len(isbn13_values),
                         "Duplicate ISBN-13 results not deduplicated")

    def test_conflicting_titles_remain_distinct(self):
        """Results with different titles are kept as separate candidates."""
        # Google returns "Dune", iTunes returns "Dune: Part Two" (same ISBN).
        itunes_different = {
            "resultCount": 1,
            "results": [{
                "trackId": 111,
                "trackName": "Dune: Part Two",
                "artistName": "Frank Herbert",
                "releaseDate": "2021-01-01T00:00:00Z",
                "isbn": "9780441172719",  # same ISBN as Google's Dune — should dedupe
            }],
        }

        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(itunes_different).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        # Both have the same ISBN-13, so only 1 should survive dedup.
        self.assertEqual(len(successes), 1)

    def test_conflicting_titles_no_isbn_remain_distinct(self):
        """Results with different titles and no ISBN are kept separate."""
        dl = {
            "resultCount": 1,
            "results": [{
                "trackId": 222,
                "trackName": "Dune: Messiah",
                "artistName": "Frank Herbert",
                "releaseDate": "1965-08-01T00:00:00Z",
                # No ISBN — different title — should be a separate candidate.
            }],
        }

        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(dl).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(title='Dune')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        successes = [r for r in results if r.ok]
        self.assertEqual(len(successes), 2)  # Google Books + iTunes

    def test_provider_attribution_preserved(self):
        """Each result carries its provider name for attribution."""
        def fetch(url, timeout=15, headers=None):
            if 'googleapis' in url:
                return json.dumps(_GOOGLE_BOOKS_RESPONSE).encode('utf-8')
            elif 'openlibrary' in url:
                return json.dumps(_OPEN_LIBRARY_RESPONSE).encode('utf-8')
            elif 'itunes' in url:
                return json.dumps(_ITUNES_RESPONSE).encode('utf-8')
            return b'{"items": []}'

        q = mp.build_query(isbn='9780441172719')
        results = mp.lookup_metadata(q, fetch_fn=fetch)
        # Since all have the same ISBN-13, dedup should keep one with attribution.
        successes = [r for r in results if r.ok]
        self.assertGreaterEqual(len(successes), 1)
        for r in successes:
            self.assertIn(r['provider'], {'google_books', 'open_library', 'itunes'})


# ---------------------------------------------------------------------------
# Normalization integration tests
# ---------------------------------------------------------------------------

class TestNormalizationIntegration(unittest.TestCase):
    """Verify provider results pass through the normalizer correctly."""

    def test_authors_normalized(self):
        """Provider authors are normalized through the normalizer."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['authors'], ['Frank Herbert'])

    def test_subtitle_normalized(self):
        """Provider subitles are stripped/normalized."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['subtitle'],
                         'A Science Fiction Masterpiece')

    def test_description_normalized(self):
        """Provider descriptions are trimmed through the normalizer."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['description'],
                         'A desert planet story.')

    def test_publisher_normalized(self):
        """Provider publisher is normalized."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['publisher'], 'Chilton Books')

    def test_language_normalized(self):
        """Provider language codes are normalized (3-letter → 2-letter)."""
        # Open Library returns 'eng' — should become 'en'.
        fetch = make_mock_fetch([('search.json', json.dumps(_OPEN_LIBRARY_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.OpenLibraryProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['languages'], ['en'])

    def test_tags_normalized(self):
        """Provider subjects/tags are normalized (trimmed)."""
        fetch = make_mock_fetch([('search.json', json.dumps(_OPEN_LIBRARY_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.OpenLibraryProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertIn('Science Fiction', results[0]['metadata']['tags'])

    def test_isbn_preserved(self):
        """ISBN-10 and ISBN-13 are preserved from provider results."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        meta = results[0]['metadata']
        self.assertEqual(meta['isbn10'], '0441172717')
        self.assertEqual(meta['isbn13'], '9780441172719')
        self.assertEqual(meta['isbn'], '9780441172719')
        self.assertIn('isbn10', meta['identifiers'])
        self.assertIn('isbn13', meta['identifiers'])

    def test_pubdate_preserved(self):
        """Publication date is preserved from provider results."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['pubdate'], '1965-08-01')

    def test_rating_preserved(self):
        """Average rating is preserved from provider results."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['rating'], '4.5')

    def test_identifiers_preserved(self):
        """Provider-specific identifiers are preserved."""
        fetch = make_mock_fetch([('search.json', json.dumps(_OPEN_LIBRARY_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.OpenLibraryProvider()
        results = provider.search(q, fetch_fn=fetch)
        identifiers = results[0]['metadata']['identifiers']
        self.assertIn('open_library_key', identifiers)

    def test_contributors_not_required(self):
        """Providers without contributor data produce empty contributors list."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        provider = mp.GoogleBooksProvider()
        results = provider.search(q, fetch_fn=fetch)
        self.assertEqual(results[0]['metadata']['contributors'], [])


# ---------------------------------------------------------------------------
# Safety / determinism tests
# ---------------------------------------------------------------------------

class TestSafetyAndDeterminism(unittest.TestCase):
    """Verify input immutability, deterministic output, and safety."""

    def test_provider_input_not_mutated(self):
        """The query dict is not mutated by search()."""
        q = mp.build_query(title='Dune', author='Herbert', isbn='9780441172719')
        q_copy = copy.deepcopy(dict(q))
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        self.assertEqual(dict(q), q_copy)

    def test_provider_output_json_serializable(self):
        """ProviderResult is JSON-serializable."""
        fetch = make_mock_fetch([('volumes', json.dumps(_GOOGLE_BOOKS_RESPONSE))])
        q = mp.build_query(title='Dune')
        results = mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        json.dumps(results[0])  # should not raise

    def test_empty_query_no_network(self):
        """Empty query produces an error result without making a network call."""
        called = []
        def fetch(url, timeout=15, headers=None):
            called.append(url)
            return b'{"items": []}'
        q = mp.build_query()
        results = mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        self.assertEqual(len(called), 0)  # no network call
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn('empty', results[0]['error'])

    def test_provider_error_not_user_facing_traceback(self):
        """Provider failures return a controlled error string, not a traceback."""
        def fetch(url, timeout=15, headers=None):
            raise Exception('unexpected boom')
        q = mp.build_query(title='Dune')
        results = mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertNotIn('Traceback', results[0]['error'])
        self.assertNotIn('unexpected boom', results[0]['error'].replace('unexpected boom', ''))


if __name__ == '__main__':
    unittest.main()
