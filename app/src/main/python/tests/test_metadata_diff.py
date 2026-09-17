# -*- coding: utf-8 -*-
"""Tests for the metadata_diff module.

Run with:
    cd /home/ubuntu/workspace/fanficfare-android/app/src/main/python
    /tmp/ff_venv/bin/python3 -m unittest tests.test_metadata_diff -v
"""
import sys
import os
import json

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import unittest
from metadata_diff import diff_metadata, get_changes, has_changed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_metadata():
    """Return a realistic metadata dict matching epub_editor.read_metadata_fields."""
    return {
        'title': 'Test Book Title',
        'authors': ['Test Author One', 'Test Author Two'],
        'languages': ['en'],
        'publisher': 'Test Publisher',
        'description': 'A test description.',
        'tags': ['fiction', 'adventure'],
        'series': 'Test Series',
        'series_index': '2',
        'rating': '4.5',
        'identifiers': {
            '_primary_id': 'bookid',
            'bookid': 'urn:uuid:test-id-12345',
            'isbn': '978-1234567890',
        },
        'isbn': '978-1234567890',
        'pubdate': '2023-01-15',
        'rights': 'Test rights',
    }


# ---------------------------------------------------------------------------
# Scalar fields
# ---------------------------------------------------------------------------

class TestScalarFields(unittest.TestCase):
    def test_identical_title(self):
        before = _base_metadata()
        after = _base_metadata()
        result = diff_metadata(before, after)
        self.assertFalse(result['changed'])
        self.assertEqual(result['changes'], [])

    def test_changed_title(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'New Title'
        result = diff_metadata(before, after)
        self.assertTrue(result['changed'])
        changes = result['changes']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['field'], 'title')
        self.assertEqual(changes[0]['change_type'], 'changed')
        self.assertEqual(changes[0]['before'], 'Test Book Title')
        self.assertEqual(changes[0]['after'], 'New Title')

    def test_title_added(self):
        before = _base_metadata()
        del before['title']
        after = _base_metadata()
        result = diff_metadata(before, after)
        self.assertTrue(result['changed'])
        changes = result['changes']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['field'], 'title')
        self.assertEqual(changes[0]['change_type'], 'added')
        self.assertIsNone(changes[0]['before'])
        self.assertEqual(changes[0]['after'], 'Test Book Title')

    def test_title_removed(self):
        before = _base_metadata()
        after = _base_metadata()
        del after['title']
        result = diff_metadata(before, after)
        self.assertTrue(result['changed'])
        changes = result['changes']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['field'], 'title')
        self.assertEqual(changes[0]['change_type'], 'removed')
        self.assertEqual(changes[0]['before'], 'Test Book Title')
        self.assertIsNone(changes[0]['after'])

    def test_empty_string_to_value_is_added(self):
        before = _base_metadata()
        before['publisher'] = ''
        after = _base_metadata()
        result = diff_metadata(before, after)
        changes = result['changes']
        # publisher was empty, now has value
        pub_change = [c for c in changes if c['field'] == 'publisher']
        self.assertEqual(len(pub_change), 1)
        self.assertEqual(pub_change[0]['change_type'], 'added')

    def test_value_to_empty_string_is_removed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['rights'] = ''
        result = diff_metadata(before, after)
        changes = result['changes']
        rights_change = [c for c in changes if c['field'] == 'rights']
        self.assertEqual(len(rights_change), 1)
        self.assertEqual(rights_change[0]['change_type'], 'removed')

    def test_none_is_treated_as_empty(self):
        before = _base_metadata()
        before['rating'] = None
        after = _base_metadata()
        result = diff_metadata(before, after)
        changes = result['changes']
        rating_change = [c for c in changes if c['field'] == 'rating']
        self.assertEqual(len(rating_change), 1)
        self.assertEqual(rating_change[0]['change_type'], 'added')


# ---------------------------------------------------------------------------
# List fields
# ---------------------------------------------------------------------------

class TestListFields(unittest.TestCase):
    def test_identical_subjects(self):
        before = _base_metadata()
        after = _base_metadata()
        result = diff_metadata(before, after)
        self.assertFalse(result['changed'])

    def test_subject_added(self):
        before = _base_metadata()
        after = _base_metadata()
        after['tags'].append('mystery')
        result = diff_metadata(before, after)
        changes = result['changes']
        tags_change = [c for c in changes if c['field'] == 'tags']
        self.assertEqual(len(tags_change), 1)
        self.assertIn('added', tags_change[0])
        self.assertIn('mystery', tags_change[0]['added'])

    def test_subject_removed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['tags'].remove('fiction')
        result = diff_metadata(before, after)
        changes = result['changes']
        tags_change = [c for c in changes if c['field'] == 'tags']
        self.assertEqual(len(tags_change), 1)
        self.assertIn('removed', tags_change[0])
        self.assertIn('fiction', tags_change[0]['removed'])

    def test_multiple_subjects_added_removed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['tags'] = ['fantasy', 'adventure', 'mystery']
        result = diff_metadata(before, after)
        changes = result['changes']
        tags_change = [c for c in changes if c['field'] == 'tags']
        self.assertEqual(len(tags_change), 1)
        # 'fiction' was removed, 'fantasy' and 'mystery' were added
        self.assertIn('fiction', tags_change[0].get('removed', []))
        self.assertIn('fantasy', tags_change[0].get('added', []))
        self.assertIn('mystery', tags_change[0].get('added', []))

    def test_ordering_change(self):
        before = _base_metadata()
        after = _base_metadata()
        after['authors'] = ['Test Author Two', 'Test Author One']
        result = diff_metadata(before, after)
        changes = result['changes']
        author_change = [c for c in changes if c['field'] == 'authors']
        self.assertEqual(len(author_change), 1)
        # Should be 'changed' with added/removed empty (pure reorder)
        self.assertEqual(author_change[0]['change_type'], 'changed')
        self.assertEqual(author_change[0]['before'], before['authors'])
        self.assertEqual(author_change[0]['after'], after['authors'])
        self.assertEqual(author_change[0].get('added', []), [])
        self.assertEqual(author_change[0].get('removed', []), [])

    def test_author_change(self):
        before = _base_metadata()
        after = _base_metadata()
        after['authors'] = ['New Author']
        result = diff_metadata(before, after)
        changes = result['changes']
        author_change = [c for c in changes if c['field'] == 'authors']
        self.assertEqual(len(author_change), 1)
        self.assertEqual(author_change[0]['change_type'], 'changed')

    def test_contributor_change(self):
        # FanFicFare doesn't have a 'contributors' field but the spec mentions
        # it. Test with a metadata dict that has it as an extra field.
        before = _base_metadata()
        before['contributors'] = ['Editor A']
        after = _base_metadata()
        after['contributors'] = ['Editor A', 'Translator B']
        result = diff_metadata(before, after)
        changes = result['changes']
        contrib_change = [c for c in changes if c['field'] == 'contributors']
        self.assertEqual(len(contrib_change), 1)
        self.assertEqual(contrib_change[0]['change_type'], 'changed')

    def test_empty_list_to_nonempty(self):
        before = _base_metadata()
        before['languages'] = []
        after = _base_metadata()
        result = diff_metadata(before, after)
        changes = result['changes']
        lang_change = [c for c in changes if c['field'] == 'languages']
        self.assertEqual(len(lang_change), 1)
        self.assertEqual(lang_change[0]['change_type'], 'changed')


# ---------------------------------------------------------------------------
# Dictionary / nested structures
# ---------------------------------------------------------------------------

class TestDictFields(unittest.TestCase):
    def test_identical_identifiers(self):
        before = _base_metadata()
        after = _base_metadata()
        result = diff_metadata(before, after)
        self.assertFalse(result['changed'])

    def test_identifier_added(self):
        before = _base_metadata()
        after = _base_metadata()
        after['identifiers']['asin'] = 'B0123456789'
        result = diff_metadata(before, after)
        changes = result['changes']
        ident_change = [c for c in changes if c['field'] == 'identifiers']
        self.assertEqual(len(ident_change), 1)
        self.assertIn('asin', dict(ident_change[0]['added_keys']))

    def test_identifier_removed(self):
        before = _base_metadata()
        after = _base_metadata()
        del after['identifiers']['isbn']
        result = diff_metadata(before, after)
        changes = result['changes']
        ident_change = [c for c in changes if c['field'] == 'identifiers']
        self.assertEqual(len(ident_change), 1)
        self.assertTrue(any(k == 'isbn' for k, v in ident_change[0]['removed_keys']))

    def test_identifier_value_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['identifiers']['isbn'] = '978-0987654321'
        result = diff_metadata(before, after)
        changes = result['changes']
        ident_change = [c for c in changes if c['field'] == 'identifiers']
        self.assertEqual(len(ident_change), 1)
        self.assertTrue(any(k == 'isbn' for k, v, w in ident_change[0]['changed_keys']))

    def test_multiple_identifiers_preserved_and_compared(self):
        before = _base_metadata()
        before['identifiers'] = {
            '_primary_id': 'bookid',
            'bookid': 'urn:uuid:test-id-12345',
            'isbn': '978-1234567890',
            'asin': 'B0123456789',
        }
        after = _base_metadata()
        after['identifiers'] = {
            '_primary_id': 'bookid',
            'bookid': 'urn:uuid:test-id-12345',
            'isbn': '978-1234567890',
            'asin': 'B0987654321',  # changed
            'google': 'test_google_id',  # added
        }
        result = diff_metadata(before, after)
        changes = result['changes']
        ident_change = [c for c in changes if c['field'] == 'identifiers']
        self.assertEqual(len(ident_change), 1)
        # asin changed, google added, isbn unchanged
        changed_keys = [k for k, v, w in ident_change[0]['changed_keys']]
        added_keys = [k for k, v in ident_change[0]['added_keys']]
        self.assertIn('asin', changed_keys)
        self.assertIn('google', added_keys)
        self.assertNotIn('isbn', changed_keys)
        self.assertNotIn('isbn', added_keys)


# ---------------------------------------------------------------------------
# Calibre metadata
# ---------------------------------------------------------------------------

class TestCalibreMetadata(unittest.TestCase):
    def test_rating_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['rating'] = '5'
        result = diff_metadata(before, after)
        changes = result['changes']
        rating_change = [c for c in changes if c['field'] == 'rating']
        self.assertEqual(len(rating_change), 1)
        self.assertEqual(rating_change[0]['change_type'], 'changed')
        self.assertEqual(rating_change[0]['before'], '4.5')
        self.assertEqual(rating_change[0]['after'], '5')

    def test_series_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['series'] = 'New Series'
        result = diff_metadata(before, after)
        changes = result['changes']
        series_change = [c for c in changes if c['field'] == 'series']
        self.assertEqual(len(series_change), 1)
        self.assertEqual(series_change[0]['change_type'], 'changed')

    def test_series_index_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['series_index'] = '3'
        result = diff_metadata(before, after)
        changes = result['changes']
        si_change = [c for c in changes if c['field'] == 'series_index']
        self.assertEqual(len(si_change), 1)
        self.assertEqual(si_change[0]['change_type'], 'changed')
        self.assertEqual(si_change[0]['before'], '2')
        self.assertEqual(si_change[0]['after'], '3')


# ---------------------------------------------------------------------------
# Other metadata fields
# ---------------------------------------------------------------------------

class TestOtherFields(unittest.TestCase):
    def test_description_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['description'] = 'Updated description.'
        result = diff_metadata(before, after)
        changes = result['changes']
        desc_change = [c for c in changes if c['field'] == 'description']
        self.assertEqual(len(desc_change), 1)
        self.assertEqual(desc_change[0]['change_type'], 'changed')

    def test_publisher_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['publisher'] = 'New Publisher'
        result = diff_metadata(before, after)
        changes = result['changes']
        pub_change = [c for c in changes if c['field'] == 'publisher']
        self.assertEqual(len(pub_change), 1)
        self.assertEqual(pub_change[0]['change_type'], 'changed')

    def test_language_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['languages'] = ['fr']
        result = diff_metadata(before, after)
        changes = result['changes']
        lang_change = [c for c in changes if c['field'] == 'languages']
        self.assertEqual(len(lang_change), 1)
        self.assertEqual(lang_change[0]['change_type'], 'changed')

    def test_date_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['pubdate'] = '2024-06-01'
        result = diff_metadata(before, after)
        changes = result['changes']
        date_change = [c for c in changes if c['field'] == 'pubdate']
        self.assertEqual(len(date_change), 1)
        self.assertEqual(date_change[0]['change_type'], 'changed')

    def test_rights_changed(self):
        before = _base_metadata()
        after = _base_metadata()
        after['rights'] = 'New copyright info'
        result = diff_metadata(before, after)
        changes = result['changes']
        rights_change = [c for c in changes if c['field'] == 'rights']
        self.assertEqual(len(rights_change), 1)
        self.assertEqual(rights_change[0]['change_type'], 'changed')

    def test_source_url_changed(self):
        # FanFicFare uses identifiers for URL
        before = _base_metadata()
        after = _base_metadata()
        after['identifiers']['_primary_id'] = 'new-source-url'
        result = diff_metadata(before, after)
        changes = result['changes']
        ident_change = [c for c in changes if c['field'] == 'identifiers']
        self.assertEqual(len(ident_change), 1)


# ---------------------------------------------------------------------------
# Empty / missing values
# ---------------------------------------------------------------------------

class TestEmptyMissingValues(unittest.TestCase):
    def test_missing_to_populated(self):
        before = _base_metadata()
        del before['isbn']
        result = diff_metadata(before, _base_metadata())
        changes = result['changes']
        isbn_change = [c for c in changes if c['field'] == 'isbn']
        self.assertEqual(len(isbn_change), 1)
        self.assertEqual(isbn_change[0]['change_type'], 'added')

    def test_populated_to_missing(self):
        before = _base_metadata()
        after = _base_metadata()
        del after['isbn']
        result = diff_metadata(before, after)
        changes = result['changes']
        isbn_change = [c for c in changes if c['field'] == 'isbn']
        self.assertEqual(len(isbn_change), 1)
        self.assertEqual(isbn_change[0]['change_type'], 'removed')

    def test_none_key_absent(self):
        before = _base_metadata()
        before['rating'] = None
        after = _base_metadata()
        result = diff_metadata(before, after)
        # None should be treated as absent, so it's an 'added'
        changes = result['changes']
        rating_change = [c for c in changes if c['field'] == 'rating']
        self.assertEqual(len(rating_change), 1)
        self.assertEqual(rating_change[0]['change_type'], 'added')

    def test_empty_list_handling(self):
        before = _base_metadata()
        before['tags'] = []
        after = _base_metadata()
        result = diff_metadata(before, after)
        changes = result['changes']
        tags_change = [c for c in changes if c['field'] == 'tags']
        self.assertEqual(len(tags_change), 1)
        self.assertEqual(tags_change[0]['change_type'], 'changed')

    def test_empty_dict_handling(self):
        before = _base_metadata()
        before['identifiers'] = {}
        after = _base_metadata()
        result = diff_metadata(before, after)
        # Empty dict is treated as absent, so it's 'added'
        changes = result['changes']
        ident_change = [c for c in changes if c['field'] == 'identifiers']
        self.assertEqual(len(ident_change), 1)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):
    def test_inputs_not_mutated(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'New Title'
        after['tags'].append('new-tag')
        original_before_title = before['title']
        original_after_tags_len = len(after['tags'])
        diff_metadata(before, after)
        # Verify inputs are unchanged.
        self.assertEqual(before['title'], original_before_title)
        self.assertEqual(len(after['tags']), original_after_tags_len)

    def test_repeated_comparison_identical_output(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'Changed'
        result1 = diff_metadata(before, before.copy() if False else after)
        result2 = diff_metadata(before, after.copy())
        self.assertEqual(result1, result2)

    def test_output_ordering_deterministic(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'Changed'
        after['publisher'] = 'New'
        result1 = diff_metadata(before, after)
        result2 = diff_metadata(before, after)
        fields1 = [c['field'] for c in result1['changes']]
        fields2 = [c['field'] for c in result2['changes']]
        self.assertEqual(fields1, fields2)

    def test_type_changes_do_not_crash(self):
        before = _base_metadata()
        before['series_index'] = '5'  # string
        after = _base_metadata()
        after['series_index'] = 5  # int
        result = diff_metadata(before, after)
        self.assertTrue(result['changed'])
        changes = result['changes']
        si_change = [c for c in changes if c['field'] == 'series_index']
        self.assertEqual(len(si_change), 1)
        self.assertEqual(si_change[0]['change_type'], 'changed')
        self.assertEqual(si_change[0]['before'], '5')
        self.assertEqual(si_change[0]['after'], 5)

    def test_summary_counts_correct(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'New'           # changed
        after['publisher'] = 'New Pub'   # changed
        del after['rating']              # removed
        after['tags'].append('new')      # changed
        result = diff_metadata(before, after)
        summary = result['summary']
        self.assertEqual(summary['changed'], 3)  # title, publisher, tags
        self.assertEqual(summary['removed'], 1)  # rating
        self.assertEqual(summary['added'], 0)


# ---------------------------------------------------------------------------
# Normalization integration
# ---------------------------------------------------------------------------

class TestNormalizationIntegration(unittest.TestCase):
    def test_compare_original_vs_normalized(self):
        """Original metadata with messy values vs the normalized version."""
        try:
            from metadata_normalizer import normalize_metadata
        except ImportError:
            self.skipTest("metadata_normalizer not available")

        original = _base_metadata()
        original['title'] = '  Test Book Title  '
        original['languages'] = ['ENG']
        original['isbn'] = '978-1234567890'

        normalized = normalize_metadata(original)['metadata']
        result = diff_metadata(original, normalized)

        self.assertTrue(result['changed'])
        # The diff should show the changes introduced by normalization.
        fields = [c['field'] for c in result['changes']]
        self.assertIn('title', fields)
        self.assertIn('languages', fields)

    def test_normalized_comparison_shows_no_diff(self):
        """If we normalize both sides identically, the diff should be empty."""
        try:
            from metadata_normalizer import normalize_metadata
        except ImportError:
            self.skipTest("metadata_normalizer not available")

        original = _base_metadata()
        normalized = normalize_metadata(original)['metadata']
        result = diff_metadata(normalized, normalized)
        self.assertFalse(result['changed'])


# ---------------------------------------------------------------------------
# Real project metadata test
# ---------------------------------------------------------------------------

class TestRealMetadata(unittest.TestCase):
    def test_realistic_metadata_structure(self):
        """Use a metadata structure matching what epub_editor.py actually reads.

        This is based on the test EPUB in test_epub_editor.py.
        """
        real_before = {
            'title': 'Test Book Title',
            'authors': ['Test Author One', 'Test Author Two'],
            'languages': ['en'],
            'publisher': 'Test Publisher',
            'description': 'Test description.',
            'tags': [],
            'series': '',
            'series_index': '',
            'rating': '',
            'identifiers': {
                '_primary_id': 'id',
                'id': 'urn:uuid:test-id-12345',
                'isbn': '978-1234567890',
            },
            'isbn': '978-1234567890',
            'pubdate': '2023-01-15',
            'rights': 'Test rights',
        }
        real_after = real_before.copy()
        real_after = {
            'title': 'Test Book Title (2nd Edition)',
            'authors': ['Test Author One', 'Test Author Two', 'New Contributor'],
            'languages': ['en'],
            'publisher': 'Test Publisher',
            'description': 'An updated test description.',
            'tags': ['fiction'],
            'series': 'Test Series',
            'series_index': '1',
            'rating': '4.5',
            'identifiers': {
                '_primary_id': 'id',
                'id': 'urn:uuid:test-id-12345',
                'isbn': '978-1234567890',
            },
            'isbn': '978-1234567890',
            'pubdate': '2024-01-15',
            'rights': 'Updated rights',
        }
        result = diff_metadata(real_before, real_after)
        self.assertTrue(result['changed'])

        fields = [c['field'] for c in result['changes']]
        # Check that all changed fields are detected.
        self.assertIn('title', fields)
        self.assertIn('authors', fields)
        self.assertIn('tags', fields)
        self.assertIn('series', fields)
        self.assertIn('series_index', fields)
        self.assertIn('rating', fields)
        self.assertIn('description', fields)
        self.assertIn('pubdate', fields)
        self.assertIn('rights', fields)

        # Verify summary.
        summary = result['summary']
        # 9 fields changed: title, authors, tags(+added), series(+added),
        # series_index(+added), rating(+added), description, pubdate, rights
        self.assertEqual(summary['added'] + summary['changed'], len(fields))
        self.assertEqual(summary['removed'], 0)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions(unittest.TestCase):
    def test_get_changes(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'New'
        result = diff_metadata(before, after)
        changes = get_changes(result)
        self.assertEqual(len(changes), 1)

    def test_has_changed_true(self):
        before = _base_metadata()
        after = _base_metadata()
        after['title'] = 'New'
        result = diff_metadata(before, after)
        self.assertTrue(has_changed(result))

    def test_has_changed_false(self):
        before = _base_metadata()
        after = _base_metadata()
        result = diff_metadata(before, after)
        self.assertFalse(has_changed(result))


if __name__ == '__main__':
    unittest.main()
