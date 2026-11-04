import unittest
import tempfile
import json
import sqlite3
import hashlib
from pathlib import Path
from unittest.mock import patch
import os
import sys

# Since tools/pack_v2/test_pipeline.py is not easily imported directly, we recreate the simple fixture locally.
def create_fixture_doc(language):
    origin='https://example.org/fixtures-only'
    source={'source_id':'fixture.demo','origin_url':origin,'publisher':'Self-authored synthetic test',
            'dataset_version':'1','retrieval_id':'synthetic:1','license_id':'LicenseRef-SyntheticTestFixture',
            'record_locator':'illustration','publication_approved':False,'fixture_only':True,
            'artifact_sha256':None}
    lex='lex.'+language+'.one'
    sense='sense.'+language+'.one'
    return {'contract_version':'1.0.0','document_id':'fixture.'+language+'.only',
       'lexemes':[{'lexeme_id':lex,'language':language,'script':'Latn','lemma':'word',
                   'surface':'word','pos':'noun','direction':'ltr','source':source}],
       'senses':[{'sense_id':sense,'lexeme_id':lex,'concept_id':'concept.'+language+'.house',
                  'definition':'word','source':source}],
       'examples':[{'example_id':'example.'+language+'.one','sense_id':sense,
                    'language':language,'script':'Latn','text':'word.','source':source}],
       'relations':[],'translations':[]}

from tools.repro_build.compiler import ReproBuilder

class TestReproBuilder(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.root = Path(self.d.name)

        self.repo_root = Path('.').resolve()
        self.builder = ReproBuilder(repo_root=self.repo_root)

        # Write fixture inside tempdir instead of working directory!
        self.source_path = self.root / "fixture_en.json"
        self.doc = create_fixture_doc('en')
        with open(self.source_path, 'w') as f:
            json.dump(self.doc, f)

        # Since source_path needs to be resolved as self.repo_root / source_path,
        # we can't just pass absolute path unless repo_root is updated.
        # But our builder resolves it relative to repo_root! So we should use a custom repo_root for builder or pass relative.
        # Actually, if we pass an absolute path in the manifest, `self.repo_root / path` resolves to `path`!
        # Because Path('/app') / Path('/tmp/foo.json') == Path('/tmp/foo.json').
        self.manifest_path = self.root / "manifest.json"
        self.manifest = {
            "source_path": str(self.source_path),
            "language": "en",
            "schema_version": "1.0.0"
        }
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f)

        self.output_dir = self.root / "output"
        self.output_dir.mkdir()

    def test_registry_resolves_from_repo_root_when_cwd_differs(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        old_cwd = Path.cwd()
        try:
            os.chdir(elsewhere)
            result = self.builder.build(self.manifest_path, self.output_dir,
                                        fixture_only=True)
            self.assertTrue(result.exists())
        finally:
            os.chdir(old_cwd)

    def test_source_mutated_after_hash_cannot_change_compiled_document(self):
        # The old implementation hashes once and opens the mutable path again.
        # Mutate between those operations; only pinned bytes may be compiled.
        original_hash = self.builder.sha256_file
        def mutate_after_hash(path):
            value = original_hash(path)
            if Path(path) == self.source_path:
                self.source_path.write_text('{}', encoding='utf-8')
            return value
        self.manifest['source_sha256'] = original_hash(self.source_path)
        self.manifest_path.write_text(json.dumps(self.manifest))
        with patch.object(self.builder, 'sha256_file', side_effect=mutate_after_hash):
            result = self.builder.build(self.manifest_path, self.output_dir,
                                        fixture_only=True)
        self.assertTrue(result.exists())

    def test_staging_directory_is_on_output_filesystem(self):
        real_temp = tempfile.TemporaryDirectory
        observed = []
        def track(*args, **kwargs):
            observed.append(kwargs.get('dir'))
            return real_temp(*args, **kwargs)
        with patch('tools.repro_build.compiler.tempfile.TemporaryDirectory',
                   side_effect=track):
            output = self.builder.build(self.manifest_path, self.output_dir,
                                        fixture_only=True)
        self.assertTrue(output.exists())
        self.assertEqual(observed, [self.output_dir])

    def test_build_success(self):
        out_path = self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)
        self.assertTrue(out_path.exists())
        self.assertTrue(out_path.name.startswith("en-"))
        self.assertTrue(out_path.name.endswith(".sqlite"))

        with sqlite3.connect(out_path) as db:
            counts = db.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]
            self.assertEqual(counts, 1)

    def test_invalid_hash(self):
        self.manifest["source_sha256"] = "invalidhash"
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f)

        with self.assertRaisesRegex(ValueError, "Source hash mismatch"):
            self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

    def test_schema_version_mismatch(self):
        self.manifest["schema_version"] = "9.9.9"
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f)

        with self.assertRaisesRegex(ValueError, "Schema version mismatch"):
            self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

    def test_invalid_license_fails_build(self):
        self.doc["lexemes"][0]["source"]["publication_approved"] = True
        self.doc["lexemes"][0]["source"]["fixture_only"] = False
        with open(self.source_path, 'w') as f:
            json.dump(self.doc, f)

        with self.assertRaises(ValueError):
            self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

    def test_deterministic_repeated_builds(self):
        path1 = self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

        path2 = self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

        self.assertEqual(path1, path2)
        with open(path1, 'rb') as f1, open(path2, 'rb') as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_failed_build_preserves_old_output(self):
        path1 = self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)
        self.assertTrue(path1.exists())

        self.manifest["language"] = "fr"
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f)

        with self.assertRaises(ValueError):
            self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

        self.assertTrue(path1.exists())

    def test_malformed_record(self):
        with open(self.source_path, 'w') as f:
            json.dump({}, f)
        with self.assertRaises(ValueError):
            self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)

    def test_empty_sources(self):
        self.doc["lexemes"][0]["source"] = {}
        with open(self.source_path, 'w') as f:
            json.dump(self.doc, f)
        with self.assertRaises(ValueError):
            self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)


    def test_grammar_is_preserved(self):
        sidecar = self.source_path.with_name("en.grammar.json")
        origin = 'https://example.org/fixtures-only'
        source = {
            'source_id':'fixture.demo',
            'origin_url':origin,
            'publisher':'Self-authored synthetic test',
            'dataset_version':'1',
            'retrieval_id':'synthetic:1',
            'license_id':'LicenseRef-SyntheticTestFixture',
            'record_locator':'illustration',
            'publication_approved':False,
            'fixture_only':True,
            'artifact_sha256':None
        }
        grammar_doc = {
            "languageCode": "en",
            "contract_version": "1.0.0",
            "rules": [
                {
                    "grammar_id": "g1",
                    "category": "noun",
                    "title": "plural",
                    "source": source
                }
            ]
        }
        with open(sidecar, 'w') as f:
            json.dump(grammar_doc, f)

        out_path = self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)
        with sqlite3.connect(out_path) as db:
            count = db.execute("SELECT COUNT(*) FROM grammar").fetchone()[0]
            self.assertEqual(count, 1)


    def test_directed_pair_metadata_is_preserved(self):
        self.doc['translations'].append({
            "translation_id": "tr1",
            "from_sense_id": "sense.en.one",
            "to_sense_id": "sense.en.one",
            "language": "en",
            "text": "word",
            "equivalence": "exact",
            "source": self.doc['lexemes'][0]['source']
        })
        with open(self.source_path, 'w') as f:
            json.dump(self.doc, f)

        out_path = self.builder.build(self.manifest_path, self.output_dir, fixture_only=True)
        with sqlite3.connect(out_path) as db:
            count = db.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
            self.assertEqual(count, 1)

if __name__ == '__main__':


    unittest.main()
