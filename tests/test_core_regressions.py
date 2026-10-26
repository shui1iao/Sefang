"""Synthetic catalogue responses only; no captured pages, media or live requests."""
import json
import tempfile
import unittest
from pathlib import Path

from se_catalog import codes
from se_catalog.catalog import fallbacks
from se_catalog.catalog.found import Found, is_same_work
from se_catalog.catalog.web import Missing
from se_catalog.testing import ResponseWeb


class CoreRegressions(unittest.TestCase):
    def test_gana_known_shop_prefix_is_same_work(self):
        self.assertTrue(codes.same_work('GANA-123', '200GANA-123'))
        self.assertTrue(codes.same_work('200GANA-123', 'GANA-123'))
        self.assertEqual(codes.identity('GANA-00123'), codes.identity('200GANA-123'))
        self.assertIn('200GANA-123', codes.search_spellings('GANA-123'))

    def test_unknown_prefix_or_different_number_still_conflicts(self):
        for other in ('201GANA-123', '999GANA-123', 'GANA-124', '200GANA-124'):
            with self.subTest(other=other):
                self.assertFalse(codes.same_work('GANA-123', other))
        self.assertTrue(codes.same_work('LUXU-123', '259LUXU-123'))
        self.assertFalse(codes.same_work('LUXU-123', '999LUXU-123'))

    def test_printed_number_has_priority_over_requested_url(self):
        self.assertFalse(is_same_work('GANA-123', Found('synthetic',
            'https://example.test/GANA-123', number='GANA-124', content_id='GANA-123')))
        self.assertTrue(is_same_work('GANA-123', Found('synthetic',
            'https://example.test/GANA-124', number='200GANA-123')))
        self.assertFalse(is_same_work('GANA-123', Found('synthetic',
            'https://example.test/GANA-123', content_id='999GANA-123')))

    def test_description_ends_japanese_and_english_tag_fields(self):
        self.assertEqual(fallbacks.tag_tokens(
            'ジャンル: SyntheticTag OtherTag Description: synthetic summary'),
            ['SyntheticTag', 'OtherTag'])
        self.assertEqual(fallbacks.tag_tokens(
            'Starring: Synthetic Actor Studio: Synthetic Studio Tags: Genre A, Genre B Description: summary'),
            ['Genre A', 'Genre B'])
        self.assertEqual(fallbacks.tag_tokens(
            'ジャンル: SyntheticTag 出演者: Synthetic Actor'), ['SyntheticTag'])

    def test_recorded_synthetic_fallback_accepts_gana_and_excludes_summary(self):
        html = ('<html><head><meta name="description" content="'
                '品番: 200GANA-123 ジャンル: SyntheticTag Description: not-a-tag'
                '"></head><body><h1>GANA-123 Synthetic work</h1></body></html>')
        responses = {'GET https://3xplanet.com/' + spelling.lower() + '/': {'body': html}
                     for spelling in fallbacks.slug_spellings('GANA-123')}
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'responses.json'
            fixture.write_text(json.dumps({'responses': responses}))
            with ResponseWeb(fixture) as web:
                result = fallbacks.three_x('GANA-123', web)
                self.assertEqual(result.number, '200GANA-123')
                self.assertEqual(result.tags, ['SyntheticTag'])
                self.assertEqual(result.field_values()['tags'], ['SyntheticTag'])
                self.assertTrue(web.calls)
        conflicting = html.replace('品番: 200GANA-123', '品番: 200GANA-124')
        with self.assertRaises(Missing):
            fallbacks.parse_three_x(conflicting, 'GANA-123', 'https://example.test/GANA-123')


if __name__ == '__main__':
    unittest.main()
