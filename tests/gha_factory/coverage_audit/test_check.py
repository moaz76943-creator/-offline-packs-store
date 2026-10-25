"""Regression tests for public-only sharded readiness verification."""
import importlib.util
import hashlib
import sqlite3
from contextlib import closing
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import unittest

CHECK_PATH = Path(__file__).resolve().parents[3] / 'tools/gha_factory/coverage_audit/check.py'
spec = importlib.util.spec_from_file_location('coverage_audit', CHECK_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        ids = [chr(97 + i // 26) + chr(97 + i % 26) for i in range(100)]
        # Synthetic fixtures: only for unit tests, NEVER production packs.
        manifest = {'total_languages': 100, 'packs': [], 'languages': [
            {'code': v, 'registered': True, 'is_active': False,
             'content_available': False, 'pack_verified': False,
             'production_ready': False, 'direction': 'ltr'} for v in ids]}
        registry = {'scripts': {'Latn': {'direction': 'ltr'}},
                    'languages': [{'id': v, 'scripts': ['Latn'], 'default_script': 'Latn'} for v in ids]}
        readiness = {'states': {v: 'unverified' for v in ids}}
        version = {'release_status': 'BLOCKED_DEPENDENCY', 'packs': {}}
        ledger = {'schema_version': '1.0.0', 'sources': []}
        self.values = {'manifest.json': manifest,
                       'catalog/language_registry.v1.json': registry,
                       'catalog/content_readiness.v1.json': readiness,
                       'version.json': version,
                       'legal/ledger/sources.json': ledger}
        self.write_all()

    def write_all(self):
        for name, value in self.values.items():
            p = self.root / name
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_text(json.dumps(value), encoding='utf-8')

    def test_all_100_languages_are_partitioned_once(self):
        checks = [checker.audit(self.root, shard=i, shards=10) for i in range(10)]
        self.assertEqual(sum(x['language_count'] for x in checks), 100)
        self.assertEqual(sum(x['verified_v2_packs'] for x in checks), 0)

    def test_manifest_direction_must_match_canonical_script(self):
        # A valid-looking direction flag cannot contradict the registered
        # writing system: otherwise RTL languages can be reported as LTR.
        self.values['manifest.json']['languages'][0]['direction'] = 'rtl'
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'script.*direction|direction.*script'):
            checker.audit(self.root, shard=0, shards=1)

    def test_registry_script_direction_must_match_manifest(self):
        # Registry metadata is not sufficient if it contradicts the
        # published language's own direction.
        self.values['catalog/language_registry.v1.json']['scripts']['Latn']['direction'] = 'rtl'
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'script.*direction|direction.*script'):
            checker.audit(self.root, shard=0, shards=1)

    def test_false_legacy_activation_fails_closed(self):
        self.values['manifest.json']['languages'][0]['is_active'] = True
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'false production activation'):
            checker.audit(self.root, shard=0, shards=1)

    def test_unapproved_packs_are_rejected(self):
        self.values['manifest.json']['packs'] = [{'id': 'aa'}]
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'empty source'):
            checker.audit(self.root, shard=0, shards=1)

    def test_missing_registered_language_fails(self):
        self.values['catalog/content_readiness.v1.json']['states'].pop('dv')
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'identities'):
            checker.audit(self.root, shard=0, shards=1)

    def test_duplicate_registry_ids_fail(self):
        self.values['catalog/language_registry.v1.json']['languages'][-1]['id'] = 'aa'
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'duplicate'):
            checker.audit(self.root, shard=0, shards=1)

    def test_duplicate_json_keys_fail(self):
        (self.root / 'version.json').write_text('{"packs":{},"packs":{}}', encoding='utf-8')
        with self.assertRaisesRegex(checker.AuditError, 'duplicate JSON key'):
            checker.audit(self.root, shard=0, shards=1)

    def test_unpaired_unicode_surrogates_in_repository_metadata_fail_closed(self):
        # JSON permits escaped UTF-16 surrogate code points even though they
        # are not Unicode scalar values. Never admit such metadata evidence.
        for raw in (
            r'{"release_status":"BLOCKED_DEPENDENCY","packs":{},"note":"\ud800"}',
            r'{"release_status":"BLOCKED_DEPENDENCY","packs":{},"\udc00":"value"}',
        ):
            with self.subTest(raw=raw):
                (self.root / 'version.json').write_text(raw, encoding='utf-8')
                with self.assertRaisesRegex(checker.AuditError, 'Unicode'):
                    checker.read_json(self.root, 'version.json')
                with self.assertRaisesRegex(checker.AuditError, 'Unicode'):
                    checker.audit(self.root, shard=0, shards=1)

    def test_valid_multilingual_unicode_metadata_remains_accepted(self):
        self.values['version.json']['note'] = 'عَرَبِي Äpfel Straße İ ı 日本語'
        self.write_all()
        self.assertEqual(checker.read_json(self.root, 'version.json')['note'],
                         self.values['version.json']['note'])
        self.assertEqual(checker.audit(self.root, shard=0, shards=1)['production_ready_languages'], 0)

    def test_pack_member_json_is_strict(self):
        # Synthetic pack metadata: ambiguous JSON cannot be evidence, even
        # when the surrounding envelope's byte digest is internally correct.
        bad_members = (
            b'{"sourceIds":["approved"],"sourceIds":["forged"]}',
            b'{"score":NaN}',
            b'{"score":1e999}',
            b'{"note":"\\ud800"}',
            b'["not", "an", "object"]',
            b'{"word":"' + bytes([255]) + b'"}',
        )
        for raw in bad_members:
            with self.subTest(raw=raw):
                with self.assertRaises(checker.AuditError):
                    checker._parse_strict_json(raw, 'synthetic pack metadata')
        valid = '{"word":"عربي Äpfel Straße İ ı 日本語"}'.encode('utf-8')
        self.assertEqual(checker._parse_strict_json(valid, 'synthetic pack metadata'),
                         {'word': 'عربي Äpfel Straße İ ı 日本語'})

    def test_oversized_json_integers_fail_as_audit_errors(self):
        # JSON numeric tokens must be bounded before Python's int parser
        # raises an implementation-specific ValueError on very long input.
        # The same rule applies to repository and synthetic pack metadata.
        for digits in (129, 5000):
            for sign in ('', '-'):
                with self.subTest(digits=digits, sign=sign):
                    raw = ('{"value":' + sign + '9' * digits + '}').encode('ascii')
                    with self.assertRaisesRegex(checker.AuditError, 'integer'):
                        checker._parse_strict_json(raw, 'synthetic metadata')
                    (self.root / 'version.json').write_bytes(raw)
                    with self.assertRaisesRegex(checker.AuditError, 'integer'):
                        checker.read_json(self.root, 'version.json')

    def test_excessive_json_nesting_fails_as_audit_error(self):
        # The decoder can raise RecursionError on deeply nested untrusted
        # metadata. The audit CLI must return classified FAIL, not a traceback.
        raw = ('{"nested":' + '[' * 15000 + '0' + ']' * 15000 + '}').encode('ascii')
        with self.assertRaisesRegex(checker.AuditError, 'nesting|depth'):
            checker._parse_strict_json(raw, 'synthetic metadata')
        (self.root / 'version.json').write_bytes(raw)
        with self.assertRaisesRegex(checker.AuditError, 'nesting|depth'):
            checker.read_json(self.root, 'version.json')

    def test_bounded_json_integer_is_preserved(self):
        value = 10 ** 127 - 1
        raw = ('{"value":' + str(value) + '}').encode('ascii')
        self.assertEqual(checker._parse_strict_json(raw, 'synthetic metadata')['value'], value)

    def test_nonfinite_exponent_in_repository_metadata_is_rejected(self):
        # These are syntactically invalid JSON numeric values, even though
        # Python's default JSON decoder converts their exponents to infinity.
        for number in ('1e999', '-1e999'):
            with self.subTest(number=number):
                (self.root / 'version.json').write_text(
                    '{"release_status":"BLOCKED_DEPENDENCY","packs":{},'
                    '"synthetic_quality_score":' + number + '}',
                    encoding='utf-8')
                with self.assertRaisesRegex(checker.AuditError, 'nonfinite JSON'):
                    checker.read_json(self.root, 'version.json')
                with self.assertRaisesRegex(checker.AuditError, 'nonfinite JSON'):
                    checker.audit(self.root, shard=0, shards=1)

    def test_finite_exponent_in_repository_metadata_remains_valid(self):
        (self.root / 'version.json').write_text(
            '{"release_status":"BLOCKED_DEPENDENCY","packs":{},'
            '"synthetic_quality_score":1.25e2}', encoding='utf-8')
        self.assertEqual(checker.read_json(self.root, 'version.json')['synthetic_quality_score'], 125.0)
        self.assertEqual(checker.audit(self.root, shard=0, shards=1)['production_ready_languages'], 0)

    def test_malformed_shard_rejected(self):
        with self.assertRaisesRegex(checker.AuditError, 'invalid shard'):
            checker.audit(self.root, shard=10, shards=10)

    def test_approved_ledger_alone_does_not_claim_content(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'reviewed-sample', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.write_all()
        self.assertFalse(checker.audit(self.root, shard=0, shards=1)['production_release_claimed'])


    def test_reports_each_language_with_no_unverified_promotion(self):
        report = checker.audit(self.root, shard=0, shards=1)
        self.assertEqual(len(report['language_rows']), 100)
        self.assertEqual(report['language_rows'][0]['status'], 'REGISTERED')
        self.assertEqual(report['language_rows'][0]['source_status'], 'NOT_ATTESTED')
        self.assertEqual(report['directed_pairs'], [])
        self.assertEqual(report['factory_ready_languages'], [])

    def test_forged_source_approval_not_counted(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'forged', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.write_all()
        report = checker.audit(self.root, shard=0, shards=1)
        self.assertEqual(report['source_approved_ids'], 0)
        self.assertEqual(report['source_approval_missing_evidence'], 1)

    def test_unverified_release_claim_rejected_even_if_flags_set(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'forged', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.values['manifest.json']['packs'] = [{'id': 'aa', 'sha256': '0'*64}]
        lang = self.values['manifest.json']['languages'][0]
        lang.update(content_available=True, pack_verified=True, production_ready=True)
        self.write_all()
        with patch.object(checker, '_verify_pack', return_value={'source_ids': ['forged'], 'directed_pairs': []}):
            with self.assertRaisesRegex(checker.AuditError, '(unapproved provenance|false production)'):
                checker.audit(self.root, shard=0, shards=1)

    def test_directions_are_not_implicitly_symmetric(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'directed.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript("""
                    CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                    CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                    CREATE TABLE translations(from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                    INSERT INTO lexicon VALUES('l1','aa'),('l2','ab');
                    INSERT INTO senses VALUES('s1','l1'),('s2','l2');
                    INSERT INTO translations VALUES('s1','s2','ab');
                """)
            pairs = checker._directed_pairs(database.read_bytes(), {'aa','ab'})
        self.assertEqual(pairs, [{'source_language': 'aa', 'target_language': 'ab',
                                  'verified_count': 1}])

    def test_fixture_package_metadata_is_not_publishable(self):
        metadata = {'sourceIds': ['sample'], 'fixtureOnly': True}
        with self.assertRaisesRegex(checker.AuditError, 'fixture'):
            checker._pack_source_ids(metadata, {'sourceIds': ['sample'], 'fixtureOnly': True})

    def test_duplicate_pack_source_ids_are_rejected(self):
        metadata = {'sourceIds': ['one', 'one'], 'fixtureOnly': False}
        with self.assertRaisesRegex(checker.AuditError, 'source IDs'):
            checker._pack_source_ids(metadata, {'sourceIds': ['one', 'one'], 'fixtureOnly': False})

    def test_positive_approval_never_implies_language_ready(self):
        payload = b'public source bytes'
        rights = b'public license evidence'
        (self.root / 'evidence').mkdir()
        (self.root / 'evidence/source.dat').write_bytes(payload)
        (self.root / 'evidence/license.txt').write_bytes(rights)
        self.values['legal/ledger/sources.json']['sources'] = [{
            'source_id': 'sample', 'status': 'APPROVED_FOR_REDISTRIBUTION',
            'publisher': 'Test publisher', 'dataset_version': '1.0',
            'origin_url': 'https://example.org/content', 'alterations': ['No changes'],
            'retrieval': {'identity': 'snapshot-1', 'url': 'https://example.org/snapshot',
                          'artifact_path': 'evidence/source.dat', 'sha256': hashlib.sha256(payload).hexdigest()},
            'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/rights',
                        'evidence_path': 'evidence/license.txt', 'evidence_sha256': hashlib.sha256(rights).hexdigest()},
            'review': {'reviewer': 'Human', 'decision_url': 'https://example.org/decision'},
        }]
        self.write_all()
        report = checker.audit(self.root, shard=0, shards=1)
        self.assertEqual(report['source_approved_ids'], 1)
        self.assertEqual(report['production_ready_languages'], 0)
        self.assertEqual(report['factory_ready_languages'], [])

    def test_symlinked_approval_proof_is_not_accepted(self):
        (self.root / 'evidence').mkdir()
        (self.root / 'evidence' / 'source.dat').symlink_to(self.root / 'manifest.json')
        source = {'source_id': 'spoof', 'status': 'APPROVED_FOR_REDISTRIBUTION',
                  'publisher': 'Test', 'dataset_version': '1', 'origin_url': 'https://example.org/data',
                  'alterations': ['No changes'],
                  'retrieval': {'identity': 'x', 'url': 'https://example.org/x',
                                'artifact_path': 'evidence/source.dat', 'sha256': '0' * 64},
                  'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/rights',
                              'evidence_path': 'evidence/source.dat', 'evidence_sha256': '0' * 64},
                  'review': {'reviewer': 'Human', 'decision_url': 'https://example.org/decision'}}
        self.values['legal/ledger/sources.json']['sources'] = [source]
        self.write_all()
        self.assertEqual(checker.audit(self.root, shard=0, shards=1)['source_approved_ids'], 0)

    def test_duplicate_approval_identifier_is_rejected(self):
        self.values['legal/ledger/sources.json']['sources'] = [
            {'source_id': 'same', 'status': 'REVIEW_REQUIRED'},
            {'source_id': 'same', 'status': 'APPROVED_FOR_REDISTRIBUTION'}]
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'duplicate provenance'):
            checker.audit(self.root, shard=0, shards=1)

    def test_metadata_symlinked_parent_is_rejected(self):
        # Synthetic fixture: metadata reached through a symlinked directory
        # must not be trusted even when the final JSON file is ordinary.
        (self.root / 'alias').symlink_to(self.root / 'catalog', target_is_directory=True)
        with self.assertRaisesRegex(checker.AuditError, 'symlink'):
            checker.read_json(self.root, 'alias/content_readiness.v1.json')

    def test_published_pack_symlinked_parent_is_rejected(self):
        # A symlinked packs/ parent currently bypasses the final-file check.
        real = self.root / 'real_packs'
        real.mkdir()
        blob = b'untrusted archive bytes'
        (real / 'aa-1.0.0.pack.gz').write_bytes(blob)
        (self.root / 'packs').symlink_to(real, target_is_directory=True)
        entry = {'id': 'aa', 'languageCode': 'aa',
                 'schemaVersion': '2.0.0', 'format': 'json-gzip-v1',
                 'version': '1.0.0', 'sha256': hashlib.sha256(blob).hexdigest(),
                 'archiveSizeBytes': len(blob)}
        with self.assertRaisesRegex(checker.AuditError, 'symlink'):
            checker._verify_pack(self.root, entry, 'aa')

    def test_verifier_symlinked_parent_is_rejected(self):
        # Never import a verifier through a symlinked tools/ directory.
        module = self.root / 'real_tools/pack_v2/pipeline.py'
        module.parent.mkdir(parents=True)
        module.write_text('def check_envelope(blob, language): return {}\n', encoding='utf-8')
        (self.root / 'tools').symlink_to(self.root / 'real_tools', target_is_directory=True)
        with self.assertRaisesRegex(checker.AuditError, 'symlink'):
            checker._load_pack_checker(self.root)

    def test_verifier_import_uses_repo_root_not_process_pythonpath(self):
        module = self.root / 'tools/pack_v2/pipeline.py'
        module.parent.mkdir(parents=True)
        module.write_text('def check_envelope(blob, language): return {"test": language}\n', encoding='utf-8')
        self.assertEqual(checker._load_pack_checker(self.root)(b'bytes', 'aa'), {'test': 'aa'})

    def test_translation_target_mismatch_not_counted_as_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'directed.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript("""
                    CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                    CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                    CREATE TABLE translations(from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                    INSERT INTO lexicon VALUES('l1','aa'),('l2','ab');
                    INSERT INTO senses VALUES('s1','l1'),('s2','l2');
                    INSERT INTO translations VALUES('s1','s2','aa');
                """)
            with self.assertRaisesRegex(checker.AuditError, 'translation target language mismatch'):
                checker._directed_pairs(database.read_bytes(), {'aa','ab'})


    def test_null_or_unknown_translation_languages_never_pass_coverage(self):
        # Legacy SQLite may omit NOT NULL constraints. SQL comparisons with
        # NULL evaluate to UNKNOWN, not TRUE, so bad evidence must be rejected
        # explicitly rather than counted or silently omitted.
        for broken in ('null_translation', 'null_source', 'null_target', 'unknown_same_language'):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as temp:
                database = Path(temp) / 'directed.sqlite'
                with closing(sqlite3.connect(database)) as db:
                    db.executescript("""
                        CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                        CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                        CREATE TABLE translations(from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                        INSERT INTO lexicon VALUES('l1','aa'),('l2','ab');
                        INSERT INTO senses VALUES('s1','l1'),('s2','l2');
                        INSERT INTO translations VALUES('s1','s2','ab');
                    """)
                    if broken == 'null_translation':
                        db.execute("UPDATE translations SET language_code=NULL")
                    elif broken == 'null_source':
                        db.execute("UPDATE lexicon SET language_code=NULL WHERE id='l1'")
                    elif broken == 'null_target':
                        db.execute("UPDATE lexicon SET language_code=NULL WHERE id='l2'")
                    else:
                        db.execute("UPDATE lexicon SET language_code='zz'")
                        db.execute("UPDATE translations SET language_code='zz'")
                    db.commit()
                with self.assertRaisesRegex(checker.AuditError, 'translation.*language|unregistered language'):
                    checker._directed_pairs(database.read_bytes(), {'aa', 'ab'})


    def test_orphan_translation_endpoints_never_disappear_from_coverage(self):
        # Valid A->B evidence must not mask an unresolvable second edge.
        # No FOREIGN KEY constraints are declared in this synthetic SQLite
        # fixture, so the coverage reader must reject missing joins itself.
        for broken in ('source_sense', 'target_sense', 'source_lexeme', 'target_lexeme'):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as temp:
                database = Path(temp) / 'directed.sqlite'
                with closing(sqlite3.connect(database)) as db:
                    db.executescript("""
                        CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                        CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                        CREATE TABLE translations(from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                        INSERT INTO lexicon VALUES('l1','aa'),('l2','ab');
                        INSERT INTO senses VALUES('s1','l1'),('s2','l2');
                        INSERT INTO translations VALUES('s1','s2','ab');
                    """)
                    if broken == 'source_sense':
                        db.execute("INSERT INTO translations VALUES('missing','s2','ab')")
                    elif broken == 'target_sense':
                        db.execute("INSERT INTO translations VALUES('s1','missing','ab')")
                    elif broken == 'source_lexeme':
                        db.execute("INSERT INTO senses VALUES('s3','missing')")
                        db.execute("INSERT INTO translations VALUES('s3','s2','ab')")
                    else:
                        db.execute("INSERT INTO senses VALUES('s4','missing')")
                        db.execute("INSERT INTO translations VALUES('s1','s4','ab')")
                    db.commit()  # closing() does not commit pending DML.
                with self.assertRaisesRegex(checker.AuditError, 'orphan translation'):
                    checker._directed_pairs(database.read_bytes(), {'aa', 'ab'})


    def test_corrupt_sqlite_coverage_is_a_classified_audit_failure(self):
        # Synthetic invalid bytes must fail closed as AuditError, not leak
        # an uncaught sqlite3.DatabaseError from a scheduled audit.
        with self.assertRaisesRegex(checker.AuditError, 'SQLite'):
            checker._directed_pairs(b'not a SQLite database', {'aa', 'ab'})

    def test_unreferenced_orphan_sense_fails_sqlite_foreign_key_audit(self):
        # A broken sense can be invisible to the translation JOIN. A canonical
        # SQLite v2 pack declares FK constraints; verify all of them even if
        # the translation table is empty. This is synthetic fixture data.
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / 'directed.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript("""
                    PRAGMA foreign_keys=OFF;
                    CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                    CREATE TABLE senses(
                        sense_id TEXT PRIMARY KEY,
                        lexeme_id TEXT REFERENCES lexicon(id));
                    CREATE TABLE translations(
                        from_sense_id TEXT REFERENCES senses(sense_id),
                        to_sense_id TEXT REFERENCES senses(sense_id),
                        language_code TEXT);
                    INSERT INTO lexicon VALUES('l1','aa');
                    INSERT INTO senses VALUES('s1','l1'),('orphan','missing');
                """)
                db.commit()
            with self.assertRaisesRegex(checker.AuditError, 'foreign key'):
                checker._directed_pairs(database.read_bytes(), {'aa', 'ab'})


    def test_unreferenced_orphan_sense_without_declared_foreign_keys_is_rejected(self):
        # Synthetic legacy SQLite fixture: foreign_key_check cannot detect
        # orphan senses when a table omits FK declarations. A valid A->B
        # translation must not hide an unrelated dangling sense/lexeme ID.
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / 'directed.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript("""
                    CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                    CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                    CREATE TABLE translations(from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                    INSERT INTO lexicon VALUES('l1','aa'),('l2','ab');
                    INSERT INTO senses VALUES('s1','l1'),('s2','l2'),('orphan','missing');
                    INSERT INTO translations VALUES('s1','s2','ab');
                """)
                db.commit()
            with self.assertRaisesRegex(checker.AuditError, 'orphan sense'):
                checker._directed_pairs(database.read_bytes(), {'aa', 'ab'})


    def test_duplicate_translation_rows_do_not_inflate_directed_sense_coverage(self):
        # Synthetic fixture: distinct row IDs/evidence may refer to the same
        # directed sense edge. Coverage must count unique A->B sense pairs,
        # not duplicate rows; B->A remains a separate directed edge.
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / 'directed.sqlite'
            with closing(sqlite3.connect(database)) as db:
                db.executescript("""
                    CREATE TABLE lexicon(id TEXT PRIMARY KEY, language_code TEXT);
                    CREATE TABLE senses(sense_id TEXT PRIMARY KEY, lexeme_id TEXT);
                    CREATE TABLE translations(translation_id TEXT PRIMARY KEY,
                        from_sense_id TEXT, to_sense_id TEXT, language_code TEXT);
                    INSERT INTO lexicon VALUES('l1','aa'),('l2','ab'),('l3','aa');
                    INSERT INTO senses VALUES('s1','l1'),('s2','l2'),('s3','l3');
                    INSERT INTO translations VALUES
                        ('t1','s1','s2','ab'),
                        ('t2','s1','s2','ab'),
                        ('t3','s3','s2','ab'),
                        ('t4','s2','s1','aa');
                """)
                db.commit()
            pairs = checker._directed_pairs(database.read_bytes(), {'aa', 'ab'})
        self.assertEqual(pairs, [
            {'source_language': 'aa', 'target_language': 'ab', 'verified_count': 2},
            {'source_language': 'ab', 'target_language': 'aa', 'verified_count': 1},
        ])


    def test_unbacked_pack_verified_flag_is_rejected(self):
        # Synthetic manifest claims a verified v2 pack but publishes no pack
        # entry. The audit must not silently report REGISTERED and PASS.
        self.values['manifest.json']['languages'][0]['pack_verified'] = True
        self.write_all()
        with self.assertRaisesRegex(checker.AuditError, 'unbacked pack_verified'):
            checker.audit(self.root, shard=0, shards=1)


if __name__ == '__main__':
    unittest.main()
