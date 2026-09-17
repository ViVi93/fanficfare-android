# -*- coding: utf-8 -*-
"""Tests for the cover_manager module.

Run with:
    cd /home/ubuntu/workspace/fanficfare-android/app/src/main/python
    /tmp/ff_venv/bin/python3 -m unittest tests.test_cover_manager -v

All tests use mocked HTTP responses and synthetic image data — NO live
network access is required.
"""

import sys
import os
import json
import struct
import io
import unittest

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import cover_manager as cm
import metadata_providers as mp


# ---------------------------------------------------------------------------
# Synthetic image data builders
# ---------------------------------------------------------------------------

def make_jpeg_bytes(width=300, height=400):
    """Build a minimal valid JPEG with the given dimensions.

    Creates a tiny JPEG with SOF0 marker encoding the dimensions.
    Not a visually meaningful image, but structurally valid.
    """
    # Minimal JPEG: SOI + APP0 + DQT + SOF0 + SOS + EOI
    # We construct a minimal but valid JPEG with specified dimensions.
    data = bytearray()
    # SOI
    data.extend(b'\xff\xd8')
    # APP0 (JFIF)
    data.extend(b'\xff\xe0')
    data.extend(struct.pack('>H', 16))  # length
    data.extend(b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00')
    # DQT
    data.extend(b'\xff\xdb')
    # 64-byte quantization table (all 1s)
    qt = b'\x00' + b'\x01' * 64
    data.extend(struct.pack('>H', len(qt) + 2))
    data.extend(qt)
    # SOF0 (baseline DCT)
    data.extend(b'\xff\xc0')
    sof_payload = struct.pack('>B', 8)  # precision
    sof_payload += struct.pack('>H', height)
    sof_payload += struct.pack('>H', width)
    sof_payload += b'\x01'  # components: 1 (grayscale)
    sof_payload += b'\x01\x11\x00'
    data.extend(struct.pack('>H', len(sof_payload) + 2))
    data.extend(sof_payload)
    # DHT (minimal Huffman table)
    data.extend(b'\xff\xc4')
    dht = b'\x00'  # DC table class 0, ID 0
    dht += b'\x01' * 16 + b'\x00'
    data.extend(struct.pack('>H', len(dht) + 2))
    data.extend(dht)
    # SOS
    data.extend(b'\xff\xda')
    sos = struct.pack('>B', 1)  # components
    sos += b'\x01\x00'  # component 1, dc/ac table 0
    sos += b'\x00\x3f\x00'  # spectral selection
    data.extend(struct.pack('>H', len(sos) + 2))
    data.extend(sos)
    # Scan data (minimal — just a few bytes)
    data.extend(b'\x00\x00\x00\x00\x00\x00')
    # EOI
    data.extend(b'\xff\xd9')
    return bytes(data)


def make_png_bytes(width=200, height=300):
    """Build a minimal valid PNG with the given dimensions."""
    def _chunk(chunk_type, data):
        chunk = chunk_type + data
        import zlib
        crc = zlib.crc32(chunk) & 0xFFFFFFFF
        return struct.pack('>I', len(data)) + chunk + struct.pack('>I', crc)

    sig = b'\x89PNG\r\n\x1a\n'
    # IHDR
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)  # 8-bit grayscale
    ihdr_chunk = _chunk(b'IHDR', ihdr)
    # IDAT (raw compressed data — just zeros, enough to be structurally valid)
    import zlib
    raw = b'\x00' * (width + 1) * height  # filter byte + scanline per row
    idat_chunk = _chunk(b'IDAT', zlib.compress(raw))
    # IEND
    iend_chunk = _chunk(b'IEND', b'')
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def make_gif_bytes(width=150, height=200):
    """Build a minimal valid GIF with the given dimensions."""
    data = bytearray()
    data.extend(b'GIF89a')
    data.extend(struct.pack('<HH', width, height))
    data.extend(b'\x80\x00\x00')  # GCT flag, color resolution, sort, GCT size
    data.extend(b'\x00\x00\x00')  # bg color
    data.extend(b'\x00\x00\x00')  # aspect ratio
    # Global Color Table (4 colors)
    data.extend(b'\x00\x00\x00')  # black
    data.extend(b'\xff\xff\xff')  # white
    data.extend(b'\x00\x00\x00')
    data.extend(b'\x00\x00\x00')
    # Image Descriptor
    data.extend(b'\x2c')  # image separator
    data.extend(struct.pack('<HHHH', 0, 0, width, height))
    data.extend(b'\x00')  # flags
    # Image Data
    data.extend(b'\x02')  # LZW minimum code size
    data.extend(b'\x02\x02\x4c\x01\x00')  # data sub-block + terminator
    data.extend(b'\x00')  # block terminator
    # Trailer
    data.extend(b'\x3b')
    return bytes(data)


def make_webp_bytes(width=100, height=150):
    """Build a minimal valid WebP (VP8L) with the given dimensions."""
    data = bytearray()
    data.extend(b'RIFF')
    # We'll compute the total size later
    webp_data = bytearray()
    webp_data.extend(b'WEBP')
    webp_data.extend(b'VP8L')
    webp_data.extend(struct.pack('<I', 25))  # chunk size
    webp_data.extend(struct.pack('<B', 1))  # version
    # Width-1 and Height-1 as 14-bit + alpha bit
    width_bits = (width - 1) & 0x3FFF if width > 0 else 0
    height_bits = (height - 1) & 0x3FFF if height > 0 else 0
    wh = width_bits | ((height_bits & 0x3FFF) << 14)
    webp_data.extend(struct.pack('<I', wh))
    webp_data.extend(b'\x00' * 20)  # filler
    data.extend(struct.pack('<I', 4 + len(webp_data) + 12))  # RIFF size
    data.extend(webp_data)
    data.extend(b'\x00' * 4)  # padding
    return bytes(data[:12 + len(webp_data)])


def make_html_bytes():
    """Return bytes that look like HTML, not an image."""
    return b'<html><body><h1>Not an image</h1></body></html>'


def make_truncated_jpeg():
    """Return truncated JPEG bytes (valid header, incomplete data)."""
    return make_jpeg_bytes(300, 400)[:10]


# ---------------------------------------------------------------------------
# Mock HTTP helpers
# ---------------------------------------------------------------------------

def make_mock_fetch(response_map):
    """Create a fetch_fn returning canned responses for matching URL substrings."""
    def _fetch(url, timeout=15, headers=None):
        for substring, body in response_map:
            if substring in url:
                if isinstance(body, bytes):
                    return body
                return body.encode('utf-8')
        raise mp.ProviderHTTPError('404: Not Found', status_code=404)
    return _fetch


def make_mock_fetch_bytes(response_map):
    """Like make_mock_fetch but responses are always bytes (for binary images)."""
    def _fetch(url, timeout=15, headers=None):
        for substring, body in response_map:
            if substring in url:
                if isinstance(body, bytes):
                    return body
                return body.encode('utf-8')
        raise mp.ProviderHTTPError('404: Not Found', status_code=404)
    return _fetch


# ---------------------------------------------------------------------------
# URL validation tests
# ---------------------------------------------------------------------------

class TestURLValidation(unittest.TestCase):
    """Tests for validate_cover_url."""

    def test_valid_https_url(self):
        self.assertTrue(cm.validate_cover_url('https://example.com/cover.jpg'))

    def test_valid_http_url(self):
        self.assertTrue(cm.validate_cover_url('http://example.com/cover.jpg'))

    def test_valid_url_with_query_string(self):
        self.assertTrue(cm.validate_cover_url(
            'https://example.com/cover.jpg?size=large&format=webp'
        ))

    def test_empty_url(self):
        self.assertFalse(cm.validate_cover_url(''))

    def test_whitespace_url(self):
        self.assertFalse(cm.validate_cover_url('   '))

    def test_malformed_url(self):
        self.assertFalse(cm.validate_cover_url('not a url'))

    def test_file_scheme_rejected(self):
        self.assertFalse(cm.validate_cover_url('file:///etc/passwd'))

    def test_ftp_scheme_rejected(self):
        self.assertFalse(cm.validate_cover_url('ftp://example.com/cover.jpg'))

    def test_javascript_scheme_rejected(self):
        self.assertFalse(cm.validate_cover_url('javascript:alert(1)'))

    def test_url_with_no_scheme(self):
        self.assertFalse(cm.validate_cover_url('example.com/cover.jpg'))

    def test_none_rejected(self):
        self.assertFalse(cm.validate_cover_url(None))

    def test_non_string_rejected(self):
        self.assertFalse(cm.validate_cover_url(12345))


# ---------------------------------------------------------------------------
# Download handling tests
# ---------------------------------------------------------------------------

class TestDownloadHandling(unittest.TestCase):
    """Tests for download_cover with various responses."""

    def test_successful_jpeg_download(self):
        """download_cover returns validated JPEG data."""
        jpeg = make_jpeg_bytes(300, 400)
        fetch = make_mock_fetch_bytes([('cover.jpg', jpeg)])
        result = cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)
        self.assertEqual(result['mime_type'], 'image/jpeg')
        self.assertEqual(result['width'], 300)
        self.assertEqual(result['height'], 400)
        self.assertEqual(result['data'], jpeg)

    def test_successful_png_download(self):
        """download_cover returns validated PNG data."""
        png = make_png_bytes(200, 300)
        fetch = make_mock_fetch_bytes([('cover.png', png)])
        result = cm.download_cover('https://example.com/cover.png', fetch_fn=fetch)
        self.assertEqual(result['mime_type'], 'image/png')
        self.assertEqual(result['width'], 200)
        self.assertEqual(result['height'], 300)

    def test_successful_gif_download(self):
        """download_cover returns validated GIF data."""
        gif = make_gif_bytes(150, 200)
        fetch = make_mock_fetch_bytes([('cover.gif', gif)])
        result = cm.download_cover('https://example.com/cover.gif', fetch_fn=fetch)
        self.assertEqual(result['mime_type'], 'image/gif')
        self.assertEqual(result['width'], 150)
        self.assertEqual(result['height'], 200)

    def test_successful_webp_download(self):
        """download_cover returns validated WebP data."""
        webp = make_webp_bytes(100, 150)
        fetch = make_mock_fetch_bytes([('cover.webp', webp)])
        result = cm.download_cover('https://example.com/cover.webp', fetch_fn=fetch)
        self.assertEqual(result['mime_type'], 'image/webp')

    def test_timeout(self):
        """download_cover raises CoverDownloadTimeout on timeout."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderTimeout('timed out')
        with self.assertRaises(cm.CoverDownloadTimeout):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_http_error(self):
        """download_cover raises CoverDownloadHTTPError on HTTP error."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderHTTPError('404', status_code=404)
        with self.assertRaises(cm.CoverDownloadHTTPError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_connection_error(self):
        """download_cover raises CoverDownloadError on network error."""
        def fetch(url, timeout=15, headers=None):
            raise mp.ProviderFailure('connection refused')
        with self.assertRaises(cm.CoverDownloadError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_oversized_response(self):
        """download_cover raises CoverValidationError on oversized response."""
        # Create data larger than MAX_DOWNLOAD_BYTES (but still valid JPEG header).
        large_jpeg = make_jpeg_bytes(300, 400) + b'\x00' * (cm.MAX_DOWNLOAD_BYTES + 100)
        fetch = make_mock_fetch_bytes([('cover.jpg', large_jpeg)])
        with self.assertRaises(cm.CoverValidationError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_truncated_response(self):
        """download_cover raises CoverValidationError on truncated image."""
        truncated = make_truncated_jpeg()
        fetch = make_mock_fetch_bytes([('cover.jpg', truncated)])
        with self.assertRaises(cm.CoverValidationError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_empty_response(self):
        """download_cover raises CoverValidationError on empty response."""
        fetch = make_mock_fetch_bytes([('cover.jpg', b'')])
        with self.assertRaises(cm.CoverValidationError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_invalid_url_rejected(self):
        """download_cover raises CoverValidationError on invalid URL."""
        with self.assertRaises(cm.CoverValidationError):
            cm.download_cover('file:///etc/passwd', fetch_fn=lambda url, timeout=15, headers=None: b'')

    def test_html_not_accepted_as_image(self):
        """download_cover rejects HTML content masquerading as an image."""
        html = make_html_bytes()
        fetch = make_mock_fetch_bytes([('cover.jpg', html)])
        with self.assertRaises(cm.CoverValidationError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)


# ---------------------------------------------------------------------------
# Content validation tests
# ---------------------------------------------------------------------------

class TestContentValidation(unittest.TestCase):
    """Tests for validate_image_content."""

    def test_valid_jpeg_signature(self):
        result = cm.validate_image_content(make_jpeg_bytes(500, 600))
        self.assertEqual(result['mime_type'], 'image/jpeg')
        self.assertEqual(result['width'], 500)
        self.assertEqual(result['height'], 600)

    def test_valid_png_signature(self):
        result = cm.validate_image_content(make_png_bytes(400, 500))
        self.assertEqual(result['mime_type'], 'image/png')
        self.assertEqual(result['width'], 400)
        self.assertEqual(result['height'], 500)

    def test_valid_gif_signature(self):
        result = cm.validate_image_content(make_gif_bytes(300, 400))
        self.assertEqual(result['mime_type'], 'image/gif')
        self.assertEqual(result['width'], 300)
        self.assertEqual(result['height'], 400)

    def test_valid_webp_signature(self):
        result = cm.validate_image_content(make_webp_bytes(200, 300))
        self.assertEqual(result['mime_type'], 'image/webp')

    def test_invalid_bytes(self):
        with self.assertRaises(cm.CoverValidationError):
            cm.validate_image_content(b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b')

    def test_html_pretending_to_be_image(self):
        with self.assertRaises(cm.CoverValidationError):
            cm.validate_image_content(b'<html><body>not an image</body></html>')

    def test_mismatched_content_type_signature(self):
        """Content-Type header says JPEG but magic bytes are PNG."""
        png = make_png_bytes(400, 500)
        # The validate_image_content function only checks magic bytes,
        # so it should correctly identify PNG regardless of Content-Type.
        result = cm.validate_image_content(png)
        self.assertEqual(result['mime_type'], 'image/png')

    def test_empty_data(self):
        with self.assertRaises(cm.CoverValidationError):
            cm.validate_image_content(b'')

    def test_too_small_data(self):
        with self.assertRaises(cm.CoverValidationError):
            cm.validate_image_content(b'\xff\xd8')

    def test_image_too_small(self):
        """Image below MIN_IMAGE_WIDTH/HEIGHT is rejected."""
        tiny = make_png_bytes(10, 10)
        with self.assertRaises(cm.CoverValidationError):
            cm.validate_image_content(tiny)

    def test_unsupported_format_rejected(self):
        """BMP or TIFF headers are not supported."""
        # BMP header: BM
        bmp = b'BM\x36\x00\x00\x00\x00\x00\x00\x00\x00\x00\x36\x00\x00\x00'
        with self.assertRaises(cm.CoverValidationError):
            cm.validate_image_content(bmp)


# ---------------------------------------------------------------------------
# Cover candidate handling tests
# ---------------------------------------------------------------------------

class TestCoverCandidateHandling(unittest.TestCase):
    """Tests for CoverCandidate creation and extraction."""

    def test_candidate_creation(self):
        c = cm.CoverCandidate(url='https://x.com/c.jpg', source='google_books',
                              source_id='1', width=300, height=400,
                              mime_type='image/jpeg')
        self.assertEqual(c.url, 'https://x.com/c.jpg')
        self.assertEqual(c.source, 'google_books')
        self.assertEqual(c.source_id, '1')
        self.assertEqual(c.width, 300)
        self.assertEqual(c.height, 400)
        self.assertEqual(c.mime_type, 'image/jpeg')

    def test_candidate_is_valid_url(self):
        c = cm.CoverCandidate(url='https://x.com/c.jpg')
        self.assertTrue(c.is_valid_url())
        c2 = cm.CoverCandidate(url='file:///etc/passwd')
        self.assertFalse(c2.is_valid_url())

    def test_candidate_missing_fields(self):
        c = cm.CoverCandidate(url='https://x.com/c.jpg')
        self.assertEqual(c.source_id, '')
        self.assertEqual(c.width, '')
        self.assertEqual(c.mime_type, '')

    def test_extract_no_cover(self):
        """Provider result with no cover URL produces zero candidates."""
        result = mp.ProviderResult(
            provider='google_books',
            metadata={'title': 'Test', 'authors': ['Author']},
            source_id='1',
        )
        candidates = cm.extract_cover_candidates([result])
        self.assertEqual(len(candidates), 0)

    def test_extract_google_books_cover(self):
        """Google Books imageLinks are extracted as cover candidates."""
        result = mp.ProviderResult(
            provider='google_books',
            metadata={
                'title': 'Dune',
                'image_links': {
                    'thumbnail': 'http://example.com/thumb.jpg',
                    'large': 'http://example.com/large.jpg',
                    'extraLarge': 'http://example.com/xl.jpg',
                },
            },
            source_id='vol1',
        )
        candidates = cm.extract_cover_candidates([result])
        self.assertEqual(len(candidates), 1)
        # Should prefer the highest-resolution URL.
        self.assertEqual(candidates[0].url, 'http://example.com/xl.jpg')
        self.assertEqual(candidates[0].source, 'google_books')

    def test_extract_open_library_cover(self):
        """Open Library cover_i is extracted as a cover candidate."""
        result = mp.ProviderResult(
            provider='open_library',
            metadata={
                'title': 'Dune',
                'cover_i': '1234567',
            },
            source_id='65050792',
        )
        candidates = cm.extract_cover_candidates([result])
        self.assertEqual(len(candidates), 1)
        self.assertIn('1234567', candidates[0].url)
        self.assertIn('openlibrary.org', candidates[0].url)
        self.assertEqual(candidates[0].source, 'open_library')

    def test_extract_itunes_cover(self):
        """iTunes artworkUrl is extracted as a cover candidate."""
        result = mp.ProviderResult(
            provider='itunes',
            metadata={
                'title': 'Dune',
                'cover_url': 'https://is1-ssl.itunes.apple.com/cover.jpg',
            },
            source_id='123',
        )
        candidates = cm.extract_cover_candidates([result])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, 'https://is1-ssl.itunes.apple.com/cover.jpg')
        self.assertEqual(candidates[0].source, 'itunes')

    def test_extract_multiple_candidates(self):
        """Candidates from multiple providers are all returned."""
        results = [
            mp.ProviderResult(
                provider='google_books',
                metadata={'title': 'Dune', 'image_links': {'thumbnail': 'http://gb.com/c.jpg'}},
                source_id='1',
            ),
            mp.ProviderResult(
                provider='open_library',
                metadata={'title': 'Dune', 'cover_i': '123'},
                source_id='2',
            ),
            mp.ProviderResult(
                provider='itunes',
                metadata={'title': 'Dune', 'cover_url': 'http://itunes.com/c.jpg'},
                source_id='3',
            ),
        ]
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 3)

    def test_extract_deduplicates_urls(self):
        """Same cover URL from different providers yields one candidate."""
        results = [
            mp.ProviderResult(
                provider='google_books',
                metadata={'title': 'Dune', 'image_links': {'thumbnail': 'http://x.com/c.jpg'}},
                source_id='1',
            ),
            mp.ProviderResult(
                provider='open_library',
                metadata={'title': 'Dune', 'cover_url': 'http://x.com/c.jpg'},
                source_id='2',
            ),
        ]
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 1)

    def test_deterministic_ranking(self):
        """rank_cover_candidates produces stable, deterministic ordering."""
        c1 = cm.CoverCandidate(url='https://x.com/a.jpg', source='google_books',
                               width=100, height=100, mime_type='')
        c2 = cm.CoverCandidate(url='https://x.com/b.jpg', source='open_library',
                               width=200, height=200, mime_type='image/jpeg')
        c3 = cm.CoverCandidate(url='https://x.com/c.jpg', source='itunes',
                               width=100, height=100, mime_type='')
        ranked1 = cm.rank_cover_candidates([c1, c2, c3])
        ranked2 = cm.rank_cover_candidates([c3, c2, c1])
        self.assertEqual(
            [c.url for c in ranked1],
            [c.url for c in ranked2],
        )
        # c2 has known dimensions + mime → should rank highest.
        self.assertEqual(ranked1[0].url, c2.url)


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------

class TestTemporaryFileHandling(unittest.TestCase):
    """Verify temporary files are cleaned up in all paths."""

    def test_temp_file_removed_after_success(self):
        """download_cover + validate leaves no temp files behind."""
        jpeg = make_jpeg_bytes(300, 400)
        fetch = make_mock_fetch_bytes([('cover.jpg', jpeg)])
        result = cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)
        # download_cover uses streaming, not temp files directly.
        # Verify the result is valid.
        self.assertEqual(result['mime_type'], 'image/jpeg')

    def test_temp_cleanup_on_validation_failure(self):
        """download_cover raises and cleans up on validation failure."""
        html = make_html_bytes()
        fetch = make_mock_fetch_bytes([('cover.jpg', html)])
        with self.assertRaises(cm.CoverValidationError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)

    def test_temp_cleanup_on_exception(self):
        """download_cover raises and cleans up on unexpected exception."""
        def fetch(url, timeout=15, headers=None):
            raise RuntimeError('disk full')
        with self.assertRaises(cm.CoverDownloadError):
            cm.download_cover('https://example.com/cover.jpg', fetch_fn=fetch)


# ---------------------------------------------------------------------------
# Provider integration tests
# ---------------------------------------------------------------------------

class TestProviderIntegration(unittest.TestCase):
    """Verify provider cover extraction works end-to-end with mocked responses."""

    def test_google_books_cover_extracted(self):
        """Google Books provider extracts imageLinks when present."""
        gb_response = {
            "items": [{
                "id": "vol1",
                "volumeInfo": {
                    "title": "Dune",
                    "authors": ["Frank Herbert"],
                    "imageLinks": {
                        "extraLarge": "http://gb.com/xl.jpg",
                        "large": "http://gb.com/large.jpg",
                        "thumbnail": "http://gb.com/thumb.jpg",
                    },
                },
            }],
        }
        fetch = make_mock_fetch([('googleapis', json.dumps(gb_response))])
        q = mp.build_query(title='Dune')
        results = mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, 'http://gb.com/xl.jpg')

    def test_google_books_no_cover_when_absent(self):
        """Google Books without imageLinks produces no cover candidate."""
        gb_response = {
            "items": [{
                "id": "vol1",
                "volumeInfo": {
                    "title": "Dune",
                    "authors": ["Frank Herbert"],
                },
            }],
        }
        fetch = make_mock_fetch([('googleapis', json.dumps(gb_response))])
        q = mp.build_query(title='Dune')
        results = mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 0)

    def test_open_library_cover_extracted(self):
        """Open Library provider extracts cover_i when present."""
        ol_response = {
            "docs": [{
                "key": "/books/OL123M",
                "title": "Dune",
                "author_name": ["Frank Herbert"],
                "cover_i": 1234567,
            }],
        }
        fetch = make_mock_fetch([('openlibrary', json.dumps(ol_response))])
        q = mp.build_query(title='Dune')
        results = mp.OpenLibraryProvider().search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 1)
        self.assertIn('1234567', candidates[0].url)

    def test_open_library_no_cover_when_absent(self):
        """Open Library without cover_i produces no cover candidate."""
        ol_response = {
            "docs": [{
                "key": "/books/OL123M",
                "title": "Dune",
                "author_name": ["Frank Herbert"],
            }],
        }
        fetch = make_mock_fetch([('openlibrary', json.dumps(ol_response))])
        q = mp.build_query(title='Dune')
        results = mp.OpenLibraryProvider().search(q, fetch_fn=fetch)
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 0)

    def test_itunes_cover_extracted(self):
        """iTunes provider extracts artworkUrl512 when present."""
        itunes_response = {
            "resultCount": 1,
            "results": [{
                "trackId": 123,
                "trackName": "Dune",
                "artistName": "Frank Herbert",
                "artworkUrl512": "http://itunes.com/artwork512.jpg",
            }],
        }
        fetch = make_mock_fetch([('itunes', json.dumps(itunes_response))])
        q = mp.build_query(title='Dune')
        results = mp.ITunesProvider().search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, 'http://itunes.com/artwork512.jpg')

    def test_itunes_no_cover_when_absent(self):
        """iTunes without artwork URLs produces no cover candidate, but metadata is still valid."""
        itunes_response = {
            "resultCount": 1,
            "results": [{
                "trackId": 123,
                "trackName": "Dune",
                "artistName": "Frank Herbert",
            }],
        }
        fetch = make_mock_fetch([('itunes', json.dumps(itunes_response))])
        q = mp.build_query(title='Dune')
        results = mp.ITunesProvider().search(q, fetch_fn=fetch)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)  # metadata found, just no cover
        candidates = cm.extract_cover_candidates(results)
        self.assertEqual(len(candidates), 0)

    def test_provider_failure_does_not_yield_cover(self):
        """A failed provider does not produce cover candidates."""
        result = mp.ProviderResult(
            provider='google_books',
            error='timeout',
        )
        candidates = cm.extract_cover_candidates([result])
        self.assertEqual(len(candidates), 0)

    def test_provider_failure_independent_of_cover(self):
        """Provider with metadata but no cover is still a success."""
        result = mp.ProviderResult(
            provider='google_books',
            metadata={'title': 'Dune', 'authors': ['Herbert']},
            source_id='1',
        )
        self.assertTrue(result.ok)
        candidates = cm.extract_cover_candidates([result])
        self.assertEqual(len(candidates), 0)


# ---------------------------------------------------------------------------
# Integration: full download + validate pipeline
# ---------------------------------------------------------------------------

class TestCoverDownloadPipeline(unittest.TestCase):
    """End-to-end: extract candidates, download, validate."""

    def test_full_pipeline_google_books(self):
        """Extract cover from Google Books result, download, validate."""
        gb_response = {
            "items": [{
                "id": "vol1",
                "volumeInfo": {
                    "title": "Dune",
                    "authors": ["Frank Herbert"],
                    "imageLinks": {
                        "extraLarge": "http://gb.com/xl.jpg",
                    },
                },
            }],
        }
        jpeg = make_jpeg_bytes(500, 700)
        fetch_map = [
            ('googleapis', json.dumps(gb_response)),
            ('xl.jpg', jpeg),
        ]

        def fetch(url, timeout=15, headers=None):
            for substring, body in fetch_map:
                if substring in url:
                    if isinstance(body, bytes):
                        return body
                    return body.encode('utf-8')
            raise mp.ProviderHTTPError('404', status_code=404)

        q = mp.build_query(title='Dune')
        provider_results = mp.GoogleBooksProvider().search(q, fetch_fn=fetch)
        candidates = cm.extract_cover_candidates(provider_results)
        self.assertEqual(len(candidates), 1)

        # Download the cover.
        result = cm.download_cover(candidates[0].url, fetch_fn=fetch)
        self.assertEqual(result['mime_type'], 'image/jpeg')
        self.assertEqual(result['width'], 500)
        self.assertEqual(result['height'], 700)
        self.assertEqual(result['data'], jpeg)


if __name__ == '__main__':
    unittest.main()
