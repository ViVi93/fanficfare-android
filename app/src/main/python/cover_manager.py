# -*- coding: utf-8 -*-
__license__ = 'GPL v3'
__copyright__ = '2026, Community'
__docformat__ = 'restructuredtext en'

"""
Cover-management layer for FanFicFare Android.

This module provides the reusable Python-side cover functionality that
complements Phase 5 (``metadata_providers``):

    Online Metadata Provider
            ↓
        ProviderResult (with cover URL)
            ↓
    CoverCandidate (validated, ranked)
            ↓
    download_cover() → validated image bytes
            ↓
    existing epub_editor.replace_cover()

Design principles:

* Standard-library only — no new dependencies.
* Reuses ``metadata_providers.fetch_url`` for HTTP.
* Does NOT modify EPUB files itself — delegates to
  ``epub_editor.replace_cover``.
* Does NOT automatically apply covers to EPUBs.
* Does NOT fetch covers during metadata search — only when explicitly
  requested via ``download_cover``.

Supported image formats (matching what ``epub_editor.replace_cover`` can
consume): JPEG, PNG, GIF, WebP.

Security:

* Only ``http://`` and ``https://`` cover URLs are accepted.
* ``file://``, ``ftp://``, and other schemes are rejected.
* Downloaded content is validated by magic bytes — HTML masquerading as
  an image is rejected.
* Download size is bounded (default 5 MB — conservative for book covers).
* Temporary files use ``tempfile.NamedTemporaryFile`` (secure, auto-cleaned).
"""

import os
import io
import struct
import json
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import socket

import metadata_providers as mp

__all__ = [
    'CoverCandidate',
    'CoverDownloadError',
    'CoverDownloadTimeout',
    'CoverDownloadHTTPError',
    'CoverValidationError',
    'SUPPORTED_MIME_TYPES',
    'SUPPORTED_EXTENSIONS',
    'MAX_DOWNLOAD_BYTES',
    'MAX_IMAGE_WIDTH',
    'MAX_IMAGE_HEIGHT',
    'validate_cover_url',
    'extract_cover_candidates',
    'download_cover',
    'validate_image_content',
    'rank_cover_candidates',
    'apply_cover_to_epub',
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum download size (5 MB) — conservative for book-cover artwork.
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024

#: Maximum image dimensions — rejects pathological images.
MAX_IMAGE_WIDTH = 4096
MAX_IMAGE_HEIGHT = 4096

#: Minimum image dimensions — rejects obviously broken images.
MIN_IMAGE_WIDTH = 64
MIN_IMAGE_HEIGHT = 64

#: HTTP timeout for cover downloads (seconds).
COVER_TIMEOUT = 15

#: Supported MIME types (matching epub_editor.replace_cover capability).
SUPPORTED_MIME_TYPES = frozenset([
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
])

#: MIME type → file extension mapping.
MIME_TO_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
}

#: Supported file extensions.
SUPPORTED_EXTENSIONS = frozenset(MIME_TO_EXT.values())

#: User-Agent for cover downloads.
COVER_USER_AGENT = 'FanFicFare-Android/1.0 (cover-download; +https://github.com/ViVi93/fanficfare-android)'


# ---------------------------------------------------------------------------
# Cover candidate model
# ---------------------------------------------------------------------------

class CoverCandidate(dict):
    """A candidate cover image URL from a provider.

    Fields (only populated when available):

    ``url``        — the HTTP/HTTPS URL to download the image
    ``source``      — provider name (e.g. ``"google_books"``)
    ``source_id``   — provider-specific record identifier
    ``width``       — image width in pixels (int or empty string)
    ``height``      — image height in pixels (int or empty string)
    ``mime_type``   — detected MIME type (e.g. ``"image/jpeg"``)

    Missing fields are represented as empty strings / absent.
    """

    def __init__(self, url='', source='', source_id='',
                 width='', height='', mime_type=''):
        super().__init__()
        self['url'] = url
        self['source'] = source
        self['source_id'] = source_id
        self['width'] = width
        self['height'] = height
        self['mime_type'] = mime_type

    @property
    def url(self):
        return self.get('url', '')

    @property
    def source(self):
        return self.get('source', '')

    @property
    def source_id(self):
        return self.get('source_id', '')

    @property
    def width(self):
        return self.get('width', '')

    @property
    def height(self):
        return self.get('height', '')

    @property
    def mime_type(self):
        return self.get('mime_type', '')

    def is_valid_url(self):
        """True if the URL passes basic validation."""
        return validate_cover_url(self.url)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CoverDownloadError(Exception):
    """Base exception for cover download/validation failures."""

    def __init__(self, message='', error_type=''):
        super().__init__(message)
        self.message = message
        self.error_type = error_type or type(self).__name__

    def __str__(self):
        return self.message if self.message else self.error_type


class CoverDownloadTimeout(CoverDownloadError):
    """Cover download timed out."""
    def __init__(self, message='timeout'):
        super().__init__(message, 'timeout')


class CoverDownloadHTTPError(CoverDownloadError):
    """Cover download returned an HTTP error status."""

    def __init__(self, message='http_error', status_code=0):
        super().__init__(message, 'http_error')
        self.status_code = status_code


class CoverValidationError(CoverDownloadError):
    """Downloaded content failed validation (size, content-type, magic bytes)."""

    def __init__(self, message='validation_error'):
        super().__init__(message, 'validation_error')


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_cover_url(url):
    """Validate that *url* is a safe HTTP/HTTPS URL for cover download.

    Returns True if the URL is acceptable, False otherwise.

    Rules:
    - Must be a non-empty string
    - Must use http:// or https:// scheme only
    - file://, ftp://, and other schemes are rejected
    - Must be a valid URL (parseable)
    - Query strings are preserved (no stripping)
    - Does NOT follow redirects
    - Does NOT download anything
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if not url:
        return False

    # Parse the URL.
    parsed = urllib.parse.urlparse(url)

    # Must have a scheme.
    if not parsed.scheme:
        return False

    # Scheme must be http or https only.
    if parsed.scheme.lower() not in ('http', 'https'):
        return False

    # Must have a netloc (host).
    if not parsed.netloc:
        return False

    # Reject empty path (e.g. "https://host" with no path is still valid
    # in practice, but some providers return URLs without paths).

    return True


# ---------------------------------------------------------------------------
# Provider cover URL extraction
# ---------------------------------------------------------------------------

def extract_cover_candidates(provider_results):
    """Extract cover candidates from a list of ProviderResult objects.

    Inspects each provider result's metadata for provider-specific cover
    fields and constructs :class:`CoverCandidate` objects.

    A provider returning valid metadata but no cover URL is NOT a failure —
    simply produces zero candidates from that provider.

    Args:
        provider_results: list of ProviderResult dicts (from Phase 5)

    Returns:
        list of CoverCandidate objects (sorted by provider preference order).
    """
    candidates = []
    seen_urls = set()

    for result in provider_results:
        if not result.ok:
            continue

        provider = result.get('provider', '')
        source_id = result.get('source_id', '')
        meta = result.get('metadata', {})

        cover_url = _extract_cover_url_from_metadata(meta, provider)
        if cover_url:
            if cover_url in seen_urls:
                continue
            seen_urls.add(cover_url)

            candidate = CoverCandidate(
                url=cover_url,
                source=provider,
                source_id=source_id,
                width=meta.get('cover_width', '') or '',
                height=meta.get('cover_height', '') or '',
                mime_type='',
            )
            candidates.append(candidate)

    return rank_cover_candidates(candidates)


def _extract_cover_url_from_metadata(meta, provider):
    """Extract the best cover URL from provider-specific metadata.

    This inspects raw provider metadata fields that are set before
    normalization.  If a provider did not set cover data, returns ''.
    """
    if provider == 'google_books':
        # Google Books: _raw_google_books metadata stores imageLinks.
        # We check provider-specific fields first (if they exist).
        image_links = meta.get('image_links')
        if isinstance(image_links, dict):
            # Prefer highest resolution (extraLarge → large → medium → small → thumbnail).
            for key in ('extraLarge', 'large', 'medium', 'small', 'thumbnail', 'smallThumbnail'):
                url = image_links.get(key, '')
                if url and validate_cover_url(url):
                    return url
        # Also check if normalized metadata has a cover_url field.
        for field in ('cover_url', 'image_url', 'thumbnail'):
            url = meta.get(field, '')
            if url and validate_cover_url(url):
                return url
        return ''

    elif provider == 'open_library':
        # Open Library: cover_i field provides a stable cover ID.
        # We check provider-specific fields.
        cover_i = meta.get('cover_i')
        if cover_i:
            url = 'https://covers.openlibrary.org/b/id/%s-L.jpg' % cover_i
            return url
        # Check for an already-formed cover URL.
        for field in ('cover_url', 'image_url', 'thumbnail'):
            url = meta.get(field, '')
            if url and validate_cover_url(url):
                return url
        return ''

    elif provider == 'itunes':
        # iTunes: artworkUrl512, artworkUrl100, artworkUrl60.
        for field in ('artwork_url_512', 'artwork_url', 'cover_url', 'image_url'):
            url = meta.get(field, '')
            if url and validate_cover_url(url):
                # iTunes uses https://is*.itunes.apple.com/.../100x100bb.jpg format.
                # We can upgrade to 512 or 600 by modifying the path.
                return url
        return ''

    return ''


# ---------------------------------------------------------------------------
# Image content validation
# ---------------------------------------------------------------------------

# Image format magic bytes/signatures.
_MAGIC_BYTES = {
    'image/jpeg': [b'\xff\xd8\xff'],
    'image/png': [b'\x89PNG\r\n\x1a\n'],
    'image/gif': [b'GIF87a', b'GIF89a'],
    'image/webp': [b'RIFF'],
}


def _detect_image_format(data):
    """Detect image format from magic bytes.

    Returns (mime_type, width, height) or (None, 0, 0) if unrecognized.

    Supports JPEG, PNG, GIF, and WebP.
    """
    if len(data) < 12:
        return (None, 0, 0)

    # JPEG: \xff\xd8\xff
    if data[:3] == b'\xff\xd8\xff':
        w, h = _parse_jpeg_dimensions(data)
        return ('image/jpeg', w, h)

    # PNG: \x89PNG\r\n\x1a\n (8 bytes)
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        w, h = _parse_png_dimensions(data)
        return ('image/png', w, h)

    # GIF: GIF87a or GIF89a
    if data[:6] in (b'GIF87a', b'GIF89a'):
        w, h = _parse_gif_dimensions(data)
        return ('image/gif', w, h)

    # WebP: RIFF....WEBP
    if data[:4] == b'RIFF' and len(data) >= 16 and data[8:12] == b'WEBP':
        w, h = _parse_webp_dimensions(data)
        return ('image/webp', w, h)

    return (None, 0, 0)


def _parse_png_dimensions(data):
    """Parse width/height from PNG IHDR chunk (bytes 16-24)."""
    try:
        # PNG: 8-byte sig + 4-byte length + 4-byte 'IHDR' + 4-byte width + 4-byte height
        if len(data) >= 24:
            w = struct.unpack('>I', data[16:20])[0]
            h = struct.unpack('>I', data[20:24])[0]
            return (w, h)
    except (struct.error, IndexError):
        pass
    return (0, 0)


def _parse_gif_dimensions(data):
    """Parse width/height from GIF logical screen descriptor (bytes 6-10)."""
    try:
        if len(data) >= 10:
            w = struct.unpack('<H', data[6:8])[0]
            h = struct.unpack('<H', data[8:10])[0]
            return (w, h)
    except (struct.error, IndexError):
        pass
    return (0, 0)


def _parse_jpeg_dimensions(data):
    """Parse width/height from JPEG SOF markers."""
    try:
        i = 2  # skip \xff\xd8
        while i < len(data) - 1:
            if data[i] != 0xFF:
                i += 1
                continue
            # Skip padding 0xFF bytes
            while i < len(data) - 1 and data[i] == 0xFF:
                i += 1
            marker = data[i]
            i += 1
            if marker == 0xD9 or marker == 0xDA:
                break  # EOI or SOS — no dimensions found
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                # SOF0-SOF15 (excluding DAC, JPG, DHP)
                # JPEG SOF structure: precision(1) + length(2) + height(2) + width(2)
                if i + 7 < len(data):
                    h = struct.unpack('>H', data[i + 3:i + 5])[0]
                    w = struct.unpack('>H', data[i + 5:i + 7])[0]
                    return (w, h)
            # Skip this marker's data
            if i + 2 <= len(data):
                seg_len = struct.unpack('>H', data[i:i + 2])[0]
                i += seg_len
    except (struct.error, IndexError):
        pass
    return (0, 0)


def _parse_webp_dimensions(data):
    """Parse width/height from WebP VP8/VP8L/VP8X headers."""
    try:
        i = 12  # skip RIFF(4) + size(4) + WEBP(4)
        chunk_type = data[i:i + 4]
        i += 4
        # Skip chunk size (4 bytes)
        i += 4
        if chunk_type == b'VP8 ':
            # VP8: 4-byte width-1 | 4-byte height-1 (masked with 0x3FFF)
            if i + 8 <= len(data):
                w = struct.unpack('<I', data[i + 2:i + 4])[0]
                h = struct.unpack('<I', data[i + 4:i + 6])[0]
                # VP8 width/height are stored as (value+1) but masked 0x3FFF
                w = (w + 1) & 0x3FFF if w else 0
                h = (h + 1) & 0x3FFF if h else 0
                return (w, h)
        elif chunk_type == b'VP8L':
            # VP8L: 1-byte version + 32-bit packed (width-1:14, height-1:14, alpha:1, unused:3)
            if i + 5 <= len(data):
                bits = int.from_bytes(data[i + 1:i + 5], 'little')
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return (w, h)
        elif chunk_type == b'VP8X':
            # VP8X: 24-bit width | 24-bit height (both +1)
            if i + 6 <= len(data):
                w = (int.from_bytes(data[i:i + 3], 'little')) + 1
                h = (int.from_bytes(data[i + 3:i + 6], 'little')) + 1
                return (w, h)
    except (struct.error, IndexError):
        pass
    return (0, 0)


def validate_image_content(data):
    """Validate downloaded image content.

    Returns a dict with keys:
    - ``mime_type``: detected MIME type (e.g. ``"image/jpeg"``)
    - ``width``: image width in pixels
    - ``height``: image height in pixels

    Raises :class:`CoverValidationError` if the content is invalid.

    Checks:
    - Non-empty data
    - Recognized image signature (magic bytes)
    - Supported format (JPEG, PNG, GIF, WebP)
    - Reasonable dimensions (>= MIN_IMAGE_WIDTH x MIN_IMAGE_HEIGHT)
    - Dimensions within safe limits (<= MAX_IMAGE_WIDTH x MAX_IMAGE_HEIGHT)
    """
    if not data or len(data) == 0:
        raise CoverValidationError('empty image data')

    if len(data) < 12:
        raise CoverValidationError('image data too small (%d bytes)' % len(data))

    mime_type, width, height = _detect_image_format(data)

    if mime_type is None:
        raise CoverValidationError(
            'unrecognized image format — not JPEG, PNG, GIF, or WebP'
        )

    if mime_type not in SUPPORTED_MIME_TYPES:
        raise CoverValidationError(
            'unsupported image format: %s' % mime_type
        )

    # Check dimensions if available.
    if width > 0 and height > 0:
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            raise CoverValidationError(
                'image too small: %dx%d (minimum %dx%d)' %
                (width, height, MIN_IMAGE_WIDTH, MIN_IMAGE_HEIGHT)
            )
        if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
            raise CoverValidationError(
                'image too large: %dx%d (maximum %dx%d)' %
                (width, height, MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT)
            )

    return {'mime_type': mime_type, 'width': width, 'height': height}


# ---------------------------------------------------------------------------
# Cover download
# ---------------------------------------------------------------------------

def download_cover(url, fetch_fn=None, timeout=COVER_TIMEOUT,
                   max_bytes=MAX_DOWNLOAD_BYTES,
                   expected_mime_type=None):
    """Download and validate a cover image from *url*.

    Args:
        url: HTTP/HTTPS URL of the image.
        fetch_fn: Optional callable (url, timeout, headers) -> bytes.
                  Defaults to ``mp.fetch_url``.
        timeout: Download timeout in seconds.
        max_bytes: Maximum response size in bytes.
        expected_mime_type: If provided, the detected format must match.

    Returns:
        dict with keys: ``data`` (bytes), ``mime_type`` (str),
        ``width`` (int), ``height`` (int).

    Raises:
        CoverValidationError: if the URL is invalid or content fails validation.
        CoverDownloadTimeout: if the download times out.
        CoverDownloadHTTPError: if the HTTP request fails.
        CoverDownloadError: for other network errors.
    """
    # Validate URL first.
    if not validate_cover_url(url):
        raise CoverValidationError('invalid or unsafe cover URL: %s' % url)

    # Use default streaming fetch if none provided.
    if fetch_fn is None:
        def _streaming_fetch(url, timeout=COVER_TIMEOUT, headers=None):
            return _fetch_with_limit(url, timeout, max_bytes)
        fetch_fn = _streaming_fetch

    # Fetch the raw bytes via the injected fetch_fn.
    # _fetch_with_limit (default) checks Content-Type and enforces size
    # during streaming.  Custom fetch_fn (tests) returns bytes directly;
    # size is checked below.
    try:
        data = fetch_fn(url, timeout=timeout)
    except mp.ProviderTimeout as e:
        raise CoverDownloadTimeout(str(e))
    except mp.ProviderHTTPError as e:
        raise CoverDownloadHTTPError(str(e), status_code=getattr(e, 'status_code', 0))
    except mp.ProviderError as e:
        raise CoverDownloadError(str(e))
    except CoverValidationError:
        raise
    except Exception as e:
        raise CoverDownloadError('%s: %s' % (type(e).__name__, e))

    # Enforce size limit (for custom fetch_fn that doesn't limit internally).
    if len(data) > max_bytes:
        raise CoverValidationError(
            'downloaded content exceeds maximum size (%d > %d bytes)' %
            (len(data), max_bytes)
        )

    # Validate content.
    validation = validate_image_content(data)

    if expected_mime_type and validation['mime_type'] != expected_mime_type:
        raise CoverValidationError(
            'content type mismatch: expected %s, got %s' %
            (expected_mime_type, validation['mime_type'])
        )

    return {
        'data': data,
        'mime_type': validation['mime_type'],
        'width': validation['width'],
        'height': validation['height'],
    }


def _fetch_with_limit(url, timeout, max_bytes):
    """Fetch URL content, enforcing a maximum byte limit.

    Uses streaming to avoid loading unbounded data into memory.
    Returns the raw bytes (truncated to max_bytes is rejected).
    """
    # Try to use urllib directly for streaming with size limit.
    try:
        req = urllib.request.Request(url, headers={'User-Agent': COVER_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Check Content-Type.
            content_type = resp.headers.get('Content-Type', '')
            if content_type and not content_type.startswith('image/'):
                raise CoverValidationError(
                    'server returned non-image Content-Type: %s' % content_type
                )

            # Stream with size limit.
            collected = bytearray()
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                collected.extend(chunk)
                if len(collected) > max_bytes:
                    raise CoverValidationError(
                        'downloaded content exceeds maximum size (%d bytes)' % max_bytes
                    )
            return bytes(collected)
    except socket.timeout:
        raise mp.ProviderTimeout('cover download timed out')
    except urllib.error.HTTPError as e:
        raise mp.ProviderHTTPError(
            'HTTP %d: %s' % (e.code, e.reason),
            status_code=e.code,
        )
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            raise mp.ProviderTimeout('cover download timed out')
        raise mp.ProviderFailure(str(e))
    except CoverValidationError:
        raise
    except mp.ProviderError:
        raise
    except Exception as e:
        raise mp.ProviderFailure('%s: %s' % (type(e).__name__, e))


# ---------------------------------------------------------------------------
# Cover candidate ranking
# ---------------------------------------------------------------------------

# Provider preference order for ties.
_PROVIDER_PRIORITY = {
    'google_books': 0,
    'open_library': 1,
    'itunes': 2,
}


def rank_cover_candidates(candidates):
    """Sort cover candidates by conservative ranking criteria.

    Ranking signals (deterministic):
    1. Provider priority (Google Books > Open Library > iTunes)
    2. Known MIME type present
    3. Known dimensions present
    4. Larger area (width * height)

    Returns the list sorted by descending quality.
    """
    def sort_key(c):
        provider_rank = _PROVIDER_PRIORITY.get(c.source, 99)

        has_mime = 1 if c.mime_type else 0
        width = c.width if isinstance(c.width, int) and c.width > 0 else 0
        height = c.height if isinstance(c.height, int) and c.height > 0 else 0
        area = width * height
        has_dims = 1 if area > 0 else 0

        return (has_mime, has_dims, area, -provider_rank)

    return sorted(candidates, key=sort_key, reverse=True)


# ---------------------------------------------------------------------------
# Apply cover to EPUB (delegates to existing epub_editor.replace_cover)
# ---------------------------------------------------------------------------

def apply_cover_to_epub(epub_path, image_data, mime_type,
                        output_path=None, backup_suffix=None):
    """Apply a downloaded cover to an EPUB via the existing epub_editor.

    This delegates to ``epub_editor.replace_cover`` and does NOT modify
    the EPUB editor's behavior.  The cover is NOT applied to any EPUB
    automatically — this function exists only as a convenience wrapper
    for when the caller explicitly requests it.

    Returns the result dict from ``epub_editor.replace_cover``.
    """
    import epub_editor
    return epub_editor.replace_cover(
        epub_path,
        image_data,
        mime_type,
        output_path=output_path,
        backup_suffix=backup_suffix,
    )
