# -*- coding: utf-8 -*-
"""Tests for metadata_normalizer module.

Run with:
    cd /home/ubuntu/workspace/fanficfare-android/app/src/main/python
    /tmp/ff_venv/bin/python3 -m unittest tests.test_metadata_normalizer -v
"""
import sys
import os
import json
import unittest

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
# Insert tests/ parent (python/) into path so we can import the module
sys.path.insert(0, os.path.join(SRC_DIR, '..'))

import metadata_normalizer as normalizer


class WhitespaceNormalizationTest(unittest.TestCase):
    """Tests 1-4: string whitespace normalization."""

    def test_title_leading_trailing_whitespace(self):
        metadata = {'title': '  Harry Potter  '}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['title'], 'Harry Potter')

    def test_title_repeated_spaces_collapsed(self):
        metadata = {'title': 'Harry   Potter'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['title'], 'Harry Potter')

    def test_whitespace_only_value_becomes_empty(self):
        metadata = {'title': '   '}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['title'], '')

    def test_description_whitespace_trimmed(self):
        metadata = {'description': '  A wizard story.  '}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['description'], 'A wizard story.')

    def test_input_not_mutated(self):
        """Test 31: input metadata object is unchanged after normalization."""
        original = {'title': '  Harry Potter  ', 'publisher': '  Test Publisher  '}
        original_copy = json.loads(json.dumps(original))
        normalizer.normalize_metadata(original)
        self.assertEqual(original, original_copy)


class HTMLNormalizationTest(unittest.TestCase):
    """Tests 5-8: HTML description normalization."""

    def test_simple_p_description(self):
        metadata = {'description': '<p>Harry Potter</p><p>A young wizard...</p>'}
        result = normalizer.normalize_metadata(metadata)
        desc = result['metadata']['description']
        self.assertIn('Harry Potter', desc)
        self.assertIn('A young wizard', desc)
        self.assertNotIn('<p>', desc)

    def test_multiple_paragraphs_preserved(self):
        metadata = {'description': '<p>Chapter 1</p><p>Chapter 2</p>'}
        result = normalizer.normalize_metadata(metadata)
        desc = result['metadata']['description']
        self.assertIn('Chapter 1', desc)
        self.assertIn('Chapter 2', desc)
        self.assertNotIn('<p>', desc)

    def test_html_entities_decoded(self):
        # HTML entities decode to visible characters; tags are stripped.
        # &amp; decodes to & (not a tag, so it survives).
        metadata = {'description': 'Tom &amp; Jerry &amp; Friends'}
        result = normalizer.normalize_metadata(metadata)
        desc = result['metadata']['description']
        self.assertIn('&', desc)
        self.assertNotIn('<', desc)  # No tag-like characters should remain
        self.assertEqual(desc, 'Tom & Jerry & Friends')

    def test_plain_text_description_unchanged(self):
        metadata = {'description': 'A simple plain text description.'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['description'],
                         'A simple plain text description.')


class SubjectNormalizationTest(unittest.TestCase):
    """Tests 9-14: subject/tag normalization."""

    def test_trim_tags(self):
        metadata = {'tags': [' Fantasy ', ' Magic ']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['tags'], ['Fantasy', 'Magic'])

    def test_remove_empty_tags(self):
        metadata = {'tags': ['Fantasy', '', '  ', 'Magic']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['tags'], ['Fantasy', 'Magic'])

    def test_case_insensitive_dedup_not_done_for_subjects(self):
        """Normalization does NOT deduplicate subjects — that is a separate
        future step. This phase only trims and removes empties."""
        metadata = {'tags': ['Fantasy', 'fantasy', 'Magic']}
        result = normalizer.normalize_metadata(metadata)
        # All three preserved (no dedup in this phase)
        self.assertEqual(len(result['metadata']['tags']), 3)

    def test_preserve_first_capitalization(self):
        # Subjects are NOT deduplicated in this phase, but if they were,
        # first capitalization would be preserved. This test documents that
        # the normalization preserves casing.
        metadata = {'tags': ['  fantasy  ', 'Magic']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['tags'], ['fantasy', 'Magic'])

    def test_preserve_ordering(self):
        metadata = {'tags': ['Zebra', 'Apple', 'Mango']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['tags'], ['Zebra', 'Apple', 'Mango'])

    def test_similar_different_tags_remain(self):
        metadata = {'tags': ['Sci-Fi', 'Science Fiction']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['tags'], ['Sci-Fi', 'Science Fiction'])


class AuthorNormalizationTest(unittest.TestCase):
    """Tests 15-17: author normalization."""

    def test_trim_names(self):
        metadata = {'authors': ['  J.K. Rowling  ', '  George R.R. Martin  ']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['authors'],
                         ['J.K. Rowling', 'George R.R. Martin'])

    def test_preserve_author_ordering(self):
        metadata = {'authors': ['Rowling', 'Martin', 'Tolkien']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['authors'], ['Rowling', 'Martin', 'Tolkien'])

    def test_no_fuzzy_merge(self):
        metadata = {'authors': ['J.K. Rowling', 'Rowling, J.K.']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['authors'],
                         ['J.K. Rowling', 'Rowling, J.K.'])


class LanguageNormalizationTest(unittest.TestCase):
    """Tests 18-21: BCP 47 language normalization."""

    def test_en_uppercase_becomes_lowercase(self):
        metadata = {'languages': ['EN']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['languages'], ['en'])

    def test_en_us_normalization(self):
        metadata = {'languages': ['EN-us']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['languages'], ['en-US'])

    def test_en_us_with_underscore(self):
        metadata = {'languages': ['en_US']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['languages'], ['en-US'])

    def test_already_normalized_stable(self):
        metadata = {'languages': ['en-US']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['languages'], ['en-US'])

    def test_malformed_preserved(self):
        metadata = {'languages': ['not-a-real-language']}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['languages'], ['not-a-real-language'])


class DateNormalizationTest(unittest.TestCase):
    """Tests 22-26: date normalization."""

    def test_year_only_preserved(self):
        metadata = {'pubdate': '2020'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['pubdate'], '2020')

    def test_year_month_preserved(self):
        metadata = {'pubdate': '2020-05'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['pubdate'], '2020-05')

    def test_full_date_preserved(self):
        metadata = {'pubdate': '2020-05-15'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['pubdate'], '2020-05-15')

    def test_iso_timestamp_normalized(self):
        metadata = {'pubdate': '2020-05-15T12:30:00Z'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['pubdate'], '2020-05-15')

    def test_month_name_date_normalized(self):
        metadata = {'pubdate': 'January 15, 2024'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['pubdate'], '2024-01-15')

    def test_ambiguous_preserved(self):
        metadata = {'pubdate': 'not a date'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['pubdate'], 'not a date')


class ISBNNormalizationTest(unittest.TestCase):
    """Tests 27-30: ISBN normalization."""

    def test_isbn13_hyphens_and_spaces_removed(self):
        # 978-0-13-110362-7 is a valid ISBN-13 (check digit 7)
        metadata = {'isbn': '978-0-13-110362-7'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['isbn'], '9780131103627')

    def test_valid_isbn13_normalized(self):
        metadata = {'isbn': '978-0-13-110362-7'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['isbn'], '9780131103627')

    def test_valid_isbn10_normalized(self):
        # 0-306-40615-2 is a known valid ISBN-10
        metadata = {'isbn': '0-306-40615-2'}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['isbn'], '0306406152')

    def test_invalid_isbn_preserved(self):
        # 978-9999999999999 stripped = 9789999999999 (15 digits, not a valid ISBN-13
        # which requires exactly 13 digits — so checksum validation fails but
        # it should still be cleaned of hyphens/spaces, not silently deleted).
        # The plan says: preserve the original semantic value rather than
        # silently deleting it. So we strip hyphens but keep the value.
        metadata = {'isbn': '978-9999999999999'}
        result = normalizer.normalize_metadata(metadata)
        # Hyphens removed, invalid value preserved (not deleted to empty string)
        self.assertEqual(result['metadata']['isbn'], '9789999999999999')

    def test_whitespace_not_silently_deleted(self):
        metadata = {'isbn': '   '}
        result = normalizer.normalize_metadata(metadata)
        self.assertEqual(result['metadata']['isbn'], '')


class ChangeReportingTest(unittest.TestCase):
    """Tests 32-34: change reporting."""

    def test_changes_reported_correctly(self):
        metadata = {'title': '  Harry Potter  '}
        result = normalizer.normalize_metadata(metadata)
        changes = result['changes']
        title_changes = [c for c in changes if c['field'] == 'title']
        self.assertEqual(len(title_changes), 1)
        self.assertEqual(title_changes[0]['before'], '  Harry Potter  ')
        self.assertEqual(title_changes[0]['after'], 'Harry Potter')
        self.assertEqual(title_changes[0]['reason'], 'normalize_whitespace')

    def test_unchanged_produces_no_changes(self):
        metadata = {'title': 'Harry Potter'}
        result = normalizer.normalize_metadata(metadata)
        title_changes = [c for c in result['changes'] if c['field'] == 'title']
        self.assertEqual(len(title_changes), 0)

    def test_change_ordering_deterministic(self):
        metadata = {'title': '  A  ', 'publisher': '  B  ', 'rights': '  C  '}
        result1 = normalizer.normalize_metadata(metadata)
        result2 = normalizer.normalize_metadata(metadata)
        self.assertEqual(
            [c['field'] for c in result1['changes']],
            [c['field'] for c in result2['changes']]
        )


class RealProjectMetadataTest(unittest.TestCase):
    """Integration-style test with real EPUB metadata structure.

    Uses a metadata dict resembling the output of read_metadata_fields().
    """

    def test_real_metadata_normalization(self):
        # This dict mirrors the structure returned by epub_editor.read_metadata_fields()
        original = {
            'title': '  The Great Gatsby  ',
            'authors': ['  F. Scott Fitzgerald  '],
            'languages': ['ENG'],
            'publisher': '  Scribner  ',
            'description': '<p>A classic novel.</p><p>  About the jazz age.</p>',
            'tags': ['Fiction', '  fiction  ', 'Classic', ''],
            'series': '',
            'series_index': '',
            'rating': '4.0',
            'identifiers': {'bookid': 'urn:uuid:test-id-12345'},
            'isbn': '978-0-7432-7356-5',
            'pubdate': 'April 10, 2004',
            'rights': '  Copyright 2024  ',
        }
        result = normalizer.normalize_metadata(original)
        md = result['metadata']

        self.assertEqual(md['title'], 'The Great Gatsby')
        self.assertEqual(md['authors'], ['F. Scott Fitzgerald'])
        self.assertEqual(md['languages'], ['en'])  # ENG → en
        self.assertEqual(md['publisher'], 'Scribner')
        self.assertNotIn('<p>', md['description'])
        self.assertIn('A classic novel', md['description'])
        self.assertIn('About the jazz age', md['description'])
        # ISBN normalized
        self.assertEqual(md['isbn'], '9780743273565')
        # Date normalized
        self.assertEqual(md['pubdate'], '2004-04-10')
        self.assertEqual(md['rights'], 'Copyright 2024')

        # Input must not be mutated
        self.assertEqual(original['title'], '  The Great Gatsby  ')


class InputImmutabilityTest(unittest.TestCase):
    """Deep immutability: nested structures must not be mutated."""

    def test_nested_list_not_mutated(self):
        original = {'tags': ['  Fantasy  ', '  Magic  ']}
        original_copy = json.loads(json.dumps(original))
        normalizer.normalize_metadata(original)
        self.assertEqual(original, original_copy)

    def test_nested_dict_not_mutated(self):
        original = {'identifiers': {'bookid': 'urn:uuid:12345'}}
        original_copy = json.loads(json.dumps(original))
        normalizer.normalize_metadata(original)
        self.assertEqual(original, original_copy)


if __name__ == '__main__':
    unittest.main()
