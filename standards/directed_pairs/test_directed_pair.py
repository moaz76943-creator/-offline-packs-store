import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from validate import DirectedPairContractError, validate, verify_compatible
from sqlite_v2 import build, check_mapping_version

HERE = Path(__file__).parent


def fixture(name='positive'):
    return json.loads((HERE / 'fixtures' / f'{name}.json').read_text(encoding='utf-8'))


class DirectedPairSchemaTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def test_positive_fixture(self):
        self.assertIs(validate(self.data), self.data)

        # Test polysemous senses
        senses_de_bank = [s for s in self.data['senses'] if s['lexeme_id'] == 'lex.de.bank']
        self.assertEqual(len(senses_de_bank), 2)

        # Test bidirectional
        pairs = self.data['directed_translations']
        self.assertTrue(any(p['source_sense_id'] == 'sense.de.bank.finance' and p['target_sense_id'] == 'sense.en.bank.finance' for p in pairs))
        self.assertTrue(any(p['source_sense_id'] == 'sense.en.bank.finance' and p['target_sense_id'] == 'sense.de.bank.finance' for p in pairs))

    def test_negative_fixture_rejected(self):
        with self.assertRaises(DirectedPairContractError) as context:
            validate(fixture('negative'))
        self.assertIn("orphan target sense", str(context.exception))

    def test_same_source_target_language_rejected(self):
        draft = copy.deepcopy(self.data)
        draft['directed_translations'][0]['target_language'] = draft['directed_translations'][0]['source_language']
        with self.assertRaises(DirectedPairContractError) as context:
            validate(draft)
        self.assertIn("source and target languages must be different", str(context.exception))

    def test_exact_equivalence_rejects_cross_concept_senses(self):
        draft = copy.deepcopy(self.data)
        draft['directed_translations'][0]['target_sense_id'] = 'sense.en.bank.river'
        with self.assertRaisesRegex(DirectedPairContractError,
                                    'exact equivalence requires matching concepts'):
            validate(draft)

    def test_contextual_equivalence_does_not_assume_same_concept(self):
        draft = copy.deepcopy(self.data)
        draft['directed_translations'][0]['target_sense_id'] = 'sense.en.bank.river'
        draft['directed_translations'][0]['equivalence'] = 'contextual'
        self.assertIs(validate(draft), draft)

    def test_pair_language_matches_referenced_lexeme_owners(self):
        draft = copy.deepcopy(self.data)
        draft['directed_translations'][0]['source_language'] = 'fr'
        with self.assertRaisesRegex(DirectedPairContractError, 'source language disagrees with lexeme owner'):
            validate(draft)
        draft = copy.deepcopy(self.data)
        draft['directed_translations'][0]['target_language'] = 'fr'
        with self.assertRaisesRegex(DirectedPairContractError, 'target language disagrees with lexeme owner'):
            validate(draft)

    def test_missing_lexeme_owner_is_rejected(self):
        draft = copy.deepcopy(self.data)
        draft['lexemes'] = [lex for lex in draft['lexemes'] if lex['lexeme_id'] != 'lex.de.bank']
        with self.assertRaisesRegex(DirectedPairContractError, 'orphan canonical lexeme'):
            validate(draft)

    def test_independent_canonical_language_mapping_must_agree(self):
        owners = {lex['lexeme_id']: lex['language'] for lex in self.data['lexemes']}
        self.assertIs(validate(self.data, canonical_lexeme_languages=owners), self.data)
        owners['lex.de.bank'] = 'fr'
        with self.assertRaisesRegex(DirectedPairContractError, 'canonical lexeme language mismatch'):
            validate(self.data, canonical_lexeme_languages=owners)
        with self.assertRaisesRegex(DirectedPairContractError, 'publication requires independent'):
            validate(self.data, publication=True)

    def test_lexeme_owner_identity_is_stable(self):
        draft = copy.deepcopy(self.data)
        draft['lexemes'][0]['language'] = 'fr'
        with self.assertRaises(DirectedPairContractError):
            verify_compatible(self.data, draft)

    def test_duplicate_pair_direction_rejected(self):
        draft = copy.deepcopy(self.data)
        dup = copy.deepcopy(draft['directed_translations'][0])
        dup['pair_id'] = 'pair.de.en.bank.finance.dup'
        draft['directed_translations'].append(dup)
        with self.assertRaises(DirectedPairContractError) as context:
            validate(draft)
        self.assertIn("duplicate translation pair direction", str(context.exception))

    def test_fixture_cannot_pass_publication_gate(self):
        with self.assertRaises(DirectedPairContractError):
            validate(self.data, publication=True)

    def test_stable_identity_compatibility(self):
        changed = copy.deepcopy(self.data)
        changed['directed_translations'][0]['text'] = 'updated bank'
        self.assertTrue(verify_compatible(self.data, changed))

        changed['directed_translations'][0]['source_language'] = 'fr'
        with self.assertRaises(DirectedPairContractError):
            verify_compatible(self.data, changed)


class SqliteMappingTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'directed_pair.sqlite'

    def test_sqlite_v2_roundtrip_and_compatibility(self):
        build(self.data, self.db)
        with sqlite3.connect(self.db) as con:
            self.assertTrue(check_mapping_version(con))
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])

            self.assertEqual(con.execute('SELECT COUNT(*) FROM senses').fetchone()[0], len(self.data['senses']))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM directed_pairs').fetchone()[0], len(self.data['directed_translations']))

            for row in self.data['directed_translations']:
                decoded = json.loads(con.execute('SELECT payload_json FROM directed_pairs WHERE pair_id=?',(row['pair_id'],)).fetchone()[0])
                self.assertEqual(decoded, row)

    def test_deterministic_reordering_no_overwrite(self):
        build(self.data, self.db)
        initial = hashlib.sha256(self.db.read_bytes()).hexdigest()
        shuffled = copy.deepcopy(self.data)
        shuffled['senses'].reverse()
        shuffled['directed_translations'].reverse()
        alternate = self.root / 'other.sqlite'
        build(shuffled, alternate)
        self.assertEqual(initial, hashlib.sha256(alternate.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            build(self.data, self.db)

# The required public gate pins test_directed_pair.py; include the separate
# factory-interop regressions without modifying the shared CI policy owner.
from test_factory_adapter import FactoryAdapterTest

if __name__ == '__main__':
    unittest.main()
