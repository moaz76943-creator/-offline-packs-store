"""Regression checks on databases built by the existing reference producer."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from standards.lexical.sqlite_v2 import build
from tools.contribution_gate.test_fixture import fixture
from tools.pack_conformance.fixture_builder import get_base_document
from tools.pack_conformance.validator import PackConformanceValidator, PackConformanceError, main


class ConformanceRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'pack #1?.sqlite'
        build(get_base_document(), self.db)

    def change(self, sql, args=()):
        with sqlite3.connect(self.db) as db:
            db.execute(sql, args)

    def manifest(self, **changes):
        meta = {'path':self.db.name, 'entry_count':1,
                'sha256':hashlib.sha256(self.db.read_bytes()).hexdigest()}
        meta.update(changes)
        path = self.root / 'manifest.json'
        path.write_text(json.dumps({'packs':{'test':meta}}))
        return path

    def test_default_cli_does_not_pass_without_source_evidence(self):
        self.assertEqual(main([str(self.db)]), 2)
        self.assertEqual(main([str(self.db), '--structural-only']), 0)

    def test_inspection_preserves_original_bytes_and_special_path_characters(self):
        before = self.db.read_bytes()
        self.assertFalse(PackConformanceValidator(self.db).validate())
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [self.db.name])

    def test_manifest_missing_or_omitting_pack_fails_closed(self):
        path = self.root / 'missing.json'
        with self.assertRaisesRegex(PackConformanceError, 'missing'):
            PackConformanceValidator(self.db, path).validate()
        path.write_text('{"packs":{}}')
        with self.assertRaisesRegex(PackConformanceError, 'exactly one'):
            PackConformanceValidator(self.db, path).validate()

    def test_manifest_same_basename_in_another_directory_is_not_identity(self):
        path = self.manifest(path='another/' + self.db.name)
        with self.assertRaisesRegex(PackConformanceError, 'exactly one'):
            PackConformanceValidator(self.db, path).validate()

    def test_manifest_requires_exact_sha_and_integer_count(self):
        for changes in ({'sha256':None}, {'entry_count':True}, {'entry_count':0}):
            with self.subTest(changes=changes), self.assertRaises(PackConformanceError):
                PackConformanceValidator(self.db, self.manifest(**changes)).validate()

    def test_unknown_mapping_and_migration_are_rejected(self):
        self.change("UPDATE metadata SET value='9.0' WHERE key='mapping_version'")
        with self.assertRaisesRegex(PackConformanceError, 'mapping'):
            PackConformanceValidator(self.db).validate()
        self.change("UPDATE metadata SET value='2.0.0' WHERE key='mapping_version'")
        self.change("UPDATE schema_migrations SET description='invented migration'")
        with self.assertRaisesRegex(PackConformanceError, 'migration'):
            PackConformanceValidator(self.db).validate()

    def test_missing_index_and_foreign_key_violation_are_rejected(self):
        self.change('DROP INDEX idx_lexicon_order')
        with self.assertRaisesRegex(PackConformanceError, 'schema mismatch'):
            PackConformanceValidator(self.db).validate()
        self.change("UPDATE senses SET lexeme_id='missing'")
        with self.assertRaisesRegex(PackConformanceError, 'foreign-key'):
            PackConformanceValidator(self.db).validate()

    def test_json_missing_pos_and_wrong_sort_key_are_rejected(self):
        with sqlite3.connect(self.db) as db:
            payload = json.loads(db.execute('SELECT fields_json FROM lexicon').fetchone()[0])
        del payload['pos']
        self.change('UPDATE lexicon SET fields_json=?', (json.dumps(payload),))
        with self.assertRaisesRegex(PackConformanceError, 'Invalid lexeme'):
            PackConformanceValidator(self.db).validate()
        payload['pos'] = 'noun'
        self.change('UPDATE lexicon SET fields_json=?,sort_key=?', (json.dumps(payload), 'wrong'))
        with self.assertRaisesRegex(PackConformanceError, 'sort_key'):
            PackConformanceValidator(self.db).validate()

    def test_fts_payload_corruption_is_rejected(self):
        self.change("UPDATE lexicon_fts SET lemma='forged'")
        with self.assertRaisesRegex(PackConformanceError, 'FTS5'):
            PackConformanceValidator(self.db).validate()

    def test_forged_row_flags_do_not_replace_canonical_ledger(self):
        doc = get_base_document()
        for collection in ('lexemes','senses'):
            doc[collection][0]['source'].update(publication_approved=True, fixture_only=False,
                                               artifact_sha256='1'*64)
        path = self.root / 'forged.sqlite'
        build(doc, path)
        self.assertFalse(PackConformanceValidator(path).validate())

    def test_source_verification_uses_independent_hashed_ledger_and_resets(self):
        # All rights and payload below are synthetic, isolated test evidence.
        _, src = fixture(self.root)
        source = {'source_id':src['source_id'], 'retrieval_id':src['retrieval']['identity'],
                  'origin_url':src['origin_url'], 'publisher':src['publisher'],
                  'dataset_version':src['dataset_version'], 'license_id':src['license']['id'],
                  'record_locator':'fixture-1', 'artifact_sha256':src['retrieval']['sha256'],
                  'publication_approved':True, 'fixture_only':False}
        doc = get_base_document()
        for collection in ('lexemes','senses'):
            doc[collection][0]['source'] = copy.deepcopy(source)
        path = self.root / 'verified-fixture.sqlite'
        build(doc, path)
        validator = PackConformanceValidator(path, repo_root=self.root)
        self.assertTrue(validator.validate())
        self.assertFalse(validator.publication_approved)
        (self.root / src['retrieval']['artifact_path']).write_bytes(b'tampered')
        self.assertFalse(validator.validate())

    def test_fixture_morphology_does_not_inherit_verified_parent(self):
        _, src = fixture(self.root)
        source = {'source_id':src['source_id'], 'retrieval_id':src['retrieval']['identity'],
                  'origin_url':src['origin_url'], 'publisher':src['publisher'],
                  'dataset_version':src['dataset_version'], 'license_id':src['license']['id'],
                  'record_locator':'fixture-1', 'artifact_sha256':src['retrieval']['sha256'],
                  'publication_approved':True, 'fixture_only':False}
        from tools.pack_conformance.validator import ROOT
        data = json.loads((ROOT / 'standards/lexical/fixtures/positive.json').read_text())
        german = next(x for x in data['lexemes'] if x['lexeme_id']=='lex.de.gehen')
        doc = get_base_document()
        doc['lexemes'] = [german]
        doc['senses'] = [x for x in data['senses'] if x['lexeme_id']==german['lexeme_id']]
        for row in doc['lexemes'] + doc['senses']:
            row['source'] = copy.deepcopy(source)
        parent_only = self.root / 'parent.sqlite'
        build(doc, parent_only)
        self.assertTrue(PackConformanceValidator(parent_only, repo_root=self.root).validate())
        german['morphology']['conjugations'][0]['source'] = get_base_document()['lexemes'][0]['source']
        nested_fixture = self.root / 'morphology.sqlite'
        build(doc, nested_fixture)
        self.assertFalse(PackConformanceValidator(nested_fixture, repo_root=self.root).validate())

    def test_corrupt_database_is_rejected_without_mutation(self):
        path = self.root / 'corrupt.sqlite'
        path.write_bytes(b'not sqlite')
        with self.assertRaises(PackConformanceError):
            PackConformanceValidator(path).validate()
        self.assertEqual(path.read_bytes(), b'not sqlite')
