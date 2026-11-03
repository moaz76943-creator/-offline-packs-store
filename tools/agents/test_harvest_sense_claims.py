"""Source-attested Wikidata concept-link rank regressions (offline fixtures)."""

import unittest

from tools.agents.harvest import _sense_qids, rows_from_lexeme


class WikidataSenseRankTests(unittest.TestCase):
    @staticmethod
    def claim(qid, rank='normal'):
        return {
            'rank': rank,
            'mainsnak': {
                'snaktype': 'value',
                'datavalue': {'type': 'wikibase-entityid', 'value': {'id': qid}},
            },
        }

    @staticmethod
    def lexeme(claims):
        return {
            'type': 'lexeme',
            'id': 'L123',
            'language': 'Q188',
            'lastrevid': 12345,
            'lexicalCategory': 'Q1084',
            'lemmas': {'de': {'language': 'de', 'value': 'Haus'}},
            'senses': [{'id': 'L123-S1', 'claims': {'P5137': claims}}],
            'forms': [],
        }

    @staticmethod
    def extract(claims):
        return rows_from_lexeme(
            WikidataSenseRankTests.lexeme(claims),
            {'wikidata': 'Q515', 'section': 'city',
             'subsection': 'places', 'concept_id': 'city.places'},
            {'Q188': 'de'}, {'de': {'script': 'Latn'}}, '2026-10-24',
        )

    def test_preferred_rank_wins_over_normal_and_deprecated(self):
        claims = [
            self.claim('Q111', 'deprecated'), self.claim('Q222'),
            self.claim('Q333', 'preferred'), self.claim('Q333', 'preferred'),
        ]
        self.assertEqual(_sense_qids({'claims': {'P5137': claims}}), ['Q333'])

    def test_deprecated_concept_cannot_become_a_candidate(self):
        rows, reason = self.extract([self.claim('Q515', 'deprecated')])
        self.assertEqual((rows, reason), ([], 'unplaced'))

    def test_deprecated_blocked_concept_does_not_poison_active_link(self):
        rows, reason = self.extract([
            self.claim('Q154', 'deprecated'), self.claim('Q515'),
        ])
        self.assertEqual(reason, 'keep')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['qids'], ['Q515'])
        self.assertEqual(rows[0]['sense_id'], 'L123-S1')
        self.assertEqual(rows[0]['language'], 'de')

    def test_preferred_novalue_does_not_fall_back_to_normal(self):
        claims = [
            self.claim('Q515'),
            {'rank': 'preferred', 'mainsnak': {'snaktype': 'novalue'}},
        ]
        self.assertEqual(_sense_qids({'claims': {'P5137': claims}}), [])
        self.assertEqual(self.extract(claims)[1], 'unplaced')

    def test_malformed_claims_do_not_create_unverified_concept_links(self):
        invalid = [
            None, 3, {}, self.claim('Q0'), self.claim('Q01'),
            self.claim('not-a-qid'),
            {'rank': 'normal', 'mainsnak': {'snaktype': 'somevalue'}},
            {'rank': 'normal', 'mainsnak': {'datavalue': {'value': 'Q515'}}},
        ]
        self.assertEqual(_sense_qids({'claims': {'P5137': invalid}}), [])
        self.assertEqual(_sense_qids({'claims': {'P5137': {}}}), [])
        self.assertEqual(_sense_qids(None), [])
        self.assertEqual(self.extract(invalid)[1], 'unplaced')

    def test_normal_rank_retained_when_no_preferred_exists(self):
        rows, reason = self.extract([self.claim('Q515')])
        self.assertEqual(reason, 'keep')
        self.assertEqual(len(rows), 1)


if __name__ == '__main__':
    unittest.main()
